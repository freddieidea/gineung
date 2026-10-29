# 약국·병의원 운영시간 (국립중앙의료원 E-GEN, pipeline/build_hours.py) — 카드와 대화에 씀
import csv, json, os, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KST = datetime.timezone(datetime.timedelta(hours=9))
WD = ["월", "화", "수", "목", "금", "토", "일"]
_DEMO = os.environ.get("GINEUNG_DEMO_NOW")   # 영상 시연 서버 전용 (10/24): 이 시각을 '지금'으로 씀 (예: 2026-10-26T10:30). 실제 서버는 설정하지 않음
def _now():
    if _DEMO:
        try: return datetime.datetime.fromisoformat(_DEMO).replace(tzinfo=KST)
        except Exception: pass
    return datetime.datetime.now(KST)
def _load():
    p = os.path.join(ROOT, "data", "processed", "hours.csv")
    if not os.path.exists(p): return {}
    return {r["fid"]: dict(r, 시간표=json.loads(r["시간표"])) for r in csv.DictReader(open(p, encoding="utf-8"))}
H = _load()
def _t(v):   # '0930' → '9:30', '2400' → '24:00'
    return f"{int(v[:2])}:{v[2:]}"
def _span(se):
    s, e = se
    if e < s and e > "0600": return f"{_t(s)}~(끝나는 시간은 전화로 확인)"   # 자료 오류로 보이는 경우 (예: 9:00~8:00)
    return f"{_t(s)}~{('다음날 ' + _t(e)) if e < s else _t(e)}"
def week_text(fid):
    """'평일 9:00~19:00 · 토 9:00~16:00 · 일 쉼 · 공휴일 10:00~14:00' (같은 시간인 요일은 묶음)"""
    h = H.get(fid)
    if not h: return None
    t = h["시간표"]; parts = []
    days = [(d, _span(t[d]) if d in t else "쉼") for d in WD]
    wk = [v for d, v in days[:5]]
    if len(set(wk)) == 1: parts.append(f"평일 {wk[0]}")
    else: parts += [f"{d} {v}" for d, v in days[:5]]
    if days[5][1] == days[6][1]: parts.append(f"토·일 {days[5][1]}")
    else: parts += [f"{d} {v}" for d, v in days[5:]]
    parts.append(f"공휴일 {_span(t['공휴일']) if '공휴일' in t else '쉼'}")
    return " · ".join(parts)
def today_text(fid, now=None):
    """'오늘(금) 9:00~19:00 · 지금 열려 있어요' / '오늘(일)은 쉬는 날이에요'. 공휴일 여부는 모르므로 요일로만"""
    h = H.get(fid)
    if not h: return None
    now = now or _now(); d = WD[now.weekday()]; t = h["시간표"].get(d)
    if not t: return f"오늘({d})은 쉬는 날이에요"
    s, e = t; cur = now.strftime("%H%M")
    if e < s and e > "0600": return f"오늘({d}) {_t(s)}부터 · 끝나는 시간은 전화로 확인해 주세요"
    open_now = (s <= cur < e) if e > s else (cur >= s or cur < e)
    state = "지금 열려 있어요" if open_now else ("아직 열기 전이에요" if cur < s else "오늘은 끝났어요")
    return f"오늘({d}) {_span(t)} · {state}"
def label(fid):
    h = H.get(fid)
    return None if not h else ("영업시간" if h["종류"] == "약국" else "진료시간")

def open_on(fid, when, now=None):
    """when: '지금' | '토' | '일' | '공휴일' | 요일 이름. 운영시간 자료가 없으면 False (모르는 곳은 남기지 않음)"""
    h = H.get(fid)
    if not h: return False
    t = h["시간표"]
    if when == "지금":
        now = now or _now(); d = WD[now.weekday()]; x = t.get(d)
        if not x: return False
        s, e = x; cur = now.strftime("%H%M")
        return (s <= cur < e) if e > s else (cur >= s or cur < e)
    return when in t
