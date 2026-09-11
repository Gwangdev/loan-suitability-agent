"""구조화 로그 — 요청 식별자가 로그와 감사 이벤트를 실제로 잇는지 고정한다.

데이터 모델은 `audit_event.correlation_id`를 「요청 하나를 추적」하는 키로 정의했지만,
구현은 감사 이벤트를 쓸 때마다 새 값을 뽑아 로그와 아무것도 잇지 못했다. 게이트는
엔드포인트 목록만 대조하므로 이런 동작 부재를 원리상 잡지 못한다. 잇는 동작 자체를
겨냥한 테스트로 고정한다.

같은 자리에서 금지 행위 ③⑦도 확인한다. 본문의 금액과 헤더의 API 키가 로그에 실리지
않는다는 것을 파싱한 필드가 아니라 출력 문자열 전체에서 본다. 필드만 보면 허용 목록
밖으로 새는 경로를 놓친다.
"""
import io
import json
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from loan_agent import logs
from loan_agent.api import app, errors, limits, request_log
from loan_agent.api.contract import API_KEY_HEADER
from loan_agent.db import engine as db_engine

VALID_BODY = {
    "monthly_income": 7_000_000,
    "existing_debt": 0,
    "credit_grade": 1,
    "requested_amount": 30_000_000,
    "employment_type": "정규직",
    "collateral_owned": False,
}


class _Captured:
    def __init__(self, stream: io.StringIO):
        self._stream = stream

    @property
    def raw(self) -> str:
        return self._stream.getvalue()

    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self.raw.splitlines()]

    def requests(self) -> list[dict]:
        return [line for line in self.lines() if line["logger"] == request_log.__name__]


@pytest.fixture()
def captured():
    stream = io.StringIO()
    logs.configure(stream=stream)
    yield _Captured(stream)
    logs.configure()


def test_every_request_leaves_one_line_with_a_correlation_id(captured):
    TestClient(app).get("/health/live")

    [line] = captured.requests()
    assert (line["method"], line["path"], line["status"]) == ("GET", "/health/live", 200)
    uuid.UUID(line["correlation_id"])
    assert isinstance(line["latency_ms"], float)


def test_requests_rejected_by_the_limits_are_logged_too(captured):
    """상한 미들웨어보다 바깥에 걸려 있어야 413도 식별자와 함께 남는다."""
    oversized = "가" * (limits.MAX_BODY_BYTES + 1)

    TestClient(app).post("/api/v1/parsing-preview", json={"text": oversized})

    [line] = captured.requests()
    assert line["status"] == 413


def test_body_query_and_api_key_never_reach_the_log(captured):
    body = {**VALID_BODY, "monthly_income": 7_777_777}
    secret = "sk-test-must-never-be-logged"

    # Idempotency-Key가 없어 핸들러에 닿기 전에 422로 끝나므로 DB가 필요 없다.
    TestClient(app).post(
        "/api/v1/assessments?probe=query-marker",
        json=body,
        headers={API_KEY_HEADER: secret},
    )

    assert captured.requests(), "요청 로그가 남지 않았다"
    assert "7777777" not in captured.raw
    assert secret not in captured.raw
    assert "query-marker" not in captured.raw


def test_unhandled_error_is_logged_under_the_request_correlation_id(captured):
    """예외 처리기는 미들웨어 바깥에서 돌지만 같은 식별자로 기록해야 둘을 이을 수 있다."""
    local = FastAPI()
    errors.install(local)
    request_log.install(local)

    @local.get("/boom")
    def boom():
        raise RuntimeError("boom")

    response = TestClient(local, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    [request_line] = captured.requests()
    [error_line] = [line for line in captured.lines() if line["logger"] == errors.__name__]
    assert request_line["status"] == 500
    assert error_line["correlation_id"] == request_line["correlation_id"]
    assert "RuntimeError" in error_line["exception"]


def test_audit_event_shares_the_request_correlation_id(api_db, captured):
    """로그 한 줄의 식별자로 감사 이벤트를 찾으면 그 요청이 만든 심사가 나와야 한다."""
    response = TestClient(app).post(
        "/api/v1/assessments",
        json=VALID_BODY,
        headers={"Idempotency-Key": f"test-{uuid.uuid4()}"},
    )
    assert response.status_code == 201

    [line] = captured.requests()
    with api_db.connect() as conn:
        target_id = conn.execute(
            text("SELECT target_id FROM audit_event WHERE correlation_id = :cid"),
            {"cid": line["correlation_id"]},
        ).scalar_one()
    assert str(target_id) == response.json()["assessment_id"]


def test_formatter_drops_fields_outside_the_allowlist():
    record = logging.LogRecord("loan_agent.probe", logging.INFO, __file__, 1, "probe", None, None)
    record.body = {"monthly_income": 7_777_777}

    entry = json.loads(logs.JsonFormatter().format(record))

    assert "body" not in entry
    assert "7777777" not in json.dumps(entry)


def test_sql_parameters_are_kept_out_of_exception_text(monkeypatch):
    """SQL 오류 문자열에 바인딩 값이 실리면 처리되지 않은 예외 로그로 금액이 샌다."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://localhost/never-connected")
    db_engine.reset()
    try:
        # 엔진 생성은 접속하지 않는다. 설정만 확인한다.
        assert db_engine.get_engine().hide_parameters is True
    finally:
        db_engine.reset()
