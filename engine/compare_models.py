# Haiku·Sonnet 비교: 같은 대화를 두 모델로 돌림. 사용: python engine/compare_models.py 모델(haiku|sonnet) 시작번호 끝번호
#  결과는 이 컴퓨터 작업 폴더 밖($HOME/cmp)에 두고, 카카오 결과(블로그 글·실시간 은행 이름)는 남기지 않음
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
from recommend import Engine
from conversation import Conversation, CLOSURES
import chat as CH
E = Engine(); C = Conversation(E)
model = {"haiku": CH.HAIKU, "sonnet": CH.SONNET}[sys.argv[1]]; a, b = int(sys.argv[2]), int(sys.argv[3])
H = CH.Chat(C, force=model)
BANWOL = (128.5935, 35.8657, "중구"); BEOMEO = (128.6250, 35.8590, "수성구")
def closed(name): return next(k for k, v in CLOSURES.items() if v["상호"] == name)
REST = next(k for k, v in CLOSURES.items() if v["업종"] == "백반/한정식" and v["단계"] == "지도 표시" and k in E.F.index)
S = [  # (시작, 주민의 말들)
 (BANWOL, ["머리 좀 자르고 싶은데 근처에 어디 없나"]),
 (BEOMEO, ["할매 무릎 아픈데 갈만한 병원"]),
 (BANWOL, ["밥 무러 갈 데 없나 국밥 같은 거"]),
 (BEOMEO, ["약국"]),
 (BEOMEO, ["우리 엄마 낮에 맡길 데 찾는데요 치매 있으세요"]),
 (BANWOL, ["경로당 문 닫았다던데 어디 가야돼"]),
 (BEOMEO, ["빵"]),
 (BANWOL, ["택배 보낼라고"]),
 (BEOMEO, ["아들이 차로 데려다준대 정형외과"]),
 (BEOMEO, ["거동이 불편해서 못 나가는데 목욕은 어떻게 해"]),
 (BEOMEO, ["애 맡길 데 퇴근 늦게까지"]),
 ("아리헤어", ["버스는?", "아니 그게 아니라 걸어서 더 가까운 데"]),
 ("아리헤어", ["거기 말고 딴 데"]),
 ("아리헤어", ["파마 잘하는 데"]),
 ("옌카롱", ["소금빵 파는 데 있나"]),
 ("옌카롱", ["평 좋은 데"]),
 (REST, ["혼자 먹기 편한 데", "주차되나"]),
 (BANWOL, ["몰라 그냥 아무거나 찾아줘"]),
 (BEOMEO, ["치과 가야되는데 무서워서 친절한 데"]),
 (BANWOL, ["어 그 뭐냐 서류 떼는 데 동사무소 말고 기계 있는 데"]),
]
def clean(r):
    out = []
    for x in r["blocks"]:
        if "card" in x: out.append({"카드": x["card"]["제목"] if "카카오맵에 '" not in json.dumps(x, ensure_ascii=False) else "(카카오맵 실시간 결과 카드)"})
        elif "blog" in x: out.append({"블로그": f"글 {x['blog'].get('글수')}개 목록을 화면에 보여 줌"})
        elif "links" in x: out.append({"출처": [l["url"] for l in x["links"]]})
        else: out.append({"말": x.get("text", "")})
    return {"블록": out, "버튼": r.get("options") or []}
for i in range(a, b):
    start, utts = S[i]; t0 = time.time(); rec = {"번호": i + 1, "시작": None, "마디": []}
    try:
        if isinstance(start, tuple):
            st, r = H.start(start[0], start[1], gu=start[2]); r = H.begin(st, r); rec["시작"] = f"지도 가운데({start[2]})에서 '하려는 일로 찾기'"
        else:
            fid = closed(start) if start in [v["상호"] for v in CLOSURES.values()] else start
            r0 = E.F.loc[fid]; st, r = H.start(float(r0["경도"]), float(r0["위도"]), gu=r0["구군"], closed_fid=fid, origin_name=r0["상호"], origin_closed=True); r = H.begin(st, r)
            rec["시작"] = f"문 닫은 '{r0['상호']}'({r0['업종']})에서 '대신 갈 곳 찾기'"
            rec["마디"].append({"주민": "(대신 갈 곳 찾기 누름)", **clean(r)})
        for u in utts:
            r = H.reply(st, u); rec["마디"].append({"주민": u, **clean(r)})
    except Exception as e:
        rec["오류"] = repr(e)[:300]
    rec["초"] = round(time.time() - t0)
    json.dump(rec, open(os.path.join(os.environ["HOME"], "cmp", f"{sys.argv[1]}_{i + 1:02d}.json"), "w"), ensure_ascii=False, indent=1)
    print(sys.argv[1], i + 1, rec["초"], "초", "오류" if "오류" in rec else "")
print("사용", H.usage)
