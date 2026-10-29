# 지자체 업무 보조 대화 학습·검증 (언어 모델 비용 듦). 사용: python engine/gov_chat_train.py 시작 끝
#  gov_chat_gen.py가 만든 담당자 대화(data/gov/chat_train.jsonl)를 실제 에이전트로 돌리고, 독립 채점관(Sonnet)이 마디마다 채점
#  채점: 의도 파악 · 맥락 · 정확성(도구 결과와 일치, 지어냄 없음) · 쉬운 말·구체성 · 할 일 안내 → 문제 유형을 모아 고칠 곳을 찾음
import os, sys, json, re, time, datetime
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline")]
os.environ["USAGE_TAG"] = "업무보조시험"
import anthropic, gov_agent as GA, gov_chat as GC
from chat import log_usage, SONNET
ROOT = GC.ROOT
P = os.path.join(ROOT, "data", "gov", "chat_train.jsonl")
CONVS = [json.loads(l) for l in open(P, encoding="utf-8") if l.strip()]
a0, a1 = int(sys.argv[1]), int(sys.argv[2])
G = GA.GovAgent(); _ = G.cm.engine(); _ = G.cm._C
c = GC.GovChat(G, pre_fn=lambda f: G.pre_review(f))
J = """당신은 지자체 업무 보조 AI의 답을 독립적으로 채점하는 검토관입니다. 담당 공무원이 이 답을 보고 바로 이해하고 일할 수 있는지가 기준입니다.
각 마디에 대해 아래를 채점하십시오 (0=나쁨, 1=보통, 2=좋음; 할일은 0/1).
- 의도: 담당자가 원한 업무를 정확히 알아듣고 맞는 일을 했는가 (대상이 없으면 되물었는가, 거짓 전제(없는 시설·잘못된 위치)를 바로잡았는가)
- 맥락: 앞 마디의 지역·시설·자료를 이어받았는가 (첫 마디면 2)
- 정확: 답의 숫자·시설·사실이 [도구 결과]나 [에이전트가 받은 화면·보고 정보]와 맞는가, 지어내거나 과장하지 않았는가, 하지 않은 일을 했다고 하지 않았는가
- 쉬움: 서비스 내부 용어 없이(또는 뜻을 붙여) 담당자가 한 번에 이해하는가, 개괄적이지 않고 구체적(어디·몇 명·얼마나)인가, 경어체인가
- 할일: 담당자가 다음에 할 일·연락할 곳·이어서 할 수 있는 것을 알려 주었는가 (필요 없는 마디면 1)
[에이전트가 실제로 할 수 있는 일 — 이 밖의 기능은 없음] 오늘의 보고·지역 현황·시설 찾기·시설 판단 근거·기능 공백 구역·주민 상담 기반 수요(주민 모드 상담 자동 집계) 조회, 폐업 사전 검토·입지 후보·개설 효과 계산, 걸어서 가기 어려운 동네 계산, 소관 업무·관할 기관·법령 근거 안내, 기준 설명, 기본 화면 옮기기, 확인 카드(폐업·휴원·운영 중 반영: 폐업 확인 필요 시설만 / 판단 바로잡기: 판정된 폐업 시설만 / 처리 완료: 조치 필요 항목만 / 판단 원칙 추가 / 다시 점검), 문서(보고서 PDF·요약·엑셀·대화 요약). 매일 오전 8시 30분 자동 점검으로 보고를 다시 계산합니다(폐업 확정·공백 해소 반영). 이 기능을 할 수 있다고 안내하는 것은 과장이 아닙니다. 폐업일(문 닫은 날)과 확정일(자료로 폐업이 확인된 날)은 다릅니다.
문제 태그(해당하는 것만): 의도오해, 되묻기필요, 불필요한되묻기, 맥락놓침, 범위오류, 지어냄, 거짓전제수용, 기능부족, 용어과다, 개괄적, 장황, 반말·명사형, 할일없음, 업무밖처리미흡
출력: JSON 배열만. 원소 {"마디": 번호, "의도": n, "맥락": n, "정확": n, "쉬움": n, "할일": n, "태그": [...], "이유": "한 문장", "고칠점": "에이전트가 어떻게 했어야 하는지 한 문장"}"""
jc = anthropic.Anthropic(api_key=open(os.path.join(ROOT, "settings", "anthropic_key.txt"), encoding="utf-8").read().strip())
out = []
for ci in range(a0, min(a1, len(CONVS))):
    cv = CONVS[ci]; st = {"role": "담당자", "trace_on": True}; turns = []
    for t in cv["turns"]:
        st["trace"] = []; st["calls"] = []; t0 = time.time()
        try: o = c.reply(st, t, {}, [])
        except Exception as ex: o = {"blocks": [{"text": f"(오류 {ex})"}], "_meta": {"model": "?", "esc": False}}
        txt = " ".join(b_["text"] for b_ in o["blocks"] if not b_.get("kind"))
        kinds = [b_.get("kind") + (":" + str(b_.get("title") or "")[:30] if b_.get("title") else "") for b_ in o["blocks"] if b_.get("kind")]
        turns.append({"앞정보": st.get("_lead", "")[:900], "말": t, "답": txt, "화면": kinds, "도구": st.get("trace", []), "모델": o["_meta"].get("model"), "다시씀": o["_meta"].get("esc"), "검사": {k: v for k, v in o["_meta"].items() if k in ("bad", "bad2", "repaired", "trimmed")}, "초": round(time.time() - t0)})
    view = "\n\n".join(f"[마디 {i + 1}] [에이전트가 받은 화면·보고 정보] {x.get('앞정보', '')}\n담당자: {x['말']}\n[도구 결과] " + " | ".join(f"{n}({json.dumps({k: v for k, v in a_.items() if k != 'fids'}, ensure_ascii=False)}) → {r_[:1800]}" for n, a_, r_ in x["도구"]) +
                       f"\n[화면에 그린 것] {x['화면']}\n[AI 답] {x['답']}" for i, x in enumerate(turns))
    try:
        TOOL = {"name": "scores", "description": "마디별 채점", "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
            "turn": {"type": "integer"}, "intent": {"type": "integer"}, "context": {"type": "integer"}, "accuracy": {"type": "integer"}, "clarity": {"type": "integer"}, "action": {"type": "integer"},
            "tags": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}, "fix": {"type": "string"}}, "required": ["turn", "intent", "context", "accuracy", "clarity", "action", "tags", "reason", "fix"]}}}, "required": ["items"]}}
        r = jc.messages.create(model=SONNET, max_tokens=3000, system=J + "\n(반드시 scores 도구를 한 번 호출해 출력: intent=의도, context=맥락, accuracy=정확, clarity=쉬움, action=할일, tags=태그, reason=이유, fix=고칠점)", tools=[TOOL],
                               messages=[{"role": "user", "content": f"의도: {cv.get('의도')} / 말투: {cv.get('말투')}\n\n{view}"}])
        log_usage(SONNET, r.usage, "업무보조시험")
        u = next(x for x in r.content if getattr(x, "type", "") == "tool_use")
        sc = [{"마디": y["turn"], "의도": y["intent"], "맥락": y["context"], "정확": y["accuracy"], "쉬움": y["clarity"], "할일": y["action"], "태그": y["tags"], "이유": y["reason"], "고칠점": y["fix"]} for y in u.input.get("items", [])]
    except Exception as ex: sc = []; print("채점 오류", ex)
    for i, x in enumerate(turns):
        s_ = next((y for y in sc if y.get("마디") == i + 1), {})
        x.update(채점=s_)
        tot = sum(s_.get(k, 0) for k in ("의도", "맥락", "정확", "쉬움", "할일"))
        print(f"{'✗' if tot < 8 or s_.get('정확', 2) < 2 or s_.get('의도', 2) < 2 else '○'} [{ci}-{i + 1} {tot}/9 {x['모델']} {x.get('검사') or ''}] {x['말'][:60]}\n    답: {x['답'][:200]}\n    도구: {[d[0] for d in x['도구']]} 태그: {s_.get('태그')} · {s_.get('이유', '')[:120]}\n    고칠점: {s_.get('고칠점', '')[:150]}")
    out.append({"때": datetime.datetime.now().isoformat(timespec="seconds"), "번호": ci, "의도": cv.get("의도"), "말투": cv.get("말투"), "마디": turns})
with open(os.path.join(ROOT, "data", "gov", "chat_train_results.jsonl"), "a", encoding="utf-8") as fh:
    for r_ in out: fh.write(json.dumps(r_, ensure_ascii=False, default=str) + "\n")
