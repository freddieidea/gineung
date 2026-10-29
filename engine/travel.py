# 주민의 이동 조건 (2026-10-15): 대화에서 알아낸 '어떻게 가는지·어디 근처인지·얼마나 멀리까지인지'로 대안을 다시 줄 세운다
# 카카오 이용 조건: 카카오 응답(장소·길찾기·지도 확인)은 파일이나 데이터베이스에 저장하지 않는다. 그 대화의 답에만 쓰고 기록에도 남기지 않음
#  - 걸어서: 우리 걷는 길 지도 (engine/walk.py)
#  - 자가용·택시: 카카오모빌리티 길찾기 (실시간). 택시는 예상 요금도
#  - 버스·지하철: 공개 대중교통 길찾기 API가 없어 시간을 지어내지 않음 → 집과 시설 근처 정류장·역(공공 자료)과 카카오맵 대중교통 길찾기 링크로 안내
#  - 다니기 어려움: 집으로 와 주는(배달·방문) 방식을 먼저 찾고, 걸음은 '아주 천천히'로 계산
import os, re, json, math, urllib.request, urllib.parse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = ["걸어서", "버스·지하철", "자가용", "택시", "다니기 어려움"]
DAEGU_RECT = "128.35,35.60,128.95,36.45"   # 대구시(군위군 포함) 범위: 출발 장소는 이 안에서만 찾음

class TravelError(Exception):
    pass

def hav(lon1, lat1, lon2, lat2):
    r = math.radians; a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(a))

# ── 주민의 말에서 이동 조건 찾기 (언어 모델 없이도 동작. 확실한 말만 잡고, 없으면 None → 대화에서 물어봄) ──
MODE_KW = [("다니기 어려움", r"못 ?걸|거동|누워|외출(이|을)? ?(못|어려)|집(으)?로 (와|오)|방문(해|으로)|나가기 (힘|어려)"),
           ("택시", r"택시"),
           ("자가용", r"자가용|운전|내 ?차|차(로|를|가 있| 타고| 끌고)|태워|주차|자차"),
           ("버스·지하철", r"버스|지하철|전철|대중교통|도시철도|마을버스"),
           ("걸어서", r"걸어|걸어서|도보|걷|산책")]
def parse_conditions(text):
    t = re.sub(r"\s+", " ", text or "")
    c = {}
    for m, pat in MODE_KW:
        if re.search(pat, t): c["mode"] = m; break
    m = re.search(r"(\d+)\s*분\s*(안|이내|내|정도|까지|거리)", t)
    if m and 1 <= int(m.group(1)) <= 120: c["max_min"] = int(m.group(1))
    m = re.search(r"([가-힣A-Za-z0-9·]{2,20}?)\s*(근처|쪽|부근|가까운 ?곳|에서 가까운|주변|인근)", t)
    if m and not re.search(r"^(집|우리 ?집|여기|이|그|저|가까운|제일|가장|동네)$", m.group(1)): c["origin_text"] = m.group(1)
    w = re.findall(r"주말|토요일|일요일|공휴일|저녁|밤|새벽|아침|오늘|지금|평일", t)
    if w: c["when"] = list(dict.fromkeys(w))
    wants = [k for k, pat in [("주차", r"주차"), ("휠체어", r"휠체어|엘리베이터|계단 ?없|문턱"), ("싼 곳", r"싼|저렴|무료|값이 ?싸"), ("예약", r"예약")] if re.search(pat, t)]
    if wants: c["wants"] = wants
    return c

class Kakao:
    def __init__(self, root=ROOT):
        self.key = open(os.path.join(root, "settings", "kakao_key.txt"), encoding="utf-8").read().strip()
    def _get(self, url, params):
        req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"Authorization": "KakaoAK " + self.key})
        with urllib.request.urlopen(req, timeout=8) as r: return json.loads(r.read().decode())
    def _post(self, url, body):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Authorization": "KakaoAK " + self.key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r: return json.loads(r.read().decode())
    # 출발 장소 찾기: 장소 이름 → 대구 안의 후보 (이름·주소·좌표). 주민에게 맞는지 꼭 다시 물어봄
    def find_place(self, text, lon, lat):
        try:
            j = self._get("https://dapi.kakao.com/v2/local/search/keyword.json", {"query": text, "rect": DAEGU_RECT, "x": f"{lon:.7f}", "y": f"{lat:.7f}", "sort": "accuracy", "size": 5})
            docs = j["documents"]
            if not docs:
                j = self._get("https://dapi.kakao.com/v2/local/search/address.json", {"query": text, "size": 5})
                docs = [{"place_name": d["address_name"], "address_name": d["address_name"], "road_address_name": "", "x": d["x"], "y": d["y"]} for d in j["documents"]]
        except Exception: raise TravelError("장소 찾기가 잠시 안 됨")
        out = []
        for d in docs:
            x, y = float(d["x"]), float(d["y"])
            if not (128.35 <= x <= 128.95 and 35.60 <= y <= 36.45): continue   # 대구 밖은 받지 않음
            out.append({"이름": d["place_name"], "주소": d.get("road_address_name") or d["address_name"], "경도": x, "위도": y})
        return out[:3]
    # 자가용: 한 출발지에서 여러 목적지까지 (반경 10km 안). 반환 {key: (거리 m, 시간 초)}
    def car_many(self, lon, lat, pts):
        out = {}
        for k in range(0, len(pts), 30):
            body = {"origin": {"x": f"{lon:.7f}", "y": f"{lat:.7f}"}, "radius": 10000, "priority": "TIME",
                    "destinations": [{"x": f"{x:.7f}", "y": f"{y:.7f}", "key": key} for key, x, y in pts[k:k + 30]]}
            try: j = self._post("https://apis-navi.kakaomobility.com/v1/destinations/directions", body)
            except Exception: raise TravelError("길찾기가 잠시 안 됨")
            for r in j.get("routes", []):
                if r.get("result_code") == 0: out[r["key"]] = (r["summary"]["distance"], r["summary"]["duration"])
        return out
    # 자가용 가는 길 선 (한 곳, 10/26 헌준님: 지도에 경로 표시). 그 답의 지도에만 그리고 파일·기록에 남기지 않음
    def car_path(self, lon, lat, x, y, max_pts=180):
        try:
            j = self._get("https://apis-navi.kakaomobility.com/v1/directions", {"origin": f"{lon:.7f},{lat:.7f}", "destination": f"{x:.7f},{y:.7f}", "priority": "TIME", "summary": "false"})
            v = [c for sec in j["routes"][0].get("sections", []) for r in sec.get("roads", []) for c in r.get("vertexes", [])]
        except Exception: return None
        pts = [[v[i + 1], v[i]] for i in range(0, len(v) - 1, 2)]
        if len(pts) < 2: return None
        k = max(1, len(pts) // max_pts)
        return pts[::k] + ([pts[-1]] if (len(pts) - 1) % k else [])
    # 택시 예상 요금 (한 곳)
    def taxi_fare(self, lon, lat, x, y):
        try:
            j = self._get("https://apis-navi.kakaomobility.com/v1/directions", {"origin": f"{lon:.7f},{lat:.7f}", "destination": f"{x:.7f},{y:.7f}", "priority": "RECOMMEND"})
            return j["routes"][0]["summary"]["fare"]["taxi"]
        except Exception: return None

def map_link(mode, a, b):
    # 카카오맵 길찾기 링크 (a, b = (이름, 경도, 위도)). 버스·지하철은 카카오맵이 노선·시간을 직접 계산
    by = {"걸어서": "walk", "다니기 어려움": "walk", "자가용": "car", "택시": "car", "버스·지하철": "traffic"}[mode]
    q = lambda p: urllib.parse.quote(f"{p[0]},{p[2]:.6f},{p[1]:.6f}", safe=",")
    return f"https://map.kakao.com/link/by/{by}/{q(a)}/{q(b)}"
def place_link(name, lon, lat):
    return "https://map.kakao.com/link/map/" + urllib.parse.quote(f"{name},{lat:.6f},{lon:.6f}", safe=",")

class Stops:
    # 버스정류장·도시철도역 (공공 자료) 가운데 걸어서 가장 가까운 곳
    def __init__(self, engine):
        F = engine.F; self.E = engine
        S = F[F["업종코드"].isin(["PUB:버스정류장", "PUB:도시철도역"]) & (F["대안후보"] == "예") & F["x"].notna()]
        self.pts = [(f, float(r["경도"]), float(r["위도"]), r["상호"], r["업종코드"]) for f, r in S.iterrows()]
    def nearest(self, lon, lat, speed="보통", k=1, within=800):
        cand = sorted(self.pts, key=lambda p: hav(lon, lat, p[1], p[2]))[:25]
        cand = [p for p in cand if hav(lon, lat, p[1], p[2]) <= within]
        if not cand: return []
        W = self.E.walk.distances_to_points(lon, lat, [(p[0], p[1], p[2]) for p in cand], max_m=within * 2)
        rows = [(W[p[0]], p) for p in cand if W.get(p[0]) is not None]
        rows.sort(key=lambda x: x[0])
        return [{"이름": p[3], "종류": "지하철역" if p[4] == "PUB:도시철도역" else "버스정류장", "걷는거리_m": int(round(w)),
                 "걷는시간_분": self.E.walk.minutes(w, speed)} for w, p in rows[:k]]
