"""약한 연결 판정표 독립 점검 (다른 모델): 판정이 틀려 주민에게 맞지 않는 곳을 추천하거나, 맞는 곳을 빠뜨리는 경우를 찾음"""
import json, sys, anthropic
sys.path.insert(0,"pipeline"); import weak_links_spec as S
client=anthropic.Anthropic(api_key=open("settings/anthropic_key.txt",encoding="utf-8").read().strip())
T=json.load(open("design/purpose_taxonomy.json",encoding="utf-8"))
nm={l["id"]:(l["name"],l["desc"]) for c in T["categories"] for p in c["purposes"] for l in p["leaves"]}
rows=[{"세부 기능":f"{k[0]} {nm[k[0]][0]} ({nm[k[0]][1]})","업종·시설 유형":k[1],"판정":v[0],"이유":v[1]} for k,v in S.W.items()]
SYSTEM="""당신은 문 닫은 시설 대신 갈 곳을 주민(특히 어르신)에게 추천하는 공공 서비스의 판정표를 점검합니다. 확실한 오류만 찾습니다.
판정의 뜻:
- 삭제: 그 업종은 그 일을 하는 곳이 아님 → 추천하지 않음
- 종류로 충분: 주민이 그 세부 종류를 콕 집어 원하면 그 종류의 모든 곳이 그 일을 함 → 확인 없이 추천
- 가게별 확인: 하는 가게도 안 하는 가게도 있음 → '하는지 전화로 확인 필요'로만 보여 줌
- 문의 창구: 직접 하지 않고 신청·문의만 받는 곳
판정 기준: "주민이 그 목적을 말했을 때, 그 가게를 안내받으면 맞다고 할 것인가?"
찾을 오류: (1) '종류로 충분'인데 실제로는 그 종류의 상당수가 그 일을 하지 않음 (확인 없이 추천하면 틀림) (2) '가게별 확인'이나 '종류로 충분'인데 실제로는 그 업종이 그 일을 하는 곳이 아님 (삭제해야 함) (3) '삭제'인데 실제로는 그 업종의 대부분이 그 일을 함 (맞는 곳을 빠뜨림) (4) 한국 제도와 다른 이유
출력은 JSON 배열만: [{"세부 기능":"...","업종":"...","지금 판정":"...","바꿀 판정":"...","이유":"한 문장"}]. 없으면 []."""
r=client.messages.create(model="claude-opus-5-5",max_tokens=20000,system=SYSTEM,messages=[{"role":"user","content":json.dumps(rows,ensure_ascii=False)}])
t="".join(b.text for b in r.content if getattr(b,"type","")=="text").strip()
if t.startswith("```"): t=t.split("\n",1)[1].rsplit("```",1)[0]
open("data/work/weak_verify_raw.txt","w",encoding="utf-8").write(t)
out=json.loads(t); json.dump(out,open("data/work/weak_verify.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
for x in out: print("-",x["세부 기능"],"|",x["업종"],"|",x["지금 판정"],"→",x["바꿀 판정"],"|",x["이유"])
print("지적",len(out))
