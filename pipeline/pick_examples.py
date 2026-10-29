# 업종별 예시 가게 고르기 (2판). 공공 자료로 지금도 영업 중일 가능성이 높은 가게를 고른다.
# 순서: ① 인허가로도 영업 중이 확인된 가게 ② 대구에 3곳 이상 있는 상호(체인) ③ ①②가 하나도 없을 때만 상가 최근 등록 1곳
# 빼는 가게: 인허가상 폐업·휴업·말소, 상호와 업종이 어긋나는 가게, 업종명·'업소명없음' 같은 자리채움 이름
import json, re, collections
import pandas as pd
S=pd.read_csv("data/raw/소상공인시장진흥공단_상가(상권)정보_대구_202606.csv",dtype=str,usecols=["상가업소번호","상호명","지점명","상권업종소분류코드","상권업종소분류명","표준산업분류명","시군구명"])
F=pd.read_csv("data/processed/facilities.csv",dtype=str,usecols=["fid","대안후보","영업근거","업종확인필요"])
F=F[F["fid"].str.startswith("S:")]; F["상가업소번호"]=F["fid"].str[2:]
S=S.merge(F[["상가업소번호","대안후보","영업근거","업종확인필요"]],on="상가업소번호",how="left")
def ym(x):
    m=re.match(r"MA0101(\d{6})",x or ""); return m.group(1) if m else "000000"
S["ym"]=S["상가업소번호"].map(ym)
M=pd.read_csv("data/processed/store_localdata_match.csv",dtype=str) if False else None
out={}
for code,g in S.groupby("상권업종소분류코드"):
    junk={g["상권업종소분류명"].iloc[0].replace(" ",""),str(g["표준산업분류명"].iloc[0]).replace(" ",""),"업소명없음","상호없음","없음"}
    ok=g[~g["상호명"].fillna("").str.replace(" ","").isin(junk)&(g["상호명"].str.len()>=2)&~g["상호명"].str.contains("업소명|상호명|미상|/",na=True)]
    ok=ok[(ok["대안후보"].fillna("예")=="예")&(ok["업종확인필요"].fillna("")=="")]
    ex=[]; used=set()
    def add(r,kind,**kw):
        if r["상호명"] in used or len(ex)>=3: return
        used.add(r["상호명"]); ex.append({"상호":r["상호명"],"구분":kind,"구군":r["시군구명"],**kw})
    lic=ok[ok["영업근거"]=="상가+인허가 영업"].sort_values(["ym","상가업소번호"],ascending=False)
    for _,r in lic.drop_duplicates("상호명").head(3).iterrows(): add(r,"인허가 영업 확인")
    cnt=ok["상호명"].value_counts()
    for n,c in cnt.items():
        if c<3 or len(ex)>=3: break
        if not any(n.startswith(u) or u.startswith(n) for u in used): add(ok[ok["상호명"]==n].iloc[0],"여러 곳",곳수=int(c))
    # ③ 최근 등록은 지도 확인율이 낮아(카카오 대조 24%) ①②로 하나도 못 채운 업종에만 1곳 씀
    for _,r in ok.sort_values(["ym","상가업소번호"],ascending=False).drop_duplicates("상호명").iterrows():
        if len(ex)>=1: break
        if not any(r["상호명"].startswith(u) or u.startswith(r["상호명"]) for u in used): add(r,"최근 등록",등록=r["ym"][:4]+"."+r["ym"][4:])
    out[code]=ex
json.dump({"method":"① 인허가로도 영업 중인 가게 ② 대구 3곳 이상 상호 ③ 둘 다 없을 때만 상가 최근 등록 1곳. 인허가 폐업·업종 어긋남·자리채움 이름 제외","examples":out},
  open("data/processed/industry_examples.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
c=collections.Counter(e["구분"] for v in out.values() for e in v); print(len(out),dict(c),"3개 미만",sum(1 for v in out.values() if len(v)<3))
