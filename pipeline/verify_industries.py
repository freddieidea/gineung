"""업종-기능 연결표 독립 점검: 분류에 쓰지 않은 별도 모델·별도 지시로 오류만 찾아냄"""
import json, sys, anthropic
MODEL=sys.argv[1]; START=int(sys.argv[2]); COUNT=int(sys.argv[3])
client=anthropic.Anthropic(api_key=open("settings/anthropic_key.txt",encoding="utf-8").read().strip())
tax=json.load(open("design/purpose_taxonomy.json",encoding="utf-8"))
assert tax["version"]=="0.9-draft", "분류표 버전 불일치: "+tax["version"]
leaves={l["id"]:l for c in tax["categories"] for p in c["purposes"] for l in p["leaves"]}
flist="\n".join(f'{i} | {l["name"]} | {l["desc"]}' for i,l in leaves.items())
ind={r["code"]:r for r in json.load(open("data/processed/industry_list.json",encoding="utf-8"))}
items=json.load(open("data/processed/industry_function_map.json",encoding="utf-8"))["items"][START:START+COUNT]
payload=[{"code":o["code"],"업종":ind[o["code"]]["소분류"],"분류":ind[o["code"]]["대분류"]+">"+ind[o["code"]]["중분류"],"상호예시":ind[o["code"]]["상호예시"][:3],
  "생활시설":o["life_facility"],"연결된기능":[f'{f["id"]} {leaves[f["id"]]["name"]}' for f in o["functions"]]} for o in items]
SYSTEM=f"""당신은 다른 사람이 만든 '업종 → 세부 기능' 연결을 검토하는 점검자입니다. 오류만 찾아냅니다.
[세부 기능 목록: ID | 이름 | 설명]
{flist}
찾아야 할 오류
- 틀린 연결: 그 업종의 가게가 실제로 제공하지 않는 기능이 연결됨
- 빠진 연결: 그 업종의 일반적인 가게가 분명히 제공하는 기능이 빠짐 (목록에 있는 기능만)
- 생활시설 판단 오류: 주민 일상생활에 쓰이는 업종인데 생활시설 아님으로 되어 있거나, 그 반대
확실한 오류만 보고합니다. 애매하면 보고하지 않습니다. 목록에 없는 ID는 쓰지 않습니다.
출력은 JSON 배열만: [{{"code":"...","problem":"틀린 연결|빠진 연결|생활시설 판단 오류","remove":["ID"],"add":["ID"],"life_facility":true,"reason":"한 문장"}}]
오류가 없으면 []만 출력합니다."""
r=client.messages.create(model=MODEL,max_tokens=12000,system=SYSTEM,messages=[{"role":"user","content":json.dumps(payload,ensure_ascii=False)}])
t="".join(b.text for b in r.content if getattr(b,"type","")=="text").strip()
if t.startswith("```"): t=t.split("\n",1)[1].rsplit("```",1)[0]
out=json.loads(t); bad=[]
codes={o["code"] for o in items}
for x in out:
    if x["code"] not in codes: bad.append(f'범위 밖 코드 {x["code"]}')
    for i in x.get("remove",[])+x.get("add",[]):
        if i not in leaves: bad.append(f'{x["code"]} 목록 밖 ID {i}')
json.dump({"model":MODEL,"start":START,"findings":out,"errors":bad},open(f"data/processed/industry_verify_{START:03d}.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print(START,"지적",len(out),"검사오류",len(bad),bad[:3])
