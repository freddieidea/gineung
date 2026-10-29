# 기능상속 웹사이트 서버 (표준 라이브러리만 씀). 사용: python web/server.py [포트]
#  - 주민 화면: 다니던 곳(또는 하려는 일)으로 대화를 시작해 1~3순위 대안을 지도·카드로 봄
#  - 지자체 화면: 에이전트가 날마다 스스로 점검한 구·군별 보고서 (생활에 큰 지장이 생길 폐업만, 예상 위험·추천 해결방안) + 문 닫은 곳 목록·변화 알림
#  - 키(카카오·앤트로픽)는 서버 안에서만 쓰고 화면으로 보내지 않음. 카카오 검색 결과는 저장하지 않음
import os, sys, json, re, uuid, time, threading, datetime, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.basename(ROOT) != "_demo":   # 실제 서버(10/25): 영상 시연 전용 설정(정해진 답·시각·위치 고정)은 환경 변수가 있어도 절대 쓰지 않음
    for _k in [k for k in os.environ if k.startswith("GINEUNG_DEMO")]: os.environ.pop(_k)
sys.path.insert(0, os.path.join(ROOT, "engine")); sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from recommend import Engine
from conversation import Conversation, CLOSURES
from chat import Chat   # 새 대화 구조 (10/16): 언어 모델이 대화를 이끌고 엔진은 도구
from travel import TravelError
from closure_policy import map_kind, MAP_KINDS
STATIC = os.path.join(ROOT, "web", "static")
DAILY_LIMIT = int(os.environ.get("GINEUNG_DAILY_LIMIT", "400"))   # 하루 대화 시작 수 (언어 모델 비용 보호)
SESSION_TTL = 60 * 60 * 3

print("엔진 준비 중..."); t0 = time.time()
E = Engine(); C = Conversation(E); CHAT = Chat(C)
print(f"엔진 준비 끝 ({time.time() - t0:.1f}초)")
LOCK = threading.Lock(); SESS = {}; USE = {"day": None, "n": 0}
KST = datetime.timezone(datetime.timedelta(hours=9))

def is_closed(r):
    """문 닫은 곳인지: 인허가 폐업, 또는 주민 제보를 AI·담당자가 확인해 문 닫음으로 정한 곳"""
    return "폐업" in str(r.get("인허가상태", "")) or "확인: 문 닫음" in str(r.get("제외사유", ""))

def _clean(x):
    if isinstance(x, dict): return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)): return [_clean(v) for v in x]
    if hasattr(x, "item"): return x.item()   # numpy 숫자
    if isinstance(x, float) and x != x: return None
    return x

def _addr(a):
    a = str(a or "")
    return re.sub(r"[\s,]*[^\s,]*\*[^\s]*", "", a).strip() if "*" in a else a   # 가려진 번지는 보이지 않음

def search(q, limit=12):
    q = re.sub(r"\s", "", q or "")
    if len(q) < 2: return []
    F = E.F; key = F["상호"].fillna("").str.replace(r"\s", "", regex=True)
    closed_all = F["인허가상태"].fillna("").str.contains("폐업")
    # 문 닫은 곳은 대안 안내 기간 안에 있는 곳만 찾힘 (pipeline/closure_policy.py). 기간이 지난 곳은 하려는 일로 찾으면 됨
    keep = ~closed_all | F.index.isin(list(CLOSURES))
    hit = F[key.str.contains(re.escape(q), regex=True) & F["경도"].notna() & keep]
    hit = hit.assign(_exact=(key[hit.index] == q).astype(int), _len=key[hit.index].str.len()).sort_values(["_exact", "_len"], ascending=[False, True]).head(limit)
    out = []
    for fid, r in hit.iterrows():
        closed = is_closed(r); c = CLOSURES.get(fid) or {}
        out.append({"fid": fid, "상호": r["상호"], "업종": r["업종"], "주소": _addr(r["주소"]), "닫음": closed, "폐업일자": c.get("폐업일자") or None,
                    "새가게": c.get("새가게") or None, "경도": float(r["경도"]), "위도": float(r["위도"]), "구군": r.get("구군")})
    return out

# 주민 말 속 문 닫은 곳 이름 (10/23): 검색 목록에서 고르지 않고 입력창·대화창에 이름만 써도, 그 곳을 기준으로 지도에 띄우고 대신 갈 곳을 찾음
#  - 대상: 안내 기간 안의 문 닫은 곳(CLOSURES). 이름이 지나가듯 나온 말('우리 약국 근처')은 빼려고, 이름만 쓰거나 문 닫음을 뜻하는 말이 함께 있을 때만
#  - 같은 이름이 여러 곳이거나 흔한 상호(체인점 등)면 짐작하지 않고 어느 곳인지 여쭘 (언어 모델 없이 코드가 답함)
CLOSE_CUE = re.compile(r"닫|폐업|폐원|폐점|없어|없더|사라|망했|그만|안 ?열|안 ?하더|문을? ?안|이사|옮겼|비어|공사")
def _nk(x): return re.sub(r"[^0-9a-z가-힣]", "", str(x or "").lower())
NAME_N = {"F": None, "n": {}}
def _name_count(n):
    if NAME_N["F"] is not E.F:   # 엔진을 새로 만들면 다시 셈
        NAME_N["F"] = E.F; NAME_N["n"] = E.F["상호"].map(_nk).value_counts().to_dict()
    return NAME_N["n"].get(n, 0)
def _place_toks(fid):
    r = E.F.loc[fid]; dong = str(r.get("행정동") or "")
    toks = set(re.sub(r"^대구(광역시)?\s*", "", _addr(r["주소"])).split()) | {dong, re.sub(r"[\d,·.]+(가)?동$", "동", dong), str(r.get("구군") or "")}
    return {_nk(x) for x in toks if re.search(r"[가-힣]", x) and len(_nk(x)) >= 2}
def named_closed(text, cur=None, among=None):
    """주민 말에 이름이 나온 문 닫은 곳 → (fid 목록, 확실한지)"""
    t = _nk(text)
    if len(t) < 3: return [], False
    hits = []
    for fid, c in list(CLOSURES.items()):
        if fid not in E.F.index or (among and fid not in among): continue
        ns = {_nk(c.get("상호")), _nk(re.sub(r"\(.*?\)", "", str(c.get("상호") or "")))}
        m = max((len(n) for n in ns if len(n) >= 3 and n != _nk(c.get("업종")) and n in t), default=0)
        if not m:   # 두 글자 상호('팥지'): 말이 그 이름으로 시작하고(이름만, 또는 문 닫음을 뜻하는 말과 함께) 흔하지 않은 이름일 때만
            m = max((len(n) for n in ns if len(n) == 2 and n != _nk(c.get("업종")) and t.startswith(n) and (t == n or CLOSE_CUE.search(text or "")) and _name_count(n) <= 2), default=0)
        if m: hits.append((fid, m))
    if not hits: return [], False
    top = max(m for _, m in hits)
    if not (among or CLOSE_CUE.search(text or "") or len(t) <= top + 8): return [], False
    hits = [f for f, m in hits if m == top]   # 더 긴 이름이 맞으면 그쪽 ('대명온누리약국' > '온누리약국')
    if cur in hits: return [], False   # 지금 이야기하는 곳
    sc = {f: sum(1 for x in _place_toks(f) if x in t) for f in hits}; best = max(sc.values())
    if best: hits = [f for f in hits if sc[f] == best]   # 말에 든 동네·길 이름으로 좁힘
    if len(hits) > 1 and len({(round(float(E.F.loc[f, "경도"]), 4), round(float(E.F.loc[f, "위도"]), 4)) for f in hits}) == 1: hits = hits[:1]   # 같은 자리에 두 번 오른 가게
    common = _name_count(_nk(re.sub(r"\(.*?\)", "", str(E.F.loc[hits[0], "상호"])))) >= 3   # 흔한 상호: 다른 지점일 수 있음
    return hits, len(hits) == 1 and (best > 0 or not common or bool(among))
def with_closed_line(r, st):
    """이름으로 바꾼 문 닫은 곳: 답 첫머리에 '○○은 ○월에 문을 닫았어요'를 둠 (주민이 물은 '닫았어요?'에 먼저 답하고, 왜 지도가 옮겨 갔는지 알게)"""
    from conversation import closed_line
    fid = st.get("closed_fid")
    if not fid or fid not in E.F.index or "닫" in str(r.get("text", ""))[:80]: return r
    line = closed_line(fid, str(E.F.loc[fid, "상호"]))
    r["blocks"] = [{"text": line}] + (r.get("blocks") or [{"text": x} for x in str(r.get("text", "")).split("\n")]); r["text"] = line + "\n" + str(r.get("text", ""))
    return r
def pick_closed_question(st, hits, text):
    """어느 곳인지 여쭘: 보기는 '상호 · 구 동' (같은 동이면 길 이름까지). 고르면 그 말로 다시 찾아 하나로 좁혀짐"""
    from conversation import josa
    road = lambda r: " ".join(re.sub(r"^대구(광역시)?\s*", "", _addr(r["주소"])).split()[1:3])
    base = {f: f"{E.F.loc[f, '상호']} · {E.F.loc[f].get('구군') or ''} {E.F.loc[f].get('행정동') or ''}".strip() for f in hits[:6]}
    labs = {f: (l + " " + road(E.F.loc[f]) if list(base.values()).count(l) > 1 else l) for f, l in base.items()}
    nm = str(E.F.loc[hits[0], "상호"])
    if len(hits) > 6:
        q = f"최근 문 닫은 {josa(nm, '이가')} 여러 곳이에요. 어느 동네에 있던 곳인가요? (예: '대명동 {nm}')"; opts = []
    elif len(hits) == 1:
        r = E.F.loc[hits[0]]; where = f"{r.get('구군') or ''} {r.get('행정동') or ''}".strip()
        q = f"{where}에 있다가 최근 문 닫은 {josa(nm, '을를')} 말씀하시는 건가요?"; opts = [labs[hits[0]], "아니요, 다른 곳이에요"]
    else:
        q = f"최근 문 닫은 {josa(nm, '이가')} {len(hits)}곳 있어요. 어느 곳인가요?"; opts = list(labs.values()) + ["여기 없어요"]
    st["pick_closed"] = hits
    st.setdefault("msgs", []).append({"role": "user", "content": text}); st["msgs"].append({"role": "assistant", "content": q + (" 보기: " + " / ".join(opts) if opts else "")})
    return {"type": "question", "text": q, "blocks": [{"text": q}], "options": opts, "기준": CHAT._origin_label(st)}
def closed_session(fid, old=None):
    """문 닫은 곳을 기준으로 새 대화 상태 (앞에서 말한 걸음·이동 조건은 이어 받음)"""
    r = E.F.loc[fid]
    st, _ = CHAT.start(float(r["경도"]), float(r["위도"]), gu=r.get("구군"), closed_fid=fid, origin_name=str(r["상호"]), origin_closed=is_closed(r))
    for k in ("slow_said", "wheel_said", "speed", "prefer", "here"):
        if old and k in old: st[k] = old[k]
    if old and (old.get("cond") or {}).get("mode_set"): st["cond"].update(mode=old["cond"]["mode"], mode_set=True)
    return st

def _now_kind(c):
    k = str(c.get("새가게업종") or "")
    return "" if (not k or k.startswith(("기타", "그 외"))) else k
def closure_pins(gu=None):
    """지도에 '문 닫음'을 띄우는 곳 (지도 표시 기간 안). 한 자리(좌표)에 핀 하나.
    새 가게는 그 칸을 이은 문 닫은 곳 기록에만 붙임: 같은 건물(같은 좌표)의 다른 칸에서 문 닫은 곳과 섞이지 않게
    (예: 다사로 23의 경양식 자리에 숯불가든이 들어왔어도, 같은 건물 미용실 자리의 새 가게로 보이면 안 됨)"""
    pins = {}
    for c in CLOSURES.values():
        if c.get("단계") != "지도 표시" or (gu and c.get("구군") != gu): continue
        try: lon, lat = float(c["경도"]), float(c["위도"])
        except Exception: continue
        p = pins.setdefault((round(lon, 5), round(lat, 5)), {"경도": lon, "위도": lat, "기록": []})
        if any(x["상호"] == c["상호"] for x in p["기록"]): continue   # 같은 가게가 상가 자료에 두 번 있는 경우
        now = {"상호": c["새가게"], "업종": _now_kind(c), "개업일": c.get("새가게개업일") or None, "fid": c.get("새가게fid") or None} if c.get("새가게") else None
        p["기록"].append({"fid": c["fid"], "상호": c["상호"], "업종": c["업종"], "폐업일자": c["폐업일자"], "주소": _addr(c["주소"]), "묶음": c["묶음"], "분류": map_kind(c["업종"], c["묶음"]),
                         "안내까지": c["안내까지"], "지금": now})
    out = list(pins.values())
    for p in out: p["기록"].sort(key=lambda x: x["폐업일자"], reverse=True)
    return out
def closure_list(gu=None):
    """지자체 화면: 대안 안내 기간 안의 문 닫은 곳 (최근 폐업부터)"""
    rows = []
    for c in CLOSURES.values():
        if gu and c.get("구군") != gu: continue
        rows.append({"fid": c["fid"], "상호": c["상호"], "업종": c["업종"], "구군": c["구군"], "주소": _addr(c["주소"]), "폐업일자": c["폐업일자"], "묶음": c["묶음"], "분류": map_kind(c["업종"], c["묶음"]),
                     "단계": c["단계"], "지도표시까지": c["지도표시까지"], "안내까지": c["안내까지"], "새가게": c.get("새가게") or None, "새가게업종": _now_kind(c) or None,
                     "새가게개업일": c.get("새가게개업일") or None, "기능이어짐": str(c.get("같은기능새가게")) == "True",
                     "경도": float(c["경도"]) if c.get("경도") else None, "위도": float(c["위도"]) if c.get("위도") else None})
    rows.sort(key=lambda x: x["폐업일자"], reverse=True)
    return rows

PUBLIC_KIND = {"경로당": ("경로당", "경"), "노인복지관": ("노인복지관", "복"), "사회복지관": ("사회복지관", "복"), "장애인복지관": ("장애인복지관", "복"),
    "행정복지센터": ("행정복지센터", "행"), "공공도서관": ("도서관", "도"), "작은도서관": ("작은도서관", "도"), "보건기관": ("보건소", "보"), "건강생활지원센터": ("건강생활지원센터", "보"),
    "정신건강복지센터": ("정신건강복지센터", "보"), "우체국": ("우체국", "우"), "무료급식소": ("무료급식소", "급"), "지역아동센터": ("지역아동센터", "아"), "다함께돌봄센터": ("다함께돌봄센터", "아"),
    "가족센터": ("가족센터", "가"), "주야간보호": ("주야간보호", "돌"), "단기보호": ("단기보호", "돌"), "지구대·파출소": ("지구대·파출소", "안")}
# 복지시설과 공공시설을 나눠 다른 색·그림으로 (헌준님 10/16)
PUB_GROUP = {"경로당": ("복지", "house"), "노인복지관": ("복지", "heart"), "사회복지관": ("복지", "heart"), "장애인복지관": ("복지", "heart"), "무료급식소": ("복지", "bowl"),
             "지역아동센터": ("복지", "child"), "다함께돌봄센터": ("복지", "child"), "가족센터": ("복지", "family"), "주야간보호": ("복지", "care"), "단기보호": ("복지", "care"),
             "정신건강복지센터": ("복지", "care"), "행정복지센터": ("공공", "gov"), "공공도서관": ("공공", "book"), "작은도서관": ("공공", "book"), "보건기관": ("공공", "cross"),
             "건강생활지원센터": ("공공", "cross"), "우체국": ("공공", "mail"), "지구대·파출소": ("공공", "shield")}
_PUB = None
def public_places(w, s, e, n, limit=400):
    """화면 범위 안의 공공·복지시설 (공공 자료, 대안으로 안내하는 곳만: 단지 안 경로당처럼 주민 누구나 갈 수 없는 곳은 뺌)"""
    global _PUB
    if _PUB is None:
        F = E.F; m = (F["출처"] == "공공") & F["업종"].isin(list(PUBLIC_KIND)) & F["대안후보"].isin(["예", "확인 필요"]) & F["경도"].notna()
        _PUB = F[m][["상호", "업종", "주소", "전화", "경도", "위도", "참고", "대안후보"]].copy()
    P = _PUB[(_PUB["경도"].astype(float).between(w, e)) & (_PUB["위도"].astype(float).between(s, n))].head(limit)
    out = []
    for fid, r in P.iterrows():
        lab, ch = PUBLIC_KIND[r["업종"]]
        note = C._pub_note({"fid": fid}).get("안내", []) if fid in E.F.index else []
        grp, ic = PUB_GROUP.get(r["업종"], ("공공", "gov"))
        out.append({"fid": fid, "상호": r["상호"], "종류": lab, "글자": ch, "갈래": grp, "그림": ic, "주소": _addr(r["주소"]), "전화": str(r["전화"] or "").replace("nan", ""),
                    "안내": note, "확인필요": r["대안후보"] == "확인 필요", "경도": float(r["경도"]), "위도": float(r["위도"])})
    return out

def gu_at(lon, lat):
    try: return C._stops_() and None
    except Exception: return None

def answer_payload(r, st):
    out = {"type": r.get("type"), "text": r.get("text", ""), "options": r.get("options") or [], "blocks": r.get("blocks") or [{"text": x} for x in r.get("text", "").split("\n")],
           "connect": r.get("connect"), "위급": r.get("위급"), "connect_options": r.get("connect_options") or [],
           "출발": ({"경도": st["from"][0], "위도": st["from"][1], "이름": "지금 계신 곳", "닫음": False} if st.get("from") else
                    {"경도": st["lon"], "위도": st["lat"], "이름": st.get("origin_name") or "출발",
                    "닫음": bool(st.get("origin_closed")) and (st["lon"], st["lat"]) == tuple(st["home"])}),
           "찾는곳": ({"경도": st["lon"], "위도": st["lat"], "이름": st.get("origin_name") or "", "닫음": bool(st.get("origin_closed")) and (st["lon"], st["lat"]) == tuple(st["home"])} if st.get("from") else None),
           "출처": r.get("출처") or [], "기준": r.get("기준"), "질문": r.get("질문"), "바로": r.get("바로"), "제목": chat_title(st)}
    return _clean(out)

def chat_title(st):
    """대화 맨 위 제목: 주민이 쓴 긴 문장 대신 지금 찾는 것을 짧게 (예: '노인복지관 찾기', '다솜약국 대신 갈 곳')"""
    if st.get("closed_fid") and st["closed_fid"] in E.F.index: return f"{E.F.loc[st['closed_fid'], '상호']} 대신 갈 곳"
    OCC = {"2차·술 위주": "2차 술집", "디저트 카페": "디저트 카페", "분위기 좋은 카페": "분위기 좋은 카페", "넓은 카페": "여럿이 앉을 카페", "데이트": "데이트할 곳", "모임·회식": "모임 장소", "손님 접대": "손님 모실 곳"}
    if st.get("occasion") in OCC: return OCC[st["occasion"]] + " 찾기"
    LEAF = {"P01.1.05": "식당", "P01.2.01": "카페", "P01.2.02": "빵집", "P03.2.01": "약국"}
    k = st.get("kind") if not st.get("auto") else None
    lid = st.get("leaf"); nm = k or LEAF.get(lid) or (E.leaf.get(lid, {}).get("name") if lid else None)
    if nm: return re.sub(r"\s*(구입|이용)$", "", str(nm)) + " 찾기"
    return "대신 갈 곳 찾기"

def gc():
    now = time.time()
    for k in [k for k, v in SESS.items() if now - v["t"] > SESSION_TTL]: SESS.pop(k, None)

def count_use():
    d = datetime.datetime.now(KST).date().isoformat()
    if USE["day"] != d: USE.update(day=d, n=0)
    if USE["n"] >= DAILY_LIMIT: return False
    USE["n"] += 1; return True

def notices(limit=200):
    p = os.path.join(ROOT, "data", "notices", "notices.jsonl"); out = []
    if not os.path.exists(p): return out
    for line in open(p, encoding="utf-8"):
        try: n = json.loads(line)
        except Exception: continue
        f = n.get("시설") or {}; fid = f.get("fid"); lon = lat = None
        if fid in E.F.index and E.F.loc[fid, "경도"] == E.F.loc[fid, "경도"]: lon, lat = float(E.F.loc[fid, "경도"]), float(E.F.loc[fid, "위도"])
        out.append({"id": n.get("id"), "등급": n.get("등급"), "종류": n.get("종류"), "구군": n.get("구군"), "만든때": n.get("만든때"), "제목": n.get("제목"),
                    "본문": n.get("본문"), "상호": f.get("상호"), "주소": _addr(f.get("주소")), "경도": lon, "위도": lat})
    out.sort(key=lambda x: ({"긴급": 0, "중요": 1, "참고": 2}.get(x["등급"], 3), x["만든때"] or ""), reverse=False)
    return out[:limit]

# ── 지자체 담당자 보조 에이전트 (10/16, engine/gov_agent.py): 날마다 스스로 점검하고 구·군별 보고서를 만듦 ──
from gov_agent import GovAgent, last_run as gov_last_run, today_done as gov_today_done
GOV = {"agent": None, "geo": None}; REPORTS = {}
def gov():
    if GOV["agent"] is None:
        G = GovAgent(engine=E)
        G.on_engine = _adopt_engine; G.on_closures = _reload_closures
        GOV["agent"] = G
    return GOV["agent"]
def _reload_closures():
    import conversation
    new = conversation._load_closures(); CLOSURES.clear(); CLOSURES.update(new)
def _adopt_engine(newE):
    """점검이 새로 문 연 곳·닫은 곳을 반영해 엔진을 다시 만들면 주민 화면도 새 엔진으로 바꿈 (진행 중인 대화는 하던 엔진으로 끝냄)"""
    global E, C, CHAT
    c2 = Conversation(newE); ch2 = Chat(c2)
    E, C, CHAT = newE, c2, ch2
# 지자체 화면 잠금 (10/19): 담당자 접속 코드가 있어야 지자체 화면과 /api/gov/* 를 씀 (주민이 '폐업 맞음' 같은 버튼을 누르지 못하게)
#  코드는 settings/gov_code.txt (없으면 서버를 처음 켤 때 6자리로 만들어 터미널에 알려 줌). 바꾸려면 그 파일을 고치고 서버를 다시 켬
import hashlib, secrets
_GC = os.path.join(ROOT, "settings", "gov_code.txt")
if not os.path.exists(_GC):
    open(_GC, "w", encoding="utf-8").write(f"{secrets.randbelow(900000) + 100000}")
GOV_CODE = open(_GC, encoding="utf-8").read().strip()
GOV_TOKEN = hashlib.sha256(("기능상속:" + GOV_CODE).encode()).hexdigest()
# 심사용 코드 (10/21, 10/29 헌준님): 심사 기간 동안 고정(settings/gov_view_code.txt, 숫자 6자리). 심사위원이 담당자와 같은 화면·기능을 쓰되
#  '다시 점검·폐업 확인·판단 바로잡기·처리 완료' 같은 반영과 업무 보조 대화·의견 기록은 서버에 일체 남기지 않음 (폐업 사전 검토는 가정 계산이라 허용)
#  정식 운영 시에는 인증된 담당자 개인별 코드로 바꾸고, 담당자 요청은 지금 담당자 코드처럼 그대로 반영
#  코드는 settings/gov_view_code.txt (없으면 처음 켤 때 8자리로 만듦. 화면·터미널에 내용을 띄우지 않음)
_GVC = os.path.join(ROOT, "settings", "gov_view_code.txt")
if not os.path.exists(_GVC):
    open(_GVC, "w", encoding="utf-8").write("".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8)))
GOV_VIEW_CODE = open(_GVC, encoding="utf-8").read().strip()
GOV_VIEW_TOKEN = hashlib.sha256(("기능상속-보기:" + GOV_VIEW_CODE).encode()).hexdigest()
GOV_WRITE = {"/api/gov/run", "/api/gov/field", "/api/gov/confirm", "/api/gov/lesson", "/api/gov/alt", "/api/gov/feedback", "/api/gov/mark"}   # 보기 전용으로는 막는 일
# 남용 막기 (10/21): 같은 접속 주소(IP)마다 하루 한도. 메모리에만 두고 저장하지 않음
IP_LIMIT = {"제보": int(os.environ.get("GINEUNG_IP_REPORTS", "5")), "대화": int(os.environ.get("GINEUNG_IP_CHATS", "20"))}
TURN_LIMIT = int(os.environ.get("GINEUNG_TURN_LIMIT", "20"))   # 대화 하나에서 주고받는 횟수
IPUSE = {"day": None}
def client_ip(h):
    """접속 주소: 앞단 프록시(사설·내부 주소)를 거쳐 왔으면 그 프록시가 붙인 X-Forwarded-For의 마지막 값, 아니면 직접 접속 주소 (꾸민 머리글로 한도를 피하지 못하게)"""
    import ipaddress
    ip = h.client_address[0]; xff = h.headers.get("X-Forwarded-For") or ""
    try: inner = ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback
    except ValueError: inner = False
    return (xff.split(",")[-1].strip() or ip) if (inner and xff) else ip
def ip_ok(h, kind):
    d = datetime.datetime.now(KST).date().isoformat()
    if IPUSE["day"] != d: IPUSE.clear(); IPUSE["day"] = d
    c = IPUSE.setdefault(kind, {}); ip = client_ip(h)
    if c.get(ip, 0) >= IP_LIMIT[kind]: return False
    c[ip] = c.get(ip, 0) + 1; return True
PRE = {}   # 폐업 사전 검토: 날짜·건수·결과 (메모리에만, 저장하지 않음)
def pre_run(fid):
    day = datetime.datetime.now(KST).date().isoformat()
    if PRE.get("day") != day: PRE.clear(); PRE.update(day=day, n=0, cache={})
    if fid in PRE["cache"]: return PRE["cache"][fid]
    if PRE["n"] >= 30: return {"오류": "오늘 사전 검토 한도(30건)를 다 썼습니다. 내일 다시 이용해 주세요."}
    PRE["n"] += 1
    try: out = gov().pre_review(fid)
    except Exception as ex:   # 계산 중 문제가 생겨도 화면에 까닭을 보여 줌
        print("[사전 검토 오류]", fid, repr(ex)[:200], flush=True); PRE["n"] -= 1
        out = {"오류": "이 시설은 지금 검토하지 못했습니다. 잠시 뒤 다시 시도해 주세요."}
    if not out.get("오류"): PRE["cache"][fid] = out
    return out
# 업무 보조 대화 (10/21): 하루 한도(담당자·심사용 따로, 언어 모델 비용), 대화는 메모리에만 3시간
GCHAT = {"chat": None, "day": None, "n": {}}; GSESS = {}
GCHAT_LIMIT = {"담당자": int(os.environ.get("GINEUNG_GOVCHAT_LIMIT", "100")), "심사": int(os.environ.get("GINEUNG_GOVCHAT_VIEW_LIMIT", "30"))}
def demo_replay(text):
    """GINEUNG_DEMO_REPLAY(파일 경로)가 있을 때만: 그 파일에 담긴 질문이면 미리 확인한 답을 돌려줌 (영상 시연 서버 전용)"""
    p = os.environ.get("GINEUNG_DEMO_REPLAY")
    if not p: return None
    try:
        R = json.load(open(p if os.path.isabs(p) else os.path.join(ROOT, p), encoding="utf-8"))
        k = re.sub(r"[\s?？.!]", "", str(text))
        return next((x for x in R if re.sub(r"[\s?？.!]", "", x["q"]) == k or (x.get("keys") and all(w in k for w in x["keys"]))), None)   # 조사·띄어쓰기가 조금 달라도 (예: '공산동에 의원이 없는 곳에…')
    except Exception as ex:
        print("[시연 답 불러오기 오류]", repr(ex)[:200], flush=True); return None
def gov_chat():
    if GCHAT["chat"] is None or GCHAT["chat"].G is not gov():
        from gov_chat import GovChat
        GCHAT["chat"] = GovChat(gov(), pre_fn=pre_run)
    return GCHAT["chat"]
def gov_chat_ok(role):
    d = datetime.datetime.now(KST).date().isoformat()
    if GCHAT["day"] != d: GCHAT.update(day=d, n={})
    if GCHAT["n"].get(role, 0) >= GCHAT_LIMIT.get(role, 30): return False
    GCHAT["n"][role] = GCHAT["n"].get(role, 0) + 1; return True
def gov_doc(q):
    import gov_docs as GD
    b = GD.load()
    if not b: return None
    gu = q("gu") if q("gu") in GD.GUS else None; kind = q("kind")
    if kind == "report": return ("text/html; charset=utf-8", GD.report_html(b, gu, gov_last_run(), auto_print=q("print") == "1", title=(q("title") or "")[:60] or None).encode("utf-8"), None)
    if kind == "xlsx":
        ts = [t for t in (q("tables") or "폐업,확인요청,공백구역").split(",") if t in GD.TABLES] or ["폐업"]
        return ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", GD.xlsx_for(b, ts, gu, q("only") or None, q("dong") or None, q("since") or None), GD.filename(b, "_".join(ts), (gu or "") + (q("dong") or "") or None))
    if kind == "summary": return ("text/plain; charset=utf-8", GD.summary_text(b, gu, q("only") or None, q("dong") or None).encode("utf-8"), None)
    return None
def find_open(qs):
    """폐업 사전 검토 대상 찾기: 영업 중인 시설 (주민 안내 대상만, 버스정류장 제외)
    이름 또는 업종으로 찾음. '동구 유치원'처럼 구·군을 함께 쓰면 그 구·군 안에서만. 이름·업종이 모두 맞는 곳 → 이름만 → 업종만, 같은 순위는 짧은 이름 순"""
    toks = str(qs).split()[:6]
    F = E.F; gus = set(F["구군"].dropna().astype(str))
    gu = [t for t in toks if t in gus]; rest = re.sub(r"\s", "", "".join(t for t in toks if t not in gus))[:30]
    if len(rest) < 2: return []
    base = F[F["대안후보"].isin(["예", "확인 필요"]) & (F["업종코드"] != "PUB:버스정류장") & F["x"].notna()]
    if gu: base = base[base["구군"].isin(gu)]
    nm = base["상호"].astype(str).str.replace(r"\s", "", regex=True).str.contains(re.escape(rest))
    ty = base["업종"].astype(str).str.replace(r"\s", "", regex=True).str.contains(re.escape(rest))
    m = base[nm | ty]
    rank = 2 - nm[m.index].astype(int) - ty[m.index].astype(int) * 2 + (ty[m.index] & ~nm[m.index]).astype(int) * 3   # 이름·업종 모두 → 이름만 → 업종만
    m = m.assign(_r=rank, _l=m["상호"].astype(str).str.len()).sort_values(["_r", "_l"]).head(10)
    return [{"fid": f, "상호": r["상호"], "업종": r["업종"], "구군": r["구군"], "주소": r["주소"]} for f, r in m.iterrows()]
def public_gaps():
    """기능 공백 현황 공개용: 지자체 보고서에서 사실만 (영향·이전 시설·운영 정보·주민 수요). AI 판단(보고·관찰), 조치, 담당 부서는 빼고"""
    p = os.path.join(ROOT, "data", "gov", "brief_latest.json")
    try: b = json.load(open(p, encoding="utf-8"))
    except Exception: return {"날짜": None, "목록": []}
    if os.environ.get("GINEUNG_DEMO_REPORT"): b["날짜"] = os.environ["GINEUNG_DEMO_REPORT"][:10]   # 영상 시연 서버 전용 (10/24)
    keep = ("구군", "행정동", "기능", "결손기능", "상호", "업종", "폐업일자", "개업일자", "운영시간", "영향", "경도", "위도", "주민찾음")
    # 10/21: 한 목록 '기능 공백 구역' (상시 부재 + 폐업 영향, 표시: 최근 폐업·지자체 보고·창업 참고 — engine/area_gap.unified). AI 판단 글·조치·담당 부서는 넣지 않음
    import gov_docs as _GD   # (10/29) 읍·면 구역은 마을(리)도 함께
    return {"날짜": b.get("날짜"), "구역": [_GD._ri(r) for r in sorted(b.get("기능공백구역", []), key=lambda r: -(r.get("주민") or 0))], "해소": b.get("구역해소", [])}   # 해소: 최근 30일 안에 시설이 생겨 사라진 구역
# 배경 지도 (10/21): 국토교통부 브이월드 배경지도. 키가 화면에 드러나지 않게 서버가 대신 받아 그대로 넘김 (파일로 저장하지 않음, 브라우저 캐시만)
_VW = os.path.join(ROOT, "settings", "vworld_key.txt")
VW_KEY = open(_VW, encoding="utf-8").read().strip() if os.path.exists(_VW) else ""
def vworld_tile(z, x, y):
    import urllib.request
    if not VW_KEY or not (6 <= z <= 19): return None
    u = f"https://api.vworld.kr/req/wmts/1.0.0/{VW_KEY}/Base/{z}/{y}/{x}.png"
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"Referer": "http://localhost/"}), timeout=10) as r:
            b = r.read(); ct = r.headers.get("Content-Type", "")
        return b if ct.startswith("image/") else None
    except Exception: return None
GAP_CELLS = {}
def gap_cells(rid):
    """기능 공백 구역 색칠용 100m 칸 (하루 한 번 계산해 둠)"""
    day = datetime.datetime.now(KST).date().isoformat()
    if GAP_CELLS.get("day") != day: GAP_CELLS.clear(); GAP_CELLS["day"] = day
    if rid not in GAP_CELLS:
        import area_gap as AG
        try: GAP_CELLS[rid] = AG.cells(gov(), rid)
        except Exception as ex: print("[구역 칸 오류]", rid, repr(ex)[:160], flush=True); return []
    return GAP_CELLS[rid]
def gap_dongs():
    """기능 공백이 있는 행정동 경계 (처음 화면에 옅게 칠함)"""
    if GOV["geo"] is None:
        g = json.load(open(os.path.join(ROOT, "data", "raw", "boundary", "daegu_hjd_20260701.geojson"), encoding="utf-8"))
        GOV["geo"] = {(f["properties"]["sggnm"], _hjd_key(f["properties"]["adm_nm"].split()[-1])): f for f in g["features"]}
    cnt = {}
    for r in public_gaps().get("구역", []):
        k = (r["구군"], _hjd_key(r["행정동"])); cnt.setdefault(k, []).append(r["시설"])
    feats = []
    for (gu, d), fs in cnt.items():
        f = GOV["geo"].get((gu, d))
        if f: feats.append({"type": "Feature", "geometry": f["geometry"], "properties": {"구군": gu, "행정동": f["properties"]["adm_nm"].split()[-1], "건수": len(fs), "시설": sorted(set(fs))}})
    return {"type": "FeatureCollection", "features": feats}
def gov_role(h):
    """담당자 / 심사(보기 전용) / None"""
    c = [p.strip() for p in (h.headers.get("Cookie") or "").split(";")]
    if f"gov={GOV_TOKEN}" in c: return "담당자"
    if f"gov={GOV_VIEW_TOKEN}" in c: return "심사"
    return None
def gov_ok(h): return gov_role(h) is not None
GOV_TIME = os.environ.get("GINEUNG_GOV_TIME", "08:30")   # 평일 이 시각에 새 자료를 받아 살펴봄 (담당자가 9시에 일을 시작하기 전에)
def _gov_due():
    n = datetime.datetime.now(KST); hh, mm = (int(x) for x in GOV_TIME.split(":"))
    return n.weekday() < 5 and (n.hour, n.minute) >= (hh, mm)
def _gov_loop():
    """서버가 켜져 있는 동안 평일 아침 GOV_TIME에 점검. 그 시각이 지나 켜졌는데 오늘 점검을 아직 못 했으면 바로 함. 자료를 다 못 받으면 1시간 뒤 다시"""
    time.sleep(15); tried = 0.0
    while True:
        try:
            if _gov_due() and not gov_today_done() and time.time() - tried > 3600:
                tried = time.time(); gov().run(fetch=True, llm=True)
        except Exception:
            import traceback; traceback.print_exc()
        time.sleep(60)
def _hm(t):   # "08:30" → "오전 8시 30분"
    h, m = (int(x) for x in t.split(":"))
    return f"{'오전' if h < 12 else '오후'} {h % 12 or 12}시" + (f" {m}분" if m else "")


def gov_brief():
    p = os.path.join(ROOT, "data", "gov", "brief_latest.json")
    b = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
    if b and os.environ.get("GINEUNG_DEMO_REPORT"): b["날짜"] = os.environ["GINEUNG_DEMO_REPORT"][:10]   # 영상 시연 서버 전용 (10/24)
    G = GOV["agent"]; lr = gov_last_run()
    handled = G.handled if G else (json.load(open(os.path.join(ROOT, "data", "gov", "handled.json"), encoding="utf-8")) if os.path.exists(os.path.join(ROOT, "data", "gov", "handled.json")) else {})
    if b:
        import gov_docs as _GD   # (10/29 헌준님) 읍·면은 마을(리)까지: 같은 면의 다른 마을이 같은 이름으로 겹쳐 보이지 않게
        for v in b["구군"].values():
            for k_ in ("항목", "확인요청", "질문", "보고안함"): v[k_] = [_GD._ri(r) for r in v.get(k_, [])]
        for k_ in ("기능공백구역", "하나남은곳", "확인대기"): b[k_] = [_GD._ri(r) for r in b.get(k_, []) or []]
        for v in b["구군"].values():
            for r in v["항목"]: r["처리"] = handled.get(r["fid"])
    live = G.live if G else None
    run = lambda x: {"시작": x["시작"], "끝": x.get("끝"), "단계": [{k: s.get(k) for k in ("단계", "상태", "글", "초")} for s in x["단계"]]} if x else None
    p_l = os.path.join(ROOT, "data", "gov", "lessons.jsonl")
    lessons = [json.loads(l) for l in open(p_l, encoding="utf-8") if l.strip()] if os.path.exists(p_l) else []
    return {"보고서": b, "점검": run(lr), "진행": run(live) if live else None, "일정": "평일 " + _hm(GOV_TIME), "배운원칙": lessons,
            "오늘": (os.environ.get("GINEUNG_DEMO_REPORT") or datetime.datetime.now(KST).isoformat())[:10]}   # 화면의 '오늘' (영상 시연 서버는 보고서 날짜)
def _hjd_key(s): return re.sub(r"[\s.·ㆍ,]", "", str(s or ""))
def gov_area(fid):
    """보고서 항목의 영향 행정동 경계 (지도에 칠함)"""
    if GOV["geo"] is None:
        g = json.load(open(os.path.join(ROOT, "data", "raw", "boundary", "daegu_hjd_20260701.geojson"), encoding="utf-8"))
        GOV["geo"] = {(f["properties"]["sggnm"], _hjd_key(f["properties"]["adm_nm"].split()[-1])): f for f in g["features"]}
    p = os.path.join(ROOT, "data", "gov", "brief_latest.json")
    if not os.path.exists(p): return {"type": "FeatureCollection", "features": []}
    b = json.load(open(p, encoding="utf-8")); feats = []
    for v in b["구군"].values():
        for r in v["항목"]:
            if r["fid"] != fid: continue
            for d in r["영향동"]:
                f = GOV["geo"].get((d["구군"], _hjd_key(d["행정동"])))
                if f: feats.append({"type": "Feature", "geometry": f["geometry"], "properties": {"행정동": d["행정동"], "주민": d["주민"]}})
    return {"type": "FeatureCollection", "features": feats}

class H(BaseHTTPRequestHandler):
    server_version = "gineung/1.0"
    def log_message(self, fmt, *a): pass
    def _json(self, obj, code=200):
        b = json.dumps(_clean(obj), ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try: return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception: return {}
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(u.query); q = lambda k: (qs.get(k) or [""])[0]
        if u.path.startswith("/api/gov/") and not gov_ok(self): return self._json({"잠김": True, "글": "담당자 접속 코드를 입력해 주세요."}, 401)
        m_t = re.fullmatch(r"/tiles/(\d+)/(\d+)/(\d+)\.png", u.path)
        if m_t:
            b = vworld_tile(*(int(v) for v in m_t.groups()))
            if b is None: self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
            self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "public, max-age=604800"); self.end_headers(); self.wfile.write(b); return
        if u.path == "/api/search": return self._json({"결과": search(q("q"))})
        if u.path == "/api/place":
            try: c = C._kakao().find_place(q("q"), 128.5935, 35.8714)
            except TravelError: return self._json({"결과": [], "오류": "장소 찾기가 잠시 안 돼요"})
            return self._json({"결과": c[:5]})
        if u.path == "/api/notices": return self._json({"알림": notices()})
        if u.path == "/api/gov-guide":   # (10/29 헌준님) 심사 기간(1~2개월)에는 지자체 화면 잠금 아래 심사용 보기 전용 코드를 안내. 정식 운영 시 GINEUNG_HIDE_REVIEW_CODE=1로 끔
            return self._json({"심사코드": None if os.environ.get("GINEUNG_HIDE_REVIEW_CODE") else GOV_VIEW_CODE})
        if u.path == "/api/blog":   # 카드의 '블로그 글' 버튼: 그 자리에서 찾아 보여 주기만 함 (저장·대화 모델 전달 없음)
            fid = q("fid")
            if fid not in E.F.index: return self._json({"글수": None, "글": []})
            r = E.F.loc[fid]
            try: b = C._blog().posts(r["상호"], r["주소"], r.get("구군"), r.get("인허가상호"))
            except Exception: return self._json({"글수": None, "글": [], "오류": "블로그 검색이 잠시 안 돼요"})
            return self._json(dict(b, 상호=r["상호"]))
        if u.path == "/api/places":   # 지도의 공공·복지시설 (화면에 보이는 범위만)
            try: w, s_, e, n = (float(q(k)) for k in ("w", "s", "e", "n"))
            except Exception: return self._json({"시설": []})
            return self._json({"시설": public_places(w, s_, e, n)})
        if u.path == "/api/closures": return self._json({"핀": closure_pins(q("gu") or None), "분류": MAP_KINDS})
        if u.path == "/api/closure_list": return self._json({"목록": closure_list(q("gu") or None)})
        if u.path == "/api/gaps": return self._json(public_gaps())   # 기능 공백 현황 (누구나: 계산한 사실만, AI 판단·조치는 빼고)
        if u.path == "/api/gaps/cells": return self._json({"칸": gap_cells(q("id"))})   # 구역 색칠 (100m 칸)
        if u.path == "/api/gaps/dongs": return self._json(gap_dongs())   # 공백이 있는 행정동 경계
        if u.path == "/api/gov/brief": return self._json(dict(gov_brief(), 권한=gov_role(self)))
        if u.path == "/api/gov/status":   # 화면이 1분마다 묻는 가벼운 확인: 점검 중인지, 마지막 점검이 언제 시작됐는지 (새 점검이 끝나면 화면이 스스로 보고서를 다시 불러옴)
            G = GOV["agent"]; lr = gov_last_run()
            return self._json({"진행": bool(G and G.live), "점검시작": lr["시작"] if lr else None})
        if u.path == "/api/gov/chat/hello":
            try: return self._json(gov_chat().hello(q("gu") or None, gov_role(self)))
            except Exception as ex: print("[업무 보조 인사 오류]", repr(ex)[:200], flush=True); return self._json({"blocks": [{"text": "업무 보조를 지금 쓸 수 없음 · 잠시 후 다시 시도해 주십시오."}], "options": []})
        if u.path == "/api/gov/doc":   # 문서 (코드가 틀에 채움, 언어 모델 없음)
            got = gov_doc(q)
            if not got: self.send_error(404); return
            ct, b, fn = got
            self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
            if fn: self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(fn))
            self.end_headers(); self.wfile.write(b); return
        if u.path == "/api/did":   # 이 곳이 하는(하던) 일 — 주민 화면과 지자체 화면이 같은 함수(Engine.what_it_does)를 씀
            fid = q("fid")
            return self._json({"하던일": E.what_it_does(fid) if fid in E.F.index else [], "규모": E.scale(fid) if fid in E.F.index else None})
        if u.path == "/api/gov/area": return self._json(gov_area(q("fid")))
        if u.path == "/api/gov/facility":   # 폐업 사전 검토할 시설 찾기: 영업 중인 시설만 (이름으로)
            try: return self._json({"목록": find_open(q("q") or "")})
            except Exception as ex: print("[시설 찾기 오류]", repr(ex)[:200], flush=True); return self._json({"목록": [], "오류": "시설을 찾지 못했습니다. 잠시 뒤 다시 시도해 주세요."})
        if u.path == "/api/health": return self._json({"ok": True, "오늘사용": USE["n"], "한도": DAILY_LIMIT})
        path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        f = os.path.normpath(os.path.join(STATIC, path))
        if not f.startswith(STATIC) or not os.path.isfile(f): self.send_error(404); return
        ct = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}.get(os.path.splitext(f)[1], "application/octet-stream")
        b = open(f, "rb").read(); self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    # ── 스트리밍 (10/16): 에이전트가 하는 일과 답 글을 만들어지는 대로 보냄 (Server-Sent Events) ──
    def _sse_open(self):
        self.send_response(200); self.send_header("Content-Type", "text/event-stream; charset=utf-8"); self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no"); self.end_headers()
    def _sse(self, ev, data):
        try:
            self.wfile.write(f"event: {ev}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")); self.wfile.flush()
        except Exception: pass
    def _stream_start(self, d):
        gc()
        self._sse_open()
        if not ip_ok(self, "대화"): self._sse("done", {"type": "limit", "text": "오늘은 새 대화를 더 시작할 수 없어요. 내일 다시 이용해 주세요."}); return
        if not count_use(): self._sse("done", {"type": "limit", "text": "오늘 이용할 수 있는 횟수를 모두 썼어요. 내일 다시 이용해 주세요."}); return
        fid = d.get("fid"); first = (d.get("text") or "").strip()[:300]; named = pick = None
        _home = os.environ.get("GINEUNG_DEMO_HOME")   # 영상 시연 서버 전용 (10/24): 주민의 '지금 위치'를 이 곳으로 (예: 128.6947,35.956,공산동 백안마을). 실제 서버는 설정하지 않음
        if _home and not fid:
            try: _x, _y, _n = _home.split(",", 2); d = dict(d, 경도=float(_x), 위도=float(_y), 이름=_n, 종류="지금 위치")
            except Exception: pass
        if not fid and first:   # 입력창에 문 닫은 곳 이름을 쓰고 목록에서 고르지 않은 경우
            try: hits, sure = named_closed(first)
            except Exception as ex: print("[이름 찾기 오류]", repr(ex)[:200], flush=True); hits, sure = [], False
            if sure: named = hits[0]
            elif hits: pick = hits
        here_ = (float(d["경도"]), float(d["위도"])) if d.get("종류") == "지금 위치" and d.get("경도") is not None and d.get("위도") is not None else None
        if named:
            st = closed_session(named); out = None
            if here_: st["here"] = here_   # 지금 위치를 알아 둠 (찾는 곳은 문 닫은 곳 그대로. '내 위치에서'가 가는 길인지 내 주변인지는 대화 엔진이 말뜻으로 가림)
        elif fid and fid in E.F.index:
            r = E.F.loc[fid]
            st, out = CHAT.start(float(r["경도"]), float(r["위도"]), gu=r.get("구군"), closed_fid=fid, origin_name=str(r["상호"]), origin_closed=is_closed(r))
            if d.get("지금경도") is not None and d.get("지금위도") is not None: st["here"] = (float(d["지금경도"]), float(d["지금위도"]))   # 위치 사용을 이미 허용한 주민만 화면이 함께 보냄
        else:
            lon, lat = float(d.get("경도") or 128.5935), float(d.get("위도") or 35.8714)
            st, out = CHAT.start(lon, lat, gu=d.get("구군"), origin_name=d.get("이름") or None, origin_kind=d.get("종류") or None)
            if here_: st["here"] = here_
        sid = uuid.uuid4().hex; SESS[sid] = {"st": st, "t": time.time(), "lock": threading.Lock()}
        self._sse("session", {"sid": sid, "출발": {"경도": st["lon"], "위도": st["lat"], "이름": st.get("origin_name") or "출발", "닫음": bool(st.get("origin_closed"))}, "기준": CHAT._origin_label(st)})
        with SESS[sid]["lock"]:
            if pick: out = pick_closed_question(st, pick, first)
            elif first and not fid:   # 첫 화면 입력창에 쓴 말로 바로 대화 시작 (이름이 나온 문 닫은 곳이면 그 곳 기준)
                out = CHAT.reply(st, first, emit=self._sse)
                if named: out = with_closed_line(out, st)
            else: out = CHAT.begin(st, out, emit=self._sse)
        self._sse("done", dict(answer_payload(out, st), sid=sid))
    def _gov_chat(self, d):
        self._sse_open(); role = gov_role(self)
        text = str(d.get("text") or "").strip()[:400]
        if not text: self._sse("done", {"blocks": [{"text": "요청을 입력해 주십시오."}], "options": []}); return
        if not gov_chat_ok(role): self._sse("done", {"type": "limit", "blocks": [{"text": f"오늘 업무 보조 이용 한도({GCHAT_LIMIT.get(role, 30)}회) 도달 · 기본 화면은 계속 이용 가능"}], "options": []}); return
        for k in [k for k, v in GSESS.items() if time.time() - v["t"] > SESSION_TTL]: GSESS.pop(k, None)
        sid = d.get("sid") if d.get("sid") in GSESS else uuid.uuid4().hex
        s = GSESS.setdefault(sid, {"st": {"role": role}, "t": time.time(), "lock": threading.Lock()}); s["st"]["role"] = role
        sc = d.get("screen") if isinstance(d.get("screen"), dict) else {}
        ev = [e for e in (d.get("events") or []) if isinstance(e, dict)][:10]
        rp = demo_replay(text)   # 영상 시연 서버 전용 (10/25): 미리 확인한 실제 답을 그대로 (실제 서버는 이 설정이 없어 늘 새로 답함)
        if rp:
            for e_, x_ in rp.get("events") or []: self._sse(e_, x_)
            self._sse("done", dict(rp["done"], sid=sid)); return
        try:
            with s["lock"]: out = gov_chat().reply(s["st"], text, sc, ev, emit=self._sse)
        except Exception:
            import traceback; traceback.print_exc()
            out = {"blocks": [{"text": "답을 만들지 못함 · 잠시 후 다시 시도해 주십시오."}], "options": []}
        s["t"] = time.time(); out.pop("_meta", None); out.pop("도구", None)
        self._sse("done", dict(_clean(out), sid=sid))
    def _stream_turn(self, d):
        s = SESS.get(d.get("sid") or "")
        self._sse_open()
        if not s: self._sse("done", {"type": "expired", "text": "대화 시간이 지나 처음부터 다시 시작해 주세요."}); return
        text = str(d.get("text") or "").strip()[:300]
        if not text: self._sse("done", {"type": "answer", "text": "말씀을 입력해 주세요.", "blocks": [{"text": "말씀을 입력해 주세요."}]}); return
        s["n"] = s.get("n", 0) + 1
        if s["n"] > TURN_LIMIT: self._sse("done", {"type": "limit", "text": "한 대화에서 나눌 수 있는 말을 다 썼어요. 처음 화면에서 새로 시작해 주세요.", "blocks": [{"text": "한 대화에서 나눌 수 있는 말을 다 썼어요. 처음 화면에서 새로 시작해 주세요."}]}); return
        with s.setdefault("lock", threading.Lock()):
            st = s["st"]; among = st.pop("pick_closed", None)
            try:
                hits, sure = named_closed(text, st.get("closed_fid"), among=set(among)) if among else ([], False)
                if not hits: hits, sure = named_closed(text, st.get("closed_fid"))
            except Exception as ex: print("[이름 찾기 오류]", repr(ex)[:200], flush=True); hits, sure = [], False
            if sure:   # 대화 중에 다른 문 닫은 곳을 말함 → 그 곳 기준으로 바꾸고 지도도 옮김
                st = closed_session(hits[0], st); s["st"] = st
                self._sse("session", {"sid": d.get("sid"), "출발": {"경도": st["lon"], "위도": st["lat"], "이름": st.get("origin_name") or "출발", "닫음": bool(st.get("origin_closed"))}, "기준": CHAT._origin_label(st)})
                r = with_closed_line(CHAT.reply(st, text, emit=self._sse), st)
            elif hits and not among: r = pick_closed_question(st, hits, text)
            else: r = CHAT.reply(st, text, emit=self._sse)
        s["t"] = time.time()
        self._sse("done", answer_payload(r, s["st"]))

    def do_HEAD(self):   # (10/29) 링크 미리보기 수집기·점검 도구의 HEAD 요청: 화면 파일은 머리만 보냄 (501이 나던 것)
        u = urllib.parse.urlparse(self.path)
        path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        f = os.path.normpath(os.path.join(STATIC, path))
        if not f.startswith(STATIC) or not os.path.isfile(f): self.send_response(404 if not u.path.startswith("/api/") else 405); self.end_headers(); return
        ct = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}.get(os.path.splitext(f)[1], "application/octet-stream")
        self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(os.path.getsize(f))); self.end_headers()
    def do_POST(self):
        u = urllib.parse.urlparse(self.path); d = self._body()
        if u.path == "/api/gov/login":   # 접속 코드 확인 → 12시간 동안 쓰는 쿠키 (담당자 코드 / 심사용 보기 전용 코드)
            code = str(d.get("code") or "").strip().upper()
            tok, role = (GOV_TOKEN, "담당자") if secrets.compare_digest(code, GOV_CODE.upper()) else (GOV_VIEW_TOKEN, "심사") if secrets.compare_digest(code, GOV_VIEW_CODE.upper()) else (None, None)
            if not tok: time.sleep(1); return self._json({"ok": False, "글": "접속 코드가 맞지 않습니다."}, 403)
            b = json.dumps({"ok": True, "권한": role}, ensure_ascii=False).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
            self.send_header("Set-Cookie", f"gov={tok}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200"); self.end_headers(); self.wfile.write(b); return
        if u.path.startswith("/api/gov/") and not gov_ok(self): return self._json({"잠김": True, "글": "담당자 접속 코드를 입력해 주세요."}, 401)
        if u.path in GOV_WRITE and gov_role(self) == "심사":
            return self._json({"ok": False, "시작": False, "보기전용": True, "글": "심사용 접속 · 처리 내용 서버 미반영 (정식 운영 시 즉시 반영)"})
        if u.path == "/api/gov/run":   # '지금 다시 점검': 오늘 자료를 이미 다 받았으면 받지 않고 분석·보고서만 다시
            G = gov()
            if G.lock.locked(): return self._json({"시작": False, "글": "지금 살펴보는 중입니다"})
            threading.Thread(target=G.run, kwargs={"fetch": not gov_today_done() and not os.environ.get("GINEUNG_DEMO_NOW"), "llm": True}, daemon=True).start()   # 영상 시연 서버는 자료를 새로 받지 않음
            return self._json({"시작": True})
        if u.path == "/api/gov/confirm":   # 확인 요청에 담당자가 답함: 폐업 / 휴원·휴업(운영 중단, 재개 시 자동 복귀) / 운영 중
            fid = str(d.get("fid") or ""); G = gov()
            if not fid: return self._json({"ok": False}, 400)
            if G.lock.locked(): return self._json({"ok": False, "글": "지금 살펴보는 중입니다. 끝난 뒤 다시 눌러 주십시오"})
            if fid not in G.unsure(): return self._json({"ok": False, "글": "이미 반영된 곳입니다"})
            threading.Thread(target=G.resolve_and_refresh, args=(fid, bool(d.get("닫음"))), kwargs={"pause": d.get("상태") == "휴업"}, daemon=True).start()
            return self._json({"ok": True})
        if u.path == "/api/gov/field":   # 담당자 현장·신고 확인 (10/22): 확인 요청 목록 밖 시설 — 폐업·휴업으로 / 다시 영업 중으로
            fid = str(d.get("fid") or ""); st_ = str(d.get("상태") or ""); G = gov()
            if not fid or st_ not in ("폐업", "휴업", "운영"): return self._json({"ok": False, "글": "시설과 상태를 확인해 주십시오"}, 400)
            if G.lock.locked(): return self._json({"ok": False, "글": "지금 살펴보는 중입니다. 끝난 뒤 다시 눌러 주십시오"})
            dt = str(d.get("날짜") or "")[:10]
            if dt and dt > datetime.datetime.now(KST).date().isoformat(): return self._json({"ok": False, "글": "아직 오지 않은 날짜입니다. 실제로 문을 닫은 뒤 반영해 주십시오"})
            threading.Thread(target=G.field_and_refresh, args=(fid, st_, dt, str(d.get("메모") or "")), daemon=True).start()
            return self._json({"ok": True, "글": f"{'운영 중' if st_ == '운영' else st_} 반영 중 · 보고 화면에 곧 반영"})
        if u.path == "/api/gov/lesson":   # 담당자가 에이전트 판단을 바로잡음 → 원칙으로 배워 다시 판단
            text = str(d.get("내용") or "").strip()
            if len(text) < 5: return self._json({"ok": False, "글": "어떤 점이 맞지 않는지 조금 더 적어 주십시오"})
            G = gov()
            if G.lock.locked(): return self._json({"ok": False, "글": "지금 살펴보는 중입니다. 끝난 뒤 다시 보내 주십시오"})
            threading.Thread(target=G.learn, args=(text, str(d.get("fid") or "") or None), daemon=True).start()
            return self._json({"ok": True, "글": "보내 주신 의견을 반영해 다시 판단하고 있습니다"})
        if u.path == "/api/gov/alt":   # '대신할 곳 확인'에 담당자가 답함
            fid = str(d.get("fid") or ""); G = gov()
            if not fid: return self._json({"ok": False}, 400)
            G.decide_alt(fid, bool(d.get("있음")))
            threading.Thread(target=G.refresh_brief, daemon=True).start()
            return self._json({"ok": True})
        if u.path == "/api/bad":   # (10/26) 답이 이상해요: 주민이 동의한 경우만 질문과 답 한 쌍을 남김 (이름·위치·대화 번호 없음, 전화번호는 가림)
            s_ = SESS.get(d.get("sid") or "")
            if not s_ or d.get("동의") is not True: return self._json({"ok": False, "글": "동의하셔야 보낼 수 있어요."}, 400)
            s_["bad"] = s_.get("bad", 0) + 1
            if s_["bad"] > 5: return self._json({"ok": True, "글": "이미 여러 번 알려 주셨어요. 고마워요."})
            mask = lambda t: re.sub(r"\d{2,4}[-\s]?\d{3,4}[-\s]?\d{4}", "(전화번호)", str(t or ""))[:600]
            st_ = s_["st"]; leaf_ = E.leaf.get(st_.get("leaf") or "", {}).get("name")
            row = {"때": datetime.datetime.now(KST).isoformat(timespec="seconds"), "질문": mask(d.get("질문")), "답": mask(d.get("답")), "메모": mask(d.get("메모"))[:300], "찾던_기능": leaf_}
            os.makedirs(os.path.join(ROOT, "data", "feedback"), exist_ok=True)
            with open(os.path.join(ROOT, "data", "feedback", "bad_answers.jsonl"), "a", encoding="utf-8") as fh: fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            return self._json({"ok": True, "글": "알려 주셔서 고마워요. 살펴보고 더 나은 답을 드릴게요."})
        if u.path == "/api/use":   # 주민 이용 결과: 다녀옴 / 맞는 곳 없음 (대화 하나에 한 번, 개인 정보 없이 동네·기능만)
            s = SESS.get(d.get("sid") or ""); res = d.get("결과")
            if not s or res not in ("다녀옴", "맞는 곳 없음"): return self._json({"ok": False}, 400)
            st = s["st"]
            if not st.get("leaf"): return self._json({"ok": False, "글": "안내받은 곳이 없어요."}, 400)
            if st.get("use_sent"): return self._json({"ok": True, "글": "이미 알려 주셨어요."})
            st["use_sent"] = True
            import demand as DM
            leaf = E.leaf.get(st["leaf"]) or {}
            lon, lat = st.get("home") or (st.get("lon"), st.get("lat"))
            import gov_agent as GVA
            try: gu0, dong0 = DM.where(lon, lat)
            except Exception: gu0, dong0 = None, None
            life = GVA.life_gap(leaf.get("grade"), st["leaf"], st.get("kind"), dong0)   # (10/26) 생활 필수 기능만 구청에 알림 (카페·식당 등은 생활 공백이 아님)
            if life: DM.use_result(st["leaf"], leaf.get("name", st["leaf"]), st.get("kind"), lon, lat, res)
            gu_w = (gu0 or "구") + "청"
            return self._json({"ok": True, "글": "알려 주셔서 고마워요." + (f" 맞는 곳이 없었다고 {gu_w}에 전할게요." if res == "맞는 곳 없음" and life else "")})   # 10/25: 문장 다듬음
        if u.path == "/api/report":   # 주민 폐업 제보 → 확인 전까지 대안으로 권하지 않음. AI가 교차검증해 분명하면 바로 반영, 보류된 공공·복지·의료 시설 가운데 공백이 생기는 곳만 담당자에게 (engine/report_check.py)
            fid = str(d.get("fid") or "")
            if fid not in E.F.index: return self._json({"ok": False, "글": "찾을 수 없는 곳이에요"}, 400)
            if not ip_ok(self, "제보"): return self._json({"ok": False, "글": "오늘은 제보를 더 받을 수 없어요. 내일 다시 알려 주세요."})
            if REPORTS.get("day") != datetime.datetime.now(KST).date().isoformat(): REPORTS.clear(); REPORTS["day"] = datetime.datetime.now(KST).date().isoformat()
            REPORTS["n"] = REPORTS.get("n", 0) + 1
            if REPORTS["n"] > 50: return self._json({"ok": False, "글": "오늘은 제보를 더 받을 수 없어요. 내일 다시 알려 주세요."})
            from changes import keep_on_report
            try: keep = keep_on_report(gov().cm.row(fid))
            except Exception: keep = False
            threading.Thread(target=gov().report_and_refresh, args=(fid, str(d.get("내용") or "")), daemon=True).start()
            return self._json({"ok": True, "글": "제보가 접수됐어요. " + ("아직 영업 중으로 나오는 곳이라, 문을 닫은 게 확인되면 안내에서 뺄게요." if keep else "확인해서 반영할게요. 확인될 때까지 이곳은 안내하지 않아요.")})
        if u.path == "/api/gov/prereview":   # 폐업 사전 검토 (가정): 실제 보고·공개·학습에 반영하지 않음. 하루 30건까지 (언어 모델 비용)
            return self._json(pre_run(str(d.get("fid") or "")))
        if u.path == "/api/gov/chat":   # 업무 보조 대화 (10/21): 담당자와 에이전트가 말로 주고받음. 바꾸는 일은 확인 카드로만 (engine/gov_chat.py)
            return self._gov_chat(d)
        if u.path == "/api/gov/chat/flag":   # 담당자가 '정확하지 않음'으로 표시한 답 → 점검·학습 자료 (언어 모델 비용 없음)
            if gov_role(self) == "심사": return self._json({"ok": True, "글": "심사용 접속 · 기록하지 않음"})   # (10/29 헌준님) 심사용 접속은 이용 기록·요청을 일체 남기지 않음
            try:
                with open(os.path.join(ROOT, "data", "gov", "chat_flags.jsonl"), "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"때": datetime.datetime.now(KST).isoformat(timespec="seconds"), "권한": gov_role(self), "질문": str(d.get("질문") or "")[:300], "답": str(d.get("답") or "")[:600], "메모": str(d.get("메모") or "")[:300]}, ensure_ascii=False) + "\n")
            except Exception: pass
            return self._json({"ok": True, "글": "기록했습니다. 답 점검에 반영합니다."})
        if u.path == "/api/gov/feedback":   # 담당자가 AI 판단을 바로잡음 (선택): 보고 / 관찰 / 해당 없음 → 그 곳에 바로 반영하고 사례로 배움
            fid = str(d.get("fid") or ""); label = d.get("판단")
            if not fid or label not in ("보고", "관찰", "해당 없음", None): return self._json({"ok": False}, 400)
            r = gov().feedback(fid, label, note=str(d.get("메모") or "")[:200])
            threading.Thread(target=gov().refresh_brief, daemon=True).start()
            return self._json({"ok": True, **r, "글": {"보고": "보고 대상으로 올렸습니다.", "관찰": "관찰 대상으로 옮겼습니다.", "해당 없음": "해당 없음으로 옮겼습니다.", None: "AI 판단으로 되돌렸습니다."}[label]})
        if u.path == "/api/gov/mark":   # 담당자가 '처리함'으로 표시 (되돌리기 가능)
            fid = str(d.get("fid") or "")
            if not fid: return self._json({"ok": False}, 400)
            gov().mark(fid, bool(d.get("done", True)), note=str(d.get("메모") or "")[:200], acts=[str(x)[:40] for x in (d.get("한일") or [])][:8])
            return self._json({"ok": True, "처리": gov().handled.get(fid)})
        if u.path in ("/api/start_stream", "/api/turn_stream"):
            try: return self._stream_start(d) if u.path == "/api/start_stream" else self._stream_turn(d)
            except Exception:
                import traceback; traceback.print_exc()
                return self._sse("done", {"type": "error", "text": "답을 만드는 중에 문제가 생겼어요. 잠시 뒤 다시 해 주세요.", "blocks": [{"text": "답을 만드는 중에 문제가 생겼어요. 잠시 뒤 다시 해 주세요."}]})
        try:
            if u.path == "/api/start":
                gc()
                if not ip_ok(self, "대화"): return self._json({"type": "limit", "text": "오늘은 새 대화를 더 시작할 수 없어요. 내일 다시 이용해 주세요."}, 429)
                if not count_use(): return self._json({"type": "limit", "text": "오늘 이용할 수 있는 횟수를 모두 썼어요. 내일 다시 이용해 주세요."}, 429)
                fid = d.get("fid")
                if True:   # (10/26) 대화마다 따로 처리 (예전 전체 잠금은 한 사람이 답을 기다리는 동안 다른 사람도 기다리게 함)
                    if fid and fid in E.F.index:
                        r = E.F.loc[fid]
                        st, out = CHAT.start(float(r["경도"]), float(r["위도"]), gu=r.get("구군"), closed_fid=fid, origin_name=str(r["상호"]),
                                          origin_closed=is_closed(r))
                    else:
                        lon, lat = float(d.get("경도") or 128.5935), float(d.get("위도") or 35.8714)
                        st, out = CHAT.start(lon, lat, gu=d.get("구군"), origin_name=d.get("이름") or None, origin_kind=d.get("종류") or None)
                    out = CHAT.begin(st, out)
                sid = uuid.uuid4().hex; SESS[sid] = {"st": st, "t": time.time(), "lock": threading.Lock()}
                return self._json(dict(answer_payload(out, st), sid=sid))
            if u.path == "/api/origin":   # 거리 기준 위치 바꾸기
                s = SESS.get(d.get("sid") or "")
                if not s: return self._json({"type": "expired", "text": "대화 시간이 지나 처음부터 다시 시작해 주세요."}, 410)
                with s.setdefault("lock", threading.Lock()):   # 대화마다 따로 잠금
                    act = d.get("할일")   # 출발: 고른 곳 그대로 가는 길만 지금 위치에서 / 처음: 문 닫은 곳 근처로 / 그 밖: 찾는 곳을 지금 위치로
                    if act == "출발": r = CHAT.set_start(s["st"], float(d["경도"]), float(d["위도"]))
                    elif act == "처음": r = CHAT.set_center_home(s["st"])
                    else: r = CHAT.set_origin(s["st"], float(d["경도"]), float(d["위도"]), str(d.get("이름") or "지금 계신 곳")[:30], str(d.get("종류") or "지금 위치"))
                s["t"] = time.time()
                return self._json(answer_payload(r, s["st"]))
            if u.path == "/api/turn":
                s = SESS.get(d.get("sid") or "")
                if not s: return self._json({"type": "expired", "text": "대화 시간이 지나 처음부터 다시 시작해 주세요."}, 410)
                text = str(d.get("text") or "").strip()[:300]
                ans = d.get("answers") if isinstance(d.get("answers"), dict) else None   # 화면에서 고른 것 (이동·누구와·언제)
                if not text and ans is not None: text = " · ".join(str(v) for v in ans.values()) or "바로 보여 주세요"
                if not text: return self._json({"type": "question", "text": "말씀을 입력해 주세요.", "blocks": [{"text": "말씀을 입력해 주세요."}], "options": []})
                s["n"] = s.get("n", 0) + 1
                if s["n"] > TURN_LIMIT: return self._json({"type": "limit", "text": "한 대화에서 나눌 수 있는 말을 다 썼어요. 처음 화면에서 새로 시작해 주세요.", "blocks": [{"text": "한 대화에서 나눌 수 있는 말을 다 썼어요. 처음 화면에서 새로 시작해 주세요."}]}, 429)
                with s.setdefault("lock", threading.Lock()):
                    r = CHAT.reply(s["st"], text, answers=ans)
                s["t"] = time.time()
                return self._json(answer_payload(r, s["st"]))
        except Exception as e:
            import traceback; traceback.print_exc()
            return self._json({"type": "error", "text": "답을 만드는 중에 문제가 생겼어요. 잠시 뒤 다시 해 주세요.", "blocks": [{"text": "답을 만드는 중에 문제가 생겼어요. 잠시 뒤 다시 해 주세요."}]}, 500)
        self.send_error(404)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8000"))
    if os.environ.get("GINEUNG_GOV_AUTO", "1") != "0": threading.Thread(target=_gov_loop, daemon=True).start()   # 지자체 에이전트 날마다 점검
    print(f"http://localhost:{port}"); print(f"지자체 화면 접속 코드: {GOV_CODE}  (settings/gov_code.txt) · 심사용 보기 전용 코드: settings/gov_view_code.txt"); ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
