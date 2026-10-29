# 창업·유치 참고 (10/20 헌준님): 지자체 보고 대상은 아니지만 생활 필수 기능이 사라진 곳을, 같은 업종을 새로 열면 경쟁이 되는지까지 따져 공개
#  지자체 보고 기준과 섞지 않음: 보고 판단(gov_agent.brief)이 끝난 뒤, AI가 '관찰'(생활 필수 기능의 실제 공백, 보고할 만큼은 아님)로 둔 민간 가게만 봄
#  1) 계산 (코드): 그 기능의 분류표 등급(필수·준필수만), 같은 업종(같은 묶음) 가게가 그 기능의 기준 거리 안에 몇 곳인지, 가장 가까운 같은 업종까지,
#     같은 업종을 걸어서 갈 수 있는 곳이 없어진 주민(새로 열면 경쟁 없이 맡을 수요)
#  2) 문턱 (코드, 누구나 확인 가능): 기준 거리 안 같은 업종 1곳 이하 + 경쟁 없는 수요가 동(도심) 100명·읍·면 30명 이상
#  3) AI 상권 판단 (따로 부름): 위 사실만 보고 '공개 / 공개 안 함'과 한 줄 까닭. 매출·임대료·폐업 원인처럼 모르는 것은 말하지 않음
import os, json, hashlib, re
import gap_agent as GA
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P_CACHE = os.path.join(ROOT, "data", "gov", "market_judged.json")
MIN_POP = {"동": 100, "읍": 30, "면": 30}; MAX_RIVAL = 1
MODEL = "claude-sonnet-5-5"
def _j(p, d):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d

def facts(G, it, A):
    """창업·유치 참고에 쓸 계산 사실 (조건에 맞지 않으면 None)"""
    if not A or str(it["fid"]).startswith("P:"): return None   # 공공 시설은 창업 대상이 아님
    E = G.cm.engine(); fid = it["fid"]
    for fx in A["사실"]:
        lid = fx["기능"]
        if fx.get("돌봄기관") or lid.startswith("G:") or lid in getattr(G, "ENROLL_SET", set()): continue
        grade = (fx.get("성격") or {}).get("등급")
        if grade not in ("필수", "준필수"): continue   # 생활 필수 기능만 (기호·편의는 부가 요소)
        s = fx.get("전체")   # 그 기능의 중심 업종이 닫힌 경우만 (전문과·보조 가게 폐업은 생활 필수 기능 전체의 공백이 아님 — gov_agent.case_facts 원칙)
        if not s or s.get("아이"): continue
        r = E.F.loc[fid]
        if r["x"] != r["x"]: continue
        code = str(r["업종코드"]); rad = s.get("기준_m") or 1000
        O = E.F[(E.F["업종코드"] == code) & (E.F["대안후보"] == "예") & E.F["x"].notna() & (E.F.index != fid)]   # 같은 업종(업종코드가 같은 가게): 새로 열면 바로 경쟁하는 곳
        d = (((O["x"] - float(r["x"])) * 90200) ** 2 + ((O["y"] - float(r["y"])) * 110540) ** 2) ** 0.5
        near = d.sort_values()
        P = [p for p in G._prov_all(lid) if p != fid and p in E.F.index and str(E.F.at[p, "업종코드"]) != code]   # 같은 일을 하는 다른 업종 (예: 슈퍼마켓 자리 근처의 편의점)
        dp = (((E.F.loc[P, "x"] - float(r["x"])) * 90200) ** 2 + ((E.F.loc[P, "y"] - float(r["y"])) * 110540) ** 2) ** 0.5 if P else None
        rivals = int((d <= rad).sum()); area = fx.get("생활권") or "동"
        return {"fid": fid, "기능": lid, "기능이름": fx["이름"], "등급": grade, "업종": str(r["업종"]), "생활권": area,
                "기준_m": int(rad), "기준_안_같은업종": rivals, "기준_안_같은일_다른업종": int((dp <= rad).sum()) if dp is not None else 0,
                "가장가까운_같은업종": [{"상호": str(E.F.loc[p, "상호"]), "직선_m": int(v)} for p, v in near.head(3).items()],
                "경쟁없는_수요": int(s.get("밀려난주민") or 0), "그중_65세이상": int(s.get("밀려난_65세이상") or 0),
                "통과": rivals <= MAX_RIVAL and int(s.get("밀려난주민") or 0) >= MIN_POP.get(area, 100)}
    return None

TOOL = {"name": "decide", "description": "곳마다 판단", "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "decision": {"type": "string", "enum": ["공개", "공개 안 함"]},
    "reason": {"type": "string", "description": "판단의 핵심을 공문서 개조식(명사형 종결) 35자 안으로. 화면에 숫자가 따로 나오므로 숫자를 되풀이하지 않음. 예: '면 유일 연료점 폐업, 대체 연료점 멀어 수요 공백 뚜렷'"}}, "required": ["id", "decision", "reason"]}}}, "required": ["items"]}}
SYS = ("당신은 대구시 생활 기능 공백 자료를 관리하는 AI입니다. 문을 닫은 민간 가게 가운데, 같은 업종을 새로 열려는 사람(창업)이나 시설 유치를 검토하는 사람에게 "
       "'이 동네에 생활 필수 기능이 비어 있다'고 알릴 만한 곳인지 판단합니다. 지자체 보고와는 다른 자료입니다.\n"
       "- 공개: 생활에 꼭 필요한 기능(먹거리·약·진료·생활필수품 등)이고, 같은 업종이 기준 거리 안에 없거나 한 곳뿐이어서 새로 열어도 기존 가게와 수요를 크게 나누지 않으며, 경쟁 없이 맡을 주민이 충분할 때.\n"
       "- 공개 안 함: 기준 거리 바로 밖에 같은 업종이 여럿 있어 사실상 경쟁이 되는 도심, 주민 수가 너무 적어 의미가 작은 곳, 기호·편의에 가까운 기능.\n"
       "- 도심은 기준 거리 밖이라도 가까운 같은 업종이 많을 수 있으니 '가장가까운_같은업종'의 거리도 봅니다. 읍·면은 주민이 적어도 대신할 곳이 멀면 의미가 큽니다.\n"
       "- 매출·임대료·폐업 원인·장사가 될지는 모르는 것이니 말하지 않습니다. 주어진 숫자만 씁니다.\n- '필수', '준필수' 같은 분류 등급 낱말은 쓰지 않습니다. 기능은 이발·미용, 식료품처럼 담당자가 아는 말로 씁니다.\n결과는 반드시 decide 도구로.")

def judge(items, client=None):
    """AI 상권 판단 (같은 사실이면 다시 부르지 않음)"""
    cache = _j(P_CACHE, {}); out = {}; todo = []
    for f in items:
        sig = hashlib.md5(json.dumps({k: v for k, v in f.items() if k != "통과"}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        c = cache.get(f["fid"])
        if c and c.get("sig") == sig: out[f["fid"]] = c
        else: todo.append((f, sig))
    if todo and client is not None:
        try:
            PLAIN = {"필수": "매일·자주 쓰지 않으면 생활이 어려운 기능 (먹거리·약·진료 등)", "준필수": "생활에 필요하지만 며칠·몇 주 간격으로 쓰는 기능 (이·미용·세탁 등)"}
            body = [dict({k: v for k, v in f.items() if k not in ("통과", "fid", "등급")}, id=f["fid"], 기능_성격=PLAIN.get(f.get("등급"), "")) for f, _ in todo]   # (10/26) 등급의 뜻은 그대로 AI 판단에 주되, 내부 낱말(필수·준필수)은 화면 글에 나오지 않게 풀어서 줌
            r = client.messages.create(model=MODEL, max_tokens=3000, system=SYS, tools=[TOOL],
                                       messages=[{"role": "user", "content": json.dumps(body, ensure_ascii=False)}])
            try:
                from chat import log_usage; log_usage(MODEL, r.usage, "창업 참고 판단")
            except Exception: pass
            res = next((b.input for b in r.content if b.type == "tool_use"), {}) or {}
            sigs = {f["fid"]: s for f, s in todo}
            for x in res.get("items", []):
                if x.get("id") in sigs and x.get("decision") in ("공개", "공개 안 함"):
                    out[x["id"]] = cache[x["id"]] = {"sig": sigs[x["id"]], "판단": x["decision"], "까닭": re.sub(r"\s+", " ", str(x.get("reason") or "")).strip()[:120]}
            os.makedirs(os.path.dirname(P_CACHE), exist_ok=True); json.dump(cache, open(P_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as ex: out["_오류"] = repr(ex)[:200]
    return out

def rows(G, quiet_items, client=None):
    """보고 판단이 끝난 '관찰' 민간 가게들 → 창업·유치 참고 행 (AI가 '공개'라고 한 곳만. AI를 부르지 못하면 비움: 사람이 보는 공개 자료라 계산만으로 올리지 않음)"""
    F = []
    for it, A in quiet_items:
        f = facts(G, it, A)
        if f and f["통과"]: F.append((it, f))
    dec = judge([f for _, f in F], client) if F else {}
    out = []
    for it, f in F:
        d = dec.get(f["fid"])
        if not d or d["판단"] != "공개": continue
        c = it["시설"]
        out.append({"fid": f["fid"], "기능id": f["기능"], "구군": c["구군"], "행정동": it["분석"].get("행정동") or f["생활권"], "기능": f["기능이름"], "업종": f["업종"], "상호": c["상호"], "폐업일자": c.get("폐업일자"),
                    "경쟁없는_수요": f["경쟁없는_수요"], "그중_65세이상": f["그중_65세이상"], "기준_m": f["기준_m"], "기준_안_같은업종": f["기준_안_같은업종"],
                    "가장가까운_같은업종": f["가장가까운_같은업종"][:1], "생활권": f["생활권"], "까닭": d["까닭"], "경도": c.get("경도"), "위도": c.get("위도")})
    return sorted(out, key=lambda r: (r["구군"], -r["경쟁없는_수요"]))
