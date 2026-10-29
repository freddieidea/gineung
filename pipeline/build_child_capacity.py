# 유치원·어린이집 정원과 현재 다니는 아이 수 → data/processed/child_capacity.csv (fid, 정원, 현원, 출처)
#  유치원: 유치원알리미 일반현황(data/raw/kinder 가장 최근 파일) — 인가총정원, 만3·4·5세·혼합·특수 원아 수
#  어린이집: 어린이집정보공개포털 기본정보(data/raw/childcare 가장 최근 파일, 인증키가 나오면) — crcapat 정원, crchcnt 현원
#  쓰는 곳: 엔진 scale() → 지자체 '재원 아동 옮김' 판단(정원), 주민 화면 '규모'
import glob, os, re, pandas as pd
rows = []
kf = sorted(glob.glob("data/raw/kinder/*.csv"))
if kf:
    K = pd.read_csv(kf[-1], dtype=str).fillna("")
    n = lambda v: int(float(v)) if re.fullmatch(r"\d+(\.\d+)?", str(v).strip()) else 0
    for _, r in K.iterrows():
        rows.append({"fid": f"P:유치원:{r['kindercode']}", "정원": n(r["prmstfcnt"]) or None,
                     "현원": sum(n(r[c]) for c in ["ppcnt3", "ppcnt4", "ppcnt5", "mixppcnt", "shppcnt"]) or None,
                     "출처": f"유치원알리미 정보공시 ({r['pbnttmng'][:4]}년 {r['pbnttmng'][4:]}차)"})
import sys; sys.path.insert(0, "engine")
import childcare as CC   # 이름 → 주소 순서로 맞춤 (engine/childcare.py)
C, day = CC.latest()
if C is not None:
    F = pd.read_csv("data/processed/facilities.csv", dtype=str, keep_default_na=False)
    try:   # 매일 반영한 변화(새로 넣은 어린이집 등)까지 얹은 시설표로 맞춤 (10/21)
        import overlay as OV; F = OV.apply_rows(F)
    except Exception: pass
    m, _, _ = CC.match(F, C)
    num = lambda v: int(v) if str(v).strip().isdigit() else None
    for fid, i in m.items():
        r = C.loc[i]
        rows.append({"fid": fid, "정원": num(r.get("crcapat")) or None, "현원": num(r.get("crchcnt")), "출처": f"어린이집정보공개포털 ({day})"})
D = pd.DataFrame(rows, columns=["fid", "정원", "현원", "출처"]).drop_duplicates("fid")
D.to_csv("data/processed/child_capacity.csv", index=False, encoding="utf-8")
print("유치원·어린이집 규모", len(D), "정원 있음", int(D["정원"].notna().sum()))
