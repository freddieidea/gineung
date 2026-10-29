# 시설 변화 관리의 언어 모델 부분 (AI 에이전트)
#  1) NameCheck: 새로 생긴 가게의 상호를 보고 업종이 맞는지 점검 — 규칙(name_signals)으로 못 정한 것만
#     1단계(Sonnet)가 상호로 업종을 고르고(업종 목록 안에서만), 2단계(Sonnet, 10/21 비용 때문에 Opus에서 바꿈)가 따로 다시 봐서 '확실하다'고 할 때만 바꿈 (pipeline/screen_names.py와 같은 2단계 방식)
#  2) OfficialAgent: 담당 공무원이 쓴 문장('○○동 △△슈퍼가 10월 말에 문을 닫았대요')을 알아듣고, 시설을 찾아 변화로 올리기 전에 확인을 받음
# 안전 장치: 언어 모델은 분류표·업종 목록·후보 번호 중에서만 고름. 시설 이름·주소·번호는 코드가 데이터베이스에서 가져옴. 확인 없이는 아무것도 반영하지 않음
import os, sys, json, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(ROOT, "engine"), os.path.join(ROOT, "pipeline")):
    if _d not in sys.path: sys.path.insert(0, _d)
import facility_rules as FR
SONNET = "claude-sonnet-5-5"; OPUS = "claude-opus-5-5"

def client(root=ROOT):
    import anthropic
    return anthropic.Anthropic(api_key=open(os.path.join(root, "settings", "anthropic_key.txt"), encoding="utf-8").read().strip())

def call_tool(c, model, system, user, tool, max_tokens=4000):
    # 도구 하나로만 답하게 함 (도구로 답하지 않으면 한 번 더 요청)
    system = system + f"\n\n답은 반드시 {tool['name']} 도구 하나로만 합니다. 도구 밖에 글을 쓰지 않습니다."
    for _ in range(2):
        r = c.messages.create(model=model, max_tokens=max_tokens, system=system, tools=[tool], tool_choice={"type": "auto"},
                              messages=[{"role": "user", "content": user}])
        try:   # 비용 기록 (10/21: 빠져 있어 사용량이 적게 보이던 것)
            from chat import log_usage; log_usage(model, r.usage, "상호 점검" if tool.get("name") in ("judge_names", "confirm") else "시설 변화 관리")
        except Exception: pass
        for b in r.content:
            if getattr(b, "type", "") == "tool_use" and b.name == tool["name"]: return b.input
    raise RuntimeError("언어 모델이 형식에 맞게 답하지 않음")

LIFE = None
def life_names(root=ROOT):
    global LIFE
    if LIFE is None:
        M = json.load(open(os.path.join(root, "data", "processed", "industry_function_map.json"), encoding="utf-8"))
        LIFE = sorted(FR.NAME[i["code"]] for i in M["items"] if i["life_facility"] and i["code"] in FR.NAME)
    return LIFE

N1 = """당신은 대구시 생활시설 자료를 관리하는 공무원입니다. 아래는 새로 인허가가 난 가게들입니다. 인허가 업종·업태로 정한 '지금 업종'은
업태가 넓어서(예: 일반음식점 업태 '기타'·'한식') 실제와 다를 수 있습니다. 상호를 보고 각 가게의 업종을 판정하세요. 상호는 띄어쓰기를 그대로 읽으세요(띄어쓰기 뒤는 보통 지점명).
- 맞음: 지금 업종이 맞거나, 상호만으로는 더 정할 수 없음 (사람 이름·지명·뜻이 넓은 낱말이면 맞음)
- 다른 업종: 상호가 다른 업종을 분명히 가리킴 → '업종'에 업종 목록 중 하나를 고름 (예: '타이 레스토랑' → 분류 안된 외국식 음식점, '○○막창' → 곱창 전골/구이)
- 생활시설 아님: 주민이 찾아가 이용하는 가게가 아님이 상호로 분명함 (회사 구내식당·급식 업체·공장·물류·본사 사무실)
- 모름: 판단할 수 없음
확실할 때만 '다른 업종'·'생활시설 아님'을 고르세요. 틀리게 바꾸면 주민이 엉뚱한 곳으로 안내됩니다."""
N2 = """당신은 생활시설 자료를 최종 확인하는 공무원입니다. 아래 가게들은 1차 점검이 '상호로 보아 업종을 바꿔야 한다'고 한 곳입니다.
각 가게를 따로 다시 보고, 상호만으로 1차 점검의 판정이 '확실히' 맞으면 "맞음", 상호만으로 단정할 수 없거나 그 업종에서 흔한 겸업·가까운 일이면 "아님"으로 판정하세요.
애매하면 "아님"입니다. 띄어쓰기를 그대로 읽으세요."""

class NameCheck:
    def __init__(self, root=ROOT):
        self.root = root; self.c = client(root)
    def run(self, items, chunk=20):
        out = {}
        for k in range(0, len(items), chunk): out.update(self._run(items[k:k + chunk]))
        return out
    @staticmethod
    def _items(a):
        xs = a.get("items", [])
        if isinstance(xs, str):
            try: xs = json.loads(xs)
            except Exception: xs = []
        return {int(x["n"]): x for x in xs if isinstance(x, dict) and str(x.get("n", "")).isdigit()}
    def _run(self, items):
        """items: [{"fid","상호","인허가업종","업태","업종"}] → {fid: {"판정","업종","이유","확인"}} (2단계까지 '맞음'인 것만 '확인': True)"""
        if not items: return {}
        names = life_names(self.root)
        tool1 = {"name": "judge_names", "description": "가게마다 상호로 업종을 판정한다",
                 "input_schema": {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {"type": "object",
                     "required": ["n", "판정", "업종", "이유"], "properties": {"n": {"type": "integer"}, "판정": {"type": "string", "enum": ["맞음", "다른 업종", "생활시설 아님", "모름"]},
                     "업종": {"type": "string", "enum": names + [""]}, "이유": {"type": "string"}}}}}}}
        rows = [[i + 1, x["상호"], f'{x.get("인허가업종","")} / {x.get("업태","")}', x["업종"]] for i, x in enumerate(items)]
        a = call_tool(self.c, SONNET, N1, json.dumps({"가게": rows, "열 설명": "[번호, 상호, 인허가 업종 / 업태, 지금 업종]"}, ensure_ascii=False), tool1, 8000)
        got = self._items(a)
        out = {}; ask2 = []
        for i, x in enumerate(items):
            g = got.get(i + 1, {"판정": "모름", "업종": "", "이유": "1차 답 없음"})
            if g["판정"] == "다른 업종" and (g.get("업종") not in names or g["업종"] == x["업종"]): g = dict(g, 판정="맞음")
            out[x["fid"]] = {"판정": g["판정"], "업종": g.get("업종", ""), "이유": g.get("이유", ""), "확인": False}
            if g["판정"] in ("다른 업종", "생활시설 아님"): ask2.append((x, g))
        if ask2:
            tool2 = {"name": "confirm", "description": "1차 판정을 확인한다", "input_schema": {"type": "object", "required": ["items"], "properties": {"items": {"type": "array",
                     "items": {"type": "object", "required": ["n", "판정", "이유"], "properties": {"n": {"type": "integer"}, "판정": {"type": "string", "enum": ["맞음", "아님"]}, "이유": {"type": "string"}}}}}}}
            rows2 = [[j + 1, x["상호"], f'{x.get("인허가업종","")} / {x.get("업태","")}', x["업종"], g["판정"] + (f" → {g['업종']}" if g["판정"] == "다른 업종" else ""), g.get("이유", "")]
                     for j, (x, g) in enumerate(ask2)]
            b = call_tool(self.c, SONNET, N2, json.dumps({"가게": rows2, "열 설명": "[번호, 상호, 인허가 업종 / 업태, 지금 업종, 1차 판정, 1차 이유]"}, ensure_ascii=False), tool2, 8000)
            ok = self._items(b)
            for j, (x, g) in enumerate(ask2):
                v = ok.get(j + 1, {"판정": "아님", "이유": "2차 답 없음"})
                out[x["fid"]].update({"확인": v["판정"] == "맞음", "확인이유": v.get("이유", "")})
        return out

GU = ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군"]
O_SYS = """당신은 대구시 구·군청 생활시설 담당 공무원을 돕는 AI 에이전트입니다. 담당자가 쓴 글에서 시설 변화(문 닫음·쉼·새로 엶·다시 엶)를 찾아 정해진 형식으로 정리합니다.
- 상호·행정동·주소는 글에 있는 그대로 옮깁니다. 글에 없는 것은 빈 칸으로 둡니다 (짐작해서 채우지 않음).
- 구·군은 글에 있거나 행정동·주소로 분명할 때만 고릅니다.
- 날짜는 YYYY-MM-DD로 적습니다. 오늘은 {today}입니다. '어제', '지난주 금요일'처럼 날짜를 정할 수 있으면 계산해 적고, '10월 말'처럼 정확하지 않으면 빈 칸으로 두고 날짜메모에 그대로 적습니다.
- 새로 연 시설은 업종 목록에서 업종을 고릅니다. 글로 알 수 없으면 빈 칸.
- 한 글에 여러 시설이 있으면 모두 적습니다. 시설 변화가 아닌 글이면 changes를 비우고 ask에 무엇을 알려 주면 되는지 적습니다."""

class OfficialAgent:
    """담당자의 말 → (확인용) 변화 제안 → 담당자가 고르면 반영. 시설 번호는 코드가 찾은 후보 중에서만"""
    def __init__(self, manager):
        self.M = manager; self.c = client(manager.root)
        X = json.load(open(os.path.join(manager.root, "data", "processed", "extra_type_functions.json"), encoding="utf-8"))["items"]
        self.pub = {x["name"]: x["code"] for x in X if str(x["code"]).startswith("PUB:") and x.get("name")}
        self.upjong = life_names(manager.root) + sorted(self.pub)

    def plan(self, text):
        from changes import today
        tool = {"name": "record_changes", "description": "담당자 글에서 시설 변화를 정리한다", "input_schema": {"type": "object", "required": ["changes", "ask"], "properties": {
            "changes": {"type": "array", "items": {"type": "object", "required": ["종류", "상호"], "properties": {
                "종류": {"type": "string", "enum": ["폐업", "휴업", "신규", "다시 엶"]}, "상호": {"type": "string"},
                "구군": {"type": "string", "enum": GU + [""]}, "행정동": {"type": "string"}, "주소": {"type": "string"},
                "업종": {"type": "string", "enum": self.upjong + [""]}, "날짜": {"type": "string"}, "날짜메모": {"type": "string"}, "메모": {"type": "string"}}}},
            "ask": {"type": "string", "description": "되물을 것 (없으면 빈 칸)"}}}}
        a = call_tool(self.c, SONNET, O_SYS.replace("{today}", today()), text, tool)
        out = []
        for ch in a.get("changes", []) or []:
            if isinstance(ch, str):
                try: ch = json.loads(ch)
                except Exception: continue
            d = {k: (ch.get(k) or "").strip() if isinstance(ch.get(k), str) else ch.get(k) for k in ("종류", "상호", "구군", "행정동", "주소", "업종", "날짜", "날짜메모", "메모")}
            if d["날짜"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["날짜"]): d["날짜메모"] = (d["날짜메모"] + " " + d["날짜"]).strip(); d["날짜"] = ""
            if d["종류"] == "신규":
                d["할일"] = "새 시설 추가"; d["준비"] = bool(d["상호"] and d["주소"] and d["업종"])
                if not d["준비"]: d["되물을것"] = "새 시설을 넣으려면 " + "·".join(x for x, v in (("상호", d["상호"]), ("주소", d["주소"]), ("업종", d["업종"])) if not v) + "을(를) 알려 주세요."
            else:
                cands = self.M.find(d["상호"], d["구군"] or None, d["행정동"] or None, d["주소"] or None, n=5) if d["상호"] else []
                d["후보"] = cands; d["할일"] = {"폐업": "문 닫음 반영", "휴업": "쉼(휴업) 반영", "다시 엶": "다시 엶 반영"}[d["종류"]]
                sure = len(cands) == 1 and cands[0]["점수"] >= 90 or (len(cands) > 1 and cands[0]["점수"] >= 90 and cands[0]["점수"] - cands[1]["점수"] >= 10)
                d["확실"] = bool(sure); d["준비"] = bool(cands)
                if not cands: d["되물을것"] = "그 이름의 시설을 찾지 못했어요. 구·군이나 주소를 함께 알려 주세요."
                elif not sure: d["되물을것"] = "비슷한 시설이 여러 곳이에요. 어느 곳인지 골라 주세요."
            out.append(d)
        return {"제안": out, "되물을것": a.get("ask", "")}

    def execute(self, d, pick=0, who=""):
        """담당자가 확인한 제안 하나를 반영 (pick: 후보 번호, 0부터)"""
        if d["종류"] == "신규":
            up = d["업종"]; code = self.pub.get(up, up)
            return self.M.add(d["상호"], d["주소"], code, date=d.get("날짜", ""), note=d.get("메모", ""), who=who)
        fid = d["후보"][pick]["fid"]
        if d["종류"] in ("폐업", "휴업"):
            return self.M.close(fid, d.get("날짜", ""), kind=d["종류"], note=" ".join(x for x in (d.get("메모"), d.get("날짜메모")) if x), who=who)
        return self.M.reopen(fid, d.get("날짜", ""), who=who)
