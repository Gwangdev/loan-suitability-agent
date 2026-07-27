"""결정적 심사 로직(screen_loan)·DSR 테스트 (API 키 불필요).

기존 인라인 self-test(run_logic_selftest)를 pytest로 이관하고, 문서(§docs A7)에서 지적한
경계값(한도 경계·연소득 0·음수·DSR 단조성) 테스트를 추가한다.
"""
import pytest

from loan_agent import core

ALL_CASES = core.TEST_CASES + core.EDGE_CASES


@pytest.mark.parametrize("tc", ALL_CASES, ids=[c["name"] for c in ALL_CASES])
def test_verdict_matches_expected(tc):
    parsed = core.rule_based_parse(tc["input"])
    result = core.screen_loan(parsed)
    assert result["판정"] == tc["expected"]


def test_all_three_verdicts_represented():
    """데모가 승인가능/상담필요/어려움 세 판정을 모두 보여주는지."""
    verdicts = {tc["expected"] for tc in core.TEST_CASES}
    assert verdicts == {"승인가능", "상담필요", "어려움"}


# ── 경계값: 한도 ────────────────────────────────────────────
def test_limit_boundary():
    # A-04 소액대출 최대한도 = 7,000,000원 (등급6↑, 담보 불필요, 제한없음)
    base = {"월소득": 3000000, "부채": 0, "신용등급": 6, "직장유형": "제한없음"}
    at_limit = core.screen_loan({**base, "희망금액": 7000000})
    over_limit = core.screen_loan({**base, "희망금액": 7000001})
    assert any(p["상품코드"] == "A-04" for p in at_limit["적격상품"])   # == 한도: 적격
    assert not any(p["상품코드"] == "A-04" for p in over_limit["적격상품"])  # 초과: 부적격


# ── 경계값: 연소득 0 / 음수 입력 ────────────────────────────
def test_zero_income_is_insufficient():
    r = core.screen_loan({"월소득": 0, "부채": 0, "신용등급": 1,
                          "희망금액": 1000000, "직장유형": "정규직"})
    assert r["상환능력"] == "부족"
    assert r["DSR"] is None  # 연소득 0 → dsr 무한대 → None으로 반환


def test_negative_income_clamped_to_insufficient():
    r = core.screen_loan({"월소득": -500, "부채": 0, "신용등급": 1,
                          "희망금액": 1000000, "직장유형": "정규직"})
    assert r["상환능력"] == "부족"


# ── DSR 단조성: 희망금액↑ → DSR↑ (예전 간이 DTI는 못 잡던 특성) ──
def test_dsr_increases_with_loan_amount():
    base = {"월소득": 3000000, "부채": 0, "신용등급": 3, "직장유형": "정규직"}
    small = core.screen_loan({**base, "희망금액": 10000000})
    large = core.screen_loan({**base, "희망금액": 100000000})
    assert large["DSR"] > small["DSR"]
    # 부채가 0이어도 큰 신청금액은 상환부담으로 잡혀야 한다(핵심 개선점)
    assert large["상환능력"] == "부족"


# ── 원리금균등상환 헬퍼 ─────────────────────────────────────
def test_monthly_payment_zero_principal():
    assert core.monthly_payment(0) == 0.0


def test_monthly_payment_zero_rate_is_simple_division():
    assert core.monthly_payment(1200000, annual_rate=0.0, months=12) == 100000.0


def test_monthly_payment_positive():
    assert core.monthly_payment(10000000) > 0


# ── '어려움'이면 추천/후보 없음 ─────────────────────────────
def test_hard_verdict_has_no_recommendation():
    hard = core.screen_loan({"월소득": 1800000, "부채": 30000000, "신용등급": 6,
                             "희망금액": 10000000, "직장유형": "제한없음"})
    assert hard["판정"] == "어려움"
    assert hard["추천상품"] is None
    assert hard["추천후보"] == []
