# 주민 제보 교차검증 (헌준님 10/19·10/20: 주민이 '문을 닫았다'고 알려 오면 담당자에게 바로 넘기지 않고, AI가 여러 자료로 견줘 스스로 판단)
#  - 판단이 분명하면 AI가 바로 반영 (시설 종류와 상관없이): 폐업 맞음 → 폐업 지도·공백 계산으로, 영업 중 → 다시 대신 갈 곳으로 안내
#  - 판단 보류: 일반 가게는 다음 검토 때 다시 봄(30일 지나도 근거가 없으면 다시 안내)
#              공공·복지·의료 시설은 문을 닫았을 때 기능 공백이 생기는 곳만 담당자에게 '폐업 확인 필요'로 넘김, 공백이 없으면 AI가 계속 확인
#  - 언제: 공공·복지·의료 시설은 제보가 오면 바로, 일반 가게는 매주 한 번(월요일 아침 점검). 보류된 공공 시설도 매주 다시 봄
#  견주는 자료
#   1) 인허가: 그 가게 인허가가 폐업·휴업으로 바뀌었는지, 같은 가게의 다른 인허가가 아직 영업인지 (지방행정 인허가, 매일 받음)
#   2) 같은 자리 새 가게: 같은 건물 같은 호실에 최근 다른 이름으로 인허가가 났는지
#   3) 카카오맵: 그 자리에서 같은 이름의 장소가 아직 검색되는지
#   4) 블로그: 제보 뒤에도 그 가게 이야기가 올라오는지 (가장 최근 글이 언제인지만)
#   5) 제보: 몇 번, 며칠에 걸쳐 들어왔는지, 주민이 쓴 말
#  카카오맵·블로그 결과는 AI 모델에 그대로 보내지 않고 '찾음/못 찾음', '최근 글 있음/없음' 같은 판정만 넘김. 저장하지 않음
#  AI가 '폐업 맞음'이라고 해도 확실한 근거(인허가 폐업, 같은 자리 새 가게, 지도에서 사라짐 + 여러 번 제보)가 없으면 보류로 둠 (잘못 지우지 않게)
import os, re, json, datetime, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
MEDICAL = re.compile(r"병원|의원|약국|치과|한의원|보건|요양|의료")
SONNET = "claude-sonnet-5-5"

def _day(x):
    try: return datetime.date.fromisoformat(str(x)[:10])
    except Exception: return None

class ReportCheck:
    def __init__(self, gov):
        self.G = gov; self.cm = gov.cm

    # 공공·복지·의료 시설인지: 담당 공무원이 확인할 곳
    def is_public(self, fid):
        E = self.cm.engine()
        if fid not in E.F.index: return False
        r = E.F.loc[fid]
        if r["출처"] == "공공" or MEDICAL.search(str(r["업종"])): return True
        try: return any(d["공공"] and d["공공"].get("회복") for d in E.what_it_does(fid))   # 되살리기 어려운 공공 기능 (종량제 봉투만 파는 편의점은 아님)
        except Exception: return False

    def pending(self, public=None):
        """아직 판단하지 않은 주민 제보 (가게 하나에 하나, 제보 목록 포함)"""
        out = []
        for e in self.cm.events:
            if e["상태"] != "확인 필요" or e["출처"] != "주민 제보": continue
            r = self.cm.rows.get(e["fid"])
            if not r or not str(r.get("제외사유", "")).startswith("주민 제보"): continue
            if public is not None and self.is_public(e["fid"]) != public: continue
            out.append(e)
        return out

    def signals(self, e):
        """판단 재료 (AI에게 보낼 사실). 카카오·블로그는 판정만"""
        E = self.cm.engine(); fid = e["fid"]; r = E.F.loc[fid] if fid in E.F.index else self.cm.rows[fid]
        reps = e.get("제보목록") or [{"날짜": e.get("날짜"), "내용": e.get("근거", "")}]
        first = min((_day(x["날짜"]) for x in reps if _day(x["날짜"])), default=None)
        today = datetime.date.today()
        f = {"id": fid, "시설": str(r["상호"]), "업종": str(r["업종"]), "동네": str(r.get("행정동") or r.get("구군") or ""),
             "제보": {"횟수": len(reps), "날짜": sorted({str(x["날짜"])[:10] for x in reps}), "처음 제보 뒤 지난 날": (today - first).days if first else None,
                      "주민이 쓴 말": [str(x.get("내용") or "")[:80] for x in reps if x.get("내용") and x.get("내용") != "주민 화면 카드에서 제보"][:3]}}
        hard = []
        # 1) 인허가
        lid = str(r.get("인허가id") or "")
        try:
            P = self.cm.load_permits()
            if lid and lid != "nan":
                s = P.state(lid)
                if s in ("폐업", "휴업"):
                    day = str(self.cm._close_day.get(lid, "") or "")[:10]
                    f["인허가"] = f"인허가가 {s}로 바뀜" + (f" ({day})" if day else ""); hard.append("인허가")
                elif s == "영업":
                    f["인허가"] = "인허가는 아직 영업 중 (폐업 신고는 늦게 하는 경우가 많음)"
                else: f["인허가"] = "최신 인허가 자료에 없음"
            else: f["인허가"] = "인허가 대상이 아닌 업종이라 인허가로는 알 수 없음"
            if e.get("남은인허가"): f["같은 가게의 다른 인허가"] = "아직 영업으로 남아 있음: " + ", ".join(e["남은인허가"][:3]) + " (폐업 신고를 빠뜨렸을 수도 있음)"
            # 2) 같은 자리 새 가게
            from unit_addr import unit
            b, u = unit(r["주소"])
            g = P.by.get(b) if b else None
            if g is not None and first is not None:
                lim = (first - datetime.timedelta(days=90)).isoformat()
                nm = re.sub(r"\s", "", str(r["상호"]))
                new = g[g["영업상태명"].fillna("").str.startswith("영업") & (g["인허가일자"].fillna("") >= lim)
                        & ~g["사업장명"].fillna("").map(lambda x: re.sub(r"\s", "", x) == nm)]
                same_unit = new[new["도로명주소"].map(lambda a: unit(a)[1] == u and u != "")] if len(new) else new
                if len(same_unit):
                    x = same_unit.iloc[0]; f["같은 자리 새 가게"] = f"같은 호실에 '{x['사업장명']}'이(가) 새로 인허가를 받음 ({str(x['인허가일자'])[:10]})"; hard.append("같은 자리")
                elif len(new): f["같은 자리 새 가게"] = f"같은 건물에 최근 새로 연 가게 {len(new)}곳 (같은 호실인지는 모름)"
        except Exception: pass
        # 3) 카카오맵 (판정만)
        try:
            from live_check import LiveCheck
            v, _ = LiveCheck().check(str(r["상호"]), float(r["경도"]), float(r["위도"]))
            f["지도 검색"] = {"확인됨": "그 자리에서 같은 이름의 장소가 아직 검색됨", "찾지 못함": "그 자리에서 같은 이름의 장소가 검색되지 않음"}.get(v, "확인하지 못함")
            if v == "찾지 못함": hard.append("지도")
        except Exception: f["지도 검색"] = "확인하지 못함"
        # 4) 블로그 (가장 최근 글이 언제인지만)
        try:
            from blog import BlogSearch
            p = BlogSearch().posts(str(r["상호"]), str(r["주소"]), str(r.get("구군") or ""), str(r.get("인허가상호") or "") or None)
            days = [_day(x["날짜"]) for x in p.get("글", []) if _day(x["날짜"])]
            if days:
                last = max(days); f["블로그"] = f"가장 최근 글이 {(today - last).days}일 전" + (f" ({e.get('_기준', '제보')} 뒤에도 글이 올라옴)" if first and last > first else "")
            else: f["블로그"] = "이 가게 이야기가 담긴 글을 찾지 못함"
        except Exception: f["블로그"] = "확인하지 못함"
        return f, hard

    def judge(self, items, public=False, chunk=8):
        """items: [(사실, 확실한 근거 목록)] → {fid: {판단, 까닭, 확인할점}}. 한 번에 많이 물으면 답이 잘려 8곳씩 나눠 물음"""
        if len(items) > chunk:
            out = {}
            for k in range(0, len(items), chunk): out.update(self.judge(items[k:k + chunk], public, chunk))
            return out
        if not items: return {}
        import anthropic
        from chat import log_usage
        client = getattr(self.G, "_client", None) or anthropic.Anthropic(api_key=open(os.path.join(ROOT, "settings", "anthropic_key.txt"), encoding="utf-8").read().strip())
        self.G._client = client
        tool = {"name": "decide", "description": "제보마다 판단", "input_schema": {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {"type": "object",
                "required": ["id", "decision", "reason"], "properties": {
                    "id": {"type": "string"}, "decision": {"type": "string", "enum": ["폐업 맞음", "영업 중", "판단 보류"]},
                    "reason": {"type": "string", "description": "담당자가 읽을 까닭. 결정적인 근거 두세 가지만 공문서 개조식(명사형 종결)으로 70자 안팎. 예: '9월 18일 인허가 폐업 전환, 지도 검색 미확인'"},
                    "check": {"type": "string", "description": "공공·의료 시설일 때만: 담당자가 전화나 현장에서 확인할 점, 개조식(명사형 종결) 40자 안팎. 예: '대표 번호 연결 여부 확인'"}}}}}}}
        sysp = ("당신은 대구시 생활시설 안내 서비스에서 주민 제보를 확인하는 AI입니다. 주민이 '이 가게가 문을 닫았다'고 알려 온 곳마다, 여러 자료를 견줘 실제로 문을 닫았는지 판단합니다.\n"
                "- 폐업 맞음: 인허가가 폐업·휴업으로 바뀌었거나, 같은 호실에 다른 가게가 새로 들어왔거나, 지도에서 사라졌고 제보가 여러 번 들어온 경우처럼 근거가 분명할 때만.\n"
                "- 영업 중: 인허가가 영업 중이고 지도에서도 검색되며, 제보 뒤에도 블로그 글이 올라오는 등 아직 연다는 근거가 분명할 때.\n"
                "- 판단 보류: 자료가 서로 다르거나 모자랄 때. 확실하지 않으면 보류합니다. 잘못 지우면 주민이 헛걸음하고, 잘못 남기면 문 닫은 곳을 권하게 됩니다.\n"
                "- 제보가 0건인 곳은 인허가 기록이 엇갈려(한 인허가는 닫혔고 같은 가게의 다른 인허가는 영업) 확인이 필요한 곳입니다. 지도 검색과 같은 자리 새 가게를 특히 봅니다.\n"
                "- 인허가는 폐업 신고가 늦은 경우가 많아 '영업 중'이라도 다른 근거와 함께 봅니다. 휴업은 다시 열 수 있다는 점도 적습니다.\n"                "- 인허가가 영업 중이고 지도 검색에서도 그 자리에 나오는데 제보가 한 번뿐이고 다른 근거가 없으면 영업 중으로 봅니다. 주민이 잘못 알았거나 잠시 쉬는 날이었을 수 있습니다.\n"
                "쓰기: 공문서 개조식으로 짧게(명사형 종결). 사실에 있는 것만 쓰고, 번역투·사족 없이. 날짜는 '10월 12일'처럼 씁니다(올해가 아니면 '2025년 11월 12일'). '카카오', '블로그'라는 말 대신 '지도 검색', '온라인 글'이라고 씁니다."
                + ("\n이 시설들은 공공·복지·의료 시설입니다. 근거가 분명하면 당신의 판단이 바로 반영되고, 보류하면 문을 닫았을 때 공백이 생기는 곳만 담당 공무원이 확인합니다. check에 담당자가 전화나 현장에서 확인할 점을 한 문장으로 씁니다." if public else ""))
        msg = json.dumps([f for f, _ in items], ensure_ascii=False)
        res = None
        for _ in range(2):
            r = client.messages.create(model=SONNET, max_tokens=4000, system=sysp + "\n결과는 반드시 decide 도구로.", tools=[tool], messages=[{"role": "user", "content": f"오늘 {datetime.date.today()}. 제보 {len(items)}건:\n{msg}"}])
            try: log_usage(SONNET, r.usage, "제보 교차검증")
            except Exception: pass
            res = next((b.input for b in r.content if b.type == "tool_use"), None)
            if res and getattr(r, "stop_reason", "") == "max_tokens": res = None   # 답이 잘리면 다시
            if res: break
        out = {}
        hardmap = {f["id"]: h for f, h in items}
        for x in (res or {}).get("items", []):
            fid = x.get("id")
            if fid not in hardmap: continue
            d = x.get("decision") if x.get("decision") in ("폐업 맞음", "영업 중", "판단 보류") else "판단 보류"
            h = hardmap[fid]; f = next(f for f, _ in items if f["id"] == fid)
            # 안전장치: 확실한 근거 없이 폐업으로 정하지 않고, 연다는 근거 없이 다시 권하지 않음
            if d == "폐업 맞음" and not ("인허가" in h or "같은 자리" in h or ("지도" in h and f["제보"]["횟수"] >= 2) or ("지도" in h and "찾지 못함" in str(f.get("블로그")))):
                d = "판단 보류"
            if d == "폐업 맞음" and f.get("같은 가게의 다른 인허가") and not ("지도" in h or "같은 자리" in h):   # 인허가가 엇갈리는 곳은 지도·같은 자리 근거가 더 있어야
                d = "판단 보류"
            if d == "영업 중" and not ("영업 중" in str(f.get("인허가")) or "아직 검색됨" in str(f.get("지도 검색"))):
                d = "판단 보류"
            if d == "영업 중" and self.is_public(fid) and not ("아직 검색됨" in str(f.get("지도 검색")) and ("영업 중" in str(f.get("인허가")) or "뒤에도 글이 올라옴" in str(f.get("블로그")))):
                d = "판단 보류"   # 공공·복지·의료: 문 닫은 곳을 잘못 다시 안내하면 공백을 놓침 → 지도 검색 + (인허가 영업 또는 제보 뒤 글)이 함께 있어야
            out[fid] = {"판단": d, "까닭": re.sub(r"\s+", " ", str(x.get("reason") or "")).strip()[:300], "확인할점": str(x.get("check") or "").strip()[:200]}
        for fid in hardmap:   # AI 답을 받지 못한 곳: 보류로 두고 다음에 다시 물음 (분석 기록을 남기지 않음)
            out.setdefault(fid, {"판단": "판단 보류", "까닭": "", "확인할점": "", "_답없음": True})
        return out

    def apply(self, fid, d):
        """AI 판단이 분명하면 바로 반영 (담당자를 거치지 않음). 보류면 그대로 둠 → 공공·복지·의료는 공백이 생기는 곳만 보고서의 '폐업 확인 필요'로"""
        if d["판단"] == "폐업 맞음": self.G.resolve(fid, True, who="AI 교차검증"); return "폐업 반영"
        if d["판단"] == "영업 중": self.G.resolve(fid, False, who="AI 교차검증"); return "다시 안내"
        return "보류"

    # ── 매일: 새 제보만 / 매주 한 번: 일반 가게 제보 전부(판단 보류 포함) + 지난 7일 안에 보지 않은 공공·복지·의료 제보 ──
    def weekly(self, only_new=False):
        """only_new: 아직 AI가 본 적 없는 새 제보만 (매일). 아니면 판단 보류된 제보까지 다시 (주 1회)"""
        evs = []
        for e in self.pending():
            if only_new and e.get("AI분석"): continue
            t = (e.get("AI분석") or {}).get("때", "")
            if self.is_public(e["fid"]) and t and (datetime.datetime.now() - datetime.datetime.fromisoformat(t)).days < 7: continue
            evs.append(e)
        if only_new and not evs: return {"폐업 맞음": 0, "영업 중": 0, "판단 보류": 0}
        items = [self.signals(e) for e in evs]
        gen = [x for x in items if not self.is_public(x[0]["id"])]; pub = [x for x in items if self.is_public(x[0]["id"])]
        dec = dict(self.judge(gen) if gen else {}, **(self.judge(pub, public=True) if pub else {}))
        log = {"날짜": datetime.date.today().isoformat(), "범위": "새 제보" if only_new else "전체", "항목": []}
        n = {"폐업 맞음": 0, "영업 중": 0, "판단 보류": 0}
        for (f, h), e in zip(items, evs):
            d = dec.get(f["id"], {"판단": "판단 보류", "까닭": ""})
            if d.get("_답없음"): d = dict(d, 까닭="AI 답을 받지 못해 다음 검토 때 다시 봅니다."); d.pop("_답없음", None)
            else: e["AI분석"] = dict(d, 때=datetime.datetime.now().isoformat(timespec="seconds"), 근거={k: f[k] for k in ("인허가", "같은 자리 새 가게", "지도 검색", "블로그") if k in f})
            self.apply(f["id"], d)
            n[d["판단"]] += 1
            log["항목"].append({"fid": f["id"], "상호": f["시설"], "업종": f["업종"], "동네": f["동네"], "제보수": f["제보"]["횟수"], "공공": self.is_public(f["id"]), **d})
        self.cm._save()
        log["요약"] = n
        p = os.path.join(ROOT, "data", "gov", "report_reviews.jsonl")
        with open(p, "a", encoding="utf-8") as fh: fh.write(json.dumps(log, ensure_ascii=False) + "\n")
        return n

    # ── 공공·복지·의료: 제보가 오면 바로 AI가 판단, 분명하면 바로 반영 ──
    def analyze_public(self, fid):
        e = next((x for x in self.pending(public=True) if x["fid"] == fid), None)
        if not e: return None
        f, h = self.signals(e)
        d = self.judge([(f, h)], public=True).get(fid)
        if d and not d.get("_답없음"):
            e["AI분석"] = dict(d, 때=datetime.datetime.now().isoformat(timespec="seconds"), 근거={k: f[k] for k in ("인허가", "같은 자리 새 가게", "지도 검색", "블로그") if k in f}); self.cm._save()
            d = dict(d, 반영=self.apply(fid, d))
        return d

    # ── 인허가가 엇갈린 곳: 매일 (지난 7일 안에 본 곳은 건너뜀) ──
    def cross_unsure(self, max_n=40):
        """AI 판단이 분명하면 바로 반영(폐업 맞음 → 폐업 지도, 영업 중 → 다시 안내). 보류된 공공·복지·의료 시설은 분석을 붙여 두고, 닫혔을 때 공백이 생기는 곳만 담당자에게"""
        U = self.G.unsure(); todo = []
        for fid, u in U.items():
            if u.get("제보"): continue
            ev = next((e for e in self.cm.events if e["id"] == u["변화id"]), None)
            if ev is None: continue
            t = (ev.get("AI분석") or {}).get("때", "")
            if t and (datetime.datetime.now() - datetime.datetime.fromisoformat(t)).days < 7: continue
            todo.append((ev, u))
        todo = todo[:max_n]
        if not todo: return {"폐업 맞음": 0, "영업 중": 0, "판단 보류": 0, "담당자 확인": 0}
        items = []
        for ev, u in todo:
            e2 = dict(ev, 남은인허가=u.get("남은인허가") or [], 제보목록=[{"날짜": u.get("폐업일자") or ev.get("날짜"), "내용": ""}], 날짜=u.get("폐업일자") or ev.get("날짜"), _기준="인허가가 닫힌")
            f, h = self.signals(e2); f["제보"]["횟수"] = 0; items.append((f, h))
        dec = self.judge(items, public=any(self.is_public(ev["fid"]) for ev, _ in todo))
        n = {"폐업 맞음": 0, "영업 중": 0, "판단 보류": 0, "담당자 확인": 0}
        for (ev, u), (f, h) in zip(todo, items):
            d = dec.get(ev["fid"]) or {"판단": "판단 보류", "까닭": "", "확인할점": "", "_답없음": True}
            if d.get("_답없음"): n["판단 보류"] += 1; continue
            ev["AI분석"] = dict(d, 때=datetime.datetime.now().isoformat(timespec="seconds"))
            a = self.apply(ev["fid"], d)   # 분명하면 시설 종류와 상관없이 바로 반영
            if a == "폐업 반영": n["폐업 맞음"] += 1
            elif a == "다시 안내": n["영업 중"] += 1
            elif self.is_public(ev["fid"]): n["담당자 확인"] += 1   # 보류된 공공 시설: 공백이 생기는 곳만 보고서에서 담당자에게
            else: n["판단 보류"] += 1
        self.cm._save()
        return n

def last_review():
    p = os.path.join(ROOT, "data", "gov", "report_reviews.jsonl")
    if not os.path.exists(p): return None
    full = [x for x in (json.loads(l) for l in open(p, encoding="utf-8").read().splitlines() if l.strip()) if x.get("범위") != "새 제보"]   # 주 1회 전체 검토만 (매일 새 제보 검토는 빼고)
    return full[-1] if full else None
