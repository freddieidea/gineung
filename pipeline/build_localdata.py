# 받은 인허가 CSV를 하나로 합치고 좌표를 경위도로 바꿔 저장 (EPSG:5174 → 4326, 상가 약국 142곳 대조로 확인: 중앙값 6.9m)
import pandas as pd, glob, os, sys
sys.path.insert(0,"pipeline"); sys.path.insert(0,"engine"); from fetch_localdata import SLUG, ORG
from coords import Transformer   # pyproj 없이 같은 변환 (engine/coords.py)
KEEP=["관리번호","사업장명","영업상태명","상세영업상태명","인허가일자","폐업일자","업태구분명","위생업태명","진료과목내용명","의료기관종별명","의료유사업종별명",
      "도로명주소","지번주소","전화번호","좌표정보(X)","좌표정보(Y)","데이터갱신시점"]
ds=[]
for slug in SLUG:
    for gu in ORG:
        p=f"data/raw/localdata/{slug}__{gu}.csv"; d=pd.read_csv(p,dtype=str)
        for c in KEEP:
            if c not in d: d[c]=None
        d=d[KEEP].copy(); d.insert(0,"구군",gu); d.insert(0,"slug",slug); d.insert(1,"인허가업종",SLUG[slug]); ds.append(d)
D=pd.concat(ds,ignore_index=True)
assert D["관리번호"].notna().all()
dup=D.duplicated(["slug","구군","관리번호"]).sum(); assert dup==0, dup
D.insert(0,"ld_id",D["slug"]+":"+D["구군"]+":"+D["관리번호"])
x=pd.to_numeric(D["좌표정보(X)"].str.strip(),errors="coerce"); y=pd.to_numeric(D["좌표정보(Y)"].str.strip(),errors="coerce")
t=Transformer.from_crs("EPSG:5174","EPSG:4326",always_xy=True)
lon,lat=t.transform(x.values,y.values); D["경도"]=lon; D["위도"]=lat
ok=D["경도"].between(128.3,129.0)&D["위도"].between(35.55,36.35)
D.loc[~ok,["경도","위도"]]=None
D=D.drop(columns=["좌표정보(X)","좌표정보(Y)"])
D.to_csv("data/processed/localdata_daegu.csv",index=False,encoding="utf-8")
print("행",len(D),"중복",dup,"좌표 있음",int(ok.sum()),"영업 중",int((D["영업상태명"]=="영업/정상").sum()))
