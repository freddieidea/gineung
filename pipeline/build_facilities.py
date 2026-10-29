# 시설 데이터베이스 (독립 점검 반영: 정신병원·호프·진료과 상호 규칙 수정): 상가 생활시설 가게 + 인허가 대조 결과 + 인허가에만 있는 가게 + 공공 자료
# + 심평원 요양기관 목록으로 의료기관 확인(10/14). 결과: data/processed/facilities.csv
import pandas as pd, numpy as np, json, glob, re, sys
sys.path.insert(0,"pipeline"); from name_signals import conflicts, reclass, other_business
L=json.load(open("data/processed/industry_list.json",encoding="utf-8")); CODE={x["소분류"]:x["code"] for x in L}; NAME={x["code"]:x["소분류"] for x in L}
M=json.load(open("data/processed/industry_function_map.json",encoding="utf-8")); life={i["code"] for i in M["items"] if i["life_facility"]}
# ---- 1) 상가 가게 ----
S=pd.read_csv("data/raw/소상공인시장진흥공단_상가(상권)정보_대구_202606.csv",dtype=str,
  usecols=["상가업소번호","상호명","지점명","상권업종소분류코드","표준산업분류명","시군구명","행정동명","도로명주소","경도","위도"])
S=S[S["상권업종소분류코드"].isin(life)].copy()
R=pd.concat([pd.read_csv(p,dtype=str) for p in glob.glob("data/work/match_*.csv")]); assert R["상가업소번호"].is_unique
R=R[R["상가업소번호"].isin(S["상가업소번호"])]; assert len(R)==len(S), (len(R),len(S))  # 생활시설에서 빠진 업종의 대조 결과는 버림
S=S.merge(R.drop(columns=["업종코드","구군"]),on="상가업소번호",how="left",validate="1:1")
A=pd.DataFrame({"fid":"S:"+S["상가업소번호"],"출처":"상가","상호":(S["상호명"].fillna("")+" "+S["지점명"].fillna("")).str.strip(),
  "업종코드":S["상권업종소분류코드"],"표준산업분류":S["표준산업분류명"],"구군":S["시군구명"],"행정동":S["행정동명"],"주소":S["도로명주소"],
  "경도":S["경도"].astype(float),"위도":S["위도"].astype(float),"전화":"","인허가상태":S["인허가상태"],"인허가id":S["인허가id"],"인허가업종":S["인허가업종"],
  "업태":S["업태"],"진료과목":S["진료과목"],"의료기관종별":S["의료기관종별"],"폐업일자":S["폐업일자"],
  "같은자리새가게":"","그외인허가":S["그외인허가"].fillna("")})
# 인허가 상호·전화 (10/15): 카카오맵 대조 때 상가 상호로 못 찾으면 인허가 상호로 한 번 더 찾고, 상가 자료에 없는 전화번호는 인허가 전화번호로 보여 줌
_LDN=pd.read_csv("data/processed/localdata_daegu.csv",dtype=str,usecols=["ld_id","사업장명","전화번호"]).drop_duplicates("ld_id").set_index("ld_id")
_id1=A["인허가id"].fillna("").str.split("|").str[0]
A["인허가상호"]=_id1.map(_LDN["사업장명"]).fillna("")
_ph=_id1.map(_LDN["전화번호"]).fillna("").str.replace(r"[^0-9]","",regex=True)
_ph=_ph.where(_ph.str.match(r"^0\d{8,10}$") & ~_ph.str.match(r"^0\d{1,2}0{6,8}$"),"")
_fmt=lambda d: (f"{d[:2]}-{d[2:-4]}-{d[-4:]}" if d.startswith("02") else f"{d[:3]}-{d[3:-4]}-{d[-4:]}") if d else ""
A.loc[A["인허가상태"].eq("영업"),"전화"]=_ph[A["인허가상태"].eq("영업")].map(_fmt)
A["업종보정"]=""
ice=(A["업종코드"]==CODE["슈퍼마켓"])&A["상호"].str.replace(" ","").str.contains("아이스크림할인|아이스크림마트|무인아이스크림")
A.loc[ice,"업종보정"]="슈퍼마켓→아이스크림 할인점 (상호 근거)"; A.loc[ice,"업종코드"]=CODE["아이스크림 할인점"]
def _reclass(D):   # 이름만으로 업종이 분명한 체인·형태(파파존스→피자, 코인빨래방→셀프 빨래방 등)는 업종을 바로잡음 (name_signals.RECLASS)
    for i in D.index:
        to=reclass(D.at[i,"상호"],NAME.get(D.at[i,"업종코드"],""))
        if to: D.at[i,"업종보정"]=f'{NAME[D.at[i,"업종코드"]]}→{to} (상호 근거)'; D.at[i,"업종코드"]=CODE[to]
_reclass(A)
cf=[conflicts(n,NAME[c]) for n,c in zip(A["상호"],A["업종코드"])]
A["업종확인필요"]=["상호와 업종이 어긋남: "+"; ".join(b) if b else "" for _,b in cf]
A["영업근거"]=np.where(A["인허가상태"]=="영업","상가+인허가 영업","상가")
bad=A["인허가상태"].isin(["폐업","휴업","말소 등"])
old=(A["인허가상태"]=="폐업")&(A["폐업일자"].fillna("9999")<"2020-01-01")  # 오래전 폐업 기록인데 상가에 있으면 다시 문을 열었을 수 있어 단정하지 않음
A["대안후보"]=np.where(old,"확인 필요",np.where(bad,"아니요","예"))
A.loc[(A["업종확인필요"]!="")&(A["대안후보"]=="예"),"대안후보"]="확인 필요"  # 상호와 업종이 어긋나면 실시간 분류 확인 전까지 단정하지 않음
A["제외사유"]=np.where(bad|old,"인허가상 "+A["인허가상태"].fillna("")+np.where(A["폐업일자"].fillna("")!=""," ("+A["폐업일자"].fillna("")+")",""),"")
# ---- 2) 인허가에만 있는 가게 ----
O=pd.concat([pd.read_csv(p,dtype=str) for p in glob.glob("data/work/ldonly_*.csv")]); assert O["ld_id"].is_unique
from facility_rules import clinic_type, ld_type   # 인허가 업종 → 상가 업종 규칙 (시설 변화 관리와 함께 씀, pipeline/facility_rules.py)
O["업종코드"]=O.apply(ld_type,axis=1); O=O[O["업종코드"].notna()].copy()
MED={"clinics","hospitals","pharmacies"}
O["med"]=O["slug"].isin(MED)
B=pd.DataFrame({"fid":"L:"+O["ld_id"],"출처":"인허가","상호":O["사업장명"],"업종코드":O["업종코드"],"표준산업분류":np.where(O["인허가업종"]=="생활_이용업","이용업",""),"구군":O["구군"],"행정동":"","주소":O["도로명주소"],
  "경도":O["경도"].astype(float),"위도":O["위도"].astype(float),"전화":O["전화번호"].fillna(""),"인허가상태":"영업","인허가id":O["ld_id"],"인허가업종":O["인허가업종"],
  "업태":O["업태구분명"],"진료과목":O["진료과목내용명"],"의료기관종별":O["의료기관종별명"],"폐업일자":"","같은자리새가게":"","그외인허가":"","업종보정":"",
  "업종확인필요":np.where(O["업종코드"].isin([CODE["기타 한식 음식점"],CODE["기타 일식 음식점"]]),"인허가 업태만으로는 세부 종류를 알 수 없음",""),
  "영업근거":np.where(O["med"],"인허가만(의료기관 등록)","인허가만(영업 확인 필요)"),
  "대안후보":np.where(O["med"],"예","확인 필요"),"제외사유":""})
# 인허가 원자료에 다른 지역 주소가 섞인 경우(예: 동구청 자료에 경산시 주소) 추천하지 않음
import re as _re
_DG=_re.compile(r"^\s*(대구광역시|대구시|대구 |경상북도 군위군|경북 군위군)")
B=B.reset_index(drop=True); _reclass(B)
_nm=lambda c: NAME.get(c, c.split(":",1)[1] if ":" in str(c) else c)
_bc=[conflicts(n,_nm(c)) for n,c in zip(B["상호"],B["업종코드"])]
_bm=pd.Series([bool(b) for _,b in _bc],index=B.index)
B.loc[_bm,"업종확인필요"]=["상호와 업종이 어긋남: "+"; ".join(b) for (_,b),m in zip(_bc,_bm.tolist()) if m]
B.loc[_bm&(B["대안후보"]=="예"),"대안후보"]="확인 필요"
_nd=~B["주소"].fillna("").map(lambda a: bool(_DG.search(a)) or a.strip()=="")
B.loc[_nd,"대안후보"]="아니요"; B.loc[_nd,"제외사유"]="주소가 대구가 아님 (인허가 원자료 오류)"
print("인허가 자료 중 대구 밖 주소",int(_nd.sum()))
# 상호로 보아 아예 다른 업종의 사무실(예: 피자집으로 등록된 'OO부동산')은 그 업종 대안으로 안내하지 않음 (독립 점검 5차)
for _D in (A,B):
    for i in _D.index:
        ob=other_business(_D.at[i,"상호"],_nm(_D.at[i,"업종코드"]))
        if ob and _D.at[i,"대안후보"]!="아니요": _D.at[i,"대안후보"]="아니요"; _D.at[i,"제외사유"]=ob
C=pd.read_csv("data/processed/public_facilities.csv",dtype=str)
C2=pd.DataFrame({"fid":C["fid"],"출처":"공공","상호":C["상호"],"업종코드":C["업종코드"],"표준산업분류":"","구군":C["구군"],"행정동":"","주소":C["주소"],
  "경도":pd.to_numeric(C["경도"]),"위도":pd.to_numeric(C["위도"]),"전화":C["전화"].fillna(""),"인허가상태":"","인허가id":"","인허가업종":"","업태":"","진료과목":"","의료기관종별":"",
  "폐업일자":"","같은자리새가게":"","그외인허가":np.where(C["표시"].fillna("")=="공원운동시설","공원운동시설",""),"업종보정":"","업종확인필요":"",
  "영업근거":"공공 자료 ("+C["자료기준일"].fillna("")+", "+C["좌표근거"]+")","대안후보":C["대안후보"],"제외사유":np.where(C["대안후보"]=="좌표 필요","주소의 좌표를 아직 못 찾음"+np.where(C["제외사유"].fillna("")!="","; "+C["제외사유"].fillna(""),""),C["제외사유"].fillna("")),"참고":C["참고"].fillna("")})
F=pd.concat([A,B,C2],ignore_index=True)
# 같은자리새가게 칸은 비워 둠: 좌표 20m 안 같은 업종으로 짝지어 같은 건물 이웃 가게가 섞였음. 이 자리 새 가게는 build_closures.py(층·호까지 같은 칸 + 폐업 뒤 개업)가 정함
# 함께 받은 인허가 가운데 '영업 중'인 것만 근거로 씀. 인허가 이름 뒤에 '(폐업)'이 붙으면 문 닫은 인허가
#  (10/14 저녁 고침: 전에는 인허가 이름 바로 뒤만 보아 '안전상비의약품 판매업소(폐업)'을 영업 중으로 읽었음 → 상비약 235곳·종량제 34곳이 잘못 표시됐었음)
_lic=F["그외인허가"].fillna("").str.split("|")
for flag,kw in [("상비약판매","안전상비의약품"),("종량제봉투판매","쓰레기종량제봉투"),("담배판매","담배소매업")]:
    F[flag]=_lic.map(lambda xs, kw=kw: any(kw in x and not x.strip().endswith("(폐업)") for x in xs))
F["도매가능성"]=F["상호"].fillna("").str.replace(" ","").str.contains("도매|식자재|도소매|총판")  # 개인이 조금씩 살 수 있는지 확인 필요
F["업종"]=F["업종코드"].map(lambda c: NAME.get(c, c.split(":",1)[1] if ":" in str(c) else c))
assert F["fid"].is_unique and pd.to_numeric(F.loc[F["대안후보"].isin(["예","확인 필요"]),"경도"]).between(128.3,129.0).all()
F["공원운동시설"]=F["그외인허가"]=="공원운동시설"
# 주민이 이용하는 우체국이 아닌 곳: 우편집중국(우편물 분류 시설)·군사우편(군 시설)
_po=(F["업종코드"]=="PUB:우체국")&F["상호"].fillna("").str.contains("집중국|군사|물류")
F.loc[_po,"대안후보"]="아니요"; F.loc[_po,"제외사유"]="우편물 처리 시설·군 시설이라 주민이 이용하는 우체국이 아님"
# 떡집인데 표준산업분류가 과자·제과로 적혀 '한과·과자' 종류에 들어가던 가게: 상호에 '떡'이 있으면 떡집으로 (독립 점검 지적)
_tk=(F["업종코드"]==CODE["떡/한과"])&F["상호"].fillna("").str.contains("떡")&F["표준산업분류"].isin(["빵류; 과자류 및 당류 소매업","제과점업"])
F.loc[_tk,"업종보정"]="상호에 '떡' → 떡집 (표준산업분류의 과자·제과 무시)"; F.loc[_tk,"표준산업분류"]=""
# 공공체육시설 자료에서 소프트볼장이 야구장으로 들어간 경우: 다른 종목이라 기타 전문 체육시설로 (독립 점검 지적)
_sb=(F["업종코드"]=="PUB:야구장")&F["상호"].fillna("").str.contains("소프트볼")
F.loc[_sb,"업종보정"]="상호에 '소프트볼' → 기타 전문 체육시설"; F.loc[_sb,"업종코드"]="PUB:기타전문체육"
print("우체국 아님",int(_po.sum()),"떡집 바로잡음",int(_tk.sum()),"소프트볼장",int(_sb.sum()))
# ---- 3) 심평원 요양기관 목록(2026.6)으로 의료기관 확인 (pipeline/hira.py) ----
import hira as _hira
_ld=pd.read_csv("data/processed/localdata_daegu.csv",dtype=str,usecols=["ld_id","인허가일자"]).dropna()
F,_rep=_hira.apply(F,clinic_type,CODE,dict(zip(_ld["ld_id"],_ld["인허가일자"])))
print("심평원 대조",json.dumps({k:v for k,v in _rep.items() if k!="방법별"},ensure_ascii=False))
F["업종"]=F["업종코드"].map(lambda c: NAME.get(c, c.split(":",1)[1] if ":" in str(c) else c))
for _c in ["상비약판매","종량제봉투판매","담배판매","도매가능성","공원운동시설"]: F[_c]=F[_c].map(lambda v: v is True or str(v)=="True")
# 상호 전수 점검(screen_names.py, 10/14 저녁): 1단계(Sonnet)가 찾고 2단계(Opus)가 '확실하다'고 확인한 가게만 '업종 확인 필요'로 (추천하지 않음)
#  심평원과 대조된 의료기관은 진료과 자료로 판정하므로 상가 업종과 상관없어 제외
import os as _os
if _os.path.exists("data/work/name_screen_flags.csv"):
    _sc=pd.read_csv("data/work/name_screen_flags.csv",dtype=str).fillna("")
    _sc=dict(zip(_sc["fid"],_sc["실제"]))
    _scm=F["fid"].isin(_sc)&(F["심평원id"].fillna("")=="")&(F["대안후보"]=="예")
    F.loc[_scm,"업종확인필요"]="상호 전수 점검: 상호가 다른 일을 가리킴 ("+F.loc[_scm,"fid"].map(_sc)+")"
    F.loc[_scm,"대안후보"]="확인 필요"
    print("상호 전수 점검으로 업종 확인 필요",int(_scm.sum()))
# 상호가 없는 가게: 상호 칸이 '업소명없음'이거나 업종 이름 그대로(예: 상호 '슈퍼마켓', '철물/공구소매업')면 어느 가게인지 특정할 수 없어 안내하지 않음 (독립 점검 3차, 10/14)
import facility_rules as _FR   # 규칙은 한 곳(facility_rules.no_name)에만 두고 시설 변화 관리와 함께 씀
_phm=F["출처"].isin(["상가","인허가"])&pd.Series([_FR.no_name(n,u) for n,u in zip(F["상호"].fillna(""),F["업종"].fillna(""))],index=F.index)
F.loc[_phm,"대안후보"]="아니요"; F.loc[_phm,"제외사유"]="상호가 없어 어느 가게인지 특정할 수 없음"
print("상호가 없는 가게",int(_phm.sum()))
assert F["fid"].is_unique
# 같은 가게가 상가 자료에 두 번 등록된 경우(이름·업종·주소가 같고 등록 번호만 다름, 예: 2022년 등록과 2024년 등록): 가장 최근 등록만 남김
import re as _re
S_=F[(F["출처"]=="상가")&(F["대안후보"]=="예")].copy()
S_["k"]=S_["상호"].fillna("").map(lambda x:_re.sub(r"\s|\(.*?\)","",x))+"|"+S_["업종코드"]+"|"+S_["주소"].fillna("").map(lambda x:_re.sub(r"\s","",x))
S_["ym"]=S_["fid"].str[8:14]
dupi=S_[S_.duplicated("k",keep=False)].sort_values("ym",ascending=False)
drop=dupi.index[dupi.duplicated("k",keep="first")]
F.loc[drop,"대안후보"]="아니요"; F.loc[drop,"제외사유"]="같은 가게가 두 번 등록됨 (더 최근 등록만 남김)"
print("상가 중복 등록 정리",len(drop))
# 공공 자료에 같은 시설이 두 번 들어간 경우(같은 종류·같은 이름·20m 안, 예: 서재체육공원 두 건): 하나만 남김 (10/15)
#  버스정류장은 같은 이름이라도 길 건너편끼리는 다른 정류장이라 제외
_P=F[(F["출처"]=="공공")&(F["대안후보"]=="예")&(F["업종코드"]!="PUB:버스정류장")].copy()
_P["k"]=_P["업종코드"]+"|"+_P["상호"].fillna("").str.replace(r"\s","",regex=True)
_dropP=[]
for _k,_g in _P[_P.duplicated("k",keep=False)].groupby("k"):
    _keep=[]
    for _i,_r in _g.sort_values("fid").iterrows():
        if any(np.hypot((_r["경도"]-F.at[j,"경도"])*90000,(_r["위도"]-F.at[j,"위도"])*111000)<20 for j in _keep): _dropP.append(_i)
        else: _keep.append(_i)
F.loc[_dropP,"대안후보"]="아니요"; F.loc[_dropP,"제외사유"]="같은 시설이 공공 자료에 두 번 등록됨 (하나만 남김)"
print("공공 자료 중복 정리",len(_dropP))
# 공공 자료의 전화번호 정리 (10/15): 000-000-0000 같은 자리 채움 번호는 지우고, 같은 종류 시설 여러 곳(3곳 이상)이 같은 번호면
#  그 시설 번호가 아니라 관리하는 구청 부서·기관 번호이므로 그렇다고 적음 (예: 경로당 296곳이 053-665-2532)
_pp=F["출처"]=="공공"
F.loc[_pp&F["전화"].fillna("").str.match(r"^0\d{1,2}-?0{3,4}-?0{4}$"),"전화"]=""
_t=F[_pp&F["전화"].fillna("").str.strip().ne("")]
_sh=_t.groupby(["업종코드","전화"])["상호"].nunique(); _sh=set(_sh[_sh>=3].index)
_m=[(u,t) in _sh for u,t in zip(F["업종코드"],F["전화"])]
F.loc[_m,"전화"]=F.loc[_m,"전화"]+" (관리 기관 번호)"
print("관리 기관 번호로 표시",sum(_m))
# 상가 자료와 공식 자료에 같은 시설이 함께 있는 경우: 공식 자료 쪽으로 안내 (10/15)
#  장례식장: 상가 '장례식장' 업종 가게 중 공식 장례식장 목록과 도로명 주소가 같은 곳은 겹친 것으로 보고 뺌 (공식 쪽에 '2026년 상가 자료에도 있음'을 적음)
def _ak(a):
    a=_re.sub(r"\(.*?\)","",str(a)).replace(" ",""); m=_re.search(r"([가-힣0-9]+(?:로|길)\d+(?:-\d+)?)",a); return m.group(1) if m else None
_pub=F[F["업종코드"]=="PUB:장례식장"]; _pk={}
for _i,_r in _pub.iterrows():
    k=_ak(_r["주소"]); 
    if k: _pk.setdefault(k,[]).append(_i)
_nd=0
for _i,_r in F[(F["출처"]=="상가")&(F["업종"]=="장례식장")&(F["대안후보"]!="아니요")].iterrows():
    k=_ak(_r["주소"])
    if k in _pk:
        F.at[_i,"대안후보"]="아니요"; F.at[_i,"제외사유"]="공식 장례식장 목록(장사시설 현황)의 같은 주소 장례식장으로 안내"; _nd+=1
        for j in _pk[k]:
            if "2026년 상가 자료에도 있음" not in str(F.at[j,"참고"]): F.at[j,"참고"]=str(F.at[j,"참고"])+". 2026년 상가 자료에도 있음"
print("상가·공식 장례식장 겹침 정리",_nd)
F.to_csv("data/processed/facilities.csv",index=False,encoding="utf-8")
print("시설",len(F)); print(F.groupby(["출처","대안후보"]).size().to_string())
print("업종 보정",(F["업종보정"]!="").sum(),"업종 확인 필요",(F["업종확인필요"]!="").sum())
print("상비약",F["상비약판매"].sum(),"종량제",F["종량제봉투판매"].sum(),"담배",F["담배판매"].sum())
print(F[F["출처"]=="인허가"].groupby("업종").size().sort_values(ascending=False).head(15).to_string())
