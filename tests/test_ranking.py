"""다기준 상품 랭킹 테스트 (API 키 불필요) — §docs C-2."""
from loan_agent import core


def test_ranking_returns_at_most_three():
    r = core.screen_loan({"월소득": 7000000, "부채": 0, "신용등급": 1,
                          "희망금액": 30000000, "직장유형": "정규직"})
    assert 1 <= len(r["추천후보"]) <= 3


def test_ranking_sorted_by_rate_nondecreasing():
    r = core.screen_loan({"월소득": 7000000, "부채": 0, "신용등급": 1,
                          "희망금액": 30000000, "직장유형": "정규직"})
    rates = [float(c["금리범위"].split("%")[0]) for c in r["추천후보"]]
    assert rates == sorted(rates)


def test_tiebreak_by_prepayment_fee_when_rate_equal():
    """최저금리 동률(A-02·F-01 모두 3.0%)일 때 중도상환수수료가 낮은 A-02(1.5%)가
    F-01(1.8%)보다 앞서야 한다. (담보보유·정규직·1등급이면 둘 다 적격)"""
    r = core.screen_loan({"월소득": 8000000, "부채": 0, "신용등급": 1,
                          "희망금액": 20000000, "직장유형": "정규직", "담보보유": True})
    codes = [c["상품코드"] for c in r["추천후보"]]
    assert r["추천상품"]["상품코드"] == "A-02"
    assert "F-01" in codes
    assert codes.index("A-02") < codes.index("F-01")


def test_recommendation_is_top_ranked():
    r = core.screen_loan({"월소득": 7000000, "부채": 0, "신용등급": 1,
                          "희망금액": 30000000, "직장유형": "정규직"})
    assert r["추천상품"]["상품코드"] == r["추천후보"][0]["상품코드"]
