# 대구 건물(도로명주소 건물, 브이월드 LT_C_SPBD)을 받아 '사람이 사는 곳'을 더 정확히 잡는 데 씀 (10/19)
#  전에는 행정동 인구를 가게·버스 정류장 250m 안에 고르게 나눠, 산속 정류장·산업단지 가게 근처에도 사람이 많은 것처럼 잡혔음
#  → 건물 바닥 면적 × 층수(연면적 어림)에 비례해 나눔 (build_pop_grid.py)
#  받는 것: 건물마다 중심점(경도·위도), 바닥 면적(m²), 지상 층수. 2km 칸으로 나눠 받고, 받은 칸은 다시 받지 않음(이어 받기)
#  쓰는 법: python pipeline/fetch_buildings_vworld.py [최대초]
import os, sys, json, time, csv, urllib.request, urllib.parse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = open(os.path.join(ROOT, "settings", "vworld_key.txt"), encoding="utf-8").read().strip()
OUT = os.path.join(ROOT, "data", "raw", "buildings"); os.makedirs(OUT, exist_ok=True)
DONE = os.path.join(OUT, "done_tiles.txt"); CSV = os.path.join(OUT, "daegu_buildings.csv")
LIMIT = float(sys.argv[1]) if len(sys.argv) > 1 else 160
X0, X1, Y0, Y1, D = 128.34, 128.80, 35.59, 36.33, 0.02   # 대구(군위 포함) 둘레
KX, KY = 90200.0, 110540.0
def area_centroid(geom):
    best = None; tot = 0.0; cx = cy = 0.0
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        ring = poly[0]; a = 0.0; sx = sy = 0.0
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            c = (x1 * KX) * (y2 * KY) - (x2 * KX) * (y1 * KY); a += c; sx += (x1 + x2) * c; sy += (y1 + y2) * c
        if abs(a) < 1e-9: continue
        a2 = a / 2; tot += abs(a2); cx += sx / (6 * a2) * abs(a2); cy += sy / (6 * a2) * abs(a2)
    return (cx / tot, cy / tot, tot) if tot > 0 else (None, None, 0)
done = set(open(DONE).read().split()) if os.path.exists(DONE) else set()
new = not os.path.exists(CSV)
fh = open(CSV, "a", newline="", encoding="utf-8"); w = csv.writer(fh)
if new: w.writerow(["bd_mgt_sn", "경도", "위도", "바닥면적", "층수", "구군"])
t0 = time.time(); n_tiles = 0; n_bld = 0
xs = [round(X0 + i * D, 4) for i in range(int((X1 - X0) / D) + 1)]; ys = [round(Y0 + j * D, 4) for j in range(int((Y1 - Y0) / D) + 1)]
for x in xs:
    for y in ys:
        key = f"{x},{y}"
        if key in done: continue
        if time.time() - t0 > LIMIT: break
        page = 1; rows = []
        while True:
            q = urllib.parse.urlencode({"service": "data", "request": "GetFeature", "data": "LT_C_SPBD", "key": KEY, "format": "json", "size": 1000, "page": page,
                                        "geomFilter": f"BOX({x},{y},{round(x + D, 4)},{round(y + D, 4)})", "domain": "localhost"})
            for k in range(3):
                try: r = json.load(urllib.request.urlopen("https://api.vworld.kr/req/data?" + q, timeout=60)); break
                except Exception as ex: time.sleep(2); r = None
            if r is None: raise SystemExit(f"받지 못함: {key}")
            res = r["response"]
            if res["status"] == "NOT_FOUND": break
            if res["status"] != "OK": raise SystemExit(f"오류 {key}: {res}")
            for f in res["result"]["featureCollection"]["features"]:
                p = f["properties"]
                if p.get("sido") != "대구광역시": continue
                cx, cy, a = area_centroid(f["geometry"])
                if cx is None: continue
                if not (x <= cx < x + D and y <= cy < y + D): continue   # 칸 경계에 걸친 건물은 중심점이 든 칸에서만
                rows.append([p.get("bd_mgt_sn"), round(cx, 6), round(cy, 6), round(a, 1), int(p.get("gro_flo_co") or 0), p.get("sigungu")])
            if page >= int(res["page"]["total"]): break
            page += 1
        w.writerows(rows); fh.flush(); n_bld += len(rows)
        with open(DONE, "a") as d: d.write(key + "\n")
        done.add(key); n_tiles += 1
    else: continue
    break
fh.close()
print(f"이번에 {n_tiles}칸, 건물 {n_bld}개 | 받은 칸 {len(done)}/{len(xs) * len(ys)}")
