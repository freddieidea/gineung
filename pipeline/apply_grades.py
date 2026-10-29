# grades_spec.py의 근거로 세부 기능 등급을 계산해 분류표에 넣는다. 여러 번 돌려도 결과가 같음
import json, sys, collections
sys.path.insert(0, "pipeline"); import grades_spec as S
EXPECT = "0.9-draft"
p = "design/purpose_taxonomy.json"; T = json.load(open(p, encoding="utf-8")); assert T["version"] == EXPECT
L = {l["id"]: l for c in T["categories"] for q in c["purposes"] for l in q["leaves"]}
assert set(L) == set(S.G) | S.FIELD and not (set(S.G) & S.FIELD), "분류표와 등급 근거의 기능 목록이 다름"
g = lambda a, b: "필수" if a and b else ("준필수" if a or b else "선택")
for i, (a, ab, b, bb, note) in S.G.items():
    l = L[i]
    l["grade"] = g(a, b)
    l["public_basis"] = ab
    l["weekly_use"] = ("예 — " if b else "아니오 — ") + bb
    l["grade_basis"] = {"public": a, "weekly": b, "note": note}
    l["grade_estimated"] = False
    l["grade_source"] = "현장 확인(박헌준)과 근거 계산" if note == "현장 확인됨" else ("건강·안전 예외(박헌준 확인)" if note == "건강·안전 예외" else "법령·국가 최저기준·통계 근거 계산")
for i in S.FIELD: L[i]["grade_estimated"] = False
T["grade_rule"] = ("① 법률이 국가·지자체에 제공·설치·지원 의무를 두거나 정부 국가 최저기준(기초생활인프라 국가적 최저기준, 농어촌서비스기준)에 들어 있음 "
  "② 그 기능을 쓰는 사람이 보통 주 1회 이상 씀(공식 통계·제도 기준으로 확인될 때만, 확인 안 되면 아니오). 자주 쓰지 않아도 끊기면 생명·건강·안전에 바로 위험한 기능은 ②를 충족한 것으로 봄. "
  "둘 다 충족 필수, 하나 충족 준필수, 둘 다 아니면 선택. 현장 판단으로 정한 기능은 그대로 둠.")
T["grade_sources"] = S.SRC
msg = "세부 기능 등급 완성: 미확정 51개를 포함해 108개 모두 법령·국가 최저기준·통계 근거로 계산 (건강·안전 예외 5개, 현장 확인 7개는 박헌준 확인). 다른 모델 독립 점검 반영"
if not any(x["change"] == msg for x in T["changelog"]): T["changelog"].append({"date": "2026-10-13", "change": msg})
left = [i for i, l in L.items() if l["grade"] not in ("필수", "준필수", "선택")]
assert not left, left
open(p, "w", encoding="utf-8").write(json.dumps(T, ensure_ascii=False, indent=1))
print(collections.Counter(l["grade"] for l in L.values()), "미확정", len(left))
