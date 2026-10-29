# 언어 모델 사용 비용 보기: python engine/usage_report.py  (data/usage/api_usage.csv, 10/16 오후부터 기록)
import os, pandas as pd
f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "usage", "api_usage.csv")
if not os.path.exists(f): print("아직 기록이 없어요"); raise SystemExit
d = pd.read_csv(f); d["날짜"] = d["시각"].str[:10]
print(d.groupby(["날짜", "용도", "모델"]).agg(호출=("달러", "size"), 달러=("달러", "sum")).round(3).to_string())
print("합계", round(d["달러"].sum(), 3), "달러")
