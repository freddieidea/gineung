# 가게가 몇 층인지 (10/16: 걷기 불편한 주민에게는 1층이 중요) → data/processed/floors.csv (fid, 층)
#  상가 자료의 '층정보'(55%가 있음) + 그 밖의 시설은 주소 끝의 '2층', '지하1층'을 읽음. 모르면 넣지 않음 (짐작하지 않음)
import re, pandas as pd
F = pd.read_csv("data/processed/facilities.csv", dtype=str, usecols=["fid", "주소"]).fillna("")
raw = pd.read_csv("data/raw/소상공인시장진흥공단_상가(상권)정보_대구_202606.csv", usecols=["상가업소번호", "층정보"], dtype=str, encoding_errors="ignore")
raw = raw[raw["층정보"].notna()]
def fl(v):
    v = str(v).strip().upper()
    m = re.fullmatch(r"(B|지하)\s*(\d+)", v)
    if m: return -int(m.group(2))
    return int(v) if re.fullmatch(r"\d{1,2}", v) and int(v) > 0 else None
S = {"S:" + k: fl(v) for k, v in zip(raw["상가업소번호"], raw["층정보"])}
rx = re.compile(r"(지하\s*(\d+)\s*층|[Bb](\d+)\s*층?|(?<![\d-])(\d{1,2})\s*층)")
out = []
for fid, a in zip(F["fid"], F["주소"]):
    f = S.get(fid)
    if f is None:
        m = rx.search(a.split(",", 1)[1] if "," in a else "")
        if m: f = -int(m.group(2) or m.group(3)) if (m.group(2) or m.group(3)) else int(m.group(4))
    if f: out.append((fid, f))
D = pd.DataFrame(out, columns=["fid", "층"]); D.to_csv("data/processed/floors.csv", index=False)
print("층을 아는 시설", len(D), "/", len(F), D["층"].value_counts().head(6).to_dict())
