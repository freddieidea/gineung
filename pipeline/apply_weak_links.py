# 약한 연결 판정표(weak_links_spec.py)를 연결표에 반영. 여러 번 실행해도 결과가 같음
#  삭제 → 연결을 지움 / 종류로 충분·가게별 확인·문의 창구·자료 판정·항목별 → 연결에 'check'로 적음 (엔진과 세부 종류 만들기가 읽음)
#  항목별은 check_items에 세부 의도별 판정을 함께 적음
#  공공·복지 시설 유형의 판정은 public_types.py가 같은 판정표로 반영함
import json, sys
sys.path.insert(0,"pipeline"); from finalize_map import finalize; import weak_links_spec as S
EXPECT="0.9-draft"
T=json.load(open("design/purpose_taxonomy.json",encoding="utf-8")); assert T["version"]==EXPECT
M=json.load(open("data/processed/industry_function_map.json",encoding="utf-8"))
L={x["code"]:x for x in json.load(open("data/processed/industry_list.json",encoding="utf-8"))}
code={x["소분류"]:c for c,x in L.items()}; items={i["code"]:i for i in M["items"]}
SRC="약한 연결 판정 (2026-10-14, 헌준님 판단·독립 점검 반영)"
done={(c.get("업종"),c.get("기능"),c.get("출처")) for c in M["corrections"]}
def log(u,lid,what,why):
    if (u,lid,SRC) not in done: M["corrections"].append({"업종":u,"기능":lid,"내용":what,"이유":why,"출처":SRC}); done.add((u,lid,SRC))
n=dict(삭제=0,표시=0,추가=0)
for (lid,u),(act,why) in S.W.items():
    if u not in code: continue            # 공공·복지 시설 유형 (public_types.py에서 처리)
    it=items[code[u]]; fs=[f for f in it["functions"] if f["id"]==lid]
    if act==S.D:
        if fs: it["functions"]=[f for f in it["functions"] if f["id"]!=lid]; n["삭제"]+=1
        log(u,lid,"연결 삭제",why)
    else:
        if not fs and any((x[0],x[1])==(u,lid) for x in S.NEW): continue   # 지웠던 연결을 근거 판정으로 다시 잇는 경우: 아래 NEW에서 더함
        assert fs, (u,lid)
        fs[0]["check"]=act; fs[0]["check_reason"]=why; n["표시"]+=1
        if act==S.I: fs[0]["check_items"]=dict(S.WI[(lid,u)])     # 세부 의도별 판정 (예: 포장 → 종류로 충분, 배달 → 가게별 확인)
        else: fs[0].pop("check_items",None)
for (u,lid,role,conf,act,why) in S.NEW:
    it=items[code[u]]; fs=[f for f in it["functions"] if f["id"]==lid]
    if fs: fs[0].update(role=role,confidence=conf,check=act,check_reason=why)
    else: it["functions"].append({"id":lid,"role":role,"confidence":conf,"reason":why,"check":act,"check_reason":why}); n["추가"]+=1
    log(u,lid,"연결 추가" if not fs else "연결 수정",why)
# 태권도장의 방과후 돌봄: 헌준님 판단으로 확신도 '보통'으로 올림
tk=[f for f in items[code["태권도/무술학원"]]["functions"] if f["id"]=="P04.2.02"][0]
tk.update(confidence="보통",reason="아이들이 방과 후 머물고 차량으로 데려다주는 곳이 많아 실제로 돌봄 역할을 함 (헌준님 판단)")
# 판정표로 다시 기능이 생긴 업종은 생활시설로 되돌림
for it in M["items"]:
    if it["functions"] and not it["life_facility"] and "약한 연결 정리로 남은 생활 기능 없음" in it.get("note",""):
        it["life_facility"]=True; it["note"]=it["note"].replace("약한 연결 정리로 남은 생활 기능 없음 (2026-10-14)","").strip()
        print("생활시설로 되돌림:",L[it["code"]]["소분류"])
# 기능이 하나도 남지 않은 업종은 생활시설이 아님. 주 기능 없이 부 기능만 남으면 멈추고 알림
for it in M["items"]:
    if not it["functions"] and it["life_facility"]:
        it["life_facility"]=False; it["note"]=(it.get("note","")+" 약한 연결 정리로 남은 생활 기능 없음 (2026-10-14)").strip()
        print("생활시설 아님으로 바뀜:",L[it["code"]]["소분류"])
bad=[L[it["code"]]["소분류"] for it in M["items"] if it["functions"] and not any(f["role"]=="주" for f in it["functions"])]
assert not bad, ("주 기능 없이 부 기능만 남은 업종", bad)
# 판정이 빠진 약한 연결이 없는지
miss=[(f["id"],L[it["code"]]["소분류"]) for it in M["items"] for f in it["functions"] if (f["role"]!="주" or f["confidence"]=="낮음") and "check" not in f]
assert not miss, ("판정 없는 약한 연결", miss)
print(n)
finalize(M,T,L)
