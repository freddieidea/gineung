# 버스가 다니는 길 그물 (대구광역시 버스 노선 공간정보 2026-09-02의 링크) → data/processed/bus_net.npz
#  쓰임: 주민 모드 '가는 길' 지도에서 버스 구간을 버스가 실제로 다니는 길(버스 링크)을 따라 그림 (걷는 길로 그리던 것을 바꿈, 10/22 헌준님)
#  방법: 링크의 모양 점을 모두 마디로 삼고(이웃 점끼리 이음), 교차로에서 끊겨 있는 링크 끝끼리는 40m 안이면 이어 줌(거리 1.5배로 계산)
#  한계: 노선별 경유 순서 자료가 없어 '타는 정류장 → 내리는 정류장' 사이를 버스 길 그물의 가장 짧은 길로 그림 (실제 노선과 다를 수 있음 → 화면에 안내)
#  실행 환경: pyshp, pyproj, scipy  ·  python pipeline/build_bus_net.py [원자료폴더] [출력파일]
import sys, os, numpy as np, shapefile
from pyproj import Transformer
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
src = sys.argv[1] if len(sys.argv) > 1 else "data/raw/public/bus_shp"; out = sys.argv[2] if len(sys.argv) > 2 else "data/processed/bus_net.npz"
JOIN = 40
L = shapefile.Reader(os.path.join(src, "link_20260902"), encoding="utf-8", encodingErrors="replace")
P, eu, ev, el, ends = [], [], [], [], []
for sr in L.iterShapeRecords():
    if str(sr.record["app_ed_dt"]) != "99999999": continue
    pts = sr.shape.points
    if len(pts) < 2: continue
    i0 = len(P); P.extend(pts)
    for k in range(len(pts) - 1):
        a, b = i0 + k, i0 + k + 1; eu.append(a); ev.append(b); el.append(float(np.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])))
    ends += [i0, i0 + len(pts) - 1]
P = np.array(P); ends = np.array(ends)
pairs = cKDTree(P[ends]).query_pairs(JOIN, output_type="ndarray")
for a, b in pairs:
    u, v = int(ends[a]), int(ends[b]); d = float(np.hypot(*(P[u] - P[v])))
    eu.append(u); ev.append(v); el.append(d * 1.5 + 1)
n = len(P); M = coo_matrix((np.ones(len(eu)), (eu, ev)), shape=(n, n))
nc, lab = connected_components(M, directed=False); cnt = np.bincount(lab)
lon, lat = Transformer.from_crs(5187, 4326, always_xy=True).transform(P[:, 0], P[:, 1])
np.savez_compressed(out, lon=np.round(lon, 6), lat=np.round(lat, 6), eu=np.array(eu, np.int32), ev=np.array(ev, np.int32), el=np.array(el, np.float32), comp=lab.astype(np.int32))
print("마디", n, "이음", len(eu), "끝 잇기", len(pairs), "덩어리", nc, "가장 큰 덩어리 마디 비율", round(cnt.max() / n, 3))
