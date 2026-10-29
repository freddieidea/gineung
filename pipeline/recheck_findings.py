# 독립 점검(verify_members.py) 지적 사항이 지금 데이터에서 아직 추천되는지 다시 확인 (고친 뒤 매번 돌림)
import json,glob,collections,sys
sys.path.insert(0,"engine"); from recommend import Engine
E=Engine(); F=[]; need_of={}
for p in sorted(glob.glob((sys.argv[1] if len(sys.argv)>1 else "data/work/members_verify")+"/*.json")):
    d=json.load(open(p)); F+=d["findings"]
    for x in d["payload"]: need_of[(x["id"],x["세부 종류"])]=x.get("주민의 이용 방식")
still=[]; gone=collections.Counter()
for it in F:
    f=it["fid"]; lid=it["id"]; k=it["kind"] if it["kind"]!="(구분 없음)" else None
    if f not in E.F.index: gone["시설 없음"]+=1; continue
    r=E.F.loc[f]
    if r["대안후보"]!="예": gone["대안후보 "+r["대안후보"]]+=1; continue
    if k and ((lid,k) not in E.kind or f not in E.kind[(lid,k)]["fids"]): gone["종류에서 빠짐"]+=1; continue
    if lid not in E.leaf: gone["기능 없음"]+=1; continue
    st=E.judge(f,lid,k,need_of.get((lid,it["kind"])))[0]
    if st in ("근거","강함"): still.append((lid,k,r["상호"],r["업종"],it["problem"],it["reason"][:70]))
    else: gone["판정 "+st]+=1
print("지적",len(F),"해결",dict(gone),"아직 추천되는 것",len(still))
for s in still: print(s)
