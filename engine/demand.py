# 주민이 찾지 못한 곳 (10/19): 주민 대화에서 걸어갈 만한 곳을 찾지 못하면 동네와 기능만 남김 (이름·말씀·정확한 위치는 남기지 않음)
#  주민에게 한 약속("가까운 곳이 없다는 걸 구청·군청에 알려 둘게요")을 지키고, 지자체 판단 에이전트가 '주민 쪽 신호'로 씀
#  (관찰 중인 공백 근처에서 주민이 자꾸 찾지 못하면 판단 점수가 올라감 → gap_agent '주민이 찾지 못한 횟수')
import os, sys, json, datetime, threading
from coords import Areas
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "data", "gov", "demand.jsonl")
_lock = threading.Lock(); _A = None
def _areas():
    global _A
    if _A is None:
        G = json.load(open(os.path.join(ROOT, "data", "raw", "boundary", "daegu_hjd_20260701.geojson"), encoding="utf-8"))["features"]
        _A = (Areas(G), [(g["properties"]["sggnm"], g["properties"]["adm_nm"].split()[-1]) for g in G])
    return _A
def _today():   # 영상 시연 서버 전용 (10/24): GINEUNG_DEMO_NOW가 있으면 그 날짜
    d = os.environ.get("GINEUNG_DEMO_NOW")
    try: return datetime.date.fromisoformat(d[:10]).isoformat() if d else datetime.date.today().isoformat()
    except Exception: return datetime.date.today().isoformat()
def where(lon, lat):
    A, names = _areas(); i = A.find(float(lon), float(lat))
    return names[i] if i is not None else (None, None)
def log(lid, name, kind, lon, lat, mode, why):
    if os.path.basename(sys.argv[0] or "").startswith(("test_", "try_", "talk_check", "want_check", "check5", "rec")): return None   # 시험 대화는 남기지 않음
    gu, dong = where(lon, lat)
    if not dong: return None
    row = {"날짜": _today(), "기능": lid, "기능이름": name, "종류": kind, "구군": gu, "행정동": dong, "이동": mode, "사유": why}
    with _lock:
        os.makedirs(os.path.dirname(P), exist_ok=True)
        with open(P, "a", encoding="utf-8") as fh: fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row
def recent(days=30):
    if not os.path.exists(P): return []
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    return [r for r in (json.loads(l) for l in open(P, encoding="utf-8") if l.strip()) if r["날짜"] >= since]
def summary(days=30):
    """동네·기능별로 모음 (많은 순)"""
    g = {}
    for r in recent(days):
        k = (r["구군"], r["행정동"], r["기능"]); x = g.setdefault(k, {"구군": r["구군"], "행정동": r["행정동"], "기능": r["기능"], "기능이름": r["기능이름"], "종류": set(), "건수": 0, "마지막": r["날짜"]})
        x["건수"] += 1; x["마지막"] = max(x["마지막"], r["날짜"])
        if r.get("종류"): x["종류"].add(r["종류"])
    out = [dict(v, 종류=sorted(v["종류"])) for v in g.values()]
    return sorted(out, key=lambda v: (-v["건수"], v["마지막"]), reverse=False)
def count(dong, lid, days=60):
    return sum(1 for r in recent(days) if r["행정동"] == dong and r["기능"] == lid)

# 주민 이용 결과 (10/20, 아이디어 제안자 답변서 6번 '결과 피드백'): 추천을 받은 뒤 '다녀옴' / '맞는 곳 없음'. 동네·기능·결과만 (이름·말씀·위치 없음)
#  '맞는 곳 없음'은 찾지 못한 것과 같은 신호라 주민 수요에도 남김 → 지자체 판단('주민이 찾지 못한 횟수')과 기능 공백 현황에 쓰임
PF = os.path.join(ROOT, "data", "gov", "use_result.jsonl")
RESULTS = ("다녀옴", "맞는 곳 없음")
def use_result(lid, name, kind, lon, lat, result):
    if result not in RESULTS: return None
    if os.path.basename(sys.argv[0] or "").startswith(("test_", "try_", "talk_check", "want_check", "check5", "rec")): return None
    gu, dong = where(lon, lat)
    if not dong: return None
    row = {"날짜": _today(), "기능": lid, "기능이름": name, "종류": kind, "구군": gu, "행정동": dong, "결과": result}
    with _lock:
        os.makedirs(os.path.dirname(PF), exist_ok=True)
        with open(PF, "a", encoding="utf-8") as fh: fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if result == "맞는 곳 없음": log(lid, name, kind, lon, lat, "", "추천을 받았지만 맞는 곳 없음")
    return row
def use_summary(days=30):
    """구·군 → {다녀옴, 맞는 곳 없음, 기능별}"""
    if not os.path.exists(PF): return {}
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat(); out = {}
    for r in (json.loads(l) for l in open(PF, encoding="utf-8") if l.strip()):
        if r["날짜"] < since: continue
        g = out.setdefault(r["구군"], {"다녀옴": 0, "맞는 곳 없음": 0, "기능": {}})
        g[r["결과"]] += 1; f = g["기능"].setdefault(r["기능이름"], {"다녀옴": 0, "맞는 곳 없음": 0}); f[r["결과"]] += 1
    return out
