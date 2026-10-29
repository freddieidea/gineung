# 창업 참고 상권 분석 (10/21 헌준님: 창업 컨설턴트가 보는 수준으로, 같은 시설이라도 공단·주거지 상권에 따라 중요도가 다름)
#  계산한 사실만 씀 (추정·지어낸 숫자 없음). 항목:
#   ① 상권 유형: 반경 500m 용도지역 비율 (국토교통부 도시계획정보, 브이월드 LT_C_UQ111 — pipeline/fetch_zoning.py)
#   ② 배후 수요: 반경 500m·1km 거주 인구, 어르신 비율 (100m 격자 인구)
#   ③ 접근성: 가장 가까운 지하철역, 반경 300m 버스 정류장 수·평일 운행 횟수
#   ④ 경쟁: 반경 1km 같은 업종 수·가장 가까운 거리 / 대신할 수 있는 업종 수(예: 식료품점에 대한 편의점)
#   ⑤ 집객 요인(업종별 핵심 조건): 약국 = 반경 500m 의원 수(처방전), 동네 의원 = 어르신 비율·대중교통, 식료품점 = 주거 인구
#   ⑥ 상권 활력: 반경 1km 최근 1년 인허가 개업·폐업 수 (같은 업종, 상권 전체)
#  적합도(높음·보통·낮음)는 아래 FIT 규칙으로 계산 → AI가 그 사실로 컨설턴트 관점 요약을 씀(구역마다 한 번, 사실이 바뀔 때만)
import os, json, datetime, hashlib
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_Z = None; _BUS = None; _SUB = None; _LD = None
def _zcls(u):
    u = str(u or "")
    if "주거" in u: return "주거"
    if "상업" in u: return "상업"
    if "공업" in u: return "공업"
    if "녹지" in u: return "녹지"
    return "기타"
def _zones():
    global _Z
    if _Z is None:
        p = os.path.join(ROOT, "data", "raw", "zoning", "daegu_uq111.geojson"); _Z = []
        if os.path.exists(p):
            for f in json.load(open(p, encoding="utf-8"))["features"]:
                if not str(f["properties"].get("용도지역") or "").strip(): continue   # (10/29) 이름 없는 겹친 경계(산업단지 등)가 먼저 잡혀 공업지역이 '기타'로 보이던 것
                g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
                rings = [np.asarray(r, dtype=float)[:, :2] for poly in polys for r in poly]
                a = np.vstack(rings); _Z.append((_zcls(f["properties"].get("용도지역")), rings, a.min(0), a.max(0)))
    return _Z
_ZN = None
def zone_names(xs, ys):
    """점마다 용도지역 이름(제2종일반주거지역·일반공업지역 등). 어느 용도지역에도 없으면 '' """
    global _ZN
    if _ZN is None:
        p = os.path.join(ROOT, "data", "raw", "zoning", "daegu_uq111.geojson"); _ZN = []
        if os.path.exists(p):
            for f in json.load(open(p, encoding="utf-8"))["features"]:
                nm = str(f["properties"].get("용도지역") or "").strip()
                if not nm: continue
                g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
                rings = [np.asarray(r, dtype=float)[:, :2] for poly in polys for r in poly]
                a = np.vstack(rings); _ZN.append((nm, rings, a.min(0), a.max(0)))
    out = []
    for x, y in zip(xs, ys):
        out.append(next((nm for nm, rings, lo, hi in _ZN if lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1] and _inside(x, y, rings)), ""))
    return out
def _inside(x, y, rings):
    c = False
    for r in rings:
        x1, y1 = r[:, 0], r[:, 1]; x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
        m = (y1 > y) != (y2 > y)
        if m.any():
            xs = x1[m] + (y - y1[m]) * (x2[m] - x1[m]) / (y2[m] - y1[m])
            if np.count_nonzero(xs > x) % 2: c = not c
    return c
def zone_mix(lon, lat, r=500, step=100):
    """반경 r 안 100m 간격 점들의 용도지역 비율. 어느 도시지역에도 안 들어가면 '비도시'(관리·농림 등)"""
    Z = _zones(); pts = []
    for dx in range(-r, r + 1, step):
        for dy in range(-r, r + 1, step):
            if dx * dx + dy * dy <= r * r: pts.append((lon + dx / 90200, lat + dy / 110540))
    cnt = {}
    near = [z for z in Z if z[2][0] - 0.01 <= lon <= z[3][0] + 0.01 and z[2][1] - 0.01 <= lat <= z[3][1] + 0.01]
    for x, y in pts:
        k = next((c for c, rings, lo, hi in near if lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1] and _inside(x, y, rings)), "비도시")
        cnt[k] = cnt.get(k, 0) + 1
    n = len(pts); return {k: round(v / n, 2) for k, v in sorted(cnt.items(), key=lambda t: -t[1])}
def area_type(mix, pop500=0):
    """용도지역 비율로 상권 유형. 녹지·비도시가 대부분이어도 주민이 모여 살면(반경 500m 1,000명 이상) 녹지 안 주거지(취락·개발제한구역 마을)"""
    g = lambda k: mix.get(k, 0)
    if g("공업") >= 0.35: return "공단(공업지역)"
    if g("상업") >= 0.30: return "상업지(중심 상권)"
    if g("주거") >= 0.50: return "주거지"
    if g("녹지") + g("비도시") >= 0.60: return "녹지 안 주거지(취락)" if pop500 >= 1000 else "외곽·농촌"
    return "혼합(주거·상업 등)"
def _bus():
    global _BUS, _SUB
    if _BUS is None:
        b = pd.read_csv(os.path.join(ROOT, "data", "processed", "bus_stops.csv"), dtype={"정류소ID": str})
        _BUS = b[["경도", "위도", "평일운행횟수"]].astype(float).dropna(subset=["경도", "위도"]).values
        s = pd.read_csv(os.path.join(ROOT, "data", "processed", "subway_stations.csv"))
        _SUB = list(zip(s["역"], s["노선"], s["경도"].astype(float), s["위도"].astype(float)))
    return _BUS, _SUB
def _dm(lon, lat, X, Y): return np.hypot((np.asarray(X, float) - lon) * 90200, (np.asarray(Y, float) - lat) * 110540)
SLUG = {"약국": ["pharmacies"], "동네 의원": ["clinics"], "식료품점": ["livestock_retail", "other_food_retailers", "large_scale_retail_stores"]}
RETAIL = {"general_restaurants", "rest_cafes", "beauty_salons", "barber_shops", "pharmacies", "clinics", "bakeries", "laundries", "livestock_retail", "other_food_retailers",
          "optical_shops", "fitness_centers", "public_baths", "karaoke_rooms", "pc_bangs", "tobacco_retailers"}
def _ld():
    global _LD
    if _LD is None:
        d = pd.read_csv(os.path.join(ROOT, "data", "processed", "localdata_daegu.csv"), dtype=str, usecols=["slug", "인허가일자", "폐업일자", "경도", "위도"])
        d = d[d["slug"].isin(RETAIL | {s for v in SLUG.values() for s in v})].copy()
        d["x"] = pd.to_numeric(d["경도"], errors="coerce"); d["y"] = pd.to_numeric(d["위도"], errors="coerce"); _LD = d.dropna(subset=["x", "y"])
    return _LD
def activity(lon, lat, label, r=1000):
    d = _ld(); m = _dm(lon, lat, d["x"].values, d["y"].values) <= r; d = d[m]
    since = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    op = d["인허가일자"].fillna("") >= since; cl = d["폐업일자"].fillna("") >= since
    own = d["slug"].isin(SLUG.get(label, []))
    return {"상권_개업": int(op.sum()), "상권_폐업": int(cl.sum()), "업종_개업": int((op & own).sum()), "업종_폐업": int((cl & own).sum()), "업종_인허가자료": bool(SLUG.get(label))}
def facts(G, label, lids, lon, lat):
    """구역 중심(가장 붐비는 빈 칸 또는 폐업 자리)의 상권 사실"""
    E = G.cm.engine(); C = G.cm._C
    d = _dm(lon, lat, C.lon, C.lat); p1 = float(C.pop[d <= 1000].sum()); p5 = float(C.pop[d <= 500].sum()); e1 = float(C.pop65[d <= 1000].sum())
    mix = zone_mix(lon, lat); typ = area_type(mix, p5)
    B, S = _bus(); db = _dm(lon, lat, B[:, 0], B[:, 1]); near_b = db <= 300
    sub = min(((float(_dm(lon, lat, [x], [y])[0]), f"{n}역({l})") for n, l, x, y in S), default=(None, None))
    def provs(broad):
        P = sorted({p for l in lids for p in G._prov_all(l, broad)})
        X = E.F.loc[[p for p in P if p in E.F.index], ["x", "y"]].astype(float).dropna().values
        return _dm(lon, lat, X[:, 0], X[:, 1]) if len(X) else np.array([])
    ds, dbd = provs(False), provs(True)
    clin = None
    if label == "약국":
        X = E.F.loc[[p for p in G._prov_all("P03.1.01") if p in E.F.index], ["x", "y"]].astype(float).dropna().values
        clin = int((_dm(lon, lat, X[:, 0], X[:, 1]) <= 500).sum()) if len(X) else 0
    f = {"상권유형": typ, "용도지역_비율": mix, "배후인구_500m": int(round(p5)), "배후인구_1km": int(round(p1)), "어르신비율_1km": round(e1 / p1, 2) if p1 else None,
         "지하철역": sub[1] if sub[0] is not None and sub[0] <= 800 else None, "지하철역_m": int(sub[0]) if sub[0] is not None and sub[0] <= 800 else None,
         "버스정류장_300m": int(near_b.sum()), "버스운행_300m": (int(np.nansum(B[near_b, 2])) or None) if near_b.any() else 0,   # 정류장은 있는데 운행 자료가 없으면 None (0회로 오해하지 않게)
         "같은업종_1km": int((ds <= 1000).sum()), "같은업종_최근접_m": int(ds.min()) if len(ds) else None,
         "대체업종_1km": int(((dbd <= 1000).sum()) - (ds <= 1000).sum()), **activity(lon, lat, label)}
    if clin is not None: f["의원_500m"] = clin
    return f
# 업종별 적합도 규칙 (사실 → 가점·감점, 근거를 함께 남김). 값을 바꾸면 화면과 AI 요약이 같이 바뀜
def fit(label, f):
    s, why = 0, []
    t = f["상권유형"]
    if t == "공단(공업지역)": s -= 2; why.append("공단 상권: 거주 주민이 적어 생활 시설 수요가 낮음")
    elif t == "주거지": s += 1; why.append("주거지 상권: 매일 쓰는 생활 시설 수요가 꾸준함")
    elif t == "상업지(중심 상권)": why.append("상업지: 유동 인구는 많으나 임대료·경쟁 부담")
    p = f["배후인구_1km"]
    if p >= 5000: s += 2; why.append(f"반경 1km 거주 {p:,}명")
    elif p >= 2000: s += 1; why.append(f"반경 1km 거주 {p:,}명")
    elif p < 1000: s -= 1; why.append(f"반경 1km 거주 {p:,}명으로 적음")
    if label == "약국":
        c = f.get("의원_500m", 0)
        if c >= 3: s += 2; why.append(f"반경 500m 의원 {c}곳: 처방전 수요")
        elif c == 0: s -= 2; why.append("반경 500m 의원 없음: 처방전 수요 약함")
    if label == "동네 의원":
        if (f["어르신비율_1km"] or 0) >= 0.25: s += 1; why.append(f"어르신 비율 {round((f['어르신비율_1km'] or 0) * 100)}%: 외래 수요 높음")
        if f["지하철역"] or (f["버스운행_300m"] or 0) >= 300: s += 1; why.append("대중교통 접근 양호")
    if label == "식료품점" and f["대체업종_1km"] >= 8: s -= 1; why.append(f"편의점 등 대신할 업종 {f['대체업종_1km']}곳: 수요 분산")
    if f["같은업종_1km"] >= 10: s -= 2; why.append(f"반경 1km 같은 업종 {f['같은업종_1km']}곳: 경쟁 심함")
    elif f["같은업종_1km"] >= 3: s -= 1; why.append(f"반경 1km 같은 업종 {f['같은업종_1km']}곳")
    lv = "높음" if s >= 3 else "보통" if s >= 1 else "낮음"
    return {"적합도": lv, "점수": s, "근거": why}

# ── AI 요약 (컨설턴트 관점, 사실로만) ──
SYS = ("너는 대구 지역 소상공인 창업 컨설턴트다. 주어진 상권 사실(계산값)만 근거로, 이 자리에 해당 업종을 여는 것의 장단점을 공공기관 보고서 개조식으로 쓴다. "
       "숫자는 주어진 값만 쓰고 새 숫자·매출·임대료를 지어내지 않는다. 상권 유형(주거지·공단·상업지·외곽)에 따라 같은 업종의 중요도가 어떻게 다른지 반드시 짚는다.")
TOOL = {"name": "write", "description": "상권 요약", "input_schema": {"type": "object", "properties": {
    "summary": {"type": "string", "description": "한 줄 결론 (40자 안, 개조식 명사형)"},
    "strengths": {"type": "array", "items": {"type": "string"}, "maxItems": 3, "description": "강점, 각 30자 안"},
    "cautions": {"type": "array", "items": {"type": "string"}, "maxItems": 3, "description": "유의점, 각 30자 안"}}, "required": ["summary", "strengths", "cautions"]}}
P_CACHE = os.path.join(ROOT, "data", "gov", "trade_judged.json")
def summarize(rows, client):
    """rows: [{id, 시설, 구군, 행정동, 상권:{...}, 적합:{...}}] → {id: {요약, 강점, 유의점}}. 사실이 같으면 다시 부르지 않음"""
    cache = json.load(open(P_CACHE, encoding="utf-8")) if os.path.exists(P_CACHE) else {}
    out = {}
    for r in rows:
        key = hashlib.md5(json.dumps([r["시설"], r["상권"], r["적합"]], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if cache.get(r["id"], {}).get("key") == key: out[r["id"]] = cache[r["id"]]["글"]; continue
        if client is None: continue
        try:
            m = client.messages.create(model="claude-sonnet-5-5", max_tokens=600, system=SYS, tools=[TOOL],
                                       messages=[{"role": "user", "content": json.dumps({"업종": r["시설"], "위치": f"{r['구군']} {r['행정동']}", "상권_사실": r["상권"], "적합도_계산": r["적합"]}, ensure_ascii=False)}])
            try:
                from chat import log_usage; log_usage("claude-sonnet-5-5", m.usage, "창업 상권 요약")
            except Exception: pass
            x = next(b.input for b in m.content if getattr(b, "type", "") == "tool_use")
            g = {"요약": str(x.get("summary", "")), "강점": [str(t) for t in x.get("strengths", [])][:3], "유의점": [str(t) for t in x.get("cautions", [])][:3]}
            cache[r["id"]] = {"key": key, "글": g}; out[r["id"]] = g
        except Exception as ex: print("상권 요약 실패:", str(ex)[:120]); continue
    json.dump(cache, open(P_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out
