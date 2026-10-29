# 지자체 에이전트 등급·할 일 검사 (헌준님 원칙 10/16: 공공·복지 중심, 사설은 마을 생활 기반 예외만, 할 일은 법령으로 확인한 것만)
# 사용: python engine/test_gov.py  (자료를 읽지 않고 가짜 분석으로 규칙만 봄)
import os, sys, datetime
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline")]
import gov_agent as GA
import gov_programs as GP
from gov_agent import GovAgent
class _E:
    def scale(self, fid): return {"글": "정원 48명", "정원": 48, "출처": "시험"} if fid == "ltc" else None
class _CM:
    def engine(self): return _E()
G = GovAgent.__new__(GovAgent); G.decisions = {}; G.cm = _CM()
today = datetime.date.today().isoformat()
def f(lid, name, grade, kind=None, gap=0, e65=0, broad=None, after=None, before=5.0, same_gu=10):
    return {"기능": lid, "이름": name, "등급": grade, "세부종류": kind, "기준_분": 15, "공백": gap, "공백_65세이상": e65, "공백_묶음": gap, "공백_넓게": broad,
            "공백_걷는시간_전": before if gap else None, "공백_걷는시간_후": after if gap else None, "가까운주민": 0, "걷는시간_전": None, "걷는시간_후": None,
            "확인필요_근처": 0, "같은구_대체수": same_gu}
def run(fid, funcs, closed=today):
    a = {"fid": fid, "구군": "수성구", "기능": funcs}; c = {"fid": fid, "폐업일자": closed}
    lv, why, used = G.triage(a, c)
    it = {"fid": fid, "셈한기능": used, "시설": {"구군": "수성구"}}
    acts = [x["id"] for x in G._actions(it)] if used else []
    return lv, acts
fails = []
def check(name, got, want):
    ok = got == want; print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  (나옴: {got}, 기대: {want})"))
    if not ok: fails.append(name)
lv, acts = run("p", [f("P03.2.01", "처방약 조제", "필수", gap=1498, e65=472, after=18.4)])
check("약국: 공백이 분명하면 긴급", lv, "긴급"); check("약국: 공공심야약국·방문건강관리", acts, ["night_pharmacy", "home_health"])
lv, acts = run("p2", [f("P03.2.01", "처방약 조제", "필수", gap=300, broad=0, after=18.4)])
check("약국: 근처에 확인할 곳이 있으면 '확인'", lv, "확인")
lv, acts = run("ltc", [f("P04.1.04", "장기 요양 입소", "필수", kind="노인요양시설(요양원)")])
check("요양원 폐업(최근): 긴급", lv, "긴급"); check("요양원: 수급자 권익보호 조치 확인(법정)", acts[:1], ["ltc_transfer"])
lv, acts = run("ltc0", [f("P04.1.04", "장기 요양 입소", "필수", kind="노인요양시설(요양원)", same_gu=0)])
check("요양원: 같은 구에 대체 기관이 없으면 철회 권고 검토까지", "ltc_withdraw" in acts, True)
lv, acts = run("old", [f("P04.1.04", "장기 요양 입소", "필수", kind="노인요양시설(요양원)")], closed="2025-01-01")
check("요양원 폐업(오래전): 참고", lv, "참고")
lv, acts = run("hosp", [f("P04.1.04", "장기 요양 입소", "필수", kind="요양병원")])
check("요양병원: 의료법 환자 권익보호 조치 확인 (장기요양 절차 아님)", acts, ["medical_transfer"])
lv, acts = run("kid", [f("P04.2.01", "영유아 보육", "필수", kind="어린이집(국공립·민간·법인 등)")])
check("어린이집: 영유아 전원 조치 확인(법정)", acts[:1], ["childcare_transfer"])
lv, acts = run("hair_city", [f("P07.2.01", "이발·미용", "준필수", kind="미용실", gap=225, after=20)])
check("도심 미용실: 지자체에 보고하지 않음", lv, "참고")
lv, acts = run("hair_village", [f("P07.2.01", "이발·미용", "준필수", kind="미용실", gap=484, e65=157, after=100, before=8.4)])
check("시골 미용실: 이발 때문에 수요응답형 교통을 권하지 않음", "drt" in acts, False)
lv, acts = run("meat_village", [f("P01.1.05", "외식", "준필수", kind="소고기 구이·찜", gap=120, after=45)])
check("시골 마을 하나뿐인 고깃집(모임 장소): 주의", lv, "주의")
lv, acts = run("cvs", [f("P02.1.07", "종량제 봉투 구입", "준필수", gap=80, after=20), f("P01.1.02", "가공식품 구입", "필수", kind="편의점", gap=80, after=20)])
check("편의점: 종량제 봉투 판매소 공백은 주의(금방 되살릴 수 있음)", lv, "주의"); check("편의점: 판매소 새로 지정", acts, ["bag_seller"])
check("편의점은 공공·복지 시설이 아님", GA.is_public_facility({"기능": [f("P02.1.07", "종량제 봉투 구입", "준필수")]}), False)
check("약국은 공공·복지 시설", GA.is_public_facility({"기능": [f("P03.2.01", "처방약 조제", "필수")]}), True)
# ---- 심각 판정 (engine/severity.py): 실제 지도·인구로 '오늘 문을 닫는다면'을 계산 ----
G = GA.GovAgent(); E = G.cm.engine()
def sev(fid):
    r = E.F.loc[fid]; c = {"상호": r["상호"], "업종": r["업종"], "구군": r["구군"], "폐업일자": GA.today()}
    return G.severity({"fid": fid, "시설": c, "분석": G.analyze(fid, True)})[0]
check("응급실 있는 종합병원(천주성삼병원)이 닫으면: 긴급", sev("S:MA010120220808920031"), "긴급")
ph = [p for p in G._prov_all("P03.2.01") if E.F.at[p, "구군"] == "중구"][:3]
check("도심 약국(중구, 가까이에 다른 약국 많음)이 닫아도: 보고 안 함", [sev(p) for p in ph], [None] * len(ph))
check("시골 5일장(군위 의흥시장)이 닫으면: 보고 (읍·면 주민 장보기 공백)", sev("P:전통시장:의흥시장") in ("긴급", "주의"), True)
check("시골 시장 폐업에 맞는 일: 임시시장(정기 장터) 개설 검토", "market_temp" in [p["id"] for p in GP.for_item([{"기능": "P01.1.01", "세부종류": "전통시장"}], {"gap": True, "elder": True, "far": True})], True)
# ---- 누가 하던 곳이든 하던 일로 잼 (10/19, 아이디어 제안자 답변서: 민간·공공 구분 없이 생활기능 기준) ----
check("농촌 마을의 마지막 가게(의흥면 파전구판장)가 닫으면: 주의 (식료품 살 곳이 멀어짐)", sev("S:MA010120220808834511"), "주의")
check("도심 마트(동구 엘지마트각산점)는 근처에 다른 가게가 있어 보고 안 함", sev("S:MA0101202409A0020395"), None)
check("학습 기준은 도심(동) 주민에게서 배움 (농촌의 먼 거리에 끌리지 않게)", G.baseline().get("배운곳"), "도심(동) 주민")
import gap_agent as GAP
check("판단 모델은 사례로 배움 (헌준님 예시 판단이 사례로 들어 있음)", GAP.Scorer().m.get("사례수", 0) >= 5, True)
check("AI가 사실과 다르게 쓰면 받지 않음 (대신 갈 약국이 18분 거리인데 '남은 약국이 없다')", GAP.verify("긴급", "동네에 남은 약국이 없습니다.", [{"대체시설": [{"걷는시간_분": 18}]}])[0], False)
check("장보기 공백에 맞는 일: 홀로 사는 어르신 생활지원 연계", "senior_daily" in [p["id"] for p in GP.for_item([{"기능": "P01.1.02", "세부종류": "슈퍼마켓"}], {"gap": True, "elder": True})], True)
def way(fid):
    r = E.F.loc[fid]; c = {"상호": r["상호"], "업종": r["업종"], "구군": r["구군"], "폐업일자": GA.today(), "행정동": r["행정동"]}
    return G.route({"fid": fid, "시설": c, "분석": G.analyze(fid, True)})[:2]
# ---- 예전에 잘못 보고됐던 곳 (10/16~17: 호텔 안 미용실, 도심 약국 등) → 지금은 보고 안 함 ----
check("예전 오류(팔공산호텔컷트·아나약국·새마음회관·나우휘트니스클럽): 모두 보고하지 않음",
      [way(x)[0] == "보고" for x in ["S:MA010120220812137868", "S:MA010120220808875853", "S:MA0106202212A1632191", "S:MA0101202604A0021107"] if x in E.F.index], [False] * 4)
check("도심 약국(진천동, 18분 거리에 다른 약국)은 '심각'까지 올라가지 않음", sev("S:MA010120220812263134") in (None, "주의"), True)
# ---- 도심 원칙 (10/19): 판단 에이전트가 원칙·사례로 판단 — 동에서는 생명 직결 공백만 보고, 나머지는 관찰 ----
check("도심 약국(진천동)이 닫으면: 보고하지 않고 관찰", way("S:MA010120220812263134")[0], "관찰")
check("도심 종합병원의 신생아 중환자실(대구파티마병원)이 닫으면: 보고 (생명 직결, 긴급·주의 단계는 AI 판단이 정함)", way("S:MA010120220808919480")[0], "보고")
check("읍·면 마지막 가게(의흥면)는 지금처럼 보고", way("S:MA010120220808834511")[0], "보고")
check("수요응답형 교통은 동(도심)에서는 권하지 않음", GA.GovAgent._rural({"분석": {"행정동": "진천동"}}), False)
# ---- 관심 지역·주민 신호·후속 관리 (10/19) ----
rw = G.rural_watch()
check("읍·면에서 하나 남은 곳: 효령면의 마지막 약국(덕화약국)을 미리 살핌", any(x["상호"] == "덕화약국" for x in rw["곳"]), True)
import demand as DM
check("주민이 찾지 못한 곳은 동네까지만 남김 (중구 성내2동)", DM.where(128.5933, 35.8714), ("중구", "성내2동"))
rq = G._request_text({"상호": "○○약국", "업종": "약국", "구군": "중구", "행정동": "성내2동", "기능": "약국", "심각": {"밀려난주민": 120, "밀려난_65세이상": 40, "기준_m": 1000}, "대체시설": [], "폐업일자": "2026-10-01"},
                     {"할일": "공공심야약국 지정 검토", "근거": "약사법 제21조의3"})
check("연계 요청문에 영향·요청·근거가 들어감", all(w in rq for w in ("120명", "공공심야약국", "약사법")), True)
check("이발·미용은 수요응답형 교통 대상이 아님", [p["id"] for p in GP.for_item([{"기능": "P07.2.01"}], {"far": True})], [])
# ---- 주민 제보 교차검증 (engine/report_check.py) ----
from report_check import ReportCheck
rc = ReportCheck(G)
class _B:
    def __init__(s, d): s.type = "tool_use"; s.input = d
class _R:
    def __init__(s, d): s.content = [_B(d)]; s.usage = None; s.stop_reason = "tool_use"
class _M:
    def __init__(s, d): s.d = d
    def create(s, **k): return _R(s.d)
class _C:
    def __init__(s, d): s.messages = _M(d)
G._client = _C({"items": [{"id": "a", "decision": "폐업 맞음", "reason": "x"}, {"id": "b", "decision": "폐업 맞음", "reason": "x"}, {"id": "c", "decision": "영업 중", "reason": "x"}]})
fa = {"id": "a", "제보": {"횟수": 1}, "인허가": "인허가가 폐업으로 바뀜", "지도 검색": "확인하지 못함", "블로그": ""}
fb = {"id": "b", "제보": {"횟수": 1}, "인허가": "인허가는 아직 영업 중", "지도 검색": "그 자리에서 같은 이름의 장소가 아직 검색됨", "블로그": ""}
fc = {"id": "c", "제보": {"횟수": 3}, "인허가": "인허가가 폐업으로 바뀜", "지도 검색": "그 자리에서 같은 이름의 장소가 검색되지 않음", "블로그": ""}
d = rc.judge([(fa, ["인허가"]), (fb, []), (fc, ["인허가", "지도"])])
check("제보 검증: 인허가 폐업이면 AI 판단대로 폐업 반영", d["a"]["판단"], "폐업 맞음")
check("제보 검증: 확실한 근거 없이 AI가 폐업이라 해도 보류", d["b"]["판단"], "판단 보류")
check("제보 검증: 연다는 근거 없이 AI가 영업 중이라 해도 보류", d["c"]["판단"], "판단 보류")
G._client = None
ph = E.F[(E.F["업종"] == "약국") & (E.F["대안후보"] == "예")].index[0]; cf = E.F[(E.F["업종"] == "카페") & (E.F["대안후보"] == "예")].index[0]
check("약국은 제보가 오면 담당자 확인 대상 (공공·의료)", rc.is_public(ph), True)
check("카페는 매주 AI가 검토하는 일반 가게", rc.is_public(cf), False)
# ---- 보육·아동 돌봄 공백 (10/19 밤): 아이 수로 재고, 지자체가 할 수 있는 공공 사업과 이음 ----
C = G.cm._C
check("영유아(0~5세) 인구가 격자에 들어 있음 (대구 약 6만 7천 명)", 60000 < float(C.pop05.sum()) < 75000, True)
check("행정동이 빈 시설은 좌표로 찾음 (공공 목록 어린이집)", bool(GA.dong_at(E.F.at["P:어린이집:수성구:범어아이파크어린이집", "경도"], E.F.at["P:어린이집:수성구:범어아이파크어린이집", "위도"])), True)
check("직장어린이집은 주민이 대신 갈 곳으로 세지 않음", any("직장" in str(E.F.at[p, "업종"]) for p in G._prov_all("P04.2.01")), False)
check("도심 어린이집(범어아이파크, 정보공개포털 현원 37명 · 2km 안 남는 자리로 옮길 수 있음): 보고하지 않음 (10/21 실제 정원·현원 반영)", way("P:어린이집:수성구:범어아이파크어린이집")[0] != "보고", True)
check("읍 어린이집(달성 중흥꿈자람): 2km 안 어린이집 남는 자리로 아이를 받을 수 있어 보고하지 않음 (10/20 원아 이전 공백 판단)", way("P:어린이집:달성군:중흥꿈자람어린이집")[0] != "보고", True)
acts = [p["id"] for p in GP.for_item([{"기능": "P04.2.01", "세부종류": "어린이집(국공립·민간·법인 등)"}], {"gap": True, "elder": True, "far": True})]
check("어린이집 공백에 맞는 일: 법정 확인 먼저, 국공립 전환·시간제보육·농어촌 보조·아이돌봄", acts, ["childcare_transfer", "public_daycare", "timed_care", "rural_daycare", "idol_care"])
check("직장어린이집에는 국공립 전환을 권하지 않음", "public_daycare" in [p["id"] for p in GP.for_item([{"기능": "P04.2.01", "세부종류": "직장어린이집(직원 자녀만)"}], {"gap": True})], False)
check("읍·면 의원 공백: 보건진료소·보건지소", [x for x in [p["id"] for p in GP.for_item([{"기능": "P03.1.01", "세부종류": "내과"}], {"gap": True, "far": True})] if x in ("health_post", "health_branch")], ["health_post", "health_branch"])
check("도심 의원 공백에는 보건진료소를 권하지 않음 (군수 권한, 읍·면만)", "health_post" in [p["id"] for p in GP.for_item([{"기능": "P03.1.01", "세부종류": "내과"}], {"gap": True, "far": False})], False)
check("소아과 공백: 달빛어린이병원 지정 건의", "kids_night" in [p["id"] for p in GP.for_item([{"기능": "P03.1.01", "세부종류": "소아청소년과"}], {"gap": True})], True)
check("분만 공백: 의료취약지 협의", "vulnerable_area" in [p["id"] for p in GP.for_item([{"기능": "G:분만"}], {"gap": True})], True)
check("방과후 돌봄 공백: 다함께돌봄센터 설치", "dahamkke" in [p["id"] for p in GP.for_item([{"기능": "P04.2.02", "세부종류": "지역아동센터"}], {"gap": True})], True)
print(f"\n실패 {len(fails)}"); sys.exit(1 if fails else 0)
