# 생활 서비스 공백 지역 (10/21 헌준님): 폐업과 상관없이, 생활 필수 시설이 걸어서 기준 거리의 2배 안에 하나도 없는 주민이 모여 사는 곳
#  지자체 보고(긴급·주의)와 따로: 공개 '기능 공백 현황'의 기본 자료. 계산만 (언어 모델 없음, 비용 없음)
#  보수적으로: 그 일을 하는지 모르는 근처 가게(예: 채소를 파는지 모르는 동네 슈퍼)까지 대신 갈 곳으로 넣고도 비는 곳만
#  기능: 식료품(신선식품·가공식품 판매처 모두) / 약국(처방약 조제) / 동네 의원(1차 진료과·보건기관)
import numpy as np
GROUPS = [("식료품점", ["P01.1.01", "P01.1.02"], "P01.1.02"), ("약국", ["P03.2.01"], "P03.2.01"), ("동네 의원", ["P03.1.01"], "P03.1.01"),
          ("공원", ["P10.1.04"], "P10.1.04")]   # (10/26) 공원: 도보 2km 안에 공원(근린·어린이·소공원)이 하나도 없는 구역
#  공공 체육시설의 상시 부재는 아직 넣지 않음: 공원 운동시설·학교 개방 시설 자료가 빠져 있어 구역이 실제보다 크게 잡힘(시험 계산 59개 동네·35만 명). 자료 보완 뒤 추가.
#  공공 체육시설이 문을 닫아 생긴 공백(폐쇄 영향)은 지금 시설 기준으로 재므로 아래 unified에서 넣음
SP_LID = {"공공 체육시설": "G:공공체육", "공원": "P10.1.04"}
PARK_DATA_GAP = {"군위군"}   # 공원 자료에 소공원 3곳만 있음 (2023년 대구 편입 뒤 도시공원 표준데이터 미반영 추정)
FACTOR = 2.0                 # 기준 거리의 2배 (걸어서 '아예 없음' 수준)
MIN_POP = {"동": 100, "읍": 30, "면": 30}   # 동네마다 이만큼 넘게 비어야 올림
# (10/29 헌준님: 월성2동 공백 구역이 사실은 성서공단) 주민 격자는 행정동 인구를 건물 연면적에 나눈 추정이라, 큰 공장 건물에도 주민이 조금씩 잡힘.
#  일반·전용공업지역 칸에는 주민이 거의 살지 않으므로 '원래 시설이 없는 구역(상시 부재)'의 주민으로 세지 않음 (준공업지역은 주거가 섞여 셈)
NO_LIVE = {"일반공업지역", "전용공업지역"}
_ZC = {}
def zone_of(C, idx):
    """칸 번호 → 용도지역 이름 (칸마다 한 번만 계산해 둠)"""
    import trade_area as TA, os
    if not _ZC:
        zp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "processed", "cell_zone.npy")
        if os.path.exists(zp):
            zn = np.load(zp)
            if len(zn) == len(C.lon): _ZC.update({i: str(v) for i, v in enumerate(zn)})
    idx = np.asarray(idx); need = [int(i) for i in idx if int(i) not in _ZC]
    if need:
        for i, nm in zip(need, TA.zone_names(C.lon[need].astype(float), C.lat[need].astype(float))): _ZC[i] = nm
    return np.array([_ZC[int(i)] for i in idx], dtype=object)
def livable(C, m):
    """마스크 m에서 일반·전용공업지역 칸을 뺀 마스크"""
    if getattr(C, "factory_cells", None) is not None: return m & ~C.factory_cells   # 격자를 불러올 때 칸별 용도지역을 이미 봄 (engine/impact.py)
    ii = np.where(m)[0]
    if not len(ii): return m
    z = zone_of(C, ii); out = m.copy(); out[ii[np.isin(z, list(NO_LIVE))]] = False
    return out

def compute(G):
    E = G.cm.engine(); C = G.cm._C
    names = np.array([str(x) for x in C.hjd_name]); out = []
    gus = getattr(C, "hjd_gu", None)
    for label, lids, std_lid in GROUPS:
        std = G._std(std_lid)
        if not std: continue
        lim_m = std[0] * FACTOR
        P = sorted({p for l in lids for p in G._prov_all(l, True)})   # 넓게 (모르는 곳까지)
        PX = E.F.loc[[p for p in P if p in E.F.index], ["x", "y"]].astype(float).dropna().values
        d = C.dist([E.walk.snap.get(p) for p in P if E.walk.snap.get(p)], limit=lim_m * 3 + 2000)
        empty = ~(d <= lim_m) & (C.pop > 0)
        for h in np.unique(C.hjd[empty]):
            m = empty & (C.hjd == h); nm = str(names[h]); area = "면" if nm.endswith("면") else "읍" if nm.endswith("읍") else "동"
            if float(C.pop[m].sum()) < MIN_POP[area]: continue
            m = livable(C, m)   # 공장 지대 칸은 빼고
            pop = float(C.pop[m].sum())
            if pop < MIN_POP[area]: continue
            if label == "공원" and (area == "면" or (gus is not None and str(gus[h]) in PARK_DATA_GAP)): continue   # 도시공원 기준은 도시지역(동·읍) 기준이라 면은 빼고, 공원 자료가 빠진 군위군도 자료 보완 전까지 뺌
            dist = d[m]; fin = np.isfinite(dist); w = C.pop[m]
            med = float(np.median(np.repeat(dist[fin], np.maximum(1, np.round(w[fin] / max(1, w[fin].mean())).astype(int))))) if fin.any() else None
            # 밀집 수요: 비어 있는 칸 가운데 한 곳을 중심으로 반경 1km 안 주민이 가장 많은 값 (흩어진 마을과 모여 사는 단지를 구분 — 창업 참고)
            ii = np.where(m)[0]; xy = np.c_[C.lon[ii] * 90200, C.lat[ii] * 110540]
            try:
                from scipy.spatial import cKDTree
                T = cKDTree(xy); dens = np.array([C.pop[ii][T.query_ball_point(p0, 1000)].sum() for p0 in xy]) if len(ii) <= 4000 else np.array([pop])
                j = int(np.argmax(dens)); dense = float(dens[j]); cx, cy = float(C.lon[ii][j]), float(C.lat[ii][j]); walk_j = float(d[ii][j])
            except Exception: dense, cx, cy, walk_j = pop, None, None, float("nan")
            straight = int(np.hypot((PX[:, 0] - cx) * 90200, (PX[:, 1] - cy) * 110540).min()) if (cx is not None and len(PX)) else None   # 가장 붐비는 칸에서 최근접 시설까지 직선 (강·도로로 돌아가는 곳 구분)
            out.append({"구군": str(gus[h]) if gus is not None else "", "행정동": nm, "생활권": area, "밀집수요": int(round(dense)), "최근접_직선_m": straight, "최근접_도보_m": int(walk_j) if np.isfinite(walk_j) else None, "기능": label, "기준_m": int(lim_m), "주민": int(round(pop)), "65세이상": int(round(float(C.pop65[m].sum()))),
                        "가장가까운곳_m": int(med) if med is not None else None, "잰거리_m": int(lim_m * 3 + 2000), "밀집_경도": cx, "밀집_위도": cy,
                        "경도": float(np.average(C.lon[m], weights=w)) if hasattr(C, "lon") else None, "위도": float(np.average(C.lat[m], weights=w)) if hasattr(C, "lat") else None})
    return sorted(out, key=lambda r: (-r["주민"]))

# ── 공개 화면 한 목록 (10/21 헌준님: 공백 지역·폐업 보고·창업 참고를 하나로, 구역을 색칠) ──
#  행 = 동네 × 시설. 원인: '상시 부재'(도보 기준 거리 2배 안에 없음) 또는 '폐업 영향'(최근 폐업으로 도보 기준 거리 안에서 사라짐: 지자체 보고 또는 창업 참고로 판단된 곳)
#  표시: 최근 폐업(그 동네 같은 시설 최근 6개월 폐업) · 지자체 보고 · 창업 참고
LABEL_OF = {l: lab for lab, lids, _ in GROUPS for l in lids}
CAPTURE = {"식료품점": 1000, "약국": 2000, "동네 의원": 1500}   # 상시 부재 구역의 창업 참고: 반경 1km 밀집 수요가 이만큼 넘을 때 (약국·의원은 전국 평균 시설당 인구 수준, 식료품점은 보수적으로). 동일 시설이 도보 2km 안에 없어 경쟁이 구조적으로 낮음
def _days(d):
    import datetime
    try: return (datetime.date.today() - datetime.date.fromisoformat(str(d)[:10])).days
    except Exception: return None
def _trade(G, label, lids, lon, lat):
    """상권 분석 (engine/trade_area.py): 사실 + 적합도. 실패하면 None (창업 참고를 계산만으로 올리지 않음)"""
    try:
        import trade_area as TA
        if lon is None or lat is None: return None
        f = TA.facts(G, label, lids, float(lon), float(lat)); return {"상권": f, "적합": TA.fit(label, f)}
    except Exception: return None
LIDS_OF = {lab: lids for lab, lids, _ in GROUPS}
PUBLIC_LABELS = {"공원", "공공 체육시설"}
def unified(G, out, its, client=None):
    reported = {r["fid"] for r in out.get("기능공백", []) if r.get("상태") == "보고"}
    recent = []
    for it in its:
        ds = _days(it["시설"].get("폐업일자"))
        if ds is None or ds > 180: continue
        labs = {LABEL_OF[f["기능"]] for f in it["분석"].get("기능", []) if f["기능"] in LABEL_OF}
        if labs: recent.append((it, labs))
    rows = []
    for r in out.get("공백지역", []):
        rel = [{"상호": it["시설"]["상호"], "업종": it["시설"]["업종"], "폐업일자": it["시설"].get("폐업일자"), "보고": it["fid"] in reported}
               for it, labs in recent if r["기능"] in labs and it["분석"].get("행정동") == r["행정동"] and it["시설"].get("구군") == r["구군"]][:3]
        cap = (r.get("밀집수요") or 0) >= CAPTURE.get(r["기능"], 2000) and r["기능"] not in PUBLIC_LABELS   # (10/29) 공원·공공 체육시설은 창업 대상이 아님 (지자체 조성·예산 검토 몫)
        ta = _trade(G, r["기능"], LIDS_OF.get(r["기능"], []), r.get("밀집_경도") or r.get("경도"), r.get("밀집_위도") or r.get("위도")) if cap else None
        ok = bool(cap and ta and ta["적합"]["적합도"] != "낮음")   # 수요가 있어도 상권이 맞지 않으면(예: 공단 상권의 약국) 창업 참고로 올리지 않음
        rows.append(dict(r, id=f"상시|{r['기능']}|{r['구군']}|{r['행정동']}", 원인="상시 부재", 시설=r["기능"], 최근접_m=r.get("최근접_도보_m"), 관련폐업=rel,
                         보고=any(x["보고"] for x in rel), 상권=(ta or {}).get("상권"), 적합=(ta or {}).get("적합"),
                         창업참고=({"근거": f"도보 {r['기준_m'] / 1000:g}km 내 동일 시설 없음 · 반경 1km 밀집 수요 {r['밀집수요']:,}명", "적합도": ta["적합"]["적합도"]} if ok else None)))
    biz = {(r["fid"], r.get("기능id")): r for r in out.get("창업참고", [])}
    for g in out.get("기능공백", []):
        if g.get("상태") != "보고": continue
        e = g.get("영향") or {}; b = biz.pop((g["fid"], g.get("기능id")), None); dn = str(g.get("행정동") or "")
        rows.append({"id": f"폐업|{g['fid']}|{g.get('기능id')}", "원인": "폐업 영향", "구군": g["구군"], "행정동": dn, "생활권": "면" if dn.endswith("면") else "읍" if dn.endswith("읍") else "동",
                     "시설": g["기능"], "기준_m": e.get("기준_m"), "주민": e.get("주민") or e.get("이용자") or 0, "65세이상": e.get("65세이상") or 0,
                     "최근접_m": e.get("거리_후_m"), "잰거리_m": e.get("잰거리_m"), "관련폐업": [{"상호": g["상호"], "업종": g["업종"], "폐업일자": g.get("폐업일자"), "보고": True}],
                     "보고": True, "창업참고": ({"근거": b["까닭"]} if b else None), "경도": g.get("경도"), "위도": g.get("위도"), "폐업위치": True})
    for (fid, lid), b in biz.items():   # 보고는 아니지만 AI 상권 판단으로 창업 참고가 된 폐업
        dn = str(b.get("행정동") or "")
        rows.append({"id": f"폐업|{fid}|{lid}", "원인": "폐업 영향", "구군": b["구군"], "행정동": dn, "생활권": b.get("생활권"), "시설": b["기능"], "기준_m": b.get("기준_m"),
                     "주민": b.get("경쟁없는_수요") or 0, "65세이상": b.get("그중_65세이상") or 0, "최근접_m": ((b.get("가장가까운_같은업종") or [{}])[0]).get("직선_m"), "잰거리_m": None,
                     "관련폐업": [{"상호": b["상호"], "업종": b["업종"], "폐업일자": b.get("폐업일자"), "보고": False}], "보고": False,
                     "창업참고": {"근거": b["까닭"], "동일업종": b.get("기준_안_같은업종")}, "경도": b.get("경도"), "위도": b.get("위도"), "폐업위치": True})
    # (10/26 헌준님) 공공 체육시설·공원이 문을 닫아 생긴 공백: 보고(긴급·주의)뿐 아니라 '관찰'(공백은 있으나 보고할 만큼은 아님)도 구역으로 보여 줌 — 원인이 무엇이든 구역에 공백이 있으면 기능 공백
    have = {r["id"] for r in rows}
    for gu_, v_ in (out.get("구군") or {}).items():
        for r_, rep in [(x, True) for x in v_.get("항목", [])] + [(x, False) for x in v_.get("보고안함", []) if x.get("관찰")]:
            k_ = G.sp_kind(r_["fid"]) if hasattr(G, "sp_kind") else None
            if not k_: continue
            lid = "G:공공체육" if G._is_sport(r_["fid"]) else "P10.1.04"
            zid = f"폐업|{r_['fid']}|{lid}"
            if zid in have: continue
            try: sv = G._severe(r_["fid"], lid) or {}
            except Exception: sv = {}
            if not sv.get("밀려난주민"): continue
            dn = str(r_.get("행정동") or "")
            rows.append({"id": zid, "원인": "폐업 영향", "구군": gu_, "행정동": dn, "생활권": "면" if dn.endswith("면") else "읍" if dn.endswith("읍") else "동",
                         "시설": "공공 체육시설" if lid == "G:공공체육" else "공원", "기준_m": sv.get("기준_m"), "주민": sv.get("밀려난주민") or 0, "65세이상": sv.get("밀려난_65세이상") or 0,
                         "최근접_m": sv.get("거리_후_m"), "잰거리_m": sv.get("잰거리_m"), "관련폐업": [{"상호": r_.get("상호"), "업종": r_.get("업종"), "폐업일자": r_.get("폐업일자"), "보고": rep}],
                         "보고": rep, "창업참고": None, "경도": r_.get("경도"), "위도": r_.get("위도"), "폐업위치": True, "공공시설": True})
            have.add(zid)
    # 약국은 처방전이 나오는 의원이 있어야 버팀: 의원이 없어 '낮음'이지만 같은 동네가 의원 창업 참고 구역이면 '조건부'(의원과 함께 입점할 때)로 올림
    clinic_ok = {(r["구군"], r["행정동"]) for r in rows if r["원인"] == "상시 부재" and r["시설"] == "동네 의원" and r.get("창업참고")}
    for r in rows:
        if r["원인"] == "상시 부재" and r["시설"] == "약국" and not r.get("창업참고") and r.get("적합") and (r["구군"], r["행정동"]) in clinic_ok \
                and (r.get("밀집수요") or 0) >= CAPTURE["약국"] and (r["상권"] or {}).get("의원_500m") == 0 and r["상권"]["상권유형"] != "공단(공업지역)":
            r["적합"] = dict(r["적합"], 적합도="조건부", 근거=r["적합"]["근거"] + ["같은 동네 동네 의원 창업 참고 구역: 의원과 함께 입점 시 처방전 수요 생김"])
            r["창업참고"] = {"근거": f"도보 {r['기준_m'] / 1000:g}km 내 동일 시설 없음 · 반경 1km 밀집 수요 {r['밀집수요']:,}명", "적합도": "조건부"}
    # 폐업 자리의 창업 참고도 같은 상권 분석 (폐업 위치 기준)
    for r in rows:
        if r["원인"] == "폐업 영향" and r.get("창업참고") and r.get("상권") is None:
            lid = r["id"].split("|")[-1]; ta = _trade(G, r["시설"], [lid], r.get("경도"), r.get("위도"))
            if ta: r.update(상권=ta["상권"], 적합=ta["적합"]); r["창업참고"]["적합도"] = ta["적합"]["적합도"]
            if ta and ta["적합"]["적합도"] == "낮음": r["창업참고"] = None   # (10/26) 상권 적합도가 낮으면 창업 참고로 올리지 않음 (상시 부재와 같은 원칙). 상권 분석은 '창업 여건'으로 남김
    # AI 컨설턴트 요약 (창업 참고 행만, 사실이 같으면 다시 부르지 않음)
    try:
        import trade_area as TA
        S = TA.summarize([{"id": r["id"], "시설": r["시설"], "구군": r["구군"], "행정동": r["행정동"], "상권": r["상권"], "적합": r["적합"]} for r in rows if r.get("창업참고") and r.get("상권")], client)
        for r in rows:
            if r["id"] in S and r.get("창업참고"): r["창업참고"]["요약"] = S[r["id"]]
    except Exception: pass
    return sorted(rows, key=lambda r: (not r["보고"], r["원인"] != "폐업 영향", -(r.get("주민") or 0)))

_DCACHE = {}
def cells(G, rid):
    """구역 색칠용 100m 칸: [[경도, 위도, 주민], ...]. rid: '상시|시설|구군|행정동' 또는 '폐업|fid|기능id'"""
    C = G.cm._C; m = _mask(G, rid)
    if m is None: return []
    ii = np.where(m)[0][:6000]
    return [[round(float(C.lon[i]), 5), round(float(C.lat[i]), 5), round(float(C.pop[i]), 1)] for i in ii]

def profile(G, rid, landmark=None):
    """(10/29 헌준님: 월성2동 공백 구역 안에 공단과 주거지가 섞여 있는데 구역을 뭉뚱그려 판단함)
    구역을 100m 칸 단위로 세분화: ① 용도지역(주거·상업·공업·녹지·비도시)별 주민 ② 이어진 칸끼리 묶은 세부 구역(위치·주민·65세 이상·주된 용도지역)"""
    import trade_area as TA
    C = G.cm._C; m = _mask(G, rid, raw=True)
    if m is None or not m.any(): return None
    ii = np.where(m)[0]
    lon, lat, pop, p65 = C.lon[ii].astype(float), C.lat[ii].astype(float), C.pop[ii].astype(float), C.pop65[ii].astype(float)
    Z = TA._zones()
    x0, x1, y0, y1 = lon.min() - .01, lon.max() + .01, lat.min() - .01, lat.max() + .01
    near = [z for z in Z if not (z[3][0] < x0 or z[2][0] > x1 or z[3][1] < y0 or z[2][1] > y1)]
    zn = zone_of(C, ii)
    def _lab(nm):
        if nm in ("일반공업지역", "전용공업지역", "준공업지역"): return nm
        if "주거" in nm: return "주거지역"
        if "상업" in nm: return "상업지역"
        if "녹지" in nm: return "녹지지역"
        return "관리·농림지역" if not nm else "기타"
    cls = [_lab(nm) for nm in zn]
    LAB = {}
    by = {}
    for c, p_, e_ in zip(cls, pop, p65):
        k = LAB.get(c, c); v = by.setdefault(k, [0.0, 0.0, 0]); v[0] += p_; v[1] += e_; v[2] += 1
    tot = float(pop.sum())
    use = [{"용도지역": k, "주민": int(round(v[0])), "65세이상": int(round(v[1])), "비율_퍼센트": round(100 * v[0] / tot) if tot else 0, "칸수": v[2]}
           for k, v in sorted(by.items(), key=lambda t: -t[1][0])]
    # 세부 구역: 100m 칸이 이웃(대각선 포함, 한 칸 건너뛰기까지)으로 이어진 묶음
    gx = np.round(lon * 90200 / 100).astype(int); gy = np.round(lat * 110540 / 100).astype(int)
    pos = {(a, b): i for i, (a, b) in enumerate(zip(gx, gy))}; lab = -np.ones(len(ii), int); n = 0
    for i in range(len(ii)):
        if lab[i] >= 0: continue
        st = [i]; lab[i] = n
        while st:
            j = st.pop()
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    k = pos.get((gx[j] + dx, gy[j] + dy))
                    if k is not None and lab[k] < 0: lab[k] = n; st.append(k)
        n += 1
    subs = []
    for g in range(n):
        q = lab == g; P = float(pop[q].sum())
        if P < 5: continue
        cc = {}
        for c, p_ in zip(np.array(cls, dtype=object)[q], pop[q]): cc[LAB.get(c, c)] = cc.get(LAB.get(c, c), 0) + p_
        top = max(cc.items(), key=lambda t: t[1])
        cy, cx = float(np.average(lat[q], weights=pop[q] + 1e-9)), float(np.average(lon[q], weights=pop[q] + 1e-9))
        subs.append({"위치": (landmark(cx, cy) if landmark else None), "주민": int(round(P)), "65세이상": int(round(float(p65[q].sum()))),
                     "주된_용도지역": f"{top[0]} {round(100 * top[1] / P)}%", "용도지역별_주민": {k: int(round(v)) for k, v in sorted(cc.items(), key=lambda t: -t[1])},
                     "넓이_칸": int(q.sum()), "경도": round(cx, 5), "위도": round(cy, 5)})
    subs.sort(key=lambda r: -r["주민"])
    ind = sum(v["주민"] for v in use if v["용도지역"] in ("일반공업지역", "전용공업지역"))
    return {"주민": int(round(tot)), "65세이상": int(round(float(p65.sum()))), "용도지역별": use, "세부_구역": subs[:6],
            "공장지대_추정주민": ind, "공장지대_뜻": "일반·전용공업지역 칸의 주민은 동 인구를 공장 건물 넓이에 나눈 추정값이라 실제로 사는 사람이 거의 없음 → 공백 구역 주민에서 뺌(공단 근로자 진료는 산업보건 영역)",
            "참고": "주민 수는 주민등록 인구를 건물에 나눈 추정(밤 거주 인구). 공단에서 낮에 일하는 근로자는 들어 있지 않음"}

def _mask(G, rid, raw=False):
    E = G.cm.engine(); C = G.cm._C; parts = str(rid).split("|")
    if parts[0] == "상시" and len(parts) == 4:
        lab, gu, dong = parts[1:]
        g = next((x for x in GROUPS if x[0] == lab), None)
        if not g: return None
        std = G._std(g[2]); lim_m = std[0] * FACTOR
        key = (lab, getattr(G.cm, "_rebuilt", None))
        if key not in _DCACHE:
            P = sorted({p for l in g[1] for p in G._prov_all(l, True)})
            _DCACHE[key] = C.dist([E.walk.snap.get(p) for p in P if E.walk.snap.get(p)], limit=lim_m * 3 + 2000)
        d = _DCACHE[key]
        names = np.array([str(x) for x in C.hjd_name]); gus = getattr(C, "hjd_gu", None)
        idx = [i for i, n in enumerate(names) if n == dong and (gus is None or str(gus[i]) == gu)]
        m = ~(d <= lim_m) & (C.pop > 0) & np.isin(C.hjd, idx)
        if not raw: m = livable(C, m)
    elif parts[0] == "폐업" and len(parts) == 3:
        fid, lid = parts[1], parts[2]
        if fid not in E.F.index: return None
        G.baseline()
        m = G._severe(fid, lid, mask=True)
        if m is None: return None
        m = m & (C.pop > 0)
    else: return None
    return m


# ── 공백 구역 해소 확인 (10/21 헌준님): 매일 점검 때 어제 있던 구역이 오늘 사라졌는지 보고, 사라졌으면 까닭(도보권 안 같은 기능 시설 신규 개업 등)을 찾아 기록 ──
#  구역은 매일 지금 영업 중인 시설로 다시 계산하므로(새 시설이 생기면 자동으로 빠짐), 여기서는 '언제·왜 빠졌는지'를 남겨 담당자·주민이 볼 수 있게 함
#  같은 날 다시 계산한 것은 비교하지 않음(마지막으로 본 날 < 오늘인 구역만). 다시 나타나면 해소 표시를 지움
def track_resolved(G, rows, t, days=30):
    import os, json, datetime
    from gov_agent import GOV, _jload, _jsave
    p = os.path.join(GOV, "zone_history.json"); H = _jload(p, {})
    cur = {r["id"]: r for r in rows}
    for zid, r in cur.items():
        h = H.setdefault(zid, {"처음": t})
        h.update(마지막=t, 상태="있음", 행={k: r.get(k) for k in ("구군", "행정동", "시설", "원인", "주민", "65세이상", "기준_m", "경도", "위도", "밀집_경도", "밀집_위도")})
        h.pop("해소일", None); h.pop("까닭", None)
    E = G.cm.engine()
    for zid, h in H.items():
        if zid in cur or h.get("상태") == "해소" or (h.get("마지막") or t) >= t: continue
        r = h.get("행") or {}; lids = set(LIDS_OF.get(r.get("시설"), []))
        x0, y0 = r.get("밀집_경도") or r.get("경도"), r.get("밀집_위도") or r.get("위도")
        why = None
        if x0 is not None and lids:
            since = (datetime.date.fromisoformat(h["마지막"]) - datetime.timedelta(days=7)).isoformat()
            for e in reversed(G.cm.events):
                if e.get("종류") not in ("신규", "재개업") or (e.get("날짜") or "") < since: continue
                f2 = e.get("fid")
                if f2 not in E.F.index or E.F.at[f2, "x"] != E.F.at[f2, "x"]: continue
                d = (((float(E.F.at[f2, "x"]) - float(x0)) * 90200) ** 2 + ((float(E.F.at[f2, "y"]) - float(y0)) * 110540) ** 2) ** 0.5
                if d > (r.get("기준_m") or 2000) * 1.5: continue
                try: ok = any(L in lids and st in ("근거", "강함", "업종") for (L, k, nd), (st, w) in E.served(f2).items())
                except Exception: ok = False
                if ok: why = f"도보권 내 {E.F.at[f2, '상호']}({E.F.at[f2, '업종']}) {'영업 재개' if e['종류'] == '재개업' else '신규 개업'} · 밀집 지점에서 직선 {d / 1000:.1f}km"; break
        h.update(상태="해소", 해소일=t, 까닭=why or "시설·인구 자료 갱신으로 도보 기준 충족 (신규 개업 기록 없음)")
    _jsave(p, H)
    out = []
    for zid, h in H.items():
        if h.get("상태") != "해소": continue
        try: ds = (datetime.date.fromisoformat(t) - datetime.date.fromisoformat(h["해소일"])).days
        except Exception: continue
        if ds <= days: out.append(dict(h.get("행") or {}, id=zid, 해소일=h["해소일"], 처음=h.get("처음"), 까닭=h.get("까닭")))
    return sorted(out, key=lambda x: x["해소일"], reverse=True)
