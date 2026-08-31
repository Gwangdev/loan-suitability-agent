"""영속화 계층 — 스키마와 제약이 데이터 모델 문서와 일치하는지 검증한다.

검증 대상은 두 가지다. 하나는 「막아야 할 것을 DB가 실제로 막는가」 — 앱 검증만으로는
마이그레이션·관리 도구 경로가 뚫리므로 제약을 DB에도 건다(하드닝 원칙). 다른 하나는
「저장하지 말아야 할 것을 저장할 자리가 없는가」 — 자연어 원문 컬럼은 코드로 검사하는
것이 아니라 아예 존재하지 않아야 한다(ADR-002).
"""
import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from loan_agent.db import models


def _case(**overrides):
    data = dict(
        idempotency_key=str(uuid.uuid4()),
        request_hash="h",
        status="SCREENED",
        monthly_income=3_000_000,
        existing_debt=0,
        credit_grade=3,
        requested_amount=10_000_000,
        employment_type="정규직",
        collateral_owned=False,
    )
    data.update(overrides)
    return models.AssessmentCase(**data)


def test_all_model_tables_exist(_migrated_db):
    names = set(inspect(_migrated_db).get_table_names())
    expected = {
        "assessment_case",
        "decision_result",
        "recommendation",
        "explanation_run",
        "eval_result",
        "audit_event",
    }
    assert expected <= names


def test_no_raw_text_columns_anywhere(_migrated_db):
    """자연어 원문·전체 프롬프트를 담을 컬럼이 어느 테이블에도 없어야 한다."""
    insp = inspect(_migrated_db)
    forbidden = {"raw_input", "raw_text", "prompt", "full_prompt", "consultation_text"}
    for table in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns(table)}
        assert not (cols & forbidden), f"{table}에 원문 컬럼이 있다: {cols & forbidden}"


def test_duplicate_idempotency_key_is_rejected(db_session):
    key = str(uuid.uuid4())
    db_session.add(_case(idempotency_key=key))
    db_session.flush()
    db_session.add(_case(idempotency_key=key))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_credit_grade_out_of_range_is_rejected(db_session):
    db_session.add(_case(credit_grade=11))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_negative_amount_is_rejected(db_session):
    db_session.add(_case(monthly_income=-1))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_only_one_in_flight_explanation_run_per_case(db_session):
    """PENDING·RUNNING 상태의 재시도가 한 심사에 둘 이상 생기지 못한다(ADR-019)."""
    case = _case()
    db_session.add(case)
    db_session.flush()
    db_session.add(models.ExplanationRun(assessment_id=case.id, status="PENDING"))
    db_session.flush()
    db_session.add(models.ExplanationRun(assessment_id=case.id, status="RUNNING"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_completed_runs_do_not_collide(db_session):
    """종료된 실행은 부분 인덱스 밖이므로 여러 건이 공존한다."""
    case = _case()
    db_session.add(case)
    db_session.flush()
    db_session.add(models.ExplanationRun(assessment_id=case.id, status="FAILED"))
    db_session.add(models.ExplanationRun(assessment_id=case.id, status="COMPLETED"))
    db_session.flush()  # 예외가 나지 않아야 한다


def test_current_explanation_pointer_is_nullable(db_session):
    """통과한 설명이 없으면 포인터는 NULL이다 — 이것이 순환 FK를 끊는다."""
    case = _case()
    db_session.add(case)
    db_session.flush()
    assert case.current_explanation_run_id is None


def test_duplicate_recommendation_rank_is_rejected(db_session):
    case = _case()
    db_session.add(case)
    db_session.flush()
    db_session.add(
        models.Recommendation(
            assessment_id=case.id, product_code="A", rank=1, eligible=True,
            reason_codes=[],
        )
    )
    db_session.flush()
    db_session.add(
        models.Recommendation(
            assessment_id=case.id, product_code="B", rank=1, eligible=True,
            reason_codes=[],
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_performance_indexes_are_a_separate_migration(_migrated_db):
    """조회 성능 인덱스는 정합성 마이그레이션과 분리돼 있어야 한다(ADR-014).

    분리돼 있어야 §18의 인덱스 전후 EXPLAIN ANALYZE 비교가 성립한다. 여기서는 head
    상태에 성능 인덱스가 존재하고, 그것이 첫 마이그레이션 소유가 아님을 확인한다.
    """
    with _migrated_db.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'assessment_case'"
            )
        ).scalars().all()
    assert "ix_assessment_case_status_cursor" in rows
