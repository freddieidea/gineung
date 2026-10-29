# 대화 엔진 정확도 검사: 주민 말 한 마디 → 세부 기능·세부 종류를 맞게 고르는지, 애매하면 고르지 않고 다시 묻는지
# 가장 중요한 지표는 '틀린 확신' (틀린 것을 확신하고 고른 경우) = 0 이어야 함
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recommend import Engine
from dialogue import Dialogue
E = Engine(); D = Dialogue(E); D.log_path = None; F = E.F  # 시험 대화는 지자체 기록에 남기지 않음
def fac(upjong=None, code=None):
    s = F[(F["업종"] == upjong) if upjong else (F["업종코드"] == code)]
    s2 = s[s["대안후보"] == "아니요"]
    return (s2 if len(s2) else s).iloc[0]["fid"]
U = "UNCLEAR"
# (문 닫은 시설, 주민 말, 맞는 세부 기능들, 맞는 세부 종류들(None=종류 구분 없음, "*"=아무 종류나 맞음), 걸음)
CASES = [
 (fac("해산물 구이/찜"), "여기 대신 갈 만한 데 있어요?", {"P01.1.05"}, {"해산물 구이·찜"}, None),
 (fac("헬스장"), "운동하러 다녔어요", {"P03.3.01", "P10.1.01"}, {"헬스장"}, None),
 (fac("헬스장"), "동네 친구들이랑 같이 운동하면서 어울리던 곳이에요", {"P11.1.03"}, {"헬스장", U}, None),
 (fac("떡/한과"), "쌀 가져가서 떡 맞추던 곳이에요", {"P01.3.01"}, {"떡집(쌀 맞춤 여부 확인 필요)", "방앗간"}, None),
 (fac("떡/한과"), "떡 사러 다녔어요", {"P01.2.02"}, {"*"}, None),
 (fac("미용실"), "파마하러 다니던 미용실이에요", {"P07.2.01"}, {"미용실"}, None),
 (fac("편의점"), "택배 찾으러 다녔어요", {"P06.2.03"}, {None}, None),
 (fac("편의점"), "라면이랑 생수 사던 곳", {"P01.1.02"}, {"편의점"}, None),
 (fac("약국"), "처방전 약 받으러 다녔어요", {"P03.2.01"}, {None}, None),
 (fac("이비인후과 의원"), "목감기 때문에 다니던 병원이에요", {"P03.1.01"}, {"*"}, None),
 (fac("세탁소"), "양복 드라이 맡기던 곳", {"P07.3.01"}, {"*"}, None),
 (fac("돼지고기 구이/찜"), "동네 어르신들이랑 모여서 이야기 나누던 데예요", {"P11.2.01", "P11.1.03"}, {"*", U}, None),
 (fac("정육점"), "고기 사던 곳이에요", {"P01.1.01"}, {"정육"}, None),
 (fac("노래방"), "노래 부르러 다녔어요", {"P10.1.03"}, {"*"}, None),
 (fac(code="PUB:방문요양"), "어머니한테 요양보호사가 오던 센터가 문을 닫았어요", {"P04.1.01"}, {"방문요양 기관"}, None),
 (fac(code="PUB:경로당"), "친구들 만나러 가던 곳이에요", {"P11.1.03"}, {"경로당"}, None),
 (None, "종량제 봉투 어디서 사요?", {"P02.1.07"}, {None}, None),
 (None, "해물찜 먹을 데 찾아요", {"P01.1.05"}, {"해산물 구이·찜"}, None),
 (None, "보청기 고치는 데 있어요?", {"P03.4.02"}, {None}, None),
 (None, "아이 맡길 어린이집 찾아요", {"P04.2.01"}, {U, "어린이집(국공립·민간·법인 등)"}, None),
 (None, "병원 가야 해요", {"P03.1.01", U}, {U}, None),
 (None, "운동하고 싶어요", {"P03.3.01", "P10.1.01", U}, {U}, None),
 (None, "골프 연습장 찾아요", {"P10.1.01", "P10.1.03"}, {"골프 연습장"}, None),
 (None, "이불 빨래할 곳", {"P07.3.02"}, {"*", U}, None),
 (None, "등본 떼야 해요", {"P06.1.01"}, {"*", U}, None),
 (None, "그냥 대신 갈 곳 찾아줘", {U}, {U}, None),
 (None, "지팡이 짚고 다녀서 멀리는 못 가요. 목욕탕 찾아요", {"P07.1.01"}, {None}, "아주 천천히"),
 (None, "농약 사야 돼요", {"P15.1.01"}, {"농약 판매업체"}, None),
 (None, "어머니가 욕창이 있어서 간호사가 집에 와야 해요", {"P04.1.05"}, {"방문간호 기관", U}, None),
 (None, "쭈꾸미 볶음 먹으러 다니던 집이 닫았어요", {"P01.1.05"}, {"해산물 구이·찜"}, None),
]
res = []; t0 = time.time()
lo, hi = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (0, len(CASES))
for closed, text, leaves, kinds, speed in CASES[lo:hi]:
    st = {"closed_fid": closed}
    try: r = D.step(st, text)
    except Exception as e: r = {"type": "error", "text": str(e)}
    leaf = st.get("leaf") or U; kind = st.get("kind") if st.get("leaf") else U
    if r["type"] == "question" and st.get("leaf"): kind = U
    if st.get("leaf") and not E.leaf[leaf]["kinds"].get("sensitive"): kind = None
    leaf_ok = leaf in leaves
    kind_ok = (kind in kinds) or ("*" in kinds and kind not in (U,)) or (U in kinds and kind == U)
    if leaf == U and U in leaves: kind_ok = True
    wrong_conf = (leaf != U and leaf not in leaves) or (leaf_ok and kind not in (U, None) and not kind_ok)
    sp_ok = (speed is None) or st.get("speed") == speed
    res.append({"text": text, "closed": F.loc[closed, "업종"] if closed else "", "leaf": leaf, "kind": kind, "leaf_ok": leaf_ok, "kind_ok": kind_ok,
                "wrong_conf": wrong_conf, "speed_ok": sp_ok, "q": r.get("text") if r["type"] == "question" else "", "opts": r.get("options", [])})
    print(("맞음" if leaf_ok and kind_ok and sp_ok else ("틀린 확신" if wrong_conf else "부분")), "|", res[-1]["closed"], "|", text, "→", leaf, E.leaf[leaf]["name"] if leaf in E.leaf else "", "/", kind, "|", res[-1]["q"], res[-1]["opts"])
n = len(res)
print(f"\n세부 기능 정확도 {sum(r['leaf_ok'] for r in res)}/{n}, 세부 종류까지 정확도 {sum(r['leaf_ok'] and r['kind_ok'] for r in res)}/{n}, 걸음 인식 {sum(r['speed_ok'] for r in res)}/{n}, 틀린 확신 {sum(r['wrong_conf'] for r in res)}건, {round(time.time()-t0)}초")
json.dump(res, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "work", f"dialogue_test_{lo}_{hi}.json" if (lo, hi) != (0, len(CASES)) else "dialogue_test.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
