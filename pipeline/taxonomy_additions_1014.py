# 분류표 보완 (2026-10-14 전체 점검): 국가 최저기준(기초생활인프라·농어촌서비스기준)·노인실태조사 항목과 대조해 빠진 생활 기능을 더함. 여러 번 실행해도 결과가 같음
import json
p="design/purpose_taxonomy.json"; T=json.load(open(p,encoding="utf-8")); assert T["version"]=="0.9-draft"
P={q["id"]:q for c in T["categories"] for q in c["purposes"]}; C={c["id"]:c for c in T["categories"]}
def leaf(pid, d):
    if not any(l["id"]==d["id"] for l in P[pid]["leaves"]):
        P[pid]["leaves"].append(dict(d, public_basis="", weekly_use="", grade="미확정", grade_estimated=False)); return True
    return False
log=[]
if leaf("P04.1", {"id":"P04.1.06","name":"단기 보호","desc":"며칠에서 몇 달까지 짧게 입소해 받는 돌봄 (가족이 돌보기 어려울 때)","modes":["직접 방문"],
                   "extra":"이용 자격(장기요양등급), 이용 일수 제한","examples":"단기보호 기관"}):
    log.append("단기 보호(P04.1.06) 추가: 단기보호는 이용 일수가 정해진 재가급여라 장기 요양 입소와 다름 (독립 점검 지적)")
if leaf("P12.1", {"id":"P12.1.04","name":"도시철도 이용","desc":"지하철 타기","modes":["직접 방문"],"extra":"","examples":"도시철도역"}):
    log.append("도시철도 이용(P12.1.04) 추가: 지하철역 자료는 있었으나 연결할 기능이 없었음")
if "P04.5" not in P:
    C["P04"]["purposes"].append({"id":"P04.5","name":"가족 지원","substitutable":False,"leaves":[]}); P["P04.5"]=C["P04"]["purposes"][-1]
if leaf("P04.5", {"id":"P04.5.01","name":"다문화가족 지원","desc":"결혼이민자·다문화가족 상담, 한국어 교육, 통번역","modes":["직접 방문","전화·온라인"],"extra":"","examples":"가족센터(다문화가족지원센터)"}):
    log.append("다문화가족 지원(P04.5.01) 추가: 농어촌서비스기준 항목인데 빠져 있었음")
L01=[l for l in P["P04.2"]["leaves"] if l["id"]=="P04.2.01"][0]
if L01["name"]!="영유아 보육·유아 교육":
    L01.update(name="영유아 보육·유아 교육", desc="어린이집, 유치원", examples="어린이집, 유치원")
    log.append("영유아 보육(P04.2.01)을 '영유아 보육·유아 교육'으로 넓힘: 만 3~5세는 어린이집과 유치원이 같은 누리과정을 해 서로 대안이 됨. 유치원은 기초생활인프라 최저기준(도보 5~10분)·농어촌서비스기준 항목")
if leaf("P02.1", {"id":"P02.1.11","name":"침구·커튼 구입","desc":"이불·베개·커튼","modes":["직접 방문"],"extra":"","examples":"이불 가게, 커튼 가게"}):
    log.append("침구·커튼 구입(P02.1.11) 추가: 이불·커튼 가게가 '생활소모품(휴지·세제)'에 잘못 연결돼 있었음 (실제 추천 시설 독립 점검 지적). 가게가 없어지면 주민이 찾는 것은 다른 이불·커튼 가게라 따로 둠")
for m in log:
    if not any(x["change"]==m for x in T["changelog"]): T["changelog"].append({"date":"2026-10-14","change":m})
open(p,"w",encoding="utf-8").write(json.dumps(T,ensure_ascii=False,indent=1)); print("\n".join(log) or "바뀐 것 없음")
