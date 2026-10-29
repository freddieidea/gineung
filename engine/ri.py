# 읍·면의 마을(리) 이름 (10/29 헌준님: 엑셀에서 같은 읍·면이 리가 달라 두 줄인데 숫자가 달라 헷갈림)
#  상가정보의 지번주소에서 '○○리'를 읽어 둠. 시설은 상가업소번호로 바로, 그 밖의 곳(공공시설·공백 구역 밀집 지점)은 같은 읍·면의 가장 가까운 가게 주소로
import os, re, csv, json, math
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "raw", "소상공인시장진흥공단_상가(상권)정보_대구_202606.csv")
CACHE = os.path.join(ROOT, "data", "processed", "ri_points.json")
_P = None
def _load():
    global _P
    if _P is not None: return _P
    if os.path.exists(CACHE) and os.path.getmtime(CACHE) >= os.path.getmtime(SRC):
        _P = json.load(open(CACHE, encoding="utf-8")); return _P
    by_id, pts = {}, {}
    with open(SRC, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m = re.search(r"(\S+[읍면]) (\S+리) ", r.get("지번주소") or "")
            if not m: continue
            by_id[r["상가업소번호"]] = m[2]
            try: pts.setdefault(m[1], []).append((round(float(r["경도"]), 5), round(float(r["위도"]), 5), m[2]))
            except (TypeError, ValueError): pass
    _P = {"id": by_id, "pts": pts}
    json.dump(_P, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    return _P
def of(dong=None, fid=None, lon=None, lat=None):
    """읍·면이면 '○○리'(가까운 가게 주소 기준이면 '○○리 일대'), 동이면 None"""
    if not dong or not str(dong).endswith(("읍", "면")): return None
    P = _load()
    if fid and str(fid).startswith("S:") and str(fid)[2:] in P["id"]: return P["id"][str(fid)[2:]]
    try: lon, lat = float(lon), float(lat)
    except (TypeError, ValueError): return None
    best, bd = None, 1e18
    for x, y, ri in P["pts"].get(str(dong), []):
        d = ((x - lon) * 90300) ** 2 + ((y - lat) * 110540) ** 2
        if d < bd: best, bd = ri, d
    return (best + " 일대") if best and bd < 1500 ** 2 else None
def label(dong, ri):
    return f"{dong} {ri}" if ri else (dong or "")
