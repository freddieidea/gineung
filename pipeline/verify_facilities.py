"""시설 데이터베이스 규칙 독립 점검: 인허가 업종·업태 → 상가 업종 대응표와 대안 후보 제외 규칙에 오류가 없는지 다른 모델이 검토"""
import json, sys, re, anthropic
client=anthropic.Anthropic(api_key=open("settings/anthropic_key.txt",encoding="utf-8").read().strip())
src=open("pipeline/build_facilities.py",encoding="utf-8").read()
m=open("pipeline/match_localdata.py",encoding="utf-8").read()
prim=m[m.index("PRIMARY="):m.index("def primary_for")]
part=src[src.index("def clinic_type"):src.index("O[\"업종코드\"]=O.apply")]
excl=src[src.index("bad=A["):src.index("# ---- 2)")]
SYSTEM="""당신은 공공데이터 처리 규칙을 점검하는 검토자입니다. 이 규칙은 문 닫은 가게 대신 갈 곳을 주민에게 추천하는 서비스의 시설 목록을 만듭니다.
가장 심각한 오류는 (1) 주민이 원하는 것과 다른 종류의 가게를 같은 종류로 분류하는 것(예: 해물찜 집을 분식집으로, 헬스장을 골프 연습장으로), (2) 문 닫은 가게를 대안으로 남기는 것, (3) 영업 중인 가게를 잘못 빼는 것입니다.
아래 규칙에서 확실한 오류만 찾으세요. 출력은 JSON 배열만: [{"where":"규칙 위치","problem":"한 문장","fix":"고칠 방법 한 문장"}]. 없으면 []."""
user=f"""[1] 상가 업종별 본업 인허가 대응 (상가 가게와 인허가를 짝지을 때 '본업'으로 보는 인허가 종류)
{prim}
[2] 인허가에만 있는 가게를 상가 업종으로 옮기는 대응표 (인허가 업태·의료기관종별 → 상가 업종)
{part}
[3] 대안 후보 제외 규칙 (인허가 상태가 폐업·휴업·말소면 대안에서 뺌)
{excl}
참고: 인허가 일반음식점 업태 값 예: 한식, 기타, 식육(숯불구이), 호프/통닭, 경양식, 중국식, 분식, 일식, 통닭(치킨), 정종/대포집/소주방, 횟집, 김밥(도시락), 외국음식전문점(인도,태국등), 까페, 탕류(보신용), 뷔페식, 패스트푸드, 복어취급, 냉면집.
휴게음식점 업태: 커피숍, 기타 휴게음식점, 편의점, 일반조리판매, 다방, 패스트푸드, 아이스크림, 푸드트럭, 전통찻집, 떡카페, 과자점.
'기타 한식 음식점'과 '기타 일식 음식점'은 세부 종류가 불명확해 '확인 필요'로 표시되는 업종입니다."""
r=client.messages.create(model="claude-opus-5-5",max_tokens=6000,system=SYSTEM,messages=[{"role":"user","content":user}])
t="".join(b.text for b in r.content if getattr(b,"type","")=="text").strip()
if t.startswith("```"): t=t.split("\n",1)[1].rsplit("```",1)[0]
out=json.loads(t); json.dump(out,open("data/work/facilities_verify.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
for x in out: print("-",x["where"],"|",x["problem"],"|",x["fix"])
print("지적",len(out))
