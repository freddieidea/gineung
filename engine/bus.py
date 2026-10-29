# 버스·지하철 한 번에 가는지 보기 (10/16): "○○ 정류장에서 내려 걸어서 2분"만 알려 주던 것을, 실제 노선으로 "410번 한 번에 / 갈아타야 함"까지
#  자료: 대구광역시 버스 노선 공간정보 2026-09-02(정류소마다 다니는 노선, data/processed/bus_stops.csv) + 정류소별·노선별 평균 배차 간격 2025-11-14(평일)
#        도시철도역은 역 이름의 호선(1·2·3호선)
#  방법: 출발지 가까운 정류장(걸어서 10분 안)과 도착지 가까운 정류장(걸어서 8분 안) 사이에 같은 노선이 있으면 '한 번에'
#        걸리는 시간 = 타는 곳까지 걷기 + 기다리기(배차 간격의 절반, 모르면 10분) + 타고 가기(곧은 거리 × 1.35 ÷ 시속 15km) + 내려서 걷기
#  한계: 정류장 순서 자료가 없어 방향은 보지 않음(같은 노선이 두 정류장을 모두 지나면 한 번에 간다고 봄. 길 건너 반대 방향 정류장도 함께 봐서 대부분 맞음)
#        시간은 어림값이라 화면에 '약'으로 보여 주고, 정확한 시간은 카카오맵 길찾기로 안내
import os, glob, io, math, re
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def hav(lon1, lat1, lon2, lat2):
    R = 6371000; p1, p2 = math.radians(lat1), math.radians(lat2); dp = p2 - p1; dl = math.radians(lon2 - lon1)
    return 2 * R * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))
class Bus:
    def __init__(self, engine):
        self.E = engine
        B = pd.read_csv(os.path.join(ROOT, "data", "processed", "bus_stops.csv"), dtype=str)
        B = B[B["경도"].notna() & (pd.to_numeric(B["평일운행횟수"], errors="coerce").fillna(0) > 0)]
        self.stops = []
        for r in B.itertuples():
            routes = {x.strip() for x in str(r.노선 or "").split(",") if x.strip()}
            if routes: self.stops.append((str(r.정류소ID), str(r.정류소), float(r.경도), float(r.위도), routes))
        F = engine.F; S = F[F["업종코드"] == "PUB:도시철도역"]
        for fid, r in S.iterrows():
            m = re.search(r"(\d)호선", fid + str(r.get("상호", "")))
            if m and r["경도"] == r["경도"]: self.stops.append((fid, str(r["상호"]).split(" (")[0], float(r["경도"]), float(r["위도"]), {f"{m.group(1)}호선"}))
        p = glob.glob(os.path.join(ROOT, "data", "raw", "public", "버스__15060936__*.csv"))
        self.head = {}
        if p:
            raw = open(p[0], "rb").read()
            for enc in ("utf-8-sig", "cp949"):
                try: t = raw.decode(enc); break
                except Exception: pass
            H = pd.read_csv(io.StringIO(t), dtype=str); H.columns = [c.replace("﻿", "").strip() for c in H.columns]
            H = H[H["시간표유형"] == "평일"]; H["간격"] = pd.to_numeric(H["평균배차간격"], errors="coerce")
            for (sid, rt), v in H.groupby(["정류소ID", "노선"])["간격"].min().items():
                if v == v: self.head[(str(sid), str(rt).strip())] = int(v)
        self.grid = {}
        for i, s in enumerate(self.stops): self.grid.setdefault((round(s[2] / 0.005), round(s[3] / 0.005)), []).append(i)
    def _near(self, lon, lat, within):
        gx, gy = round(lon / 0.005), round(lat / 0.005); out = []
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                for i in self.grid.get((gx + dx, gy + dy), []):
                    s = self.stops[i]; d = hav(lon, lat, s[2], s[3])
                    if d <= within: out.append((d, s))
        return sorted(out, key=lambda x: x[0])
    def origin(self, lon, lat, speed="보통", within=700):
        """출발지에서 걸어서 갈 정류장들 (실제 걷는 길로 잰 거리)"""
        cand = self._near(lon, lat, within)[:14]
        if not cand: return []
        W = self.E.walk.distances_to_points(lon, lat, [(s[0], s[2], s[3]) for _, s in cand], max_m=within * 2)
        return [(self.E.walk.minutes(W[s[0]], speed), s) for _, s in cand if W.get(s[0]) is not None and W[s[0]] <= within * 1.4]
    def plan(self, O, lon, lat, speed="보통", within=550):
        """O: origin()의 결과. 도착지까지 한 번에 가는 가장 빠른 길. 없으면 None"""
        D = [(self.E.walk.minutes(d * 1.3, speed), s) for d, s in self._near(lon, lat, within)[:14]]
        best = None
        for wo, so in O:
            for wd, sd in D:
                if so[0] == sd[0]: continue
                common = so[4] & sd[4]
                if not common: continue
                dist = hav(so[2], so[3], sd[2], sd[3])
                if dist < 500: continue   # 너무 가까우면 버스를 탈 일이 아님
                subway = any(r.endswith("호선") for r in common)
                waits = {r: self.head.get((so[0], r)) for r in common}
                rt = min(common, key=lambda r: (waits[r] or 99))
                wait = 3 if subway else min(15, (waits[rt] or 20) / 2)
                ride = dist * 1.35 / (550 if subway else 250)   # 지하철 약 시속 33km, 버스 약 시속 15km
                tot = wo + wait + ride + wd
                if best is None or tot < best["예상_분"]:
                    rts = sorted(common, key=lambda r: (waits[r] or 99))[:3]
                    best = {"노선": rts, "지하철": subway, "타는곳": so[1], "타는곳_분": round(wo), "내리는곳": sd[1], "내려서_분": max(1, round(wd)),
                            "배차_분": None if subway else waits[rt], "예상_분": round(tot), "타는_분_원값": wo, "타고가는_분": round(ride, 1),
                            "타는곳_좌표": [so[3], so[2]], "내리는곳_좌표": [sd[3], sd[2]]}
        return best

    # ── 한 번 갈아타는 길 (10/25 헌준님: 어떤 순서로 물어도 버스를 물으면 노선과 경로를 카카오맵처럼) ──
    #  방법: 출발 정류장(걸어서 10분 안)의 노선 r1과 도착 정류장(걸어서 8분 안)의 노선 r2가 같은 정류장(또는 걸어서 150m 안 정류장)에서 만나면 갈아탐
    #        걸리는 시간 = 타는 곳까지 걷기 + 기다리기 + 타고 가기 + 갈아타며 걷기·기다리기 + 타고 가기 + 내려서 걷기 (plan과 같은 어림)
    #  한계: 노선 경유 순서 자료가 없어 방향은 보지 않음 → 크게 돌아가는 조합(곧은 거리의 1.5배+1.5km 넘음)은 버림
    def _xfer_index(self, xfer_m=150):
        if getattr(self, "_ri", None) is not None: return
        self._ri = {}
        for i, s in enumerate(self.stops):
            for r in s[4]: self._ri.setdefault(r, []).append(i)
        self._near_r = []   # 정류장마다 걸어서 150m 안 정류장의 노선 (갈아탈 수 있는 노선)
        for i, s in enumerate(self.stops):
            rs = set(s[4])
            for d, t in self._near(s[2], s[3], xfer_m): rs |= t[4]
            self._near_r.append(rs)
    def plan_transfer(self, O, lon, lat, speed="보통", within=550, xfer_m=150):
        """O: origin()의 결과. 한 번 갈아타서 가는 가장 빠른 길. 없으면 None"""
        self._xfer_index(xfer_m)
        D = [(self.E.walk.minutes(d * 1.3, speed), s) for d, s in self._near(lon, lat, within)[:10]]
        if not O or not D: return None
        Ro, Rd = {}, {}
        for wo, so in O:
            for r in so[4]:
                if r not in Ro or wo < Ro[r][0]: Ro[r] = (wo, so)
        for wd, sd in D:
            for r in sd[4]:
                if r not in Rd or wd < Rd[r][0]: Rd[r] = (wd, sd)
        sub = lambda r: r.endswith("호선")
        wait = lambda sid, r: 3 if sub(r) else min(15, (self.head.get((sid, r)) or 20) / 2)
        speed_m = lambda r: 550 if sub(r) else 250
        best = None
        for r1, (wo, so) in Ro.items():
            for i in self._ri.get(r1, []):
                t1 = self.stops[i]
                if t1[0] == so[0]: continue
                d1 = hav(so[2], so[3], t1[2], t1[3])
                if d1 < 400: continue
                for r2 in self._near_r[i] & set(Rd):
                    if r2 == r1 or r2 in so[4]: continue
                    wd, sd = Rd[r2]
                    if r1 in sd[4]: continue   # 한 번에 가는 노선이 있는 경우는 plan()이 맡음
                    d2 = hav(t1[2], t1[3], sd[2], sd[3])
                    if d2 < 400 or d1 + d2 > hav(so[2], so[3], sd[2], sd[3]) * 1.5 + 1500: continue
                    tot = wo + wait(so[0], r1) + d1 * 1.35 / speed_m(r1) + 2 + wait(t1[0], r2) + d2 * 1.35 / speed_m(r2) + wd
                    if best is None or tot < best[0]: best = (tot, wo, so, r1, i, r2, wd, sd, d1, d2)
        if best is None: return None
        tot, wo, so, r1, i, r2, wd, sd, d1, d2 = best
        t1 = self.stops[i]
        t2 = t1 if r2 in t1[4] else min((t for d, t in self._near(t1[2], t1[3], xfer_m) if r2 in t[4]), key=lambda t: hav(t1[2], t1[3], t[2], t[3]))
        xw = 0 if t2[0] == t1[0] else max(1, round(self.E.walk.minutes(hav(t1[2], t1[3], t2[2], t2[3]) * 1.3, speed)))
        rts = lambda a, b, r: sorted(a[4] & b[4], key=lambda x: (x != r, self.head.get((a[0], x)) or 99))[:3]
        leg = lambda a, b, r, d: {"노선": rts(a, b, r), "지하철": sub(r), "탈곳": a[1], "내릴곳": b[1], "배차_분": None if sub(r) else self.head.get((a[0], r)),
                                  "타고가는_분": round(d * 1.35 / speed_m(r), 1), "탈곳_좌표": [a[3], a[2]], "내릴곳_좌표": [b[3], b[2]]}
        return {"갈아타기": True, "구간": [leg(so, t1, r1, d1), leg(t2, sd, r2, d2)], "갈아타며_걷기_분": xw,
                "타는곳": so[1], "타는곳_분": round(wo), "갈아타는곳": t2[1], "내리는곳": sd[1], "내려서_분": max(1, round(wd)), "예상_분": round(tot)}

# ── 버스 구간 지도 선 (10/22 헌준님: 출발지→도착지 이동 경로를 실제 지도처럼) ──
#  자료: data/processed/bus_net.npz (pipeline/build_bus_net.py · 대구광역시 버스 노선 공간정보의 버스 링크 모양)
#  방법: 타는 정류장 → 내리는 정류장 사이를, 버스가 다니는 길(버스 링크) 위에서 그 노선 정류장 가까이(200m)를 지나는 길을 우선(그 밖은 8배 비용)해 가장 짧은 길로 그림
#  한계: 노선별 경유 순서 자료가 없어 실제 운행 경로와 다를 수 있음 → 화면에 '정류장 자료로 그린 길' 안내, 정확한 길은 카카오맵 길찾기
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
_KX = math.cos(math.radians(35.87)) * 111320; _KY = 110540
class BusNet:
    def __init__(self, bus):
        z = np.load(os.path.join(ROOT, "data", "processed", "bus_net.npz"))
        self.lon, self.lat, self.eu, self.ev, self.el = z["lon"], z["lat"], z["eu"], z["ev"], z["el"].astype(float)
        self.XY = np.c_[self.lon * _KX, self.lat * _KY]; self.T = cKDTree(self.XY); self.n = len(self.lon); self.bus = bus
    def path(self, alon, alat, blon, blat, routes=()):
        """[[위도, 경도], ...] 또는 None"""
        try:
            da, i = self.T.query([alon * _KX, alat * _KY]); db, j = self.T.query([blon * _KX, blat * _KY])
            if da > 120 or db > 120: return None
            w = self.el
            rs = set(routes or [])
            S = [(s[2] * _KX, s[3] * _KY) for s in self.bus.stops if s[4] & rs] if rs else []
            if S:
                d, _ = cKDTree(np.array(S)).query(self.XY, distance_upper_bound=200); near = np.isfinite(d)
                w = self.el * np.where(near[self.eu] & near[self.ev], 1.0, 8.0)
            M = coo_matrix((np.r_[w, w], (np.r_[self.eu, self.ev], np.r_[self.ev, self.eu])), shape=(self.n, self.n)).tocsr()
            straight = hav(alon, alat, blon, blat)
            dist, pred = dijkstra(M, directed=False, indices=int(i), return_predecessors=True, limit=max(8000, straight * 8))
            if not np.isfinite(dist[j]): return None
            seq = [int(j)]
            while seq[-1] != i and pred[seq[-1]] >= 0: seq.append(int(pred[seq[-1]]))
            seq = seq[::-1]
            L = float(np.sum(np.hypot(*np.diff(self.XY[seq], axis=0).T))) if len(seq) > 1 else 0
            if L > straight * 3 + 2000: return None   # 너무 돌아가면 그리지 않음 (틀린 길을 보여 주지 않게)
            pts = [[alat, alon]] + [[round(float(self.lat[k]), 6), round(float(self.lon[k]), 6)] for k in seq] + [[blat, blon]]
            return [p for k, p in enumerate(pts) if k == 0 or p != pts[k - 1]]
        except Exception:
            return None
