# 블로그 글 찾기 (카카오 '다음 블로그 검색', 하루 3만 건 무료) — 헌준님 의견(10/15): 별점 대신 블로그 추천
#  지키는 것
#   - 결과는 저장하지 않고 그때그때 찾아 화면에만 보여 줌 (카카오 정책)
#   - 검색 결과를 외부 언어 모델(대화 모델)에 넘기지 않음: 카카오가 '검색 데이터를 외부 LLM API로 전송해 활용하는 것은 제한'이라고 답함
#     (devtalk.kakao.com/t/api-llm/151458). 그래서 거르기·세기는 모두 이 코드가 하고, 대화 모델에는 '보여 드렸다'는 사실만 알림
#   - 이 가게 글만: 글 제목·요약에 가게 이름(띄어쓰기 무시)이 있고, 동·구·도로명·'대구' 중 하나가 함께 있어야 함 (다른 지역 같은 이름 가게를 섞지 않음)
#   - 블로그 글에는 광고가 섞여 있어, 좋다·나쁘다를 판단하지 않고 글 수와 링크만 보여 줌
import json, os, re, urllib.request, urllib.parse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = re.compile(r"<[^>]+>")
def _plain(x): return re.sub(r"&[a-z]+;|&#\d+;", " ", TAG.sub("", str(x or ""))).strip()
def _key(x): return re.sub(r"[\s\(\)\[\]·.,'\"-]", "", _plain(x)).lower()
BRANCH = re.compile(r"\s*\S+(점|지점|호점)$")

class BlogSearch:
    URL = "https://dapi.kakao.com/v2/search/blog"
    def __init__(self, key=None):
        self.key = key or open(os.path.join(ROOT, "settings", "kakao_key.txt"), encoding="utf-8").read().strip()
    def _call(self, q, size=50):
        u = self.URL + "?" + urllib.parse.urlencode({"query": q, "size": size, "sort": "accuracy"})
        with urllib.request.urlopen(urllib.request.Request(u, headers={"Authorization": "KakaoAK " + self.key}), timeout=8) as r:
            return json.load(r).get("documents", [])
    @staticmethod
    def area_words(addr, gu=None):
        a = str(addr or ""); out = set()
        if gu: out.add(str(gu))
        out |= set(re.findall(r"([가-힣]+[구군])\s", a)) - {"대구"}
        out |= set(re.findall(r"\(([가-힣0-9]+동)", a)) | set(re.findall(r"([가-힣0-9]+(?:동|읍|면))(?=[\s,)])", a))
        out |= {m for m in re.findall(r"([가-힣0-9]+(?:로|길))\s", a)}
        out.add("대구")
        return {w for w in out if len(w) >= 2}
    def posts(self, name, addr="", gu=None, alt_name=None, limit=5):
        """돌려줌: {'글수': 이 가게 이야기로 보이는 글 수(상위 50개 안에서), '글': [{제목, 날짜, 블로그, 주소}] 최근 순, '검색어'}"""
        names = [n for n in {str(name or ""), BRANCH.sub("", str(name or "")), str(alt_name or "")} if len(_key(n)) >= 2]
        area = self.area_words(addr, gu)
        dong = next((w for w in area if re.search(r"(동|읍|면)$", w)), None) or (gu or "대구")
        q = f"{BRANCH.sub('', str(name))} {dong}"
        docs = self._call(q)
        keys = {_key(n) for n in names}
        seen = set(); hit = []
        for d in docs:
            t, c = _plain(d.get("title")), _plain(d.get("contents"))
            if d.get("url") in seen: continue
            if not any(k in _key(t + c) for k in keys): continue
            if not any(w in t + c for w in area): continue
            seen.add(d.get("url"))
            hit.append({"제목": t[:80], "날짜": str(d.get("datetime", ""))[:10], "블로그": _plain(d.get("blogname"))[:30], "주소": d.get("url")})
        hit.sort(key=lambda x: x["날짜"], reverse=True)
        return {"글수": len(hit), "글": hit[:limit], "검색어": q}
