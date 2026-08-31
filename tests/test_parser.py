"""파싱 경계와 필수필드 검증 테스트 (API 키 불필요)."""
from fastapi.testclient import TestClient

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
