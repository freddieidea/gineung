"""분류표 데이터(json)로 검토 화면(html)을 만든다. 맥 폴더 안에서만 작업해 동기화 문제를 없앤다."""
import json, hashlib
d=open("design/purpose_taxonomy.json",encoding="utf-8").read()
v=json.loads(d)["version"]
core=open("pipeline/templates/taxonomy_page.html",encoding="utf-8").read().replace("__DATA__",d.replace("</","<\\/"))
html='<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n</head>\n<body>\n'+core+'\n</body>\n</html>\n'
open("design/purpose_taxonomy.html","w",encoding="utf-8").write(html)
print("분류표 화면 생성:",v)
