# 시설 변화 덮어쓰기: 시설 변화 관리(engine/changes.py)가 반영한 변화를 원래 시설 데이터베이스 위에 얹는다
#  - 원래 자료(data/processed/facilities.csv 등)는 고치지 않고, 바뀐 시설만 data/changes/에 따로 둠
#    → 언제든 어떤 변화가 언제, 무슨 근거로 들어왔는지 되짚을 수 있고, 잘못 들어온 변화는 그 기록만 되돌리면 됨
#  - overlay_rows.csv     : 바뀐 시설의 전체 행 (같은 fid가 원래 자료에 있으면 갈아 끼우고, 없으면 새 시설로 더함). '변경id' 칸에 변화 기록 번호
#  - overlay_evidence.csv : 새 시설·인허가가 바뀐 시설의 기능 근거표 (그 시설들의 원래 근거 행을 갈아 끼움, 문 닫은 시설은 원래 근거 유지)
#  - overlay_members.csv  : 새 시설의 근거 유형(EV:) 행
#  - overlay_walk.csv     : 새 시설을 걷는 길에 붙인 지점
import os, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _p(root, name): return os.path.join(root, "data", "changes", name)
def _read(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False) if os.path.exists(path) and os.path.getsize(path) > 0 else None

def apply_rows(F, root=ROOT):
    O = _read(_p(root, "overlay_rows.csv"))
    if O is None or O.empty: return F
    O = O[[c for c in F.columns if c in O.columns] + (["변경id"] if "변경id" in O.columns else [])]
    assert O["fid"].is_unique, "덮어쓰기 행에 같은 시설이 두 번 있음"
    if "변경id" not in F.columns: F = F.assign(변경id="")
    keep = F[~F["fid"].isin(O["fid"])]
    rep = O[O["fid"].isin(F["fid"])]; new = O[~O["fid"].isin(F["fid"])]
    # 원래 순서를 지키며 갈아 끼움 (새 시설은 끝에)
    M = pd.concat([keep, rep]).set_index("fid", drop=False).loc[F["fid"]].reset_index(drop=True)
    return pd.concat([M, new], ignore_index=True)

# 근거를 다시 만든 시설 목록 (overlay_redone.csv, 시설 변화 관리가 근거표를 다시 만들 때 함께 씀)
#  문 닫은 시설은 다시 만들지 않고 원래 근거를 그대로 둠 (알림에 '하던 일'을 보여 주려고)
def _redone(root):
    R = _read(_p(root, "overlay_redone.csv"))
    return set() if R is None else set(R["fid"])

def apply_evidence(EV, root=ROOT):
    O = _read(_p(root, "overlay_evidence.csv"))
    if O is None: return EV
    return pd.concat([EV[~EV["fid"].isin(_redone(root))], O], ignore_index=True)

def apply_members(EM, root=ROOT):
    O = _read(_p(root, "overlay_members.csv"))
    if O is None: return EM
    return pd.concat([EM[~EM["fid"].isin(_redone(root))], O], ignore_index=True)

def walk_snaps(root=ROOT):
    O = _read(_p(root, "overlay_walk.csv"))
    if O is None: return {}
    return dict(zip(O["fid"], zip(O["edge"].astype(int), O["t"].astype(float), O["snap_m"].astype(float))))
