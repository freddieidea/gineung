# 대구 행정동별 인구와 65세 이상 인구 (행정안전부 주민등록 인구, 2026-09-30) + 행정동 경계(vuski/admdongkor ver20260701)와 맞춤
import pandas as pd, json, glob, io
p=glob.glob("data/raw/public/인구__15097972__*.csv")[0]
d=pd.read_csv(io.StringIO(open(p,"rb").read().decode("cp949")),dtype=str)
d=d[d["시도명"]=="대구광역시"].copy()
d=d[d["읍면동명"].notna()&(d["읍면동명"].str.strip()!="")]  # 시군구 합계 행 제외
num=lambda c: pd.to_numeric(d[c].str.replace(",",""),errors="coerce").fillna(0).astype(int)
old=[c for c in d.columns if c.endswith("세남자") or c.endswith("세여자") or "이상" in c]
age=lambda c: int("".join(ch for ch in c if ch.isdigit()) or -1)
c65=[c for c in old if age(c)>=65]
d["인구"]=num("계"); d["65세이상"]=sum(num(c) for c in c65)
# (10/19) 보육·아동 돌봄 공백을 재려고 아이 인구도 둠: 영유아 0~5세(어린이집·유치원), 초등 아동 6~12세(지역아동센터·다함께돌봄센터)
d["영유아"]=sum(num(c) for c in old if 0<=age(c)<=5 and "이상" not in c)
# 영아(0~2세)는 어린이집만, 유아(3~5세)는 어린이집·유치원 모두 다닐 수 있어 따로 셈 (10/20)
d["영아"]=sum(num(c) for c in old if 0<=age(c)<=2 and "이상" not in c); d["유아"]=sum(num(c) for c in old if 3<=age(c)<=5 and "이상" not in c); d["아동"]=sum(num(c) for c in old if 6<=age(c)<=12 and "이상" not in c)
out=d[["행정기관코드","시군구명","읍면동명","인구","65세이상","영유아","영아","유아","아동"]].copy()
G=json.load(open("data/raw/boundary/daegu_hjd_20260701.geojson",encoding="utf-8"))
codes={f["properties"]["adm_cd2"] for f in G["features"]}
# 경계 자료(2026-07)에 없는 코드: 출장소는 본 읍의 경계 안, 구지면→구지읍 승격으로 코드가 바뀜
ALIAS={"2771025400":"2771025300","2771025700":"2771025600","2771026800":"2771038000"}
out["경계코드"]=out["행정기관코드"].map(lambda c: ALIAS.get(c,c))
out["경계있음"]=out["경계코드"].isin(codes)
assert out["경계있음"].all(), out[~out["경계있음"]]
print("행정동",len(out),"인구",out["인구"].sum(),"65세 이상",out["65세이상"].sum(),"경계와 맞음",out["경계있음"].sum(),"/ 경계",len(codes))
print(out[~out["경계있음"]].head(10).to_string())
print(out.groupby("시군구명")[["인구","65세이상","영유아","아동"]].sum().to_string())
out.to_csv("data/processed/population_hjd.csv",index=False,encoding="utf-8")
