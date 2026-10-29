# 주민 폐업 제보 흐름 검사 (10/20 원칙). 사용: python engine/test_report_flow.py
#  진짜 자료는 건드리지 않음 (임시 폴더). 지도 검색·온라인 글·언어 모델은 부르지 않고 정해 둔 답으로 대신함 (비용 없음)
#  원칙: 제보 → AI 교차검증 → 분명하면 AI가 바로 반영(시설 종류 무관) / 보류면 공공·복지·의료 중 폐업 시 공백이 생기는 곳만 담당자에게
import os, sys, tempfile, types, datetime
REAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix="gineung_rep_")
for d in ("design", "pipeline", "engine", "settings"): os.symlink(os.path.join(REAL, d), os.path.join(T, d))
os.makedirs(os.path.join(T, "data"))
for d in ("raw", "processed", "work"): os.symlink(os.path.join(REAL, "data", d), os.path.join(T, "data", d))
sys.path[:0] = [os.path.join(T, "engine"), os.path.join(T, "pipeline")]
import gov_agent as GA, report_check as RC
assert GA.GOV.startswith(T), GA.GOV
fails = []
def check(name, cond, detail=""):
    print(("통과 " if cond else "실패 ") + name + ("" if cond else f"  {detail}"))
    if not cond: fails.append(name)
G = GA.GovAgent(T); rc = G._rc(); E = G.cm.engine()
NOGAP = "P:행정복지센터:달서구:본동 행정복지센터"; GAP = "P:노인복지관:달성군 노인복지관"
SHOP = next(f for f in E.F.index if E.F.loc[f, "업종"] == "편의점" and E.F.loc[f, "대안후보"] == "예")
FACT = {}
def fake_signals(self, e):
    fid = e["fid"]; f = {"id": fid, "시설": str(E.F.loc[fid, "상호"]), "업종": str(E.F.loc[fid, "업종"]), "동네": "", "제보": {"횟수": 1, "날짜": [], "처음 제보 뒤 지난 날": 0, "주민이 쓴 말": []}}
    f.update(FACT.get(fid, {})); return f, [k for k in ("인허가", "지도") if FACT.get(fid, {}).get("_" + k)]
RC.ReportCheck.signals = fake_signals
ANS = {}
class _Blk:
    def __init__(s, inp): s.type = "tool_use"; s.input = inp
class _Res:
    def __init__(s, inp): s.content = [_Blk(inp)]; s.stop_reason = "tool_use"; s.usage = types.SimpleNamespace(input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0)
class _Cli:
    class messages:
        @staticmethod
        def create(**k): return _Res({"items": [{"id": i, "decision": d, "reason": "시험"} for i, d in ANS.items()]})
G._client = _Cli()
def row(fid): return G.cm.row(fid)["대안후보"]
def report(fid, facts, ans):
    FACT[fid] = facts; ANS.clear(); ANS[fid] = ans
    G.cm.report(fid, note="시험 제보", source="주민 제보")
    return rc.analyze_public(fid) if rc.is_public(fid) else None

# 1) 공공 시설 + 분명한 폐업 근거 → AI가 바로 폐업 반영 (담당자를 거치지 않음)
d = report(GAP, {"인허가": "인허가가 폐업로 바뀜", "_인허가": True, "지도 검색": "그 자리에서 같은 이름의 장소가 검색되지 않음", "_지도": True}, "폐업 맞음")
check("공공 시설 폐업 근거 분명 → AI가 바로 폐업 반영", d and d.get("반영") == "폐업 반영" and row(GAP) == "아니요", (d, row(GAP)))
G.cm.reopen(GAP, source="시험 되돌림", who="시험")
# 2) 공공 시설 + 근거 없이 '폐업 맞음' → 안전장치가 보류로
d = report(GAP, {"인허가": "인허가 대상이 아닌 업종", "지도 검색": "확인하지 못함"}, "폐업 맞음")
check("근거 없는 '폐업 맞음'은 보류 (잘못 지우지 않음)", d and d["판단"] == "판단 보류" and row(GAP) == "확인 필요", (d, row(GAP)))
# 3) 보류된 공공 시설: 폐업 시 공백이 생기면 담당자 확인 대상, 공백이 없으면 담당자에게 넘기지 않음
U = G.unsure()
G.an[GAP] = G.analyze(GAP, True)
lv_gap = G.severity({"fid": GAP, "시설": U[GAP], "분석": G.an[GAP]})[0]
check("보류 + 폐업 시 공백 → 담당자 확인 대상 (달성군 노인복지관)", lv_gap in ("긴급", "주의"), lv_gap)
d = report(NOGAP, {"인허가": "인허가 대상이 아닌 업종", "지도 검색": "확인하지 못함"}, "판단 보류")
U = G.unsure(); G.an[NOGAP] = G.analyze(NOGAP, True)
lv_no = G.severity({"fid": NOGAP, "시설": U[NOGAP], "분석": G.an[NOGAP]})[0]
check("보류 + 폐업해도 공백 없음 → 담당자에게 넘기지 않음 (행정복지센터)", lv_no is None and row(NOGAP) == "확인 필요", lv_no)
# 4) 공공 시설 '영업 중': 지도 검색만으로는 되돌리지 않음, 지도 + 인허가 영업이면 되돌림
ANS.clear(); ANS[NOGAP] = "영업 중"; FACT[NOGAP] = {"인허가": "인허가 대상이 아닌 업종", "지도 검색": "그 자리에서 같은 이름의 장소가 아직 검색됨"}
d = rc.analyze_public(NOGAP)
check("공공 시설: 지도 검색만으로 '영업 중' 되돌리지 않음 (보수적)", d["판단"] == "판단 보류" and row(NOGAP) == "확인 필요", d)
FACT[NOGAP] = {"인허가": "인허가는 아직 영업 중", "지도 검색": "그 자리에서 같은 이름의 장소가 아직 검색됨"}
d = rc.analyze_public(NOGAP)
check("공공 시설: 지도 + 인허가 영업 → AI가 바로 다시 안내", d.get("반영") == "다시 안내" and row(NOGAP) == "예", (d, row(NOGAP)))
# 5) 30일 정리: 공백이 생기는 공공 시설은 남기고, 일반 가게는 다시 안내
G.cm.report(SHOP, note="시험 제보", source="주민 제보")
old = (datetime.date.today() - datetime.timedelta(days=40)).isoformat()
for e in G.cm.events:
    if e["상태"] == "확인 필요" and e["fid"] in (GAP, SHOP): e["날짜"] = old
G.tidy_reports()
check("30일 정리: 일반 가게는 다시 안내", row(SHOP) == "예", row(SHOP))
check("30일 정리: 폐업 시 공백이 생기는 공공 시설은 담당자 확인을 기다림", row(GAP) == "확인 필요", row(GAP))
# 6) 일반 가게 제보는 바로 담당자에게 가지 않음 (매주 AI 검토)
G.cm.report(SHOP, note="시험 제보", source="주민 제보")
check("일반 가게 제보는 공공 아님 → 매주 AI 검토 대상", not rc.is_public(SHOP) and SHOP in [e["fid"] for e in rc.pending(public=False)])
# 7) 원아 이전 공백 (10/20): 주변 2km 안 같은 기관 남는 자리로 아이를 다 받을 수 있으면 공백 아님, 먼 읍·면은 공백
def kfid(nm): return next(f for f in E.F.index if E.F.loc[f, "상호"] == nm and E.F.loc[f, "업종"] == "유치원")
for nm, want in (("아름다운유치원", False), ("대구고매초등학교병설유치원", True)):
    f = kfid(nm); it = {"fid": f, "시설": {"fid": f, "상호": nm, "업종": "유치원", "구군": E.F.loc[f, "구군"], "경도": E.F.loc[f, "경도"], "위도": E.F.loc[f, "위도"], "폐업일자": GA.today()}, "분석": G.analyze(f, True)}
    has = any(x.get("돌봄기관") for x in G.case_facts(it))
    check(f"원아 이전 공백: {nm} → {'공백' if want else '주변 기관이 받을 수 있어 공백 아님'}", has == want, (has, G._spare(f, "P04.2.01")))
# 8) 담당자가 판단을 바로잡으면 그 곳은 담당자 판단을 따르고 사례로 남김 (임시 폴더의 판단 기록에만)
import gap_practice as PR
it = PR.hypo_item(G, "S:MA010120220809494653")   # 정대숲상회 (가정 폐업)
check("바로잡기 시험 사례 준비", bool(it and G.assess(it)))
if it:
    before = G.route(it)[0]
    r8 = G.feedback(it["fid"], "보고", note="시험")
    after = G.route(it)
    check("담당자 바로잡기 → 그 곳은 담당자 판단(보고)을 따름", after[0] == "보고", (before, after[:2]))
    check("담당자 바로잡기 → 사례로 남음", r8.get("사례") is True, r8)
    G.feedback(it["fid"], None)
    check("바로잡기 되돌리기 → AI 판단으로 돌아감", G.route(it)[0] == before, G.route(it)[:2])
print("\n실패", len(fails))
