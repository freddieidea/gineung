# 기능 연결 전수 검토(2026-10-15 오후)에서 바로잡은 것들이 다시 틀어지지 않는지 보는 검사. 사용: python engine/test_review.py
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recommend import Engine
E = Engine(); F = E.F; fails = []
def check(n, c):
    print(("통과 " if c else "실패 ") + n); (None if c else fails.append(n))
def j(name, lid, upjong=None):
    s = F[(F["상호"] == name) & (F["대안후보"] != "아니요")]
    if upjong: s = s[s["업종"] == upjong]
    return E.judge(s.index[0], lid, None)[0] if len(s) else "없음"
check("증명사진: 웨딩 스튜디오는 아님", j("엘프웨딩", "P06.1.03") == "아니요")
check("증명사진: 사진관은 근거와 함께", j("한양사진관", "P06.1.03") == "근거")
check("증명사진: 셀프 사진 부스는 아님", j("인생네컷", "P06.1.03") == "아니요")
check("장례식장: 의전 업체는 아님", j("대중의전", "P16.1.01") == "아니요")
pub = F[(F["업종코드"] == "PUB:장례식장") & (F["대안후보"] == "예")]
check(f"장례식장: 공식 목록 {len(pub)}곳은 모두 확실", len(pub) >= 50 and all(E.judge(f, "P16.1.01", None)[0] == "강함" for f in pub.index))
r = E.recommend("P16.1.01", None, 128.5935, 35.8714, n=10)
check("장례식장 추천은 공식 목록이나 상호로 장례식장인 곳만", r["추천"] and all(c["fid"].startswith("P:장례식장:") or "장례식장" in c["상호"] for c in r["추천"]))
dup = F[(F["출처"] == "상가") & (F["업종"] == "장례식장") & (F["제외사유"].fillna("").str.contains("공식 장례식장 목록"))]
check(f"장례식장: 공식 목록과 겹치는 상가 {len(dup)}곳은 한 번만 보임", len(dup) >= 20)
gn = F[(F["업종"] == "구내식당") & (F["대안후보"] == "예")]
check("구내식당은 외식 대안으로 확실하다고 하지 않음", all(E.judge(f, "P01.1.05", "구내식당")[0] in ("모름", "아니요") for f in gn.index[:50]))
check("테니스장 업종의 PT 스튜디오는 테니스 대안이 아님", j("하이그룹피티", "P10.1.01") == "아니요")
check("슈퍼마켓 업종의 아이스크림 가게는 가공식품 대안이 아님", j("얼어죽어도아이스께끼 대현점", "P01.1.02") == "아니요")
check("가전 수리: 청소 업체는 아님", j("클린몬스터", "P08.1.03") == "아니요")
check("농자재: 반려동물 사료 가게는 아님", j("다이뜨라신천 직영점", "P15.1.01") == "아니요")
mil = F[F["상호"].fillna("").str.contains("군사우편")]
check("군사우편출장소는 추천하지 않음", len(mil) and (mil["대안후보"] == "아니요").all())
check("농약 판매업 등록 나무병원·방제 업체는 농자재 가게가 아님", j("주식회사한솔나무병원", "P15.1.01") == "아니요")
sch = F[F["상호"].isin(["대구외국어고등학교", "경화여자고등학교", "대구교육대학교대구부설초등학교"])]
check("따로 뽑는 학교·여자 학교는 '확인 필요'", len(sch) == 3 and (sch["대안후보"] == "확인 필요").all())
check("'운영 준비 중' 작은도서관은 추천하지 않음", (F[F["상호"].str.contains("운영준비중", na=False)]["대안후보"] == "아니요").all())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline")); import facility_rules as FR
gy = F[(F["업종코드"] == "PUB:경로당")]
check("아파트 단지 경로당은 대안으로 안내하지 않음", (gy[[FR.in_complex(n, a) for n, a in zip(gy["상호"], gy["주소"])]]["대안후보"] == "아니요").all())
f0 = F.index[F["상호"] == "학남경로당"][0]
r = E.recommend("P11.1.02", "경로당", float(F.loc[f0, "경도"]), float(F.loc[f0, "위도"]), n=15, elig_ok={"경로당"}, exclude=[f0])
check("동네 경로당 대신 갈 곳에 단지 경로당이 없음", r["추천"] and not any(FR.in_complex(c["상호"], c["주소"]) for c in r["추천"] + r["제공여부확인필요"]))
lib = F[(F["업종코드"] == "PUB:작은도서관") & (F["대안후보"] == "예")]
check("누구나 이용하는 작은도서관은 공공이 운영하는 곳만", len(lib) > 30 and all(re.search(r"구청|군청|주민센터|행정복지센터|문화재단|복지관|새마을|노인회|청소년|교육|시청", str(x)) for x in lib["참고"] + lib["상호"]))
check("같은 번호를 여러 경로당이 쓰면 관리 기관 번호라고 표시", F.loc[f0, "전화"].endswith("(관리 기관 번호)"))
# ---- 문 닫은 곳 안내 기간 · 같은 자리 새 가게 (10/15) ----
import pandas as pd, datetime
from unit_addr import unit
CL = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "processed", "closures.csv"), dtype=str).fillna("")
check("안내 기간이 지난 문 닫은 곳은 목록에 없음", len(CL) and (CL["단계"] != "지남").all() and (CL["안내까지"] >= datetime.date.today().isoformat()).all())
lk = CL[CL["새가게"] != ""]
check(f"이 자리 새 가게 {len(lk)}곳은 모두 층·호까지 아는 칸", len(lk) and (lk["칸주소"].str.contains(" ")).all())
check("이 자리 새 가게는 모두 문 닫은 뒤(30일 여유)에 연 곳", all(o >= (datetime.date.fromisoformat(c) - datetime.timedelta(days=30)).isoformat() for o, c in zip(lk["새가게개업일"], lk["폐업일자"])))
bk = CL[CL["상호"].str.contains("버거킹대구 시지점")]
check("같은 건물 이웃 가게(2018년부터 있던 짬뽕집)를 버거킹 자리의 새 가게로 보지 않음", bk.empty or not bk["새가게"].str.contains("짬뽕").any())
check("같은 기능 새 가게가 들어온 곳은 지도 표시를 내림", (CL[CL["같은기능새가게"] == "True"]["단계"] != "지도 표시").all())
import conversation as CV
check("문 닫은 곳 말머리: 폐업 달과 그 자리 새 가게를 말함", any("그 자리에는 지금" in CV.closed_line(f, r["상호"]) and "년" in CV.closed_line(f, r["상호"]) for f, r in CV.CLOSURES.items() if r["새가게"]))
st = {"leaf": "P07.2.01", "menu_words": ["커트"]}
res = CV.Conversation._menu_order(CV.Conversation.__new__(CV.Conversation), st, {"추천": [{"상호": "류헤어센스", "표시": []}]})
check("미용실 결과에 '찾으시는 메뉴가 있는지'를 붙이지 않음", not any("메뉴" in m for c in res["추천"] for m in c["표시"]))
re_ = F[F["상호"].isin(["김진희부동산", "마루부동산", "붕붕자동차구하기"])]
check("다른 업종으로 등록된 부동산·중고차 사무실은 안내하지 않음", len(re_) == 3 and (re_["대안후보"] == "아니요").all())
# ---- 주민에게 보이는 말 (10/15) ----
from ask_phrases import ASK
chk = {(l.get("kinds") or {}).get("check", "") for l in E.leaf.values()} - {""}
check(f"세부 기능 {len(chk)}개의 '물어보실 것'에 모두 주민용 문장이 있음", all(c in ASK for c in chk))
check("주민용 문장에 내부 자료 이름(심평원·인허가·확인됨)이 없음", not any(re.search(r"심평원|인허가|확인됨|현황 \d|판매 품목|취급 품목", v) for v in ASK.values()))
print("실패", len(fails)); sys.exit(1 if fails else 0)
