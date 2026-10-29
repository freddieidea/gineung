# 대구 유치원 목록·정원·원아 수·위치 받기 (유치원알리미 Open API: 일반현황 basicInfo2, 교육부·KERIS)
#  키: settings/kinder_key.txt (화면에 보이지 않게 파일로만 둠)
#  주의: 유치원알리미는 정보공시 자료라 1년에 두 번(공시차수) 바뀜. 운영 상태 항목이 없어, 폐원은 '이전 공시에 있던 유치원이 빠졌는지'로 봄
#  받는 것: 구·군마다 → data/raw/kinder/YYYY-MM-DD.csv (응답 항목 그대로)
#  사용: python pipeline/fetch_kinder.py
import os, sys, csv, json, datetime, urllib.request, urllib.parse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://e-childschoolinfo.moe.go.kr/api/notice/basicInfo2.do"
SIDO = "27"
SGG = {"중구": "27110", "동구": "27140", "서구": "27170", "남구": "27200", "북구": "27230", "수성구": "27260", "달서구": "27290", "달성군": "27710", "군위군": "27720"}
def key():
    p = os.path.join(ROOT, "settings", "kinder_key.txt")
    if not os.path.exists(p): sys.exit("settings/kinder_key.txt 가 없습니다 (유치원알리미 인증키를 받아 저장해 주세요)")
    return open(p, encoding="utf-8").read().strip()
def get(k, sgg):
    u = URL + "?" + urllib.parse.urlencode({"key": k, "sidoCode": SIDO, "sggCode": sgg, "pageCnt": 1000, "currentPage": 1})
    d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode("utf-8"))
    if d.get("status") != "SUCCESS": raise RuntimeError(f"{d.get('status')}: {d.get('message')}")
    return d.get("kinderInfo") or []
def main():
    k = key(); out = []; t = datetime.date.today().isoformat()
    for gu, code in SGG.items():
        rows = get(k, code)
        for r in rows: r["_구군"] = gu
        out += rows; print(gu, len(rows))
    cols = sorted({c for r in out for c in r})
    d = os.path.join(ROOT, "data", "raw", "kinder"); os.makedirs(d, exist_ok=True); p = os.path.join(d, f"{t}.csv")
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(out)
    print("합계", len(out), "설립유형", {e: sum(1 for r in out if r.get("establish") == e) for e in sorted({r.get("establish") for r in out})}, "→", p)
if __name__ == "__main__": main()
