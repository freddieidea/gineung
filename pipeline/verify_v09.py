"""분류표 0.9 추가분 독립 점검 (다른 모델): 새 기능의 위치·대체 관계·세부 종류·업종 연결·추천 안전 규칙의 빈틈"""
import json, anthropic
client=anthropic.Anthropic(api_key=open("settings/anthropic_key.txt",encoding="utf-8").read().strip())
T=json.load(open("design/purpose_taxonomy.json",encoding="utf-8")); assert T["version"]=="0.9-draft"
M=json.load(open("data/processed/industry_function_map.json",encoding="utf-8"))
L={x["code"]:x["소분류"] for x in json.load(open("data/processed/industry_list.json",encoding="utf-8"))}
NEW=("P02.1.08","P02.1.09","P02.1.10","P02.2","P03.3.03","P06.1.04","P06.3","P07.4","P08.2","P08.1.07","P09.2.03","P10.1.05","P12.2.04","P15.2","P16","P17")
rows=[]
for c in T["categories"]:
    for p in c["purposes"]:
        for l in p["leaves"]:
            if l["id"].startswith(NEW):
                k=l["kinds"]
                rows.append({"분야":c["name"],"이용 목적":p["name"],"목적 안 대체":"가능" if p["substitutable"] else "불가","같은 목적의 다른 기능":[x["name"] for x in p["leaves"] if x["id"]!=l["id"]],
                  "id":l["id"],"세부 기능":l["name"],"설명":l["desc"],"등급":l["grade"],"공적 보장":l["public_basis"],
                  "세부 종류":[{"묶음":g["name"],"종류":[x["name"]+(" (가게별 확인)" if x["mixed"] else "") for x in g["kinds"]]} for g in k.get("groups",[])] if k.get("sensitive") else k.get("reason"),
                  "가게별 확인 항목":k.get("check",""),
                  "연결 업종":[f'{L[i["code"]]}({f["role"]}·{f["confidence"]})' for i in M["items"] for f in i["functions"] if f["id"]==l["id"]]})
SYSTEM="""당신은 문 닫은 가게 대신 갈 곳을 주민에게 추천하는 서비스의 분류 체계를 점검합니다. 확실한 오류만 찾습니다.
규칙: '목적 안 대체 가능'인 이용 목적에서는 원하는 기능의 대안이 없을 때 같은 목적의 다른 기능으로 넓혀 찾습니다. 세부 종류가 다르면 주민에게 묻기 전에는 대신하지 않습니다.
찾을 오류: (1) 서로 대신할 수 없는 기능이 '대체 가능' 목적에 함께 있음 (2) 서로 대신할 수 없는 것이 한 세부 종류에 섞임 (3) 업종 연결이 틀림 (4) 등급·공적 보장 근거가 사실과 다름 (5) 아래 추천 안전 규칙으로 막지 못하는 '없는 시설·안 맞는 시설·섞인 정보' 추천 경로
출력은 JSON 배열만: [{"id":"세부 기능 ID 또는 rules","problem":"한 문장","fix":"한 문장"}]. 없으면 []."""
user=json.dumps({"새 세부 기능":rows,"추천 안전 규칙":T["rules"]["recommend_safety"],"세부 종류 규칙":T["rules"].get("kinds")},ensure_ascii=False)
r=client.messages.create(model="claude-opus-5-5",max_tokens=8000,system=SYSTEM,messages=[{"role":"user","content":user}])
t="".join(b.text for b in r.content if getattr(b,"type","")=="text").strip()
if t.startswith("```"): t=t.split("\n",1)[1].rsplit("```",1)[0]
out=json.loads(t); json.dump(out,open("data/work/v09_verify.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
for x in out: print("-",x["id"],"|",x["problem"],"|",x["fix"])
print("지적",len(out))
