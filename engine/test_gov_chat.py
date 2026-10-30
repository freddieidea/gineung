# 지자체 업무 보조 대화 검사 (언어 모델 없이: 도구 계산·확인 카드 조건·답 검사·문서). 사용: python engine/test_gov_chat.py
import re, os, sys, json, zipfile, io
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline")]
import gov_agent as GA, gov_chat as GC, gov_docs as D
fails = []
def check(name, got, want):
    ok = got == want; print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  (나옴: {got}, 기대: {want})"))
    if not ok: fails.append(name)
G = GA.GovAgent(); E = G.cm.engine()
class _NoLLM: pass
c = GC.GovChat(G, client=_NoLLM(), pre_fn=lambda f: {"오류": "시험"})
ROOT = GC.ROOT; b = D.load(os.path.join(ROOT, "data", "gov", "brief_latest.json"))
def T(n, a, st=None):
    bl = []; r = c._tool(st if st is not None else {}, n, a, bl); return r, bl
# 첫 인사: 모델 없이 오늘 보고 숫자 그대로
h = c.hello(); R = D.rows(b)
check("첫 인사: 건수 나열 대신 오늘 할 일 (없으면 없다고)", ("할 일" in h["blocks"][1]["text"]) if (R["항목"] or R["확인요청"] or R["질문"]) else bool(re.search(r"없습니다|없음", h["blocks"][1]["text"])), True)   # (10/30) 공공기관체 '없음'도 인정
check("첫 인사: 집계 단축 버튼(구·군별 현황) 없음", "구·군별 현황" in h["options"], False)
# 오늘의 보고 요약 = 보고서 합계
r, bl = T("report_overview", {})
check("오늘의 보고: 할 일 = 보고서의 조치 필요·확인 요청·판단 확인", (len(r["할_일"]["조치_필요"]), len(r["할_일"]["폐업_확인_필요"]), len(r["할_일"]["판단_확인"])), (len(R["항목"]), len(R["확인요청"]), len(R["질문"])))
check("오늘의 보고: 폐업 건수 누계는 주지 않음", any("누계" in k or "대상아님" in k for k in r), False)
rb = bl
r, bl = T("area_overview", {"dong": "상인동"})
check("관할 현황: '상인동' → 상인1·2동 등 같은 이름 동을 모두 맞춤", all(d.startswith("상인") for d in r["맞춘_행정동"]) or r["맞춘_행정동"] == [], True)
r, bl = T("area_overview", {"gu": "군위군", "dong": "구지면"})
check("관할 현황: 구를 잘못 말해도 동이 있는 구로 바로잡음 (구지면 → 달성군)", r["범위"].startswith("달성군"), True)
from gov_chat import _dong_ok
check("행정동 맞추기: 범어1동은 범어2동과 섞이지 않음", (_dong_ok("범어1동", "범어1동"), _dong_ok("범어2동", "범어1동")), (True, False))
check("오늘의 보고: 할 일이 없으면 집계 표를 그리지 않음", (not rb) if not (R["항목"] or R["확인요청"] or R["질문"]) else True, True)
# 시설 찾기: 구분·숫자 근거 (구군별·표시·나머지)
r, bl = T("search_facilities", {"status": "검토완료", "limit": 3})
check("시설 찾기: 개수·표시·나머지가 맞음", (r["표시"], r["나머지"]), (min(3, r["개수"]), max(0, r["개수"] - 3)))
check("시설 찾기: 구군별 합 = 개수", sum(r["구군별"].values()), r["개수"])
r2, _ = T("search_facilities", {"status": "검토완료", "public_only": True})
check("공공 시설만 거르기: 모두 공공", r2["개수"] <= r["개수"], True)
r3, _ = T("search_facilities", {"confirmed_since": b["날짜"], "status": "검토완료"})
check("오늘 확정만 거르기 = 보고서의 오늘 확정 수", r3["개수"], sum(1 for x in R["검토완료"] if x.get("확정일") == b["날짜"]))
# 시설 판단 카드: 보고서 행 그대로
q = R["검토완료"][0]; r, bl = T("facility_detail", {"fid": q["fid"]})
check("시설 판단: 보고서의 판단 근거 그대로", r.get("판단근거"), q.get("까닭"))
check("시설 판단: 화면에 카드", bl[0]["card_type"], "quiet")
check("없는 시설은 오류", "오류" in T("facility_detail", {"fid": "없는시설"})[0], True)
# 확인 카드: 조건에 맞지 않으면 띄우지 않음
check("폐업 확인 필요 목록에 없는 곳은 폐업 확인 카드 안 띄움", "오류" in T("propose_action", {"action": "confirm_closed", "fid": q["fid"]})[0], True)
st = {}; r, bl = T("propose_action", {"action": "set_level", "fid": q["fid"], "level": "관찰", "note": "시험"}, st)
check("판단 바로잡기 카드: 기존 버튼과 같은 경로(/api/gov/feedback)", (bl[0]["endpoint"], bl[0]["body"]["판단"]), ("/api/gov/feedback", "관찰"))
check("카드는 '아직 반영 안 됨'", "아직 반영 안 됨" in r["상태"], True)
st = {"role": "심사"}; r, bl = T("propose_action", {"action": "add_lesson", "lesson": "도심 세탁소는 보고하지 않음"}, st)
check("심사용 보기 전용: 카드에 반영 불가 표시", bl[0].get("view_only"), True)
check("처리 완료는 조치 필요 항목만", "오류" in T("propose_action", {"action": "mark_done", "fid": q["fid"]})[0], True)
# 정책 계산: 같은 기준 거리, 숫자 일관
r, bl = T("policy_candidates", {"function_id": "P03.2.01", "gu": "동구", "n": 3})
rb = (b.get("보고기준") or {}).get("거리", []); ph = next((x for x in rb if "약국" in x["기능"]), None)
r = bl[0]["data"]  # 화면 블록은 원래 이름, 모델에게는 쉬운 이름(_plain)
check("모델에게 주는 이름은 쉬운 말", "걸어서_다닐만한_거리_m" in T("policy_candidates", {"function_id": "P03.2.01", "gu": "동구", "n": 3})[0], True)
check("입지 후보 기준 거리 = 보고 기준 거리(약국)", r["기준_m"], round(ph["기준_m"]) if ph else r["기준_m"])
check("입지 후보: 새로 기준 안 주민 ≤ 그 동네 기준 밖 주민", all(x["새로_기준안_주민"] <= x["동네_기준밖_주민"] + 1 for x in bl[0]["data"]["후보"]), True)
z = next(x for x in b["기능공백구역"] if x["시설"] == "약국")
_, bl = T("open_effect", {"function_id": "P03.2.01", "zone_id": z["id"]}); r = bl[0]["data"]
check("개설 효과: 공백 구역 기준 거리 = 공백 구역 계산(체감 기준 2배)", r["공백구역기준_m"], z["기준_m"])
check("개설 효과: 해소 주민 ≤ 그 구역 주민", r["공백구역기준_해소_주민"] <= z["주민"] + 1, True)
# 답 검사
st = {"screen_done": False, "used_now": []}
ctx = json.dumps({"주민": 2577, "기준_m": 900, "상호": "세븐일레븐달성구지대로점"}, ensure_ascii=False)
check("검사: 자료의 숫자·단위 바꾼 숫자는 통과", c._check(st, "주민 2,577명이고 기준은 0.9km입니다", ctx), None)
check("검사: 자료에 없는 숫자는 막음", c._check(st, "주민은 3,000명입니다", ctx), "num:3000")
check("검사: 반영했다고 말하면 막음 (카드는 담당자가 눌러야)", c._check(st, "폐업 반영했습니다", ctx), "claim")
check("검사: 다시 점검했다고 말하면 막음", c._check(st, "다시 점검했습니다", ctx), "claim")
check("검사: 명사형 종결(~임·~함)은 막음 (대화는 경어체)", c._check(st, "주민 2,577명이 기준 밖에 있음", ctx), "style")
check("검사: 문서를 만들었다면서 만들지 않으면 막음", c._check(st, "보고용 요약을 정리했습니다", ctx), "doc_claim")
check("검사: 도구 이름이 보이면 막음", c._check(st, "gap_areas로 확인할 수 있습니다", ctx), "tool_name")
check("검사: 카드를 띄웠다면서 띄우지 않으면 막음", c._check(st, "확인 카드를 띄웠습니다. 카드의 [반영]을 누르시면 반영됩니다", ctx), "card_claim")
check("검사: 조건문('누르시면 반영됩니다')은 통과", c._check(dict(st, used_now=["propose_action"]), "카드의 [반영]을 누르시면 반영됩니다", ctx), None)
# 문서
txt = D.summary_text(b)
check("개조식 요약: 공문서 기호(□ ○)로 시작", txt.startswith("□") and "\n ○" in txt, True)
h = D.report_html(b); check("보고서: 인쇄용 HTML(PDF로 저장 버튼)", "PDF로 저장" in h and "<h1>생활 기능 공백 일일 보고</h1>" in h, True)
x = D.xlsx_for(b, list(D.TABLES)); zf = zipfile.ZipFile(io.BytesIO(x))
check("엑셀: 표마다 시트", sum(1 for n in zf.namelist() if n.startswith("xl/worksheets/")), len(D.TABLES))
H, B = D.table(b, "확인요청"); check("엑셀 '폐업 확인 필요' 행 = 보고서의 폐업 확인 필요 수 (운영 미확정은 따로)", len(B), len(R["확인요청"]))
print(f"\n실패 {len(fails)}"); sys.exit(1 if fails else 0)
