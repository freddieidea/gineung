# 주민이 사는 곳 격자: 행정동 인구를 '사람이 사는 곳'의 100m 격자 점에 나눠 담는다 → data/processed/pop_grid.npz
# (10/19 고침) 건물 연면적 어림(바닥 면적 × 지상 층수, 브이월드 도로명주소 건물 257,896동)에 비례해 나눔
#  - 전에는 가게·정류장 250m 안에 고르게 나눠, 산속 정류장(진밭골)·산업단지 가게 근처에도 사람이 많은 것처럼 잡혔음
#  - 공업지역 건물은 사람이 거의 살지 않으므로 아주 적게(일반·전용공업 5%, 준공업 30%), 상업지역은 60%로 셈 (브이월드 용도지역)
#  - 건물 자료가 없는 동은 예전 방식(가게·정류장 250m 안에 고르게)
#  - 한계: 건물 용도(주택·상가)를 몰라 상가 건물에도 사람을 나눔 → 상업·공업지역 비율로 줄여 보완
# 쓰는 곳: 시설이 문을 닫았을 때 '영향받는 주민'을 셀 때 (engine/impact.py)
# 가정 (알림에 그대로 밝힘):
#  - 행정동 인구(2026-09-30)는 그 동의 '사람이 사는 곳' 안에 고르게 산다고 봄 (집계구 인구가 없어 행정동 단위가 가장 작은 단위)
#  - '사람이 사는 곳' = 가게(상가 자료 118,357곳) 또는 버스 정류장에서 250m 안. 산·강·논밭 한가운데처럼 가게도 정류장도 없는 곳에는 사람을 두지 않음
#    (그런 점이 하나도 없는 동은 동 전체 격자에 나눔)
#  - 각 점은 걷는 길 위의 가장 가까운 지점에 붙임 (시설과 같은 방식)
import json, numpy as np, pandas as pd, shapely
from shapely.geometry import shape
from scipy.spatial import cKDTree
KX = np.cos(np.radians(35.87)) * 111320; KY = 110540; STEP = 100.0; NEAR = 250.0
G = json.load(open("data/raw/boundary/daegu_hjd_20260701.geojson", encoding="utf-8"))["features"]
P = pd.read_csv("data/processed/population_hjd.csv", dtype={"경계코드": str})
pop = P.groupby("경계코드")[["인구", "65세이상"]].sum()
S = pd.read_csv("data/raw/소상공인시장진흥공단_상가(상권)정보_대구_202606.csv", dtype=str, usecols=["경도", "위도"]).astype(float).dropna()
B = pd.read_csv("data/processed/bus_stops.csv", dtype=str, usecols=["경도", "위도"]).astype(float).dropna()
anchor = cKDTree(np.r_[np.c_[S["경도"] * KX, S["위도"] * KY], np.c_[B["경도"] * KX, B["위도"] * KY]])
Z = np.load("data/processed/walk_daegu.npz"); walkT = cKDTree(np.c_[Z["sx"] * KX, Z["sy"] * KY])
BL = pd.read_csv("data/raw/buildings/daegu_buildings.csv", usecols=["경도", "위도", "바닥면적", "층수"]).dropna()
BL["연면적"] = BL["바닥면적"].clip(upper=20000) * BL["층수"].clip(lower=1, upper=80)
ZN = json.load(open("data/raw/boundary/daegu_zoning.geojson", encoding="utf-8"))["features"]
ZF = {"일반공업지역": 0.05, "전용공업지역": 0.05, "준공업지역": 0.3, "일반상업지역": 0.6, "근린상업지역": 0.6, "중심상업지역": 0.6, "유통상업지역": 0.3}
zg = [shape(f["geometry"]) for f in ZN]; zt = shapely.STRtree(zg); fac = np.ones(len(BL))
bpts = shapely.points(BL["경도"].values, BL["위도"].values)
pi, zi = zt.query(bpts, predicate="within")
for a_, b_ in zip(pi, zi): fac[a_] = min(fac[a_], ZF.get(ZN[b_]["properties"]["uname"], 1.0))
BL["무게"] = BL["연면적"] * fac
bx_all, by_all, bw_all = BL["경도"].values, BL["위도"].values, BL["무게"].values
n_bld_dong = 0
out = {k: [] for k in ["lon", "lat", "hjd", "pop", "pop65", "edge", "t", "snap"]}
names = []; miss = []
for i, f in enumerate(G):
    pr = f["properties"]; code = pr["adm_cd2"]; poly = shape(f["geometry"])
    names.append((code, pr["sggnm"], pr["adm_nm"].split()[-1]))
    if code not in pop.index: miss.append(pr["adm_nm"]); continue
    x0, y0, x1, y1 = poly.bounds
    xs = np.arange(x0 * KX, x1 * KX, STEP) / KX; ys = np.arange(y0 * KY, y1 * KY, STEP) / KY
    gx, gy = np.meshgrid(xs + STEP / KX / 2, ys + STEP / KY / 2); gx = gx.ravel(); gy = gy.ravel()
    inside = shapely.contains_xy(poly, gx, gy)
    if inside.sum() == 0: gx, gy = np.array([poly.representative_point().x]), np.array([poly.representative_point().y]); inside = np.array([True])
    gx, gy = gx[inside], gy[inside]
    pp, p65 = pop.loc[code, "인구"], pop.loc[code, "65세이상"]
    m = (bx_all >= x0) & (bx_all <= x1) & (by_all >= y0) & (by_all <= y1)
    bx, by, bw = bx_all[m], by_all[m], bw_all[m]
    ins = shapely.contains_xy(poly, bx, by) if len(bx) else np.zeros(0, bool)
    bx, by, bw = bx[ins], by[ins], bw[ins]
    if len(bx) and bw.sum() > 0:   # 건물 연면적에 비례해 나눔: 건물마다 가장 가까운 격자 점에 무게를 더함
        _, gi = cKDTree(np.c_[gx * KX, gy * KY]).query(np.c_[bx * KX, by * KY])
        wt = np.bincount(gi, weights=bw, minlength=len(gx)); keep = wt > 0
        gx, gy, wt = gx[keep], gy[keep], wt[keep] / wt[keep].sum(); n_bld_dong += 1
    else:   # 건물 자료가 없으면 예전 방식
        d, _ = anchor.query(np.c_[gx * KX, gy * KY], distance_upper_bound=NEAR)
        live = np.isfinite(d)
        if live.sum() > 0: gx, gy = gx[live], gy[live]
        wt = np.full(len(gx), 1.0 / len(gx))
    n = len(gx)
    sd, j = walkT.query(np.c_[gx * KX, gy * KY])
    out["lon"].append(gx); out["lat"].append(gy); out["hjd"].append(np.full(n, i, np.int16))
    out["pop"].append(pp * wt); out["pop65"].append(p65 * wt)
    out["edge"].append(Z["se"][j]); out["t"].append(Z["st"][j]); out["snap"].append(sd.astype(np.float32))
A = {k: np.concatenate(v) for k, v in out.items()}
np.savez_compressed("data/processed/pop_grid.npz", **A, hjd_code=np.array([n[0] for n in names]), hjd_gu=np.array([n[1] for n in names]), hjd_name=np.array([n[2] for n in names]))
print("격자 점", len(A["lon"]), "인구 합", round(A["pop"].sum()), "/ 행정동 인구 합", int(P["인구"].sum()), "65세 이상", round(A["pop65"].sum()))
print("인구 자료 없는 경계", miss, "길까지 150m 넘는 점", int((A["snap"] > 150).sum()))
