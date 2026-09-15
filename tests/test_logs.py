"""구조화 로그 — 요청 식별자가 로그와 감사 이벤트를 실제로 잇는지 고정한다.

데이터 모델은 `audit_event.correlation_id`를 「요청 하나를 추적」하는 키로 정의했지만,
구현은 감사 이벤트를 쓸 때마다 새 값을 뽑아 로그와 아무것도 잇지 못했다. 게이트는
엔드포인트 목록만 대조하므로 이런 동작 부재를 원리상 잡지 못한다. 잇는 동작 자체를
겨냥한 테스트로 고정한다.

같은 자리에서 금지 행위 ③⑦도 확인한다. 본문의 금액과 헤더의 API 키가 로그에 실리지
않는다는 것을 파싱한 필드가 아니라 출력 문자열 전체에서 본다. 필드만 보면 허용 목록
밖으로 새는 경로를 놓친다.
"""
import copy
import io
import json
import logging
import logging.config
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from uvicorn.config import LOGGING_CONFIG

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


def _app_raising_an_error_that_carries_a_key() -> FastAPI:
    """형식이 틀린 키로 요청을 만들 때 제공자 SDK가 던지는 연쇄 예외를 흉내 낸다.

    끝에 줄바꿈이 붙은 키로 HTTP 요청을 만들면 전송 계층 오류 메시지에 키 원문이 들어가고,
    제공자 SDK는 그 오류를 감싸 다시 던지므로 연쇄 traceback에 키가 남는다.
    """
    probe = FastAPI()
    errors.install(probe)

    @probe.get("/boom")
    def boom():
        try:
            raise ValueError("Illegal header value b'Bearer sk-proj-LEAKCHECK0123456789abcdef\\n'")
        except ValueError as transport_error:
            raise ConnectionError("Connection error.") from transport_error

    return probe


@pytest.fixture()
def uvicorn_stderr():
    """uvicorn 기본 로그 설정이 먼저 걸리고 앱이 뒤에 로그를 설정하는 실제 순서를 만든다.

    uvicorn은 앱 모듈을 import하기 전에 `dictConfig`로 자기 핸들러를 건다. 그 핸들러가 쓰는
    표준 오류 자리에 버퍼를 넣고, 끝나면 uvicorn 로거를 원래 상태로 되돌린다.
    """
    names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    saved = {}
    for name in names:
        logger = logging.getLogger(name)
        saved[name] = (list(logger.handlers), logger.propagate, logger.level)
    stream = io.StringIO()
    config = copy.deepcopy(LOGGING_CONFIG)
    config["handlers"]["default"]["stream"] = stream
    logging.config.dictConfig(config)
    logs.configure(stream=io.StringIO())
    yield stream
    for name, (handlers, propagate, level) in saved.items():
        logger = logging.getLogger(name)
        logger.handlers = handlers
        logger.propagate = propagate
        logger.setLevel(level)
    logs.configure()


def test_an_api_key_inside_an_unhandled_exception_never_reaches_the_app_log(captured):
    """처리되지 않은 예외의 traceback에 키가 섞여 있어도 앱 처리기가 남기는 JSON 줄에는 없어야 한다.

    이 테스트는 앱 처리기의 기록만 본다. `raise_server_exceptions=False`는 처리기가 응답을 만든
    뒤 Starlette가 다시 던지는 예외를 삼키므로, 실제 서버에서 uvicorn이 그 예외를 한 번 더 쓰는
    기록은 여기서 보이지 않는다. 그 경로는 아래 테스트가 따로 본다.
    """
    TestClient(_app_raising_an_error_that_carries_a_key(), raise_server_exceptions=False).get("/boom")

    assert "unhandled error" in captured.raw
    assert "LEAKCHECK" not in captured.raw


def test_an_api_key_in_the_traceback_uvicorn_writes_after_the_rethrow_is_masked(uvicorn_stderr):
    """예외 처리기가 응답을 만든 뒤에도 예외는 서버까지 올라가고, uvicorn이 traceback을 한 번 더 쓴다.

    앱 로거의 핸들러만 가리면 uvicorn이 자기 로거와 포매터로 쓰는 이 기록에는 키 원문이 남는다.
    예외가 실제로 다시 던져지는지 확인한 뒤, uvicorn의 HTTP 프로토콜 구현이 쓰는 호출 그대로
    `uvicorn.error` 로거에 기록한다.
    """
    with pytest.raises(ConnectionError) as rethrown:
        TestClient(_app_raising_an_error_that_carries_a_key()).get("/boom")

    logging.getLogger("uvicorn.error").error("Exception in ASGI application\n", exc_info=rethrown.value)

    written = uvicorn_stderr.getvalue()
    assert "Exception in ASGI application" in written
    assert "Illegal header value" in written
    assert "LEAKCHECK" not in written


def test_formatter_masks_api_key_shaped_values_in_messages(captured):
    """메시지 인자로 키 형태 값이 들어가도 가려서 기록한다. 호출자의 실수가 로그로 새지 않게 한다."""
    logging.getLogger("loan_agent.test_masking").error("provider rejected %s", "sk-LEAKCHECK0123456789")

    assert "provider rejected" in captured.raw
    assert "LEAKCHECK" not in captured.raw


def test_masking_leaves_words_that_merely_end_in_sk_intact(captured):
    """키 형태는 단어 경계에서 시작해야 한다. 경계가 없으면 `risk-`·`task-`로 끝나는 일반 문구가 가려진다."""
    phrases = ["risk-assessment-pipeline started", "task-scheduler-backlog", "disk-usage-12345678"]
    logger = logging.getLogger("loan_agent.test_masking")
    for phrase in phrases:
        logger.info(phrase)

    assert [line["message"] for line in captured.lines()] == phrases


def test_a_key_right_after_a_line_break_is_still_masked(captured):
    """경계는 원래 문자열에서 판단한다. 줄바꿈 바로 뒤의 키와, 이스케이프된 `\\n` 바로 뒤의 키를 둘 다 가린다.

    JSON으로 직렬화한 줄이나 `repr` 문자열에서는 줄바꿈이 `\\` `n` 두 글자가 되어 키가 영문자 뒤에
    붙은 것처럼 보인다. 그 상태에서 경계를 걸면 이 키를 놓친다.
    """
    logger = logging.getLogger("loan_agent.test_masking")
    logger.error("first line\nsk-LEAKCHECK0123456789")
    logger.error("header b'\\nsk-LEAKCHECK9876543210'")

    assert len(captured.lines()) == 2
    assert "LEAKCHECK" not in captured.raw


def test_a_key_right_after_a_percent_escape_is_still_masked(captured):
    """URL에 실린 문자열은 구분 기호가 `%3D`·`%20`처럼 인코딩되어, 키가 영숫자 바로 뒤에 붙은 것처럼 보인다."""
    logger = logging.getLogger("loan_agent.test_masking")
    logger.error("GET /x?q=api_key%3Dsk-proj-LEAKCHECK0123456789")
    logger.error("header Bearer%20sk-proj-LEAKCHECK9876543210")

    assert len(captured.lines()) == 2
    assert "LEAKCHECK" not in captured.raw


def test_a_malformed_log_call_neither_raises_nor_leaks_a_key(captured, capsys):
    """형식 문자열과 인자가 맞지 않는 호출도 호출한 코드로 예외를 던지지 않고, 인자의 키를 흘리지 않는다.

    `logging`은 형식 오류를 기록 단계에서 잡아 표준 오류에 보고하고 넘어간다. 가림 필터는 그보다 앞서
    메시지를 만들어 보므로, 거기서 난 예외를 놓치면 로그 한 줄 때문에 요청 처리가 실패한다. 표준 보고는
    인자를 그대로 찍으므로 넘겨 버리면 키가 표준 오류로 샌다.
    """
    class Unprintable:
        def __str__(self):
            raise RuntimeError("cannot render")

        __repr__ = __str__

    logger = logging.getLogger("loan_agent.test_masking")
    logger.error("%(missing)s", {"present": "sk-proj-LEAKCHECK0123456789"})
    logger.error("value %s", Unprintable())

    assert len(captured.lines()) == 2
    assert "LEAKCHECK" not in captured.raw
    assert "LEAKCHECK" not in capsys.readouterr().err


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
            text(
                "SELECT target_id FROM audit_event"
                " WHERE correlation_id = :cid AND action = 'assessment.created'"
            ),
            {"cid": line["correlation_id"]},
        ).scalar_one()
    assert str(target_id) == response.json()["assessment_id"]


def test_the_server_log_config_writes_one_json_line_per_record(uvicorn_stderr):
    """서버 자체 로그도 한 줄 JSON이어야 앱 로그와 시간순으로 합쳐 읽을 수 있다.

    기본 설정은 평문이고 traceback은 여러 줄이라, 수집기가 줄 단위로 읽으면 한 기록이 여러 조각으로
    흩어진다. 기동 명령이 넘기는 설정 파일을 그대로 적용해 확인한다.
    """
    import pathlib

    config = json.loads(
        (pathlib.Path(__file__).resolve().parents[1] / "loan_agent" / "uvicorn_log.json").read_text(
            encoding="utf-8"
        )
    )
    config["handlers"]["default"]["stream"] = uvicorn_stderr
    logging.config.dictConfig(config)

    logging.getLogger("uvicorn.error").info("Application startup complete.")

    [entry] = [json.loads(line) for line in uvicorn_stderr.getvalue().splitlines()]
    assert entry["message"] == "Application startup complete."
    assert entry["logger"] == "uvicorn.error"


def test_the_server_log_config_still_masks_keys_in_a_traceback(uvicorn_stderr):
    """로그 형식을 바꿔도 가림은 그대로여야 한다.

    가림은 포매터가 아니라 핸들러 필터이고, 앱이 설정될 때 서버 로거의 핸들러에 붙는다. 서버 쪽
    설정을 갈아 끼우면 그 핸들러가 새것으로 바뀌므로, 이 순서가 유지되는지 형식 교체와 함께 본다.
    """
    import pathlib

    config = json.loads(
        (pathlib.Path(__file__).resolve().parents[1] / "loan_agent" / "uvicorn_log.json").read_text(
            encoding="utf-8"
        )
    )
    config["handlers"]["default"]["stream"] = uvicorn_stderr
    logging.config.dictConfig(config)
    logs.configure(stream=io.StringIO())

    with pytest.raises(ConnectionError) as rethrown:
        TestClient(_app_raising_an_error_that_carries_a_key()).get("/boom")
    logging.getLogger("uvicorn.error").error("Exception in ASGI application", exc_info=rethrown.value)

    [entry] = [json.loads(line) for line in uvicorn_stderr.getvalue().splitlines()]
    assert "Illegal header value" in entry["exception"]
    assert "LEAKCHECK" not in uvicorn_stderr.getvalue()


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
