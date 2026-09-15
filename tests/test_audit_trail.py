"""감사 추적 — 요청에서 실행 결과까지 같은 기록 줄기로 이어지는지 고정한다.

감사 이벤트는 심사 생성 한 곳에만 있었다. 데이터 모델은 이 테이블의 인덱스를 「요청 하나를
API→AI→Eval로 추적」하는 용도로 정의했는데, 설명 실행을 요청한 사실도 그 결과도 기록되지 않아
추적이 API 한 칸에서 끊겼다. 실행 행을 대상으로 요청과 결과를 남기면, 요청 식별자로 시작해 실행 행을
거쳐 결과까지 이어진다.

워커는 요청 밖에서 돌아 이어받을 식별자가 없다. 실행마다 새로 만들어 그 실행의 로그와 결과 이벤트가
같은 값을 갖게 한다. 방문자 동기 경로는 요청 안에서 돌므로 그 요청의 식별자를 그대로 쓴다. 두 경로
모두 실행 행을 대상으로 기록하므로, 어느 쪽이든 실행 행 하나로 앞뒤가 이어진다.
"""
import io
import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from loan_agent import audit, logs, worker
from loan_agent.api import app, request_log
from loan_agent.db import models

client = TestClient(app)

BODY = {
    "monthly_income": 7_000_000,
    "existing_debt": 0,
    "credit_grade": 1,
    "requested_amount": 30_000_000,
    "employment_type": "정규직",
    "collateral_owned": False,
}


@pytest.fixture()
def captured():
    stream = io.StringIO()
    logs.configure(stream=stream)
    yield stream
    logs.configure()


_SELECT_EVENTS = (
    "SELECT action, actor_type, target_type, target_id, correlation_id, metadata"
    " FROM audit_event"
)


def _events(engine, correlation_id=None):
    """감사 이벤트를 시간순으로 읽는다. 조건은 고정 문장 두 개로 두고 값만 바인딩한다."""
    statement = text(
        f"{_SELECT_EVENTS} ORDER BY occurred_at"
        if correlation_id is None
        else f"{_SELECT_EVENTS} WHERE correlation_id = :correlation_id ORDER BY occurred_at"
    )
    params = {} if correlation_id is None else {"correlation_id": str(correlation_id)}
    with engine.connect() as conn:
        return [row._mapping for row in conn.execute(statement, params).all()]


def _request_correlation(captured) -> str:
    """마지막 요청 한 줄의 식별자. 준비 단계의 요청도 같은 스트림에 쌓이므로 가장 최근 것을 본다."""
    lines = [json.loads(line) for line in captured.getvalue().splitlines()]
    return [line for line in lines if line["logger"] == request_log.__name__][-1]["correlation_id"]


def _create(api_db):
    response = client.post(
        "/api/v1/assessments", json=BODY, headers={"Idempotency-Key": f"audit-{uuid.uuid4()}"}
    )
    assert response.status_code == 201
    return response.json()["assessment_id"]


def _passing_explanation(monkeypatch):
    from tests.test_eval import GOOD_ADVICE

    monkeypatch.setattr(
        worker, "generate_explanation",
        lambda *_args, **_kwargs: worker.Explanation(
            text=GOOD_ADVICE, model_name="test-model", prompt_version="test-prompt",
            input_tokens=1, output_tokens=1,
        ),
    )


def test_creating_an_assessment_records_the_case_and_the_requested_run(api_db, captured):
    assessment_id = _create(api_db)
    correlation = _request_correlation(captured)

    events = _events(api_db, correlation_id=correlation)

    assert [event["action"] for event in events] == ["assessment.created", "explanation_run.requested"]
    assert str(events[0]["target_id"]) == assessment_id
    assert events[1]["target_type"] == "explanation_run"


def test_a_rejected_regeneration_records_nothing(api_db):
    assessment_id = _create(api_db)
    before = len(_events(api_db))

    assert client.post(f"/api/v1/assessments/{assessment_id}/explanation-runs").status_code == 409

    assert len(_events(api_db)) == before


def test_an_accepted_regeneration_records_the_new_run(api_db, captured):
    assessment_id = _create(api_db)
    with api_db.begin() as conn:
        conn.execute(
            text("UPDATE explanation_run SET status = 'FAILED' WHERE assessment_id = :id"),
            {"id": assessment_id},
        )

    response = client.post(f"/api/v1/assessments/{assessment_id}/explanation-runs")
    assert response.status_code == 201

    events = _events(api_db, correlation_id=_request_correlation(captured))
    assert [event["action"] for event in events] == ["explanation_run.requested"]
    assert str(events[0]["target_id"]) == response.json()["id"]


def test_a_visitor_run_records_its_outcome_under_the_request_correlation(api_db, captured, monkeypatch):
    _passing_explanation(monkeypatch)
    assessment_id = _create(api_db)

    response = client.post(
        f"/api/v1/assessments/{assessment_id}/explanation-runs",
        headers={"X-OpenAI-API-Key": "visitor-test-key"},
    )
    assert response.status_code == 200

    events = _events(api_db, correlation_id=_request_correlation(captured))
    [finished] = [event for event in events if event["action"] == "explanation_run.finished"]
    assert str(finished["target_id"]) == response.json()["id"]
    assert finished["metadata"] == {
        "status": "COMPLETED", "error_code": None, "passed": True, "executor": "app",
    }


def test_a_worker_run_ties_its_log_line_to_its_outcome(api_db, captured, monkeypatch):
    _passing_explanation(monkeypatch)
    first = _create(api_db)
    second = _create(api_db)

    assert worker.run_once() is True
    assert worker.run_once() is True

    finished = [event for event in _events(api_db) if event["action"] == "explanation_run.finished"]
    assert len(finished) == 2
    correlations = {str(event["correlation_id"]) for event in finished}
    assert len(correlations) == 2, "실행마다 식별자를 새로 만들어야 서로 섞이지 않는다"
    logged = {
        json.loads(line)["correlation_id"]
        for line in captured.getvalue().splitlines()
        if json.loads(line).get("run_id")
    }
    assert logged == correlations
    assert {first, second} == {str(event["target_id"]) for event in _events(api_db)
                               if event["action"] == "assessment.created"}


def test_a_discarded_result_records_no_outcome(api_db, monkeypatch):
    _passing_explanation(monkeypatch)
    assessment_id = _create(api_db)
    run_id = worker.claim_one()

    def _reclaimed_by_someone_else(*_args, **_kwargs):
        with api_db.begin() as conn:
            conn.execute(
                text("UPDATE explanation_run SET status = 'PENDING', started_at = NULL WHERE id = :id"),
                {"id": run_id},
            )
        from tests.test_eval import GOOD_ADVICE

        return worker.Explanation(
            text=GOOD_ADVICE, model_name="m", prompt_version="p", input_tokens=None, output_tokens=None,
        )

    monkeypatch.setattr(worker, "generate_explanation", _reclaimed_by_someone_else)
    worker.execute_claimed_run(run_id)

    assert [event for event in _events(api_db) if event["action"] == "explanation_run.finished"] == []


def test_reclaiming_a_stale_run_is_recorded(api_db):
    assessment_id = _create(api_db)
    run_id = worker.claim_one()
    with api_db.begin() as conn:
        conn.execute(
            text("UPDATE explanation_run SET started_at = now() - interval '1 day' WHERE id = :id"),
            {"id": run_id},
        )

    assert worker.reclaim_stale() == 1

    [reclaimed] = [event for event in _events(api_db) if event["action"] == "explanation_run.reclaimed"]
    assert str(reclaimed["target_id"]) == str(run_id)
    assert reclaimed["actor_type"] == "system"


def test_a_visitor_run_created_without_a_pending_row_is_also_recorded_as_requested(api_db, captured, monkeypatch):
    """방문자 경로도 실행 행을 새로 만들 수 있다. 그 사실을 남기지 않으면 결과만 떠 있게 된다."""
    _passing_explanation(monkeypatch)
    assessment_id = _create(api_db)
    with api_db.begin() as conn:
        conn.execute(
            text("UPDATE explanation_run SET status = 'FAILED' WHERE assessment_id = :id"),
            {"id": assessment_id},
        )

    response = client.post(
        f"/api/v1/assessments/{assessment_id}/explanation-runs",
        headers={"X-OpenAI-API-Key": "visitor-test-key"},
    )
    assert response.status_code == 200

    events = _events(api_db, correlation_id=_request_correlation(captured))
    assert [event["action"] for event in events] == [
        "explanation_run.requested", "explanation_run.finished",
    ]
    assert all(str(event["target_id"]) == response.json()["id"] for event in events)


def test_a_visitor_taking_over_a_stale_run_records_the_reclaim(api_db, captured, monkeypatch):
    """상한을 넘긴 실행을 가로채는 것은 워커의 회수와 같은 일이다. 같은 기록을 남겨야 한다."""
    _passing_explanation(monkeypatch)
    assessment_id = _create(api_db)
    stale_run = worker.claim_one()
    with api_db.begin() as conn:
        conn.execute(
            text("UPDATE explanation_run SET started_at = now() - interval '1 day' WHERE id = :id"),
            {"id": stale_run},
        )

    response = client.post(
        f"/api/v1/assessments/{assessment_id}/explanation-runs",
        headers={"X-OpenAI-API-Key": "visitor-test-key"},
    )
    assert response.status_code == 200

    events = _events(api_db, correlation_id=_request_correlation(captured))
    assert [event["action"] for event in events] == [
        "explanation_run.reclaimed", "explanation_run.finished",
    ]
    assert str(events[0]["target_id"]) == str(stale_run)


def test_metadata_keeps_only_allowed_keys():
    filtered = audit.allowed_metadata({"status": "COMPLETED", "안내문": "본문", "api_key": "sk-x"})

    assert filtered == {"status": "COMPLETED"}
