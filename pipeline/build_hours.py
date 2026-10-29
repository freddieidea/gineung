# 약국·병의원 운영시간을 지도 시설에 붙임 (국립중앙의료원 E-GEN) → data/processed/hours.csv
#  짝짓기: 150m 안 + 이름이 같거나(띄어쓰기·괄호 무시) 매우 비슷함(90 이상). 둘 이상이면 가장 가깝고 비슷한 것. 애매하면 붙이지 않음(지어내지 않음)
#  요일: 1월 2화 3수 4목 5금 6토 7일 8공휴일. 자료에 없는 요일은 쉬는 날
import json, glob, re, math, sys
import pandas as pd, numpy as np
from scipy.spatial import cKDTree
from rapidfuzz import fuzz
F = pd.read_csv("data/processed/facilities.csv", dtype=str)
MED = F["업종"].fillna("").str.contains("의원|병원|약국|보건|한의원|치과") | F["업종코드"].fillna("").str.contains("clinic|hospital|pharm|PUB:보건", regex=True)
M = F[MED & F["경도"].notna()].copy(); M["x"] = M["경도"].astype(float); M["y"] = M["위도"].astype(float)
k = math.cos(math.radians(35.87)) * 111320
tree = cKDTree(np.c_[M["x"] * k, M["y"] * 110540])
def norm(s): return re.sub(r"[\s\(\)\[\]·.,\-]|주식회사|\(주\)", "", str(s or "")).lower()
LEGAL = re.compile(r"^(의료법인|사회복지법인|학교법인|재단법인|\(재\)|\(의\)|\(사\))?[가-힣A-Za-z]*?(의료재단|복지재단|재단|학원|성직수도회|수도회)?")
def core(n):
    n = re.sub(r"^(의료법인|사회복지법인|학교법인|재단법인|\(재\)|\(의\)|\(사\)|대구광역시|군위군)", "", n)
    n = re.sub(r"^.*?(의료재단|복지재단|재단|학원)", "", n) if re.search(r"(의료재단|복지재단|재단|학원)", n[:-2] or "x") else n
    return re.sub(r"(약국|치과의원|한의원|의원|병원|보건소|보건지소|보건진료소|의학과)$", "", n)
DAYS = {1: "월", 2: "화", 3: "수", 4: "목", 5: "금", 6: "토", 7: "일", 8: "공휴일"}
def hhmm(v):
    v = str(v or "").strip()
    if not v or v == "nan": return None
    v = v.zfill(4)
    return v if re.fullmatch(r"\d{4}", v) and int(v[:2]) <= 24 and int(v[2:]) < 60 else None
rows = []; stat = {"받음": 0, "짝지음": 0}
for p in sorted(glob.glob("data/raw/public/egen_*_대구_*.json")):
    src = json.load(open(p, encoding="utf-8")); typ = "약국" if "약국" in p else "병의원"
    for it in src["items"]:
        stat["받음"] += 1
        try: x, y = float(it["wgs84Lon"]), float(it["wgs84Lat"])
        except Exception: continue
        sched = {}; odd = False
        for d, nm in DAYS.items():
            s, e = hhmm(it.get(f"dutyTime{d}s")), hhmm(it.get(f"dutyTime{d}c"))
            if s and e:
                if e <= s and e > "0600": odd = True   # 끝나는 시간이 여는 시간보다 이르면 자료 오류일 수 있음 → 그 요일은 '확인 필요'
                sched[nm] = [s, e]
        if not sched: continue
        en = norm(it.get("dutyName")); best = None
        for j in tree.query_ball_point([x * k, y * 110540], r=150):
            r = M.iloc[j]; fn = norm(r["상호"])
            d0 = math.hypot((r["x"] - x) * k, (r["y"] - y) * 110540)
            cf, ce = core(fn), core(en)   # 법인 이름·'약국/의원' 같은 꼬리를 뗀 알맹이 (예: '봄봄'과 '봄'은 다른 약국)
            if fn == en or (cf and cf == ce): sc = 100
            elif cf and ce and (cf in ce or ce in cf) and (min(len(cf), len(ce)) >= 4 or d0 <= 30): sc = 95
            else: sc = fuzz.ratio(cf or fn, ce or en) if min(len(cf), len(ce)) >= 3 else 0
            if typ == "약국" and "약국" not in str(r["업종"]): continue
            if typ == "병의원" and "약국" in str(r["업종"]): continue
            d = math.hypot((r["x"] - x) * k, (r["y"] - y) * 110540)
            if sc >= 90 and (best is None or (sc, -d) > (best[1], -best[2])): best = (M.index[j], sc, d)
        if best:
            stat["짝지음"] += 1
            rows.append({"fid": F.loc[best[0], "fid"], "hpid": it.get("hpid"), "이름": it.get("dutyName"), "종류": typ, "시간표": json.dumps(sched, ensure_ascii=False),
                         "확인필요": odd, "비고": re.sub(r"\s+", " ", str(it.get("dutyEtc") or ""))[:200], "유사도": best[1], "거리m": round(best[2]), "출처": src["출처"], "받은날": src["받은날"]})
H = pd.DataFrame(rows).sort_values(["fid", "유사도", "거리m"], ascending=[True, False, True]).drop_duplicates("fid")
H.to_csv("data/processed/hours.csv", index=False, encoding="utf-8")
med_f = M[M["대안후보"].isin(["예", "확인 필요"])]
print(stat, "시설에 붙음", len(H), "/ 지도의 안내 대상 약국·병의원", len(med_f), f"({len(set(H['fid']) & set(med_f['fid'])) / max(1, len(med_f)):.0%})")
