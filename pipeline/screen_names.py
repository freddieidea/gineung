"""상호 전수 점검 (2026-10-14 저녁): 추천 후보가 되는 상가·인허가 가게 전부(약 9만 6천 곳)의 상호를 업종별로 모델에게 보여 주고,
등록 업종과 분명히 다른 일을 하는 가게를 찾는다. 표본 점검(독립 점검 1~3차)은 3%만 보므로, 표본 밖의 업종 오류까지 찾기 위한 전수 점검.
  1단계(Sonnet): 업종별 상호 목록에서 어긋난 가게 후보를 넓게 찾음
  2단계(Opus): 1단계 후보만 다시 확인해 '확실히 다른 일을 하는 가게'만 남김 → build_facilities.py가 '업종 확인 필요'로 표시 (추천하지 않음)
사용: python pipeline/screen_names.py 1 [동시 요청 수] [시간 제한 초]   /   python pipeline/screen_names.py 2 ...   /   python pipeline/screen_names.py 정리
결과: data/work/name_screen/s1_*.json, s2_*.json → data/work/name_screen_flags.csv (fid, 상호, 업종, 실제, 이유)"""
import json, sys, os, time, glob, re, concurrent.futures as cf
import pandas as pd
OUT = "data/work/name_screen"; os.makedirs(OUT, exist_ok=True)
STAGE = sys.argv[1]; WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 6; BUDGET = float(sys.argv[3]) if len(sys.argv) > 3 else 150
T0 = time.time(); CH = 300
F = pd.read_csv("data/processed/facilities.csv", dtype=str).fillna("")
P = F[(F["대안후보"] == "예") & F["출처"].isin(["상가", "인허가"])].sort_values(["업종", "fid"])
M = json.load(open("data/processed/industry_function_map.json", encoding="utf-8"))
L = {x["code"]: x for x in json.load(open("data/processed/industry_list.json", encoding="utf-8"))}
T = json.load(open("design/purpose_taxonomy.json", encoding="utf-8"))
LEAF = {}
def walk(x):
    if isinstance(x, dict):
        if str(x.get("id", "")).startswith("P") and "name" in x and "desc" in x: LEAF[x["id"]] = f'{x["name"]}({x["desc"]})'
        for v in x.values(): walk(v)
    elif isinstance(x, list):
        for v in x: walk(v)
walk(T)
PURP = {L[it["code"]]["소분류"]: [LEAF.get(f["id"], f["id"]) for f in it["functions"]] for it in M["items"] if it["code"] in L}
def client():
    import anthropic
    return anthropic.Anthropic(api_key=open("settings/anthropic_key.txt", encoding="utf-8").read().strip())
def ask(c, model, system, content, max_tokens):
    for k in range(4):
        try:
            r = c.messages.create(model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": content}])
            t = "".join(getattr(b, "text", "") for b in r.content).strip()
            if t.startswith("```"): t = t.split("\n", 1)[1].rsplit("```", 1)[0]
            i, j = t.find("["), t.rfind("]")
            return json.loads(t[i:j + 1]) if i >= 0 else [], (r.usage.input_tokens, r.usage.output_tokens)
        except Exception as e:
            if k == 3: raise
            time.sleep(5 * (k + 1))
S1 = """당신은 대구시 생활시설 자료를 점검하는 공무원입니다. 아래는 소상공인 상가 자료(또는 인허가 자료)에서 같은 업종으로 등록된 가게들의 상호 목록입니다.
상가 자료의 업종은 틀린 경우가 있습니다. 이 업종의 가게는 주민에게 '안내 목적'에 적힌 일로 안내됩니다.
상호를 보고, 등록된 업종과 '분명히 다른 일'을 하는 가게만 골라 주세요. 상호는 띄어쓰기를 그대로 읽으세요 (띄어쓰기 뒤는 보통 지점명).
골라야 하는 것 (상호만으로 분명한 것만):
- 상호가 다른 업종을 분명히 가리킴 (예: 업종 '채소/과일 소매업'인데 '수제담배', 업종 '테니스장'인데 '발레스튜디오', 업종 '악기 소매업'인데 '스피커음향', 업종 '자동차 정비소'인데 '세차장')
- 주민이 찾아가 이용하는 가게가 아님 (회사 사무실·본사·공장·물류센터·도매 유통 회사·건설 회사·협회·단체·연구소)
- 안내 목적으로 보면 그 일을 하지 않는 곳이 분명함 (예: '의료용품 구입' 목적인데 안마의자·온열 침대 매장)
고르지 말 것:
- 상호만으로 알 수 없는 것 (사람 이름, 지명, 뜻이 넓은 낱말: '행복', '대성', '그린', '하늘' 등)
- 그 업종에서 흔한 겸업이나 가까운 일 (예: 카페의 '베이커리카페', 정육점의 '식육식당', 슈퍼마켓의 '식자재마트')
- 지명·건물명이 들어간 지점명 (예: '유통단지점', '공단점', '과학관점')
출력: JSON 배열만. [{"n": 번호, "실제": "상호가 가리키는 업종(짧게)", "이유": "한 문장"}]. 없으면 []."""
S2 = """당신은 생활시설 자료를 최종 확인하는 공무원입니다. 아래 가게들은 '상호가 등록 업종과 다른 일을 가리킨다'고 1차 점검에서 지적된 곳입니다.
각 가게를 다시 보고, 상호만으로 '확실히' 등록 업종과 다른 일을 하는 곳(또는 주민이 찾아가는 가게가 아닌 곳)이면 "맞음", 상호만으로는 단정할 수 없거나
그 업종에서 흔한 겸업·가까운 일이면 "아님"으로 판정하세요. 띄어쓰기를 그대로 읽으세요. 애매하면 "아님"입니다. 틀린 '맞음'은 멀쩡한 가게를 주민 안내에서 빼므로 신중하게.
출력: JSON 배열만. [{"n": 번호, "판정": "맞음|아님", "이유": "한 문장"}] — 모든 번호에 대해."""
def chunks1():
    out = []
    for u, g in P.groupby("업종"):
        rows = list(zip(g["fid"], g["상호"]))
        for k in range(0, len(rows), CH): out.append((u, k // CH, rows[k:k + CH]))
    return out
def key(u, k): return re.sub(r"[^\w가-힣]", "_", u) + f"_{k:03d}"
def run1(c, u, k, rows):
    content = json.dumps({"업종": u, "안내 목적": PURP.get(u, []), "가게": [[i + 1, n] for i, (_, n) in enumerate(rows)]}, ensure_ascii=False)
    res, use = ask(c, "claude-sonnet-5-5", S1, content, 6000)
    flags = [{"fid": rows[x["n"] - 1][0], "상호": rows[x["n"] - 1][1], "업종": u, "실제": x.get("실제", ""), "이유": x.get("이유", "")} for x in res if isinstance(x, dict) and 1 <= int(x.get("n", 0)) <= len(rows)]
    json.dump({"업종": u, "k": k, "n": len(rows), "flags": flags, "usage": use}, open(f"{OUT}/s1_{key(u, k)}.json", "w", encoding="utf-8"), ensure_ascii=False)
    return len(flags)
def run2(c, u, k, items):
    content = json.dumps({"업종": u, "안내 목적": PURP.get(u, []), "가게": [[i + 1, x["상호"], x["실제"], x["이유"]] for i, x in enumerate(items)],
                          "열 설명": "[번호, 상호, 1차 점검이 본 실제 업종, 1차 이유]"}, ensure_ascii=False)
    res, use = ask(c, "claude-opus-5-5", S2, content, 8000)
    got = {int(x["n"]): x for x in res if isinstance(x, dict) and str(x.get("n", "")).isdigit()}
    out = [dict(x, 판정=got.get(i + 1, {}).get("판정", "아님"), 확인이유=got.get(i + 1, {}).get("이유", "")) for i, x in enumerate(items)]
    json.dump({"업종": u, "k": k, "items": out, "usage": use}, open(f"{OUT}/s2_{key(u, k)}.json", "w", encoding="utf-8"), ensure_ascii=False)
    return sum(x["판정"] == "맞음" for x in out)
if STAGE in ("1", "2"):
    if STAGE == "1": todo = [(u, k, r) for u, k, r in chunks1() if not os.path.exists(f"{OUT}/s1_{key(u, k)}.json")]
    else:
        fl = {}
        for p in sorted(glob.glob(f"{OUT}/s1_*.json")):
            d = json.load(open(p, encoding="utf-8"))
            for x in d["flags"]: fl.setdefault(x["업종"], []).append(x)
        todo = [(u, k // 60, xs[k:k + 60]) for u, xs in fl.items() for k in range(0, len(xs), 60)]
        todo = [t for t in todo if not os.path.exists(f"{OUT}/s2_{key(t[0], t[1])}.json")]
    print("남은 묶음", len(todo)); c = client(); done = 0
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        futs = {}
        it = iter(todo)
        def submit():
            if time.time() - T0 > BUDGET: return False
            try: u, k, r = next(it)
            except StopIteration: return False
            futs[ex.submit(run1 if STAGE == "1" else run2, c, u, k, r)] = (u, k); return True
        for _ in range(WORKERS): submit()
        while futs:
            d, _ = cf.wait(list(futs), return_when=cf.FIRST_COMPLETED)
            for f in d:
                u, k = futs.pop(f)
                try: print(u, k, "→", f.result()); done += 1
                except Exception as e: print(u, k, "오류", str(e)[:120])
                submit()
    print("이번에 끝낸 묶음", done, "걸린 시간", round(time.time() - T0))
else:   # 정리
    rows = []; use = [0, 0, 0, 0]; n1 = 0
    for p in glob.glob(f"{OUT}/s1_*.json"):
        d = json.load(open(p, encoding="utf-8")); use[0] += d["usage"][0]; use[1] += d["usage"][1]; n1 += len(d["flags"])
    for p in glob.glob(f"{OUT}/s2_*.json"):
        d = json.load(open(p, encoding="utf-8")); use[2] += d["usage"][0]; use[3] += d["usage"][1]
        rows += [x for x in d["items"] if x["판정"] == "맞음"]
    pd.DataFrame(rows, columns=["fid", "상호", "업종", "실제", "이유", "판정", "확인이유"]).to_csv("data/work/name_screen_flags.csv", index=False, encoding="utf-8")
    print("1단계 묶음", len(glob.glob(f"{OUT}/s1_*.json")), "후보", n1, "/ 2단계 확정", len(rows), "/ 토큰(1단계 입력·출력, 2단계 입력·출력)", use)
