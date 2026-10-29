# 어린이집정보공개포털 자료(pipeline/fetch_childcare.py → data/raw/childcare/날짜.csv)와 우리 시설 목록을 맞춤 (10/20)
#  맞추는 순서: 구·군 + 이름(띄어쓰기·괄호 무시) → 구·군 + 도로명주소(도로명 + 건물번호, 이름이 바뀐 곳: 예 '빛나는별어린이집' → '국공립빛나는별어린이집')
#  쓰는 곳: pipeline/build_child_capacity.py(정원·현원), gov_agent.childcare_check(휴지 → 휴업 반영, 공식 목록에 없는 곳 → 확인 필요)
import os, re, glob, datetime
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODES = ("PUB:어린이집", "PUB:가정어린이집", "PUB:직장어린이집")
def _nm(s): return re.sub(r"[\s()（）]", "", str(s))
def _ad(a):
    a = re.sub(r"\(.*?\)", "", str(a)); m = re.search(r"([가-힣0-9]+(?:로|길))\s*(\d+(?:-\d+)?)", a)
    return f"{m.group(1)} {m.group(2)}" if m else None
def latest():
    fs = sorted(glob.glob(os.path.join(ROOT, "data", "raw", "childcare", "*.csv")))
    if not fs: return None, None
    C = pd.read_csv(fs[-1], dtype=str, keep_default_na=False)
    if C.get("crname") is None or C["crname"].str.fullmatch(r"\d+").all(): return None, None   # 견본 응답이면 쓰지 않음
    return C, os.path.basename(fs[-1])[:10]
def match(F, C):
    """F: 시설 표(fid 색인 또는 fid 열), C: 포털 자료 → ({fid: C 행 번호}, 우리에만 있는 fid 목록, 포털에만 있는 행 번호 목록)"""
    F = F.reset_index() if "fid" not in F.columns else F
    D = F[F["업종코드"].isin(CODES)]
    by_nm = {}; by_ad = {}
    for i, r in C.iterrows():
        by_nm.setdefault((r["_구군"], _nm(r["crname"])), i)
        a = _ad(r["craddr"])
        if a: by_ad.setdefault((r["_구군"], a), []).append(i)
    out = {}; used = set()
    for _, r in D.iterrows():
        i = by_nm.get((r["구군"], _nm(r["상호"])))
        if i is not None and i not in used: out[r["fid"]] = i; used.add(i)
    for _, r in D.iterrows():   # 이름이 바뀐 곳: 같은 주소에 맞는 짝이 하나뿐일 때만
        if r["fid"] in out: continue
        a = _ad(r["주소"]); cand = [i for i in by_ad.get((r["구군"], a), []) if i not in used] if a else []
        if len(cand) == 1: out[r["fid"]] = cand[0]; used.add(cand[0])
    ours = [f for f in D["fid"] if f not in out]
    theirs = [i for i in C.index if i not in used]
    return out, ours, theirs
