# 국립중앙의료원 E-GEN: 대구 약국·병의원 요일별 운영시간 받기 (공공데이터, 저장 가능)
#  사용: python pipeline/fetch_egen.py → data/raw/public/egen_약국_대구_YYYYMMDD.json, egen_병의원_대구_YYYYMMDD.json
import urllib.request, urllib.parse, json, datetime, os, time
K = open("settings/datagokr_pharmacy_key.txt").read().strip()
API = {"약국": "B552657/ErmctInsttInfoInqireService/getParmacyListInfoInqire", "병의원": "B552657/HsptlAsembySearchService/getHsptlMdcncListInfoInqire"}
day = datetime.date.today().strftime("%Y%m%d")
for name, path in API.items():
    items, page = [], 1
    while True:
        u = f"https://apis.data.go.kr/{path}?" + urllib.parse.urlencode({"serviceKey": K, "Q0": "대구광역시", "pageNo": page, "numOfRows": 1000, "_type": "json"})
        for t in range(3):
            try: d = json.loads(urllib.request.urlopen(u, timeout=40).read().decode("utf-8")); break
            except Exception as e:
                if t == 2: raise
                time.sleep(2)
        b = d["response"]["body"]; it = (b.get("items") or {}).get("item") or []
        if isinstance(it, dict): it = [it]
        items += it; total = int(b.get("totalCount") or 0)
        print(name, "쪽", page, "받음", len(items), "/", total)
        if len(items) >= total or not it: break
        page += 1
    p = f"data/raw/public/egen_{name}_대구_{day}.json"
    json.dump({"받은날": day, "출처": "국립중앙의료원 " + ("전국 약국 정보 조회 서비스" if name == "약국" else "전국 병·의원 찾기 서비스"), "items": items}, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    print("저장", p, len(items))
