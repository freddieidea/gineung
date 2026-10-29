# 지자체 업무 보조 대화 학습 문장 만들기 (언어 모델로 다양한 담당자 말을 지어냄, 비용 듦). 사용: python engine/gov_chat_gen.py 묶음번호
#  주민 대화 때처럼: 담당자의 업무(의도) × 말투(공손·반말·짧은 말·오타·불친절) × 맥락(이어 묻기·지시어)을 섞어, 실제 자료(구·동·시설 이름)를 넣은 대화를 만듦
#  만든 대화는 data/gov/chat_train.jsonl에 쌓고, gov_chat_train.py가 돌려 보고 채점함
import os, sys, json, random, re
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline")]
import anthropic, gov_docs as D
from chat import log_usage, SONNET
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
b = D.load(); R = D.rows(b)
random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
names = [r["상호"] for r in random.sample(R["검토완료"], min(12, len(R["검토완료"])))] + [r["상호"] for r in R["단절우려"][:8]]
dongs = sorted({r["행정동"] for r in R["공백구역"]} | {r.get("행정동") for r in R["검토완료"] if r.get("행정동")})
INTENTS = ["오늘 상황·건수 파악", "특정 구·동의 공백 현황", "특정 시설의 판단 근거·대체 시설", "판단에 이의 제기·바로잡기 요청", "폐업 확인 처리(폐업·휴원·운영 중)", "처리 완료 등록",
           "앞으로의 판단 원칙 주기", "보고서·요약·엑셀 등 문서 요청", "소관 부서·관계 기관·조치 방법 문의", "입지 후보·개설 효과 등 정책 검토", "어떤 기능이 걸어서 가기 힘든 동네",
           "용어·기준·안내 기간·자료 신뢰성 질문", "주민 상담 기반 수요(주민이 찾았지만 없던 시설)", "단절 우려(문 닫으면 대신 갈 곳 없는 영업 중 시설)와 폐업 사전 검토",
           "업무 밖 부탁이나 없는 자료(예산·작년 통계·개인 연락처)", "복합 질문(두 가지를 한 번에)", "화면 조작(구 바꾸기·칸 열기·위치 보기)"]
STYLES = ["공손한 존댓말", "짧은 반말", "업무 메모처럼 명사형 몇 단어", "오타·띄어쓰기 틀림", "불친절하고 급한 말투", "길고 장황한 설명", "행정 용어를 섞은 말", "서비스 용어를 모르는 사람의 말"]
SYS = "당신은 대구광역시 구·군청에서 일하는 다양한 공무원(복지·보건·보육·경제·민원 담당, 팀장·주무관·신규 직원)을 흉내 내어, 생활시설 공백 관리 AI 비서에게 실제로 할 법한 말을 만드는 역할입니다. 한국어 구어체로, 사람마다 말버릇이 다르게 만듭니다."
def make(k=12):
    picks = [(random.choice(INTENTS), random.choice(STYLES), random.choice([1, 2, 2, 3, 3, 4])) for _ in range(k)]
    ask = ("아래 조건마다 담당자가 AI 비서에게 하는 대화(담당자 말만)를 하나씩 만드십시오. 턴 수만큼 이어지는 말을 만들고, 두 번째 말부터는 앞 대답을 받아 '여기·그거·그중·거기' 같은 지시어나 짧은 말로 이어 가게 하십시오(앞 대답은 쓰지 말고 담당자 말만).\n"
           f"쓸 수 있는 실제 이름: 구·군 {', '.join(D.GUS)} / 동 {', '.join(random.sample(dongs, min(25, len(dongs))))} / 시설 {', '.join(names)} / 기능 예: 약국, 동네 의원, 어린이집, 유치원, 경로당, 지역아동센터, 슈퍼, 전통시장, 무인민원발급기, 요양원, 분만 병원\n"
           "조건 목록:\n" + "\n".join(f"{i + 1}. 의도: {a} / 말투: {s} / 턴: {n}" for i, (a, s, n) in enumerate(picks)) +
           "\n\n출력: JSON 배열만. 각 원소는 {\"의도\": ..., \"말투\": ..., \"turns\": [\"담당자 말1\", ...]}")
    c = anthropic.Anthropic(api_key=open(os.path.join(ROOT, "settings", "anthropic_key.txt"), encoding="utf-8").read().strip())
    r = c.messages.create(model=SONNET, max_tokens=6000, system=SYS, messages=[{"role": "user", "content": ask}])
    log_usage(SONNET, r.usage, "업무보조시험")
    t = "".join(x.text for x in r.content if getattr(x, "type", "") == "text")
    m = re.search(r"\[.*\]", t, re.S)
    return json.loads(m.group(0)) if m else []
if __name__ == "__main__":
    convs = make(int(sys.argv[2]) if len(sys.argv) > 2 else 12)
    p = os.path.join(ROOT, "data", "gov", "chat_train.jsonl")
    with open(p, "a", encoding="utf-8") as fh:
        for c_ in convs: fh.write(json.dumps(dict(c_, 묶음=int(sys.argv[1]) if len(sys.argv) > 1 else 0), ensure_ascii=False) + "\n")
    print(len(convs)); [print(c_["의도"], "|", c_["말투"], "|", " → ".join(c_["turns"])) for c_ in convs]
