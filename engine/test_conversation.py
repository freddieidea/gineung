# 대화 흐름 검사 (언어 모델 없이 넓히기·자격·걸음 단계를 검사하고, 마지막에 실제 대화 2개)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recommend import Engine
from conversation import Conversation
E = Engine(); C = Conversation(E); C.D.log_path = None; fails = []  # 시험 대화는 지자체 기록에 남기지 않음
def check(n, c):
    print(("통과 " if c else "실패 ") + n); (None if c else fails.append(n))
PART = sys.argv[1] if len(sys.argv) > 1 else "ab"   # 시간 제한 때문에 나눠 돌릴 수 있음: a(1~5) / b(6~8)
if "a" in PART:
  # 1) 군위군 한가운데서 방문간호 → 걸어갈 곳 없음 → 같은 묶음 없음 → 다른 묶음(재택의료센터·보건소 방문건강관리) 제안
  st = C.start(128.62, 36.24, gu="군위군"); st.update(leaf="P04.1.05", kind="방문간호 기관", stage="speed")
  r = C.turn(st, "천천히 걸어요"); check("걸음 '천천히' 인식", st["speed"] == "천천히")
  check("방문간호 → 이용 자격(장기요양 등급) 질문", r["type"] == "question" and "장기요양" in r["text"])
  r = C.turn(st, "네, 해당돼요"); print("  ", r["text"][:120])
  check("군위군: 걸어갈 방문간호 기관 없음 → 다른 종류(재택의료센터 등)로 넓힐지 묻기", r["type"] == "question" and "재택의료센터" in r["text"])
  r = C.turn(st, "아니요"); check("거절하면 넓히지 않고 결과 + 공백 기록", r["type"] == "result" and st.get("gap") and all(c["세부종류"] == "방문간호 기관" for c in r["result"]["추천"]))
  # 2) 도심 해물찜 → 바로 결과, 모든 카드가 해산물 구이·찜
  st = C.start(128.5935, 35.8714, gu="중구"); st.update(leaf="P01.1.05", kind="해산물 구이·찜", stage="speed")
  r = C.turn(st, "보통으로 걸어요"); print("  ", r["text"][:300].replace("\n", " / "))
  check("도심 해물찜 → 결과 3곳, 모두 해산물 구이·찜, 걷는 시간 표시", r["type"] == "result" and len(r["result"]["추천"]) == 3 and all(c["업종"] == "해산물 구이/찜" for c in r["result"]["추천"]) and "걸어서 약" in r["text"])
  check("문장 속 시설 이름은 모두 엔진 결과에 있는 이름", all(c["상호"] in r["text"] for c in r["result"]["추천"]))
  # 3) 경로당: 자격 '아니요' → 추천 목록에 넣지 않고 자격 목록으로
  st = C.start(128.60, 35.87, gu="중구"); st.update(leaf="P11.1.03", kind="경로당", stage="speed")
  r = C.turn(st, "보통"); r = C.turn(st, "아니요")
  check("경로당 자격 '아니요' → 추천에 경로당 없음", r["type"] in ("result", "question") and (r["type"] == "question" or not r["result"]["추천"]))
  # 4) 실제 대화 (언어 모델)
  fid = E.F[(E.F["업종"] == "헬스장") & (E.F["대안후보"] == "아니요")].index[0]; f = E.F.loc[fid]
  st = C.start(float(f["x"]), float(f["y"]), gu=f["구군"], closed_fid=fid); print("  안내:", st["opening"])
  r = C.turn(st, "운동하러 다녔어요. 무릎이 안 좋아서 천천히 걸어요"); print("  ", r.get("text", "")[:300].replace("\n", " / "))
  check("헬스장 실제 대화 → 헬스장만 추천", r["type"] == "result" and all(c["세부종류"] == "헬스장" for c in r["result"]["추천"]) or r["type"] == "question")
  # 5) 메뉴 단서: 쭈꾸미집이 닫음 → 상호에 쭈꾸미(주꾸미)가 들어간 해산물 구이·찜집이 앞으로
  fid = [f for f in E.F[(E.F["업종"] == "해산물 구이/찜")].index if "쭈꾸미" in E.F.loc[f, "상호"]][0]; f = E.F.loc[fid]
  st = C.start(float(f["x"]), float(f["y"]), gu=f["구군"], closed_fid=fid)
  r = C.turn(st, "여기 대신 갈 데 찾아요"); 
  if r["type"] == "question": r = C.turn(st, "보통으로 걸어요")
  print("  ", st.get("menu_words"), r.get("text", "")[:400].replace("\n", " / "))
  check("쭈꾸미집 → 메뉴 단서 '쭈꾸미' 인식, 해산물 구이·찜만, 단서 표시는 상호 사실만", r["type"] == "result" and any("쭈꾸미" in w or "주꾸미" in w for w in st.get("menu_words", []))
        and all(c["세부종류"] == "해산물 구이·찜" for c in r["result"]["추천"]) and all(any(("가게 이름에" in m) or m == "찾으시는 메뉴가 있는지" for m in c["표시"]) for c in r["result"]["추천"]))
if "b" in PART:
  # 6) 세부 의도: 배달·포장에 따라 대안이 갈리는 종류만 묻고, 답에 따라 판정 (헌준님 판단: 포장이 기본인 종류만 포장을 종류로 판정)
  st = C.start(128.5935, 35.8714, gu="중구"); st.update(leaf="P01.1.06", kind="김밥·만두·분식", stage="speed")
  r = C.turn(st, "보통")
  check("분식집 배달·포장 → 포장인지 배달인지 묻기", r["type"] == "question" and "배달" in r["text"] and "포장" in r["text"])
  r = C.turn(st, "집으로 배달받고 싶어요")
  check("'집으로 배달받고 싶어요' → 의도 '배달'로 인식", st.get("need") == "배달")
  check("배달 + 분식집 → 근거 없는 분식집을 추천으로 내지 않음 (넓힐지 묻거나 확인 필요로만)",
        (r["type"] == "question") or not any(c["세부종류"] == "김밥·만두·분식" for c in r["result"]["추천"]))
  st = C.start(128.5935, 35.8714, gu="중구"); st.update(leaf="P01.1.06", kind="중국집", stage="speed")
  r = C.turn(st, "보통")
  check("중국집 → 포장·배달 모두 하는 종류라 묻지 않고 바로 결과", r["type"] == "result" and r["result"]["추천"] and "need" not in st)
  st = C.start(128.5935, 35.8714, gu="중구"); st.update(leaf="P01.1.06", kind="김밥·만두·분식", stage="speed")
  C.turn(st, "보통"); r = C.turn(st, "가서 포장해 올게요")
  check("포장 + 분식집 → 추천 결과", st.get("need") == "포장" and r["type"] == "result" and r["result"]["추천"])
  st = C.start(128.5935, 35.8714, gu="중구"); st.update(leaf="P01.1.06", kind="백반·한정식", stage="speed")
  r = C.turn(st, "보통")
  check("백반집 → 포장·배달 모두 가게마다 달라 근거 없는 백반집을 추천으로 내지 않음", r["type"] == "question" or not any(c["세부종류"] == "백반·한정식" for c in r["result"]["추천"]))
  # 7) 근거가 있는 대안이 있으면 '하는지 확인 필요' 목록은 답에 나오지 않음, 근거 문장은 카드에 나옴
  st = C.start(128.60, 35.87, gu="중구"); st.update(leaf="P03.1.03", kind="물리치료실 있는 의원", stage="speed")
  r = C.turn(st, "보통")
  check("물리치료 → 근거 문장이 답에 나옴, 확인 필요 목록 없음", r["type"] == "result" and "근거:" in r["text"] and "확인이 필요한 곳" not in r["text"])
  print("  ", r["text"][:300].replace("\n", " / "))
  # 8) 금융: 은행은 카카오맵 실시간 검색(저장 안 함) + 우체국(데이터베이스), 걷는 거리 순
  st = C.start(128.5935, 35.8714, gu="중구"); st.update(leaf="P05.1.01", kind=None, stage="speed")
  r = C.turn(st, "보통")
  cs = r["result"]["추천"] if r["type"] == "result" else []
  check("현금 입출금 → 은행(실시간) 추천, 걷는 거리 순, 실시간 안내 문장", bool(cs) and any(c.get("실시간") for c in cs) and "카카오맵에서 지금 찾은" in r["text"]
        and [c["걷는거리_m"] for c in cs if c["걷는거리_m"] is not None] == sorted(c["걷는거리_m"] for c in cs if c["걷는거리_m"] is not None))
  check("현금 입출금 → 우편취급국은 나오지 않음", not any("취급국" in c["상호"] for c in cs))
  print("  ", r.get("text", "")[:300].replace("\n", " / "))
  st = C.start(128.5935, 35.8714, gu="중구"); st.update(leaf="P05.1.03", kind=[k for (l, k) in E.kind if l == "P05.1.03"][0], stage="speed", history=[{"role": "user", "text": "농협 통장 재발급하려고요"}])
  r = C.turn(st, "보통"); cs = r["result"]["추천"] if r["type"] == "result" else []
  check("창구 업무 + '농협' → ATM 없이 농협 창구만(실시간 카드)", all(("농협" in c["상호"] and "ATM" not in c["업종"]) for c in cs if c.get("실시간")) and any(c.get("실시간") for c in cs))
print("실패", len(fails)); sys.exit(1 if fails else 0)
