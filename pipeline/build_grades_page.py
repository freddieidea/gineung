# 생활기능 등급표 화면 만들기 → design/생활기능_등급표.html (분류표의 등급과 근거를 그대로 보여 줌)
# '이전 등급'은 등급을 확정하기 전 값으로, data/work/grades_final.json에 남겨 둔 것을 씀
import json, os
T=json.load(open("design/purpose_taxonomy.json",encoding="utf-8")); assert T["version"]=="0.9-draft"
old={}
if os.path.exists("data/work/grades_final.json"):
    old={r["id"]:r["old"] for r in json.load(open("data/work/grades_final.json",encoding="utf-8"))["rows"]}
rows=[]
for c in T["categories"]:
    for p in c["purposes"]:
        for l in p["leaves"]:
            gb=l.get("grade_basis")
            rows.append(dict(id=l["id"],cat=c["name"],pur=p["name"],name=l["name"],desc=l["desc"],old=old.get(l["id"],l["grade"]),new=l["grade"],
                a=gb["public"] if gb else None,ab=l.get("public_basis",""),b=gb["weekly"] if gb else None,
                bb=(l.get("weekly_use","").split(" — ",1)[-1] if gb else l.get("weekly_use","")),note=(gb["note"] if gb else "현장 판단")))
assert all(r["new"] in ("필수","준필수","선택") for r in rows), "미확정 등급이 남아 있음"
data=json.dumps({"rows":rows,"src":T["grade_sources"]},ensure_ascii=False).replace("</","<\\/")
tpl=open("pipeline/templates/grades_page.html",encoding="utf-8").read()
n=len(rows); tpl=tpl.replace("세부 기능 109개",f"세부 기능 {n}개")
html=('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      '<style>[hidden]{display:none!important}body{margin:0}</style></head><body>'+tpl.replace("__DATA__",data)+'</body></html>')
open("design/생활기능_등급표.html","w",encoding="utf-8").write(html)
print("등급표 화면 생성:",n,"개 기능")
