"""대출 적합성 심사의 공용 로직.
작성자 : 원광식

노트북과 Streamlit 앱이 이 모듈 하나를 함께 import한다. 심사 로직·프롬프트를
고칠 일이 생기면 이 파일만 고치면 양쪽에 동일하게 반영된다.

설계 원칙: API 키가 필요 없는 부분(상품 로딩, screen_loan, 규칙기반 파서,
lookup_product)은 이 모듈을 import하는 순간 바로 쓸 수 있어야 한다. Agent/Crew
생성처럼 OPENAI_API_KEY가 필요한 부분은 parse_with_llm()/generate_guidance() 호출 시점에만
지연 생성한다 — import만으로 키 오류가 나면 안 되기 때문이다(노트북 self-test는
키 없이 동작해야 함).
"""
import os
import re
import json
from pathlib import Path

from dotenv import load_dotenv

# 이 파일(core.py)의 상위 폴더가 프로젝트 루트(CSV·.env 위치). cwd에 의존하지 않는다.
BASE_DIR = Path(__file__).resolve().parent.parent
# 데이터 파일명을 한글('대출상품.csv') → 영문('loan_products.csv')으로 변경.
#   저장소를 공개했을 때 파일명 인코딩 문제를 피하고 국제적으로 통용되도록 함.
#   (CSV의 컬럼/내용은 한글 그대로 유지 — 도메인 데이터이므로.)
CSV_PATH = BASE_DIR / "loan_products.csv"

load_dotenv(BASE_DIR / ".env", override=True)

# 교육용 디스클레이머(모든 안내문에 필수 포함 — 규제 통제)
DISCLAIMER = (
    "본 안내는 교육용 데모이며 실제 대출 심사·법적·금융 자문이 아닙니다. "
    "실제 대출은 각 금융기관 심사를 따릅니다."
)

# ADR-022가 정한 설명 실행 상한의 단일 정의다. 동기 요청·워커·화면이 같은 실행을
# 서로 다른 값으로 끊으면 상태 전이와 사용자 경험이 갈라진다.
EXPLANATION_RUN_TIMEOUT_SECONDS = 200


# ---------------------------------------------------------------------------
# 상품 로딩 (API 키 불필요)
# ---------------------------------------------------------------------------
def _pct(s: str) -> float:
    """'4.5%' -> 4.5"""
    return float(str(s).replace("%", "").strip())


def _grade(s: str) -> int:
    """'3등급이상' -> 3 / '3등급' -> 3 (숫자가 낮을수록 우량)"""
    m = re.search(r"(\d+)", str(s))
    return int(m.group(1)) if m else 99


def load_products(csv_path: Path = CSV_PATH) -> list:
    """대출상품.csv를 파싱해 구조화 리스트로 반환. pandas 없이 동작."""
    products = []
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    header = [h.strip() for h in lines[0].split(",")]
    for line in lines[1:]:
        cols = [c.strip() for c in line.split(",")]
        row = dict(zip(header, cols))
        products.append({
            "상품코드": row["상품코드"],
            "상품명": row["상품명"],
            "은행": row["은행"],
            "최저금리": _pct(row["최저금리"]),
            "최고금리": _pct(row["최고금리"]),
            "최대한도": int(row["최대한도"]),          # 원
            "필요신용등급": _grade(row["필요신용등급"]),  # 이 값 이하(우량)면 충족
            "담보필요": row["담보필요"] == "필요",
            "직장조건": row["직장조건"],                # '정규직' | '제한없음'
            # 금융감독원 「금융상품 한눈에」 공시가 실제로 노출하는 필드를 합성값으로 추가한다
            #   (상환방식·금리방식·중도상환수수료). 최저금리 단일 기준을 넘어선 다기준 상품 랭킹
            #   (§docs 기술부채_보안_개선계획 C-2)을 시연하기 위한 데이터다.
            #   기존 CSV에 이 컬럼이 없을 수도 있으므로 .get으로 안전하게 읽고 기본값을 둔다.
            "상환방식": row.get("상환방식", "원리금균등"),   # '원리금균등' | '만기일시'
            "금리방식": row.get("금리방식", "변동"),         # '고정' | '변동'
            "중도상환수수료": _pct(row.get("중도상환수수료", "0%")),  # % (낮을수록 유리)
        })
    return products


PRODUCTS = load_products()


# ---------------------------------------------------------------------------
# 상환능력 지표를 간이 DTI → 실제 DSR로 교체하기 위한 가정값·헬퍼.
#   배경: 예전 지표(DTI = 기존부채잔액 ÷ 연소득)는 이번에 신청하는 희망금액의 상환부담을
#         전혀 반영하지 못해, 기존 부채가 0이면 아무리 큰 금액을 신청해도 항상 "여유"로 나왔다.
#   변경: 금융위 실제 정의(DSR = 연간 원리금상환액 ÷ 연소득)를 따라, 기존부채와 신규 희망금액을
#         모두 '원리금균등상환(annuity)'으로 월상환액을 산출해 합산한다.
#   가정: 상환능력 판정을 상품과 독립적으로 유지하기 위해 '대표 고정금리·고정기간'을 쓴다
#         (사용자와 합의한 방식). 실제 서비스라면 상품별 실제 금리를 적용하도록 확장할 수 있다.
#   남은 단순화(정직하게 명시): 대표금리·기간은 고정 가정이며 개별 상품 금리를 반영하지 않는다.
ASSUMED_ANNUAL_RATE = 0.06   # 연 6% — DSR 산정용 대표 가정금리
ASSUMED_TERM_MONTHS = 60     # 60개월(5년) — DSR 산정용 대표 가정기간


def monthly_payment(principal: float, annual_rate: float = ASSUMED_ANNUAL_RATE,
                    months: int = ASSUMED_TERM_MONTHS) -> float:
    """원리금균등상환(annuity) 공식으로 월상환액을 계산한다.
    M = P·r(1+r)^n / ((1+r)^n − 1)   (P=원금, r=월금리, n=개월수)
    원금이 0이면 0, 금리가 0이면 단순 분할(P/n)로 처리한다."""
    if principal <= 0:
        return 0.0
    r = annual_rate / 12
    if r == 0:
        return principal / months
    factor = (r * (1 + r) ** months) / ((1 + r) ** months - 1)
    return principal * factor


# ---------------------------------------------------------------------------
# 결정적 적합성 심사 로직 (API 키 불필요 · 핵심 안전장치)
# ---------------------------------------------------------------------------
def screen_loan(customer: dict, products: list = None) -> dict:
    """고객 구조화 정보를 CSV 하드규칙으로 심사해 결정적 판정을 반환한다.
    customer 필드(원 단위 금액): 월소득, 부채, 신용등급, 희망금액, 직장유형, (선택)담보보유

    상환능력 지표(DSR): 금융위 실제 정의인 DSR(= 연간 원리금상환액 ÷ 연소득)을 사용한다.
    기존부채와 이번 희망금액을 모두 원리금균등상환으로 월상환액을 산출해 합산하므로, 예전
    간이 DTI와 달리 '이번에 신청하는 금액의 상환부담'까지 반영된다.
    판정 밴드: DSR ≤ 0.30 여유 / ≤ 0.40 보통 / > 0.40 부족.
      (0.40은 은행권 실제 DSR 규제 상한을 데모에 반영한 값이다.)
    남은 단순화: 대표 고정금리(ASSUMED_ANNUAL_RATE)·고정기간(ASSUMED_TERM_MONTHS)을 가정하며
    개별 상품의 실제 금리는 반영하지 않는다."""
    if products is None:
        products = PRODUCTS

    월소득 = max(int(customer.get("월소득", 0)), 0)
    부채 = max(int(customer.get("부채", 0)), 0)
    신용등급 = int(customer.get("신용등급", 99))
    희망금액 = max(int(customer.get("희망금액", 0)), 0)
    직장유형 = str(customer.get("직장유형", "제한없음")).strip()
    담보보유 = bool(customer.get("담보보유", False))  # 미기재 시 미보유로 간주

    # (2) 상환능력(DSR)
    #   기존부채·신규 희망금액을 각각 원리금균등상환으로 월상환액을 산출해 합산 → 연환산 → 연소득 대비.
    연소득 = 월소득 * 12
    기존부채_월상환 = monthly_payment(부채)
    신규대출_월상환 = monthly_payment(희망금액)  # 예전엔 누락됐던 '이번 신청분'의 상환부담
    연간_원리금 = (기존부채_월상환 + 신규대출_월상환) * 12
    dsr = (연간_원리금 / 연소득) if 연소득 > 0 else float("inf")
    if dsr <= 0.30:
        상환 = "여유"
    elif dsr <= 0.40:      # 0.40 = 은행권 실제 DSR 규제 상한을 반영
        상환 = "보통"
    else:
        상환 = "부족"

    # (1) 적격 상품 선별 (하드규칙)
    적격, 사유_by_product = [], {}
    for p in products:
        실패 = []
        if 신용등급 > p["필요신용등급"]:
            실패.append(f"신용등급 미달(필요 {p['필요신용등급']}등급 이상, 현재 {신용등급}등급)")
        if p["담보필요"] and not 담보보유:
            실패.append("담보 필요(미보유)")
        if p["직장조건"] == "정규직" and 직장유형 != "정규직":
            실패.append(f"직장조건 미충족(정규직 필요, 현재 {직장유형})")
        if 희망금액 > p["최대한도"]:
            실패.append(f"희망금액 초과(한도 {p['최대한도']:,}원)")
        사유_by_product[f"{p['상품코드']} {p['상품명']}({p['은행']})"] = 실패
        if not 실패:
            적격.append(p)

    # (3) 최종 판정
    if not 적격 or 상환 == "부족":
        판정 = "어려움"
    elif 상환 == "여유":
        판정 = "승인가능"
    else:
        판정 = "상담필요"

    # 예전엔 적격 상품을 '최저금리' 단일 기준으로만 골랐다.
    #   금융권 실무는 소비자 총부담·승인 가능성·중도상환 부담을 함께 본다(§docs C-2).
    #   여기서는 결정성을 위해 아래 3단 정렬키를 쓴다(모두 작을수록 우선):
    #     (1) 최저금리        — 소비자 총부담(예상 적용금리)의 프록시, 주축
    #     (2) -(승인여유마진)  — 승인여유 = 필요신용등급 - 고객신용등급(클수록 안전) → 음수로 desc
    #     (3) 중도상환수수료   — 낮을수록 유리
    def _rank_key(p):
        승인여유 = p["필요신용등급"] - 신용등급
        return (p["최저금리"], -승인여유, p["중도상환수수료"])

    def _brief(p):
        return {"상품코드": p["상품코드"], "상품명": p["상품명"], "은행": p["은행"],
                "금리범위": f"{p['최저금리']}%~{p['최고금리']}%", "최대한도": p["최대한도"],
                "상환방식": p["상환방식"], "금리방식": p["금리방식"],
                "중도상환수수료": p["중도상환수수료"], "승인여유마진": p["필요신용등급"] - 신용등급}

    추천 = None
    추천후보 = []
    if 적격 and 판정 != "어려움":
        순위 = sorted(적격, key=_rank_key)
        추천후보 = [_brief(p) for p in 순위[:3]]  # 상위 3개 랭킹(시연·비교용)
        추천 = 추천후보[0]                          # 최종 추천 = 랭킹 1위

    return {
        "판정": 판정, "상환능력": 상환,
        # 지표를 DTI→DSR로 교체했다. 안내문·UI에서 상환부담 근거로 쓰도록
        #   월상환액 내역(기존/신규)과 가정값(금리·기간)도 함께 노출한다.
        "DSR": round(dsr, 3) if dsr != float("inf") else None,
        "월상환액": {
            "기존부채": round(기존부채_월상환),
            "신규대출": round(신규대출_월상환),
            "합계": round(기존부채_월상환 + 신규대출_월상환),
            "가정": {"연금리": ASSUMED_ANNUAL_RATE, "기간개월": ASSUMED_TERM_MONTHS},
        },
        "적격상품": [{"상품코드": p["상품코드"], "상품명": p["상품명"], "은행": p["은행"]} for p in 적격],
        "부적격사유": {k: v for k, v in 사유_by_product.items() if v},
        "추천상품": 추천,
        # 상위 3개 랭킹(비교·시연용). 안내문/UI에서 대안 상품 비교에 쓸 수 있다.
        "추천후보": 추천후보,
        "입력요약": {"월소득": 월소득, "부채": 부채, "신용등급": 신용등급,
                    "희망금액": 희망금액, "직장유형": 직장유형, "담보보유": 담보보유},
    }


# ---------------------------------------------------------------------------
# 자연어 -> 구조화 파싱 (규칙 기반 폴백, API 키 불필요)
# ---------------------------------------------------------------------------
def parse_korean_amount(text: str, keywords: list, gap: int = 6):
    """키워드<->숫자가 서로 가까이 있으면(양방향 ±gap자 이내) '○○만원/○○원'을 원 단위 정수로 추출.
    '월급 700만원'처럼 키워드가 먼저 오는 경우와 '3000만원 대출받고'처럼 숫자가 먼저 오는 경우를 모두 잡는다."""
    for kw in keywords:
        # 방향 1: 키워드 -> 숫자 (예: '월급 700만원', '부채 3000만원')
        # 숫자 그룹은 반드시 숫자로 시작해야 함(\d[\d,]*) — 콤마 하나만 있는 문장부호를
        # 숫자로 잘못 매칭하는 것을 방지(예: '대출받고 싶은데, 집을' 의 ',').
        m = re.search(rf"{kw}[^\d]{{0,{gap}}}(\d[\d,]*)\s*(만원|만|원)?", text)
        if m:
            num = int(m.group(1).replace(",", ""))
            unit = m.group(2) or "만원"
            return num * 10000 if unit.startswith("만") else num
        # 방향 2: 숫자 -> 키워드 (예: '3000만원 대출받고', '1000만원 빌리고')
        m = re.search(rf"(\d[\d,]*)\s*(만원|만|원)?[^\d]{{0,{gap}}}{kw}", text)
        if m:
            num = int(m.group(1).replace(",", ""))
            unit = m.group(2) or "만원"
            return num * 10000 if unit.startswith("만") else num
    return None


def rule_based_parse(text: str) -> dict:
    """규칙 기반 파서 — Agent 1(LLM) 산출 검증 및 오프라인 테스트용."""
    월소득 = parse_korean_amount(text, ["월급", "월소득", "소득", "월"]) or 0
    부채 = parse_korean_amount(text, ["부채", "빚", "대출.?있"]) or 0
    if re.search(r"부채\D{0,6}(없|0)", text):
        부채 = 0
    희망금액 = parse_korean_amount(text, ["희망", "대출받", "빌리", "받고"]) or 0
    g = re.search(r"신용\s*등급\s*(\d+)|(\d+)\s*등급", text)
    신용등급 = int(next(x for x in (g.group(1), g.group(2)) if x)) if g else 99
    직장유형 = "정규직" if "정규직" in text else ("계약직" if "계약직" in text else "제한없음")
    담보긍정 = re.search(r"담보\D{0,6}(있|보유|제공)", text)
    담보부정 = re.search(r"담보\D{0,6}(없|불가)", text)
    담보보유 = bool(담보긍정) and not bool(담보부정)
    return {"월소득": 월소득, "부채": 부채, "신용등급": 신용등급,
            "희망금액": 희망금액, "직장유형": 직장유형, "담보보유": 담보보유}


# ---------------------------------------------------------------------------
# 필수 입력 검증 (API 키 불필요)
# ---------------------------------------------------------------------------
# 사용자가 필수 정보를 입력하지 않을 때의 에러처리 대책.
#   예전엔 소득·신용등급 등이 빠지면 Agent가 sentinel 기본값(월소득 0, 신용등급 99 등)으로
#   채워 screen_loan이 그대로 '어려움'을 내버려, '정보 부족'을 '거절'로 오판했다.
#   → 아래 필수필드 검증으로 심사 전에 걸러 사용자에게 재입력을 안내한다(app.py에서 사용).
# 심사에 반드시 필요한 필드와, "미입력"을 뜻하는 sentinel 기본값.
#   - 부채는 '없음=0'이 정상 입력이라 필수에서 제외한다.
#   - 직장유형('제한없음')·담보보유(False)는 합리적 기본값이 있어 선택 항목이다.
REQUIRED_FIELDS = {
    "월소득": ("월 소득", lambda v: not isinstance(v, (int, float)) or v <= 0),
    "신용등급": ("신용등급", lambda v: not isinstance(v, (int, float)) or v <= 0 or v >= 99),
    "희망금액": ("희망 대출금액", lambda v: not isinstance(v, (int, float)) or v <= 0),
}


def missing_required_fields(parsed: dict) -> list:
    """파싱 결과에서 값이 없거나 sentinel(미입력) 기본값인 필수 필드의 '한글 라벨' 목록을 반환한다.
    비어 있으면([]) 필수 정보가 모두 채워진 것이다. screen_loan을 돌리기 전에 이걸로 걸러,
    정보 부족을 '어려움'으로 오판하지 않게 한다."""
    if not isinstance(parsed, dict):
        return [label for label, _ in REQUIRED_FIELDS.values()]
    missing = []
    for key, (label, is_missing) in REQUIRED_FIELDS.items():
        if key not in parsed or is_missing(parsed.get(key)):
            missing.append(label)
    return missing


# ---------------------------------------------------------------------------
# 테스트 케이스 3종(기획서 데모) + 엣지케이스 2종(담보/계약직) — 노트북·앱 공용
# ---------------------------------------------------------------------------
TEST_CASES = [
    {"name": "승인 케이스",
     "input": "월급 700만원 받는 정규직이고 부채는 없습니다. 신용등급 1등급이고 3000만원 대출받고 싶어요.",
     "expected": "승인가능"},
    # DSR 고도화에 맞춰 이 케이스 입력을 조정했다. 기존 입력(월280·부채1500·희망2000)은 옛 간이 DTI에선
    #   '보통(상담필요)'이었지만, 이번 신청분까지 반영하는 새 DSR에선 상환부담이 실제로는 여유(≈24%)로 나온다
    #   (옛 지표가 과대평가했던 것). 데모가 '보통(30~40%)' 구간을 계속 보여주도록, 새 DSR 기준으로 실제
    #   보통 구간(≈35%)에 드는 시나리오로 교체한다.
    {"name": "상담필요 케이스",
     "input": "월소득 250만원이고 부채가 2000만원 있어요. 신용등급 4등급, 2500만원 대출 희망합니다.",
     "expected": "상담필요"},
    {"name": "어려움 케이스",
     "input": "월급 180만원이고 부채 3000만원 있습니다. 신용등급 6등급, 1000만원 빌리고 싶어요.",
     "expected": "어려움"},
]

# 엣지케이스(담보 저신용·계약직 소액)를 정의만 하지 않고 노트북 자체테스트·LLM 파이프라인에서
#           실제 실행해 증거를 남긴다(노트북 셀 6-1·14-3 참고). 담보·직장조건 하드규칙을 검증하는 자랑거리.
EDGE_CASES = [
    {"name": "담보 보유 저신용 케이스",
     "input": "월소득 300만원이고 부채는 500만원 있어요. 신용등급 8등급이고 800만원 대출받고 싶은데, "
              "집을 담보로 제공할 수 있습니다.",
     "expected": "승인가능"},
    {"name": "계약직 소액 케이스",
     "input": "월급 150만원 받는 계약직이고 부채 200만원 있습니다. 신용등급 6등급이고 500만원 빌리고 싶어요.",
     "expected": "승인가능"},
]


# ---------------------------------------------------------------------------
# 사전 녹화된 데모 결과 로더.
#   공개 배포 시 방문자가 자기 OPENAI_API_KEY 없이도 '입력 → 실제 3-Agent 출력'을
#   토큰 소모 0으로 열람할 수 있도록, 미리 1회 실행해 구운 결과(demo_fixtures.json)를 읽는다.
#   (파일 생성 스크립트: 저장소 외부에서 owner 키로 1회 실행 → 결과만 커밋)
# ---------------------------------------------------------------------------
DEMO_FIXTURES_PATH = Path(__file__).resolve().parent / "demo_fixtures.json"


def load_demo_fixtures() -> dict:
    """사전 녹화된 데모 결과를 로드한다(키·토큰 불필요). 파일이 없으면 빈 구조를 반환."""
    if not DEMO_FIXTURES_PATH.exists():
        return {"cases": [], "generated_at": None, "model": None}
    return json.loads(DEMO_FIXTURES_PATH.read_text(encoding="utf-8"))


def run_logic_selftest(cases: list = None) -> bool:
    """API 키 없이 결정적 심사 로직만 검증(R5 핵심). 전체 일치 시 True."""
    cases = cases if cases is not None else TEST_CASES
    print("=" * 60, "\n결정적 심사 로직 자체 테스트 (API 키 불필요)\n" + "=" * 60)
    all_pass = True
    for tc in cases:
        parsed = rule_based_parse(tc["input"])
        result = screen_loan(parsed)
        ok = result["판정"] == tc["expected"]
        all_pass = all_pass and ok
        print(f"\n[{tc['name']}] {'✅' if ok else '❌'}")
        print(f"  파싱 : {parsed}")
        print(f"  기대 : {tc['expected']} / 판정: {result['판정']} (상환 {result['상환능력']}, DSR {result['DSR']})")
        print(f"  적격 : {result['적격상품']}")
    print("\n" + "=" * 60)
    print(f"결과: {'전체 통과 (' + str(len(cases)) + '/' + str(len(cases)) + ')' if all_pass else '실패 — 로직 수정 필요'}")
    print("=" * 60)
    return all_pass
