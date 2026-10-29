# 지자체 담당자 보조 에이전트 (2026-10-16)
# 대화 상대(챗봇)가 아니라, 날마다 스스로 일을 하고 결과를 담당자에게 '보고'하는 에이전트
#  날마다 하는 일 (data/gov/runs.jsonl에 단계별 기록이 남음)
#   1) 자료 받기   : 행정안전부 지방행정 인허가 자료를 새로 받음 (engine/changes.py ChangeManager.fetch)
#   2) 변화 찾기   : 지난번 자료와 견줘 폐업·휴업·개업을 찾아 지금의 분류 체계로 분류 (ChangeManager.process_localdata)
#      문 닫음 다시 판정: 가게 하나의 인허가를 모두 보고 정말 닫았는지 판정 (pipeline/permit_status.py, ChangeManager.recheck)
#        같은 가게의 다른 인허가가 아직 영업이면 '확인 요청'으로 담당자에게 넘기고, 주민에게는 문 닫음으로 단정하지 않음
#   3) 영향 분석   : 문 닫은 곳마다 '그곳이 하던 생활 기능'과 '생활 공백'(걸어서 기준 시간 안에 갈 곳이 없어지는 주민, 65세 이상 따로)을 계산
#                    (engine/impact.py 걷는 길 지도 + 100m 인구 격자). 대체 시설도 찾음 (대안 찾기 엔진)
#   4) 우선순위    : 계산한 숫자로만 긴급·주의·참고를 나눔 (아래 기준). 참고는 담당자 화면에서 접어 둠
#   5) 구·군 보고서: 긴급·주의만 골라 언어 모델이 구·군마다 요약·예상 위험·추천 해결방안을 씀
#                    언어 모델에는 계산한 사실만 주고, 사실에 없는 시설 이름·숫자가 나오면 그 문장을 버림 (지어내기 방지)
#  결과: data/gov/brief_날짜.json (보고서), data/gov/analysis.json (시설별 분석 보관), data/gov/handled.json (담당자가 '처리함'으로 둔 것)
# 우선순위 기준 (현장 판단, 바꿀 수 있음 — engine/changes.py와 같은 값)
#   긴급: 필수 기능(처방약 조제 등)을 그 일을 하는 모든 곳으로 넓혀 봐도 기준 시간 안에 갈 곳이 없어지는 주민이 ALERT_POP명 이상
#   주의: 준필수 기능에서 위와 같은 주민이 ALERT_POP명 이상 / 필수 기능의 같은 묶음 안에서 ALERT_POP명 이상 /
#         필수·준필수 기능에서 이곳이 가장 가까웠던 주민이 ATTN_NEAR명 이상이고 걷는 시간(중앙값)이 ATTN_JUMP분 넘게 늘어남 /
#         65세 이상 주민의 생활 공백이 ELDER_POP명 이상
#   참고: 그 밖 (근처에 대신 갈 곳이 충분함)
# 사용
#   python engine/gov_agent.py 점검 [--받기없음] [--모델없음]      # 오늘 점검을 한 번 돌림
#   python engine/gov_agent.py 보고서 [--모델없음]                 # 분석해 둔 것으로 보고서만 다시 만듦
#   python engine/gov_agent.py 분석 [제한초]                       # 영향 분석만 (나눠 돌릴 수 있음)
import os, sys, json, re, time, datetime, threading, glob, hashlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(ROOT, "engine"), os.path.join(ROOT, "pipeline")):
    if _d not in sys.path: sys.path.insert(0, _d)
import pandas as pd
import public_basis as PB
import closure_policy as CP
import gov_programs as GP
import severity as SV
import gap_agent as GA
import demand as DM
import numpy as np
from changes import ChangeManager, ALERT_POP, ATTN_NEAR, ATTN_JUMP, now, today
ELDER_POP = 15
AI_MIN = 0.1     # 판단 모델 점수가 이보다 낮으면 AI에게 묻지 않고 지켜봄 (비용)
ASK_MAX = 3      # 구마다 하루에 담당자에게 물을 수 있는 판단 확인 수 (담당자에게 일을 더 주지 않게)
GOV = os.path.join(ROOT, "data", "gov")
GUS = ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군"]
LV_ORDER = {"긴급": 0, "주의": 1, "확인": 2, "참고": 3}   # 확인: 대신할 곳이 있는지 담당자가 확인하면 등급이 정해짐
HAIKU = "claude-haiku-5-5"
SONNET_J = "claude-sonnet-5-5"   # 보고할지 판단: 상황을 읽고 현실에 비춰 판단해야 해 큰 모델 (후보가 하루 몇 곳뿐이고, 사실이 같으면 다시 부르지 않음)

# ---- 담당자 보고에 넣을지 정하는 표 (현장 판단, 바꿀 수 있음) ----
# 분류표 등급(필수·준필수)은 그 '기능'의 공공 근거로 정했음. 그런데 같은 기능을 하는 가게 중에는 근거가 가리키는 시설이 아닌 곳도 있음
# (예: '친목 장소'의 근거는 경로당인데, 자료에서 이 기능을 하는 곳은 카페·PC방·노래방) → 그런 곳이 닫힌 것은 보고에서 뺌. 주민 화면의 대안 안내는 그대로
SKIP_FUNC = {
    "P01.1.05": "외식: 공공 근거 없음", "P01.1.06": "음식 배달·포장: 공공 근거 없음",
    "P11.1.03": "친목 장소: 근거는 경로당인데, 자료의 친목 장소는 카페·PC방·노래방 같은 가게",
    "P06.2.03": "택배 수령: 근거는 아파트 무인택배함", "P06.3.01": "법률·세무 상담: 근거는 법률구조공단 무료 상담",
    "P15.2.01": "일자리 소개: 근거는 지자체 무료 직업소개", "P06.1.02": "신고·신청: 근거는 행정복지센터",
}
CORE_ONLY = {   # 기능: 근거가 가리키는 세부 종류만 셈 (다른 종류가 닫힌 것은 보고에서 뺌)
    "P01.1.01": {"슈퍼마켓 신선 코너", "채소·과일", "생선·해산물", "전통시장"}, "P01.1.02": {"슈퍼마켓", "편의점", "전통시장"}, "P01.1.03": {"슈퍼마켓"},
    "P01.1.04": {"반찬가게", "슈퍼마켓 반찬 코너", "도시락 가게"},
    "P02.1.01": {"슈퍼마켓", "편의점", "생활용품점", "전통시장"},
    "P03.3.01": {"헬스장", "수영장", "공공 체육센터", "종합 스포츠시설", "탁구", "배드민턴", "테니스", "스쿼시·라켓볼"},
    "P10.1.01": {"헬스장", "수영장", "테니스", "탁구", "스쿼시·라켓볼", "배드민턴", "종합 스포츠시설", "청소년 수련시설"},
    "P04.2.01": {"어린이집(국공립·민간·법인 등)", "가정어린이집(주로 만 0~2세)", "유치원(만 3~5세)"},   # 직장어린이집은 직원 자녀만 다녀 주민이 대신 갈 곳이 아님
    "P04.2.02": {"지역아동센터", "다함께돌봄센터"}, "P09.2.01": {"청소년 수련시설"}, "P09.2.02": {"평생교육시설"},
    "P09.1.01": {"공공도서관", "작은도서관"}, "P09.1.02": {"공공도서관 열람실", "작은도서관"},
}
# 이용자가 등록해 다니거나 지내는 곳: 문을 닫으면 지금 이용자를 다른 기관으로 옮겨야 함 → 걷는 거리보다 '옮길 곳'이 중요
ENROLL = {"P04.1.01", "P04.1.02", "P04.1.04", "P04.1.05", "P04.1.06", "P04.2.01", "P04.2.02", "P07.1.02"}
# (10/19) 등록해 다니는 곳 가운데 동네 아이가 걸어서 다니는 곳: '지금 다니는 아이가 옮길 곳'과 함께 '동네 아이가 걸어서 갈 곳이 사라지는 공백'도 잼
CHILD_GAP = {"P04.2.01", "P04.2.02"}
# '긴급'까지 올릴 수 있는 기능: 먹거리·의료·돌봄·안전 (그 밖은 생활 공백이 커도 '주의'까지)
URGENT_OK = {"G:분만", "G:신생아중환자", "G:중환자", "P01.1.01", "P01.1.02", "P01.1.07", "P03.1.01", "P03.1.02", "P03.2.01", "P04.1.01", "P04.1.02", "P04.1.03", "P04.1.04", "P04.1.05",
             "P04.1.06", "P04.2.01", "P04.2.02", "P04.3.01", "P07.1.02", "P13.1.01", "P13.1.02", "P13.2.01", "P17.1.01"}
def _j(w, pair):
    """조사: 받침에 따라 (예: _j('약국', '을를') → '약국을'). '로'는 ㄹ받침이면 '로'"""
    w = str(w); last = w.rstrip("')\" ")[-1:] if w else ""
    if not ("가" <= last <= "힣"): return w + pair[0] + "(" + pair[1] + ")"
    b = (ord(last) - 0xAC00) % 28
    if pair == "으로": return w + ("로" if b in (0, 8) else "으로")
    return w + (pair[0] if b else pair[1])
def fm(m):
    """걷는 시간 표기: 6km를 넘으면 걸어서 갈 수 있는 거리가 아님 (impact.py는 이를 100분으로 적어 둠)"""
    return "걸어서 못 갈 거리(6km 넘음)" if m is None or m >= 99.9 else f"{m:g}분"
PUB_NEAR_M = 3000   # 공립 선택권(10/21): 공립 유치원이 닫힐 때 차량 등원 10분 안팎(반경 3km) 다른 공립 유치원의 남는 자리로 원아를 받을 수 있는지
ENROLL_DAYS = 60   # 이용자 옮김은 문 닫을 무렵의 일: 이만큼 지난 곳은 '참고'로 내림 (현장 판단)
def days_since(d):
    try: return (datetime.date.fromisoformat(today()) - datetime.date.fromisoformat(str(d)[:10])).days
    except Exception: return None
FAR_MIN = 30   # 사설 시설은 대신할 곳이 걸어서 이 시간(분) 넘게 떨어질 때만(마을 생활 기반이 무너짐) 지자체에 보고 (헌준님 10/16: 웬만한 도심의 가게 폐업은 보고하지 않음)
VILLAGE_OK = {"P01.1.05", "P11.1.03"}   # 마을 예외에서는 외식·친목 장소도 셈 (예: 시골 마을의 하나뿐인 식당이 닫혀 마을 잔치·모임을 할 곳이 없어짐)
VILLAGE_NO = {"P01.1.06", "P06.2.03", "P06.3.01", "P15.2.01", "P06.1.02"}   # 배달·택배·법률 상담·직업소개·행정사: 마을 생활 기반과 거리가 멂
# 동네 슈퍼 가운데 이름으로 보아 장보기 마트인 곳 (10/19): 자료에는 신선식품을 파는지 '모름'이라 마지막 마트가 닫혀도 공백을 못 잼
#  → 지자체 공백 계산에서만 신선식품을 파는 곳으로 봄. 주민 화면은 근거 없이 '판다'고 하지 않는 원칙 그대로 (recommend.py verify)
MART_NAME = re.compile(r"마트|하나로|농협|식자재|롯데슈퍼|더프레시|에브리데이|홈플러스|코스트코|트레이더스")
MART_KIND = ("P01.1.01", "슈퍼마켓 신선 코너")
# (10/19) 행정동이 비어 있는 시설(공공 목록·인허가 자료의 26%)은 좌표로 행정동 경계에서 찾음
#  전에는 비어 있으면 읍·면인지 '모름'으로 봐서, 도심 어린이집이 도심 원칙(생명 직결 아니면 관찰)을 받지 않고 보고됐음
from dong import dong_at   # 좌표 → 행정동 (engine/dong.py)
# 인허가일자 (지방행정 인허가 자료): 인허가id '업종:구군:관리번호' → 그 파일에서 찾음 (파일마다 한 번만 읽음)
_PERMIT = {}
def permit_open(E, fid):
    try: pid = str(E.F.at[fid, "인허가id"] or "")
    except Exception: return None
    for one in [x for x in re.split(r"[;|,]\s*", pid) if x.count(":") >= 2][:1]:
        slug, gu, no = one.split(":", 2); key = (slug, gu)
        if key not in _PERMIT:
            p = os.path.join(ROOT, "data", "raw", "localdata", f"{slug}__{gu}.csv")
            try: d = pd.read_csv(p, dtype=str, usecols=["관리번호", "인허가일자"]).dropna(); _PERMIT[key] = dict(zip(d["관리번호"], d["인허가일자"]))
            except Exception: _PERMIT[key] = {}
        v = _PERMIT[key].get(no)
        if v and re.match(r"\d{4}-\d{2}-\d{2}", v): return v[:10]
    return None
# (10/26 헌준님) 공공 생활체육시설: 공공 자료의 체육시설 + 운동시설이 있는 공원. 민간 헬스장과 따로 '공공 체육시설(G:공공체육)'로 잼
SPORT_UP = {"파크골프장", "공공테니스장", "공공체육센터", "축구장", "공공수영장", "다목적운동장", "풋살장", "야구장", "족구장", "인라인스케이트장", "리틀야구장",
            "인공암벽장", "농구장", "배드민턴장", "기타전문체육", "게이트볼장", "경기장"}
PARK_UP = {"공원", "소공원"}
# 근거가 가리키는 기능이지만 생활 필수가 아닌 세부 종류 (10/26 전수 점검): 미용 목적 진료, 정해진 사람만 쓰는 거처
CORE_EXCLUDE = {"P03.1.01": {"성형외과"}, "P17.1.01": {"기숙사(정해진 사람만 입주)"}}
def counts_village(f):
    if f["등급"] not in ("필수", "준필수") or f["기능"] in VILLAGE_NO: return False
    if f.get("세부종류") in CORE_EXCLUDE.get(f["기능"], ()): return False
    if f["기능"] in SKIP_FUNC and f["기능"] not in VILLAGE_OK: return False
    core = CORE_ONLY.get(f["기능"])
    return core is None or f.get("세부종류") in core
def is_public_facility(a):
    """공공·복지 시설인지: 되살리기 어려운 공공 목적 기능을 하던 곳 (종량제 봉투만 팔던 편의점처럼 금방 되살릴 수 있는 공공 기능만 있으면 아님)"""
    return any((PB.info(f["기능"], f.get("세부종류")) or {}).get("회복") for f in a.get("기능", []))
def counts(f):
    if f["등급"] not in ("필수", "준필수") or f["기능"] in SKIP_FUNC: return False
    if f.get("세부종류") in CORE_EXCLUDE.get(f["기능"], ()): return False
    core = CORE_ONLY.get(f["기능"])
    return core is None or f.get("세부종류") in core
def in_scope(f, rural=False):
    """공백 심각도 판정 대상 기능인지 (생활 필수 기능): 도심은 counts, 읍·면은 마을 예외(counts_village)까지"""
    return counts(f) or (rural and counts_village(f))
SPORT_PARK_LEAVES = {"P10.1.01", "P10.1.04", "P03.3.01"}
def life_gap(grade, lid, kind=None, dong=None):
    """주민이 걸어서 갈 곳을 못 찾았을 때 지자체에 알릴 생활 공백인지 (10/26 헌준님: 카페가 없는 것은 생활 공백이 아님)
    지자체 공백 심각도 판정과 같은 기준: 생활 필수 기능(필수·준필수, 공공 근거가 가리키는 세부 종류)만. 읍·면은 마을 예외까지"""
    if str(lid) in SPORT_PARK_LEAVES: return False   # (10/26) 공공 체육시설·공원: 학교 개방 시설·공원 운동시설 자료가 모자라 '걸어서 갈 곳이 없다'가 틀릴 수 있음 → 자료 보완 전까지 주민이 찾은 결과로는 알리지 않음 (상시 부재 판정 보류와 같은 까닭)
    rural = bool(dong) and str(dong).endswith(("읍", "면"))
    return in_scope({"기능": lid, "등급": grade, "세부종류": kind}, rural)
def scope_of(a, rural=False):
    """폐업 시설이 판정 대상(생활 필수 기능을 하던 곳)인지"""
    return any(in_scope(f, rural) for f in a.get("기능", []))

# ---- 참고할 대응 (언어 모델이 이 가운데서 골라 상황에 맞게 다듬음. 없는 사업을 지어내지 않게) ----
HINTS = [
    (("P03.2.01", "P03.2.02", "P03.2.03"), [("대체 약국 위치와 운영 시간을 행정복지센터·경로당 게시판과 이통장 회의로 안내", "행정복지센터"),
        ("지역 약사회와 협의해 인근 약국의 야간·주말 운영 확인, 공공심야약국 지정 검토", "보건소 의약 담당"),
        ("거동이 불편한 어르신은 보건소 방문건강관리와 연계", "보건소 방문건강관리")]),
    (("P03.1.01",), [("대체 의원과 보건소·보건지소 진료를 안내", "보건소"), ("거동이 불편한 주민은 방문진료 의료기관과 연계", "보건소")]),
    (("P01.1.01", "P01.1.02", "P01.1.03", "P02.1.01"), [("근처 대체 가게와 배달되는 가게를 안내", "행정복지센터"),
        ("이동장터·찾아가는 장보기 같은 장보기 지원 검토", "경제(유통·소상공인) 부서"),
        ("혼자 사는 어르신은 생필품·반찬 배달 지원과 연계", "노인복지 부서"), ("빈 점포에 같은 업종이 들어올 수 있게 골목상권 지원 사업 안내", "경제(유통·소상공인) 부서")]),
    (("P01.1.04", "P01.1.07"), [("결식이 우려되는 어르신을 경로식당·도시락 배달과 연계", "노인복지 부서")]),
    (("P07.2.01",), [("근처 대체 이·미용실 안내", "행정복지센터"), ("복지관·행정복지센터의 찾아가는 이·미용 서비스와 연계", "노인복지 부서")]),
    (("P07.1.01", "P07.1.03"), [("근처 대체 목욕탕 안내", "행정복지센터"), ("목욕비 지원·이동 지원 같은 목욕 지원 프로그램 연계 검토", "노인복지 부서")]),
    (("P07.3.01", "P07.3.02", "P07.3.03"), [("근처 세탁소·빨래방 안내", "행정복지센터"), ("이불 빨래 같은 세탁 지원 서비스 연계", "노인복지 부서")]),
    (("P04.1.04", "P04.1.02", "P04.1.06", "P04.1.01", "P04.1.05", "P07.1.02"), [("이용자와 보호자에게 대체 기관을 안내하고 옮기는 일을 도움", "노인복지 부서"),
        ("국민건강보험공단 장기요양 지사와 함께 이용자 전원 상황 확인", "노인복지 부서"), ("옮기는 동안 돌봄이 끊기지 않게 노인맞춤돌봄서비스와 연계", "행정복지센터")]),
    (("P04.2.01",), [("재원 아동 보호자에게 대체 어린이집과 빈자리를 안내", "보육 담당 부서"), ("인근 어린이집 정원 여유 확인", "보육 담당 부서")]),
    (("P04.2.02",), [("이용 아동을 인근 지역아동센터·다함께돌봄센터와 연계", "아동복지 부서")]),
    (("P03.3.01", "P10.1.01"), [("근처 공공 체육시설과 생활체육 프로그램 안내", "체육 담당 부서"), ("학교 체육관 개방 프로그램 안내", "체육 담당 부서")]),
    (("P02.1.07",), [("인근 가게를 종량제 봉투 지정 판매소로 새로 지정하고 판매소 목록 갱신", "자원순환(청소) 부서")]),
    (("P03.4.01", "P03.4.02"), [("근처 대체 안경점·보청기 판매점 안내", "행정복지센터")]),
    (("G:공공체육",), [("생활체육시설 확충 지원 공모(국민체육진흥기금) 신청 검토", "체육 담당 부서"), ("인근 학교 운동장·체육관 주민 개방 협의", "체육 담당 부서")]),
    (("P10.1.04",), [("유치거리 미충족 지역 공원 조성 도시·군관리계획 반영 검토", "공원녹지 부서"), ("공원·유휴부지 안 생활체육시설 설치 검토", "공원녹지 부서")]),
]
def hints_for(lids):
    out = []; seen = set()
    for lid in lids:
        for keys, hs in HINTS:
            if lid in keys:
                for h, who in hs:
                    if h not in seen: seen.add(h); out.append({"할일": h, "담당": who})
    return out or [{"할일": "근처 대체 시설을 주민에게 안내", "담당": "행정복지센터"}]
GENERIC_PLACES = ("행정복지센터", "보건소", "보건지소", "보건진료소", "건강생활지원센터", "정신건강복지센터", "노인복지관", "종합사회복지관", "사회복지관", "복지관",
                  "지역아동센터", "다함께돌봄센터", "가족센터", "공공심야약국", "대체 약국", "약국", "의원", "병원", "어린이집", "센터")

def _jload(p, d):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d
def _num(v):
    try: v = float(v); return None if v != v else round(v, 6)
    except Exception: return None
def _jsave(p, x):
    tmp = p + ".tmp"; json.dump(x, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, p)

class GovAgent:
    def __init__(self, root=ROOT, engine=None):
        os.makedirs(GOV, exist_ok=True)
        self.root = root; self.cm = ChangeManager(root)
        if engine is not None:   # 서버가 이미 띄운 엔진을 함께 씀 (메모리 아낌)
            from impact import Coverage
            self.cm._E = engine; self.cm._C = Coverage(engine.walk); self.cm._prov = {}
        self.p_an = os.path.join(GOV, "analysis.json"); self.an = _jload(self.p_an, {})
        self.p_h = os.path.join(GOV, "handled.json"); self.handled = _jload(self.p_h, {})
        self.p_dec = os.path.join(GOV, "decisions.json"); self.decisions = _jload(self.p_dec, {})   # 담당자가 확인한 '대신할 곳 있음/없음'
        self.lock = threading.Lock(); self.live = None   # 지금 도는 점검의 단계 (화면이 지켜봄)

    # ---------- 대상: 안내 기간 안의 문 닫은 곳 + 새로 감지한 폐업·휴업 ----------
    def _before(self):
        """문 닫기 전에 주민 안내 대상이었는지: 변화 기록에 '확인 필요'(상호·업종 어긋남, 오래된 인허가 등)였으면 안내 대상이 아니었던 곳.
        기록이 없거나 '아니요'(처음 받은 자료에서 이미 닫혀 있던 곳)면 문 닫기 전엔 영업하던 가게로 봄"""
        b = {}
        for e in self.cm.events:
            if e["종류"] in ("폐업", "휴업"):
                v = (e.get("분류") or {}).get("이전대안후보")
                if v: b[e["fid"]] = v
        return b
    def candidates(self):
        out = {}
        c = pd.read_csv(os.path.join(self.root, "data", "processed", "closures.csv"), dtype=str, keep_default_na=False)
        for r in c.to_dict("records"):
            out[r["fid"]] = {"fid": r["fid"], "상호": r["상호"], "업종": r["업종"], "구군": r["구군"], "주소": r["주소"], "경도": r["경도"], "위도": r["위도"],
                             "폐업일자": r["폐업일자"], "변화": "폐업", "출처": "상가·인허가 자료", "새가게": r["새가게"] or None, "새가게업종": r["새가게업종"] or None,
                             "새가게이음": str(r.get("같은기능새가게")) == "True", "시작일": r.get("시작일") or None, "공개까지": r.get("안내까지") or None}
        for e in self.cm.events:
            if e["종류"] not in ("폐업", "휴업") or e["상태"] != "반영" or e["fid"] in out: continue
            r = self.cm.rows.get(e["fid"])
            if r is None or r.get("대안후보") != "아니요": continue   # 같은 가게가 인허가만 새로 받아 다시 연 경우
            if str(r.get("제외사유", "")).startswith("인허가가 엇갈림"): continue   # 정말 닫았는지 모름 → '확인 요청'으로
            w = CP.window(r["업종"], e.get("날짜", ""), (e.get("접수") or "")[:10], r.get("출처", ""), datetime.date.fromisoformat(today()))
            if w and w["단계"] == "지남": continue   # 대상 기간 = 주민 화면과 같은 시설 공개 기간(안내 기간, pipeline/closure_policy.py) — 한 기준 (10/21)
            out[e["fid"]] = {"fid": e["fid"], "상호": r["상호"], "업종": r["업종"], "구군": r["구군"], "주소": r["주소"], "경도": r["경도"], "위도": r["위도"],
                             "폐업일자": e.get("날짜", ""), "변화": e["종류"], "출처": e["출처"], "감지": e["접수"][:10], "새가게": None, "새가게업종": None,
                             "시작일": (w or {}).get("시작일"), "공개까지": (w or {}).get("안내까지")}
            same = [s for s in e.get("같은자리", []) if s.get("상호")]
            if same: out[e["fid"]].update(새가게=same[0]["상호"], 새가게업종=same[0].get("업종"))
        # 보고(긴급·주의) 중인 곳은 공개 기간이 지나도 담당자 '처리함' 또는 공백 해소 전까지 지자체 화면에 남김 (10/21 헌준님 결정). 주민 화면·관찰·검토 완료는 공개 기간 그대로
        for fid, x in _jload(os.path.join(GOV, "followup.json"), {}).items():
            if fid in out or x.get("상태") != "남아 있음" or fid in self.handled: continue   # handled: 담당자가 '처리함'으로 표시한 곳
            out[fid] = {"fid": fid, "상호": x.get("상호"), "업종": x.get("업종"), "구군": x.get("구군"), "주소": x.get("주소") or "", "경도": x.get("경도"), "위도": x.get("위도"),
                        "폐업일자": x.get("폐업일자") or "", "변화": "폐업", "출처": "보고 유지", "새가게": None, "새가게업종": None, "공개까지": None, "보고유지": True}
        for fid, x in out.items(): self._stop_fix(fid, x)
        return out

    def _pub_k(self, fid):
        """공립 유치원(병설·단설)인지: 유치원알리미 설립 유형"""
        E = self.cm.engine()
        return fid in E.F.index and E.F.at[fid, "업종코드"] == "PUB:유치원" and str(E.F.at[fid, "참고"] or "").startswith("공립")
    def _pub_alt(self, fid, r_m=PUB_NEAR_M):
        """반경 r_m 안 다른 공립 유치원(운영 중)의 남는 자리 (정원 − 현원, 둘 다 아는 곳만). 가까운 순"""
        E = self.cm.engine()
        if fid not in E.F.index: return None
        x0, y0 = float(E.F.at[fid, "경도"]), float(E.F.at[fid, "위도"])
        K = E.F[(E.F["업종코드"] == "PUB:유치원") & (E.F["대안후보"] == "예") & E.F["참고"].astype(str).str.startswith("공립")]
        out = []
        for f, r in K.iterrows():
            if f == fid: continue
            try: d = ((float(r["경도"]) - x0) * 90200) ** 2 + ((float(r["위도"]) - y0) * 110540) ** 2
            except Exception: continue
            d = d ** 0.5
            if d > r_m: continue
            sc = E.scale(f) or {}
            if sc.get("정원") is None or sc.get("현원") is None: continue
            out.append({"상호": re.sub(r"^대구", "", str(r["상호"])).replace("초등학교병설유치원", "초병설유치원"), "거리_m": int(d), "여유": max(0, int(sc["정원"]) - int(sc["현원"]))})
        out.sort(key=lambda x: x["거리_m"])
        return {"반경_m": r_m, "곳": len(out), "여유": sum(x["여유"] for x in out), "목록": out[:3]}
    def _reorg(self):
        if not hasattr(self, "_RG"): self._RG = _jload(os.path.join(GOV, "kinder_reorg.json"), {})
        return self._RG
    def kinder_stop(self, fid, name):
        """공립 병설유치원 운영 종료 시점과 근거 (10/21): 교육청 통폐합·휴원 결정이 있으면 그 날짜, 없으면 정보공시가 멈춘 차수로 추정.
        유치원 휴원·폐원·통합은 학년도 시작(3월 1일)에 맞춰 정해짐 → 공시 Y년 2차가 마지막이면 Y+1년 3월 1일, 1차가 마지막이면 Y년 9월 1일(2학기)부터 운영하지 않은 것으로 봄"""
        R = self._reorg(); n = re.sub(r"\s", "", str(name or ""))
        if n in (R.get("통합") or {}): return R.get("시행"), f"교육청 통합: {R['통합'][n].replace('대구', '', 1).replace('초등학교병설유치원', '초병설유치원')}으로 통합 운영"
        if n in (R.get("폐원") or []): return R.get("시행"), "교육청 폐원(장기 휴원) 결정"
        if n in (R.get("폐교") or []): return R.get("시행"), "초등학교 폐교·통합에 따른 폐원"
        for g in R.get("거점") or []:
            if n in g.get("대상", []): return g.get("휴원부터"), f"교육청 휴원 · {g['거점'].replace('대구', '', 1).replace('초등학교병설유치원', '초병설유치원')}(거점)으로 배치 · {g.get('지원', '')}"
        txt = " ".join(str(x) for x in [(self.cm.rows.get(fid) or {}).get("참고"), (self.cm.rows.get(fid) or {}).get("제외사유")] + [e.get("근거") for e in self.cm.events if e.get("fid") == fid])
        m = re.search(r"마지막 공시 (\d{4})년 ([12])차", txt)
        if m: y, k = int(m.group(1)), int(m.group(2)); return (f"{y + 1}-03-01" if k == 2 else f"{y}-09-01"), "정보공시 중단 시점으로 추정"
        return None, None
    def _stop_fix(self, fid, x):
        """유치원이면 운영 종료일을 교육청 결정·공시 기준으로 고침 (확인한 날이 아니라 실제로 문을 닫은 학년도 시작일)"""
        if not (str(fid).startswith("P:유치원") or x.get("업종") == "유치원"): return x
        d, why = self.kinder_stop(fid, x.get("상호"))
        if d and (not x.get("폐업일자") or d < str(x["폐업일자"])[:10]): x.update(폐업일자=d, 운영종료_근거=why)
        elif why: x["운영종료_근거"] = why
        return x
    def unsure(self):
        """확인 요청: 짝지은 인허가는 닫혔는데 같은 가게의 다른 인허가가 아직 영업인 곳 (pipeline/permit_status.py). 담당자가 전화 등으로 확인하면 반영"""
        out = {}; seen = set()
        for e in self.cm.events:
            if e["상태"] != "확인 필요" or e["종류"] not in ("폐업", "휴업"): continue
            r = self.cm.rows.get(e["fid"])
            reason = str((r or {}).get("제외사유", ""))
            if r is None or not reason.startswith(("인허가가 엇갈림", "주민 제보", "유치원알리미", "어린이집정보공개포털")): continue
            key = (re.sub(r"[\s()（）]", "", str(r["상호"])), " ".join(str(r["주소"]).split()[:4]))   # 같은 가게가 두 번 잡힌 경우 하나로
            if key in seen or e["fid"] in out: continue
            seen.add(key)
            out[e["fid"]] = {"fid": e["fid"], "변화id": e["id"], "상호": r["상호"], "업종": r["업종"], "구군": r["구군"], "주소": r["주소"], "경도": r["경도"], "위도": r["위도"],
                             "전화": r.get("전화", ""), "폐업일자": e.get("날짜", ""), "남은인허가": (e.get("분류") or {}).get("남은인허가", []),
                             "까닭": reason.replace("인허가가 엇갈림 — ", ""), "출처": e["출처"], "제보": reason.startswith("주민 제보"), "제보내용": e.get("근거", "") if reason.startswith("주민 제보") else ""}
            self._stop_fix(e["fid"], out[e["fid"]])
        return out

    def resolve(self, fid, closed, who="담당자"):
        """담당자의 확인 결과를 반영: 문 닫음 맞음 → 문 닫은 곳으로 / 영업 중 → 다시 안내 대상으로. 이후 날마다 하는 재판정은 이 판단을 따름"""
        u = self.unsure().get(fid)
        if not u: return {"결과": "확인할 것이 아님"}
        if closed: res = self.cm.confirm(u["변화id"], who=who)
        else:
            res = self.cm.reopen(fid, source="담당자 확인", who=who)
            for e in self.cm.events:
                if e["id"] == u["변화id"]: e.update({"상태": "반려", "반려": {"담당자": who, "이유": "영업 중 확인", "때": now().isoformat(timespec="seconds")}})
            self.cm._save()
        self.an.pop(fid, None)
        return res

    def tidy_reports(self, days=30):
        """주민 제보 정리: 30일이 지나도 폐업 근거가 없으면 다시 대안으로 안내 (일반 가게, 그리고 닫혀도 공백이 없는 공공·복지·의료 시설).
        닫혔을 때 공백이 생기는 공공 시설은 담당자 확인을 기다림"""
        E = self.cm.engine(); n = 0; U = self.unsure()
        for e in list(self.cm.events):
            if e["상태"] != "확인 필요" or e["출처"] != "주민 제보": continue
            r = self.cm.rows.get(e["fid"])
            if not r or not str(r.get("제외사유", "")).startswith("주민 제보"): continue
            if self._rc().is_public(e["fid"]) and self.an.get(e["fid"]) and e["fid"] in U and self.severity({"fid": e["fid"], "시설": U[e["fid"]], "분석": self.an[e["fid"]]})[0]:
                continue   # 닫혔을 때 공백이 생기는 공공 시설은 담당자 확인을 기다림
            ds = days_since(e.get("날짜"))
            if ds is not None and ds > days:
                self.cm.reopen(e["fid"], source=f"주민 제보 {days}일 지남 (폐업 근거 없음)", who="에이전트")
                e.update({"상태": "반려", "반려": {"담당자": "에이전트", "이유": f"{days}일 동안 폐업 근거 없음", "때": now().isoformat(timespec="seconds")}}); n += 1
        if n: self.cm._save()
        return {"다시 안내": n}

    def learn(self, text, fid=None, who="담당자"):
        """담당자가 '이 판단은 틀렸어요'로 알려 준 것을 원칙으로 저장하고, 그 원칙으로 다시 판단 (배운 원칙이 바뀌면 판단 기록이 무효가 됨)"""
        with self.lock:
            x = self.add_lesson(text, fid, who); self.brief()
        return x

    def refresh_brief(self):
        with self.lock: self.brief()

    def _rc(self):
        from report_check import ReportCheck
        if getattr(self, "_rcobj", None) is None: self._rcobj = ReportCheck(self)
        return self._rcobj
    def _review_due(self):
        from report_check import last_review
        lr = last_review(); t = datetime.date.fromisoformat(today())
        if lr is None: return t.weekday() == 0
        d = datetime.date.fromisoformat(lr["날짜"])
        return (t.weekday() == 0 and d != t) or (t - d).days >= 8   # 월요일, 또는 월요일을 놓쳤으면 그다음 점검 때
    def review_reports(self, only_new=False):
        return self._rc().weekly(only_new=only_new)

    def report_and_refresh(self, fid, note=""):
        """주민 제보 (10/20 원칙): 담당자에게 바로 넘기지 않음. 확인 전까지 대안으로 권하지 않고, AI가 교차검증해 분명하면 스스로 반영.
        공공·복지·의료 시설은 바로 판단하고, 보류되면 문을 닫았을 때 공백이 생기는 곳만 보고서의 '폐업 확인 필요'로 (일반 가게는 다음 날 아침 검토, 보류는 매주 다시)
        인허가로 영업이 확인된 일반 가게는 제보 한 건으로 안내에서 빼지 않음 (AI가 폐업을 확인한 뒤 뺌)"""
        with self.lock:
            res = self.cm.report(fid, note=note[:200], source="주민 제보")
            public = self._rc().is_public(fid); applied = None
            if res.get("결과") in ("확인 요청", "제보 더함") and public:
                try: applied = (self._rc().analyze_public(fid) or {}).get("반영")
                except Exception: pass
            if (res.get("결과") == "확인 요청" and not res.get("안내유지")) or applied in ("폐업 반영", "다시 안내"):
                self._rebuild(True); self.analyze_all(); self.brief()
            elif res.get("결과") == "제보 더함" and public: self.brief()
            res["공공"] = public; res["AI반영"] = applied
        return res

    def field_and_refresh(self, fid, state, date="", note="", who="담당자"):
        """담당자 현장·신고 확인 (10/22): 확인 요청 목록에 없는 시설도 담당자가 확인한 사실을 반영
        state: 폐업·휴업 = 영업 중으로 되어 있던 곳이 문 닫음 (폐원 신고 처리 등) / 운영 = 문 닫은 것으로 되어 있던 곳이 영업 중 (현장 확인)"""
        with self.lock:
            if state == "운영": res = self.cm.reopen(fid, date=date, source="담당자 현장 확인", who=who)
            else:
                res = self.cm.close(fid, date=date or today(), kind="휴업" if state == "휴업" else "폐업", source="담당자 확인", note=note[:120], who=who)
                if res.get("결과") == "반영":
                    r = self.cm.row(fid)
                    if not str(r.get("폐업일자") or "").strip(): r["폐업일자"] = date or today()
                    if state == "휴업": r["제외사유"] = str(r.get("제외사유") or "") + " (휴원·휴업)"
                    self.cm._put(r, res["변화"]); self.cm._save()
            if res.get("결과") == "반영": self._rebuild(True); self.analyze_all(); self.brief()
        return res

    def resolve_and_refresh(self, fid, closed, who="담당자", pause=False):
        """확인 결과 반영 → 폐업 목록·엔진 다시 맞춤 → 보고서 다시 (점검과 겹치지 않게 잠금)
        pause: 휴원·휴업 (10/21): 운영 중단으로 반영하되 폐업과 구분. 공식 자료에 다시 운영으로 나오면 저절로 다시 안내 (official_check·childcare_check)"""
        with self.lock:
            res = self.resolve(fid, closed, who)
            if closed and pause and res.get("결과") == "반영":
                r = self.cm.row(fid); r["제외사유"] = str(r.get("제외사유") or "") + " (휴원·휴업)"; self.cm._save()
            if res.get("결과") == "반영":
                self._rebuild(True); self.analyze_all(); self.brief()
        return res

    # ---------- 학습 기준과 심각 판정 (engine/severity.py) ----------
    _crit = None
    def _special(self, lid):
        """생명 직결 진료(SV.SPECIAL)를 하는 병원: {fid: 병원 이름}. 같은 병원이 상가·인허가 자료에 두 번 있으면 이름으로 묶음"""
        if self._crit is None:
            p = os.path.join(self.root, "data", "processed", "critical_care.csv")
            self._crit = pd.read_csv(p) if os.path.exists(p) else pd.DataFrame()
        out = {}
        if self._crit.empty: return out
        for _, r in self._crit.iterrows():
            if any((r.get(c) or 0) > 0 for c in SV.SPECIAL.get(lid, [])) and isinstance(r.get("fid"), str):
                for f in r["fid"].split(";"): out[f] = r["요양기관명"]
        return out
    def _special_alts(self, lid, fid, n=3):
        """문 닫은 병원에서 가까운 같은 진료 병원 (직선 거리)"""
        E = self.cm.engine(); S = self._special(lid); me = S.get(fid); r = E.F.loc[fid]; seen = {}
        for p in self._prov_all(lid):
            if S.get(p) == me or p not in E.F.index: continue
            d = ((float(E.F.at[p, "x"]) - float(r["x"])) * 90200) ** 2 + ((float(E.F.at[p, "y"]) - float(r["y"])) * 110540) ** 2
            seen[S[p]] = min(seen.get(S[p], (9e18, p)), (d, p))
        best = sorted(seen.values())[:n]
        return [{"상호": E.F.at[p, "상호"], "업종": E.F.at[p, "업종"], "주소": E.F.at[p, "주소"], "전화": E.F.at[p, "전화"], "걷는시간_분": None, "직선_m": round(d ** 0.5),
                 "경도": _num(E.F.at[p, "x"]), "위도": _num(E.F.at[p, "y"])} for d, p in best]
    def sp_kind(self, fid):
        """공공 체육시설·공원이면 '공공 체육시설' / '공원', 아니면 None (공공 자료 기준)"""
        E = self.cm.engine()
        if fid not in E.F.index or str(E.F.at[fid, "출처"]) != "공공": return None
        u = str(E.F.at[fid, "업종"])
        if u in SPORT_UP: return "공공 체육시설"
        if u in PARK_UP: return "공원"
        return None
    def sp_package(self, fid, kind, lon, lat):
        """(10/29 헌준님) 공공 체육시설·공원 폐쇄 공백의 담당자 대응 자료: 예산 검토 자료만이 아니라 즉시·단기·중장기 대응과 판단 근거를 함께
        대체 시설: 같은 공공 시설(공공 체육시설끼리·공원끼리) 가운데 가까운 3곳 (직선거리) · 대응: 법령 근거가 있는 것만 (engine/gov_programs.py)"""
        E = self.cm.engine(); alt = []
        try:
            from conversation import hav
            lid = "G:공공체육" if kind == "공공 체육시설" else "P10.1.04"
            P = [f for f in self._prov_all(lid) if f != fid and f in E.F.index and self.sp_kind(f) == kind]
            up0 = str(E.F.at[fid, "업종"]) if fid in E.F.index else ""
            d = sorted((hav(lon, lat, float(E.F.at[f, "경도"]), float(E.F.at[f, "위도"])), f) for f in P if E.F.at[f, "경도"] == E.F.at[f, "경도"])
            same = [x for x in d if str(E.F.at[x[1], "업종"]) == up0][:2]   # 같은 종류(예: 축구장 → 축구장) 먼저
            other = [x for x in d if x not in same][:3 - len(same)]
            alt = [{"시설": str(E.F.at[f, "상호"]), "종류": str(E.F.at[f, "업종"]), "직선거리_m": int(round(m))} for m, f in same + other]
        except Exception: pass
        nm = alt[0]["시설"] + f" (직선 {alt[0]['직선거리_m'] / 1000:.1f}km)" if alt else "인근 동종 공공 시설"
        if kind == "공원":
            steps = [{"단계": "즉시", "할일": f"대체 공원 안내: {nm} · 행정복지센터·공동주택 게시판 게시", "근거": "주민 이용 안내"},
                     {"단계": "단기", "할일": "인근 유휴부지·소규모 공공용지의 쉼터·소공원 조성 검토", "근거": "도시공원 및 녹지 등에 관한 법률 시행규칙 별표 3 (유치거리)"},
                     {"단계": "중장기", "할일": "유치거리(도보권 근린공원 1km·근린생활권 500m·어린이공원 250m) 미충족 지역 공원 조성의 도시·군관리계획 반영", "근거": "도시공원 및 녹지 등에 관한 법률 시행규칙 별표 3"}]
        else:
            steps = [{"단계": "즉시", "할일": f"대체 시설 안내: {nm} · 기존 이용 동호회·주민 대상 이용 안내", "근거": "주민 이용 안내"},
                     {"단계": "단기", "할일": "인근 학교 운동장·체육관 주민 개방 협의 · 공원 내 운동기구·다목적 구장 설치 검토", "근거": "체육시설의 설치·이용에 관한 법률 제6조, 같은 법 시행령 제4조"},
                     {"단계": "중장기", "할일": "생활체육시설 확충 지원 공모(국민체육진흥기금) 신청 또는 자체 예산 편성 검토", "근거": "국민체육진흥법 · 체육시설의 설치·이용에 관한 법률 제6조"}]
        return {"대체_시설": alt, "대응_단계": steps,
                "게시_기간": "폐쇄일부터 2년 (시설 조성은 본예산 편성·공모 일정에 따라 2개 회계연도에 걸쳐 검토)",
                "입지_검토": "새 시설 입지 후보는 업무 보조의 입지 후보 산정(영향 주민 최다 지점)으로 확인"}
    def _sp_pkg(self, r_, k_):
        try: return self.sp_package(r_["fid"], k_, float(r_["경도"]), float(r_["위도"]))
        except Exception: return {}
    def _is_sport(self, fid):
        E = self.cm.engine()
        if fid not in E.F.index or str(E.F.at[fid, "출처"]) != "공공": return False
        u = str(E.F.at[fid, "업종"])
        return u in SPORT_UP or (u in PARK_UP and str(E.F.at[fid, "공원운동시설"]) in ("True", "1", "1.0"))
    _sport = None
    def _sport_all(self, broad=False):
        if self._sport is None:
            E = self.cm.engine(); F = E.F
            m = (F["출처"] == "공공") & F["x"].notna() & (F["업종"].isin(SPORT_UP) | (F["업종"].isin(PARK_UP) & F["공원운동시설"].astype(str).isin(["True", "1", "1.0"])))
            self._sport = {"예": sorted(F.index[m & (F["대안후보"] == "예")]), "넓게": sorted(F.index[m & F["대안후보"].isin(["예", "확인 필요"])])}
        return self._sport["넓게" if broad else "예"]
    def _sport_alts(self, fid, n=3):
        """문 닫은 체육시설에서 가까운 공공 체육시설 (직선 거리)"""
        E = self.cm.engine(); r = E.F.loc[fid]
        P = [p for p in self._sport_all() if p != fid]
        if not P or r["x"] != r["x"]: return []
        X = E.F.loc[P]; d = (((X["x"] - float(r["x"])) * 90200) ** 2 + ((X["y"] - float(r["y"])) * 110540) ** 2) ** 0.5
        return [{"상호": E.F.at[p, "상호"], "업종": E.F.at[p, "업종"], "주소": E.F.at[p, "주소"], "전화": E.F.at[p, "전화"], "걷는시간_분": None, "직선_m": round(float(d[p])),
                 "경도": _num(E.F.at[p, "x"]), "위도": _num(E.F.at[p, "y"])} for p in d.sort_values().index[:n]]
    def _prov_all(self, lid, broad=False, kinds=None):
        """broad: 그 일을 하는지 모르는 곳(예: 채소를 파는지 모르는 동네 슈퍼)·영업 확인이 안 된 곳까지 대신 갈 곳으로 봄
        kinds: 이 세부 종류들만 (같은 묶음끼리 볼 때). 이때는 중심 종류·공공 근거 종류로 거르지 않음"""
        E = self.cm.engine()
        if kinds is not None and lid not in SV.SPECIAL:
            return sorted({p for kk in kinds if (lid, kk) in E.kind for p in (self.cm.providers_broad if broad else self.cm.providers)(lid, kk, None)})
        if lid == "G:공공체육": return self._sport_all(broad)   # 공공 체육시설끼리 (민간 헬스장은 대신 갈 곳으로 세지 않음)
        if lid in SV.SPECIAL:   # 생명 직결 진료: 심평원 시설정보로 아는 병원 가운데 지금 영업 중인 곳
            ok = {"예", "확인 필요"} if broad else {"예"}
            return sorted(p for p in self._special(lid) if p in E.F.index and E.F.at[p, "대안후보"] in ok and E.F.at[p, "x"] == E.F.at[p, "x"])
        ks = [kk for (L, kk) in E.kind if L == lid] or [None]
        P = {p for kk in ks for p in (self.cm.providers_broad if broad else self.cm.providers)(lid, kk, None)}
        if not broad and lid == MART_KIND[0] and (lid, MART_KIND[1]) in E.kind:
            P |= {p for p in self.cm.providers_broad(lid, MART_KIND[1], None) if E.F.at[p, "대안후보"] == "예" and MART_NAME.search(str(E.F.at[p, "상호"]))}
        # 대신 갈 수 있는 곳: 그 일의 중심 종류(CORE_ONLY)가 있으면 그것, 없으면 공공 근거가 가리키는 종류 (예: 외래 진료는 1차 진료과)
        # (10/19) 전에는 늘 공공 근거의 종류만 써서, 장보기는 전통시장만 대신 갈 곳으로 셌음 → 슈퍼마켓이 있어도 없는 것처럼 계산됨
        pk = CORE_ONLY.get(lid) or (PB.PUBLIC.get(lid) or {}).get("kinds")
        if pk: P = {p for p in P if any(k in pk for (L, g, k) in E.of_fid.get(p, []) if L == lid)}
        return sorted(P)
    def _w(self, who):
        """누구 기준으로 셀지: 65세 이상 / 영유아(0~5세) / 아동(6~12세) / 주민 전체"""
        C = self.cm._C
        return {"65세 이상": C.pop65, "영유아": getattr(C, "pop05", None), "아동": getattr(C, "pop612", None)}.get(who) if who in ("65세 이상", "영유아", "아동") else C.pop
    def _std(self, lid):
        """(체감 기준 m, 누구 기준, 까닭). 헌준님과 정한 표(SV.STD)에 없으면 분류표의 국가 최저기준(도보 N분, 보통 걸음 1m/s)으로"""
        if lid in SV.STD: return SV.STD[lid]
        from impact import threshold
        leaf = self.cm.engine().leaf.get(lid)
        if not leaf: return None
        m, basis = threshold(leaf)
        return (int(m * 60), "전체", f"{leaf['name']}: {basis}")
    @staticmethod
    def _wq(x, w, q):
        m = np.isfinite(x) & (w > 0); x, w = x[m], w[m]
        if not len(x): return None
        o = np.argsort(x); x, c = x[o], np.cumsum(w[o]); return float(x[np.searchsorted(c, c[-1] * q)])
    def learn_baseline(self):
        """새 자료로 대구 주민이 기능마다 얼마나 멀리 다니는지 다시 계산 → 가장 멀리 다니는 5%의 거리를 학습 기준으로 (변화는 기록으로 남음)"""
        # (10/19) 도심(동) 주민에게서만 배움: 대구 전체로 배우면 원래 먼 농촌(주민의 11%)에 끌려 기준이 늘어남 (약국 1.9km → 2.5km)
        #  → 도심의 공백을 놓치고, 농촌은 '원래 멀다'는 이유로 기준이 더 느슨해짐. 생활에 필요한 거리는 도심이든 농촌이든 같게 봄
        E = self.cm.engine(); C = self.cm._C; out = {"날짜": today(), "배운곳": "도심(동) 주민"}
        names = np.array([str(x) for x in C.hjd_name]); urban = ~(np.char.endswith(names, "읍") | np.char.endswith(names, "면"))[C.hjd]
        lids = list(SV.STD) + [k for k in (getattr(self, "_base", None) or {}) if isinstance((self._base or {}).get(k), dict) and k not in SV.STD]
        for lid in lids:
            st = self._std(lid)
            if not st: continue
            std, who, why = st
            P = self._prov_all(lid); sn = [E.walk.snap.get(p) for p in P if E.walk.snap.get(p)]
            if not sn: continue
            w0 = self._w(who)
            if w0 is None: continue
            d = C.dist(sn, limit=max(6000, std * 3)); w = w0 * urban
            # 심각은 예전처럼 대구 전체에서 가장 다니기 어려운 5%가 될 때만 (도심 약국이 '심각'으로 잡히던 오류를 되풀이하지 않게), 주의는 도심 기준
            out[lid] = {"이름": (E.leaf.get(lid) or {}).get("name") or SV.NAME.get(lid, lid), "시설수": len(sn), "중앙값_m": self._wq(d, w, .5), "하위5퍼_m": self._wq(d, w, .95), "전체_하위5퍼_m": self._wq(d, w0, .95), "체감기준_m": std}
        old = _jload(os.path.join(GOV, "baseline.json"), {})
        _jsave(os.path.join(GOV, "baseline.json"), out); self._base = out
        with open(os.path.join(GOV, "baseline_history.jsonl"), "a", encoding="utf-8") as fh: fh.write(json.dumps(out, ensure_ascii=False) + "\n")
        ch = [f"{v['이름']} {old[k]['하위5퍼_m']:.0f}→{v['하위5퍼_m']:.0f}m" for k, v in out.items() if isinstance(v, dict) and isinstance(old.get(k), dict) and old[k].get("하위5퍼_m") and v.get("하위5퍼_m") and abs(old[k]["하위5퍼_m"] - v["하위5퍼_m"]) >= 20]
        return {"기능": sum(isinstance(v, dict) for v in out.values()), "바뀐 기준": ch}
    def baseline(self):
        if not getattr(self, "_base", None): self._base = _jload(os.path.join(GOV, "baseline.json"), {})
        if not self._base.get("날짜"): self.learn_baseline()
        return self._base
    def _base_of(self, lid):
        """그 기능의 학습 기준. 처음 보는 기능이면 그 자리에서 배워 둠 (다음 평일 점검부터는 함께 다시 배움)"""
        b = self.baseline()
        if lid in b: return b[lid]
        st = self._std(lid)
        if not st: return None
        E = self.cm.engine(); C = self.cm._C
        P = self._prov_all(lid); sn = [E.walk.snap.get(p) for p in P if E.walk.snap.get(p)]
        if not sn: return None
        names = np.array([str(x) for x in C.hjd_name]); urban = ~(np.char.endswith(names, "읍") | np.char.endswith(names, "면"))[C.hjd]
        w0 = self._w(st[1])
        if w0 is None: return None
        d = C.dist(sn, limit=max(6000, st[0] * 3)); w = w0 * urban
        b[lid] = {"이름": (E.leaf.get(lid) or {}).get("name") or SV.NAME.get(lid, lid), "시설수": len(sn), "중앙값_m": self._wq(d, w, .5), "하위5퍼_m": self._wq(d, w, .95),
                  "전체_하위5퍼_m": self._wq(d, w0, .95), "체감기준_m": st[0]}
        _jsave(os.path.join(GOV, "baseline.json"), b)
        return b[lid]
    def _severe(self, fid, lid, broad=False, kind=None, mask=False):
        """사실 재기: 이 시설이 닫혀, 그전엔 체감 기준 안에 살던 주민이 '체감 기준'과 '학습 기준(도심)' 가운데 먼 쪽 밖으로, 500m 넘게 멀어지는 주민
        broad: 그 일을 하는지 모르는 곳까지 대신 갈 곳으로 봄 / kind: 같은 세부 종류(예: 시장은 시장끼리)만 대신 갈 곳으로 봄
        보고할지는 여기서 정하지 않음 (gap_agent)"""
        E = self.cm.engine(); C = self.cm._C; one = E.walk.snap.get(fid)
        if not one: return None
        if lid == "P04.2.01" and kind is None and getattr(C, "pop02", None) is not None: return None if mask else self._severe_child(fid, broad)
        std = self._std(lid); b = self._base_of(lid)
        if not std or not b: return None
        thr = max(std[0], b.get("하위5퍼_m") or 0)
        P = self._prov_all(lid, broad, (set(kind) if isinstance(kind, (set, frozenset, tuple, list)) else {kind}) if kind else None)
        if lid in SV.SPECIAL: S = self._special(lid); P = [p for p in P if S.get(p) != S.get(fid)]   # 같은 병원의 다른 기록은 대신 갈 곳이 아님
        lim = max(6000, std[0], b.get("전체_하위5퍼_m") or 0) + 2000   # 먼 거리 기준(분만 15km 등)도 끝까지 잼 (기본은 6km까지만 잼)
        # 문 닫은 곳은 이미 대신 갈 곳 목록에 없으므로, 같은 기능의 '나머지 거리'는 하루에 한 번만 계산해 씀 (가정 시험처럼 열려 있는 곳이면 새로 계산)
        if not hasattr(self, "_rest"): self._rest = {}; self._own = {}
        key = (lid, broad, tuple(sorted(kind)) if isinstance(kind, (set, frozenset, tuple, list)) else kind, lim)
        if fid not in P and key in self._rest: rest = self._rest[key]
        else:
            rest = C.dist([E.walk.snap.get(p) for p in P if p != fid and E.walk.snap.get(p)], limit=lim)
            if fid not in P: self._rest[key] = rest
        okey = (fid, lim)
        if okey not in self._own: self._own[okey] = C.dist([one], limit=lim)
        own = self._own[okey]; before = np.minimum(rest, own)
        rural_only = False
        # 그전엔 체감 기준 안에서 쓰던 주민이, 학습 기준(대구 하위 5%)보다도 멀어지고, 실제로 500m 넘게 멀어질 때만 (기준선 근처에서 조금 넘는 경우는 셈하지 않음)
        with np.errstate(invalid="ignore"): hit = (before <= std[0]) & (rest > thr) & ((rest - before) >= SV.WORSE_M)
        if rural_only:   # 읍·면 주민만 셈 (예: 시장)
            names = np.array([str(x) for x in C.hjd_name]); rural = np.char.endswith(names, "읍") | np.char.endswith(names, "면")
            hit = hit & rural[C.hjd]
        if mask: return hit   # 영향 구역(100m 칸) — 공개 화면에서 색칠 (engine/area_gap.py)
        thr_all = max(thr, b.get("전체_하위5퍼_m") or 0)
        with np.errstate(invalid="ignore"): hit_all = hit & (rest > thr_all)
        kid = std[1] in SV.CHILD_WHO; wk = self._w(std[1]) if kid else None
        if kid and wk is None: return None
        if not hit.any(): return {"기준_m": thr, "체감기준_m": std[0], "학습기준_m": b.get("하위5퍼_m"), "밀려난주민": 0, "밀려난_65세이상": 0, "심각_주민": 0, "심각_65세이상": 0,
                                  **({"누구": std[1], "밀려난_아이": 0, "심각_아이": 0} if kid else {})}
        dongs = {}
        for h in np.unique(C.hjd[hit]):
            m = hit & (C.hjd == h); dongs[str(C.hjd_name[h])] = round(float(C.pop[m].sum()))
        aft = np.where(np.isfinite(rest[hit]), rest[hit], lim + 1.0)   # 잰 거리 밖이면 '그보다 멂'
        chk = self._straight(hit, [p for p in P if p != fid], np.where(np.isfinite(rest[hit]), rest[hit], np.nan), (wk if kid else C.pop)[hit])
        return {"기준_m": thr, "체감기준_m": std[0], "학습기준_m": b.get("하위5퍼_m"), "누구": std[1], "까닭": std[2], "이름": kind,
                "밀려난주민": round(float(C.pop[hit].sum())), "밀려난_65세이상": round(float(C.pop65[hit].sum())),
                "심각_주민": round(float(C.pop[hit_all].sum())), "심각_65세이상": round(float(C.pop65[hit_all].sum())), "심각기준_m": thr_all,
                **({"밀려난_아이": round(float(wk[hit].sum())), "심각_아이": round(float(wk[hit_all].sum())), "아이": SV.CHILD_WHO[std[1]]} if kid else {}),
                "거리_전_m": self._wq(before[hit], (wk if kid else C.pop)[hit], .5), "거리_후_m": self._wq(aft, (wk if kid else C.pop)[hit], .5), "잰거리_m": lim, "교차검증": chk,
                "동": sorted(dongs.items(), key=lambda x: -x[1])[:4]}
    def audit(self, it, A=None):
        """보고 전 스스로 하는 계산 검토 (10/20 헌준님: 공백 계산에 오차·오류가 있으면 절대 안 됨, 교차검증으로 스스로 검토)
        돌려줌 {'통과': bool, '문제': [보고를 막는 계산 오류], '참고': [판단할 때 따져 볼 점]}"""
        A = A or it.get("판단재료") or self.assess(it)
        if not A: return {"통과": False, "문제": ["잴 공백이 없음"], "참고": []}
        E = self.cm.engine(); fx = A["사실"][0]; hard = []; soft = []
        sn = E.walk.snap.get(it["fid"])
        if sn and sn[2] > 150: hard.append(f"문 닫은 곳이 길에서 {sn[2]:.0f}m 떨어져 있어 걷는 거리 계산을 믿기 어려움")
        if fx.get("돌봄기관"):
            e = fx["돌봄기관"]
            if not (e.get("현원") or e.get("정원")) and not (e.get("가장가까운같은기관_m") or 0) > SV.ENROLL_NEAR_M: hard.append("이용자 수와 대체 기관 거리를 모두 모름")
            return {"통과": not hard, "문제": hard, "참고": soft}
        s = fx["전체"] if self._enough(fx.get("전체"), fx.get("읍면") is True) else fx.get("같은종류")
        if not s: return {"통과": False, "문제": ["잴 공백이 없음"], "참고": []}
        rule = []
        if not GA.area_ok(fx):   # 생활권 원칙 (10/20): 읍·면 민간 가게인데 생활권이 끊기지 않음 → 보고하지 않고 관찰 (계산 오류와 따로 둠)
            iso = fx.get("고립_m")
            rule.append(f"{fx.get('생활권') or '읍·면'} {'보조 가게' if fx.get('보조공급처') else '가게'}이고 같은 일을 할 곳이 직선 {iso/1000:.1f}km에 있어 생활권이 끊기지 않음" if iso is not None
                        else f"{fx.get('생활권') or '읍·면'} 민간 가게로 생활권이 끊긴다는 근거가 없음")
        if (s.get("거리_전_m") or 0) > s["체감기준_m"] + 1: hard.append("폐업 전에도 기준 거리 밖이던 주민을 센 계산 오류")
        if (s.get("거리_후_m") or 0) <= s["기준_m"]: hard.append("폐업 뒤 거리가 기준 안인데 공백으로 셈")
        if (s.get("거리_후_m") or 0) - (s.get("거리_전_m") or 0) < SV.WORSE_M: hard.append("더 멀어지는 거리가 500m 미만")
        chk = s.get("교차검증") or {}
        if chk.get("직선보다_짧은_비율", 0) > 0.05: hard.append("걷는 거리가 직선거리보다 짧게 나온 점이 있어 길 계산 오류 의심")
        if chk.get("우회비", 1) >= 3: soft.append(f"남은 곳까지 직선거리의 {chk['우회비']:.1f}배를 돌아감 (강·산·철도·고속도로로 막혔는지 확인)")
        b = fx.get("넓게")
        key = "밀려난_아이" if s.get("아이") else "밀려난주민"
        if b and s.get(key) and b.get(key, 0) < 0.5 * s[key]: soft.append("그 일을 하는지 모르는 가게까지 넣으면 공백이 절반 아래로 줄어듦 (자료 부족 가능)")
        if (s.get("거리_후_m") or 0) >= (s.get("잰거리_m") or 1e9): soft.append(f"가장 가까운 남은 곳이 측정 범위({(s.get('잰거리_m') or 0)/1000:.0f}km) 밖 · 실제 거리는 {(s.get('잰거리_m') or 0)/1000:.0f}km 이상")
        return {"통과": not hard and not rule, "문제": hard, "원칙": rule, "참고": soft}
    def _straight(self, hit, P, aft, w):
        """교차검증 (10/20): 걷는 길 거리를 직선거리와 견줌. 걷는 거리가 직선보다 짧으면 계산 오류, 몇 배나 길면 강·산·철도로 돌아가는 길인지 확인할 것
        hit: 밀려난 격자 점, P: 남은 시설, aft: 그 점들의 걷는 거리(m), w: 사람 수"""
        from scipy.spatial import cKDTree
        E = self.cm.engine(); C = self.cm._C; KX = np.cos(np.radians(35.87)) * 111320; KY = 110540
        X = E.F.loc[[p for p in P if p in E.F.index], ["x", "y"]].astype(float).dropna()
        if X.empty or not hit.any(): return {}
        d, _ = cKDTree(np.c_[X["x"] * KX, X["y"] * KY]).query(np.c_[C.lon[hit] * KX, C.lat[hit] * KY])
        ok = np.isfinite(aft) & (d > 0)
        if not ok.any(): return {"직선_후_m": self._wq(d, w, .5)}
        ratio = aft[ok] / d[ok]
        return {"직선_후_m": self._wq(d, w, .5), "우회비": round(float(self._wq(ratio, w[ok], .5)), 2),
                "직선보다_짧은_비율": round(float(w[ok][ratio < 0.9].sum() / max(w[ok].sum(), 1e-9)), 3)}
    def _severe_child(self, fid, broad=False):
        """보육 공백 (10/20): 영아(0~2세)는 어린이집만, 유아(3~5세)는 어린이집·유치원 모두 다닐 수 있음
        → 영아는 '남은 어린이집'까지, 유아는 '남은 어린이집·유치원'까지 거리로 따로 재서 더함 (유치원이 많아도 영아 공백을 놓치지 않고, 어린이집이 닫혀도 유치원이 있으면 유아는 공백이 아님)
        닫은 곳이 유치원이면 영아는 원래 다니지 않았으므로 유아만 셈"""
        lid = "P04.2.01"; E = self.cm.engine(); C = self.cm._C; one = E.walk.snap.get(fid)
        std = self._std(lid); b = self._base_of(lid)
        if not std or not b: return None
        P = self._prov_all(lid, broad)
        isk = lambda p: str(E.F.at[p, "업종코드"]) == "PUB:유치원"
        Pdc = [p for p in P if not isk(p)]
        lim = max(6000, std[0], b.get("전체_하위5퍼_m") or 0) + 2000
        if not hasattr(self, "_rest"): self._rest = {}; self._own = {}
        def rest_of(PP, tag):
            key = (lid, broad, tag, lim)
            if fid not in PP and key in self._rest: return self._rest[key]
            r = C.dist([E.walk.snap.get(p) for p in PP if p != fid and E.walk.snap.get(p)], limit=lim)
            if fid not in PP: self._rest[key] = r
            return r
        r_all = rest_of(P, "전체"); r_dc = rest_of(Pdc, "어린이집")
        okey = (fid, lim)
        if okey not in self._own: self._own[okey] = C.dist([one], limit=lim)
        own = self._own[okey]; kinder = isk(fid) if fid in E.F.index else False
        # 영아 기준(남은 어린이집까지 도심 주민의 하위 5%)은 따로 배움
        bk = (getattr(self, "_base", None) or {}).get("P04.2.01|영아")
        if not bk:
            names = np.array([str(x) for x in C.hjd_name]); urban = ~(np.char.endswith(names, "읍") | np.char.endswith(names, "면"))[C.hjd]
            d0 = C.dist([E.walk.snap.get(p) for p in Pdc if E.walk.snap.get(p)], limit=lim)
            bk = {"하위5퍼_m": self._wq(d0, C.pop02 * urban, .95), "전체_하위5퍼_m": self._wq(d0, C.pop02, .95)}
            self.baseline()["P04.2.01|영아"] = bk
        thr35 = max(std[0], b.get("하위5퍼_m") or 0); thr02 = max(std[0], bk.get("하위5퍼_m") or 0)
        all35 = max(thr35, b.get("전체_하위5퍼_m") or 0); all02 = max(thr02, bk.get("전체_하위5퍼_m") or 0)
        bef35 = np.minimum(r_all, own); bef02 = r_dc if kinder else np.minimum(r_dc, own)
        with np.errstate(invalid="ignore"):
            h35 = (bef35 <= std[0]) & (r_all > thr35) & ((r_all - bef35) >= SV.WORSE_M)
            h02 = (bef02 <= std[0]) & (r_dc > thr02) & ((r_dc - bef02) >= SV.WORSE_M)
            s35 = h35 & (r_all > all35); s02 = h02 & (r_dc > all02)
        hit = h35 | h02
        base = {"기준_m": thr35, "기준_영아_m": thr02, "체감기준_m": std[0], "학습기준_m": b.get("하위5퍼_m"), "누구": "영유아", "아이": "영유아", "까닭": std[2], "이름": None}
        if not hit.any(): return dict(base, 밀려난주민=0, 밀려난_65세이상=0, 심각_주민=0, 심각_65세이상=0, 밀려난_아이=0, 심각_아이=0)
        dongs = {}
        for h in np.unique(C.hjd[hit]):
            m = hit & (C.hjd == h); dongs[str(C.hjd_name[h])] = round(float(C.pop02[m & h02].sum() + C.pop35[m & h35].sum()))
        a35 = np.where(np.isfinite(r_all), r_all, lim + 1.0); a02 = np.where(np.isfinite(r_dc), r_dc, lim + 1.0)
        dist_b = np.r_[bef35[h35], bef02[h02]]; dist_a = np.r_[a35[h35], a02[h02]]; w = np.r_[C.pop35[h35], C.pop02[h02]]
        c35 = self._straight(h35, [p for p in P if p != fid], np.where(np.isfinite(r_all[h35]), r_all[h35], np.nan), C.pop35[h35]) if h35.any() else {}
        c02 = self._straight(h02, [p for p in Pdc if p != fid], np.where(np.isfinite(r_dc[h02]), r_dc[h02], np.nan), C.pop02[h02]) if h02.any() else {}
        chk = c02 if (C.pop02[h02].sum() >= C.pop35[h35].sum()) else c35
        if c35 and c02: chk = dict(chk, 직선보다_짧은_비율=max(c35.get("직선보다_짧은_비율", 0), c02.get("직선보다_짧은_비율", 0)))
        return dict(base, 밀려난주민=round(float(C.pop[hit].sum())), 밀려난_65세이상=round(float(C.pop65[hit].sum())),
                    심각_주민=round(float(C.pop[s35 | s02].sum())), 심각_65세이상=round(float(C.pop65[s35 | s02].sum())), 심각기준_m=all35,
                    밀려난_아이=round(float(C.pop02[h02].sum() + C.pop35[h35].sum())), 밀려난_영아=round(float(C.pop02[h02].sum())), 밀려난_유아=round(float(C.pop35[h35].sum())),
                    심각_아이=round(float(C.pop02[s02].sum() + C.pop35[s35].sum())),
                    거리_전_m=self._wq(dist_b, w, .5), 거리_후_m=self._wq(dist_a, w, .5), 잰거리_m=lim, 교차검증=chk, 동=sorted(dongs.items(), key=lambda x: -x[1])[:4])
    # ---------- 사실 → 판단 재료 (10/19 다시 세움: 목록으로 거르지 않고 하던 모든 일을 같은 방식으로 잼, 보고 여부는 gap_agent가 정함) ----------
    @staticmethod
    def _enough(s, rural=False):
        """재어 볼 만한 공백이 있는지 (계산 잡음을 거르는 바닥값일 뿐, 보고 여부가 아님)
        읍·면은 관심 지역이라 더 작은 공백부터 봄 (10/19 헌준님: 마을은 사람이 적어도 마지막 가게가 닫히면 생활이 무너짐)"""
        if s and s.get("누구") in SV.CHILD_WHO:   # 아이 기준 기능은 아이 수로만 셈
            return s.get("밀려난_아이", 0) >= (SV.CHILD_MIN_R if rural else SV.CHILD_MIN)
        a, e = (SV.POP_MIN_R, SV.ELDER_MIN_R) if rural else (SV.POP_MIN, SV.ELDER_MIN)
        return bool(s) and (s.get("밀려난주민", 0) >= a or s.get("밀려난_65세이상", 0) >= e)
    def case_facts(self, it):
        """문 닫은 곳이 하던 일마다 사실을 잼. [{기능, 이름, 세부종류, 읍면, 공공권리, 되살리기어려움, 성격, 할일있음, 대체시설, 전체, 넓게, 같은종류, 돌봄기관, f}]"""
        a = it["분석"]; c = it["시설"]; fid = it["fid"]; rural = self._rural(it); E = self.cm.engine()
        funcs = list(a.get("기능", []))
        for lid in SV.SPECIAL:   # 분류표에 따로 없는 생명 직결 진료 (분만·중환자실, 심평원 시설정보)
            if fid in self._special(lid):
                funcs.append({"기능": lid, "이름": SV.NAME[lid], "세부종류": None, "등급": "필수", "대체시설": self._special_alts(lid, fid), "공백": 0, "공백_65세이상": 0, "이용방법": []})
        if self._is_sport(fid):   # (10/26) 공공 체육시설(운동시설이 있는 공원 포함): 공공 체육시설끼리 공백을 잼
            funcs = [f for f in funcs if f["기능"] not in ("P03.3.01", "P10.1.01")]   # 민간 헬스장까지 대신 갈 곳으로 세는 일반 운동 기능은 빼고
            funcs.append({"기능": "G:공공체육", "이름": SV.NAME["G:공공체육"], "세부종류": None, "등급": "필수", "대체시설": self._sport_alts(fid), "공백": 0, "공백_65세이상": 0, "이용방법": []})
        out = []
        for f in funcs:
            lid = f["기능"]
            if not in_scope(f, rural is True): continue   # 공백 심각도 판정 대상 = 생활 필수 기능만 (등급 필수·준필수 + 공공 근거 + 중심 종류, 읍·면 예외 포함). 카페·식당·오락 등은 대상 아님 (10/21, 분류 기준 하나로)
            pubf = PB.PUBLIC.get(lid); pub = PB.info(lid, f.get("세부종류"))
            fx = {"기능": lid, "이름": f["이름"], "세부종류": f.get("세부종류"), "읍면": rural, "공공권리": (pubf or {}).get("권리"),
                  "되살리기어려움": bool(pub and pub.get("회복")), "성격": GA.profile(lid, f["이름"], pubf, f.get("이용방법"), f.get("등급")),
                  "할일있음": False, "대체시설": f.get("대체시설", []), "f": f,
                  "주민수요": DM.count(a.get("행정동"), lid, 60) if a.get("행정동") else 0}
            dn = str(a.get("행정동") or c.get("행정동") or "")   # 생활권 재료 (10/20): 면(농촌 마을) / 읍(시가지) / 동, 같은 일을 할 곳까지 직선거리, 보조 가게인지, 지자체가 직접 맡는 시설인지
            fx.update(생활권="면" if dn.endswith("면") else "읍" if dn.endswith("읍") else ("동" if dn else None), 고립_m=self._nearest_same(fid, lid),
                      보조공급처=lid in GA.AUX_FOR and str(E.F.loc[fid, "업종코드"] if fid in E.F.index else "") in GA.SUPPLY_AUX, 직접대응=str(fid).startswith("P:"))
            if lid in ENROLL:   # 등록해 다니는 돌봄·보육: 거리보다 '이용자가 옮길 곳'
                if not pub: continue
                ds = days_since(c.get("폐업일자"))
                if not (ds is not None and ds > ENROLL_DAYS):   # 이용자 옮김은 문 닫을 무렵의 일
                    sc = E.scale(fid) or {}; near = self._nearest_same(fid, lid)
                    cap = sc.get("현원") or sc.get("정원") or 0   # 옮겨야 할 이용자: 지금 다니는 아이 수를 알면 그것, 모르면 정원
                    spare = self._spare(fid, lid)   # 반경 2km 안 같은 기관의 남는 자리 (정원 − 다니는 아이, 둘 다 아는 곳만)
                    fe = dict(fx, 할일있음=bool(GP.for_item([f], {"gap": True, "elder": True, "far": near is not None and near > SV.ENROLL_NEAR_M})), 돌봄기관={"정원": sc.get("정원"), "현원": sc.get("현원"), "가장가까운같은기관_m": near, "문닫은지_일": ds,
                                         "주변_여유정원": spare["여유"] if spare else None, "주변_기관수": spare["곳"] if spare else None})
                    far = near is not None and near > SV.ENROLL_NEAR_M
                    absorbed = bool(spare and cap and spare["여유"] >= cap)   # 옮겨야 할 아이를 주변 기관이 다 받을 수 있으면 전원 공백 아님 (모르면 보수적으로 공백)
                    if far or (cap >= SV.ENROLL_CAP and not absorbed): out.append(fe)
                    elif self._pub_k(fid) and sc.get("현원"):   # 공립 선택권: 전체로는 옮길 곳이 있어도, 공립끼리 받을 자리가 모자라면 관찰 (긴급·주의로는 올리지 않음)
                        pa = self._pub_alt(fid)
                        if pa is not None and pa["여유"] < sc["현원"]: out.append(dict(fe, 공립선택권=pa))
                if lid not in CHILD_GAP: continue   # 보육·아동 돌봄은 동네 아이가 걸어서 갈 곳이 사라지는 공백도 잼 (아래)
                if not (ds is not None and ds > ENROLL_DAYS) and absorbed and not far: continue   # (10/29 재확인: 10/20 원칙) 2km 안 같은 기관 남는 자리로 아이를 모두 받을 수 있으면 보고하지 않음
            # 그 일 전체의 공백은, 문 닫은 곳이 그 일의 중심 종류일 때만 잼 (10/20: 약국이 닫혔는데 '의료용품 구입'을 복지용구 가게로만 세어 공백이 부풀던 것).
            # 중심 종류가 아니면 같은 묶음(같은 종류끼리)의 공백만 봄 — 예: 피부과 의원이 닫히면 외래 진료 전체가 아니라 피부과끼리
            pk = CORE_ONLY.get(lid) or (PB.PUBLIC.get(lid) or {}).get("kinds")
            mine = [k0 for (L, g0, k0) in E.of_fid.get(fid, []) if L == lid] or [f.get("세부종류")]
            fx["핵심종류"] = bool(not pk or any(k0 in pk for k0 in mine) or lid in SV.SPECIAL)   # 그 일의 중심 종류인지 (아니면 같은 종류끼리만 잼 — 예: 친목 장소에서 당구장)
            sv = self._severe(fid, lid) if fx["핵심종류"] else None
            R = rural is True
            if sv:
                fx["전체"] = sv
                if self._enough(sv, R): fx["넓게"] = self._severe(fid, lid, broad=True)
            k = f.get("세부종류")
            if k and (lid, k) in E.kind and lid not in CHILD_GAP and lid not in SKIP_FUNC:   # 마을 예외(외식·친목)는 '그 마을에 갈 곳이 있는지'라 같은 종류끼리는 재지 않음   # 같은 묶음 (보육·아동 돌봄은 나이로 이미 나눠 잼)(사람이 확인한 '서로 대신할 수 있는 종류')만 볼 때 — 예: 시장은 시장끼리. 대신하기 어려운지는 에이전트가 판단
                grp = E.kind[(lid, k)]["group"]; same = frozenset(kk for (L, kk), v in E.kind.items() if L == lid and v["group"] == grp)
                if len(same) < len({kk for (L, kk) in E.kind if L == lid}):
                    sk = self._severe(fid, lid, kind=same)
                    if self._enough(sk, R):
                        skb = self._severe(fid, lid, broad=True, kind=same)
                        if self._enough(skb, R): fx["같은종류"] = dict(sk, 이름=grp); fx["같은종류_넓게"] = skb; fx["묶음"] = grp   # 모르는 곳까지 넣어도 남을 때만 (보수적으로)
            if (sv and self._enough(sv, R)) or fx.get("같은종류"):
                fx["할일있음"] = bool(GP.for_item([f], {"gap": True, "elder": True, "far": GA.village_cut(fx) or (fx["직접대응"] and rural is True)}))
                out.append(fx)
        return out
    def _why(self, fx):
        nm = re.sub(r"\s*\(.*\)$", "", SV.NAME.get(fx["기능"]) or fx["이름"])
        if fx.get("공립선택권"):
            pa = fx["공립선택권"]; e = fx["돌봄기관"]
            return f"공립 선택권 축소: 반경 {pa['반경_m'] / 1000:g}km 공립 유치원 여유 {pa['여유']}명 < 원아 {e.get('현원')}명"
        if fx.get("돌봄기관"):
            e = fx["돌봄기관"]
            return (f"다니는 아이 {e['현원']}명 다른 기관으로 이전 필요" if e.get("현원") else f"이용자(정원 {e['정원']}명) 다른 기관으로 이전 필요" if e.get("정원") else f"{fx['이름']} 이용자 이전 필요") \
                + (f" · 가장 가까운 같은 기관 {e['가장가까운같은기관_m']/1000:.1f}km" if e.get("가장가까운같은기관_m") else "") + (f" · 2km 안 같은 기관 남는 자리 {e['주변_여유정원']:,}명" if e.get("주변_여유정원") is not None else "")
        s = fx.get("전체") if self._enough(fx.get("전체"), fx.get("읍면") is True) else None
        if s and s.get("아이"): return f"{nm}까지 {s['기준_m']/1000:.1f}km 초과 {s['아이']} {s['밀려난_아이']:,}명"
        if s: return f"{nm}까지 {s['기준_m']/1000:.1f}km 초과 주민 {s['밀려난주민']:,}명 (65세 이상 {s['밀려난_65세이상']:,}명)"
        s = fx["같은종류"]
        if s.get("아이"): return f"{fx.get('묶음') or fx['세부종류']}: 기준 {s['기준_m']/1000:.1f}km 초과 {s['아이']} {s['밀려난_아이']:,}명"
        return f"{fx.get('묶음') or fx['세부종류']}: 기준 {s['기준_m']/1000:.1f}km 초과 주민 {s['밀려난주민']:,}명 (65세 이상 {s['밀려난_65세이상']:,}명)"
    def assess(self, it, scorer=None):
        """판단 재료: 사실 + 판단 모델 점수 + AI가 없을 때의 보수적 판단. 재어 볼 공백이 없으면 None"""
        fxs = self.case_facts(it)
        if not fxs: return None
        sc = scorer or GA.Scorer(); scored = []
        for fx in fxs:
            x = GA.features(fx); scored.append((sc.p(x), fx, x))
        scored.sort(key=lambda t: -t[0]); p, fx, x = scored[0]
        used = []
        for _, f, _ in scored:
            s = f.get("돌봄기관") or (f["전체"] if self._enough(f.get("전체"), f.get("읍면") is True) else f["같은종류"])
            used.append(dict(f["f"], 심각=s, 핵심종류=f.get("핵심종류", True)))
        return {"점수": round(p, 3), "특징": x, "설명": sc.explain(x), "기능": fx, "사실": [f for _, f, _ in scored], "셈한기능": used,
                "까닭": [self._why(f) for _, f, _ in scored], "제안": GA.fallback(p, fx, x), "질문": self._question(p, fx)}
    def _question(self, p, fx):
        """스스로 판단이 애매할 때만 담당자에게 물을 것 하나 (점수가 경계 근처이고, 자료로 알 수 없는 사실이 있을 때)"""
        if not (0.35 <= p <= 0.75): return None
        s = fx.get("전체") or {}; b = fx.get("넓게") or {}
        if s.get("밀려난주민") and b and b.get("밀려난주민", 0) < 0.7 * s["밀려난주민"]:
            near = [d for d in (self._near_list_of(fx) or [])][:3]
            what = ", ".join(n["상호"] for n in near) if near else "근처 가게"
            return f"{what}에서 {_j(fx['이름'], '을를')} 할 수 있는지 아시나요? 할 수 있으면 보고하지 않아도 됩니다."
        return None
    def _near_list_of(self, fx):
        return (fx.get("f") or {}).get("확인할곳_목록") or []
    def route(self, it, scorer=None):
        """보고할지: ('보고' | '관찰' | None, 등급, 까닭, 기능, 판단재료). AI 판단이 없을 때의 보수적 판단 (brief에서는 AI가 먼저 판단함)"""
        A = self.assess(it, scorer)
        if not A: return None, None, [], [], None
        ov = GA.overrides().get(it["fid"])
        d = ov["판단"] if ov else A["제안"]
        d = {"보고": "주의"}.get(d, d)
        way = "보고" if d in ("긴급", "주의") else ("관찰" if d == "관찰" else None)
        return way, (d if way == "보고" else A["제안"]), A["까닭"], A["셈한기능"], A
    def severity(self, it):
        """(예전 호출과 맞춤) 보고한다면 등급, 까닭, 기능 — 판단 재료의 보수적 제안"""
        A = self.assess(it)
        if not A: return None, [], []
        return (A["제안"] if A["제안"] in ("긴급", "주의") else None), A["까닭"], A["셈한기능"]
    def _spare(self, fid, lid, radius=None):
        """옮겨야 할 이용자를 받을 수 있는지 (10/20): 반경(기본 2km) 안 같은 기관들의 남는 자리 합 = Σ(정원 − 다니는 아이).
        정원과 다니는 아이 수를 둘 다 아는 곳만 셈 (모르는 곳은 0으로 → 보수적). 셀 수 있는 곳이 없으면 None"""
        E = self.cm.engine(); r = E.F.loc[fid]; radius = radius or SV.ENROLL_NEAR_M
        if r["x"] != r["x"]: return None
        P = [p for p in self._prov_all(lid) if p != fid and p in E.F.index]
        core = CORE_ONLY.get(lid)
        if not P: return None
        X = E.F.loc[P]; d = (((X["x"] - float(r["x"])) * 90200) ** 2 + ((X["y"] - float(r["y"])) * 110540) ** 2) ** 0.5
        tot = 0; n = 0
        for p in d[d <= radius].index:
            sc = E.scale(p) or {}
            if not (sc.get("정원") and sc.get("현원") is not None): continue
            n += 1; tot += max(0, int(sc["정원"]) - int(sc["현원"]))
        return {"여유": tot, "곳": n} if n else None
    def spare_list(self, fid, k=5, radius=None):
        """옮길 곳 후보 (10/22 담당자 질문 '애들은 어디로 옮겨요? 자리 있어요?'): 같은 기관 가운데 가까운 순, 남는 자리(정원 − 다니는 아이)가 있는 곳만.
        돌려줌: [{상호, 행정동, 직선_m, 여유, 정원, 현원}] (모르면 [])"""
        try:
            E = self.cm.engine(); r = E.F.loc[fid]; radius = radius or SV.ENROLL_NEAR_M
            if r["x"] != r["x"]: return []
            lids = [l for l in ENROLL if fid in set(self._prov_all(l))]
            if not lids: return []
            P = [p for p in self._prov_all(lids[0]) if p != fid and p in E.F.index]
            X = E.F.loc[P]; d = (((X["x"] - float(r["x"])) * 90200) ** 2 + ((X["y"] - float(r["y"])) * 110540) ** 2) ** 0.5
            out = []
            for p in d[d <= radius].sort_values().index:
                sc = E.scale(p) or {}
                if not (sc.get("정원") and sc.get("현원") is not None): continue
                sp = int(sc["정원"]) - int(sc["현원"])
                kd = str(E.F.at[p, "업종"] or ""); age = "주로 만 0~2세" if "가정" in kd else "만 3~5세" if "유치원" in kd else ""
                if sp > 0: out.append({"상호": str(E.F.at[p, "상호"]), "종류": kd + (f"({age})" if age else ""), "행정동": str(E.F.at[p, "행정동"] or ""), "직선_m": int(round(float(d[p]))), "여유": sp, "정원": int(sc["정원"]), "현원": int(sc["현원"])})
                if len(out) >= k: break
            return out
        except Exception: return []
    def _nearest_same(self, fid, lid):
        E = self.cm.engine(); r = E.F.loc[fid]
        P = [p for p in self._prov_all(lid) if p != fid]
        if not P or r["x"] != r["x"]: return None
        X = E.F.loc[P]; d = (((X["x"] - float(r["x"])) * 90200) ** 2 + ((X["y"] - float(r["y"])) * 110540) ** 2) ** 0.5
        return float(d.min()) if len(d) else None

    # ---------- 영향 분석 (시설 하나) ----------
    def analyze(self, fid, was=True):
        """was: 문 닫기 전에 주민 안내 대상이었는지. 아니었으면(예: 상호·업종이 어긋나 '확인 필요'였던 곳) 생활 공백 계산의 '하던 곳'에 없었으므로 공백도 셈하지 않음 (변화 알림과 같은 규칙)"""
        cm = self.cm; E = cm.engine()
        if fid not in E.F.index: return None
        r = E.F.loc[fid]; funcs = []
        for (lid, k, nd), (st, why) in cm.served(fid).items():
            if st not in ("근거", "강함", "업종") and not (st == "모름" and (lid, k) == MART_KIND and MART_NAME.search(str(r["상호"]))): continue
            f = cm._func_block(fid, lid, k, nd, st, why, "closed", was)
            wide = f["영향_기능전체"] or f["영향"] or {}; grp = f["영향_묶음"] or wide; kind = f["영향"] or wide
            ks = [kk for (L, kk) in E.kind if L == lid] or [None]
            same_gu = len({p for kk in ks for p in cm.providers(lid, kk, nd) if p != fid and E.F.at[p, "구군"] == r["구군"]})
            self._near_list = []
            gap_b, extra_near = self._broad(fid, r, lid, ks, nd, f["기준_분"], wide, was)
            near_list = self._near_list
            alts = [{"상호": a["상호"], "업종": a["업종"], "주소": a["주소"], "전화": a.get("전화"), "걷는시간_분": a.get("걷는시간_분"), "걷는거리_m": a.get("걷는거리_m"),
                     "확인필요": bool(a.get("확인필요")), "경도": _num(E.F.at[a["fid"], "x"]) if a.get("fid") in E.F.index else None,
                     "위도": _num(E.F.at[a["fid"], "y"]) if a.get("fid") in E.F.index else None} for a in f["대체시설"]]
            funcs.append({"기능": lid, "이름": f["이름"], "분야": f["분야"], "등급": f["등급"], "세부종류": f["세부종류"], "의도": f["의도"], "기준_분": f["기준_분"],
                          "가까운주민": wide.get("가까운주민", 0), "가까운주민_65세이상": wide.get("가까운주민_65세이상", 0),
                          "공백": wide.get("뚜렷한공백주민", 0), "공백_65세이상": wide.get("뚜렷한공백주민_65세이상", 0),
                          "공백_기준선": wide.get("공백변화주민", 0), "공백_묶음": grp.get("뚜렷한공백주민", 0), "공백_종류": kind.get("뚜렷한공백주민", 0),
                          "공백_걷는시간_전": wide.get("뚜렷한공백_걷는시간_전"), "공백_걷는시간_후": wide.get("뚜렷한공백_걷는시간_후"),
                          "공백_넓게": gap_b, "확인할곳": extra_near, "확인할곳_목록": near_list, "확인필요_근처": sum(extra_near.values()),
                          "걷는시간_전": wide.get("걷는시간_전_중앙값"), "걷는시간_후": wide.get("걷는시간_후_중앙값"),
                          "행정동": [d for d in wide.get("행정동", []) if d.get("뚜렷한공백", 0) > 0][:6] or wide.get("행정동", [])[:3],
                          "대체시설": alts, "같은구_대체수": same_gu, "이용방법": f["이용방법"]})
        order = {"필수": 0, "준필수": 1, "선택": 2}
        funcs.sort(key=lambda f: (order.get(f["등급"], 3), -f["공백"], -f["공백_묶음"], -f["가까운주민"]))
        return {"fid": fid, "분석일": today(), "기준": self.cm.state.get("인허가_기준일"), "행정동": r.get("행정동", "") or dong_at(r.get("경도"), r.get("위도")), "전화": r.get("전화", ""), "기능": funcs}

    def _broad(self, fid, r, lid, ks, nd, thr, wide, was):
        """확인이 필요한 곳(그 일을 하는지 모르는 곳·영업하는지 확인 안 된 곳)까지 대신 갈 곳으로 봤을 때의 생활 공백과, 근처의 그런 곳 수 (업종별)
        생활 공백이 있을 때만 계산 (시간 아낌)"""
        if not was or (wide.get("뚜렷한공백주민", 0) < ALERT_POP and wide.get("뚜렷한공백주민_65세이상", 0) < ELDER_POP): return None, {}
        cm = self.cm; E = cm.engine(); gu = r["구군"] if lid == "P02.1.07" else None
        cert = {p for kk in ks for p in cm.providers(lid, kk, nd)} - {fid}
        broad = {p for kk in ks for p in cm.providers_broad(lid, kk, nd)} - {fid}
        if gu: cert = {p for p in cert if E.F.at[p, "구군"] == gu}; broad = {p for p in broad if E.F.at[p, "구군"] == gu}
        extra = broad - cert; snap = E.walk.snap.get(fid)
        if not extra or not snap: return wide.get("뚜렷한공백주민", 0), {}
        xb = cm._C.impact([E.walk.snap.get(p) for p in sorted(broad)], snap, thr, "closed", gu)
        X = E.F.loc[sorted(extra)]
        d = (((X["x"] - float(r["x"])) * 90200) ** 2 + ((X["y"] - float(r["y"])) * 110540) ** 2) ** 0.5
        near = {}; self._near_list = []
        m = d < thr * 60 * 0.75
        Y = X[m].copy(); Y["_d"] = d[m]   # (빈 표에 assign하면 행이 새로 생기는 pandas 동작을 피함)
        for p, rr in Y.sort_values("_d").iterrows():
            why = "영업하는지 확인 안 됨" if rr["대안후보"] == "확인 필요" else f"'{E.leaf[lid]['name']}'을(를) 하는지 자료에 없음"
            lab = f"{rr['업종']} ({'영업 확인 안 됨' if rr['대안후보'] == '확인 필요' else E.leaf[lid]['name'] + ' 하는지 모름'})"
            near[lab] = near.get(lab, 0) + 1
            if len(self._near_list) < 8:
                self._near_list.append({"상호": rr["상호"], "업종": rr["업종"], "전화": rr.get("전화", ""), "거리_m": int(rr["_d"]), "확인할것": why,
                                        "경도": _num(rr["x"]), "위도": _num(rr["y"])})
        return xb["뚜렷한공백주민"], near

    def _unsure_near(self, r, thr_min):
        """같은 업종인데 지금 영업하는지 확인하지 못해 계산에서 뺀 가게 수 (걸어서 기준 시간쯤 거리 안, 직선 거리로 어림). 담당자가 전화로 확인할 몫"""
        E = self.cm.engine(); F = E.F
        if not hasattr(self, "_unsure"):
            U = F[(F["대안후보"] == "확인 필요") & F["x"].notna()]
            self._unsure = {u: g for u, g in U.groupby("업종")}
        g = self._unsure.get(r["업종"])
        if g is None or r["x"] != r["x"]: return 0
        d = (((g["x"] - float(r["x"])) * 90200) ** 2 + ((g["y"] - float(r["y"])) * 110540) ** 2) ** 0.5   # 경도·위도 → m (대구 위도)
        return int((d < thr_min * 60 * 0.75).sum())

    def analyze_all(self, budget=None, emit=None, force=False):
        """아직 분석하지 않았거나, 인허가 기준일이 바뀐 뒤 분석한 적 없는 곳만 분석 (시간 제한 안에서 나눠 함)"""
        t0 = time.time(); cands = dict(self.candidates(), **self.unsure()); base = self.cm.state.get("인허가_기준일")
        todo = [f for f in cands if force or f not in self.an or self.an[f].get("기준") != base or self.an[f].get("오류")]   # 오류가 난 분석은 다음 점검 때 다시
        before = self._before()
        done = 0
        for i, fid in enumerate(todo):
            if budget and time.time() - t0 > budget: break
            try: a = self.analyze(fid, was=before.get(fid) != "확인 필요")   # '아니요'는 처음 받은 자료에서 이미 닫혀 있던 곳 → 닫기 전엔 영업하던 곳
            except Exception as ex: a = {"fid": fid, "오류": str(ex)[:200], "기능": [], "분석일": today(), "기준": base}
            if a: self.an[fid] = a
            done += 1
            if emit and (done % 25 == 0): emit({"단계": "분석", "진행": f"{done}/{len(todo)}"})
            if done % 100 == 0: _jsave(self.p_an, self.an)
        _jsave(self.p_an, self.an)
        return {"대상": len(cands), "새로 분석": done, "남음": len(todo) - done}

    # ---------- 우선순위 (계산한 숫자로만) ----------
    def triage(self, a, c=None):
        """등급과 까닭 (까닭은 담당자에게 그대로 보임). 헌준님과 정한 원칙 (10/16)
        긴급: 공공 목적 기능(법령상 기본권, 되살리기 어려움 — engine/public_basis.py)에서 대신할 곳이 분명히 부족함, 또는 이용자를 옮겨야 하는 돌봄·보육 기관
        주의: 공공은 아니지만 일상에 손실을 주고 대신할 곳이 분명히 부족함 (또는 공공이지만 금방 되살릴 수 있음)
        확인: 확실한 곳만 보면 부족하지만, 근처에 확인이 필요한 곳(하는지 모르는 곳·영업 확인 안 된 곳)이 있어 담당자 확인으로 정해짐
        참고: 근처에 대신할 곳이 충분함"""
        lv = "참고"; why = []; used = []
        dec = self.decisions.get(a.get("fid") or (c or {}).get("fid") or "", {})
        def up(l, w, f):
            nonlocal lv
            if LV_ORDER[l] < LV_ORDER[lv]: lv = l
            why.append(w)
            if f not in used: used.append(f)
        for f in a.get("기능", []):
            pub = PB.info(f["기능"], f.get("세부종류"))
            if not pub:   # 사설 시설·공공이 아닌 일: 마을 생활 기반이 무너질 때만 (대신할 곳이 분명히 없고, 걸어서 30분 넘게 떨어짐)
                if not counts_village(f): continue
                after = f.get("공백_걷는시간_후")
                if f["공백"] >= ALERT_POP and (f.get("공백_넓게") is None or f["공백_넓게"] >= ALERT_POP) and after is not None and after >= FAR_MIN:
                    far = "6km 넘게" if after >= 99.9 else f"걸어서 {after:g}분 넘게"
                    up("주의", f"[마을 생활 기반] 주민 {f['공백']:,}명이 {_j(f['이름'], '을를')} 위해 {far} 가야 합니다 (전에는 걸어서 {fm(f['공백_걷는시간_전'])}).", f)
                continue
            if not counts(f): continue
            n = f["이름"]; hard = bool(pub.get("회복"))
            tag = f"[공공 · {pub['권리']} · {pub['법령']}] " if pub else ""
            if f["기능"] in ENROLL:
                ds = days_since((c or {}).get("폐업일자"))
                if ds is not None and ds > ENROLL_DAYS:
                    why.append(f"문을 닫은 지 {ds}일이 지나 이용자는 이미 다른 기관으로 옮겼을 가능성이 큽니다 (같은 {a.get('구군') or '구·군'} 안 대체 기관 {f['같은구_대체수']}곳)."); continue
                sc = self.cm.engine().scale(a.get("fid") or (c or {}).get("fid") or "")
                cap = f", {sc['글']} 규모" if sc else ""
                up("긴급", f"{tag}이용자를 다른 기관으로 옮겨야 합니다 (같은 {a.get('구군') or '구·군'} 안 대체 기관 {f['같은구_대체수']}곳{cap}).", f); continue
            tm = f" (걷는 시간 {fm(f['공백_걷는시간_전'])} → {fm(f['공백_걷는시간_후'])})" if f.get("공백_걷는시간_전") is not None and f.get("공백_걷는시간_후") is not None else ""
            big = f["공백"] >= ALERT_POP or f["공백_65세이상"] >= ELDER_POP
            sure = big and (f.get("공백_넓게") is None or f["공백_넓게"] >= ALERT_POP)
            what = (f"주민 {f['공백']:,}명이 {_j(n, '을를')} 위해 걸어서 {f['기준_분']}분 넘게 가야 합니다" if f["공백"] >= ALERT_POP
                    else f"65세 이상 주민 {f['공백_65세이상']:,}명이 {_j(n, '을를')} 위해 걸어서 {f['기준_분']}분 넘게 가야 합니다") + tm
            if big and not sure:
                if dec.get("대안") == "없음": sure = True; why.append("담당자가 근처 시설로는 대신할 수 없다고 확인했습니다.")
                elif dec.get("대안") == "있음": why.append(f"{what}. 다만 담당자가 근처에 대신할 곳이 있다고 확인했습니다."); continue
            if sure: up("긴급" if hard else "주의", tag + what + ".", f)
            elif big:
                up("확인", f"{tag}{what}. 다만 근처에 확인할 곳이 {f['확인필요_근처']}곳 있어, 이곳들이 대신할 수 있으면 영향받는 주민은 {f['공백_넓게']:,}명입니다.", f)
            elif pub and f["등급"] == "필수" and f["공백_묶음"] >= ALERT_POP:
                up("주의", f"{tag}같은 종류만 보면 주민 {f['공백_묶음']:,}명이 {_j(n, '을를')} 위해 걸어서 {f['기준_분']}분 넘게 가야 합니다.", f)
            b, e = f["걷는시간_전"], f["걷는시간_후"]
            unsure_near = f.get("공백_넓게") is not None and f["공백_넓게"] < ALERT_POP and f.get("확인필요_근처", 0) > 0 and dec.get("대안") != "없음"
            if b is not None and e is not None and f["가까운주민"] >= ATTN_NEAR and e - b > ATTN_JUMP and not unsure_near and dec.get("대안") != "있음":
                up("주의", f"{tag}이곳이 가장 가까웠던 주민 {f['가까운주민']:,}명은 걷는 시간(중앙값)이 {fm(b)}에서 {_j(fm(e), '으로')} 늘어납니다. 가까이에 대신할 곳이 부족합니다.", f)
        if c and c.get("새가게") and c.get("새가게이음") and lv != "참고":
            lv = "참고"; why.insert(0, f"같은 자리에 {_j(chr(39) + c['새가게'] + chr(39), '이가')} 새로 열어 같은 일을 이어 합니다.")
        return lv, why, used

    def decide_alt(self, fid, has_alt, who="담당자"):
        """'확인' 항목에 담당자가 답함: 근처 확인할 곳이 대신할 수 있음/없음 → 등급이 정해짐"""
        self.decisions[fid] = {"대안": "있음" if has_alt else "없음", "때": now().isoformat(timespec="minutes"), "누가": who}
        _jsave(self.p_dec, self.decisions)

    def items(self):
        """대상 전체에 등급을 매김 (같은 가게가 두 번 잡힌 경우는 하나로)"""
        cands = self.candidates(); out = []; seen = set()
        for fid, c in cands.items():
            a = self.an.get(fid)
            if not a: continue
            key = (re.sub(r"[\s()（）]", "", str(c["상호"])), " ".join(str(c["주소"]).split()[:4]))
            if key in seen: continue
            seen.add(key)
            a = dict(a, 구군=c["구군"], 행정동=a.get("행정동") or dong_at(c.get("경도"), c.get("위도"))); lv, why, used = self.triage(a, c)
            out.append({"fid": fid, "등급": lv, "까닭": why, "시설": c, "분석": a, "셈한기능": used})
        return out

    # ---------- 구·군 보고서 ----------
    def _ctx(self, it):
        """할 수 있는 일을 고를 상황: gap(대신할 곳이 분명히 부족) / elder(65세 이상 공백) / far(걸어서 30분 넘게 떨어짐)"""
        ctx = {"gap": False, "elder": False, "far": False}
        for f in it["셈한기능"]:
            sure = f.get("공백_넓게") is None or f["공백_넓게"] >= ALERT_POP
            if f["기능"] in ENROLL: ctx["gap"] = ctx["gap"] or f["같은구_대체수"] == 0   # 장기요양: 인근에 대체 기관이 없을 때 (노인장기요양보험법 제36조제4항)
            elif f["공백"] >= ALERT_POP and sure: ctx["gap"] = True
            if f["공백_65세이상"] >= ELDER_POP and sure: ctx["elder"] = True
            if f.get("공백_걷는시간_후") is not None and f["공백_걷는시간_후"] >= FAR_MIN and f["공백"] >= ALERT_POP and sure and self._rural(it) is not False:
                fx = next((x for x in ((it.get("판단재료") or {}).get("사실") or []) if x.get("기능") == f["기능"]), None)
                if fx is None or GA.village_cut(fx) or fx.get("직접대응"): ctx["far"] = True   # 걸어서 못 가는 마을: 읍·면이고 생활권이 끊길 때만 (10/20)
        return ctx
    @staticmethod
    def _rural(it):
        """읍·면이면 True, 동이면 False, 모르면 None"""
        d = str((it.get("분석") or {}).get("행정동") or (it.get("시설") or {}).get("행정동") or "")
        return bool(re.search(r"[읍면]$", d)) if d else None
    def _far(self, it):
        """'걸어서 못 가는 마을'의 일(수요응답형 교통·이동장터·보건진료소 등)을 고를 수 있는지: 읍·면이고, 민간 가게면 생활권이 끊길 때, 지자체가 직접 맡는 시설이면 읍·면이면"""
        fxs = (it.get("판단재료") or {}).get("사실")
        if not fxs: return self._rural(it) is not False
        return any(GA.village_cut(x) or (x.get("직접대응") and x.get("읍면") is True) for x in fxs)
    def _actions(self, it):
        return GP.for_item(it["셈한기능"], self._ctx(it))[:4]

    def _facts(self, it):
        c = it["시설"]; a = it["분석"]; fs = []
        for f in it["셈한기능"]:
            pub = PB.info(f["기능"], f.get("세부종류"))
            x = {"기능": f["이름"], "등급": f["등급"], "같은구_대체기관수": f["같은구_대체수"],
                 **({"공공_목적": f"{pub['권리']} ({pub['법령']})" + (f" — {pub['회복']}" if pub.get("회복") else "")} if pub else {}),
                 "대체시설": [f"{d['상호']} (걸어서 {d['걷는시간_분']:g}분)" if d.get("걷는시간_분") is not None else d["상호"] for d in f["대체시설"][:3]]}
            if f["기능"] not in ENROLL:
                x.update({"기준_분": f["기준_분"], "생활공백_주민": f["공백"], "생활공백_65세이상": f["공백_65세이상"],
                          "생활공백_주민의_걷는시간": f"{fm(f['공백_걷는시간_전'])} → {fm(f['공백_걷는시간_후'])}" if f.get("공백_걷는시간_전") is not None else None,
                          "근처_확인할_곳": f.get("확인할곳", {}), "확인할_곳이_대신하면_생활공백": f.get("공백_넓게"), "이곳이_가장_가까웠던_주민": f["가까운주민"],
                          "이곳이_가장_가까웠던_주민의_걷는시간_중앙값": f"{fm(f['걷는시간_전'])} → {fm(f['걷는시간_후'])}" if f["걷는시간_전"] is not None else None,
                          "영향_행정동": [f"{d['행정동']} {d.get('뚜렷한공백') or d['주민']:,}명" for d in f["행정동"][:4]]})
            fs.append(x)
        ds = days_since(c["폐업일자"])
        village = any(w.startswith("[마을") for w in it["까닭"])
        return {"id": it["fid"], "시설": c["상호"], "업종": c["업종"], "행정동": a.get("행정동"), "문닫은날": c["폐업일자"], "문닫은지_며칠": ds, "등급": it["등급"], "까닭": it["까닭"],
                "보고_까닭": "마을 생활 기반 (공공 시설은 아니지만, 마을에서 이 일을 할 곳이 걸어서 갈 수 없을 만큼 멀어짐)" if village else "공공·복지 기능의 공백",
                "같은자리_새가게": c.get("새가게"), "기능": fs, "지자체가_할_일": [a["할일"] for a in self._actions(it)]}

    @staticmethod
    def _clean(text, facts_one, names):
        """사실 밖의 숫자·시설 이름이 든 문장을 버림 (숫자는 1,498 / 11.0 / 06 같은 표기 차이를 맞춰 견줌)"""
        def canon(n):
            try: v = float(n.replace(",", "")); return str(int(v)) if v == int(v) else str(v)
            except Exception: return n
        nums = {canon(v) for v in re.findall(r"\d[\d,]*(?:\.\d+)?", json.dumps(facts_one, ensure_ascii=False))}
        nums |= {str(today()[:4]), "65"}
        vals = []
        for v in nums:
            try: vals.append(float(v))
            except Exception: pass
        def near_fact(n):   # '약 9분'처럼 사실의 값(8.8)을 어림한 숫자는 받아들임 (앞에 '약'이 있고 10% 안)
            try: x = float(n.replace(",", ""))
            except Exception: return False
            return any(abs(x - v) <= max(1.0, 0.1 * v) for v in vals)
        sents = [x for x in re.split(r"(?<=[.다요])\s+", str(text).strip()) if x]; keep = []
        for sent in sents:
            bad = [m.group(1) for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)", sent)
                   if canon(m.group(1)) not in nums and not (canon(m.group(1)).isdigit() and int(canon(m.group(1))) <= 3)
                   and not (sent[max(0, m.start() - 2):m.start()].strip() == "약" and near_fact(m.group(1)))]
            for m in re.findall(r"[가-힣A-Za-z0-9]{1,15}(?:약국|의원|병원|마트|슈퍼|정육점|미용실|이용원|목욕탕|사우나|요양원|센터|복지관|어린이집|헬스|클럽)", sent):
                if m not in names and not any(m.endswith(g) for g in GENERIC_PLACES) and not any(m in nm for nm in names): bad.append(m)
            if not bad and len(sent) >= 12: keep.append(sent)
        return " ".join(keep)

    @staticmethod
    def _tidy(t):
        t = re.sub(r"(\d[\d,]*)\s*약\s*명", r"약 \1명", str(t)); t = re.sub(r"약\s+약\s+", "약 ", t)
        t = re.sub(r"(\d{4})-(\d{2})-(\d{2})", lambda m: f"{int(m.group(2))}월 {int(m.group(3))}일", t)   # 날짜는 '7월 22일'처럼
        return t.strip()

    def _fallback(self, it):
        """언어 모델 없이 만드는 보고 (계산한 사실을 그대로 문장으로)"""
        c = it["시설"]; f = it["셈한기능"][0] if it["셈한기능"] else None
        where = it["분석"].get("행정동") or c["구군"]
        if f is None: return {"요약": f"{where} {_j(c['상호'], '이가')} 문을 닫았습니다.", "위험": []}
        if f["기능"] in ENROLL:
            risk = [f"지금 이용하던 분들이 다른 기관을 찾아야 합니다 (같은 구·군 안 대체 기관 {f['같은구_대체수']}곳)."]
        else:
            risk = [(lambda x: x if x.endswith(".") else x + ".")(re.sub(r"^\[[^\]]*\]\s*", "", w)) for w in it["까닭"][:2]]
        return {"요약": f"{where} {_j(c['상호'], '이가')} 문을 닫아 {_j(f['이름'], '을를')} 위해 멀리 가야 하는 주민이 생겼습니다.", "위험": risk}

    # ---------- 판단 (언어 모델 에이전트) ----------
    # 계산은 '후보'를 고를 뿐이고, 보고할지와 무엇을 할지는 에이전트가 상황을 보고 판단함 (헌준님 10/16 밤:
    #  '약국까지 10분 더 걸리는 것이 왜 위험인가', '호텔 안 미용실은 없어져도 주민 문제가 아님', '이발 때문에 수요응답형 교통은 맞지 않음')
    #  담당자에게 배운 원칙(data/gov/lessons.jsonl)을 판단 때마다 읽음 → 담당자가 '이 판단은 틀렸어요'로 알려 주면 다음 판단부터 반영 (배움)
    def lessons(self):
        p = os.path.join(GOV, "lessons.jsonl")
        if not os.path.exists(p): return []
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    def add_lesson(self, text, fid=None, who="담당자"):
        x = {"때": now().isoformat(timespec="minutes"), "누가": who, "원칙": str(text).strip()[:400], "시설": fid}
        with open(os.path.join(GOV, "lessons.jsonl"), "a", encoding="utf-8") as fh: fh.write(json.dumps(x, ensure_ascii=False) + "\n")
        return x

    def _context(self, it):
        """판단에 쓸 상황: 같은 건물의 다른 시설(호텔·병원 안 가게인지), 동네 성격(읍·면·동), 가까운 대신할 곳"""
        E = self.cm.engine(); c = it["시설"]
        from unit_addr import unit
        b = unit(c["주소"])[0]; same = []
        try:
            near = E.F[(abs(E.F["x"] - float(c["경도"])) < 0.0004) & (abs(E.F["y"] - float(c["위도"])) < 0.0004)]
            for fid2, r2 in near.iterrows():
                if fid2 == it["fid"] or unit(r2["주소"])[0] != b: continue
                same.append(f"{r2['상호']} ({r2['업종']})")
        except Exception: pass
        dong = it["분석"].get("행정동") or ""
        return {"같은_건물의_다른_시설": same[:8], "동네": ("읍·면 (농촌)" if re.search(r"[읍면]$", dong) else "동 (도시)") if dong else "모름"}

    def pre_review(self, fid):
        """폐업 사전 검토 (10/20): 영업 중인 시설이 문을 닫는다고 가정하고, 실제 보고와 같은 계산 → AI 판단 → 계산 검토·독립 검토를 함
        (폐업 신고·휴업 예고처럼 문을 닫기 전에 알게 된 경우). 결과는 어디에도 저장하지 않음:
        실제 보고·판단 기록(judged.json)·기능 공백 공개·경험(학습)·주민 수요·처리 기록에 들어가지 않음"""
        E = self.cm.engine()
        if fid not in E.F.index: return {"오류": "시설을 찾을 수 없습니다"}
        r = E.F.loc[fid]
        if str(r["대안후보"]) == "아니요": return {"오류": "이미 폐업했거나 주민에게 안내하지 않는 시설입니다"}
        try: lon, lat = float(r["경도"]), float(r["위도"])
        except Exception: return {"오류": "위치 정보가 없는 시설입니다"}
        c = {"fid": fid, "상호": r["상호"], "업종": r["업종"], "주소": r["주소"], "구군": r["구군"], "폐업일자": today(), "경도": lon, "위도": lat, "전화": r.get("전화", "")}
        a = self.analyze(fid, True)
        if not a: return {"오류": "이 시설이 하던 일을 알 수 없습니다"}
        if not a.get("행정동"): a = dict(a, 행정동=dong_at(lon, lat))
        it = {"fid": fid, "시설": c, "분석": a}
        base = {"fid": fid, "상호": c["상호"], "업종": c["업종"], "주소": c["주소"], "구군": c["구군"], "행정동": a.get("행정동"), "경도": lon, "위도": lat, "사전검토": True}
        if self._pub_k(fid):
            sc = E.scale(fid) or {}; pa = self._pub_alt(fid)
            if pa is not None: base["공립대체"] = dict(pa, 원아=sc.get("현원"), 가능=bool(sc.get("현원") is not None and pa["여유"] >= (sc.get("현원") or 0)))
        A = self.assess(it)
        if not A:   # 공백 없음: 하던 일마다 가장 가까운 대체 시설
            alts = []   # 하는 일마다 가장 가까운 대체 시설 하나 (예: 종합병원이면 외래 진료·응급 진료 각각)
            for f in a.get("기능", []):
                d = next((d for d in f.get("대체시설", []) if d.get("상호")), None)
                if d and f.get("이름") not in [x["기능"] for x in alts]:
                    alts.append(dict({k: d.get(k) for k in ("상호", "업종", "걷는시간_분", "경도", "위도")}, 기능=f.get("이름")))
            why = "하는 일마다 기준 거리 내 대체 시설 있음 · 기능 공백 없음"
            ef = next((f for f in a.get("기능", []) if f["기능"] in ENROLL), None)
            if ef:   # 돌봄·보육: 이용자 옮김 기준으로 설명 (거리보다 '옮길 자리')
                sc = E.scale(fid) or {}; sp = self._spare(fid, ef["기능"]); n = sc.get("현원") or sc.get("정원")
                if sp and n: why = f"{'원아' if 'P04.2' in ef['기능'] else '이용자'} {n:,}명 · 반경 2km 동종 기관 {sp['곳']}곳 여유 정원 {sp['여유']:,}명 · 이전 가능"
            return dict(base, 공백=False, 판단="해당 없음", 판단까닭=why, 대체시설=alts[:6], 하던일=self._did(fid))
        it = dict(it, 등급=A["제안"] if A["제안"] in ("긴급", "주의") else "주의", 까닭=list(dict.fromkeys(A["까닭"] or [])), 셈한기능=A["셈한기능"], 판단재료=A)   # 10/25: 같은 까닭이 세 번 되풀이되던 것
        j = None
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=open(os.path.join(self.root, "settings", "anthropic_key.txt"), encoding="utf-8").read().strip())
            keep = getattr(self, "_hist", None); self._hist = {}; keep_rej = list(getattr(self, "_rejected", []))   # 실제 점검의 기록을 건드리지 않게
            try:
                res, _ = self._judge(c["구군"], [it], client, SONNET_J)
                res = self._self_review([it], res, client)
            finally:
                if keep is None: self.__dict__.pop("_hist", None)
                else: self._hist = keep
                self._rejected = keep_rej
            j = res.get(fid)
        except Exception as ex:
            j = None; err = str(ex)[:80]
        src = "AI"
        if not j:   # AI를 부르지 못하면 경험으로 배운 판단 모델로 (계산 검토를 통과할 때만 보고)
            d = A["제안"]
            if d in ("긴급", "주의") and not self.audit(it, A)["통과"]: d = "관찰"
            j = {"판단": d, "까닭": "", "대응": GP.for_item(it["셈한기능"], {"gap": True, "elder": True, "far": any(GA.village_cut(x) for x in A["사실"])})[:3]}; src = "모델"
        d = j.get("판단") or A["제안"]
        if A["사실"] and all(x.get("공립선택권") for x in A["사실"]) and d in ("긴급", "주의", "보고"): d = "관찰"   # 공립 선택권 축소는 관찰 (실제 판정과 같은 원칙)
        row = self._srow(dict(it, 등급=d if d in ("긴급", "주의") else "주의"), j, None, today())
        row.update(base, 공백=True, 판단=d, 판단한곳=src, 판단점수=A["점수"], 판단까닭=j.get("까닭") or ("; ".join(A["까닭"][:1])),
                   검토=j.get("검토") or ({"결과": "계산 검토 통과 (AI 판단 전)", "참고": self.audit(it, A)["참고"]} if src == "모델" else None),
                   이어받을자원=self._relay(it) if d in ("긴급", "주의") else [], 처리=None, 새로=False, 폐업일자=None)
        return row
    def _gap_row(self, gu, it, A, state):
        """기능 공백 현황 (아이디어 제안자 답변서 6번: 사라진 시설의 정보를 남겨 그 지역에 기능이 다시 생기도록): 결손 기능·영향·이전 운영 정보·주민 수요
        모든 값은 계산·공식 자료에서만 (영업 기간: 인허가일자~폐업일자, 운영시간: 국립중앙의료원 자료가 있을 때만)"""
        top = A["사실"][0]; dong = it["분석"].get("행정동") or ""; c = it["시설"]
        s = top.get("돌봄기관") or (top.get("전체") if self._enough(top.get("전체"), top.get("읍면") is True) else top.get("같은종류")) or {}
        lids = []
        for f in A["사실"]:
            if f["기능"] not in lids: lids.append(f["기능"])
        import hours as HR
        opened = permit_open(self.cm.engine(), it["fid"])
        eff = ({"이용자": s.get("현원") or s.get("정원"), "최근접_같은기관_m": s.get("가장가까운같은기관_m")} if top.get("돌봄기관") else
               {"주민": s.get("밀려난주민"), "65세이상": s.get("밀려난_65세이상"), "아이": s.get("밀려난_아이"), "아이구분": s.get("아이"),
                "기준_m": s.get("기준_m"), "거리_전_m": s.get("거리_전_m"), "거리_후_m": s.get("거리_후_m"), "잰거리_m": s.get("잰거리_m")})
        return {"구군": gu, "행정동": dong, "기능id": top["기능"], "기능": SV.NAME.get(top["기능"]) or top["이름"], "결손기능": [SV.NAME.get(l) or next(f["이름"] for f in A["사실"] if f["기능"] == l) for l in lids][:4],
                "상태": state, "fid": it["fid"], "상호": c["상호"], "업종": c["업종"], "폐업일자": c.get("폐업일자"), "개업일자": opened,
                "운영시간": HR.week_text(it["fid"]), "영향": eff, "경도": c.get("경도"), "위도": c.get("위도"),
                "주민찾음": sum(DM.count(dong, l, 90) for l in lids) if dong else 0}
    RELAY_F = {"P01.1.01", "P01.1.02", "P01.1.03", "P01.1.04", "P02.1.01"}
    def _relay(self, it):
        """기능상속 (아이디어 제안자 답변서 5번): 사라진 장보기 기능을 이어받을 지역 자원
        ① 직접 이용(대체 시설, 카드에 따로) ② 공급처(마트·농협 등 큰 가게: 배송·주문) ③ 공동 수령 거점(경로당·마을회관: 일괄 배송받아 나눠 줌)"""
        A = it.get("판단재료") or {}; lids = {f["기능"] for f in A.get("셈한기능", [])}
        if not lids & self.RELAY_F: return []
        E = self.cm.engine(); c = it["시설"]
        try: x, y = float(c["경도"]), float(c["위도"])
        except Exception: return []
        dist = lambda X: (((X["x"].astype(float) - x) * 90200) ** 2 + ((X["y"].astype(float) - y) * 110540) ** 2) ** 0.5
        P = [p for p in self.cm.providers_broad("P01.1.02", "슈퍼마켓", None) if p != it["fid"] and p in E.F.index] if ("P01.1.02", "슈퍼마켓") in E.kind else []
        S = E.F.loc[P]; S = S[S["상호"].astype(str).str.contains(MART_NAME)]
        out = []
        if len(S):
            S = S.assign(d=dist(S)).sort_values("d"); S = S[S["d"] <= 15000].head(2)
            if len(S): out.append({"역할": "공급처", "글": ", ".join(f"{n}({d / 1000:.1f}km)" for n, d in zip(S["상호"], S["d"])) + " · 배송·주문 가능 여부 확인"})
        H = E.F[(E.F["업종코드"] == "PUB:경로당") & (E.F["대안후보"] == "예")]
        H = H.assign(d=dist(H)); H = H[H["d"] <= 1000].sort_values("d").head(2)
        if len(H): out.append({"역할": "수령 거점", "글": ", ".join(f"{n}({d:.0f}m)" for n, d in zip(H["상호"], H["d"])) + " · 공동 수령 장소로 활용 협의"})
        return out
    def _self_review(self, cands, res, client):
        """보고(긴급·주의)하려는 판단을 스스로 다시 검토 (10/20 헌준님: 교차검증·정확한 계산으로 스스로 검토하고 판단해 보고)
        1) 계산 검토(audit): 계산 오류가 의심되면 보고하지 않고 관찰
        2) 검토관(다른 AI): 사람이 보고 '이게 왜 심각하지?'라고 물을 만한지, 숫자끼리 맞는지 → 동의하지 않으면 중재관이 최종 판단
        결과는 res[fid]['검토']에 남김 (화면의 '교차검증' 줄)"""
        import gap_practice as PR
        rep = [it for it in cands if (res.get(it["fid"]) or {}).get("판단") in ("긴급", "주의")]
        if not rep: return res
        cases = []
        for it in rep:
            A = it.get("판단재료") or self.assess(it)
            au = self.audit(it, A)
            if not au["통과"]:
                if au["문제"]: res[it["fid"]] = dict(res[it["fid"]], 판단="관찰", 까닭="계산 검토에서 오류 의심 — " + au["문제"][0], 검토={"결과": "계산 검토 통과 못 함", "문제": au["문제"]})
                else: res[it["fid"]] = dict(res[it["fid"]], 판단="관찰", 까닭="보고 원칙 — " + au["원칙"][0], 검토={"결과": "생활권 원칙 미충족 (관찰)", "문제": au["원칙"]})
                continue
            fo, _ = PR.case_of(self, it, A); top = A["사실"][0]
            cases.append({"fid": it["fid"], "기능": top["기능"], "기능이름": top["이름"], "읍면": self._rural(it), "특징": list(A["특징"]), "감사": au, "사례": fo})
        if not cases: return res
        dec = {c["fid"]: {"decision": res[c["fid"]]["판단"], "reason": res[c["fid"]].get("까닭", "")} for c in cases}
        try:
            rev = PR.review(self, client, cases, dec)
            split = [c for c in cases if c["fid"] in rev and not rev[c["fid"]]["agree"] and rev[c["fid"]]["decision"] != dec[c["fid"]]["decision"]]
            arb = PR.arbitrate(self, client, split, dec, rev) if split else {}
        except Exception as ex:
            for c in cases: res[c["fid"]] = dict(res[c["fid"]], 검토={"결과": "검토관 오류로 검토 못 함", "문제": [str(ex)[:80]]})
            return res
        for c in cases:
            f = c["fid"]; r = rev.get(f)
            if not r: continue
            if f in arb:
                fin = arb[f]["decision"]
                if fin in ("긴급", "주의"): res[f] = dict(res[f], 판단=fin, 검토={"결과": "검토관과 의견이 달라 중재 후 보고", "설명": r.get("plain", ""), "문제": r.get("issues", [])})
                else: res[f] = dict(res[f], 판단=fin, 까닭=self._tidy(arb[f].get("reason", "")), 검토={"결과": "검토에서 보고 보류", "설명": r.get("plain", ""), "문제": r.get("issues", [])})
            else: res[f] = dict(res[f], 검토={"결과": "계산 검토·검토관 확인 통과", "설명": r.get("plain", ""), "문제": r.get("issues", []), "참고": c["감사"]["참고"]})
        return res
    def _judge(self, gu, cands, client, model):
        """후보마다: 보고할지(긴급·주의·보고 안 함), 그 까닭, 예상 위험, 할 일(목록에서만)을 판단"""
        facts = []; allowed = {}; cmap = {}
        for it in cands:
            fo = self._sfacts(it, getattr(self, "_hist", {})); cmap[it["fid"]] = (it.get("판단재료") or {}).get("사실", [])
            # 판단 재료: 이 기능과 관계있는 모든 일 (상황이 맞는지는 에이전트가 판단). 수요응답형 교통·이동장터처럼 '걸어서 못 가는 마을'의 일은 읍·면 생활권이 끊길 때만 (10/20)
            progs = GP.for_item(it["셈한기능"], {"gap": True, "elder": True, "far": self._far(it)})
            allowed[it["fid"]] = {p["id"]: p for p in progs}
            fo["고를_수_있는_일"] = [{"id": p["id"], "종류": p["종류"], "할일": p["할일"], "근거": p["근거"]} for p in progs]
            facts.append(fo)
        tool = {"name": "judge", "description": "후보마다 판단",
                "input_schema": {"type": "object", "properties": {
                    "summary": {"type": "string", "description": "이 구에서 담당자가 오늘 알아야 할 것 한두 문장. 보고할 곳이 없으면 그렇게 말함"},
                    "items": {"type": "array", "items": {"type": "object", "properties": {
                        "id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["긴급", "주의", "관찰", "해당 없음"]},
                        "reason": {"type": "string", "description": "왜 그렇게 판단했는지 담당자가 납득할 핵심 근거. 공문서 개조식(명사형 종결, 예: '대체 기관 3.6km·차량 이동 가능, 원아 이전 계획 확인 필요'), 60자 안. 화면에 이미 나오는 숫자(멀어지는 주민 수·거리)를 되풀이하지 말고, 계산이 놓친 사정이 없는지 따져 본 결과를 씀. 아무 문제 없던 확인 과정(같은 건물에 다른 시설 없음 등)은 늘어놓지 않음"},
                        "summary": {"type": "string", "description": "보고할 때만: 담당자가 제목만 보고도 알 수 있게, 무엇이 끊겼고 누가 영향받는지 한 문장. 시설 이름·업종·날짜는 화면에 따로 나오므로 쓰지 않음"},
                        "risks": {"type": "array", "items": {"type": "string"}, "description": "보고할 때만: 이 공백 때문에 현실에서 벌어질 일 1~3개. 화면에 나오는 숫자를 되풀이하지 않음"},
                        "actions": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "why": {"type": "string", "description": "이 상황에 왜 맞는지 한 문장"}}, "required": ["id", "why"]},
                                    "description": "'고를_수_있는_일'에서 이 상황을 실제로 풀 수 있는 것만. 맞는 것이 없으면 빈 목록"}},
                        "required": ["id", "decision", "reason"]}}}, "required": ["summary", "items"]}}
        lessons = "\n".join(f"- {x['원칙']}" for x in self.lessons()) or "- (아직 없음)"
        sys_p = ("당신은 대구시 구·군 복지·공공시설 담당 공무원의 업무 비서인 AI 에이전트입니다. 매일 문 닫은 시설마다 계산한 사실을 받아, "
                 "담당자에게 보고할지 스스로 판단합니다. 담당자가 모든 것을 확인하지 않아도 되도록, 보고할 것만 보고하고 나머지는 계속 살펴봅니다.\n\n"
                 "판단 (하나를 고름)\n"
                 "- 긴급: 담당자가 오늘 바로 움직여야 함. 법이 보장하고 되살리기 어려운 생명·건강·돌봄 기능이 그 동네에서 사실상 끊김.\n"
                 "- 주의: 담당자가 알고 할 일을 검토해야 하는 공백.\n"
                 "- 관찰: 공백은 있지만 지금 보고할 만큼은 아님. 매일 다시 살펴봄.\n"
                 "- 해당 없음: 계산이 놓친 사정으로 실제 공백이 아님(시설 안 매장, 같은 자리에 새로 연 가게 등).\n\n"
                 f"원칙 (꼭 따름)\n{GA.principles()}\n담당자가 알려 준 원칙 (꼭 따름)\n{lessons}\n\n"
                 "재료 읽는 법\n- '판단_모델_점수'는 에이전트가 수많은 사례를 판단·검토하며 쌓은 경험과 담당자 반응으로 배운 점수(0~1, 높을수록 보고 쪽)입니다. 참고하되, 사실과 원칙에 비춰 스스로 판단합니다.\n"
                 "- '비슷한_지난_사례'는 담당자가 판단한 사례(담당자)와 에이전트가 쌓은 경험(경험)입니다. 담당자 판단은 따르고, 경험은 참고하되 오늘 사실로 다시 판단합니다.\n"
                 "- '계산_검토'에 문제가 있으면 계산을 믿을 수 없으니 보고하지 않습니다.\n"
                 "- '그_일을_하는지_모르는_곳까지_대신_갈_곳으로_볼_때'의 공백이 훨씬 작으면 자료가 부족한 것이니 보수적으로 봅니다.\n"
                 "- '같은_종류만_볼_때'는 그 종류(예: 시장)만 대신 갈 곳으로 볼 때입니다. 그 종류가 다른 곳으로 대신되기 어려운지는 기능의 성격과 원칙으로 판단합니다.\n\n"
                 "할 일\n- '고를_수_있는_일'에서 이 공백을 실제로 풀 수 있는 것만 고릅니다. 법정 확인은 해당하면 꼭 고릅니다. 맞는 것이 없으면 비웁니다.\n\n"
                 "쓰기\n- 담당자 화면에는 멀어지는 주민 수, 65세 이상 수, 가장 가까운 곳까지 거리, 영향받는 동이 이미 숫자로 나옵니다. 요약·까닭·위험에서 이 숫자를 되풀이하지 않습니다.\n"
                 "- 까닭·요약·위험은 공문서 개조식으로 짧게 씁니다. 명사형으로 끝냅니다(예: '대체 약국 도보 18분 거리', '어르신 복약 중단 우려', '방문건강관리 연계 필요'). 번역투·사족 없이. 내부 처리 과정(점수·후보·계산)을 드러내는 말은 쓰지 않습니다.\n"
                 "- 재료에 없는 사실을 지어내지 않습니다. 대신 갈 곳이 걸어서 30분 안에 있으면 '없다'고 쓰지 않습니다.")
        msg = f"점검일 {today()}. {gu}의 후보 {len(facts)}곳입니다.\n" + json.dumps(facts, ensure_ascii=False)
        res = None
        for _ in range(2):   # 이 모델은 도구를 강제로 부르게 할 수 없어, 부르지 않으면 한 번 더 요청
            r = client.messages.create(model=model, max_tokens=4000, system=sys_p + "\n\n판단 결과는 반드시 judge 도구로 냅니다.", tools=[tool],
                                       messages=[{"role": "user", "content": msg}])
            try:
                from chat import log_usage; log_usage(model, r.usage, "지자체 판단")
            except Exception: pass
            res = next((b.input for b in r.content if b.type == "tool_use"), None)
            if res: break
        if not res: raise RuntimeError("판단 도구를 부르지 않음")
        self._last_raw = res
        fmap = {x["id"]: x for x in facts}; out = {}
        for x in res.get("items", []):
            fid = x.get("id")
            if fid not in fmap: continue
            fo = fmap[fid]; names = {fo["시설"]} | {d.split(" (")[0] for ff in fo["기능"] for d in ff["대체시설"]} | {s_.split(" (")[0] for s_ in fo.get("같은_건물의_다른_시설", [])}
            T = self._tidy; dec = x.get("decision") if x.get("decision") in ("긴급", "주의", "관찰", "해당 없음") else None
            if dec is None: continue
            # 확인: AI가 쓴 글이 계산한 사실과 어긋나면 이 판단은 받지 않음 → 판단 모델의 보수적 판단으로 (예: 대신 갈 약국이 18분 거리에 있는데 '남은 약국이 없다')
            ok, bad = GA.verify(dec, " ".join([x.get("reason", ""), x.get("summary", "")] + list(x.get("risks", []))), cmap[fid])
            if not ok:
                self._rejected = getattr(self, "_rejected", []) + [{"fid": fid, "까닭": bad}]; continue
            acts = []
            for a in x.get("actions", [])[:4]:
                p = allowed[fid].get(a.get("id"))
                if p: acts.append(dict(p, 맞춤=self._clean(T(a.get("why", "")), fo, names)))
            acts.sort(key=lambda p: {"법정 확인": 0, "지자체 사업": 1, "기관 협의": 2}.get(p["종류"], 3))
            why = self._clean(T(x.get("reason", "")), fo, names) or ("가까이에 대신 갈 곳이 있어 보고하지 않았습니다." if dec == "해당 없음" else "")
            why = why.rstrip(".")
            out[fid] = {"판단": dec, "까닭": why,
                        "요약": self._clean(T(x.get("summary", "")), fo, names), "위험": [y for y in (self._clean(T(z), fo, names) for z in x.get("risks", [])[:3]) if y],
                        "대응": acts}
        s0 = self._clean(self._tidy(res.get("summary", "")), {"n": len(facts), "사실": facts}, {f["시설"] for f in facts})
        return out, s0

    def _village(self, it):
        """사설 가게 예외: 농촌(읍·면)에서 그 일을 할 곳이 5km 넘게 멀어지는 주민이 100명 이상 (마을 생활 자체가 어려워짐)"""
        dong = it["분석"].get("행정동") or ""
        if not re.search(r"[읍면]$", dong): return None, [], []
        for f in it["분석"].get("기능", []):
            if PB.info(f["기능"], f.get("세부종류")) or not counts_village(f): continue
            after = f.get("공백_걷는시간_후")
            if f["공백"] >= SV.POP_MIN and after is not None and after >= 83 and (f.get("공백_넓게") is None or f["공백_넓게"] >= SV.POP_MIN):
                return "주의", [f"농촌 마을 주민 {f['공백']:,}명이 {_j(f['이름'], '을를')} 위해 5km 넘게 가야 합니다."], [dict(f, 심각={"밀려난주민": f["공백"], "밀려난_65세이상": f["공백_65세이상"], "마을": True})]
        return None, [], []

    def _sfacts(self, it, history):
        """AI 에이전트에게 주는 판단 재료: 계산한 사실·기능의 성격·판단 모델 점수·비슷한 지난 사례 (판단 규칙은 주지 않음, 원칙은 시스템 글에)"""
        A = it.get("판단재료") or self.assess(it); c = it["시설"]; a = it["분석"]; fs = []
        km = lambda m: round((m or 0) / 1000, 1)
        seen_f = set()
        for fx in (A["사실"] if A else []):
            if fx["이름"] in seen_f or len(seen_f) >= 3: continue   # 같은 기능이 세부 종류마다 여러 번 나오면 가장 무거운 하나만 (10/20)
            seen_f.add(fx["이름"])
            pr = fx["성격"]
            x = {"기능": fx["이름"], "기능의_성격": {"못_받으면_위험해지는_시간": pr.get("시간민감도"), "생명과_바로_이어짐": pr.get("생명직결"),
                                                 "대신하는_다른_방법": pr.get("대신하는_방법"), "취약계층": pr.get("취약계층"), "성격_정리": pr.get("만든이")},
                 **({"법이_보장하는_권리": fx["공공권리"]} if fx["공공권리"] else {}), "되살리기_어려운_공공시설": fx["되살리기어려움"],
                 "지자체가_할_수_있는_일이_있음": fx["할일있음"],
                 "생활권": {"면": "면(농촌 마을)", "읍": "읍(시가지)", "동": "동(도심)"}.get(fx.get("생활권"), "모름"),
                 **({"같은_일을_할_곳까지_직선_km": km(fx["고립_m"])} if fx.get("고립_m") is not None else {}),
                 "보조_가게(편의점·매점 등)": bool(fx.get("보조공급처")), "지자체가_직접_맡는_시설": bool(fx.get("직접대응")),
                 **({"영향_주민_중_어르신_비율": f"{round(GA.elder_share(fx) * 100)}%"} if fx.get("전체") and not (fx.get("전체") or {}).get("아이") else {}),
                 "생활권_원칙_충족": GA.area_ok(fx),
                 "대체시설": [f"{d['상호']} (걸어서 {d['걷는시간_분']:g}분)" if d.get("걷는시간_분") is not None else (f"{d['상호']} (직선 {km(d['직선_m'])}km)" if d.get("직선_m") else d["상호"]) for d in fx.get("대체시설", [])[:3]]}
            near = [d["걷는시간_분"] for d in fx.get("대체시설", []) if d.get("걷는시간_분") is not None]
            if near: x["문닫은_곳에서_가장_가까운_대체시설_걷는분"] = round(min(near))
            if fx.get("돌봄기관"): x["돌봄기관"] = {k: v for k, v in fx["돌봄기관"].items() if v is not None}
            if fx.get("공립선택권"): x["공립_선택권_축소"] = {"반경_km": fx["공립선택권"]["반경_m"] / 1000, "공립_유치원_수": fx["공립선택권"]["곳"], "공립_남는_자리": fx["공립선택권"]["여유"], "원칙": "어린이집·사립까지 보면 옮길 곳은 있음. 공립끼리 자리가 모자라 선택권만 줄어듦 → 관찰"}
            if fx.get("주민수요"): x["최근_60일_이_동네_주민이_이_일을_할_곳을_찾지_못한_횟수"] = fx["주민수요"]
            for key, lab in (("전체", "그_일을_하는_모든_곳으로_볼_때"), ("넓게", "그_일을_하는지_모르는_곳까지_대신_갈_곳으로_볼_때"), ("같은종류", f"같은_종류({fx.get('묶음') or fx.get('세부종류')})만_볼_때")):
                sv = fx.get(key)
                if not sv: continue
                if key == "넓게" and fx.get("전체") and all(sv.get(k0) == fx["전체"].get(k0) for k0 in ("밀려난주민", "밀려난_아이", "거리_후_m")):
                    x[lab] = "그_일을_하는_모든_곳으로_볼_때와_같음"; continue
                x[lab] = {"멀어지는_아이": f"{sv['아이']} {sv.get('밀려난_아이', 0)}명"} if sv.get("아이") else {"멀어지는_주민": sv.get("밀려난주민", 0), "그중_65세이상": sv.get("밀려난_65세이상", 0)}
                if self._enough(sv, fx.get("읍면") is True):
                    x[lab].update({"기준_km": km(sv["기준_m"]), "가장_가까운_곳까지_km": f"{km(sv.get('거리_전_m'))} → {km(sv.get('거리_후_m'))}",
                                   "대구_전체에서도_가장_다니기_어려운_수준인_주민": sv.get("심각_주민", 0), "영향_동": [f"{d} {n:,}명" for d, n in sv.get("동", [])]})
            fs.append(x)
        return {"id": it["fid"], "시설": c["상호"], "업종": c["업종"], "행정동": a.get("행정동"), "문닫은날": c["폐업일자"], "기능": fs,
                "판단_모델_점수": A["점수"] if A else None, "점수에_크게_작용한_것": [f"{e['특징']} ({e['방향']})" for e in (A["설명"] if A else [])],
                "비슷한_지난_사례": GA.similar(A["특징"]) if A else [],
                "같은_동네_최근_6개월_같은_기능_폐업": history.get(it["fid"], 0), **self._context(it)}

    def brief(self, llm=True, emit=None):
        """오늘 보고서: 심각 판정(engine/severity.py)을 통과한 곳만 에이전트가 상황을 보고 판단해 올림. 그 밖은 올리지 않음"""
        its = self.items(); unsure = self.unsure(); prev = _jload(os.path.join(GOV, "judged.json"), {})
        p_seen = os.path.join(GOV, "first_seen.json"); initial = not os.path.exists(p_seen)
        seen = _jload(p_seen, {}); t = today()
        client = None
        if llm:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=open(os.path.join(self.root, "settings", "anthropic_key.txt"), encoding="utf-8").read().strip())
            except Exception: client = None
        # 같은 동네에서 최근 6개월 사이 같은 공공 기능이 몇 번 사라졌는지 (연달아 사라지면 더 무겁게 봄)
        hist = {}; recent = [it for it in its if (days_since(it["시설"]["폐업일자"]) or 999) <= 180]
        for it in recent:
            mine = {f["기능"] for f in it["분석"].get("기능", []) if PB.info(f["기능"], f.get("세부종류"))}
            if not mine: continue
            hist[it["fid"]] = sum(1 for o in recent if o is not it and o["분석"].get("행정동") == it["분석"].get("행정동")
                                  and mine & {f["기능"] for f in o["분석"].get("기능", [])})
        lsig = hashlib.md5((json.dumps(self.lessons(), ensure_ascii=False) + GA.principles()).encode()).hexdigest()[:8]
        sc = GA.Scorer(); ovr = GA.overrides()
        out = {"날짜": t, "만든때": now().isoformat(timespec="seconds"), "구군": {}, "학습기준": {k: v for k, v in self.baseline().items() if isinstance(v, dict)}}
        if os.environ.get("GINEUNG_DEMO_REPORT"): out["날짜"] = os.environ["GINEUNG_DEMO_REPORT"][:10]   # 영상 시연 서버 전용 (10/24): 보고서 날짜를 이 날로
        checked_public = 0
        gaps = []; waiting = []; watch_all = []
        for gu in GUS:
            g = [it for it in its if it["시설"]["구군"] == gu]
            cands = []; quiet = []; n_out = 0; n_out_t = 0   # quiet: 관찰 + 공백 없음(검토 완료) / n_out: 판정 대상 아님 (생활 필수 기능 없음)
            for it in g:
                pub = is_public_facility(it["분석"])
                if pub: checked_public += 1
                A = self.assess(it, sc)
                if not A:
                    if scope_of(it["분석"]): quiet.append((it, None))   # 생활 필수 시설 · 공백 없음 → 검토 완료 (마을 예외 기능(외식·친목)은 실제 공백이 생길 때만 대상)
                    else:
                        n_out += 1   # 카페·식당·오락 등: 공백 심각도 판정 대상 아님
                        if self._confirm_basis(it["fid"], it["시설"])["확정일"] == out["날짜"]: n_out_t += 1   # 오늘 확정분 (화면의 '오늘 검토 완료'에 함께 보임, 10/26)
                    continue
                cands.append(dict(it, 등급=A["제안"] if A["제안"] in ("긴급", "주의") else "주의", 까닭=A["까닭"], 셈한기능=A["셈한기능"], 판단재료=A))
            sig = lambda it: hashlib.md5((json.dumps(self._sfacts(it, hist), ensure_ascii=False, sort_keys=True, default=str) + lsig).encode()).hexdigest()
            ask_ai = [it for it in cands if it["판단재료"]["점수"] >= AI_MIN]   # 점수가 아주 낮은 곳은 AI에게 묻지 않고 지켜봄 (비용)
            todo = [it for it in ask_ai if prev.get(it["fid"], {}).get("sig") != sig(it)]
            gkey = "구:" + gu; gsig = hashlib.md5(json.dumps(sorted(sig(it) for it in ask_ai)).encode()).hexdigest()
            summary = prev.get(gkey, {}).get("text") if prev.get(gkey, {}).get("sig") == gsig else None
            if ask_ai and (todo or summary is None) and client is not None:
                if emit: emit({"단계": "판단", "진행": f"{gu} {len(ask_ai)}곳"})
                try:
                    self._hist = hist
                    res, s0 = self._judge(gu, ask_ai, client, SONNET_J)
                    res = self._self_review(ask_ai, res, client)   # 보고하려는 곳은 계산 검토 + 독립 검토관 + (다르면) 중재 (10/20)
                    for it in ask_ai:
                        if it["fid"] in res: prev[it["fid"]] = dict(res[it["fid"]], sig=sig(it))
                    prev[gkey] = {"sig": gsig, "text": s0 or None}; summary = s0 or None
                except Exception as ex:
                    if emit: emit({"단계": "판단", "진행": f"{gu} 언어 모델 오류 ({str(ex)[:60]})"})
            rows = []; qs = []
            for it in cands:
                A = it["판단재료"]; fid = it["fid"]; ov = ovr.get(fid)
                j = prev.get(fid) if prev.get(fid, {}).get("sig") == sig(it) else None
                if ov: d, src = ov["판단"], "담당자"
                elif j: d, src = j["판단"], "AI"
                else:
                    d, src = A["제안"], "모델"   # AI 판단 전: 경험으로 배운 판단 모델로, 확실할 때만 보고 (보수적)
                    if d in ("긴급", "주의") and not self.audit(it, A)["통과"]: d = "관찰"   # 계산 검토를 통과하지 못하면 보고하지 않음
                if d == "보고": d = A["제안"] if A["제안"] in ("긴급", "주의") else "주의"
                if src != "담당자" and A["사실"] and all(x.get("공립선택권") for x in A["사실"]): d = "관찰"   # 공립 선택권 축소: 생명·돌봄 단절이 아니라 관찰 (원칙)
                if d in ("긴급", "주의"):
                    j = j if (j and src == "AI") else {"판단": d, "까닭": "", "요약": "", "위험": [], "대응": GP.for_item(it["셈한기능"], {"gap": True, "elder": True, "far": self._far(it)})[:3]}
                    it = dict(it, 등급=d); seen.setdefault(fid, "처음 점검" if initial else t)
                    row = self._srow(it, dict(j, 판단=d), seen.get(fid), t); row["판단한곳"] = src; row["판단점수"] = A["점수"]
                    row["이어받을자원"] = self._relay(it)
                    gaps.append(self._gap_row(gu, it, A, "보고"))
                    row["검토"] = (j or {}).get("검토") or ({"결과": "계산 검토 통과 (AI 판단 전)", "참고": self.audit(it, A)["참고"]} if src == "모델" else None); rows.append(row)
                elif d == "관찰":
                    quiet.append((it, {"까닭": self._watch_text(A, j, src), "관찰": True, "판단한곳": src, "판단점수": A["점수"]}))
                    watch_all.append((it, A))   # 창업·유치 참고 후보 (engine/market_gap.py, 보고 기준과 따로)
                    if A.get("질문") and src != "담당자": qs.append((A["점수"], it, A))
                else: quiet.append((it, dict(j or {"까닭": self._watch_text(A, None, src, none=True)}, 판단한곳=src)))
            # 스스로 판단이 애매한 곳만 담당자에게 하나씩 물음 (하루에 구마다 최대 ASK_MAX곳, 경계에 가까운 것부터)
            qs.sort(key=lambda q: abs(q[0] - 0.55))
            questions = [{"fid": it["fid"], "상호": it["시설"]["상호"], "업종": it["시설"]["업종"], "행정동": it["분석"].get("행정동"), "폐업일자": it["시설"]["폐업일자"],
                          "경도": it["시설"]["경도"], "위도": it["시설"]["위도"], "질문": A["질문"], "까닭": A["까닭"][0], "판단점수": A["점수"]} for _, it, A in qs[:ASK_MAX]]
            rows.sort(key=lambda r: (LV_ORDER[r["등급"]], r["폐업일자"]))
            ask = []
            for fid, u in unsure.items():
                if u["구군"] != gu: continue
                ev = next((e for e in self.cm.events if e["id"] == u["변화id"]), {})
                # 폐업 확인 필요 (10/20 원칙): AI 교차검증으로 확정하지 못한 공공·복지·의료 시설 가운데 문을 닫았을 때 기능 공백이 생기는 곳만 담당자에게.
                # 주민 제보든 인허가 엇갈림·공식 자료든 같은 기준. 일반 가게는 AI가 매주 검토하므로 넘기지 않음. 공백이 없으면 묻지 않고 AI가 계속 확인
                if not self._rc().is_public(fid): continue
                it = {"fid": fid, "시설": u, "분석": self.an.get(fid) or {"기능": []}}; lv, why, used = self.severity(it) if self.an.get(fid) else (None, [], [])
                if not lv:
                    waiting.append({"구군": gu, "상호": u["상호"], "업종": u["업종"], "까닭": u.get("까닭", ""), "제보": bool(u.get("제보"))}); continue
                ask.append({"fid": fid, "상호": u["상호"], "업종": u["업종"], "주소": u["주소"], "행정동": self.an[fid].get("행정동"), "전화": u["전화"] or self.an[fid].get("전화"),
                            "폐업일자": u["폐업일자"], "남은인허가": u["남은인허가"], "경도": u["경도"], "위도": u["위도"], "제보": u.get("제보"),
                            "하던일": self._did(fid), "닫았다면": lv, "닫았다면_까닭": why[:1],
                            "제보수": len(ev.get("제보목록") or []) or (1 if u.get("제보") else 0), "AI분석": ev.get("AI분석"), "까닭": u.get("까닭", "")})
            n_u = sum(1 for r in rows if r["등급"] == "긴급")
            skip = sorted((self._quiet_row(it, j) for it, j in quiet), key=lambda r: (not r["관찰"], -int(re.sub(r"\D", "", r["폐업일자"] or "") or 0)))   # 지켜보는 곳 먼저, 최근 폐업 먼저
            n_w = sum(1 for r in skip if r["관찰"])
            out["구군"][gu] = {"요약": summary or "", "긴급": n_u, "주의": len(rows) - n_u, "관찰": n_w, "항목": rows, "확인요청": ask, "질문": questions, "보고안함": skip,
                              "확정": len(g), "대상아님": n_out, "대상아님_오늘": n_out_t}   # 대상아님: 폐업 확정 시설 중 생활 필수 기능이 없어 공백 심각도 판정 대상이 아닌 곳 (수만)
        out["확인대기"] = waiting
        # 기능 공백 현황(공개)은 지자체에 보고된 곳만 (10/20 헌준님: 지자체를 거친 자료만). 관찰 중인 곳은 지자체 화면에만 두고, 보고로 올라가면 그때 공개
        out["기능공백"] = sorted(gaps, key=lambda r: (r["상태"] != "보고", r["구군"], r["행정동"] or "", -(r.get("주민찾음") or 0)))
        try:   # 생활 서비스 공백 지역 (10/21): 폐업과 상관없이 생활 필수 시설이 걸어서 기준 거리의 2배 안에 없는 동네 (계산만, engine/area_gap.py)
            import area_gap as AGP
            out["공백지역"] = AGP.compute(self)
        except Exception as ex: out["공백지역"] = []; out["공백지역_오류"] = str(ex)[:120]
        try:   # 창업·유치 참고 (10/20): 관찰 중인 민간 가게 가운데 생활 필수 기능 + 같은 업종 경쟁이 적은 곳, AI 상권 판단으로 공개 여부 (보고와 섞지 않음)
            import market_gap as MG
            MG_ENROLL = ENROLL; self.ENROLL_SET = MG_ENROLL
            out["창업참고"] = MG.rows(self, watch_all, client)
        except Exception as ex: out["창업참고"] = []; out["창업참고_오류"] = str(ex)[:120]
        try:   # 공개 '기능 공백 현황' 한 목록 (10/21): 상시 부재 구역 + 폐업 영향(보고·창업 참고) — engine/area_gap.py
            import area_gap as AGP
            out["기능공백구역"] = AGP.unified(self, out, its, client)
        except Exception as ex: out["기능공백구역"] = []; out["기능공백구역_오류"] = str(ex)[:160]
        try:   # 공백 구역 해소 확인 (10/21): 어제 있던 구역이 오늘 사라졌으면 까닭과 함께 기록 (최근 30일)
            out["구역해소"] = AGP.track_resolved(self, out.get("기능공백구역", []), t) if out.get("기능공백구역") else []
        except Exception as ex: out["구역해소"] = []; out["구역해소_오류"] = str(ex)[:160]
        out["살펴본_공공복지_폐업"] = checked_public; out["보고기준"] = report_rules(self.baseline())
        sp = []   # (10/26) 공공 체육시설·공원 공백: 같은 절차로 판정한 결과를 참고에 따로 (예산 처리 기간이 길어 공공·복지 안내 기간(2년) 동안 보임)
        for gu_, v_ in out["구군"].items():
            for r_ in v_.get("항목", []):
                k_ = self.sp_kind(r_["fid"])
                if k_: sp.append({"fid": r_["fid"], "구분": k_, "상호": r_.get("상호"), "업종": r_.get("업종"), "구군": gu_, "행정동": r_.get("행정동"), "폐업일자": r_.get("폐업일자"),
                                  "판정": r_.get("등급"), "까닭": r_.get("까닭"), "대응": r_.get("대응"), "경도": r_.get("경도"), "위도": r_.get("위도"), **self._sp_pkg(r_, k_)})
            for r_ in v_.get("보고안함", []):
                k_ = self.sp_kind(r_["fid"])
                if k_: sp.append({"fid": r_["fid"], "구분": k_, "상호": r_.get("상호"), "업종": r_.get("업종"), "구군": gu_, "행정동": r_.get("행정동"), "폐업일자": r_.get("폐업일자"),
                                  "판정": "관찰" if r_.get("관찰") else (r_.get("구분") or "공백 없음"), "까닭": r_.get("까닭"), "경도": r_.get("경도"), "위도": r_.get("위도"), **self._sp_pkg(r_, k_)})
        out["체육공원"] = sorted([r for r in sp if r["판정"] in ("긴급", "주의", "관찰")], key=lambda r: ({"긴급": 0, "주의": 1, "관찰": 2}.get(r["판정"], 3), str(r.get("폐업일자") or "")))   # 공백 없는 폐쇄는 검토 완료에만 (10/26)
        _lf = self.cm.engine().leaf
        out["주민수요"] = [r for r in DM.summary(30) if any(life_gap((_lf.get(r["기능"]) or {}).get("grade"), r["기능"], k, r.get("행정동")) for k in (r.get("종류") or [None]))][:40]   # 생활 필수 기능만 (10/26)
        out["이용결과"] = DM.use_summary(30)
        out["하나남은곳"] = (_jload(os.path.join(GOV, "watch_rural.json"), {}) or {}).get("곳", [])
        rep = {r["fid"]: r for v in out["구군"].values() for r in v["항목"]}
        for r in rep.values():
            for a in r.get("대응") or []: a["요청문"] = self._request_text(r, a)
        FU = self.follow_up(rep, {it["fid"]: it for it in its}, t)
        for r in rep.values():
            x = FU.get(r["fid"]) or {}
            if x.get("처음") and x["처음"] != t: r["후속"] = {"처음": x["처음"], "처음_주민": x.get("처음_주민"), "지금_주민": x.get("지금_주민")}
        out["해소"] = sorted([dict(v, fid=k) for k, v in FU.items() if v.get("상태") == "해소" and (days_since(v.get("해소일")) or 0) <= 30], key=lambda v: v["해소일"], reverse=True)
        out["판단모델"] = {"사례수": sc.m.get("사례수", 0), "배운때": sc.m.get("배운때"), "바뀐_특징": sc.m.get("바뀐_특징", [])}
        from report_check import last_review
        lr = last_review()
        _F = self.cm.engine().F
        def _xy(r):   # 지자체 화면에서 누르면 위치를 보여 주려고 좌표를 붙임 (시설 자료에서)
            f = r.get("fid")
            if f in _F.index and not r.get("위도"):
                try: r = dict(r, 경도=float(_F.at[f, "경도"]), 위도=float(_F.at[f, "위도"]))
                except Exception: pass
            return r
        out["해소"] = [_xy(r) for r in out.get("해소", [])]
        out["해소"] += [{"상호": f"{z.get('행정동')} {z.get('시설')} 공백 구역", "업종": "기능 공백 구역", "구군": z.get("구군"), "해소일": z["해소일"], "까닭": z.get("까닭"),
                        "경도": z.get("밀집_경도") or z.get("경도"), "위도": z.get("밀집_위도") or z.get("위도"), "구역": True} for z in out.get("구역해소", [])]   # 지자체 '공백 해소'에 구역 해소도 함께
        if lr and lr.get("항목"): lr = dict(lr, 항목=[_xy(r) for r in lr["항목"]])
        out["제보검토"] = lr
        out["제보대기"] = len(self._rc().pending(public=False))
        _jsave(os.path.join(GOV, "first_seen.json"), seen)
        _jsave(os.path.join(GOV, "judged.json"), prev)
        _jsave(os.path.join(GOV, f"brief_{t}.json"), out); _jsave(os.path.join(GOV, "brief_latest.json"), out)
        return out

    WATCH_PHRASE = {"도심의 생명 직결 아닌 공백": "도심 내 비긴급 공백", "담당자가 할 일 없음": "지자체 조치 수단 없음",
                    "다른 방법으로 대신할 수 있음": "배달·방문 등 대체 수단 있음"}
    def _watch_text(self, A, j, src, none=False):
        """관찰 중인 까닭 한 줄: 무엇이 멀어지는지 + 왜 보고하지 않는지"""
        what = re.sub(r"\s*\(65세 이상 [\d,]+명\)$", "", A["까닭"][0]).rstrip(".")
        if src == "담당자": return f"{what} · 담당자 판단으로 {'보고 안함' if none else '관찰'}"
        if j and j.get("까닭"): return f"{what} · {j['까닭']}"
        neg = [e["특징"] for e in A["설명"] if e["방향"] == "내림" and e["특징"] in self.WATCH_PHRASE]
        why = self.WATCH_PHRASE[neg[0]] if neg else ("공백 정도 경미" if none else "보고 필요성 불분명")
        return f"{what} · {_j(why, '으로')} 보고 안함" if none else f"{what} · {_j(why, '으로')} 관찰"
    def _confirm_basis(self, fid, c):
        """폐업 확정 근거와 상태 (10/21): 그 시설의 마지막 폐업·휴업 반영 기록 기준
        근거: 담당자 확인 / AI 교차검증 / 공식 자료(유치원알리미·어린이집정보공개포털) / 인허가. 상태: 폐업 / 운영 중단(휴원·휴업)"""
        e = next((x for x in reversed(self.cm.events) if x.get("fid") == fid and x.get("종류") in ("폐업", "휴업") and x.get("상태") == "반영"), None)
        why = str((self.cm.rows.get(fid) or {}).get("제외사유") or c.get("제외사유") or "")
        who = str(((e or {}).get("확인") or {}).get("담당자") or "")
        src = str((e or {}).get("출처") or c.get("출처") or "") + " " + why
        if who: basis = "AI 교차검증" if who.startswith("AI") else "담당자 확인"   # resolve(who=...)가 남긴 확인자
        elif "담당자" in src: basis = "담당자 확인"
        elif "AI" in src: basis = "AI 교차검증"
        elif "유치원알리미" in src or "정보공개" in src or "교육청" in src: basis = "공식 자료"
        elif "인허가" in src or "상가" in src: basis = "인허가"
        else: basis = None
        pause = "휴원·휴업" in why or bool(e and e.get("종류") == "휴업" and not who)   # 담당자가 확인했으면 담당자가 고른 상태(폐업 / 휴원·휴업)를 따름
        when = str(((e or {}).get("확인") or {}).get("때") or (e or {}).get("접수") or c.get("시작일") or c.get("폐업일자") or "")[:10] or None   # 확정일: 담당자·AI가 확인한 날, 자동 반영한 날, 자료에 폐업이 올라온 날 순
        return {"확정근거": basis, "확정상태": "운영 중단" if pause else "폐업", "확정일": when}
    def _quiet_row(self, it, j=None):
        """살펴봤지만 보고하지 않은 공공·복지 시설: 이름·폐업일과 보고하지 않은 까닭 한 줄 (계산한 사실로만 씀)"""
        c = it["시설"]; a = it["분석"]
        f = next((f for f in a.get("기능", []) if (PB.info(f["기능"], f.get("세부종류")) or {}).get("회복")), None) \
            or next((f for f in a.get("기능", []) if in_scope(f, self._rural(it) is True)), None)   # 공공 목적 기능, 없으면 하던 생활 필수 기능
        why = (j or {}).get("까닭") or ""
        if not why and f is not None:
            if f["기능"] in ENROLL:
                cap = ((self.cm.engine().scale(it["fid"]) or {}).get("정원")) or 0; near = self._nearest_same(it["fid"], f["기능"]); ds = days_since(c.get("폐업일자"))
                bits = []
                if near is not None and near <= SV.ENROLL_NEAR_M: bits.append(f"{near/1000:.1f}km 거리 동일 기관 있음")
                if ds is not None and ds > ENROLL_DAYS: bits.append(f"폐업 후 {ds}일 경과")
                if cap and cap < SV.ENROLL_CAP: bits.insert(0, f"정원 {cap}명")
                why = " · ".join(bits)
            else:
                alt = next((d for d in f.get("대체시설", []) if d.get("걷는시간_분") is not None), None)
                if alt and alt["걷는시간_분"] <= 30:
                    n = alt["상호"]; last = n[-1] if n else ""
                    why = f"도보 {max(1, round(alt['걷는시간_분']))}분 거리 {n} 대체 가능"
        if c.get("운영종료_근거") and c["운영종료_근거"] != "정보공시 중단 시점으로 추정": why = c["운영종료_근거"] + (" · " + why if why else "")   # 교육청이 원아 배치까지 정한 통폐합·휴원
        elif c.get("운영종료_근거") == "정보공시 중단 시점으로 추정" and not (j or {}).get("관찰"): why = (why + " · " if why else "") + "정보공시 중단 기준 운영 종료 추정"
        if not why: why = "인근 대체 시설 있음"
        if self._pub_k(it["fid"]) and not (j or {}).get("관찰"):
            pa = self._pub_alt(it["fid"])
            if pa and pa["곳"]: why += f" · 공립 대체 가능(반경 {pa['반경_m'] / 1000:g}km 공립 {pa['곳']}곳·여유 {pa['여유']}명)"
        # 구분 (10/21 재정리): 관찰 / 공백 없음(도보권 대체 시설) / 공백 경미(공백은 계산됐으나 대체 수단·영향이 작아 해당 없음)
        gap = bool(it.get("판단재료"))
        kind = "관찰" if (j or {}).get("관찰") else ("공백 경미" if gap else "공백 없음")
        fname = ""
        cb = self._confirm_basis(it["fid"], c)
        if cb["확정상태"] == "운영 중단": why = why.replace("폐업 후", "운영 중단 후")
        return {"fid": it["fid"], "상호": c["상호"], "업종": c["업종"], "행정동": a.get("행정동"), "폐업일자": c["폐업일자"],
                "기능": f["이름"] if f else (fname or None), "까닭": why, "구분": kind, "공개까지": c.get("공개까지"), "공공": is_public_facility(a), "경도": c["경도"], "위도": c["위도"], "관찰": bool((j or {}).get("관찰")),
                **self._confirm_basis(it["fid"], c),
                "판단한곳": (j or {}).get("판단한곳"), "판단점수": (j or {}).get("판단점수")}

    def _srow(self, it, j, first, t):
        c = it["시설"]; a = it["분석"]; fs = it["셈한기능"]; f0 = fs[0]; sv = f0.get("심각") or {}
        def crow(d):   # 직선거리 (걸어서 갈 수 없는 먼 곳도 얼마나 먼지 보여 줌)
            try: return round(((float(d["경도"]) - float(c["경도"])) * 90200) ** 2 + ((float(d["위도"]) - float(c["위도"])) * 110540) ** 2) ** 0.5
            except Exception: return None
        alts = [{"상호": d["상호"], "업종": d.get("업종"), "걷는시간_분": d.get("걷는시간_분"), "직선_m": crow(d), "주소": d.get("주소"), "전화": d.get("전화"), "경도": d.get("경도"), "위도": d.get("위도")}
                for d in f0.get("대체시설", [])[:3]]
        dongs = [{"행정동": d, "구군": c["구군"], "주민": n} for d, n in sv.get("동", [])]
        return {"fid": it["fid"], "등급": it["등급"], "상호": c["상호"], "업종": c["업종"], "주소": c["주소"], "구군": c.get("구군"), "행정동": a.get("행정동"), "전화": a.get("전화"),
                "폐업일자": c["폐업일자"], "경도": c["경도"], "위도": c["위도"], "까닭": it["까닭"], "기능": re.sub(r"\s*\(.*\)$", "", (f0.get("심각") or {}).get("이름") or SV.NAME.get(f0["기능"]) or f0["이름"]), "심각": sv,
                "대체시설": alts, "영향동": dongs, "요약": j.get("요약") or "",
                "위험": j.get("위험") or [], "대응": j.get("대응") or [], "판단까닭": j.get("까닭"), "새로": first == t, "알린날": first,
                "처리": self.handled.get(it["fid"]), "하던일": self._did(it["fid"]), "보고유지": bool(c.get("보고유지"))}

    def _did(self, fid):
        """이 곳이 하던 일 (주민 화면과 같은 함수: Engine.what_it_does) — 공공 목적이면 근거 법령까지, 장기요양기관이면 규모(정원·인력)"""
        try:
            E = self.cm.engine(); sc = E.scale(fid)
            return [{"이름": d["이름"], "등급": d["등급"], "세부종류": d["세부종류"], "판정": d["판정"], "근거": d["근거"][:1],
                     "공공": ({"권리": d["공공"]["권리"], "법령": d["공공"]["법령"]} if d["공공"] else None), "규모": sc["글"] if (sc and i == 0) else None}
                    for i, d in enumerate(E.what_it_does(fid))]
        except Exception: return []

    def _ltc_numbers(self, it, f):
        """돌봄 기관이 문 닫았을 때 담당자에게 필요한 숫자: 이 기관 정원(옮겨야 할 이용자 규모), 같은 구 같은 일을 하는 기관의 정원 합계"""
        E = self.cm.engine(); me = E.scale(it["fid"]); gu = it["시설"]["구군"]
        ks = [kk for (L, kk) in E.kind if L == f["기능"]] or [None]
        prov = {p for kk in ks for p in self.cm.providers(f["기능"], kk, None) if p != it["fid"] and E.F.at[p, "구군"] == gu}
        caps = [E.scale(p) for p in prov]; total = sum((c or {}).get("정원") or 0 for c in caps)
        return {"정원": (me or {}).get("정원"), "같은구_정원합계": total or None, "정원출처": (me or {}).get("출처")}

    def _row(self, it, txt, first, t, acts=None, why=None):
        c = it["시설"]; a = it["분석"]; fs = it["셈한기능"]
        key = []
        for f in fs[:2]:
            if f["기능"] in ENROLL: key.append(dict({"기능": f["이름"], "같은구_대체수": f["같은구_대체수"], "이용자옮김": True}, **self._ltc_numbers(it, f)))
            else: key.append({"기능": f["이름"], "기준_분": f["기준_분"], "공백": f["공백"], "공백_65세이상": f["공백_65세이상"], "가까운주민": f["가까운주민"],
                              "걷는시간_전": f["걷는시간_전"], "걷는시간_후": f["걷는시간_후"], "공백_걷는시간_전": f.get("공백_걷는시간_전"), "공백_걷는시간_후": f.get("공백_걷는시간_후"),
                              "확인필요_근처": f.get("확인필요_근처", 0), "확인할곳": f.get("확인할곳", {}), "공백_넓게": f.get("공백_넓게")})
        alts = []
        for f in fs[:1]:
            for d in f["대체시설"][:3]: alts.append({"상호": d["상호"], "업종": d.get("업종"), "걷는시간_분": d.get("걷는시간_분"), "주소": d.get("주소"), "전화": d.get("전화"),
                                                 "확인필요": d.get("확인필요"), "경도": d.get("경도"), "위도": d.get("위도")})
        dongs = []
        for f in fs:
            for d in f["행정동"]:
                if d["행정동"] not in [x["행정동"] for x in dongs]: dongs.append({"행정동": d["행정동"], "구군": d["구군"], "주민": d.get("뚜렷한공백") or d["주민"]})
        h = self.handled.get(it["fid"])
        return {"fid": it["fid"], "등급": it["등급"], "상호": c["상호"], "업종": c["업종"], "주소": c["주소"], "구군": c.get("구군"), "행정동": a.get("행정동"), "전화": a.get("전화"),
                "폐업일자": c["폐업일자"], "변화": c["변화"], "경도": c["경도"], "위도": c["위도"], "새가게": c.get("새가게"),
                "까닭": it["까닭"], "숫자": key, "대체시설": alts, "영향동": dongs[:6], "요약": txt["요약"], "위험": txt["위험"], "대응": acts if acts is not None else self._actions(it), "판단까닭": why, "범위": "마을" if any(w.startswith("[마을") for w in it["까닭"]) else "공공",
                "새로": first == t, "알린날": first, "처리": h, "하던일": self._did(it["fid"])}

    def mark(self, fid, done=True, who="", note="", acts=None):
        if done: self.handled[fid] = {"때": now().isoformat(timespec="minutes"), "누가": who, "메모": note, "한일": list(acts or [])}
        else: self.handled.pop(fid, None)
        _jsave(self.p_h, self.handled)
        if done: self._remember(fid, "처리 완료", note, who or "담당자")   # 보고가 쓸모 있었다는 약한 신호 (학습)

    # ---------- 관심 지역(읍·면) 미리 살피기 (10/19 헌준님: 시골은 도심보다 더 주시) ----------
    def rural_watch(self, max_s=150):
        """읍·면에서 그 일을 하는 마지막 곳: 문을 닫으면 마을 주민이 걸어서 갈 곳이 없어지는 곳을 미리 찾아 둠 (문 닫기 전부터 살핌)
        어떤 일을 볼지는 기능의 성격으로 정함 (못 받으면 하루 안팎에 생활이 어려워지는 꼭 필요한 일)"""
        p_out = os.path.join(GOV, "watch_rural.json"); old = _jload(p_out, {})
        if old.get("날짜") == today() and old.get("판정") == 4: return old   # 3: 생활권 원칙·거주형 제외 (10/21) / 4: 먹거리·의료·돌봄·안전만 (10/26)
        E = self.cm.engine(); t0 = time.time(); out = []
        lids = [l for l in list(E.leaf) + list(SV.SPECIAL) if self._std(l) or l in SV.SPECIAL]
        for lid in lids:
            name = re.sub(r"\s*\(.*\)$", "", SV.NAME.get(lid) or (E.leaf.get(lid) or {}).get("name", lid)); grade = (E.leaf.get(lid) or {}).get("grade", "필수" if lid in SV.SPECIAL else None)
            prof = GA.profile(lid, name, PB.PUBLIC.get(lid), None, grade)
            if grade != "필수" or prof.get("시간민감도") not in ("분", "시간", "일"): continue
            if lid not in URGENT_OK: continue   # (10/26 전수 점검) 단절 우려는 끊기면 하루 안에 생활이 어려워지는 먹거리·의료·돌봄·안전만 (테니스장이 '마을 마지막 운동 시설'로 오르던 것)
            P = self._prov_all(lid); B = self._prov_all(lid, True)
            rural = [p for p in P if re.search(r"[읍면]$", str(E.F.at[p, "행정동"] or ""))]
            if not rural or not B: continue
            bx = E.F.loc[B, "x"].astype(float).values * 90200; by = E.F.loc[B, "y"].astype(float).values * 110540
            for p in rural:
                if time.time() - t0 > max_s: break
                x, y = float(E.F.at[p, "x"]) * 90200, float(E.F.at[p, "y"]) * 110540
                d = np.sqrt((bx - x) ** 2 + (by - y) ** 2); d = d[d > 1]
                if len(d) and d.min() < 1000: continue   # 1km 안에 같은 일을 하는(하는지 모르는 곳 포함) 곳이 있으면 마지막 곳이 아님
                sv = self._severe(p, lid)
                if not self._enough(sv, True): continue
                sb = self._severe(p, lid, broad=True)
                if not self._enough(sb, True): continue
                dn = str(E.F.at[p, "행정동"] or "")
                fx = {"기능": lid, "읍면": True, "생활권": "면" if dn.endswith("면") else "읍", "고립_m": self._nearest_same(p, lid), "성격": prof, "전체": sb,
                      "보조공급처": lid in GA.AUX_FOR and str(E.F.at[p, "업종코드"]) in GA.SUPPLY_AUX, "직접대응": str(p).startswith("P:")}
                if not GA.area_ok(fx): continue   # 생활권 원칙: 문을 닫아도 생활권이 끊기지 않는 민간 가게는 사전 관찰 대상이 아님 (보고 기준과 같은 원칙)
                out.append({"fid": p, "상호": E.F.at[p, "상호"], "업종": E.F.at[p, "업종"], "구군": E.F.at[p, "구군"], "행정동": E.F.at[p, "행정동"], "기능": name,
                            "주민": sb["밀려난주민"], "65세이상": sb["밀려난_65세이상"], "가장가까운_직선_m": round(float(d.min())) if len(d) else None,
                            "경도": _num(E.F.at[p, "x"]), "위도": _num(E.F.at[p, "y"])})
        out.sort(key=lambda r: -r["65세이상"])
        res = {"날짜": today(), "판정": 4, "곳": out[:60], "다_봄": time.time() - t0 <= max_s}
        _jsave(p_out, res); return res

    # ---------- 조치 후속 관리 (10/19): 보고한 곳을 매일 다시 재서, 공백이 풀렸는지 알려 줌 ----------
    def _new_near(self, fid, lids, since, within=2500):
        """보고한 뒤 근처에 같은 일을 하는 곳이 새로 열었거나 다시 열었는지 (인허가 변화 기록)"""
        E = self.cm.engine()
        if fid not in E.F.index: return None
        x0, y0 = float(E.F.at[fid, "x"]), float(E.F.at[fid, "y"])
        for e in reversed(self.cm.events):
            if e.get("종류") not in ("신규", "재개업") or (e.get("날짜") or "") < since: continue
            f2 = e.get("fid")
            if f2 not in E.F.index or E.F.at[f2, "x"] != E.F.at[f2, "x"]: continue
            d = (((float(E.F.at[f2, "x"]) - x0) * 90200) ** 2 + ((float(E.F.at[f2, "y"]) - y0) * 110540) ** 2) ** 0.5
            if d > within: continue
            if f2 == fid and e["종류"] == "재개업": return "영업 재개로 해소"
            if any(L in lids and st in ("근거", "강함", "업종") for (L, k, nd), (st, why) in E.served(f2).items()):
                return f"{d / 1000:.1f}km 거리 {E.F.at[f2, '상호']} 신규 개업으로 해소"
        return None
    def follow_up(self, reported, its_by_fid, t):
        """보고한 적이 있는 곳마다: 공백이 그대로인지, 풀렸는지. data/gov/followup.json에 쌓음"""
        p = os.path.join(GOV, "followup.json"); F = _jload(p, {})
        for fid, row in reported.items():   # 오늘도 보고하는 곳
            it = its_by_fid.get(fid) or {}
            x = F.setdefault(fid, {"처음": t, "상호": row["상호"], "업종": row["업종"], "구군": row.get("구군"), "처음_주민": (row.get("심각") or {}).get("밀려난주민"),
                                   "기능": [f["기능"] for f in (it.get("셈한기능") or [])] or [f["기능"] for f in (it.get("분석") or {}).get("기능", [])]})
            x.update({"상태": "남아 있음", "지금_주민": (row.get("심각") or {}).get("밀려난주민"), "확인": t,
                      "폐업일자": row.get("폐업일자"), "주소": row.get("주소"), "경도": row.get("경도"), "위도": row.get("위도")})
        for fid, x in F.items():
            if fid in reported or x.get("상태") == "해소": continue
            it = its_by_fid.get(fid)
            A = self.assess(it) if it else None
            lids = set(x.get("기능") or [])
            why = self._new_near(fid, lids or {f["기능"] for f in ((it or {}).get("분석") or {}).get("기능", [])}, x.get("처음", t))
            if A is None or why:
                x.update({"상태": "해소", "해소일": t, "까닭": why or "공백 감소로 보고 기준 미달", "확인": t})
            else:
                x.update({"상태": "관찰로 내려감", "확인": t, "지금_주민": (A["기능"].get("전체") or {}).get("밀려난주민")})
        _jsave(p, F); return F
    def _request_text(self, row, act):
        """관련 기관에 보낼 연계 요청문 (계산한 사실로만 씀, 크레딧 없음)"""
        sv = row.get("심각") or {}; place = " ".join(x for x in (row.get("구군"), row.get("행정동")) if x)
        lines = [f"[연계 요청] {place} {row['상호']}({row['업종']}) 폐업에 따른 {row.get('기능') or '생활'} 공백"]
        if sv.get("밀려난주민"): lines.append(f"- 영향: {row.get('기능')}까지 {sv['기준_m'] / 1000:.1f}km 넘게 멀어지는 주민 약 {sv['밀려난주민']:,}명 (65세 이상 {sv.get('밀려난_65세이상', 0):,}명)")
        if sv.get("정원"): lines.append(f"- 영향: 이용자 옮김 필요 (정원 {sv['정원']}명)")
        alts = [a for a in row.get("대체시설", [])[:2]]
        if alts: lines.append("- 가까운 대체 시설: " + ", ".join(f"{a['상호']}" + (f"(걸어서 {round(a['걷는시간_분'])}분)" if a.get("걷는시간_분") else "") for a in alts))
        lines.append(f"- 요청: {act['할일']}")
        if act.get("근거"): lines.append(f"- 근거: {act['근거']}")
        lines.append(f"- 폐업일: {row.get('폐업일자') or '-'}")
        return "\n".join(lines)

    # ---------- 배우기: 담당자 반응을 사례로 남기고, 판단 모델을 다시 배움 ----------
    def _case(self, fid):
        """사례로 남길 이 곳의 판단 재료 (지금 보고서의 문 닫은 곳, 없으면 가정해서 잼)"""
        E = self.cm.engine()
        c = next((x["시설"] for x in self.items() if x["fid"] == fid), None)
        if c is None:
            if fid not in E.F.index: return None, None
            r = E.F.loc[fid]; c = {"상호": r["상호"], "업종": r["업종"], "구군": r["구군"], "폐업일자": today(), "행정동": r["행정동"], "경도": _num(r["x"]), "위도": _num(r["y"])}
        a = self.an.get(fid) or self.analyze(fid, True)
        return {"fid": fid, "시설": c, "분석": dict(a, 구군=c["구군"])}, c
    def _remember(self, fid, label, note="", who="담당자"):
        it, c = self._case(fid)
        A = self.assess(it) if it else None
        if not A: return None
        return GA.add_precedent(fid, label, A["특징"], f"{c['상호']}({c['업종']}, {it['분석'].get('행정동') or c['구군']}): {A['까닭'][0]}", note, who,
                                ai=(_jload(os.path.join(GOV, "judged.json"), {}).get(fid) or {}).get("판단"))
    def feedback(self, fid, label, note="", who="담당자"):
        """담당자가 AI 판단을 바로잡음 (선택): '보고' '관찰' '해당 없음'. 그 곳은 담당자 판단을 따르고, 사례로 남겨 다음 학습에 씀"""
        if label not in ("보고", "관찰", "해당 없음", None): raise ValueError(label)
        GA.set_override(fid, label, who)
        row = self._remember(fid, label, note, who) if label else None
        self.train()
        return {"판단": label, "사례": bool(row)}
    def refresh_precedents(self):
        """판단 재료(특징)가 바뀌어 예전 사례의 특징 수가 맞지 않으면, 그 곳을 다시 재서 특징을 새로 씀 (배운 것을 잃지 않게)"""
        P = GA.precedents(); bad = [r for r in P if len(r.get("특징", [])) != len(GA.FEATS)]
        if not bad: return 0
        n = 0
        for r in bad:
            it, c = self._case(r["fid"]); A = self.assess(it) if it else None
            if A: r["특징"] = [round(float(v), 4) for v in A["특징"]]; n += 1
            elif len(r.get("특징", [])) < len(GA.FEATS):   # 다시 잴 수 없는 사례(예시로 만든 가정 사례): 새로 생긴 판단 재료는 '해당 없음(0)'으로 채움
                r["특징"] = list(r["특징"]) + [0.0] * (len(GA.FEATS) - len(r["특징"])); n += 1
        with open(GA.P_PREC, "w", encoding="utf-8") as fh: fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in P)
        return n
    def train(self):
        """판단 모델 다시 배우기 (크레딧 없음): 에이전트가 쌓은 경험 + 담당자 반응(3배 무겁게). 헌준님 예시는 시험에만 (engine/gap_practice.py)"""
        # (10/29 헌준님: 한 번 배우고 끝이 아니라 매일 꾸준히 정밀도를 높이게) 매일 다시 배우고 정확도를 기록,
        #  같은 시험 사례(고정)에서 정확도가 최고 기록보다 2%p 넘게 떨어지면 새 모델을 쓰지 않고 이전 모델로 되돌림
        import gap_practice as PR, gap_agent as GAx, shutil
        self.refresh_precedents()
        bak = {}
        for k, pth in GAx.P_HEADS.items():
            if os.path.exists(pth): bak[k] = pth + ".prev"; shutil.copyfile(pth, bak[k])
        r = PR.train()
        acc = {k: (v or {}).get("정확도") for k, v in (r.get("시험") or {}).items() if isinstance(v, dict)}
        hp = os.path.join(ROOT, "data", "gov", "model_history.jsonl")
        hist = [json.loads(l) for l in open(hp, encoding="utf-8") if l.strip()] if os.path.exists(hp) else []
        best = max([h.get("정확도", {}).get("보고") or 0 for h in hist if h.get("채택", True)], default=0)
        prev = next((h for h in reversed(hist) if h.get("채택", True)), None)
        now_acc = acc.get("보고"); keep = True
        if now_acc is not None and best and now_acc < best - 0.02:
            keep = False
            for k, b in bak.items(): shutil.copyfile(b, GAx.P_HEADS[k])   # 이전 모델 유지
        row = {"날짜": today(), "사례": r["경험"], "담당자_반응": r["담당자_반응"], "정확도": acc, "채택": keep}
        with open(hp, "a", encoding="utf-8") as fh: fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        d = None if (now_acc is None or not prev or (prev.get("정확도") or {}).get("보고") is None) else round((now_acc - prev["정확도"]["보고"]) * 100, 1)
        return {"경험": r["경험"], "담당자_반응": r["담당자_반응"], "시험_정확도": now_acc, "전일_대비_퍼센트포인트": d, "채택": keep}
    def official_check(self):
        """공식 자료로 공공 시설 운영 확인 (10/20): 유치원 정보공시가 멈춘 곳 → 확인 필요 (닫혔다면 공백이 생기는 곳만 담당자에게 묻고, 나머지는 다음 공시를 기다림)"""
        E = self.cm.engine(); n = 0
        K = E.F[(E.F["업종코드"] == "PUB:유치원") & (E.F["대안후보"] == "확인 필요") & E.F["제외사유"].astype(str).str.startswith("최근 공시")]
        R = self._reorg(); official = 0
        for fid, r in E.F[(E.F["업종코드"] == "PUB:유치원") & (E.F["대안후보"] != "아니요")].iterrows():   # 교육청 통폐합·휴원 결정(공식) → 바로 반영
            nm = re.sub(r"\s", "", str(r["상호"])); d, why = self.kinder_stop(fid, r["상호"])
            if not d or why == "정보공시 중단 시점으로 추정": continue
            kind = "휴업" if why.startswith("교육청 휴원") else "폐업"   # 폐원·통합·폐교 결정은 폐업, 휴원 결정만 운영 중단
            if self.cm.close(fid, date=d, kind=kind, source="대구시교육청 결정", note=why, who="공식 자료").get("결과") == "반영": official += 1
        if official: K = E.F[(E.F["업종코드"] == "PUB:유치원") & (E.F["대안후보"] == "확인 필요") & E.F["제외사유"].astype(str).str.startswith("최근 공시")]
        for fid, r in K.iterrows():
            why = str(r["제외사유"]).replace("휴원·폐원 여부 확인 필요", "휴업·폐업 여부 확인 필요")
            if self.cm.flag(fid, why, source="유치원알리미")["결과"] == "확인 요청": n += 1
        back = 0
        F0 = self.cm.F0.set_index("fid", drop=False) if "fid" in self.cm.F0.columns and self.cm.F0.index.name != "fid" else self.cm.F0
        for fid, r in E.F[(E.F["업종코드"] == "PUB:유치원") & (E.F["대안후보"] == "아니요") & E.F["제외사유"].astype(str).str.contains("휴원·휴업")].iterrows():
            b0 = F0.loc[fid] if fid in F0.index else None
            if b0 is not None and str(b0.get("대안후보")) == "예" and not str(b0.get("제외사유") or "").startswith("최근 공시"):   # 최신 공시에 다시 나옴 → 운영 재개
                if self.cm.reopen(fid, date=today(), source="유치원알리미", who="공식 자료").get("결과") == "반영": back += 1
        if n or back or official: self.cm._finish_new(self.cm._update_dirs())
        waiting = int(((E.F["업종코드"] == "PUB:유치원") & E.F["제외사유"].astype(str).str.startswith("유치원알리미")).sum())   # 이미 확인 필요로 올린 곳까지 (화면 글이 '0곳'으로 나오지 않게)
        return {"새_확인요청": n, "공시_멈춘_유치원": max(len(K), waiting), "교육청_결정_반영": official}
    def childcare_check(self, fetch=True):
        """어린이집정보공개포털로 어린이집 운영 확인 (10/20). 공식 기록이라 분명한 것은 바로 반영:
        휴지 → 휴업으로 반영(주민 안내 중단, 공백 계산), 다시 정상·재개 → 다시 안내.
        공식 목록에 없는 곳(폐지 가능) → 확인 필요 (AI 교차검증 → 분명하면 반영, 아니면 공백이 생기는 곳만 담당자에게).
        정원·현원도 새로 맞춤 (원아 이전 공백·주변 남는 자리 계산)"""
        import childcare as CC, subprocess
        if fetch:
            C0, d0 = CC.latest()
            if d0 != today():   # 하루 한 번 받음 (구·군 9번 요청)
                try: subprocess.run([sys.executable, os.path.join(self.root, "pipeline", "fetch_childcare.py")], cwd=self.root, timeout=240, capture_output=True)
                except Exception: pass
        C, day = CC.latest()
        if C is None: return {"자료": "없음", "맞춤": 0, "휴업": 0, "다시 안내": 0, "확인 필요": 0}
        try: subprocess.run([sys.executable, os.path.join(self.root, "pipeline", "build_child_capacity.py")], cwd=self.root, timeout=120, capture_output=True)
        except Exception: pass
        E = self.cm.engine(); E._ccap = None
        F = E.F; m, ours, _ = CC.match(F, C)
        n = {"자료": day, "맞춤": len(m), "휴업": 0, "다시 안내": 0, "확인 필요": 0}
        fresh = (datetime.date.fromisoformat(today()) - datetime.date.fromisoformat(day)).days <= 7
        busy = {e["fid"] for e in self.cm.events if e["상태"] == "확인 필요"}
        for fid, i in m.items():
            r = C.loc[i]; st = str(r.get("crstatusname", "")); row = F.loc[fid]
            if st == "휴지" and row["대안후보"] != "아니요" and fid not in busy:
                b, e = str(r.get("crpausebegindt", ""))[:10], str(r.get("crpauseenddt", ""))[:10]
                if self.cm.close(fid, date=b, kind="휴업", source="어린이집정보공개포털", note=f"휴지 {b}~{e}", who="공식 자료")["결과"] == "반영": n["휴업"] += 1
            elif st in ("정상", "재개") and row["대안후보"] == "아니요" and (str(row["제외사유"]).startswith("어린이집정보공개포털: 휴업") or "휴원·휴업" in str(row["제외사유"])):
                if self.cm.reopen(fid, date=today(), source="어린이집정보공개포털", who="공식 자료")["결과"] == "반영": n["다시 안내"] += 1
        if fresh and len(m) >= 0.8 * len(F[F["업종코드"].isin(CC.CODES)]):   # 자료가 새것이고 거의 다 맞췄을 때만 '목록에 없음'을 믿음 (받다 만 자료로 잘못 의심하지 않게)
            for fid in ours:
                row = F.loc[fid]
                if row["업종코드"] == "PUB:직장어린이집" or row["대안후보"] == "아니요" or fid in busy: continue   # 직장어린이집은 주민 안내 대상이 아님
                if self.cm.flag(fid, f"정보공개 목록({day})에 없음 · 폐지 여부 확인 필요", source="어린이집정보공개포털")["결과"] == "확인 요청": n["확인 필요"] += 1
        if n["휴업"] or n["다시 안내"] or n["확인 필요"]: self.cm._finish_new(self.cm._update_dirs())
        return n
    def new_public(self):
        """새로 생긴 공공·돌봄 시설 반영 (10/21): 어린이집정보공개포털·유치원알리미 공식 목록에 있는데 우리 시설 목록에 없는 곳(운영 중)을 새 시설로 넣음
        (인허가 자료로는 새로 연 가게가 매일 들어오지만, 어린이집·유치원은 인허가 자료에 없어 공식 목록으로 맞춤) → 대체 시설 안내·공백 해소 판단에 바로 쓰임"""
        import childcare as CC, glob as _g
        E = self.cm.engine(); out = {"어린이집": 0, "유치원": 0}
        nm = lambda x: re.sub(r"\s|\(.*?\)", "", str(x or ""))
        C, day = CC.latest()
        if C is not None and (datetime.date.fromisoformat(today()) - datetime.date.fromisoformat(day)).days <= 7:
            _, _, only = CC.match(E.F, C)
            for i in only:
                r = C.loc[i]
                if str(r.get("crstatusname")) not in ("정상", "재개") or "직장" in str(r.get("crtypename")): continue
                try: lon, lat = float(r["lo"]), float(r["la"])
                except Exception: continue
                up = "가정어린이집" if str(r.get("crtypename")) == "가정" else "어린이집(국공립·민간·법인 등)"
                res = self.cm.add(str(r["crname"]), str(r.get("craddr") or ""), up, lon, lat, phone=str(r.get("crtelno") or ""), date=str(r.get("crcnfmdt") or "")[:10],
                                  source="어린이집정보공개포털", note=f"정보공개 목록({day})에 있으나 시설 목록에 없음 · {r.get('crtypename')}", who="공식 자료")
                if res.get("결과") == "반영": out["어린이집"] += 1
        fs = sorted(_g.glob(os.path.join(self.root, "data", "raw", "kinder", "*.csv")))
        if fs:
            K = pd.read_csv(fs[-1], dtype=str, keep_default_na=False); cur = K["pbnttmng"].max()
            have = {nm(x) for x in E.F[E.F["업종코드"] == "PUB:유치원"]["상호"]}
            for _, r in K[(K["pbnttmng"] == cur) & ~K["kindername"].map(nm).isin(have)].iterrows():
                try: lon, lat = float(r["lngtcdnt"]), float(r["lttdcdnt"])
                except Exception: continue
                res = self.cm.add(str(r["kindername"]), str(r.get("addr") or ""), "유치원(만 3~5세)", lon, lat, phone=str(r.get("telno") or ""), date=str(r.get("odate") or "")[:10],
                                  source="유치원알리미", note=f"정보공시({cur})에 있으나 시설 목록에 없음 · {r.get('establish')}", who="공식 자료")
                if res.get("결과") == "반영": out["유치원"] += 1
        return out
    def practice(self, llm=True):
        """경험 쌓기 (평일 점검 때): 오늘 판단이 애매했던 실제 사례와 아직 판단해 보지 않은 사례를 조금씩 (하루 비용 상한 0.3달러) → 다시 배움"""
        import gap_practice as PR
        if not llm: return dict(self.train(), 연습=0)
        its = []
        for it in self.items():
            try:
                A = self.assess(it)
                if A: its.append(dict(it, 판단재료=A))
            except Exception: pass
        r = PR.daily(self, its, n=20, budget=0.3)
        return dict(self.train(), 연습=r.get("연습", 0))

    # ---------- 날마다 하는 점검 ----------
    def run(self, fetch=True, llm=True, emit=None, fetch_budget=900):
        """오늘 점검을 한 번 돌림. 단계마다 emit({'단계','상태','글'})로 알림. 결과는 runs.jsonl에 남김
        fetch: 인허가 자료를 새로 받을지 (오늘 이미 다 받았으면 받지 않고 넘어감)"""
        if not self.lock.acquire(blocking=False): return {"오류": "이미 점검 중"}
        log = {"시작": now().isoformat(timespec="seconds"), "단계": [], "자료": None}
        def step(name, fn, say):
            t0 = time.time(); s = {"단계": name, "상태": "진행", "글": ""}; log["단계"].append(s); self.live = log
            if emit: emit(dict(s))
            try:
                res = fn(); s.update(상태="완료", 결과=res)
                try: s["글"] = say(res)
                except Exception: s["글"] = ""
            except Exception as ex: s.update(상태="실패", 결과=str(ex)[:300], 글="이 단계를 마치지 못했습니다. 다음 점검 때 다시 합니다"); res = None
            s["초"] = round(time.time() - t0, 1)
            if emit: emit(dict(s))
            return res
        try:
            changed = False
            if fetch:
                got = step("자료 받기", lambda: self.cm.fetch(budget=fetch_budget), lambda r: f"인허가 자료 {r['받음']}개를 받았습니다" if r['받음'] == r['전체'] else f"인허가 자료 {r['전체']}개 가운데 {r['받음']}개를 받았습니다")
                base = self.cm.state.get("인허가_기준")
                if got and got["받음"] == got["전체"]:
                    log["자료"] = "완료"
                    if os.path.relpath(got["폴더"], self.root) != base:
                        res = step("변화 찾기", lambda: self.cm.process_localdata(got["폴더"], llm=llm),
                                   lambda r: "새로 바뀐 곳이 없습니다" if not r["반영"] else ", ".join(f"{k} {v}곳" for k, v in r["종류별"].items()) + "을 반영했습니다")
                        changed = bool(res and res.get("반영"))
                        self._prune()
                    else:
                        log["단계"].append({"단계": "변화 찾기", "상태": "완료", "글": "오늘 자료는 이미 반영했습니다"})
                    rc = step("폐업 여부 확인", lambda: self.cm.recheck(got["폴더"]),
                              lambda r: "바뀐 곳이 없습니다" if not sum(r.values()) else ", ".join(f"{ {'다시 영업으로': '다시 문을 연 곳', '문 닫음으로': '문을 닫은 곳', '확인 필요로': '확인이 필요한 곳'}.get(k, k)} {v}곳" for k, v in r.items() if v) + "을 찾았습니다")
                    changed = changed or bool(rc and sum(rc.values()))
                    cx = step("폐업 여부 교차검증", lambda: self._rc().cross_unsure(),
                              lambda r: "교차검증할 곳이 없습니다" if not sum(r.values()) else ", ".join(f"{ {'폐업 맞음': '폐업 반영', '영업 중': '영업 중 확인', '판단 보류': '판단 보류', '담당자 확인': '운영 미확정 공공시설'}[k]} {v}곳" for k, v in r.items() if v) + "입니다")
                    changed = changed or bool(cx and (cx["폐업 맞음"] or cx["영업 중"]))
                    tr = step("주민 제보 정리", self.tidy_reports, lambda r: "정리할 제보가 없습니다" if not r["다시 안내"] else f"30일이 지나도 폐업 근거가 없는 제보 {r['다시 안내']}건을 다시 안내 대상으로 돌렸습니다")
                    changed = changed or bool(tr and tr["다시 안내"])
                    # 주민 제보 (10/21): 새 제보는 매일 아침 AI가 교차검증해 분명하면 바로 반영. 판단 보류된 제보는 주 1회(월요일) 다시 검토 (engine/report_check.py)
                    full = self._review_due()
                    rv = step("주민 제보 검토" + ("(주간 재검토)" if full else ""), lambda: self.review_reports(only_new=not full),
                              lambda r: ("새 제보가 없습니다" if not full else "검토할 제보가 없습니다") if not sum(r.values()) else f"제보 {sum(r.values())}건을 검토해 폐업 {r['폐업 맞음']}곳을 지도에 반영했습니다. 영업 중인 {r['영업 중']}곳은 다시 주민에게 안내합니다" + (f" (판단 보류 {r['판단 보류']}곳: 다음 주 다시 검토)" if r["판단 보류"] else ""))
                    changed = changed or bool(rv and (rv["폐업 맞음"] or rv["영업 중"]))
                elif got:
                    log["자료"] = "덜 받음"
                    log["단계"].append({"단계": "변화 찾기", "상태": "미룸", "글": "자료를 다 받지 못해 한 시간 뒤 다시 받습니다"})
                ck = step("폐업 시설 분류 점검", lambda: self.cm.closure_check(),   # 새로 확인한 폐업 시설도 상호를 보고 업종·하는 일을 다시 점검 (대신 갈 곳을 바르게 찾도록)
                          lambda r: "새로 점검할 폐업 시설이 없습니다" if not r["점검"] else f"폐업 시설 {r['점검']}곳을 점검해 업종 {r['업종 바꿈']}곳을 바로잡았습니다" + (f", 생활시설이 아닌 곳 {r['생활시설 아님']}곳을 뺐습니다" if r["생활시설 아님"] else ""))
                changed = changed or bool(ck and (ck["업종 바꿈"] or ck["생활시설 아님"]))
                step("폐업 목록 정리", lambda: self._rebuild(changed), lambda r: r)
            else:
                log["단계"].append({"단계": "자료 받기", "상태": "완료", "글": "오늘 자료는 이미 받았습니다"})
            step("공식 자료로 운영 확인", self.official_check, lambda r: f"정보공시가 멈춘 유치원 {r['공시_멈춘_유치원']}곳을 살폈습니다" + (f" (교육청 통폐합·휴원 결정 {r['교육청_결정_반영']}곳 반영)" if r.get("교육청_결정_반영") else "") + (f" (새로 확인할 곳 {r['새_확인요청']}곳)" if r["새_확인요청"] else ""))
            cc = step("어린이집 운영 확인", self.childcare_check, lambda r: "어린이집 공식 자료를 받지 못했습니다" if r.get("자료") == "없음" else
                      f"어린이집 {r['맞춤']}곳을 공식 자료와 맞췄습니다" + "".join(f", {k} {r[k]}곳" for k in ("휴업", "다시 안내", "확인 필요") if r[k]))
            if cc and (cc.get("휴업") or cc.get("다시 안내")): step("폐업 목록 정리", lambda: self._rebuild(True), lambda r: r)
            nw = step("새 공공·돌봄 시설 반영", self.new_public, lambda r: "공식 목록에 새로 생긴 어린이집·유치원이 없습니다" if not sum(r.values()) else f"새로 생긴 어린이집 {r['어린이집']}곳·유치원 {r['유치원']}곳을 시설 목록에 넣었습니다")
            if nw and sum(nw.values()): step("시설 자료 다시 맞춤", lambda: self._rebuild(True), lambda r: r)
            step("기준 다시 계산", self.learn_baseline, lambda r: "주민이 시설까지 다니는 거리를 다시 계산했습니다" + (f" (바뀐 기준: {', '.join(r['바뀐 기준'][:3])})" if r["바뀐 기준"] else ""))
            res = step("영향 분석", lambda: self.analyze_all(emit=emit), lambda r: f"문 닫은 곳 {r['대상']:,}곳을 확인했습니다")
            step("읍·면 하나 남은 곳 살피기", self.rural_watch, lambda r: f"마을에 하나 남은 생활 시설 {len(r['곳'])}곳을 살펴봤습니다")
            step("경험 쌓기·다시 배우기", lambda: self.practice(llm=llm),
                 lambda r: (f"새 사례 {r['연습']}건을 판단·검토했고, " if r.get("연습") else "") + f"경험 {r['경험']:,}건" + (f"과 담당자 판단 {r['담당자_반응']}건" if r.get("담당자_반응") else "") + "으로 다시 배웠습니다" + (f" (시험 정확도 {r['시험_정확도'] * 100:.1f}%" + (f", 직전 대비 {r['전일_대비_퍼센트포인트']:+.1f}%p" if r.get("전일_대비_퍼센트포인트") is not None else "") + ("" if r.get("채택", True) else ", 정확도 하락으로 이전 모델 유지") + ")" if r.get("시험_정확도") else ""))
            step("보고서 작성", lambda: self._sum(self.brief(llm=llm, emit=emit)), lambda r: (f"공백 심각도 긴급 {r['긴급']} · 주의 {r['주의']} · 관찰 {r.get('관찰', 0)}" if r['긴급'] + r['주의'] + r.get('관찰', 0) else "공백 심각도 해당 시설 없음"))
            import self_check as SCK   # (10/26) 자가 점검: 보고서를 만든 뒤 에이전트가 자기 결과를 스스로 확인하고 바로잡음 (engine/self_check.py)
            step("자가 점검", lambda: SCK.run(self), SCK.say)
            log["변화반영"] = changed
        finally:
            log["끝"] = now().isoformat(timespec="seconds"); self.live = None
            self.cm.permits = None; self.cm._permits_dir = None   # 인허가 색인(32만 건)은 점검 때만 씀 → 메모리 돌려줌
            with open(os.path.join(GOV, "runs.jsonl"), "a", encoding="utf-8") as fh: fh.write(json.dumps(log, ensure_ascii=False, default=str) + "\n")
            self.lock.release()
        return log

    @staticmethod
    def _sum(b):
        return {"긴급": sum(v["긴급"] for v in b["구군"].values()), "주의": sum(v["주의"] for v in b["구군"].values()), "관찰": sum(v.get("관찰", 0) for v in b["구군"].values()), "살펴본 공공·복지 폐업": b.get("살펴본_공공복지_폐업", 0),
                "확인 요청": sum(len(v.get("확인요청", [])) for v in b["구군"].values())}

    on_engine = None     # 서버가 넣는 함수: 새 엔진을 주민 화면에도 씀
    on_closures = None   # 서버가 넣는 함수: 폐업 목록을 다시 읽음
    def _rebuild(self, changed):
        """폐업 목록(안내·지도 기간)을 오늘 날짜로 다시 만들고, 새로 반영한 시설이 있으면 엔진도 다시 계산"""
        import subprocess
        r = subprocess.run([sys.executable, "pipeline/build_closures.py"], cwd=self.root, capture_output=True, text=True)
        if r.returncode != 0: raise RuntimeError(r.stderr[-300:])
        if self.on_closures: self.on_closures()
        if changed:
            self.cm._prov = {}; self.cm.engine(reload=True)
            if hasattr(self, "_unsure"): del self._unsure
            if self.on_engine: self.on_engine(self.cm._E)
            return "폐업 목록과 시설 자료를 새로 고쳤습니다"
        return "폐업 목록을 오늘 기준으로 고쳤습니다"

    def _prune(self, keep=2):
        """인허가 자료는 날마다 전체를 받으므로 최근 것만 남김 (디스크 아낌)"""
        import shutil
        ds = sorted(d for d in glob.glob(os.path.join(self.root, "data", "raw", "localdata_updates", "*")) if os.path.isdir(d))
        base = os.path.join(self.root, self.cm.state.get("인허가_기준", ""))
        for d in ds[:-keep]:
            if os.path.abspath(d) != os.path.abspath(base): shutil.rmtree(d, ignore_errors=True)

def report_rules(base):
    """화면에 보여 줄 보고 기준 (engine/severity.py와 같은 값). 기능마다 체감 기준과 대구 주민에게서 배운 기준 가운데 먼 쪽"""
    rows = []
    for lid, (m, who, why) in SV.STD.items():
        b = (base or {}).get(lid) or {}; p95 = b.get("하위5퍼_m")
        lv = "긴급" if (PB.PUBLIC.get(lid) or {}).get("회복") else "주의"
        rows.append({"기능": SV.NAME.get(lid) or b.get("이름") or lid, "등급": lv, "대상": who, "체감기준_m": m, "학습기준_m": p95, "기준_m": max(m, p95 or 0), "까닭": why,
                     "최소인원": SV.ELDER_MIN if who == "65세 이상" else (SV.CHILD_MIN if who in SV.CHILD_WHO else SV.POP_MIN)})
    rows.sort(key=lambda r: (r["등급"] != "긴급", r["기준_m"]))
    rules = [l[2:].strip() for l in GA.principles().splitlines() if l.startswith("- ")]
    return {"거리": rows, "더멀어짐_m": SV.WORSE_M, "돌봄정원": SV.ENROLL_CAP, "돌봄거리_m": SV.ENROLL_NEAR_M, "돌봄기간_일": ENROLL_DAYS, "아이최소": SV.CHILD_MIN, "아이최소_읍면": SV.CHILD_MIN_R, "원칙": rules}

def today_done():
    """오늘 자료를 다 받아 점검을 끝냈는지 (서버 일정이 씀)"""
    p = os.path.join(GOV, "runs.jsonl")
    if not os.path.exists(p): return False
    for line in reversed(open(p, encoding="utf-8").read().strip().splitlines()):
        x = json.loads(line)
        if x["시작"][:10] != today(): return False
        if x.get("자료") == "완료" and not any(s0.get("상태") == "실패" for s0 in x["단계"]): return True
    return False

# 10/25 (헌준님: 지자체 화면 공공기관 용어체) 점검 내역의 단계 이름·결과 글을 개조식으로 (지난 기록도 화면에 낼 때 바꿈)
RUN_STEP = {"자료 받기": "자료 수신", "변화 찾기": "변경 사항 반영", "폐업 여부 확인": "폐업 여부 확인", "폐업 여부 교차검증": "폐업 여부 교차검증",
            "폐업 시설 분류 점검": "폐업 시설 분류 점검", "폐업 목록 정리": "폐업 목록 정리", "공식 자료로 운영 확인": "공식 자료 운영 확인",
            "새 공공·돌봄 시설 반영": "신규 공공·돌봄 시설 반영", "시설 자료 다시 맞춤": "시설 자료 재정비", "기준 다시 계산": "기준 거리 재산정",
            "읍·면 하나 남은 곳 살피기": "읍·면 유일 생활 시설 점검", "경험 쌓기·다시 배우기": "판단 모델 재학습", "판단 모델 다시 배우기": "판단 모델 재학습",
            "주민 제보 정리": "주민 제보 검토", "문 닫음 다시 판정": "폐업 재판정", "우선순위·보고서": "보고서 작성"}
RUN_TEXT = [(re.compile(p_), t_) for p_, t_ in [
    (r"^이 단계를 마치지 못했습니다\.? ?다음 점검 때 다시 합니다\.?$", "미완료 · 다음 점검 시 재수행"),
    (r"^오늘 자료는 이미 .*$", "금일 자료 처리 완료"),
    (r"^인허가 자료 ([\d,/]+)개를 받았습니다$", r"인허가 자료 \1개 수신"),
    (r"^인허가 자료 ([\d,]+)개 가운데 ([\d,]+)개를 받았습니다$", r"인허가 자료 \1개 중 \2개 수신"),
    (r"^자료를 다 받지 못해 한 시간 뒤 다시 받습니다$", "자료 일부 미수신 · 1시간 후 재수신"),
    (r"^(.+)을 반영했습니다$", r"\1 반영"),
    (r"^정보공시가 멈춘 유치원 ([\d,]+)곳을 살폈습니다", r"정보공시 중단 유치원 \1곳 확인"),
    (r"^어린이집 ([\d,]+)곳을 공식 자료와 맞췄습니다", r"어린이집 \1곳 공식 자료 대조"),
    (r"^어린이집 공식 자료를 받지 못했습니다$", "어린이집 공식 자료 미수신"),
    (r"^공식 목록에 새로 생긴 어린이집·유치원이 없습니다$", "신규 어린이집·유치원 없음"),
    (r"^새로 생긴 어린이집 ([\d,]+)곳·유치원 ([\d,]+)곳을 시설 목록에 넣었습니다$", r"신규 어린이집 \1곳·유치원 \2곳 시설 목록 반영"),
    (r"^(대구 )?주민이 (시설까지 다니는 거리|기능별로 얼마나 멀리 다니는지)를? 다시 계산했습니다", "주민 실제 이동 거리 기준 재산정"),
    (r"^문 닫은 곳 ([\d,]+)곳을 (확인했습니다|살펴봤습니다)$", r"폐업 시설 \1곳 영향 분석"),
    (r"^마을에 하나 남은 생활 시설 ([\d,]+)곳을 살펴봤습니다$", r"읍·면 유일 생활 시설 \1곳 점검"),
    (r"^새 사례 ([\d,]+)건을 판단·검토했고, ", r"신규 사례 \1건 판단·검토 · "),
    (r"경험 ([\d,]+)건과 담당자 판단 ([\d,]+)건으로 다시 배웠습니다", r"판단 사례 \1건(담당자 판단 \2건 포함) 재학습"),
    (r"경험 ([\d,]+)건으로 다시 배웠습니다", r"판단 사례 \1건 재학습"),
    (r"담당자 판단 사례 ([\d,]+)건으로 다시 배웠습니다", r"담당자 판단 사례 \1건 재학습"),
    (r"\(시험 정확도", "(검증 정확도"),
    (r"^새로 점검할 폐업 시설이 없습니다$", "신규 점검 대상 폐업 시설 없음"),
    (r"^폐업 시설 ([\d,]+)곳을 점검해 업종 ([\d,]+)곳을 바로잡았습니다", r"폐업 시설 \1곳 점검 · 업종 \2곳 정정"),
    (r", 생활시설이 아닌 곳 ([\d,]+)곳을 뺐습니다", r" · 비생활시설 \1곳 제외"),
    (r"^다시 문을 연 곳 ([\d,]+)곳, 문을 닫은 곳 ([\d,]+)곳을 찾았습니다$", r"재개업 \1곳 · 폐업 \2곳 확인"),
    (r"^확인이 필요한 곳 ([\d,]+)곳을 찾았습니다$", r"확인 필요 \1곳"),
    (r"^(바뀐 곳이 없습니다|바뀐 곳 없음)$", "변경 없음"),
    (r"^폐업 반영 ([\d,]+)곳, 담당자 확인 요청 ([\d,]+)곳입니다$", r"폐업 반영 \1곳 · 담당자 확인 요청 \2곳"),
    (r"^(.+ [\d,]+곳)입니다$", r"\1"),
    (r"^교차검증할 곳이 없습니다$", "교차검증 대상 없음"),
    (r"(담당자 확인 요청|운영 미확정 공공시설) ([\d,]+)곳$", r"운영 미확정 공공시설 \2곳(공백 발생 시설만 확인 요청)"),
    (r"(\d)곳, ", r"\1곳 · "),   # (10/29) 교차검증 보류 공공시설 수가 '폐업 확인 필요 0'과 어긋나 보이던 것
    (r"^(새 제보가 없습니다|정리할 제보가 없습니다|정리할 제보 없음)$", "신규 제보 없음"),
    (r"^보고드릴 일이 없습니다$", "보고 사항 없음"),
    (r"^보고드릴 일이 ([\d,]+)건 있습니다$", r"보고 사항 \1건"),
    (r"^폐업 목록.*(맞췄습니다|고쳤습니다|맞춤)$", "폐업 목록·시설 자료 갱신"),
]]
def run_text(x):
    """점검 기록 한 건의 단계 이름·글을 화면용 개조식으로"""
    if not x: return x
    st = []
    for s in x.get("단계") or []:
        s = dict(s); s["단계"] = RUN_STEP.get(s.get("단계"), s.get("단계"))
        if isinstance(s.get("글"), str):
            g = s["글"]
            for rx, to in RUN_TEXT: g = rx.sub(to, g)
            s["글"] = g
        st.append(s)
    return dict(x, 단계=st)

def last_run():
    p = os.path.join(GOV, "runs.jsonl")
    if not os.path.exists(p): return None
    lines = open(p, encoding="utf-8").read().strip().splitlines()
    x = json.loads(lines[-1]) if lines else None
    d = os.environ.get("GINEUNG_DEMO_REPORT")
    if x and d:   # 영상 시연 서버 전용 (10/24): 점검 시각을 이 시각으로 보이게 (걸린 시간은 그대로)
        try:
            a = datetime.datetime.fromisoformat(x["시작"]); t0 = datetime.datetime.fromisoformat(d).replace(tzinfo=a.tzinfo)
            x = dict(x, 시작=t0.isoformat(timespec="seconds"))
            if x.get("끝"): x["끝"] = (t0 + (datetime.datetime.fromisoformat(x["끝"]) - a)).isoformat(timespec="seconds")
        except Exception: pass
    return run_text(x)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "점검"
    G = GovAgent()
    if cmd == "분석": print(G.analyze_all(budget=float(sys.argv[2]) if len(sys.argv) > 2 else None, emit=print))
    elif cmd == "보고서": b = G.brief(llm="--모델없음" not in sys.argv, emit=print); print(GovAgent._sum(b))
    elif cmd == "점검":
        no_fetch = "--받기없음" in sys.argv; no_llm = "--모델없음" in sys.argv
        log = G.run(fetch=not no_fetch, llm=not no_llm, emit=lambda e: print(json.dumps(e, ensure_ascii=False), flush=True))
