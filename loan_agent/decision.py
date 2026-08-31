"""결정적 판정을 영속화 계층이 저장할 수 있는 형태로 옮긴다.

`core.screen_loan`은 노트북·화면이 함께 쓰는 한글 구조를 돌려준다. API와 DB는 영문
enum과 정규화된 행을 다루므로 그 사이를 변환하는 자리가 필요하고, 이 변환을 HTTP
모듈에 두면 「판정은 코드, 설명은 LLM」이라는 경계가 표면에서부터 흐려진다. 그래서
변환을 API 밖의 이 모듈에 둔다.

버전 두 종을 여기서 확정한다. 규칙 버전은 판정 기준(DSR 밴드·하드규칙)이 바뀔 때
손으로 올리는 문자열이고, 상품 데이터셋 버전은 CSV 내용에서 파생한 해시라 파일이
바뀌면 저절로 달라진다. 어느 규칙·어느 상품표로 나온 판정인지 결과에 박아 두어야
과거 판정을 당시 기준으로 재현할 수 있다(ADR-005).
"""
import hashlib

from loan_agent import core

# 판정 기준이 바뀌면(밴드 경계, 하드규칙, 대표 가정금리·기간) 이 값을 올린다.
RULE_VERSION = "screening-2026.08"

_VERDICT_BY_LABEL = {
    "승인가능": "ELIGIBLE",
    "상담필요": "CONDITIONAL",
    "어려움": "INELIGIBLE",
}

_BAND_BY_LABEL = {
    "여유": "COMFORTABLE",
    "보통": "MODERATE",
    "부족": "STRAINED",
}


# 화면·안내문은 한글 어휘를 쓴다(ADR-012). 저장은 영문 enum이므로 사용자에게 나가는
# 경로에서는 되돌려야 한다. 되돌리지 않으면 LLM이 ELIGIBLE을 "적격", COMFORTABLE을
# "편안한"으로 직역해 도메인 어휘와 어긋난 안내문이 나간다.
VERDICT_LABEL = {v: k for k, v in _VERDICT_BY_LABEL.items()}
BAND_LABEL = {v: k for k, v in _BAND_BY_LABEL.items()}


def product_dataset_version() -> str:
    """현재 상품 CSV의 내용 해시. 파일이 한 글자라도 바뀌면 값이 달라진다."""
    digest = hashlib.sha256(core.CSV_PATH.read_bytes()).hexdigest()
    return f"csv-{digest[:12]}"


def decide(
    *,
    monthly_income: int,
    existing_debt: int,
    credit_grade: int,
    requested_amount: int,
    employment_type: str,
    collateral_owned: bool,
) -> dict:
    """구조화 입력을 결정적으로 판정하고 저장 가능한 형태로 돌려준다."""
    raw = core.screen_loan(
        {
            "월소득": monthly_income,
            "부채": existing_debt,
            "신용등급": credit_grade,
            "희망금액": requested_amount,
            "직장유형": employment_type,
            "담보보유": collateral_owned,
        }
    )
    return {
        "verdict": _VERDICT_BY_LABEL[raw["판정"]],
        "repayment_band": _BAND_BY_LABEL[raw["상환능력"]],
        "dsr": raw["DSR"],
        "monthly_payment": raw["월상환액"],
        "recommendations": [
            {
                "product_code": brief["상품코드"],
                "rank": index + 1,
                "eligible": True,
                "reason_codes": brief,
            }
            for index, brief in enumerate(raw["추천후보"])
        ],
        "rule_version": RULE_VERSION,
        "product_dataset_version": product_dataset_version(),
    }


__all__ = ["RULE_VERSION", "product_dataset_version", "decide"]
