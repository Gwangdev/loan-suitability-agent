"""Eval 하네스 테스트 (API 키·토큰 불필요).

두 방향으로 검증한다.
1) 현재 사전 녹화 출력이 전 지표를 통과하는지(품질 회귀 가드).
2) 일부러 결함을 심은 출력을 eval이 실제로 '잡아내는지'(하네스가 무의미하게 통과만 하지 않음).
"""
import pytest

from loan_agent import core, eval as ev

# 승인 케이스 입력 → 결정적으로 판정 승인가능, 추천 A-02(금리 3.0%~5.5%, 한도 1억, 중도상환 1.5%)
APPROVE_INPUT = "월급 700만원 받는 정규직이고 부채는 없습니다. 신용등급 1등급이고 3000만원 대출받고 싶어요."
GOOD_PARSE = '{"월소득":7000000,"부채":0,"신용등급":1,"희망금액":30000000,"직장유형":"정규직","담보보유":false}'
GOOD_ADVICE = (
    "검토 결과 승인 가능한 것으로 판단됩니다(데모 기준). "
    "추천 상품: 프리미엄대출(A-02, A은행), 금리 3.0%~5.5%, 최대한도 100,000,000원. "
    + core.DISCLAIMER
)


def _case(advice=GOOD_ADVICE, parse=GOOD_PARSE, name="승인", expected="승인가능", inp=APPROVE_INPUT):
    return {"name": name, "input": inp, "expected": expected,
            "result": {"파싱결과": parse, "심사결과": "", "안내문": advice}}


# ── 1) 현재 사전 녹화 출력은 전 지표 통과 ───────────────────────────
def test_recorded_fixtures_full_pass():
    report = ev.run_eval()
    assert report["n"] == 5
    assert report["total"] == report["total_max"], report  # 30/30


def test_good_synthetic_case_full_pass():
    s = ev.score_case(_case())
    assert s["score"] == s["max"], s["detail"]


# ── 2) 결함을 심으면 해당 지표를 잡아낸다 ───────────────────────────
def test_detects_missing_disclaimer():
    s = ev.score_case(_case(advice="승인 가능한 것으로 판단됩니다. 추천 상품 A-02, 금리 3.0%~5.5%."))
    assert s["checks"]["디스클레이머"] is False


def test_detects_hallucinated_number():
    # 금리 2.0% 는 A-02(3.0~5.5%)·CSV·입력 어디에도 없는 값 → 환각
    bad = "승인 가능한 것으로 판단됩니다. 추천 A-02, 금리 2.0%~5.5%. " + core.DISCLAIMER
    s = ev.score_case(_case(advice=bad))
    assert s["checks"]["수치근거"] is False


def test_detects_definitive_expression():
    bad = "대출을 승인합니다. 추천 A-02, 금리 3.0%~5.5%, 한도 100,000,000원. " + core.DISCLAIMER
    s = ev.score_case(_case(advice=bad))
    assert s["checks"]["조건부표현"] is False


def test_detects_wrong_recommendation():
    # 결정적 추천은 A-02 인데 안내문은 A-02를 언급하지 않음
    bad = "승인 가능한 것으로 판단됩니다. 추천 상품 B-01, 금리 6.0%~12.0%. " + core.DISCLAIMER
    s = ev.score_case(_case(advice=bad))
    assert s["checks"]["추천정합성"] is False


def test_detects_parse_error():
    s = ev.score_case(_case(parse='{"월소득":1000000,"부채":0,"신용등급":1,"희망금액":30000000,"직장유형":"정규직"}'))
    assert s["checks"]["파싱정확도"] is False  # 월소득 불일치


def test_detects_verdict_contradiction():
    bad = "죄송하지만 대출이 거절되었습니다. " + core.DISCLAIMER
    s = ev.score_case(_case(advice=bad))
    assert s["checks"]["판정정합성"] is False


def test_hard_case_should_not_recommend_product():
    # '어려움' 판정 입력인데 안내문이 상품코드를 추천하면 추천정합성 실패
    hard_input = "월급 180만원이고 부채 3000만원 있습니다. 신용등급 6등급, 1000만원 빌리고 싶어요."
    bad = "현재 기준으로는 승인이 어려운 것으로 판단됩니다. 그래도 A-04 소액대출을 추천드립니다. " + core.DISCLAIMER
    s = ev.score_case(_case(advice=bad, name="어려움", expected="어려움", inp=hard_input,
                            parse='{"월소득":1800000,"부채":30000000,"신용등급":6,"희망금액":10000000,"직장유형":"제한없음","담보보유":false}'))
    assert s["checks"]["추천정합성"] is False
