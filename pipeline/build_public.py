# 공공시설 목록 만들기 → data/processed/public_facilities.csv
# 좌표: 표준데이터의 좌표를 그대로 쓰고, 주소만 있는 자료는 상가·인허가의 같은 건물 주소 좌표를 씀. 못 찾으면 '좌표 필요'(대안 후보 아님)
import json, glob, io, re, sys, collections, pandas as pd, numpy as np
sys.path.insert(0,"pipeline"); from addr_lookup import key, build
LOOK=build()
GU=["중구","동구","서구","남구","북구","수성구","달서구","달성군","군위군"]
def gu_of(a):
    m=re.search("|".join(GU),str(a or "")); return m.group(0) if m else ""
# 대구 주소인지: "대구광역시·대구시·대구 "로 시작하거나, 2023년 대구에 편입된 군위군의 옛 주소(경상북도 군위군). "해운대구", "강진군 대구면"은 아님
DAEGU_RE=re.compile(r"(^|\|)\s*(대구광역시|대구시|대구 )|(^|\|)\s*(경상북도|경북)\s*군위군")
is_daegu=lambda a: bool(DAEGU_RE.search(str(a or "")))
def std(n):
    d=json.load(open(f"data/raw/public/{n}_전국.json",encoding="utf-8")); m=dict(zip(d["cols_en"],d["cols_kr"]))
    rows=[{m.get(k,k):v for k,v in r.items()} for r in d["rows"]]
    return [r for r in rows if is_daegu((r.get("소재지도로명주소") or "")+"|"+(r.get("소재지지번주소") or ""))]
def raw_csv(pat):
    p=glob.glob(f"data/raw/public/{pat}")[0]; b=open(p,"rb").read()
    for enc in ("utf-8-sig","cp949"):
        try: return pd.read_csv(io.StringIO(b.decode(enc)),dtype=str)
        except Exception: pass
rows=[]
# 원자료 주소 바로잡기 (원자료 파일은 고치지 않고 여기서만, 이유를 참고에 함께 적음)
ADDR_FIX={
 "P:우체국:대구대평리우편취급국":("대구광역시 서구 서대구로42길 42","원자료 주소 '서대구로길 42'는 없는 주소 — 카카오맵에 서대구로42길 42로 나옴(2026-10-15 확인)"),
 "P:정신건강:대구광역 정신건강복지센터":("대구광역시 남구 두류공원로17길 33","원자료에 건물 번호가 빠져 있음 — 대구가톨릭대학교병원(두류공원로17길 33) 라파엘관 5층"),
}
def add(fid,typ,name,addr,lon,lat,tel="",extra="",asof="",flags="",gu=None,cand=None,why=""):
    if fid in ADDR_FIX: addr,_why=ADDR_FIX[fid]; extra=(str(extra)+". " if extra else "")+"주소 바로잡음: "+_why
    if typ=="PUB:우체국" and "군사우편" in str(name): cand,why="아니요","군부대 안에 있는 우체국이라 일반 주민이 이용할 수 없음"
    _st=re.search(r"운영\s?준비\s?중|개관\s?준비|휴관|폐관|폐쇄|폐지",str(name))
    if _st: cand,why="아니요",f"자료의 이름에 '{_st.group(0)}'이라고 나옴"
    src="자료 좌표"
    if lon in (None,"") or lat in (None,""):
        k=key(addr); 
        if k in LOOK.index: lon,lat=LOOK.loc[k,"경도"],LOOK.loc[k,"위도"]; src="같은 건물 주소 좌표"
        else: lon,lat=None,None; src="좌표 필요"
    rows.append({"fid":fid,"출처":"공공","상호":name,"업종코드":typ,"구군":gu if gu is not None else gu_of(addr),"주소":addr,"경도":lon,"위도":lat,"전화":tel or "","좌표근거":src,"참고":extra,"자료기준일":asof,"표시":flags,"대안후보_지정":cand or "","제외사유":why})
# 1) 도서관
for r in std("도서관"):
    t={"공공도서관":"PUB:공공도서관","작은도서관":"PUB:작은도서관"}.get(r["도서관유형"])
    if not t: continue
    hrs=f'평일 {r.get("평일운영시작시각") or "?"}~{r.get("평일운영종료시각") or "?"}, 휴관 {r.get("휴관일") or "?"}'
    op=str(r.get("운영기관명") or "").strip()
    add(f'P:도서관:{r["도서관명"]}:{r.get("소재지도로명주소")}',t,r["도서관명"],r.get("소재지도로명주소"),r.get("경도"),r.get("위도"),r.get("도서관전화번호"),hrs+(f", 운영: {op}" if op else ""),r.get("데이터기준일자"))
# 2) 전통시장
for r in std("전통시장"):
    add(f'P:전통시장:{r["시장명"]}',"PUB:전통시장",r["시장명"],r.get("소재지도로명주소") or r.get("소재지지번주소"),r.get("경도"),r.get("위도"),r.get("전화번호"),f'{r.get("시장유형")}, 점포 {r.get("점포수")}곳, 개설주기 {r.get("시장개설주기")}',r.get("데이터기준일자"))
# 3) 무인민원발급기
for i,r in enumerate(std("무인민원발급")):
    add(f'P:무인민원:{r.get("설치장소")}:{i}',"PUB:무인민원발급기",(r.get("설치장소") or "")+" 무인민원발급기",r.get("소재지도로명주소"),r.get("경도"),r.get("위도"),r.get("전화번호"),"발급 서류: "+(r.get("발급민원종류") or "")[:300],r.get("데이터기준일자"))
# 4) 도시공원
for r in std("도시공원"):
    big=r["공원구분"] in ("근린공원","체육공원","수변공원","문화공원","역사공원","기타","묘지공원")
    sp=(r.get("공원보유시설(운동시설)") or "").strip()
    add(f'P:공원:{r["관리번호"]}',"PUB:공원" if big else "PUB:소공원",r["공원명"],r.get("소재지도로명주소") or r.get("소재지지번주소"),r.get("경도"),r.get("위도"),r.get("전화번호"),
        f'{r["공원구분"]}, 면적 {r.get("공원면적")}㎡'+(f', 운동시설: {sp}' if sp else ""),r.get("데이터기준일자"),"공원운동시설" if sp else "")
# 5) 경로당: 표준데이터(좌표) + 대구시 목록(주소, 표준에 없는 구·군 보충)
S=std("마을회관경로당"); seen=set()
nm=lambda s: re.sub(r"\s|경로당|노인정|\(.*?\)","",str(s))
for r in S:
    if r.get("시설유형")!="경로당": continue
    a=r.get("소재지도로명주소") or r.get("소재지지번주소"); g=gu_of(a); seen.add((g,nm(r["시설명"])))
    add(f'P:경로당:{g}:{r["시설명"]}',"PUB:경로당",r["시설명"],a,r.get("경도"),r.get("위도"),r.get("전화번호"),"",r.get("데이터기준일자"))
F=raw_csv("대구_경로당_20241231.bin") if glob.glob("data/raw/public/대구_경로당_20241231.bin") else None
for _,r in F.iterrows():
    g=r["소속지회"].strip(); a=r["주소"] if gu_of(r["주소"]) else f'{g} {r["주소"]}'
    if (g,nm(r["경로당명"])) in seen: continue
    seen.add((g,nm(r["경로당명"])))
    add(f'P:경로당:{g}:{r["경로당명"]}',"PUB:경로당",r["경로당명"],"대구광역시 "+a,None,None,"","대구시 경로당 목록(2024-12-31)에만 있음","2024-12-31")
# 6) 우체국
U=raw_csv("우체국__*"); U.columns=[c.strip() for c in U.columns]
for _,r in U[U["주소(도로명)"].fillna("").map(is_daegu)].iterrows():
    add(f'P:우체국:{r["우체국명"]}',"PUB:우체국",r["우체국명"],r["주소(도로명)"].strip(),None,None,r.get("전화번호",""),"","2026-08-31")
# 7) 행정복지센터
E=raw_csv("읍면동__*"); E.columns=[c.strip() for c in E.columns]
for _,r in E[E["시도"].fillna("").str.contains("대구")].iterrows():
    add(f'P:행정복지센터:{r["시군구"]}:{r["읍면동"]}',"PUB:행정복지센터",r["읍면동"].strip(),r["주소"],None,None,"","","2025-12-31")
# 8) 장기요양기관 (국민건강보험공단 장기요양기관 시설별 현황, 2026-06-10). 한 기관이 여러 서비스를 하면 서비스마다 한 줄
#    입소(요양원·공동생활가정), 주야간보호, 단기보호, 방문요양, 방문목욕, 방문간호, 복지용구. 기관코드가 바뀌지 않아 다음 자료와 비교(폐업 감지)에 씀
LX=glob.glob("data/raw/public/장기요양__*.xlsx")[0]
LG=pd.read_excel(LX,sheet_name="일반현황",dtype=str); LW=pd.read_excel(LX,sheet_name="인력현황",dtype=str)
LG=LG[LG["시도 시군구 법정동명"].fillna("").str.startswith("대구")].set_index("장기요양기관코드")
LTYPE={"A02":("PUB:노인요양시설","노인전문요양시설"),"A03":("PUB:노인요양시설","노인요양시설"),"A04":("PUB:노인요양공동생활가정","노인요양공동생활가정(9명 이하 소규모)"),
       "S41":("PUB:노인요양공동생활가정","치매전담형 노인요양공동생활가정"),
       "B01":("PUB:방문요양",""),"C01":("PUB:방문요양",""),"B02":("PUB:방문목욕",""),"C02":("PUB:방문목욕",""),
       "B03":("PUB:주야간보호",""),"C03":("PUB:주야간보호",""),"B04":("PUB:단기보호",""),"C04":("PUB:단기보호",""),
       "B05":("PUB:방문간호",""),"C05":("PUB:방문간호",""),"B06":("PUB:복지용구",""),"C06":("PUB:복지용구","")}
VISIT={"PUB:방문요양","PUB:방문목욕","PUB:방문간호"}
done=set(); nskip=collections.Counter()
for _,r in LW.iterrows():
    c=r["장기요양기관코드"]
    if c not in LG.index: continue
    t=r["기관유형코드"]
    if t[:1] in ("G","M","H","I"): nskip["치매전담실(본 서비스에 포함)"]+=1; continue
    if t not in LTYPE: nskip[t]+=1; continue
    typ,sub=LTYPE[t]
    if (c,typ) in done: continue
    done.add((c,typ)); g=LG.loc[c]
    a=re.sub(r"\s+"," ",str(g["기관별 상세주소"])).strip()
    note=("집으로 찾아오는 서비스. 장기요양 등급이 있어야 함. 사무실 위치보다 방문 가능한 지역이 중요(기관에 확인)" if typ in VISIT else
          "장기요양 등급이 있어야 함. 자리(정원)와 대기는 기관에 확인" if typ!="PUB:복지용구" else "장기요양 등급이 있으면 지원받아 사거나 빌릴 수 있음")
    add(f'P:장기요양:{c}:{typ[4:]}',typ,str(g["장기요양기관이름"]).strip(),a,None,None,"",(sub+". " if sub else "")+note,"2026-06-10")
print("장기요양 줄",len(done),"건너뜀",dict(nskip))
# 8-2) 어린이집 (대구광역시 어린이집 현황, 2025-09-30). 가정어린이집은 주로 만 0~2세, 직장어린이집은 그 회사 직원 자녀만
KD=raw_csv("어린이집__15069119__*")
for _,r in KD.iterrows():
    ty=str(r["어린이집유형"]).strip()
    typ={"가정":"PUB:가정어린이집","직장":"PUB:직장어린이집"}.get(ty,"PUB:어린이집")
    a=re.sub(r"\s+"," ",str(r["주소"])).strip()
    add(f'P:어린이집:{r["시군구"]}:{r["어린이집명"]}',typ,str(r["어린이집명"]).strip(),a,None,None,r.get("전화번호",""),f"{ty} 어린이집. 반 자리와 대기는 어린이집에 확인","2025-09-30",
        cand="확인 필요" if typ=="PUB:직장어린이집" else None,why="직장어린이집은 그 회사·기관 직원 자녀만 다닐 수 있음" if typ=="PUB:직장어린이집" else "")
# 8-2b) 유치원 (유치원알리미 일반현황 Open API, pipeline/fetch_kinder.py → data/raw/kinder/날짜.csv). 정보공시라 1년에 두 번 바뀜
#  가장 최근 공시차수에 없는 유치원(공시가 멈춤)은 휴원·폐원했을 수 있어 '확인 필요' (지자체 에이전트가 담당자에게 확인 요청)
_kf=sorted(glob.glob("data/raw/kinder/*.csv"))
if _kf:
    KG=pd.read_csv(_kf[-1],dtype=str).fillna(""); _last=KG["pbnttmng"].max()
    _cha=lambda t: f"{t[:4]}년 {t[4:]}차" if len(t)==5 else t
    for _,r in KG.iterrows():
        a=re.sub(r"\s+"," ",str(r["addr"])).strip(); old=r["pbnttmng"]<_last
        cap=f"인가 정원 {r['prmstfcnt']}명" if str(r["prmstfcnt"]).strip() not in ("","0") else ""
        add(f'P:유치원:{r["kindercode"]}',"PUB:유치원",str(r["kindername"]).strip(),a,r["lngtcdnt"] or None,r["lttdcdnt"] or None,r.get("telno",""),
            ", ".join(x for x in [str(r["establish"]), cap, f"공시 {_cha(old and r['pbnttmng'] or _last)}"] if x)+". 반 자리와 방과후 과정은 유치원에 확인",_kf[-1][-14:-4],
            gu=r.get("_구군") or None, cand="확인 필요" if old else None,
            why=f"최근 공시({_cha(_last)})에 없음 — 마지막 공시 {_cha(r['pbnttmng'])}. 휴원·폐원 여부 확인 필요" if old else "")
    print("유치원",len(KG),"공시 멈춤",int((KG["pbnttmng"]<_last).sum()))
# 8-3) 장애인복지관 (보건복지부 2024-04-25). 원자료 좌표가 다른 지역을 가리켜 쓰지 않고 주소로 찾음
JB=raw_csv("장애인복지관__*")
for _,r in JB[JB["시도"].fillna("").str.strip().eq("대구")].iterrows():
    add(f'P:장애인복지관:{r["시설명"]}',"PUB:장애인복지관",str(r["시설명"]).strip(),re.sub(r"\s+"," ",str(r["시설 주소"])).strip(),None,None,r.get("전화번호",""),"프로그램과 대상(장애 유형)은 복지관마다 다름","2024-04-25")
# 8-4) 초·중·고등학교 (전국초중등학교위치표준데이터). 운영 중인 학교만. 학교는 사는 곳에 따라 배정됨
for r in std("학교"):
    if r.get("운영상태")!="운영": continue
    t={"초등학교":"PUB:초등학교","중학교":"PUB:중학교","고등학교":"PUB:고등학교"}.get(r.get("학교급구분"))
    if not t: continue
    # 사는 곳으로 배정되지 않는 학교(예술·체육·과학·외국어·마이스터·특성화·대학 부설)와 남녀 한쪽만 다니는 학교는 '확인 필요' (10/15 공공시설 이름 전수 점검)
    _n=str(r["학교명"]); _sp=re.search(r"예술|체육|과학|외국어|국제|마이스터|공업|상업|기계|보건|소프트웨어|정보|디자인|조리|농업|부설|미용|관광|에너지|생명",_n); _gd=re.search(r"여자|남자",_n)
    _why=("따로 뽑는 학교라 사는 곳으로 배정되지 않음" if _sp and t!="PUB:초등학교" or (_sp and "부설" in _sp.group(0)) else "")
    if not _why and _gd: _why=f"{_gd.group(0)} 학교라 {'여학생' if _gd.group(0)=='여자' else '남학생'}만 다님"
    add(f'P:학교:{r["학교ID"]}',t,r["학교명"],r.get("소재지도로명주소") or r.get("소재지지번주소"),r.get("경도"),r.get("위도"),"",
        f'{r.get("설립형태","")} {r.get("본교분교구분","")}. 다닐 학교는 사는 곳에 따라 배정됨(전학·배정은 교육지원청 문의)',r.get("데이터기준일자"),
        cand="확인 필요" if _why else None, why=_why)
# 8-5) 지구대·파출소 (경찰청, 2025-12-31)
PO=raw_csv("지구대__*")
for _,r in PO[PO["시도청"].fillna("").str.contains("대구")&PO["주소"].fillna("").map(is_daegu)].iterrows():
    add(f'P:지구대:{r["경찰서"]}:{r["관서명"]}{r["구분"]}',"PUB:지구대·파출소",f'{r["관서명"]}{r["구분"]}',re.sub(r"\s+"," ",str(r["주소"])).strip(),None,None,"",f'{r["경찰서"]}경찰서 소속',"2025-12-31")
# 8-6) 지역보건의료기관 (보건복지부 지역보건의료기관 현황, 2025-12-31). 보건소·보건지소·보건진료소는 PUB:보건기관, 건강생활지원센터는 따로
HB=raw_csv("지역보건__*"); HB=HB[HB["시도"].fillna("").str.strip().eq("대구광역시")]
for _,r in HB.iterrows():
    ty=str(r["기관유형"]).strip()
    typ="PUB:건강생활지원센터" if "건강생활" in ty else ("PUB:보건기관" if ty in ("보건소","일반보건지소","보건진료소") else None)
    if not typ: continue
    a=re.sub(r"\s+"," ",str(r["주소"]).split(",")[0]).strip()
    add(f'P:보건:{r["시군구"]}:{r["보건기관명"]}',typ,str(r["보건기관명"]).strip(),a,None,None,r.get("대표 전화번호",""),ty,"2025-12-31")
# 8-7) 장기요양 재택의료센터 (국민건강보험공단, 2025-08-21): 의사·간호사가 집으로 찾아오는 장기요양 수급자 대상 재택의료
RT=raw_csv("재택의료__*")
for _,r in RT[RT["시도"].fillna("").str.strip().eq("대구광역시")].iterrows():
    add(f'P:재택의료:{r["재택의료센터 기관명"]}',"PUB:재택의료센터",str(r["재택의료센터 기관명"]).strip(),re.sub(r"\s+"," ",str(r["주소"])).strip(),None,None,"",
        f'{r["재택의료센터 기관 종별"]}. 장기요양 재가 수급자 대상, 의사·간호사 방문(방문 가능 지역은 기관에 확인)',"2025-08-21")
# 8-8) 지역아동센터 (대구광역시 아동복지시설 현황, 2025-01-30)
JA=raw_csv("아동돌봄__15011666__*")
for _,r in JA[JA["소재지"].fillna("").map(is_daegu)].iterrows():
    add(f'P:지역아동센터:{r["구군"]}:{r["지역아동센터명"]}',"PUB:지역아동센터",str(r["지역아동센터명"]).strip(),re.sub(r"\s+"," ",str(r["소재지"])).strip(),None,None,r.get("전화번호",""),
        f'정원 {r.get("정원","")}명. 자리와 이용 기준은 센터에 확인',"2025-01-30")
# 8-9) 다함께돌봄센터 (대구광역시 다함께돌봄센터 현황, 2026-10-01)
DH=raw_csv("아동돌봄__15143084__*")
for _,r in DH.iterrows():
    add(f'P:다함께돌봄:{r["시설명"]}',"PUB:다함께돌봄센터",str(r["시설명"]).strip(),re.sub(r"\s+"," ",str(r["주소"])).strip(),None,None,r.get("연락처",""),"초등학생 방과후 돌봄. 자리는 센터에 확인","2026-10-01")
# 8-10) 정신건강복지센터 (국립정신건강센터 정신건강 관련기관 정보, 2022-03-01). 기초 센터의 기관명은 운영 병원 이름이라 '구·군 정신건강복지센터'로 부름
MH=raw_csv("정신건강__*")
for _,r in MH[MH["주소"].fillna("").map(is_daegu)&MH["기관구분"].isin(["기초정신건강복지센터","광역정신건강복지센터"])].iterrows():
    a=re.sub(r"\s+"," ",str(r["주소"])).strip(); g=gu_of(a)
    mhn=("대구광역 정신건강복지센터" if r["기관구분"]=="광역정신건강복지센터" else f"{g} 정신건강복지센터")  # nm은 아래 경로당 비교에서 쓰므로 다른 이름
    add(f'P:정신건강:{mhn}',"PUB:정신건강복지센터",mhn,a,None,None,"",f'운영: {r["기관명"]}. 2022년 자료라 지금 위치는 확인 필요',"2022-03-01")
# 8-11) 농약·비료 판매업체 (전국농약및비료판매업체표준데이터)
for r in std("농약비료"):
    t={"농약":"PUB:농약판매업","비료":"PUB:비료판매업"}.get(r.get("취급품목구분명"))
    if not t: continue
    add(f'P:농자재:{r["업체명"]}:{r.get("소재지도로명주소") or r.get("소재지지번주소")}',t,r["업체명"],r.get("소재지도로명주소") or r.get("소재지지번주소"),r.get("경도"),r.get("위도"),r.get("전화번호"),
        "등록 판매업체. 개인에게 소량 파는지, 취급 품목은 가게에 확인",r.get("데이터기준일자"))
# 8-12) 버스 정류장 (대구시 버스 노선 공간정보 2026-09-02, 지금 쓰는 정류장만, build_bus.py) · 도시철도역 (build_subway.py)
BS=pd.read_csv("data/processed/bus_stops.csv",dtype=str)
for _,r in BS.iterrows():
    nt=pd.to_numeric(r.get("평일운행횟수"),errors="coerce"); nr=pd.to_numeric(r.get("노선수"),errors="coerce")
    info=(f"평일 {int(nt)}회 운행, 노선 {int(nr)}개: {r['노선']}" if nt==nt else f"노선: {r['노선']} (운행 횟수 자료 없음)")
    add(f'P:버스:{r["정류소ID"]}',"PUB:버스정류장",f'{r["정류소"]} 정류장',"",r["경도"],r["위도"],"",info+". 가려는 곳으로 가는 노선인지 확인","2026-09-02",gu="")
SB=pd.read_csv("data/processed/subway_stations.csv",dtype=str)
for _,r in SB.iterrows():
    add(f'P:지하철:{r["노선"]}:{r["역"]}',"PUB:도시철도역",f'{r["역"]}역 ({r["노선"]})',r["주소"],r["경도"],r["위도"],"",f'대구 도시철도 {r["노선"]}',r["자료기준일"])
# 9) 공공체육시설 (대구시 2024-12-31 목록, 이름과 관리 주체만 있음 → 좌표는 지오코딩으로 찾음)
from sports_types import sport_type, who_note
T=raw_csv("체육__*")
for _,r in T.iterrows():
    n=re.sub(r"\s+"," ",r["시설명"]).strip(); t,why=sport_type(n); w=who_note(n)
    g=gu_of(r["관리주체"]); g={"중":"중구"}.get(g,g)
    if t=="제외": add(f'P:체육:{n}',"PUB:경기장",n,None,None,None,"",f'관리 {r["관리주체"]}',"2024-12-31",gu=g,cand="아니요",why=why); continue
    add(f'P:체육:{n}',t,n,None,None,None,"",f'관리 {r["관리주체"]}. 이용 방법(예약·회원제)은 시설마다 다름',"2024-12-31",gu=g,
        cand="확인 필요" if w else None,why=w)
# 10) 장사시설 (한국장례문화진흥원 2023-06 기준). 대구 시민이 쓰는 대구시립 시설은 경북 칠곡에 있어도 넣음
ZX="data/raw/public/장사/2023년 6월/1.장사시설 현황_20230601.xlsx"
for sh,t in [("화장시설","PUB:화장시설"),("봉안시설","PUB:봉안시설"),("자연장지","PUB:자연장지"),("묘지","PUB:묘지")]:
    Z=pd.read_excel(ZX,sheet_name=sh,dtype=str)
    Z=Z[Z["시도"].fillna("").str.contains("대구")|Z["시군구"].fillna("").str.contains("군위")]
    for _,r in Z.iterrows():
        a=str(r["주소"]).strip(); pub=str(r["운영형태"]).strip()=="공설"
        g=gu_of(a) or ("군위군" if "군위" in a else "")
        add(f'P:장사:{sh}:{r["시설명"]}',t,str(r["시설명"]).strip(),a,None,None,r.get("전화번호",""),f'{r["운영형태"]}',"2023-06-01",gu=g,
            cand=None if pub and not re.search("가족|종중|문중",str(r["시설명"])) else "확인 필요",
            why="" if pub and not re.search("가족|종중|문중",str(r["시설명"])) else ("가족·종중 묘지는 일반 주민이 쓸 수 없을 수 있음" if pub else "사설 시설: 교회·사찰·단체 전용인지, 남은 자리가 있는지 확인 필요"))
# 10-2) 장례식장 (같은 장사시설 현황의 '장례식장' 표, 2023-06): 상가 자료의 '장례식장' 업종에는 상조·의전·장묘 업체가 섞여 있어 빈소가 있는 곳은 이 공식 목록으로 안내 (10/15)
#  빈소 수가 0인 곳은 운영하는지 확인 필요. 2023년 자료라 2026년 상가 자료와 주소가 겹치지 않는 곳은 추천할 때 카카오맵으로 한 번 더 확인 (engine/live_check.py)
Z=pd.read_excel(ZX,sheet_name="장례식장",dtype=str)
Z=Z[Z["시도"].fillna("").str.contains("대구")|Z["시군구"].fillna("").str.contains("군위")]
for _,r in Z.iterrows():
    a=str(r["주소"]).strip(); a=re.sub(r"(\d)(?=[가-힣]{2,}(병원|장례식장|요양))",r"\1 ",a)   # '논공로 210성요셉…' → 번호 뒤 띄어쓰기
    g=gu_of(a) or ("군위군" if "군위" in a else ""); nb=str(r.get("빈소수") or "").strip()
    add(f'P:장례식장:{r["시설명"]}',"PUB:장례식장",str(r["시설명"]).strip(),a,None,None,r.get("전화번호",""),
        f'빈소 {nb}개, {r.get("운영형태","")}. 2023년 6월 자료',"2023-06-01",gu=g,
        cand="확인 필요" if nb in ("0","","nan") or "연도실" in str(r["시설명"]) else None,
        why="자료에 빈소 수가 0으로 나와 지금 운영하는지 확인 필요" if nb in ("0","","nan") else ("성당 연도실이라 신자가 아니어도 빈소를 차릴 수 있는지 확인 필요" if "연도실" in str(r["시설명"]) else ""))
# 11) 종합사회복지관 (대구시 2024-06-28 목록, 주소만 있음)
W=raw_csv("사회복지관__*")
for _,r in W.iterrows():
    add(f'P:사회복지관:{r["시설명"]}',"PUB:사회복지관",r["시설명"].strip(),r["주소"],None,None,r.get("연락처",""),"프로그램은 복지관마다 다름","2024-06-28")
# 12) 가족센터 (여성가족부 가족센터 현황 — 구·군마다 1곳, 기관 이름 없이 주소만 있음. 2026-10-15 카카오맵·안내 페이지와 하나하나 맞춰 봄)
#  - 달서구: 원자료 '야외음악당로 13-60'은 '야외음악당로13길 60'의 띄어쓰기 오기
#  - 수성구: 원자료 주소(들안로16길 78)에서 수성행복드림센터(달구벌대로526길 50)로 옮김 (카카오맵·수성행복드림센터 안내가 일치)
#  - 군위군: 자료마다 주소가 다름(중앙길 31-10 / 중앙길 134) → 확인될 때까지 '확인 필요'
FIX={"달서구":"대구광역시 달서구 야외음악당로13길 60","수성구":"대구광역시 수성구 달구벌대로526길 50"}
FC=raw_csv("가족센터__*")
for _,r in FC.iterrows():
    g=str(r["구군"]).strip(); a=FIX.get(g, str(r["소재지"]).strip())
    add(f'P:가족센터:{g}',"PUB:가족센터",f"{g}가족센터",a,None,None,"","다문화가족 상담·한국어 교육·통번역, 가족 상담·교육 (프로그램은 센터마다 다름)","2026-10-15",gu=g,
        cand="확인 필요" if g=="군위군" else None, why="주소가 자료마다 달라 지금 위치를 확인하는 중" if g=="군위군" else "")
# 13) 노인복지관·무료급식소 (대구광역시 누리집 '노인여가복지시설'·'노인급식지원사업' 목록, 2026-10-15 헌준님이 저장해 줌)
#  27곳 모두 카카오맵에서 같은 주소에 같은 시설이 있는 것을 하나하나 확인함 (2026-10-15, 카카오 결과는 저장하지 않음)
#  경로식당: 대구시 목록에 있는 4곳(복지관 안, 기초생활수급자만 무료)만 근거로 씀 (build_evidence.py)
# 전화번호 바로잡기: 원자료는 고치지 않고 여기서만 (출처를 함께 적음)
#  자비의집: 대구시 목록 053-253-1082, 카카오맵 053-256-1082로 달랐음 → 자비의집 블로그에 사무처 번호가 053-256-1082로 나옴 (헌준님 확인, 2026-10-15)
DC_PHONE_FIX={"자비의집":"053-256-1082 (사무처)"}
DC=pd.read_csv("data/raw/daegu_city/노인복지관_경로식당_무료급식소_20261015.csv",dtype=str).fillna("")
for _,r in DC.iterrows():
    if r["구분"]=="노인복지관":
        note=f'60세 이상 어르신. 운영: {r["운영주체"]}. 누리집: {r["누리집"]}' + (". 경로식당 운영(기초생활수급자만 무료, 월~금)" if r["경로식당"]=="예" else "")
        add(f'P:노인복지관:{r["기관명"]}',"PUB:노인복지관",r["기관명"],r["주소"],None,None,r["연락처"],note,"2026-10-15")
    else:
        note=f'경로 무료급식소. 급식일: {r["급식일"]} (급식일은 바뀔 수 있음)'
        add(f'P:무료급식소:{r["기관명"]}',"PUB:무료급식소",r["기관명"],r["주소"],None,None,DC_PHONE_FIX.get(r["기관명"],r["연락처"]),note,"2026-10-15")
# 아파트 단지 안 경로당·작은도서관 (10/15 헌준님 판단): 그 단지 주민 위주라 단지 밖 주민에게는 대안으로 안내하지 않음
#  단지 시설이 문을 닫으면 동네 경로당·공공도서관을 안내하고(그 반대는 안 됨), 시설 자체는 남겨 두어 문을 닫았을 때 무엇을 하던 곳인지 앎
#  작은도서관은 구청·주민센터·문화재단·복지관 등 공공이 운영하는 곳만 누구나 이용하는 곳으로 보고, 교회·개인 등이 운영하는 곳은 '확인 필요'
sys.path.insert(0,"pipeline"); import facility_rules as _FR
_PUBOP=r"구청|군청|주민센터|행정복지센터|문화재단|복지관|새마을|노인회|청소년|학생문화센터|교육|시청"
_nc=_nl=_nq=0
for r in rows:
    if r["대안후보_지정"]=="아니요": continue
    if r["업종코드"]=="PUB:경로당" and _FR.in_complex(r["상호"],r["주소"]):
        r["대안후보_지정"]="아니요"; r["제외사유"]="아파트 단지 경로당이라 그 단지 어르신이 다니는 곳 (단지 밖 어르신께는 안내하지 않음)"; _nc+=1
    if r["업종코드"] in ("PUB:작은도서관","PUB:공공도서관") and re.search(r"임시\s?휴무|임시\s?휴관|휴관\s?중|리모델링",str(r["참고"])):
        r["대안후보_지정"]="아니요"; r["제외사유"]="자료에 임시 휴관 중으로 나옴"; continue
    if r["업종코드"]=="PUB:작은도서관":
        op=(re.search(r"운영: (.*)$",str(r["참고"])) or [None,""])[1]
        if _FR.in_complex(r["상호"],r["주소"],op):
            r["대안후보_지정"]="아니요"; r["제외사유"]="아파트 단지 안 작은도서관이라 단지 주민 위주로 운영 (단지 밖 주민께는 안내하지 않음)"; _nl+=1
        elif not re.search(_PUBOP,op+" "+str(r["상호"])):
            r["대안후보_지정"]="확인 필요"; r["제외사유"]="교회·개인 등이 운영하는 작은도서관이라 누구나 이용할 수 있는지 확인 필요"; _nq+=1
print("아파트 단지 경로당",_nc,"단지 작은도서관",_nl,"운영 주체 확인 필요 작은도서관",_nq)
# 3-2) 도시철도역 안 무인민원발급기 (대구교통공사 운영 현황 2026-07-16, 헌준님이 받은 파일): 역 좌표에 둠. 같은 역의 2020년 자료 발급기는 겹치므로 뺌
_ST={}
for r in rows:
    if r["업종코드"]=="PUB:도시철도역" and r["경도"] not in (None,""): _ST.setdefault(re.sub(r"(역)?\s*\(.*$","",r["상호"]).strip(),r)
_KM=pd.read_csv("data/raw/public/무인민원발급기_대구교통공사_20260716.csv",dtype=str); _new=set()
for _,m in _KM.iterrows():
    stn=re.sub(r"역$","",m["역명"].strip()); sr=_ST.get(stn)
    if sr is None: print("  [무인민원발급기] 역을 찾지 못함:",stn); continue
    _new.add(stn)
    add(f'P:무인민원:지하철:{stn}',"PUB:무인민원발급기",f'{stn}역 무인민원발급기',sr["주소"],sr["경도"],sr["위도"],m["연락처"],
        f'도시철도 {m["호선"]}호선 {stn}역 {m["상세위치"]}. 관리: {m["운영사"]}',"2026-07-16")
for r in rows:
    if r["업종코드"]=="PUB:무인민원발급기" and r["자료기준일"]!="2026-07-16":
        stn=re.match(r"^(?:대구광역시\s+)?(\S+?)역\s",str(r["상호"]))
        if stn and stn.group(1) in _new: r["대안후보_지정"]="아니요"; r["제외사유"]="같은 역의 2026년 자료(대구교통공사)로 안내"
P=pd.DataFrame(rows); P["주소근거"]=""
n0=len(P); P=P.drop_duplicates(subset=["업종코드","상호","주소","경도","위도"]).copy()  # 원자료에 같은 줄이 두 번 있는 경우
_k=P["업종코드"]+"|"+P["상호"].fillna("").str.replace(" ","")+"|"+P["주소"].fillna("").str.replace(" ","")
P=P[~(_k.duplicated()&P["주소"].fillna("").str.strip().ne(""))].copy()   # 관리번호만 다르고 이름·주소가 같은 줄 (예: 2.28기념 중앙공원 두 번)
dup=P["fid"].duplicated(keep=False)
P.loc[dup,"fid"]=P.loc[dup,"fid"]+":"+P.loc[dup].groupby("fid").cumcount().astype(str)  # 이름이 같은 다른 시설(예: 다른 구의 중앙시장)
assert P["fid"].is_unique
print("원자료 중복 제거",n0-len(P),"이름 같은 다른 시설",int(dup.sum()))
ok=P["경도"].notna()
P["경도"]=pd.to_numeric(P["경도"]); P["위도"]=pd.to_numeric(P["위도"])
inb=P["경도"].between(128.3,129.0)&P["위도"].between(35.55,36.35)
P.loc[ok&~inb,["좌표근거"]]="좌표 이상"; P.loc[ok&~inb,["경도","위도"]]=np.nan
# 자료 좌표 점검: 같은 건물 주소 좌표(상가·인허가)와 500m 넘게 어긋나면 주소 쪽 좌표로 고침 (주소가 더 믿을 만함)
kx=np.cos(np.radians(35.87))*111320
chk=P[(P["좌표근거"]=="자료 좌표")].copy(); chk["k"]=chk["주소"].map(key); chk=chk[chk["k"].isin(LOOK.index)]
dd=np.hypot((chk["경도"]-LOOK.loc[chk["k"],"경도"].values)*kx,(chk["위도"]-LOOK.loc[chk["k"],"위도"].values)*110540)
for i in chk.index[dd>500]:
    P.loc[i,["경도","위도"]]=LOOK.loc[chk.at[i,"k"],["경도","위도"]].values
    P.loc[i,"좌표근거"]=f"자료 좌표가 주소와 {int(dd[i])}m 어긋나 같은 건물 주소 좌표로 고침"
print("자료 좌표를 주소 좌표로 고친 곳",int((dd>500).sum()),"/ 점검한 곳",len(chk))
# 브이월드로 찾은 좌표 넣기 (pipeline/geocode_vworld.py 결과). 찾은 점이 그 구·군 경계 안에 있을 때만 받음 (구·군을 모르면 대구 경계 안)
import os
from shapely.geometry import shape, Point
from shapely.ops import unary_union
_G=json.load(open("data/raw/boundary/daegu_hjd_20260701.geojson",encoding="utf-8"))["features"]
GUPOLY={g: unary_union([shape(f["geometry"]) for f in _G if f["properties"]["sggnm"]==g]).buffer(0.003) for g in GU}  # 약 300m 여유(경계선 위 시설)
DAEGU=unary_union(list(GUPOLY.values()))
if os.path.exists("data/work/vworld_geocode.csv"):
    V=pd.read_csv("data/work/vworld_geocode.csv",dtype=str).set_index("fid")
    nin=0; nok=0
    for i in P.index[P["좌표근거"]=="좌표 필요"]:
        f=P.at[i,"fid"]
        if f not in V.index or pd.isna(V.at[f,"경도"]): continue
        x,y=float(V.at[f,"경도"]),float(V.at[f,"위도"]); g=P.at[i,"구군"] if isinstance(P.at[i,"구군"],str) else ""
        poly=GUPOLY.get(g)
        if poly is None and P.at[i,"업종코드"] in ("PUB:화장시설","PUB:봉안시설","PUB:자연장지","PUB:묘지"): poly=None  # 대구시립 시설은 경북에 있을 수 있음
        elif poly is None: poly=DAEGU
        if poly is not None and not poly.contains(Point(x,y)): nin+=1; P.at[i,"참고"]=(str(P.at[i,"참고"]) if isinstance(P.at[i,"참고"],str) else "")+" [브이월드 좌표가 구·군 경계 밖이라 버림]"; continue
        P.loc[i,["경도","위도"]]=[x,y]; P.at[i,"좌표근거"]=V.at[f,"근거"]; nok+=1
        if (not isinstance(P.at[i,"주소"],str) or not P.at[i,"주소"].strip()) and isinstance(V.at[f,"찾은주소"],str): P.at[i,"주소"]=V.at[f,"찾은주소"]; P.at[i,"주소근거"]="브이월드 장소 이름 검색으로 찾은 주소"
    print("브이월드 좌표 넣음",nok,"경계 밖이라 버림",nin)
# 이름 검색으로 바로 못 찾은 곳: 브이월드 장소 검색 결과를 사람이(Claude) 이름·위치를 하나하나 대조해 고른 좌표 (data/work/geo_fix/manual_points.csv, 근거 함께)
#  이름이 조금이라도 애매한 곳은 넣지 않고 '좌표 필요'로 둠 (새 공공체육시설 자료를 받으면 다시 봄)
MP="data/work/geo_fix/manual_points.csv"
if os.path.exists(MP):
    M=pd.read_csv(MP,dtype=str).set_index("fid"); n_manual=0
    for i in P.index[(P["좌표근거"]=="좌표 필요")&P["fid"].isin(M.index)]:
        f=P.at[i,"fid"]; x,y=float(M.at[f,"경도"]),float(M.at[f,"위도"]); g=M.at[f,"구군"]
        if g in GUPOLY and not GUPOLY[g].contains(Point(x,y)): print("  [수동 좌표가 구·군 경계 밖이라 버림]",f); continue
        P.loc[i,["경도","위도"]]=[x,y]; P.at[i,"좌표근거"]="브이월드 장소 검색(직접 대조): "+M.at[f,"근거"]; P.at[i,"구군"]=g; n_manual+=1
        if not isinstance(P.at[i,"주소"],str) or not P.at[i,"주소"].strip(): P.at[i,"주소"]=M.at[f,"주소"]; P.at[i,"주소근거"]="브이월드 장소 검색으로 찾은 주소"
    print("직접 대조한 좌표 넣음",n_manual)
# 같은 단지 안 시설(주소가 없는 체육시설 등): 이름이 좌표 있는 다른 시설 이름과 띄어쓰기 빼고 같거나, 그 이름으로 시작하면(예: "성서국민체육센터 내 축구장" ← "성서국민체육센터") 그 좌표를 씀
_n=lambda x: re.sub(r"\s|\(.*?\)","",str(x))
_has=P[P["경도"].notna()&P["상호"].notna()]
_base={}
for _,r in _has.iterrows():
    k=_n(r["상호"])
    if len(k)>=5: _base.setdefault(k,[]).append((float(r["경도"]),float(r["위도"]),r["상호"]))
nin2=0
# 주소가 있는 곳은 이 방법을 쓰지 않음: 이름이 같아도 주소가 다르면 다른 시설임(예: 다른 구의 같은 이름 요양기관)
for i in P.index[(P["좌표근거"]=="좌표 필요")&P["상호"].notna()&P["주소"].fillna("").str.strip().eq("")]:
    nmi=_n(P.at[i,"상호"]); cand=[k for k in _base if nmi==k or nmi.startswith(k)]
    if not cand: continue
    k=max(cand,key=len); pts=_base[k]
    if len({(round(a,3),round(b,3)) for a,b,_ in pts})!=1: continue  # 같은 이름이 여러 곳이면 안 씀
    x,y,src=pts[0]; g=P.at[i,"구군"] if isinstance(P.at[i,"구군"],str) else ""
    if g in GUPOLY and not GUPOLY[g].contains(Point(x,y)): continue
    sg=P.loc[(P["상호"]==src)&P["경도"].notna(),"구군"].dropna().unique()
    if g and len(sg) and g not in sg: continue  # 같은 구·군일 때만
    P.loc[i,["경도","위도"]]=[x,y]; P.at[i,"좌표근거"]=f"같은 단지 시설({src})의 좌표"; nin2+=1
print("같은 단지 시설 좌표로 채움",nin2)
# 구·군 빈칸 채우기: 좌표가 있는 곳은 좌표가 들어 있는 구·군 경계로 정함 (대구 밖 장사시설은 빈칸 그대로)
GUPOLY0={g: unary_union([shape(f["geometry"]) for f in _G if f["properties"]["sggnm"]==g]) for g in GU}
nfill=0
for i in P.index[P["구군"].fillna("").eq("") & P["경도"].notna()]:
    pt=Point(float(P.at[i,"경도"]),float(P.at[i,"위도"]))
    inn=[g for g,v in GUPOLY0.items() if v.contains(pt)]
    if len(inn)==1: P.at[i,"구군"]=inn[0]; nfill+=1
print("구·군 빈칸을 좌표로 채움",nfill)
# 대구 시내버스가 다니는 경산·칠곡·고령 등 대구 밖 정류장은 뺌 (구·군 경계 안에 들지 않는 정류장)
_out=(P["업종코드"]=="PUB:버스정류장")&P["구군"].fillna("").eq("")
P=P[~_out].copy(); print("대구 밖 버스 정류장 뺌",int(_out.sum()))
# 경로당: 대구시 목록에서 보충한 것 중 표준데이터 경로당과 100m 안에 있고 이름이 비슷하면 같은 곳으로 보고 뺌
from rapidfuzz import fuzz
k=np.cos(np.radians(35.87))*111320
base=P[(P["업종코드"]=="PUB:경로당")&(P["참고"]=="")&P["경도"].notna()]
add_=P[(P["업종코드"]=="PUB:경로당")&(P["참고"]!="")&P["경도"].notna()]
drop=[]
for i,r in add_.iterrows():
    d=np.hypot((base["경도"]-r["경도"])*k,(base["위도"]-r["위도"])*110540)
    near=base[d<=100]
    if any(fuzz.ratio(nm(r["상호"]),nm(x))>=70 for x in near["상호"]): drop.append(i)
P=P.drop(index=drop); print("보충 경로당 중 같은 곳으로 본 것",len(drop))
_hb={key(a) for a in P.loc[P["업종코드"]=="PUB:보건기관","주소"] if key(a)}
_mh=P["업종코드"]=="PUB:정신건강복지센터"
P.loc[_mh&~P["주소"].map(lambda a: key(a) in _hb),"대안후보_지정"]="확인 필요"
P.loc[_mh&P["주소"].map(lambda a: key(a) in _hb),"참고"]=P.loc[_mh,"참고"].str.replace("2022년 자료라 지금 위치는 확인 필요","2022년 자료지만 2025년 보건소·보건지소 주소와 같은 건물")
P["대안후보"]=np.where(P["대안후보_지정"]=="아니요","아니요",np.where(P["경도"].isna(),"좌표 필요",np.where(((P["업종코드"]=="PUB:무인민원발급기")&(P["자료기준일"]!="2026-07-16"))|(P["대안후보_지정"]=="확인 필요"),"확인 필요","예")))
P=P.drop(columns=["대안후보_지정"])
_old=(P["업종코드"]=="PUB:무인민원발급기")&(P["자료기준일"]!="2026-07-16")
P.loc[_old,"참고"]="자료 기준일이 오래돼(2020년 등) 지금도 있는지 확인 필요. "+P.loc[_old,"참고"]
P.to_csv("data/processed/public_facilities.csv",index=False,encoding="utf-8")
print(P.groupby(["업종코드","좌표근거"]).size().unstack(fill_value=0).to_string())
print("합계",len(P),"대안후보",P["대안후보"].value_counts().to_dict())
