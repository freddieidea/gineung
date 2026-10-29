# 생명과 직결되는 진료를 하는 병원 목록 (심평원 의료기관별 상세정보 '시설정보', 2026.6)
#  분만실·신생아 중환자실·소아 중환자실·성인 중환자실 병상이 있는 대구 의료기관 → 우리 시설 fid와 이음 (hira_match.csv)
#  지자체 에이전트가 도심에서도 보고하는 '생명 직결 공백'을 잴 때 씀 (engine/severity.py SPECIAL)
#  쓰는 법: python pipeline/build_critical_care.py
import os, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
f = os.path.join(ROOT, "data", "raw", "hira", "3.의료기관별상세정보서비스_01_시설정보(2026.6.).xlsx")
d = pd.read_excel(f); d = d[d["시도코드명"].astype(str).str.contains("대구")]
cols = ["분만실병상수", "신생아중환자병상수", "소아중환자병상수", "성인중환자병상수", "응급실병상수"]
d = d[(d[cols].fillna(0) > 0).any(axis=1)][["요양기관명", "종별코드명", "시군구코드명", "읍면동", "주소"] + cols]
m = pd.read_csv(os.path.join(ROOT, "data", "processed", "hira_match.csv"))
g = m.groupby("hira_name")["fid"].apply(lambda s: ";".join(s)).reset_index()
d = d.merge(g, left_on="요양기관명", right_on="hira_name", how="left").drop(columns=["hira_name"])
out = os.path.join(ROOT, "data", "processed", "critical_care.csv"); d.to_csv(out, index=False)
print(len(d), "곳 →", out, "| 이어지지 않은 곳:", int(d["fid"].isna().sum()), "| " + ", ".join(f"{c} {int((d[c].fillna(0) > 0).sum())}" for c in cols))
