# 가게가 정말 문을 닫았는지: 그 가게의 인허가를 모두 보고 판단 (10/16, 헌준님 '폐업·현재 시설에 오류가 없는지' 점검에서 나온 원칙)
#  가게 하나에 인허가가 여러 개 붙는 경우가 많음 (편의점: 휴게음식점·담배·상비약·종량제 봉투 / 식당: 일반음식점·즉석판매 등)
#  예전에는 시설과 짝지은 인허가 하나만 보고 폐업으로 봄 → 담배 인허가만 닫힌 편의점, 주인이 바뀌어 인허가를 다시 받은 가게도 '문 닫음'이 됨
# 판정 (같은 건물 주소 + 같은 상호의 인허가끼리 한 가게로 봄)
#   영업      : 닫힌 인허가 말고, 같은 가게 이름의 인허가가 문 닫기 30일 전 이후에 새로 나서 영업 중 (주인 바뀜·인허가 다시 받음)
#   확인 필요 : 같은 가게의 다른 인허가가 아직 영업으로 남아 있음 (예전부터 있던 것). 실제로 닫았는지 자료만으로는 알 수 없음
#              → 주민에게 '문 닫음'으로 단정하지 않고, 대안으로도 바로 권하지 않으며, 담당자에게 확인을 요청
#   폐업      : 같은 가게의 다른 인허가도 모두 닫혔거나 없음
#  다른 인허가가 예전 것이면 주인이 폐업 신고를 빠뜨린 것일 수도 있어 '확인 필요'로 둠 (어느 쪽이 맞는지 추측하지 않음)
import re, datetime
import pandas as pd
from unit_addr import unit
from ld_common import norm, sim
from rapidfuzz import fuzz
SLACK = 30
UNSURE_DAYS = 400   # '확인 필요'는 이만큼 안에 닫힌 곳에만 씀 (아주 오래전 폐업에 남은 인허가는 폐업 신고를 빠뜨린 것으로 보고 폐업 그대로)
NAMES = {"tobacco_retailers": "담배 소매", "pay_as_you_throw_bag_retailers": "종량제 봉투 판매", "over_the_counter_medicine_stores": "안전상비의약품 판매",
         "rest_cafes": "휴게음식점", "general_restaurants": "일반음식점", "instant_food_processors": "즉석판매제조가공", "bakeries": "제과점",
         "group_meal_facilities": "집단급식소", "health_functional_food_general_retailers": "건강기능식품 판매", "livestock_retail": "축산물 판매",
         "other_food_retailers": "식품 판매", "medical_device_sales_rental": "의료기기 판매"}
def _contains(new, old):
    """새 인허가 이름이 문 닫은 가게 이름을 그대로 품음 (예: '빅스타피자' → '빅스타피자 구지점'). 거꾸로(큰 건물 이름 '홈플러스'가 '앤티앤스 홈플러스점'에 들어 있음)는 아님"""
    new, old = norm(new).replace("대구", ""), norm(old).replace("대구", "")
    return len(old) >= 3 and old in new
def _same(a, b):
    """같은 가게의 인허가인지: 상호가 거의 같거나(유사도 85 이상), 한쪽이 다른 쪽에 들어 있고 남는 말이 지점 표시(대구·본점·지점·○호점)뿐일 때
    — 큰 건물 이름이 들어간 다른 가게(예: '1847 영남대학교병원점' 카페와 영남대학교병원, '앤티앤스 홈플러스 수성점'과 홈플러스)는 같은 가게로 보지 않음"""
    a, b = norm(a).replace("대구", ""), norm(b).replace("대구", "")
    if not a or not b: return False
    if fuzz.ratio(a, b) >= 85: return True
    lo, hi = (a, b) if len(a) <= len(b) else (b, a)
    if len(lo) >= 3 and lo in hi:
        rest = hi.replace(lo, "", 1)
        rest = re.sub(r"(본점|지점|직영점|\d+호점|점)$", "", rest)
        return rest == ""
    return False
try:
    import fetch_localdata as _FL
    for _s, _n in _FL.SLUG.items(): NAMES.setdefault(_s, _n.split("_", 1)[-1].replace("업", "") if _n.endswith("업") else _n.split("_", 1)[-1])
except Exception: pass
def _day(x):
    try: return datetime.date.fromisoformat(str(x)[:10])
    except Exception: return None

class Permits:
    """인허가 표(최신 자료) → 건물별 색인. 열: ld_id, slug, 사업장명, 영업상태명, 인허가일자, 폐업일자, 도로명주소"""
    def __init__(self, L):
        L = L[["ld_id", "slug", "사업장명", "영업상태명", "인허가일자", "폐업일자", "도로명주소"]].copy()
        self.st = dict(zip(L["ld_id"], L["영업상태명"].fillna("")))   # 상태는 모든 인허가 (주소가 가려진 것도)
        L["_b"] = L["도로명주소"].map(lambda a: "" if "*" in str(a) else unit(a)[0])   # 가려진 주소('○○로*길 **', 개인 판매자)는 건물을 알 수 없어 짝짓기에 안 씀
        L = L[L["_b"] != ""]
        self.by = {b: g for b, g in L.groupby("_b")}
    def state(self, ld_id):
        s = self.st.get(ld_id)
        return None if s is None else ("영업" if s.startswith("영업") else ("휴업" if s.startswith("휴업") else "폐업"))
    def others(self, ld_id, name, addr, loose=False):
        if "*" in str(addr or ""): return None
        b = unit(addr)[0]
        g = self.by.get(b)
        if g is None: return g
        f = (lambda n: _same(n, name) or _contains(n, name)) if loose else (lambda n: _same(n, name))
        return g[(g["ld_id"] != ld_id) & g["사업장명"].map(f)]
    def last_close(self, ld_id, name, addr, close_day):
        """그 가게가 마지막으로 인허가를 닫은 날 (짝지은 인허가는 오래전에 닫혔어도 다른 인허가를 최근에 닫았으면 그날)"""
        g = self.others(ld_id, name, addr); days = [str(close_day or "")[:10]]
        if g is not None: days += [str(x)[:10] for x in g.loc[~g["영업상태명"].fillna("").str.startswith("영업"), "폐업일자"].dropna()]
        days = [d for d in days if _day(d)]
        return max(days) if days else ""
    def verdict(self, ld_id, name, addr, close_day, today=None):
        """돌려줌: (판정, 까닭, 남은 인허가 목록 — '영업'이면 새로 받은 인허가 id 하나)
        문 닫은 뒤 새로 난 인허가는 이름이 조금 달라도(예: '빅스타피자' → '빅스타피자 다사점') 같은 가게가 이어 하는 것으로 봄"""
        c = _day(close_day); lim = (c - datetime.timedelta(days=SLACK)).isoformat() if c else "9999"
        gl = self.others(ld_id, name, addr, loose=True)
        if gl is not None:
            new = gl[gl["영업상태명"].fillna("").str.startswith("영업") & (gl["인허가일자"].fillna("") >= lim)]
            if len(new): return "영업", f"문 닫은 뒤 같은 이름으로 인허가를 다시 받음 ({NAMES.get(new.iloc[0]['slug'], new.iloc[0]['slug'])} '{new.iloc[0]['사업장명']}', {str(new.iloc[0]['인허가일자'])[:10]})", [new.iloc[0]["ld_id"]]
        g = self.others(ld_id, name, addr)
        op = g[g["영업상태명"].fillna("").str.startswith("영업")] if g is not None else []
        if g is None or len(op) == 0: return "폐업", "같은 가게의 다른 인허가도 모두 닫혔거나 없음", []
        left = [f"{NAMES.get(s, s)} ({str(d)[:10]}부터)" for s, d in zip(op["slug"], op["인허가일자"])]
        today = today or datetime.date.today()
        if c and (today - c).days > UNSURE_DAYS: return "폐업", "오래전에 닫힘 (남은 인허가는 폐업 신고를 빠뜨린 것으로 봄)", left
        return "확인 필요", "같은 가게의 다른 인허가가 아직 영업으로 남아 있음: " + ", ".join(left), left

def load_dump(d, slugs, orgs):
    """하루치 인허가 자료 폴더 → 한 표 (ld_id = slug:구군:관리번호)"""
    import os
    L = []
    for slug in slugs:
        for gu in orgs:
            p = f"{d}/{slug}__{gu}.csv"
            if not os.path.exists(p): continue
            x = pd.read_csv(p, dtype=str, usecols=lambda c: c in ("관리번호", "사업장명", "영업상태명", "인허가일자", "폐업일자", "도로명주소", "업태구분명", "데이터갱신시점", "전화번호"))
            x["ld_id"] = f"{slug}:{gu}:" + x["관리번호"]; x["slug"] = slug; x["인허가업종"] = slugs[slug]; L.append(x)
    return pd.concat(L, ignore_index=True).drop_duplicates("ld_id") if L else pd.DataFrame(columns=["ld_id", "slug"])
