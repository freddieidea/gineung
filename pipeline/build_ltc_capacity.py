# 장기요양기관의 규모(정원·인력) → data/processed/ltc_capacity.csv (10/16)
#  출처: 국민건강보험공단_장기요양기관 시설별 현황 (공공데이터포털 15124763, 2026-06-10 지정자료) — data/raw/public/ltc/
#  쓰는 곳: 주민·지자체 화면의 '이 곳이 하는 일'(규모), 지자체 에이전트의 '이용자 옮김' (정원만큼 이용자가 옮겨야 할 수 있음)
#  현원(지금 이용자 수)은 2025년 4월 뒤 자료에 없어 정원만 씀 (지금 이용자 수는 기관에 확인)
import pandas as pd
X = pd.read_excel("data/raw/public/ltc/장기요양기관_시설별현황_20260610.xlsx", sheet_name=None, dtype=str)
F = pd.read_csv("data/processed/facilities.csv", dtype=str, keep_default_na=False)
P = F[F["fid"].str.startswith("P:장기요양:")].copy()
P["code"] = P["fid"].str.split(":").str[2]; P["유형"] = P["fid"].str.split(":").str[3]
cap = X["입소인원"]; man = X["인력현황"]
rows = []
for _, r in P.iterrows():
    c = cap[(cap["장기요양기관코드"] == r["code"]) & cap["기관유형명"].str.contains(r["유형"], regex=False, na=False)]
    m = man[(man["장기요양기관코드"] == r["code"]) & man["기관유형코드명"].str.contains(r["유형"], regex=False, na=False)]
    n = pd.to_numeric(c["정원"], errors="coerce").max() if len(c) else None
    care = pd.to_numeric(m["요양보호사"], errors="coerce").max() if len(m) else None
    nurse = (pd.to_numeric(m["간호사"], errors="coerce").max() if len(m) else 0) or 0
    rows.append({"fid": r["fid"], "정원": None if n != n else n, "요양보호사": None if care != care else care, "간호사": nurse if nurse == nurse else None})
R = pd.DataFrame(rows); R.to_csv("data/processed/ltc_capacity.csv", index=False, encoding="utf-8")
print("장기요양기관", len(P), "정원 있음", int(R["정원"].fillna(0).gt(0).sum()), "요양보호사 있음", int(R["요양보호사"].fillna(0).gt(0).sum()))
print(R.merge(P[["fid", "유형"]]).groupby("유형")[["정원", "요양보호사"]].median())
