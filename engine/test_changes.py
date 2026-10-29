# 시설 변화 관리 검사. 사용: python engine/test_changes.py [--llm]
#  진짜 자료(data/changes, data/notices)는 건드리지 않음: 임시 폴더에 원래 자료를 이어 붙인(링크) 시험용 자리를 만들어 그 안에서만 반영함
#  --llm: 담당자 말 알아듣기(언어 모델)까지 시험
import os, sys, json, tempfile, random, time
import numpy as np, pandas as pd
REAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix="gineung_test_")
for d in ("design", "pipeline", "engine", "settings"): os.symlink(os.path.join(REAL, d), os.path.join(T, d))
os.makedirs(os.path.join(T, "data"))
for d in ("raw", "processed", "work"): os.symlink(os.path.join(REAL, "data", d), os.path.join(T, "data", d))
sys.path[:0] = [os.path.join(T, "engine"), os.path.join(T, "pipeline")]
import changes as CH
from changes import ChangeManager
from recommend import Engine, SafetyError
fails = []
def check(name, cond, detail=""):
    print(("통과 " if cond else "실패 ") + name + ("" if cond else f"  {detail}"))
    if not cond: fails.append(name)
t0 = time.time()
M = ChangeManager(T)
F = M.F0
# ---- 1) 분류 규칙이 데이터베이스와 같음 ----
import facility_rules as FR
nn = F[F["제외사유"] == "상호가 없어 어느 가게인지 특정할 수 없음"]
check("상호 없음 규칙이 데이터베이스와 같음", all(FR.no_name(n, u) for n, u in zip(nn["상호"], nn["업종"])), nn.head(3)[["상호", "업종"]].values.tolist())
smp = F[F["출처"].isin(["상가", "인허가"]) & (F["대안후보"] == "예")].sample(3000, random_state=1)
check("멀쩡한 가게를 상호 없음으로 보지 않음", not any(FR.no_name(n, u) for n, u in zip(smp["상호"], smp["업종"])))
# ---- 2) 인허가 변화 반영 (실제 자료 모양의 시험 기록) ----
E0 = Engine(T)
L = F[(F["출처"] == "인허가") & (F["대안후보"] == "예") & (F["업종"] == "약국")].iloc[5]
ld = L["인허가id"]; slug, gu, mng = ld.split(":", 2)
rec = {"ld_id": ld, "slug": slug, "구군": gu, "인허가업종": L["인허가업종"], "관리번호": mng, "사업장명": L["상호"], "영업상태명": "폐업", "상세영업상태명": "폐업",
       "인허가일자": "2010-01-01", "폐업일자": "2026-10-14", "휴업시작일자": None, "휴업종료일자": None, "업태구분명": "", "진료과목내용명": "", "의료기관종별명": "",
       "도로명주소": L["주소"], "지번주소": "", "전화번호": "", "데이터갱신시점": "2026-10-15 00:00:00", "경도": float(L["경도"]), "위도": float(L["위도"]), "변화": "폐업", "이전상태": "영업"}
e = M.apply_ld(rec)
check("인허가 폐업 → 시설이 '아니요'로 바뀜", e is not None and M.row(L["fid"])["대안후보"] == "아니요" and e["종류"] == "폐업")
check("같은 변화를 두 번 반영하지 않음", M.apply_ld(rec) is None)
# 새 인허가 (가상의 새 약국): 근처 주소, 오늘 인허가
new = dict(rec, ld_id=f"{slug}:{gu}:TEST-0001", 관리번호="TEST-0001", 사업장명="시험새봄약국", 영업상태명="영업/정상", 폐업일자=None, 인허가일자=CH.today(),
           경도=float(L["경도"]) + 0.004, 위도=float(L["위도"]) + 0.002, 변화="개업", 이전상태=None)
e2 = M.apply_ld(new)
r2 = M.row("L:" + new["ld_id"]) if e2 else {}
check("새 인허가 → 새 시설로 분류 (약국, 대안 후보 예)", e2 is not None and e2["종류"] == "신규" and r2.get("업종") == "약국" and r2.get("대안후보") == "예", (e2 or {}).get("분류"))
check("새 시설에 행정동이 채워짐", bool(r2.get("행정동")))
# 같은 자리 같은 상호가 인허가만 새로 받음 → 새 시설을 만들지 않고 이어 붙임
same = dict(new, ld_id=f"{slug}:{gu}:TEST-0002", 관리번호="TEST-0002", 경도=new["경도"] + 0.00005)
e3 = M.apply_ld(same)
check("같은 자리 같은 상호의 새 인허가는 같은 시설로 봄", e3 is not None and e3["종류"] == "인허가 확인" and "L:" + same["ld_id"] not in M.rows)
# 이름으로 업종 바로잡기 (일반음식점 '기타' 업태 + 상호의 메뉴)
food = dict(new, ld_id=f"general_restaurants:{gu}:TEST-0003", slug="general_restaurants", 인허가업종="식품_일반음식점", 관리번호="TEST-0003", 사업장명="시험막창 본점",
            업태구분명="기타", 경도=new["경도"] + 0.003)
e4 = M.apply_ld(food)
r4 = M.row("L:" + food["ld_id"])
check("상호의 메뉴로 세부 업종을 정함 (막창 → 곱창 전골/구이) 하고 업종 확인 없이 안내", r4["업종"] == "곱창 전골/구이" and r4["대안후보"] == "예" and not r4["업종확인필요"], (r4["업종"], r4["대안후보"], r4["업종확인필요"]))
vague = dict(food, ld_id=f"general_restaurants:{gu}:TEST-0004", 관리번호="TEST-0004", 사업장명="시험하늘", 경도=new["경도"] + 0.006)
M.apply_ld(vague); r5 = M.row("L:" + vague["ld_id"])
check("업태만으로 종류를 알 수 없는 새 음식점은 '확인 필요' (주민에게 안내하지 않음)", r5["대안후보"] == "확인 필요")
old = dict(vague, ld_id=f"general_restaurants:{gu}:TEST-0005", 관리번호="TEST-0005", 사업장명="시험옛날짜장", 업태구분명="중국식", 인허가일자="2015-03-02", 경도=new["경도"] + 0.009)
M.apply_ld(old); r6 = M.row("L:" + old["ld_id"])
check("오래전 인허가가 이번에 올라온 곳은 '확인 필요'", r6["대안후보"] == "확인 필요")
# 가게에 붙는 인허가: 종량제 봉투 판매를 그만둠
host = F[(F["종량제봉투판매"] == "True") & (F["대안후보"] == "예") & (F["업종"] == "편의점")].iloc[3]
fl = {"ld_id": f"pay_as_you_throw_bag_retailers:{host['구군']}:TEST-0006", "slug": "pay_as_you_throw_bag_retailers", "구군": host["구군"], "인허가업종": "자원환경_쓰레기종량제봉투판매업",
      "관리번호": "TEST-0006", "사업장명": host["상호"], "영업상태명": "폐업", "상세영업상태명": "폐업", "인허가일자": "2020-01-01", "폐업일자": "2026-10-14", "도로명주소": host["주소"],
      "경도": float(host["경도"]), "위도": float(host["위도"]), "변화": "폐업", "이전상태": "영업", "데이터갱신시점": "2026-10-15", "업태구분명": ""}
e7 = M.apply_ld(fl)
check("종량제 봉투 판매 인허가 폐업 → 가게는 그대로, 판매 표시만 꺼짐", e7 is not None and e7["종류"] == "기능 중단" and str(M.row(host["fid"])["종량제봉투판매"]) == "False" and M.row(host["fid"])["대안후보"] == "예")
M._save(); M._finish_new()
# ---- 3) 엔진에 반영됐는지 ----
E = Engine(T)
check("엔진: 덮어쓰기 반영 (폐업 시설 '아니요', 새 시설 있음)", E.F.at[L["fid"], "대안후보"] == "아니요" and "L:" + new["ld_id"] in E.F.index)
fs = [f for f in E.functions_of(L["fid"]) if f["role"] == "주"]
lid = fs[0]["leaf"]; kind = fs[0]["kind"]
res = E.recommend(lid, kind, float(L["경도"]), float(L["위도"]), n=5)
ids = [c["fid"] for c in res["추천"] + res["제공여부확인필요"] + res["운영확인필요"]]
check("엔진: 문 닫은 약국은 어느 목록에도 없음", L["fid"] not in ids)
resn = E.recommend(lid, kind, new["경도"], new["위도"], n=3)
check("엔진: 새 약국 자리에서 찾으면 새 약국이 가장 가까운 대안으로 나옴", resn["추천"] and resn["추천"][0]["fid"] == "L:" + new["ld_id"],
      [(c["상호"], c["걷는거리_m"]) for c in resn["추천"]] + [E.judge("L:" + new["ld_id"], lid, kind), "L:" + new["ld_id"] in E.walk.snap])
res2 = E.recommend("P02.1.07", None, float(host["경도"]), float(host["위도"]), user_gu=host["구군"], n=10)
check("엔진: 종량제 봉투 판매를 그만둔 편의점은 종량제 봉투 대안에서 빠짐", host["fid"] not in [c["fid"] for c in res2["추천"] + res2["제공여부확인필요"]])
check("엔진: 원래 자료만 보는 모드에서는 폐업 전 그대로", Engine(T, overlay=False).F.at[L["fid"], "대안후보"] == "예")
# ---- 4) 알림 ----
out = M.notify(budget=120)
N = {n["변화"]: n for n in M.notices}
n1 = N.get(e["id"])
check("폐업 알림이 만들어짐", n1 is not None and n1["종류"] == "문 닫음", out)
if n1:
    f1 = n1["기능"][0] if n1["기능"] else None
    check("알림: 맡던 기능·등급·기준 시간이 있음", f1 is not None and f1["등급"] in ("필수", "준필수", "선택") and f1["기준_분"] > 0)
    alts = [c for f in n1["기능"] for c in f["대체시설"]]
    check("알림: 대체 시설은 모두 영업 중 '예'이고 문 닫은 시설이 아님", alts and all(E.F.at[c["fid"], "대안후보"] == "예" and c["fid"] != L["fid"] for c in alts if not c.get("확인필요")))
    imp = [x for f in n1["기능"] for x in (f["영향"], f["영향_묶음"], f["영향_기능전체"]) if x]
    check("알림: 영향 숫자가 앞뒤가 맞음 (공백 ≤ 가까운 주민, 65세 이상 ≤ 전체)", imp and all(0 <= x["공백변화주민"] <= x["가까운주민"] + 1 and x["가까운주민_65세이상"] <= x["가까운주민"] + 1 for x in imp))
    check("알림: 넓은 범위일수록 공백이 같거나 작음 (종류 ≥ 묶음 ≥ 기능 전체)", all((f["영향"] or {}).get("공백변화주민", 0) + 1 >= (f["영향_묶음"] or {}).get("공백변화주민", 0) and
          ((f["영향_묶음"] or f["영향"] or {}).get("공백변화주민", 0) + 1 >= (f["영향_기능전체"] or {}).get("공백변화주민", 0)) for f in n1["기능"]))
    check("알림: 본문에 시설 이름·대체 시설 이름이 들어감", L["상호"] in n1["본문"] and all(c["상호"] in n1["본문"] for c in alts))
n7 = N.get(e7["id"])
check("판매 중단 알림이 그 일(종량제 봉투 구입)만 다룸", n7 is not None and [f["기능"] for f in n7["기능"]] == ["P02.1.07"], n7 and [f["기능"] for f in n7["기능"]])
# ---- 5) 담당자 입력·주민 제보 ----
cand = F[(F["출처"] == "상가") & (F["대안후보"] == "예") & (F["업종"] == "세탁소")].iloc[10]
hits = M.find(cand["상호"], cand["구군"])
check("상호로 시설 찾기 (첫 후보가 그 시설)", hits and hits[0]["fid"] == cand["fid"], hits[:2])
rr = M.report(cand["fid"], "주민: 문에 폐업 안내문이 붙어 있어요")
check("주민 제보 → '확인 필요'로만 바꾸고 확인 요청 알림", M.row(cand["fid"])["대안후보"] == "확인 필요" and rr["결과"] == "확인 요청" and next(n for n in M.notices if n["id"] == rr["알림"])["등급"] == "확인 요청", rr)
E = Engine(T); fs = [f for f in E.functions_of(cand["fid"]) if f["role"] == "주"]
res = E.recommend(fs[0]["leaf"], fs[0]["kind"], float(cand["경도"]), float(cand["위도"]), n=5)
check("제보된 시설은 확인 전까지 주민 추천 목록에 없음", cand["fid"] not in [c["fid"] for c in res["추천"] + res["제공여부확인필요"]])
rj = M.reject(rr["변화"], why="시험: 영업 중 확인")
check("제보 되돌리기 → 원래대로", M.row(cand["fid"])["대안후보"] == "예" and rj["결과"] == "되돌림")
rr2 = M.report(cand["fid"], "다시 제보"); cf = M.confirm(rr2["변화"], who="시험 담당자")
check("제보 확인 → 문 닫음 반영 + 폐업 알림", M.row(cand["fid"])["대안후보"] == "아니요" and cf["알림"] and next(n for n in M.notices if n["id"] == cf["알림"])["등급"] != "확인 요청")
ro = M.reopen(cand["fid"], CH.today())
check("다시 엶 → '예'", M.row(cand["fid"])["대안후보"] == "예" and ro["결과"] == "반영", ro)
pub = F[(F["업종코드"] == "PUB:경로당") & (F["대안후보"] == "예")].iloc[0]
ad = M.add("시험행복경로당", pub["주소"], "PUB:경로당", lon=float(pub["경도"]) + 0.01, lat=float(pub["위도"]))
check("담당자가 새 공공시설 추가 → 분류·행정동·좌표", ad["결과"] == "반영" and ad["대안후보"] == "예" and M.row(ad["fid"])["행정동"], ad)
cl = M.close(pub["fid"], "2026-10-14", note="시험 폐쇄")
check("담당자가 경로당 폐쇄 입력 → 알림", cl["결과"] == "반영" and cl["알림"])
check("이미 닫은 시설을 또 닫지 않음", M.close(pub["fid"])["결과"].startswith("이미"))
# ---- 6) 요약·알림함 ----
dg = M.digest(); check("하루 요약", "생활시설 변화 요약" in dg and "폐업" in dg)
p = M.render_inbox(); check("알림함 화면", os.path.exists(p) and os.path.getsize(p) > 5000)
# ---- 7) 언어 모델 (선택) ----
if "--llm" in sys.argv:
    from change_agent import OfficialAgent
    A = OfficialAgent(M)
    pl = A.plan(f"{cand['구군']} '{cand['상호']}' 세탁소가 어제 문을 닫았다고 동 주민센터에서 연락 왔어요. 그리고 {pub['구군']}에 '시험새싹경로당'이 새로 생겼는데 주소는 {pub['주소']}입니다.")
    ps = pl["제안"]
    check("담당자 말 → 폐업 1건 + 새 시설 1건", sorted(d["종류"] for d in ps) == ["신규", "폐업"], ps)
    d1 = next((d for d in ps if d["종류"] == "폐업"), None)
    check("담당자 말: 폐업 시설 후보 첫째가 맞음", d1 and d1["후보"] and d1["후보"][0]["fid"] == cand["fid"], d1 and d1["후보"][:2])
    check("담당자 말: '어제'를 날짜로 바꿈", d1 and d1["날짜"] and d1["날짜"] < CH.today())
    d2 = next((d for d in ps if d["종류"] == "신규"), None)
    check("담당자 말: 새 시설 업종을 경로당으로", d2 and d2["업종"] == "경로당", d2)
print(f"\n걸린 시간 {round(time.time() - t0)}초, 실패 {len(fails)}")
if fails: print("실패한 검사:", fails); sys.exit(1)
