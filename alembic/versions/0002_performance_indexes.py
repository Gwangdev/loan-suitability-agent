"""조회 성능 인덱스 — 정합성 마이그레이션과 분리한다(ADR-014).

분리해야 §18의 인덱스 전후 EXPLAIN ANALYZE 비교가 성립한다. 합성 이력 1만 건을 넣은
뒤 이 마이그레이션을 적용하기 전과 후를 재는 것이 목적이다.

컬럼 순서 근거(데이터 모델 §6): 등호 조건을 앞에, 범위·정렬을 뒤에 둔다.
(status, created_at DESC, id DESC)는 WHERE status = ? 로 좁힌 뒤 그 안에서 이미
정렬된 상태로 읽히므로 필터와 정렬을 인덱스 하나로 처리한다. id가 마지막에 붙는
이유는 created_at이 유일하지 않아 같은 시각 레코드에서 커서가 흔들리기 때문이다 —
유일 컬럼을 tiebreaker로 붙여야 커서가 안정적이다.

recommendation(assessment_id, rank)는 넣지 않는다. 0001의 부분 UNIQUE가 이미 같은
컬럼으로 인덱스를 만든다. 중복 인덱스는 쓰기 비용만 늘린다.

Revision ID: 0002_performance_indexes
Revises: 0001_integrity
Create Date: 2026-08-28
"""
import sqlalchemy as sa

from alembic import op

revision = "0002_performance_indexes"
down_revision = "0001_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_assessment_case_cursor",
        "assessment_case",
        [sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_assessment_case_status_cursor",
        "assessment_case",
        ["status", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_explanation_run_history",
        "explanation_run",
        ["assessment_id", sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_audit_event_trace",
        "audit_event",
        ["correlation_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_event_trace", table_name="audit_event")
    op.drop_index("ix_explanation_run_history", table_name="explanation_run")
    op.drop_index("ix_assessment_case_status_cursor", table_name="assessment_case")
    op.drop_index("ix_assessment_case_cursor", table_name="assessment_case")
