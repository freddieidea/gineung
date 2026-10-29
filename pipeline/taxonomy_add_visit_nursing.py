# 분류표에 '방문 간호'(P04.1.05) 세부 기능을 더한다 (현장 판단: 박헌준, 2026-10-13). 여러 번 돌려도 결과가 같음
# 방문간호 기관(국민건강보험공단 장기요양기관 자료 51곳)이 맞는 기능이 없어 비어 있었음. 방문요양과 하는 일이 달라(간호사의 간호·처치) 따로 둠
import json
p="design/purpose_taxonomy.json"; T=json.load(open(p,encoding="utf-8")); assert T["version"]=="0.9-draft"
P=[q for c in T["categories"] for q in c["purposes"] if q["id"]=="P04.1"][0]
assert P["substitutable"] is False  # 노인 돌봄은 대체 불가 목적: 방문요양으로 방문간호를 대신하지 않음
if not any(l["id"]=="P04.1.05" for l in P["leaves"]):
    P["leaves"].append({"id":"P04.1.05","name":"방문 간호","desc":"간호사가 집으로 방문해 간호·처치(욕창 관리, 도뇨관·위루관 관리 등)",
        "modes":["배달·방문"],"extra":"이용 자격(장기요양등급), 의사의 방문간호지시서","examples":"방문간호 기관",
        "public_basis":"","weekly_use":"","grade":"미확정","grade_estimated":False})
    T["changelog"].append({"date":"2026-10-13","change":"방문 간호(P04.1.05) 추가 (현장 판단: 박헌준). 방문간호 기관 51곳이 맞는 세부 기능이 없었음. 방문요양과 하는 일이 달라 따로 두고, 노인 돌봄(대체 불가) 목적에 넣음"})
    open(p,"w",encoding="utf-8").write(json.dumps(T,ensure_ascii=False,indent=1)); print("추가함")
else: print("이미 있음")
