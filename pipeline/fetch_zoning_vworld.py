# 대구 용도지역(브이월드 LT_C_UQ111: 주거·상업·공업·녹지): 산업단지(공업지역) 건물에 주민을 많이 두지 않으려고 씀 (build_pop_grid.py)
#  쓰는 법: python pipeline/fetch_zoning_vworld.py
import os, json, time, urllib.request, urllib.parse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = open(os.path.join(ROOT, "settings", "vworld_key.txt"), encoding="utf-8").read().strip()
X0, X1, Y0, Y1, D = 128.34, 128.80, 35.59, 36.33, 0.05
feats = {}
x = X0
while x < X1:
    y = Y0
    while y < Y1:
        page = 1
        while True:
            q = urllib.parse.urlencode({"service": "data", "request": "GetFeature", "data": "LT_C_UQ111", "key": KEY, "format": "json", "size": 1000, "page": page,
                                        "geomFilter": f"BOX({x:.3f},{y:.3f},{x + D:.3f},{y + D:.3f})", "domain": "localhost"})
            r = json.load(urllib.request.urlopen("https://api.vworld.kr/req/data?" + q, timeout=90))["response"]
            if r["status"] != "OK": break
            for f in r["result"]["featureCollection"]["features"]:
                if f["properties"].get("sido_name") == "대구광역시": feats[f["id"]] = {"type": "Feature", "properties": {"uname": f["properties"]["uname"]}, "geometry": f["geometry"]}
            if page >= int(r["page"]["total"]): break
            page += 1
        y += D
    x += D
out = os.path.join(ROOT, "data", "raw", "boundary", "daegu_zoning.geojson")
json.dump({"type": "FeatureCollection", "features": list(feats.values())}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
from collections import Counter
print(len(feats), Counter(f["properties"]["uname"] for f in feats.values()).most_common(12))
