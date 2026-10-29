# 도로명주소 → 좌표 찾기: 상가·인허가 자료에 같은 건물 주소가 있으면 그 좌표를 씀 (같은 건물 여러 건이면 중앙값)
import re, pandas as pd, numpy as np
GU=["중구","동구","서구","남구","북구","수성구","달서구","달성군","군위군"]
def key(addr):
    s=str(addr or "").replace("대구광역시","").replace("경상북도","").strip()
    s=re.sub(r"\(.*?\)","",s).split(",")[0]
    g=re.search(r"(중구|동구|서구|남구|북구|수성구|달서구|달성군|군위군)",s)
    if not g: return None
    rest=s[g.end():]
    m=re.search(r"([가-힣A-Za-z0-9.·]+(?:로|길)(?:\s*\d+(?:번)?길)?)\s*(\d+(?:-\d+)?)(?!\d)",rest)
    if not m: return None
    return f"{g.group(1)}|{m.group(1).replace(' ','')}|{m.group(2)}"
def build():
    S=pd.read_csv("data/raw/소상공인시장진흥공단_상가(상권)정보_대구_202606.csv",dtype=str,usecols=["도로명주소","경도","위도"])
    D=pd.read_csv("data/processed/localdata_daegu.csv",dtype=str,usecols=["도로명주소","경도","위도"]).dropna()
    A=pd.concat([S,D]); A["k"]=A["도로명주소"].map(key); A=A.dropna(subset=["k"])
    A["경도"]=A["경도"].astype(float); A["위도"]=A["위도"].astype(float)
    return A.groupby("k")[["경도","위도"]].median()
