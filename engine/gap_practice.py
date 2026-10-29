# 판단 에이전트의 경험 쌓기 (2026-10-20, 헌준님: "예시는 내 말을 이해하도록 돕는 것일 뿐. 에이전트가 스스로 사례를 수없이 만들고 경험을 쌓아 판단 모델을 만들어야 한다")
#
# 1) 사례 만들기 (크레딧 없음): 지금 영업 중인 실제 시설에 '오늘 문을 닫는다면'을 계산 → 실제 지도·인구로 잰 사실만 씀 (지어낸 사실 없음)
#    모든 생활 기능 × 도심/읍·면에서 고르게 뽑고, 가까이에 같은 일을 하는 곳이 없는(공백이 생길 수 있는) 시설부터 잼 → data/gov/practice_pool.jsonl
# 2) 고르기: 판단 재료(특징)가 서로 가장 다른 사례부터 고름 (먼 점 고르기, 기능마다 최소 몇 건) → 비슷한 사례만 잔뜩 배우지 않게
# 3) 판단·검토·중재 (크레딧): 서로 모르는 두 AI
#    - 판단관: 원칙에 따라 긴급·주의·관찰·해당 없음
#    - 검토관: 계산이 맞는지, 사람이 보고 '이게 왜 심각하지?'라고 묻지 않을지 따짐
#    - 둘이 다르면 중재관이 두 의견을 보고 최종 판단. 계산 검토(gov_agent.audit)를 통과하지 못한 사례는 '보고 안 함'으로 배움
#    → data/gov/experience.jsonl (경험)
# 4) 배우기: 경험으로 판단 모델(gap_agent.Scorer)을 학습. 경험의 20%는 떼어 두고 맞히는지 시험 → data/gov/practice_report.json
#    헌준님 예시 6건은 배우지 않고 '제대로 배웠는지' 보는 시험 문제로만 씀. 담당자 반응은 경험보다 3배 무겁게 배움
# 5) 매일: 그날 판단이 애매했던 실제 사례와 아직 판단하지 않은 사례를 조금씩 더 연습 (비용 상한 안에서)
import os, sys, json, time, math, random, re, hashlib, csv, datetime, threading
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gov_agent as GV, gap_agent as GA, gov_programs as GP, severity as SV
ROOT = GV.ROOT; GOV = os.path.join(ROOT, "data", "gov")
P_POOL = os.path.join(GOV, "practice_pool.jsonl"); P_EXP = os.path.join(GOV, "experience.jsonl")
P_STATE = os.path.join(GOV, "practice_state.json"); P_REP = os.path.join(GOV, "practice_report.json")
MODEL = "claude-sonnet-5-5"; TAG = "경험 쌓기"
DECS = ["긴급", "주의", "관찰", "해당 없음"]
RULES_VER = 3   # 3: 생활권 원칙 (읍·면 민간 가게는 생활권이 끊길 때만 보고, 10/20 헌준님). 2: 관찰(생활 필수 기능의 실제 공백)과 해당 없음(기호·편의 기능, 할 일 없음)을 나눔 (10/20 헌준님). 1판 경험은 보고 여부만 배움
def _jl(p): return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []
def _app(p, rows):
    with open(p, "a", encoding="utf-8") as fh:
        for r in rows: fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
def spent(since=None, tag=TAG):
    """이 작업에 쓴 돈(달러). data/usage/api_usage.csv"""
    f = os.path.join(ROOT, "data", "usage", "api_usage.csv")
    if not os.path.exists(f): return 0.0
    tot = 0.0
    for r in csv.DictReader(open(f, encoding="utf-8")):
        if r["용도"] == tag and (since is None or r["시각"] >= since): tot += float(r["달러"] or 0)
    return tot

# ───────── 1) 사례 만들기 ─────────
def functions(G):
    E = G.cm.engine()
    return sorted(set(E.leaf) | set(SV.SPECIAL))
def make_queue(G, per=60, seed=20):
    """기능 × 도심/읍·면마다 공백이 생길 수 있는 시설(같은 일을 하는 다른 곳이 직선 350m 밖)을 뽑아, 기능을 번갈아 가며 잴 순서를 만듦"""
    from scipy.spatial import cKDTree
    E = G.cm.engine(); KX = np.cos(np.radians(35.87)) * 111320; KY = 110540; rnd = random.Random(seed); groups = {}
    for lid in functions(G):
        try: P = [p for p in G._prov_all(lid) if p in E.F.index]
        except Exception: continue
        X = E.F.loc[P, ["x", "y"]].astype(float)
        X = X[X["x"].notna()]
        if len(X) < 2: continue
        d, _ = cKDTree(np.c_[X["x"] * KX, X["y"] * KY]).query(np.c_[X["x"] * KX, X["y"] * KY], k=2)
        far = [p for p, dd in zip(X.index, d[:, 1]) if dd >= 350]
        for p in far:
            dong = str(E.F.at[p, "행정동"] or "") or GV.dong_at(E.F.at[p, "경도"], E.F.at[p, "위도"])
            groups.setdefault((lid, bool(re.search(r"[읍면]$", dong))), []).append(p)
    q = []; keys = sorted(groups); seen = set()
    for k in keys: rnd.shuffle(groups[k]); groups[k] = groups[k][:per]
    while any(groups.values()):
        for k in keys:
            if groups[k]:
                p = groups[k].pop()
                if p not in seen: seen.add(p); q.append(p)
    return q
def hypo_item(G, fid):
    E = G.cm.engine(); r = E.F.loc[fid]
    c = {"fid": fid, "상호": r["상호"], "업종": r["업종"], "구군": r["구군"], "폐업일자": GV.today(), "주소": r["주소"],
         "행정동": r["행정동"] or GV.dong_at(r["경도"], r["위도"]), "경도": r["경도"], "위도": r["위도"]}
    a = G.analyze(fid, True)
    return {"fid": fid, "시설": c, "분석": a} if a else None
_GRADE = None
def grade_of(G, name):
    """기능 이름 → 분류표 등급(필수·준필수·선택)"""
    global _GRADE
    if _GRADE is None:
        E = G.cm.engine(); _GRADE = {l["name"]: l.get("grade") for l in E.leaf.values()}
        _GRADE.update({SV.NAME[k]: (E.leaf.get(k) or {}).get("grade", "필수") for k in SV.NAME})
    return _GRADE.get(name)
def case_of(G, it, A):
    """언어 모델에게 줄 사례 (실제 보고와 같은 재료, 다만 판단 모델 점수·비슷한 사례는 빼고 스스로 판단하게)"""
    fo = G._sfacts(dict(it, 판단재료=A), {})
    for k in ("판단_모델_점수", "점수에_크게_작용한_것", "비슷한_지난_사례"): fo.pop(k, None)
    rural = G._rural(it) is not False
    for f in fo.get("기능", []): f.setdefault("분류표_등급", grade_of(G, f["기능"]))
    fo["고를_수_있는_일"] = [{"id": p["id"], "할일": p["할일"]} for p in GP.for_item(A["셈한기능"], {"gap": True, "elder": True, "far": rural})][:6]
    au = G.audit(it, A); fo["계산_검토"] = {"통과": not au["문제"], "문제": au["문제"], "참고": au["참고"]}
    if au.get("원칙"): fo["보고_원칙"] = {"충족": False, "까닭": au["원칙"]}   # 생활권 원칙 (계산 오류가 아님)
    return fo, au
def _measure(G, fids, seconds, t0):
    out = []; tried = []
    for fid in fids:
        if time.time() - t0 > seconds: break
        tried.append(fid)
        try:
            it = hypo_item(G, fid)
            A = G.assess(it) if it else None
        except Exception: A = None
        if not A: continue
        fo, au = case_of(G, it, A); top = A["사실"][0]
        out.append({"fid": fid, "기능": top["기능"], "기능이름": top["이름"], "읍면": G._rural(it), "특징": [round(float(v), 4) for v in A["특징"]],
                    "사전점수": A["점수"], "감사": au, "사례": fo})
    return out, tried
_GW = None
def _work(args):
    fids, seconds, t0 = args
    return _measure(_GW, fids, seconds, t0)
def build_pool(G, seconds=140, workers=4):
    """이어서 하기: 한 번에 seconds초까지 재고 저장 (여러 일꾼이 나눠 잼)"""
    global _GW
    t0 = time.time(); st = json.load(open(P_STATE, encoding="utf-8")) if os.path.exists(P_STATE) else {}
    if not st.get("queue"): st = {"queue": make_queue(G), "done": [], "공백없음": 0}
    have = {r["fid"] for r in _jl(P_POOL)}; done = set(st.get("done", [])) | have
    todo = [f for f in st["queue"] if f not in done][:workers * 700]
    G.baseline(); G._severe(todo[0], "P03.2.01") if todo else None   # 일꾼이 나눠 쓰도록 먼저 읽어 둠
    _GW = G; parts = [todo[k::workers] for k in range(workers)]
    import multiprocessing as mp
    with mp.get_context("fork").Pool(workers) as pool:
        res = pool.map(_work, [(pt, seconds, t0) for pt in parts])
    out = [r for o, _ in res for r in o]; tried = [f for _, t in res for f in t]
    st["done"] = sorted(done | set(tried)); st["공백없음"] = st.get("공백없음", 0) + len(tried) - len(out)
    _app(P_POOL, out); json.dump(st, open(P_STATE, "w", encoding="utf-8"))
    return {"이번에_만든_사례": len(out), "모은_사례": len(have) + len(out), "잰_시설": len(st["done"]), "남은_시설": len(st["queue"]) - len(st["done"])}

# ───────── 2) 서로 가장 다른 사례 고르기 ─────────
def pick(n=600, per_fn=None, seed=7):
    pool = _jl(P_POOL); done = {r["fid"] for r in _jl(P_EXP)}
    pool = [r for r in pool if r["fid"] not in done]
    if not pool: return []
    X = np.array([r["특징"] for r in pool], float); mu = X.mean(0); sd = X.std(0) + 1e-6; Z = (X - mu) / sd
    rnd = random.Random(seed); chosen = []
    by = {}
    for i, r in enumerate(pool): by.setdefault((r["기능"], r["읍면"]), []).append(i)
    if per_fn is None: per_fn = max(1, int(0.4 * n / max(len(by), 1)))   # 고를 수의 40%는 기능 × 도심/읍·면마다 고르게, 나머지는 가장 다른 사례
    for k in sorted(by, key=str):   # 기능 × 도심/읍·면마다 몇 건은 꼭
        ids = by[k][:]; rnd.shuffle(ids); chosen += ids[:per_fn]
    chosen = chosen[:n]
    if len(chosen) < n:   # 나머지는 이미 고른 것과 가장 먼 사례부터 (먼 점 고르기)
        dmin = np.full(len(pool), np.inf)
        for c in chosen: dmin = np.minimum(dmin, np.linalg.norm(Z - Z[c], axis=1))
        if not chosen: chosen = [rnd.randrange(len(pool))]; dmin = np.linalg.norm(Z - Z[chosen[0]], axis=1)
        while len(chosen) < min(n, len(pool)):
            j = int(np.argmax(dmin)); chosen.append(j); dmin = np.minimum(dmin, np.linalg.norm(Z - Z[j], axis=1))
    return [pool[i] for i in chosen]

# ───────── 3) 판단·검토·중재 ─────────
def _client():
    import anthropic
    return anthropic.Anthropic(api_key=open(os.path.join(ROOT, "settings", "anthropic_key.txt"), encoding="utf-8").read().strip())
def _call(cl, system, tool, msg, max_tokens=6000):
    for _ in range(3):
        r = cl.messages.create(model=MODEL, max_tokens=max_tokens, system=[{"type": "text", "text": system + "\n도구만 부르고, 도구 밖에 다른 글은 쓰지 않습니다.", "cache_control": {"type": "ephemeral"}}],
                               tools=[tool], messages=[{"role": "user", "content": msg}])
        try:
            from chat import log_usage; log_usage(MODEL, r.usage, TAG)
        except Exception: pass
        res = next((b.input for b in r.content if b.type == "tool_use"), None)
        if res: return res
    return None
def rules(G):
    lessons = "\n".join(f"- {x['원칙']}" for x in G.lessons()) or "- (아직 없음)"
    return ("판단 (하나를 고름)\n"
            "- 긴급: 담당자가 오늘 바로 움직여야 함. 법이 보장하고 되살리기 어려운 생명·건강·돌봄 기능이 그 동네에서 사실상 끊김.\n"
            "- 주의: 담당자가 알고 할 일을 검토해야 하는 공백.\n"
            "- 관찰: 생활에 꼭 필요한 기능(먹거리·의료·약·돌봄·행정처럼 없으면 생활이 흔들리는 일)에 실제 공백이 생겼지만 지금 보고할 만큼은 아님. 근처가 더 닫히면 보고가 될 수 있어 매일 다시 살펴봄.\n"
            "- 해당 없음: 지켜볼 필요도 없음. 실제 공백이 아니거나(대신 갈 곳이 가까움, 시설 안 매장, 주민이 다니던 곳이 아님), "
            "생활 필수와 거리가 먼 기능이거나(빵·커피 같은 기호식품, 꽃·악기·가구·취미용품, 외식·여가처럼 없어도 생활이 이어지는 일), 지자체가 할 일이 없는 공백.\n\n"
            "기능이 생활 필수인지 기호·편의인지는 정해진 목록이 아니라, 기능의 성격(못 받으면 위험해지는 시간, 대신하는 방법, 분류표 등급, 누가 영향을 받는지)을 보고 스스로 판단합니다. "
            "예를 들어 편의점은 생활용품을 팔지만 도심에서는 다른 가게로 쉽게 대신하고 생명과 이어지지 않습니다.\n\n"
            f"원칙 (꼭 따름)\n{GA.principles()}\n담당자가 알려 준 원칙 (꼭 따름)\n{lessons}\n\n"
            "재료 읽는 법\n"
            "- 숫자는 실제 지도·인구로 계산한 것입니다. '계산_검토'의 문제가 있으면 계산을 믿을 수 없는 것이니 보고하지 않습니다. '참고'는 판단할 때 따져 봅니다.\n"
            "- '그_일을_하는지_모르는_곳까지_대신_갈_곳으로_볼_때'의 공백이 훨씬 작으면 자료가 부족한 것이니 보수적으로 봅니다.\n"
            "- '같은_건물의_다른_시설'로 호텔·병원·대학·산업단지 안 매장인지 봅니다.\n"
            "- '지자체가_할_수_있는_일이_있음'이 false이고 '고를_수_있는_일'이 비어 있으면, 생명과 바로 이어진 공백이 아닌 한 보고하지 않습니다(관찰). 담당자가 할 일이 없는 보고는 짐입니다.\n"
            "- '생활권_원칙_충족'이 false이면(읍·면 민간 가게인데 같은 일을 할 곳이 가깝거나 보조 가게이거나 읍내 시가지) 보고하지 않습니다(관찰). 읍·면이라는 이유만으로 보고하지 않습니다.\n"
            "- '생활권_원칙_충족'이 true이면 생활권 기준은 이미 넘은 것입니다(4km 안에 같은 일을 할 곳이 없거나, 면 마을의 장보기·진료 중심이 닫혀 1km 안에 대신할 곳이 없고 어르신이 대부분). 이때 '4km 안에 대신할 곳이 있다'는 이유로 다시 낮추지 않고, 공백의 크기·어르신 수·자료 확실성·할 일로 판단합니다.\n"
            "- '생활권', '같은_일을_할_곳까지_직선_km', '보조_가게', '영향_주민_중_어르신_비율'로 그 동네가 실제로 고립되는지 봅니다. 수요응답형 교통·이동장터 같은 일은 생활권이 끊긴 마을의 일입니다.\n"
            "- 보고는 담당자에게 일을 주는 것입니다. 사람이 보고 '이게 왜 심각한 문제지?'라고 물을 만한 공백은 보고하지 않습니다.")
JUDGE_TOOL = {"name": "judge", "description": "사례마다 판단", "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "decision": {"type": "string", "enum": DECS}, "reason": {"type": "string", "description": "핵심 근거, 개조식 60자 안"}},
    "required": ["id", "decision", "reason"]}}}, "required": ["items"]}}
REVIEW_TOOL = {"name": "review", "description": "사례마다 검토", "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "agree": {"type": "boolean"}, "decision": {"type": "string", "enum": DECS, "description": "검토관 자신의 판단"},
    "plain": {"type": "string", "description": "보고라면 왜 심각한지를 숫자 없이 주민도 알아듣게 한 문장(70자 안). 보고하지 않는다면 왜 그래도 되는지 한 문장"},
    "issues": {"type": "array", "items": {"type": "string"}, "description": "계산·사실·원칙에 어긋난 점 (없으면 빈 목록)"}},
    "required": ["id", "agree", "decision", "plain"]}}}, "required": ["items"]}}
ARB_TOOL = {"name": "decide", "description": "최종 판단", "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "decision": {"type": "string", "enum": DECS}, "reason": {"type": "string", "description": "개조식 60자 안"}}, "required": ["id", "decision", "reason"]}}}, "required": ["items"]}}
def judge(G, cl, cases):
    sys_p = ("당신은 대구시 구·군 복지·공공시설 담당 공무원의 업무 비서인 AI 에이전트입니다. 문 닫은 시설마다 계산한 사실을 받아 담당자에게 보고할지 스스로 판단합니다. "
             "담당자가 모든 것을 확인하지 않아도 되도록, 보고할 것만 보고합니다.\n\n" + rules(G) + "\n\n판단 결과는 반드시 judge 도구로 냅니다.")
    res = _call(cl, sys_p, JUDGE_TOOL, f"사례 {len(cases)}곳입니다.\n" + json.dumps([dict(c["사례"], id=c["fid"]) for c in cases], ensure_ascii=False))
    return {x["id"]: x for x in (res or {}).get("items", []) if x.get("decision") in DECS}
def review(G, cl, cases, dec):
    sys_p = ("당신은 구청의 계산 검증관이자 깐깐한 검토자입니다. 다른 AI가 내린 '담당자에게 보고할지' 판단을 독립적으로 검토합니다.\n"
             "1) 계산 확인: 재료의 숫자끼리 맞는지(폐업 전 거리는 기준 안, 폐업 뒤 거리는 기준 밖, 대체 시설의 걷는 시간), '계산_검토'의 문제·참고가 판단에 반영됐는지.\n"
             "2) 납득 시험: 보고(긴급·주의)라면 왜 심각한지 숫자 없이 주민도 알아듣게 한 문장으로 설명해 봅니다. 설명이 억지스럽거나 '이게 왜 심각하지?'라는 반문이 나올 만하면 동의하지 않습니다. "
             "보고하지 않는 판단(관찰·해당 없음)이라면, 놓치면 주민이 실제로 위험해지거나 생활이 무너지는 공백이 아닌지 따집니다.\n"
             "3) 원칙 확인: 아래 원칙과 판단 기준에 맞는지.\n\n" + rules(G) + "\n\n검토 결과는 반드시 review 도구로 냅니다.")
    body = [dict(c["사례"], id=c["fid"], 판단관={"판단": dec[c["fid"]]["decision"], "까닭": dec[c["fid"]]["reason"]}) for c in cases if c["fid"] in dec]
    res = _call(cl, sys_p, REVIEW_TOOL, f"사례 {len(body)}곳과 판단관의 판단입니다.\n" + json.dumps(body, ensure_ascii=False))
    return {x["id"]: x for x in (res or {}).get("items", []) if x.get("decision") in DECS}
def arbitrate(G, cl, cases, dec, rev):
    sys_p = ("당신은 구청 생활공백 판단 책임자입니다. 판단관과 검토관의 의견이 다른 사례를 받아, 사실과 원칙에 비춰 최종 판단합니다. "
             "계산에 문제가 있으면 보고하지 않습니다. 사람이 보고 '이게 왜 심각하지?'라고 물을 만하면 보고하지 않고, 놓치면 주민이 실제로 위험해지는 공백은 보고합니다.\n\n" + rules(G) +
             "\n\n결과는 반드시 decide 도구로 냅니다.")
    body = [dict(c["사례"], id=c["fid"], 판단관={"판단": dec[c["fid"]]["decision"], "까닭": dec[c["fid"]]["reason"]},
                 검토관={"판단": rev[c["fid"]]["decision"], "설명": rev[c["fid"]].get("plain", ""), "문제": rev[c["fid"]].get("issues", [])}) for c in cases]
    res = _call(cl, sys_p, ARB_TOOL, f"의견이 다른 사례 {len(body)}곳입니다.\n" + json.dumps(body, ensure_ascii=False))
    return {x["id"]: x for x in (res or {}).get("items", []) if x.get("decision") in DECS}
def label(G, cases, cl=None):
    """사례 묶음 하나(10곳 안팎)를 판단 → 검토 → (다르면) 중재 → 경험으로 저장"""
    cl = cl or _client()
    dec = judge(G, cl, cases)
    rev = review(G, cl, [c for c in cases if c["fid"] in dec], dec) if dec else {}
    split = [c for c in cases if c["fid"] in dec and c["fid"] in rev and not rev[c["fid"]]["agree"] and rev[c["fid"]]["decision"] != dec[c["fid"]]["decision"]]
    arb = arbitrate(G, cl, split, dec, rev) if split else {}
    rows = []
    for c in cases:
        f = c["fid"]
        if f not in dec or f not in rev: continue
        if f in arb: final, how = arb[f]["decision"], "중재"
        elif rev[f]["agree"] or rev[f]["decision"] == dec[f]["decision"]: final, how = dec[f]["decision"], "합의"
        else: continue
        if not c["감사"]["통과"] and final in ("긴급", "주의"): final, how = "관찰", how + ("·계산 검토 실패로 보고 안 함" if c["감사"].get("문제") else "·생활권 원칙으로 보고 안 함")
        rows.append({"때": GV.now().isoformat(timespec="seconds"), "규칙": RULES_VER, "fid": f, "기능": c["기능"], "기능이름": c["기능이름"], "읍면": c["읍면"], "특징": c["특징"],
                     "판단": final, "보고": final in ("긴급", "주의"), "어떻게": how, "판단관": dec[f], "검토관": rev[f], "중재관": arb.get(f),
                     "요약": f"{c['사례'].get('시설')}({c['사례'].get('업종')}, {c['사례'].get('행정동')}) 가정 폐업: {c['기능이름']}", "감사": c["감사"]})
    _app(P_EXP, rows); return rows
def label_many(G, cases, batch=10, workers=5, seconds=150, budget=None, since=None):
    """여러 묶음을 동시에 (한 번에 seconds초까지, 비용 상한 budget달러)"""
    t0 = time.time(); cl = _client(); groups = [cases[i:i + batch] for i in range(0, len(cases), batch)]; out = []; lock = threading.Lock(); idx = [0]
    def work():
        while True:
            with lock:
                if idx[0] >= len(groups) or time.time() - t0 > seconds or (budget is not None and spent(since) > budget): return
                g = groups[idx[0]]; idx[0] += 1
            try: r = label(G, g, cl)
            except Exception as ex: r = []; print("오류", str(ex)[:120])
            with lock: out.extend(r)
    th = [threading.Thread(target=work) for _ in range(workers)]
    for t in th: t.start()
    for t in th: t.join()
    return out

# ───────── 4) 배우기 ─────────
_GRADE = None
def _grade(lid):
    global _GRADE
    if _GRADE is None:
        T = json.load(open(os.path.join(GV.ROOT, "design", "purpose_taxonomy.json"), encoding="utf-8"))
        _GRADE = {l["id"]: l.get("grade") for c in T["categories"] for q in c["purposes"] for l in q["leaves"]}
    return _GRADE.get(lid, "필수" if str(lid).startswith("G:") else None)
def in_scope_case(r):
    """(10/26 전수 점검) 공백 심각도 판정 대상 기능의 사례만 배움: 카페·꽃·가구 같은 생활 필수 아닌 기능을 '관찰'로 배운 사례가 판단 모델에 섞이지 않게"""
    lid = r.get("기능"); g = _grade(lid); rural = bool(r.get("읍면"))
    if g not in ("필수", "준필수"): return False
    if lid in GV.SKIP_FUNC: return rural and lid in GV.VILLAGE_OK and lid not in GV.VILLAGE_NO   # 외식·친목 장소는 읍·면 마을 예외에서만
    return True   # 사례에는 세부 종류가 남아 있지 않아 기능 단위로 가름
def experiences(): return [r for r in _jl(P_EXP) if len(r.get("특징", [])) == len(GA.FEATS)]
def _fold(fid): return int(hashlib.md5(fid.encode()).hexdigest(), 16) % 5   # 다섯 묶음 (돌아가며 시험)
def _hold(fid): return _fold(fid) == 0   # 20%는 시험용
def _fit(name, rows, test):
    """한 갈래를 배우고(시험용을 뺀 경험으로) 시험 → 다시 모든 경험으로 배워 저장"""
    S = GA.Scorer(name); S.m = {"bias": S.prior["bias"], "w": list(S.prior["w"]), "사례수": 0, "배운때": None}
    lam = 1.0 if name == "report" else 0.5
    if name == "urgent":   # 긴급은 아주 적어(600건 중 9건) 적은 쪽을 그만큼 무겁게 배움
        npos = sum(1 for r in rows if r[1]); nneg = len(rows) - npos
        if npos and nneg: rows = [(r[0], r[1], r[2] * (nneg / npos if r[1] else 1.0)) + tuple(r[3:]) for r in rows]
    tr = [r for r in rows if not r[3]]; te = [r for r in rows if r[3]]
    S.train([r[:3] for r in tr], lam=lam, steps=2000, lr=0.2)
    # 보고 문턱도 시험 사례로 배움: 잘못 보고(담당자에게 짐, '이게 왜 심각하지?')를 놓친 보고보다 1.5배 무겁게 보고 가장 적게 틀리는 문턱
    thr = 0.5
    if name == "report" and te:
        # 보고 문턱 (10/20 고침): 시험 사례 한 묶음(보고 사례 20건 안팎)으로 정하면 흔들려서, 경험 전체를 다섯 묶음으로 나눠 돌아가며 시험한 점수로 정함.
        # 원칙대로 무게를 둠: 도심의 필요 없는 보고('이게 왜 심각하지?') 1.5, 읍·면(관심 지역)의 놓친 보고 1.5, 그 밖 1.0. 비용이 거의 같으면 0.5에 가까운 문턱
        oof = []
        for k in range(5):
            Sk = GA.Scorer(name); Sk.m = {"bias": Sk.prior["bias"], "w": list(Sk.prior["w"]), "사례수": 0, "배운때": None}
            Sk.train([r[:3] for r in rows if r[4] != k], lam=lam, steps=2000, lr=0.2)
            oof += [(Sk.p(r[0]), r[1], float(r[0][GA.FEATS.index("읍·면")]) >= 0.5) for r in rows if r[4] == k]
        def cost(t):
            c = 0.0
            for p_, y, rural in oof:
                if p_ >= t and not y: c += 1.0 if rural else 1.5
                elif p_ < t and y: c += 1.5 if rural else 1.0
            return c
        grid = [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]; best = min(cost(t) for t in grid)
        thr = min([t for t in grid if cost(t) <= best * 1.03 + 0.5], key=lambda t: abs(t - 0.5))
    elif te:   # 관찰: 기호·편의 기능을 '지켜볼 공백'으로 잘못 두는 것을 1.2배 무겁게 / 긴급: 생명 직결 공백을 주의로 낮추는 것을 2배 무겁게
        cfp, cfn = (1.2, 1.0) if name == "watch" else (1.0, 2.0)
        if len(rows[0]) > 4:   # 보고 문턱과 같이 다섯 묶음을 돌아가며 시험한 점수로 (한 묶음만 보면 흔들림)
            sc = []
            for k in range(5):
                Sk = GA.Scorer(name); Sk.m = {"bias": Sk.prior["bias"], "w": list(Sk.prior["w"]), "사례수": 0, "배운때": None}
                Sk.train([r[:3] for r in rows if r[4] != k], lam=lam, steps=2000, lr=0.2)
                sc += [(Sk.p(r[0]), r[1]) for r in rows if r[4] == k]
        else: sc = [(S.p(r[0]), r[1]) for r in te]
        cost = lambda t: sum(cfp for p_, y in sc if p_ >= t and not y) + sum(cfn for p_, y in sc if p_ < t and y)
        grid = [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]; best = min(cost(t) for t in grid)
        thr = min([t for t in grid if cost(t) <= best * 1.03 + 0.5], key=lambda t: abs(t - 0.5))
    pred = [S.p(r[0]) >= thr for r in te]
    res = {"배운_사례": len(tr), "시험_사례": len(te),
           "정확도": round(sum(p_ == bool(r[1]) for p_, r in zip(pred, te)) / len(te), 3) if te else None,
           "틀리게_예": sum(1 for p_, r in zip(pred, te) if p_ and not r[1]), "틀리게_아니요": sum(1 for p_, r in zip(pred, te) if not p_ and r[1]),
           "맞힌_예": sum(1 for p_, r in zip(pred, te) if p_ and r[1]), "맞힌_아니요": sum(1 for p_, r in zip(pred, te) if not p_ and not r[1])}
    S2 = GA.Scorer(name); S2.m = {"bias": S2.prior["bias"], "w": list(S2.prior["w"]), "사례수": 0, "배운때": None}
    m = S2.train([r[:3] for r in rows], lam=lam, steps=2000, lr=0.2)
    m["문턱"] = thr; res["문턱"] = thr; GA._js(S2.path, m)
    return res, m, S
def train():
    """경험(무게 1, 중재는 0.7) + 담당자 반응(무게 3)으로 세 갈래를 배움. 헌준님 예시는 시험에만"""
    GA._EXP = None   # 비슷한 사례 찾기가 새 경험을 쓰도록
    exp = experiences(); last = {}
    for r in exp: last[r["fid"]] = r
    exp = list(last.values())
    off = [r for r in GA.precedents() if r.get("누가") not in ("헌준님 예시",) and r["판단"] in GA.LABEL and len(r["특징"]) == len(GA.FEATS)]
    seeds = [r for r in GA.precedents() if r.get("누가") == "헌준님 예시"]
    X = lambda r: np.array(r["특징"], float); wt = lambda r: 0.7 if r["어떻게"].startswith("중재") else 1.0
    rep_rows = [(X(r), 1 if r["보고"] else 0, wt(r), _hold(r["fid"]), _fold(r["fid"])) for r in exp] + [(X(r), GA.LABEL[r["판단"]], 3.0, False, -1) for r in off]   # 담당자 반응은 늘 배움에만
    watch_rows = [(X(r), 1 if r["판단"] == "관찰" else 0, wt(r), _hold(r["fid"]), _fold(r["fid"])) for r in exp if not r["보고"] and r.get("규칙", 1) >= 2 and in_scope_case(r)]   # (10/26) 관찰은 생활 필수 기능 사례로만 배움 (카페·꽃집을 '관찰'로 배운 사례 뺌). 보고 여부는 그런 사례도 '보고 안함'의 바른 예라 그대로 씀
    urg_rows = [(X(r), 1 if r["판단"] == "긴급" else 0, wt(r), _hold(r["fid"]), _fold(r["fid"])) for r in exp if r["보고"]]
    out = {}
    out["보고"], m, S = _fit("report", rep_rows, None)
    if len(watch_rows) >= 20: out["관찰"], _, _ = _fit("watch", watch_rows, None)
    if len(urg_rows) >= 20 and sum(r[1] for r in urg_rows) >= 5: out["긴급"], _, _ = _fit("urgent", urg_rows, None)
    seed_ok = []
    for r in seeds:
        x = np.array(r["특징"], float)
        if len(x) != len(GA.FEATS): continue
        got = GA.fallback(GA.Scorer("report").p(x), {"성격": {}, "전체": {}}, x)
        want = r["판단"]; ok = (got in ("긴급", "주의")) == (want == "보고") if want in ("보고", "관찰", "해당 없음") else None
        seed_ok.append({"사례": r["요약"][:45], "헌준님": want, "모델": got, "보고_여부_맞음": ok})
    from collections import Counter
    rep = {"때": GV.now().isoformat(timespec="seconds"), "경험": len(exp), "담당자_반응": len(off),
           "판단_분포": dict(Counter(r["판단"] for r in exp)), "합의": sum(1 for r in exp if r["어떻게"].startswith("합의")), "중재": sum(1 for r in exp if r["어떻게"].startswith("중재")),
           "계산검토_실패": sum(1 for r in exp if not r["감사"]["통과"]),
           "기능_수": len({r["기능"] for r in exp}), "읍면_사례": sum(1 for r in exp if r["읍면"] is True), "도심_사례": sum(1 for r in exp if r["읍면"] is False),
           "시험": out, "헌준님_예시_시험": seed_ok,
           "보고_가중치": dict(zip(GA.FEATS, m["w"])), "보고_절편": m["bias"]}
    json.dump(rep, open(P_REP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return rep

# ───────── 5) 매일 조금씩 ─────────
def daily(G, its=None, n=20, budget=0.3):
    """오늘 판단이 애매했던 실제 사례(점수 0.3~0.75)와 아직 판단하지 않은 사례를 연습 → 다시 배움"""
    since = datetime.datetime.now().isoformat(timespec="seconds")   # 사용 기록(chat.log_usage)과 같은 시계
    done = {r["fid"] for r in _jl(P_EXP)}; cases = []
    for it in (its or []):
        A = it.get("판단재료")
        if not A or it["fid"] in done or not (0.3 <= A["점수"] <= 0.75): continue
        fo, au = case_of(G, it, A); top = A["사실"][0]
        cases.append({"fid": it["fid"], "기능": top["기능"], "기능이름": top["이름"], "읍면": G._rural(it), "특징": [round(float(v), 4) for v in A["특징"]], "감사": au, "사례": fo})
    if GV.now().weekday() == 0: cases += pick(max(0, n - len(cases)))   # 새 사례 만들기는 월요일만 (10/21 비용). 다른 날은 그날 판단이 애매했던 실제 사례만 연습
    if not cases: return {"연습": 0}
    rows = label_many(G, cases[:n], batch=10, workers=2, seconds=120, budget=budget + spent(since), since=since)
    rep = train() if rows else None
    return {"연습": len(rows), "경험": rep["경험"] if rep else None, "시험_정확도": (rep or {}).get("시험", {}).get("정확도")}

if __name__ == "__main__":
    G = GV.GovAgent(); G.baseline(); cmd = sys.argv[1] if len(sys.argv) > 1 else "pool"
    if cmd == "pool": print(build_pool(G, seconds=float(sys.argv[2]) if len(sys.argv) > 2 else 140))
    elif cmd == "label":   # python engine/gap_practice.py label 목표건수 비용상한
        goal = int(sys.argv[2]); cap = float(sys.argv[3]); since = sys.argv[4] if len(sys.argv) > 4 else "2026-10-20T00:00:00"   # 이 날짜 뒤로 쓴 돈의 상한
        have = len(_jl(P_EXP)); need = goal - have
        if need <= 0: print("이미", have); sys.exit()
        cs = pick(need); print("고른 사례", len(cs), "지금까지 쓴 돈", round(spent(since), 3))
        rows = label_many(G, cs, batch=10, workers=6, seconds=float(sys.argv[5]) if len(sys.argv) > 5 else 140, budget=cap, since=since)
        print("이번", len(rows), "경험 합계", len(_jl(P_EXP)), "쓴 돈", round(spent(since), 3))
    elif cmd == "train": print(json.dumps(train(), ensure_ascii=False, indent=1)[:3000])
