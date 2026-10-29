# 대구 어린이집 운영 상태·정원·현원 받기 (어린이집정보공개포털 Open API: 어린이집 기본정보 조회, cpmsapi030)
#  키: settings/childcare_key.txt (화면에 보이지 않게 파일로만 둠)
#  받는 것: 구·군마다 한 번씩(9번) → data/raw/childcare/YYYY-MM-DD.csv (응답 항목을 그대로 저장)
#  쓰는 곳(키가 나온 뒤 연결): 운영 상태가 폐지·휴지로 바뀐 곳 → 폐업으로 반영(공식 기록이라 담당자 확인 없이), 정원 → '재원 아동 옮김' 판단
#  사용: python pipeline/fetch_childcare.py
import os, sys, csv, datetime, urllib.request, urllib.parse, xml.etree.ElementTree as ET
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://api.childcare.go.kr/mediate/rest/cpmsapi030/cpmsapi030/request"
# 대구 구·군 시군구 코드 (행정표준코드, 군위군은 2023-07 경북에서 편입)
ARCODE = {"중구": "27110", "동구": "27140", "서구": "27170", "남구": "27200", "북구": "27230", "수성구": "27260", "달서구": "27290", "달성군": "27710", "군위군": "27720"}
def key():
    """settings/childcare_key.txt (일반 글). 맥 텍스트 편집기로 저장해 .rtf가 된 경우(childcare_key.txt.rtf)도 그 안의 키만 꺼내 씀"""
    import re
    for p in (os.path.join(ROOT, "settings", "childcare_key.txt"), os.path.join(ROOT, "settings", "childcare_key.txt.rtf"), os.path.join(ROOT, "settings", "childcare_key.rtf")):
        if not os.path.exists(p): continue
        s = open(p, encoding="utf-8", errors="replace").read()
        if s.lstrip().startswith("{\\rtf"):
            s = re.sub(r"\{\\fonttbl.*?\}\}|\{\\colortbl.*?\}|\{\\\*\\expandedcolortbl.*?\}", "", s, flags=re.S)
            s = re.sub(r"[{}]", "", re.sub(r"\\[a-zA-Z]+-?\d* ?", "", s))
        toks = re.findall(r"[A-Za-z0-9\-_]{16,}", s)
        if len(toks) == 1: return toks[0]
        sys.exit(f"{os.path.basename(p)} 안에서 인증키를 하나로 찾지 못했습니다 (키만 적어 저장해 주세요)")
    sys.exit("settings/childcare_key.txt 가 없습니다 (인증키를 받아 저장해 주세요)")
def get(k, code):
    u = URL + "?" + urllib.parse.urlencode({"key": k, "arcode": code})
    try: b = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
    except Exception as e: raise RuntimeError(f"응답 없음 ({type(e).__name__}): 인증키가 아직 승인 전이거나, 신청한 접근 URL과 다른 곳에서 부른 경우일 수 있음")
    root = ET.fromstring(b)
    rows = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
    if not rows: raise RuntimeError("자료 없음: " + b.decode("utf-8", "replace")[:300])
    if all(r.get("crname", "").isdigit() and r.get("sidoname", "").isdigit() for r in rows):   # 승인 전 키: 항목 번호(01, 02 …)만 든 견본 응답 → 받지 않음
        raise RuntimeError("견본 응답만 옴: 인증키가 아직 운영 승인 전입니다 (어린이집정보공개포털 > 인증키 발급 현황 확인)")
    return rows
def main():
    k = key(); out = []; t = datetime.date.today().isoformat()
    for gu, code in ARCODE.items():
        rows = get(k, code)
        for r in rows: r["_구군"] = gu
        out += rows; print(gu, len(rows))
    cols = sorted({c for r in out for c in r})
    d = os.path.join(ROOT, "data", "raw", "childcare"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{t}.csv")
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(out)
    st = {}
    for r in out: st[r.get("crstatusname", "?")] = st.get(r.get("crstatusname", "?"), 0) + 1
    print("합계", len(out), "운영 상태", st, "항목", cols, "→", p)
if __name__ == "__main__": main()
