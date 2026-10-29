# 연결표 공통 마무리: 재검사 → 저장 → 검토 화면용 행 → 검토 화면(HTML) 갱신
import json, re
def finalize(M, T, L):
    leaf={}; cat_of={}
    for c in T["categories"]:
        for p in c["purposes"]:
            for l in p["leaves"]:
                leaf[l["id"]]=l["name"]; cat_of[l["id"]]=c["name"]
    assert M["taxonomy_version"]==T["version"]
    items={i["code"]:i for i in M["items"]}
    err=[]
    if not (len(M["items"])==len(L)==247 and set(items)==set(L)): err.append(("업종 수/코드 불일치",))
    for it in M["items"]:
        ids=[f["id"] for f in it["functions"]]
        if len(ids)!=len(set(ids)): err.append(("중복",it["code"]))
        for f in it["functions"]:
            if f["id"] not in leaf: err.append(("분류표에 없는 기능",it["code"],f["id"]))
            if f["role"] not in ("주","부") or f["confidence"] not in ("높음","보통","낮음"): err.append(("값 오류",it["code"]))
        if it["life_facility"]!=bool(it["functions"]): err.append(("생활시설-기능 불일치",it["code"]))
        if it["life_facility"] and not any(f["role"]=="주" for f in it["functions"]): err.append(("주 기능 없음",it["code"]))
    print("재검사 오류:",len(err),err[:10])
    assert not err
    json.dump(M,open("data/processed/industry_function_map.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
    E=json.load(open("data/processed/industry_examples.json",encoding="utf-8"))["examples"]
    rows=[]
    for it in M["items"]:
        x=L[it["code"]]
        rows.append({"code":it["code"],"name":x["소분류"],"group":f'{x["대분류"]} > {x["중분류"]}',"n":x["업소수"],"ex":[e["상호"] for e in E.get(it["code"],[])][:3],
          "life":it["life_facility"],"note":it.get("note",""),
          "f":[{"name":leaf[f["id"]],"cat":cat_of[f["id"]],"role":f["role"],"conf":f["confidence"],"reason":f["reason"]} for f in it["functions"]]})
    json.dump(rows,open("data/processed/industry_map_rows.json","w",encoding="utf-8"),ensure_ascii=False)
    life=[r for r in rows if r["life"]]
    stores=sum(r["n"] for r in life); allst=sum(r["n"] for r in rows)
    nfix=sum(1 for c in M["corrections"] if "출처" in c)
    h=open("design/industry_function_map.html",encoding="utf-8").read()
    i=h.find('<script id="d" type="application/json">'); j=h.find("</script>",i); assert i>0 and j>i
    h=h[:i]+'<script id="d" type="application/json">'+json.dumps(rows,ensure_ascii=False).replace("</","<\\/")+h[j:]
    box=(f"<b>자동 검사 결과</b> · 247개 업종 모두 분류됨(누락 0, 중복 0) · 분류표({T['version']}, 세부 기능 {len(leaf)}개)에 없는 기능 0건 · "
         f"별도 모델의 독립 점검으로 틀린 연결 6건 제거, 생활시설 판단 3건 수정 · 현장 판단과 전체 검토로 {nfix}건 수정 · "
         f"최종 재검사 오류 0건 · 대구 상가 {allst:,}곳 중 생활시설 업종 가게 {stores:,}곳<br>")
    h,k=re.subn(r'<b>자동 검사 결과</b>.*?<br>',lambda m:box,h,count=1,flags=re.S); assert k==1
    open("design/industry_function_map.html","w",encoding="utf-8").write(h)
    print("생활시설 업종",len(life),"가게",stores,"/",allst,"수정 기록",nfix,"세부 기능",len(leaf))
