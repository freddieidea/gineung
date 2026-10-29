# 생활 공백 판단 에이전트의 '생각하는 부분' (10/19 다시 세움, 헌준님: "물새는 곳을 테이프로 막지 말고, 스스로 판단하고 배우는 AI를 만들어 달라")
#
#  예전: 계산 규칙(시장만 따로, 도심은 생명 직결 목록만…)이 보고 여부를 정하고, AI는 글만 다듬음 → 목록에 없는 경우가 나올 때마다 규칙을 덧댐
#  이제: 계산은 '사실'만 만들고, 보고할지는 판단하는 쪽이 정하며, 담당자의 반응으로 배움
#
#   1) 사실 (gov_agent.GovAgent.case_facts): 문 닫은 곳이 하던 모든 일마다 같은 방식으로 잼. 목록으로 거르지 않음
#      멀어지는 주민(전체·65세 이상), 전후 거리, 대신 갈 곳(확실한 곳/모르는 곳까지), 같은 종류만 볼 때, 도심·농촌, 자료가 얼마나 확실한지
#   2) 기능의 성격 (design/function_profiles.json): 몇 시간 안에 못 받으면 생명이 위험한지, 얼마나 자주 쓰는지, 배달·방문·교통으로 대신할 수 있는지
#      AI가 기능마다 한 번 정리하고(pipeline/build_function_profiles.py), 담당자가 고칠 수 있음. 아직 정리 전이면 자료로 임시 성격을 만듦
#   3) 원칙 (data/gov/principles.md): 헌준님·담당자가 말한 원칙. 코드 규칙이 아니라 AI가 읽고 따르는 글
#   4) 사례 (data/gov/precedents.jsonl): 담당자가 '보고로 올리기' '보고 안 해도 됨' '처리 완료'를 누를 때마다 쌓임
#   5) 판단 모델 (data/gov/scorer.json): 사례로 매일 다시 배우는 작은 로지스틱 모델 (크레딧 없음).
#      처음 값(사전 지식)은 원칙에서 옴 → 사례가 쌓일수록 담당자 판단 쪽으로 바뀜 (사전값 쪽으로 당기는 정규화로 사례가 적을 때 흔들리지 않게)
#   6) 판단: AI 에이전트가 사실·성격·원칙·비슷한 사례·모델 점수를 보고 보고 대상(심각·주의)·관찰·해당 없음을 정함 (gov_agent._judge)
#      AI가 없을 때(크레딧·오류)는 모델 점수로 정하되 보수적으로 (확실할 때만 보고, 나머지는 관찰)
#   7) 확인: AI가 쓴 사실이 계산과 어긋나면(예: 대신 갈 곳이 있는데 '없다') 받지 않고 모델 판단으로 돌림
import os, json, math, re, datetime
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOV = os.path.join(ROOT, "data", "gov")
P_PROF = os.path.join(ROOT, "design", "function_profiles.json")
P_PRIN = os.path.join(GOV, "principles.md")
P_PREC = os.path.join(GOV, "precedents.jsonl")
P_SCORER = os.path.join(GOV, "scorer.json")
P_OVR = os.path.join(GOV, "overrides.json")

def _jl(p, d):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d
def _js(p, x):
    os.makedirs(os.path.dirname(p), exist_ok=True); tmp = p + ".tmp"
    json.dump(x, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, p)
def now(): return datetime.datetime.now().isoformat(timespec="seconds")

# ── 2) 기능의 성격 ──
TIME_W = {"분": 1.0, "시간": 0.8, "일": 0.4, "주": 0.15, "달": 0.05}
def bootstrap_profile(lid, name, pb=None, modes=None, grade=None):
    """AI가 정리하기 전 임시 성격: 자료(공공 근거의 권리, 분류, 이용 방법)로만 짐작. 'AI 정리 전'이라고 표시함"""
    right = (pb or {}).get("권리", "") if pb else ""
    if lid in ("P03.1.02", "G:분만", "G:신생아중환자", "G:중환자", "P13.1.02"): t = "분"
    elif "생명" in right or "결식" in right: t = "시간"
    elif grade == "선택": t = "달"   # 분류표에서 '있으면 좋은' 일 (외식·카페·취미 등)
    elif lid.startswith(("P03", "P04", "P01", "P02")) and grade == "필수": t = "일"
    elif grade in ("필수", "준필수"): t = "주"
    else: t = "달"
    sub = [m for m in (modes or []) if m in ("배달", "방문", "택배", "온라인", "전화")]
    return {"이름": name, "시간민감도": t, "생명직결": t in ("분", "시간"), "대신하는_방법": sub, "대신_정도": 0.5 if sub else 0.0,
            "취약계층": [], "근거": "AI가 정리하기 전 임시 성격 (공공 근거·분류·이용 방법으로 짐작)", "만든이": "임시"}
def profiles(): return _jl(P_PROF, {})
def profile(lid, name, pb=None, modes=None, grade=None):
    p = profiles().get(lid)
    return dict(p, 등급=grade) if p else dict(bootstrap_profile(lid, name, pb, modes, grade), 등급=grade)

# ── 3) 원칙 ──
DEFAULT_PRINCIPLES = """# 지자체 보고 원칙 (AI 에이전트가 읽고 따르는 글. 담당자가 고칠 수 있음)
- 시설의 종류가 아니라 시설이 하던 생활 기능을 기준으로, 민간·공공 구분 없이 판단합니다. (아이디어 제안자 답변서)
- 담당자가 실제로 할 수 있는 일이 있는 공백만 보고합니다. 할 일이 없는 보고는 담당자에게 짐입니다.
- 도심(동)은 버스·택시로 다른 동네에 갈 수 있으므로, 몇 시간 안에 받지 못하면 생명이 위험하거나 되돌릴 수 없는 피해가 나는 공백(예: 응급환자가 응급실을 못 찾음, 임산부가 출산할 곳이 없음)이 아니면 보고하지 않고 계속 살펴봅니다. 이런 공백은 공백 심각도 '관찰'로 담당자에게 알리고, AI가 매일 다시 판단합니다.
- 읍·면은 관심 지역으로 더 자세히 재되(주민이 적어도 전체 30명, 어르신 10명부터 셈), 읍·면이라는 이유만으로 보고하지 않습니다. 지자체가 직접 운영·지정·감독하는 시설(보건지소·보건진료소, 경로당·복지관, 어린이집·돌봄 기관, 행정)은 공백의 크기로 판단합니다. 민간 가게(장보기·약국·의원 등)는 그 생활권이 끊길 때만 보고합니다: 같은 일을 할 곳이 직선 4km(걸어서 1시간) 안에 하나도 없는 마을이거나, 면(농촌 마을)에서 그 동네 장보기·진료의 중심이던 곳이 닫혀 1km 안에 대신할 곳이 없고 영향받는 주민 대부분(40% 넘게)이 어르신일 때입니다. 읍내(시가지)는 버스·차로 닿는 가게가 여럿이어서, 편의점·매점 같은 보조 가게나 2~3km 안에 대신할 곳이 있는 가게가 닫힌 것은 관찰합니다. 마을에 하나만 남은 생활 시설은 문을 닫기 전부터 살펴봅니다.
- 긴급은 법령이 보장하고 되살리기 어려운 생명·건강·돌봄 기능이 그 동네에서 사실상 끊길 때입니다. 그 밖에 보고할 공백은 주의입니다.
- 자료가 부족하거나 계산이 틀렸을 수 있으면 보수적으로 판단합니다. 그 일을 하는지 모르는 근처 가게까지 대신 갈 곳으로 봐도 공백이 남는지 봅니다.
- 호텔·병원·대학·공항·골프장·산업단지·휴게소 안 매점이나 농장 직판장처럼 주민이 다니던 곳이 아니면 보고하지 않습니다. 같은 자리에 같은 일을 하는 곳이 새로 열렸으면 보고하지 않습니다.
- 대신 갈 곳이 걸어서 30분 안에 있으면 '남은 곳이 없다'고 하지 않습니다. 사실과 다르게 쓰지 않습니다.
"""
def principles():
    if not os.path.exists(P_PRIN):
        os.makedirs(GOV, exist_ok=True); open(P_PRIN, "w", encoding="utf-8").write(DEFAULT_PRINCIPLES)
    return open(P_PRIN, encoding="utf-8").read()

# ── 5) 판단 모델 ──
# 특징: 사실을 0~1 근처의 숫자로. 이름은 화면에서 '왜 이 점수인지' 설명할 때 씀
FEATS = ["멀어지는 주민 규모", "멀어지는 어르신 규모", "더 멀어지는 거리", "읍·면", "생명 직결 정도", "법이 보장하는 기능",
         "되살리기 어려운 공공 시설", "자료 확실성", "대구에서 가장 다니기 어려운 수준", "다른 방법으로 대신할 수 있음",
         "도심의 생명 직결 아닌 공백", "담당자가 할 일 없음", "이용자가 옮겨야 하는 돌봄 기관", "생활에 꼭 필요한 정도", "주민이 찾지 못한 횟수", "멀어지는 아이 규모",
         "같은 일을 할 곳까지 먼 정도", "보조 가게(편의점·매점 등)", "읍·면 생활권이 끊김"]
# ── 생활권 원칙 (10/20 헌준님: 읍·면이라고 모든 폐업이 심각한 공백은 아님. 지자체가 할 일이 없거나 '이게 왜 주의지?' 싶은 보고는 하지 않음) ──
#  지자체가 직접 운영·지정·감독하는 기능(공공 시설, 등록해 다니는 돌봄·보육)과 생명 직결 진료는 그 자체로 판단.
#  그 밖의 민간 가게(장보기·약·의원 등)는 읍·면이라도 '생활권이 끊길 때'만 보고할 수 있음:
#   - 같은 일을 할 곳이 직선 4km(걸어서 1시간 넘음) 안에 하나도 없는 마을, 또는
#   - 면(농촌 마을)에서 그 동네 장보기·진료의 중심이던 곳(편의점·매점 같은 보조 가게가 아님)이 닫혀, 1km 안에 대신할 곳이 없고 영향받는 주민 가운데 어르신이 40% 넘을 때
#  읍내(시가지)는 버스·차로 닿는 가게가 여럿이라, 보조 가게나 2~3km 안에 대신할 곳이 있는 가게가 닫힌 것은 관찰
ISOLATE_M = 4000; ANCHOR_NEAR_M = 1000; ELDER_SHARE = 0.4
SUPPLY_AUX = {"G20405", "G20499", "G20508", "G20603", "G20604"}   # 편의점, 그 외 종합 소매(매점 등), 건강보조식품, 생수, 우유: 장보기·약의 보조 가게
AUX_FOR = {"P01.1.01", "P01.1.02", "P01.1.03", "P01.1.04", "P02.1.01", "P03.2.02"}   # 보조 가게가 '보조'인 기능 (식료품·생활소모품·일반의약품)
def elder_share(fx):
    s = fx.get("전체") or {}; n = s.get("밀려난주민") or 0
    return (s.get("밀려난_65세이상") or 0) / n if n else 0.0
def village_cut(fx):
    """읍·면에서 민간 가게가 닫혀 그 생활권이 사실상 끊기는지 (수요응답형 교통·이동장터 같은 일을 고를 수 있는 상황)"""
    if fx.get("읍면") is not True: return False
    iso = fx.get("고립_m")
    if iso is not None and iso >= ISOLATE_M: return True
    if fx.get("보조공급처"): return False
    return fx.get("생활권") == "면" and elder_share(fx) >= ELDER_SHARE and (iso is None or iso >= ANCHOR_NEAR_M)
def area_ok(fx):
    """생활권 원칙으로 보고할 수 있는 공백인지 (판단 모델·계산 검토가 함께 씀). 도심은 '생명 직결만' 원칙을 AI와 판단 모델이 따름"""
    if (fx.get("성격") or {}).get("거주형") and not fx.get("직접대응"): return False   # 거주형(고시원·기숙사): 이용자가 사는 곳 → 닫으면 주거 이전 문제, 주변 주민의 걸어서 갈 곳 공백 아님 (10/21)
    if fx.get("돌봄기관") or fx.get("직접대응") or (fx.get("성격") or {}).get("생명직결") or str(fx.get("기능", "")).startswith("G:"): return True   # G: 분만·중환자실 (생명 직결 진료)
    if fx.get("읍면") is not True: return True
    return village_cut(fx)
# 사전 지식(원칙에서 옴). 사례가 쌓이면 학습으로 바뀜
PRIOR = {"bias": -5.0, "w": [2.0, 1.5, 1.0, 1.5, 3.0, 0.8, 0.8, 1.5, 1.0, -1.0, -5.0, -4.0, 4.0, 2.0, 1.5, 2.5, 1.5, -2.0, 2.0]}
# 멀어지는 아이 규모(10/19): 보육·아동 돌봄은 아이 수로 셈. 아이 20명(가정어린이집 정원)≈0.53, 100명≈0.81 → 주민 규모·어르신 규모와 비슷한 크기로 작용
GRADE_W = {"필수": 1.0, "준필수": 0.5, "선택": 0.0}
def features(fx):
    """fx: 기능 하나의 사실 (case_facts의 항목) → 특징 벡터"""
    s = fx.get("전체") or {}; b = fx.get("넓게") or {}
    if fx.get("돌봄기관"):
        e = fx["돌봄기관"]
        big = min(1.0, math.log1p(e.get("현원") or e.get("정원") or 0) / math.log(100)); return np.array([big, big, 0, float(bool(fx.get("읍면"))), TIME_W.get(fx["성격"]["시간민감도"], .1),
                 float(bool(fx.get("공공권리"))), float(bool(fx.get("되살리기어려움"))), 1.0, 0.0, fx["성격"].get("대신_정도", 0),
                 0.0, float(not fx.get("할일있음")), 1.0, 1.0, _dem(fx), 0.0] + _area_feats(fx))
    kid = bool(s.get("아이"))   # 아이 기준 기능: 주민 전체·어르신 수 대신 아이 수로 봄
    n_all = 0 if kid else s.get("밀려난주민", 0); n65 = 0 if kid else s.get("밀려난_65세이상", 0); nk = s.get("밀려난_아이", 0) if kid else 0
    base = nk if kid else n_all; bk = "밀려난_아이" if kid else "밀려난주민"
    worse = max(0.0, ((s.get("거리_후_m") or 0) - (s.get("거리_전_m") or 0)) / 1000.0)
    conf = (b.get(bk, base) / base) if base else 0.0
    sev = (s.get("심각_아이" if kid else "심각_주민", 0) / base) if base else 0.0
    life = TIME_W.get(fx["성격"]["시간민감도"], .1)
    urban_non = float(fx.get("읍면") is False) * (1.0 - life)
    return np.array([min(1.2, math.log1p(n_all) / math.log(10000)), min(1.2, math.log1p(n65) / math.log(3000)), min(1.0, worse / 10.0),
                     float(bool(fx.get("읍면"))), life, float(bool(fx.get("공공권리"))), float(bool(fx.get("되살리기어려움"))),
                     max(0.0, min(1.0, conf)), max(0.0, min(1.0, sev)), float(fx["성격"].get("대신_정도", 0)), urban_non, float(not fx.get("할일있음")), 0.0,
                     GRADE_W.get(fx["성격"].get("등급"), 0.5), _dem(fx), min(1.2, math.log1p(nk) / math.log(300))] + _area_feats(fx))
def _area_feats(fx):
    """생활권 판단 재료: 같은 일을 할 곳까지 먼 정도(직선 4km = 1), 보조 가게인지, 읍·면 생활권이 끊기는지"""
    iso = fx.get("고립_m"); far = 0.0 if iso is None else min(1.0, iso / ISOLATE_M)
    return [far, float(bool(fx.get("보조공급처"))), float(village_cut(fx))]
def _dem(fx): return min(1.0, math.log1p(fx.get("주민수요", 0)) / math.log(20))   # 주민이 그 동네에서 그 일을 할 곳을 찾지 못한 횟수 (최근 60일)
def _sig(z): return 1.0 / (1.0 + math.exp(-z))
# 판단 모델은 세 갈래 (10/20): 보고할지(report) / 보고하지 않을 때 지켜볼 공백인지(watch: 관찰 vs 해당 없음) / 보고한다면 긴급인지(urgent)
#  report는 원칙에서 온 사전값에서 출발, watch·urgent는 경험으로만 배움 (경험이 없으면 쓰지 않고 규칙으로)
P_HEADS = {"report": P_SCORER, "watch": os.path.join(GOV, "scorer_watch.json"), "urgent": os.path.join(GOV, "scorer_urgent.json")}
class Scorer:
    def __init__(self, name="report"):
        self.name = name; self.path = P_HEADS[name]
        self.prior = PRIOR if name == "report" else {"bias": 0.0, "w": [0.0] * len(FEATS)}
        m = _jl(self.path, None)
        if not m or len(m.get("w", [])) != len(FEATS): m = {"bias": self.prior["bias"], "w": list(self.prior["w"]), "사례수": 0, "배운때": None}
        self.m = m
    def p(self, x): return _sig(self.m["bias"] + float(np.dot(self.m["w"], x)))
    def explain(self, x, k=3):
        c = np.array(self.m["w"]) * x; o = np.argsort(-np.abs(c))[:k]
        return [{"특징": FEATS[i], "방향": "올림" if c[i] > 0 else "내림", "크기": round(float(c[i]), 2)} for i in o if abs(c[i]) > 0.05]
    def train(self, rows, lam=1.0, steps=800, lr=0.1):
        """rows: [(x, y, 무게)]. 사전값 쪽으로 당기는 L2(MAP) 로지스틱 회귀. 사례가 적을 때는 거의 사전값 그대로"""
        if not rows: return self.m
        X = np.array([r[0] for r in rows]); y = np.array([r[1] for r in rows], float); sw = np.array([r[2] for r in rows], float)
        w0 = np.array(self.prior["w"], float); b0 = self.prior["bias"]; w = np.array(self.m["w"], float); b = float(self.m["bias"])
        for _ in range(steps):
            z = b + X @ w; p = 1 / (1 + np.exp(-z)); g = (p - y) * sw
            w -= lr * (X.T @ g / max(sw.sum(), 1) + lam * (w - w0) / max(len(rows), 1))
            b -= lr * (g.sum() / max(sw.sum(), 1) + lam * (b - b0) / max(len(rows), 1))
        old = list(self.m["w"])
        self.m = {"bias": round(float(b), 4), "w": [round(float(v), 4) for v in w], "사례수": len(rows), "배운때": now(),
                  "바뀐_특징": [FEATS[i] for i in np.argsort(-np.abs(w - np.array(old)))[:3] if abs(w[i] - old[i]) > 0.05]}
        _js(self.path, self.m); return self.m
    def trained(self): return (self.m.get("사례수") or 0) >= 20

# ── 4) 사례 ──
def precedents():
    if not os.path.exists(P_PREC): return []
    return [json.loads(l) for l in open(P_PREC, encoding="utf-8") if l.strip()]
LABEL = {"보고": 1, "처리 완료": 1, "해당 없음": 0, "관찰": 0}
def add_precedent(fid, label, x, summary, note="", who="담당자", ai=None):
    os.makedirs(GOV, exist_ok=True)
    row = {"때": now(), "fid": fid, "판단": label, "특징": [round(float(v), 4) for v in x], "요약": summary, "메모": note, "누가": who, "AI판단": ai}
    with open(P_PREC, "a", encoding="utf-8") as fh: fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row
def training_rows():
    """같은 곳에 여러 번 반응했으면 마지막 것만. '처리 완료'는 보고가 쓸모 있었다는 약한 신호(무게 0.5)"""
    last = {}
    for r in precedents(): last[(r["fid"], r["판단"] == "처리 완료")] = r
    rows = []
    for (fid, done), r in last.items():
        if r["판단"] not in LABEL or len(r["특징"]) != len(FEATS): continue   # 특징이 바뀌기 전 사례는 빼고 (gov_agent.refresh_precedents가 다시 잼)
        if done and (fid, False) in last: continue   # 담당자가 직접 보고 여부를 말했으면 그것을 씀
        rows.append((np.array(r["특징"], float), LABEL[r["판단"]], 0.5 if done else 1.0))
    return rows
_EXP = None
def _experience():
    global _EXP
    if _EXP is None:
        p = os.path.join(GOV, "experience.jsonl")
        _EXP = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []
        _EXP = [r for r in _EXP if len(r.get("특징", [])) == len(FEATS)]
        try:   # (10/26) 판단 근거로 보여 줄 비슷한 사례도 생활 필수 기능 사례만
            import gap_practice as _PR
            _EXP = [r for r in _EXP if _PR.in_scope_case(r)]
        except Exception: pass
    return _EXP
def similar(x, k=3):
    """특징이 비슷한 지난 사례 (AI 판단의 근거로 줌): 담당자가 판단한 사례 먼저, 그다음 에이전트가 쌓은 경험 (10/20)"""
    out = []
    P = [r for r in precedents() if r["판단"] in LABEL and len(r["특징"]) == len(FEATS) and r.get("누가") != "헌준님 예시"]
    if P:
        d = [float(np.linalg.norm(np.array(r["특징"]) - x)) for r in P]
        out += [{"누가": "담당자", "요약": P[i]["요약"], "판단": P[i]["판단"], "메모": P[i].get("메모", "")} for i in np.argsort(d)[:k] if d[i] < 1.5]
    X = _experience()
    if X and len(out) < k:
        d = np.linalg.norm(np.array([r["특징"] for r in X], float) - np.asarray(x, float), axis=1)
        for i in np.argsort(d)[:k - len(out)]:
            if d[i] < 1.0:
                r = X[i]; why = (r.get("중재관") or r["판단관"]).get("reason", "")
                out.append({"누가": "경험", "요약": r["요약"], "판단": r["판단"], "까닭": why})
    return out

# 담당자가 그 곳에 직접 정한 것 (AI 판단보다 앞섬)
def overrides(): return _jl(P_OVR, {})
def set_override(fid, label, who="담당자"):
    o = overrides()
    if label is None: o.pop(fid, None)
    else: o[fid] = {"판단": label, "때": now(), "누가": who}
    _js(P_OVR, o); return o

# ── 6) AI가 없을 때의 판단 (보수적으로) ──
REPORT_P = 0.6   # 이 점수부터 보고 (AI 판단이 없을 때)
WATCH_P = 0.05   # 이 점수부터 관찰 (그 아래는 해당 없음)
def fallback(p, fx, x=None):
    """AI가 없을 때 판단 모델로: 보고 점수가 확실할 때만 보고. 보고하지 않으면 경험으로 배운 '지켜볼 공백인지'로 관찰·해당 없음,
    보고하면 경험으로 배운 '긴급인지'로 긴급·주의 (배운 경험이 없으면 규칙으로)"""
    blocked = bool(fx.get("성격") or fx.get("전체")) and not area_ok(fx)   # 생활권 원칙: 읍·면 민간 가게인데 생활권이 끊기지 않음 → 보고하지 않음 (관찰·해당 없음은 아래에서 따로 판단)
    if blocked or p < Scorer("report").m.get("문턱", REPORT_P):   # 보고 문턱: 경험의 시험 사례로 배운 값 (없으면 0.6)
        if x is not None:
            W = Scorer("watch")
            if W.trained(): return "관찰" if W.p(x) >= W.m.get("문턱", 0.5) else "해당 없음"
        return "해당 없음" if p < WATCH_P else "관찰"
    if x is not None:
        U = Scorer("urgent")
        if U.trained(): return "긴급" if U.p(x) >= U.m.get("문턱", 0.5) and urgent_ok(fx, x) else "주의"
    s = fx.get("전체") or {}
    if (fx.get("돌봄기관") or (fx.get("되살리기어려움") and s.get("심각_주민", 0) >= 100 and fx["성격"].get("생명직결"))) and urgent_ok(fx): return "긴급"
    return "주의"

def urgent_ok(fx, x=None):
    """'긴급' 원칙 (보고 원칙: 법령이 보장하고 되살리기 어려운 생명·건강·돌봄 기능이 그 동네에서 사실상 끊길 때)을 판단 모델에도 지킴 (10/20).
    배운 사례가 적은 '긴급 머리'가 지나치게 긴급으로 기울지 않게:
     - 등록해 다니는 돌봄 기관: 같은 기관이 5km 안에 있거나 옮길 이용자가 10명 안팎이면 '끊김'이 아니라 옮길 자리의 문제 → 주의
     - 그 밖: 생명 직결 기능이거나, 읍·면에서 되살리기 어려운 공공 기능일 때만 긴급"""
    if not fx.get("성격") and not fx.get("돌봄기관") and x is not None:   # 사실 없이 특징만 있을 때 (예시 시험): 같은 원칙을 특징으로
        g = lambda name: float(x[FEATS.index(name)])
        return g("이용자가 옮겨야 하는 돌봄 기관") >= 0.5 or g("생명 직결 정도") >= 0.8 or (g("읍·면") >= 0.5 and g("되살리기 어려운 공공 시설") >= 0.5)
    e = fx.get("돌봄기관")
    if e:   # 같은 기관이 5km 안에 없고(사실상 끊김) 옮겨야 할 이용자가 10명 이상(의미 있는 규모)일 때만 긴급 (10/20)
        near = e.get("가장가까운같은기관_m"); users = e.get("현원") or e.get("정원") or 0
        return (near is None or near > 5000) and users >= 10
    pr = fx.get("성격") or {}
    return bool(pr.get("생명직결")) or (fx.get("읍면") is True and bool(fx.get("되살리기어려움")))

# ── 7) 확인 ──
NONE_CLAIM = re.compile(r"(남은|대신할|대신 갈|갈 수 있는)[^.]{0,12}(곳|약국|병원|가게|기관)[^.]{0,6}(이|가)?\s*(없|사라)")
def verify(decision, text, fxs):
    """AI가 쓴 글이 계산과 어긋나는지: 대신 갈 곳이 걸어서 30분 안에 있는데 '없다'고 하면 받지 않음"""
    near = [d.get("걷는시간_분") for f in fxs for d in (f.get("대체시설") or []) if d.get("걷는시간_분") is not None]
    if near and min(near) <= 30 and NONE_CLAIM.search(text or ""): return False, f"대신 갈 곳이 걸어서 {round(min(near))}분 거리에 있는데 '없다'고 씀"
    return True, ""
