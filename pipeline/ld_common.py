# 인허가 대조에 함께 쓰는 정의: 상가 업종별 본업 인허가, 상호 정리, 상호 유사도
import re
from rapidfuzz import fuzz
PRIMARY={  # 상가 업종 → 그 가게의 본업 인허가
 "I2":["general_restaurants","rest_cafes","bakeries"],
 "미용실":["beauty_salons","barber_shops"],"세탁소":["laundries"],"셀프 빨래방":["laundries"],"목욕탕/사우나":["public_baths"],
 "약국":["pharmacies"],"안경렌즈 소매업":["optical_shops"],"의료기기 소매업":["medical_device_sales_rental"],"유사 의료업":["medical_related_businesses"],
 "헬스장":["fitness_centers"],"수영장":["swimming_pools"],"골프 연습장":["golf_practice_ranges"],"당구장":["billiard_halls"],"태권도/무술학원":["martial_arts_dojo"],
 "종합 스포츠시설":["comprehensive_sports_facilities"],"노래방":["karaoke_rooms"],"PC방":["pc_bangs"],"비디오방":["video_viewing_rooms"],"전자 게임장":["general_game_providers"],
 "정육점":["livestock_retail"],"우유 소매업":["livestock_retail"],"건강보조식품 소매업":["health_functional_food_general_retailers"],
 "동물병원":["animal_hospitals"],"애완동물/애완용품 소매업":["animal_sales","pet_grooming","animal_boarding"],
 "주유소":["oil_retailers"],"가정용 연료 소매업":["oil_retailers"],"떡/한과":["instant_food_processors","bakeries","rest_cafes"],"반찬/식료품 소매업":["instant_food_processors"],
 "편의점":["rest_cafes","tobacco_retailers"],"슈퍼마켓":["other_food_retailers","large_scale_retail_stores","tobacco_retailers"],
 "산후 조리원":["postpartum_care"],
 "마사지/안마":["medical_related_businesses"],
}
def primary_for(code,name):
    if name in PRIMARY: return PRIMARY[name]
    if code.startswith("I2"): return PRIMARY["I2"]
    if code.startswith("Q1"): return ["clinics","hospitals"]
    return []
def norm(s):
    s=str(s or "")
    s=re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(사\)|\s|[()\[\]·.,'\"\-_/&]","",s)
    return s.lower()
def sim(a,b):
    if not a or not b: return 0
    if a==b: return 100
    s=fuzz.ratio(a,b)
    if min(len(a),len(b))>=3 and (a in b or b in a): s=max(s,92)
    return s
GENERIC=re.compile(r"(대구|본점|지점|직영점|\d*호?점|코리아|주식회사|주)$")
def same_biz(nm,nm0,ln):
    # 다른 인허가(상비약·종량제봉투·담배 등)를 이 가게 것으로 볼지: 상호가 거의 같거나, 가게 이름이 인허가 이름 안에 들어 있거나,
    # 인허가 이름이 가게 이름 안에 들어 있되 나머지가 지점명 같은 일반 낱말뿐일 때만 (10/14: 이마트 안 네일숍에 이마트 종량제봉투 허가가 붙던 오류)
    ln=ln.replace("대구","")
    for n in (nm,nm0):
        n=(n or "").replace("대구","")
        if not n or not ln: continue
        if fuzz.ratio(n,ln)>=85 or (len(n)>=3 and n in ln): return True
        if len(ln)>=3 and ln in n:
            rest=n.replace(ln,"",1)
            if not rest or GENERIC.fullmatch(rest) or re.fullmatch(r"[가-힣]{0,4}점",rest): return True
    return False
