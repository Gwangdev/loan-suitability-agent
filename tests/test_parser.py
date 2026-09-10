"""파싱 경계와 필수필드 검증 테스트 (API 키 불필요)."""
from fastapi.testclient import TestClient

import pytest

from loan_agent import core, llm
from loan_agent.api import app

client = TestClient(app)


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


def test_parsing_preview_surfaces_independent_candidates_and_disagreements(monkeypatch):
    """두 파서가 다르면 사람에게 두 값과 필드명을 모두 보여야 한다.

    이 경로가 LLM 값을 자동 채택하면 검증 경계가 사라진다. 의도적으로 월소득이
    다른 후보를 주고, 응답이 어느 쪽도 하나의 정답으로 축약하지 않는지 확인한다.
    """
    monkeypatch.setattr(
        llm,
        "parse_with_llm",
        lambda _text, _api_key: {
            "월소득": 4_000_000,
            "부채": 0,
            "신용등급": 1,
            "희망금액": 30_000_000,
            "직장유형": "정규직",
            "담보보유": False,
        },
    )

    response = client.post(
        "/api/v1/parsing-preview",
        json={"text": "월급 700만원 받는 정규직이고 부채는 없습니다. 신용등급 1등급이고 3000만원 빌리고 싶어요."},
        headers={"X-OpenAI-API-Key": "test-visitor-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rule_candidate"]["월소득"] == 7_000_000
    assert body["llm_candidate"]["월소득"] == 4_000_000
    assert body["mismatched_fields"] == ["월소득"]
    assert body["parse_accuracy"] is False
    assert body["degraded"] is False


def test_parsing_preview_marks_agreeing_candidates_as_parse_accurate(monkeypatch):
    rule = core.rule_based_parse("월소득 300만원입니다.")
    monkeypatch.setattr(llm, "parse_with_llm", lambda *_: rule)

    response = client.post(
        "/api/v1/parsing-preview",
        json={"text": "월소득 300만원입니다."},
        headers={"X-OpenAI-API-Key": "test"},
    )

    assert response.status_code == 200
    assert response.json()["mismatched_fields"] == []
    assert response.json()["parse_accuracy"] is True


def test_parsing_preview_degrades_to_rule_candidate_without_a_key(monkeypatch):
    monkeypatch.setattr(llm, "parse_with_llm", lambda *_: (_ for _ in ()).throw(AssertionError()))

    response = client.post(
        "/api/v1/parsing-preview", json={"text": "월소득 300만원입니다."}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rule_candidate"]["월소득"] == 3_000_000
    assert body["llm_candidate"] is None
    assert body["parse_accuracy"] is None
    assert body["degraded"] is True


# ── 필수필드 검증 (§docs A2/타팀 피드백-2) ──────────────────
def test_missing_required_fields_none_when_complete():
    parsed = {"월소득": 3000000, "신용등급": 3, "희망금액": 20000000, "부채": 0}
    assert core.missing_required_fields(parsed) == []


def test_debt_zero_passes_but_absent_debt_is_missing():
    """부채는 0이 정상 입력이므로 0을 미입력 표식으로 쓸 수 없다.

    다른 필수 항목은 0이 도메인상 불가능해 0을 미입력으로 읽어도 되지만, 부채 0은
    "빚이 없다"는 뜻이다. 그래서 값의 부재만 미입력으로 본다. 구분하지 않으면 파서가
    못 읽은 부채가 "빚 없음"으로 심사에 들어가 판정이 승인 쪽으로 기운다.
    """
    complete = {"월소득": 3_000_000, "신용등급": 3, "희망금액": 20_000_000, "부채": 0}
    assert core.missing_required_fields(complete) == []
    assert core.missing_required_fields({**complete, "부채": None}) == ["부채"]


def test_unparsable_debt_is_absent_not_zero():
    """한글 수사처럼 파서가 못 읽는 표기가 남아도 안전한 쪽으로 실패해야 한다."""
    parsed = core.rule_based_parse("월급 350만원 정규직이고 부채 오천만원 있어요. 신용등급 3등급, 2000만원 대출받고 싶어요.")
    assert parsed["부채"] is None
    assert "부채" in core.missing_required_fields(parsed)


def test_stated_absence_of_debt_is_zero_not_absent():
    """「부채 없음」은 읽어 낸 값이므로 미입력으로 떨어지지 않는다."""
    parsed = core.rule_based_parse("월급 700만원 받는 정규직이고 부채는 없습니다. 신용등급 1등급이고 3000만원 대출받고 싶어요.")
    assert parsed["부채"] == 0
    assert core.missing_required_fields(parsed) == []


def test_missing_required_fields_flags_missing_income():
    parsed = {"월소득": 0, "신용등급": 3, "희망금액": 20000000}
    missing = core.missing_required_fields(parsed)
    assert "월 소득" in missing


def test_missing_required_fields_flags_sentinel_grade():
    # 신용등급 99 = 미입력 sentinel
    parsed = {"월소득": 3000000, "신용등급": 99, "희망금액": 20000000}
    assert "신용등급" in core.missing_required_fields(parsed)


@pytest.mark.parametrize("text,expected,note", [
    ("월소득 3,000,000", 3_000_000, "콤마 둘은 백만 이상이므로 원 단위 전체 금액이다"),
    ("월소득 5000000원", 5_000_000, "원을 명시하면 그대로"),
    ("월급 700만원", 7_000_000, "만원을 명시하면 만 배"),
    ("월 300", 3_000_000, "단위 생략은 만원 관행을 따른다"),
    ("월소득 5000000", 5_000_000, "단위 없어도 백만 이상은 원이다"),
    ("월소득 10,000", 100_000_000, "콤마 하나는 자릿수 구분일 뿐 원 단위 신호가 아니다"),
    ("월소득 2,000", 20_000_000, "네 자리 콤마 표기도 만원 관행을 따른다"),
    ("월소득 100,000,000", 100_000_000, "콤마 셋도 원이다"),
])
def test_amount_unit_is_inferred_from_notation(text, expected, note):
    """단위 미기재의 기본값을 어디까지 적용할지가 만 배 오차의 갈림길이다.

    운영에서 "월소득 3,000,000"이 300억으로 파싱돼, 콤마가 있으면 원으로 읽도록
    막았다. 그 규칙은 반대 방향을 열어 두었다 — 만원 단위로 "10,000"(=1억)을 적으면
    1만원이 된다. 축소는 상환부담을 낮게 보이게 해 승인 쪽으로 기울므로 더 위험하다.

    콤마의 유무가 아니라 개수가 자리수를 말해 준다. 하나면 만원 표기에서 흔한
    자리수이고, 둘 이상이면 백만 이상이라 만원으로 읽을 수 없다.
    """
    assert core.parse_korean_amount(text, ["월소득", "월급", "월"]) == expected, note


@pytest.mark.parametrize("text,expected,note", [
    ("1억 대출받고 싶어요", 100_000_000, "억이 단위 목록에 없어 통째로 버려지던 표기"),
    ("1억원 대출받고 싶어요", 100_000_000, "억에 원이 붙어도 같다"),
    ("1억 5000만원 대출받고 싶어요", 150_000_000, "큰 단위와 작은 단위를 이어 쓰면 더한다"),
    ("1억5천만원 대출받고 싶어요", 150_000_000, "띄어쓰기 없이 이어 써도 같다"),
    ("5천만원 대출받고 싶어요", 50_000_000, "천만은 천 곱하기 만이다"),
    ("5백만원 대출받고 싶어요", 5_000_000, "백만도 같은 방식으로 쌓인다"),
    ("1.5억 대출받고 싶어요", 150_000_000, "억은 소수 표기로도 쓴다"),
    ("1.15억 대출받고 싶어요", 115_000_000, "소수 곱셈이 경계 아래로 떨어져도 1원이 모자라면 안 된다"),
    ("12345678901234567원 대출받고 싶어요", 12345678901234567, "정수 표기는 자리수가 커도 그대로 돌아온다"),
    ("3000만원 대출받고 싶어요", 30_000_000, "기존 만원 표기는 그대로다"),
])
def test_korean_magnitude_units_compose(text, expected, note):
    """억을 단위 목록에 더하는 것만으로는 부족하다.

    "1억"이 1만원으로 읽힌 것은 단위 목록에 만원·원만 있어 억이 버려지고 단위 미기재로
    떨어졌기 때문이다. 그런데 억만 목록에 더하면 "1억 5천만원"이 여전히 틀린다 — 큰
    단위와 작은 단위를 이어 쓰는 것이 한국어 금액 표기의 기본형이기 때문이다. 단위
    하나를 고르는 대신 조각을 이어 읽어 더해야 표기 전체가 맞는다.
    """
    assert core.parse_korean_amount(text, ["희망", "대출받", "빌리", "받고"]) == expected, note


def test_unitless_numbers_do_not_merge_across_fields():
    """단위를 가진 조각 뒤에서만 이어 읽는다.

    "월 300 부채 500"은 한 금액의 두 조각이 아니라 서로 다른 항목이다. 이어 붙이면
    소득에 부채가 합쳐져 상환능력이 과대평가된다 — 승인 쪽으로 기우는 방향이다.
    """
    parsed = core.rule_based_parse("월 300 부채 500 신용등급 4등급, 2000만원 희망")
    assert parsed["월소득"] == 3_000_000
    assert parsed["부채"] == 5_000_000


def test_zero_amount_is_a_parsed_value_not_a_miss():
    """0원은 읽어 낸 값이므로 못 읽은 것과 구분한다.

    구분하지 않으면 "부채 0원"이 실패로 떨어지고, 키워드 주변을 다시 훑는 과정에서
    뒤쪽의 무관한 숫자가 부채로 붙는다.
    """
    assert core.parse_korean_amount("부채 0원", ["부채"]) == 0
    assert core.rule_based_parse("월급 300만원, 부채 0원, 신용등급 3등급")["부채"] == 0


def test_single_comma_six_digits_still_reads_as_man_won():
    """콤마 하나짜리 여섯 자리는 두 해석이 모두 성립해 표기만으로 풀 수 없다.

    "월소득 500,000"은 50만원을 뜻할 수도, 50억을 뜻할 수도 있다. 어느 쪽으로 읽든
    반대편이 틀리므로 파서는 만원 관행을 따르고, 확정은 화면에서 사람이 한다.
    이 테스트는 한계를 고정해 두어, 값이 조용히 바뀌면 드러나게 한다.
    """
    assert core.parse_korean_amount("월소득 500,000", ["월소득"]) == 5_000_000_000
