# 카카오맵 대조 표본 점검 (10/15): 지도에 나올 수 있는 가게(상가·인허가)를 업종별로 고르게 뽑아 카카오맵에서 찾히는 비율만 셈
#  카카오 이용 조건에 따라 가게별 결과는 저장하지 않고, 업종·출처별 '찾음/못 찾음' 개수(집계)만 남김 → data/work/kakao_sample_summary.csv
import sys, os, random, collections, concurrent.futures as cf
sys.path.insert(0, "engine")
import pandas as pd
from live_check import LiveCheck
N = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
F = pd.read_csv("data/processed/facilities.csv", dtype=str)
P = F[F["출처"].isin(["상가", "인허가"]) & (F["대안후보"] == "예") & F["경도"].notna()]
random.seed(20261015)
per = max(3, N // P["업종"].nunique())
pick = pd.concat([g.sample(min(len(g), per), random_state=1) for _, g in P.groupby("업종")])
L = LiveCheck()
def one(r):
    v = L.check(r["상호"], float(r["경도"]), float(r["위도"]))[0]
    alt = str(r.get("인허가상호") or "")
    if v == "찾지 못함" and alt not in ("", "nan") and alt.replace(" ", "") != str(r["상호"]).replace(" ", ""): v = L.check(alt, float(r["경도"]), float(r["위도"]))[0]
    return r["업종"], r["출처"] + "/" + str(r["인허가상태"]), v
cnt = collections.Counter()
with cf.ThreadPoolExecutor(8) as ex:
    for u, src, v in ex.map(one, [r for _, r in pick.iterrows()]): cnt[(u, src, v)] += 1
rows = collections.defaultdict(lambda: {"찾음": 0, "못 찾음": 0, "확인 실패": 0})
for (u, src, v), n in cnt.items(): rows[(u, src)][{"확인됨": "찾음", "찾지 못함": "못 찾음"}.get(v, "확인 실패")] += n
S = pd.DataFrame([{"업종": u, "출처": s, **d} for (u, s), d in rows.items()])
S["못 찾은 비율"] = (S["못 찾음"] / (S["찾음"] + S["못 찾음"]).clip(lower=1)).round(3)
S.sort_values("못 찾은 비율", ascending=False).to_csv("data/work/kakao_sample_summary.csv", index=False, encoding="utf-8")
t = S[["찾음", "못 찾음", "확인 실패"]].sum(); print("표본", int(t.sum()), dict(t), "못 찾은 비율", round(t["못 찾음"] / max(1, t["찾음"] + t["못 찾음"]), 3))
print(S.groupby("출처")[["찾음", "못 찾음"]].sum())
print(S.sort_values("못 찾은 비율", ascending=False).head(25).to_string())
