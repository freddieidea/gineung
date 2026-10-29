# 5차 점검 ② 채점: 대화를 만든 쪽과 따로, 결과만 읽고 판정 (Sonnet). 사용: python engine/grade5.py [폴더] [동시 개수]
import sys, os, json, glob, time
from concurrent.futures import ThreadPoolExecutor
import anthropic
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine")); sys.path.insert(0, os.path.join(ROOT, "pipeline"))
client = anthropic.Anthropic(api_key=open(os.path.join(ROOT, "settings", "anthropic_key.txt"), encoding="utf-8").read().strip())
LEAF = {}
for c in json.load(open(os.path.join(ROOT, "design", "purpose_taxonomy.json"), encoding="utf-8"))["categories"]:
    for p in c["purposes"]:
        for l in p["leaves"]: LEAF[l["id"]] = l["name"]
D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "check5", "run")
OUT = D.rstrip("/") + "_grade"; os.makedirs(OUT, exist_ok=True)
W = int(sys.argv[2]) if len(sys.argv) > 2 else 8
SYS = """당신은 대구시 생활시설 안내 서비스의 대화 품질 심사원입니다. 주민(특히 어르신)과 안내 AI의 대화 기록을 읽고 엄격하고 공정하게 채점합니다.
서비스의 원칙: 문 닫은 곳 대신 갈 곳을 찾아 줌. 카드(시설 이름·거리)는 검증된 데이터베이스에서 나오므로 카드 자체의 존재는 믿어도 됨.
좋은 대화: 사람처럼 자연스럽고 따뜻함, 맥락을 잘 알아들음, 먼저 돕고 꼭 필요할 때만 짧게 물음, 모르는 것은 솔직히 말함, 필요한 안내(자격·생활 서비스·위급 연락처)를 빠뜨리지 않음, 번역투 없음.
나쁜 대화의 예: 주민의 목적과 다른 곳 추천, 비슷한 종류인데 굳이 되묻기(예: 이발소·미용실을 묻기), 문 닫은 곳을 눌렀는데 추천 없이 되묻기만, 정보를 지어냄, 위급한데 119·112·상담전화를 바로 안내하지 않음, 딱딱하거나 장황함.
판정 '실패'는 주민이 실제로 불편하거나 잘못 안내받는 경우에만 줍니다. 사소한 말투 아쉬움은 '통과'에 문제 목록으로만 남깁니다."""
TOOL = {"name": "grade", "description": "채점 결과", "input_schema": {"type": "object", "required": ["understood", "fit", "natural", "problems", "verdict", "reason"], "properties": {
    "understood": {"type": "string", "enum": ["맞음", "틀림", "애매"], "description": "주민이 원하는 것을 맞게 알아들었나"},
    "fit": {"type": "string", "enum": ["맞음", "틀림", "해당없음"], "description": "보여 준 곳(카드)이 목적에 맞나. 카드가 없으면 해당없음"},
    "natural": {"type": "integer", "minimum": 1, "maximum": 5, "description": "사람처럼 자연스러운 정도"},
    "problems": {"type": "array", "items": {"type": "string", "enum": ["엉뚱한 추천", "지어냄", "불필요한 되묻기", "추천 없이 되묻기만", "맥락 놓침", "안내 누락", "위급 대응 미흡", "번역투·딱딱함", "장황함", "같은 말 반복", "기타"]}},
    "verdict": {"type": "string", "enum": ["통과", "실패"]}, "reason": {"type": "string", "description": "한두 문장"}}}}
def text(r):
    L = [f"[시험 유형] {r['유형']}", f"[시작] {r.get('시작')}", f"[채점 참고] {r.get('참고') or '없음'}",
         "[맞는 목적 예시] " + (", ".join(LEAF.get(x, x) for x in r["맞는기능"]) if r.get("맞는기능") else "정해진 시설 목적 없음 (묻거나 안내하는 것이 맞을 수 있음)"), "", "[대화]"]
    for t in r["마디"]:
        L.append(f"주민: {t['주민']}")
        for b in t["블록"]:
            k, v = list(b.items())[0]
            L.append(("안내: " if k == "말" else f"  ({k}) ") + (v if isinstance(v, str) else ", ".join(v)))
        if t["버튼"]: L.append("  (빠른 답 버튼) " + " / ".join(t["버튼"]))
        if t.get("전화연결"): L.append("  (화면에 전화 걸기 버튼 있음)")
    return "\n".join(L)
def grade(f):
    o = os.path.join(OUT, os.path.basename(f))
    if os.path.exists(o):
        g0 = json.load(open(o))
        if g0.get("verdict") in ("통과", "실패"): return g0   # 채점이 안 된 것만 다시
    r = json.load(open(f))
    for _ in range(2):
        res = client.messages.create(model="claude-sonnet-5-5", max_tokens=600, system=SYS, tools=[TOOL],
                                     messages=[{"role": "user", "content": text(r) + "\n\n반드시 grade 도구로만 답하세요."}])
        g = next((b.input for b in res.content if getattr(b, "type", "") == "tool_use"), None)
        if g and g.get("verdict") in ("통과", "실패"): break
    g = dict(g or {"verdict": "채점 실패"}, 번호=r["번호"], 유형=r["유형"])
    json.dump(g, open(o, "w", encoding="utf-8"), ensure_ascii=False, indent=1); return g
fs = sorted(glob.glob(os.path.join(D, "*.json"))); t0 = time.time(); done = []
with ThreadPoolExecutor(W) as ex:
    for k in range(0, len(fs), W * 2):
        if time.time() - t0 > 120: print("시간 다 됨, 다음에 이어서"); break
        done += list(ex.map(grade, fs[k:k + W * 2]))
print("채점", len(done), "/", len(fs))
