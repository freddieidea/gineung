# 새 대화 구조 자동 검사 (5차 점검에서 고른 대표 대화 20개, 실제 언어 모델을 씀, 한 번에 약 0.3달러). 사용: python engine/test_chat.py
#  코드가 바로 보는 것: 맞는 목적으로 찾았는지, 추천 카드가 나왔는지, 자료에 없는 번호·내부 용어·도구 형식이 새지 않았는지, 위급하면 연락처가 먼저인지
import sys, os, re, json
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
os.environ.setdefault("CHECK5_RUN", "_test")
from recommend import Engine
from conversation import Conversation, CLOSURES
import chat as CH, check5_cases as K
E = Engine(); C = Conversation(E); H = CH.Chat(C)
PICK = [1, 19, 33, 35, 44, 50, 52, 69, 70, 87, 103, 104, 110, 120, 132, 151, 165, 172, 182, 185]   # 유형마다 고루 (번호는 check5_cases 순서)
INTERNAL = re.compile(r"업종|인허가|우리 자료|데이터베이스|상가 자료|세부 기능|</?parameter|</?answer")
fails = []
def check(n, c): print(("통과 " if c else "실패 ") + n); (None if c else fails.append(n))
def closed(up):
    xs = sorted([k for k, v in CLOSURES.items() if v["업종"] == up and k in E.F.index], key=lambda k: (CLOSURES[k]["단계"] != "지도 표시", k))
    return xs[0] if xs else None
def run(i):
    typ, start, utts, leaves, note = K.C[i - 1]
    if start.startswith("closed:"):
        fid = closed(start[7:]); r0 = E.F.loc[fid]
        st, r = H.start(float(r0["경도"]), float(r0["위도"]), gu=r0["구군"], closed_fid=fid, origin_name=r0["상호"], origin_closed=True); r = H.begin(st, r); outs = [r]
    else:
        lon, lat, gu = K.LOC[start]; st, r = H.start(lon, lat, gu=gu, origin_name="지도 가운데"); r = H.begin(st, r); outs = []
    for u in utts: outs.append(H.reply(st, u))
    last = outs[-1] if outs else r
    if not any(b.get("card") for b in last.get("blocks", [])) and last.get("options") and typ != "위급":   # 에이전트가 먼저 여쭸으면 첫 보기를 누른 것으로 (10/16: 묻기는 에이전트가 판단)
        outs.append(H.reply(st, last["options"][0]))
    return i, typ, utts, leaves, st, outs
with ThreadPoolExecutor(6) as ex:
    for i, typ, utts, leaves, st, outs in ex.map(run, PICK):
        tag = f"{i}번 {typ} {'/'.join(utts) or '(대신 갈 곳 찾기)'}"
        note = K.C[i - 1][4]; last = outs[-1]; text = " ".join(o.get("text", "") for o in outs)
        asks = "물음" in note and not st.get("leaf")   # 묻는 것이 맞는 경우 (예: 애 봐줄 데 → 아이 나이)
        if leaves and not asks: check(f"{tag} → 맞는 목적({st.get('leaf')})", st.get("leaf") in leaves)
        if leaves and not asks and typ not in ("위급",): check(f"{tag} → 추천 카드가 나옴", any(b.get("card") for o in outs for b in o.get("blocks", [])))
        if asks: check(f"{tag} → 짧게 되물음", last.get("text", "").rstrip().endswith("?") or bool(last.get("options")) or bool(last.get("질문")))
        check(f"{tag} → 같은 질문을 두 번 하지 않음", len([o for o in outs if not any(b.get("card") for b in o.get("blocks", [])) and o.get("text", "").rstrip().endswith("?")]) <= 2)
        check(f"{tag} → 내부 용어·도구 형식이 새지 않음", not INTERNAL.search(text))
        check(f"{tag} → 검사 신호 없음", all(not (o.get("_meta") or {}).get("bad2") for o in outs))
        if typ == "위급" and re.search(r"죽고|때려|쓰러|숨이|불이", "".join(utts)): check(f"{tag} → 위급 연락처 안내", bool(re.search(r"119|112|109|1577-1389|1393|상담", text)))
print("사용", {k: v for k, v in H.usage.items() if not k.startswith("tok")}, "실패", len(fails)); sys.exit(1 if fails else 0)
