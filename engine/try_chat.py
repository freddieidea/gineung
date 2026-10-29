# 새 대화 구조 손으로 돌려 보기: python engine/try_chat.py
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
from recommend import Engine
from conversation import Conversation
from chat import Chat
E = Engine(); C = Conversation(E); H = Chat(C)
def show(tag, r):
    print(f"--- {tag} [{r['type']}] 버튼={r.get('options')}")
    for b in r["blocks"]:
        if "card" in b: print("   [카드]", b["card"]["제목"][:70])
        elif "blog" in b: print("   [블로그]", b["blog"].get("글수"))
        elif "links" in b: print("   [출처]", [l["url"][:50] for l in b["links"]])
        else: print("  ", b["text"])
fid = "S:MA010120220808605214"; r0 = E.F.loc[fid]
t = time.time(); st, r = H.start(float(r0["경도"]), float(r0["위도"]), gu=r0["구군"], closed_fid=fid, origin_name=r0["상호"], origin_closed=True); r = H.begin(st, r); show("시작(아리헤어)", r)
for u in sys.argv[1:] or ["버스는?", "아 그냥 평 좋은 데로", "1등 한 데 후기 좀", "됐고 파마 얼마임"]:
    r = H.reply(st, u); show(u, r)
print("사용", H.usage, f"{time.time() - t:.0f}초")
