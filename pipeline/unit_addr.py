# 가게 한 칸의 주소 (같은 자리에서 문을 닫고 새로 연 가게를 짝지을 때 씀: build_closures.py, engine/changes.py)
#  '대구광역시 북구 동북로 345, 상가 401동 109호 (복현동, 복현푸르지오)' → ('대구광역시북구동북로345', '401동109호')
#  층·호(쉼표 뒤)가 없으면 같은 건물의 이웃 가게와 구별할 수 없어 칸을 모름(빈칸)
import re, datetime
def unit(a):
    a = str(a or "").strip()
    if not a or a == "nan": return "", ""
    a = re.sub(r"\s*\(.*$", "", a)
    base, _, det = a.partition(",")
    base = re.sub(r"\s+", "", base); det = re.sub(r"\s+", "", det)
    det = re.sub(r"^(상가|지상|일부|외\d*필지)", "", det); det = re.sub(r"(일부|전체|전층)$", "", det)
    return base, det
def same_unit(a, b):
    ua, ub = unit(a), unit(b)
    return bool(ua[0] and ua[1] and ua == ub)
def opened_after(open_day, close_day, slack=30):
    """새 가게 개업(인허가)일이 폐업일 slack일 전 이후인지 (새 주인이 먼저 허가를 받고 옛 주인이 늦게 폐업 신고하는 경우까지)"""
    try: return str(open_day)[:10] >= (datetime.date.fromisoformat(str(close_day)[:10]) - datetime.timedelta(days=slack)).isoformat()
    except Exception: return False
