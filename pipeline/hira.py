# 심평원 '전국 병의원 및 약국 현황'(2026.6)으로 의료기관을 확인한다. build_facilities.py가 불러 씀.
#  match(F): 우리 의료 시설 ↔ 심평원 요양기관 짝짓기
#   짝 조건 (하나라도 맞으면): ① 100m 안 + 상호 거의 같음(10m 안이면 조금 덜 같아도 됨)  ② 도로명주소 같음 + 상호 거의 같음
#   ③ 병원급은 300m 안 + 상호 매우 비슷 (큰 병원은 건물 좌표가 넓게 찍힘)
#   ④ 상가 상호가 법인 이름(…의료재단)이고 같은 건물에 병원급 기관이 하나뿐  ⑤ 같은 건물 + 고유 이름이 한쪽에 다 들어 있음
#   ⑥ 보건소·지소·진료소는 지역 이름을 뺀 이름이 같음 (좌표 차이는 따로 표시)
#   ⑦ 같은 건물 + 짧은 이름 글자가 긴 이름 안에 순서대로 다 들어 있음(6자 이상)  ⑧ 200m 안 + 고유 이름 4자 이상이 거의 같음 ('좌표 차이' 표시)
#   같은 건물에서 자모 하나만 다른 표기(래미안↔레미안)도 같은 곳으로 봄
#   상호 정리: 괄호 풀이말 빼기, 영문 글자는 한글 읽기로(W→더블유), 소아청소년과=소아과, 비뇨의학과=비뇨기과
#   공통: 진료과 이름(내과·외과 등)이 서로 다르면 짝짓지 않음. 기관 종류가 다르면 상호가 거의 같고 같은 자리일 때만 짝짓고 '종별 다름' 표시.
#  apply(F, clinic_type, CODE): 짝 결과를 시설표에 반영 (중복 정리, 종류 바로잡기, 목록에 없는 시설 보류, 목록에만 있는 기관 추가)
import pandas as pd, numpy as np, re, json, hashlib
from scipy.spatial import cKDTree
from rapidfuzz import fuzz
H="data/raw/hira"
LAT={"A":"에이","B":"비","C":"씨","D":"디","E":"이","F":"에프","G":"지","H":"에이치","I":"아이","J":"제이","K":"케이","L":"엘","M":"엠","N":"엔",
     "O":"오","P":"피","Q":"큐","R":"알","S":"에스","T":"티","U":"유","V":"브이","W":"더블유","X":"엑스","Y":"와이","Z":"제트"}
REG=r"대구광역시|대구|중구|동구|서구|남구|북구|수성구|달서구|달성군|군위군"
def norm(s):
    s=str(s or "").upper()
    s=re.sub(r"의료법인|재단법인|사단법인|사회복지법인|학교법인|\((의|재|사|복지|학|주|유)\)|㈜|주식회사","",s)
    s=re.sub(r"\([^()]*\)","",s)                       # 괄호 안 풀이말은 뺌: 뉴(NEW)·범어더블유(W)·우리미(美)
    s=s.replace("소아청소년과","소아과").replace("비뇨의학과","비뇨기과")   # 같은 진료과의 옛·새 이름
    s=re.sub(r"\s|[()\[\]·.,;'\"\-_/&]","",s)
    s="".join(LAT.get(ch,ch) for ch in s)
    return s.lower()
def core_pub(s):
    s=norm(s); s=re.sub(REG,"",s)
    s=re.sub(r"(\w+?)[읍면](?=\w*보건)",r"\1",s)
    return s
SPEC=["이비인후과","정형외과","신경외과","성형외과","흉부외과","산부인과","비뇨기과","정신건강의학과","재활의학과","마취통증의학과",
      "가정의학과","영상의학과","신경과","피부과","안과","내과","외과","소아과","치과","한의원","약국","요양병원","한방병원"]
def spec(n):
    out=set(); t=n
    for s in SPEC:
        if s in t: out.add(s); t=t.replace(s," ")
    return out
def sim(a,b):
    if not a or not b: return 0
    if a==b: return 100
    s=fuzz.ratio(a,b)
    if min(len(a),len(b))>=3 and (a in b or b in a): s=max(s,92)
    if sorted(a)==sorted(b): s=max(s,90)   # 글자 순서만 다름 (약국 백화점 ↔ 백화점약국)
    return s
GEN=re.compile(r"의원|병원|약국|치과|한의원|연합|센터|클리닉|점$")
def jamo(t):
    out=[]
    for ch in t:
        c=ord(ch)-0xAC00
        if 0<=c<11172: out+= [chr(0x1100+c//588), chr(0x1161+(c%588)//28)] + ([chr(0x11A7+c%28)] if c%28 else [])
        else: out.append(ch)
    return out
def typo1(a,b):
    # 받침·모음 한 글자만 다른 표기 차이 (래미안↔레미안, 가톨릭↔카톨릭). 끝의 '의원'은 빼고 비교
    a=re.sub(r"의원$","",a); b=re.sub(r"의원$","",b)
    if a==b or min(len(a),len(b))<3: return a==b and len(a)>=3
    x,y=jamo(a),jamo(b)
    if abs(len(x)-len(y))>1: return False
    from rapidfuzz.distance import Levenshtein
    return Levenshtein.distance(x,y)<=1
def subseq(a,b):
    # 짧은 이름 글자가 긴 이름 안에 순서대로 다 들어 있음 (꿈키우다봄이비인후과연합의원 ⊂ 꿈키우다소아과봄이비인후과연합의원)
    a,b=(a,b) if len(a)<=len(b) else (b,a)
    if len(a)<6: return False
    it=iter(b); return all(ch in it for ch in a)
def part(a,b):
    # 같은 건물 안에서만 쓰는 부분 일치: 일반 낱말(의원·약국·점 등)을 뺀 고유 이름이 3자 이상이고 한쪽에 다 들어 있음
    ca,cb=GEN.sub("",a),GEN.sub("",b)
    ca=re.sub(r"(내과|외과|소아청소년과|정형|신경|이비인후과|피부과|안과|산부인과|비뇨의학과|비뇨기과|마취통증의학과|정신건강의학과|재활의학과|가정의학과)","",ca)
    cb=re.sub(r"(내과|외과|소아청소년과|정형|신경|이비인후과|피부과|안과|산부인과|비뇨의학과|비뇨기과|마취통증의학과|정신건강의학과|재활의학과|가정의학과)","",cb)
    if min(len(ca),len(cb))<3: return False
    return ca in cb or cb in ca
ADDR=re.compile(r"대구광역시\s+(\S+?[구군])\s+(?:\S+?[읍면]\s+)?(\S+?(?:로|길))\s*(\d+(?:-\d+)?)")
def akey(s):
    m=ADDR.search(str(s or "")); return "|".join(m.groups()) if m else ""
HOSP={"종합병원","상급종합","병원","요양병원","정신병원","한방병원","치과병원"}
FAM={"Q10101":{"종합병원","상급종합"},"Q10102":{"병원","정신병원","종합병원"},"Q10103":{"치과병원","치과의원"},"Q10104":{"한방병원","한의원"},
     "Q10105":{"요양병원"},"Q10210":{"치과의원","치과병원"},"Q10211":{"한의원","한방병원"},"G21501":{"약국"}}
for c in ["Q10201","Q10202","Q10203","Q10204","Q10205","Q10206","Q10207","Q10208","Q10209","Q10212"]: FAM[c]={"의원","병원"}
PUBF={"보건소","보건지소","보건진료소"}
def load():
    A=pd.concat([pd.read_csv(f"{H}/daegu_병원정보서비스.csv",dtype=str),pd.read_csv(f"{H}/daegu_약국정보서비스.csv",dtype=str)],ignore_index=True)
    return A[A["좌표(X)"].notna()].reset_index(drop=True)
def match(F0):
    F=F0.copy()
    pubtypes=sorted(t for t in F["업종코드"].unique() if str(t).startswith("PUB:") and "보건" in str(t))
    F=F[F["업종코드"].isin(list(FAM)+pubtypes)].reset_index(drop=True)
    A=pd.concat([pd.read_csv(f"{H}/daegu_병원정보서비스.csv",dtype=str),pd.read_csv(f"{H}/daegu_약국정보서비스.csv",dtype=str)],ignore_index=True)
    A=A[A["좌표(X)"].notna()].reset_index(drop=True)
    k=np.cos(np.radians(35.87))*111320
    XY=np.c_[A["좌표(X)"].astype(float)*k,A["좌표(Y)"].astype(float)*110540]
    FP=np.c_[F["경도"].astype(float)*k,F["위도"].astype(float)*110540]
    tree=cKDTree(XY)
    A["nm"]=A["요양기관명"].map(norm); A["sp"]=A["nm"].map(spec); A["ak"]=A["주소"].map(akey); A["cp"]=A["요양기관명"].map(core_pub)
    byaddr={}
    for j,a in A.iterrows():
        if a["ak"]: byaddr.setdefault(a["ak"],[]).append(j)
    rows=[]
    for i,f in F.iterrows():
        code=f["업종코드"]; ispub=code.startswith("PUB:")
        fam=PUBF if ispub else FAM[code]
        nm=norm(f["상호"]); sp=spec(nm); ak=akey(f["주소"]); corp=bool(re.search(r"재단|의료원|의료법인",str(f["상호"])))
        cand=set(tree.query_ball_point(FP[i],r=3000 if ispub else 300))|set(byaddr.get(ak,[]))
        best=None
        for j in cand:
            a=A.iloc[j]; d=float(np.hypot(*(FP[i]-XY[j]))); same=bool(ak) and ak==a["ak"]
            if sp and a["sp"] and not (sp & a["sp"]): continue
            if ispub:
                if a["종별코드명"] not in PUBF: continue
                sc=100 if core_pub(f["상호"])==a["cp"] else sim(core_pub(f["상호"]),a["cp"])
                if sc<92: continue
                how="보건기관 이름"; flag="좌표 차이 큼" if d>300 else ""
            else:
                sc=sim(nm,a["nm"]); how=None; flag=""
                if a["종별코드명"] in fam:
                    if (sc>=92 and d<=100) or (sc>=85 and d<=10) or (d<=10 and typo1(nm,a["nm"])): how="100m·상호" if sc>=92 else "같은 건물·상호 비슷"
                    elif sc>=85 and same: how="주소·상호"
                    elif sc>=90 and d<=300 and a["종별코드명"] in HOSP: how="병원급 300m·상호"
                    elif corp and a["종별코드명"] in HOSP and (d<=30 or same): how="법인명·같은 건물"; sc=80
                    elif (d<=10 or same) and part(nm,a["nm"]): how="같은 건물·고유 이름"; sc=max(sc,86)
                    elif (d<=10 or same) and subseq(nm,a["nm"]): how="같은 건물·글자 순서 포함"; sc=max(sc,85)
                    elif sc>=92 and d<=200 and len(GEN.sub("",nm))>=4: how="200m·고유 상호"; flag="좌표 차이"
                elif sc>=92 and (d<=30 or same):
                    how="종별 다름·상호"; flag="종별 다름"
                if not how: continue
            key=(sc,-d)
            if best is None or key>best[0]: best=(key,j,sc,d,how,flag)
        if best:
            _,j,sc,d,how,flag=best; a=A.iloc[j]
            # 법인명 규칙은 같은 건물에 병원급이 둘 이상이면 고르지 않는다
            if how=="법인명·같은 건물":
                n=sum(1 for jj in cand if A.iloc[jj]["종별코드명"] in HOSP and (np.hypot(*(FP[i]-XY[jj]))<=30 or (ak and A.iloc[jj]["ak"]==ak)))
                if n>1: continue
            rows.append({"fid":f["fid"],"상호":f["상호"],"업종코드":code,"업종":f["업종"],"hira_id":a["암호화요양기호"],"hira_name":a["요양기관명"],
                         "hira_종별":a["종별코드명"],"hira_주소":a["주소"],"hira_전화":a["전화번호"],"점수":sc,"거리m":round(d,1),"방법":how,"표시":flag})
    return pd.DataFrame(rows), A
HIRA_DATE="2026-06-01"
def disp_name(n):
    n=str(n).strip()
    n=re.sub(r"^(의료법인|재단법인|사단법인|사회복지법인|학교법인)\s*","",n); n=re.sub(r"^\((의|재|사|복지|학)\)\s*","",n)
    m=re.match(r"^\S*(의료재단|의료사단|재단)\s+(.+)$",n)
    return re.sub(r"\s+"," ",m.group(2) if m else n).strip()
def apply(F, clinic_type, CODE, ldate):
    """F: 시설표, clinic_type(name,kind)->업종코드, CODE: 업종명→코드, ldate: 인허가id→인허가일자"""
    M,A=match(F)
    M.to_csv("data/processed/hira_match.csv",index=False,encoding="utf-8")
    Fi=F.set_index("fid",drop=False)
    rep={}
    for c in ["심평원id","심평원명","심평원종별"]:
        if c not in F.columns: F[c]=""
    idx={f:i for i,f in zip(F.index,F["fid"])}
    for _,m in M.iterrows():
        i=idx[m["fid"]]; F.at[i,"심평원id"]=m["hira_id"]; F.at[i,"심평원명"]=m["hira_name"]; F.at[i,"심평원종별"]=m["hira_종별"]
    on=F["심평원id"]!=""
    # 1) 심평원(2026.6)에 있는데 그보다 앞서 폐업 처리된 옛 인허가에 붙은 행 → 같은 자리에서 다시 문을 연 것. 영업으로 봄
    re_=on&(F["대안후보"]=="아니요")&(F["인허가상태"]=="폐업")&(F["폐업일자"].fillna("9999")<HIRA_DATE)
    F.loc[re_,"대안후보"]="예"; F.loc[re_,"제외사유"]=""; F.loc[re_,"영업근거"]="심평원 2026.6 등록 (옛 인허가 "+F.loc[re_,"폐업일자"].fillna("")+" 폐업 후 다시 엶)"
    F.loc[re_,"인허가상태"]="심평원 등록 (옛 인허가는 폐업)"; F.loc[re_,"폐업일자"]=""
    rep["옛 폐업 기록이지만 심평원에 있음 → 영업"]=int(re_.sum())
    # 2) 이름은 심평원 공식 이름으로 (법인 이름 앞부분은 뺌). 원래 상호는 참고에 남김
    nm=F.loc[on,"심평원명"].map(disp_name); chg=pd.Series(False,index=F.index)
    chg.loc[on]=(nm.str.replace(" ","")!=F.loc[on,"상호"].fillna("").str.replace(" ","")).values
    F.loc[chg,"참고"]=(F.loc[chg,"참고"].fillna("")+np.where(F.loc[chg,"참고"].fillna("")!="","; ","")+F.loc[chg,"출처"]+" 자료 상호: "+F.loc[chg,"상호"].fillna(""))
    F.loc[on,"상호"]=nm; rep["상호를 심평원 이름으로 바꿈"]=int(chg.sum())
    # 3) 같은 기관이 두 행 이상 → 심평원 좌표에 가장 가까운 행만 남김
    live=F[on&(F["대안후보"]!="아니요")].copy()
    dist=M.set_index("fid")["거리m"].astype(float)
    live["d"]=live["fid"].map(dist)
    live=live.sort_values(["심평원id","d"]); dup=live.index[live.duplicated("심평원id",keep="first")]
    F.loc[dup,"대안후보"]="아니요"; F.loc[dup,"제외사유"]="같은 기관 중복 (심평원 기준 한 기관, 더 가까운 행만 남김)"
    rep["같은 기관 중복 정리"]=int(len(dup))
    # 4) 기관 종류 바로잡기
    HOSPC={CODE["종합병원"],CODE["일반병원"],CODE["요양병원"],CODE["한방병원"],CODE["치과병원"]}
    fix=[]
    for i in F.index[on]:
        code=F.at[i,"업종코드"]; hz=F.at[i,"심평원종별"]; new=None
        if hz=="의원" and code in HOSPC: new=clinic_type(F.at[i,"상호"],"의원")
        elif hz=="정신병원" and code!=CODE["신경/정신과 의원"]: new=CODE["신경/정신과 의원"]
        elif hz in ("종합병원","상급종합") and code!=CODE["종합병원"]: new=CODE["종합병원"]
        elif hz=="요양병원" and code!=CODE["요양병원"]: new=CODE["요양병원"]
        elif hz=="병원" and code==CODE["요양병원"]: new=CODE["일반병원"]
        elif hz=="한방병원" and code==CODE["한의원"]: new=CODE["한방병원"]
        elif hz=="치과병원" and code==CODE["치과의원"]: new=CODE["치과병원"]
        elif hz=="치과의원" and code==CODE["치과병원"]: new=CODE["치과의원"]
        elif hz=="한의원" and code==CODE["한방병원"]: new=CODE["한의원"]
        elif hz=="병원" and code==CODE["종합병원"]: new=CODE["일반병원"]
        if new and new!=code:
            F.at[i,"업종보정"]=(F.at[i,"업종보정"]+"; " if F.at[i,"업종보정"] else "")+f"심평원 종별 '{hz}'에 맞춤"; F.at[i,"업종코드"]=new; fix.append(i)
    rep["기관 종류 바로잡음"]=len(fix)
    # 5) 심평원 목록에 없는 의료기관 → 보류 (단, 2026.5 이후 새로 인허가된 곳은 목록 시점 뒤에 문을 연 것이라 그대로 둠)
    medc=set(FAM)
    miss=F["업종코드"].isin(medc)&~on&(F["대안후보"]=="예")
    newly=F["인허가id"].fillna("").map(lambda x: str(ldate.get(x,""))>="2026-05")
    hold=miss&~newly
    F.loc[hold,"대안후보"]="확인 필요"; F.loc[hold,"제외사유"]="심평원 요양기관 목록(2026.6)에서 찾지 못함 (폐업·이전 가능)"
    rep["심평원 목록에 없어 보류"]=int(hold.sum()); rep["목록 이후 새로 연 곳(유지)"]=int((miss&newly).sum())
    # 6) 심평원 목록에만 있는 기관 추가
    ua=A[~A["암호화요양기호"].isin(M["hira_id"])].copy()
    HMAP={"종합병원":"종합병원","상급종합":"종합병원","병원":"일반병원","요양병원":"요양병원","정신병원":"신경/정신과 의원","한방병원":"한방병원",
          "치과병원":"치과병원","치과의원":"치과의원","한의원":"한의원","약국":"약국"}
    add=[]
    for _,a in ua.iterrows():
        z=a["종별코드명"]
        if z in ("보건소","보건지소","보건진료소"): continue   # 보건기관은 보건복지부 목록을 씀 (심평원 목록의 대율보건진료소는 주소가 지소와 같게 잘못 들어 있음)
        code=clinic_type(a["요양기관명"],"의원") if z=="의원" else CODE.get(HMAP.get(z,""))
        if not code: continue
        gu=str(a["시군구코드명"]).replace("대구","")
        add.append({"fid":"H:"+hashlib.md5(a["암호화요양기호"].encode()).hexdigest()[:12],"출처":"심평원","상호":disp_name(a["요양기관명"]),"업종코드":code,
          "표준산업분류":"","구군":gu,"행정동":"","주소":a["주소"],"경도":float(a["좌표(X)"]),"위도":float(a["좌표(Y)"]),"전화":a["전화번호"] or "",
          "인허가상태":"","인허가id":"","인허가업종":"","업태":"","진료과목":"","의료기관종별":z,"폐업일자":"","같은자리새가게":"","그외인허가":"",
          "업종보정":"","업종확인필요":"","영업근거":"심평원 요양기관 목록 (2026.6)","대안후보":"예","제외사유":"","참고":"",
          "심평원id":a["암호화요양기호"],"심평원명":a["요양기관명"],"심평원종별":z})
    if add: F=pd.concat([F,pd.DataFrame(add)],ignore_index=True)
    rep["심평원 목록에만 있어 추가"]=len(add)
    # 6-2) 기관 부속의원: 교도소·법원 청사·회사 안 의원처럼 그 기관 사람만 쓰는 곳은 주민 대안이 아님
    nmall=F["심평원명"].fillna("")+" "+F["상호"].fillna("")
    closed=nmall.str.contains(r"교도소|구치소|소년원|청사|사내|부대|군병원|공군|육군|해군|보호관찰") & F["업종코드"].isin(set(FAM)) & (F["대안후보"]!="아니요")
    F.loc[closed,"대안후보"]="아니요"; F.loc[closed,"제외사유"]="기관 직원·수용자 전용 의원 (일반 주민 진료처 아님)"
    other=nmall.str.contains(r"부속\s?의원") & ~closed & (F["대안후보"]=="예")
    F.loc[other,"대안후보"]="확인 필요"; F.loc[other,"제외사유"]="기관 부속의원 (일반 주민도 진료받을 수 있는지 확인 필요)"
    rep["기관 전용 의원 제외"]=int(closed.sum()); rep["부속의원 확인 필요"]=int(other.sum())
    # 7) 짝지어진 행: 전화가 비었으면 심평원 전화, 영업 근거에 심평원 표시
    on=F["심평원id"]!=""
    F.loc[on&(F["전화"].fillna("")==""),"전화"]=F.loc[on&(F["전화"].fillna("")==""),"심평원id"].map(A.set_index("암호화요양기호")["전화번호"]).fillna("")
    keep=on&(F["출처"]!="심평원")&(F["대안후보"]=="예")&~F["영업근거"].fillna("").str.contains("심평원")
    F.loc[keep,"영업근거"]=F.loc[keep,"영업근거"].fillna("")+" + 심평원 2026.6"
    rep.update({"짝지음":int(len(M)),"방법별":M["방법"].value_counts().to_dict()})
    json.dump(rep,open("data/work/hira_apply_report.json","w"),ensure_ascii=False,indent=1)
    return F, rep
