# 지자체 업무 보조 문서 (10/21 헌준님): 언어 모델 없이 코드가 보고서 자료(brief_latest.json)를 정해진 틀에 채움 → API 비용 0, 숫자는 계산값 그대로
#  - 인쇄용 보고서(HTML): 브라우저 인쇄 창에서 'PDF로 저장' (글꼴·라이브러리 없이 어디서나 같은 모양)
#  - 개조식 요약 글: 공문서 기호 체계(□ ○ -)로, 기관 양식에 붙여 넣기 좋게
#  - 엑셀(.xlsx): 표준 라이브러리로 직접 만듦 (한글 문서 표에 바로 붙여 넣기)
import datetime, html, io, json, os, re, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUS = ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군"]
DOW = "월화수목금토일"

def load(path=None):
    p = path or os.path.join(ROOT, "data", "gov", "brief_latest.json")
    b = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
    if b and os.environ.get("GINEUNG_DEMO_REPORT"): b["날짜"] = os.environ["GINEUNG_DEMO_REPORT"][:10]   # 영상 시연 서버 전용 (10/24)
    return b

def _d(s):   # 2026-10-21 → 2026. 10. 21.
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    return f"{m[1]}. {int(m[2])}. {int(m[3])}." if m else ""
def _dw(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    if not m: return ""
    return f"{_d(s)}({DOW[datetime.date(int(m[1]), int(m[2]), int(m[3])).weekday()]})"
def _md(s):
    m = re.match(r"\d{4}-(\d{2})-(\d{2})", str(s or ""))
    return f"{int(m[1])}. {int(m[2])}." if m else ""
def _n(v): return f"{int(round(v or 0)):,}"
def _km(m):
    if m is None: return ""
    return f"{m / 1000:.1f}km".replace(".0km", "km")
def _gus(b, gu): return [g for g in GUS if g in b["구군"] and (not gu or g == gu)]

# 용어 풀이 (10/21 밤 헌준님: 담당자·관계 기관이 서비스 용어를 몰라도 한눈에) — 문서에 나온 용어만 맨 끝 ※ 한 줄씩
GLOSS = [("긴급", "생명·돌봄 기능이 끊겨 즉시 조치가 필요한 공백"), ("주의", "대체 수단이 부족해 조치 검토가 필요한 공백"), ("관찰", "공백은 있으나 지금은 조치가 필요 없어 AI가 매일 지켜보는 곳"),
         ("기능 공백 구역", "약국·동네 의원·식료품점이 걸어서 갈 거리(약국 2km 등) 안에 없는 동네"), ("단절 우려", "영업 중이나 문을 닫으면 주민이 대신 갈 곳이 없는 시설"),
         ("검토 완료", "폐업했지만 공백이 없거나 경미해 보고하지 않은 곳(근처 대체 시설·이용자 없음·교육청 통합 등)"), ("폐업 확인 필요", "운영 여부가 자료마다 달라 담당자 확인이 필요한 곳"),
         ("도보권 미충족 상담", "주민이 상담에서 찾은 시설이 걸어서 갈 거리 안에 없었던 경우(직접 요청 아님)")]
def gloss_lines(text):
    return [f" ※ {k}: {v}" for k, v in GLOSS if k in text]
def dong_ok(dn, q):
    """행정동 맞추기: '상인동' → 상인1·2동, '범어1동' → 범어1동만, '불로동' → 불로·봉무동 (gov_chat와 같은 규칙)"""
    if not q: return True
    d = re.sub(r"\s", "", str(dn or "")); qq = re.sub(r"\s", "", str(q))
    if not d: return False
    if d == qq: return True
    if re.search(r"\d(동|읍|면)$", qq): return False
    stem = re.sub(r"(동|읍|면)$", "", qq)
    if not stem: return False
    if re.fullmatch(re.escape(stem) + r"[\d.·]*(가)?(동|읍|면)", d): return True
    return any(p_ == stem or re.fullmatch(re.escape(stem) + r"[\d.·]*(가)?동", p_) for p_ in d.split("·"))
def _loc(r, gu_fallback=True):
    """행정동(읍·면이면 마을까지): 문서 글에 쓰는 위치"""
    d = r.get("행정동") or (r.get("구군") if gu_fallback else "") or ""
    return f"{d} {r['리']}" if r.get("리") and d else d
def _ri(r):
    """(10/29) 읍·면이면 마을(리)을 붙임: 같은 읍·면의 서로 다른 마을이 한 이름으로 겹쳐 보이지 않게"""
    if r.get("리") is None and str(r.get("행정동") or "").endswith(("읍", "면")):
        try:
            import ri as RI
            r = dict(r, 리=RI.of(r.get("행정동"), r.get("fid"), r.get("밀집_경도") or r.get("경도"), r.get("밀집_위도") or r.get("위도")) or "")
        except Exception: pass
    return r
def rows(b, gu=None, dong=None):
    """문서와 대화가 같이 쓰는 행 묶음 (구·군 거름, dong이 있으면 행정동까지)"""
    if dong:
        R = rows(b, gu)
        for k, v in list(R.items()):
            if isinstance(v, list): R[k] = [r for r in v if dong_ok(r.get("행정동"), dong)]
        R["동"] = dong
        return R
    gs = _gus(b, gu); G = b["구군"]; f = lambda k: [_ri(dict(r, 구군=r.get("구군") or g)) for g in gs for r in G[g].get(k, [])]
    quiet = f("보고안함")
    return {"항목": f("항목"), "확인요청": f("확인요청"), "질문": f("질문"), "관찰": [r for r in quiet if r.get("관찰")], "검토완료": [r for r in quiet if not r.get("관찰")],
            "확인대기": [r for r in b.get("확인대기", []) if not gu or r.get("구군") == gu],
            "공백구역": [_ri(r) for r in b.get("기능공백구역", []) if not gu or r.get("구군") == gu],
            "주민수요": [r for r in b.get("주민수요", []) if not gu or r.get("구군") == gu],
            "단절우려": [_ri(r) for r in b.get("하나남은곳", []) if not gu or r.get("구군") == gu],
            "해소": [r for r in b.get("해소", []) if not gu or r.get("구군") == gu],
            "확정": sum(G[g].get("확정", 0) for g in gs), "대상아님": sum(G[g].get("대상아님", 0) for g in gs),
            "긴급": sum(G[g].get("긴급", 0) for g in gs), "주의": sum(G[g].get("주의", 0) for g in gs), "관찰수": sum(G[g].get("관찰", 0) for g in gs)}

def _impact(r):
    """조치 필요 항목의 영향 한 줄 (계산값 그대로)"""
    sv = r.get("심각") or {}
    if "정원" in sv:
        n = sv.get("현원") or sv.get("정원")
        s = f"이용자 {_n(n)}명 타 기관 이전 필요" if n else "이용자 이전 필요(정원 확인 필요)"
        if sv.get("가장가까운같은기관_m"): s += f" · 최근접 동일 기관 {_km(sv['가장가까운같은기관_m'])}"
        if sv.get("주변_여유정원") is not None: s += f" · 2km 내 여유 정원 {_n(sv['주변_여유정원'])}명"
        return s
    if sv.get("밀려난주민") is not None:
        who = f"{sv['아이']} {_n(sv.get('밀려난_아이'))}명" if sv.get("아이") else f"주민 {_n(sv['밀려난주민'])}명(65세 이상 {_n(sv.get('밀려난_65세이상'))}명)"
        s = f"도보 {_km(sv.get('기준_m'))} 내 {r.get('기능') or '이용 시설'} 소멸 {who}"
        if sv.get("거리_전_m") is not None and sv.get("거리_후_m") is not None:
            cap = sv.get("잰거리_m"); aft = f"{_km(cap)} 이상" if cap and sv["거리_후_m"] >= cap else _km(sv["거리_후_m"])
            s += f" · 최근접 {_km(sv['거리_전_m'])} → {aft}"
        return s
    return "; ".join(r.get("까닭") or [])

def _scope_title(gu): return f"대구광역시 {gu}" if gu else "대구광역시 전체"

# ── 개조식 요약 (복사해 기관 양식에 붙여 넣기) ──
def summary_text(b, gu=None, only=None, dong=None, where=None):
    """개조식 요약 (10/22 헌준님: 폐업 건수 같은 집계 대신 '어디서 어떤 기능이 부족한지 → 누가 얼마나 → 할 일')
    only: 기능 이름 일부(예: '약국', '돌봄')로 걸러 부서별 전달용으로 · where: 공백 구역 위치 설명 함수(업무 보조가 넘김)"""
    R = rows(b, gu, dong); hay = lambda r: " ".join(str(r.get(k) or "") for k in ("기능", "기능이름", "시설", "업종", "상호", "까닭"))
    flt = (lambda r: True) if not only else (lambda r: only in hay(r))
    it = [r for r in R["항목"] if flt(r)]; wt = [r for r in R["관찰"] if flt(r)]; ask = [r for r in R["확인요청"] if flt(r)]
    zones = sorted([r for r in R["공백구역"] if flt(r)], key=lambda r: -(r.get("주민") or 0)); lone = sorted([r for r in R["단절우려"] if flt(r)], key=lambda r: -(r.get("주민") or 0))
    dm = sorted([r for r in R["주민수요"] if flt(r)], key=lambda r: -(r.get("건수") or 0))
    scope = f"{_scope_title(gu)}{' ' + dong if dong else ''}"
    L = [f"□ 생활 기능 부족 현황 ({_d(b['날짜'])}, {scope})" + (f" — {only} 관련" if only else "")]
    if not (it or ask or wt): L.append(" ○ 오늘 새로 생긴 공백 없음 · 조치·확인할 폐업 없음")
    if it:
        L.append("□ 조치가 필요한 공백 (폐업으로 기능이 끊긴 곳)")
        for r in it:
            L.append(f" ○ {_loc(r)} {r.get('기능') or r['업종']}: {r['상호']} {_md(r.get('폐업일자'))} 폐업 [{r['등급']}]" + (" · 처리 완료" if r.get("처리") else ""))
            L.append(f"  - 영향: {_impact(r)}")
            for a in (r.get("대응") or [])[:3]: L.append(f"  - 할 일: {a['할일']}" + (f"({a['담당']})" if a.get("담당") else "") + (f" · 근거 {a['근거']}" if a.get("근거") else ""))
    if ask:
        L.append("□ 운영 여부 확인이 필요한 곳 (닫혔다면 공백 발생)")
        for r in ask: L.append(f" ○ {_loc(r)} {r['상호']}({r['업종']})" + (f": 닫혔다면 {r['닫았다면']}" if r.get("닫았다면") else "") + " · 운영 여부 확인 회신 필요")
    if zones:
        L.append("□ 원래 시설이 없어 걸어서 이용하기 어려운 구역 (동 안 일부 구역)")
        for z in zones[:6]:
            w = where(z) if where else None
            L.append(f" ○ {z['구군']} {_loc(z, False)} {z.get('시설')}: 도보 {_km(z.get('기준_m'))} 안에 없음 · 주민 {_n(z.get('주민'))}명(65세 이상 {_n(z.get('65세이상'))}명)" + (f" · 가장 가까운 곳 도보 {_km(z.get('최근접_m'))}" if z.get("최근접_m") else "") + (f" · 위치: {w}" if w else ""))
        if len(zones) > 6: L.append(f" ○ 외 {len(zones) - 6}곳")
    if lone:
        L.append("□ 영업 중이나 닫히면 대신 갈 곳이 없는 시설")
        for r in lone[:5]: L.append(f" ○ {_loc(r)} {r['상호']}({r.get('기능') or r['업종']}): 닫히면 주민 {_n(r.get('주민'))}명(65세 이상 {_n(r.get('65세이상'))}명) 걸어서 이용 불가")
    if wt:
        L.append("□ 지켜볼 곳 (공백 있음 · 조치 불필요 · 매일 재검토)")
        for r in wt: L.append(f" ○ {_loc(r)} {r['상호']}({r['업종']}): {r.get('까닭') or ''}")
    if dm:
        L.append("□ 주민 상담에서 확인된 수요 (찾은 기능의 시설이 도보권에 없던 상담)")
        L.append(" ○ " + ", ".join(f"{r.get('행정동')} {r.get('기능이름')} {r['건수']}건" for r in dm[:6]))
    if only:   # 부서 전달용: 그 기능의 폐업 가운데 공백 없음으로 정리한 곳 (전달할 사실만, 최근 10곳)
        dn = sorted([r for r in R["검토완료"] if flt(r)], key=lambda r: r.get("확정일") or "", reverse=True)
        if dn:
            L.append(f"□ 참고: {only} 폐업 중 대체 시설이 있어 공백 없는 곳")
            for r in dn[:10]: L.append(f" ○ {_loc(r)} {r['상호']}({_md(r.get('폐업일자')) if str(r.get('폐업일자') or '')[:4] == b['날짜'][:4] else _d(r.get('폐업일자'))} 폐업): {r.get('까닭') or ''}")
            if len(dn) > 10: L.append(f" ○ 외 {len(dn) - 10}곳")
    L.append("□ 향후: 평일 오전 자동 재점검 · 폐업 확정·공백 해소 시 갱신")
    L += gloss_lines("\n".join(L))
    return "\n".join(L)

def facility_text(r, kind, date):
    t = _facility_text(r, kind, date)
    return t + ("\n" + "\n".join(gloss_lines(t)) if gloss_lines(t) else "")
def _facility_text(r, kind, date):
    """시설 한 곳의 개조식 정리 (관계 기관 전달용). kind: 조치필요·관찰·검토완료·폐업확인필요·사전검토·단절우려"""
    loc = " ".join(x for x in (r.get("구군"), r.get("행정동"), r.get("리")) if x)
    pre = kind == "사전검토"
    L = [f"□ {r.get('상호')} {'폐업 가정 시' if pre or kind == '단절우려' else '폐업에 따른'} 생활 기능 공백 검토 ({_d(date)})"]
    if kind == "단절우려":
        L.append(f" ○ 시설: {r.get('업종') or ''} · {loc} · 영업 중")
        L.append(f" ○ 폐업 시 기준 거리 안에 이용할 곳이 없어지는 주민 {_n(r.get('주민'))}명(65세 이상 {_n(r.get('65세이상'))}명) · {r.get('기능') or ''}" + (f" · 다음 시설 직선 {_km(r.get('가장가까운_직선_m'))}" if r.get("가장가까운_직선_m") else ""))
        L.append(" ○ 향후: 운영 변동 시 즉시 재검토")
        return "\n".join(L)
    if kind == "폐업확인필요":
        L.append(f" ○ 시설: {r.get('업종') or ''} · {loc}")
        why = re.sub(r"^[^:]+:\s*", "", str(r.get("까닭") or ""))
        L.append(f" ○ 확인 사유: {why}")
        if r.get("닫았다면"): L.append(f" ○ 폐업 시 예상: {r['닫았다면']}" + (f" · {r['닫았다면_까닭'][0]}" if r.get("닫았다면_까닭") else ""))
        L.append(" ○ 요청: 운영 여부(폐업·휴원·운영 중) 확인 회신")
        return "\n".join(L)
    head = f" ○ 시설: {r.get('업종') or ''} · {loc}" + ("" if pre else f" · {_d(r.get('폐업일자'))} 폐업") + (f"({r['확정근거']} 확정)" if r.get("확정근거") else "")
    L.append(head)
    lv = r.get("판단") if pre else (r.get("등급") if kind == "조치필요" else ("관찰" if kind == "관찰" else (r.get("구분") or "공백 없음")))
    L.append(" ○ 판단: " + (f"공백 심각도 {lv}" if lv in ("긴급", "주의", "관찰") else (lv or "공백 없음")) + (" (폐업 가정)" if pre else ""))
    if kind in ("조치필요",) or (pre and r.get("공백")): L.append(f" ○ 영향: {_impact(r)}")
    why = r.get("판단까닭") or (r.get("까닭") if isinstance(r.get("까닭"), str) else "; ".join(r.get("까닭") or []))
    if why: L.append(f" ○ 근거: {why}")
    alts = [a for a in (r.get("대체시설") or []) if a.get("상호")][:3]
    if alts: L.append(" ○ 대체 시설: " + ", ".join(a["상호"] + (f"(도보 {round(a['걷는시간_분'])}분)" if a.get("걷는시간_분") is not None and a["걷는시간_분"] <= 40 else "") for a in alts))
    for a in (r.get("대응") or [])[:3]: L.append(f"  - 검토할 일: {a['할일']}" + (f"({a['담당']})" if a.get("담당") else "") + (f" · 근거 {a['근거']}" if a.get("근거") else ""))
    if r.get("공립대체"):
        p = r["공립대체"]; L.append(f" ○ 공립 대체: 반경 {_km(p.get('반경_m'))} 공립 {p.get('곳')}곳 · 여유 {_n(p.get('여유'))}명" + (" · 수용 가능" if p.get("가능") else " · 선택권 축소"))
    mv = r.get("옮길곳") or []
    if mv:
        tot = sum(x["여유"] for x in mv); sc = (r.get("심각") or {}); cur = sc.get("현원")
        L.append(f" ○ 이용 아동 이전: 인근 동종 기관 {len(mv)}곳 여유 정원 {_n(tot)}명" + (f" (현원 {_n(cur)}명)" if cur else "") + " · 연령별 빈자리는 기관 확인 필요")
        L.append("  - " + ", ".join(f"{x['상호']}({x['종류'] + ' · ' if x.get('종류') else ''}직선 {_n(x['직선_m'])}m · 여유 {_n(x['여유'])}명)" for x in mv))
    L.append(" ○ 향후: " + ("실제 폐업 확정 시 정식 판정" if pre else "매일 재검토 · 공백 해소 시 종료" if kind in ("조치필요", "관찰") else "안내 기간 종료 시까지 주민 대안 안내"))
    return "\n".join(L)

# ── 인쇄용 보고서 (PDF로 저장) ──
CSS = """
@page{size:A4;margin:16mm 14mm}
*{box-sizing:border-box}body{font:13.5px/1.6 "IBM Plex Sans KR","Malgun Gothic","Apple SD Gothic Neo",sans-serif;color:#1d2b2a;margin:0;background:#eef1f0;word-break:keep-all}
.sheet{max-width:820px;margin:20px auto;background:#fff;padding:28px 32px;box-shadow:0 1px 3px rgba(0,0,0,.12)}
.bar{max-width:820px;margin:16px auto 0;display:flex;gap:8px;justify-content:flex-end}
.bar button{font:inherit;border:1px solid #0e7a5f;background:#0e7a5f;color:#fff;border-radius:6px;padding:7px 14px;cursor:pointer}
.bar button.sub{background:#fff;color:#0e7a5f}
h1{font-size:21px;margin:0 0 4px;letter-spacing:-.01em}.meta{color:#5d6b69;margin:0 0 18px;font-size:12.5px}
h2{font-size:15px;margin:22px 0 8px;padding-bottom:4px;border-bottom:1.5px solid #1d2b2a}
.kpi{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid #c9d2cf;margin:6px 0 4px}
.kpi div{padding:8px 10px;border-right:1px solid #c9d2cf}.kpi div:last-child{border-right:0}
.kpi b{display:block;font-size:19px}.kpi span{font-size:12px;color:#5d6b69}
.kpi .u b{color:#c5221f}.kpi .a b{color:#b26a00}.kpi .w b{color:#1a5fb4}
table{width:100%;border-collapse:collapse;margin:4px 0 6px;font-size:12.5px}
th,td{border:1px solid #c9d2cf;padding:5px 7px;text-align:left;vertical-align:top}th{background:#f1f4f2;font-weight:600}
td.n{text-align:right;white-space:nowrap}
.item{border:1px solid #c9d2cf;padding:10px 12px;margin:8px 0;break-inside:avoid}
.item h3{margin:0 0 2px;font-size:14px}.lv{display:inline-block;font-size:11.5px;padding:0 6px;border-radius:4px;margin-right:6px;color:#fff;background:#b26a00}
.lv.u{background:#c5221f}.item p{margin:2px 0}.item ul{margin:4px 0 0;padding-left:18px}
.none{color:#5d6b69;margin:2px 0 6px}.foot{margin-top:22px;font-size:11.5px;color:#5d6b69;border-top:1px solid #c9d2cf;padding-top:8px}
@media print{body{background:#fff}.sheet{box-shadow:none;margin:0;max-width:none;padding:0}.bar{display:none}}
"""
def report_html(b, gu=None, run=None, auto_print=False, title=None):
    e = lambda s: html.escape(str(s if s is not None else ""))
    R = rows(b, gu); it = R["항목"]; wt = R["관찰"]
    when = (run or {}).get("시작") or b.get("만든때") or ""
    hm = re.search(r"T(\d{2}):(\d{2})", when); t = f" {int(hm[1]):02d}:{hm[2]} 점검" if hm else ""
    H = [f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(title or '생활 기능 공백 일일 보고')} {e(_d(b['날짜']))} {e(gu or '대구 전체')}</title><style>{CSS}</style></head><body>",
         "<div class='bar'><button class='sub' onclick='window.close()'>닫기</button><button onclick='window.print()'>PDF로 저장 · 인쇄</button></div><div class='sheet'>",
         f"<h1>{e(title or '생활 기능 공백 일일 보고')}</h1><p class='meta'>{e(_dw(b['날짜']))}{e(t)} · {e(_scope_title(gu))} · 기능상속 AI 에이전트 작성</p>",
         "<h2>1. 점검 개요</h2>",
         f"<div class='kpi'><div class='u'><b>{sum(1 for r in it if r.get('등급') == '긴급')}</b><span>긴급</span></div><div class='a'><b>{sum(1 for r in it if r.get('등급') != '긴급')}</b><span>주의</span></div>"
         f"<div class='w'><b>{len(wt)}</b><span>관찰</span></div><div><b>{len(R['확인요청'])}</b><span>폐업 확인 필요</span></div></div>"]
    # (10/22 헌준님) 폐업 건수 누계·판정 대상 아님 같은 집계는 빼고, 대구 전체 표는 할 일이 있는 구·군만
    if not (it or wt or R["확인요청"]): H.append("<p class='none'>오늘 새로 생긴 공백·확인할 폐업 없음 · 아래는 원래 시설이 없는 구역 등 상시 확인 자료</p>")
    if not gu:
        gs_ = [g for g in _gus(b, None) if b["구군"][g].get("긴급", 0) + b["구군"][g].get("주의", 0) + b["구군"][g].get("관찰", 0) + len(b["구군"][g].get("확인요청", []))]
        if gs_:
            H.append("<table><tr><th>구·군</th><th>긴급</th><th>주의</th><th>관찰</th><th>폐업 확인 필요</th></tr>")
            for g in gs_:
                v = b["구군"][g]; H.append(f"<tr><td>{e(g)}</td><td class='n'>{v.get('긴급', 0)}</td><td class='n'>{v.get('주의', 0)}</td><td class='n'>{v.get('관찰', 0)}</td><td class='n'>{len(v.get('확인요청', []))}</td></tr>")
            H.append("</table>")
    H.append("<h2>2. 조치 필요 (긴급·주의)</h2>")
    if not it: H.append("<p class='none'>해당 없음</p>")
    for r in sorted(it, key=lambda r: r.get("등급") != "긴급"):
        H.append(f"<div class='item'><h3><span class='lv{' u' if r.get('등급') == '긴급' else ''}'>{e(r['등급'])}</span>{e(r['상호'])}</h3>"
                 f"<p>{e(r['업종'])} · {e(r['구군'])} {e(_loc(r, False))} · {e(_d(r.get('폐업일자')))} 폐업" + (" · 처리 완료" if r.get("처리") else "") + "</p>"
                 f"<p><b>영향</b> {e(_impact(r))}</p>")
        if r.get("위험"): H.append("<p><b>예상 문제</b></p><ul>" + "".join(f"<li>{e(x)}</li>" for x in r["위험"]) + "</ul>")
        if r.get("대응"): H.append("<p><b>검토할 일</b></p><ul>" + "".join(f"<li>{e(a['할일'])}" + (f" ({e(a['담당'])})" if a.get("담당") else "") + (f" — {e(a['근거'])}" if a.get("근거") else "") + "</li>" for a in r["대응"]) + "</ul>")
        if r.get("대체시설"): H.append("<p><b>대체 시설</b> " + e(" · ".join(f"{a['상호']}" + (f"(도보 {round(a['걷는시간_분'])}분)" if a.get("걷는시간_분") is not None and a["걷는시간_분"] <= 40 else "") for a in r["대체시설"])) + "</p>")
        if r.get("판단까닭"): H.append(f"<p><b>판단 근거</b> {e(r['판단까닭'])}</p>")
        H.append("</div>")
    H.append("<h2>3. 관찰 (조치 불필요 · 매일 재검토)</h2>")
    if not wt: H.append("<p class='none'>해당 없음</p>")
    else:
        H.append("<table><tr><th>시설</th><th>업종</th><th>위치</th><th>폐업일</th><th>판단 근거</th></tr>")
        for r in wt: H.append(f"<tr><td>{e(r['상호'])}</td><td>{e(r['업종'])}</td><td>{e(r['구군'])} {e(_loc(r, False))}</td><td>{e(_md(r.get('폐업일자')))}</td><td>{e(r.get('까닭'))}</td></tr>")
        H.append("</table>")
    H.append("<h2>4. 폐업 확인 필요</h2>")
    if not R["확인요청"]: H.append("<p class='none'>해당 없음</p>")
    else:
        H.append("<table><tr><th>시설</th><th>위치</th><th>확인 사유</th><th>폐업 시 예상</th><th>전화</th></tr>")
        for r in R["확인요청"]:
            why = re.sub(r"^[^:]+:\s*", "", str(r.get("까닭") or ""))
            H.append(f"<tr><td>{e(r['상호'])}<br><small>{e(r['업종'])}</small></td><td>{e(r['구군'])} {e(_loc(r, False))}</td><td>{e(why)}</td>"
                     f"<td>{e(r.get('닫았다면') or '')}" + (f"<br><small>{e((r.get('닫았다면_까닭') or [''])[0])}</small>" if r.get("닫았다면_까닭") else "") + f"</td><td>{e(r.get('전화') or '')}</td></tr>")
        H.append("</table>")
    H.append("<h2>5. 참고: 오늘 확정된 폐업 (대체 시설이 있어 공백 없음)</h2>")
    done = [r for r in R["검토완료"] if r.get("확정일") == b["날짜"]]   # 오늘 확정분만, 시설과 까닭 (업종별 건수 같은 집계는 넣지 않음)
    if not done: H.append("<p class='none'>없음</p>")
    else:
        H.append("<table><tr><th>시설</th><th>위치</th><th>폐업일</th><th>공백이 없는 까닭</th></tr>")
        for r in sorted(done, key=lambda r: not r.get("공공"))[:20]: H.append(f"<tr><td>{e(r['상호'])}<br><small>{e(r['업종'])}</small></td><td>{e(r['구군'])} {e(_loc(r, False))}</td><td>{e(_md(r.get('폐업일자')))}</td><td>{e(r.get('까닭'))}</td></tr>")
        H.append("</table>")
        if len(done) > 20: H.append(f"<p class='none'>외 {len(done) - 20}곳</p>")
    if R["공백구역"]:
        H.append("<h2>6. 기능 공백 구역 (식료품점·약국·동네 의원 도보권 부재)</h2><table><tr><th>위치</th><th>시설</th><th>원인</th><th>주민(65세 이상)</th><th>최근접 도보</th></tr>")
        for r in sorted(R["공백구역"], key=lambda r: -(r.get("주민") or 0))[:15]:
            H.append(f"<tr><td>{e(r['구군'])} {e(_loc(r, False))}</td><td>{e(r.get('시설'))}</td><td>{e(r.get('원인'))}</td><td class='n'>{_n(r.get('주민'))}명({_n(r.get('65세이상'))}명)</td><td class='n'>{e(_km(r.get('최근접_m')))}</td></tr>")
        H.append("</table>" + (f"<p class='none'>외 {len(R['공백구역']) - 15}곳 · 엑셀에서 전체 확인</p>" if len(R["공백구역"]) > 15 else ""))
    if R["단절우려"]:
        H.append("<h2>7. 단절 우려 시설 (영업 중 · 폐업 시 대체 수단 부족)</h2><table><tr><th>시설</th><th>위치</th><th>기능</th><th>폐업 시 기준 거리 안에 이용할 곳이 없어지는 주민</th><th>다음 시설(직선)</th></tr>")
        for r in sorted(R["단절우려"], key=lambda r: -(r.get("주민") or 0))[:15]:
            H.append(f"<tr><td>{e(r['상호'])}</td><td>{e(r['구군'])} {e(_loc(r, False))}</td><td>{e(r.get('기능'))}</td><td class='n'>{_n(r.get('주민'))}명(65세 이상 {_n(r.get('65세이상'))}명)</td><td class='n'>{e(_km(r.get('가장가까운_직선_m')))}</td></tr>")
        H.append("</table>")
    if R["주민수요"]:
        H.append("<h2>8. 도보권 미충족 상담 (최근 30일)</h2><p class='none'>주민 상담에서 찾은 기능의 시설이 도보 거리 안에 없던 경우의 자동 집계 · 주민의 직접 설치 요청 아님</p><table><tr><th>위치</th><th>기능</th><th>상담</th><th>최근</th></tr>")
        for r in sorted(R["주민수요"], key=lambda r: -r["건수"])[:15]:
            H.append(f"<tr><td>{e(r['구군'])} {e(r['행정동'])}</td><td>{e(r['기능이름'])}</td><td class='n'>{r['건수']}건</td><td>{e(_md(r.get('마지막')))}</td></tr>")
        H.append("</table>")
    H.append("<p class='foot'><b>용어</b> " + " · ".join(f"{k}: {v}" for k, v in GLOSS) + "</p>")
    H.append("<p class='foot'>자료: 행정안전부 지방행정 인허가, 소상공인시장진흥공단 상가정보, 건강보험심사평가원, 유치원알리미, 어린이집정보공개포털 등 · 주민 수: 행정동 인구의 100m 단위 배분 추정 · 거리: 걷는 길 기준 · "
             "공백 심각도는 계산 교차검증과 독립 검토를 거친 AI 판단이며 담당자 확인으로 바로잡을 수 있음</p></div>")
    if auto_print: H.append("<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),300))</script>")
    H.append("</body></html>")
    return "".join(H)

# ── 엑셀 (.xlsx, 표준 라이브러리만) ──
def _col(i):
    s = ""
    while True:
        i, r = divmod(i, 26); s = chr(65 + r) + s
        if i == 0: return s
        i -= 1
def xlsx(sheets):
    """sheets: [(시트이름, 머리글 목록, 행 목록)] → .xlsx 바이트. 첫 줄 굵게·고정, 숫자는 숫자로"""
    x = lambda s: html.escape(str(s), quote=False).replace("\x00", "")
    buf = io.BytesIO(); z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    n = len(sheets)
    z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
               + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(n)) + "</Types>")
    z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
               + "".join(f'<sheet name="{x(nm[:31])}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, (nm, _, _) in enumerate(sheets)) + "</sheets></workbook>")
    z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(n))
               + f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    z.writestr("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0"/></numFmts><fonts count="2"><font><sz val="11"/><name val="맑은 고딕"/></font><font><b/><sz val="11"/><name val="맑은 고딕"/></font></fonts>'
               '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFEEF1F0"/></patternFill></fill></fills><borders count="2"><border/><border><left style="thin"><color rgb="FFC9D2CF"/></left><right style="thin"><color rgb="FFC9D2CF"/></right><top style="thin"><color rgb="FFC9D2CF"/></top><bottom style="thin"><color rgb="FFC9D2CF"/></bottom></border></borders>'
               '<cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="4"><xf/><xf fontId="1" fillId="2" borderId="1" applyFont="1" applyFill="1" applyBorder="1"/><xf borderId="1" applyBorder="1"><alignment wrapText="1" vertical="top"/></xf><xf numFmtId="164" borderId="1" applyNumberFormat="1" applyBorder="1"><alignment vertical="top"/></xf></cellXfs></styleSheet>')
    for i, (nm, head, body) in enumerate(sheets):
        width = [max([len(str(h)) * 2 + 2] + [min(60, len(str(r[j])) * 2 + 2) for r in body[:200] if j < len(r) and r[j] is not None]) for j, h in enumerate(head)]
        S = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>']
        S += [f'<col min="{j + 1}" max="{j + 1}" width="{max(8, min(60, w))}" customWidth="1"/>' for j, w in enumerate(width)]
        S.append("</cols><sheetData>")
        for ri, row in enumerate([head] + list(body)):
            cells = []
            for j, v in enumerate(row):
                ref = f"{_col(j)}{ri + 1}"
                if v is None or v == "": cells.append(f'<c r="{ref}" s="{1 if ri == 0 else 2}"/>'); continue
                if ri and isinstance(v, (int, float)) and not isinstance(v, bool): cells.append(f'<c r="{ref}" s="3"><v>{v}</v></c>')
                else: cells.append(f'<c r="{ref}" t="inlineStr" s="{1 if ri == 0 else 2}"><is><t xml:space="preserve">{x(v)}</t></is></c>')
            S.append(f'<row r="{ri + 1}">' + "".join(cells) + "</row>")
        S.append(f'</sheetData><autoFilter ref="A1:{_col(max(0, len(head) - 1))}{len(body) + 1}"/></worksheet>')
        z.writestr(f"xl/worksheets/sheet{i + 1}.xml", "".join(S))
    z.close(); return buf.getvalue()

def _num(v):
    try: return int(round(float(v)))
    except Exception: return None
TABLES = {   # 엑셀로 내보낼 수 있는 표 (대화의 make_document와 화면 버튼이 같은 이름을 씀)
    "폐업": "폐업 시설 판정 (공백 심각도·검토 완료)", "확인요청": "폐업 확인 필요", "확인대기": "운영 미확정 (공백 없음·AI 확인 중)", "공백구역": "기능 공백 구역", "주민문의": "도보권 미충족 상담", "단절우려": "단절 우려 시설"}
def table(b, kind, gu=None, only=None, dong=None, since=None):
    if since:   # 기간 거름 (10/22 '이번 주 폐업 현황'): 폐업일이 since 이후인 행만 (폐업·확인 요청 표)
        H, B = table(b, kind, gu, only, dong)
        if kind == "폐업": return H, [r for r in B if str(r[6] or "") >= since]
        return H, B
    R = rows(b, gu, dong)
    flt = (lambda r: True) if not only else (lambda r: only in " ".join(str(r.get(k) or "") for k in ("기능", "기능이름", "시설", "업종", "상호", "까닭")))
    if kind == "폐업":
        H = ["구분", "구·군", "행정동", "마을(리)", "시설", "업종", "폐업일", "판단 근거", "확정 근거", "확정일", "안내 종료일"]
        B = [[r["등급"], r["구군"], r.get("행정동"), r.get("리") or "", r["상호"], r["업종"], r.get("폐업일자"), _impact(r), "", "", ""] for r in R["항목"] if flt(r)]
        B += [["관찰" if r.get("관찰") else (r.get("구분") or "공백 없음"), r["구군"], r.get("행정동"), r.get("리") or "", r["상호"], r["업종"], r.get("폐업일자"), r.get("까닭"), r.get("확정근거"), r.get("확정일"), r.get("공개까지")]
              for r in R["관찰"] + R["검토완료"] if flt(r)]
    elif kind == "확인요청":
        H = ["구·군", "행정동", "마을(리)", "시설", "업종", "확인 사유", "폐업 시 예상", "전화"]
        B = [[r["구군"], r.get("행정동"), r.get("리") or "", r["상호"], r["업종"], re.sub(r"^[^:]+:\s*", "", str(r.get("까닭") or "")), r.get("닫았다면"), r.get("전화")] for r in R["확인요청"] if flt(r)]
    elif kind == "확인대기":   # 운영 여부는 엇갈리나 닫혀도 공백이 없어 담당자 확인 없이 AI가 계속 확인하는 곳
        H = ["구·군", "시설", "업종", "운영 미확정 사유", "폐업 시 공백"]
        B = [[r["구군"], r["상호"], r["업종"], r.get("까닭"), "없음"] for r in R["확인대기"] if flt(r)]
    elif kind == "공백구역":
        H = ["구·군", "행정동", "구역 위치(인구 밀집 지점)", "부재 시설", "원인", "주민(추정)", "65세 이상", "기준 거리(m)", "최근접 도보(m)", "지자체 보고", "창업 참고"]
        B = [[r["구군"], r["행정동"], r.get("리") or "", r.get("시설") or r.get("기능"), r.get("원인"), _num(r.get("주민")), _num(r.get("65세이상")), _num(r.get("기준_m")), _num(r.get("최근접_m")), "예" if r.get("보고") else "", (r.get("창업참고") or {}).get("적합도", "")]
             for r in sorted(R["공백구역"], key=lambda r: -(r.get("주민") or 0)) if flt(r)]
    elif kind == "주민문의":
        H = ["구·군", "행정동", "기능", "찾은 시설 종류", "상담 건수", "최근 상담"]
        B = [[r["구군"], r["행정동"], r["기능이름"], ", ".join(r.get("종류") or []), r["건수"], r.get("마지막")] for r in sorted(R["주민수요"], key=lambda r: -r["건수"]) if flt(r)]
    elif kind == "단절우려":
        H = ["구·군", "행정동", "마을(리)", "시설", "업종", "기능", "폐업 시 기준 거리 안에 이용할 곳이 없어지는 주민", "65세 이상", "다음 시설 직선(m)"]
        B = [[r["구군"], r.get("행정동"), r.get("리") or "", r["상호"], r.get("업종"), r.get("기능"), _num(r.get("주민")), _num(r.get("65세이상")), _num(r.get("가장가까운_직선_m"))] for r in sorted(R["단절우려"], key=lambda r: -(r.get("주민") or 0)) if flt(r)]
    else: raise ValueError(kind)
    return H, B
def xlsx_for(b, kinds, gu=None, only=None, dong=None, since=None):
    return xlsx([(TABLES[k] + (f" ({_d(since)} 이후 폐업)" if since and k == "폐업" else ""), *table(b, k, gu, only, dong, since)) for k in kinds])

def diff(b_new, b_old, gu=None):
    """두 날 보고 비교 (10/22 담당자 '어제랑 뭐가 달라졌어요?'): 칸마다 새로 생긴 곳·빠진 곳"""
    A, B = rows(b_new, gu), rows(b_old, gu); out = {"비교": f"{b_old.get('날짜')} → {b_new.get('날짜')}", "칸": {}}
    key = lambda r: r.get("fid") or r.get("id") or (r.get("상호"), r.get("행정동"))
    nm = lambda r: f"{r.get('상호') or (str(r.get('행정동')) + ' ' + str(r.get('시설') or r.get('기능') or ''))}({r.get('구군') or ''} {r.get('행정동') or ''})".replace("( ", "(").replace(" )", ")")
    for k, lab in (("항목", "조치 필요(긴급·주의)"), ("확인요청", "폐업 확인 필요"), ("질문", "판단 확인"), ("관찰", "관찰(지켜볼 곳)"), ("검토완료", "검토 완료(공백 없음)"), ("단절우려", "단절 우려(영업 중)"), ("공백구역", "기능 공백 구역")):
        a = {key(r): r for r in A.get(k, [])}; o = {key(r): r for r in B.get(k, [])}
        new = [nm(a[x]) for x in a if x not in o]; gone = [nm(o[x]) for x in o if x not in a]
        out["칸"][lab] = {"전": len(o), "후": len(a), "새로": new[:8], "새로_수": len(new), "빠짐": gone[:8], "빠짐_수": len(gone)}
    return out
def filename(b, kind, gu=None, ext="xlsx"):
    return f"기능공백_{kind}_{gu or '대구전체'}_{str(b.get('날짜') or '').replace('-', '')}.{ext}"
