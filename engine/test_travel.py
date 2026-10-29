# 이동 조건 검사 (2026-10-15): 이동 수단 질문, 버스·자가용·택시, 지도 확인, 최대 시간, 출발 장소, 결과 뒤 조건 바꾸기, 순위 안전 규칙
# 카카오는 가짜로 바꿔 끼워 매번 같은 결과로 검사함 (실제 카카오 연결은 마지막 한 항목만)
import sys, os, random, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recommend import Engine
from conversation import Conversation
from travel import TravelError, hav, Kakao
E = Engine(); fails = []
def check(n, c):
    print(("통과 " if c else "실패 ") + n); (None if c else fails.append(n))
class FakeKakao:
    def __init__(self, place=None, slow_first=False, broken=False): self.place = place; self.slow_first = slow_first; self.broken = broken; self.calls = 0
    def find_place(self, text, lon, lat): return [self.place] if self.place else []
    def car_many(self, lon, lat, pts):
        if self.broken: raise TravelError("x")
        self.calls += 1; out = {}
        for i, (k, x, y) in enumerate(pts):
            d = hav(lon, lat, x, y); t = d / 8 + (2000 if (self.slow_first and i == 0) else 0)   # 첫 후보만 일부러 아주 느리게 (차로는 다른 순서가 됨)
            if d <= 10000: out[k] = (int(d * 1.3), t)
        return out
    def taxi_fare(self, lon, lat, x, y): return 4800
class FakeLive:
    def __init__(self, miss=()): self.miss = set(miss); self.asked = []
    def needed(self, row): return row["출처"] == "상가"
    def check(self, name, lon, lat):
        self.asked.append(name); return ("찾지 못함", "") if name in self.miss else ("확인됨", "")
def conv(kakao=None, live=None):
    C = Conversation(E); C.D.log_path = None; C.kakao = kakao or FakeKakao(); C.live = live or FakeLive(); return C
LON, LAT = 128.5935, 35.8714
# 1) 이동 수단을 모르면 먼저 물어봄
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P07.2.01", kind="미용실")
r = C._next(st); check("이동 수단을 모르면 '어떻게 가실 거예요?' 질문", r["type"] == "question" and "어떻게 가실" in r["text"] and st["stage"] == "mode")
r = C.turn(st, "걸어서 가요"); check("'걸어서' → 걸음 질문", r["type"] == "question" and st["cond"]["mode"] == "걸어서" and st["stage"] == "speed")
r = C.turn(st, "보통"); res = r["result"]
check("걸어서 → 순위 1~3, 걷는 시간 순", r["type"] == "result" and [c["순위"] for c in res["순위"]] == list(range(1, len(res["순위"]) + 1))
      and ([c["걷는시간_분"] for c in res["순위"]] == sorted(c["걷는시간_분"] for c in res["순위"]) or bool(res.get("순위기준"))))   # 10/19: 걸어서 5분 차이 안이면 지금 연 곳·이야기가 많은 곳 먼저 (그 기준을 밝힘)
check("카드에 'N순위'와 카카오맵 길찾기 링크", "1순위." in r["text"] and "map.kakao.com/link/by/walk/" in r["text"])
# 2) 한 문장에 조건이 함께 있으면 묻지 않음 + 최대 시간
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P07.2.01", kind="미용실", stage="mode")
r = C.turn(st, "천천히 걸어서 5분 안에 갈 곳이요")
check("'천천히 걸어서 5분 안' → 걸음·최대 시간 함께 인식, 더 묻지 않음", r["type"] == "result" and st["speed"] == "천천히" and st["cond"].get("max_min") == 5)
check("최대 5분 → 순위의 걷는 시간 모두 5분 이하 (없으면 그렇다고 말함)", all(c["걷는시간_분"] <= 5 for c in r["result"]["순위"]) or "5분 안에 갈 수 있는 곳은 없어요" in r["text"])
# 3) 버스·지하철: 시간을 지어내지 않고 정류장·역 + 카카오맵 대중교통 길찾기
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P03.1.01", kind="정형외과", stage="mode")
r = C.turn(st, "버스 타요"); res = r["result"]
check("버스 → 정류장·역 안내, 대중교통 길찾기 링크, 버스 시간은 말하지 않음", r["type"] == "result" and "map.kakao.com/link/by/traffic/" in r["text"]
      and re.search(r"에서 내려 걸어서 약|한 번에|갈아타야|걸어가는 게 빨라요", r["text"]) and "집에서 가장 가까운 곳은" in r["text"] and not re.search(r"버스로 약 \d+분|한 번에, 약", r["text"]))
check("버스 → 정형외과만, 근거 문장(심평원)", all(c["세부종류"] == "정형외과" for c in res["순위"]) and "근거:" in r["text"])
# 4) 자가용: 카카오 길찾기 시간 순 (걷는 순서와 다를 수 있음)
K = FakeKakao(slow_first=True); C = conv(K); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P07.2.01", kind="미용실", stage="mode")
r = C.turn(st, "아들이 차로 태워 줘요"); res = r["result"]
check("자가용 → 차로 가는 시간 순, '차로 약 N분' 표시, 길찾기 car 링크", r["type"] == "result" and K.calls >= 1 and "차로 약" in r["text"] and "map.kakao.com/link/by/car/" in r["text"]
      and [c["차_시간_분"] for c in res["순위"]] == sorted(c["차_시간_분"] for c in res["순위"]))
# 5) 택시: 예상 요금
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P07.2.01", kind="미용실", stage="mode")
r = C.turn(st, "택시 타요"); check("택시 → 택시비 표시", r["type"] == "result" and "택시비 약 4,800원" in r["text"])
# 6) 길찾기가 안 되면 걷는 거리로 줄 세우고 그렇다고 말함
C = conv(FakeKakao(broken=True)); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P07.2.01", kind="미용실", stage="mode")
r = C.turn(st, "차로 가요 (직접 운전하거나 태워 줘요)"); check("길찾기 오류 → 걷는 거리 순 + 안내 문장", r["type"] == "result" and "차 길찾기가 잠시 안 돼서" in r["text"])
# 7) 지도 확인: 카카오맵에서 못 찾은 가게는 1·2순위가 아님
C0 = conv(); st0 = C0.start(LON, LAT, gu="중구"); st0.update(leaf="P07.2.01", kind="미용실", stage="mode"); r0 = C0.turn(st0, "걸어서 보통으로 가요")
first = r0["result"]["순위"][0]["상호"]
L = FakeLive(miss={first}); C = conv(live=L); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P07.2.01", kind="미용실", stage="mode")
r = C.turn(st, "걸어서 보통으로 가요"); res = r["result"]
check(f"지도에서 못 찾은 '{first}' → 1·2순위에 없음, 있으면 '확인 필요' 표시", not any(c["상호"] == first and c["순위"] <= 2 for c in res["순위"])
      and all(c["확실성"] == "확인 필요" for c in res["순위"] if c["상호"] == first))
check("지도에서 확인된 곳은 '카카오맵에서도 확인돼요' 표시", "카카오맵에서도 확인돼요" in r["text"])
# 8) 출발 장소: 카카오로 찾고 주민에게 확인한 뒤 그 근처에서
P = {"이름": "서문시장", "주소": "대구 중구 대신동 115-378", "경도": 128.5806, "위도": 35.8693}
C = conv(FakeKakao(place=P)); st = C.start(128.62, 35.88, gu="동구"); st.update(leaf="P07.2.01", kind="미용실", stage="mode")
r = C.turn(st, "서문시장 근처로 걸어서 갈래요")
check("'서문시장 근처' → 맞는지 확인 질문", r["type"] == "question" and "서문시장" in r["text"] and st["stage"] == "origin")
r = C.turn(st, "글쎄요"); check("엉뚱한 답 → 한 번 더 물어봄", r["type"] == "question" and st["stage"] == "origin")
r = C.turn(st, "네, 거기 근처요")
if r["type"] == "question" and st["stage"] == "speed": r = C.turn(st, "보통")
check("확인하면 서문시장에서 가까운 순 (첫 곳이 1km 안), 문장에 '서문시장' 근처", r["type"] == "result" and "서문시장 근처에서" in r["text"]
      and hav(P["경도"], P["위도"], r["result"]["순위"][0]["경도"], r["result"]["순위"][0]["위도"]) < 1000)
# 9) 결과를 본 뒤 '버스로 가면요?' → 다시 찾음
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P07.2.01", kind="미용실", stage="mode")
C.turn(st, "걸어서 보통으로 가요"); r = C.turn(st, "버스로 가면요?")
check("결과 뒤 '버스로 가면요?' → 버스 기준으로 다시 찾음", r["type"] == "result" and st["cond"]["mode"] == "버스·지하철" and "link/by/traffic/" in r["text"])
r = C.turn(st, "고마워요"); check("조건이 없는 말 → 끝 안내", r["type"] == "end")
# 10) 다니기 어려움 + 배달이 되는 목적 → 배달로 찾음
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P01.1.06", kind="중국집", stage="mode")
r = C.turn(st, "다니기 어려워요 (집으로 와 주면 좋겠어요)")
check("다니기 어려움 → 아주 천천히 + 배달로 찾음", st["speed"] == "아주 천천히" and st.get("need") == "배달" and r["type"] in ("result", "question"))
# 11) 이용 시간·원하는 조건은 단정하지 않고 '확인하세요'로
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P07.2.01", kind="미용실", stage="mode")
r = C.turn(st, "일요일 저녁에 주차되는 곳이요, 차로 갈게요")
check("일요일 저녁·주차 → '확인하세요'에 들어감 (된다고 말하지 않음)", r["type"] == "result" and "일요일·저녁에도 문을 여는지" in r["text"] and "주차할 수 있는지" in r["text"])
# 11-2) 인허가에만 있는 가게: 카카오맵에서 찾으면 확인된 곳으로 (반려동물 위탁은 모두 인허가에만 있음)
o = E.F[(E.F["업종"] == "반려동물 위탁업")].iloc[0]
C = conv(); st = C.start(float(o["경도"]), float(o["위도"]), gu=o["구군"]); st.update(leaf="P14.1.04", kind=None, stage="mode")
r = C.turn(st, "걸어서 보통으로 가요")
check("반려동물 위탁 → 인허가 영업 중 + 카카오맵 확인된 곳이 순위에 나옴", r["type"] == "result" and r["result"]["순위"] and all(c["확실성"] == "인허가·카카오맵 확인" for c in r["result"]["순위"]))
L = FakeLive(); L.check = lambda n, x, y: ("찾지 못함", ""); C = conv(live=L); st = C.start(float(o["경도"]), float(o["위도"]), gu=o["구군"]); st.update(leaf="P14.1.04", kind=None, stage="mode")
r = C.turn(st, "걸어서 보통으로 가요")
check("카카오맵에서 못 찾으면 올리지 않음", not r["result"]["순위"])
# 11-3) 생활 필수 서비스: 교통약자 이동 → 시설 목록 대신 나드리콜 안내 → 원하면 전화 연결
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P12.1.02", kind=None)
r = C._next(st)
check("교통약자 이동 → 나드리콜 이용 방법(대상·신청·요금·1577-6776) + 연결 질문", r["type"] == "question" and "1577-6776" in r["text"] and "회원 등록" in r["text"] and "연결해 드릴까요" in r["text"])
r = C.turn(st, "네, 전화 연결해 주세요"); check("'네' → 전화 연결 (번호를 대신 걸지 않고 '전화 걸기' 안내)", r["type"] == "connect" and r["connect"]["전화"] == "1577-6776")
# 다니기 어렵다고 하면 결과 뒤에 나드리콜을 제안, 원할 때만 안내
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P07.2.01", kind="미용실", stage="mode")
r = C.turn(st, "다니기 어려워요 (집으로 와 주면 좋겠어요)")
check("다니기 어려움 → 결과 뒤 나드리콜 제안 (묻기만 함)", r["type"] == "question" and "나드리콜" in r["text"] and "알려 드릴까요" in r["text"] and r["result"]["순위"])
r = C.turn(st, "아니요, 괜찮아요"); check("거절하면 안내하지 않고 끝", r["type"] == "end" and "1577-6776" not in r["text"])
# 장기요양 등급이 있어야 하는 곳인데 '아니요' → 등급 신청 방법 제안
C = conv(); st = C.start(128.60, 35.87, gu="중구"); st.update(leaf="P04.1.02", kind=[k for (l, k) in E.kind if l == "P04.1.02"][0], stage="mode")
r = C.turn(st, "걸어서 보통으로 가요")
if r["type"] == "question" and "해당되세요" in r["text"]: r = C.turn(st, "아니요")
check("장기요양 등급 '아니요' → 장기요양 등급 신청(1577-1000) 제안", r["type"] == "question" and "장기요양 등급 신청" in r["text"])
r = C.turn(st, "네, 알려 주세요"); check("'네' → 등급 신청 방법과 1577-1000", "1577-1000" in r["text"] and "연결해 드릴까요" in r["text"])
# 위급한 말: 묻지 않고 맨 앞에 바로 109
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P07.2.01", kind="미용실", stage="mode"); C.turn(st, "걸어서 보통으로 가요")
r = C.turn(st, "요즘 너무 힘들어서 죽고 싶어요")
check("위급한 말 → 맨 앞에 109 안내 + 전화 연결 정보", r["text"].startswith("말씀해 주셔서 고마워요") and "109" in r["text"] and r.get("connect", {}).get("전화") == "109")
# 12) 전체 훑기: 기능·종류 120개, 무작위로 지도 확인 실패를 섞어도 '확인 필요'가 1·2순위에 오지 않음
random.seed(15); bad = 0; n = 0
units = random.sample(sorted(E.kind), 120)
O = E.F[(E.F["대안후보"] == "예") & E.F["x"].notna() & (E.F["출처"] == "상가")].sample(120, random_state=15)
for (lid, k), (_, o) in zip(units, O.iterrows()):
    L = FakeLive(); C = conv(live=L)
    C.live.check = lambda name, lon, lat: ("찾지 못함", "") if random.random() < 0.4 else ("확인됨", "")
    st = C.start(float(o["경도"]), float(o["위도"]), gu=o["구군"]); st.update(leaf=lid, kind=k, speed="보통", cond={"mode": random.choice(["걸어서", "자가용", "버스·지하철"])}, elig_ok=set())
    try: res = E.recommend(lid, k, st["lon"], st["lat"], n=15, user_gu=st["gu"]); res = C._arrange(st, res)
    except RuntimeError as e:
        bad += 1; print("   ", lid, k, e); continue
    n += 1; bad += sum(1 for c in res["순위"] if c["순위"] <= 2 and c["확실성"] == "확인 필요")
check(f"전체 훑기 {n}건: '확인 필요' 시설이 1·2순위에 온 경우 0", bad == 0)
# 12-2) 대구시 노인복지관·경로식당·무료급식소 목록 (10/15)
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P01.1.07")
r = C._next(st); check("세부 종류를 모르면 짐작하지 않고 고르게 함", r["type"] == "question" and "경로 무료급식소" in r["options"] and st["stage"] == "kind")
r = C.turn(st, "무료급식소"); check("'무료급식소' → 경로 무료급식소로 알아듣고 이동 수단 질문", st.get("kind") == "경로 무료급식소" and st["stage"] == "mode")
r = C.turn(st, "밥 먹으러요"); check("이동 수단을 못 알아들으면 한 번 더 여쭤봄", r["type"] == "question" and "잘 알아듣지 못했어요" in r["text"] and not st["cond"].get("mode"))
r = C.turn(st, "걸어서 갈게요"); r = C.turn(st, "보통"); res = r["result"]
check("무료급식소 → 확실한 곳은 대구시 목록 시설만(종합사회복지관은 '운영 확인 필요'), 급식일 표시, 가격은 묻지 않음", res["순위"] and all(C.E.F.loc[c["fid"], "업종코드"] == "PUB:무료급식소" or c["확실성"] == "확인 필요" for c in res["순위"])
      and "급식일:" in r["text"] and "가격" not in r["text"])
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P01.1.07", kind="노인복지관 경로식당", stage="mode")
r = C.turn(st, "버스 타요"); res = r["result"]
check("경로식당 → 대구시 목록에 경로식당으로 나온 복지관만(근거 있음)", res["순위"] and all("경로식당 운영" in " ".join(c.get("근거자료") or []) for c in res["순위"]))
C = conv(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P11.1.02", kind="노인복지관", stage="mode")
r = C.turn(st, "버스 타요"); check("노인복지관 → 60세 이상 자격 질문", r["type"] == "question" and "60세 이상" in r["text"])
r = C.turn(st, "네, 해당돼요"); check("자격에 해당한다고 답하면 카드에 다시 '해당하는지' 확인하라고 하지 않음", r["type"] == "result" and "해당하는지" not in r["text"] and "누리집:" in r["text"])
# 12-3) 시설 목록이 없는 목적: 택시는 부르는 방법, 농기계 수리는 카카오맵에서 그 자리에서 (가짜 검색으로 검사)
C = conv(); C.taxis = lambda lon, lat: [{"이름": "가짜콜택시", "전화": "053-000-0000"}]; st = C.start(LON, LAT, gu="중구"); st.update(leaf="P12.1.03")
r = C._next(st); check("택시 → 앱·콜택시 전화 안내 + 나드리콜 제안 (시설 목록 아님)", r["type"] == "question" and "카카오T" in r["text"] and "053-000-0000" in r["text"] and "나드리콜" in r["text"])
class FakeKW:
    def search(self, lid, lon, lat, n=5, speed="보통"):
        base = {"실시간": True, "주소": "대구 달성군 가짜로 1", "전화": "053-111-1111", "경도": LON + 0.01, "위도": LAT, "직선거리_m": 900, "걷는거리_m": 1100, "걷는시간_분": 18,
                "걸음": speed, "세부종류": None, "묶음": None, "안내": "", "참고": "", "근거": "카카오맵", "지도": ""}
        s1 = dict(base, fid="KAKAO:1", 상호="가짜농기계수리센타", 업종="농기계 수리점", 표시=[], 근거자료=["카카오맵 — 상호에 '수리'"])
        u1 = dict(base, fid="KAKAO:2", 상호="가짜트랙터대리점", 업종="농기계 판매점", 표시=["제공 여부 확인 필요"], 근거자료=[])
        return [s1], [u1]
C = conv(); C._kw = FakeKW(); st = C.start(LON, LAT, gu="중구"); st.update(leaf="P15.1.02", stage="mode")
r = C.turn(st, "걸어서 갈게요"); r = C.turn(st, "보통"); res = r["result"]
check("농기계 수리 → 상호로 수리점인 곳만 순위, 대리점은 '확인 필요'로 따로", [c["상호"] for c in res["순위"]] == ["가짜농기계수리센타"] and "가짜트랙터대리점" in [c["상호"] for c in res["확인필요후보"]]
      and "은행" not in r["text"])
# 13) 실제 카카오 연결 (한 번): 서문시장 찾기, 차 길찾기
try:
    k = Kakao(); p = k.find_place("서문시장", LON, LAT); t = k.car_many(LON, LAT, [("a", 128.6014, 35.8661)])
    check("실제 카카오: 서문시장 찾기·차 길찾기", p and "서문시장" in p[0]["이름"] and "a" in t)
except Exception as e: check(f"실제 카카오 연결 ({e})", False)
# 버스 노선 (10/16): 칠곡시장 근처에서 노인복지관 → 한 번에 가는 노선과 타는 곳·내리는 곳, 시간은 지어내지 않음
C = conv(); st = C.start(128.5506, 35.9431); st.update(leaf="P11.1.02", kind="노인복지관", cond={"mode": "버스·지하철"}, speed="보통"); st["elig_ok"] = {"노인복지관"}
res = C._core_search(st); cards = [C._card_text(st, 0, c) for c in res["순위"]]
mv = cards[0].card["이동"]; rt = cards[0].card["경로"]
check("버스 노선 → '○○번 버스 한 번에' + 그림(걷기·버스·걷기, 타는 곳·내리는 곳) + 지도 선, 타고 가는 시간은 말하지 않음",
      res["순위"] and "번 버스 한 번에" in cards[0] and [g["t"] for g in mv] == ["walk", "bus", "walk"] and mv[1]["탈곳"] and mv[1]["내릴곳"]
      and all(r["선"] and len(r["선"]) >= 2 for r in rt) and not re.search(r"한 번에, 약", " ".join(cards)))
check("버스 노선 → 한 번에 가는 곳이 갈아타는 곳보다 앞", [bool(c.get("버스")) for c in res["순위"]] == sorted([bool(c.get("버스")) for c in res["순위"]], reverse=True))
print("실패", len(fails)); sys.exit(1 if fails else 0)
