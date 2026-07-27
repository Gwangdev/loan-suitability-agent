"""상품 로딩·파싱 헬퍼 테스트 (API 키 불필요)."""
from loan_agent import core


def test_products_loaded():
    assert len(core.PRODUCTS) == 22
    assert all("상품코드" in p for p in core.PRODUCTS)


def test_new_ranking_columns_present():
    # [디벨롭: 다기준 랭킹] FSS 공시 미러 컬럼이 모두 로드되는지
    for p in core.PRODUCTS:
        assert p["상환방식"] in ("원리금균등", "만기일시")
        assert p["금리방식"] in ("고정", "변동")
        assert isinstance(p["중도상환수수료"], float)
        assert p["중도상환수수료"] >= 0


def test_pct_helper():
    assert core._pct("4.5%") == 4.5
    assert core._pct("10.0%") == 10.0


def test_grade_helper():
    assert core._grade("3등급이상") == 3
    assert core._grade("1등급") == 1
