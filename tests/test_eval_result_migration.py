"""이미 저장된 채점 행을 「채점하지 않음」으로 되돌리는 마이그레이션을 실제 PostgreSQL에서 확인한다.

채점 행을 쓰는 경로는 설명 실행 하나뿐이었고, 그 경로는 파싱정확도를 항상 통과로 채웠다. 그러니 기존 행의
통과 값은 전부 채점의 부재였고 행마다 판단할 것이 없다. 마이그레이션은 값을 비우고 근거에 남은 파싱 실패
문구를 지운다. 공개 여부(`passed`)는 원래도 나머지 지표만으로 정해졌으므로 건드리지 않는다.
되돌릴 때는 이전 스키마가 기대하던 대로 통과 값과 NOT NULL을 복원한다.
"""
import datetime
import json
import uuid

from alembic import command
from sqlalchemy import text
from sqlalchemy.orm import Session

from loan_agent.db import models
from tests.conftest import _APP_TABLES, _alembic_config

BEFORE = "0003_dsr_numeric_precision"


def _stored_row(engine) -> uuid.UUID:
    now = datetime.datetime.now(datetime.timezone.utc)
    with Session(bind=engine) as session, session.begin():
        case = models.AssessmentCase(
            idempotency_key=str(uuid.uuid4()), request_hash="h", status="REVIEW_REQUIRED",
            monthly_income=7_000_000, existing_debt=0, credit_grade=1,
            requested_amount=30_000_000, employment_type="정규직", collateral_owned=False,
        )
        session.add(case)
        session.flush()
        session.add(models.DecisionResult(
            assessment_id=case.id, verdict="ELIGIBLE", repayment_band="여유", dsr=0.083,
            monthly_payment={}, rule_version="r", product_dataset_version="p",
        ))
        run = models.ExplanationRun(
            assessment_id=case.id, status="REVIEW_REQUIRED", started_at=now, finished_at=now,
        )
        session.add(run)
        session.flush()
        session.execute(
            text(
                "INSERT INTO eval_result (explanation_run_id, parse_accuracy, verdict_consistency,"
                " disclaimer_present, recommendation_consistency, numeric_grounding,"
                " conditional_language, passed, detail)"
                " VALUES (:id, TRUE, TRUE, TRUE, TRUE, FALSE, TRUE, FALSE, CAST(:detail AS JSONB))"
            ),
            {"id": run.id, "detail": json.dumps(
                {"파싱정확도": "Agent1 출력 JSON 파싱 실패", "수치근거": "근거 없는 금리"}, ensure_ascii=False,
            )},
        )
        return run.id


def _read(engine, run_id):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT parse_accuracy, passed, detail FROM eval_result WHERE explanation_run_id = :id"),
            {"id": run_id},
        ).one()


def _parse_accuracy_nullable(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT is_nullable FROM information_schema.columns"
            " WHERE table_name = 'eval_result' AND column_name = 'parse_accuracy'"
        )).scalar_one()


def test_existing_scores_become_unscored_and_downgrade_restores_the_old_shape(_migrated_db):
    cfg = _alembic_config()
    command.downgrade(cfg, BEFORE)
    try:
        run_id = _stored_row(_migrated_db)

        command.upgrade(cfg, "head")
        upgraded = _read(_migrated_db, run_id)
        assert upgraded.parse_accuracy is None
        assert upgraded.detail == {"수치근거": "근거 없는 금리"}
        assert upgraded.passed is False
        assert _parse_accuracy_nullable(_migrated_db) == "YES"

        command.downgrade(cfg, BEFORE)
        assert _read(_migrated_db, run_id).parse_accuracy is True
        assert _parse_accuracy_nullable(_migrated_db) == "NO"
    finally:
        command.upgrade(cfg, "head")
        with _migrated_db.begin() as conn:
            conn.execute(text("TRUNCATE " + ", ".join(_APP_TABLES) + " CASCADE"))
