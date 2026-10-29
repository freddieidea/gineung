# 문 닫음 판정 원칙 검사 (pipeline/permit_status.py). 사용: python engine/test_permits.py
import os, sys, datetime
sys.path[:0] = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline")]
import pandas as pd
from permit_status import Permits
A = "대구광역시 수성구 용학로 325"; B = "대구광역시 중구 동성로 10"
rows = [  # ld_id, slug, 사업장명, 영업상태명, 인허가일자, 폐업일자, 도로명주소
    ("t1", "rest_cafes", "씨유가나점", "폐업", "2019-01-01", "2026-09-01", A),
    ("t2", "pay_as_you_throw_bag_retailers", "씨유 가나점", "영업/정상", "2019-01-02", None, A),            # 예전부터 있던 다른 인허가 → 확인 필요
    ("p1", "general_restaurants", "빅스타피자", "폐업", "2020-01-01", "2026-09-04", B),
    ("p2", "general_restaurants", "빅스타피자 구지점", "영업/정상", "2026-09-04", None, B),                 # 닫은 뒤 새로 받음 → 영업
    ("h1", "bakeries", "앤티앤스홈플러스 동성점", "폐업", "2015-01-01", "2026-06-05", "대구광역시 중구 동성로 20"),
    ("h2", "tobacco_retailers", "홈플러스(주) 동성점", "영업/정상", "2026-05-28", None, "대구광역시 중구 동성로 20"),   # 큰 건물(홈플러스)의 다른 가게 → 폐업
    ("o1", "general_restaurants", "옛날식당", "폐업", "2010-01-01", "2020-01-01", "대구광역시 남구 대명로 1"),
    ("o2", "instant_food_processors", "옛날식당", "영업/정상", "2012-01-01", None, "대구광역시 남구 대명로 1"),     # 아주 오래전 폐업 → 폐업
    ("s1", "pharmacies", "새약국", "폐업", "2018-01-01", "2026-10-01", "대구광역시 북구 연암로 1"),             # 다른 인허가 없음 → 폐업
    ("c1", "general_restaurants", "1847영남대학교 병원점", "폐업", "2020-01-01", "2026-02-02", "대구광역시 남구 현충로 170"),
    ("c2", "hospitals", "영남대학교병원", "영업/정상", "1983-03-14", None, "대구광역시 남구 현충로 170"),         # 병원 안 카페 → 병원 인허가와 다른 가게
]
P = Permits(pd.DataFrame(rows, columns=["ld_id", "slug", "사업장명", "영업상태명", "인허가일자", "폐업일자", "도로명주소"]))
T = datetime.date(2026, 10, 16); fails = []
def check(name, got, want):
    ok = got == want; print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  (나옴: {got})"))
    if not ok: fails.append(name)
for lid, want, name in [("t1", "확인 필요", "편의점: 휴게음식점만 닫히고 종량제 봉투 판매는 영업 → 확인 필요"),
                        ("p1", "영업", "닫은 뒤 이름을 조금 바꿔 다시 받음 → 영업"),
                        ("h1", "폐업", "홈플러스 안 빵집: 홈플러스 담배 인허가는 다른 가게 → 폐업"),
                        ("o1", "폐업", "아주 오래전 폐업에 남은 인허가 → 폐업"),
                        ("s1", "폐업", "다른 인허가 없음 → 폐업"),
                        ("c1", "폐업", "병원 안 카페: 병원 인허가는 다른 가게 → 폐업")]:
    r = next(x for x in rows if x[0] == lid)
    check(name, P.verdict(lid, r[2], r[6], r[5], today=T)[0], want)
print(f"\n실패 {len(fails)}"); sys.exit(1 if fails else 0)
