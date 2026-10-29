# 상황(데이트·아이와 등)과 '주민이 콕 집은 종류' 검사 (언어 모델 없이 찾기 도구만 바로 부름, 비용 없음): python engine/test_occasion.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
from recommend import Engine
from conversation import Conversation, CLOSURES
from chat import Chat
import occasions as O
E = Engine(); C = Conversation(E); H = Chat(C); fail = 0
def ok(cond, msg):
    global fail
    print(("  통과 " if cond else "  실패 ") + msg); fail += 0 if cond else 1
def run(fid, args, text=""):
    r = E.F.loc[fid]
    st = C.start(float(r["경도"]), float(r["위도"]), gu=r["구군"], closed_fid=fid)
    st.update(stage="chat", msgs=[], turns=0, shown_names=set(), origin_closed=True, origin_name=r["상호"], user_text=text)
    h = O.detect(text)
    if h: st["occ_hint"] = h
    facts, cards = H._find(st, args)
    return st, facts, [c for c in st["last_result"]["순위"]]
BAD_DATE = {u for u, t in O.TABLE["데이트"].items() if t == O.BAD}
gukbap = next(f for f, c in CLOSURES.items() if c["업종"] == "국/탕/찌개류")
print("1) 국밥집이 문 닫음 + '여자친구랑 저녁 먹을 데' → 국밥집은 연인과 잘 안 맞으니 데이트에 어울리는 곳을 먼저, 국밥집은 버튼으로")
st, facts, rk = run(gukbap, {"leaf_id": "P01.1.05", "kind": "국·탕·찌개"}, "여자친구랑 저녁 먹을 데")
ok(rk and not [c for c in rk if c.get("업종") in BAD_DATE], "결과: " + ", ".join(f"{c['상호']}({c.get('업종')})" for c in rk))
ok(any("국·탕·찌개으로 볼래요" in m and "없다고 하지 말 것" in m for m in facts.get("메모", [])), "국밥집으로 돌아가는 버튼을 권함 (국밥집이 없다고 하지 않게)")
print("1-2) 고깃집이 문 닫음 + '여자친구랑 저녁 먹을 데' → 고깃집은 연인과도 무난하니 그대로")
pork = next(f for f, c in CLOSURES.items() if c["업종"] == "돼지고기 구이/찜")
st, facts, rk = run(pork, {"leaf_id": "P01.1.05", "kind": "돼지고기 구이·찜"}, "여자친구랑 저녁 먹을 데")
ok(rk and all(c.get("업종") == "돼지고기 구이/찜" for c in rk), "결과: " + ", ".join(f"{c['상호']}({c.get('업종')})" for c in rk))
print("1-2b) 경양식집이 문 닫음 + '부모님 모시고 갈 만한 데' → 부모님께 어울리는 곳 + 경양식(무난)도 함께, 안 어울리는 곳 없음")
st, facts, rk = run(next(f for f, c in CLOSURES.items() if c["상호"] == "돈까스식당"), {"leaf_id": "P01.1.05", "kind": "경양식"}, "부모님 모시고 갈 만한 데")
BAD_PAR = {u for u, t in O.TABLE["어르신 모시고"].items() if t == O.BAD}
ok(rk and not [c for c in rk if c.get("업종") in BAD_PAR], "결과: " + ", ".join(f"{c['상호']}({c.get('업종')})" for c in rk))
print("1-2c) 국밥집이 문 닫음 + '친구랑 밥 먹을 데' → 친구와는 국밥도 무난하니 그대로")
st, facts, rk = run(gukbap, {"leaf_id": "P01.1.05", "kind": "국·탕·찌개"}, "친구랑 밥 먹을 데")
ok(rk and all(c.get("업종") == "국/탕/찌개류" for c in rk), "결과: " + ", ".join(f"{c['상호']}({c.get('업종')})" for c in rk))
for text in ["여자친구랑 분위기 좋은 데 가고 싶어", "데이트할 곳 찾아줘"]:
    print(f"1-3) 국밥집이 문 닫음 + '{text}' (상황에 맞는 곳을 원함이 분명) → 데이트에 어울리는 종류")
    st, facts, rk = run(gukbap, {"leaf_id": "P01.1.05", "kind": "국·탕·찌개"}, text)
    ok(st.get("occasion") == "데이트" and rk and not [c for c in rk if c.get("업종") in BAD_DATE], "결과: " + ", ".join(f"{c['상호']}({c.get('업종')})" for c in rk))
print("1-4) 경양식집이 문 닫음 + '여자친구랑 국밥 먹을 데' → 국밥 (주민이 고른 메뉴가 먼저)")
st, facts, rk = run("S:MA0101202308A0024206", {"leaf_id": "P01.1.05", "kind": "국·탕·찌개", "menu_words": ["국밥"]}, "여자친구랑 국밥 먹을 데")
ok(rk and all(c.get("업종") == "국/탕/찌개류" for c in rk) and not st.get("occasion"), "결과: " + ", ".join(f"{c['상호']}({c.get('업종')})" for c in rk))
print("1-5) 술집이 문 닫음 + '애들 데리고 밥 먹을 데' → 아이와 술집은 어려우니 아이와 가기 좋은 종류로")
st, facts, rk = run(next(f for f, c in CLOSURES.items() if c["업종"] == "요리 주점"), {"leaf_id": "P01.1.05", "kind": "요리 주점"}, "애들 데리고 밥 먹을 데")
ok(rk and not [c for c in rk if c.get("업종") in ("요리 주점", "생맥주 전문")], "결과: " + ", ".join(f"{c['상호']}({c.get('업종')})" for c in rk))
print("2) 경양식집이 문 닫음 + '데이트하려는데 괜찮은 데' (가까운 경양식이 1곳뿐) → 가까운 경양식 + 데이트에 어울리는 다른 종류")
st, facts, rk = run("S:MA0101202308A0024206", {"leaf_id": "P01.1.05", "kind": "경양식"}, "데이트하려는데 괜찮은 데")
ok(rk and rk[0].get("업종") == "경양식" and all((c.get("걷는시간_분") or 99) <= 20 for c in rk), "결과: " + ", ".join(f"{c['상호']}({c.get('업종')}, {c.get('걷는시간_분')}분)" for c in rk))
ok(not [c for c in rk if c.get("업종") in BAD_DATE], "어울리지 않는 종류 없음")
print("3) 아무 종류나(any_kind)라고 해도 주민이 '헬스장'이라고 콕 집었으면 헬스장만")
fid = next(f for f, c in CLOSURES.items() if c["업종"] == "헬스장") if any(c["업종"] == "헬스장" for c in CLOSURES.values()) else E.F[E.F["업종"] == "헬스장"].index[0]
st, facts, rk = run(fid, {"leaf_id": "P10.1.01", "any_kind": True}, "헬스장 추천해줘")
ok(rk and all(c.get("업종") == "헬스장" for c in rk), "결과: " + ", ".join(f"{c['상호']}({c.get('업종')})" for c in rk))
print("4) 앞에서 아무 종류로 찾은 뒤 '헬스장'을 고르면 넓힌 범위가 남지 않음 (공원이 섞이던 원인)")
st, facts, rk = run(fid, {"leaf_id": "P10.1.01", "any_kind": True}, "운동할 데")
st["user_text"] = "헬스장으로 볼래요"; H._find(st, {"leaf_id": "P10.1.01", "kind": "헬스장"}); rk = st["last_result"]["순위"]
ok(st.get("scope", "kind") == "kind" and all(c.get("업종") == "헬스장" for c in rk), f"범위 {st.get('scope', 'kind')}, 결과: " + ", ".join(f"{c['상호']}({c.get('업종')})" for c in rk))
print("5) 같은 가게가 두 번 나오지 않음 (트랙(Track)·트랙)")
st, facts, rk = run(next(f for f, c in CLOSURES.items() if c["상호"] == "돈까스식당"), {"leaf_id": "P01.1.05", "kind": "경양식"})
keys = [C._name_key(c["상호"]) for c in rk]
ok(len(keys) == len(set(keys)), "결과: " + ", ".join(c["상호"] for c in rk))
print("6) 상황 표의 업종 이름이 실제 업종과 모두 맞음")
ok(O.build(set(E.F["업종"].dropna().unique())) == [], "오타 없음")
print("실패", fail)
