# 지자체 업무 보조 대화 점검 (언어 모델 실제 호출, 비용 듦). 사용: python engine/gov_chat_eval.py [시작 끝]  (대화 번호 범위)
#  담당자 말투(경어체)·맥락(범위)·도구·확인 카드·답 검사를 한꺼번에 보고, 결과를 data/gov/chat_eval_results.jsonl에 남김
import os, sys, json, re, time, datetime
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline")]
os.environ["USAGE_TAG"] = "업무보조시험"
import gov_agent as GA, gov_chat as GC, gov_docs as D
ROOT = GC.ROOT
EV = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gov_chat_eval.json"), encoding="utf-8"))["대화"]
a0, a1 = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (0, len(EV))
G = GA.GovAgent(); _ = G.cm.engine(); _ = G.cm._C
c = GC.GovChat(G, pre_fn=lambda f: G.pre_review(f))
orig_unsure = G.unsure
res = []; nbad = 0
for ci, conv in enumerate(EV[a0:a1], a0):
    if conv.get("patch"):
        b = D.load(os.path.join(ROOT, conv["patch"])); c.brief = (lambda b=b: b)
        asks = {r["fid"]: r for g in b["구군"].values() for r in g.get("확인요청", [])}; G.unsure = (lambda asks=asks: asks)
    else: c.__dict__.pop("brief", None); G.unsure = orig_unsure
    st = {"role": "담당자"}; scr = dict(conv.get("screen") or {})
    print(f"\n### {ci}. {conv['이름']}")
    for t in conv["turns"]:
        if "screen_gu" in t: scr["gu"] = t["screen_gu"]   # (10/26) 화면에서 구·군을 바꾼 뒤의 요청
        st["calls"] = []; t0 = time.time()
        out = c.reply(st, t["text"], scr, [])
        for b_ in out["blocks"]:
            if b_.get("kind") == "screen" and "gu" in b_: scr["gu"] = b_["gu"]
        m = out["_meta"]; calls = st.get("calls", []); names = [x[0] for x in calls]
        txt = " ".join(b_["text"] for b_ in out["blocks"] if not b_.get("kind")); cards = [b_["title"] for b_ in out["blocks"] if b_.get("kind") == "action"]
        prob = []
        if m.get("bad2"): prob.append(f"검사 실패({m.get('bad2')})")   # 고쳐 쓰기·문장 덜기로 풀린 것(repaired·trimmed)은 통과, 용어만 남은 것(soft)은 경고만
        if re.search(r"(임|함|됨|음)[.]?(\s|$)", txt) and any(re.search(r"(임|함|됨|음)[.]?$", x.strip()) and len(x.strip()) > 12 for x in re.split(r"(?<=[.!?])\s+", txt)): prob.append("명사형 종결")
        if t.get("gu") and calls and not any(x[1].get("gu") == t["gu"] for x in calls if x[0] not in ("criteria", "propose_action", "show_on_screen", "pre_review", "facility_detail")): prob.append(f"범위 {t['gu']} 아님: {[x[1].get('gu') for x in calls]}")
        if t.get("gu_none") and any(x[1].get("gu") for x in calls if x[0] not in ("criteria", "propose_action", "show_on_screen", "facility_detail")): prob.append(f"대구 전체인데 범위가 남음: {[x[1].get('gu') for x in calls]}")
        if re.search(r"준필수|필수·준필수|등급(이|은|을)? ?필수|생활 필수 등급", txt): prob.append("내부 분류 용어 노출")
        if t.get("dong") and not any(t["dong"] in str(x[1].get("dong") or "") for x in calls): prob.append(f"동 {t['dong']} 없음")
        if t.get("tools") and not set(t["tools"]) & set(names): prob.append(f"도구 {t['tools']} 안 씀: {names}")
        if t.get("no_tools") and set(t["no_tools"]) & set(names): prob.append(f"쓰면 안 되는 도구: {set(t['no_tools']) & set(names)}")
        for k_ in (t.get("args") or {}):
            if not any(x[1].get(k_) for x in calls): prob.append(f"인자 {k_} 안 씀")
        if re.search(r"fid|[SPL]:[A-Za-z0-9]|_overview|_areas|_signals|_review|_candidates|_effect|propose_|make_doc|show_on", txt): prob.append("내부 식별자·도구 이름 노출")
        if re.search(r"(요약|문서|보고서|엑셀|PDF)[^.]{0,20}(정리|작성|만들|적|담)[가-힣]*(었|았|했)", txt) and "make_document" not in names: prob.append("문서 안 만들고 만들었다고 함")
        jar = [w for w in ("공백 심각도", "기능 공백 구역", "상시 부재", "판정 대상", "단절 우려", "도보권 미충족", "검토 완료", "기준 거리", "폐업 영향") if w in txt]
        if len(jar) >= 3: prob.append(f"서비스 용어 과다 {jar}")
        if t.get("card") and t["card"] not in cards: prob.append(f"카드 {t['card']} 없음: {cards}")
        for w in t.get("not", []):
            if w in txt: prob.append(f"'{w}' 나옴")
        for w in t.get("has", []):
            if not re.search(w, txt): prob.append(f"'{w}' 없음")
        nbad += bool(prob)
        print(f"{'✗' if prob else '○'} [{time.time()-t0:.0f}s {m['model']}{'↑' if m['esc'] else ''}] {t['text']}\n   도구 {[(x[0], {k: v for k, v in x[1].items() if k in ('gu', 'dong', 'status', 'kind', 'action', 'function_id', 'keyword', 'section', 'confirmed_since', 'public_only') or (k in ('fid',) and v) or (k == 'fids' and v)}) for x in calls]}\n   답: {txt[:260]}" + (f"\n   문제: {prob}" if prob else ""))
        res.append({"때": datetime.datetime.now().isoformat(timespec="seconds"), "대화": conv["이름"], "말": t["text"], "도구": calls, "답": txt, "모델": m["model"], "다시씀": m["esc"], "문제": prob})
with open(os.path.join(ROOT, "data", "gov", "chat_eval_results.jsonl"), "a", encoding="utf-8") as fh:
    for r in res: fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
print(f"\n문제 있는 마디 {nbad} / {len(res)}")
