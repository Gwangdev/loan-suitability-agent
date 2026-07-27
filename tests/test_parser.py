"""규칙 기반 파서(rule_based_parse) + 필수필드 검증 테스트 (API 키 불필요)."""
from loan_agent import core


def test_parse_keyword_before_number():
    # '월급 700만원' — 키워드 → 숫자 방향
    assert core.parse_korean_amount("월급 700만원", ["월급", "월소득"]) == 7000000


def test_parse_number_before_keyword():
    # '3000만원 대출받고' — 숫자 → 키워드 방향
    assert core.parse_korean_amount("3000만원 대출받고 싶어요", ["대출받", "희망"]) == 30000000


def test_rule_based_parse_full_case():
    parsed = core.rule_based_parse(
        "월급 700만원 받는 정규직이고 부채는 없습니다. 신용등급 1등급이고 3000만원 대출받고 싶어요."
    )
    assert parsed["월소득"] == 7000000
    assert parsed["부채"] == 0            # '부채는 없습니다' → 0
    assert parsed["신용등급"] == 1
    assert parsed["희망금액"] == 30000000
    assert parsed["직장유형"] == "정규직"


def test_collateral_detection():
    with_col = core.rule_based_parse("집을 담보로 제공할 수 있습니다.")
    without_col = core.rule_based_parse("담보는 없어요.")
    assert with_col["담보보유"] is True
    assert without_col["담보보유"] is False


# ── 필수필드 검증 (§docs A2/타팀 피드백-2) ──────────────────
def test_missing_required_fields_none_when_complete():
    parsed = {"월소득": 3000000, "신용등급": 3, "희망금액": 20000000}
    assert core.missing_required_fields(parsed) == []


def test_missing_required_fields_flags_missing_income():
    parsed = {"월소득": 0, "신용등급": 3, "희망금액": 20000000}
    missing = core.missing_required_fields(parsed)
    assert "월 소득" in missing


def test_missing_required_fields_flags_sentinel_grade():
    # 신용등급 99 = 미입력 sentinel
    parsed = {"월소득": 3000000, "신용등급": 99, "희망금액": 20000000}
    assert "신용등급" in core.missing_required_fields(parsed)
