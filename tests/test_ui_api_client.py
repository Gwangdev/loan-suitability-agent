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


def test_submit_assessment_reuses_the_key_for_the_same_confirmed_form(monkeypatch):
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

    assert keys[0] == keys[1]


def test_usage_cost_uses_input_and_output_token_rates():
    cost = app._usage_cost_usd({"prompt_tokens": 1_000, "completion_tokens": 500})

    assert cost == app.Decimal("0.00045")
