# 문 닫은 시설 목록 + '이 자리에 새로 들어온 가게' (지도·대화에서 함께 씀) → data/processed/closures.csv
#  이 자리 새 가게로 보는 조건 (둘 다 맞아야 함, 헌준님과 정함 10/15):
#   1) 같은 칸: 도로명주소의 건물 번호까지 같고, 쉼표 뒤 층·호(예: '105동 102호', '1층')도 같아야 함. 층·호가 없으면 같은 건물의 이웃 가게와 구별할 수 없어 연결하지 않음
#   2) 폐업 뒤 개업: 새 가게 인허가일이 폐업일 30일 전 이후 (새 주인이 먼저 허가를 받고 옛 주인이 늦게 폐업 신고하는 경우까지)
#  예전 규칙(같은자리새가게: 좌표 20m 안 같은 업종)은 같은 건물 이웃 가게가 섞여(예: 2026년 폐업한 가게에 2018년부터 있던 이웃 가게) 쓰지 않음
#  인허가가 필요 없는 업종(옷가게 등)은 새 가게를 알 수 없음 → '새 가게 정보 없음'으로 둠 (추측하지 않음)
import pandas as pd, re, sys, datetime
sys.path.insert(0, "pipeline")
from closure_policy import window
from ld_common import norm, sim
#  10/16: 시설 변화 관리가 반영한 변화(덮어쓰기)까지 얹은 시설표로 만듦 → 날마다 새로 찾은 폐업도 지도·대화에 들어가고,
#         '인허가가 엇갈림'(같은 가게의 다른 인허가가 아직 영업, pipeline/permit_status.py)인 곳은 문 닫은 곳으로 단정하지 않아 뺌
#         인허가 기록은 처음 받은 자료 위에 가장 최근에 받은 하루치 자료를 덮어 씀
import os, json
sys.path.insert(0, "engine")
import overlay as OV
F = OV.apply_rows(pd.read_csv("data/processed/facilities.csv", dtype=str, keep_default_na=False))
F = F.mask(F == "")   # 빈칸은 비어 있음으로 (아래에서 notna로 거름)
D = pd.read_csv("data/processed/localdata_daegu.csv", dtype=str,
                usecols=["ld_id","slug","인허가업종","사업장명","영업상태명","인허가일자","폐업일자","업태구분명","도로명주소","데이터갱신시점","전화번호"])
try:
    _st = json.load(open("data/changes/state.json", encoding="utf-8")); _d = _st.get("인허가_기준", "")
    if "localdata_updates" in _d and os.path.isdir(_d):
        import fetch_localdata as FL
        from permit_status import load_dump
        U = load_dump(_d, FL.SLUG, FL.ORG)[D.columns]
        D = pd.concat([D[~D["ld_id"].isin(U["ld_id"])], U], ignore_index=True)
        print("최근 인허가 자료를 얹음:", _d, len(U))
except Exception as ex: print("최근 인허가 자료를 얹지 못함:", ex)
from unit_addr import unit as split   # 칸 주소 규칙은 시설 변화 관리(engine/changes.py)와 함께 씀
D[["_b","_d"]] = D["도로명주소"].map(split).apply(pd.Series)
ALL = D[(D["_b"]!="") & (D["_d"]!="")]
by = {k: g for k, g in ALL.groupby(["_b","_d"])}
#  3) 한 가게만 쓰는 칸: 문 닫은 가게가 영업하던 동안 같은 칸에 다른 가게(이름이 다른 인허가)가 함께 영업했다면 그 칸은 여러 가게가 나눠 쓰는 곳
#     (예: 백화점 지하1층, 큰 건물 1층) → 누가 그 자리를 이었는지 알 수 없어 연결하지 않음. 새로 들어온 가게가 서로 다른 두 곳 이상이어도 연결하지 않음
def _day(x, add=0):
    try: return (datetime.date.fromisoformat(str(x)[:10]) + datetime.timedelta(days=add)).isoformat()
    except Exception: return None
LD = D.set_index("ld_id")
TODAY = datetime.date.today()
NAME_SLUG = {}   # 인허가 업종 → 같은 기능인지 볼 때 씀 (같은 인허가 업종이면 같은 기능으로 봄)
rows = []
NOT_LIFE = F["업종확인필요"].fillna("").str.startswith("상호 점검: 주민이 찾아가는 생활시설이 아님")   # 공장·도매·사무실은 폐업 지도에 넣지 않음 (폐업 시설 상호 점검)
closed = F[(F["인허가상태"]=="폐업") & F["인허가id"].notna() & F["폐업일자"].notna() & ~F["제외사유"].fillna("").str.startswith("인허가가 엇갈림") & ~NOT_LIFE]
for _, f in closed.iterrows():
    own = LD.loc[f["인허가id"]] if f["인허가id"] in LD.index else None
    if own is None: continue
    upd = str(own["데이터갱신시점"])[:10]
    w = window(f["업종"], f["폐업일자"], upd, f["출처"], TODAY)
    if w is None or w["단계"] == "지남": continue
    b, d = own["_b"], own["_d"]
    new = None
    if b and d and (b, d) in by:
        lim = (datetime.date.fromisoformat(f["폐업일자"][:10]) - datetime.timedelta(days=30)).isoformat()
        g = by[(b, d)]; g = g[g["ld_id"] != f["인허가id"]]
        g = g[pd.Series([sim(norm(f["상호"]), norm(n)) < 85 and sim(norm(own["사업장명"]), norm(n)) < 85 for n in g["사업장명"]], index=g.index, dtype=bool)]   # 같은 이름이면 다시 연 같은 가게라 '새 가게'가 아님
        o_start = _day(own["인허가일자"], 30) or "0000"
        overlap = g[(g["인허가일자"].fillna("9999") < lim) & (g["폐업일자"].isna() | (g["폐업일자"].fillna("") > o_start))]
        cand = g[(g["영업상태명"]=="영업/정상") & (g["인허가일자"].fillna("") >= lim)].sort_values("인허가일자")
        groups = []
        for _, c in cand.iterrows():   # 같은 가게가 업종별로 인허가를 여러 개 받은 경우(카페+제과점)는 한 가게로 봄
            if not any(sim(norm(c["사업장명"]), norm(x["사업장명"])) >= 85 for x in groups): groups.append(c)
        if len(overlap) == 0 and len(groups) == 1: new = groups[0]
    nf = None   # 새 가게가 우리 지도에도 있으면 그 업종(세부 종류)으로 같은 기능인지 봄. 인허가 업태('한식', '기타')는 너무 넓어 쓰지 않음
    if new is not None:
        m = F[(F["fid"] == "L:" + new["ld_id"]) | ((F["인허가id"] == new["ld_id"]) & (F["인허가상태"] == "영업"))]
        if len(m): nf = m.iloc[0]
    same_fn = bool(nf is not None and nf["업종"] == f["업종"] and str(nf.get("업종확인필요") or "") in ("", "nan"))
    if same_fn and w["단계"] == "지도 표시": w["단계"] = "안내만"   # 같은 기능의 새 가게가 들어와 기능이 이어짐
    rows.append({"fid": f["fid"], "상호": f["상호"], "업종": f["업종"], "구군": f["구군"], "주소": f["주소"], "경도": f["경도"], "위도": f["위도"],
                 "폐업일자": f["폐업일자"][:10], **w, "칸주소": (b + " " + d).strip() if d else "",
                 "새가게": "" if new is None else new["사업장명"], "새가게업종": "" if nf is None else nf["업종"],   # 우리 지도에 없는 가게는 인허가 업종 이름(예: 담배소매업)이 실제 가게와 달라 보일 수 있어 비워 둠
                 "새가게fid": "" if nf is None else nf["fid"],
                 "새가게개업일": "" if new is None else str(new["인허가일자"])[:10], "새가게인허가id": "" if new is None else new["ld_id"],
                 "같은기능새가게": same_fn})
# 인허가로는 알 수 없지만 확인으로 문을 닫은 곳 (주민 제보를 AI가 교차검증했거나 담당자가 확인, 10/19): 인허가 기록 없이도 폐업 지도에 넣음
have = {r["fid"] for r in rows}
conf = F[F["제외사유"].fillna("").str.contains("확인: 문 닫음") & F["경도"].notna() & ~NOT_LIFE & ~F["fid"].isin(have)]
for _, f in conf.iterrows():
    day = str(f["폐업일자"] or "")[:10] if pd.notna(f["폐업일자"]) else TODAY.isoformat()
    w = window(f["업종"], day, TODAY.isoformat(), f["출처"], TODAY)
    if w is None or w["단계"] == "지남": continue
    rows.append({"fid": f["fid"], "상호": f["상호"], "업종": f["업종"], "구군": f["구군"], "주소": f["주소"], "경도": f["경도"], "위도": f["위도"],
                 "폐업일자": day, **w, "칸주소": "", "새가게": "", "새가게업종": "", "새가게fid": "", "새가게개업일": "", "새가게인허가id": "", "같은기능새가게": False})
print("확인으로 문 닫은 곳 더함:", len(rows) - len(have))
R = pd.DataFrame(rows)
# 같은 가게가 상가 자료에 두 번 있어 문 닫은 곳도 두 번 잡힌 경우 (같은 상호·같은 건물) → 하나만
R["_k"] = [norm(n) + "|" + (split(a)[0] or f"{x}{y}") for n, a, x, y in zip(R["상호"], R["주소"], R["경도"], R["위도"])]
n0 = len(R); R = R.drop_duplicates("_k").drop(columns="_k")
print("같은 가게 두 번 잡힌 것 뺌:", n0 - len(R))
R.to_csv("data/processed/closures.csv", index=False, encoding="utf-8")
print("안내 기간 안의 문 닫은 시설", len(R), R["단계"].value_counts().to_dict())
print("묶음", R.groupby(["묶음","단계"]).size().to_dict())
print("층·호까지 아는 곳", int((R["칸주소"]!="").sum()), " 이 자리 새 가게", int((R["새가게"]!="").sum()), " 그중 같은 기능", int(R["같은기능새가게"].sum()))
