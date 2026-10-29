# 지자체 업무 보조 대화 오답 모으기 (언어 모델 비용 없음). 사용: python engine/gov_chat_learn.py
#  실제 대화에서 검사에 걸린 답(자료에 없는 숫자·명사형 종결·하지 않은 일을 했다는 말 등)과 담당자가 '정확하지 않음'으로 표시한 답을
#  점검 문장(gov_chat_eval.json의 '실제 대화에서 모은 문장')에 더함 → gov_chat_eval.py로 다시 돌려 고쳐졌는지 확인 (주민 대화와 같은 방식)
import os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gov_chat_eval.json")
def _rows(p):
    p = os.path.join(ROOT, "data", "gov", p)
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []
ev = json.load(open(EP, encoding="utf-8"))
box = next((c for c in ev["대화"] if c["이름"] == "실제 대화에서 모은 문장"), None)
if box is None: box = {"이름": "실제 대화에서 모은 문장", "turns": []}; ev["대화"].append(box)
have = {t["text"] for c in ev["대화"] for t in c["turns"]}
new = []
for r in _rows("chat_log.jsonl"):
    if r.get("권한") != "담당자" or not r.get("말"): continue
    if r.get("다시검사") or (r.get("검사") and not r.get("다시씀")):
        if r["말"] not in have: new.append({"text": r["말"], "출처": f"검사 {r.get('다시검사') or r.get('검사')} ({r['때'][:10]})"}); have.add(r["말"])
for r in _rows("chat_flags.jsonl"):
    q = str(r.get("질문") or "").strip()
    if len(q) > 1 and q not in have and q != "q": new.append({"text": q, "출처": f"담당자 '정확하지 않음' ({str(r.get('때'))[:10]})", "not_answer": str(r.get("답") or "")[:200]}); have.add(q)
box["turns"] += new
json.dump(ev, open(EP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"새로 모은 문장 {len(new)}개 · 모은 문장 전체 {len(box['turns'])}개")
for t in new: print(" -", t["text"], "·", t["출처"])
