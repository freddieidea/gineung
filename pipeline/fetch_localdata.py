# 행정안전부 지방행정 인허가 자료(file.localdata.go.kr)를 대구 9개 구·군별로 받아 UTF-8 CSV로 저장.
# 이미 받은 파일은 건너뛴다. 사용: python fetch_localdata.py [제한초]
import os, sys, time, csv, io, json, urllib.request, urllib.parse, concurrent.futures as cf
OUT="data/raw/localdata"; os.makedirs(OUT,exist_ok=True)
ORG={"중구":"3410000","동구":"3420000","서구":"3430000","남구":"3440000","북구":"3450000","수성구":"3460000","달서구":"3470000","달성군":"3480000","군위군":"5141000"}
SLUG={  # 생활기능과 관련된 인허가 업종
 "general_restaurants":"식품_일반음식점","rest_cafes":"식품_휴게음식점","bakeries":"식품_제과점영업","instant_food_processors":"식품_즉석판매제조가공업",
 "livestock_retail":"식품_축산판매업","other_food_retailers":"식품_식품판매업(기타)","health_functional_food_general_retailers":"식품_건강기능식품일반판매업",
 "group_meal_facilities":"식품_집단급식소","large_scale_retail_stores":"생활_대규모점포","over_the_counter_medicine_stores":"건강_안전상비의약품 판매업소",
 "tobacco_retailers":"기타_담배소매업","pay_as_you_throw_bag_retailers":"자원환경_쓰레기종량제봉투판매업","oil_retailers":"자원환경_석유판매업",
 "barber_shops":"생활_이용업","beauty_salons":"생활_미용업","laundries":"생활_세탁업","public_baths":"생활_목욕장업",
 "billiard_halls":"생활_당구장업","fitness_centers":"생활_체력단련장업","swimming_pools":"생활_수영장업","golf_practice_ranges":"생활_골프연습장업",
 "martial_arts_dojo":"생활_체육도장업","comprehensive_sports_facilities":"생활_종합체육시설업","dance_academies":"생활_무도학원업",
 "karaoke_rooms":"문화_노래연습장업","pc_bangs":"문화_인터넷컴퓨터게임시설제공업","video_viewing_rooms":"문화_비디오물감상실업","general_game_providers":"문화_일반게임제공업",
 "pharmacies":"건강_약국","clinics":"건강_의원","hospitals":"건강_병원","optical_shops":"건강_안경업","medical_device_sales_rental":"건강_의료기기판매(임대)업",
 "medical_related_businesses":"건강_의료유사업","postpartum_care":"건강_산후조리업",
 "animal_hospitals":"동물_동물병원","pet_grooming":"동물_동물미용업","animal_boarding":"동물_동물위탁관리업","animal_sales":"동물_동물판매업",
}
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
def one(slug,gu,org):
    path=f"{OUT}/{slug}__{gu}.csv"
    if os.path.exists(path) and os.path.getsize(path)>0: return (slug,gu,"있음",None)
    req=urllib.request.Request(f"https://file.localdata.go.kr/file/download/{slug}/info?"+urllib.parse.urlencode({"orgCode":org}),
        headers={"User-Agent":UA,"Referer":f"https://file.localdata.go.kr/file/{slug}/info"})
    try:
        with urllib.request.urlopen(req,timeout=90) as r:
            ct=r.headers.get("Content-Type",""); b=r.read()
        if "csv" not in ct: return (slug,gu,"실패",f"형식 {ct}")
        t=b.decode("cp949",errors="strict")
        rows=list(csv.reader(io.StringIO(t)))
        if not rows or "관리번호" not in rows[0]: return (slug,gu,"실패","머리줄 이상")
        tmp=path+".part"
        with open(tmp,"w",encoding="utf-8",newline="") as f: csv.writer(f).writerows(rows)
        os.replace(tmp,path); return (slug,gu,"받음",len(rows)-1)
    except UnicodeDecodeError as e: return (slug,gu,"실패","인코딩 "+str(e)[:60])
    except Exception as e: return (slug,gu,"실패",str(e)[:80])
if __name__=="__main__":
    LIMIT=float(sys.argv[1]) if len(sys.argv)>1 else 150; t0=time.time()
    jobs=[(s,g,o) for s in SLUG for g,o in ORG.items()]
    res=[]
    with cf.ThreadPoolExecutor(6) as ex:
        futs=[]
        for j in jobs:
            futs.append(ex.submit(one,*j))
        for f in cf.as_completed(futs, timeout=max(1,LIMIT-(time.time()-t0))):
            res.append(f.result())
    c={}
    for r in res: c[r[2]]=c.get(r[2],0)+1
    print(c); [print(r) for r in res if r[2]=="실패"][:20]
    done=sum(1 for s in SLUG for g in ORG if os.path.exists(f"{OUT}/{s}__{g}.csv"))
    print("완료",done,"/",len(jobs))
