# 대구 버스 정류소 (대구광역시 버스 노선 공간정보 2026-09-02) + 정류소별 노선·평일 운행 횟수 (평균배차간격 자료 2025-11-14)
import geopandas as gpd, pandas as pd, glob, io
g=gpd.read_file("data/raw/public/bus_shp/bs_20260902.shp").to_crs(4326)
g=g[g["app_ed_dt"].astype(str)=="99999999"]  # 지금 쓰는 정류소만
S=pd.DataFrame({"정류소ID":g["bs_id"].astype(str),"정류소":g["bs_nm"],"경도":g.geometry.x.round(7),"위도":g.geometry.y.round(7),"노선":g["route_no"].fillna("")})
p=glob.glob("data/raw/public/버스__15060936__*.csv")[0]
raw=open(p,"rb").read()
for enc in ("utf-8-sig","cp949"):
    try: t=raw.decode(enc); break
    except Exception: pass
F=pd.read_csv(io.StringIO(t),dtype=str); F.columns=[c.replace("﻿","").strip() for c in F.columns]
F=F[F["시간표유형"]=="평일"]; F["운행횟수"]=pd.to_numeric(F["운행횟수"],errors="coerce").fillna(0)
agg=F.groupby("정류소ID").agg(평일운행횟수=("운행횟수","sum"),노선수=("노선","nunique"),첫차=("첫차","min"),막차=("막차","max")).reset_index()
B=S.merge(agg,on="정류소ID",how="left")
assert B["정류소ID"].is_unique, B["정류소ID"].duplicated().sum()
B.to_csv("data/processed/bus_stops.csv",index=False,encoding="utf-8")
print("정류소",len(B),"운행 자료 있음",B["평일운행횟수"].notna().sum(),"평일 운행 0회",int((B["평일운행횟수"]==0).sum()))
print(B.describe().to_string()[:500])
