# 용도지역(도시지역: 주거·상업·공업·녹지) 경계 받기 — 브이월드 공간정보 오픈API (LT_C_UQ111, 국토교통부 도시계획정보)
#  창업 참고의 상권 유형(주거지·상업지·공단·외곽)을 가리는 데 씀 (engine/trade_area.py). 대구광역시만 남김
#  쓰는 법: python pipeline/fetch_zoning.py   → data/raw/zoning/daegu_uq111.geojson
import os, json, urllib.request, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = open(os.path.join(ROOT, "settings", "vworld_key.txt"), encoding="utf-8").read().strip()
def page(layer, n):
    u = (f"https://api.vworld.kr/req/data?service=data&request=GetFeature&data={layer}&key={KEY}&geomFilter=BOX(128.35,35.60,128.80,36.33)"
         f"&format=json&size=1000&page={n}&geometry=true&attribute=true&domain=localhost&crs=EPSG:4326")
    r = json.load(urllib.request.urlopen(u, timeout=60))["response"]
    if r.get("status") != "OK": return [], 0
    return r["result"]["featureCollection"]["features"], int(r["page"]["total"])
feats = []; n = 1
while True:
    fs, total = page("LT_C_UQ111", n); feats += fs
    print("쪽", n, "/", total, len(fs))
    if n >= total or not fs: break
    n += 1; time.sleep(0.3)
keep = [f for f in feats if f["properties"].get("sido_name") == "대구광역시"]
json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": f["geometry"], "properties": {"용도지역": f["properties"]["uname"], "구군": f["properties"].get("sigg_name")}} for f in keep]},
          open(os.path.join(ROOT, "data", "raw", "zoning", "daegu_uq111.geojson"), "w", encoding="utf-8"), ensure_ascii=False)
import collections
print("대구", len(keep), collections.Counter(f["properties"]["uname"] for f in keep).most_common())
