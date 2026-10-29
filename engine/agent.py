# 대화 모델이 스스로 생각해서 답하는 부분 (10/15, 헌준님 지적: 정해진 길만 가는 대화)
#  쓰는 때: 결과를 본 뒤의 자유로운 물음("2순위 빵집은 무슨 빵 팔아?", "주차돼?", "평 좋은 데는?"), 질문 중간에 끼어든 물음
#  도구: ① 후보 자세히 보기(우리 데이터 + 카카오맵 그 자리 확인) ② 조건 바꿔 다시 찾기(대안 찾기 엔진) ③ 인터넷 검색(메뉴·후기 글, 출처 표시)
#  지키는 원칙 (우리가 세운 원칙 그대로)
#   - 대안 시설은 대안 찾기 엔진이 고른 곳만. 대화 모델은 새 시설을 고르지 않음 (더 찾으려면 ②로 엔진을 다시 부름)
#   - 전화번호·주소·거리는 자료에 있는 값만. 대화 모델이 쓴 번호가 자료에 없으면 답을 쓰지 않고 다시 쓰게 함
#   - 인터넷에서 찾은 내용은 '인터넷 글'이라고 밝히고 출처 링크를 붙임. 못 찾으면 못 찾았다고 말함 (지어내지 않음)
#   - 카카오 검색 결과·인터넷 검색 결과는 저장하지 않음 (이번 답에만 씀)
import json, os, re
import anthropic
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = "claude-sonnet-5-5"
MAX_PER_SESSION = 12   # 한 대화에서 대화 모델이 자유롭게 답하는 횟수 (비용 보호)
PHONE = re.compile(r"(?<!\d)(0\d{1,2}-\d{3,4}-\d{4}|1\d{3}-\d{4})(?!\d)")

SYSTEM = """당신은 대구시 '기능상속' 생활시설 안내 상담원입니다. 다니던 곳이 문을 닫은 주민, 특히 어르신이 대신 갈 곳을 찾도록 돕습니다.

말투
- 동네 복지관 직원이 어르신께 말하듯 따뜻하고 쉬운 우리말로, 짧게(보통 2~4문장) 답합니다.
- 번역투와 딱딱한 말은 쓰지 않습니다. (쓰지 말 것: '~하는 것이 가능합니다', '~에 대해', '~을 통해', '해당 시설', '제공됩니다', '확인이 필요합니다')
- 목록이 꼭 필요할 때만 짧게 나눠 쓰고, 마크다운 기호(#, **, 표)는 쓰지 않습니다.

반드시 지킬 것
1. 대신 갈 곳으로 안내할 수 있는 곳은 [지금 보여 드린 곳]뿐입니다. 인터넷 검색에서 다른 가게가 나와도 새로 추천하지 않습니다.
   주민이 다른 조건(버스로, 다른 동네 근처, 더 가까운 곳, 몇 분 안)을 원하면 search_again 도구로 다시 찾습니다.
2. 전화번호·주소·거리·걸리는 시간은 주어진 자료에 있는 그대로만 씁니다. 모르는 값은 지어내지 않습니다.
3. 메뉴·파는 물건·가격·영업시간·주차·분위기·후기처럼 우리 자료에 없는 것은 먼저 place_details로 보고, 거기 없으면 web_search로 그 가게 이름과 동네를 함께 넣어 찾습니다.
   - 찾은 내용은 "인터넷 글을 보면 ~래요"처럼 인터넷에서 본 내용임을 밝힙니다. 글이 오래됐을 수 있으면 그렇게 말합니다.
   - 같은 이름의 다른 지점·다른 지역 가게 글과 섞지 않습니다. 주소나 동네가 맞는 글만 씁니다. 확실하지 않으면 쓰지 않습니다.
   - 못 찾으면 못 찾았다고 솔직히 말하고, 가게 전화번호로 물어보시라고 권합니다.
4. 별점·평점은 우리 서비스에 없습니다. 후기·평·블로그 글을 물으면 show_blog_posts 도구로 그 가게의 블로그 글 목록을 화면에 보여 드립니다.
   블로그 글의 내용은 당신에게 전달되지 않습니다(카카오 정책). 글 내용을 짐작해 좋다·나쁘다 말하지 말고, "아래 블로그 글을 보시면 돼요"처럼 안내만 합니다.
   여러 곳을 블로그 글이 많은 순서로 다시 보고 싶어 하면 search_again의 sort를 '블로그'로 씁니다.
5. 병의 진단, 약, 법률 판단은 하지 않습니다. 위급하면 119를 안내합니다.
6. 생활시설 찾기와 관계없는 물음에는 짧게 답하고, 필요한 곳 찾기를 도와드리겠다고 말합니다.
7. [하던 질문]이 있으면 그 질문은 화면이 다시 여쭈므로, 당신은 주민의 물음에만 답합니다.
8. 도구를 쓰기 전이나 쓰는 중에는 아무 글도 쓰지 않습니다. 모든 글은 한국어로만 씁니다.
9. 지금 물음에만 짧게 답합니다. 앞에서 한 답을 다시 설명하거나 사과하지 않습니다. 순위 번호는 [지금 보여 드린 곳]의 번호를 그대로 씁니다.
"""

TOOLS = [
    {"name": "place_details", "description": "지금 보여 드린 곳 하나의 자세한 자료를 봄: 우리 데이터(업종, 인허가 업태, 진료과목, 주소, 전화, 공공 자료의 운영 안내)와 카카오맵에서 지금 찾은 정보(분류, 전화, 카카오맵 링크).",
     "input_schema": {"type": "object", "required": ["rank"], "properties": {"rank": {"type": "integer", "description": "몇 순위인지 (1부터). 순위 밖 곳은 [지금 보여 드린 곳]에 적힌 번호"}}}},
    {"name": "search_again", "description": "조건을 바꿔 대신 갈 곳을 다시 찾음 (대안 찾기 엔진). 주민이 이동 방법, 기준 장소, 최대 시간, 걸음 빠르기를 바꾸고 싶어 할 때만.",
     "input_schema": {"type": "object", "properties": {
         "mode": {"type": "string", "enum": ["걸어서", "버스·지하철", "자가용", "택시", "다니기 어려움"]},
         "near_place": {"type": "string", "description": "이 장소 근처에서 찾기 (예: 서문시장, 반월당역)"},
         "max_minutes": {"type": "integer", "minimum": 1, "maximum": 120},
         "walk_speed": {"type": "string", "enum": ["보통", "천천히", "아주 천천히"]},
         "sort": {"type": "string", "enum": ["가까운 순", "블로그"], "description": "'블로그'는 블로그에 그 가게 이야기가 많이 나온 순 (가까운 8곳 안에서)"}}}},
    {"name": "show_blog_posts", "description": "보여 드린 곳 하나의 블로그 글 목록(다음 블로그 검색)을 주민 화면에 바로 보여 줌. 글 내용은 당신에게 오지 않음.",
     "input_schema": {"type": "object", "required": ["rank"], "properties": {"rank": {"type": "integer"}}}},
]
WEB = {"type": "web_search_20250305", "name": "web_search", "max_uses": 2,
       "user_location": {"type": "approximate", "city": "Daegu", "country": "KR", "timezone": "Asia/Seoul"}}

class Agent:
    def __init__(self, conv, client=None, model=MODEL):
        self.C = conv; self.E = conv.E; self.model = model; self.web = True
        self.client = client or anthropic.Anthropic(api_key=open(os.path.join(ROOT, "settings", "anthropic_key.txt"), encoding="utf-8").read().strip())

    # ── 대화 모델에게 주는 사실 (화면에 보인 것과 같은 값) ──
    def _rows(self, st):
        """화면에 보인 곳들과 번호: 1~3순위, 그 뒤에 '전화로 확인할 곳'을 4, 5…번으로"""
        res = st.get("last_result") or {}
        rank = list(res.get("순위") or []); extra = [c for c in (res.get("확인필요후보") or []) if c not in rank]
        return [(k + 1, c) for k, c in enumerate(rank)] + [(len(rank) + j + 1, c) for j, c in enumerate(extra)]
    def _shown(self, st):
        return [{"번호": n, "상호": c["상호"], "종류": self.C._kind_word(c["세부종류"]) if c.get("세부종류") else c.get("업종"),
                 "주소": c.get("주소"), "전화": c.get("전화") or "", "가는 길": self.C._travel_main(st, c).lstrip(" —"),
                 "확실성": c.get("확실성"), "참고": [m for m in c.get("표시", []) if m]} for n, c in self._rows(st)]
    def _facts(self, st):
        lines = []
        if st.get("closed_fid") and st["closed_fid"] in self.E.F.index:
            r = self.E.F.loc[st["closed_fid"]]
            lines.append(f"[문 닫은 곳] {r['상호']} ({r['업종']}), {r['주소']}")
        if st.get("leaf"): lines.append(f"[주민이 찾는 일] {self.E.leaf[st['leaf']]['name']}" + (f" / 종류: {st['kind']}" if st.get("kind") else ""))
        cond = st.get("cond", {})
        lines.append(f"[조건] 이동: {cond.get('mode', '아직 모름')}, 최대 시간: {cond.get('max_min') or '없음'}분, 걸음: {st.get('speed') or '모름'}, 기준 장소: {st.get('origin_name') or '문 닫은 곳(또는 지금 위치)'}")
        shown = self._shown(st)
        lines.append("[지금 보여 드린 곳]\n" + (json.dumps(shown, ensure_ascii=False, indent=0) if shown else "아직 없음 (대신 갈 곳을 찾기 전)"))
        if st.get("stage") != "done" and st.get("last_q"): lines.append(f"[하던 질문] {st['last_q']['text']}")
        hist = [h for h in st.get("history", []) if isinstance(h, dict)][-10:]
        if hist: lines.append("[지금까지 대화]\n" + "\n".join(("주민: " if h["role"] == "user" else "안내: ") + h["text"][:300] for h in hist))
        return "\n\n".join(lines), shown

    # ── 도구 실행 ──
    def _place_details(self, st, shown, rank):
        hit = [c for n, c in self._rows(st) if n == rank]
        if not hit: return {"오류": f"{rank}번은 지금 보여 드린 곳에 없어요"}
        c = hit[0]; out = {"상호": c["상호"], "주소": c.get("주소"), "전화": c.get("전화") or "자료에 없음"}
        fid = c.get("fid")
        if fid in self.E.F.index:
            r = self.E.F.loc[fid]
            for k in ("업종", "업태", "진료과목", "인허가업종", "출처"):
                v = str(r.get(k) or "")
                if v and v != "nan": out[k] = v
            ref = str(r.get("참고") or "")
            if r["출처"] == "공공" and ref and ref != "nan": out["공공 자료 안내"] = ref[:400]
        try:
            v, why, kd = self.C._live().check_detail(c["상호"], float(c["경도"]), float(c["위도"]))
            if v == "확인됨": out["카카오맵(지금 찾음)"] = {"분류": kd.get("분류"), "전화": kd.get("전화"), "링크": kd.get("지도")}
            else: out["카카오맵(지금 찾음)"] = "같은 이름의 장소를 찾지 못함"
        except Exception:
            out["카카오맵(지금 찾음)"] = "확인이 잠시 안 됨"
        return out

    def _search_again(self, st, a):
        cond = st.setdefault("cond", {})
        if a.get("mode"):
            cond["mode"] = a["mode"]
            if a["mode"] not in ("걸어서", "다니기 어려움"): st.pop("speed", None)
        if a.get("max_minutes"): cond["max_min"] = int(a["max_minutes"])
        if a.get("walk_speed"): st["speed"] = a["walk_speed"]
        if a.get("near_place"): cond["origin_text"] = a["near_place"]; st["origin_done"] = False
        if a.get("sort"): cond["sort"] = "블로그" if a["sort"] == "블로그" else None
        if not st.get("leaf"): return None
        return self.C._next(st)

    # ── 한 번의 답 ──
    def reply(self, st, text):
        st["agent_n"] = st.get("agent_n", 0) + 1
        pend = st.get("last_q") if st.get("stage") != "done" else None
        if st["agent_n"] > MAX_PER_SESSION:
            return self._wrap(st, "더 자세한 건 가게에 전화로 물어보시는 게 가장 정확해요. 다른 곳을 찾으시려면 처음부터 다시 찾아 주세요.", [], pend)
        facts, shown = self._facts(st)
        allowed_phones = set(PHONE.findall(facts))
        msgs = [{"role": "user", "content": f"{facts}\n\n[주민의 말]\n{text}"}]
        tools = TOOLS + ([WEB] if self.web else [])
        links = []; again = None; fixes = 0; blogs = []
        for _ in range(6):
            try:
                r = self.client.messages.create(model=self.model, max_tokens=900, system=SYSTEM, tools=tools, messages=msgs)
            except anthropic.BadRequestError as e:
                if self.web and "web_search" in str(e):   # 인터넷 검색을 쓸 수 없는 계정·모델이면 검색 없이
                    self.web = False; tools = TOOLS; continue
                raise
            if r.stop_reason == "pause_turn":
                msgs.append({"role": "assistant", "content": r.content}); continue
            uses = [b for b in r.content if getattr(b, "type", "") == "tool_use"]
            if uses:
                msgs.append({"role": "assistant", "content": r.content}); outs = []
                for u in uses:
                    if u.name == "place_details":
                        d = self._place_details(st, shown, int(u.input.get("rank", 0)))
                        allowed_phones |= set(PHONE.findall(json.dumps(d, ensure_ascii=False)))
                        outs.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(d, ensure_ascii=False)})
                    elif u.name == "show_blog_posts":
                        hit = [c for n, c in self._rows(st) if n == int(u.input.get("rank", 0))]
                        if hit: blogs.append(self._blog_block(hit[0]))
                        outs.append({"type": "tool_result", "tool_use_id": u.id, "content": "블로그 글 목록을 주민 화면에 보여 드렸어요. 글 내용은 전달하지 않아요(카카오 정책). 내용을 짐작하지 말고 짧게 안내만 해 주세요." if hit else "그 번호는 보여 드린 곳에 없어요"})
                    elif u.name == "search_again":
                        again = self._search_again(st, u.input)
                        outs.append({"type": "tool_result", "tool_use_id": u.id, "content": "다시 찾은 결과는 화면에 바로 보여 드려요. 한 문장으로만 무엇을 바꿔 찾았는지 말해 주세요."})
                    else:
                        outs.append({"type": "tool_result", "tool_use_id": u.id, "content": "알 수 없는 도구", "is_error": True})
                msgs.append({"role": "user", "content": outs}); continue
            # 글 답: 출처 모으기 + 전화번호 검사
            # 인터넷 검색 전에 쓴 혼잣말(예: 'I'll search the web')은 버리고, 마지막 검색 뒤의 답만 씀
            cut = max([i for i, b in enumerate(r.content) if getattr(b, "type", "") in ("server_tool_use", "web_search_tool_result")] or [-1])
            final = r.content[cut + 1:]
            body = "".join(b.text for b in final if getattr(b, "type", "") == "text").strip()
            if re.search(r"[A-Za-z]{4,}(\s+[A-Za-z']+){3,}", body) and not re.search(r"[가-힣]", body[:40]):   # 영어 문장으로 시작하면 한국어 부분만
                m = re.search(r"[가-힣]", body); body = body[m.start():] if m else body
            for b in final:
                for ct in (getattr(b, "citations", None) or []):
                    u = getattr(ct, "url", None)
                    if u and all(u != x["url"] for x in links): links.append({"url": u, "제목": getattr(ct, "title", "") or u})
            bad = [p for p in PHONE.findall(body) if p not in allowed_phones]
            if bad and fixes < 1:
                fixes += 1
                msgs.append({"role": "assistant", "content": r.content})
                msgs.append({"role": "user", "content": f"답에 자료에 없는 전화번호({', '.join(bad)})가 들어 있어요. 자료에 있는 번호만 쓰거나 번호 없이 다시 답해 주세요."}); continue
            if bad: body = PHONE.sub("(번호는 가게에 확인)", body)
            body = re.sub(r"\*\*|^#+\s*", "", body, flags=re.M)
            if again is not None:
                return self._merge(st, body, again)
            return self._wrap(st, body or "죄송해요, 지금은 답을 찾지 못했어요. 가게에 전화로 물어보시는 게 가장 정확해요.", links[:3], pend, blogs)
        return self._wrap(st, "죄송해요, 지금은 답을 찾지 못했어요. 가게에 전화로 물어보시는 게 가장 정확해요.", [], pend)

    def _blog_block(self, c):
        r = self.E.F.loc[c["fid"]] if c.get("fid") in self.E.F.index else {}
        try: b = self.C._blog().posts(c["상호"], c.get("주소") or "", r.get("구군") if len(r) else None, r.get("인허가상호") if len(r) else None)
        except Exception: b = {"글수": None, "글": []}
        return {"blog": dict(b, 상호=c["상호"])}
    def _wrap(self, st, body, links, pend, blogs=()):
        blocks = [{"text": x} for x in body.split("\n") if x.strip()]
        blocks += list(blogs)
        if links: blocks.append({"links": links})
        out = {"type": "answer", "text": body, "blocks": blocks, "options": [], "agent": True, "출처": links}
        if pend:   # 하던 질문을 다시 여쭘 (선택지 그대로)
            out.update(type="question", options=pend.get("options") or [])
            out["blocks"] = blocks + [{"text": pend["text"]}]; out["text"] = body + "\n" + pend["text"]
        st.setdefault("history", []).append({"role": "assistant", "text": body[:300]})
        return out
    def _merge(self, st, body, r):
        lead = [{"text": body}] if body else []
        out = dict(r); out["blocks"] = lead + (r.get("blocks") or [{"text": x} for x in r.get("text", "").split("\n")]); out["text"] = (body + "\n" + r.get("text", "")).strip()
        return out
