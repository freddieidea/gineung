# 자가 점검 (10/26 헌준님): 에이전트가 매일 아침 보고서를 만든 뒤 자기 결과를 스스로 확인하고, 고칠 수 있는 것은 바로 고침
#  사람이 하는 단계가 아님. 결과는 점검 내역(runs.jsonl)의 '자가 점검' 한 줄로 남음
#  점검 항목 (모두 오늘 실제로 나왔던 오류에서 나옴)
#   1) 숫자와 목록: 구·군마다 긴급·주의·관찰 숫자가 실제 목록 수와 같은지 ('관찰 1'인데 시설이 안 보이던 것)
#   2) 내부 용어: 화면에 나가는 글에 필수·준필수·등급·산책·쉼터 같은 내부 분류 낱말이 없는지 (창업 참고 근거의 '준필수 미용 기능')
#   3) 칸 겹침: 같은 시설이 보고와 보고 안 함에 함께 있거나, 공백 없는 폐쇄가 참고 '공공 체육시설·공원 공백'에 들어가지 않았는지
#   4) 담당자 판단: 담당자가 '해당 없음'으로 정한 곳이 관찰·창업 참고·기능 공백 구역에 남지 않았는지 (팔공산호텔컷트)
#   5) 창업 참고 원칙: 상권 적합도 '낮음'인 구역, 공원·공공 체육시설 구역에 창업 참고가 붙지 않았는지
#   6) 단절 우려: '영업 중' 시설만 있는지 (문을 닫은 곳이 남으면 뺌)
import os, json, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOV = os.path.join(ROOT, "data", "gov")
TERMS = [(re.compile(r"(생활\s*)?필수·준필수(\s*기능)?"), "생활에 꼭 필요한 기능"), (re.compile(r"준필수\s*"), ""), (re.compile(r"등급(이)?\s?필수"), "생활에 꼭 필요한"),
         (re.compile(r"산책·쉼터(\s*시설)?"), "공원")]
SKIP_KEYS = {"fid", "id", "기능id", "기능", "학습기준", "보고기준", "판단모델"}   # 내부 식별자·기준표는 고치지 않음 (기준표는 화면이 따로 풀어 씀)

def _clean(x, fixed, key=None):
    if isinstance(x, str):
        if key in SKIP_KEYS: return x
        y = x
        for rx, to in TERMS: y = rx.sub(to, y)
        if y != x: fixed.append(x[:40]); y = re.sub(r"\s{2,}", " ", y).strip()
        return y
    if isinstance(x, list): return [_clean(v, fixed, key) for v in x]
    if isinstance(x, dict): return {k: _clean(v, fixed, k) for k, v in x.items()}
    return x

def run(G=None, path=None):
    p = path or os.path.join(GOV, "brief_latest.json")
    b = json.load(open(p, encoding="utf-8"))
    out = {"숫자": 0, "용어": 0, "겹침": 0, "담당자 판단": 0, "창업 참고": 0, "단절 우려": 0}
    try:
        import gap_agent as GA
        none_fids = {f for f, o in GA.overrides().items() if o.get("판단") == "해당 없음"}
    except Exception: none_fids = set()
    for gu, v in (b.get("구군") or {}).items():
        items = v.get("항목", []); quiet = v.get("보고안함", [])
        rep = {r["fid"] for r in items}
        n0 = len(quiet); v["보고안함"] = quiet = [r for r in quiet if r["fid"] not in rep]; out["겹침"] += n0 - len(quiet)   # 3) 보고와 보고 안 함에 함께 있으면 보고만
        for r in quiet:
            if r["fid"] in none_fids and r.get("관찰"): r["관찰"] = False; r["구분"] = r.get("구분") or "공백 없음"; out["담당자 판단"] += 1   # 4)
        want = {"긴급": sum(1 for r in items if r.get("등급") == "긴급"), "주의": sum(1 for r in items if r.get("등급") != "긴급"), "관찰": sum(1 for r in quiet if r.get("관찰"))}
        for k, n in want.items():   # 1)
            if v.get(k) != n: v[k] = n; out["숫자"] += 1
    n0 = len(b.get("체육공원") or [])
    b["체육공원"] = [r for r in (b.get("체육공원") or []) if r.get("판정") in ("긴급", "주의", "관찰") and r["fid"] not in none_fids]; out["겹침"] += n0 - len(b["체육공원"])   # 3)
    n0 = len(b.get("창업참고") or [])
    b["창업참고"] = [r for r in (b.get("창업참고") or []) if r["fid"] not in none_fids]; out["담당자 판단"] += n0 - len(b["창업참고"])   # 4)
    zones = []
    for z in b.get("기능공백구역") or []:
        if any(f in str(z.get("id")) for f in none_fids): out["담당자 판단"] += 1; continue   # 4)
        if z.get("창업참고") and (z.get("적합") or {}).get("적합도") == "낮음": z["창업참고"] = None; out["창업 참고"] += 1   # 5)
        if z.get("창업참고") and (z.get("시설") in ("공원", "공공 체육시설") or z.get("공공시설")): z["창업참고"] = None; out["창업 참고"] += 1   # 5) 공원·공공 체육시설은 창업 대상이 아님 (10/29)
        zones.append(z)
    b["기능공백구역"] = zones
    if G is not None and b.get("하나남은곳"):   # 6) 단절 우려는 영업 중인 곳만
        try:
            F = G.cm.engine().F; n0 = len(b["하나남은곳"])
            b["하나남은곳"] = [r for r in b["하나남은곳"] if r.get("fid") in F.index and F.at[r["fid"], "대안후보"] == "예"]; out["단절 우려"] += n0 - len(b["하나남은곳"])
        except Exception: pass
    fixed = []; b = _clean(b, fixed); out["용어"] = len(fixed)   # 2)
    if sum(out.values()):
        tmp = p + ".tmp"; json.dump(b, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, p)
        d = os.path.join(GOV, f"brief_{b.get('날짜')}.json")
        if b.get("날짜") and os.path.exists(d) and os.path.abspath(d) != os.path.abspath(p): json.dump(b, open(d, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out["점검"] = 6
    return out

def say(r):
    got = [f"{k} {v}건" for k, v in r.items() if k != "점검" and v]
    return "보고서를 스스로 점검했습니다 · 바로잡을 곳 없음" if not got else "보고서를 스스로 점검해 바로잡았습니다 (" + ", ".join(got) + ")"
