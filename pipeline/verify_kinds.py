"""세부 종류 독립 점검: 종류를 만든 쪽과 다른 모델이 오류만 찾아냄. 사용: python verify_kinds.py 모델 시작 개수"""
import json, sys, collections, anthropic
sys.path.insert(0,"pipeline"); import kinds_spec as S
MODEL=sys.argv[1]
IDS=sys.argv[2].split(",") if sys.argv[2].startswith("P") else None
START=0 if IDS else int(sys.argv[2]); COUNT=0 if IDS else int(sys.argv[3])
client=anthropic.Anthropic(api_key=open("settings/anthropic_key.txt",encoding="utf-8").read().strip())
T=json.load(open("design/purpose_taxonomy.json",encoding="utf-8")); assert T["version"]=="0.9-draft", T["version"]
leaves={l["id"]:l for c in T["categories"] for p in c["purposes"] for l in p["leaves"]}
M=json.load(open("data/processed/industry_function_map.json",encoding="utf-8"))
L={x["code"]:x for x in json.load(open("data/processed/industry_list.json",encoding="utf-8"))}
E=json.load(open("data/processed/industry_examples.json",encoding="utf-8"))["examples"]
code={x["소분류"]:c for c,x in L.items()}
link=collections.defaultdict(set)
for it in M["items"]:
    for f in it["functions"]: link[f["id"]].add(L[it["code"]]["소분류"])
ids=IDS or sorted(set(S.K)|set(S.NOT))[START:START+COUNT]
payload=[]
for lid in ids:
    l=leaves[lid]; row={"id":lid,"세부 기능":l["name"],"설명":l["desc"]}
    if lid in S.K:
        sp=S.K[lid]; g=S.food_for(link[lid]) if sp.get("food") else sp["groups"]
        row["종류 묶음"]={gn:[{"세부 종류":x["name"],"업종":[f'{u} (예: {", ".join(e["상호"] for e in E[code[u]][:2])})'+(f' 중 표준산업분류 {x["std"]}' if x.get("std") else "") for u in x["upjong"]],"여러 종류 겸업":x["mixed"]} for x in ks] for gn,ks in g.items()}
        if sp.get("note"): row["참고"]=sp["note"]
        row["가게별 확인 항목"]=sp["check"]
    else:
        row["종류 구분 안 함"]=S.NOT[lid]; row["연결 업종"]=sorted(link[lid])
        row["가게별 확인 항목"]=S.CHECK.get(lid,"")
    payload.append(row)
SYSTEM="""당신은 다른 사람이 만든 '세부 종류' 분류를 점검합니다. 이 분류는 문 닫은 가게 대신 갈 곳을 주민에게 추천할 때 쓰입니다.
규칙: 대안은 같은 '세부 종류' 안에서 먼저 찾고, 없으면 같은 '종류 묶음'(비슷한 종류)을 주민에게 물어본 뒤 보여 주며, 다른 묶음은 주민이 따로 원할 때만 보여 줍니다.
예: 해물찜 집을 찾는 사람에게 분식집이나 고깃집을, 헬스장을 찾는 사람에게 골프 연습장을 같은 것처럼 알려 주면 심각한 오류입니다.
'여러 종류 겸업'은 슈퍼·편의점·종합병원처럼 여러 종류를 함께 하는 업종이라 가게별로 실제 하는지 확인한다는 뜻입니다.
찾아야 할 오류 (확실한 것만):
- 잘못된 묶음: 주민이 비슷하다고 여기지 않을 종류가 같은 묶음에 있음
- 너무 넓은 세부 종류: 한 세부 종류 안에 주민이 서로 다르게 여기는 것이 섞여 있는데 '가게별 확인 항목'으로도 걸러지지 않음
- 잘못된 위치: 업종이 다른 묶음에 들어가야 함
- 종류 구분이 필요한데 '종류 구분 안 함'으로 되어 있음
- 확인 항목 부족: 가게마다 달라 꼭 확인해야 할 점이 '가게별 확인 항목'에 없음
출력은 JSON 배열만: [{"id":"세부 기능 ID","problem":"잘못된 묶음|너무 넓은 세부 종류|잘못된 위치|종류 구분 필요|확인 항목 부족","target":"문제가 된 묶음·종류·업종 이름","suggest":"고칠 방법 한 문장","reason":"이유 한 문장"}]
오류가 없으면 []만 출력합니다."""
r=client.messages.create(model=MODEL,max_tokens=8000,system=SYSTEM,messages=[{"role":"user","content":json.dumps(payload,ensure_ascii=False)}])
t="".join(b.text for b in r.content if getattr(b,"type","")=="text").strip()
if t.startswith("```"): t=t.split("\n",1)[1].rsplit("```",1)[0]
out=json.loads(t)
bad=[x for x in out if x.get("id") not in ids]
json.dump({"model":MODEL,"ids":ids,"findings":out,"out_of_range":bad},open(f"data/work/kinds_verify_{('re_'+IDS[0]) if IDS else START}.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print(START,len(ids),"지적",len(out),"범위밖",len(bad))
