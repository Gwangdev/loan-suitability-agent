"""Streamlit UI의 결정적 심사가 API 계층을 거치는지 확인한다."""
from loan_agent import app


def test_submit_assessment_posts_structured_form_with_idempotency_key(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"assessment_id": "a", "verdict": "ELIGIBLE"}

    def post(url, *, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr(app.httpx, "post", post)
    result = app._submit_assessment({"월소득": 7_000_000, "부채": 0, "신용등급": 1, "희망금액": 30_000_000, "직장유형": "정규직", "담보보유": False})

    assert result["verdict"] == "ELIGIBLE"
    assert captured["url"].endswith("/api/v1/assessments")
    assert captured["json"]["monthly_income"] == 7_000_000
    assert captured["headers"]["Idempotency-Key"]
    assert captured["timeout"] == 10.0


def test_submit_assessment_uses_a_new_key_for_each_new_confirmed_submission(monkeypatch):
    keys = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"assessment_id": "a", "verdict": "ELIGIBLE"}

    def post(_url, *, json, headers, timeout):
        keys.append(headers["Idempotency-Key"])
        return Response()

    monkeypatch.setattr(app.httpx, "post", post)
    customer = {"월소득": 7_000_000, "부채": 0, "신용등급": 1, "희망금액": 30_000_000, "직장유형": "정규직", "담보보유": False}
    app._submit_assessment(customer)
    app._submit_assessment(customer)

    assert keys[0] != keys[1]


def test_usage_cost_uses_input_and_output_token_rates():
    cost = app._usage_cost_usd({"prompt_tokens": 1_000, "completion_tokens": 500})

    assert cost == app.Decimal("0.00045")


def test_screen_from_assessment_carries_every_field_the_table_renders():
    """API 응답만으로 대안 비교표를 그릴 수 있어야 한다.

    운영에서 KeyError로 화면이 죽었다. 데모 픽스처 경로는 screen_loan을 다시 돌려
    아홉 필드를 전부 갖지만, 실제 심사 경로는 API 응답을 옮기므로 API가 주지 않는
    필드는 없다. 두 경로가 같은 렌더 함수를 쓰는데 구조가 달랐던 것이다.

    표가 읽는 키를 여기에 고정한다. 화면이 새 열을 요구하면 이 테스트가 먼저 깨진다.
    """
    from loan_agent import app

    assessment = {
        "decision": {
            "verdict": "ELIGIBLE", "repayment_band": "COMFORTABLE",
            "dsr": 0.097, "monthly_payment": {"합계": 289992},
        },
        "recommendations": [{
            "product_code": "B-01", "rank": 1, "eligible": True,
            "product_name": "무담보신용대출", "bank": "B은행",
            "interest_rate_range": "6.0%~12.0%", "maximum_limit": 30000000,
            "repayment_method": "원리금균등", "rate_type": "변동",
            "early_repayment_fee": 1.0, "approval_margin": 0,
        }],
    }

    screen = app._screen_from_assessment(assessment)
    후보 = screen["추천후보"][0]

    for key in ("상품코드", "상품명", "은행", "금리범위",
                "상환방식", "금리방식", "중도상환수수료", "승인여유마진"):
        assert key in 후보, f"대안 비교표가 읽는 키가 없다: {key}"
        assert 후보[key] is not None, f"API가 값을 주지 않았다: {key}"
