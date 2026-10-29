# 좌표 → 행정동 이름 (행정동 경계 2026-07, 지자체 에이전트·주민 대화가 함께 씀)
#  10/20: 추가 설치 없이 동작하도록 numpy만 씀 (헌준님 컴퓨터 파이썬에는 shapely가 없음). 결과는 shapely 판정과 같음을 확인함
#  점이 경계 안에 있으면 그 동, 어느 경계에도 안 들어가면(강·경계선 위 등) 가장 가까운 경계의 동
import os, json
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DONG = None

def _load():
    G = json.load(open(os.path.join(ROOT, "data", "raw", "boundary", "daegu_hjd_20260701.geojson"), encoding="utf-8"))["features"]
    out = []
    for f in G:
        g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        rings = [np.asarray(r, dtype=float)[:, :2] for p in polys for r in p]
        allp = np.vstack(rings)
        out.append((f["properties"]["adm_nm"].split()[-1], rings, allp.min(0), allp.max(0)))
    return out

def _inside(x, y, rings):
    """짝홀 규칙 (구멍이 있는 경계·여러 조각 경계 모두 맞음)"""
    c = False
    for r in rings:
        x1, y1 = r[:, 0], r[:, 1]; x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
        m = (y1 > y) != (y2 > y)
        if m.any():
            xs = x1[m] + (y - y1[m]) * (x2[m] - x1[m]) / (y2[m] - y1[m])
            if (np.count_nonzero(xs > x) % 2) == 1: c = not c
    return c

def _dist(x, y, rings):
    """점에서 경계선까지 가장 짧은 거리 (경위도 단위, 가까운 동 찾기용)"""
    best = np.inf
    for r in rings:
        a = r; b = np.roll(r, -1, axis=0); d = b - a; p = np.array([x, y])
        L = (d ** 2).sum(1); t = np.clip(((p - a) * d).sum(1) / np.where(L == 0, 1, L), 0, 1)
        q = a + d * t[:, None]; best = min(best, float(np.sqrt(((q - p) ** 2).sum(1)).min()))
    return best

def dong_at(lon, lat):
    global _DONG
    try: lon, lat = float(lon), float(lat)
    except Exception: return ""
    if lon != lon or lat != lat: return ""
    try:
        if _DONG is None: _DONG = _load()
    except Exception: return ""
    for name, rings, lo, hi in _DONG:
        if lo[0] <= lon <= hi[0] and lo[1] <= lat <= hi[1] and _inside(lon, lat, rings): return name
    near = [(_dist(lon, lat, rings), name) for name, rings, lo, hi in _DONG
            if lo[0] - 0.02 <= lon <= hi[0] + 0.02 and lo[1] - 0.02 <= lat <= hi[1] + 0.02]
    return min(near)[1] if near else ""
