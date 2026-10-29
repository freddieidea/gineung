"""공공·복지 시설 추가분 독립 점검 (다른 모델): 시설 유형의 기능 연결, 세부 종류, 신청·문의 창구 표시, 자료·좌표 처리, 대안 찾기 엔진의 빈틈"""
import json, anthropic, pandas as pd
client=anthropic.Anthropic(api_key=open("settings/anthropic_key.txt",encoding="utf-8").read().strip())
T=json.load(open("design/purpose_taxonomy.json",encoding="utf-8")); assert T["version"]=="0.9-draft"
X=json.load(open("data/processed/extra_type_functions.json",encoding="utf-8"))
P=pd.read_csv("data/processed/public_facilities.csv",dtype=str)
L={l["id"]:(c["name"],p["name"],l) for c in T["categories"] for p in c["purposes"] for l in p["leaves"]}
used=sorted({f["id"] for x in X["items"] if x["code"].startswith("PUB:") for f in x["functions"]})
leaves=[{"id":i,"분야/목적":f"{L[i][0]}/{L[i][1]}","세부 기능":L[i][2]["name"],"설명":L[i][2]["desc"],"등급":L[i][2]["grade"],
         "세부 종류":[{"묶음":g["name"],"종류":[k["name"]+(" [신청·문의 창구]" if k.get("contact") else "")+(" [가게별 확인]" if k["mixed"] else "")+f" {k['stores']}곳" for k in g["kinds"]]} for g in L[i][2]["kinds"].get("groups",[])],
         "가게별 확인 항목":L[i][2]["kinds"].get("check","")} for i in used]
types=[{"code":x["code"],"이름":x["name"],"출처":x["source"],"기능":[f'{f["id"]} {L[f["id"]][2]["name"]} ({f["role"]}·{f["confidence"]}): {f["reason"]}' for f in x["functions"]],
        "시설 수":int((P["업종코드"]==x["code"]).sum()),"대안 후보 상태":P[P["업종코드"]==x["code"]]["대안후보"].value_counts().to_dict(),"메모":x.get("note","")} for x in X["items"] if x["code"].startswith("PUB:")]
coord=P["좌표근거"].str.replace(r"\(.*","",regex=True).value_counts().to_dict()
SYSTEM="""당신은 문 닫은 시설 대신 갈 곳을 대구 주민에게 추천하는 서비스의 공공시설 자료를 점검합니다. 확실한 오류만 찾습니다.
찾을 오류: (1) 시설 유형에 연결한 기능이 사실과 다름(그 시설이 실제로 하지 않는 일, 신청 창구를 서비스 제공처처럼 연결 등) (2) 서로 대신할 수 없는 것이 한 세부 종류에 섞임(예: 이용 자격이 다른 시설) (3) 신청 창구 안내 내용이 한국 제도와 다름(예: 어떤 서비스의 실제 신청처가 다른 기관) (4) 이용 자격 제한이 있는데 표시가 없음 (5) 좌표·자료 처리 방법에서 다른 시설 정보가 섞일 수 있는 경로 (6) 추천 안전 규칙으로 막지 못하는 경로
출력은 JSON 배열만: [{"id":"시설 유형 code 또는 세부 기능 ID 또는 rules","problem":"한 문장","fix":"한 문장"}]. 없으면 []."""
METHOD=("좌표: 표준데이터 좌표 → 상가·인허가 자료에서 도로명주소(구·군+도로명+건물번호)가 같은 건물의 좌표 → 브이월드 주소 검색(돌려준 주소가 입력 주소와 도로명·번호까지 똑같을 때만, 구·군 경계 안일 때만) → 주소가 없는 체육시설만 브이월드 장소 이름 검색(띄어쓰기 뺀 이름이 똑같고 같은 구·군, 같은 이름이 300m 넘게 흩어져 있으면 버림) → 주소 없는 시설만 같은 단지 시설 이름으로 시작하면 그 좌표. 못 찾으면 '좌표 필요'로 추천에서 뺌. "
        "대구 주소 판단: '대구광역시·대구시·대구 '로 시작하거나 '경상북도 군위군'. 장기요양기관은 기관코드×서비스마다 한 줄.")
user=json.dumps({"시설 유형":types,"연결된 세부 기능":leaves,"좌표 근거별 시설 수":coord,"처리 방법":METHOD,"추천 안전 규칙":T["rules"]["recommend_safety"],"세부 종류 규칙":T["rules"].get("kinds")},ensure_ascii=False)
r=client.messages.create(model="claude-opus-5-5",max_tokens=10000,system=SYSTEM,messages=[{"role":"user","content":user}])
t="".join(b.text for b in r.content if getattr(b,"type","")=="text").strip()
if t.startswith("```"): t=t.split("\n",1)[1].rsplit("```",1)[0]
out=json.loads(t); json.dump(out,open("data/work/public_verify.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
for x in out: print("-",x["id"],"|",x["problem"],"|",x["fix"])
print("지적",len(out))
