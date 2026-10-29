# 공공·복지 시설 유형의 기능을 extra_type_functions.json에 넣는다 (같은 code가 있으면 바꾸고, 없으면 더함). 여러 번 돌려도 결과가 같음
# '신청·문의 창구'는 그 서비스를 직접 하는 곳이 아니라 신청·문의하는 곳: 세부 종류에서 contact=True로 따로 표시함
import json
EXPECT="0.9-draft"
T=json.load(open("design/purpose_taxonomy.json",encoding="utf-8")); assert T["version"]==EXPECT
LEAF={l["id"] for c in T["categories"] for p in c["purposes"] for l in p["leaves"]}
P="data/processed/extra_type_functions.json"; X=json.load(open(P,encoding="utf-8")); assert X["taxonomy_version"]==EXPECT
NHIS="국민건강보험공단 장기요양기관 시설별 현황(2026-06-10)"
f=lambda i,role,conf,why: {"id":i,"role":role,"confidence":conf,"reason":why}
NEW=[
 {"code":"PUB:노인요양시설","name":"노인요양시설(요양원)","source":NHIS+" 노인요양시설·노인전문요양시설","functions":[f("P04.1.04","주","높음","장기요양 등급 어르신이 입소하는 요양원")]},
 {"code":"PUB:노인요양공동생활가정","name":"노인요양공동생활가정","source":NHIS,"functions":[f("P04.1.04","주","높음","9명 이하가 함께 지내는 소규모 입소 돌봄")]},
 {"code":"PUB:단기보호","name":"단기보호 기관","source":NHIS,"functions":[f("P04.1.06","주","높음","며칠에서 몇 달까지 짧게 입소하는 돌봄 (장기요양 재가급여)")]},
 {"code":"PUB:주야간보호","name":"주야간보호 기관","source":NHIS,"functions":[f("P04.1.02","주","높음","낮 동안 센터에서 돌봄")]},
 {"code":"PUB:방문요양","name":"방문요양 기관","source":NHIS,"functions":[f("P04.1.01","주","높음","요양보호사가 집으로 방문")]},
 {"code":"PUB:방문목욕","name":"방문목욕 기관","source":NHIS,"functions":[f("P07.1.02","주","높음","목욕 차량·요양보호사가 집으로 와서 목욕을 도움")]},
 {"code":"PUB:방문간호","name":"방문간호 기관","source":NHIS,"functions":[f("P04.1.05","주","높음","간호사가 집으로 방문해 간호·처치")]},
 {"code":"PUB:복지용구","name":"복지용구 사업소","source":NHIS,"functions":[f("P03.2.03","주","높음","보행보조기·휠체어·욕창 방지 용품 등을 팔거나 빌려줌(장기요양 등급이 있으면 지원)")]},
 {"code":"PUB:어린이집","name":"어린이집(국공립·민간·법인 등)","source":"대구광역시 어린이집 현황(2025-09-30)","functions":[f("P04.2.01","주","높음","영유아 보육")]},
 {"code":"PUB:가정어린이집","name":"가정어린이집","source":"대구광역시 어린이집 현황(2025-09-30)","functions":[f("P04.2.01","주","높음","주로 만 0~2세 영아 보육")]},
 {"code":"PUB:유치원","name":"유치원(만 3~5세)","source":"유치원알리미 일반현황(교육부·한국교육학술정보원, 정보공시)","functions":[f("P04.2.01","주","높음","만 3~5세 유아 교육과 방과후 과정 돌봄")]},
 {"code":"PUB:직장어린이집","name":"직장어린이집","source":"대구광역시 어린이집 현황(2025-09-30)","functions":[f("P04.2.01","주","높음","그 회사·기관 직원 자녀 보육")]},
 {"code":"PUB:장애인복지관","name":"장애인복지관","source":"보건복지부 장애인복지관 현황(2024-04-25)","functions":[f("P04.3.01","주","높음","장애인 재활·상담·프로그램 (대상 장애 유형은 복지관마다 다름)")]},
 {"code":"PUB:초등학교","name":"초등학교","source":"전국초중등학교위치표준데이터","functions":[f("P09.3.01","주","높음","초등학교")]},
 {"code":"PUB:중학교","name":"중학교","source":"전국초중등학교위치표준데이터","functions":[f("P09.3.01","주","높음","중학교")]},
 {"code":"PUB:고등학교","name":"고등학교","source":"전국초중등학교위치표준데이터","functions":[f("P09.3.01","주","높음","고등학교")]},
 {"code":"PUB:건강생활지원센터","name":"건강생활지원센터","source":"보건복지부 지역보건의료기관 현황(2025-12-31)","functions":[f("P03.3.02","주","높음","만성질환 예방·관리와 건강 상담을 하는 보건소 분소")]},
 {"code":"PUB:재택의료센터","name":"장기요양 재택의료센터","source":"국민건강보험공단 재택의료센터 기관정보(2025-08-21)","functions":[f("P04.1.05","주","보통","의사·간호사가 장기요양 수급자 집으로 방문 (할 수 있는 처치는 기관에 확인)")]},
 {"code":"PUB:지역아동센터","name":"지역아동센터","source":"대구광역시 아동복지시설(지역아동센터) 현황(2025-01-30)","functions":[f("P04.2.02","주","높음","방과후 아동 돌봄 (아동복지법)")]},
 {"code":"PUB:다함께돌봄센터","name":"다함께돌봄센터","source":"대구광역시 다함께돌봄센터 현황(2026-10-01)","functions":[f("P04.2.02","주","높음","초등학생 방과후 돌봄")]},
 {"code":"PUB:노인복지관","name":"노인복지관","source":"대구광역시 노인여가복지시설 목록 (2026-10-15 확인, 2024-12-31 기준)","functions":[f("P11.1.02","주","높음","60세 이상 어르신의 교양·취미·사회참여 프로그램 (노인복지법 제36조)"),f("P01.1.07","부","보통","경로식당을 운영하는 복지관이 있음 (대구시 노인급식지원사업 목록에 있는 곳만 근거)")]},
 {"code":"PUB:무료급식소","name":"경로 무료급식소","source":"대구광역시 노인급식지원사업 목록 (2026-10-15 확인)","functions":[f("P01.1.07","주","높음","어르신께 무료로 식사를 드리는 곳 (급식일은 곳마다 다름)")]},
 {"code":"PUB:가족센터","name":"가족센터","source":"여성가족부 가족센터 현황 (2026-10-15 주소 확인)","functions":[f("P04.5.01","주","높음","결혼이민자·다문화가족 상담, 한국어 교육, 통번역 (다문화가족지원법·건강가정기본법)")]},
 {"code":"PUB:정신건강복지센터","name":"정신건강복지센터","source":"국립정신건강센터 정신건강 관련기관 정보(2022-03-01)","functions":[f("P03.1.05","주","높음","정신건강 상담과 사례 관리 (정신건강복지법)")]},
 {"code":"PUB:농약판매업","name":"농약 판매업체","source":"전국농약및비료판매업체표준데이터","functions":[f("P15.1.01","주","높음","등록된 농약 판매업체")]},
 {"code":"PUB:비료판매업","name":"비료 판매업체","source":"전국농약및비료판매업체표준데이터","functions":[f("P15.1.01","주","높음","등록된 비료 판매업체")]},
 {"code":"PUB:버스정류장","name":"버스 정류장","source":"대구광역시 버스 노선 공간정보(2026-09-02)","functions":[f("P12.1.01","주","높음","시내버스·농어촌버스를 타는 곳")]},
 {"code":"PUB:도시철도역","name":"도시철도역","source":"전국도시철도역사정보표준데이터","functions":[f("P12.1.04","주","높음","지하철을 타는 곳")]},
 {"code":"PUB:장례식장","name":"장례식장","source":"한국장례문화진흥원 장사시설 현황 장례식장(2023-06-01)","functions":[f("P16.1.01","주","높음","빈소를 차리고 장례를 치르는 곳 (빈소 수는 곳마다 다름)")]},
 {"code":"PUB:지구대·파출소","name":"지구대·파출소","source":"경찰청 전국 지구대·파출소 주소 현황(2025-12-31)","functions":[f("P13.2.01","주","높음","지구대·파출소")]},
]
# 기존 유형에 더하는 기능 (신청·문의 창구 등)
ADD={
 "PUB:행정복지센터":[f("P04.1.03","부","보통","노인맞춤돌봄서비스 신청 창구"),f("P13.1.01","부","보통","노인맞춤돌봄서비스(안부 확인) 신청 창구"),
                  f("P13.1.02","부","보통","응급안전안심서비스 신청 창구"),f("P04.3.01","부","보통","장애인 활동지원 등 신청 창구"),
                  f("P07.1.03","부","보통","목욕 지원 사업 문의 창구"),f("P07.2.02","부","보통","방문 이미용 지원 문의 창구"),
                  f("P07.3.03","부","보통","이불 빨래 등 세탁 지원 문의 창구"),f("P01.1.07","부","보통","경로식당·도시락 배달 등 식사 지원 신청 창구")],
 "PUB:사회복지관":[f("P07.1.03","부","낮음","목욕 지원 프로그램이 있는 복지관이 있음(복지관마다 다름)"),f("P07.2.02","부","낮음","이미용 봉사가 있는 복지관이 있음(복지관마다 다름)"),
                 f("P07.3.03","부","낮음","세탁 지원이 있는 복지관이 있음(복지관마다 다름)"),f("P01.1.07","부","낮음","경로식당·밑반찬 지원이 있는 복지관이 있음(복지관마다 다름)")],
 "PUB:우체국":[f("P05.1.04","부","보통","우체국 금융 창구 송금")],
 "PUB:보건기관":[f("P04.1.05","부","낮음","보건소 방문건강관리사업 문의 창구 (방문간호처럼 처치를 하는지는 확인 필요)")],
}
by={x["code"]:x for x in X["items"]}
for n in NEW:
    if n["code"] in by: by[n["code"]].clear(); by[n["code"]].update(n)
    else: X["items"].append(n); by[n["code"]]=n
for c,fs in ADD.items():
    have={g["id"] for g in by[c]["functions"]}
    by[c]["functions"]+=[g for g in fs if g["id"] not in have]
by["PUB:보건기관"]["source"]="보건복지부 지역보건의료기관 현황(2025-12-31) 보건소·보건지소·보건진료소"
# 약한 연결 판정표(weak_links_spec.py)를 시설 유형에도 반영: 삭제는 지우고, 나머지는 check로 적음
import sys as _s; _s.path.insert(0,"pipeline"); import weak_links_spec as _W
for x in X["items"]:
    if x["code"].startswith(("PERMIT:","LD:")): continue
    keep=[]
    for g in x["functions"]:
        d=None if x["code"] in getattr(_W,"PUB_OWN",set()) else _W.W.get((g["id"],x["name"]))   # 상가 업종과 이름이 같은 공식 시설 유형은 상가 쪽 판정을 받지 않음
        if d and d[0]==_W.D: continue
        if d:
            g["check"]=d[0]; g["check_reason"]=d[1]
            if d[0]==_W.I: g["check_items"]=dict(_W.WI[(g["id"],x["name"])])
            else: g.pop("check_items",None)
        elif g["role"]!="주" or g["confidence"]=="낮음": raise SystemExit(f"판정 없는 약한 연결: {x['name']} {g['id']}")
        keep.append(g)
    x["functions"]=keep
err=[]
codes=[x["code"] for x in X["items"]]
if len(codes)!=len(set(codes)): err.append("code 중복")
for x in X["items"]:
    ids=[g["id"] for g in x["functions"]]
    if len(ids)!=len(set(ids)): err.append(("기능 중복",x["code"]))
    for g in x["functions"]:
        if g["id"] not in LEAF: err.append(("분류표에 없는 기능",x["code"],g["id"]))
        if g["role"] not in ("주","부") or g["confidence"] not in ("높음","보통","낮음"): err.append(("값 오류",x["code"],g))
print("검사 오류",len(err)); [print(e) for e in err]; assert not err
json.dump(X,open(P,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
print("시설 유형",len(X["items"]))
