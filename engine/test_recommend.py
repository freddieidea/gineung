# 대안 찾기 엔진 검사. 사용: python engine/test_recommend.py  (하나라도 틀리면 멈춤)
import sys, os, random, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recommend import Engine, SafetyError
t0 = time.time(); E = Engine(); print("엔진 준비", round(time.time() - t0, 1), "초, 세부 종류", len(E.kind))
F = E.F; ok = F[F["대안후보"] == "예"]
fails = []
def check(name, cond):
    print(("통과 " if cond else "실패 ") + name)
    if not cond: fails.append(name)
def must_fail(name, fn):
    try: fn(); check(name + " (막혀야 함)", False)
    except SafetyError as e: check(name + f" (막힘: {e})", True)
def pick(code, cand="예", src=None):
    s = F[(F["업종코드"] == code) & (F["대안후보"] == cand)]
    if src: s = s[s["출처"] == src]
    return s.iloc[len(s) // 2]
# 1) 해물찜 가게가 닫음 → 같은 세부 종류(해산물 구이·찜)만
r = pick(E.F[E.F["업종"] == "해산물 구이/찜"]["업종코드"].iloc[0], cand="아니요")
fn = E.functions_of(r["fid"]); main = [f for f in fn if f["role"] == "주"]
print("  닫은 가게:", r["상호"], "/", [(f["name"], f["kind"]) for f in main])
f0 = [f for f in main if f["kind"]][0]
res = E.recommend(f0["leaf"], f0["kind"], r["x"], r["y"], exclude=[r["fid"]])
check("해물찜 → 해산물 구이·찜만 추천", res["추천"] and all(c["업종"] == "해산물 구이/찜" for c in res["추천"]))
print("  ", [(c["상호"], c["업종"], c["직선거리_m"], c["걷는거리_m"], c["걷는시간_분"]) for c in res["추천"]])
must_fail("해물찜 → 묶음 넓히기를 동의 없이", lambda: E.recommend(f0["leaf"], f0["kind"], r["x"], r["y"], scope="group"))
res = E.recommend(f0["leaf"], f0["kind"], r["x"], r["y"], scope="group", consent_group=True, exclude=[r["fid"]], n=10)
check("동의 후 넓히면 해산물 요리 묶음 안에서만", all(c["묶음"] == "해산물 요리" for c in res["추천"]))
# 2) 헬스장 → 골프연습장이 섞이면 안 됨
r = pick(E.F[E.F["업종"] == "헬스장"]["업종코드"].iloc[0])
for f in [f for f in E.functions_of(r["fid"]) if f["kind"]]:
    res = E.recommend(f["leaf"], f["kind"], r["x"], r["y"], exclude=[r["fid"]], n=10)
    allc = res["추천"] + res["제공여부확인필요"]
    check(f"헬스장({f['name']}/{f['kind']}) → 골프 없음" + (" (약한 연결이라 확인 필요 목록으로)" if not res["추천"] else ""), allc and not any("골프" in (c["업종"] + c["세부종류"]) for c in allc))
# 약한 연결은 추천 목록에 바로 나오지 않음: 반찬(분식집 포장), 친목(헬스장), 방과후 돌봄(교과 학원), 현금 입출금(편의점)
# 삭제한 연결은 어떤 목록에도 나오지 않음 (김밥집→반찬, 입시학원→방과후 돌봄)
check("김밥집은 반찬 종류에 없음", ("P01.1.04", "분식집 포장") not in E.kind)
for k in [k for (L, k) in E.kind if L == "P04.2.02"]:
    res = E.recommend("P04.2.02", k, 128.6, 35.87, scope="kind", elig_ok={k})
    check(f"방과후 돌봄/{k} → 입시·교과학원 없음", not any(c["업종"] == "입시·교과학원" for c in res["추천"] + res["제공여부확인필요"] + res["이용자격확인필요"]))
res = E.recommend("P04.2.02", "태권도·무술 도장", 128.6, 35.87)
check("방과후 돌봄 → 태권도장은 예체능 학원 묶음, 추천 목록에 나옴 (헌준님 판단)", res["추천"] and all(c["묶음"] == "예체능 학원" for c in res["추천"]))
res = E.recommend("P11.1.03", "헬스장", 128.6, 35.87)
check("친목 장소/헬스장 → 같은 종류면 충분 (모임이 옮겨 감)", res["추천"] and all(c["업종"] == "헬스장" for c in res["추천"]))
res = E.recommend("P05.1.01", None, 128.6, 35.87)
check("현금 입출금 → 편의점(부 기능)은 추천 목록에 없음", all(c["업종"] != "편의점" for c in res["추천"]) and any(c["업종"] == "편의점" for c in res["제공여부확인필요"]))
# 3) 이발소(인허가 이용업)는 미용실과 다른 종류
res = E.recommend("P07.2.01", "이발소", 128.6, 35.87, n=10)
check("이발소 → 이발소(이용업)만", res["추천"] and all(F.loc[c["fid"], "표준산업분류"] == "이용업" for c in res["추천"]))
res = E.recommend("P07.2.01", "미용실", 128.6, 35.87, n=10)
check("미용실 → 이용업 없음", res["추천"] and all(F.loc[c["fid"], "표준산업분류"] != "이용업" for c in res["추천"]))
# 4) 노인맞춤돌봄(생활 지원) → 행정복지센터를 '신청 창구'로만
res = E.recommend("P04.1.03", "행정복지센터(신청)", 128.6, 35.87)
check("생활 지원·안부 돌봄 → 신청·문의 창구 표시", res["추천"] and all("신청·문의 창구" in c["표시"] for c in res["추천"]))
res = E.recommend("P04.1.01", "방문요양 기관", 128.6, 35.87)
check("방문요양 → 장기요양 등급 확인 전에는 추천 목록 비움", not res["추천"] and res["이용자격확인필요"] and all(c["업종"] == "방문요양" for c in res["이용자격확인필요"]))
res = E.recommend("P04.1.01", "방문요양 기관", 128.6, 35.87, elig_ok={"방문요양 기관"})
check("방문요양 → 등급 확인 후 방문요양 기관만", res["추천"] and all(c["업종"] == "방문요양" for c in res["추천"]))
res = E.recommend("P04.1.05", "방문간호 기관", 128.6, 35.87, elig_ok={"방문간호 기관"})
check("방문 간호 → 방문간호 기관만 (방문요양과 섞이지 않음)", res["추천"] and all(c["업종"] == "방문간호" for c in res["추천"]))
res = E.recommend("P11.1.03", "경로당", 128.6, 35.87)
check("경로당 → 65세 이상 확인 전에는 추천 목록 비움", not res["추천"] and res["이용자격확인필요"])
# 5) 종량제 봉투는 같은 구·군만
must_fail("종량제 봉투를 구·군 없이", lambda: E.recommend("P02.1.07", None, 128.6, 35.87))
res = E.recommend("P02.1.07", None, 128.6, 35.87, user_gu="수성구", n=10)
check("종량제 봉투 → 수성구 판매소만", res["추천"] and all(F.loc[c["fid"], "구군"] == "수성구" for c in res["추천"]))
# 6) 연결된 시설이 없는 기능은 추천하지 않음, 없는 종류 이름도 막음
must_fail("연결 시설 없는 기능(택시)", lambda: E.recommend("P12.1.03", None, 128.6, 35.87))
must_fail("없는 세부 종류 이름", lambda: E.recommend("P01.1.05", "해물찜 맛집", 128.6, 35.87))
# 7) 겸업 종류·약한 연결: 추천 목록에는 자료로 근거가 확인된 곳만 (근거 문장이 카드에 있어야 함), 근거 없는 곳은 '제공 여부 확인 필요'로
mx = [(l, k) for (l, k), v in E.kind.items() if v["mixed"] and v["fids"]]
random.seed(7)
for l, k in random.sample(mx, min(25, len(mx))):
    res = E.recommend(l, k, 128.6, 35.87)
    v = E.kind[(l, k)]
    def all_ways(f):   # 의도와 상관없이 그 종류면 모두 하는 연결 (예: 중국집은 포장·배달 모두) — 근거 없이도 추천 가능
        fs = [x for x in E.func.get(v["via"][f], []) if x["id"] == l]
        return bool(fs) and bool(fs[0].get("check_items")) and all(a == "종류로 충분" for a in fs[0]["check_items"].values()) and not v["mixed_spec"]
    check(f"겸업 종류 {l}/{k} → 추천은 근거 있는 곳(또는 의도와 상관없이 모두 하는 종류)만 ({len(res['추천'])}곳), 확인 필요에는 근거 없는 곳만",
          all(c["근거자료"] or all_ways(c["fid"]) for c in res["추천"]) and not any(c["근거자료"] for c in res["제공여부확인필요"]))
# 7-1) 근거 자료로 가르는 의료 기능
ps = [f for (l, k), v in E.kind.items() if l == "P03.1.05" and k in ("정신건강의학과 의원", "정신과 병원") for f in v["fids"]]
neuro_only = [f for f in ps if E.ev.get((f, "P03.1.01")) and {r[0] for r in E.ev[(f, "P03.1.01")]} == {"신경과"}]
check(f"정신건강 상담 종류에 신경과만 있는 의원 0곳 (발견 {len(neuro_only)})", not neuro_only)
res = E.recommend("P03.1.02", "지정 응급의료기관 응급실", 128.6, 35.87, n=10)
check("응급 진료 → 정부 지정 응급의료기관만", res["추천"] and all("응급의료" in c["근거자료"][0] for c in res["추천"]))
res = E.recommend("P03.1.01", "정형외과", 128.6, 35.87, n=10)
check("외래 진료 정형외과 → 정형외과 근거가 있는 곳만", res["추천"] and all("정형외과" in c["근거자료"][0] for c in res["추천"]))
res = E.recommend("P03.1.03", "물리치료실 있는 의원", 128.6, 35.87, n=10)
check("물리치료 → 물리치료실·재활의학과 근거가 있는 곳만", res["추천"] and all(("물리치료실" in c["근거자료"][0]) or ("재활" in c["근거자료"][0]) for c in res["추천"]))
# 7-2) 세부 의도(포장·배달): 의도에 따라 판정이 갈림
res = E.recommend("P01.1.06", "중국집", 128.6, 35.87, need="배달")
check("배달 + 중국집 → 추천 있음 (중국집은 거의 모두 배달)", bool(res["추천"]))
res = E.recommend("P01.1.06", "백반·한정식", 128.6, 35.87, need="배달")
check("배달 + 백반집 → 추천 비움, 확인 필요로만 (배달 여부 자료 없음)", not res["추천"] and res["제공여부확인필요"])
res = E.recommend("P01.1.06", "백반·한정식", 128.6, 35.87, need="포장")
check("포장 + 백반집 → 추천 비움, 확인 필요로만 (헌준님 판단: 일반 식당의 포장은 가게마다 다름)", not res["추천"] and res["제공여부확인필요"])
res = E.recommend("P01.1.06", "김밥·만두·분식", 128.6, 35.87, need="포장")
check("포장 + 분식집 → 추천 있음 (포장이 기본인 종류)", bool(res["추천"]))
res = E.recommend("P01.1.06", "김밥·만두·분식", 128.6, 35.87, need="배달")
check("배달 + 분식집 → 추천 비움 (배달 여부 자료 없음)", not res["추천"])
res = E.recommend("P01.1.06", "백반·한정식", 128.6, 35.87)
check("의도 모름 + 백반집 → 추천 비움 (먼저 물어봐야 함)", not res["추천"])
must_fail("없는 세부 의도", lambda: E.recommend("P01.1.06", "중국집", 128.6, 35.87, need="택배"))
# 7-3) 근거 '아니요'는 어디에도 나오지 않음 (작은 식당은 단체 식사에서 빠짐)
res = E.recommend("P11.2.01", "돼지고기 구이·찜", 128.6, 35.87, n=10)
allc = res["추천"] + res["제공여부확인필요"] + res["운영확인필요"]
check("단체 식사 → 영업장 50㎡ 미만 식당 0곳, 추천은 100㎡ 이상만", not any(E.evidence(c["fid"], "P11.2.01")[0] == "아니요" for c in allc)
      and all("영업장 넓이" in c["근거자료"][0] for c in res["추천"]))
# 7-2) 걷는 거리: 고른 5곳이 정말 걷는 거리로 가장 가까운 5곳인지 (후보 전부를 직접 계산해 대조)
random.seed(14)
for (lid, k) in [("P07.2.01", "미용실"), ("P03.2.01", None), ("P04.2.01", "어린이집(국공립·민간·법인 등)"), ("P10.1.04", "근린·체육·수변 공원")]:
    o = ok.sample(1, random_state=random.randint(0, 9999)).iloc[0]
    res = E.recommend(lid, k, o["x"], o["y"], n=5)
    pool = [f for f in (E.kind[(lid, k)]["fids"] if k else {f for f in F.index if any(g["id"] == lid for g in E.func.get(F.loc[f, "업종코드"], []))})
            if F.loc[f, "대안후보"] == "예" and F.loc[f, "x"] == F.loc[f, "x"]]
    W = E.walk.distances(o["x"], o["y"], pool, max_m=8000)
    best = sorted(w for w in W.values() if w is not None)[:5]
    got = [c["걷는거리_m"] for c in res["추천"] if c["걷는거리_m"] is not None]
    far = [c for c in res["추천"] if c["걷는거리_m"] is None]
    check(f"걷는 거리 순서 {lid}/{k}: 가장 가까운 곳과 일치 (걸어서 먼 곳 {len(far)}곳은 표시 붙임)",
          [round(b) for b in best][:len(got)] == got and all(any("걸어서 가기 먼" in x for x in c["표시"]) for c in far))
res = E.recommend("P07.2.01", "미용실", 128.6, 35.87, speed="천천히")
check(f"천천히 걸음 → 걷는 시간 = 거리 ÷ {E.SPEED['천천히']}m/s", all(abs(c["걷는시간_분"] - c["걷는거리_m"] / E.SPEED["천천히"] / 60) < 0.06 for c in res["추천"]))
check("걷는 거리는 직선거리보다 짧지 않음", all(c["걷는거리_m"] >= c["직선거리_m"] - 1 for c in res["추천"]))
must_fail("모르는 걸음 속도", lambda: E.recommend("P07.2.01", "미용실", 128.6, 35.87, speed="뛰어서"))
# 8) 전체 훑기: 모든 세부 종류에서, 그 종류 시설 하나의 자리에서 찾았을 때 결과가 모두 같은 종류 정의에 맞는지 (색인과 따로 분류표 정의로 대조)
random.seed(2026); n_kind = 0; bad = []
for (lid, k), v in E.kind.items():
    mem = [f for f in v["fids"] if F.loc[f, "대안후보"] == "예"]
    if not mem: continue
    f = random.choice(mem); n_kind += 1
    kd = [x for g in E.leaf[lid]["kinds"]["groups"] for x in g["kinds"] if x["name"] == k][0]
    allowed_codes = {u["code"] for u in kd["upjong"]} | {t["code"] for t in kd["types"]}
    res = E.recommend(lid, k, F.loc[f, "x"], F.loc[f, "y"], exclude=[f], n=5)
    for c in res["추천"] + res["제공여부확인필요"]:
        code = F.loc[c["fid"], "업종코드"]
        if any(c["fid"] in E.evm.get(t, {}) for t in allowed_codes if t.startswith("EV:")): continue   # 근거 유형으로 들어온 시설
        perm = [t for t in allowed_codes if t.startswith("PERMIT:")]
        if code not in allowed_codes and not any(F.loc[c["fid"], {"PERMIT:상비약판매": "상비약판매", "PERMIT:종량제봉투판매": "종량제봉투판매", "PERMIT:공원운동시설": "공원운동시설"}[t]] == "True" for t in perm):
            bad.append((lid, k, c["fid"], code))
check(f"전체 훑기: 세부 종류 {n_kind}개에서 종류가 다른 시설 0곳 (발견 {len(bad)})", not bad)
print(bad[:10])
print("실패", len(fails)); sys.exit(1 if fails else 0)
