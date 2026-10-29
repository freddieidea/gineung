# 상가 가게(생활시설 업종)와 인허가 자료를 가게 단위로 짝짓는다. 좌표 거리 + 상호 유사도.
# 결과: data/processed/store_localdata_match.csv (가게별 인허가 상태·업태·진료과목 등)
import pandas as pd, numpy as np, re, json, sys
from scipy.spatial import cKDTree
from rapidfuzz import fuzz
import sys as _s; _s.path.insert(0,'pipeline')
from ld_common import PRIMARY, primary_for, norm, sim
GU=sys.argv[1]
M=json.load(open("data/processed/industry_function_map.json",encoding="utf-8"))
life={i["code"] for i in M["items"] if i["life_facility"]}
S=pd.read_csv("data/raw/소상공인시장진흥공단_상가(상권)정보_대구_202606.csv",dtype=str,
   usecols=["상가업소번호","상호명","지점명","상권업종소분류코드","상권업종소분류명","시군구명","경도","위도"])
S=S[S["상권업종소분류코드"].isin(life)&(S["시군구명"]==GU)].reset_index(drop=True)
S["lon"]=S["경도"].astype(float); S["lat"]=S["위도"].astype(float)
S["nm"]=(S["상호명"].fillna("")+S["지점명"].fillna("")).map(norm); S["nm0"]=S["상호명"].map(norm)
cols=["ld_id","slug","인허가업종","사업장명","영업상태명","폐업일자","인허가일자","업태구분명","진료과목내용명","의료기관종별명","경도","위도"]
D=pd.read_csv("data/processed/localdata_daegu.csv",dtype=str,usecols=cols); D=D[D["경도"].notna()]
D["lon"]=D["경도"].astype(float); D["lat"]=D["위도"].astype(float)
m=0.006
D=D[D["lon"].between(S["lon"].min()-m,S["lon"].max()+m)&D["lat"].between(S["lat"].min()-m,S["lat"].max()+m)].reset_index(drop=True)
D["nm"]=D["사업장명"].map(norm)
k=np.cos(np.radians(35.87))*111320
XY=np.c_[D["lon"].values*k,D["lat"].values*110540]; SP=np.c_[S["lon"].values*k,S["lat"].values*110540]
tree=cKDTree(XY)
A={c:D[c].fillna("").values for c in ["ld_id","slug","인허가업종","사업장명","영업상태명","폐업일자","인허가일자","업태구분명","진료과목내용명","의료기관종별명","nm"]}
from ld_common import same_biz   # 다른 인허가를 이 가게 것으로 볼지 (시설 변화 관리와 함께 씀)
rows=[]
for i in range(len(S)):
    s=S.iloc[i]; prim=set(primary_for(s["상권업종소분류코드"],s["상권업종소분류명"]))
    near=tree.query_ball_point(SP[i],r=80)
    hits=[]
    for j in near:
        sc=max(sim(s["nm"],A["nm"][j]),sim(s["nm0"],A["nm"][j]))
        if sc>=85: hits.append((j,sc,float(np.hypot(*(SP[i]-XY[j])))))
    if not hits:
        for j in tree.query_ball_point(SP[i],r=300):
            if A["nm"][j] and A["nm"][j] in (s["nm"],s["nm0"]): hits.append((j,100,float(np.hypot(*(SP[i]-XY[j])))))
    ph=[h for h in hits if A["slug"][h[0]] in prim]
    op=[h for h in ph if A["영업상태명"][h[0]]=="영업/정상"]
    if op: st="영업"; best=max(op,key=lambda h:(h[1],-h[2]))
    elif ph:
        best=max(ph,key=lambda h:(A["폐업일자"][h[0]],h[1]))
        st={"폐업":"폐업","휴업":"휴업"}.get(A["영업상태명"][best[0]],"말소 등")
    else: st="본업 인허가 없음" if prim else "인허가 대상 아님"; best=None
    other=""
    if prim and st!="영업":
        cand=[j for j in tree.query_ball_point(SP[i],r=20) if A["slug"][j] in prim and A["영업상태명"][j]=="영업/정상"
              and max(sim(s["nm"],A["nm"][j]),sim(s["nm0"],A["nm"][j]))<60]
        if cand:
            j=max(cand,key=lambda j:A["인허가일자"][j]); other=f'{A["사업장명"][j]} / {A["인허가업종"][j]} / {A["업태구분명"][j]} / 인허가 {A["인허가일자"][j]}'
    b=best[0] if best else None
    g=lambda c: A[c][b] if b is not None else ""
    rows.append({"상가업소번호":s["상가업소번호"],"업종코드":s["상권업종소분류코드"],"구군":GU,"인허가상태":st,"인허가id":g("ld_id"),"인허가업종":g("인허가업종"),
      "인허가상호":g("사업장명"),"유사도":best[1] if best else "","거리m":round(best[2],1) if best else "","업태":g("업태구분명"),"진료과목":g("진료과목내용명"),
      "의료기관종별":g("의료기관종별명"),"폐업일자":g("폐업일자"),"인허가일자":g("인허가일자"),
      "그외인허가":"|".join(sorted({A["인허가업종"][h[0]]+("" if A["영업상태명"][h[0]]=="영업/정상" else "(폐업)") for h in hits if A["slug"][h[0]] not in prim and same_biz(s["nm"],s["nm0"],A["nm"][h[0]])})),
      "같은자리새가게":other})
R=pd.DataFrame(rows); R.to_csv(f"data/work/match_{GU}.csv",index=False,encoding="utf-8")
print(GU,"가게",len(R),dict(R["인허가상태"].value_counts()))
