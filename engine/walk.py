# 걷는 거리·시간 계산 (OpenStreetMap 걷는 길, pipeline/build_walk.py가 만든 자료)
# - 주민 위치와 시설을 각각 '길 위의 가장 가까운 지점'에 붙이고, 그 사이를 실제 길로 따라간 거리 + 길까지의 직선거리를 더함
#   (길까지 직선 구간을 더하므로 걷는 거리는 언제나 직선거리 이상)
# - 걷는 속도는 대화에서 확인한 주민의 걸음에 따라 (근거: SPEED_SRC)
import os, numpy as np, pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KX = np.cos(np.radians(35.87)) * 111320; KY = 110540
SPEED = {"보통": 1.00, "천천히": 0.85, "아주 천천히": 0.70}   # m/s. 걷는 시간을 실제보다 짧게 말하지 않도록 보수적으로 잡음 (네이버지도 도보 시간과 비교해 확인: 3.2km 51분 ≈ 1.05m/s)
SPEED_SRC = {
 "보통": "일반 횡단보도 보행신호 산정 기준 1.0m/s (경찰청 교통신호기 설치·관리 매뉴얼). 실측 평균은 65세 이상 1.13m/s, 64세 이하 1.29m/s (박순용 외, 2019)",
 "천천히": "65세 이상 하위 15% 보행속도 0.85m/s (같은 연구)",
 "아주 천천히": "교통약자 보호구역 보행신호 산정 기준 0.7m/s (경찰청 교통신호기 설치·관리 매뉴얼). 보행보조기·휠체어 이용 등",
}
FAR_SNAP = 150  # 길까지 이보다 멀면 '길 정보 부족'

class Walk:
    def __init__(self, root=ROOT):
        z = np.load(os.path.join(root, "data", "processed", "walk_daegu.npz"))
        self.eu, self.ev, self.el = z["eu"], z["ev"], z["el"]
        self.sx, self.sy, self.se, self.st = z["sx"], z["sy"], z["se"], z["st"]
        n = len(z["x"])
        self.M = coo_matrix((np.r_[self.el, self.el], (np.r_[self.eu, self.ev], np.r_[self.ev, self.eu])), shape=(n, n)).tocsr()
        self.T = cKDTree(np.c_[self.sx * KX, self.sy * KY])
        self._x, self._y = z["x"], z["y"]
        # 길 모양 점이 u→v와 거꾸로 저장된 길(약 4%) 찾기: 첫 점이 v에, 끝 점이 u에 더 가까움 (10/16 경로 그리기 중 발견)
        o = np.lexsort((self.st, self.se)); ses = self.se[o]; n_e = len(self.el)
        self._eg_order = o; self._eg_start = np.searchsorted(ses, np.arange(n_e)); self._eg_end = np.searchsorted(ses, np.arange(n_e), side="right")
        has = self._eg_end > self._eg_start; fi = o[np.minimum(self._eg_start, len(o) - 1)]; la = o[np.maximum(self._eg_end - 1, 0)]
        ux, uy, vx, vy = self._x[self.eu], self._y[self.eu], self._x[self.ev], self._y[self.ev]
        d = lambda i, X, Y: (self.sx[i] - X) ** 2 + (self.sy[i] - Y) ** 2
        self.rev = has & (d(fi, vx, vy) < d(fi, ux, uy)) & (d(la, ux, uy) < d(la, vx, vy))
        S = pd.read_csv(os.path.join(root, "data", "processed", "facility_walk.csv"), dtype={"fid": str})
        tt = [1 - t if self.rev[e] else t for e, t in zip(S["edge"].astype(int), S["t"].astype(float))]
        self.snap = dict(zip(S["fid"], zip(S["edge"].astype(int), tt, S["snap_m"].astype(float))))
        self._cache = {}

    def _snap_point(self, lon, lat):
        d, j = self.T.query([lon * KX, lat * KY]); e = int(self.se[j]); t = float(self.st[j])
        return e, (1 - t if self.rev[e] else t), float(d)   # t는 언제나 u쪽 0, v쪽 1

    def _from(self, lon, lat):
        key = (round(lon, 7), round(lat, 7))
        if key not in self._cache:
            e, t, d0 = self._snap_point(lon, lat); L = self.el[e]
            du = dijkstra(self.M, directed=False, indices=int(self.eu[e])); dv = dijkstra(self.M, directed=False, indices=int(self.ev[e]))
            node = np.minimum(du + t * L, dv + (1 - t) * L)   # 주민이 붙은 길 지점에서 모든 교차점까지
            self._cache = {key: (e, t, d0, node)}             # 마지막 출발점 하나만 기억
        return self._cache[key]

    # 주민 위치 → 시설들까지 걷는 거리(m). 길로 이어지지 않거나 max_m을 넘으면 None
    def distances(self, lon, lat, fids, max_m=8000):
        e0, t0, d0, node = self._from(lon, lat); out = {}
        for f in fids:
            if f not in self.snap: out[f] = None; continue
            e, t, d1 = self.snap[f]; L = self.el[e]
            net = min(node[self.eu[e]] + t * L, node[self.ev[e]] + (1 - t) * L)
            if e == e0: net = min(net, abs(t - t0) * L)        # 같은 길 위
            m = float(net) + d0 + d1
            out[f] = m if np.isfinite(m) and m <= max_m else None
        return out

    # 주민 위치 → 데이터베이스에 없는 지점들(예: 실시간 검색한 은행)까지 걷는 거리(m). 지점을 그 자리에서 길에 붙여 같은 방식으로 계산
    def distances_to_points(self, lon, lat, pts, max_m=8000):
        e0, t0, d0, node = self._from(lon, lat); out = {}
        for key, plon, plat in pts:
            e, t, d1 = self._snap_point(plon, plat); L = self.el[e]
            net = min(node[self.eu[e]] + t * L, node[self.ev[e]] + (1 - t) * L)
            if e == e0: net = min(net, abs(t - t0) * L)
            m = float(net) + d0 + d1
            out[key] = m if np.isfinite(m) and m <= max_m and d1 <= FAR_SNAP else None
        return out

    # 걷는 길 모양 (지도에 그리기용, 10/16 헌준님: 네이버·카카오 지도처럼 그림으로). 돌려줌: [[위도, 경도], ...] 또는 None
    def _edge_geom(self, e):
        if not hasattr(self, "_pair"):
            self._pair = {(min(u, v), max(u, v)): i for i, (u, v) in enumerate(zip(self.eu.tolist(), self.ev.tolist()))}
        idx = self._eg_order[self._eg_start[e]:self._eg_end[e]]
        g = [(float(self.st[i]), float(self.sx[i]), float(self.sy[i])) for i in idx]
        return [(1 - t, x, y) for t, x, y in reversed(g)] if self.rev[e] else g
    def _along(self, e, t_from, t_to):
        """길 e 위에서 t_from → t_to 사이의 점들 (u쪽 0, v쪽 1)"""
        g = self._edge_geom(e); ends = {0.0: (float(self._x[self.eu[e]]), float(self._y[self.eu[e]])), 1.0: (float(self._x[self.ev[e]]), float(self._y[self.ev[e]]))}
        pts = [(0.0, *ends[0.0])] + [(t, x, y) for t, x, y in g] + [(1.0, *ends[1.0])]
        def at(t):   # 길 위 t 자리 (앞뒤 점 사이를 이어서 구함: 긴 길은 점이 듬성듬성해서)
            for (ta, xa, ya), (tb, xb, yb) in zip(pts, pts[1:]):
                if ta <= t <= tb:
                    r = 0 if tb == ta else (t - ta) / (tb - ta); return (xa + (xb - xa) * r, ya + (yb - ya) * r)
            return pts[-1][1:]
        lo, hi = sorted((t_from, t_to)); sel = [at(lo)] + [(x, y) for t, x, y in pts if lo < t < hi] + [at(hi)]
        return sel if t_from <= t_to else sel[::-1]
    def path(self, lon1, lat1, lon2, lat2, max_m=4000):
        try:
            e0, t0, _ = self._snap_point(lon1, lat1); e1, t1, _ = self._snap_point(lon2, lat2)
            self._edge_geom(e0)
            if e0 == e1:
                mid = self._along(e0, t0, t1); return [[lat1, lon1]] + [[y, x] for x, y in mid] + [[lat2, lon2]]
            L0, L1 = self.el[e0], self.el[e1]; best = None
            for a, off_a, ta in ((int(self.eu[e0]), t0 * L0, 0.0), (int(self.ev[e0]), (1 - t0) * L0, 1.0)):
                dist, pred = dijkstra(self.M, directed=False, indices=a, return_predecessors=True, limit=max_m)
                for b, off_b, tb in ((int(self.eu[e1]), t1 * L1, 0.0), (int(self.ev[e1]), (1 - t1) * L1, 1.0)):
                    tot = off_a + dist[b] + off_b
                    if np.isfinite(tot) and (best is None or tot < best[0]): best = (tot, a, ta, b, tb, pred)
            if best is None: return None
            _, a, ta, b, tb, pred = best
            nodes = [b]
            while nodes[-1] != a and pred[nodes[-1]] >= 0: nodes.append(int(pred[nodes[-1]]))
            nodes = nodes[::-1]
            pts = self._along(e0, t0, ta)
            for u, v in zip(nodes, nodes[1:]):
                e = self._pair.get((min(u, v), max(u, v)))
                if e is None: pts.append((float(self._x[v]), float(self._y[v]))); continue
                pts += self._along(e, 0.0, 1.0) if int(self.eu[e]) == u else self._along(e, 1.0, 0.0)
            pts += self._along(e1, tb, t1)
            out = [[lat1, lon1]] + [[round(y, 6), round(x, 6)] for x, y in pts] + [[lat2, lon2]]
            return [p for i, p in enumerate(out) if i == 0 or p != out[i - 1]]
        except Exception:
            return None

    @staticmethod
    def minutes(m, speed="보통"):
        return None if m is None else round(m / SPEED[speed] / 60, 1)
