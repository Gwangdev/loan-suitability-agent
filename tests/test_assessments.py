"""POST /api/v1/assessments — 결정적 판정을 한 트랜잭션에 저장하고 중복 요청을 막는다.

수용 기준을 명세(SPEC.yaml R1/R2, 오류 코드 정책)와 데이터 모델(§1·§4·§5)에서
그대로 옮긴다. 핵심 두 가지는 「한 요청이 다섯 테이블을 원자적으로 채운다」와
「같은 Idempotency-Key로 무엇을 해도 심사는 정확히 하나」다. 뒤의 것은 병렬 요청
테스트가 없으면 무증거로 남으므로(ADR-004) 함께 둔다.
"""
import concurrent.futures
from decimal import Decimal
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from loan_agent.api import app

client = TestClient(app)

VALID_BODY = {
    "monthly_income": 7_000_000,
    "existing_debt": 0,
    "credit_grade": 1,
    "requested_amount": 30_000_000,
    "employment_type": "정규직",
    "collateral_owned": False,
}


def _key():
    return f"test-{uuid.uuid4()}"


def _counts(engine, assessment_id):
    with engine.connect() as conn:
        return {
            table: conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :id"),
                {"id": str(assessment_id)},
            ).scalar()
            for table, column in (
                ("assessment_case", "id"),
                ("decision_result", "assessment_id"),
                ("recommendation", "assessment_id"),
                ("explanation_run", "assessment_id"),
                ("audit_event", "target_id"),
            )
        }


def test_create_returns_deterministic_decision(api_db):
    r = client.post("/api/v1/assessments", json=VALID_BODY, headers={"Idempotency-Key": _key()})

    assert r.status_code == 201
    body = r.json()
    assert body["decision"]["verdict"] == "ELIGIBLE"
    assert body["decision"]["dsr"] >= 0
    assert body["decision"]["rule_version"]
    assert body["decision"]["product_dataset_version"]
    assert body["recommendations"]
    assert body["recommendations"][0]["product_name"]
    assert body["recommendations"][0]["bank"]
    assert body["recommendations"][0]["interest_rate_range"]
    assert body["recommendations"][0]["maximum_limit"]
    assert body["explanation_runs"][0]["status"] == "PENDING"


def test_dsr_round_trips_from_postgresql_as_decimal(api_db):
    """Numeric 컬럼의 읽기 타입은 실제 DB 왕복 결과로 고정한다."""
    r = client.post("/api/v1/assessments", json=VALID_BODY, headers={"Idempotency-Key": _key()})
    assessment_id = r.json()["assessment_id"]

    with api_db.connect() as conn:
        dsr = conn.execute(
            text("SELECT dsr FROM decision_result WHERE assessment_id = :id"),
            {"id": assessment_id},
        ).scalar()

    assert isinstance(dsr, Decimal)


def test_single_transaction_persists_every_row(api_db):
    r = client.post("/api/v1/assessments", json=VALID_BODY, headers={"Idempotency-Key": _key()})
    assessment_id = r.json()["assessment_id"]

    counts = _counts(api_db, assessment_id)
    assert counts["assessment_case"] == 1
    assert counts["decision_result"] == 1
    assert counts["recommendation"] >= 1
    assert counts["explanation_run"] == 1
    assert counts["audit_event"] >= 1

    with api_db.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM assessment_case WHERE id = :id"),
            {"id": assessment_id},
        ).scalar()
        run_status = conn.execute(
            text("SELECT status FROM explanation_run WHERE assessment_id = :id"),
            {"id": assessment_id},
        ).scalar()
    assert status == "SCREENED"
    assert run_status == "PENDING"


def test_missing_idempotency_key_is_422(api_db):
    r = client.post("/api/v1/assessments", json=VALID_BODY)

    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


def test_out_of_range_field_is_422(api_db):
    r = client.post(
        "/api/v1/assessments",
        json={**VALID_BODY, "credit_grade": 11},
        headers={"Idempotency-Key": _key()},
    )

    assert r.status_code == 422


def test_same_key_same_body_returns_existing(api_db):
    key = _key()
    first = client.post("/api/v1/assessments", json=VALID_BODY, headers={"Idempotency-Key": key})
    second = client.post("/api/v1/assessments", json=VALID_BODY, headers={"Idempotency-Key": key})

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["assessment_id"] == second.json()["assessment_id"]

    counts = _counts(api_db, first.json()["assessment_id"])
    assert counts["assessment_case"] == 1
    assert counts["explanation_run"] == 1


def test_same_key_different_body_is_409(api_db):
    key = _key()
    client.post("/api/v1/assessments", json=VALID_BODY, headers={"Idempotency-Key": key})
    conflict = client.post(
        "/api/v1/assessments",
        json={**VALID_BODY, "requested_amount": 40_000_000},
        headers={"Idempotency-Key": key},
    )

    assert conflict.status_code == 409
    assert conflict.headers["content-type"].startswith("application/problem+json")


def test_llm_is_never_called_on_this_path(api_db, monkeypatch):
    """설명 생성은 PENDING 행으로 미뤄지고 LLM은 이 경로에서 호출되지 않는다(ADR-003)."""
    def _boom(*_a, **_k):
        raise AssertionError("이 경로에서 LLM을 불러서는 안 된다")

    # 안내문 생성 진입점 두 곳만 막으면 된다. 3-Agent 파이프라인은 코드에서 삭제됐으므로
    # 감시할 대상이 없고, 그 부재 자체를 아래에서 단언한다.
    monkeypatch.setattr("loan_agent.llm.get_llm", _boom)
    monkeypatch.setattr("loan_agent.llm.generate_guidance", _boom)
    monkeypatch.setattr("loan_agent.llm.parse_with_llm", _boom)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    r = client.post("/api/v1/assessments", json=VALID_BODY, headers={"Idempotency-Key": _key()})

    assert r.status_code == 201


def test_the_superseded_pipeline_is_gone_from_the_module():
    """옛 3-Agent 진입점이 되살아나면 여기서 걸린다.

    호출을 감시하는 것보다 부재를 단언하는 편이 강한 보장이다 — 감시는 그 경로를 지나갈
    때만 작동하지만, 부재는 어느 경로에서도 부를 수 없다는 뜻이다(ADR-030).
    """
    from loan_agent import core

    for name in ("get_crew", "build_fresh_crew", "run_service", "run_service_with_stages",
                 "build_tasks", "build_reviewer_agent", "build_advisor_agent"):
        assert not hasattr(core, name), f"삭제한 3-Agent 진입점이 되살아났다: {name}"


def test_parallel_same_key_creates_exactly_one_assessment(api_db):
    """같은 Idempotency-Key로 병렬 요청 N개 — 심사는 정확히 1건이어야 한다(T1 #9).

    선조회는 최적화일 뿐 보장이 아니다. READ COMMITTED에서 조회와 삽입 사이에
    경쟁이 있으므로, 이 테스트가 통과하려면 DB의 UNIQUE 제약이 최종 방어선으로
    실제 동작해야 한다(ADR-004).
    """
    key = _key()
    workers = 8

    def _post():
        return client.post(
            "/api/v1/assessments", json=VALID_BODY, headers={"Idempotency-Key": key}
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        responses = [f.result() for f in [pool.submit(_post) for _ in range(workers)]]

    assert all(r.status_code in (200, 201) for r in responses), [r.status_code for r in responses]
    ids = {r.json()["assessment_id"] for r in responses}
    assert len(ids) == 1

    with api_db.connect() as conn:
        cases = conn.execute(
            text("SELECT count(*) FROM assessment_case WHERE idempotency_key = :k"),
            {"k": key},
        ).scalar()
        runs = conn.execute(
            text(
                "SELECT count(*) FROM explanation_run WHERE assessment_id = :id"
            ),
            {"id": ids.pop()},
        ).scalar()
    assert cases == 1
    assert runs == 1
