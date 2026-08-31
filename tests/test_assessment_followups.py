"""심사 읽기·설명 재생성·파싱 미리보기·데모 열람의 수용 기준."""
import datetime
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from loan_agent.api import app

client = TestClient(app)

BODY = {
    "monthly_income": 7_000_000,
    "existing_debt": 0,
    "credit_grade": 1,
    "requested_amount": 30_000_000,
    "employment_type": "정규직",
    "collateral_owned": False,
}


def _assessment(api_db, **changes):
    response = client.post(
        "/api/v1/assessments",
        json={**BODY, **changes},
        headers={"Idempotency-Key": f"followup-{uuid.uuid4()}"},
    )
    assert response.status_code == 201
    return response.json()


def test_get_assessment_returns_decision_explanation_and_versions(api_db):
    created = _assessment(api_db)

    response = client.get(f"/api/v1/assessments/{created['assessment_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["assessment_id"] == created["assessment_id"]
    assert body["decision"]["rule_version"]
    assert body["decision"]["product_dataset_version"]
    assert body["explanation_runs"][0]["status"] == "PENDING"
    assert "eval_result" in body["explanation_runs"][0]


def test_get_missing_assessment_returns_problem_404(api_db):
    response = client.get(f"/api/v1/assessments/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_list_assessments_is_cursor_paginated_and_empty_is_an_array(api_db):
    assert client.get("/api/v1/assessments").json() == {"items": [], "next_cursor": None}
    first = _assessment(api_db)
    second = _assessment(api_db, requested_amount=20_000_000)

    page = client.get("/api/v1/assessments?limit=1")
    assert page.status_code == 200
    assert len(page.json()["items"]) == 1
    assert page.json()["next_cursor"]

    following = client.get(
        "/api/v1/assessments",
        params={"limit": 1, "cursor": page.json()["next_cursor"]},
    )
    ids = {first["assessment_id"], second["assessment_id"]}
    assert following.status_code == 200
    assert following.json()["items"][0]["assessment_id"] in ids
    assert following.json()["items"][0]["assessment_id"] != page.json()["items"][0]["assessment_id"]


def test_list_assessments_filters_status_and_rejects_limit_above_100(api_db):
    _assessment(api_db)

    assert client.get("/api/v1/assessments?status=COMPLETED").json()["items"] == []
    assert client.get("/api/v1/assessments?limit=101").status_code == 422


def test_regeneration_creates_pending_run_only_after_prior_run_finishes(api_db):
    created = _assessment(api_db)
    assessment_id = created["assessment_id"]

    blocked = client.post(f"/api/v1/assessments/{assessment_id}/explanation-runs")
    assert blocked.status_code == 409

    with api_db.begin() as conn:
        conn.execute(
            text("UPDATE explanation_run SET status = 'FAILED' WHERE assessment_id = :id"),
            {"id": assessment_id},
        )
    retried = client.post(f"/api/v1/assessments/{assessment_id}/explanation-runs")
    assert retried.status_code == 201
    assert retried.json()["status"] == "PENDING"


def _passing_explanation(monkeypatch):
    """외부 호출 없이 동기 실행 경로의 행 상태 전이만 검증한다."""
    from loan_agent import worker

    monkeypatch.setattr(
        worker,
        "generate_explanation",
        lambda *_args, **_kwargs: worker.Explanation(
            text="검토 결과 승인 가능한 것으로 판단됩니다(데모 기준).",
            model_name="test-model",
            prompt_version="test-prompt",
            input_tokens=1,
            output_tokens=1,
        ),
    )
    monkeypatch.setattr(
        worker,
        "score_explanation",
        lambda *_args: worker.Score(
            checks={name: True for name in worker.EVAL_METRICS}, passed=True, detail={}
        ),
    )


def test_visitor_key_claims_existing_pending_and_returns_completed_run(api_db, monkeypatch):
    _passing_explanation(monkeypatch)
    created = _assessment(api_db)

    response = client.post(
        f"/api/v1/assessments/{created['assessment_id']}/explanation-runs",
        headers={"X-OpenAI-API-Key": "visitor-test-key"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"


def test_visitor_key_rejects_a_fresh_running_run(api_db):
    created = _assessment(api_db)
    with api_db.begin() as conn:
        conn.execute(
            text("UPDATE explanation_run SET status = 'RUNNING', started_at = now() WHERE assessment_id = :id"),
            {"id": created["assessment_id"]},
        )

    response = client.post(
        f"/api/v1/assessments/{created['assessment_id']}/explanation-runs",
        headers={"X-OpenAI-API-Key": "visitor-test-key"},
    )

    assert response.status_code == 409


def test_visitor_key_reclaims_a_stale_running_run(api_db, monkeypatch):
    from loan_agent import worker

    _passing_explanation(monkeypatch)
    created = _assessment(api_db)
    stale = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=worker.RUN_TIMEOUT_SECONDS + 1
    )
    with api_db.begin() as conn:
        conn.execute(
            text("UPDATE explanation_run SET status = 'RUNNING', started_at = :started_at WHERE assessment_id = :id"),
            {"id": created["assessment_id"], "started_at": stale},
        )

    response = client.post(
        f"/api/v1/assessments/{created['assessment_id']}/explanation-runs",
        headers={"X-OpenAI-API-Key": "visitor-test-key"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"


def test_visitor_key_provider_failure_keeps_deterministic_decision(api_db, monkeypatch):
    from loan_agent import worker

    created = _assessment(api_db)
    monkeypatch.setattr(worker, "generate_explanation", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))

    response = client.post(
        f"/api/v1/assessments/{created['assessment_id']}/explanation-runs",
        headers={"X-OpenAI-API-Key": "visitor-test-key"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    with api_db.connect() as conn:
        assert conn.execute(
            text("SELECT verdict FROM decision_result WHERE assessment_id = :id"),
            {"id": created["assessment_id"]},
        ).scalar() == "ELIGIBLE"


def test_visitor_key_timeout_returns_the_existing_503_contract(monkeypatch):
    from loan_agent import worker

    def _timeout(*_args, **_kwargs):
        raise worker.ExplanationTimedOut(uuid.uuid4())

    monkeypatch.setattr(worker, "run_for_visitor", _timeout)

    response = client.post(
        f"/api/v1/assessments/{uuid.uuid4()}/explanation-runs",
        headers={"X-OpenAI-API-Key": "test"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")


def test_explanation_history_exposes_metadata_without_raw_prompt(api_db):
    created = _assessment(api_db)

    response = client.get(f"/api/v1/assessments/{created['assessment_id']}/explanation-runs")

    assert response.status_code == 200
    run = response.json()["items"][0]
    assert {"model_name", "prompt_version", "latency_ms", "input_tokens", "output_tokens", "error_code"} <= set(run)
    assert "prompt" not in run


def test_parsing_preview_returns_candidates_and_missing_without_persisting(api_db):
    with api_db.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM assessment_case")).scalar()
    response = client.post("/api/v1/parsing-preview", json={"text": "월소득 300만원입니다."})
    with api_db.connect() as conn:
        after = conn.execute(text("SELECT count(*) FROM assessment_case")).scalar()

    assert response.status_code == 200
    assert response.json()["missing_fields"]
    assert response.json()["rule_candidate"]["월소득"] == 3_000_000
    assert before == after


def test_demo_cases_return_recorded_output_without_an_api_key():
    response = client.get("/api/v1/demo-cases")

    assert response.status_code == 200
    assert response.json()["cases"]
