# 대안 찾기 엔진 (기본형)
# 하는 일: 문 닫은 시설(또는 주민이 말한 목적)의 세부 기능·세부 종류를 알아내고, 같은 종류의 영업 중인 시설을 가까운 순서로 찾는다.
# 안전 규칙(분류표 rules.recommend_safety)을 코드로 지킨다:
#  - 시설은 데이터베이스(facilities.csv)의 ID로만 고르고, 이름·주소·전화는 데이터베이스 값을 그대로 씀 (없는 시설 금지, 정보 섞임 금지)
#  - 대안 후보 '예'만 추천 목록에 넣고, '확인 필요'는 따로 둠 (문 닫은 시설 금지)
#  - 세부 종류가 다른 시설은 넣지 않음. 넓히기(같은 묶음 → 다른 묶음)는 주민 동의가 있을 때만 (안 맞는 시설 금지)
#  - '여러 종류 겸업' 종류와 약한 연결은 근거표(facility_evidence.csv)로 가게마다 판정 (2026-10-14):
#      근거 '예' → 추천 목록 (카드에 근거를 함께 보임) / 근거 '아니요' → 어느 목록에도 넣지 않음 / 근거 없음 → '제공 여부 확인 필요' 목록 (추측 금지)
#  - 근거 유형(EV:) 종류는 자료로 그 일을 하는 것이 확인된 시설만 모은 것이라 추천 목록에 바로 넣고 근거를 보임
#  - 세부 의도(예: 음식 배달·포장의 '배달'/'포장')에 따라 연결의 세기가 다르면, 대화에서 확인한 의도로 판정
#  - '신청·문의 창구' 종류는 그곳에서 서비스를 받는다고 하지 않고 '신청·문의할 곳'으로 표시
#  - 내보내기 직전에 결과 전체를 다시 검사하고, 하나라도 어긋나면 예외를 내고 아무것도 내보내지 않음
import json, os, re, math
import numpy as np, pandas as pd
from rapidfuzz import fuzz
EXPECT = "0.9-draft"
WEAK_CHECKS = ("가게별 확인", "문의 창구", "자료 판정", "항목별")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class SafetyError(Exception):
    pass

def _haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371008.8 * 2 * np.arcsin(np.sqrt(a))

class Engine:
    # overlay: 시설 변화 관리가 반영한 변화(폐업·새 시설·기능 변화, data/changes/)를 얹어서 씀 (False면 원래 자료만)
    def __init__(self, root=ROOT, overlay=True):
        self.root = root
        p = lambda *a: os.path.join(root, *a)
        self.T = json.load(open(p("design", "purpose_taxonomy.json"), encoding="utf-8"))
        assert self.T["version"] == EXPECT, self.T["version"]
        self.leaf = {}; self.purpose_of = {}; self.purpose = {}
        for c in self.T["categories"]:
            for q in c["purposes"]:
                self.purpose[q["id"]] = q
                for l in q["leaves"]:
                    self.leaf[l["id"]] = l; self.purpose_of[l["id"]] = q["id"]
        M = json.load(open(p("data", "processed", "industry_function_map.json"), encoding="utf-8")); assert M["taxonomy_version"] == EXPECT
        X = json.load(open(p("data", "processed", "extra_type_functions.json"), encoding="utf-8")); assert X["taxonomy_version"] == EXPECT
        self.func = {}  # 업종코드·시설유형 → [{id, role, confidence, reason}]
        for it in M["items"]: self.func[it["code"]] = it["functions"]
        for it in X["items"]: self.func[it["code"]] = it["functions"]
        # 근거표: (시설, 기능) → [(항목, 판정, 근거, 출처)] / 근거 유형별 시설: code → {시설: (근거, 출처)}
        self.ev = {}
        EV = pd.read_csv(p("data", "processed", "facility_evidence.csv"), dtype=str, keep_default_na=False)
        import overlay as OV; self.overlay = overlay
        if overlay: EV = OV.apply_evidence(EV, root)
        for f, l, it, v, why, src in zip(EV["fid"], EV["기능"], EV["항목"], EV["판정"], EV["근거"], EV["출처"]):
            self.ev.setdefault((f, l), []).append((it, v, why, src))
        self.evm = {}
        EM = pd.read_csv(p("data", "processed", "evidence_members.csv"), dtype=str, keep_default_na=False)
        if overlay: EM = OV.apply_members(EM, root)
        for c, f, why, src in zip(EM["code"], EM["fid"], EM["근거"], EM["출처"]): self.evm.setdefault(c, {})[f] = (why, src)
        self.needs = {}   # 기능 → 세부 의도 (연결의 check_items에 적힌 것: 예 음식 배달·포장 → 배달, 포장)
        for fs in self.func.values():
            for f in fs:
                if f.get("check_items"): self.needs.setdefault(f["id"], set()).update(f["check_items"])
        F = pd.read_csv(p("data", "processed", "facilities.csv"), dtype=str, keep_default_na=False)
        if overlay: F = OV.apply_rows(F, root)
        F["x"] = pd.to_numeric(F["경도"], errors="coerce"); F["y"] = pd.to_numeric(F["위도"], errors="coerce")
        assert F["fid"].is_unique
        self.F = F.set_index("fid", drop=False)
        self._name = self.F["상호"].str.replace(" ", "", regex=False)          # 같은 가게 겹침 정리용 (이름끼리 비교)
        self._name_sp = self.F["상호"].str.replace(r"\s+", " ", regex=True).str.strip()   # 상호 규칙(pat)은 띄어쓰기를 살려서 읽음 ('파파존스 시지점' ≠ '스시')
        self._build_kind_index()
        from walk import Walk, SPEED
        self.walk = Walk(root); self.SPEED = SPEED   # 걷는 길 계산 (engine/walk.py)
        if overlay: self.walk.snap.update(OV.walk_snaps(root))   # 새 시설을 길에 붙인 지점

    # 세부 종류마다 속한 시설 ID 모음 만들기 (build_kinds.py와 같은 규칙)
    def _members(self, lid, u_or_t, is_type):
        F = self.F
        if is_type:
            t = u_or_t
            if t == "PERMIT:상비약판매": return F["상비약판매"] == "True"
            if t == "PERMIT:종량제봉투판매": return F["종량제봉투판매"] == "True"
            if t == "PERMIT:공원운동시설": return F["공원운동시설"] == "True"
            if t.startswith("EV:"): return pd.Series(F.index.isin(list(self.evm.get(t, {}))), index=F.index)
            return F["업종코드"] == t
        u = u_or_t; m = F["업종코드"] == u["code"]
        same = [v for g in self.leaf[lid]["kinds"]["groups"] for x in g["kinds"] for v in x["upjong"] if v["code"] == u["code"]]
        if u["std"]: m &= F["표준산업분류"].isin(u["std"])
        else:
            claimed = [s for v in same if v["std"] for s in v["std"]]
            if claimed: m &= ~F["표준산업분류"].isin(claimed)
        pats = [v["pat"] for v in same if v.get("pat")]
        if pats:
            hits = pd.DataFrame({q: self._name_sp.str.contains(q, regex=True) for q in pats})
            one = hits.sum(axis=1) == 1
            m &= (one & hits[u["pat"]]) if u.get("pat") else ~one
        return m

    def _build_kind_index(self):
        self.kind = {}      # (lid, kind name) → {"group", "mixed", "contact", "fids"}
        self.of_fid = {}    # fid → [(lid, group, kind)]
        for lid, l in self.leaf.items():
            k = l.get("kinds") or {}
            if not k.get("sensitive"): continue
            for g in k["groups"]:
                for x in g["kinds"]:
                    m = pd.Series(False, index=self.F.index); via = {}   # via: 시설이 어떤 업종·유형으로 이 종류에 들어왔는지
                    for code, mm in [(u["code"], self._members(lid, u, False)) for u in x["upjong"]] + [(t["code"], self._members(lid, t["code"], True)) for t in x["types"]]:
                        via.update({f: code for f in self.F.index[mm & ~m]}); m |= mm
                    fids = set(self.F.index[m])
                    self.kind[(lid, x["name"])] = {"group": g["name"], "mixed": x["mixed"], "mixed_spec": x.get("mixed_spec", x["mixed"]),
                                                   "evidence": x.get("evidence", False), "types": [t["code"] for t in x["types"]],
                                                   "contact": x.get("contact", False), "elig": x.get("elig"), "fids": fids, "via": via}
                    for f in fids: self.of_fid.setdefault(f, []).append((lid, g["name"], x["name"]))

    # 시설 하나가 하던 일 (요약 카드 "이 가게가 하던 일"에 씀)
    # 그 업종·유형이 이 기능을 '주 기능'으로, 확신도 높음·보통으로 하는가 (아니면 약한 연결 → 가게마다 확인 필요)
    # 인허가 표시(PERMIT:)는 허가 자체가 그 일을 한다는 근거라 강한 연결로 봄
    # need: 대화에서 확인한 세부 의도 (예: '배달'/'포장'). 의도별 판정(check_items)이 있는 연결은 의도를 알아야 강한 연결이 될 수 있음
    def strong_link(self, code, lid, need=None):
        if str(code).startswith(("PERMIT:", "LD:", "EV:")): return any(f["id"] == lid for f in self.func.get(code, []))
        for f in self.func.get(code, []):
            if f["id"] != lid: continue
            if f.get("check_items"):
                if need is None: return all(v == "종류로 충분" for v in f["check_items"].values())   # 의도와 상관없이 하는 곳 (예: 중국집은 포장·배달 모두)
                return f["check_items"].get(need) == "종류로 충분"
            if f.get("check") == "종류로 충분": return True      # 약한 연결 판정표: 그 종류면 모두 그 일을 함
            if f.get("check") in WEAK_CHECKS: return False
            return f["role"] == "주" and f["confidence"] in ("높음", "보통")
        return False

    # 이 종류를 찾을 때 세부 의도를 물어야 하는지: 의도에 따라 판정이 갈리는 연결이 있으면 그 의도 목록, 없으면 []
    def need_choices(self, lid, kind):
        v = self.kind.get((lid, kind)); codes = set(v["via"].values()) if v else set()
        out = set()
        for c in codes:
            for f in self.func.get(c, []):
                if f["id"] == lid and f.get("check_items") and len(set(f["check_items"].values())) > 1: out |= set(f["check_items"])
        return sorted(out)

    # 근거표 판정: ("예"|"아니요"|None, [근거 (출처)])
    def evidence(self, fid, lid, item=None):
        rows = [r for r in self.ev.get((fid, lid), []) if r[0] in ("", item or "")]
        yes = [f"{r[2]} ({r[3]})" for r in rows if r[1] == "예"]; no = [f"{r[2]} ({r[3]})" for r in rows if r[1] == "아니요"]
        if yes and no: return None, []     # 자료끼리 어긋나면 단정하지 않음 (예: '키즈 도예 공방' — 어린이 대상이면서 성인 공방 신호) → 확인 필요
        if yes: return "예", yes
        if no: return "아니요", no
        return None, []

    # 시설 하나를 이 기능·종류로 판정: ("근거"|"강함"|"모름"|"아니요", [근거 문장])
    def judge(self, fid, lid, kind, need=None):
        v = self.kind.get((lid, kind)) if kind else None
        if v and v["evidence"]:
            for t in v["types"]:
                if fid in self.evm.get(t, {}):
                    why, src = self.evm[t][fid]; return "근거", [f"{why} ({src})"]
        verdict, why = self.evidence(fid, lid, need)      # 세부 의도별 근거(예: 반찬 가게의 '포장')도 봄
        if verdict == "아니요": return "아니요", why
        if verdict == "예": return "근거", why
        pm = self.permit_proof(fid, lid, v)
        if pm: return "근거", pm
        nw = self._name_proof(fid, lid, kind, need)
        if nw: return "근거", [f"가게 이름에 '{nw}'{'이' if (ord(nw[-1]) - 0xAC00) % 28 else '가'} 들어 있음"]
        if v: strong = not v["mixed_spec"] and (v["contact"] or self.strong_link(v["via"][fid], lid, need))
        else: strong = self._strong_fac(fid, lid, need)
        return ("강함" if strong else "모름"), []

    # 가게 이름이 그 종류를 말해 주는 경우 (예: '반찬/식료품 소매업' 가운데 '월성엄마손반찬' → 반찬가게, 떡집 가운데 '○○방앗간' → 방앗간)
    #  업종만으로는 확실하지 않아 '확인 필요'로 두던 곳 가운데 이름에 종류 낱말이 그대로 든 곳만. 진료·돌봄처럼 자격·면허가 걸린 일은 쓰지 않음
    NAME_STOP = {"가게", "전문", "판매점", "코너", "슈퍼마켓", "슈퍼", "편의점", "병원", "의원", "종합병원", "카페", "식당", "음식점", "소매", "기타", "업소", "가정용", "여러", "종류", "확인", "필요", "미확인"}
    def _name_proof(self, fid, lid, kind, need=None):
        if not kind or need is not None or lid.startswith(("P03", "P04", "P06.3", "P09.3", "P13", "P16")): return None   # 배달·포장 같은 이용 방식은 이름으로 정하지 않음
        up = str(self.F.at[fid, "업종"])
        words = [re.sub(r"(가게|집|점)$", "", w) for w in re.findall(r"[가-힣]{2,}", str(kind))]
        words = [w for w in words if len(w) >= 2 and w not in self.NAME_STOP and w not in up]   # 가게의 업종 이름에 이미 든 낱말(백반집의 '백반')은 증거가 아님
        n = re.sub(r"\s", "", str(self.F.at[fid, "상호"]))
        return next((w for w in words if w in n), None)

    # 인허가 자체가 그 일을 한다는 근거인 경우 (예: 종량제 봉투 판매 허가, 안전상비의약품 판매 허가) — 카드에 근거로 보임
    PERMIT_TEXT = {"PERMIT:상비약판매": "안전상비의약품 판매 인허가 (지방행정 인허가)", "PERMIT:종량제봉투판매": "쓰레기 종량제 봉투 판매 인허가 (지방행정 인허가)",
                   "PERMIT:공원운동시설": "공원 운동시설 (공원 자료)", "LD:반려동물 미용업": "동물미용업 인허가 (지방행정 인허가)", "LD:반려동물 위탁업": "동물위탁관리업 인허가 (지방행정 인허가)"}
    def permit_proof(self, fid, lid, v=None):
        if v is not None:
            c = v["via"].get(fid, "")
            return [self.PERMIT_TEXT[c]] if c in self.PERMIT_TEXT and self.strong_link(c, lid) else []
        r = self.F.loc[fid]
        if self.strong_link(r["업종코드"], lid): return []      # 업종 자체로 하는 곳이면 따로 보이지 않음
        if r["업종코드"] in self.PERMIT_TEXT and self.strong_link(r["업종코드"], lid): return [self.PERMIT_TEXT[r["업종코드"]]]
        for col, code in [("상비약판매", "PERMIT:상비약판매"), ("종량제봉투판매", "PERMIT:종량제봉투판매"), ("공원운동시설", "PERMIT:공원운동시설")]:
            if r[col] == "True" and self.strong_link(code, lid): return [self.PERMIT_TEXT[code]]
        return []

    def _strong_fac(self, fid, lid, need=None):
        r = self.F.loc[fid]
        if self.strong_link(r["업종코드"], lid, need): return True
        return any(r[col] == "True" and self.strong_link(code, lid, need) for col, code in
                   [("상비약판매", "PERMIT:상비약판매"), ("종량제봉투판매", "PERMIT:종량제봉투판매"), ("공원운동시설", "PERMIT:공원운동시설")])

    def functions_of(self, fid):
        r = self.F.loc[fid]; out = []
        codes = [r["업종코드"]] + [c for c, flag in [("PERMIT:상비약판매", r["상비약판매"]), ("PERMIT:종량제봉투판매", r["종량제봉투판매"]), ("PERMIT:공원운동시설", r["공원운동시설"])] if flag == "True"]
        kinds = {lid: (g, k) for lid, g, k in self.of_fid.get(fid, [])}
        for c in codes:
            for f in self.func.get(c, []):
                lid = f["id"]; l = self.leaf[lid]
                g, k = kinds.get(lid, (None, None))
                out.append({"leaf": lid, "name": l["name"], "grade": l.get("grade"), "role": f["role"], "confidence": f["confidence"], "reason": f["reason"],
                            "group": g, "kind": k, "kinds_needed": bool((l.get("kinds") or {}).get("sensitive"))})
        order = {"주": 0, "부": 1}; conf = {"높음": 0, "보통": 1, "낮음": 2}
        return sorted(out, key=lambda d: (order[d["role"]], conf[d["confidence"]]))

    # 이 시설이 실제로 하는(하던) 일 — 주민 화면(문 닫은 곳·대안 카드)과 지자체 에이전트가 같은 함수를 씀 (10/16, 헌준님: 주민과 지자체가 맞물려 작동)
    #  판정: 근거(자료로 확인) / 강함(그 업종이면 그 일을 함) / 업종(여러 가지를 함께 파는 가게지만 업종 자체가 그 일을 주로 함) / 모름 / 아니요
    PERMITS = [("상비약판매", "PERMIT:상비약판매"), ("종량제봉투판매", "PERMIT:종량제봉투판매"), ("공원운동시설", "PERMIT:공원운동시설")]
    def does(self, fid, lid, k, nd):
        st, why = self.judge(fid, lid, k, nd)
        if st != "모름": return st, why
        v = self.kind.get((lid, k)) if k else None
        code = v["via"].get(fid) if v else self.F.at[fid, "업종코드"]
        if code and self.strong_link(code, lid, nd): return "업종", [f"업종({self.F.at[fid, '업종']})이 이 일을 주로 함"]
        return st, why
    def served(self, fid, only_codes=None):
        """{(기능, 세부 종류, 세부 의도): (판정, 근거)}. only_codes: 이 업종·유형으로 생긴 일만"""
        r = self.F.loc[fid]; out = {}
        def add(lid, k):
            ns = sorted(self.needs.get(lid, set()))
            for nd in (ns or [None]): out[(lid, k, nd)] = self.does(fid, lid, k, nd)
        for lid, g, k in self.of_fid.get(fid, []):
            if only_codes and self.kind[(lid, k)]["via"].get(fid) not in only_codes: continue
            add(lid, k)
        codes = only_codes or ([r["업종코드"]] + [c for col, c in self.PERMITS if str(r[col]) == "True"])
        for c in codes:
            for f in self.func.get(c, []):
                lid = f["id"]
                if (self.leaf[lid].get("kinds") or {}).get("sensitive") is False and not any(key[0] == lid for key in out): add(lid, None)
        return out
    _cap = None
    def scale(self, fid):
        """시설 규모 (장기요양기관 정원·인력, 국민건강보험공단 2026.6 지정자료). 모르면 None"""
        if self._cap is None:
            p = os.path.join(self.root, "data", "processed", "ltc_capacity.csv")
            try: self._cap = {r["fid"]: r for r in pd.read_csv(p).to_dict("records")}
            except Exception: self._cap = {}
        r = self._cap.get(fid)
        if not r:   # 유치원·어린이집 (10/20): 정원과 현재 다니는 아이 수 (pipeline/build_child_capacity.py)
            if getattr(self, "_ccap", None) is None:
                try: self._ccap = {x["fid"]: x for x in pd.read_csv(os.path.join(self.root, "data", "processed", "child_capacity.csv")).to_dict("records")}
                except Exception: self._ccap = {}
            c = self._ccap.get(fid)
            if not c: return None
            ok = lambda v: v == v and v is not None and v > 0
            parts = ([f"정원 {int(c['정원'])}명"] if ok(c.get("정원")) else []) + ([f"다니는 아이 {int(c['현원'])}명"] if ok(c.get("현원")) else [])
            return {"글": " · ".join(parts), "정원": int(c["정원"]) if ok(c.get("정원")) else None, "현원": int(c["현원"]) if ok(c.get("현원")) else None, "출처": c["출처"]} if parts else None
        parts = []
        if r.get("정원") == r.get("정원") and (r.get("정원") or 0) > 0: parts.append(f"정원 {int(r['정원'])}명")
        if r.get("요양보호사") == r.get("요양보호사") and (r.get("요양보호사") or 0) > 0: parts.append(f"요양보호사 {int(r['요양보호사'])}명")
        return {"글": " · ".join(parts), "정원": int(r["정원"]) if r.get("정원") == r.get("정원") and r.get("정원") else None,
                "출처": "국민건강보험공단 장기요양기관 지정자료 (2026.6)"} if parts else None
    def what_it_does(self, fid):
        """사람이 읽는 '이 곳이 하는(하던) 일': 공공 목적 여부(근거 법령)와 근거를 함께. 같은 일의 세부 의도(포장·배달)는 하나로 묶음"""
        import public_basis as PB
        if fid not in self.F.index: return []
        best = {}; rank = {"근거": 0, "강함": 1, "업종": 2}
        for (lid, k, nd), (st, why) in self.served(fid).items():
            if st not in rank: continue
            cur = best.get(lid)
            if cur is None or rank[st] < rank[cur["판정"]]:
                l = self.leaf[lid]
                why = list(why)[:2]
                if not why:   # 업종으로 하는 일 (예: '약국은 이 일을 하는 곳')
                    u = str(self.F.at[fid, "업종"]); last = u[-1:] if u else ""
                    jo = ("은" if (ord(last) - 0xAC00) % 28 else "는") if "가" <= last <= "힣" else "은(는)"
                    why = [f"{u}{jo} 이 일을 하는 곳 (업종)"]
                best[lid] = {"기능": lid, "이름": l["name"], "등급": l.get("grade"), "세부종류": k, "판정": st, "근거": why, "공공": PB.info(lid, k)}
        order = {"필수": 0, "준필수": 1, "선택": 2}
        return sorted(best.values(), key=lambda d: (d["공공"] is None, order.get(d["등급"], 3), rank[d["판정"]]))

    # 세부 종류 구분이 필요 없는 기능: 이 기능을 하는 업종·유형의 시설 전체 (대안 찾기와 시설 변화 관리가 함께 씀)
    def leaf_pool(self, lid):
        codes = {c for c, fs in self.func.items() if any(f["id"] == lid for f in fs)}
        m = self.F["업종코드"].isin(codes)
        for t in [c for c in codes if c.startswith("PERMIT:")]: m |= self._members(lid, t, True)
        return set(self.F.index[m])

    # 대안 찾기
    # scope: "kind"(같은 세부 종류) | "group"(같은 묶음, 주민 동의 필요) | "leaf"(다른 묶음까지, 주민이 따로 원할 때만)
    def recommend(self, lid, kind, lon, lat, scope="kind", consent_group=False, consent_leaf=False, exclude=(), user_gu=None, n=5, max_m=None, elig_ok=(), speed="보통", need=None, name_words=None):
        # name_words: 이 낱말이 상호에 든 가게만 (주민 바람에 맞는 이름, engine/wants.py가 정한 낱말로 더 넓게 찾을 때)
        # need: 세부 의도 (예: 음식 배달·포장의 '배달'/'포장'). 이 기능에 정해진 의도만 받음
        if need is not None and need not in self.needs.get(lid, set()): raise SafetyError(f"{lid}에 없는 세부 의도: {need}")
        # speed: 대화에서 확인한 주민의 걸음 (보통 / 천천히 / 아주 천천히)
        if speed not in self.SPEED: raise SafetyError(f"알 수 없는 걸음 속도: {speed}")
        # elig_ok: 대화에서 주민의 이용 자격이 확인된 세부 종류 이름들 (예: 장기요양 등급이 있다고 답함)
        if lid not in self.leaf: raise SafetyError(f"분류표에 없는 기능: {lid}")
        l = self.leaf[lid]; ks = l.get("kinds") or {}
        if ks.get("sensitive"):
            if (lid, kind) not in self.kind: raise SafetyError(f"{lid}에 없는 세부 종류: {kind}")
            grp = self.kind[(lid, kind)]["group"]
            if scope == "kind": allowed = [kind]
            elif scope == "group":
                if not consent_group: raise SafetyError("같은 묶음으로 넓히려면 주민 동의가 필요함")
                allowed = [k for (L, k), v in self.kind.items() if L == lid and v["group"] == grp]
            elif scope == "leaf":
                if not consent_leaf: raise SafetyError("다른 묶음까지 넓히려면 주민이 따로 원해야 함")
                allowed = [k for (L, k) in self.kind if L == lid]
            else: raise SafetyError(f"알 수 없는 범위: {scope}")
            pool = set().union(*[self.kind[(lid, k)]["fids"] for k in allowed])
            kind_of = {f: k for k in allowed for f in self.kind[(lid, k)]["fids"]}
        elif ks.get("sensitive") is False:
            # 세부 종류 구분이 필요 없는 기능: 이 기능을 하는 업종·유형 전체
            pool = self.leaf_pool(lid); allowed = [None]; kind_of = {f: None for f in pool}

        else:
            raise SafetyError(f"{lid}({l['name']})은 아직 연결된 시설이 없음 — 추천하지 않음")
        # 가게마다 판정 (근거 '아니요'는 어느 목록에도 넣지 않음)
        J = {f: self.judge(f, lid, kind_of[f], need) for f in pool}
        ruled_out = {f for f, (st, _) in J.items() if st == "아니요"}
        S = self.F.loc[sorted(pool - set(exclude) - ruled_out)]
        S = S[S["x"].notna()]
        if name_words:
            nm = S["상호"].astype(str).str.replace(r"\s", "", regex=True)
            S = S[nm.apply(lambda x: any(w in x for w in name_words))]
        if lid == "P02.1.07":  # 종량제 봉투는 사는 곳의 구·군 것만 쓸 수 있음
            if not user_gu: raise SafetyError("종량제 봉투는 주민의 구·군을 알아야 찾을 수 있음")
            S = S[S["구군"] == user_gu]
        d = _haversine(lon, lat, S["x"].values, S["y"].values)
        S = S.assign(직선거리_m=np.round(d).astype(int)).sort_values("직선거리_m")
        if max_m: S = S[S["직선거리_m"] <= max_m]
        WALK = {}
        def nearest(df, k):
            # 걷는 거리로 가까운 k곳. 걷는 거리는 직선거리보다 짧을 수 없으므로, 직선거리 순으로 늘려 가다가
            # 다음 후보의 직선거리가 지금 k번째 걷는 거리보다 멀면 멈춤 (빠뜨리는 곳 없이 정확함)
            if df.empty: return df
            got = []; i = 0; step = max(20, k * 4); rows = df.reset_index(drop=True)
            while i < len(rows):
                chunk = rows.iloc[i:i + step]; i += step
                need = [f for f in chunk["fid"] if f not in WALK]
                if need: WALK.update(self.walk.distances(lon, lat, need, max_m=8000))
                got = sorted([(WALK[f], f) for f in rows["fid"].iloc[:i] if WALK[f] is not None])
                if len(got) >= k and i < len(rows) and rows["직선거리_m"].iloc[i] > got[k - 1][0]: break
                if i >= 400 and len(got) >= k: break   # 아주 먼 후보까지는 보지 않음
            order = []
            for _, f in got:   # 같은 가게(띄어쓰기 뺀 이름이 같거나 오타 정도로만 다르고 30m 안)는 한 번만
                r0 = self.F.loc[f]; n0 = self._name.loc[f]
                if any((self._name.loc[g] == n0 or fuzz.ratio(self._name.loc[g], n0) >= 85) and _haversine(r0["x"], r0["y"], self.F.loc[g, "x"], self.F.loc[g, "y"]) < 30 for g in order): continue
                order.append(f)
                if len(order) == k: break
            if len(order) < k:  # 길로 이어지지 않거나 8km 넘는 곳은 직선거리 순으로 뒤에 붙임 (걷는 거리 '계산 안 됨')
                order += [f for f in rows["fid"] if WALK.get(f) is None and f not in order][:k - len(order)]
            return df.set_index("fid", drop=False).loc[order]
        def card(r):
            k = kind_of[r["fid"]]; v = self.kind.get((lid, k), {})
            return {"fid": r["fid"], "상호": r["상호"], "업종": r["업종"], "주소": r["주소"], "전화": r["전화"], "경도": float(r["x"]), "위도": float(r["y"]),
                    "직선거리_m": int(r["직선거리_m"]), "걷는거리_m": None if WALK.get(r["fid"]) is None else int(round(WALK[r["fid"]])),
                    "걷는시간_분": self.walk.minutes(WALK.get(r["fid"]), speed), "걸음": speed, "세부종류": k, "묶음": v.get("group"),
                    "표시": [s for s, on in [("신청·문의 창구", v.get("contact")), ("제공 여부 확인 필요", J[r["fid"]][0] == "모름"),
                                            ("오래된 폐업 기록", r["인허가상태"] in ("폐업", "휴업", "말소 등")),
                                            ("걸어서 가기 먼 거리(8km 넘거나 길로 이어지지 않음)", WALK.get(r["fid"]) is None)] if on]
                          + ([f"이용 자격: {v['elig']}"] if v.get("elig") else []),
                    "안내": "이곳은 서비스를 직접 하는 곳이 아니라 신청·문의하는 곳입니다" if v.get("contact") else "",
                    "참고": r["참고"], "근거": r["영업근거"], "근거자료": list(J[r["fid"]][1])}
        ok = S[S["대안후보"] == "예"]
        elig_k = {k for k in allowed if k and self.kind[(lid, k)].get("elig") and k not in elig_ok}
        is_m = ok["fid"].map(lambda f: J[f][0] == "모름"); is_e = ok["fid"].map(lambda f: kind_of[f] in elig_k)
        main = [card(r) for _, r in nearest(ok[~is_m & ~is_e], n).iterrows()]
        unconfirmed = [card(r) for _, r in nearest(ok[is_m & ~is_e], n).iterrows()]
        need_elig = [card(r) for _, r in nearest(ok[is_e], n).iterrows()]
        need_check = [card(r) for _, r in nearest(S[S["대안후보"] == "확인 필요"], n).iterrows()]
        res = {"기능": lid, "기능이름": l["name"], "세부종류": kind, "범위": scope, "허용종류": allowed,
               "_출발": (lon, lat), "의도": need, "근거로제외": len(ruled_out), "추천": main, "제공여부확인필요": unconfirmed, "이용자격확인필요": need_elig, "운영확인필요": need_check, "자격확인됨": sorted(elig_ok),
               "확인할것": ks.get("check", ""), "대체가능목적": bool(self.purpose[self.purpose_of[lid]].get("substitutable"))}
        self.verify(res, exclude, user_gu)
        return res

    # 내보내기 직전 검사: 하나라도 어긋나면 전체를 내보내지 않음
    def verify(self, res, exclude=(), user_gu=None):
        lid = res["기능"]
        for lst, need in [("추천", "예"), ("제공여부확인필요", "예"), ("이용자격확인필요", "예"), ("운영확인필요", "확인 필요")]:
            for c in res[lst]:
                f = c["fid"]
                if f not in self.F.index: raise SafetyError(f"데이터베이스에 없는 시설: {f}")
                r = self.F.loc[f]
                if r["대안후보"] != need: raise SafetyError(f"대안 후보 상태가 다름: {f} {r['대안후보']}")
                # 추천·제공여부 목록에는 인허가 폐업·휴업·말소 시설이 절대 없어야 함. '운영 확인 필요' 목록에는 오래전(2020년 전) 폐업 기록만 있는
                # 상가 가게가 있을 수 있음(다른 인허가로 영업 중일 수 있음) → 실시간 확인 전에는 주민 화면에 내보내지 않음
                if r["인허가상태"] in ("폐업", "휴업", "말소 등") and (lst != "운영확인필요" or "오래된 폐업 기록" not in c["표시"]): raise SafetyError(f"문 닫은 시설: {f}")
                if f in exclude: raise SafetyError(f"제외해야 할 시설: {f}")
                for col in ("상호", "주소", "전화"):
                    if c[col] != r[col]: raise SafetyError(f"시설 정보가 데이터베이스와 다름: {f} {col}")
                # 근거표 다시 확인: '아니요'는 어느 목록에도 없어야 하고, 카드의 근거 문장은 근거표·근거 유형과 글자까지 같아야 함
                ev = self.evidence(f, lid, res.get("의도"))
                if ev[0] == "아니요": raise SafetyError(f"자료상 이 일을 하지 않는 시설이 들어감: {f}")
                kv = self.kind.get((lid, c["세부종류"])) if c["세부종류"] else None
                expect = []
                if kv and kv["evidence"]:
                    expect = [f"{self.evm[t][f][0]} ({self.evm[t][f][1]})" for t in kv["types"] if f in self.evm.get(t, {})][:1]
                    if not expect: raise SafetyError(f"근거 유형 종류인데 근거가 없는 시설: {f}")
                if not expect and ev[0] == "예": expect = ev[1]
                if not expect and ev[0] is None: expect = self.permit_proof(f, lid, kv)
                if not expect and ev[0] is None:   # 가게 이름이 종류를 말해 주는 경우 (judge와 같은 규칙)
                    nw = self._name_proof(f, lid, c["세부종류"], res.get("의도"))
                    if nw: expect = [f"가게 이름에 '{nw}'{'이' if (ord(nw[-1]) - 0xAC00) % 28 else '가'} 들어 있음"]
                if c["근거자료"] != expect: raise SafetyError(f"근거 문장이 근거표와 다름: {f}")
                proof = bool(expect)
                if lst == "제공여부확인필요" and proof: raise SafetyError(f"근거가 있는데 확인 필요로 분류됨: {f}")
                if c["세부종류"] is not None:
                    if c["세부종류"] not in res["허용종류"]: raise SafetyError(f"허용되지 않은 세부 종류: {f}")
                    if f not in self.kind[(lid, c["세부종류"])]["fids"]: raise SafetyError(f"세부 종류에 속하지 않는 시설: {f}")
                    v = self.kind[(lid, c["세부종류"])]
                    if lst == "추천" and v["mixed_spec"] and not proof: raise SafetyError(f"겸업 종류가 근거 없이 추천 목록에 들어감: {f}")
                    if lst == "추천" and not proof and not (v["contact"] or self.strong_link(v["via"][f], lid, res["의도"])):
                        raise SafetyError(f"약한 연결 시설이 근거 없이 추천 목록에 들어감: {f}")
                    if v["contact"] and ("신청·문의 창구" not in c["표시"] or not c["안내"]): raise SafetyError(f"신청·문의 창구 표시 빠짐: {f}")
                    if lst in ("추천", "제공여부확인필요") and v.get("elig") and c["세부종류"] not in res["자격확인됨"]: raise SafetyError(f"이용 자격 확인 없이 추천: {f}")
                else:
                    if not any(g["id"] == lid for g in self.func.get(r["업종코드"], [])) and not any(
                        r[col] == "True" and any(g["id"] == lid for g in self.func.get(code, []))
                        for col, code in [("상비약판매", "PERMIT:상비약판매"), ("종량제봉투판매", "PERMIT:종량제봉투판매"), ("공원운동시설", "PERMIT:공원운동시설")]):
                        raise SafetyError(f"이 기능을 하지 않는 시설: {f}")
                if lst == "추천" and c["세부종류"] is None and not proof and not self._strong_fac(f, lid, res["의도"]): raise SafetyError(f"약한 연결 시설이 추천 목록에 들어감: {f}")
                if c["걷는거리_m"] is not None:
                    w = self.walk.distances(float(res["_출발"][0]), float(res["_출발"][1]), [f], max_m=8000)[f]
                    if w is None or abs(w - c["걷는거리_m"]) > 1: raise SafetyError(f"걷는 거리가 다시 계산한 값과 다름: {f}")
                    if self.walk.minutes(w, c["걸음"]) != c["걷는시간_분"]: raise SafetyError(f"걷는 시간이 다시 계산한 값과 다름: {f}")
                if lid == "P02.1.07" and r["구군"] != user_gu: raise SafetyError(f"다른 구·군 종량제 봉투 판매소: {f}")
        return True
