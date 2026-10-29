import re
# 정책 검토 계산 (10/21 헌준님: 지자체 업무 보조 대화의 '정책 검토'). 언어 모델 없음 — 숫자는 모두 여기서 계산하고, 모델은 설명만
#  - 개설 효과 산정: 어떤 기능의 시설을 한 곳에 새로 두면, 걸어서 기준 거리 밖에 있던 주민 가운데 몇 명이 기준 안으로 들어오는지
#  - 입지 후보 비교: 기준 거리 밖 주민이 많은 동네마다 가장 붐비는 지점을 후보로 잡고, 후보마다 개설 효과를 계산해 순위
#  기준 거리: 보고와 같은 체감 기준(GovAgent._std). 지금 있는 시설은 '그 일을 하는지 모르는 곳'까지 넓게 넣어 효과를 부풀리지 않음
#  사람 수는 행정동 인구를 100m 칸에 나눈 추정 (보고와 같은 자료)
import numpy as np
SPEED = 1.0
def _cov(G, lid):
    std = G._std(lid)
    if not std: return None
    E = G.cm.engine(); C = G.cm._C; who = std[1]
    b = G._base_of(lid) or {}
    thr = float(max(std[0], b.get("하위5퍼_m") or 0))   # 보고 기준 거리와 같은 값 (체감 기준과 대구 주민에게서 배운 기준 가운데 먼 쪽, gov_agent.report_rules)
    zthr = float(std[0]) * 2                            # 공백 구역 기준 (체감 기준의 2배, engine/area_gap.py)
    P = G._prov_all(lid, broad=True)
    snaps = [E.walk.snap.get(p) for p in P if E.walk.snap.get(p)]
    d = C.dist(snaps, limit=max(thr, zthr) * 3 + 2000)
    w = G._w(who); w = C.pop if w is None else w
    n_dong = _count_dong(G, P)   # (10/25) 동네 안 시설 수: '○○ 없는 동네' 질문용
    return {"d": d, "thr": thr, "zthr": zthr, "who": who, "w": w, "n_prov": len(snaps), "why": std[2] if len(std) > 2 else "", "n_dong": n_dong}
def _count_dong(G, P):
    """시설들을 행정동별로 셈 (좌표 → 가장 가까운 인구 칸의 행정동)"""
    from collections import Counter
    E = G.cm.engine(); C = G.cm._C; n_dong = Counter(); F = E.F
    try: from dong import dong_at
    except Exception: dong_at = None
    names = {(str(C.hjd_gu[h]), str(C.hjd_name[h])) for h in range(len(C.hjd_name))}
    rest = []
    for p in P:   # 행정동 경계(폴리곤)로 먼저 — 경계 근처 시설이 이웃 동으로 잘못 세지지 않게
        if p not in F.index: continue
        lon, lat = F.at[p, "경도"], F.at[p, "위도"]
        try: lon, lat = float(lon), float(lat)
        except Exception: continue
        if lon != lon or lat != lat: continue
        d = dong_at(lon, lat) if dong_at else ""; g = str(F.at[p, "구군"])
        if d and (g, d) in names: n_dong[(g, d)] += 1
        else: rest.append((lon, lat))
    if rest:   # 경계로 못 정한 곳은 가장 가까운 인구 칸의 행정동
        try:
            from scipy.spatial import cKDTree
            _, ix = cKDTree(np.c_[C.lon, C.lat]).query(np.array(rest))
            for i in np.atleast_1d(ix): h = int(C.hjd[int(i)]); n_dong[(str(C.hjd_gu[h]), str(C.hjd_name[h]))] += 1
        except Exception: pass
    return n_dong
_CACHE = {}
def coverage(G, lid):
    key = (lid, id(G.cm._C))
    if key not in _CACHE: _CACHE.clear(); _CACHE[key] = _cov(G, lid)
    return _CACHE[key]
def _gain(G, cv, lon, lat):
    E = G.cm.engine(); C = G.cm._C
    e, t, d0 = E.walk._snap_point(lon, lat)
    own = C.dist([(e, t, d0)], limit=max(cv["thr"], cv["zthr"]) + 10)
    out = (cv["d"] > cv["thr"]) & (C.pop > 0); got = out & (own <= cv["thr"])
    out2 = (cv["d"] > cv["zthr"]) & (C.pop > 0); got2 = out2 & (own <= cv["zthr"])   # 공백 구역 기준(체감 기준의 2배, engine/area_gap.py)으로 본 해소
    dongs = {}
    for h in np.unique(C.hjd[got]):
        m = got & (C.hjd == h); dongs[str(C.hjd_name[h])] = int(round(float(C.pop[m].sum())))
    return {"새로_기준안_주민": int(round(float(C.pop[got].sum()))), "그중_65세이상": int(round(float(C.pop65[got].sum()))),
            "대상": cv["who"], "대상_인원": int(round(float(cv["w"][got].sum()))) if cv["who"] != "전체" else None,
            "공백구역기준_m": int(cv["zthr"]), "공백구역기준_해소_주민": int(round(float(C.pop[got2].sum()))), "공백구역기준_해소_65세이상": int(round(float(C.pop65[got2].sum()))),
            "길까지_m": int(d0), "동네별": sorted(dongs.items(), key=lambda x: -x[1])[:4]}
def where(G, lon, lat):
    C = G.cm._C
    i = int(np.argmin((C.lon - lon) ** 2 + (C.lat - lat) ** 2))
    return str(C.hjd_gu[C.hjd[i]]), str(C.hjd_name[C.hjd[i]])
def open_effect(G, lid, lon, lat):
    cv = coverage(G, lid)
    if not cv: return {"오류": "이 기능은 걸어서 갈 기준 거리가 정해지지 않아 계산할 수 없습니다"}
    g = _gain(G, cv, float(lon), float(lat)); gu, dn = where(G, lon, lat)
    if g["길까지_m"] > 150: g["주의"] = "고른 지점이 걷는 길에서 멀어(150m 넘음) 결과가 실제와 다를 수 있음"
    out = dict(g, 기준_m=int(cv["thr"]), 구군=gu, 행정동=dn, 경도=float(lon), 위도=float(lat), 기준근거=cv["why"])
    out.update(_share(G, cv, gu, dn, g))
    return out
def _share(G, cv, gu, dn, g):
    """판단 재료 (10/22 헌준님: 숫자만이 아니라 '얼마나 해결되는지'): 그 동의 걸어서 못 가는 주민 가운데 이 한 곳으로 해결되는 몫"""
    C = G.cm._C; nm = np.array([str(x) for x in C.hjd_name]); gs = np.array([str(x) for x in C.hjd_gu])
    hs = [h for h in range(len(nm)) if nm[h] == dn and gs[h] == gu]
    if not hs: return {}
    m = np.isin(C.hjd, hs) & (C.pop > 0)
    out_d = float(C.pop[m & (cv["d"] > cv["thr"])].sum()); zone_d = float(C.pop[m & (cv["d"] > cv["zthr"])].sum())
    here = dict(g.get("동네별") or []).get(dn, 0)
    r = {"그동네_기준밖_주민": int(round(out_d)), "그동네_공백구역기준밖_주민": int(round(zone_d))}
    if out_d >= 1: r["그동네_기준밖_주민중_해결_퍼센트"] = int(round(100 * here / out_d))
    if zone_d >= 1: r["그동네_공백구역기준밖_주민중_해결_퍼센트(이웃 동 포함 근사)"] = int(round(min(100, 100 * g["공백구역기준_해소_주민"] / zone_d)))
    return r
def _got(G, cv, lon, lat):
    E = G.cm.engine(); C = G.cm._C
    e, t, d0 = E.walk._snap_point(lon, lat)
    own = C.dist([(e, t, d0)], limit=cv["thr"] + 10)
    return (cv["d"] > cv["thr"]) & (C.pop > 0) & (own <= cv["thr"])
def plan_route(G, lid, pts, k=4):
    """여러 곳을 돌아가며 할 때 (10/22): 겹치는 주민을 빼고 새로 닿는 주민이 가장 많이 늘도록 차례로 고름 (탐욕 선택)
    돌려줌: [{이름, 더해지는_주민, 더해지는_65세이상, 누적_주민, 누적_65세이상}]"""
    cv = coverage(G, lid)
    if not cv: return []
    C = G.cm._C; masks = [(nm, _got(G, cv, float(lo), float(la))) for nm, lo, la in pts]
    cover = np.zeros(len(C.pop), bool); out = []
    for _ in range(min(k, len(masks))):
        best = max(masks, key=lambda x: float(C.pop[x[1] & ~cover].sum()))
        add = best[1] & ~cover; g = float(C.pop[add].sum())
        if g < 1: break
        cover |= best[1]; masks = [x for x in masks if x[0] != best[0]]
        out.append({"이름": best[0], "더해지는_주민": int(round(g)), "더해지는_65세이상": int(round(float(C.pop65[add].sum()))),
                    "누적_주민": int(round(float(C.pop[cover].sum()))), "누적_65세이상": int(round(float(C.pop65[cover].sum())))})
    return out
def compare_points(G, lid, pts):
    """여러 지점(시설 자리) 비교: [(이름, lon, lat)] → 지점마다 개설 효과, 효과 큰 순"""
    cv = coverage(G, lid)
    if not cv: return {"오류": "이 기능은 걸어서 갈 기준 거리가 정해지지 않아 계산할 수 없습니다"}
    rows = []
    for nm, lon, lat in pts:
        g = _gain(G, cv, float(lon), float(lat)); gu, dn = where(G, lon, lat)
        rows.append(dict(g, 이름=nm, 구군=gu, 행정동=dn, 경도=float(lon), 위도=float(lat)))
    key = (lambda r: (r["대상_인원"] or 0, r["새로_기준안_주민"])) if cv["who"] != "전체" else (lambda r: (r["새로_기준안_주민"], r["공백구역기준_해소_주민"]))   # 걸어서 다닐 만한 거리 안에 새로 드는 주민 순
    rows.sort(key=key, reverse=True)
    return {"기준_m": int(cv["thr"]), "공백구역기준_m": int(cv["zthr"]), "대상": cv["who"], "지점": rows}
def dong_point(G, gu, dong, lid=None):
    """행정동 안의 대표 지점: 그 기능의 기준 거리 밖 주민이 가장 몰린 곳 (없으면 인구 중심)"""
    C = G.cm._C; nm = np.array([str(x) for x in C.hjd_name]); gs = np.array([str(x) for x in C.hjd_gu])
    hs = [h for h in range(len(nm)) if nm[h].replace(" ", "") == str(dong).replace(" ", "") and (not gu or gs[h] == gu)]
    if not hs: return None
    m = np.isin(C.hjd, hs) & (C.pop > 0)
    if lid:
        cv = coverage(G, lid)
        if cv: mo = m & (cv["d"] > cv["thr"]); m = mo if mo.any() else m
    return _dense(C, m)
def _dense(C, m, r=700):
    ii = np.where(m)[0]
    if not len(ii): return None
    xy = np.c_[C.lon[ii] * 90200, C.lat[ii] * 110540]
    from scipy.spatial import cKDTree
    T = cKDTree(xy); k = ii if len(ii) <= 3000 else ii[np.argsort(-C.pop[ii])[:3000]]
    best = max(k, key=lambda j: C.pop[ii][T.query_ball_point([C.lon[j] * 90200, C.lat[j] * 110540], r)].sum())
    return float(C.lon[best]), float(C.lat[best])
def candidates(G, lid, gu=None, n=5):
    """기준 거리 밖 주민(대상 기준)이 많은 동네 → 동네마다 가장 붐비는 지점 → 개설 효과 순"""
    cv = coverage(G, lid)
    if not cv: return {"오류": "이 기능은 걸어서 갈 기준 거리가 정해지지 않아 계산할 수 없습니다"}
    C = G.cm._C; gs = np.array([str(x) for x in C.hjd_gu])
    out = (cv["d"] > cv["thr"]) & (C.pop > 0)
    if gu: out &= gs[C.hjd] == gu
    tot = {"기준밖_주민": int(round(float(C.pop[out].sum()))), "기준밖_65세이상": int(round(float(C.pop65[out].sum())))}
    hs = sorted(np.unique(C.hjd[out]), key=lambda h: -float(cv["w"][out & (C.hjd == h)].sum()))[: n * 2]
    rows = []
    for h in hs:
        p = _dense(C, out & (C.hjd == h))
        if not p: continue
        g = _gain(G, cv, *p)
        if g["새로_기준안_주민"] <= 0: continue
        rows.append(dict(g, 구군=str(gs[h]), 행정동=str(C.hjd_name[h]), 경도=p[0], 위도=p[1], 동네_기준밖_주민=int(round(float(C.pop[out & (C.hjd == h)].sum())))))
    key = (lambda r: -(r["대상_인원"] or 0)) if cv["who"] != "전체" else (lambda r: -r["새로_기준안_주민"])
    rows.sort(key=key)
    return dict(tot, 기준_m=int(cv["thr"]), 대상=cv["who"], 기준근거=cv["why"], 지금시설수=cv["n_prov"], 구군=gu, 후보=rows[:n])
def access(G, lid, gu=None, n=8, label=None):
    """걸어서 가기 어려운 동네 (어떤 생활 기능이든): 보고 기준 거리 밖에 사는 주민(대상: 영유아·65세 이상 등)을 동네별로. 계산만"""
    cv = coverage(G, lid)
    if not cv: return {"오류": "이 기능은 걸어서 갈 기준 거리가 정해지지 않아 계산할 수 없습니다"}
    C = G.cm._C; gs = np.array([str(x) for x in C.hjd_gu])
    out = (cv["d"] > cv["thr"]) & (C.pop > 0); sel = np.ones(len(C.pop), bool) if not gu else (gs[C.hjd] == gu)
    rows = []
    for h in np.unique(C.hjd[out & sel]):
        m = C.hjd == h; mo = m & out
        tot_w = float(cv["w"][m].sum()); o_w = float(cv["w"][mo].sum())
        if o_w < 1: continue
        rows.append({"구군": str(gs[h]), "행정동": str(C.hjd_name[h]), "동네_안_시설_수": cv.get("n_dong", {}).get((str(gs[h]), str(C.hjd_name[h])), 0), "기준밖_대상": int(round(o_w)), "동네_대상": int(round(tot_w)),
                     "기준밖_비율": round(o_w / tot_w, 2) if tot_w else None, "기준밖_주민": int(round(float(C.pop[mo].sum()))), "그중_65세이상": int(round(float(C.pop65[mo].sum())))})
    rows.sort(key=lambda r: -r["기준밖_대상"])
    tot = int(round(float(cv["w"][out & sel].sum())))
    nd = cv.get("n_dong") or {}
    lab = re.sub(r"\s", "", str(label or ""))
    if lab:   # 담당자가 시설 종류를 말했으면(예: 경로당) 그 종류만 셈 — 같은 기능의 다른 종류(마을회관 등)는 빼고
        F_ = G.cm.engine().F
        nd = _count_dong(G, [p for p in G._prov_all(lid, broad=True) if p in F_.index and lab in re.sub(r"\s", "", str(F_.at[p, "업종"]))])
    none = []   # 범위 안에서 그 기능을 하는 시설이 동 안에 한 곳도 없는 동 (이웃 동 시설을 걸어서 이용할 수는 있음)
    for h in range(len(C.hjd_name)):
        g_, d_ = str(C.hjd_gu[h]), str(C.hjd_name[h])
        if (gu and g_ != gu) or nd.get((g_, d_), 0): continue
        m = C.hjd == h
        if float(C.pop[m].sum()) < 1: continue
        mo = m & out
        none.append({"구군": g_, "행정동": d_, "주민": int(round(float(C.pop[m].sum()))), "그중_기준밖_주민": int(round(float(C.pop[mo].sum())))})
    if none and lab:   # 안내에서 뺀 같은 종류(아파트 단지 전용 경로당 등)가 그 동에 있으면 함께 알림 — '한 곳도 없다'로 오해하지 않게
        F_ = G.cm.engine().F
        ex = F_[F_["업종"].astype(str).str.replace(r"\s", "", regex=True).str.contains(re.escape(lab)) & (F_["대안후보"] == "아니요") & F_["제외사유"].astype(str).str.contains("단지")]
        nx = _count_dong(G, list(ex.index))
        for r in none:
            k = nx.get((r["구군"], r["행정동"]), 0)
            if k: r["단지_주민_전용_시설_수(안내_제외)"] = k
    none.sort(key=lambda r: -r["그중_기준밖_주민"])
    return {"기준_m": int(cv["thr"]), "대상": cv["who"], "범위": gu or "대구 전체", "기준밖_대상_합계": tot, "동네수": len(rows), "동네": rows[:n], "기준근거": cv["why"],
            "동_안에_시설이_한곳도_없는_동": none[:15], "동_안에_시설이_한곳도_없는_동_수": len(none)}
