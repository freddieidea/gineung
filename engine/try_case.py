# 문 닫은 곳 하나로 대화를 손으로 돌려 보기: python engine/try_case.py <업종 또는 fid> "말1" "말2" ...
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
from recommend import Engine
from conversation import Conversation, CLOSURES
from chat import Chat
E = Engine(); C = Conversation(E); H = Chat(C)
def show(tag, r):
    print(f"--- {tag} [{r['type']}] 버튼={r.get('options')} {r.get('_meta')}" + (f" 질문={[g['key'] for g in r['질문']]}" if r.get("질문") else ""))
    for b in r["blocks"]:
        if "card" in b: print("   [카드]", b["card"]["제목"][:80], "|", (b["card"].get("부제") or "")[:60])
        elif "blog" in b: print("   [블로그]", b["blog"].get("글수"))
        elif "links" in b: print("   [출처]", [l["url"][:50] for l in b["links"]])
        else: print("  ", b["text"])
key = sys.argv[1]; t = time.time()
if key.startswith("free"):   # free = 문 닫은 곳 없이 대화로 시작 (지도 가운데: 범어역 근처)
    lon, lat = (128.6255, 35.8590) if "@" not in key else map(float, key.split("@")[1].split(","))
    st, r = H.start(lon, lat, gu=None, origin_name="지도 가운데", origin_kind="지도 가운데"); r = H.begin(st, r); show("시작(대화)", r)
else:
    fid = key if key in E.F.index else next(f for f, c in CLOSURES.items() if c["업종"] == key)
    r0 = E.F.loc[fid]; print("시작:", r0["상호"], r0["업종"], r0["구군"])
    st, r = H.start(float(r0["경도"]), float(r0["위도"]), gu=r0["구군"], closed_fid=fid, origin_name=r0["상호"], origin_closed=True); r = H.begin(st, r); show("시작", r)
for u in sys.argv[2:]:   # '@mode=버스·지하철,who=연인' = 화면에서 고른 것, '@' 만 = 바로 보기
    if u.startswith("@"):
        ans = dict(x.split("=", 1) for x in u[1:].split(",") if "=" in x)
        lab = " · ".join(ans.values()) or "그냥 걸어서 가까운 곳 볼래요"; r = H.reply(st, lab, answers=ans); show("고름 " + lab, r)
    else:
        r = H.reply(st, u); show(u, r)
print("사용", H.usage, f"{time.time() - t:.0f}초")
