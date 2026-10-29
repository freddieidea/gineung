# 시설 한 곳을 분류하는 규칙 (시설 데이터베이스 만들기와 시설 변화 관리가 함께 씀)
#  - build_facilities.py: 전체 시설 데이터베이스를 만들 때
#  - engine/changes.py: 새로 생긴 시설을 하나씩 분류할 때 (같은 규칙을 써야 결과가 어긋나지 않음)
# 2026-10-15: build_facilities.py 안에 있던 규칙을 그대로 옮김 (옮긴 뒤 facilities.csv가 글자 하나까지 같은 것을 확인)
import json, os, re
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L = json.load(open(os.path.join(_ROOT, "data", "processed", "industry_list.json"), encoding="utf-8"))
CODE = {x["소분류"]: x["code"] for x in L}; NAME = {x["code"]: x["소분류"] for x in L}

def upjong_name(c):
    return NAME.get(c, c.split(":", 1)[1] if ":" in str(c) else c)

# ---- 인허가 자료의 업종 → 상가 업종 ----
def clinic_type(name, kind):
    n = str(name).replace(" ", "")
    if kind in ("보건소", "보건지소", "보건진료소"): return None  # 보건기관은 보건복지부 지역보건의료기관 현황(공공 자료)으로 넣음 (인허가에는 2곳이 빠져 있음)
    if kind == "치과의원": return CODE["치과의원"]
    if kind == "한의원": return CODE["한의원"]
    for pat, u in [(r"이비인후", "이비인후과 의원"), (r"안과", "안과 의원"), (r"피부|비뇨", "피부/비뇨기과 의원"), (r"산부인과|여성의원", "산부인과 의원"),
                   (r"정신건강|정신과|신경과", "신경/정신과 의원"), (r"성형외과", "성형외과 의원"), (r"정형외과|외과|통증", "외과 의원"), (r"내과|소아", "내과/소아과 의원")]:
        if re.search(pat, n): return CODE[u]
    return CODE["기타 의원"]
HOSP = {"병원": "일반병원", "종합병원": "종합병원", "요양병원(일반요양병원)": "요양병원", "한방병원": "한방병원", "치과병원": "치과병원", "정신병원": "신경/정신과 의원"}
REST = {"중국식": "중국집", "분식": "김밥/만두/분식", "김밥(도시락)": "김밥/만두/분식", "일식": "기타 일식 음식점", "경양식": "경양식", "횟집": "횟집", "통닭(치킨)": "치킨", "호프/통닭": "생맥주 전문",
        "냉면집": "냉면/밀면", "복어취급": "복 요리 전문", "탕류(보신용)": "국/탕/찌개류", "뷔페식": "뷔페", "패스트푸드": "버거", "외국음식전문점(인도,태국등)": "분류 안된 외국식 음식점",
        "정종/대포집/소주방": "요리 주점", "패밀리레스트랑": "패밀리레스토랑", "한식": "기타 한식 음식점", "식육(숯불구이)": "기타 한식 음식점", "기타": "기타 한식 음식점"}
CAFE = {"커피숍": "카페", "다방": "카페", "전통찻집": "카페", "편의점": "편의점", "아이스크림": "아이스크림/빙수", "떡카페": "떡/한과", "과자점": "빵/도넛"}
SIMPLE = {"barber_shops": "미용실", "beauty_salons": "미용실", "public_baths": "목욕탕/사우나", "fitness_centers": "헬스장", "swimming_pools": "수영장", "golf_practice_ranges": "골프 연습장",
          "billiard_halls": "당구장", "martial_arts_dojo": "태권도/무술학원", "comprehensive_sports_facilities": "종합 스포츠시설", "karaoke_rooms": "노래방", "pc_bangs": "PC방",
          "pharmacies": "약국", "optical_shops": "안경렌즈 소매업", "animal_hospitals": "동물병원", "bakeries": "빵/도넛", "livestock_retail": "정육점"}
def ld_type(r):
    s, u = r["slug"], str(r["업태구분명"] or "")
    if s == "clinics": return clinic_type(r["사업장명"], r["의료기관종별명"])
    if s == "hospitals": return CODE[HOSP[r["의료기관종별명"]]] if r["의료기관종별명"] in HOSP else None
    if s == "general_restaurants": return CODE[REST[u]] if u in REST else None
    if s == "rest_cafes": return CODE[CAFE[u]] if u in CAFE else None
    if s == "laundries": return CODE["셀프 빨래방"] if u == "빨래방업" else CODE["세탁소"]
    if s == "oil_retailers": return CODE["주유소"] if u == "주유소" else (CODE["가정용 연료 소매업"] if u == "일반판매소" else None)
    if s == "large_scale_retail_stores": return CODE["슈퍼마켓"] if u == "대형마트" else None
    if s == "pet_grooming": return "LD:반려동물 미용업"
    if s == "animal_boarding": return "LD:반려동물 위탁업"
    if s in SIMPLE: return CODE[SIMPLE[s]]
    return None
MED_SLUGS = {"clinics", "hospitals", "pharmacies"}
# 가게에 함께 붙는 인허가 (그 자체로 시설이 아니라, 가게가 그 일을 한다는 표시)
FLAG_SLUGS = {"over_the_counter_medicine_stores": ("상비약판매", "안전상비의약품"), "pay_as_you_throw_bag_retailers": ("종량제봉투판매", "쓰레기종량제봉투"),
              "tobacco_retailers": ("담배판매", "담배소매업")}
# 인허가 업종 이름에서 'XX_' 앞부분을 뺀 이름이 그외인허가 칸에 들어감 (예: '자원환경_쓰레기종량제봉투판매업')

# ---- 주소·상호 ----
DAEGU_ADDR = re.compile(r"^\s*(대구광역시|대구시|대구 |경상북도 군위군|경북 군위군)")
def in_daegu(addr):
    a = str(addr or "")
    return bool(DAEGU_ADDR.search(a)) or a.strip() == ""
_ALLU = {x["소분류"].replace("/", "").replace(" ", "").replace(";", "") for x in L}
PLACEHOLDER = {"업소명없음", "상호없음", "무명", "미상", "없음", "상호미상", ""}
def _k(s): return re.sub(r"[\s/;·.,()]", "", str(s or ""))
def no_name(name, upjong):
    # 상호가 없는 가게: '업소명없음'이거나 업종 이름 그대로(예: 상호 '슈퍼마켓') → 어느 가게인지 특정할 수 없어 안내하지 않음
    p = _k(name)
    return p in PLACEHOLDER or p == _k(upjong) or p in _ALLU

# ---- 아파트 단지 안 시설 (10/15 헌준님 판단) ----
#  단지 경로당·단지 작은도서관은 그 단지 주민 위주로 운영되어, 단지 밖 주민에게는 대안으로 안내하지 않음
#  (단지 시설을 다니던 분께는 동네 경로당·공공도서관을 안내해도 되지만, 그 반대는 안 됨)
#  상호·주소·운영기관으로 판정. 틀릴 때 위험한 쪽(단지 시설을 동네 시설로 보는 것)을 피하려고 넓게 잡음
APT_WORD = (r"아파트|단지|APT|타운|빌라|맨션|맨숀|하이츠|팰리스|펠리스|캐슬|자이|푸르지오|래미안|편한세상|e-편한|힐스테이트|아이파크|롯데|우방|청구|태왕|서한|코오롱|위브|SK|더샵|"
            r"휴먼시아|LH|엘에이치|주공|시영|그린빌|한신|보성|유보라|데시앙|수자인|하늘채|리버|센트럴|시티|씨티|월드|메르디앙|파크|레이크|포레|힐즈|더휴|휴플러스|휴포레|스타힐스|이다음|"
            r"아이위시|IWISH|예미지|우미린|풍경채|코아|그랜드|빌$|빌\s|가든|하이빌|아트빌|궁전|로얄|삼익|동서|신동아|동신|협성|화성|영남|동아|대림|삼성|현대|한라|쌍용|금호|효성|벽산|신일|"
            r"반도|대우|두산|영조|동화|세영|대백|에덴|청아람|강변|녹원|성원|럭키|태영|건영|내안애|뜨란채|엘레브|해모로|노르웨이|아이프라임|메트로|트루엘|하이엔|오페라|헤리티지|타워|스위첸|"
            r"어울림|리더스|호반|다숲|웰리치|중흥|캐스빌|클래스|예다음|엘크루|파라곤|금탑|행복주택|이진|영무|선수촌|힐데스하임|트레빌|메가시티|휴먼|천년나무|그린코아|브라운스톤|"
            r"빌\s?경로당|빌\s?(작은)?도서관|에스케이|푸르나임|나우빌|유앤아이|유니드|더샾|삼정|에일린|이안|비스타|스위트|넥스빌|아이투빌|혁신|네스빌|"
            r"[가-힣A-Za-z0-9]A\s?경로당|\dA|[0-9]차|\d단지")
def in_complex(name, addr="", op=""):
    n = str(name or ""); a = str(addr or ""); o = str(op or "")
    if re.search(r"구청|군청|주민센터|행정복지센터|문화재단|복지관|새마을|노인회|청소년", o): return False   # 구청·주민센터·복지관이 운영하면 공공
    m = re.search(r"\(([^()]*)\)\s*$", a); inner = m.group(1) if m else ""
    if "," in inner and not re.search(r"복지관|주민센터|행정복지|교회|천주교|센터|노인회", inner.split(",", 1)[1]): return True   # 도로명주소 괄호 안 건물 이름(공동주택)
    if re.search(r",\s*\d+호|\d+호\s*\(|\d{3}동|[0-9]+동\s*[0-9]+층|단지|아파트", a): return True
    return bool(re.search(APT_WORD, n) or re.search(APT_WORD, o))
