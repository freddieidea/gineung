# 생활 기능의 성격을 AI가 정리 (지자체 판단 에이전트가 씀, engine/gap_agent.py) — 크레딧이 드는 작업 (약 70개 기능, Sonnet 4번 안팎)
#  기능마다: 못 받으면 얼마나 빨리 위험해지는지(분·시간·일·주·달), 생명과 바로 이어지는지, 배달·방문·교통 같은 다른 방법으로 대신할 수 있는지(0~1), 특히 영향을 받는 사람
#  결과: design/function_profiles.json — 담당자·헌준님이 직접 고칠 수 있음('만든이'를 '담당자'로 바꾸면 다시 돌려도 덮어쓰지 않음)
#  쓰는 법: python pipeline/build_function_profiles.py
import os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(ROOT, "engine"))
import anthropic, public_basis as PB
T = json.load(open(os.path.join(ROOT, "design", "purpose_taxonomy.json"), encoding="utf-8"))
P = os.path.join(ROOT, "design", "function_profiles.json")
old = json.load(open(P, encoding="utf-8")) if os.path.exists(P) else {}
leaves = [(l["id"], l["name"], c["name"], l.get("grade"), str(l.get("public_basis") or "")[:120], l.get("modes", []))
          for c in T["categories"] for q in c["purposes"] for l in q["leaves"]]
leaves += [("G:분만", "분만", "건강", "필수", "모자보건법", []), ("G:신생아중환자", "신생아·소아 중환자 진료", "건강", "필수", "의료법", []), ("G:중환자", "중환자 진료", "건강", "필수", "의료법", [])]
# 이어서 하기: 이미 정리한 기능은 건너뜀 (다시 정리하려면 --redo). 한 번 실행에 140초까지만 하고 저장 → 다시 실행하면 이어서 함
import time; T0 = time.time()
todo = [x for x in leaves if (old.get(x[0]) or {}).get("만든이") not in (("담당자",) if "--redo" in sys.argv else ("담당자", "AI"))]
print("남은 기능", len(todo))
TOOL = {"name": "profiles", "description": "기능마다 성격", "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "시간민감도": {"type": "string", "enum": ["분", "시간", "일", "주", "달"], "description": "이 일을 못 받게 되면 얼마 안에 생명·건강·생활에 큰 해가 생기는지"},
    "생명직결": {"type": "boolean", "description": "몇 시간 안에 받지 못하면 생명이 위험하거나 되돌릴 수 없는 피해가 나는지"},
    "대신하는_방법": {"type": "array", "items": {"type": "string"}, "description": "가게·시설에 가지 않고 할 수 있는 실제 방법 (배달, 방문 서비스, 택시·버스로 먼 곳 이용 등)"},
    "대신_정도": {"type": "number", "description": "그 방법들로 얼마나 대신할 수 있는지 0~1 (어르신 기준)"},
    "취약계층": {"type": "array", "items": {"type": "string"}}, "근거": {"type": "string", "description": "한두 문장"}},
    "required": ["id", "시간민감도", "생명직결", "대신_정도", "근거"]}}}, "required": ["items"]}}
SYS = ("당신은 지자체 생활 서비스 정책 전문가입니다. 생활 기능 목록을 받아 기능마다 성격을 판단합니다. 대구(대도시와 농촌이 함께 있음)의 주민, 특히 어르신을 기준으로 현실에 맞게 판단합니다. "
       "응급 진료·분만처럼 시간이 생명인 일과, 외식·카페처럼 없어도 생활이 이어지는 일을 분명히 구분합니다. 결과는 profiles 도구로만.")
cl = anthropic.Anthropic(api_key=open(os.path.join(ROOT, "settings", "anthropic_key.txt"), encoding="utf-8").read().strip())
out = dict(old)
for i in range(0, len(todo), 12):
    if time.time() - T0 > 110: print("시간이 다 되어 멈춤 — 다시 실행하면 이어서 함"); break
    part = todo[i:i + 12]
    msg = "\n".join(f"{lid} | {nm} | 분야 {cat} | 분류표 등급 {g} | 공공 근거 {pb or '-'} | 이용 방법 {', '.join(m) or '-'}" for lid, nm, cat, g, pb, m in part)
    res = None
    for _ in range(3):   # 이 모델은 도구를 강제로 부르게 할 수 없어, 부르지 않으면 다시 요청
        r = cl.messages.create(model="claude-sonnet-5-5", max_tokens=8000, system=SYS + " 반드시 profiles 도구를 부릅니다.", tools=[TOOL], messages=[{"role": "user", "content": msg}])
        res = next((b.input for b in r.content if b.type == "tool_use"), None)
        if res: break
    if not res: sys.exit("도구를 부르지 않음")
    names = {lid: nm for lid, nm, *_ in part}
    for x in res["items"]:
        if x["id"] in names: out[x["id"]] = dict(x, 이름=names[x["id"]], 만든이="AI")
    json.dump(out, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    try:
        from chat import log_usage; log_usage("claude-sonnet-5-5", r.usage, "기능 성격 정리")
    except Exception: pass
    print(f"{i + len(part)}/{len(todo)}")
json.dump(out, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("저장:", P, len(out), "개")
