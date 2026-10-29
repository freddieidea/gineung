# 심평원 '전국 병의원 및 약국 현황'(2026.6) 엑셀에서 대구 기관만 골라 CSV로 저장한다.
# 사용: python pipeline/extract_hira.py   (data/raw/hira/*.xlsx → data/raw/hira/daegu_*.csv)
import openpyxl, glob, csv, os, re
D="data/raw/hira"
def rows(f):
    ws=openpyxl.load_workbook(f,read_only=True).worksheets[0]
    it=ws.iter_rows(values_only=True); hdr=[h for h in next(it)]
    for r in it: yield dict(zip(hdr,r))
def name(f): return re.sub(r"^\d+\.|\(2026\.6\.\)\.xlsx$","",os.path.basename(f)).replace("의료기관별상세정보서비스_","")
files=sorted(glob.glob(f"{D}/*.xlsx"))
keys=set()
for f in files:
    if "병원정보서비스" in f or "약국정보서비스" in f or "시설정보" in f:
        for r in rows(f):
            if r.get("시도코드명")=="대구": keys.add(r["암호화요양기호"])
print("대구 기관", len(keys))
for f in files:
    out=f"{D}/daegu_{name(f)}.csv"; n=0
    with open(out,"w",newline="",encoding="utf-8") as fo:
        w=None
        for r in rows(f):
            if r.get("암호화요양기호") not in keys: continue
            r={k:v for k,v in r.items() if k}
            if w is None: w=csv.DictWriter(fo,fieldnames=list(r)); w.writeheader()
            w.writerow(r); n+=1
    print(out,n)
