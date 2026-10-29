# 보여 주기 직전 실시간 영업 확인 (카카오 지도 장소 검색)
# - 상가 자료에만 근거한 가게(인허가로 영업 확인이 안 되는 업종)는 지금도 그 자리에 있는지 카카오 지도에서 찾아본다
# - 이름이 거의 같고(띄어쓰기·지점명 무시) 좌표가 가까운 장소가 있으면 '지도에서 확인됨', 없으면 '지도에서 찾지 못함'
# - 카카오 이용 조건: 검색 결과를 파일이나 데이터베이스에 저장하지 않는다. 이 모듈은 결과를 어디에도 쓰지 않고 그 자리에서 판단만 한다
import os, re, json, math, urllib.request, urllib.parse
from rapidfuzz import fuzz
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
NEED = {"인허가 대상 아님", "본업 인허가 없음"}   # 이 상태의 상가 가게만 실시간 확인 (인허가 영업·공공 자료는 따로 근거가 있음)

BRAND = [(r"씨유|CU", "CU"), (r"지에스\s?\(?GS\)?\s?25|지에스\s?25|GS25", "GS25"), (r"세븐일레븐|7-?eleven|세븐", "세븐일레븐"), (r"이마트24|emart24", "이마트24"),
         (r"미니스톱", "미니스톱"), (r"파리바게뜨|파리바게트", "파리바게뜨"), (r"뚜레쥬르", "뚜레쥬르"), (r"배스킨라빈스|베스킨라빈스", "배스킨라빈스")]
def _clean(s):
    s = re.sub(r"\(.*?\)|주식회사|\(주\)|㈜", " ", str(s))
    for p, b in BRAND: s = re.sub(p, b + " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()
def _norm(s):
    # 비교용 전체 이름 (띄어쓰기·괄호 뺌, 브랜드 표기 통일: 씨유→CU, 지에스25→GS25)
    return re.sub(r"\s", "", _clean(s))
def _base(s):
    # 지점명을 뺀 이름: 띄어 쓴 마지막 낱말이 '…점'이면 뺌 (예: '막창도둑 대구율하점' → '막창도둑'), 브랜드로 시작하면 브랜드만
    c = _clean(s); t = c.split(" ")
    for _, b in BRAND:
        if c.startswith(b): return b
    if len(t) > 1 and t[-1].endswith("점"): t = t[:-1]
    return "".join(t)

class LiveCheck:
    def __init__(self, root=ROOT, radius=150):
        self.key = open(os.path.join(root, "settings", "kakao_key.txt"), encoding="utf-8").read().strip()
        self.radius = radius

    def needed(self, row):
        if row.get("업종코드") == "PUB:장례식장":   # 2023년 공식 자료에만 있고 2026년 상가 자료에 없는 장례식장은 지금도 있는지 카카오맵으로 확인
            return "2026년 상가 자료에도 있음" not in str(row.get("참고") or "")
        # 10/15 헌준님 요청: 지도에 보여 줄 가게는 모두 카카오맵과 비교 (인허가로 영업 중인 가게도). 공공·심평원 자료는 공식 목록이라 제외
        return row["출처"] in ("상가", "인허가")

    def _search(self, query, lon, lat):
        q = urllib.parse.urlencode({"query": query, "x": f"{lon:.7f}", "y": f"{lat:.7f}", "radius": self.radius, "sort": "distance", "size": 15})
        req = urllib.request.Request(URL + "?" + q, headers={"Authorization": "KakaoAK " + self.key})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())["documents"]

    # 확인과 함께, 원자료 주소가 가려진 경우 그 자리에서 보여 줄 카카오맵 주소·전화 (화면에만 쓰고 어디에도 저장하지 않음)
    @staticmethod
    def best(name, docs):
        # 같은 장소로 볼 수 있는 후보 가운데 이름이 가장 비슷한 곳 (예: '중구가족센터' → '대구중구가족센터'를 고르고 '…공동육아나눔터'는 고르지 않음)
        #  같은 곳으로 보는 기준: 이름 비슷함 85 이상, 또는 한쪽 이름이 다른 쪽에 들어 있고 글자 수 차이가 4자 이하
        n0 = _norm(name); best = None
        for d in docs:
            n1 = _norm(d["place_name"]); sc = fuzz.ratio(n0, n1)
            ok = sc >= 85 or (len(n0) >= 3 and (n0 in n1 or n1 in n0) and abs(len(n0) - len(n1)) <= 4)
            # 지점명만 다른 같은 곳 (예: '막창도둑' ↔ '막창도둑 대구율하점', '씨유두산리치점' ↔ 'CU 두산리치점'): 50m 안이고 지점명을 뺀 이름이 같을 때
            if not ok and d.get("distance") not in (None, "") and float(d["distance"]) <= 50:
                b0, b1 = _base(name), _base(d["place_name"])
                if len(b0) >= 2 and (b0 == b1 or (len(b0) >= 3 and fuzz.ratio(b0, b1) >= 90)): ok = True; sc = min(sc, 84)
            # 글자 순서만 다른 같은 곳 (예: '권진규법무사사무소' ↔ '법무사권진규사무소', '명덕분사무소' ↔ '명덕분소'): 50m 안이고 글자 구성이 거의 같을 때만
            if not ok and d.get("distance") not in (None, "") and float(d["distance"]) <= 50:
                ok = len(n0) >= 4 and (fuzz.ratio("".join(sorted(n0)), "".join(sorted(n1))) >= 85 or fuzz.partial_ratio(n0, n1) >= 90 and abs(len(n0) - len(n1)) <= 3)
                if ok: sc = min(sc, 84)
            if ok and (best is None or sc > best[0]): best = (sc, d)
        return best[1] if best else None

    def check_detail(self, name, lon, lat):
        try: docs = self._search(name, lon, lat)
        except Exception: return "확인 실패", "지도 확인이 잠시 안 됨", {}
        d = self.best(name, docs)
        if d: return "확인됨", "카카오 지도에 같은 이름의 장소가 있음", {"주소": d.get("road_address_name") or d.get("address_name", ""), "전화": d.get("phone", ""), "지도": d.get("place_url", ""), "분류": d.get("category_name", "")}
        return "찾지 못함", "카카오 지도에서 같은 이름의 장소를 찾지 못함 (문을 닫았거나 이름이 바뀌었을 수 있음)", {}

    # 반환: ("확인됨" | "찾지 못함" | "확인 실패", 근거 문장). 카카오 결과 자체는 돌려주지 않음(저장 방지)
    def check(self, name, lon, lat):
        v, why, _ = self.check_detail(name, lon, lat)
        return v, why
