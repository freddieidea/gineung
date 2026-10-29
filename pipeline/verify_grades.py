"""등급 근거 독립 점검 (다른 모델): 법률·기준·통계 근거가 사실과 맞는지, 규칙 적용이 일관된지"""
import json, sys, anthropic
sys.path.insert(0,"pipeline"); import grades_spec as S
client=anthropic.Anthropic(api_key=open("settings/anthropic_key.txt",encoding="utf-8").read().strip())
T=json.load(open("design/purpose_taxonomy.json",encoding="utf-8")); assert T["version"]=="0.9-draft"
L={l["id"]:(c["name"],l) for c in T["categories"] for p in c["purposes"] for l in p["leaves"]}
g=lambda a,b: "필수" if a and b else ("준필수" if a or b else "선택")
rows=[{"id":i,"분야":L[i][0],"세부 기능":L[i][1]["name"],"설명":L[i][1]["desc"],"①공적 최소 보장":a,"①근거":ab,"②주 1회 이상":b,"②근거":bb,"계산된 등급":g(a,b)} for i,(a,ab,b,bb,_) in S.G.items()]
SYSTEM="""당신은 한국 생활 서비스의 법·제도·통계 전문가입니다. 세부 기능별 등급 근거를 점검합니다. 확실한 오류만 찾습니다.
규칙: ① 법률이 국가·지자체에 제공·설치·지원 의무를 두거나 정부 국가 최저기준(기초생활인프라 국가적 최저기준, 농어촌서비스기준)에 들어 있으면 예. 단순히 영업을 규제하는 법(허가·신고)은 해당 안 됨. ② 그 기능을 쓰는 사람이 보통 주 1회 이상 쓴다는 것이 통계·제도 기준으로 확인될 때만 예, 확인 안 되면 아니오.
찾을 오류: (1) 근거로 든 법률·조항·기준이 존재하지 않거나 그런 내용이 아님 (2) 근거가 있는데 '없음'으로 둠(한국 법률·국가 최저기준에 실제로 있는 경우만) (3) ② 판단이 근거와 맞지 않음 (4) 같은 성격의 기능끼리 판단이 어긋남
출력은 JSON 배열만: [{"id":"..","problem":"한 문장","fix":"한 문장"}]. 없으면 []."""
r=client.messages.create(model="claude-opus-5-5",max_tokens=12000,system=SYSTEM,messages=[{"role":"user","content":json.dumps({"출처":S.SRC,"기능":rows},ensure_ascii=False)}])
t="".join(b.text for b in r.content if getattr(b,"type","")=="text").strip()
if t.startswith("```"): t=t.split("\n",1)[1].rsplit("```",1)[0]
out=json.loads(t); json.dump(out,open("data/work/grades_verify.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
for x in out: print("-",x["id"],L.get(x["id"],("",{"name":""}))[1]["name"] if x["id"] in L else "","|",x["problem"],"|",x["fix"])
print("지적",len(out))
