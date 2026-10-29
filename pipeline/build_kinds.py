# 세부 종류(kinds_spec.py)를 검사하고 분류표 JSON의 각 세부 기능에 넣는다. 검사에서 하나라도 틀리면 저장하지 않는다.
import json, sys, collections
import pandas as pd
sys.path.insert(0,"pipeline"); import kinds_spec as S
EXPECT="0.9-draft"
p="design/purpose_taxonomy.json"; T=json.load(open(p,encoding="utf-8")); assert T["version"]==EXPECT, T["version"]
M=json.load(open("data/processed/industry_function_map.json",encoding="utf-8")); assert M["taxonomy_version"]==EXPECT
L={x["code"]:x for x in json.load(open("data/processed/industry_list.json",encoding="utf-8"))}
code={x["소분류"]:c for c,x in L.items()}
df=pd.read_csv("data/raw/소상공인시장진흥공단_상가(상권)정보_대구_202606.csv",dtype=str,usecols=["상권업종소분류코드","표준산업분류명"])
stdcnt=df.groupby(["상권업종소분류코드","표준산업분류명"]).size()
import re
NAMES=pd.read_csv("data/raw/소상공인시장진흥공단_상가(상권)정보_대구_202606.csv",dtype=str,usecols=["상권업종소분류코드","상호명"])
def pat_count(c,pat,allpats):
    # 상호가 정확히 한 종류의 말에만 걸리면 그 종류, 하나도 안 걸리거나 둘 이상 걸리면 '종류 미확인'(섞임 방지)
    n=NAMES.loc[NAMES["상권업종소분류코드"]==c,"상호명"].fillna("").str.replace(r"\s+"," ",regex=True)   # 띄어쓰기를 살려서 읽음
    hits=pd.DataFrame({q:n.str.contains(q,regex=True) for q in allpats})
    one=hits.sum(axis=1)==1
    if pat: return int((one&hits[pat]).sum())
    return int((~one).sum())
leaves={l["id"]:l for c in T["categories"] for q in c["purposes"] for l in q["leaves"]}
link=collections.defaultdict(set)
for it in M["items"]:
    for f in it["functions"]: link[f["id"]].add(L[it["code"]]["소분류"])
X=json.load(open("data/processed/extra_type_functions.json",encoding="utf-8")); assert X["taxonomy_version"]==EXPECT
XT={x["code"]:{f["id"] for f in x["functions"]} for x in X["items"]}; XN={x["code"]:x["name"] for x in X["items"]}
# 연결의 세기: 그 업종·유형의 '주 기능'이 아니거나(부) 확신도가 '낮음'이면 약한 연결. 약한 연결로 들어온 종류는 가게마다 확인해야 하므로
# '여러 종류 겸업'과 똑같이 추천 목록에 바로 넣지 않고 '제공 여부 확인 필요'로 보냄 (예: 김밥집의 반찬 판매, 헬스장의 친목, 편의점의 현금 인출)
# 단, 인허가로 그 일을 하는 것이 확인되는 표시(PERMIT:·LD:)는 약한 연결로 보지 않음 (예: 편의점 상비약 판매 허가)
STRENGTH={}
for it in M["items"]:
    for f in it["functions"]: STRENGTH[(L[it["code"]]["소분류"],f["id"])]=f
for x in X["items"]:
    for f in x["functions"]: STRENGTH[(x["code"],f["id"])]=f
def weak_of(key,lid):
    f=STRENGTH.get((key,lid))
    if f is None or str(key).startswith(("PERMIT:","LD:")): return None
    if f.get("check")=="종류로 충분": return None          # 판정표: 그 종류면 모두 그 일을 함
    if f.get("check") in ("가게별 확인","문의 창구","자료 판정","항목별"): return f'{f["role"]}·{f["confidence"]}·{f["check"]}'
    return f'{f["role"]}·{f["confidence"]}' if (f["role"]!="주" or f["confidence"]=="낮음") else None
F=pd.read_csv("data/processed/facilities.csv",dtype=str,usecols=["fid","업종코드","대안후보","상비약판매","종량제봉투판매","공원운동시설"])
EVM=pd.read_csv("data/processed/evidence_members.csv",dtype=str)   # 근거 유형(EV:)별 시설 (build_evidence.py)
_live=set(F.loc[~F["대안후보"].isin(["아니요","좌표 필요"]),"fid"])
def type_count(t):
    if t.startswith("EV:"): return int(EVM.loc[EVM["code"]==t,"fid"].isin(_live).sum())
    if t=="PERMIT:상비약판매": return int((F["상비약판매"]=="True").sum())
    if t=="PERMIT:종량제봉투판매": return int((F["종량제봉투판매"]=="True").sum())
    if t=="PERMIT:공원운동시설": return int(((F["공원운동시설"]=="True")&(F["대안후보"]!="좌표 필요")).sum())
    return int(((F["업종코드"]==t)&(~F["대안후보"].isin(["아니요","좌표 필요"]))).sum())
err=[]
def n_stores(c,std,claimed):
    s=stdcnt.get(c)
    if s is None: return 0
    if std: return int(sum(s.get(x,0) for x in std))
    return int(s.sum()-sum(s.get(x,0) for x in claimed))
for lid,l in leaves.items():
    if lid in S.K:
        sp=S.K[lid]; groups=S.food_for(link[lid]) if sp.get("food") else sp["groups"]
        per=collections.defaultdict(list)
        for g in groups.values():
            for x in g:
                for t in x.get("types",[]):
                    if t not in XT: err.append(("없는 시설 유형",lid,t))
                    elif lid not in XT[t]: err.append(("시설 유형에 이 기능 없음",lid,t))
                for u in x["upjong"]:
                    if u not in code: err.append(("없는 업종",lid,u)); continue
                    if u not in link[lid]: err.append(("연결 안 된 업종",lid,u))
                    per[u].append(x)
        for u in link[lid]-set(per)-set(getattr(S,"EVCOVER",{}).get(lid,[])): err.append(("빠진 업종",lid,u))   # 근거 유형이 대신 맡는 업종은 빠진 것이 아님
        for u in getattr(S,"EVCOVER",{}).get(lid,[]):
            if u not in link[lid]: err.append(("근거 유형이 맡는다는 업종이 연결에 없음",lid,u))
        for u,xs in per.items():
            rest=[x for x in xs if not x["std"] and not x.get("pat")]
            if len(rest)>1: err.append(("같은 업종이 나머지 종류로 두 번",lid,u))
            stds=[s for x in xs if x["std"] for s in x["std"]]
            if len(stds)!=len(set(stds)): err.append(("표준산업분류 겹침",lid,u))
            for s in stds:
                if stdcnt.get((code[u],s),0)==0: err.append(("자료에 없는 표준산업분류",lid,u,s))
            if not rest and code[u] in stdcnt.index.get_level_values(0):
                left=int(stdcnt[code[u]].sum())-sum(int(stdcnt.get((code[u],s),0)) for s in stds)
                if left>0: err.append(("어느 종류에도 안 들어간 가게",lid,u,left))
        for u,xs in per.items():
            pats=[x["pat"] for x in xs if x.get("pat")]
            if pats:
                tot=int((NAMES["상권업종소분류코드"]==code[u]).sum())
                if sum(pat_count(code[u],q,pats) for q in pats)+pat_count(code[u],None,pats)!=tot: err.append(("상호 나누기 합계 불일치",lid,u))
        for g in groups.values():
            for x in g:
                if x.get("contact") and x["upjong"]: err.append(("신청·문의 창구에 상가 업종이 들어감",lid,x["name"]))
        names=[x["name"] for g in groups.values() for x in g]
        if len(names)!=len(set(names)): err.append(("종류 이름 중복",lid))
        out=[]
        for gn,xs in groups.items():
            ks=[]
            for x in xs:
                ups=[]
                for u in x["upjong"]:
                    claimed=[s for y in per[u] if y["std"] for s in y["std"]]
                    pats=[y["pat"] for y in per[u] if y.get("pat")]
                    if pats: cnt=pat_count(code[u],x.get("pat"),pats)
                    else: cnt=n_stores(code[u],x["std"],claimed)
                    ups.append({"code":code[u],"name":u,"std":x["std"],"pat":x.get("pat"),"stores":cnt})
                tps=[{"code":t,"name":XN[t],"stores":type_count(t)} for t in x.get("types",[])]
                weak=[f"{u}({w})" for u in x["upjong"] if (w:=weak_of(u,lid))]+[f"{XN[t]}({w})" for t in x.get("types",[]) if (w:=weak_of(t,lid))]
                mixed=x["mixed"] or (bool(weak) and not x.get("contact"))
                for t in x.get("types",[]):
                    if t.startswith("EV:") and type_count(t)==0: err.append(("근거 유형에 시설이 없음",lid,t))
                ks.append({"name":x["name"],"mixed":mixed,"mixed_spec":x["mixed"],"weak":weak,"evidence":any(t.startswith("EV:") for t in x.get("types",[])),"contact":x.get("contact",False),"elig":x.get("elig"),"upjong":ups,"types":tps,"stores":sum(v["stores"] for v in ups)+sum(v["stores"] for v in tps)})
            out.append({"name":gn,"kinds":ks})
        l["kinds"]={"sensitive":True,"check":sp["check"],"note":sp.get("note",""),"groups":out}
    elif lid in S.NOT:
        l["kinds"]={"sensitive":False,"reason":S.NOT[lid],"check":S.CHECK.get(lid,"")}
    elif not link[lid]:
        l["kinds"]={"sensitive":None,"reason":"아직 연결된 업종이 없음 (공공시설 자료를 넣을 때 정함)","check":""}
    else:
        err.append(("판단 안 된 기능",lid,l["name"]))
# 반대 방향 검사: 시설 유형이 어떤 기능을 한다고 적혀 있으면, 그 기능의 세부 종류 어딘가에 반드시 들어가 있어야 함
for t,fs in XT.items():
    for lid in fs:
        if lid in S.K:
            sp=S.K[lid]; gs=S.food_for(link[lid]) if sp.get("food") else sp["groups"]
            if not any(t in x.get("types",[]) for g in gs.values() for x in g): err.append(("세부 종류에 빠진 시설 유형",lid,t))
        elif lid not in S.NOT: err.append(("종류 판단이 없는 기능에 시설 유형 연결",lid,t))
for lid in set(S.K)|set(S.NOT):
    if lid not in leaves: err.append(("분류표에 없는 기능",lid))
print("검사 오류",len(err)); [print(e) for e in err]
assert not err
T["rules"]["kinds"]=("대안은 ① 같은 세부 종류 → ② 같은 종류 묶음(주민에게 먼저 물어본 뒤) → ③ 다른 묶음(주민이 따로 원할 때만) 순서로 찾는다. "
  "'여러 종류 겸업' 가게와 '가게별 확인 항목'은 실시간 조회(카카오 지도·블로그 후기·공공 자료)로 확인하고, 확인되지 않으면 '확인 안 됨'으로 표시하고 전화 확인을 안내한다. 실시간 조회 결과는 저장하지 않는다. "
  "'신청·문의 창구'(contact) 종류는 그 서비스를 직접 하는 곳이 아니므로, 추천할 때 반드시 '신청·문의할 곳'으로 안내하고 그곳에서 서비스를 받는다고 말하지 않는다.")
T["rules"]["eligibility"]=("이용 자격이 있는 세부 종류(예: 경로당은 65세 이상, 방문요양·주야간보호·요양원은 장기요양 등급, 직장어린이집은 직원 자녀, 학교는 배정)는 "
  "대화에서 주민의 자격이 확인된 경우에만 추천 목록에 넣는다. 확인되지 않으면 '이용 자격 확인 필요'로 따로 보여 주고 자격을 카드에 적는다.")
open(p,"w",encoding="utf-8").write(json.dumps(T,ensure_ascii=False,indent=1))
c=collections.Counter(str(l["kinds"]["sensitive"]) for l in leaves.values())
print("종류 구분",c["True"],"구분 불필요",c["False"],"업종 미연결",c["None"],"세부 기능",len(leaves))
print("세부 종류 수",sum(len(k["kinds"]) for l in leaves.values() if l["kinds"]["sensitive"] for k in l["kinds"]["groups"]))
for lid in ["P01.3.01","P07.2.01","P01.1.05"]:
    print(lid,[(g["name"],[(k["name"],k["stores"]) for k in g["kinds"]]) for g in leaves[lid]["kinds"]["groups"]][:6])
