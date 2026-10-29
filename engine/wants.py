# 주민이 바라는 가게의 성격 (헌준님 10/19: 카페·술집만이 아니라 모든 가게에서 '어떤 곳을 바라는지'를 AI가 스스로 판단)
#  예: '디저트가 많은 카페', '남자 커트만 하는 싼 미용실', '24시간 헬스장', '코인노래방', '아이 놀이방 있는 식당', '운동화 빨래', '조용한 이자카야'
#  흐름
#   1) 대화 모델이 주민 말에서 바람을 짧게 뽑음 (find_places의 want)
#   2) 가까운 후보 40곳의 이름·업종·세부 종류(공공 자료)를 작은 모델(Haiku)에게 보여 주고 '맞음 / 모름 / 안 맞음'을 판단하게 함
#      이름만으로 알 수 있는 것만 판단 (브랜드·가게 이름에 드러난 것). 확실하지 않으면 '모름' → 지어내지 않음
#      같은 판단으로, 나머지 후보와 카카오맵 분류에 쓸 낱말(좋은 말·피할 말)도 받음
#   3) '모름'인 앞쪽 후보는 카카오맵 분류를 그 자리에서 받아 2)의 낱말과 코드로만 대조 (카카오 결과는 모델에 보내지 않고 저장하지 않음)
#   4) '안 맞음'은 빼고, '맞음'을 순위 앞에. 맞는 곳이 하나도 없으면 빼지 않고 그렇다고 알려 드림
#  가게 하나하나의 실제 메뉴·시설은 우리가 모름. 그래서 '맞음'은 이름·분류에 드러난 경우만이고, 모르는 것은 전화로 확인하시라고 안내함
import json, re, os, threading
GOOD, OK, BAD = 2, 1, 0
MODEL = "claude-haiku-5-5"
_cache = {}; _lock = threading.Lock()   # (바람, fid) → 판단 / 바람 → 낱말 (서버가 켜져 있는 동안만, 저장하지 않음)

TOOL = {"name": "judge_fit", "description": "후보 가게마다 주민의 바람에 맞는지 판단",
        "input_schema": {"type": "object", "required": ["label", "verdicts", "name_good", "name_bad", "category_good", "category_bad"], "properties": {
            "label": {"type": "string", "description": "카드에 붙일 짧은 이름: 바람의 특징만 (가게 종류 이름은 빼고, 8자 안, 예: '디저트', '남성 커트', '24시간', '코인', '단체석', '공부하기 좋음')"},
            "verdicts": {"type": "array", "items": {"type": "object", "required": ["i", "fit"], "properties": {
                "i": {"type": "integer"}, "fit": {"type": "string", "enum": ["맞음", "모름", "안 맞음"]}}}},
            "name_good": {"type": "array", "items": {"type": "string"}, "description": "가게 이름에 들어 있으면 바람에 맞는 낱말·브랜드 (2자 이상, 10개 안)"},
            "name_bad": {"type": "array", "items": {"type": "string"}, "description": "가게 이름에 들어 있으면 바람과 분명히 맞지 않는 낱말·브랜드 (10개 안)"},
            "category_good": {"type": "array", "items": {"type": "string"}, "description": "카카오맵 장소 분류(예: '디저트카페', '코인노래방', '바버샵', '이자카야')에 들어 있으면 맞는 낱말 (8개 안)"},
            "category_bad": {"type": "array", "items": {"type": "string"}, "description": "카카오맵 분류에 들어 있으면 맞지 않는 낱말 (8개 안)"}}}}

SYS = """당신은 대구 생활시설 안내 서비스의 판단 담당입니다. 주민이 바라는 가게의 성격과 후보 가게 목록(이름·업종·세부 종류)을 받습니다.
가게마다 바람에 맞는지 판단합니다.
- 맞음: 가게 이름·브랜드·업종만으로 바람에 맞는 것이 분명함 (예: '디저트가 많은 카페'에 '○○케이크', '투썸플레이스' / '남자 커트 싼 곳'에 '블루클럽', '○○바버샵' / '코인노래방'에 '○○코인노래연습장')
- 안 맞음: 이름·브랜드로 보아 바람과 분명히 다름 (예: '디저트가 많은 카페'에 '빽다방'(저가 테이크아웃 커피) / '2차 술자리'에 '명륜진사갈비'(고기 무한리필 식당) / '조용한 곳'에 '○○감성주점'·'헌팅포차')
- 널리 알려진 브랜드의 대표 상품·서비스는 알고 있는 대로 판단합니다 (예: 파리바게뜨·뚜레쥬르는 케이크를 팖, 크린토피아는 운동화 세탁을 받음, 스포애니·애니타임피트니스는 24시간, 커브스는 여성 전용, 블루클럽은 남성 커트 전문).
- 바람에 가게 종류가 들어 있으면(예: '단체석 있는 고깃집', '조용한 이자카야', '혼술하기 좋은 바', '와인바') 업종·이름이 그 종류와 다른 가게는 안 맞음입니다 (예: '고깃집'인데 솥밥집·국밥집, '바'인데 초밥집·닭갈비집).
- 이름에 바람과 반대되는 성격이 드러나면 안 맞음입니다 (예: '룸 있는 노래방'에 '○○코인노래연습장'(칸막이 부스)·'○○오락실', '조용한 곳'에 '○○헌팅포차', '남자 커트'에 '○○네일').
- 이름에 바람이 그대로 드러나면 맞음입니다 (예: '공부하기 좋은 카페'에 '○○북카페'·'○○스터디카페', '애견 동반'에 '○○애견카페'·'○○펫카페').
- 모름: 이름만으로는 알 수 없음. 확실하지 않으면 반드시 모름. 이름에 없는 시설·메뉴를 짐작하지 않습니다.
- 이름 일부가 우연히 같은 글자는 맞음이 아닙니다 (예: '아이 커트'에 '아이비헤어'(Ivy)·'아이린헤어', '코인노래방'에 '코인세탁'). 이름 전체의 뜻으로 판단합니다. name_good에도 '아이'처럼 다른 말 속에 흔히 들어가는 짧은 낱말은 넣지 않습니다(예: '키즈', '어린이'처럼 분명한 말만).
바람이 그 가게들의 일과 상관없는 조건(주차, 엘리베이터, 가격처럼 이름으로 알 수 없는 것)이면 모두 모름으로 둡니다.
낱말 목록은 이 목록 밖의 다른 가게 이름과 카카오맵 장소 분류를 코드로 가를 때 씁니다. 너무 넓은 낱말(예: '카페', '커피', '식당')은 넣지 않습니다.
결과는 judge_fit 도구로만 냅니다."""

def _norm(s): return re.sub(r"[\s()（）\[\]·.,-]", "", str(s or ""))

def judge(client, want, job, cands, log_usage=None):
    """cands: [{'fid','상호','업종','세부종류'}] → ({fid: 단계}, 낱말 dict). 이미 판단한 가게는 다시 묻지 않음"""
    key = want.strip()
    out = {}; ask = []
    with _lock:
        spec = _cache.get(("spec", key))
        for c in cands:
            v = _cache.get((key, c["fid"]))
            if v is None: ask.append(c)
            else: out[c["fid"]] = v
    if ask or spec is None:
        rows = [f"{i}. {c['상호']} | {c.get('업종') or ''}" + (f" | {c['세부종류']}" if c.get("세부종류") else "") for i, c in enumerate(ask)]
        msg = f"주민의 바람: {want}\n찾는 일: {job}\n후보:\n" + ("\n".join(rows) if rows else "(새 후보 없음, 낱말만)")
        res = None
        for _ in range(2):
            r = client.messages.create(model=MODEL, max_tokens=4000, system=SYS + "\n결과는 반드시 judge_fit 도구로.", tools=[TOOL], messages=[{"role": "user", "content": msg}])
            if log_usage:
                try: log_usage(MODEL, r.usage, "바람 판단")
                except Exception: pass
            res = next((b.input for b in r.content if b.type == "tool_use"), None)
            if res and r.stop_reason == "max_tokens": res = None   # 답이 잘리면 다시
            if res: break
        if res:
            lv = {"맞음": GOOD, "모름": OK, "안 맞음": BAD}
            got = {int(v["i"]): lv.get(v.get("fit"), OK) for v in res.get("verdicts", []) if isinstance(v, dict) and str(v.get("i", "")).lstrip("-").isdigit()}
            clean = lambda xs, n: [str(x).strip() for x in (xs or []) if 2 <= len(str(x).strip()) <= 20][:n]
            spec = {"label": str(res.get("label") or want)[:10], "name_good": clean(res.get("name_good"), 10), "name_bad": clean(res.get("name_bad"), 10),
                    "category_good": clean(res.get("category_good"), 8), "category_bad": clean(res.get("category_bad"), 8)}
            with _lock:
                _cache[("spec", key)] = spec
                for i, c in enumerate(ask):
                    t = got.get(i, OK); out[c["fid"]] = t; _cache[(key, c["fid"])] = t
                if len(_cache) > 20000: _cache.clear()
        else:
            spec = spec or {"label": want[:10], "name_good": [], "name_bad": [], "category_good": [], "category_bad": []}
            for c in ask: out[c["fid"]] = OK
    return out, spec

def by_words(spec, name="", category=""):
    """판단하지 않은 가게: 이름·카카오맵 분류에 든 낱말로 (분류는 코드에서만 씀)"""
    n = _norm(name); c = _norm(category)
    bad = any(_norm(w) and _norm(w) in n for w in spec.get("name_bad", [])) or (c and any(_norm(w) and _norm(w) in c for w in spec.get("category_bad", [])))
    if bad: return BAD
    good = any(_norm(w) and _norm(w) in n for w in spec.get("name_good", [])) or (c and any(_norm(w) and _norm(w) in c for w in spec.get("category_good", [])))
    return GOOD if good else OK
