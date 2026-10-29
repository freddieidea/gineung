# 공공데이터포털 '표준데이터'(전국 단위)를 받아 대구 것만 남겨 UTF-8 CSV로 저장. 사용: python fetch_standard.py 이름 PK [PK ...]
import sys, json, urllib.request, urllib.parse, csv, os, time
B="https://www.data.go.kr"; UA="Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
def get(url,params=None):
    if params: url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Referer":B+"/","X-Requested-With":"XMLHttpRequest"})
    return json.load(urllib.request.urlopen(req,timeout=120))
def fetch(name,pk):
    h=get(f"{B}/download/columList.json?pk={pk}&ext=CSV")
    cols=h["tableVO"]["colNmList"]; total=int(h["totalCount"]); kr=[c["columNm"] for c in h["columList"]]; en=[c["columCode"] for c in h["columList"]]
    rows=[]; page=1  # 이 서비스는 1쪽부터 시작
    while len(rows)<total:
        d=get(f"{B}/download/standard.json?publicDataPk={pk}",{"colNmList":cols,"totalCount":total,"svcTableNm":h["tableVO"]["svcTableNm"],"perPage":10000,"page":page})
        recs=d if isinstance(d,list) else (d.get("data") or d.get("list") or d.get("records"))
        if not isinstance(recs,list) or not recs: break
        rows+=recs; page+=1; time.sleep(0.3)
    return kr,en,rows,total,h.get("fileName")
if __name__=="__main__":
    name=sys.argv[1]
    for pk in sys.argv[2:]:
        kr,en,rows,total,fn=fetch(name,pk)
        print(name,pk,fn,"전체",total,"받음",len(rows),"열",kr[:12])
        if rows: print("예시 키",list(rows[0].keys())[:15])
        out=f"data/raw/public/{name}_전국.json"; json.dump({"pk":pk,"file":fn,"cols_kr":kr,"cols_en":en,"total":total,"rows":rows},open(out,"w",encoding="utf-8"),ensure_ascii=False)
