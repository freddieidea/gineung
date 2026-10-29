"""업종(상권업종 소분류) → 세부 기능 연결표 초안 생성 (Claude 분류 + 자동 검사)"""
import json, sys, time, anthropic
MODEL = sys.argv[1] if len(sys.argv) > 1 else "claude-sonnet-5-5"
START = int(sys.argv[2]) if len(sys.argv) > 2 else 0
COUNT = int(sys.argv[3]) if len(sys.argv) > 3 else 25
key = open("settings/anthropic_key.txt", encoding="utf-8").read().strip()
client = anthropic.Anthropic(api_key=key)
tax = json.load(open("design/purpose_taxonomy.json", encoding="utf-8"))
EXPECT = "0.9-draft"
assert tax["version"] == EXPECT, f"분류표 버전 불일치: {tax['version']} (기대 {EXPECT})"
leaves = {l["id"]: l for c in tax["categories"] for p in c["purposes"] for l in p["leaves"]}
func_list = "\n".join(f'{i} | {l["name"]} | {l["desc"]}' for i, l in leaves.items())
inds = json.load(open("data/processed/industry_list.json", encoding="utf-8"))[START:START+COUNT]

SYSTEM = f"""당신은 생활시설의 기능을 분류하는 전문가입니다.
대구 상가 데이터의 업종(소분류)마다, 그 업종의 일반적인 가게가 주민에게 제공하는 '세부 기능'을 아래 목록에서만 골라 연결합니다.

[세부 기능 목록: ID | 이름 | 설명]
{func_list}

규칙
1. 반드시 위 목록에 있는 ID만 사용합니다. 목록에 없는 기능은 만들지 않습니다.
2. 그 업종의 '일반적인' 가게가 실제로 제공하는 기능만 연결합니다. 일부 가게만 하는 기능은 confidence를 "낮음"으로 둡니다.
3. 주된 기능(그 업종의 핵심)은 role을 "주", 곁들여 제공하는 기능은 "부"로 둡니다.
4. 주민의 일상생활과 관련이 없는 업종(예: 부동산 중개, 공학 서비스, 도매업)은 life_facility를 false로 두고 functions는 빈 목록으로 둡니다.
5. 근거(reason)는 한 문장으로, 자연스러운 우리말로 씁니다.
6. 출력은 JSON 배열만 씁니다. 다른 설명은 쓰지 않습니다.
confidence 값은 반드시 "높음", "보통", "낮음" 셋 중 하나만 씁니다 ("중간" 등 다른 말은 쓰지 않음).
형식: [{{"code":"업종코드","life_facility":true,"functions":[{{"id":"P01.1.01","role":"주","confidence":"높음","reason":"..."}}],"note":""}}]"""

payload = [{k: r[k] for k in ["code","대분류","중분류","소분류","표준산업분류","상호예시"]} for r in inds]
t = time.time()
resp = client.messages.create(model=MODEL, max_tokens=16000, system=SYSTEM,
    messages=[{"role": "user", "content": "다음 업종들을 분류해 주세요.\n" + json.dumps(payload, ensure_ascii=False)}])
text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
if text.startswith("```"): text = text.split("\n", 1)[1].rsplit("```", 1)[0]
out = json.loads(text)
# 자동 검사
errs = []
codes_in = [r["code"] for r in inds]; codes_out = [o["code"] for o in out]
if sorted(codes_in) != sorted(codes_out): errs.append(f"업종 누락/추가: 입력 {len(codes_in)}, 출력 {len(codes_out)}, 누락 {set(codes_in)-set(codes_out)}")
for o in out:
    for f in o.get("functions", []):
        if f["id"] not in leaves: errs.append(f'{o["code"]}: 목록 밖 ID {f["id"]}')
        if f.get("role") not in ("주","부"): errs.append(f'{o["code"]}: role 값 오류')
        if f.get("confidence") not in ("높음","보통","낮음"): errs.append(f'{o["code"]}: confidence 값 오류')
    if o.get("life_facility") and not o.get("functions"): errs.append(f'{o["code"]}: 생활시설인데 기능 없음')
    if not o.get("life_facility") and o.get("functions"): errs.append(f'{o["code"]}: 비생활시설인데 기능 있음')
json.dump({"model": MODEL, "start": START, "items": out, "errors": errs},
          open(f"data/processed/industry_map_part_{START:03d}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"{START}~{START+len(inds)-1} 완료 {round(time.time()-t)}초, 오류 {len(errs)}건", errs[:5],
      f"토큰 입력 {resp.usage.input_tokens} 출력 {resp.usage.output_tokens}")
