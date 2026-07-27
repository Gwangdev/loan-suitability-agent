"""대출 적합성 심사 3-Agent 파이프라인의 공용 로직.
작성자 : 원광식

노트북과 Streamlit 앱이 이 모듈 하나를 함께 import한다. 심사 로직·프롬프트를
고칠 일이 생기면 이 파일만 고치면 양쪽에 동일하게 반영된다.

설계 원칙: API 키가 필요 없는 부분(상품 로딩, screen_loan, 규칙기반 파서,
lookup_product)은 이 모듈을 import하는 순간 바로 쓸 수 있어야 한다. Agent/Crew
생성처럼 OPENAI_API_KEY가 필요한 부분은 get_crew()/run_service() 호출 시점에만
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
# [포트폴리오 정리] 데이터 파일명을 한글('대출상품.csv') → 영문('loan_products.csv')으로 변경.
#   저장소를 공개했을 때 파일명 인코딩 문제를 피하고 국제적으로 통용되도록 함.
#   (CSV의 컬럼/내용은 한글 그대로 유지 — 도메인 데이터이므로.)
CSV_PATH = BASE_DIR / "loan_products.csv"

load_dotenv(BASE_DIR / ".env", override=True)

# 교육용 디스클레이머(모든 안내문에 필수 포함 — 규제 통제)
DISCLAIMER = (
    "본 안내는 교육용 데모이며 실제 대출 심사·법적·금융 자문이 아닙니다. "
    "실제 대출은 각 금융기관 심사를 따릅니다."
)


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
        })
    return products


PRODUCTS = load_products()


# ---------------------------------------------------------------------------
# [디벨롭: DSR 고도화] 상환능력 지표를 간이 DTI → 실제 DSR로 교체하기 위한 가정값·헬퍼.
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

    # (2) 상환능력(DSR)  [디벨롭: DSR 고도화]
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

    # 적격 상품 중 최저금리 우선 추천
    추천 = None
    if 적격 and 판정 != "어려움":
        best = min(적격, key=lambda p: p["최저금리"])
        추천 = {"상품코드": best["상품코드"], "상품명": best["상품명"], "은행": best["은행"],
                "금리범위": f"{best['최저금리']}%~{best['최고금리']}%", "최대한도": best["최대한도"]}

    return {
        "판정": 판정, "상환능력": 상환,
        # [디벨롭: DSR 고도화] 지표를 DTI→DSR로 교체. 안내문·UI에서 상환부담 근거로 쓰도록
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
# [타팀 피드백-2] 사용자가 필수 정보를 입력하지 않을 때의 에러처리 대책.
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
    # [디벨롭: DSR 고도화] 이 케이스 입력을 조정했다. 기존 입력(월280·부채1500·희망2000)은 옛 간이 DTI에선
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

# [피드백③] 엣지케이스(담보 저신용·계약직 소액)를 정의만 하지 않고 노트북 자체테스트·LLM 파이프라인에서
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


# ---------------------------------------------------------------------------
# 상품코드 조회 도구 (API 키 불필요 — crewai @tool 데코레이터만 사용)
# ---------------------------------------------------------------------------
from crewai.tools import tool  # noqa: E402  (지연 없이 바로 써도 되는 가벼운 임포트)


@tool("lookup_loan_product")
def lookup_product(조회어: str) -> str:
    """상품코드 또는 은행명·상품명으로 대출상품을 조회한다.
    1) 상품코드(예: 'A-01') 정확 일치를 최우선으로 찾는다.
    2) 실패하면 '은행명+상품명' 정확 일치(공백 무시)를 시도한다(LLM이 코드를 모를 때 대비).
    3) 그래도 실패하면 상품명 부분 일치 후보를 찾되, 여러 개면 후보 전체를 리스트로 반환해
       모호함을 그대로 드러낸다(같은 이름이 여러 은행에 있을 때 첫 번째만 조용히 반환하지 않음).
    CSV 외 값은 반환하지 않는다."""
    q = 조회어.strip()

    # 1) 상품코드 정확 일치
    for p in PRODUCTS:
        if p["상품코드"] == q:
            return json.dumps(p, ensure_ascii=False)

    # 2) 은행명+상품명 정확 일치 (공백 무시)
    q_norm = q.replace(" ", "")
    for p in PRODUCTS:
        combo1 = (p["은행"] + p["상품명"]).replace(" ", "")
        combo2 = (p["상품명"] + p["은행"]).replace(" ", "")
        if q_norm in (combo1, combo2):
            return json.dumps(p, ensure_ascii=False)

    # 3) 상품명 부분 일치 — 후보가 하나면 반환, 여럿이면 전체 후보를 노출
    candidates = [p for p in PRODUCTS if p["상품명"] in q or q in p["상품명"]]
    if len(candidates) == 1:
        return json.dumps(candidates[0], ensure_ascii=False)
    if len(candidates) > 1:
        return json.dumps({
            "안내": f"'{q}'과(와) 이름이 유사한 후보가 여러 은행에 있습니다. 상품코드로 다시 조회하세요.",
            "후보목록": candidates,
        }, ensure_ascii=False)

    return (f"'{q}'은(는) 상품 목록에 없습니다. "
            f"상품코드 목록: {[p['상품코드'] + ' ' + p['상품명'] + '(' + p['은행'] + ')' for p in PRODUCTS]}")


@tool("assess_loan_eligibility")
def screen_tool(고객정보_json: str) -> str:
    """고객 필드(월소득·부채·신용등급·희망금액·직장유형, 원 단위, 선택적으로 담보보유) JSON을 받아
    CSV 하드규칙으로 결정적 판정(승인가능/상담필요/어려움)을 반환한다. 이 판정을 최종으로 따른다.
    적격상품·추천상품에는 상품코드가 함께 포함되므로, 같은 이름의 상품이 여러 은행에 있어도
    상품코드로 구분해서 안내해야 한다."""
    try:
        customer = json.loads(고객정보_json)
    except Exception as e:
        return f"입력 JSON 파싱 실패: {e}"
    return json.dumps(screen_loan(customer), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Agent / Task / Crew (API 키 필요 — get_crew() 호출 시점까지 생성을 미룬다)
# ---------------------------------------------------------------------------
def get_llm():
    """OPENAI_API_KEY가 없으면 즉시 명확한 ValueError로 중단."""
    from crewai import LLM

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY를 찾을 수 없습니다. 프로젝트 폴더의 .env 파일에 "
            "OPENAI_API_KEY를 설정하세요. (.env.example 참고)"
        )
    model_name = os.getenv("OPENAI_MODEL_NAME", "openai/gpt-4o-mini")
    return LLM(model=model_name, api_key=api_key, temperature=0.2), model_name


def build_parser_agent(llm):
    """Agent 1 — 정보 파싱가."""
    from crewai import Agent

    return Agent(
        role="정보 파싱가",
        goal="고객 자연어 입력에서 월소득·부채·신용등급·희망금액·직장유형·담보보유 6개 필드를 정확히 추출해 원 단위 JSON으로 구조화한다.",
        backstory=(
            "당신은 고객의 자연어를 구조화 데이터로 바꾸는 전문가입니다. "
            "금액은 모두 원 단위 정수로 환산합니다(예: 700만원 -> 7000000). "
            "명시되지 않은 값은 추측하지 말고 0 또는 '제한없음'으로 둡니다. "
            "담보보유는 고객이 담보(예: 집, 부동산)를 제공할 수 있다고 명시한 경우에만 true, "
            "언급이 없거나 없다고 하면 false로 둡니다. "
            "입력에 없는 정보를 지어내지 않습니다."
        ),
        llm=llm, allow_delegation=False, verbose=True,
    )


def build_reviewer_agent(llm):
    """Agent 2 — 심사 판단가 (CoT + Self-Consistency)."""
    from crewai import Agent

    return Agent(
        role="심사 판단가",
        goal="assess_loan_eligibility 도구의 결정적 판정을 최우선으로 따르되, 상환능력을 CoT 4단계로 설명하고 후보를 교차검증(SC)한다.",
        backstory=(
            "당신은 대출 상환능력을 단계적으로 추론하는 심사역입니다. "
            "반드시 'assess_loan_eligibility' 도구를 호출해 CSV 규정 기준 판정을 받고, 그 판정(승인가능/상담필요/어려움)을 최종 결론으로 삼습니다. "
            "그 위에서 CoT로 (1)DSR 상환능력(연간 원리금상환액÷연소득) (2)신용등급 조건 (3)희망금액 대비 한도 (4)적합상품 선별을 단계적으로 설명하고, "
            "Self-Consistency 관점(보수적·낙관적·중립)으로 교차검증해 일관된 근거를 제시합니다. "
            "단, 이 SC는 동일 질문을 여러 번 독립 추론해 다수결로 답을 정하는 엄밀한 의미의 Self-Consistency가 아니라, "
            "한 번의 응답 안에서 세 관점을 서술해 근거 설명을 다각도로 검증하는 응용임을 유념하고, "
            "최종 판정은 이 SC가 아니라 도구의 결정적 판정을 그대로 따른다는 점을 답변에서 분명히 합니다. "
            "도구가 준 적격/부적격 사유와 어긋나는 수치나 상품을 만들지 않습니다. "
            # [피드백①] 결정적 추천상품을 항상 최종으로 고정: 예전엔 Agent가 안내 단계에서 다른 상품을
            #           골라(예: 승인 케이스에서 A-02 누락하고 A-01·B-01 추천) '결정적 로직이 최종'이라는
            #           설계가 샜음. 도구의 '추천상품' 필드를 그대로 최종 추천으로 넘기도록 못박음.
            "도구 결과의 '추천상품' 필드는 이미 적격 상품 중 최저금리 기준으로 결정된 시스템 추천이므로, "
            "다음 Agent(결과 안내가)에게 넘길 때 이 필드를 그대로 최종 추천으로 명시하고 임의로 다른 상품을 골라 대체하지 않습니다. "
            # [피드백②] '어려움' 판정일 땐 추천상품=None → 상품을 추천으로 제시하지 않음(대안·상담으로).
            "판정이 '어려움'이면 '추천상품'이 None이라는 사실을 그대로 전달하고, 적격상품 중 하나를 대신 추천하지 않습니다."
        ),
        llm=llm, tools=[screen_tool], allow_delegation=False, verbose=True,
    )


def build_advisor_agent(llm):
    """Agent 3 — 결과 안내가 (ReAct)."""
    from crewai import Agent

    return Agent(
        role="결과 안내가",
        goal="심사 판정을 고객 눈높이 안내문으로 전달하되, ReAct로 금리·한도를 재확인하고 디스클레이머를 반드시 포함한다.",
        backstory=(
            "당신은 심사 결과를 고객이 이해하기 쉽게 안내하는 상담사입니다. "
            # [피드백①] 시스템(결정적 로직) 추천상품을 그대로 우선 노출 — Agent가 임의로 다른 상품을 고르지 못하게 함.
            "Agent 2(심사 판단가)가 전달한 '추천상품'은 결정적 로직(assess_loan_eligibility)이 적격 상품 중 "
            "최저금리 기준으로 이미 확정한 시스템 추천입니다. 안내문의 추천 상품은 반드시 이 '추천상품' 필드를 "
            "그대로 최우선으로 제시하고, 스스로 다른 상품을 계산해 대체하거나 추가하지 않습니다. "
            "이 추천 상품의 금리·한도 수치를 쓰기 전에 반드시 'lookup_loan_product' 도구를 호출해 CSV 값을 "
            "재확인합니다(ReAct). 불필요하게 다른 적격 상품까지 하나하나 조회하지 않습니다 — 토큰과 응답 시간만 낭비합니다. "
            "조회로 확인되지 않은 수치·상품은 언급하지 않습니다. "
            # [피드백④] 판정 라벨과 안내 톤을 일치시킴(라벨별로 첫 문장·톤을 분리). 예전엔 '상담필요'가 아닌
            #           승인/어려움 케이스에까지 '상담 안내' 문구가 번지거나, 상담필요 안내가 부정적 톤으로 시작했음.
            "판정 라벨에 따라 안내문의 톤과 첫 문장을 다르게 맞춥니다(라벨마다 하나만 적용):\n"
            "- '승인가능'이면 긍정적인 톤으로 '검토 결과 승인 가능한 것으로 판단됩니다(데모 기준)'처럼 시작하고, "
            "시스템 추천상품 1건을 안내합니다. 이 경우에는 '상담이 필요하다'는 문장을 넣지 않습니다.\n"
            # [피드백④] '상담필요'는 중립·보완가능 상태이므로 부정적 문장으로 시작하지 않도록 톤을 맞춤.
            "- '상담필요'이면 승인 거절이 아니라 보완하면 승인 가능성이 있는 중립적 상태이므로, "
            "'승인 가능성이 낮은 상황입니다' 같은 부정적 문장으로 시작하지 말고 "
            "'추가로 확인·보완이 필요한 부분이 있어 상담을 안내드립니다'처럼 중립적인 문장으로 시작한 뒤, 시스템 추천상품 1건을 안내합니다.\n"
            # [피드백②] '어려움'은 추천상품=None → 상품 나열/추천 대신 개선 방향·상담 안내로 통일.
            "- '어려움'이면 '추천상품'이 None이므로 상품을 나열하거나 '추천'하지 않습니다. "
            "'현재 기준으로는 승인이 어려운 것으로 판단됩니다(데모 기준)'처럼 솔직하되 정중하게 시작하고, "
            "상환능력·신용등급을 개선하는 방향(부채 축소, 소득 안정화, 담보 제공, 소액부터 재신청 등)과 별도 상담 채널 안내로 마무리합니다.\n"
            "'승인합니다/대출해드립니다' 같은 확정 표현 대신 '~로 판단됩니다(데모 기준)'처럼 조건부로 씁니다. "
            "안내문 마지막에 다음 문장을 반드시 그대로 포함합니다: \"" + DISCLAIMER + "\""
        ),
        llm=llm, tools=[lookup_product], allow_delegation=False, verbose=True,
    )


def build_tasks(parser, reviewer, advisor, on_stage=None):
    """parse/review/advise Task 3종을 생성한다.
    on_stage(stage: str, output) 콜백을 넘기면 각 Task 완료 직후 호출된다
    (Streamlit이 '파싱 중 → 심사 중 → 안내문 작성 중' 단계를 실시간으로 보여주는 용도)."""
    from crewai import Task

    def _cb(stage):
        if on_stage is None:
            return None
        return lambda output: on_stage(stage, output)

    parse_task = Task(
        description=(
            "다음 고객 입력을 파싱하라:\n\"{customer_input}\"\n\n"
            "월소득·부채·신용등급·희망금액·직장유형·담보보유 6개 필드를 추출하라. "
            "금액은 원 단위 정수로 환산하라(700만원->7000000). "
            "부채가 '없다'면 0. 직장유형은 정규직/계약직/제한없음 중 하나. "
            "담보보유는 담보 제공 의사가 명시된 경우에만 true, 그 외 false."
        ),
        expected_output=(
            '오직 JSON만 출력: {"월소득": 정수, "부채": 정수, "신용등급": 정수, '
            '"희망금액": 정수, "직장유형": "문자열", "담보보유": true 또는 false}'
        ),
        agent=parser, callback=_cb("parse"),
    )

    review_task = Task(
        description=(
            "Agent 1이 파싱한 고객 JSON을 그대로 'assess_loan_eligibility' 도구에 입력해 결정적 판정을 받아라. "
            "그 판정(승인가능/상담필요/어려움)을 최종 결론으로 확정하라. "
            "그런 다음 CoT 4단계((1)DSR 상환능력(연간 원리금상환액÷연소득) (2)신용등급 조건 (3)희망금액 대비 한도 (4)적합상품 선별)로 근거를 설명하고, "
            "보수적·낙관적·중립 3관점으로 교차검증(SC)해 일관성을 확인하라. "
            "도구가 준 적격상품/부적격사유와 모순되는 내용을 쓰지 마라. "
            # [피드백①] 시스템 추천상품을 그대로 인용(임의 대체 금지).
            "도구 결과의 '추천상품' 필드를 최종 추천 상품으로 그대로 인용하라(상품코드·은행명 포함) — "
            "적격상품 목록에서 직접 다른 상품을 골라 대체하지 마라. "
            # [피드백②] '어려움'이면 추천상품=None을 그대로 전달(대체 추천 금지).
            "판정이 '어려움'이면 '추천상품'이 None이라는 점을 그대로 명시하고, 상품을 대신 추천하지 마라."
        ),
        expected_output="최종 판정(승인가능/상담필요/어려움), CoT 4단계 근거, SC 교차검증 요약, 도구의 '추천상품' 필드(상품코드·은행명 포함, 어려움이면 None) 그대로, 적격/부적격 상품과 사유, DSR 등 핵심 계산값.",
        agent=reviewer, context=[parse_task], callback=_cb("review"),
    )

    advise_task = Task(
        description=(
            "Agent 2의 판정과 근거를 받아 고객용 안내문을 작성하라. "
            # [피드백①] 시스템 추천상품을 그대로 우선 노출(임의 대체·추가 금지).
            "Agent 2가 전달한 '추천상품'(도구가 최저금리 기준으로 확정한 시스템 추천)을 최우선으로 그대로 안내하라 — "
            "스스로 다른 상품을 계산해 대체하거나 추가로 끼워 넣지 마라. "
            "그 추천 상품 하나만 'lookup_loan_product' 도구로 조회해 금리·한도를 재확인하라(ReAct) — 불필요한 반복 조회로 "
            "토큰과 응답 시간을 낭비하지 않는다. "
            # [피드백④] 판정 라벨과 안내 톤 일치(라벨별 첫 문장 분리).
            "판정 라벨에 맞춰 톤과 첫 문장을 다르게 하라(라벨마다 하나만): "
            "'승인가능'이면 긍정적 톤으로 시작하고 '상담이 필요하다'는 문장은 넣지 마라. "
            # [피드백④] '상담필요'는 중립·보완가능 → 부정적 문장으로 시작 금지.
            "'상담필요'이면 보완하면 승인 가능성이 있는 중립적 상태이니 '승인 가능성이 낮은 상황입니다' 같은 부정적 문장 대신 "
            "'추가로 확인·보완이 필요한 부분이 있어 상담을 안내드립니다'처럼 중립적으로 시작하라. "
            # [피드백②] '어려움'은 상품 나열/추천 금지 → 개선 방향·상담 안내로 마무리.
            "'어려움'이면 '추천상품'이 없으므로(None) 상품을 나열하거나 '추천'하지 말고, '현재 기준으로는 승인이 어려운 것으로 "
            "판단됩니다(데모 기준)'처럼 시작한 뒤 상환능력·신용등급 개선 방향(부채 축소, 소득 안정화, 담보 제공, 소액부터 재신청 등)과 "
            "상담 채널 안내로 마무리하라. "
            "확인된 수치만 사용하고, 확정 표현 대신 조건부 표현을 쓰라. "
            "같은 이름의 상품이 여러 은행에 있을 수 있으니, 상품을 언급할 때 상품코드와 은행명을 함께 명시하라. "
            "안내문 마지막 줄에 다음을 그대로 포함하라: \"" + DISCLAIMER + "\""
        ),
        expected_output=(
            "고객 눈높이 안내문. 판정 결과(라벨과 어울리는 톤), 승인가능/상담필요면 시스템 추천상품 1건"
            "(상품코드·은행명 포함)·금리·한도, 어려움이면 상품 나열 없이 개선 방향·상담 안내, "
            "다음 행동 제안, 마지막 줄 디스클레이머 포함."
        ),
        agent=advisor, context=[review_task], callback=_cb("advise"),
    )

    return parse_task, review_task, advise_task


_crew = None
_model_name = None


def get_crew():
    """Crew를 지연 생성해 캐시한다. OPENAI_API_KEY가 없으면 여기서 ValueError."""
    global _crew, _model_name
    if _crew is None:
        from crewai import Crew, Process

        llm, _model_name = get_llm()
        parser = build_parser_agent(llm)
        reviewer = build_reviewer_agent(llm)
        advisor = build_advisor_agent(llm)
        tasks = build_tasks(parser, reviewer, advisor)
        _crew = Crew(
            agents=[parser, reviewer, advisor],
            tasks=list(tasks),
            process=Process.sequential,
            verbose=True,
        )
    return _crew


def get_model_name() -> str:
    """현재 .env에 설정된 모델명(키 유무와 무관하게 조회만, 오류 없음)."""
    return os.getenv("OPENAI_MODEL_NAME", "openai/gpt-4o-mini")


def has_api_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def build_fresh_crew(on_stage=None):
    """호출할 때마다 새 Agent/Task/Crew를 생성한다(캐시하지 않음).
    Streamlit처럼 요청마다 서로 다른 on_stage 콜백(단계별 진행 표시)을 붙여야 할 때 사용."""
    from crewai import Crew, Process

    llm, model_name = get_llm()
    parser = build_parser_agent(llm)
    reviewer = build_reviewer_agent(llm)
    advisor = build_advisor_agent(llm)
    tasks = build_tasks(parser, reviewer, advisor, on_stage=on_stage)
    crew = Crew(
        agents=[parser, reviewer, advisor],
        tasks=list(tasks),
        process=Process.sequential,
        verbose=True,
    )
    return crew, model_name


def _result_dict(result, usage) -> dict:
    tasks_output = getattr(result, "tasks_output", None) or []
    return {
        "파싱결과": tasks_output[0].raw if len(tasks_output) > 0 else None,
        "심사결과": tasks_output[1].raw if len(tasks_output) > 1 else None,
        "안내문": str(result),
        "usage": usage,
    }


async def run_service(customer_input: str) -> dict:
    """전체 3-Agent 파이프라인을 1회 실행하고 Agent별 원문 출력·토큰 Usage를 반환한다.
    (캐시된 crew 재사용 — 노트북처럼 같은 파이프라인을 반복 호출하는 경우에 적합)"""
    crew = get_crew()
    result = await crew.kickoff_async(inputs={"customer_input": customer_input})
    return _result_dict(result, getattr(crew, "usage_metrics", None))


async def run_service_with_stages(customer_input: str, on_stage=None) -> dict:
    """매 호출마다 새 crew를 만들어 실행한다. on_stage("parse"|"review"|"advise", output)로
    단계 완료 시점을 통지받을 수 있다(Streamlit 단계별 spinner용)."""
    crew, _ = build_fresh_crew(on_stage=on_stage)
    result = await crew.kickoff_async(inputs={"customer_input": customer_input})
    return _result_dict(result, getattr(crew, "usage_metrics", None))
