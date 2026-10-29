# 5차 점검 ② 돌리기: python engine/check5.py 시작 끝 [동시 개수]
#  결과: data/check5/run/NNN.json (카카오 결과는 남기지 않음: 블로그는 글 수만, 실시간 은행 카드는 이름 없이)
import sys, os, json, time, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
from recommend import Engine
from conversation import Conversation, CLOSURES
import chat as CH, importlib
K = importlib.import_module(os.environ.get("CHECK5_CASES", "check5_cases"))   # (10/29) 사회적 맥락 점검 묶음 등 다른 시험 묶음도 같은 방식으로
E = Engine(); C = Conversation(E); H = CH.Chat(C)
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "check5", os.environ.get("CHECK5_RUN", "run")); os.makedirs(OUT, exist_ok=True)
def pick_closed(up):
    xs = sorted([k for k, v in CLOSURES.items() if v["업종"] == up and k in E.F.index], key=lambda k: (CLOSURES[k]["단계"] != "지도 표시", k))
    if xs: return xs[0]
    F = E.F; ys = F[(F["업종"] == up) & F["인허가상태"].fillna("").str.contains("폐업") & F["경도"].notna()].index
    return ys[0] if len(ys) else None
def clean(r):
    out = []
    for x in r.get("blocks", []):
        if "card" in x: out.append({"카드": "(카카오맵 실시간 결과)" if "카카오맵에 '" in json.dumps(x, ensure_ascii=False) else x["card"]["제목"]})
        elif "blog" in x: out.append({"블로그": f"글 {x['blog'].get('글수')}개 목록을 화면에 보여 줌"})
        elif "links" in x: out.append({"출처": [l["url"] for l in x["links"]]})
        else: out.append({"말": x.get("text", "")})
    return {"블록": out, "버튼": r.get("options") or [], "전화연결": bool(r.get("connect") or r.get("connect_options")), "위급": r.get("위급"), "meta": r.get("_meta")}
def run(i):
    typ, start, utts, leaves, note = K.C[i]; t0 = time.time()
    rec = {"번호": i + 1, "유형": typ, "참고": note, "맞는기능": leaves, "마디": []}
    try:
        if start.startswith("closed:") or start.startswith("closedname:"):
            fid = pick_closed(start[7:]) if start.startswith("closed:") else next((k for k, v in CLOSURES.items() if start[11:] in str(v.get("상호", "")) and k in E.F.index), None)
            if fid is None: rec["오류"] = "그 업종의 문 닫은 곳 없음"; return rec
            r0 = E.F.loc[fid]
            st, r = H.start(float(r0["경도"]), float(r0["위도"]), gu=r0["구군"], closed_fid=fid, origin_name=r0["상호"], origin_closed=True); r = H.begin(st, r)
            rec["시작"] = f"문 닫은 '{r0['상호']}'({r0['업종']})에서 '대신 갈 곳 찾기'"
            rec["마디"].append({"주민": "(대신 갈 곳 찾기 누름)", **clean(r)})
        else:
            lon, lat, gu = K.LOC[start]; st, r = H.start(lon, lat, gu=gu, origin_name="지도 가운데"); r = H.begin(st, r)
            rec["시작"] = f"{start}({gu}) 지도 가운데에서 '하려는 일로 찾기'"
        for u in utts:
            r = H.reply(st, u); rec["마디"].append({"주민": u, **clean(r)})
        rec["최종기능"] = st.get("leaf"); rec["최종종류"] = st.get("kind")
        rec["기능맞음"] = None if leaves is None else (st.get("leaf") in leaves)
    except Exception as e:
        import traceback; rec["오류"] = traceback.format_exc()[-600:]
    rec["초"] = round(time.time() - t0)
    json.dump(rec, open(os.path.join(OUT, f"{i + 1:03d}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return rec
a, b = int(sys.argv[1]), int(sys.argv[2]); W = int(sys.argv[3]) if len(sys.argv) > 3 else 4
only = [int(x) - 1 for x in os.environ.get("CHECK5_ONLY", "").split(",") if x.strip()]
todo = [i for i in (only or range(a, b)) if not os.path.exists(os.path.join(OUT, f"{i + 1:03d}.json"))]
t0 = time.time()
with ThreadPoolExecutor(W) as ex:   # W개씩 묶어 돌리고, 시간이 넉넉할 때만 다음 묶음 (한 번에 3분 안)
    for k in range(0, len(todo), W):
        if time.time() - t0 > 95: print("시간 다 됨, 다음에 이어서"); break
        for rec in ex.map(run, todo[k:k + W]):
            print(rec["번호"], rec["유형"], rec.get("초"), "오류" if rec.get("오류") else "", rec.get("기능맞음"))
print("사용", {k: v for k, v in H.usage.items()})
