"""실제 추천될 시설 독립 점검 (2026-10-14): 세부 종류마다 엔진이 '추천'으로 내보낼 시설을 무작위로 뽑아,
판정을 만든 쪽과 다른 모델(Opus)이 '이 목적의 주민에게 이곳을 안내하면 맞는가'를 시설 하나하나 봄.
사용: python pipeline/verify_members.py 시작 개수 [결과 폴더]   (기본 결과 폴더: data/work/members_verify, 다시 점검할 때는 members_verify2 등)"""
import json, sys, random, os
sys.path.insert(0, "engine"); from recommend import Engine
import anthropic
START, COUNT = int(sys.argv[1]), int(sys.argv[2]); PER = 8
OUT = sys.argv[3] if len(sys.argv) > 3 else "data/work/members_verify"
KAKAO = "--kakao" in sys.argv
if KAKAO:
    from live_check import LiveCheck; LC = LiveCheck()
E = Engine()
client = anthropic.Anthropic(api_key=open("settings/anthropic_key.txt", encoding="utf-8").read().strip())
units = []   # (기능, 종류, 의도)
for lid, l in sorted(E.leaf.items()):
    ks = l.get("kinds") or {}
    if ks.get("sensitive"):
        for g in ks["groups"]:
            for x in g["kinds"]:
                needs = E.need_choices(lid, x["name"]) or [None]
                for nd in needs: units.append((lid, x["name"], nd))
    elif ks.get("sensitive") is False: units.append((lid, None, None))
units = units[START:START + COUNT]
payload = []
for lid, k, nd in units:
    l = E.leaf[lid]
    if k: pool = E.kind[(lid, k)]["fids"]
    else:
        codes = {c for c, fs in E.func.items() if any(f["id"] == lid for f in fs)}
        pool = set(E.F.index[E.F["업종코드"].isin(codes)])
        for t in [c for c in codes if c.startswith("PERMIT:")]: pool |= set(E.F.index[E._members(lid, t, True)])
    rec = [f for f in sorted(pool) if E.F.loc[f, "대안후보"] == "예" and E.judge(f, lid, k, nd)[0] in ("근거", "강함")]
    random.seed(hash((lid, k, nd)) % 10**6)
    if KAKAO:   # 5차(10/15): 주민에게 실제로 보일 곳만 — 상가·인허가 가게는 카카오맵에서 지금 찾히는 곳만 표본으로 (결과는 저장하지 않음)
        order = random.sample(rec, len(rec)); pick = []
        for f in order:
            if len(pick) >= PER: break
            r = E.F.loc[f]
            if LC.needed(r):
                v = LC.check(r["상호"], float(r["경도"]), float(r["위도"]))[0]
                alt = str(r.get("인허가상호") or "")
                if v == "찾지 못함" and alt not in ("", "nan") and alt.replace(" ", "") != str(r["상호"]).replace(" ", ""): v = LC.check(alt, float(r["경도"]), float(r["위도"]))[0]
                if v != "확인됨": continue
            pick.append(f)
    else:
        pick = random.sample(rec, min(PER, len(rec)))
    item = {"id": lid, "목적": f'{l["name"]} ({l["desc"]})', "세부 종류": k or "(구분 없음)", "추천 후보 수": len(rec),
            "시설": [{"fid": f, "상호": E.F.loc[f, "상호"], "업종": E.F.loc[f, "업종"], "근거": "; ".join(E.judge(f, lid, k, nd)[1])} for f in pick]}
    if nd: item["주민의 이용 방식"] = nd
    payload.append(item)
SYSTEM = """당신은 생활시설 대안 추천 서비스의 결과를 독립적으로 점검합니다. 이 서비스는 주민이 다니던 곳이 문을 닫았을 때, 주민의 '목적'과 '세부 종류'에 맞는 다른 시설을 추천합니다.
아래 각 묶음의 '시설'은 실제로 주민에게 '추천'으로 보여 줄 곳들입니다. 각 시설을 보고, 그 목적·세부 종류(그리고 이용 방식이 있으면 그 방식)를 가진 주민에게 이곳을 안내하는 것이 맞는지 판단하세요.
판단 기준: "사람 담당 공무원이라면 이 주민에게 이곳을 안내하겠는가?" 상호·업종·근거만 보고 판단하되, 상호만으로 알 수 없는 것은 지적하지 마세요(근거가 있으면 근거를 믿으세요).
지적할 것 (확실한 것만):
- 목적에 안 맞음: 이 목적을 이루려는 주민에게 안내하면 틀린 곳 (예: 방과후 돌봄에 입시학원, 신선식품에 건어물 가게, 응급실에 일반 의원)
- 종류가 다름: 목적은 맞지만 주민이 고른 세부 종류와 다른 곳 (예: '정형외과'를 찾는데 안과)
- 문을 닫았거나 시설이 아님이 상호로 분명함 (예: 상호에 '폐업', '사무실', '본사', '물류')
출력은 JSON 배열만: [{"id":"기능 ID","kind":"세부 종류","fid":"시설 fid","problem":"목적에 안 맞음|종류가 다름|시설이 아님","reason":"이유 한 문장"}]. 문제가 없으면 []."""
r = client.messages.create(model="claude-opus-5-5", max_tokens=12000, system=SYSTEM, messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
t = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
if t.startswith("```"): t = t.split("\n", 1)[1].rsplit("```", 1)[0]
os.makedirs(OUT, exist_ok=True)
try: out = json.loads(t)
except Exception:
    open(f"{OUT}/raw_{START}.txt", "w").write(t); raise
json.dump({"units": [list(u) for u in units], "payload": payload, "findings": out}, open(f"{OUT}/{START:03d}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(START, len(units), "지적", len(out))
