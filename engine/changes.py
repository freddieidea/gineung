# 시설 변화 관리 (AI 에이전트의 지자체 역할, 2026-10-15)
# 하는 일
#  1) 변화를 알게 되는 길 세 가지
#     - 인허가 자동 감지: 행정안전부 지방행정 인허가 자료를 새로 받아 지난번 자료와 견줌 → 새로 난 인허가(개업), 폐업·휴업·말소, 다시 영업
#     - 담당자 입력: 공무원이 '○○동 △△슈퍼 10월 말 폐업'처럼 알려 줌 (engine/change_agent.py가 말을 알아듣고 여기 함수를 부름)
#     - 주민 제보: 주민이 대화 중 '거기 문 닫았어요'라고 알려 줌 → 담당자가 확인하기 전까지는 '확인 필요'로만 둠 (주민에게 그곳을 안내하지 않음)
#  2) 지금의 분류 체계로 알아서 분류 (데이터베이스를 만들 때와 같은 규칙을 그대로 씀)
#     - 업종: 인허가 업종·업태 → 상가 업종 (pipeline/facility_rules.py), 상호로 업종 바로잡기·어긋남 찾기 (pipeline/name_signals.py)
#     - 기능·세부 종류: 업종-기능 연결표와 분류표 세부 종류 (엔진이 덮어쓰기를 얹어 다시 계산)
#     - 가게별 근거: 근거표 규칙 (pipeline/build_evidence.py를 새 시설에만 돌림)
#     - 대안 후보 여부: 의료기관 등록 → 예 / 인허가가 NEW_PERMIT_DAYS일 안에 난 곳 → 예 / 상호와 업종이 어긋남 → 확인 필요 / 상호 없음·대구 밖 주소 → 아니요
#  3) 폐업 시설은 담당 공무원에게 알림 (지자체 모드): 그 시설이 맡던 기능, 영향받는 주민(추정), 대체 시설 (engine/impact.py, 대안 찾기 엔진)
#     새 시설이 생활 공백을 메우면 그것도 알림. 모든 변화는 날마다 구·군별 요약으로 묶음
# 원래 자료는 고치지 않음: 바뀐 것은 data/changes/ (덮어쓰기, engine/overlay.py), 알림은 data/notices/
# 사용
#   python engine/changes.py 받기 [제한초]          # 오늘 인허가 자료를 data/raw/localdata_updates/날짜/에 받음 (나눠 받기 가능)
#   python engine/changes.py 감지 [폴더]            # 지난번 자료와 견줘 변화를 찾아 분류하고 덮어쓰기에 반영
#   python engine/changes.py 알림 [제한초]          # 반영한 변화마다 영향 계산 → 알림 (시간 제한 안에서 나눠 함)
#   python engine/changes.py 요약 [날짜]            # 구·군별 하루 요약
import os, sys, json, re, glob, datetime, subprocess, time
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(ROOT, "engine"), os.path.join(ROOT, "pipeline")):
    if _d not in sys.path: sys.path.insert(0, _d)
import facility_rules as FR
from name_signals import conflicts, reclass, other_business
from ld_common import norm, sim, same_biz
import overlay as OV
def _plain(upjong, name, lid):
    """(10/26 전수 점검) 같은 업종 안의 성격이 다른 가게는 대신 갈 곳으로 세지 않음: 미용실 업종의 네일·두피관리, 약국 업종의 한약방(처방약),
    슈퍼마켓 업종의 다이소·무인 할인점(장보기), 세탁소 업종의 옷 수선 전문 등 (engine/occasions.py SPECIAL). 뒤로만 미는 종류(PT 전문)는 그대로 셈"""
    try:
        import occasions as _O
        return _O.special_check(upjong, name, set(), lid)[0]
    except Exception:
        return True
KX = np.cos(np.radians(35.87)) * 111320; KY = 110540
KST = datetime.timezone(datetime.timedelta(hours=9))
# ---- 기준값 (현장 판단, 바꿀 수 있음) ----
NEW_PERMIT_DAYS = 180   # 인허가가 이만큼 안에 난 곳은 실제로 문을 연 것으로 봄. 오래된 인허가만 있는 곳은 지금처럼 '확인 필요'
HOST_R = 80             # 가게에 붙는 인허가(상비약·종량제 봉투)를 가게와 짝지을 거리(m) — match_localdata.py와 같음
SAME_PLACE_R = 30       # 같은 자리 새 가게로 볼 거리(m)
ALERT_POP = 30          # 생활 공백이 생기거나 메워지는 주민이 이만큼 이상이면 '긴급'·'주의'·'좋은 소식'
ATTN_NEAR = 300; ATTN_JUMP = 5   # 필수 기능에서 가까운 주민이 이만큼 이상이고 걷는 시간 중앙값이 이만큼(분) 넘게 늘면 '주의'
LEVELS = ["긴급", "주의", "확인 요청", "좋은 소식", "참고"]
COLS = None
LD_KEEP = ["관리번호", "사업장명", "영업상태명", "상세영업상태명", "인허가일자", "폐업일자", "휴업시작일자", "휴업종료일자", "업태구분명", "진료과목내용명",
           "의료기관종별명", "도로명주소", "지번주소", "전화번호", "좌표정보(X)", "좌표정보(Y)", "데이터갱신시점"]

def now(): return datetime.datetime.now(KST)
def today(): return now().date().isoformat()
def ld_state(s):
    s = str(s or "")
    return "영업" if s.startswith("영업") else ("폐업" if s.startswith("폐업") else ("휴업" if s.startswith("휴업") else "말소 등"))

def keep_on_report(r):
    """주민 제보가 와도 확인 전까지 안내를 유지할 곳: 인허가로 영업이 확인된 일반 가게 (공공·복지·의료는 제보 즉시 AI가 판단하므로 해당 없음)"""
    return str(r.get("인허가상태")) == "영업" and bool(str(r.get("인허가id") or "").strip()) and str(r.get("출처")) not in ("공공", "심평원") and r.get("대안후보") == "예"
class ChangeManager:
    def __init__(self, root=ROOT):
        self.root = root; self.ch = os.path.join(root, "data", "changes"); self.note = os.path.join(root, "data", "notices")
        os.makedirs(self.ch, exist_ok=True); os.makedirs(self.note, exist_ok=True)
        self.F0 = pd.read_csv(os.path.join(root, "data", "processed", "facilities.csv"), dtype=str, keep_default_na=False)
        global COLS; COLS = list(self.F0.columns)
        O = OV._read(os.path.join(self.ch, "overlay_rows.csv"))
        self.rows = {} if O is None else {r["fid"]: r for r in O.to_dict("records")}   # 바뀐 시설: fid → 행 전체
        self.events = self._jsonl(os.path.join(self.ch, "events.jsonl"))
        self.notices = self._jsonl(os.path.join(self.note, "notices.jsonl"))
        sp = os.path.join(self.ch, "state.json")
        self.state = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {"인허가_기준": "data/raw/localdata", "인허가_기준일": "2026-10-13"}
        self._F = None; self._E = None; self._tree = None; self._hjd = None

    # ---------------- 기록 ----------------
    @staticmethod
    def _jsonl(p):
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []
    def _save(self):
        def dump(p, xs):
            tmp = p + ".part"
            with open(tmp, "w", encoding="utf-8") as f:
                for x in xs: f.write(json.dumps(x, ensure_ascii=False) + "\n")
            os.replace(tmp, p)
        dump(os.path.join(self.ch, "events.jsonl"), self.events); dump(os.path.join(self.note, "notices.jsonl"), self.notices)
        if self.rows:
            R = pd.DataFrame(list(self.rows.values()))
            for c in COLS + ["변경id"]:
                if c not in R: R[c] = ""
            R[COLS + ["변경id"]].to_csv(os.path.join(self.ch, "overlay_rows.csv"), index=False, encoding="utf-8")
        json.dump(self.state, open(os.path.join(self.ch, "state.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        self._F = None
    def _new_id(self, prefix, xs):
        d = now().strftime("%Y%m%d"); n = sum(1 for x in xs if x["id"].startswith(f"{prefix}{d}-")) + 1
        return f"{prefix}{d}-{n:04d}"
    def _event(self, **kw):
        e = {"id": self._new_id("C", self.events), "접수": now().isoformat(timespec="seconds"), "알림": None}; e.update(kw)
        self.events.append(e); return e

    # 지금 시설표 (원래 자료 + 덮어쓰기)
    @property
    def F(self):
        if self._F is None:
            if self.rows:
                O = pd.DataFrame(list(self.rows.values()))
                for c in COLS + ["변경id"]:
                    if c not in O: O[c] = ""
                keep = self.F0[~self.F0["fid"].isin(O["fid"])].assign(변경id="")
                self._F = pd.concat([keep, O[COLS + ["변경id"]]], ignore_index=True)
            else: self._F = self.F0.assign(변경id="")
            self._F["x"] = pd.to_numeric(self._F["경도"], errors="coerce"); self._F["y"] = pd.to_numeric(self._F["위도"], errors="coerce")
            self._tree = None
        return self._F
    def row(self, fid):
        if fid in self.rows: return dict(self.rows[fid])
        r = self.F0[self.F0["fid"] == fid]
        if r.empty: raise KeyError(f"시설 데이터베이스에 없는 시설: {fid}")
        return r.iloc[0].to_dict()
    def _put(self, r, eid):
        r = {c: ("" if r.get(c) is None or (isinstance(r.get(c), float) and np.isnan(r.get(c))) else r.get(c)) for c in COLS}
        r["변경id"] = eid; self.rows[r["fid"]] = r; self._F = None

    # 가까운 시설 찾기 (좌표)
    def _near(self, lon, lat, r):
        F = self.F
        if self._tree is None:
            from scipy.spatial import cKDTree
            ok = F["x"].notna().values; self._tidx = np.where(ok)[0]
            self._tree = cKDTree(np.c_[F["x"].values[ok] * KX, F["y"].values[ok] * KY])
        j = self._tree.query_ball_point([lon * KX, lat * KY], r=r)
        S = F.iloc[self._tidx[j]].copy()
        S["거리m"] = np.hypot((S["x"] - lon) * KX, (S["y"] - lat) * KY)
        return S.sort_values("거리m")

    # 좌표 → 행정동
    def hjd_of(self, lon, lat):
        if self._hjd is None:   # shapely 없이 (engine/coords.py)
            from coords import Areas
            G = json.load(open(os.path.join(self.root, "data", "raw", "boundary", "daegu_hjd_20260701.geojson"), encoding="utf-8"))["features"]
            self._hjd = (Areas(G), [(g["properties"]["sggnm"], g["properties"]["adm_nm"].split()[-1]) for g in G])
        A, names = self._hjd; i = A.find(lon, lat)
        return names[i] if i is not None else (None, None)

    # 주소 → 좌표: 같은 건물 주소의 상가·인허가 좌표 → 브이월드 주소 검색(돌려준 주소가 입력과 같을 때만)
    def geocode(self, addr, gu=None):
        import addr_lookup as AL
        if not hasattr(self, "_addr"):
            self._addr = AL.build()
        k = AL.key(addr)
        if k and k in self._addr.index:
            x, y = self._addr.loc[k]; return float(x), float(y), "같은 건물 주소의 상가·인허가 좌표"
        try:
            import geocode_vworld as GV
            res, why = GV.by_addr(addr, gu or ""); GV.save_cache()
            if res: return res[0], res[1], why
            return None, None, why
        except Exception as e:
            return None, None, f"브이월드 검색 실패 ({str(e)[:60]})"

    # ---------------- 새 시설 분류 (데이터베이스를 만들 때와 같은 규칙) ----------------
    def classify_row(self, r, base_cand):
        """r: 시설 행(업종코드·상호·주소·좌표가 채워진 것), base_cand: 영업 근거로 정한 대안 후보('예'|'확인 필요').
        업종 바로잡기·어긋남·대안 후보를 정해 돌려줌. why: 판단 근거 목록 (데이터베이스를 만들 때와 같은 규칙)"""
        why = []
        if str(r.get("업종확인필요", "")).startswith("상호와 업종이 어긋남"): r["업종확인필요"] = ""   # 업종이 바뀌었으면 어긋남을 다시 봄
        up = FR.upjong_name(r["업종코드"])
        to = reclass(r["상호"], up) if r["업종코드"] in FR.NAME else None
        if to:
            r["업종보정"] = f"{up}→{to} (상호 근거)"; r["업종코드"] = FR.CODE[to]; why.append(f"상호로 업종 바로잡음: {up} → {to}"); up = to
            if str(r.get("업종확인필요", "")).startswith("인허가 업태만으로는"): r["업종확인필요"] = ""   # 상호의 메뉴로 세부 종류가 정해짐
        hit, bad = conflicts(r["상호"], up)
        if bad: r["업종확인필요"] = "상호와 업종이 어긋남: " + "; ".join(bad); why.append(r["업종확인필요"])
        r["업종"] = up
        r["도매가능성"] = bool(re.search("도매|식자재|도소매|총판", str(r["상호"]).replace(" ", "")))
        r["대안후보"] = base_cand; r["제외사유"] = ""
        if base_cand == "예" and r.get("업종확인필요"): r["대안후보"] = "확인 필요"; why.append("업종을 확인하기 전까지 주민에게 안내하지 않음")
        ob = other_business(r["상호"], up)
        if ob: r["대안후보"] = "아니요"; r["제외사유"] = ob; why.append(ob)
        if FR.no_name(r["상호"], up): r["대안후보"] = "아니요"; r["제외사유"] = "상호가 없어 어느 가게인지 특정할 수 없음"; why.append(r["제외사유"])
        if not FR.in_daegu(r["주소"]): r["대안후보"] = "아니요"; r["제외사유"] = "주소가 대구가 아님"; why.append(r["제외사유"])
        if r["대안후보"] in ("예", "확인 필요") and not str(r.get("경도") or "").strip():
            r["대안후보"] = "좌표 필요"; r["제외사유"] = "주소의 좌표를 아직 못 찾음"; why.append("좌표를 못 찾아 대안 안내에서 뺌")
        if str(r.get("경도") or "").strip():
            gu, dong = self.hjd_of(float(r["경도"]), float(r["위도"]))
            if dong: r["행정동"] = dong
            if gu and r.get("구군") and gu != r["구군"]: why.append(f"좌표가 {gu}에 있음 (자료의 구·군: {r['구군']})")
        return r, why
    def _blank(self):
        r = {c: "" for c in COLS}
        for c in ("상비약판매", "종량제봉투판매", "담배판매", "도매가능성", "공원운동시설"): r[c] = False
        return r

    # 인허가 한 건 → 새 시설 행 (build_facilities.py의 '인허가에만 있는 가게'와 같은 칸)
    def row_from_ld(self, rec):
        code = FR.ld_type(rec)
        if code is None: return None, ["생활시설 업종이 아님"], None
        r = self._blank(); slug = rec["slug"]
        r.update({"fid": "L:" + rec["ld_id"], "출처": "인허가", "상호": rec["사업장명"], "업종코드": code, "표준산업분류": "이용업" if rec["인허가업종"] == "생활_이용업" else "",
                  "구군": rec["구군"], "주소": rec["도로명주소"] or rec.get("지번주소") or "", "경도": rec.get("경도") or "", "위도": rec.get("위도") or "", "전화": rec.get("전화번호") or "",
                  "인허가상태": "영업", "인허가id": rec["ld_id"], "인허가업종": rec["인허가업종"], "업태": rec.get("업태구분명") or "", "진료과목": rec.get("진료과목내용명") or "",
                  "의료기관종별": rec.get("의료기관종별명") or ""})
        why = []
        if code in (FR.CODE["기타 한식 음식점"], FR.CODE["기타 일식 음식점"]): r["업종확인필요"] = "인허가 업태만으로는 세부 종류를 알 수 없음"
        d0 = str(rec.get("인허가일자") or "")[:10]
        fresh = bool(d0) and (now().date() - datetime.date.fromisoformat(d0)).days <= NEW_PERMIT_DAYS
        if slug in FR.MED_SLUGS: base = "예"; r["영업근거"] = f"인허가 의료기관 등록 ({d0}, 시설 변화 관리)"; why.append(f"의료기관 인허가 ({d0})")
        elif fresh: base = "예"; r["영업근거"] = f"인허가 새로 남 ({d0}, 시설 변화 관리)"; why.append(f"인허가가 {d0}에 새로 나 문을 연 것으로 봄")
        else: base = "확인 필요"; r["영업근거"] = f"인허가만(영업 확인 필요, {d0})"; why.append(f"인허가가 {d0}에 난 것이 이번에 자료에 올라와, 지금도 영업하는지 확인 필요")
        if not r["경도"] and r["주소"]:
            x, y, how = self.geocode(r["주소"], r["구군"])
            if x: r["경도"], r["위도"] = x, y; why.append(f"좌표: {how}")
        r, w2 = self.classify_row(r, base)
        return r, why + w2, base
    # ---------------- 인허가 자료 받기·견주기 ----------------
    def fetch(self, date=None, budget=150):
        import fetch_localdata as FL
        date = date or today(); out = os.path.join(self.root, "data", "raw", "localdata_updates", date); os.makedirs(out, exist_ok=True)
        FL.OUT = out; t0 = time.time(); res = []
        import concurrent.futures as cf
        jobs = [(s, g, o) for s in FL.SLUG for g, o in FL.ORG.items()]
        with cf.ThreadPoolExecutor(6) as ex:
            futs = [ex.submit(FL.one, *j) for j in jobs]
            try:
                for f in cf.as_completed(futs, timeout=max(1, budget - (time.time() - t0))): res.append(f.result())
            except cf.TimeoutError: pass
        done = sum(1 for s in FL.SLUG for g in FL.ORG if os.path.exists(f"{out}/{s}__{g}.csv"))
        return {"폴더": out, "받음": done, "전체": len(jobs), "실패": [r for r in res if r[2] == "실패"]}

    def _read_ld(self, path, slug, gu, inh):
        d = pd.read_csv(path, dtype=str)
        for c in LD_KEEP + ["시설총규모"]:
            if c not in d: d[c] = None
        d = d[LD_KEEP + ["시설총규모"]].copy()
        d["ld_id"] = f"{slug}:{gu}:" + d["관리번호"]; d["slug"] = slug; d["구군"] = gu; d["인허가업종"] = inh
        return d.drop_duplicates("ld_id").set_index("ld_id", drop=False)

    def detect(self, new_dir, base_dir=None):
        """두 번 받은 인허가 자료를 견줘 변화 목록을 돌려줌 (아직 반영하지 않음)"""
        import fetch_localdata as FL
        from coords import Transformer   # pyproj 없이 같은 변환 (engine/coords.py)
        base_dir = base_dir or os.path.join(self.root, self.state["인허가_기준"])
        self.load_permits(new_dir)   # 가게의 다른 인허가까지 보고 문 닫음을 판정 (pipeline/permit_status.py)
        tf = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
        out = []; missing = []
        for slug, inh in FL.SLUG.items():
            for gu in FL.ORG:
                pb, pn = f"{base_dir}/{slug}__{gu}.csv", f"{new_dir}/{slug}__{gu}.csv"
                if not os.path.exists(pn): missing.append(f"{slug}__{gu}"); continue
                N = self._read_ld(pn, slug, gu, inh)
                B = self._read_ld(pb, slug, gu, inh) if os.path.exists(pb) else N.iloc[0:0]
                sb = B["영업상태명"].map(ld_state); sn = N["영업상태명"].map(ld_state)
                new = N.index.difference(B.index); com = N.index.intersection(B.index)
                ch = com[sb.loc[com].values != sn.loc[com].values]
                for i in new:
                    if sn[i] == "영업": out.append(("개업", None, N.loc[i]))
                for i in ch:
                    o, n = sb[i], sn[i]
                    if o == "영업": out.append((n if n != "말소 등" else "말소", o, N.loc[i]))
                    elif n == "영업": out.append(("재개업", o, N.loc[i]))
        recs = []
        for kind, before, s in out:
            d = s.to_dict()
            x = pd.to_numeric(str(d.get("좌표정보(X)") or "").strip(), errors="coerce"); y = pd.to_numeric(str(d.get("좌표정보(Y)") or "").strip(), errors="coerce")
            lon = lat = None
            if pd.notna(x) and pd.notna(y):
                lon, lat = tf.transform(x, y)
                if not (128.3 <= lon <= 129.0 and 35.55 <= lat <= 36.35): lon = lat = None
            d.update({"경도": lon, "위도": lat, "변화": kind, "이전상태": before})
            recs.append({k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in d.items()})
        return recs, missing

    # ---------------- 변화 반영 ----------------
    permits = None; _permits_dir = None
    def load_permits(self, d=None):
        """최신 인허가 자료(하루치 전체)로 가게별 인허가 색인을 만듦"""
        import fetch_localdata as FL
        from permit_status import Permits, load_dump
        d = d or os.path.join(self.root, self.state["인허가_기준"])
        if self.permits is None or self._permits_dir != d:
            L = load_dump(d, FL.SLUG, FL.ORG); self.permits = Permits(L); self._permits_dir = d
            self._close_day = dict(zip(L["ld_id"], L["폐업일자"].fillna(""))); self._ld_name = dict(zip(L["ld_id"], L["사업장명"].fillna("")))
            self._ld_addr = dict(zip(L["ld_id"], L["도로명주소"].fillna("")))
        return self.permits

    def _fids_of_permit(self, ld_id):
        F = self.F
        return F.loc[(F["인허가id"] == ld_id) | (F["fid"] == "L:" + ld_id), "fid"].tolist()

    def _host(self, rec):
        """가게에 붙는 인허가(상비약·종량제 봉투 등)의 주인 가게: 80m 안, 상호가 같은 가게 (match_localdata.py와 같은 규칙)"""
        if rec.get("경도") is None: return None
        S = self._near(rec["경도"], rec["위도"], HOST_R)
        S = S[S["출처"].isin(["상가", "인허가"])]
        ln = norm(rec["사업장명"]); best = None
        for _, s in S.iterrows():
            nm = norm(s["상호"]); nm0 = norm(str(s["상호"]).split(" ")[0])
            sc = max(sim(nm, ln), sim(nm0, ln))
            if sc >= 85 and same_biz(nm, nm0, ln) and (best is None or (sc, -s["거리m"]) > best[0]): best = ((sc, -s["거리m"]), s["fid"])
        return best[1] if best else None

    def apply_ld(self, rec, source="인허가 자동 감지"):
        """인허가 변화 한 건을 반영하고 변화 기록을 돌려줌 (반영할 것이 없으면 None)"""
        slug = rec["slug"]; kind = rec["변화"]; ld = rec["ld_id"]
        key = f"{ld}|{kind}|{rec.get('폐업일자') or rec.get('인허가일자') or ''}"
        if any(e.get("키") == key for e in self.events): return None   # 이미 반영한 변화
        raw = {k: rec.get(k) for k in ("ld_id", "사업장명", "인허가업종", "업태구분명", "영업상태명", "상세영업상태명", "인허가일자", "폐업일자", "휴업시작일자", "휴업종료일자", "도로명주소", "데이터갱신시점")}
        src = f"지방행정 인허가 ({rec['인허가업종']}, 자료 갱신 {str(rec.get('데이터갱신시점') or '')[:10]})"
        # (가) 가게에 붙는 인허가: 기능 추가·중단
        if slug in FR.FLAG_SLUGS:
            col, kw = FR.FLAG_SLUGS[slug]
            if col == "담배판매": return None          # 담배는 생활기능 연결이 없음
            host = self._host(rec)
            if not host: return None
            r = self.row(host); was = str(r[col]) == "True"; on = kind in ("개업", "재개업")
            if was == on: return None
            r[col] = on
            lic = [x for x in str(r["그외인허가"]).split("|") if x and not x.startswith(rec["인허가업종"])]
            r["그외인허가"] = "|".join(sorted(lic + [rec["인허가업종"] + ("" if on else "(폐업)")]))
            e = self._event(키=key, 출처=source, 종류="기능 추가" if on else "기능 중단", 상태="반영", fid=host, 상호=r["상호"], 구군=r["구군"],
                            날짜=(rec.get("인허가일자") if on else rec.get("폐업일자")) or "", 근거=src, 원자료=raw,
                            분류={"인허가": col, "이전": was, "이후": on})
            self._put(r, e["id"]); return e
        # (나) 본업 인허가가 문을 닫음
        if kind in ("폐업", "휴업", "말소"):
            fids = [f for f in self._fids_of_permit(ld)]
            last = None
            ad = rec.get("도로명주소") or ""
            if "*" in ad and fids: ad = self.row(fids[0])["주소"]   # 가려진 주소면 시설 주소로 건물을 봄
            v, vwhy, left = (self.permits.verdict(ld, rec.get("사업장명"), ad, rec.get("폐업일자") or rec.get("휴업시작일자"))
                             if self.permits is not None and ad else ("폐업", "", []))
            if v == "영업": return None   # 주인이 바뀌어 인허가를 다시 받은 가게: 문을 닫지 않음 (새 인허가는 '개업'으로 따로 들어옴)
            for f in fids:
                r = self.row(f)
                if r["대안후보"] == "아니요" and r["인허가상태"] in ("폐업", "휴업", "말소 등"): continue
                before = r["대안후보"]
                day = rec.get("폐업일자") if kind == "폐업" else (rec.get("휴업시작일자") or "")
                if v == "확인 필요":   # 같은 가게의 다른 인허가가 아직 영업 → 주민에게 단정하지 않고 담당자에게 확인 요청
                    r["인허가상태"] = {"말소": "말소 등"}.get(kind, kind); r["폐업일자"] = rec.get("폐업일자") or r["폐업일자"]
                    r["대안후보"] = "아니요"; r["제외사유"] = "인허가가 엇갈림 — " + vwhy
                    last = self._event(키=key, 출처=source, 종류="폐업", 상태="확인 필요", fid=f, 상호=r["상호"], 구군=r["구군"], 날짜=day or "",
                                       근거=src + " / " + vwhy, 원자료=dict(raw, 이전대안후보=before), 분류={"업종": r["업종"], "이전대안후보": before, "남은인허가": left})
                    self._put(r, last["id"]); continue
                r["인허가상태"] = {"말소": "말소 등"}.get(kind, kind); r["폐업일자"] = rec.get("폐업일자") or r["폐업일자"]
                r["대안후보"] = "아니요"; r["제외사유"] = f"인허가상 {kind}" + (f" ({day})" if day else "") + " — 시설 변화 관리"
                last = self._event(키=key, 출처=source, 종류=kind if kind != "말소" else "폐업", 상태="반영", fid=f, 상호=r["상호"], 구군=r["구군"], 날짜=day or "",
                                   근거=src, 원자료=dict(raw, 이전대안후보=before), 분류={"업종": r["업종"], "이전대안후보": before})
                self._put(r, last["id"])
            return last
        # (다) 본업 인허가가 새로 남 / 다시 영업
        if kind in ("개업", "재개업"):
            if FR.ld_type(rec) is None: return None
            targets = [(f, "같은 인허가") for f in self._fids_of_permit(ld)]
            if not targets and rec.get("경도") is not None:
                # 같은 자리(30m 안)에 상호가 같은 가게가 이미 있으면 새 시설로 더하지 않고 그 가게에 인허가를 붙임 (양도·명의 변경·인허가 다시 받음 등)
                S = self._near(rec["경도"], rec["위도"], SAME_PLACE_R); S = S[S["출처"].isin(["상가", "인허가"])]
                S = S[[sim(norm(n), norm(rec["사업장명"])) >= 85 for n in S["상호"]]]
                if len(S): targets = [(S.iloc[0]["fid"], "같은 자리 같은 상호")]
            if not targets and rec.get("도로명주소"):   # 좌표가 없으면 같은 건물 주소로
                import addr_lookup as AL
                k0 = AL.key(rec["도로명주소"]); F = self.F
                if k0:
                    S = F[F["출처"].isin(["상가", "인허가"]) & (F["구군"] == rec["구군"])]
                    S = S[[sim(norm(n), norm(rec["사업장명"])) >= 85 for n in S["상호"]]]
                    S = S[[AL.key(a) == k0 for a in S["주소"]]]
                    if len(S): targets = [(S.iloc[0]["fid"], "같은 건물 같은 상호")]
            if targets:
                last = None
                from ld_common import primary_for
                for f, how in targets:
                    h = self.row(f); before = h["대안후보"]; was_closed = h["인허가상태"] in ("폐업", "휴업", "말소 등")
                    if how != "같은 인허가" and slug not in primary_for(h["업종코드"], h["업종"]):
                        # 그 가게의 본업 인허가가 아님 (예: 음식점이 축산물 판매업도 받음) → 함께 받은 인허가로만 적음
                        lic = [x for x in str(h["그외인허가"]).split("|") if x and x != rec["인허가업종"]]
                        h["그외인허가"] = "|".join(sorted(lic + [rec["인허가업종"]]))
                        last = self._event(키=key, 출처=source, 종류="인허가 확인", 상태="반영", fid=f, 상호=h["상호"], 구군=h["구군"], 날짜=rec.get("인허가일자") or "",
                                           근거=src, 원자료=raw, 분류={"업종": h["업종"], "이전대안후보": before, "대안후보": before, "짝": how + " (함께 받은 인허가)"})
                        self._put(h, last["id"]); continue
                    h["인허가상태"] = "영업"; h["폐업일자"] = ""
                    if how != "같은 인허가":
                        h.update({"인허가id": ld, "인허가업종": rec["인허가업종"], "업태": rec.get("업태구분명") or h["업태"]})
                        if h["출처"] == "상가": h["영업근거"] = "상가+인허가 영업"
                    # 문 닫은 기록 때문에 빠졌던 경우만 되살림 (상호 없음·중복 등록 같은 다른 이유로 빠진 곳은 그대로)
                    if str(h["제외사유"]).startswith("인허가상") or (before == "확인 필요" and not h["제외사유"] and not h.get("업종확인필요") and h["출처"] == "상가"):
                        h["제외사유"] = ""; h["대안후보"] = "예" if not h.get("업종확인필요") else "확인 필요"
                    kind2 = "재개업" if (was_closed or before == "아니요") and h["대안후보"] != "아니요" else "인허가 확인"
                    last = self._event(키=key, 출처=source, 종류=kind2, 상태="반영", fid=f, 상호=h["상호"], 구군=h["구군"], 날짜=rec.get("인허가일자") or "",
                                       근거=src, 원자료=raw, 분류={"업종": h["업종"], "이전대안후보": before, "대안후보": h["대안후보"], "짝": how})
                    self._put(h, last["id"])
                return last
            r, why, base = self.row_from_ld(rec)
            if r is None: return None
            e = self._event(키=key, 출처=source, 종류="신규", 상태="반영", fid=r["fid"], 상호=r["상호"], 구군=r["구군"], 날짜=rec.get("인허가일자") or "",
                            근거=src, 원자료=raw, 분류={"업종": r["업종"], "업종보정": r["업종보정"], "업종확인필요": r["업종확인필요"], "대안후보": r["대안후보"], "기본대안후보": base, "판단": why})
            self._put(r, e["id"]); return e
        return None

    # 같은 자리에서 문을 닫고 새로 연 가게 짝 (알림에 함께 보임)
    def _same_place(self, evs):
        import unit_addr as UA
        opened = [e for e in evs if e["종류"] in ("신규", "재개업", "인허가 확인")]
        closed = [e for e in evs if e["종류"] in ("폐업", "휴업")]
        F = self.F.set_index("fid")
        for c in closed:
            rc = F.loc[c["fid"]]
            for o in opened:
                if o["fid"] == c["fid"]: continue
                ro = F.loc[o["fid"]]
                # 같은 칸(도로명주소 + 층·호가 같음)이고 문 닫은 뒤에 연 가게만 (10/15 고침: 전에는 같은 건물이면 짝지어 이웃 가게가 섞였음. pipeline/unit_addr.py)
                same = UA.same_unit(rc["주소"], ro["주소"]) and UA.opened_after(o.get("날짜"), c.get("날짜"))
                if same:
                    c.setdefault("같은자리", []).append({"fid": o["fid"], "상호": o["상호"], "업종": ro["업종"], "날짜": o["날짜"]})
                    o.setdefault("같은자리", []).append({"fid": c["fid"], "상호": c["상호"], "업종": rc["업종"], "날짜": c["날짜"]})
    def _update_dirs(self):   # 지금까지 받은 새 인허가 폴더들 (오래된 것부터, 쉼표로 이음)
        return ",".join(sorted(os.path.relpath(d, self.root) for d in glob.glob(os.path.join(self.root, "data", "raw", "localdata_updates", "*")) if os.path.isdir(d)))

    # 근거표 다시 만들기 (build_evidence.py를 바뀐 시설에만 돌림): 새 시설과, 인허가가 바뀐 시설 중 아직 문을 연 곳
    #  문 닫은 시설은 원래 근거를 그대로 둠 (그 시설이 하던 일을 알림에 보여 줘야 하므로)
    def _finish_new(self, extra_ld=None):
        todo = [r for r in self.rows.values() if r["대안후보"] != "아니요"]
        if not todo:
            for name, cols in (("overlay_evidence.csv", ["fid", "기능", "항목", "판정", "근거", "출처"]), ("overlay_members.csv", ["code", "fid", "근거", "출처"]), ("overlay_redone.csv", ["fid"])):
                pd.DataFrame(columns=cols).to_csv(os.path.join(self.ch, name), index=False, encoding="utf-8")
        if not todo: return 0
        tmp = os.path.join(self.ch, "_reevaluate.csv"); outd = os.path.join(self.ch, "_evidence"); os.makedirs(outd, exist_ok=True)
        pd.DataFrame(todo, columns=COLS + ["변경id"])[COLS].to_csv(tmp, index=False, encoding="utf-8")
        cmd = [sys.executable, "pipeline/build_evidence.py", "--facilities", tmp, "--out", outd] + (["--localdata", extra_ld] if extra_ld else [])
        r = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True)
        if r.returncode != 0: raise RuntimeError("바뀐 시설 근거표 만들기 실패: " + r.stderr[-800:])
        os.replace(os.path.join(outd, "facility_evidence.csv"), os.path.join(self.ch, "overlay_evidence.csv"))
        os.replace(os.path.join(outd, "evidence_members.csv"), os.path.join(self.ch, "overlay_members.csv"))
        pd.DataFrame({"fid": [r0["fid"] for r0 in todo]}).to_csv(os.path.join(self.ch, "overlay_redone.csv"), index=False, encoding="utf-8")
        from walk import Walk
        W = Walk(self.root); rows = []; base = set(self.F0["fid"])
        for r0 in self.rows.values():
            if r0["fid"] not in base and str(r0["경도"]).strip():
                e, t, d = W._snap_point(float(r0["경도"]), float(r0["위도"])); rows.append({"fid": r0["fid"], "edge": e, "t": round(t, 4), "snap_m": round(d, 1)})
        pd.DataFrame(rows, columns=["fid", "edge", "t", "snap_m"]).to_csv(os.path.join(self.ch, "overlay_walk.csv"), index=False, encoding="utf-8")
        return sum(1 for r0 in self.rows.values() if r0["fid"] not in base)

    def process_localdata(self, new_dir, llm=True):
        recs, missing = self.detect(new_dir)
        if missing: raise RuntimeError(f"새 인허가 자료가 다 받아지지 않음 ({len(missing)}개 없음, 예: {missing[:3]}) — '받기'를 다시 돌려 주세요")
        evs = []; skipped = 0
        recs.sort(key=lambda r: 0 if r["변화"] in ("폐업", "휴업", "말소") else 1)   # 닫은 것 먼저: 같은 가게가 인허가만 새로 받은 경우 '다시 엶'으로 이어지게
        for rec in recs:
            e = self.apply_ld(rec)
            if e: evs.append(e)
            else: skipped += 1
        self._same_place(evs)
        named = self.name_check([e for e in evs if e["종류"] == "신규"]) if llm else {"점검": 0}
        self._save()
        n_new = self._finish_new(self._update_dirs())
        self.state["인허가_기준"] = os.path.relpath(new_dir, self.root); self.state["인허가_기준일"] = os.path.basename(new_dir)
        self._save()
        c = {}
        for e in evs: c[e["종류"]] = c.get(e["종류"], 0) + 1
        return {"인허가 변화": len(recs), "반영": len(evs), "생활시설과 관계없음·이미 반영": skipped, "종류별": c, "새 시설": n_new, "상호 점검": named}

    # 폐업 시설 분류 점검 (10/19 헌준님: 새로 확인한 폐업 시설도 우리 분류 체계로 이어서, 그곳이 하던 주~부 기능을 바르게 알고 대안을 찾도록)
    #  폐업 목록에 든 곳 가운데 아직 상호를 점검하지 않은 곳을 새 가게 상호 점검과 같은 2단계(Sonnet → Opus 확인)로 봄
    #  업종이 상호와 다르면 바로잡고(하는 일이 따라 바뀜), 주민이 찾아가는 생활시설이 아니면(공장·도매·사무실) 폐업 지도에서 뺌
    #  한 번에 많이 하지 않음 (아침 보고가 늦어지지 않게, 하루 최대 limit곳). 점검 결과는 data/changes/closure_names.json
    def closure_check(self, limit=60):   # 하루 60곳 (10/21: 200곳은 7분·비용이 커서 줄임. 새 폐업은 하루 20~30곳이라 밀린 것도 며칠 안에 끝남)
        p = os.path.join(self.root, "data", "changes", "closure_names.json")
        done = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
        cp = os.path.join(self.root, "data", "processed", "closures.csv")
        fids = list(pd.read_csv(cp, dtype=str).sort_values("폐업일자", ascending=False)["fid"]) if os.path.exists(cp) else []   # 최근에 닫은 곳부터
        fids += [f for f, r in self.rows.items() if "확인: 문 닫음" in str(r.get("제외사유", ""))]
        F = self.F; todo = []
        if F.index.name != "fid" and "fid" in F.columns: F = F.set_index("fid", drop=False)
        for f in dict.fromkeys(fids):
            if f in done or f not in F.index: continue
            r = F.loc[f]; todo.append({"fid": f, "상호": r["상호"], "인허가업종": r.get("인허가업종", ""), "업태": r.get("업태", ""), "업종": r["업종"]})
        todo = todo[:limit]; ch = {"점검": len(todo), "업종 바꿈": 0, "생활시설 아님": 0}
        if not todo: return ch
        from change_agent import NameCheck
        res = NameCheck(self.root).run(todo)
        for x in todo:
            v = res.get(x["fid"]) or {"판정": "모름"}
            done[x["fid"]] = {"판정": v.get("판정"), "업종": v.get("업종", ""), "확인": v.get("확인", False), "이유": v.get("이유", "")[:120], "날짜": today()}
            if v.get("판정") not in ("다른 업종", "생활시설 아님") or not v.get("확인"): continue
            r = self.row(x["fid"])
            if v["판정"] == "다른 업종" and v.get("업종") in FR.CODE:
                old = r["업종"]; r["업종코드"] = FR.CODE[v["업종"]]; r["업종"] = v["업종"]
                r["업종보정"] = "; ".join(t for t in (str(r.get("업종보정") or ""), f"{old}→{v['업종']} (폐업 시설 상호 점검, 언어 모델 2단계 확인: {v.get('이유', '')[:60]})") if t and t != "nan")
                ch["업종 바꿈"] += 1
            elif v["판정"] == "생활시설 아님":
                r["업종확인필요"] = f"상호 점검: 주민이 찾아가는 생활시설이 아님 ({v.get('이유', '')[:60]})"; ch["생활시설 아님"] += 1
            e = self._event(키=f"폐업분류|{x['fid']}|{today()}", 출처="폐업 시설 상호 점검", 종류="분류 점검", 상태="반영", fid=x["fid"], 상호=r["상호"], 구군=r["구군"], 날짜=today(),
                            근거=v.get("이유", ""), 분류={"업종": r["업종"], "대안후보": r["대안후보"]})
            self._put(r, e["id"])
        json.dump(done, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        self._save()
        return ch

    # 새 가게 상호 점검 (언어 모델 2단계, engine/change_agent.py): 규칙으로 못 정한 업종을 상호로 정하고, 생활시설이 아닌 곳을 걸러냄
    def name_check(self, evs):
        items = []
        for e in evs:
            r = self.rows.get(e["fid"])
            if not r or r["대안후보"] == "아니요": continue
            items.append({"fid": r["fid"], "상호": r["상호"], "인허가업종": r["인허가업종"], "업태": r["업태"], "업종": r["업종"]})
        if not items: return {"점검": 0}
        from change_agent import NameCheck
        res = NameCheck(self.root).run(items); ch = {"점검": len(items), "업종 바꿈": 0, "생활시설 아님": 0, "1차만 지적(그대로 둠)": 0}
        for e in evs:
            x = res.get(e["fid"])
            if not x: continue
            e["분류"]["상호 점검"] = x
            if x["판정"] not in ("다른 업종", "생활시설 아님"): continue
            if not x["확인"]: ch["1차만 지적(그대로 둠)"] += 1; continue
            r = self.rows[e["fid"]]; base = e["분류"].get("기본대안후보", "확인 필요")
            if x["판정"] == "다른 업종":
                old = r["업종"]; r["업종코드"] = FR.CODE[x["업종"]]
                r["업종보정"] = "; ".join(v for v in (r["업종보정"], f"{old}→{x['업종']} (상호, 언어 모델 2단계 확인: {x['이유']})") if v)
                if str(r.get("업종확인필요", "")).startswith("인허가 업태만으로는"): r["업종확인필요"] = ""
                r, why = self.classify_row(r, base); ch["업종 바꿈"] += 1
                e["분류"].update({"업종": r["업종"], "업종보정": r["업종보정"], "업종확인필요": r["업종확인필요"], "대안후보": r["대안후보"]})
                e["분류"]["판단"] = e["분류"].get("판단", []) + [f"상호로 업종 바꿈: {old} → {x['업종']} (언어 모델 2단계 확인)"]
            else:
                r["업종확인필요"] = f"상호 점검: 주민이 찾아가는 생활시설이 아님 ({x['이유']})"
                if r["대안후보"] == "예": r["대안후보"] = "확인 필요"
                ch["생활시설 아님"] += 1
                e["분류"].update({"업종확인필요": r["업종확인필요"], "대안후보": r["대안후보"]})
            self._put(r, e["id"])
        return ch

    # ---------------- 문 닫음 다시 판정 ----------------
    def recheck(self, d=None):
        """모든 시설의 문 닫음 판정을 최신 인허가 자료로 다시 봄 (pipeline/permit_status.py 원칙). 바뀐 것만 반영하고 기록을 남김
        예전 자료는 시설과 짝지은 인허가 하나만 보고 폐업을 정했음 → 담배 인허가만 닫힌 편의점, 주인이 바뀌어 인허가를 다시 받은 가게가 '문 닫음'이 됨"""
        import fetch_localdata as FL
        from permit_status import UNSURE_DAYS
        P = self.load_permits(d); slugs = set(FL.SLUG); cnt = {}
        src = f"인허가 재판정 (지방행정 인허가 {os.path.basename(self._permits_dir)} 자료의 같은 가게 인허가 모두)"
        tdy = datetime.date.fromisoformat(today())
        decided = {e["fid"] for e in self.events if str(e.get("출처", "")).startswith("담당자") or e.get("확인")}   # 담당자가 확인한 곳은 그 판단을 따름
        for r0 in self.F[self.F["인허가id"] != ""][COLS].to_dict("records"):
            lid = r0["인허가id"]
            if r0["fid"] in decided: continue
            if lid.split(":")[0] not in slugs or str(r0["인허가상태"]).startswith("심평원") or r0["출처"] not in ("상가", "인허가"): continue
            s0 = P.state(lid)
            if s0 is None: continue
            closed = r0["인허가상태"] in ("폐업", "휴업", "말소 등"); unsure = str(r0["제외사유"]).startswith("인허가가 엇갈림")
            if s0 == "영업":
                if unsure: v, why, left, day = "영업", "짝지은 인허가가 다시 영업", [], ""
                else: continue
            else:
                nm, ad = self._ld_name.get(lid) or r0["상호"], self._ld_addr.get(lid) or r0["주소"]
                if "*" in ad: ad = r0["주소"]   # 가려진 주소면 시설 주소로
                day = P.last_close(lid, nm, ad, self._close_day.get(lid, "") or r0["폐업일자"])
                try: old = (tdy - datetime.date.fromisoformat(str(day)[:10])).days > UNSURE_DAYS
                except Exception: old = True
                if old and closed and not unsure: continue   # 아주 오래전 폐업은 그대로
                v, why, left = P.verdict(lid, nm, ad, day)
            want = {"폐업": closed and not unsure, "확인 필요": unsure, "영업": not closed and not unsure}[v]
            if want and v == "영업" and left and left[0] != lid and s0 != "영업":   # 이미 영업으로 되살린 곳: 짝지은 인허가를 새 인허가로 바꿔 둠
                r = self.row(r0["fid"]); r["인허가id"] = left[0]; r["인허가업종"] = FL.SLUG.get(left[0].split(":")[0], r["인허가업종"])
                e = self._event(키=f"재판정|{r0['fid']}|인허가|{left[0]}", 출처="인허가 재판정", 종류="인허가 확인", 상태="반영", fid=r["fid"], 상호=r["상호"], 구군=r["구군"], 날짜="",
                                근거=src + " / 짝지은 인허가를 새 인허가로 바꿈", 분류={"업종": r["업종"], "이전대안후보": r["대안후보"], "대안후보": r["대안후보"]})
                self._put(r, e["id"]); continue
            if want: continue
            key = f"재판정|{r0['fid']}|{v}|{day}"
            if any(e.get("키") == key for e in self.events): continue
            r = self.row(r0["fid"]); before = r["대안후보"]
            if v == "영업":
                r["인허가상태"] = "영업"; r["폐업일자"] = ""
                if left and left[0] != lid: r["인허가id"] = left[0]; r["인허가업종"] = FL.SLUG.get(left[0].split(":")[0], r["인허가업종"])
                if str(r["제외사유"]).startswith(("인허가상", "인허가가 엇갈림")):
                    r["제외사유"] = ""; r["대안후보"] = "확인 필요" if r.get("업종확인필요") else "예"
                e = self._event(키=key, 출처="인허가 재판정", 종류="재개업", 상태="반영", fid=r["fid"], 상호=r["상호"], 구군=r["구군"], 날짜="",
                                근거=src + " / " + why, 분류={"업종": r["업종"], "이전대안후보": before, "대안후보": r["대안후보"]})
            else:
                st = "말소 등" if s0 not in ("폐업", "휴업") else s0
                r["인허가상태"] = st; r["폐업일자"] = str(day)[:10] or r["폐업일자"]; r["대안후보"] = "아니요"
                r["제외사유"] = (f"인허가상 {st} ({str(day)[:10]}) — 인허가 재판정" if v == "폐업" else "인허가가 엇갈림 — " + why)
                e = self._event(키=key, 출처="인허가 재판정", 종류="폐업", 상태="반영" if v == "폐업" else "확인 필요", fid=r["fid"], 상호=r["상호"], 구군=r["구군"],
                                날짜=str(day)[:10], 근거=src + " / " + why, 분류={"업종": r["업종"], "이전대안후보": before, "남은인허가": left})
            self._put(r, e["id"]); cnt[v] = cnt.get(v, 0) + 1
        if cnt: self._save()
        return {"다시 영업으로": cnt.get("영업", 0), "문 닫음으로": cnt.get("폐업", 0), "확인 필요로": cnt.get("확인 필요", 0)}

    # ---------------- 영향 계산과 알림 ----------------
    PERMITS = [("상비약판매", "PERMIT:상비약판매"), ("종량제봉투판매", "PERMIT:종량제봉투판매"), ("공원운동시설", "PERMIT:공원운동시설")]
    def engine(self, reload=False):
        if self._E is None or reload:
            from recommend import Engine
            from impact import Coverage
            self._E = Engine(self.root); self._C = Coverage(self._E.walk); self._prov = {}
        return self._E

    def served(self, fid, only_codes=None):
        """시설이 하는(하던) 일: 엔진의 같은 함수 (판정 '근거'·'강함'·'업종'을 실제로 하던 일로 봄)"""
        return self.engine().served(fid, only_codes)
    def does(self, fid, lid, k, nd): return self.engine().does(fid, lid, k, nd)   # 엔진과 같은 판정 (주민 화면과 맞물림)
    def providers_broad(self, lid, k, nd):
        """넓게 본 '하는 곳': 확실한 곳 + 그 일을 하는지 모르는 곳(판정 '모름', 예: 작은 슈퍼의 신선식품) + 영업하는지 확인 안 된 곳(대안후보 '확인 필요').
        생활 공백이 이 넓은 범위로 봐도 남는지 → '긴급'은 확인이 필요 없을 만큼 분명할 때만 (지자체 에이전트)"""
        key = ("넓게", lid, k, nd)
        if key not in self._prov:
            E = self.engine(); pool = E.kind[(lid, k)]["fids"] if k else E.leaf_pool(lid)
            S = E.F.loc[sorted(pool)]
            S = S[S["대안후보"].isin(["예", "확인 필요"]) & S["x"].notna() & ~S["인허가상태"].isin(["폐업", "휴업", "말소 등"])]
            # '확인 필요' 가운데 넣는 것: 인허가는 영업 중인데 가게(상가 자료)를 못 찾은 곳만
            #  - 인허가가 있어야 하는 업종인데 인허가가 없는 곳('본업 인허가 없음', 예: 심평원에 없는 약국)은 영업하지 않을 가능성이 커서 뺌
            #  - 가게 없이 인허가만 있는 회사 이름(주식회사·유통·농업회사법인 등)은 도매·가공일 가능성이 커서 뺌
            unsure = S["대안후보"] == "확인 필요"
            ok_unsure = (S["영업근거"] == "인허가만(영업 확인 필요)") & ~S["상호"].str.contains(r"\(주\)|㈜|주식회사|유한회사|농업회사법인|영농조합|유통|컴퍼니|시스템|에프앤비|F&B", regex=True, na=False)
            S = S[~unsure | ok_unsure]
            self._prov[key] = [f for f in S.index if self.does(f, lid, k, nd)[0] != "아니요" and _plain(S.at[f, "업종"], S.at[f, "상호"], lid)]
        return self._prov[key]
    def providers(self, lid, k, nd):
        key = (lid, k, nd)
        if key not in self._prov:
            E = self.engine(); pool = E.kind[(lid, k)]["fids"] if k else E.leaf_pool(lid)
            S = E.F.loc[sorted(pool)]; S = S[(S["대안후보"] == "예") & S["x"].notna()]
            self._prov[key] = [f for f in S.index if self.does(f, lid, k, nd)[0] in ("근거", "강함", "업종") and _plain(S.at[f, "업종"], S.at[f, "상호"], lid)]
        return self._prov[key]

    def _alts(self, fid, lid, k, nd, n=3):
        E = self.engine(); r = E.F.loc[fid]
        elig = [kk for (L, kk), v in E.kind.items() if L == lid and v.get("elig")]
        try:
            res = E.recommend(lid, k, float(r["x"]), float(r["y"]), exclude=[fid], n=n, elig_ok=elig, need=nd, user_gu=r["구군"])
        except Exception as ex:
            return [], f"대체 시설을 찾지 못함 ({ex})"
        cards = res["추천"][:n]
        more = [dict(c, 확인필요=True) for c in res["제공여부확인필요"]][:max(0, n - len(cards))]
        keep = ("fid", "상호", "업종", "주소", "전화", "걷는거리_m", "걷는시간_분", "직선거리_m", "세부종류", "표시", "근거자료")
        return [{kk: c.get(kk) for kk in keep + ("확인필요",)} for c in cards + more], ""

    def _func_block(self, fid, lid, k, nd, st, why, mode, was_provider):
        """기능 하나에 대한 영향: 세 단계로 잼
           종류: 같은 세부 종류 (주민 대화에서 처음 안내하는 범위) / 묶음: 사람이 확인한 같은 종류 묶음 (주민 동의 후 넓히는 범위) / 기능 전체: 그 일을 하는 모든 곳"""
        from impact import threshold
        E = self.engine(); C = self._C; l = E.leaf[lid]; r = E.F.loc[fid]
        thr, basis = threshold(l); gu = r["구군"] if lid == "P02.1.07" else None
        snap = E.walk.snap.get(fid)
        if k:
            grp = E.kind[(lid, k)]["group"]
            levels = [("종류", k, [k]), ("묶음", grp, [kk for (L, kk), v in E.kind.items() if L == lid and v["group"] == grp]),
                      ("기능 전체", l["name"], [kk for (L, kk) in E.kind if L == lid])]
        else: levels = [("기능 전체", l["name"], [None])]
        imp = {}; seen = {}
        for lv, label, kinds in levels:
            prov = sorted({f for kk in kinds for f in self.providers(lid, kk, nd)} - {fid})
            if gu: prov = [f for f in prov if E.F.at[f, "구군"] == gu]
            key = tuple(prov)
            if key in seen: imp[lv] = dict(seen[key], 범위=label, 같은범위=True); continue   # 묶음에 종류가 하나뿐이면 같은 값
            x = C.impact([E.walk.snap.get(f) for f in prov], snap, thr, mode, gu) if (snap and was_provider) else None
            if x is not None: x = dict(x, 범위=label, 시설수=len(prov)); seen[key] = x
            imp[lv] = x
        alts, err = self._alts(fid, lid, k, nd) if mode == "closed" else ([], "")
        cat = next(c["name"] for c in E.T["categories"] if any(lid in [x["id"] for x in q["leaves"]] for q in c["purposes"]))
        return {"기능": lid, "이름": l["name"], "분야": cat, "등급": l.get("grade"), "세부종류": k, "묶음": levels[1][1] if k else None, "의도": nd, "판정": st, "판정근거": list(why),
                "기준_분": thr, "기준근거": basis, "영향": imp.get("종류") or imp.get("기능 전체"), "영향_묶음": imp.get("묶음"), "영향_기능전체": imp.get("기능 전체"),
                "대체시설": alts, "대체시설_오류": err, "이용방법": [m for m in l.get("modes", []) if m != "직접 방문"]}
    @staticmethod
    def _level(funcs, mode):
        """알림 등급 (현장 판단, 바꿀 수 있음)
        긴급: 필수 기능이 '기능 전체'로 봐도 기준 시간 안에서 끊기는 주민이 ALERT_POP명 이상
        주의: 준필수 기능이 '기능 전체'로 끊기는 주민이 ALERT_POP명 이상, 또는 필수 기능의 '같은 묶음'(사람이 확인한 대체 범위)이 끊기는 주민이 ALERT_POP명 이상
        좋은 소식(새 시설): 위와 같은 기준으로 공백이 메워짐 / 참고: 그 밖 (같은 종류만 끊기는 경우 등은 알림 본문에 숫자로 보임)"""
        lv = "참고"
        for f in funcs:
            g = f["등급"]; a = (f["영향_기능전체"] or {}).get("공백변화주민", 0); b = (f["영향_묶음"] or f["영향_기능전체"] or {}).get("공백변화주민", 0)
            if mode == "closed":
                if g == "필수" and a >= ALERT_POP: return "긴급"
                if (g == "준필수" and a >= ALERT_POP) or (g == "필수" and b >= ALERT_POP): lv = "주의"
            elif (g in ("필수", "준필수") and a >= ALERT_POP) or (g == "필수" and b >= ALERT_POP): lv = "좋은 소식"
        return lv
    def notice_for(self, e):
        """변화 기록 하나 → 알림 (만들 필요가 없으면 None)"""
        E = self.engine(); fid = e["fid"]
        if fid not in E.F.index: return None
        r = E.F.loc[fid]; kind = e["종류"]
        if kind in ("폐업", "휴업") and e["상태"] == "반영" and r["대안후보"] != "아니요": return None   # 같은 가게가 인허가를 새로 받아 다시 엶 (요약에만)
        if kind in ("폐업", "휴업") or e["상태"] == "확인 필요": mode = "closed"
        elif kind == "기능 중단": mode = "closed"
        else: mode = "opened"
        only = None
        if kind in ("기능 추가", "기능 중단"):
            if r["대안후보"] == "아니요": return None   # 가게가 문을 닫으면서 함께 닫은 인허가 (가게 폐업 알림에 들어 있음)
            only = [c for col, c in self.PERMITS if col == e["분류"]["인허가"]]
        before = (e.get("분류") or {}).get("이전대안후보") or (e.get("원자료") or {}).get("이전대안후보")
        if kind in ("기능 추가", "기능 중단"): was = r["대안후보"] == "예"
        elif mode == "closed": was = (before or r["대안후보"]) == "예"
        else: was = r["대안후보"] == "예"
        funcs = []; unsure = []
        sv = self.served(fid, only)
        if kind == "기능 중단":   # 인허가를 닫은 뒤라 지금 자료로는 그 일을 안 함 → 그 인허가로 하던 일을 인허가 유형에서 바로 찾음
            sv = {}
            for code in only:
                for f0 in E.func.get(code, []):
                    lid = f0["id"]; ks = (E.leaf[lid].get("kinds") or {})
                    if ks.get("sensitive"):
                        for (L, kk), v in E.kind.items():
                            if L == lid and code in v["types"]: sv[(lid, kk, None)] = ("근거", [E.PERMIT_TEXT.get(code, code)])
                    elif ks.get("sensitive") is False: sv[(lid, None, None)] = ("근거", [E.PERMIT_TEXT.get(code, code)])
        for (lid, k, nd), (st, why) in sv.items():
            if st not in ("근거", "강함", "업종"):
                if st == "모름": unsure.append(E.leaf[lid]["name"] + (f"({', '.join(x for x in (k, nd) if x)})" if (k or nd) else ""))
                continue
            funcs.append(self._func_block(fid, lid, k, nd, st, why, mode, was))
        order = {"필수": 0, "준필수": 1, "선택": 2}
        gap = lambda f, k: (f[k] or {}).get("공백변화주민") or 0
        funcs.sort(key=lambda f: (order.get(f["등급"], 3), -gap(f, "영향_기능전체"), -gap(f, "영향_묶음"), -gap(f, "영향"), -((f["영향"] or {}).get("가까운주민") or 0)))
        lv = self._level(funcs, mode)
        if e["상태"] == "확인 필요": lv = "확인 요청"
        if mode == "opened" and lv != "좋은 소식": return None   # 새 시설은 생활 공백을 메울 때만 따로 알리고, 나머지는 하루 요약에
        gus = sorted({d["구군"] for f in funcs if f["영향"] for d in f["영향"]["행정동"] if d["주민"] >= 1} | {r["구군"]})
        n = {"id": self._new_id("N", self.notices), "변화": e["id"], "만든때": now().isoformat(timespec="seconds"), "등급": lv, "구군": gus,
             "담당분야": sorted({f["분야"] for f in funcs}), "종류": "문 닫음" if mode == "closed" else "새로 엶",
             "시설": {"fid": fid, "상호": r["상호"], "업종": r["업종"], "주소": r["주소"], "구군": r["구군"], "행정동": r["행정동"], "전화": r["전화"],
                     "변화": kind, "날짜": e.get("날짜", ""), "출처": e["출처"], "근거": e.get("근거", ""), "주민안내대상이었음": bool(was)},
             "기능": funcs, "확인안된기능": unsure, "같은자리": e.get("같은자리", []), "인허가": (e.get("분류") or {}).get("인허가"), "읽음": False}
        n["제목"], n["본문"] = self._text(n)
        return n

    def _text(self, n):
        s = n["시설"]; where = " ".join(x for x in (s["구군"], s["행정동"]) if x)
        what = {"상비약판매": "안전상비의약품 판매", "종량제봉투판매": "종량제 봉투 판매", "공원운동시설": "운동시설"}.get(n.get("인허가") or "", "일부 일")
        head = {"폐업": "문을 닫았습니다", "휴업": "쉬고 있습니다(휴업)", "기능 중단": f"{what}{'을' if (ord(what[-1]) - 0xAC00) % 28 else '를'} 그만두었습니다", "신규": "새로 문을 열었습니다", "재개업": "다시 문을 열었습니다",
                "기능 추가": f"{what}{'을' if (ord(what[-1]) - 0xAC00) % 28 else '를'} 시작했습니다", "인허가 확인": "인허가가 새로 확인됐습니다"}.get(s["변화"], s["변화"])
        if n["등급"] == "확인 요청": head = "문을 닫았다는 제보가 있습니다 (확인 전)"
        closed = n["종류"] == "문 닫음"; gw = "갈 곳이 없어지는" if closed else "갈 곳이 새로 생긴"
        def pick(f, least):   # 제목에 쓸 공백: 넓은 범위부터 (기능 전체 → 묶음 → 같은 종류)
            for key in ("영향_기능전체", "영향_묶음", "영향"):
                x = f[key]
                if x and x["공백변화주민"] >= least: return (f["이름"] + " 전체" if key == "영향_기능전체" else x["범위"]), x
            return None
        top = next(((f, pick(f, ALERT_POP)) for f in n["기능"] if pick(f, ALERT_POP)), None) or next(((f, pick(f, 1)) for f in n["기능"] if pick(f, 1)), None)
        title = f"[{n['등급']}] {where} '{s['상호']}' {head}"
        if top: title += f" — {top[1][0]}: 걸어서 {top[0]['기준_분']}분 안에 {gw} 주민 약 {top[1][1]['공백변화주민']:,}명"
        L = [title, "", f"시설: {s['상호']} ({s['업종']})", f"주소: {s['주소'] or '없음'}"]
        if s["전화"]: L.append(f"전화: {s['전화']}")
        L.append(f"변화: {head}" + (f" ({s['날짜']})" if s["날짜"] else "") + f" — 알게 된 곳: {s['출처']}" + (f", {s['근거']}" if s["근거"] else ""))
        if closed and not s["주민안내대상이었음"]:
            L.append("※ 이 시설은 운영 확인이 안 돼 주민에게 대안으로 안내하지 않던 곳이라, 주민 안내 결과는 달라지지 않습니다.")
        for o in n["같은자리"]:
            L.append(f"같은 자리(같은 건물): '{o['상호']}'({o['업종']})" + (" 새로 문을 엶" if closed else " 문을 닫음") + (f" ({o['날짜']})" if o.get("날짜") else ""))
        if not n["기능"]: L += ["", "자료로 확인된 생활기능이 없습니다 (업종만으로는 하는 일이 가게마다 달라 판정하지 않음)."]
        for f in n["기능"]:
            nm = f["이름"] + (f" — {f['세부종류']}" if f["세부종류"] else "") + (f" ({f['의도']})" if f["의도"] else "")
            L += ["", f"■ {nm} [{f['등급']}]" + (f" · 근거: {'; '.join(f['판정근거'])}" if f["판정근거"] else "")]
            i = f["영향"]
            nogap = i and max([(x or {}).get("공백변화주민", 0) for x in (f["영향"], f["영향_묶음"], f["영향_기능전체"])]) < 1
            if nogap:   # 어느 범위로 봐도 공백이 생기지(메워지지) 않음 → 짧게
                L.append(f"  이 시설이 가장 {'가까웠던' if closed else '가까워진'} 주민 약 {i['가까운주민']:,}명 — 걸어서 {f['기준_분']}분 안에 같은 종류의 다른 곳이 {'남아 있어' if closed else '이미 있어'} 생활 공백 변화 없음"
                         + (f" (걷는 시간 중앙값 {i['걷는시간_전_중앙값']}분 → {i['걷는시간_후_중앙값']}분)" if i["걷는시간_전_중앙값"] is not None else ""))
            elif i:
                verb = "가장 가까웠던" if closed else "가장 가까워진"
                L.append(f"  이 시설이 {verb} 주민(추정): 약 {i['가까운주민']:,}명 (65세 이상 {i['가까운주민_65세이상']:,}명)")
                if i["걷는시간_전_중앙값"] is not None:
                    a, b = i["걷는시간_전_중앙값"], i["걷는시간_후_중앙값"]
                    L.append(f"  같은 종류의 가장 가까운 곳까지 걷는 시간(그 주민들의 중앙값): {a}분 → {'6km 넘음' if b is not None and b > 100 else str(b) + '분'}")
                L.append(f"  걸어서 {f['기준_분']}분 안에 {gw} 주민 (기준: {f['기준근거']})")
                rows = [("같은 종류" if f["세부종류"] else f"{f['이름']} 전체", i)]
                if f["세부종류"]:
                    if f["영향_묶음"] and not f["영향_묶음"].get("같은범위"): rows.append((f"같은 묶음({f['묶음']})", f["영향_묶음"]))
                    if f["영향_기능전체"] and not f["영향_기능전체"].get("같은범위"): rows.append((f"{f['이름']} 전체", f["영향_기능전체"]))
                for lab, x in rows:
                    L.append(f"   · {lab}로 보면: 약 {x['공백변화주민']:,}명 (65세 이상 {x['공백변화주민_65세이상']:,}명)")
                ds = [d for d in i["행정동"] if d["공백변화"] >= 1][:5] or i["행정동"][:5]
                if ds: L.append("  행정동별(이 시설이 가장 가까운 주민): " + ", ".join(f"{d['구군']} {d['행정동']} {d['주민']:,}명" + (f"(같은 종류 공백 {d['공백변화']:,}명)" if d["공백변화"] else "") for d in ds))
            if f["대체시설"]:
                L.append("  가까운 대체 시설 (같은 종류):")
                for j, c in enumerate(f["대체시설"], 1):
                    w = f"걸어서 약 {max(1, round(c['걷는시간_분']))}분 ({c['걷는거리_m']:,}m)" if c["걷는거리_m"] is not None else f"직선 {c['직선거리_m']:,}m (걸어가기엔 멂)"
                    L.append(f"   {j}. {c['상호']} ({c['업종']}) — {w}" + (f", {c['전화']}" if c["전화"] else "") + (" · 하는지 확인 필요" if c.get("확인필요") else ""))
            elif closed:
                L.append("  가까운 대체 시설: 없음" + (f" ({f['대체시설_오류']})" if f["대체시설_오류"] else ""))
            big = max([(x or {}).get("공백변화주민", 0) for x in (f["영향"], f["영향_묶음"], f["영향_기능전체"])])
            if closed and big >= 1 and f["이용방법"]:
                L.append(f"  이 일은 직접 가는 것 말고도 {', '.join(f['이용방법'])} 방식으로 이용할 수 있어, 공백 지역에는 이런 방식을 검토할 수 있습니다 (분류표 이용 방법).")
        if n["확인안된기능"]: L += ["", "했을 수도 있지만 자료로 확인되지 않은 일: " + ", ".join(n["확인안된기능"][:8])]
        L += ["", "※ 주민 수는 행정동 인구(2026-09-30)를 그 동의 사람이 사는 곳(가게·버스 정류장 250m 안)에 고르게 나눈 추정입니다. 걷는 시간은 걷는 길 지도로 잰 보통 걸음(1.0m/s) 기준입니다."]
        return title, "\n".join(L)
    def notify(self, budget=150, ids=None):
        """반영한 변화마다 알림을 만듦 (시간 제한 안에서, 남은 것은 다음에)"""
        t0 = time.time(); self.engine(reload=True); made = 0; left = 0
        for e in self.events:
            if e.get("알림") is not None or e["상태"] not in ("반영", "확인 필요"): continue
            if ids and e["id"] not in ids: continue
            if time.time() - t0 > budget: left += 1; continue
            n = self.notice_for(e)
            if n: self.notices.append(n); e["알림"] = n["id"]; made += 1
            else: e["알림"] = "요약에만"
            if made % 10 == 0: self._save()
        self._save()
        return {"알림": made, "남음": left}

    # ---------------- 담당자 입력·주민 제보 ----------------
    def find(self, name, gu=None, dong=None, addr=None, n=5):
        """상호(와 구·군·행정동·주소)로 시설 후보 찾기. 점수 높은 순. 언어 모델은 이 후보 번호 중에서만 고름"""
        from rapidfuzz import process, fuzz
        F = self.F; S = F[F["대안후보"] != "좌표 필요"]
        if gu: S = S[S["구군"] == gu]
        q = norm(name)
        if not q: return []
        names = [norm(x) for x in S["상호"]]
        hits = process.extract(q, names, scorer=fuzz.ratio, limit=300, score_cutoff=55)
        idx = {i: sc for _, sc, i in hits}
        for i, nm in enumerate(names):   # 이름 안에 들어 있음 (예: '행복슈퍼' ↔ '행복슈퍼마켓')
            if len(q) >= 2 and nm and (q in nm or (len(nm) >= 3 and nm in q)): idx[i] = max(idx.get(i, 0), 88)
        import addr_lookup as AL
        ak = AL.key(addr) if addr else None
        out = []
        for i, sc in idx.items():
            r = S.iloc[i]; bonus = 0
            if dong and dong.replace(" ", "") in str(r["행정동"]).replace(" ", ""): bonus += 8
            if ak and AL.key(r["주소"]) == ak: bonus += 15
            elif addr and str(addr).replace(" ", "")[:8] and str(addr).replace(" ", "") in str(r["주소"]).replace(" ", ""): bonus += 10
            out.append({"fid": r["fid"], "상호": r["상호"], "업종": r["업종"], "주소": r["주소"], "구군": r["구군"], "행정동": r["행정동"], "대안후보": r["대안후보"],
                        "출처": r["출처"], "점수": round(min(100, sc + bonus))})
        out.sort(key=lambda x: (-x["점수"], x["대안후보"] != "예"))
        return out[:n]

    def _snapshot(self, fid):
        return dict(self.rows[fid]) if fid in self.rows else None   # 덮어쓰기 전 상태 (None이면 원래 자료 그대로였음)

    def close(self, fid, date="", kind="폐업", source="담당자 입력", note="", who=""):
        """담당자가 알려 준 폐업·휴업 반영 → 영향 알림까지 만듦"""
        r = self.row(fid)
        if r["대안후보"] == "아니요" and (r["제외사유"] or r["인허가상태"] in ("폐업", "휴업", "말소 등")): return {"결과": "이미 문 닫은 시설로 되어 있음", "제외사유": r["제외사유"]}
        before = r["대안후보"]; snap = self._snapshot(fid)
        r["대안후보"] = "아니요"; r["제외사유"] = f"{source}: {kind}" + (f" ({date})" if date else "") + (f" — {note}" if note else "")
        e = self._event(키=f"{fid}|{kind}|{date}|{source}", 출처=source, 종류=kind, 상태="반영", fid=fid, 상호=r["상호"], 구군=r["구군"], 날짜=date, 근거=note or source,
                        원자료={"이전대안후보": before, "이전행": snap, "담당자": who}, 분류={"업종": r["업종"], "이전대안후보": before})
        self._put(r, e["id"]); self._save(); self.notify(ids=[e["id"]])
        return {"결과": "반영", "변화": e["id"], "알림": e["알림"]}

    def report(self, fid, note="", source="주민 제보"):
        """주민 제보: 확인 전까지 '확인 필요'로만 둠 (그동안 주민에게 이곳을 대안으로 안내하지 않음. 단 인허가로 영업이 확인된 일반 가게는 안내 유지). 확인은 AI 교차검증(report_check.py)이 하고,
        분명하지 않은 공공·복지·의료 시설 가운데 공백이 생기는 곳만 담당자에게"""
        r = self.row(fid)
        if r["대안후보"] == "아니요": return {"결과": "이미 안내하지 않는 시설"}
        prev = next((e for e in self.events if e["fid"] == fid and e["상태"] == "확인 필요" and e["출처"] == source), None)
        if prev:   # 같은 곳에 제보가 또 들어오면 모아 둠 (여러 번 들어온 제보는 AI 교차검증의 근거가 됨)
            lst = prev.setdefault("제보목록", [{"날짜": prev.get("날짜"), "내용": prev.get("근거", "")}])
            if len(lst) < 30: lst.append({"날짜": today(), "내용": note or source})
            self._save(); return {"결과": "제보 더함", "변화": prev["id"]}
        if any(e["fid"] == fid and e["상태"] == "확인 필요" for e in self.events): return {"결과": "이미 확인 요청 중"}
        before = r["대안후보"]; snap = self._snapshot(fid)
        keep = keep_on_report(r)   # 인허가로 영업이 확인된 일반 가게: 장난 제보 한 건으로 주민 안내에서 빠지지 않게, AI가 폐업을 확인할 때까지 안내 유지 (10/21)
        if not keep: r["대안후보"] = "확인 필요"
        r["제외사유"] = f"{source}: 문을 닫았다는 제보 ({today()}, 확인 전" + (" · 인허가 영업 중이라 안내 유지)" if keep else ")")
        e = self._event(키=f"{fid}|제보|{today()}", 출처=source, 종류="폐업", 상태="확인 필요", fid=fid, 상호=r["상호"], 구군=r["구군"], 날짜=today(), 근거=note or source,
                        원자료={"이전대안후보": before, "이전행": snap}, 분류={"업종": r["업종"], "이전대안후보": before}, 제보목록=[{"날짜": today(), "내용": note or source}])
        self._put(r, e["id"]); self._save(); self._finish_new(self._update_dirs()); self.notify(ids=[e["id"]])
        return {"결과": "확인 요청", "변화": e["id"], "알림": e["알림"], "안내유지": keep}

    def flag(self, fid, note, source="공식 자료"):
        """공식 자료로 운영 여부가 의심되는 공공 시설 (예: 유치원 정보공시가 멈춤) → '확인 필요'로 두고 담당자 확인을 기다림 (주민 알림은 만들지 않음)"""
        if any(e["fid"] == fid and e["상태"] == "확인 필요" for e in self.events): return {"결과": "이미 확인 요청 중"}
        r = self.row(fid)
        if r["대안후보"] == "아니요": return {"결과": "이미 안내하지 않는 시설"}
        before = r["대안후보"]; snap = self._snapshot(fid)
        r["대안후보"] = "확인 필요"; r["제외사유"] = f"{source}: {note}"
        e = self._event(키=f"{fid}|공식확인|{today()}", 출처=source, 종류="휴업", 상태="확인 필요", fid=fid, 상호=r["상호"], 구군=r["구군"], 날짜=today(), 근거=note,
                        원자료={"이전대안후보": before, "이전행": snap}, 분류={"업종": r["업종"], "이전대안후보": before})
        self._put(r, e["id"]); self._save()
        return {"결과": "확인 요청", "변화": e["id"]}

    def confirm(self, eid, who="", date=""):
        """확인 요청(주민 제보)을 담당자가 '맞다'고 확인 → 문 닫음으로 반영하고 영향 알림"""
        e = next(x for x in self.events if x["id"] == eid)
        if e["상태"] != "확인 필요": return {"결과": f"확인할 것이 아님 ({e['상태']})"}
        r = self.row(e["fid"]); r["대안후보"] = "아니요"; r["제외사유"] = f"{e['출처']} → {who or '담당자'} 확인: 문 닫음" + (f" ({date})" if date else "")
        if not str(r.get("폐업일자") or "").strip() or str(r.get("인허가상태")) not in ("폐업", "휴업", "말소 등"): r["폐업일자"] = date or today()   # 폐업 지도에 넣을 날 (확인한 날)
        old = e["알림"]; e.update({"상태": "반영", "확인": {"담당자": who, "때": now().isoformat(timespec="seconds")}, "알림": None})
        for n0 in self.notices:
            if n0["id"] == old: n0["처리"] = "확인됨"
        self._put(r, e["id"]); self._save(); self.notify(ids=[eid])
        return {"결과": "반영", "변화": eid, "알림": e["알림"]}

    def reject(self, eid, who="", why=""):
        """잘못 들어온 변화를 되돌림 (주민 제보가 틀렸거나 담당자 입력 실수)"""
        e = next(x for x in self.events if x["id"] == eid)
        if e["상태"] == "반려": return {"결과": "이미 되돌림"}
        snap = (e.get("원자료") or {}).get("이전행", "없음")
        if snap == "없음": return {"결과": "이 변화는 되돌릴 수 없음 (자동 감지 변화는 다음 인허가 자료로 바로잡힘)"}
        if snap is None: self.rows.pop(e["fid"], None)
        else: self.rows[e["fid"]] = snap
        e.update({"상태": "반려", "반려": {"담당자": who, "이유": why, "때": now().isoformat(timespec="seconds")}})
        for n0 in self.notices:
            if n0["id"] == e.get("알림"): n0["처리"] = "되돌림"
        self._F = None; self._save(); self._finish_new(self._update_dirs())
        if not self.rows and os.path.exists(os.path.join(self.ch, "overlay_rows.csv")):
            pd.DataFrame(columns=COLS + ["변경id"]).to_csv(os.path.join(self.ch, "overlay_rows.csv"), index=False, encoding="utf-8")
        return {"결과": "되돌림", "변화": eid}

    def reopen(self, fid, date="", source="담당자 입력", who=""):
        """문 닫은 것으로 되어 있던 시설이 다시 문을 엶 (담당자 확인)"""
        r = self.row(fid)
        if r["대안후보"] == "예": return {"결과": "이미 영업 중으로 되어 있음"}
        reason = str(r["제외사유"])
        if not (reason.startswith(("인허가상", "인허가가 엇갈림")) or "폐업" in reason or "휴업" in reason or "문 닫음" in reason or "제보" in reason):
            return {"결과": f"문을 닫아서 빠진 시설이 아님 ({reason or r['대안후보']}) — 다시 열 수 없음"}
        before = r["대안후보"]; snap = self._snapshot(fid)
        r["대안후보"] = "예" if not r.get("업종확인필요") else "확인 필요"; r["제외사유"] = ""
        if r["인허가상태"] in ("폐업", "휴업"): r["인허가상태"] = "영업"; r["폐업일자"] = ""
        e = self._event(키=f"{fid}|재개업|{date}|{source}", 출처=source, 종류="재개업", 상태="반영", fid=fid, 상호=r["상호"], 구군=r["구군"], 날짜=date, 근거=source,
                        원자료={"이전대안후보": before, "이전행": snap, "담당자": who}, 분류={"업종": r["업종"], "이전대안후보": before, "대안후보": r["대안후보"]})
        self._put(r, e["id"]); self._save(); self._finish_new(self._update_dirs()); self.notify(ids=[e["id"]])
        return {"결과": "반영", "변화": e["id"], "대안후보": r["대안후보"], "알림": e["알림"]}

    def add(self, name, address, upjong, lon=None, lat=None, phone="", date="", source="담당자 입력", note="", who=""):
        """담당자가 알려 준 새 시설: 지금의 분류 체계로 분류하고 반영 (생활 공백을 메우면 알림)"""
        code = FR.CODE.get(upjong) or (upjong if upjong in self.engine().func else None)
        if code is None:
            X = {it["name"]: it["code"] for it in json.load(open(os.path.join(self.root, "data", "processed", "extra_type_functions.json"), encoding="utf-8"))["items"] if "name" in it}
            code = X.get(upjong)
        if code is None: return {"결과": f"업종을 알 수 없음: {upjong}"}
        how = "담당자가 알려 준 좌표"
        if lon is None and address:
            lon, lat, how = self.geocode(address)
        r = self._blank(); eid = self._new_id("C", self.events)
        gu = re.search(r"(중구|동구|서구|남구|북구|수성구|달서구|달성군|군위군)", str(address or ""))
        r.update({"fid": "M:" + eid, "출처": "공공" if who == "공식 자료" else "담당자 입력", "상호": name, "업종코드": code, "주소": address or "", "구군": gu.group(1) if gu else "",
                  "경도": lon if lon is not None else "", "위도": lat if lat is not None else "", "전화": phone, "영업근거": f"{source} ({date or today()})"})
        if lon is not None and not r["구군"]: r["구군"] = self.hjd_of(float(lon), float(lat))[0] or ""
        if code in FR.NAME: r, why = self.classify_row(r, "예")
        else:
            r["업종"] = FR.upjong_name(code); r["대안후보"] = "예" if lon is not None else "좌표 필요"; why = []
            if lon is not None: r["행정동"] = self.hjd_of(float(lon), float(lat))[1] or ""
        why = [f"좌표: {how}"] + why
        e = self._event(키=f"{r['fid']}|신규", 출처=source, 종류="신규", 상태="반영", fid=r["fid"], 상호=name, 구군=r["구군"], 날짜=date, 근거=note or source,
                        원자료={"이전행": None, "담당자": who}, 분류={"업종": r["업종"], "업종확인필요": r["업종확인필요"], "대안후보": r["대안후보"], "판단": why})
        self._put(r, e["id"]); self._save(); self._finish_new(self._update_dirs()); self.notify(ids=[e["id"]])
        return {"결과": "반영", "변화": e["id"], "fid": r["fid"], "업종": r["업종"], "대안후보": r["대안후보"], "판단": why, "알림": e["알림"]}

    # ---------------- 요약·알림함 ----------------
    def digest(self, day=None, gu=None):
        day = day or today()
        evs = [e for e in self.events if e["접수"][:10] == day and (gu is None or e["구군"] == gu) and e["상태"] != "반려"]
        nts = [n for n in self.notices if n["만든때"][:10] == day and (gu is None or gu in n["구군"])]
        L = [f"{day} 생활시설 변화 요약 — {gu or '대구 전체'}", ""]
        if not evs: return "\n".join(L + ["반영한 변화가 없습니다."])
        by = {}
        for e in evs: by.setdefault(e["구군"] or "구·군 모름", {}).setdefault(e["종류"] if e["상태"] != "확인 필요" else "확인 요청", []).append(e)
        for g in sorted(by):
            L.append(f"■ {g}: " + ", ".join(f"{k} {len(v)}건" for k, v in sorted(by[g].items(), key=lambda x: -len(x[1]))))
        lv = {}
        for n in nts: lv[n["등급"]] = lv.get(n["등급"], 0) + 1
        L += ["", "알림: " + ", ".join(f"{k} {lv[k]}건" for k in LEVELS if k in lv)]
        for k in LEVELS:
            if k == "참고": continue
            for n in nts:
                if n["등급"] == k: L.append("  " + n["제목"])
        nn = [e for e in evs if e["종류"] == "신규"]
        if nn:
            L += ["", f"새로 생긴 시설 {len(nn)}곳: " + ", ".join(f"{e['상호']}({(e.get('분류') or {}).get('업종', '')})" for e in nn[:30]) + (" …" if len(nn) > 30 else "")]
            chk = [e for e in nn if (e.get("분류") or {}).get("대안후보") == "확인 필요"]
            if chk: L.append(f"  그중 업종·영업 확인이 필요해 주민 안내를 미룬 곳 {len(chk)}곳")
        return "\n".join(L)

    def render_inbox(self, path=None):
        """담당 공무원용 알림함 화면 (data/notices/알림함.html)"""
        path = path or os.path.join(self.note, "알림함.html")
        t = open(os.path.join(self.root, "pipeline", "templates", "inbox_page.html"), encoding="utf-8").read()
        D = {"made": now().strftime("%Y-%m-%d %H:%M"), "base": self.state.get("인허가_기준일", ""), "notices": self.notices}
        open(path, "w", encoding="utf-8").write(t.replace("__DATA__", json.dumps(D, ensure_ascii=False).replace("</", "<\\/")))
        return path

# ---------------- 명령 ----------------
if __name__ == "__main__":
    a = sys.argv[1:]; M = ChangeManager()
    cmd = a[0] if a else "도움말"
    if cmd == "받기": print(json.dumps(M.fetch(budget=float(a[1]) if len(a) > 1 else 150), ensure_ascii=False))
    elif cmd == "감지":
        d = a[1] if len(a) > 1 else sorted(glob.glob(os.path.join(ROOT, "data", "raw", "localdata_updates", "*")))[-1]
        print(json.dumps(M.process_localdata(d, llm="--규칙만" not in a), ensure_ascii=False))
    elif cmd == "알림": print(M.notify(budget=float(a[1]) if len(a) > 1 else 150)); print(M.render_inbox())
    elif cmd == "요약": print(M.digest(a[1] if len(a) > 1 else None, a[2] if len(a) > 2 else None))
    elif cmd == "알림함": print(M.render_inbox())
    elif cmd == "찾기": print(json.dumps(M.find(a[1], a[2] if len(a) > 2 else None), ensure_ascii=False, indent=1))
    elif cmd == "닫기": print(M.close(a[1], a[2] if len(a) > 2 else "")); M.render_inbox()
    elif cmd == "제보": print(M.report(a[1], a[2] if len(a) > 2 else "")); M.render_inbox()
    elif cmd == "확인": print(M.confirm(a[1])); M.render_inbox()
    elif cmd == "되돌리기": print(M.reject(a[1], why=a[2] if len(a) > 2 else "")); M.render_inbox()
    else: print(__doc__ or open(__file__, encoding="utf-8").read().split("import os")[0])
