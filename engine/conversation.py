# 대화 흐름 (주민 한 사람과의 대화 전체): 목적 찾기 → 걸음 확인 → 이용 자격 확인 → 대안 찾기 → 없으면 넓히기(동의) → 문의 창구·지자체 기록
# 안전 장치
#  - 주민에게 보여 주는 시설 이름·주소·전화·거리·시간은 모두 대안 찾기 엔진 결과(데이터베이스 값)를 코드가 문장 틀에 넣어 만든다. 언어 모델은 이 문장을 쓰지 않는다
#  - 넓히기는 순서대로, 매번 주민에게 묻고 동의한 경우에만: 같은 세부 종류 → 같은 묶음 → 같은 세부 기능의 다른 묶음 → (대체 가능 목적만) 같은 목적의 다른 세부 기능
#  - 다시 묻기는 최대 3번. 그래도 모르면 대표 선택지를 보여 준다
import re, os
import pandas as pd
from dialogue import Dialogue
from live_places import LiveBanks, LiveError, bank_in, LiveKeyword, LIVE_KW, live_call_taxis
from travel import parse_conditions, Kakao, Stops, TravelError, map_link, place_link, hav, MODES
from live_check import LiveCheck
MODE_OPTS = [("걸어서 가요", "걸어서"), ("버스·지하철 타요", "버스·지하철"), ("차로 가요 (직접 운전하거나 태워 줘요)", "자가용"), ("택시 타요", "택시"),
             ("다니기 어려워요 (집으로 와 주면 좋겠어요)", "다니기 어려움")]
import json as _json, os as _os
def _load_closures():   # 문 닫은 시설과 그 자리의 새 가게 (pipeline/build_closures.py)
    import csv
    p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "data", "processed", "closures.csv")
    if not _os.path.exists(p): return {}
    return {r["fid"]: r for r in csv.DictReader(open(p, encoding="utf-8"))}
CLOSURES = _load_closures()
def closed_line(fid, name):
    """'○○은 2026년 8월에 문을 닫았어요. 그 자리에는 지금 △△(카페)이 있어요.' — 폐업일·새 가게를 아는 만큼만 말함"""
    c = CLOSURES.get(fid) or {}
    d = str(c.get("폐업일자") or "")
    when = f"{int(d[:4])}년 {int(d[5:7])}월에 " if re.match(r"\d{4}-\d{2}", d) else ""
    import datetime as _dt
    if re.match(r"\d{4}-\d{2}-\d{2}", d) and d > _dt.date.today().isoformat():   # (10/29) 폐업 예정 신고
        return f"{josa(name, '은는')} {int(d[5:7])}월 {int(d[8:10])}일에 문을 닫을 예정이에요."
    out = f"{josa(name, '은는')} {when}문을 닫았어요."
    if c.get("새가게"):
        k = str(c.get("새가게업종") or "")
        kind = "" if (not k or k.startswith(("기타", "그 외"))) else k.split("/")[0] + " "   # '기타 한식 음식점'처럼 넓은 이름은 말하지 않음
        out += f" 그 자리에는 지금 {kind}{josa(chr(39) + c['새가게'] + chr(39), '이가')} 있어요."
    return out
SERVICES = {x["id"]: x for x in _json.load(open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "data", "processed", "essential_services.json"), encoding="utf-8"))["서비스"]}
class CardLine(str):
    """카드 한 장의 글(화면 글자와 같음) + 웹 화면이 지도·버튼을 그리는 데 쓰는 값. 값은 모두 엔진 결과(데이터베이스·카카오 응답) 그대로"""
    card = None

def pack(lines):
    # 답 글을 웹 화면용 조각으로: 일반 문장과 카드를 나눔 (글 내용은 text와 똑같음)
    out = []
    for l in lines:
        if isinstance(l, CardLine) and l.card is not None:
            rows = [x.strip() for x in str(l).split("\n")]
            out.append({"card": dict(l.card, 제목=rows[0], 줄=[r for r in rows[1:] if not r.startswith("길찾기:")])})
        else:
            for x in str(l).split("\n"): out.append({"text": x})
    return out

WANT_CHECK = {"주차": "주차할 수 있는지", "휠체어": "휠체어로 들어갈 수 있는지(계단·문턱)", "싼 곳": "가격", "예약": "예약이 필요한지"}
SPEED_OPTS = [("보통으로 걸어요", "보통"), ("천천히 걸어요", "천천히"), ("지팡이·보행기를 쓰거나 오래 못 걸어요", "아주 천천히")]   # 예전 선택지 (말로 답해도 알아듣게 남겨 둠)
# 걸어서 갈 때 묻는 말 (헌준님 지적 10/15: '걸음은 어떠세요?'는 문맥에 안 맞음) → 주민이 실제로 생각하는 단위인 '몇 분까지 걸을 수 있는지'로 묻고, 답을 최대 시간과 걸음 빠르기로 바로 씀
WALK_OPTS = [("10분 안쪽이 좋아요", "보통", 10), ("20분쯤은 괜찮아요", "보통", 20), ("멀어도 괜찮아요", "보통", None), ("걸음이 느린 편이에요", "천천히", None)]
MENU_LEAVES = {"P01.1.04", "P01.1.05", "P01.1.06", "P01.2.01", "P01.2.02"}   # 반찬·외식·배달·카페·빵: 가게마다 메뉴가 다름
BLOGWANT = re.compile(r"평(이|가)?\s*(좋|괜찮|많)|후기\s*(좋|많)|블로그|맛집|유명한|인기\s*(있|많)|소문난|잘한다는|잘하는 ?(데|곳|집)")
QUESTIONISH = re.compile(r"\?|뭐|무엇|무슨|어디|언제|몇|얼마|왜|어떻|어때|어떤 게|있어요|있나요|있어\b|되나요|돼요|되요|되죠|나요|까요|는지|궁금|알려 ?줘|알려 ?주")
YES = re.compile(r"^(네|예|응|좋|괜찮|그래|있어|있습|맞)"); NO = re.compile(r"^(아니|아뇨|없|싫|안 )")
MAX_ASK = 3

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FLOORS = None
def floor_of(fid):
    """가게가 몇 층인지 (data/processed/floors.csv, 모르면 None)"""
    global _FLOORS
    if _FLOORS is None:
        try:
            D = pd.read_csv(os.path.join(ROOT_DIR, "data", "processed", "floors.csv"), dtype={"fid": str}); _FLOORS = dict(zip(D["fid"], D["층"].astype(int)))
        except Exception: _FLOORS = {}
    return _FLOORS.get(str(fid))

def _batchim(word):
    w = re.sub(r"[\s\)\]'\"’”]+$", "", str(word))
    if not w: return False
    ch = w[-1]
    if "가" <= ch <= "힣": return (ord(ch) - 0xAC00) % 28 != 0
    if ch.isdigit(): return ch in "013678"
    return ch.lower() in "lmnr"   # 영어 이름은 대략적으로
def josa(word, pair):
    # pair: "은는", "이가", "을를", "과와", "으로" 처럼 받침 있을 때/없을 때 순서
    if pair == "으로": return f"{word}{'으로' if _batchim(word) and not str(word).endswith('ㄹ') else '로'}"
    a, b = pair[0], pair[1]
    return f"{word}{a if _batchim(word) else b}"
def fmt_phone(p):
    """'0532101234' → '053-210-1234' (원자료에 하이픈 없이 들어온 번호를 읽기 쉽게. 숫자는 바꾸지 않음)"""
    p = str(p or "").strip(); d = re.sub(r"\D", "", p)
    if not d or "-" in p or not re.fullmatch(r"\d+", p): return p
    if d.startswith("02") and len(d) in (9, 10): return f"02-{d[2:-4]}-{d[-4:]}"
    if re.match(r"0(1\d|[3-6]\d|70|50\d)", d) and len(d) in (10, 11): return f"{d[:3]}-{d[3:-4]}-{d[-4:]}" if not d.startswith("050") or len(d) == 11 else d
    if len(d) == 8 and d[0] == "1": return f"{d[:4]}-{d[4:]}"
    return p
def mins(m):
    return max(1, int(round(m)))

def yesno(text):
    t = text.strip()
    if NO.search(t): return False
    if YES.search(t): return True
    return None

FAR_WALK_MIN = 60   # 10/25: 걸어서 이보다 오래 걸리는 곳은 걸음 시간 대신 '걸어가기엔 멀어요 (약 ○km)'로

def _words_rx(ws):
    ws = [re.escape(re.sub(r"\s", "", str(w))) for w in (ws or []) if str(w).strip()]
    return re.compile("|".join(ws)) if ws else None
def _avoided(av, fx, c):   # 맞지 않는 말이 이름에 있으면 뺌. 종류 이름에만 있으면 그 종류가 어울리는 말도 함께 품지 않을 때만 뺌 ('백반·한정식' 종류는 '한정식'을 바라면 남기고, 이름에 '집밥'이 든 곳은 뺌)
    nm = re.sub(r"\s", "", str(c.get("상호") or "")); kd = re.sub(r"\s", "", f"{c.get('업종') or ''} {c.get('세부종류') or ''}")
    if av.search(nm) and not (fx and fx.search(nm)): return True
    return bool(av.search(kd) and not (fx and fx.search(kd)))
def _fit_score(rx, c):   # 가게 이름에 들어 있으면 2 ('○○한정식'), 종류에만 맞으면 1 ('백반·한정식' 종류의 백반집)
    if not rx: return 0
    return 2 if rx.search(re.sub(r"\s", "", str(c.get("상호") or ""))) else (1 if rx.search(_shop_text(c)) else 0)
def _shop_text(c): return re.sub(r"\s", "", f"{c.get('업종') or ''} {c.get('세부종류') or ''} {c.get('상호') or ''}")
DRINK_RX = re.compile(r"주점|생맥주|호프|포차|포장마차|이자카야|와인|칵테일|펍|소주방|맥주")
SNACK_RX = re.compile(r"치킨|피자|족발|보쌈|도시락|반찬|떡볶이|아이스크림|간식")
class Conversation:
    def __init__(self, engine, dialogue=None):
        self.E = engine; self.D = dialogue or Dialogue(engine); self._banks = None; self._kw = None
        self.kakao = None; self.live = None; self._stops = None   # 처음 쓸 때 만듦 (시험에서는 가짜로 바꿔 끼움)

    def _kakao(self):
        if self.kakao is None: self.kakao = Kakao()
        return self.kakao
    def _live(self):
        if self.live is None: self.live = LiveCheck()
        return self.live
    def _blog(self):
        if getattr(self, "blog", None) is None:
            from blog import BlogSearch
            self.blog = BlogSearch()
        return self.blog
    def _stops_(self):
        if self._stops is None: self._stops = Stops(self.E)
        return self._stops
    def _busnet_path(self, alon, alat, blon, blat, routes):
        """버스 구간 지도 선: 버스 길 그물 → 안 되면 걷는 길 (bus.BusNet)"""
        if getattr(self, "_busnet", None) is None:
            try:
                from bus import BusNet
                self._busnet = BusNet(self._bus_())
            except Exception: self._busnet = False
        p = self._busnet.path(alon, alat, blon, blat, routes) if self._busnet else None
        return p or self.E.walk.path(alon, alat, blon, blat, max_m=20000)
    def alt_reachable(self, st, res, lid):
        """(10/29 헌준님) 걸어서 갈 곳이 기준 거리 안에 없어도 대체 시설을 이용할 수 있으면 생활 공백이 아님 → 구청에 알리지 않음
        이용 가능: ① 가장 가까운 곳이 기준 거리의 2배 안(기능 공백 구역과 같은 기준) ② 버스로 30분(갈아타면 40분) 안"""
        far = [c for c in (res.get("멀리") or []) + (res.get("확인필요후보") or []) if c.get("경도") is not None]   # 운영 여부만 확인하면 되는 곳(예: 노인복지관 경로식당)도 대체 시설로 봄
        if not far: return False
        try:
            import severity as SV
            if lid in SV.STD: std = SV.STD[lid][0]
            else:
                from impact import threshold
                std = int(threshold(self.E.leaf[lid])[0] * 60)
        except Exception: std = None
        walk = [c.get("걷는거리_m") for c in far if c.get("걷는거리_m")]
        if std and walk and min(walk) <= 2 * std: return True
        try:
            BU = self._bus_(); O = BU.origin(st["lon"], st["lat"], "보통")
            if O:
                for c in far:
                    p1 = BU.plan(O, c["경도"], c["위도"])
                    if p1 and p1.get("예상_분", 99) <= 30: return True
                    p2 = BU.plan_transfer(O, c["경도"], c["위도"])
                    if p2 and p2.get("예상_분", 99) <= 40: return True
        except Exception: pass
        return False
    def _bus_(self):
        if getattr(self, "_bus", None) is None:
            from bus import Bus
            self._bus = Bus(self.E)
        return self._bus

    # ── 생활 필수 서비스 (시설이 아닌 서비스: 나드리콜·장기요양 신청 등) ─────────────────────
    #  원칙: 필요해 보일 때만 제안하고, 주민이 원할 때만 안내·연결. 자격은 판정하지 않고 '이런 분이 이용할 수 있어요'로만.
    #  번호·대상은 공식 출처에서 확인한 것만 (essential_services.json). 연결은 전화 걸기·누리집까지 (개인 정보를 대신 넘기지 않음)
    #  위급한 말(자살·학대)은 묻지 않고 바로 안내
    def _svc_card(self, sid):
        v = SERVICES[sid]
        t = [f"[{v['이름']}]", v["하는일"], f"이용할 수 있는 분: {v['대상']}", "이용 방법:"] + [f"  {i + 1}) {x}" for i, x in enumerate(v["이용방법"])]
        if v.get("요금"): t.append(f"요금: {v['요금']}" + (f" · 운영: {v['운영']}" if v.get("운영") else ""))
        t.append(f"전화: {v['전화']}" + (f" · 누리집: {v['누리집']}" if v.get("누리집") else ""))
        t.append(f"(안내 출처: {v['출처']})")
        return "\n".join(t)

    def _crisis(self, text):
        for sid, v in SERVICES.items():
            if v.get("위급") and re.search(v["제안"]["말"], text or ""): return sid
        return None

    def _svc_suggest(self, st):
        cond = st.get("cond", {}); said = " ".join(h["text"] for h in st.get("history", []) if isinstance(h, dict) and h.get("role") == "user")
        out = []
        for sid, v in SERVICES.items():
            if v.get("위급") or sid in st.get("svc_offered", set()): continue
            c = v["제안"]
            hit = (st.get("leaf") in v["기능"]) or (cond.get("mode") in c.get("mode", [])) or any(w in c.get("wants", []) for w in cond.get("wants", [])) or (c.get("말") and re.search(c["말"], said))
            if "자격없음" in c:   # 장기요양 등급이 있어야 하는 곳을 찾는데 '아니요/모르겠어요'라고 한 경우
                hit = hit or any("장기요양" in str(self.E.kind.get((st.get("leaf"), k), {}).get("elig", "")) for k in st.get("elig_no", set()))
            if hit: out.append(sid)
        return out[:1]   # 한 번에 하나만 제안 (어르신께 한꺼번에 여러 개를 묻지 않음)

    def _svc_offer(self, st, r):
        # 결과 뒤에 서비스 제안을 붙임 (주민이 원할 때만 안내)
        if r.get("type") not in ("result", "end"): return r
        sug = self._svc_suggest(st)
        if not sug: return r
        sid = sug[0]; st["svc_offered"] = st.get("svc_offered", set()) | {sid}; st["svc_pending"] = sid; st["stage"] = "svc_offer"
        v = SERVICES[sid]; q = f"{josa(v['이름'].split(' (')[0], '을를')} 이용하실 수도 있어요. {v['하는일']} 이용 방법을 알려 드릴까요?"
        out = dict(r, type="question", text=(r.get("text", "") + "\n" + q).strip(), options=["네, 알려 주세요", "아니요, 괜찮아요"])
        if "blocks" in r: out["blocks"] = r["blocks"] + [{"text": q}]
        return out

    # 주민의 말마다 이동 조건(이동 수단·출발 장소·최대 시간·이용 시간·원하는 조건)을 찾아 쌓음. 새로 말한 것이 앞의 것을 바꿈
    def _absorb(self, st, text):
        c = parse_conditions(text); cond = st.setdefault("cond", {})
        if BLOGWANT.search(text or ""): c["sort"] = "블로그"   # '평 좋은 데', '블로그에 많이 나온 데', '맛집' → 블로그 글이 많은 순 (별점 대신, 10/15)
        if c.get("origin_text") and c["origin_text"] != cond.get("origin_text"): st["origin_done"] = False
        for k in ("when", "wants"):
            if k in c: c[k] = list(dict.fromkeys(cond.get(k, []) + c[k]))
        cond.update(c)
        if cond.get("mode") in ("걸어서", "다니기 어려움") and re.search(r"지팡이|보행기|휠체어|오래 못|못 걸|힘들|천천히|느리|느려|보통", text or ""):
            st["speed"] = self._parse_speed(text)
        return c

    # 금융: 대구 전체 은행 목록이 공공데이터에 없어, 주민이 물을 때 카카오맵에서 그 자리에서 찾는다 (결과는 저장하지 않음)
    LIVE_BANK = {"P05.1.01": "모두", "P05.1.02": "창구", "P05.1.03": "창구", "P05.1.04": "모두"}   # 현금·송금은 ATM도, 공과금·창구 업무는 은행 창구만
    def _live_banks(self, st, res):
        if self._banks is None: self._banks = LiveBanks(self.E.walk)
        said = " ".join(h.get("text", "") if isinstance(h, dict) else str(h) for h in st.get("history", []))
        try: cards = self._banks.search(st["lon"], st["lat"], what=self.LIVE_BANK[st["leaf"]], bank=bank_in(said), n=3, speed=st["speed"])
        except LiveError as e: res["실시간오류"] = str(e); return res
        mix = cards + res["추천"]   # 은행(실시간) + 우체국(데이터베이스) — 걷는 거리 순으로
        mix.sort(key=lambda c: (c["걷는거리_m"] is None, c["걷는거리_m"] if c["걷는거리_m"] is not None else c["직선거리_m"]))
        res["추천"] = mix[:3]; res["실시간"] = sum(1 for c in res["추천"] if c.get("실시간"))
        return res

    def _live_kw(self, st, res):
        if self._kw is None: self._kw = LiveKeyword(self.E.walk)
        try: sure, unsure = self._kw.search(st["leaf"], st["lon"], st["lat"], n=5, speed=st["speed"])
        except LiveError as e: res["실시간오류"] = str(e); return res
        res["추천"] = sure; res["제공여부확인필요"] = unsure; res["실시간"] = len(sure) + len(unsure); res["실시간목적"] = st["leaf"]
        return res

    # 택시: 시설이 아니라 부르는 방법을 안내 (앱 두 가지 + 가까운 콜택시 전화). 거동이 불편하면 나드리콜을 함께 안내
    def _taxi(self, st):
        st["stage"] = "done"
        lines = ["택시는 이렇게 부르실 수 있어요.", "· 휴대폰 앱: 카카오T, 또는 대구시가 만든 '대구로' 앱의 택시 호출"]
        calls = []
        try:
            if getattr(self, "taxis", None): calls = self.taxis(st["lon"], st["lat"])   # 검사에서 가짜로 바꿔 끼움
            else: calls = live_call_taxis(open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "settings", "kakao_key.txt"), encoding="utf-8").read().strip(), st["lon"], st["lat"])
        except Exception: calls = []
        if calls: lines.append("· 전화로 부르기: " + ", ".join(f"{c['이름']} {c['전화']}" for c in calls) + " (카카오맵에 '콜택시'로 등록된 곳, 지금 찾은 결과)")
        else: lines.append("· 전화로 부르려면 동네에서 쓰시는 콜택시 번호로 거시면 돼요. (지금 가까운 콜택시를 찾지 못했어요)")
        lines.append("휠체어를 쓰시거나 혼자 타고 내리기 어려우시면 나드리콜을 부르실 수 있어요. 이용 방법을 알려 드릴까요?")
        st["svc_pending"] = "나드리콜"; st["stage"] = "svc_offer"
        return {"type": "question", "text": "\n".join(lines), "options": ["네, 알려 주세요", "아니요, 괜찮아요"], "connect_options": calls}

    def start(self, lon, lat, gu=None, closed_fid=None):
        st = {"lon": lon, "lat": lat, "home": (lon, lat), "gu": gu, "closed_fid": closed_fid, "stage": "purpose", "history": [], "asked": 0, "elig_ok": set(), "ladder": 0, "cond": {}}
        if closed_fid:
            fs = [f for f in self.E.functions_of(closed_fid) if f["role"] == "주" and f["confidence"] in ("높음", "보통")]
            r = self.E.F.loc[closed_fid]
            names = list(dict.fromkeys(f["name"] for f in fs))
            closed = "폐업" in str(r.get("인허가상태", "")) or str(r.get("대안후보", "")) == "아니요" and "폐업" in str(r.get("제외사유", ""))
            first = closed_line(closed_fid, r['상호']) if closed else f"{r['상호']} 대신 갈 만한 곳을 찾아 드릴게요."   # 실제로 닫은 곳이 아니면 닫았다고 말하지 않음
            pairs = list(dict.fromkeys((f["leaf"], f.get("kind") if f.get("kind") not in (None, "None", "") else None) for f in fs))
            nm = r['상호']
            # 규칙(10/15): 이미 아는 것은 묻지 않음. 하던 일이 하나로 분명하면 확인만 하고, 여럿이면 그 일들을 선택지로 보여 줌
            if len(pairs) == 1 and pairs[0][1] and not self.E.kind.get(pairs[0], {}).get("mixed") in (True, "True"):
                st["stage"] = "confirm"; st["confirm_pair"] = pairs[0]
                st["opening"] = f"{first} {nm} 대신 갈 만한 {josa(self._place_word(*pairs[0]), '을를')} 찾아 드릴까요?"
                st["opening_options"] = ["네, 찾아 주세요", "다른 일로 다녔어요"]
            elif names:
                st["purpose_opts"] = {}
                for f in fs:
                    st["purpose_opts"].setdefault(f["name"], (f["leaf"], f.get("kind") if f.get("kind") not in (None, "None", "") else None))
                ops = list(st["purpose_opts"])[:4]
                joined = ", ".join(f"'{x}'" for x in ops[:-1]) + (" 아니면 " if len(ops) > 1 else "") + f"'{ops[-1]}'"
                st["opening"] = f"{first} {nm}에서는 주로 {joined} 같은 일을 {'하셨을' if closed else '하실'} 텐데요, 어떤 일로 {'다니셨어요' if closed else '가세요'}?"
                st["opening_options"] = ops + ["다른 일이에요"]
            else:   # 주 기능이 확실하지 않은 업종: 짐작해서 말하지 않음
                st["opening"] = f"{first} {nm}에 어떤 일로 {'다니셨어요' if closed else '가세요'}?"
        else:
            st["opening"] = "어떤 곳을 찾으세요? 하시려는 일을 편하게 말씀해 주세요."
        return st

    # 주민의 말 한 번 → 다음 응답 (질문 또는 결과)
    def turn(self, st, text):
        crisis = self._crisis(text)
        r = self._turn(st, text)
        if r.get("type") == "question" and not r.get("agent"): st["last_q"] = {"text": r.get("text", ""), "options": r.get("options") or []}
        if crisis:   # 위급한 말은 묻지 않고 맨 앞에 바로 안내 (대화는 이어 감)
            v = SERVICES[crisis]
            msg = (f"말씀해 주셔서 고마워요. 지금 많이 힘드시면 혼자 견디지 마시고 {v['전화']}에 전화해 주세요. {v['하는일']}" if crisis == "자살예방"
                   else f"걱정되는 상황이네요. {v['하는일']} 전화: {v['전화']}")
            r = dict(r, text=msg + "\n\n" + r.get("text", ""), connect={"이름": v["이름"], "전화": v["전화"]}, 위급=crisis)
            if "blocks" in r: r["blocks"] = [{"text": msg, "위급": True}] + r["blocks"]
        return r

    def _turn(self, st, text):
        stage = st["stage"]; st.setdefault("cond", {})
        got = self._absorb(st, text)
        if stage == "confirm":   # 첫마디에서 '○○ 대신 갈 만한 미용실을 찾아 드릴까요?'라고 확인한 경우
            a = yesno(text)
            if a and not re.search(r"다른 일", text):
                st["leaf"], st["kind"] = st.pop("confirm_pair"); st["matches_closed"] = "예"; st["stage"] = "speed"
                if st["leaf"] in MENU_LEAVES:   # 문 닫은 가게 이름에 드러난 메뉴(예: 쭈꾸미)는 그대로 살림
                    try: st["menu_words"] = self.D.pick_kind(st, st["leaf"]).get("menu_words", [])
                    except Exception: st["menu_words"] = []
                return self._next(st)
            st.pop("confirm_pair", None); st["stage"] = "purpose"
            if a is False or re.search(r"^다른 일", text.strip()):
                return {"type": "question", "text": "그럼 어떤 일로 다니셨는지 편하게 말씀해 주세요.", "options": []}
            return self._turn(st, text)   # '파마하러 다녔어요'처럼 바로 목적을 말하면 그대로 알아들음
        if stage == "purpose" and text.strip() in st.get("purpose_opts", {}):   # 첫마디의 선택지를 누른 경우: 언어 모델 없이 바로
            st["leaf"], k = st["purpose_opts"][text.strip()]; st["matches_closed"] = "예"; st["stage"] = "speed"
            if k: st["kind"] = k
            return self._next(st)
        if stage == "purpose" and re.search(r"^다른 일", text.strip()) and st.get("purpose_opts"):
            st.pop("purpose_opts", None)
            return {"type": "question", "text": "어떤 일로 다니셨는지 편하게 말씀해 주세요.", "options": []}
        if stage in ("mode", "speed", "kind", "need", "elig", "widen", "origin", "unsure") and self._side_question(st, text, got):
            return self._agent_reply(st, text)   # 질문에 답하는 대신 주민이 다른 걸 물으면 대화 모델이 답하고, 하던 질문을 다시 여쭘
        if stage == "svc_offer":
            sid = st.pop("svc_pending", None)
            if yesno(text) and sid:
                st["stage"] = "svc_connect"; st["svc_pending"] = sid
                return {"type": "question", "text": self._svc_card(sid) + "\n전화로 바로 연결해 드릴까요?", "options": ["네, 전화 연결해 주세요", "아니요, 나중에 할게요"], "service": sid}
            st["stage"] = "done"; return {"type": "end", "text": "알겠어요. 필요하시면 언제든 다시 말씀해 주세요."}
        if stage == "svc_connect":
            sid = st.pop("svc_pending", None); st["stage"] = "done"
            if yesno(text) and sid:
                v = SERVICES[sid]
                return {"type": "connect", "text": f"{v['이름'].split(' (')[0]}({v['전화']})로 전화를 연결할게요. 화면의 '전화 걸기'를 누르시면 바로 걸려요.", "connect": {"이름": v["이름"], "전화": v["전화"]}, "service": sid}
            return {"type": "end", "text": f"알겠어요. 번호는 {SERVICES[sid]['전화']}예요. 필요하실 때 전화하시면 돼요." if sid else "알겠어요."}
        if stage == "kind":
            ks = st.get("kind_opts", []); t = text.strip()
            hit = [k for k in ks if t == k] or [k for k in ks if t and (t in k or k in t)]
            if len(hit) == 1: st["kind"] = hit[0]; st.pop("kind_opts", None); return self._next(st)
            return {"type": "question", "text": "잘 알아듣지 못했어요. 아래에서 골라 주세요.", "options": ks}
        if stage == "mode":
            for label, key in MODE_OPTS:
                if text.strip() == label: st["cond"]["mode"] = key
            if not st["cond"].get("mode") and not st.get("mode_reasked"):   # 못 알아들으면 한 번 더 여쭤봄
                st["mode_reasked"] = True
                return {"type": "question", "text": "잘 알아듣지 못했어요. 걸어서 가세요, 버스나 차를 타세요?", "options": [o[0] for o in MODE_OPTS]}
            if not st["cond"].get("mode"): st["cond"]["mode"] = "걸어서"; st["mode_guessed"] = True   # 두 번째도 모르면 걸어서로 보고, 결과에 그렇게 적음
            return self._next(st)
        if stage == "origin":
            a = yesno(text)
            if a is None and not st.get("origin_reasked"):   # 네·아니요가 아닌 답이면 한 번 더 물어봄 (조용히 집 근처로 바꾸지 않음)
                st["origin_reasked"] = True; c0 = st["origin_cand"]
                return {"type": "question", "text": f"잘 알아듣지 못했어요. '{c0['이름']}' 근처에서 찾아 드릴까요?", "options": ["네, 거기 근처요", "아니요, 지금 있는 곳 근처로"]}
            cand = st.pop("origin_cand", None); st["origin_done"] = True
            if a and cand: st["lon"], st["lat"] = cand["경도"], cand["위도"]; st["origin_name"] = cand["이름"]
            else: st["lon"], st["lat"] = st["home"]; st.pop("origin_name", None); st["cond"].pop("origin_text", None)
            return self._next(st)
        if stage == "unsure":
            res = st.get("last_result")
            if yesno(text) and res: return self._answer(st, res, show_unsure=True)
            st["stage"] = "done"; return {"type": "end", "text": "알겠어요. 가는 방법이나 동네를 바꿔서 다시 찾고 싶으시면 말씀해 주세요."}
        if stage == "done":
            if got:   # 결과를 본 뒤 조건을 바꿔 말하면(예: '버스로 가면요?', '서문시장 근처로') 다시 찾음
                st.pop("speed", None) if got.get("mode") not in (None, "걸어서", "다니기 어려움") else None
                return self._next(st)
            if re.match(r"^(고마|감사|됐어|됐습|괜찮아요|아니요?$|없어요|그만)", text.strip()):
                return {"type": "end", "text": "네, 도움이 됐으면 좋겠어요. 또 필요하시면 언제든 말씀해 주세요."}
            return self._agent_reply(st, text)   # 결과를 본 뒤의 자유로운 물음(메뉴·후기·주차 등)은 대화 모델이 도구를 써서 답함
        if stage == "purpose":
            r = self.D.step(st, text)
            if r["type"] == "question":
                if r["count"] > MAX_ASK: return self._fallback(st)
                return r
            st["stage"] = "speed"; return self._next(st)
        if stage == "need":
            st["need"] = self._parse_need(st, text); st["need_asked"] = True; return self._next(st)
        if stage == "speed":
            st["speed"] = self._parse_speed(text); st["stage"] = "elig"
            for label, spd, mx in WALK_OPTS:
                if text.strip() == label:
                    st["speed"] = spd
                    if mx: st["cond"]["max_min"] = mx
            if not st["cond"].get("mode"): st["cond"]["mode"] = "걸어서"
            return self._next(st)
        if stage == "elig":
            k = st["elig_kind"]; a = yesno(text)
            if a: st["elig_ok"].add(k)
            else: st["elig_no"] = st.get("elig_no", set()) | {k}
            st["elig_answered"] = st.get("elig_answered", set()) | {k}
            return self._next(st)
        if stage == "widen":
            a = yesno(text)
            if a: st["scope"] = st["pending_scope"]; st["consented"] = st.get("consented", set()) | {st["pending_scope"]}
            else: st["declined"] = st.get("declined", set()) | {st["pending_scope"]}
            return self._next(st)
        return {"type": "end", "text": "대화가 끝났어요. 다시 찾으시려면 새로 시작해 주세요."}

    def _parse_speed(self, text):
        for label, key in SPEED_OPTS:
            if text.strip() == label: return key
        if re.search(r"지팡이|보행기|휠체어|오래 못|못 걸|힘들", text): return "아주 천천히"
        if re.search(r"천천히|느리|느려|느린", text): return "천천히"
        return "보통"

    # 세부 의도 질문 (의도에 따라 대안이 갈리는 종류일 때만 묻는다)
    NEED_Q = {"P01.1.06": ("가게에 가서 포장해 오실 건가요, 집으로 배달받으실 건가요?", [("가서 포장해 올게요", "포장"), ("집으로 배달받고 싶어요", "배달")])}
    NEED_KW = {"포장": r"포장|가서|사 ?[오와올]|들고|픽업|찾으러", "배달": r"배달|집으로|시켜|갖다|가져다"}
    def _parse_need(self, st, text):
        for label, key in self.NEED_Q.get(st["leaf"], ("", []))[1]:
            if text.strip() == label: return key
        hits = [k for k, pat in self.NEED_KW.items() if k in self.E.needs.get(st["leaf"], set()) and re.search(pat, text)]
        return hits[0] if len(hits) == 1 else None

    def _next(self, st):
        E = self.E; lid = st["leaf"]; kind = st.get("kind")
        # 시설이 아니라 서비스로 해결하는 목적 (예: 교통약자 이동 → 나드리콜): 시설 목록 대신 이용 방법을 안내하고, 원하면 전화 연결
        svc = [sid for sid, v in SERVICES.items() if lid in v["기능"]]
        if svc and not (E.leaf[lid].get("kinds") or {}).get("sensitive") in (True, False):
            sid = svc[0]; st["svc_offered"] = st.get("svc_offered", set()) | {sid}; st["svc_pending"] = sid; st["stage"] = "svc_connect"
            return {"type": "question", "text": f"이 일은 시설에 가지 않고 서비스로 도움을 받을 수 있어요.\n{self._svc_card(sid)}\n전화로 바로 연결해 드릴까요?",
                    "options": ["네, 전화 연결해 주세요", "아니요, 나중에 할게요"], "service": sid}
        ks = [k for (l, k) in E.kind if l == lid] if not kind else []
        if len(ks) == 1: st["kind"] = kind = ks[0]
        elif len(ks) > 1:   # 세부 종류가 여럿인데 모르면 짐작하지 않음: 종류를 보여 주고 고르게 함 (종류가 없는 목적은 목적 전체로 찾음)
            st["stage"] = "kind"; st["kind_opts"] = ks
            return {"type": "question", "text": "어떤 곳을 찾으세요?", "options": ks}
        if lid == "P12.1.03": return self._taxi(st)
        if kind and not st.get("need") and not st.get("need_asked") and E.need_choices(lid, kind) and lid in self.NEED_Q:
            st["stage"] = "need"; q, opts = self.NEED_Q[lid]
            return {"type": "question", "text": q, "options": [o[0] for o in opts]}
        cond = st.setdefault("cond", {})
        if not cond.get("mode"):
            st["stage"] = "mode"
            return {"type": "question", "text": f"{self._place_word(lid, kind)}까지는 어떻게 가실 거예요?", "options": [o[0] for o in MODE_OPTS]}
        if cond["mode"] == "다니기 어려움":
            st["speed"] = "아주 천천히"
            if "배달" in E.needs.get(lid, set()) and not st.get("need"): st["need"] = "배달"   # 집으로 가져다주는 방식으로 찾음
        if cond["mode"] in ("자가용", "택시", "버스·지하철") and not st.get("speed"): st["speed"] = "보통"   # 정류장·주차장에서 걷는 시간 계산용
        if cond.get("origin_text") and not st.get("origin_done"):
            try: cands = self._kakao().find_place(cond["origin_text"], *st["home"])
            except TravelError: cands = []
            if cands:
                st["stage"] = "origin"; st["origin_cand"] = cands[0]
                return {"type": "question", "text": f"'{cands[0]['이름']}'({cands[0]['주소']}) 근처에서 찾아 드릴까요?", "options": ["네, 거기 근처요", "아니요, 지금 있는 곳 근처로"]}
            st["origin_done"] = True; st["origin_missing"] = cond.pop("origin_text")
        if not st.get("speed"):
            st["stage"] = "speed"
            if cond.get("max_min"): st["speed"] = st.get("speed") or "보통"   # 몇 분 안이라고 이미 말했으면 다시 묻지 않음
            else: return {"type": "question", "text": "걸어서 얼마나 가실 수 있으세요?", "options": [o[0] for o in WALK_OPTS]}
        # 이용 자격: 지금 찾을 종류들 중 자격이 필요한 것이 있으면 한 번씩 묻는다
        allowed = self._allowed(st)
        for k in allowed:
            v = E.kind.get((lid, k), {})
            if v.get("elig") and k not in st.get("elig_answered", set()):
                st["stage"] = "elig"; st["elig_kind"] = k
                return {"type": "question", "text": f"{josa(k, '은는')} {v['elig']}만 이용할 수 있어요. 해당되세요?", "options": ["네, 해당돼요", "아니요", "잘 모르겠어요"]}
        st["stage"] = "result"
        res = self._core_search(st)
        st["last_result"] = res
        near = res["순위"]; near_check = [c for c in res["이용자격확인필요"] if c["_갈수있음"]]
        # '하는지 확인 필요' 후보는 넓혀도 근거 있는 대안이 없을 때만 보여 줌 (근거 있는 대안을 먼저 찾음)
        if not near and not near_check and self._widen_option(st, peek=True): return self._widen_option(st)
        if near or near_check or res["확인필요후보"]: return self._svc_offer(st, self._answer(st, res))
        # 가까운 대안이 없으면 넓히기 (순서대로, 동의를 받아서)
        nxt = self._widen_option(st)
        if nxt: return nxt
        return self._svc_offer(st, self._answer(st, res, nothing=True))

    def _core_search(self, st):
        """대안 찾기 핵심 (질문 없이): 엔진 → 메뉴 단서 → 실시간(은행·키워드) → 순위 정하기. 옛 대화 흐름과 새 대화 구조(engine/chat.py)가 함께 씀"""
        E = self.E; lid = st["leaf"]; kind = st.get("kind")
        if lid in LIVE_KW:   # 공공데이터에 목록이 없는 목적(농기계 수리): 카카오맵에서 그 자리에서 찾음
            res = {"기능": lid, "기능이름": E.leaf[lid]["name"], "세부종류": None, "범위": "kind", "허용종류": [], "_출발": (st["lon"], st["lat"]), "의도": None,
                   "추천": [], "근거로제외": [], "제공여부확인필요": [], "이용자격확인필요": [], "운영확인필요": [], "자격확인됨": [],
                   "확인할것": "수리해 주는 기계 종류와 출장 수리가 되는지", "대체가능목적": []}
            res = self._live_kw(st, res)
        else:
            ask = lambda n: E.recommend(lid, kind, st["lon"], st["lat"], scope=st.get("scope", "kind"), consent_group="group" in st.get("consented", set()),
                          consent_leaf="leaf" in st.get("consented", set()), exclude=([st["closed_fid"]] if st.get("closed_fid") else []) + list(st.get("exclude_extra") or []),
                          user_gu=st.get("gu"), n=n, elig_ok=st["elig_ok"], speed=st["speed"], need=st.get("need"))
            res = ask(250 if st.get("fit_words") else 80 if (st.get("hours_filter") or st.get("occasion") or st.get("want") or st.get("kind_set_up") or st.get("meal_only") or st.get("fit_words") or st.get("avoid_words")) else 15)
            if st.get("meal_only"):   # (10/29) '식당', '밥집'처럼 종류를 가리지 않고 찾을 때: 밥 먹으러 가는 곳이니 술집(생맥주·요리 주점·호프 등)은 빼고
                for k_ in ("추천", "제공여부확인필요", "운영확인필요"):
                    if isinstance(res.get(k_), list): res[k_] = [c for c in res[k_] if not DRINK_RX.search(str(c.get("업종") or "") + " " + str(c.get("세부종류") or ""))]
                ml = [c for c in res.get("추천", []) if not SNACK_RX.search(str(c.get("업종") or "") + " " + str(c.get("세부종류") or ""))]   # 치킨·피자·족발처럼 시켜 먹는 쪽은 밥집이 넉넉하면 뺌
                if len(ml) >= 3: res["추천"] = ml
            ks_ = st.get("kind_set_up")
            if ks_:   # (10/29) '일식집'처럼 여러 세부 종류를 함께 찾을 때: 그 종류들만 (같은 묶음의 장어죽·조개구이 등은 빼고)
                for k_ in ("추천", "근거로제외", "제공여부확인필요", "이용자격확인필요", "운영확인필요", "자격확인됨"):
                    if isinstance(res.get(k_), list): res[k_] = [c for c in res[k_] if c.get("fid") in ks_[1] or c.get("업종") in ks_[0]]
            hf = st.get("hours_filter")
            if hf:   # '지금·주말에 여는 곳': 가까운 곳이 모두 닫혀 있으면 더 넓게 찾음 (10/20 점검: 밤 10시 범어동에서 1.5km 안 심야약국을 못 찾던 것 고침)
                import hours as HR
                if sum(1 for c in res["추천"] if HR.open_on(c.get("fid"), hf)) < 3: res = ask(600)
        if st.get("menu_words"): res = self._menu_order(st, res)
        if lid in self.LIVE_BANK: res = self._live_banks(st, res)
        if st.get("want") and lid not in LIVE_KW: res = self._apply_want(st, res)   # 주민이 바라는 가게 성격 (engine/wants.py)
        st["want_label"] = (res.get("바람") or {}).get("이름") if st.get("want") else None
        import occasions as O2   # (10/26 헌준님) '카페'는 커피·디저트를 마시는 곳: 만화·보드게임·스터디·룸·키즈·라이브카페·다방은 주민이 그 말을 했거나 문 닫은 곳이 그런 곳일 때만, 그 종류끼리
        closed_nm = self.E.F.loc[st["closed_fid"], "상호"] if st.get("closed_fid") in self.E.F.index else ""
        wanted = O2.wanted_for(st.get("user_text"), closed_nm, st.get("want"))
        for k in ("추천", "제공여부확인필요", "운영확인필요", "이용자격확인필요"):
            if res.get(k):
                kept = []
                wt = wanted & O2.types_for_leaf(lid)
                for c in res[k]:
                    if wt and not O2.types_here(c.get("업종"), lid) & wt and not O2.name_is(wt, c.get("상호")): continue   # (10/26) 룸카페를 찾는데 이름으로 가를 수 없는 다른 업종(디저트 가게)이 '확인 필요'로 끼던 것: 이름이 그 종류일 때만
                    ok, pen = O2.special_check(c.get("업종"), c.get("상호"), wanted, lid)
                    if ok: kept.append(dict(c, _결벌점=max(c.get("_결벌점", 0), pen)) if pen else c)
                res[k] = kept
        occ = st.get("occasion")
        if occ and lid not in LIVE_KW:   # 상황(데이트·아이와·회식 등)에 어울리는 종류만 (engine/occasions.py). '어울림'이 3곳 안 되면 '무난'까지, '안 어울림'은 빼고
            import occasions as O
            keys = ("추천", "제공여부확인필요", "이용자격확인필요", "운영확인필요")
            base = {k: list(res.get(k) or []) for k in keys}
            if occ in O.NEEDS_CAT:   # 디저트·분위기 카페, 2차: 이름만으로 모르는 가게는 카카오맵 분류를 그 자리에서 봄 (가까운 20곳, 판단에만 쓰고 저장·모델 전달 없음)
                self._kakao_kinds(occ, [c for k in keys for c in base[k]][:60])
            for lo in (O.GOOD, O.OK):
                keep = st.get("occ_keep")   # 하던 종류가 그 상대와도 무난하면 '어울림'과 같이 대함 (부모님 모시고 + 경양식집이 문 닫음 → 경양식도 함께)
                fx_ = _words_rx(st.get("fit_words"))   # (10/29) 모델이 사회적 맥락으로 고른 어울리는 곳(틀니 → 죽집 등)은 상황 표에서 덜 어울려도 '어울림'으로
                def tr(c):   # 어울리는 말에 맞아도 그 자리에 아예 맞지 않는 곳(격식 자리의 푸드코트·무한리필)은 그대로 뺌
                    t = O.tier(occ, c.get("업종"), c.get("상호"), (c.get("_live") or ("", "", {}))[2].get("분류"))
                    return O.GOOD if (keep and c.get("업종") == keep) or (fx_ and t != O.BAD and fx_.search(_shop_text(c))) else t
                for k in keys:
                    res[k] = [dict(c, _상황=max(c.get("_상황", 0), int(tr(c) == O.GOOD)), _결벌점=max(c.get("_결벌점", 0), O.penalty(occ, c.get("상호"), (c.get("_live") or ("", "", {}))[2].get("분류")))) for c in base[k] if tr(c) >= lo]
                sure_k = O.CERTAIN.get(occ, set())   # 그 자리에 맞는 일이 확실한 업종(2차 술자리의 요리 주점)은 '이 일을 해 주는지 확인'이 필요 없음
                if sure_k:
                    mv = [c for c in res["제공여부확인필요"] if c.get("업종") in sure_k]
                    for c in mv: c["표시"] = [m for m in c["표시"] if m != "제공 여부 확인 필요"]
                    res["추천"] = res["추천"] + mv; res["제공여부확인필요"] = [c for c in res["제공여부확인필요"] if c not in mv]
                out = self._arrange(st, dict(res))
                if len([c for c in out["순위"] if c["확실성"] != "확인 필요"]) >= 3 or lo == O.OK: break
            out["상황"] = occ; out["상황단계"] = "어울림" if lo == O.GOOD else "어울림·무난"
            st["last_result"] = out
            return out
        res = self._arrange(st, res)
        st["last_result"] = res
        return res

    def _apply_want(self, st, res):
        """주민이 바라는 성격에 맞는 곳을 앞에, 분명히 맞지 않는 곳은 뺌 (engine/wants.py 설명)"""
        import wants as W
        client = getattr(self, "client", None)
        if client is None: return res
        keys = ("추천", "제공여부확인필요", "이용자격확인필요", "운영확인필요")
        allc = [c for k in keys for c in (res.get(k) or [])]
        uniq = {}
        for c in sorted(allc, key=lambda c: c.get("직선거리_m") or 1e9):
            nk = self._name_key(c.get("상호"))
            if nk not in uniq: uniq[nk] = c
        near = list(uniq.values())[:40]
        job = self.E.leaf.get(st["leaf"], {}).get("name", "")
        try:
            from chat import log_usage
            tiers, spec = W.judge(client, st["want"], job, [{"fid": c["fid"], "상호": c["상호"], "업종": c.get("업종"), "세부종류": c.get("세부종류")} for c in near], log_usage)
        except Exception:
            return res
        name_t = {self._name_key(c["상호"]): tiers.get(c["fid"]) for c in near}
        # 이름으로 모르는 앞쪽 가게는 카카오맵 분류로 (그 자리에서 받아 코드로만 대조)
        todo = [c for c in near[:30] if name_t.get(self._name_key(c["상호"])) == W.OK and W.by_words(spec, c["상호"]) == W.OK
                and "_live" not in c and c.get("fid") in self.E.F.index and self.E.F.loc[c["fid"], "출처"] in ("상가", "인허가")]
        if todo and (spec.get("category_good") or spec.get("category_bad")):
            from concurrent.futures import ThreadPoolExecutor
            L = self._live()
            def one(c):
                try: return L.check_detail(c["상호"], float(c["경도"]), float(c["위도"]))
                except Exception: return ("확인 실패", "", {})
            with ThreadPoolExecutor(6) as ex:
                for c, r in zip(todo, ex.map(one, todo)): c["_live"] = r
        cat_of = {self._name_key(c["상호"]): (c.get("_live") or ("", "", {}))[2].get("분류", "") for c in allc if c.get("_live")}
        def tier(c):
            nk = self._name_key(c.get("상호")); t = name_t.get(nk)
            if t is None or t == W.OK:
                t2 = W.by_words(spec, c.get("상호"), cat_of.get(nk, ""))
                t = t2 if t is None or t2 != W.OK else t
            return t
        # 바람에 맞는 이름이 가까운 후보에 모자라면, 그 낱말로 조금 더 넓게(직선 3km) 찾아 보탬 (동성로처럼 가게가 많은 곳에서 와인바가 가까운 80곳 밖에 있던 일)
        words = [re.sub(r"\s", "", w) for w in spec.get("name_good", []) if len(re.sub(r"\s", "", w)) >= 2]
        if words and sum(1 for c in res.get("추천") or [] if tier(c) == W.GOOD) < 3:
            try:
                more = self.E.recommend(st["leaf"], st.get("kind"), st["lon"], st["lat"], scope=st.get("scope", "kind"), consent_group="group" in st.get("consented", set()),
                                        consent_leaf="leaf" in st.get("consented", set()), exclude=([st["closed_fid"]] if st.get("closed_fid") else []) + list(st.get("exclude_extra") or []),
                                        user_gu=st.get("gu"), n=10, max_m=3000, elig_ok=st["elig_ok"], speed=st["speed"], need=st.get("need"), name_words=words)
                have = {c["fid"] for c in allc}
                for k in keys:
                    add = [c for c in (more.get(k) or []) if c["fid"] not in have]
                    res = dict(res); res[k] = list(res.get(k) or []) + add
            except Exception: pass
        out = dict(res); kept_any = False
        for k in keys:
            lst = []
            for c in res.get(k) or []:
                t = tier(c)
                if t == W.BAD: continue
                c = dict(c); c["_상황"] = max(c.get("_상황", 0), int(t == W.GOOD)); c["_바람"] = t == W.GOOD
                if c.get("_live") is None and cat_of.get(self._name_key(c["상호"])): c["_live"] = next((x["_live"] for x in allc if x.get("_live") and self._name_key(x["상호"]) == self._name_key(c["상호"])), None)
                lst.append(c)
            out[k] = lst; kept_any = kept_any or bool(lst)
        if not kept_any: return dict(res, 바람={"말": st["want"], "이름": spec["label"], "맞는곳": 0, "뺀곳": 0, "알림": "바람에 맞지 않는 곳만 있어 그대로 보여 드림"})
        good = sum(1 for k in keys for c in out[k] if c.get("_바람")); dropped = sum(len(res.get(k) or []) - len(out[k]) for k in keys)
        total = sum(len(out[k]) for k in keys)
        if total >= 5 and good >= 0.8 * total:   # 거의 모든 곳이 맞다고 나오면 바람이 가게를 가르지 못하는 것 (예: '가볍게 갈 곳') → 표시·순서에 쓰지 않음
            for k in keys:
                for c in out[k]: c["_바람"] = False; c["_상황"] = 0
            return dict(out, 바람={"말": st["want"], "이름": spec["label"], "맞는곳": 0, "뺀곳": dropped, "알림": "이 바람으로는 가게를 가를 수 없어 가까운 순서로 보여 드림"})
        out["바람"] = {"말": st["want"], "이름": spec["label"], "맞는곳": good, "뺀곳": dropped}
        return out

    def _kakao_kinds(self, occ, cands):
        """앞쪽 후보 가운데 이름만으로는 성격을 모르는 가게(상가·인허가 자료)의 카카오맵 분류를 그 자리에서 받아 둠 (c['_live'], 이 요청 안에서만 씀)"""
        import occasions as O
        from concurrent.futures import ThreadPoolExecutor
        todo = []
        for c in sorted(cands, key=lambda c: c.get("직선거리_m") or 1e9):
            if len(todo) >= 30: break
            if "_live" in c or c.get("fid") not in self.E.F.index or self.E.F.loc[c["fid"], "출처"] not in ("상가", "인허가"): continue
            if any(self._name_key(c.get("상호")) == self._name_key(x.get("상호")) for x in todo): continue
            if O.tier(occ, c.get("업종"), c.get("상호")) != O.OK: continue   # 이름으로 이미 정해진 곳은 묻지 않음
            todo.append(c)
        L = self._live()
        def one(c):
            try: return L.check_detail(c["상호"], float(c["경도"]), float(c["위도"]))
            except Exception: return ("확인 실패", "", {})
        if todo:
            with ThreadPoolExecutor(6) as ex:
                for c, r in zip(todo, ex.map(one, todo)): c["_live"] = r
        same = {}   # 같은 가게(같은 이름)가 여러 목록·자료에 들어 있으면 함께 씀
        for c in cands:
            if "_live" in c and c["_live"][0] == "확인됨": same[self._name_key(c.get("상호"))] = c["_live"]
        for c in cands:
            if "_live" not in c and self._name_key(c.get("상호")) in same: c["_live"] = same[self._name_key(c["상호"])]

    # 주민이 말한 메뉴(예: 쭈꾸미)가 상호에 들어 있는 가게를 앞으로. 메뉴를 한다고 단정하지 않고 '상호에 들어 있음'만 사실대로 표시
    SYN = {"쭈꾸미": ["쭈꾸미", "주꾸미"], "주꾸미": ["쭈꾸미", "주꾸미"], "아구": ["아구", "아귀"], "아귀": ["아구", "아귀"], "짜장": ["짜장", "자장"], "자장": ["짜장", "자장"]}
    def _menu_order(self, st, res):
        words = []
        for w in st["menu_words"]:
            base = re.sub(r"(찜|볶음|구이|탕|전골|요리|집)$", "", w) or w
            words += self.SYN.get(base, [base]) + ([w] if w != base else [])
        words = [w for w in dict.fromkeys(words) if len(w) >= 2]
        hit = lambda c: next((w for w in words if w in c["상호"]), None)   # 띄어쓰기를 살려서 찾음 (서로 다른 낱말이 붙어 메뉴처럼 보이지 않게)
        cards = res["추천"]; a = [c for c in cards if hit(c)]; b = [c for c in cards if not hit(c)]
        for c in a: c["표시"] = c["표시"] + [f"가게 이름에 '{hit(c)}'{'이' if _batchim(hit(c)) else '가'} 들어 있어요"]; c["_메뉴"] = 1
        if st.get("leaf") in MENU_LEAVES:   # '메뉴'는 음식을 고르는 곳에만 맞는 말 (미용실에 '찾으시는 메뉴가 있는지'가 붙던 것 고침, 10/15)
            for c in b: c["표시"] = c["표시"] + ["찾으시는 메뉴가 있는지"]
        res["추천"] = a + b; res["메뉴단서"] = words
        return res

    def _allowed(self, st):
        lid = st["leaf"]; kind = st.get("kind"); scope = st.get("scope", "kind")
        if kind is None: return []
        grp = self.E.kind[(lid, kind)]["group"]
        if scope == "kind": return [kind]
        if scope == "group": return [k for (L, k), v in self.E.kind.items() if L == lid and v["group"] == grp]
        return [k for (L, k) in self.E.kind if L == lid]

    def _widen_option(self, st, peek=False):
        lid = st["leaf"]; kind = st.get("kind"); scope = st.get("scope", "kind"); declined = st.get("declined", set())
        if kind is None: return None
        if peek:
            grp = self.E.kind[(lid, kind)]["group"]
            og = [k for (L, k), v in self.E.kind.items() if L == lid and v["group"] == grp and k != kind]
            ol = [1 for (L, k), v in self.E.kind.items() if L == lid and v["group"] != grp]
            return (scope == "kind" and og and "group" not in declined) or (scope in ("kind", "group") and ol and "leaf" not in declined)
        grp = self.E.kind[(lid, kind)]["group"]
        others_g = [k for (L, k), v in self.E.kind.items() if L == lid and v["group"] == grp and k != kind]
        others_l = sorted({v["group"] for (L, k), v in self.E.kind.items() if L == lid and v["group"] != grp})
        if scope == "kind" and others_g and "group" not in declined:
            st["stage"] = "widen"; st["pending_scope"] = "group"
            return {"type": "question", "text": f"{self._reach_word(st)} {josa(self._kind_word(kind), '이가')} 없어요. 비슷한 {', '.join(others_g[:4])}도 괜찮으세요?", "options": ["네, 괜찮아요", "아니요"]}
        if scope in ("kind", "group") and others_l and "leaf" not in declined:
            st["stage"] = "widen"; st["pending_scope"] = "leaf"
            lead = "그래도 마땅한 곳이 없네요." if scope == "group" else f"{self._reach_word(st)} {josa(self._kind_word(kind), '이가')} 없어요."   # (10/29) 처음 묻는데 '그래도'로 시작하던 것 고침
            return {"type": "question", "text": f"{lead} 같은 일을 하는 다른 종류의 곳({', '.join(others_l[:4])})까지 찾아볼까요?", "options": ["네, 찾아봐 주세요", "아니요"]}
        return None

    # ── 순위 정하기 (헌준님 제안, 10/15) ──────────────────────────────────────────────
    #  1) 확실성: 자료·업종으로 그 일을 하는 것이 확인된 곳만 1·2순위. '확인 필요'는 확실한 곳이 모자랄 때 마지막 한 자리(3순위까지)에만
    #  2) 주민 조건: 세부 종류·의도·자격은 엔진이 이미 거름. 최대 이동 시간을 말했으면 그 안의 곳만 (없으면 그렇다고 말하고 가장 가까운 곳)
    #  3) 이동 수단으로 가는 시간이 짧은 순 (걸어서: 걷는 길 / 차·택시: 카카오 길찾기 / 버스·지하철: 정류장 기준 가늠값으로 순서만, 시간은 지어내지 않음)
    #  상가 자료에만 근거한 가게는 카카오맵에서 지금도 있는지 확인하고, 찾지 못하면 '확인 필요'로 내림 (카카오 결과는 저장하지 않음)
    def _arrange(self, st, res):
        cond = st.get("cond", {}); mode = cond.get("mode", "걸어서"); spd = st.get("speed", "보통"); mx = cond.get("max_min")
        sure = [dict(c) for c in res["추천"]]; unsure = [dict(c) for c in res["제공여부확인필요"]]; elig = [dict(c) for c in res["이용자격확인필요"]]
        hf = st.get("hours_filter")
        if hf:   # '지금/토/일/공휴일에 여는 곳만' (약국·병의원 운영시간이 있는 곳만 남김, 10/16)
            import hours as HR
            ok = lambda c: HR.open_on(c.get("fid"), hf)
            sure = [c for c in sure if ok(c)]; unsure = [c for c in unsure if ok(c)]; elig = [c for c in elig if ok(c)]
        sure, unsure = self._dedupe(sure, unsure)
        for c in sure: c["확실성"] = "자료로 확인" if c.get("근거자료") and not c.get("실시간") else ("카카오맵에서 지금 찾음" if c.get("실시간") else "업종으로 확인")
        for c in unsure: c["확실성"] = "확인 필요"
        res["지도확인"] = 0; notes = []
        # 실시간 지도 확인: 앞쪽 후보 중 상가 자료에만 근거한 가게
        keep = []; checked = 0
        fx0, av0 = _words_rx(st.get("fit_words")), _words_rx(st.get("avoid_words"))   # (10/29) 상황에 맞지 않는 곳은 확인 전에 빼고, 어울리는 곳을 먼저 확인 (가까운 10곳만 확인하다 보니 어울리는 곳이 빠지던 것)
        if av0: sure = [c for c in sure if not _avoided(av0, fx0, c)]; unsure = [c for c in unsure if not _avoided(av0, fx0, c)]
        if fx0:
            for c in sure: c["_맞춤"] = _fit_score(fx0, c)
        sure = sorted(sure, key=lambda c: (-c.get("_메뉴", 0), -c.get("_맞춤", 0), -c.get("_상황", 0)))   # 바람·메뉴에 맞는 곳을 먼저 확인 (가까운 10곳만 확인하다 보니 바람에 맞는 곳이 빠지던 것 고침, 10/19)
        for c in sure:
            need = not str(c["fid"]).startswith("KAKAO:") and c["fid"] in self.E.F.index and self._live().needed(self.E.F.loc[c["fid"]])
            if need and checked >= 10: continue   # 확인하지 못한 가게는 보여 주지 않음 (가까운 10곳까지만 확인하고, 그 뒤는 더 먼 곳이라 뺌)
            if need:
                checked += 1
                r = self.E.F.loc[c["fid"]]
                if c.get("_live") and c["_live"][0] != "확인 실패": v, why = c["_live"][0], c["_live"][1]   # 성격을 보려고 이미 받은 확인을 다시 씀
                else: v, why = self._live().check(r["상호"], float(r["경도"]), float(r["위도"]))
                res["지도확인"] += 1
                alt = str(r.get("인허가상호") or "")
                if v == "찾지 못함" and alt and alt not in ("nan",) and re.sub(r"\s", "", alt) != re.sub(r"\s", "", str(r["상호"])):   # 상가 상호로 못 찾으면 인허가 상호로 한 번 더
                    v, why = self._live().check(alt, float(r["경도"]), float(r["위도"])); res["지도확인"] += 1
                if v == "찾지 못함":
                    c["확실성"] = "확인 필요"; c["표시"] = c["표시"] + ["카카오맵에 나오지 않아요 (문을 닫았거나 이름이 바뀌었을 수 있어요)"]; unsure.insert(0, c); continue
                if v == "확인됨": c["표시"] = c["표시"] + ["카카오맵에서도 확인돼요"]
            keep.append(c)
        sure = keep
        # 인허가에만 있는 가게(상가 자료에 없어 '운영 확인 필요'로 넘어온 곳): 아래를 모두 만족하면 확인된 곳으로 올림 (10/15)
        #  인허가 영업 중 + 상호·업종 어긋남 없음 + 그 업종이 이 일을 하는 것이 확실함(엔진 판정) + 카카오맵에서 같은 이름의 장소를 찾음
        tried = 0
        for c in res.get("운영확인필요", []):
            if tried >= 6 or c["fid"] not in self.E.F.index: continue
            r = self.E.F.loc[c["fid"]]
            if not (r["출처"] == "인허가" and r["영업근거"] == "인허가만(영업 확인 필요)" and r["인허가상태"] == "영업" and not r["업종확인필요"]): continue
            if "제공 여부 확인 필요" in c["표시"] or "오래된 폐업 기록" in c["표시"]: continue
            tried += 1; res["지도확인"] += 1
            L = self._live()
            v, why, kd = L.check_detail(r["상호"], float(r["경도"]), float(r["위도"])) if hasattr(L, "check_detail") else (*L.check(r["상호"], float(r["경도"]), float(r["위도"])), {})
            if v == "확인됨":
                c = dict(c); c["확실성"] = "인허가·카카오맵 확인"; c["표시"] = c["표시"] + ["인허가상 영업 중이고 카카오맵에서도 확인돼요"]
                if "*" in (c["주소"] or "") and kd.get("주소"): c["주소"] = kd["주소"] + " (카카오맵 주소)"   # 원자료 주소가 가려진 경우만, 화면에만
                if not c["전화"] and kd.get("전화"): c["전화"] = kd["전화"]
                sure.append(c)
        sure, unsure = self._dedupe(sure, unsure)   # 인허가로 올린 가게가 상가 자료의 같은 가게와 겹칠 수 있어 한 번 더
        if st.get("menu_words") and st.get("leaf") in MENU_LEAVES:   # 인허가에서 올린 가게에도 메뉴 단서 표시 (메뉴 순서 정하기 뒤에 들어온 곳)
            for c in sure:
                if not any(m.startswith("가게 이름에") or m == "찾으시는 메뉴가 있는지" for m in c["표시"]): c["표시"] = c["표시"] + ["찾으시는 메뉴가 있는지"]
        # 이동 시간
        o_lon, o_lat = st["lon"], st["lat"]
        allc = sure + unsure + elig
        for c in allc: c["이동수단"] = mode; c["_비용"] = None; c["_갈수있음"] = c["걷는거리_m"] is not None
        if mode in ("자가용", "택시"):
            pts = [(str(k), c["경도"], c["위도"]) for k, c in enumerate(allc) if c.get("경도") == c.get("경도")]
            try:
                T = self._kakao().car_many(o_lon, o_lat, pts)
                for k, c in enumerate(allc):
                    t = T.get(str(k))
                    c["차_거리_m"], c["차_시간_분"] = (t[0], round(t[1] / 60)) if t else (None, None)
                    c["_비용"] = c["차_시간_분"]; c["_갈수있음"] = t is not None
            except TravelError:
                notes.append("차 길찾기가 잠시 안 돼서 걸어서 가까운 순서로 알려 드려요."); mode = "걸어서"
                for c in allc: c["이동수단"] = mode
        if mode == "버스·지하철":
            S = self._stops_(); home = S.nearest(o_lon, o_lat, spd); res["집근처정류장"] = home[0] if home else None
            BU = self._bus_(); O = BU.origin(o_lon, o_lat, spd)   # 실제 노선으로 한 번에 가는지 (engine/bus.py, 10/16)
            for c in allc:
                ok = c.get("경도") == c.get("경도") and c.get("경도") is not None
                near = S.nearest(c["경도"], c["위도"], spd) if ok else []
                c["정류장"] = near[0] if near else None
                d = hav(o_lon, o_lat, c["경도"], c["위도"]) if ok else None
                c["_갈수있음"] = d is not None and d <= 15000
                c["버스"] = BU.plan(O, c["경도"], c["위도"], spd) if ok and O else None
                if c["버스"]: c["_비용"] = c["버스"]["예상_분"]
                else:   # 한 번에 가는 노선이 없음 → 한 번 갈아타는 길을 찾음 (10/25), 없으면 어림값 + 갈아타는 품 20분
                    c["버스환승"] = BU.plan_transfer(O, c["경도"], c["위도"], spd) if ok and O else None
                    c["_비용"] = c["버스환승"]["예상_분"] if c["버스환승"] else (None if d is None else ((home[0]["걷는시간_분"] if home else 15) + d / 250 + (near[0]["걷는시간_분"] if near else 15) + 20))
                    c["_갈아타기"] = d is not None and bool(O)
                    c["_정류장없음"] = not O   # 출발지 가까이에 정류장이 없으면 '갈아타야 함'이 아니라 '타는 곳이 멀다'
                    if not O: res["출발정류장없음"] = True
                wk = c.get("걷는시간_분")
                if wk is not None and wk <= 15 and (c["_비용"] is None or wk <= c["_비용"]): c["_비용"] = wk; c["_걷기가빠름"] = True   # 가까우면 걸어가는 게 더 빠름
        if mode in ("걸어서", "다니기 어려움"):   # 걸어서 찾을 때는 걸어서 갈 만한 곳(30분, 다니기 어려우면 20분)까지만 순위에 넣음. 더 먼 곳은 '멀리'로 따로 (헌준님 지적 10/19: 걸어서 71분이 2순위)
            lim = 30 if mode == "걸어서" else 20
            for c in allc:
                c["_비용"] = c.get("걷는시간_분")
                c["_갈수있음"] = c["_비용"] is not None and c["_비용"] <= lim
        # 주민의 형편과 바라는 것을 순서에 반영 (10/16 헌준님: 거리만이 아니라 걷기 불편함·몸 상태·구체적인 필요까지 따져 가장 맞는 곳을)
        #  걷기 불편: 2층 이상·지하는 걷는 시간 5분만큼 불리하게, 층을 모르면 1.5분 / 휠체어·보행기: 15분, 모르면 3분
        #  '1층' 바람: 1층이 아니면 8분, 모르면 2분 / '정류장 가까운 곳' 바람(버스): 걷는 구간을 두 배로 셈
        mob = st.get("mobility"); pref = set(st.get("prefer") or [])
        for c in allc:
            if c["_비용"] is None: continue
            f = floor_of(c.get("fid")); c["층"] = f; pen = 0
            if mob in ("걷기 불편", "휠체어·보행기"):
                big = 15 if mob == "휠체어·보행기" else 5
                pen += big if (f is not None and f != 1) else (0 if f == 1 else (3 if mob == "휠체어·보행기" else 1.5))
            if "1층" in pref: pen += 8 if (f is not None and f != 1) else (0 if f == 1 else 2)
            pen += c.get("_결벌점", 0)   # 상황에 덜 어울리는 가게(감성 카페를 찾는데 대형 프랜차이즈)는 뒤로 (10/26)
            b = c.get("버스")
            if b and ("정류장 가까운 곳" in pref or mob): pen += (b["타는곳_분"] + b["내려서_분"]) * (1 if mob else 0.5) + (b["타는곳_분"] + b["내려서_분"]) * (1 if "정류장 가까운 곳" in pref else 0)
            x = c.get("버스환승")   # 10/25: 갈아타는 길은 걷는 구간(타는 곳·갈아타며·내려서)을 똑같이 셈하고, 다리가 불편하면 갈아타기 자체를 무겁게 (갈아타는 길이 오히려 앞에 오던 것)
            if x and not b:
                xw = x["타는곳_분"] + x["갈아타며_걷기_분"] + x["내려서_분"]
                if "정류장 가까운 곳" in pref or mob: pen += xw * (1 if mob else 0.5) + xw * (1 if "정류장 가까운 곳" in pref else 0)
                pen += 15 if mob else 5
            c["_비용"] = c["_비용"] + pen
        fitx, avx = _words_rx(st.get("fit_words")), _words_rx(st.get("avoid_words"))   # (10/29) 사회적 맥락: 모델이 판단한 어울리는 곳은 앞으로, 맞지 않는 곳은 뺌
        if avx: sure = [c for c in sure if not _avoided(avx, fitx, c)]; unsure = [c for c in unsure if not _avoided(avx, fitx, c)]
        for c in sure + unsure: c["_맞춤"] = _fit_score(fitx, c)
        cost = lambda c: (-c.get("_메뉴", 0), -min(c.get("_맞춤", 0), 1), -c.get("_상황", 0), (c["_비용"] - (2 if c.get("_맞춤") == 2 else 0)) if c["_비용"] is not None else 1e9)   # 이름에 맞는 말이 들어 있으면 2분 가까운 것처럼   # _상황: 주민이 바라는 성격에 딱 맞는 곳(디저트 카페·술집)을 먼저
        # 최대 이동 시간 (걸어서·차·택시만 시간이 있음)
        if mx and mode != "버스·지하철":
            inside = [c for c in sure if c["_비용"] is not None and c["_비용"] <= mx]
            if inside or not sure: sure = inside
            else: notes.append(f"말씀하신 {mx}분 안에 갈 수 있는 곳은 없어요. 그중 가까운 곳을 알려 드릴게요.")
        reach = sorted([c for c in sure if c["_갈수있음"]], key=cost); far = sorted([c for c in sure if not c["_갈수있음"]], key=cost)
        if cond.get("sort") == "블로그" and reach:   # 블로그 글이 많은 순: 가까운 8곳 안에서만 (멀리 있는 유명한 곳보다 갈 수 있는 곳이 먼저). 글 수는 이 코드가 셈
            top = reach[:8]
            try:
                from concurrent.futures import ThreadPoolExecutor
                B = self._blog()
                def cnt(c):
                    r = self.E.F.loc[c["fid"]] if c.get("fid") in self.E.F.index else {}
                    return B.posts(c["상호"], c.get("주소") or "", (r.get("구군") if len(r) else None), (r.get("인허가상호") if len(r) else None))["글수"]
                with ThreadPoolExecutor(4) as ex: ns = list(ex.map(cnt, top))
                for c, n in zip(top, ns): c["블로그글수"] = n
                reach = sorted(top, key=lambda c: (-c["블로그글수"], cost(c))) + reach[8:]
                res["블로그순"] = True
            except Exception:
                notes.append("블로그 검색이 잠시 안 돼서 가까운 순서로 보여 드려요.")
        elif reach: reach = self._balanced(st, reach, cost, mode, res)
        if fitx and reach: reach = sorted(reach, key=lambda c: -min(c.get("_맞춤", 0), 1))   # 블로그·거리 균형으로 섞인 뒤에도 상황에 맞는 곳이 앞에
        if fitx and any(c.get("_맞춤") for c in reach):   # (10/30 헌준님) 상황에 맞는 곳이 있으면 그곳들만 보여 줌. 맞는 곳이 한두 곳뿐이라고 빈자리를 가까운 아무 가게(고깃집·육회집)로 채우지 않음
            reach = [c for c in reach if c.get("_맞춤")]; unsure = [c for c in unsure if c.get("_맞춤")]; res["맞춤만"] = True
        unsure_far = [c for c in unsure if not c["_갈수있음"]]
        unsure = sorted([c for c in unsure if c["_갈수있음"]], key=cost)
        if not reach and not unsure and unsure_far: far = sorted(far + unsure_far, key=cost)   # (10/29 헌준님) 확실한 곳만 멀리 보여 주면 더 가까운 '운영 여부 확인 필요' 시설(예: 같은 구 노인종합복지관)이 빠짐 → 함께 거리순으로
        rank = self._variety(reach, 3)   # 같은 브랜드(파리바게뜨 세 지점 등)가 순위를 다 차지하지 않게
        if len(rank) == 2 and unsure: rank = rank + [unsure[0]]   # 확인 필요는 3순위 자리에만 (확실한 곳이 2곳일 때). 1곳 이하면 순위에 넣지 않고 원하면 따로 보여 줌
        for k, c in enumerate(rank): c["순위"] = k + 1
        # 공공·복지 시설인데 원자료에 전화번호가 없으면 카카오맵에서 그 자리에서 찾아 보여 줌 (화면에만, 저장하지 않음)
        L = self._live()
        for c in rank:
            if (not c.get("전화") or "관리 기관 번호" in str(c.get("전화"))) and c["fid"] in self.E.F.index and self.E.F.loc[c["fid"], "출처"] == "공공" and hasattr(L, "check_detail"):
                v, why, kd = L.check_detail(c["상호"], c["경도"], c["위도"])   # 시설 자체 번호가 카카오맵에 있으면 그 번호를 먼저 보여 줌 (화면에만)
                if v == "확인됨" and kd.get("전화"): c["전화"] = kd["전화"] + " (카카오맵 정보)"
        if mode == "택시":
            for c in rank: c["택시요금"] = self._kakao().taxi_fare(o_lon, o_lat, c["경도"], c["위도"]) if c.get("차_시간_분") is not None else None
        # 안전 검사: '확인 필요'는 절대 1·2순위가 아님, 카드 정보는 데이터베이스 값 그대로
        for c in rank:
            if c["순위"] <= 2 and c["확실성"] == "확인 필요": raise RuntimeError("확인 필요 시설이 1·2순위에 들어감")
            if c["fid"] in self.E.F.index and c["상호"] != self.E.F.loc[c["fid"], "상호"]: raise RuntimeError("시설 이름이 데이터베이스와 다름")
        for c in rank + far:
            if "*" in (c.get("주소") or ""): c["주소"] = re.sub(r"[\s,]*[^\s,]*\*[^\s]*", "", c["주소"]).strip() + " (자세한 주소는 전화로 확인)"   # 가려진 번지는 보여 주지 않음
        if res.get("출발정류장없음"): notes.append("출발하시는 곳에서 걸어서 10분 안에 버스정류장이 없어요. 택시나 자가용이 편할 거예요.")
        self._why(st, rank, mode)
        res["순위"] = rank; res["멀리"] = far[:3]; res["확인필요후보"] = [c for c in unsure if c not in rank][:3]
        res["이용자격확인필요"] = sorted(elig, key=cost)[:3]; res["안내메모"] = notes; res["이동수단"] = mode
        res["추천"] = [c for c in rank if c["확실성"] != "확인 필요"]   # 예전 형식과 맞춤: 확실한 곳만
        res["제공여부확인필요"] = [c for c in rank if c["확실성"] == "확인 필요"] + res["확인필요후보"]
        return res

    @staticmethod
    def _name_key(n):
        n = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", str(n or ""))
        k = re.sub(r"[^가-힣0-9]", "", n)
        return k or re.sub(r"[^A-Za-z0-9]", "", n).lower()
    def _dedupe(self, sure, unsure):
        """같은 가게가 자료에 두 번 있는 경우 하나만 (10/16 발견: '트랙(Track)'과 '트랙'이 7m 떨어져 1·2순위로 나옴)
        이름에서 괄호·영문·띄어쓰기를 뺀 것이 같고 100m 안이면 같은 가게로 봄 (상가·인허가 좌표가 수십 m 어긋나는 일이 많음, 10/19). 확인된 쪽(앞쪽)을 남김"""
        kept = []; out_s = []; out_u = []
        for lst, out in ((sure, out_s), (unsure, out_u)):
            for c in lst:
                key = self._name_key(c.get("상호"))
                dup = key and c.get("경도") == c.get("경도") and any(key == k2 and hav(c["경도"], c["위도"], lo, la) <= 100 for k2, lo, la in kept)
                if dup: continue
                if key and c.get("경도") == c.get("경도"): kept.append((key, c["경도"], c["위도"]))
                out.append(c)
        return out_s, out_u

    # 기본 순위 (헌준님 10/19: 버튼으로 찾으면 주민 조건을 모르니, 가까운 순서만이 아니라 사람들이 따질 만한 것을 함께)
    #  - 가장 가까운 곳과 걸어서 5분(차·버스는 7분) 안쪽 차이인 곳들은 '비슷한 거리'로 보고 그 안에서 순서를 다시 정함
    #  - 약국·병의원: 지금 문을 연 곳 먼저 / 가게(식당·카페·미용실 등): 블로그에 이야기가 많은 곳 먼저 (별점은 쓸 수 있는 공식 자료가 없음)
    #  - 블로그 글 수는 카카오(다음) 블로그 검색으로 그 자리에서 세고 저장하지 않음. 공공·복지 시설에는 쓰지 않음
    POPULAR = {"P01.1.05", "P01.2.01", "P01.2.02", "P01.1.04", "P07.2.01", "P07.4.01", "P03.3.01", "P03.3.03", "P10.1.01", "P10.1.02", "P10.1.03", "P11.2.01", "P11.1.03"}
    def _balanced(self, st, reach, cost, mode, res):
        import hours as HR
        win = 5 if mode in ("걸어서", "다니기 어려움") else 7
        top = [c for c in reach[:8] if c["_비용"] is not None]
        if len(top) < 2: return reach
        best = top[0]["_비용"]; near = [c for c in top if c["_비용"] <= best + win]
        if len(near) < 2: return reach
        keyf = None; basis = None
        if any(c.get("fid") in HR.H for c in near):   # 여는 시간을 아는 곳(약국·병의원): 지금 연 곳 먼저
            for c in near: c["_열림"] = bool(c.get("fid") in HR.H and HR.open_on(c["fid"], "지금"))
            if any(c["_열림"] for c in near) and not all(c["_열림"] for c in near):
                keyf = lambda c: (-c.get("_메뉴", 0), -c.get("_상황", 0), c.get("_결벌점", 0) > 0, not c["_열림"], c["_비용"]); basis = f"걸어서 {win}분 차이 안의 가까운 곳 가운데 지금 문을 연 곳 먼저"
        elif st.get("leaf") in self.POPULAR and all(c.get("fid") in self.E.F.index and self.E.F.loc[c["fid"], "출처"] != "공공" for c in near):
            try:
                from concurrent.futures import ThreadPoolExecutor
                B = self._blog()
                def cnt(c):
                    r = self.E.F.loc[c["fid"]]
                    return B.posts(c["상호"], c.get("주소") or "", r.get("구군"), r.get("인허가상호"))["글수"]
                with ThreadPoolExecutor(4) as ex: ns = list(ex.map(cnt, near[:6]))
                for c, n in zip(near[:6], ns): c["_인기"] = n or 0
                if max(c.get("_인기", 0) for c in near) >= 3:   # 글이 거의 없으면 가까운 순서 그대로
                    keyf = lambda c: (-c.get("_메뉴", 0), -c.get("_상황", 0), c.get("_결벌점", 0) > 0, -min(c.get("_인기", 0), 50) // 10, c["_비용"])   # 상황에 덜 어울리는 곳(데이트에 만화카페, 감성 카페에 프랜차이즈)은 비슷한 거리 안에서도 뒤로   # 글 수(위 50개 안에서 셈)를 10개 단위로 묶어 비슷하면 가까운 곳 먼저
                    basis = f"걸어서 {win}분 차이 안의 가까운 곳 가운데 블로그에 이야기가 많은 곳 먼저"
            except Exception: pass
        if not keyf: return reach
        res["순위기준"] = basis
        rest = [c for c in reach if c not in near]
        return sorted(near, key=keyf) + rest

    @staticmethod
    def _brand(name):
        n = re.sub(r"[\s()（）]", "", str(name or ""))
        return n[:4] if len(n) >= 6 and n.endswith("점") else n
    def _variety(self, lst, k):
        """앞에서부터 k곳을 고르되 같은 브랜드는 한 곳만 (모자라면 채움)"""
        out = []; seen = []
        nm = lambda c: re.sub(r"[\s()（）]", "", str(c.get("상호") or ""))
        def same(a, b):
            if self._brand(a) == self._brand(b): return True
            short, long_ = sorted((a, b), key=len)
            return len(short) >= 3 and long_.startswith(short)   # '크린토피아'와 '크린토피아대구달서본동점'
        for c in lst:
            n = nm(c)
            if any(same(n, x) for x in seen): continue
            out.append(c); seen.append(n)
            if len(out) == k: return out
        for c in lst:
            if c not in out: out.append(c)
            if len(out) == k: break
        return out

    def _why(self, st, rank, mode):
        """카드에 보여 줄 '고른 까닭' (그림 칩). 실제 값으로만: 가장 가까움·1층·정류장 가까움·지금 영업 중·층 주의"""
        if not rank: return
        mob = st.get("mobility"); pref = set(st.get("prefer") or [])
        def base(c):   # 카드에 그려지는 실제 가는 방법의 시간 (10/25: 걸어가는 게 빠른 곳인데 버스 시간으로 견줘 '가장 빨리 가요'가 엉뚱한 곳에 붙던 것)
            if mode in ("자가용", "택시"): return c.get("차_시간_분")
            if mode == "버스·지하철" and not c.get("_걷기가빠름"):
                if c.get("버스"): return c["버스"]["예상_분"]
                if c.get("버스환승"): return c["버스환승"]["예상_분"]
            return c.get("걷는시간_분")
        vals = [base(c) for c in rank if base(c) is not None]
        first_min = next((c for c in rank if vals and base(c) is not None and base(c) == min(vals)), None)   # 같은 시간이 여럿이면 앞 카드 하나에만 (10/26: 두 카드에 '가장 가까워요'가 함께 붙던 것)
        for c in rank:
            w = []
            if c is first_min and len(rank) > 1: w.append({"t": "가장 가까워요" if mode in ("걸어서", "다니기 어려움") else "가장 빨리 가요"})
            f = c.get("층") if "층" in c else floor_of(c.get("fid"))
            if f == 1 and (mob or "1층" in pref): w.append({"t": "1층"})
            elif f is not None and f < 0: w.append({"t": f"지하 {-f}층", "주의": bool(mob)})
            elif f is not None and f >= 2 and (mob or "1층" in pref): w.append({"t": f"{f}층 · 엘리베이터는 전화로 확인", "주의": True})
            b = c.get("버스")
            if b and not c.get("_걷기가빠름") and b["타는곳_분"] <= 3 and b["내려서_분"] <= 3: w.append({"t": "정류장이 가까워요"})
            import hours as HR
            if c.get("fid") in HR.H and HR.open_on(c["fid"], "지금"): w.append({"t": "지금 영업 중"})
            import occasions as O
            occ_lab = {"2차·술 위주": "술집·호프", "넓은 카페": "대형 매장 프랜차이즈", "분위기 좋은 카페": None, "격식 있는 곳": None, "가성비 좋은 곳": None}.get(st.get("occasion"), st.get("occasion")) if st.get("occasion") in O.TRAITS else None
            lab = st.get("want_label") or occ_lab   # 바람과 상황이 함께 있으면 한 이름으로
            if lab and (c.get("_바람") or (c.get("_상황") and occ_lab)): w.insert(0, {"t": lab})
            pop = [x.get("_인기", 0) for x in rank]
            if c.get("_인기") and c["_인기"] == max(pop) and pop.count(max(pop)) == 1 and c["_인기"] >= 3: w.insert(0, {"t": "블로그 이야기가 가장 많아요"})
            c["까닭"] = w[:3]

    def _travel_text(self, st, c):
        t = self._travel_main(st, c)
        if c.get("이동수단") in ("자가용", "택시", "버스·지하철") and not c.get("_걷기가빠름") and c.get("걷는시간_분") is not None and c["걷는시간_분"] <= 10:
            t += f" (걸어서도 약 {mins(c['걷는시간_분'])}분)"   # 가까운 곳은 걸어서도 갈 수 있다고 함께 알려 줌
        return t

    def _travel_main(self, st, c):
        mode = c.get("이동수단", "걸어서")
        if mode in ("자가용", "택시"):
            if c.get("차_시간_분") is None: return " — 차로 가는 길을 찾지 못했어요"
            t = f" — 차로 약 {c['차_시간_분']}분 ({c['차_거리_m'] / 1000:.1f}km)"
            if mode == "택시" and c.get("택시요금"): t += f", 택시비 약 {c['택시요금']:,}원"
            return t
        if mode == "버스·지하철":
            if c.get("_걷기가빠름") and c.get("걷는거리_m") is not None: return f" — 걸어서 약 {mins(c['걷는시간_분'])}분 ({c['걷는거리_m']:,}m), 버스보다 걸어가는 게 빨라요"
            b = c.get("버스")
            if b:   # 한 번에 가는 노선 (예: "410-1번 버스 한 번에, 약 25분")
                what = "·".join(b["노선"]) + (" 지하철" if b["지하철"] else "번 버스")
                return f" — {what} 한 번에"   # 타고 가는 시간은 노선이 돌아가는 길을 몰라 보여 주지 않음 (순서 정하기에만 씀)
            x = c.get("버스환승")
            if x:   # 한 번 갈아탐 (예: "401번 버스 → 동구8번 버스로 갈아타기")
                nm = lambda g: "·".join(g["노선"][:2]) + (" 지하철" if g["지하철"] else "번 버스")
                return f" — {nm(x['구간'][0])} → {x['갈아타는곳']}에서 {nm(x['구간'][1])}{'으로' if x['구간'][1]['지하철'] else '로'} 갈아타기"
            if c.get("_갈아타기"): return " — 버스·지하철을 갈아타야 해요"
            if c.get("_정류장없음"): return " — 출발하시는 곳 가까이에 버스정류장이 없어요"
            s = c.get("정류장")
            return f" — {s['이름']}에서 내려 걸어서 약 {mins(s['걷는시간_분'])}분" if s else " — 근처에 버스정류장이나 지하철역이 없어요"
        if c["걷는거리_m"] is not None and (c.get("걷는시간_분") or 0) <= FAR_WALK_MIN: return f" — 걸어서 약 {mins(c['걷는시간_분'])}분 ({c['걷는거리_m']:,}m)"
        d = c["걷는거리_m"] if c["걷는거리_m"] is not None else c["직선거리_m"]   # 10/25: 먼 곳은 '106분'과 '직선 6,242m'가 섞여 보이던 것 → 모두 같은 말로
        return f" — 걸어가기엔 멀어요 (약 {d / 1000:.1f}km)"

    def _card_text(self, st, i, c, label=None):
        if c.get("전화"): c["전화"] = fmt_phone(c["전화"])
        head = label or (f"{c['순위']}순위" if c.get("순위") else f"{i}")
        tag = "가시기 전에 전화로 확인하세요" if c.get("확실성") == "확인 필요" else ""   # 확실한 곳은 꼬리표 없이 (근거가 있으면 근거 줄로)
        kind = self._kind_word(c["세부종류"]) if c.get("세부종류") else c["업종"]
        t = f"{head}. {c['상호']} ({kind})" + self._travel_text(st, c) + (f"\n   [{tag}]" if tag else "")
        if c["주소"]: t += f"\n   주소: {c['주소']}"
        note = self._pub_note(c)
        if c["전화"]: t += f"\n   전화: {c['전화']}" + (" (안 되면 카카오맵 번호로)" if note.get("전화다름") else "")
        for x in note.get("안내", []): t += "\n   " + x.replace("(급식일은 바뀔 수 있음)", "(요일은 바뀔 수 있어요)")
        import hours as HR   # 약국·병의원 운영시간 (국립중앙의료원)
        if c.get("fid") in HR.H:
            t += f"\n   {HR.label(c['fid'])}: {HR.today_text(c['fid'])}\n   {HR.label(c['fid'])}(요일별): {HR.week_text(c['fid'])} (국립중앙의료원, 바뀔 수 있음)"
        if c["안내"]: t += "\n   " + {"이곳은 서비스를 직접 하는 곳이 아니라 신청·문의하는 곳입니다": "신청·문의하는 곳이에요."}.get(c["안내"], c["안내"])
        if c.get("근거자료"): t += "\n   근거: " + "; ".join(self._plain(x) for x in c["근거자료"])
        INFO = ("가게 이름에", "카카오맵에서도", "인허가상 영업 중")
        info = [m for m in c["표시"] if m.startswith(INFO)]
        def say(m):   # 엔진의 표시(검사용 말)를 주민에게 보여 줄 자연스러운 말로
            if m == "제공 여부 확인 필요": return f"{self._need_word}되는지" if self._need_word else "이 일을 해 주는지"
            if m.startswith("이용 자격: "): return m[len("이용 자격: "):] + "에 해당하는지"
            return m
        elig_done = c.get("세부종류") in st.get("elig_ok", set())   # 주민이 자격에 해당한다고 이미 답했으면 다시 확인하라고 하지 않음
        ask_ok = lambda m: m != "신청·문의 창구" and not m.startswith(INFO) and not m.startswith("걸어서 가기 먼 거리") and not m.startswith("이용 자격: ")
        marks = [say(m) for m in c["표시"] if ask_ok(m)]
        who = [m[len("이용 자격: "):] for m in c["표시"] if m.startswith("이용 자격: ")]   # 이용 대상은 주민 자신에 관한 것이라 '전화로 물어볼 것'이 아니라 안내로
        if who: t += "\n   이용 대상: " + ", ".join(who)
        if info: t += "\n   참고: " + ", ".join(info)
        if c.get("블로그글수") is not None: t += f"\n   블로그 글: {c['블로그글수']}개" + (" (다음 블로그 검색)" if c["블로그글수"] else " (찾지 못했어요)")
        if marks: t += "\n   물어보실 것: " + ", ".join(marks)
        if c.get("경도") == c.get("경도") and c.get("경도") is not None:
            o = (st.get("origin_name") or "출발", st["lon"], st["lat"])
            t += "\n   길찾기: " + map_link(c.get("이동수단", "걸어서"), o, (c["상호"], c["경도"], c["위도"]))
        out = CardLine(t)
        ok = c.get("경도") == c.get("경도") and c.get("경도") is not None
        mv, route = self._move_graphic(st, c) if ok else (None, None)
        import hours as HR2
        tm = None
        if c.get("fid") in HR2.H:   # 영업·진료 시간은 그림(상태 표시)으로: 지금 열렸는지 + 오늘 시간 + 요일별
            today = HR2.today_text(c["fid"]); m = re.search(r"\d{1,2}:\d{2}~\d{1,2}:\d{2}", today)
            tm = {"열림": HR2.open_on(c["fid"], "지금"), "오늘": m.group(0) if m else ("쉬는 날" if "쉼" in today else ""), "요일": HR2.week_text(c["fid"]), "이름": HR2.label(c["fid"]).replace("시간", "")}
        web = next((re.sub(r"^누리집:\s*", "", x) for x in note.get("안내", []) if x.startswith("누리집")), None)
        # 블로그 버튼은 가게에만 (복지관·주민센터에 블로그 후기는 맞지 않음, 10/19)
        out.card = {"까닭": c.get("까닭") or [], "층": c.get("층") if "층" in c else floor_of(c.get("fid")), "이동": mv, "경로": route, "종류": kind, "주소": c.get("주소") or "", "누리집": web, "시간": tm,
                    "물어볼것": marks, "이동글": self._travel_text(st, c).lstrip(" —").strip(),
                    "안내": [f"이용 대상: {', '.join(who)}"] * bool(who) + [x.replace("(급식일은 바뀔 수 있음)", "(요일은 바뀔 수 있어요)") for x in note.get("안내", []) if not x.startswith("누리집")] + ([{"이곳은 서비스를 직접 하는 곳이 아니라 신청·문의하는 곳입니다": "신청·문의하는 곳이에요."}.get(c["안내"], c["안내"])] if c.get("안내") else []),
                    "fid": c.get("fid"), "순위": c.get("순위"), "블로그": c.get("fid") in self.E.F.index and self.E.F.loc[c["fid"], "출처"] != "공공", "표시이름": head, "상호": c["상호"], "확실성": c.get("확실성"), "전화": (c.get("전화") or "").split(" (")[0],
                    "경도": c.get("경도") if ok else None, "위도": c.get("위도") if ok else None,
                    "길찾기": map_link(c.get("이동수단", "걸어서"), (st.get("origin_name") or "출발", st["lon"], st["lat"]), (c["상호"], c["경도"], c["위도"])) if ok else None}
        return out

    def _move_graphic(self, st, c):
        """카드의 '가는 길' 그림과 지도에 그릴 경로 (헌준님 10/16: 네이버·카카오 지도처럼 그림으로).
        돌려줌: (구간 목록, 지도 선 목록). 구간 t: walk·bus·car·transfer·none"""
        o_lon, o_lat = st["lon"], st["lat"]; mode = c.get("이동수단", "걸어서"); W = self.E.walk
        walk = lambda: ([{"t": "walk", "분": max(1, round(c["걷는시간_분"])), "m": c["걷는거리_m"]}],
                        [{"t": "walk", "선": W.path(o_lon, o_lat, c["경도"], c["위도"])}]) if c.get("걷는거리_m") is not None and (c.get("걷는시간_분") or 0) <= FAR_WALK_MIN else \
                       ((None, [{"t": "walk", "선": W.path(o_lon, o_lat, c["경도"], c["위도"], max_m=12000)}]) if c.get("걷는거리_m") is not None and c["걷는거리_m"] <= 10000 else (None, None))   # (10/26) 먼 곳도 걸어서 가는 길을 물으면 지도에는 선으로 (카드 그림은 '멀어요')
        if mode in ("걸어서", "다니기 어려움") or (mode == "버스·지하철" and c.get("_걷기가빠름")): return walk()
        if mode == "버스·지하철":
            b = c.get("버스")
            if b:
                segs = [{"t": "walk", "분": max(1, b["타는곳_분"])},
                        {"t": "bus", "노선": b["노선"], "지하철": b["지하철"], "탈곳": b["타는곳"], "내릴곳": b["내리는곳"], "배차": b.get("배차_분"), "비율": b.get("타고가는_분")},
                        {"t": "walk", "분": b["내려서_분"]}]
                (alat, alon), (blat, blon) = b["타는곳_좌표"], b["내리는곳_좌표"]
                route = [{"t": "walk", "선": W.path(o_lon, o_lat, alon, alat)}, {"t": "bus", "지하철": b["지하철"], "노선": b["노선"], "선": (None if b["지하철"] else self._busnet_path(alon, alat, blon, blat, b["노선"])) or [[alat, alon], [blat, blon]], "탈곳": b["타는곳"], "내릴곳": b["내리는곳"], "추정": not b["지하철"]},   # 버스는 버스가 다니는 길(버스 링크)을 따라 그 노선 정류장 쪽으로 (10/22), 지하철은 곧게
                         {"t": "walk", "선": W.path(blon, blat, c["경도"], c["위도"])}]
                return segs, route
            x = c.get("버스환승")
            if x:   # 한 번 갈아타는 길: 걷기 → 버스① → (갈아타며 걷기) → 버스② → 걷기 (10/25)
                g1, g2 = x["구간"]
                segs = [{"t": "walk", "분": max(1, x["타는곳_분"])},
                        {"t": "bus", "노선": g1["노선"], "지하철": g1["지하철"], "탈곳": g1["탈곳"], "내릴곳": g1["내릴곳"], "배차": g1.get("배차_분"), "비율": g1.get("타고가는_분")}]
                if x["갈아타며_걷기_분"]: segs.append({"t": "walk", "분": x["갈아타며_걷기_분"]})
                segs += [{"t": "bus", "노선": g2["노선"], "지하철": g2["지하철"], "탈곳": g2["탈곳"], "내릴곳": g2["내릴곳"], "배차": g2.get("배차_분"), "비율": g2.get("타고가는_분"), "환승": True},
                         {"t": "walk", "분": x["내려서_분"]}]
                line = lambda g: (None if g["지하철"] else self._busnet_path(g["탈곳_좌표"][1], g["탈곳_좌표"][0], g["내릴곳_좌표"][1], g["내릴곳_좌표"][0], g["노선"])) or [g["탈곳_좌표"], g["내릴곳_좌표"]]
                (a1, o1), (a2, o2) = g1["탈곳_좌표"], g2["내릴곳_좌표"]
                route = [{"t": "walk", "선": W.path(o_lon, o_lat, o1, a1)},
                         {"t": "bus", "지하철": g1["지하철"], "노선": g1["노선"], "선": line(g1), "이어짐": True}]
                if x["갈아타며_걷기_분"]: route.append({"t": "walk", "선": W.path(g1["내릴곳_좌표"][1], g1["내릴곳_좌표"][0], g2["탈곳_좌표"][1], g2["탈곳_좌표"][0])})
                route += [{"t": "bus", "지하철": g2["지하철"], "노선": g2["노선"], "선": line(g2), "환승": True},
                          {"t": "walk", "선": W.path(o2, a2, c["경도"], c["위도"])}]
                return segs, route
            if c.get("_갈아타기"): return [{"t": "transfer"}], None
            return [{"t": "none"}], None
        if mode in ("자가용", "택시") and c.get("차_시간_분") is not None:
            seg = [{"t": "car", "분": c["차_시간_분"], "km": round(c["차_거리_m"] / 1000, 1), "요금": c.get("택시요금")}]
            try: line = self._kakao().car_path(o_lon, o_lat, float(c["경도"]), float(c["위도"]))   # (10/26) 차로 가는 길도 지도에 선으로 (카카오 길찾기, 그 답에만 쓰고 남기지 않음)
            except Exception: line = None
            return seg, ([{"t": "car", "선": line}] if line else None)
        return None, None

    # ── 말 만들기 도우미 (10/15) ──
    def _place_word(self, lid, kind):
        """질문·첫마디에 쓰는 곳 이름: '미용실', '백반·한정식 가게', 종류가 없으면 '그곳'"""
        if not kind: return "그곳"
        w = self._kind_word(kind)
        if lid in MENU_LEAVES and not re.search(r"(집|점|가게|식당|카페|뷔페|주점|방)$", w): w += " 가게"
        return w
    def _reach_word(self, st):
        mode = st.get("cond", {}).get("mode", "걸어서")
        return {"걸어서": "걸어서 갈 만한 거리에", "다니기 어려움": "가까운 곳에", "버스·지하철": "버스나 지하철로 갈 만한 곳에"}.get(mode, "차로 가기 가까운 곳에")
    def _criteria(self, st, res, mode):
        """고른 기준을 한두 문장으로 (헌준님 지적 10/15: 추천 기준이 안 보임)"""
        mx = st.get("cond", {}).get("max_min")
        where = {"걸어서": f"걸어서 {mx}분 안에서" if mx else "걸어서 갈 수 있는 곳 가운데",
                 "다니기 어려움": "가장 가까운 곳으로", "자가용": f"차로 {mx}분 안에서" if mx else "차로 갈 수 있는 곳 가운데",
                 "택시": f"택시로 {mx}분 안에서" if mx else "택시로 갈 수 있는 곳 가운데", "버스·지하철": "버스나 지하철로 갈 만한 곳 가운데"}[mode]
        order = {"걸어서": "가까운 순서로", "다니기 어려움": "", "자가용": "빨리 가는 순서로", "택시": "빨리 가는 순서로", "버스·지하철": "가기 편한 순서로"}[mode]
        if res.get("블로그순"): order = "블로그에 이 가게 이야기가 많이 나온 순서로"
        if res.get("상황"): where = f"{res['상황']}에 어울리는 종류 가운데 " + where
        hf = st.get("hours_filter")
        if hf: where = {"지금": "지금 열려 있는 곳", "토": "토요일에 여는 곳", "일": "일요일에 여는 곳", "공휴일": "공휴일에 여는 곳"}[hf] + " 가운데(운영시간 자료가 있는 곳만) " + where
        out = f"{where} {order} 골랐어요.".replace("  ", " ") if order else f"{where} 골랐어요."
        if res.get("블로그순"): out += " 블로그 글에는 광고도 섞여 있으니 참고만 하세요."
        rk = res["순위"]; sure = [c for c in rk if c["확실성"] != "확인 필요"]
        seen = lambda c: any(m.startswith(("카카오맵에서도", "인허가상 영업 중")) for m in c["표시"]) or bool(c.get("근거자료")) or (c.get("fid") in self.E.F.index and self.E.F.loc[c["fid"], "출처"] == "공공")
        if sure and all(seen(c) for c in sure):
            out += (" 모두" if len(sure) == len(rk) else f" {'·'.join(str(c['순위']) for c in sure)}순위는") + " 카카오맵이나 공공 자료로 지금 있는 곳인지 확인했어요."
        if any(c["확실성"] == "확인 필요" for c in rk):
            out += f" {'·'.join(str(c['순위']) for c in rk if c['확실성'] == '확인 필요')}순위는 해 주는지 가게마다 달라서 가시기 전에 전화로 물어보세요."
        return out
    def _successor_note(self, st, res):
        """문 닫은 곳 자리에 같은 일을 하는 새 가게가 들어왔으면 알려 줌 (같은 칸·폐업 뒤 개업, pipeline/build_closures.py)"""
        c = CLOSURES.get(st.get("closed_fid") or "") or {}
        if str(c.get("같은기능새가게")) != "True" or not c.get("새가게"): return None
        if any(x["상호"] == c["새가게"] for x in res["순위"]): return None
        d = str(c.get("새가게개업일") or ""); when = f"{int(d[:4])}년 {int(d[5:7])}월에 " if re.match(r"\d{4}-\d{2}", d) else ""
        return f"참고로 {c['상호']} 자리에는 {when}같은 일을 하는 {josa(chr(39) + c['새가게'] + chr(39), '이가')} 새로 문을 열었어요. (인허가 자료)"
    def _side_question(self, st, text, got):
        """질문에 답하는 대신 다른 것을 묻는 말인지: 선택지와 같지 않고, 조건도 아니고, 묻는 말투일 때"""
        t = text.strip()
        if not t or got or yesno(t) is not None: return False
        if any(t == o for o in (st.get("last_q") or {}).get("options", [])): return False
        if st["stage"] == "speed" and re.search(r"\d+\s*분|보통|천천|느리|느린|빨리|지팡이|보행기|휠체어|멀어도|가까", t): return False
        return bool(QUESTIONISH.search(t))
    def _agent_reply(self, st, text):
        from agent import Agent
        if getattr(self, "agent", None) is None: self.agent = Agent(self)
        return self.agent.reply(st, text)

    PUB_NOTE_KEYS = ("급식일", "운영 시간", "운영시간", "누리집")
    def _pub_note(self, c):
        # 공공·복지 시설 원자료의 참고 글에서 주민에게 쓸모 있는 것(급식일·운영 시간·누리집)만 그대로 보여 줌 (지어내지 않음)
        F = self.E.F; fid = c.get("fid")
        if fid not in F.index or F.loc[fid, "출처"] != "공공": return {}
        ref = str(F.loc[fid].get("참고") or "")
        if ref in ("", "nan"): return {}
        parts = [p.strip() for p in re.split(r"\.\s+(?=\S)", ref) if p.strip()]
        out = {"안내": [p.rstrip(".") for p in parts if p.startswith(self.PUB_NOTE_KEYS)]}
        if "전화번호가 자료마다 달라" in ref: out["전화다름"] = True
        return out

    @staticmethod
    def _plain(x):
        # 근거 문장을 주민이 읽기 쉬운 말로: '(상호에 '마음') (상호)' → '가게 이름에 '마음'이 들어 있음', '비의료' → '병원이 아닌'
        m = re.match(r"^(.*?) \(상호에 '(.+?)'\) \(상호\)$", x)
        if m: x = f"{m.group(1)} (가게 이름에 '{m.group(2)}'{'이' if _batchim(m.group(2)) else '가'} 들어 있음)"
        return x.replace("비의료 ", "병원이 아닌 ").replace("상호(브랜드)", "가게 이름(브랜드)")

    @staticmethod
    def _kind_word(k):
        return re.sub(r"\s*\(.*?\)", "", k).strip()   # 문장 안에서는 괄호 설명을 뺌: '심리상담센터(의료기관 아님)' → '심리상담센터'

    _need_word = None
    def _office(self, st):
        # 확실한 대안이 없을 때 안내할 문의처: 주민이 사는 행정동의 행정복지센터(읍·면사무소) — 신청은 관할 센터에서 하므로 (10/20)
        #  주민 위치의 행정동 센터를 못 찾으면 가장 가까운 센터 (공공 자료)
        F = self.E.F; O = F[(F["업종코드"] == "PUB:행정복지센터") & (F["대안후보"] == "예") & F["x"].notna()]
        if O.empty: return None
        try:
            from dong import dong_at
            dn = re.sub(r"[\s·.,]", "", dong_at(st["home"][0], st["home"][1]) or "")   # '두류1,2동' ↔ '두류1·2동 행정복지센터'
            mine = O[O["상호"].astype(str).str.replace(r"[\s·.,]", "", regex=True).str.startswith(dn)] if dn else O.iloc[:0]
            if len(mine) == 1: return mine.iloc[0]
        except Exception: pass
        d = O.apply(lambda r: hav(st["home"][0], st["home"][1], float(r["경도"]), float(r["위도"])), axis=1)
        return O.loc[d.idxmin()]

    def _answer(self, st, res, nothing=False, show_unsure=False):
        lines = []; self._need_word = st.get("need"); cond = st.get("cond", {}); mode = res.get("이동수단", cond.get("mode", "걸어서"))
        kwp = res.get("실시간목적")   # 카카오 키워드로 찾은 목적(농기계 수리 등)
        what = (LIVE_KW[kwp]["kind"] if kwp else "은행·우체국") if res.get("실시간") else (self._place_word(st["leaf"], st["kind"]) if st.get("kind") else f"{res['기능이름']}할 곳")
        where = f"'{st['origin_name']}' 근처" if st.get("origin_name") else "가까운 곳"
        how = {"걸어서": "걸어서 가기 편한", "다니기 어려움": "가장 가까운", "자가용": "차로 가기 가까운", "택시": "택시로 가기 가까운", "버스·지하철": "버스나 지하철로 가기 좋은"}[mode]
        if st.get("mode_guessed"): lines.append("걸어서 가시는 것으로 알고 찾았어요.")
        if st.get("origin_missing"): lines.append(f"{josa(chr(39) + st.pop('origin_missing') + chr(39), '을를')} 지도에서 찾지 못해서 지금 계신 곳 근처로 찾았어요.")
        if cond.get("mode") == "다니기 어려움": lines.append("다니시기 불편하시다고 해서 집으로 배달해 주는 곳으로 찾았어요." if st.get("need") == "배달" else "다니시기 불편하시다고 해서 가장 가까운 곳으로 찾았어요. 집으로 와 줄 수 있는지는 전화로 물어보세요.")
        lines += res.get("안내메모", [])
        if show_unsure:
            lines.append("아래 가게들은 해 주는 곳도 있고 안 해 주는 곳도 있어요. 가시기 전에 전화로 꼭 물어보세요.")
            lines += [self._card_text(st, i + 1, c, label=f"확인 필요 {i + 1}") for i, c in enumerate(res["확인필요후보"])]
            st["stage"] = "done"; return {"type": "result", "text": "\n".join(lines), "result": res, "blocks": pack(lines)}
        if mode in ("걸어서", "다니기 어려움") and res["순위"] and max((c.get("걷는시간_분") or 0) for c in res["순위"]) > 20:
            how = "걸어서 갈 수 있는 곳 중 가까운"   # 20분이 넘는 곳이 있으면 '편한'이라고 하지 않음
        if res["순위"]:
            # 규칙(10/15): 무엇을 찾았는지 + 어떤 기준으로 골랐는지를 주민 말로 밝힘
            lines.append((f"{st['origin_name']} 근처에서 " if st.get("origin_name") else "") + f"{what} {len(res['순위'])}곳을 찾았어요. " + self._criteria(st, res, mode))
            lines += [self._card_text(st, 0, c) for c in res["순위"]]
            succ = self._successor_note(st, res)
            if succ: lines.append(succ)
            if mode in ("걸어서", "다니기 어려움") and min((c.get("걷는시간_분") or 0) for c in res["순위"]) > 30:
                lines.append("걸어서는 30분 넘게 걸려요. 버스로 가는 길은 '버스로 가면요?'라고 물어보세요.")
        else:
            lines.append(f"{where}에서 {josa(what, '을를')} 찾지 못했어요.")
            if res.get("멀리"): lines.append("조금 먼 곳:"); lines += [self._card_text(st, i + 1, c) for i, c in enumerate(res["멀리"])]
            off = self._office(st)
            if off is not None: lines.append(f"{off['상호']}" + (f"(전화 {off['전화']})" if off["전화"] else "") + "에 문의해 보세요. 다른 방법을 안내받으실 수 있어요.")
        if st.get("kind") == "경로당" and st["leaf"] in ("P11.1.02", "P11.1.03"):   # 헌준님 제안(10/15): 경로당 말고도 복지관 프로그램 같은 다른 어울림 활동을 함께 안내
            alt = self._welfare_programs(st)
            if alt: lines.append("경로당 말고도 가까운 복지관 프로그램에 함께하실 수 있어요: " + ", ".join(alt))
        if res["이용자격확인필요"]:
            lines.append("이용하려면 자격이 필요한 곳:"); lines += [self._card_text(st, i + 1, c) for i, c in enumerate(res["이용자격확인필요"])]
        if mode == "버스·지하철":
            h = res.get("집근처정류장")
            lines.append((f"집에서 가장 가까운 곳은 {h['이름']}(걸어서 약 {mins(h['걷는시간_분'])}분)이에요. " if h else "") + "몇 번 버스를 타는지, 얼마나 걸리는지는 '길찾기'를 누르면 카카오맵에서 볼 수 있어요.")
        if res.get("실시간"): lines.append("카카오맵에서 지금 찾은 결과예요 (저장하지 않아요). " + ("영업시간은 은행마다 달라요." if not kwp else "가시기 전에 전화로 한 번 확인해 주세요."))
        if res.get("실시간오류"): lines.append("은행 검색이 잠시 안 돼서 우체국만 보여 드렸어요." if not res.get("실시간목적") and st["leaf"] not in LIVE_KW else "지도 검색이 잠시 안 돼요. 조금 뒤에 다시 찾아 주세요.")
        # 가시기 전에 물어보실 것: 세부 기능별로 주민 말로 써 둔 문장(engine/ask_phrases.py) + 주민이 따로 말한 조건
        from ask_phrases import ASK, WANT_ASK
        free = bool(res.get("순위")) and all(c.get("fid") in self.E.F.index and self.E.F.loc[c["fid"], "출처"] == "공공" for c in res["순위"])   # 공공·복지 시설만이면 값은 묻지 않음 (무료이거나 정해진 요금)
        extra = ([f"{'·'.join(cond['when'])}에도 문을 여는지"] if cond.get("when") else []) + [WANT_ASK[w] for w in cond.get("wants", []) if w in WANT_ASK and not (free and w == "싼 곳")]
        sent = ASK.get(res["확인할것"], "") if res["확인할것"] else ""
        if res["확인할것"] and res["확인할것"] not in ASK: sent = f"가시기 전에 전화로 {res['확인할것']}" + ("을" if _batchim(re.sub(r"\s*\(.*?\)\s*$", "", res["확인할것"])) else "를") + " 물어보세요."
        if extra: sent = (sent + " " if sent else "가시기 전에 ") + ", ".join(extra) + "도 함께 물어보세요."
        if sent and (res["순위"] or res.get("멀리")): lines.append(sent)
        ex = "'1순위 가게는 무슨 메뉴가 있어요?', '블로그에 많이 나온 데로 보여 줘'" if st.get("leaf") in MENU_LEAVES else "'2순위는 주차돼요?', '버스로 가면요?'"
        lines.append(f"더 궁금하신 게 있으면 편하게 물어보세요. 예를 들어 {ex}처럼요.")
        gap = nothing or not (res["순위"] or [c for c in res["이용자격확인필요"] if c["_갈수있음"]])
        life = False
        if gap and st.get("leaf") and st.get("lon") is not None:   # (10/26) 생활 필수 기능일 때만 구청에 알림 (카페·식당·오락이 없는 것은 생활 공백이 아님)
            try:
                import demand, gov_agent as GVA
                life = GVA.life_gap(self.E.leaf[st["leaf"]].get("grade"), st["leaf"], st.get("kind"), demand.where(st["lon"], st["lat"])[1])
            except Exception: life = False
        if gap and life and self.alt_reachable(st, res, st["leaf"]): life = False   # (10/29) 버스 등으로 이용할 수 있는 곳이 있으면 알리지 않음
        if gap and life:
            lines.append("가까운 곳이 없다고 구청·군청에 전할게요. 이름과 대화 내용은 전하지 않아요."); st["gap"] = True
            try:   # 약속대로 지자체 화면의 '주민이 찾지 못한 곳'에 남김 (동네와 기능만, engine/demand.py)
                import demand
                if True: demand.log(st["leaf"], self.E.leaf[st["leaf"]]["name"], st.get("kind"), st["lon"], st["lat"], cond.get("mode") or "걸어서", "가까운 곳이 없음")
            except Exception: pass
        self.D.log(st, len(res["순위"]))
        if len(res["순위"]) <= 1 and res["확인필요후보"]:
            st["stage"] = "unsure"
            ask = "전화로 확인해 봐야 하는 곳은 있어요. 보여 드릴까요?" if not res["순위"] else "이 밖에 전화로 확인해 봐야 하는 곳도 있어요. 보여 드릴까요?"
            return {"type": "question", "text": "\n".join(lines) + "\n" + ask, "options": ["네, 보여 주세요", "아니요"], "result": res, "blocks": pack(lines + [ask])}
        st["stage"] = "done"
        return {"type": "result", "text": "\n".join(lines), "result": res, "blocks": pack(lines)}

    def _welfare_programs(self, st):
        out = []
        for kind, note in (("노인복지관", "60세 이상"), ("종합사회복지관 프로그램", "")):
            try: r = self.E.recommend("P11.1.02", kind, st["lon"], st["lat"], n=1, elig_ok={kind}, speed=st.get("speed", "보통"))
            except Exception: continue
            c = (r.get("추천") or [None])[0]
            if c and c.get("걷는시간_분") is not None and c["걷는시간_분"] <= 60:
                out.append(f"{c['상호']}(걸어서 약 {mins(c['걷는시간_분'])}분" + (f", {note}" if note else "") + ")")
        return out

    def _fallback(self, st):
        st["stage"] = "purpose"
        return {"type": "question", "text": "잘 알아듣지 못했어요. 아래에서 가장 가까운 것을 골라 주세요.",
                "options": ["장보기·식사", "병원·약국", "돌봄·복지", "운동·여가·모임", "행정·우편·금융", "그 밖의 일"]}
