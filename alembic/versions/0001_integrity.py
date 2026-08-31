"""정합성 스키마 — 테이블·PK·FK·UNIQUE·CHECK만.

조회 성능용 복합 인덱스는 여기 넣지 않는다(ADR-014). 나중 마이그레이션으로 분리해야
합성 이력 1만 건을 넣고 인덱스 전후를 실제로 측정할 수 있다. 지금 다 만들면 그
비교가 성립하지 않는다.

순환 FK(assessment_case.current_explanation_run_id ↔ explanation_run.assessment_id)는
두 테이블을 만든 뒤 FK를 따로 붙여 푼다. 런타임에서 이 포인터는 통과한 설명이 생겼을
때만 채워지므로 실제로는 순환하지 않는다(데이터 모델 §3).

Revision ID: 0001_integrity
Revises:
Create Date: 2026-08-28
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_integrity"
down_revision = None
branch_labels = None
depends_on = None

CASE_STATUSES = ("SCREENED", "COMPLETED", "EXPLANATION_FAILED", "REVIEW_REQUIRED")
RUN_STATUSES = ("PENDING", "RUNNING", "COMPLETED", "FAILED", "REVIEW_REQUIRED")
VERDICTS = ("ELIGIBLE", "CONDITIONAL", "INELIGIBLE")


def _in(column, values):
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


def upgrade() -> None:
    op.create_table(
        "assessment_case",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "current_explanation_run_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("monthly_income", sa.BigInteger(), nullable=False),
        sa.Column("existing_debt", sa.BigInteger(), nullable=False),
        sa.Column("credit_grade", sa.Integer(), nullable=False),
        sa.Column("requested_amount", sa.BigInteger(), nullable=False),
        sa.Column("employment_type", sa.Text(), nullable=False),
        sa.Column("collateral_owned", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_assessment_idempotency_key"),
        sa.CheckConstraint(_in("status", CASE_STATUSES), name="ck_status_valid"),
        sa.CheckConstraint(
            "credit_grade BETWEEN 1 AND 10", name="ck_credit_grade_range"
        ),
        sa.CheckConstraint(
            "monthly_income >= 0 AND existing_debt >= 0 AND requested_amount >= 0",
            name="ck_assessment_amounts_nonneg",
        ),
    )

    op.create_table(
        "explanation_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessment_case.id"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("explanation_text", sa.Text(), nullable=True),
        sa.CheckConstraint(_in("status", RUN_STATUSES), name="ck_run_status_valid"),
    )

    op.create_foreign_key(
        "fk_case_current_run",
        "assessment_case",
        "explanation_run",
        ["current_explanation_run_id"],
        ["id"],
    )

    # 진행 중 실행은 심사당 최대 하나(ADR-019). 앱은 409, 이 인덱스가 최종 방어선.
    op.create_index(
        "uq_explanation_run_in_flight",
        "explanation_run",
        ["assessment_id"],
        unique=True,
        postgresql_where=sa.text(_in("status", ("PENDING", "RUNNING"))),
    )

    op.create_table(
        "decision_result",
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessment_case.id"),
            primary_key=True,
        ),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("repayment_band", sa.Text(), nullable=False),
        sa.Column("dsr", sa.Numeric(), nullable=False),
        sa.Column("monthly_payment", postgresql.JSONB(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("product_dataset_version", sa.Text(), nullable=False),
        sa.Column(
            "decided_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_in("verdict", VERDICTS), name="ck_verdict_valid"),
        sa.CheckConstraint("dsr >= 0", name="ck_dsr_nonneg"),
    )

    op.create_table(
        "recommendation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessment_case.id"),
            nullable=False,
        ),
        sa.Column("product_code", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "assessment_id", "product_code", name="uq_recommendation_product"
        ),
        sa.CheckConstraint("rank >= 1", name="ck_recommendation_rank_positive"),
    )

    # 부분 UNIQUE로 두는 근거는 models.Recommendation에 적혀 있다.
    op.create_index(
        "uq_recommendation_rank",
        "recommendation",
        ["assessment_id", "rank"],
        unique=True,
        postgresql_where=sa.text("eligible"),
    )

    op.create_table(
        "eval_result",
        sa.Column(
            "explanation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("explanation_run.id"),
            primary_key=True,
        ),
        sa.Column("parse_accuracy", sa.Boolean(), nullable=False),
        sa.Column("verdict_consistency", sa.Boolean(), nullable=False),
        sa.Column("disclaimer_present", sa.Boolean(), nullable=False),
        sa.Column("recommendation_consistency", sa.Boolean(), nullable=False),
        sa.Column("numeric_grounding", sa.Boolean(), nullable=False),
        sa.Column("conditional_language", sa.Boolean(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
    )

    # 감사 이력은 대상이 삭제돼도 남아야 하므로 FK를 걸지 않는다(데이터 모델 §2).
    op.create_table(
        "audit_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "occurred_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_event")
    op.drop_table("eval_result")
    op.drop_index("uq_recommendation_rank", table_name="recommendation")
    op.drop_table("recommendation")
    op.drop_table("decision_result")
    op.drop_constraint("fk_case_current_run", "assessment_case", type_="foreignkey")
    op.drop_index("uq_explanation_run_in_flight", table_name="explanation_run")
    op.drop_table("explanation_run")
    op.drop_table("assessment_case")
