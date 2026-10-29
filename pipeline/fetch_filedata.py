# 공공데이터포털 '파일데이터'를 받는다. 사용: python fetch_filedata.py 저장이름 PK [PK...]  (data/raw/public/에 원래 파일 이름으로 저장)
import sys, re, urllib.request, urllib.parse, os
UA="Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
def page(pk):
    r=urllib.request.Request(f"https://www.data.go.kr/data/{pk}/fileData.do",headers={"User-Agent":UA})
    return urllib.request.urlopen(r,timeout=60).read().decode("utf-8","replace")
def fetch(name,pk):
    h=page(pk); t=re.search(r"<title>([^<|]*)",h).group(1).strip()
    m=re.search(r"/cmm/cmm/fileDownload\.do\?atchFileId=(FILE_\d+)&fileDetailSn=(\d+)",h)
    if m: aid,sn=m.group(1),m.group(2)
    else:  # 두 단계 내려받기: 화면의 uddi로 파일 번호를 먼저 묻는다
        u=re.search(r"fn_fileDataDown\('\d+', '(uddi:[0-9a-f-]+)'",h)
        if not u: print(pk,t,"→ 내려받기 링크 없음 (로그인·API 전용일 수 있음)"); return
        q=f"https://www.data.go.kr/tcs/dss/selectFileDataDownload.do?publicDataDetailPk={u.group(1)}&publicDataPk={pk}&atchFileId=&fileDetailSn=1&publicDataTyCode=PR0051"
        r=urllib.request.Request(q,headers={"User-Agent":UA,"Referer":f"https://www.data.go.kr/data/{pk}/fileData.do"})
        j=urllib.request.urlopen(r,timeout=60).read().decode("utf-8","replace")
        a=re.search(r'"atchFileId":"(FILE_\d+)"',j)
        if not a: print(pk,t,"→ 파일 번호를 받지 못함"); return
        aid,sn=a.group(1),"1"
    url=f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={aid}&fileDetailSn={sn}&insertDataPrcus=N"
    r=urllib.request.Request(url,headers={"User-Agent":UA,"Referer":f"https://www.data.go.kr/data/{pk}/fileData.do"})
    with urllib.request.urlopen(r,timeout=170) as resp:
        cd=resp.headers.get("Content-Disposition",""); b=resp.read()
    fn=re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)',cd); fn=urllib.parse.unquote(fn.group(1)) if fn else f"{pk}.bin"
    fn=f"{name}__{pk}__{fn}".replace("/","_")
    open(os.path.join("data/raw/public",fn),"wb").write(b); print(pk,t,"→",fn,len(b),"바이트")
if __name__=="__main__":
    for pk in sys.argv[2:]: fetch(sys.argv[1],pk)
