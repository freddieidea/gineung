# 대화 엔진 (첫 버전): 주민의 말에서 이용 목적(세부 기능)과 세부 종류를 찾아내고, 애매하면 다시 묻고, 대안 찾기 엔진을 부른다
# 안전 장치
#  - 언어 모델은 분류표에 있는 번호·종류 이름 중에서만 고른다 (도구 입력의 enum으로 막고, 코드가 다시 검사)
#  - 시설 이름·주소·전화·거리·시간은 언어 모델이 쓰지 않는다. 대안 찾기 엔진 결과(데이터베이스 값)를 그대로 보여 준다
#  - 확신이 없으면 고르지 않고 다시 묻는다 (최대 3번). 그래도 모르면 대표 선택지를 보여 준다
#  - 문 닫은 시설이 하던 일과 주민의 목적이 다르면 주민의 목적으로 찾고, 지자체 기록에 남긴다 (개인 정보 없이)
import json, os, datetime
import anthropic
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = "claude-sonnet-5-5"
SPEEDS = ["보통", "천천히", "아주 천천히"]

NEED_HELP = {"포장": "포장 = 가게에 가서 음식을 사 들고 옴", "배달": "배달 = 집으로 가져다줌"}

class Dialogue:
    def __init__(self, engine, model=MODEL):
        self.E = engine; self.model = model
        self.log_path = os.path.join(ROOT, "data", "logs", "dialogue_events.jsonl")   # 시험할 때는 None으로 두어 기록하지 않음
        self.client = anthropic.Anthropic(api_key=open(os.path.join(ROOT, "settings", "anthropic_key.txt"), encoding="utf-8").read().strip())
        rows = []
        for c in engine.T["categories"]:
            for p in c["purposes"]:
                for l in p["leaves"]:
                    rows.append(f'{l["id"]} | {c["name"]} > {p["name"]} | {l["name"]} | {l["desc"]}' + (f' | 예: {l["examples"]}' if l.get("examples") else ""))
        self.leaf_text = "\n".join(rows)
        self.leaf_ids = list(engine.leaf)

    # ── 언어 모델 호출 (도구 하나를 반드시 쓰게 해서 정해진 형식으로만 답하게 함) ──
    def _call(self, system, user, tool):
        # 이 모델은 도구 사용을 강제할 수 없어서, 반드시 도구로 답하라고 지시하고 도구로 답하지 않으면 한 번 더 요청함
        system = system + f"\n\n답은 반드시 {tool['name']} 도구 하나로만 합니다. 도구 밖에 글을 쓰지 않습니다."
        for _ in range(2):
            r = self.client.messages.create(model=self.model, max_tokens=1500, system=system, tools=[tool],
                                            tool_choice={"type": "auto"}, messages=[{"role": "user", "content": user}])
            for b in r.content:
                if getattr(b, "type", "") == "tool_use" and b.name == tool["name"]: return b.input
        raise RuntimeError("언어 모델이 형식에 맞게 답하지 않음")

    def _history(self, st):
        return "\n".join(("주민: " if m["role"] == "user" else "안내: ") + m["text"] for m in st["history"])

    def _closed_text(self, st):
        if not st.get("closed_fid"): return "없음 (주민이 대화창에서 바로 물어봄)"
        r = self.E.F.loc[st["closed_fid"]]
        fs = self.E.functions_of(st["closed_fid"])
        return f'{r["상호"]} ({r["업종"]})\n이 가게가 하던 일: ' + "; ".join(f'{f["leaf"]} {f["name"]}({f["role"]}' + (f', 종류: {f["kind"]}' if f["kind"] else "") + ")" for f in fs)

    # 1단계: 이용 목적(세부 기능) 찾기
    def pick_leaf(self, st):
        tool = {"name": "pick_purpose", "description": "주민의 이용 목적을 분류표의 세부 기능 하나로 고른다",
                "input_schema": {"type": "object", "required": ["leaf_id", "confidence", "summary", "mobility", "clarify_question", "clarify_options", "matches_closed"],
                    "properties": {
                        "leaf_id": {"type": "string", "enum": self.leaf_ids + ["UNCLEAR"]},
                        "alternatives": {"type": "array", "items": {"type": "string", "enum": self.leaf_ids}, "maxItems": 3},
                        "confidence": {"type": "string", "enum": ["높음", "보통", "낮음"]},
                        "summary": {"type": "string", "description": "주민이 원하는 것을 한 문장으로 (자연스러운 우리말)"},
                        "mobility": {"type": "string", "enum": SPEEDS + ["모름"]},
                        "matches_closed": {"type": "string", "enum": ["예", "아니오", "해당 없음"]},
                        "clarify_question": {"type": "string", "description": "UNCLEAR이거나 확신이 낮을 때 주민에게 물을 짧은 질문. 아니면 빈 문자열"},
                        "clarify_options": {"type": "array", "items": {"type": "string"}, "maxItems": 4}}}}
        system = f"""당신은 대구시 생활시설 안내 상담원입니다. 주민이 다니던 시설이 문을 닫았거나 필요한 것이 있을 때, 주민이 '무엇을 하려고' 그곳에 갔는지(이용 목적)를 분류표의 세부 기능 하나로 정확히 고릅니다.

[분류표 세부 기능: 번호 | 분야 > 이용 목적 | 세부 기능 | 설명]
{self.leaf_text}

규칙
1. 시설의 종류가 아니라 주민의 목적으로 고릅니다. 예: 고깃집에 '동네 사람들과 모이려고' 갔다면 외식이 아니라 친목 장소입니다.
2. 반드시 위 목록의 번호만 고릅니다. 둘 이상이 똑같이 그럴듯하거나 정보가 부족하면 leaf_id를 UNCLEAR로 두고, 그 차이를 가려낼 짧은 질문과 2~4개의 선택지를 만듭니다. 짐작해서 고르지 않습니다.
3. 문 닫은 시설이 주어졌으면 먼저 그 시설이 하던 일 목록에서 고릅니다.
   - 주민이 다른 말을 하지 않거나 그 시설의 주 기능과 맞는 말(예: 헬스장에 '운동하러 다녔다')을 하면, 그 시설의 주 기능을 고릅니다. 비슷한 세부 기능이 여럿 있어도 묻지 않고 주 기능을 고릅니다.
   - 주민의 말이 그 시설의 부 기능과 맞으면(예: 고깃집에서 '동네 사람들과 모여 먹던 곳' → 그 시설의 단체 식사 장소) 그 부 기능을 고릅니다.
   - 주민의 목적이 그 시설이 하던 일 어디에도 없을 때만 목록 전체에서 고르고, matches_closed를 '아니오'로 둡니다.
4. 이동 능력은 주민이 말한 경우에만 고릅니다 (지팡이·보행기, 오래 못 걸음 → 아주 천천히 / 천천히 걸음 → 천천히). 말하지 않았으면 '모름'.
5. 질문과 선택지는 어르신도 알기 쉬운 자연스러운 우리말로, 짧게 씁니다. 번역투(예: '~에 대해', '~하는 것이 가능합니다')나 딱딱한 행정 용어 대신, 동네 복지관 직원이 어르신께 말하듯 씁니다."""
        user = f"[문 닫은 시설]\n{self._closed_text(st)}\n\n[대화]\n{self._history(st)}"
        out = self._call(system, user, tool)
        if out["leaf_id"] != "UNCLEAR" and out["leaf_id"] not in self.E.leaf: raise RuntimeError("분류표에 없는 번호")
        return out

    # 2단계: 세부 종류 찾기
    def pick_kind(self, st, lid):
        l = self.E.leaf[lid]; ks = l["kinds"]
        if not ks.get("sensitive"): return {"kind": None, "confidence": "높음", "clarify_question": "", "clarify_options": []}
        names = [k["name"] for g in ks["groups"] for k in g["kinds"]]
        desc = "\n".join(f'- 묶음 "{g["name"]}": ' + "; ".join(f'"{k["name"]}"' + (f' (업종: {", ".join(u["name"] for u in k["upjong"])})' if k["upjong"] else "")
                         + (" [여러 종류를 함께 하는 곳]" if k["mixed"] else "") + (" [신청·문의 창구]" if k.get("contact") else "") for k in g["kinds"]) for g in ks["groups"])
        needs = sorted(self.E.needs.get(lid, []))
        tool = {"name": "pick_kind", "description": "세부 기능 안에서 주민이 원하는 세부 종류를 고른다",
                "input_schema": {"type": "object", "required": ["kind", "confidence", "clarify_question", "clarify_options", "menu_words"] + (["need"] if needs else []),
                    "properties": {"kind": {"type": "string", "enum": names + ["UNCLEAR"]},
                                   "menu_words": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                                                  "description": "주민이 말했거나 문 닫은 가게 이름에 드러난 구체적인 메뉴·물건·서비스 이름 (예: 해물찜, 쭈꾸미, 아구찜, 파마, 이불). 없으면 빈 배열"},
                                   "confidence": {"type": "string", "enum": ["높음", "보통", "낮음"]},
                                   "clarify_question": {"type": "string"}, "clarify_options": {"type": "array", "items": {"type": "string"}, "maxItems": 4}}}}
        if needs:
            tool["input_schema"]["properties"]["need"] = {"type": "string", "enum": needs + ["모름"],
                "description": "주민이 말한 이용 방식. " + " / ".join(NEED_HELP.get(n, n) for n in needs) + ". 주민이 직접 말하지 않았으면 반드시 '모름'"}
        system = f"""당신은 대구시 생활시설 안내 상담원입니다. 주민의 목적은 '{l["name"]}'({l["desc"]})로 정해졌습니다. 이제 주민이 원하는 것을 아래 세부 종류 중 하나로 정확히 고릅니다.

[세부 종류]
{desc}

규칙
1. 세부 종류가 다르면 서로 대신할 수 없습니다 (예: 해물찜집을 찾는 사람에게 분식집이나 고깃집은 틀린 답, 헬스장을 찾는 사람에게 골프연습장은 틀린 답). 그래서 확실할 때만 고릅니다.
2. 문 닫은 시설의 세부 종류가 주어졌고 주민이 다른 것을 원한다고 말하지 않으면, 그 종류를 고릅니다.
3. 주민이 말한 메뉴·물건·서비스가 어느 종류인지 애매하면 kind를 UNCLEAR로 두고, 가려낼 짧은 질문과 2~4개의 선택지를 만듭니다. 선택지는 위 종류 이름을 쉬운 말로 바꿔 씁니다.
4. 질문은 어르신도 알기 쉬운 자연스러운 우리말로 짧게 씁니다. 번역투나 딱딱한 행정 용어 대신, 동네 복지관 직원이 어르신께 말하듯 씁니다.
5. 병원 진료과는 증상과 상황으로 고르되, 둘 이상이 맞을 수 있으면 UNCLEAR로 두고 묻습니다 (예: 무릎·허리가 아프다 → 정형외과·마취통증의학과·재활의학과 중 무엇을 다녔는지 묻기). 신경과(두통·어지럼·손떨림·저림)와 정신건강의학과(우울·불안·잠·마음)는 서로 대신할 수 없습니다. 아이 진료는 소아청소년과입니다.
6. 이용 방식(예: 포장인지 배달인지)은 주민이 말한 것만 적고, 짐작하지 않습니다."""
        user = f"[문 닫은 시설]\n{self._closed_text(st)}\n\n[대화]\n{self._history(st)}"
        out = self._call(system, user, tool)
        if out["kind"] != "UNCLEAR" and out["kind"] not in names: raise RuntimeError("없는 세부 종류")
        out["menu_words"] = [w.strip() for w in out.get("menu_words", []) if 1 < len(w.strip()) <= 10]
        return out

    # 한 번의 주민 말에 대한 처리
    def step(self, st, user_text):
        st.setdefault("history", []); st.setdefault("asked", 0); st.setdefault("elig_ok", set())
        st["history"].append({"role": "user", "text": user_text})
        if not st.get("leaf"):
            a = self.pick_leaf(st); st["last_leaf_pick"] = a
            if a["mobility"] != "모름": st["speed"] = a["mobility"]
            if a["leaf_id"] == "UNCLEAR" or a["confidence"] == "낮음":
                return self._ask(st, a["clarify_question"] or "어떤 일로 그곳에 다니셨는지 조금 더 알려 주시겠어요?", a["clarify_options"])
            st["leaf"] = a["leaf_id"]; st["matches_closed"] = a["matches_closed"]; st["asked"] = 0
        if st.get("kind") is None and self.E.leaf[st["leaf"]]["kinds"].get("sensitive"):
            b = self.pick_kind(st, st["leaf"]); st["last_kind_pick"] = b
            if b["kind"] == "UNCLEAR" or b["confidence"] == "낮음":
                return self._ask(st, b["clarify_question"] or "어떤 것을 찾으시는지 조금 더 알려 주시겠어요?", b["clarify_options"])
            st["kind"] = b["kind"]; st["asked"] = 0; st["menu_words"] = b.get("menu_words", [])
            if b.get("need") in self.E.needs.get(st["leaf"], set()): st["need"] = b["need"]
        return {"type": "ready", "leaf": st["leaf"], "kind": st.get("kind")}

    def _ask(self, st, q, options):
        st["asked"] += 1
        st["history"].append({"role": "assistant", "text": q})
        return {"type": "question", "text": q, "options": options, "count": st["asked"]}

    # 지자체 기록 (개인 정보 없이: 날짜, 구·군, 문 닫은 시설 번호, 목적, 결과 수)
    def log(self, st, n_found):
        if not self.log_path: return
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        e = {"date": datetime.date.today().isoformat(), "gu": st.get("gu"), "closed_fid": st.get("closed_fid"), "leaf": st.get("leaf"),
             "kind": st.get("kind"), "matches_closed": st.get("matches_closed"), "found": n_found}
        with open(self.log_path, "a", encoding="utf-8") as f: f.write(json.dumps(e, ensure_ascii=False) + "\n")
