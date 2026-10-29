# 인허가상 영업 중인데 상가 자료에 없는 가게 찾기 (상가 자료가 빠뜨린 대안 후보). 구·군 하나씩: python find_localdata_only.py 구군
# 상가에 '있다'고 보는 조건: 80m 안 상가 가게와 상호가 거의 같음(글자 유사도 85 이상).
#   상호가 다른 가게 이름 안에 들어 있기만 한 경우(예: '삼일병원' ⊂ '삼일병원장례식장', '세븐일레븐대구삼일 병원점')는
#   그 상가 가게의 업종이 이 인허가의 본업일 때만 같은 가게로 봄 (10/14 수정: 큰 병원이 매점·장례식장 때문에 빠지던 오류)
import pandas as pd, numpy as np, sys, re
from scipy.spatial import cKDTree
sys.path.insert(0,"pipeline"); from ld_common import norm, sim, primary_for
from rapidfuzz import fuzz
GU=sys.argv[1]
ADD={"barber_shops":None,"beauty_salons":["일반미용업"],"laundries":None,"public_baths":None,"pharmacies":None,"clinics":None,"hospitals":None,
     "optical_shops":None,"fitness_centers":None,"swimming_pools":None,"golf_practice_ranges":None,"billiard_halls":None,"martial_arts_dojo":None,
     "comprehensive_sports_facilities":None,"karaoke_rooms":None,"pc_bangs":None,"animal_hospitals":None,"pet_grooming":None,"animal_boarding":None,
     "livestock_retail":["식육판매업"],"bakeries":None,"oil_retailers":["주유소","일반판매소"],"large_scale_retail_stores":["대형마트","시장","쇼핑센터","백화점","복합쇼핑몰"],
     "medical_device_sales_rental":None,"postpartum_care":None,"general_restaurants":None,"rest_cafes":["커피숍","편의점","다방","전통찻집","아이스크림","떡카페","과자점"]}
cols=["ld_id","slug","인허가업종","구군","사업장명","영업상태명","업태구분명","진료과목내용명","의료기관종별명","인허가일자","도로명주소","전화번호","경도","위도"]
D=pd.read_csv("data/processed/localdata_daegu.csv",dtype=str,usecols=cols)
D=D[(D["구군"]==GU)&(D["영업상태명"]=="영업/정상")&D["slug"].isin(ADD)&D["경도"].notna()].copy()
D=D[[ADD[s] is None or u in ADD[s] for s,u in zip(D["slug"],D["업태구분명"].fillna(""))]].reset_index(drop=True)
S=pd.read_csv("data/raw/소상공인시장진흥공단_상가(상권)정보_대구_202606.csv",dtype=str,usecols=["상호명","지점명","상권업종소분류코드","상권업종소분류명","경도","위도"])
S["prim"]=[set(primary_for(c,n)) for c,n in zip(S["상권업종소분류코드"],S["상권업종소분류명"])]
S["nm"]=(S["상호명"].fillna("")+S["지점명"].fillna("")).map(norm); S["nm0"]=S["상호명"].map(norm)
k=np.cos(np.radians(35.87))*111320
SX=np.c_[S["경도"].astype(float)*k,S["위도"].astype(float)*110540]; tree=cKDTree(SX)
DX=np.c_[D["경도"].astype(float)*k,D["위도"].astype(float)*110540]
nm=S["nm"].values; nm0=S["nm0"].values; prim=S["prim"].values
only=[]
for i,(nb) in enumerate(tree.query_ball_point(DX,r=80)):
    dn=norm(D.at[i,"사업장명"]); sl=D.at[i,"slug"]
    hit=[j for j in nb if max(sim(dn,nm[j]),sim(dn,nm0[j]))>=85]
    if not any(max(fuzz.ratio(dn,nm[j]),fuzz.ratio(dn,nm0[j]))>=85 or sl in prim[j] for j in hit): only.append(i)
O=D.iloc[only]
O.to_csv(f"data/work/ldonly_{GU}.csv",index=False,encoding="utf-8")
print(GU,"인허가 영업",len(D),"상가에 없음",len(O),dict(O["slug"].value_counts().head(8)))
