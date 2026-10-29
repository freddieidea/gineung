# 시설이 문을 닫거나 새로 생겼을 때 주민에게 미치는 영향 계산 (시설 변화 관리, engine/changes.py가 부름)
# 방법
#  - 주민이 사는 곳 격자(pipeline/build_pop_grid.py, 100m 점 44,630개에 행정동 인구를 나눔)의 점마다
#    '같은 일(세부 기능·세부 종류)을 하는 가장 가까운 시설'까지 걷는 거리를 걷는 길 지도로 잼 (여러 시설에서 한꺼번에 퍼져 나가는 최단 거리)
#  - 문 닫은 시설: 그 시설이 가장 가까웠던 점 = 영향받는 주민. 그중 기준 시간 안에 갈 곳이 있다가 없어진 점 = 새로 생긴 생활 공백
#  - 새로 생긴 시설: 그 시설이 가장 가까워진 점 = 혜택 주민. 그중 기준 시간 밖에 있다가 안으로 들어온 점 = 메워진 생활 공백
# 기준 시간: 분류표 등급 근거(public_basis)에 국가 최저기준의 '도보 N분'이 있으면 그 시간(범위면 긴 쪽), 없으면 15분
#   걷는 속도는 보통 걸음 1.0m/s (engine/walk.py와 같은 근거: 보행신호 산정 기준)
# 사람 수는 추정: 행정동 안에서 사람이 사는 곳에 고르게 산다고 본 값 (알림에 그대로 밝힘)
import os, re, numpy as np
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.csgraph import dijkstra
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MIN = 15; SPEED = 1.0; LIMIT_M = 6000
JUMP_MIN = 5   # 뚜렷한 생활 공백: 기준 시간 밖으로 밀려나면서 걷는 시간이 이만큼(분) 넘게 늘어난 주민 (15분→16분처럼 기준선 근처에서 조금 넘는 경우를 가려냄, 현장 판단)
DEFAULT_BASIS = "도보 기준이 정해지지 않은 기능은 15분 생활권으로 봄 (현장 판단, 바꿀 수 있음)"

def threshold(leaf):
    pb = str(leaf.get("public_basis") or "")
    m = [int(b or a) for a, b in re.findall(r"도보\s*(\d+)(?:\s*~\s*(\d+))?\s*분", pb)]
    if m: return max(m), f"국가 최저기준 도보 {max(m)}분 ({pb})"
    return DEFAULT_MIN, DEFAULT_BASIS

class Coverage:
    def __init__(self, walk, root=ROOT):
        self.W = walk
        z = np.load(os.path.join(root, "data", "processed", "pop_grid.npz"))
        self.lon, self.lat, self.hjd = z["lon"], z["lat"], z["hjd"].astype(int)
        self.pop, self.pop65 = z["pop"].astype(float), z["pop65"].astype(float)
        # (10/29 헌준님: 월성2동 '공백 구역'이 사실은 성서공단) 격자 인구는 동 인구를 건물 연면적에 나눈 추정이라 큰 공장 건물에도 주민이 잡힘.
        #  일반·전용공업지역 칸의 주민은 같은 동의 다른 칸(주거·상업·녹지 등)으로 비율대로 옮김 (동 인구 합은 그대로). 칸별 용도지역: data/processed/cell_zone.npy
        try:
            zp = os.path.join(root, "data", "processed", "cell_zone.npy")
            if os.path.exists(zp):
                zn = np.load(zp)
                if len(zn) == len(self.pop):
                    ind = np.isin(zn, ["일반공업지역", "전용공업지역"])
                    for arr in (self.pop, self.pop65):
                        tot = np.bincount(self.hjd, weights=arr); live = np.bincount(self.hjd, weights=np.where(ind, 0.0, arr), minlength=len(tot))
                        f = np.divide(tot, live, out=np.ones_like(tot), where=live > 0)
                        ok = live[self.hjd] > 0   # 동 전체가 공장 지대면 그대로 둠
                        arr[ind & ok] = 0.0; arr[~ind & ok] *= f[self.hjd][~ind & ok]
                    self.factory_cells = ind
        except Exception as ex: print("[격자 공장지대 보정 실패]", repr(ex)[:120])
        self.pe, self.pt, self.ps = z["edge"].astype(int), z["t"].astype(float), z["snap"].astype(float)
        # (10/20 교차검증에서 발견) 길 모양 점이 거꾸로 저장된 길(약 4%) 위의 격자 점은 t를 뒤집어야 함 — 시설(walk.py)은 이미 뒤집어 쓰는데 격자 점은 안 뒤집어,
        #  그 길 위 주민의 걷는 거리가 실제와 다르게(직선거리보다 짧게도) 계산됐음
        rev = getattr(self.W, "rev", None)
        if rev is not None: self.pt = np.where(rev[self.pe], 1.0 - self.pt, self.pt)
        self.hjd_code, self.hjd_gu, self.hjd_name = z["hjd_code"], z["hjd_gu"], z["hjd_name"]
        # 아이 인구 (10/19): 격자는 동 인구를 건물 무게로 나눈 것이므로, 동마다 '영유아·아동 비율'을 곱하면 같은 방식으로 나눈 것과 같음
        self.pop05 = np.zeros_like(self.pop); self.pop612 = np.zeros_like(self.pop); self.pop02 = np.zeros_like(self.pop); self.pop35 = np.zeros_like(self.pop)
        try:
            import pandas as pd
            P = pd.read_csv(os.path.join(root, "data", "processed", "population_hjd.csv"), dtype={"경계코드": str}).groupby("경계코드")[["인구", "영유아", "영아", "유아", "아동"]].sum()
            r = P.reindex([str(c) for c in self.hjd_code]); tot = r["인구"].replace(0, np.nan)
            self.pop05 = self.pop * (r["영유아"] / tot).fillna(0).values[self.hjd]; self.pop612 = self.pop * (r["아동"] / tot).fillna(0).values[self.hjd]
            self.pop02 = self.pop * (r["영아"] / tot).fillna(0).values[self.hjd]; self.pop35 = self.pop * (r["유아"] / tot).fillna(0).values[self.hjd]
        except Exception: pass   # 아이 인구 자료가 없으면 0 (보육 공백을 재지 못함)
        self.n = self.W.M.shape[0]
        M = self.W.M.tocoo()
        self._base = (M.row, M.col, M.data)
        L = self.W.el[self.pe]
        self._pu, self._pv, self._pL = self.W.eu[self.pe], self.W.ev[self.pe], L
        order = np.argsort(self.pe, kind="stable"); self._by_edge_order = order
        self._edges_sorted = self.pe[order]

    def _points_on_edge(self, e):
        a = np.searchsorted(self._edges_sorted, e, "left"); b = np.searchsorted(self._edges_sorted, e, "right")
        return self._by_edge_order[a:b]

    # 시설들(길 위 지점 목록) → 격자 점마다 가장 가까운 시설까지 걷는 거리(m). 길로 이어지지 않거나 limit을 넘으면 inf
    def dist(self, snaps, limit=LIMIT_M):
        out = np.full(len(self.lon), np.inf)
        snaps = [s for s in snaps if s is not None]
        if not snaps: return out
        e = np.array([s[0] for s in snaps], int); t = np.array([s[1] for s in snaps]); d0 = np.array([s[2] for s in snaps])
        L = self.W.el[e]; u = self.W.eu[e]; v = self.W.ev[e]
        tgt = np.r_[u, v]; w = np.r_[t * L + d0, (1 - t) * L + d0] + 1e-6
        best = {}
        for a, b in zip(tgt.tolist(), w.tolist()):
            if b < best.get(a, np.inf): best[a] = b
        r0, c0, w0 = self._base; S = self.n
        G = csr_matrix((np.r_[w0, list(best.values())], (np.r_[r0, np.full(len(best), S)], np.r_[c0, list(best.keys())])), shape=(S + 1, S + 1))
        D = dijkstra(G, directed=True, indices=S, limit=limit)
        out = np.minimum(D[self._pu] + self.pt * self._pL, D[self._pv] + (1 - self.pt) * self._pL) + self.ps
        for k in range(len(e)):   # 같은 길 위에 있는 점은 교차점을 거치지 않고 바로
            idx = self._points_on_edge(e[k])
            if len(idx): out[idx] = np.minimum(out[idx], np.abs(self.pt[idx] - t[k]) * L[k] + d0[k] + self.ps[idx])
        out[out > limit] = np.inf
        return out

    @staticmethod
    def _wmedian(x, w):
        if len(x) == 0 or w.sum() == 0: return None
        o = np.argsort(x); x, w = x[o], w[o]; c = np.cumsum(w)
        return float(x[np.searchsorted(c, c[-1] / 2)])

    # 문 닫음(mode="closed") 또는 새로 생김(mode="opened")의 영향
    # others: 바뀐 시설을 뺀 '같은 일을 하는 시설'의 길 위 지점들, one: 바뀐 시설의 길 위 지점, thr_min: 기준 시간(분)
    def impact(self, others, one, thr_min, mode="closed", gu=None):
        thr = thr_min * 60 * SPEED
        rest = self.dist(others); own = self.dist([one])
        with_one = np.minimum(rest, own)
        sel = np.ones(len(self.lon), bool) if gu is None else (self.hjd_gu[self.hjd] == gu)   # 종량제 봉투처럼 구·군 안에서만 쓰는 것
        near = sel & np.isfinite(own) & (own < rest)                      # 이 시설이 가장 가까운(가까웠던/가까워진) 주민
        if mode == "closed": crossed = near & (with_one <= thr) & (rest > thr)    # 기준 안 → 밖
        else: crossed = near & (rest > thr) & (with_one <= thr)                   # 기준 밖 → 안
        before, after = (with_one, rest) if mode == "closed" else (rest, with_one)
        with np.errstate(invalid="ignore"): clear = crossed & (np.abs(after - before) > JUMP_MIN * 60 * SPEED)   # 무한대(6km 넘음)도 뚜렷한 공백
        def mins(m): return None if m is None or not np.isfinite(m) else round(m / SPEED / 60, 1)
        res = {"기준_분": thr_min, "가까운주민": round(float(self.pop[near].sum())), "가까운주민_65세이상": round(float(self.pop65[near].sum())),
               "공백변화주민": round(float(self.pop[crossed].sum())), "공백변화주민_65세이상": round(float(self.pop65[crossed].sum())),
               "걷는시간_전_중앙값": mins(self._wmedian(before[near], self.pop[near])) if near.any() else None,
               "걷는시간_후_중앙값": mins(self._wmedian(np.where(np.isfinite(after[near]), after[near], LIMIT_M + 1), self.pop[near])) if near.any() else None,
               "뚜렷한공백주민": round(float(self.pop[clear].sum())), "뚜렷한공백주민_65세이상": round(float(self.pop65[clear].sum())),
               "뚜렷한공백_걷는시간_전": mins(self._wmedian(before[clear], self.pop[clear])) if clear.any() else None,
               "뚜렷한공백_걷는시간_후": mins(self._wmedian(np.where(np.isfinite(after[clear]), after[clear], LIMIT_M + 1), self.pop[clear])) if clear.any() else None,
               "후_6km넘음_주민": round(float(self.pop[near & ~np.isfinite(after)].sum())),
               "공백주민_전": round(float(self.pop[sel & (before > thr)].sum())) if gu else None,
               "행정동": []}
        if near.any():
            hs = np.unique(self.hjd[near])
            rows = []
            for h in hs:
                m = near & (self.hjd == h); c = crossed & (self.hjd == h)
                rows.append({"구군": str(self.hjd_gu[h]), "행정동": str(self.hjd_name[h]), "주민": round(float(self.pop[m].sum())),
                             "65세이상": round(float(self.pop65[m].sum())), "공백변화": round(float(self.pop[c].sum())), "공백변화_65세이상": round(float(self.pop65[c].sum())),
                             "뚜렷한공백": round(float(self.pop[c & clear].sum())), "뚜렷한공백_65세이상": round(float(self.pop65[c & clear].sum()))})
            res["행정동"] = sorted([r for r in rows if r["주민"] > 0], key=lambda r: (-r["공백변화"], -r["주민"]))
        return res
