# 실시간 장소 찾기 (카카오 지도 장소 검색) — 공공데이터에 대구 전체 목록이 없는 시설(은행·ATM)을 주민이 물을 때 그 자리에서 찾는다
# - 카카오 이용 조건: 검색 결과를 파일이나 데이터베이스에 저장하지 않는다. 결과는 그 대화의 답에만 쓰고, 어디에도 기록하지 않는다
#   (지자체 기록에도 남기지 않음. 몇 곳을 찾았는지 숫자만 남길 수 있음)
# - 이름·주소·전화는 카카오 응답 값을 그대로 쓰고(섞임 방지), verify()가 응답과 글자까지 같은지 다시 확인한다
# - 걷는 거리는 우리 걷는 길 지도로 계산 (engine/walk.py)
import os, re, json, math, urllib.request, urllib.parse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://dapi.kakao.com/v2/local/search/category.json"
BANKS = r"농협|NH|국민|KB|신한|우리|하나|기업|IBK|iM|아이엠|대구은행|DGB|새마을금고|신협|우체국|SC제일|제일은행|씨티|수협|부산은행|경남은행|산업은행|저축은행|카카오"
SRC = "카카오맵에 '은행'으로 등록된 곳 (지금 검색한 결과, 저장하지 않음)"

class LiveError(Exception):
    pass

def _hav(lon1, lat1, lon2, lat2):
    r = math.radians; a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(a))

def is_atm(d):
    return d["category_name"].endswith("> ATM") or bool(re.search(r"ATM|365|자동화", d["place_name"], re.I))

class LiveBanks:
    def __init__(self, walk, root=ROOT):
        self.key = open(os.path.join(root, "settings", "kakao_key.txt"), encoding="utf-8").read().strip()
        self.walk = walk

    def _fetch(self, lon, lat, radius):
        docs = []
        for page in (1, 2, 3):
            q = urllib.parse.urlencode({"category_group_code": "BK9", "x": f"{lon:.7f}", "y": f"{lat:.7f}", "radius": radius, "sort": "distance", "size": 15, "page": page})
            req = urllib.request.Request(URL + "?" + q, headers={"Authorization": "KakaoAK " + self.key})
            with urllib.request.urlopen(req, timeout=8) as r: j = json.loads(r.read().decode())
            docs += j["documents"]
            if j["meta"]["is_end"]: break
        return docs

    # what: "창구"(은행 지점) | "ATM"(ATM·365코너) | "모두". bank: 주민이 말한 은행 이름(있으면 그 은행만)
    def search(self, lon, lat, what="모두", bank=None, radius=2000, n=5, speed="보통"):
        try: docs = self._fetch(lon, lat, radius)
        except Exception as e: raise LiveError("은행 검색이 잠시 안 됨")
        keep = []
        for d in docs:
            atm = is_atm(d)
            if what == "창구" and atm: continue
            if what == "ATM" and not atm: continue
            if bank and bank not in d["place_name"]: continue
            keep.append(d)
        W = self.walk.distances_to_points(lon, lat, [(d["id"], float(d["x"]), float(d["y"])) for d in keep])
        cards = []
        for d in keep:
            w = W[d["id"]]
            cards.append({"fid": "KAKAO:" + d["id"], "실시간": True, "상호": d["place_name"], "업종": "ATM·365코너" if is_atm(d) else "은행",
                          "주소": d["road_address_name"] or d["address_name"], "전화": d["phone"], "경도": float(d["x"]), "위도": float(d["y"]),
                          "직선거리_m": int(round(_hav(lon, lat, float(d["x"]), float(d["y"])))), "걷는거리_m": None if w is None else int(round(w)),
                          "걷는시간_분": self.walk.minutes(w, speed), "걸음": speed, "세부종류": None, "묶음": None,
                          "표시": [] if w is not None else ["걸어서 가기 먼 거리(8km 넘거나 길로 이어지지 않음)"], "안내": "", "참고": "",
                          "근거": SRC, "근거자료": [SRC], "지도": d.get("place_url", "")})
        cards.sort(key=lambda c: (c["걷는거리_m"] is None, c["걷는거리_m"] or c["직선거리_m"]))
        out = cards[:n]
        self.verify(out, docs, lon, lat, speed)
        return out

    # 내보내기 직전 검사: 카드의 이름·주소·전화가 방금 받은 카카오 응답과 글자까지 같은지, 걷는 거리를 다시 계산해도 같은지
    def verify(self, cards, docs, lon, lat, speed):
        by = {"KAKAO:" + d["id"]: d for d in docs}
        for c in cards:
            d = by.get(c["fid"])
            if d is None: raise LiveError(f"응답에 없는 장소: {c['fid']}")
            if c["상호"] != d["place_name"] or c["주소"] != (d["road_address_name"] or d["address_name"]) or c["전화"] != d["phone"]: raise LiveError(f"장소 정보가 응답과 다름: {c['fid']}")
            w = self.walk.distances_to_points(lon, lat, [(d["id"], float(d["x"]), float(d["y"]))])[d["id"]]
            if (w is None) != (c["걷는거리_m"] is None) or (w is not None and abs(w - c["걷는거리_m"]) > 1): raise LiveError(f"걷는 거리가 다시 계산한 값과 다름: {c['fid']}")
        return True

def bank_in(text):
    m = re.search(BANKS, text or "", re.I)
    if not m: return None
    t = m.group(0)
    return {"NH": "농협", "KB": "국민", "IBK": "기업", "아이엠": "iM", "DGB": "iM", "대구은행": "iM", "제일은행": "SC제일"}.get(t.upper() if t.isascii() else t, t)

# ---- 공공데이터에 목록이 없는 생활 목적: 카카오 키워드 검색으로 그 자리에서 찾음 (10/15). 결과는 저장하지 않음 ----
KW_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
LIVE_KW = {
    # 농기계 수리: 상호에 수리·정비·서비스가 드러난 곳은 '수리하는 곳', 농기계 대리점·판매점은 '수리해 주는지 확인'
    "P15.1.02": {"q": ["농기계 수리", "농기계"], "radius": 20000,
                 "name": r"농기|농업기계|트랙터|TYM|티와이엠|LS엠트론|LS트랙터|대동|아세아농업|국제종합기계|구보다|얀마|경운기",
                 "exclude": r"임대(?!.*수리)|육묘|종묘|비료|농약|묘목",
                 "sure": r"수리|정비|서비스|A/?S",
                 "src": "카카오맵에 농기계 업체로 등록된 곳 (지금 검색한 결과, 저장하지 않음)", "kind": "농기계 수리점", "unsure_kind": "농기계 판매점"},
}

class LiveKeyword:
    def __init__(self, walk, root=ROOT):
        self.key = open(os.path.join(root, "settings", "kakao_key.txt"), encoding="utf-8").read().strip()
        self.walk = walk

    def _fetch(self, q, lon, lat, radius):
        u = KW_URL + "?" + urllib.parse.urlencode({"query": q, "x": f"{lon:.7f}", "y": f"{lat:.7f}", "radius": radius, "sort": "distance", "size": 15})
        with urllib.request.urlopen(urllib.request.Request(u, headers={"Authorization": "KakaoAK " + self.key}), timeout=8) as r:
            return json.loads(r.read().decode())["documents"]

    # 돌려줌: (확실한 카드들, 확인이 필요한 카드들) — 이름·주소·전화는 카카오 응답 그대로
    def search(self, lid, lon, lat, n=5, speed="보통"):
        cfg = LIVE_KW[lid]; docs = {}
        try:
            for q in cfg["q"]:
                for d in self._fetch(q, lon, lat, cfg["radius"]): docs.setdefault(d["id"], d)
        except Exception: raise LiveError("지도 검색이 잠시 안 됨")
        keep = [d for d in docs.values() if re.search(cfg["name"], d["place_name"], re.I) and not re.search(cfg["exclude"], d["place_name"])]
        if not keep: return [], []
        W = self.walk.distances_to_points(lon, lat, [(d["id"], float(d["x"]), float(d["y"])) for d in keep])
        sure, unsure = [], []
        for d in keep:
            w = W[d["id"]]; ok = bool(re.search(cfg["sure"], d["place_name"], re.I))
            c = {"fid": "KAKAO:" + d["id"], "실시간": True, "상호": d["place_name"], "업종": cfg["kind"] if ok else cfg["unsure_kind"],
                 "주소": d["road_address_name"] or d["address_name"], "전화": d["phone"], "경도": float(d["x"]), "위도": float(d["y"]),
                 "직선거리_m": int(round(_hav(lon, lat, float(d["x"]), float(d["y"])))), "걷는거리_m": None if w is None else int(round(w)),
                 "걷는시간_분": self.walk.minutes(w, speed), "걸음": speed, "세부종류": None, "묶음": None,
                 "표시": ([] if w is not None else ["걸어서 가기 먼 거리(8km 넘거나 길로 이어지지 않음)"]) + ([] if ok else ["제공 여부 확인 필요"]),
                 "안내": "", "참고": "", "근거": cfg["src"], "근거자료": [cfg["src"] + (f" — 상호에 '{re.search(cfg['sure'], d['place_name'], re.I).group(0)}'" if ok else "")] if ok else [],
                 "지도": d.get("place_url", "")}
            (sure if ok else unsure).append(c)
        key = lambda c: (c["걷는거리_m"] is None, c["걷는거리_m"] or c["직선거리_m"], c["직선거리_m"])
        sure.sort(key=key); unsure.sort(key=key)
        return sure[:n], unsure[:n]

# 택시: 시설이 아니라 부르는 방법을 안내. 전화 호출은 지금 있는 곳 가까이의 '콜택시'(카카오맵 분류)만, 대구 지역번호(053)인 곳만
def live_call_taxis(key, lon, lat, n=2):
    u = KW_URL + "?" + urllib.parse.urlencode({"query": "콜택시", "x": f"{lon:.7f}", "y": f"{lat:.7f}", "radius": 15000, "sort": "distance", "size": 15})
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"Authorization": "KakaoAK " + key}), timeout=8) as r: docs = json.loads(r.read().decode())["documents"]
    except Exception: raise LiveError("지도 검색이 잠시 안 됨")
    out = [d for d in docs if d["category_name"].endswith("콜택시") and d["phone"].startswith("053") and not re.search(r"장거리|리무진|점보|모범|대형", d["place_name"])]
    return [{"이름": d["place_name"], "전화": d["phone"]} for d in out[:n]]
