# 데이터 검사 한 번에 돌리기. 자료를 고칠 때마다 실행: python pipeline/check_all.py
# 고치지 않고 읽기만 함. 하나라도 실패하면 끝에 '실패'와 내용을 보여 주고 종료 코드 1
import json, re, sys, subprocess, numpy as np, pandas as pd
from shapely.geometry import shape, Point
from shapely.ops import unary_union
from shapely.prepared import prep
ok_n=0; bad=[]
def check(name, cond, detail=""):
    global ok_n
    if cond: ok_n+=1; print("통과", name)
    else: bad.append(name); print("실패", name, detail)
EXPECT="0.9-draft"; GRADES={"필수","준필수","선택"}; CANDS={"예","확인 필요","아니요","좌표 필요"}
GU=["중구","동구","서구","남구","북구","수성구","달서구","달성군","군위군"]
# 1) 분류표
T=json.load(open("design/purpose_taxonomy.json",encoding="utf-8"))
check("분류표 버전", T["version"]==EXPECT, T["version"])
L=[l for c in T["categories"] for p in c["purposes"] for l in p["leaves"]]; ids=[l["id"] for l in L]
check("세부 기능 번호가 겹치지 않음", len(ids)==len(set(ids)))
check("모든 세부 기능에 등급(필수·준필수·선택)", all(l["grade"] in GRADES for l in L), [l["id"] for l in L if l["grade"] not in GRADES])
check("모든 세부 기능에 등급 근거", all(l.get("public_basis") is not None and l.get("weekly_use") for l in L))
check("모든 세부 기능에 세부 종류 판단", all("kinds" in l and "sensitive" in l["kinds"] for l in L))
X=json.load(open("data/processed/extra_type_functions.json",encoding="utf-8")); XT={x["code"] for x in X["items"]}
M=json.load(open("data/processed/industry_function_map.json",encoding="utf-8"))
check("연결표·시설 유형 버전", M["taxonomy_version"]==EXPECT and X["taxonomy_version"]==EXPECT)
fids=set(ids)
check("연결표의 기능 번호가 모두 분류표에 있음", all(f["id"] in fids for it in M["items"] for f in it["functions"]))
check("시설 유형의 기능 번호가 모두 분류표에 있음", all(f["id"] in fids for it in X["items"] for f in it["functions"]))
kt=[t["code"] for l in L if l["kinds"].get("sensitive") for g in l["kinds"]["groups"] for k in g["kinds"] for t in k["types"]]
check("세부 종류의 시설 유형이 모두 정의돼 있음", all(t in XT for t in kt), set(t for t in kt if t not in XT))
check("신청·문의 창구 종류에는 상가 업종이 없음", all(not k["upjong"] for l in L if l["kinds"].get("sensitive") for g in l["kinds"]["groups"] for k in g["kinds"] if k.get("contact")))
# 2) 시설 목록
F=pd.read_csv("data/processed/facilities.csv",dtype=str,keep_default_na=False)
F["x"]=pd.to_numeric(F["경도"],errors="coerce"); F["y"]=pd.to_numeric(F["위도"],errors="coerce")
check("시설 번호가 겹치지 않음", F["fid"].is_unique)
check("대안 후보 값이 정해진 네 가지 중 하나", F["대안후보"].isin(CANDS).all(), F["대안후보"].unique())
closed=F["인허가상태"].isin(["폐업","휴업","말소 등"])
check("인허가상 폐업·휴업·말소 시설은 '예'가 아님", not (closed&(F["대안후보"]=="예")).any(), int((closed&(F["대안후보"]=="예")).sum()))
cand=F[F["대안후보"].isin(["예","확인 필요"])]
check("추천 후보는 모두 좌표가 있음", cand["x"].notna().all(), int(cand["x"].isna().sum()))
G=json.load(open("data/raw/boundary/daegu_hjd_20260701.geojson",encoding="utf-8"))["features"]
GP={g:prep(unary_union([shape(f["geometry"]) for f in G if f["properties"]["sggnm"]==g]).buffer(0.003)) for g in GU}
DG=prep(unary_union([unary_union([shape(f["geometry"]) for f in G])]).buffer(0.003))
JANG={"PUB:화장시설","PUB:봉안시설","PUB:자연장지","PUB:묘지"}
# 대구 도시철도 2호선의 경산 구간 역(정평·임당·영남대)은 대구 시내에서 바로 이어지는 대구 노선이라 대구 주민 대안으로 둠
METRO_OUT=lambda fid,addr: str(fid).startswith(("P:지하철:","P:무인민원:지하철:")) and "경산시" in str(addr)   # 역 안 무인민원발급기(영남대역)도 같은 경산 구간
c2=cand[~cand["업종코드"].isin(JANG)&~cand.apply(lambda r: METRO_OUT(r["fid"],r["주소"]),axis=1)]
out_gu=[f for f,g,x,y in zip(c2["fid"],c2["구군"],c2["x"],c2["y"]) if g in GP and not GP[g].contains(Point(x,y))]
check("추천 후보가 적힌 구·군 경계 안에 있음 (경계에서 300m 여유)", not out_gu, out_gu[:10])
out_dg=[f for f,x,y in zip(c2["fid"],c2["x"],c2["y"]) if not DG.contains(Point(x,y))]
check("추천 후보가 대구 안에 있음 (대구시립 장사시설, 대구 도시철도 경산 구간 역 제외)", not out_dg, out_dg[:10])
# 3) 공공시설
P=pd.read_csv("data/processed/public_facilities.csv",dtype=str,keep_default_na=False)
DAEGU_RE=re.compile(r"(^|\|)\s*(대구광역시|대구시|대구 )|(^|\|)\s*(경상북도|경북)\s*군위군")
wrong=P[(P["주소"]!="")&~P["주소"].map(lambda a: bool(DAEGU_RE.search(a)))&~P["업종코드"].isin(JANG)&~P["좌표근거"].str.startswith("브이월드 장소")
        &~P.apply(lambda r: METRO_OUT(r["fid"],r["주소"]),axis=1)]
check("공공시설 주소가 모두 대구 (해운대구 같은 다른 지역 없음)", wrong.empty, wrong[["상호","주소"]].head().values.tolist())
check("공공시설 번호가 겹치지 않음", P["fid"].is_unique)
# 4) 걷는 길
fw=pd.read_csv("data/processed/facility_walk.csv",dtype=str)
check("좌표 있는 시설은 모두 걷는 길 연결 지점이 있음", set(F.loc[F["x"].notna(),"fid"])<=set(fw["fid"]), len(set(F.loc[F["x"].notna(),"fid"])-set(fw["fid"])))
# 5) 대안 찾기 엔진 검사
r=subprocess.run([sys.executable,"engine/test_recommend.py"],capture_output=True,text=True)
last=[l for l in r.stdout.splitlines() if l.startswith("실패")]
check("대안 찾기 엔진 검사", r.returncode==0, "\n".join(last[-5:]) or r.stderr[-500:])
print(f"\n통과 {ok_n} / 실패 {len(bad)}")
if bad: print("실패한 검사:", bad); sys.exit(1)
