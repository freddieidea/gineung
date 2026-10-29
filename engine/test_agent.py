# 대화 모델 자유 답변 검사 (실제 언어 모델·카카오·인터넷 검색을 씀, 비용 조금 듦). 사용: python engine/test_agent.py
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
from recommend import Engine
from conversation import Conversation, CLOSURES
from agent import PHONE
E = Engine(); C = Conversation(E); fails = []
def check(n, c):
    print(("통과 " if c else "실패 ") + n); (None if c else fails.append(n))
def show(r): print("   →", (r.get("text") or "")[:500].replace("\n", " / "), "| 출처:", [l["url"][:60] for l in r.get("출처", [])])
def phones_ok(st, r):
    known = set()
    for c in (st.get("last_result") or {}).get("순위", []) + (st.get("last_result") or {}).get("확인필요후보", []): known |= set(PHONE.findall(str(c.get("전화"))))
    return all(p in known for p in PHONE.findall(r.get("text", ""))) or "kakao" in json.dumps(r, ensure_ascii=False)
def turn(st, t):
    st.setdefault("history", []).append({"role": "user", "text": t}); return C.turn(st, t)

# 1) 미용실: 첫마디 확인 → 걸음 질문 → 결과 → 자유 물음
fid = "S:MA010120220808605214"; r0 = E.F.loc[fid]
st = C.start(float(r0["경도"]), float(r0["위도"]), gu=r0["구군"], closed_fid=fid); st["origin_name"] = r0["상호"]
print("  첫마디:", st["opening"], st.get("opening_options"))
check("하던 일이 하나로 분명하면 확인만 (어떤 일로 다니셨는지 묻지 않음)", st["stage"] == "confirm" and "미용실" in st["opening"] and "어떤 일로" not in st["opening"])
r = turn(st, "네, 찾아 주세요"); print("  ", r["text"], r.get("options"))
check("확인하면 이동 수단을 '미용실까지는'으로 물음", r["type"] == "question" and r["text"].startswith("미용실까지는"))
r = turn(st, "거기 몇 시까지 해요?"); show(r)
check("질문 중에 끼어든 물음 → 답하고 하던 질문을 다시 여쭘", r["type"] == "question" and r.get("agent") and "미용실까지는" in r["text"] and st["stage"] == "mode")
r = turn(st, "걸어서 가요"); print("  ", r["text"], r.get("options"))
check("걸음 질문은 '걸어서 얼마나'", "얼마나" in r["text"] and "걸음은" not in r["text"])
r = turn(st, "10분 안쪽이 좋아요"); print("  ", r["text"][:300].replace("\n", " / "))
check("10분 안쪽 → 최대 10분, 기준을 밝힘", r["type"] == "result" and st["cond"].get("max_min") == 10 and "10분 안에서" in r["text"])
r = turn(st, "1순위 미용실은 파마 얼마 정도 해요?"); show(r)
check("가격 물음 → 지어내지 않고(번호 검사) 답함", r.get("agent") and phones_ok(st, r))
r = turn(st, "평 좋은 데는 어디예요?"); print("  ", r["text"][:260].replace("\n", " / "))
check("'평 좋은 데' → 별점 대신 블로그 글이 많은 순으로 다시 찾음 (엔진, 갈 수 있는 곳 안에서)", r["type"] in ("result", "question") and st["cond"].get("sort") == "블로그" and "블로그" in r["text"])
r = turn(st, "1순위 후기는 어때요?"); show(r)
bl = [b for b in r.get("blocks", []) if b.get("blog")]
check("후기 물음 → 블로그 글 목록을 화면에 보여 주고, 대화 모델은 내용을 짐작해 말하지 않음", r.get("agent") and bl and not re.search(r"맛있|친절|좋다는|칭찬|불만", r["text"]))
r = turn(st, "버스로 가면요?"); print("  ", r["text"][:200].replace("\n", " / "))
check("조건 바꾸기는 엔진으로 다시 찾음", r["type"] in ("result", "question") and st["cond"]["mode"] == "버스·지하철")

# 2) 빵집: 무슨 빵 파는지
bak = [k for k, v in CLOSURES.items() if v["업종"] == "빵/도넛" and k in E.F.index]
fid = bak[0]; r0 = E.F.loc[fid]
st = C.start(float(r0["경도"]), float(r0["위도"]), gu=r0["구군"], closed_fid=fid); st["origin_name"] = r0["상호"]
print("  첫마디:", st["opening"])
r = turn(st, "네, 찾아 주세요")
if st["stage"] == "mode": r = turn(st, "걸어서 가요")
if st["stage"] == "speed": r = turn(st, "20분쯤은 괜찮아요")
print("  ", r["text"][:300].replace("\n", " / "))
r = turn(st, "1순위 빵집은 무슨 빵 팔아요?"); show(r)
check("메뉴 물음 → 인터넷 글이면 출처를 붙이고, 못 찾으면 못 찾았다고", r.get("agent") and (r.get("출처") or re.search(r"못 찾|찾지 못|확인하기 어려|전화", r["text"])))
check("자료에 없는 전화번호를 쓰지 않음", phones_ok(st, r))
print("실패", len(fails)); sys.exit(1 if fails else 0)
