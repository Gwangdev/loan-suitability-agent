"""영속화 모델 — 스키마의 진실의 원천은 Alembic 마이그레이션이고, 이 파일은 앱이
그 테이블을 다루기 위한 매핑이다. 두 곳이 갈라지지 않도록 제약 이름을 양쪽에서
같게 쓴다.

모델이 지켜야 하는 성격은 데이터 모델 문서 §1에 있다. 그중 이 파일에서 눈에 보이는
것 둘 — 심사와 판정을 다른 테이블로 나눈 것(생명주기가 다르다. 심사는 상태가 변하고
판정은 불변이다)과, 자연어 원문 컬럼이 어디에도 없는 것(저장할 자리가 없으면 실수로
저장할 수 없다).
"""
import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

CASE_STATUSES = ("SCREENED", "COMPLETED", "EXPLANATION_FAILED", "REVIEW_REQUIRED")
RUN_STATUSES = ("PENDING", "RUNNING", "COMPLETED", "FAILED", "REVIEW_REQUIRED")
VERDICTS = ("ELIGIBLE", "CONDITIONAL", "INELIGIBLE")

# 진행 중으로 볼 실행 상태. 부분 UNIQUE 인덱스와 애플리케이션 검사가 같은 목록을
# 봐야 하므로 한자리에 둔다.
IN_FLIGHT_RUN_STATUSES = ("PENDING", "RUNNING")


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _status_check(column: str, values: tuple[str, ...]) -> CheckConstraint:
    joined = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({joined})", name=f"ck_{column}_valid")


class Base(DeclarativeBase):
    pass


class AssessmentCase(Base):
    __tablename__ = "assessment_case"

    id: Mapped[uuid.UUID] = _pk()
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)

    # 통과한 설명이 생겼을 때만 채워진다. NULL 허용이 순환 FK를 끊는다(데이터 모델 §3).
    current_explanation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("explanation_run.id", use_alter=True, name="fk_case_current_run"),
        nullable=True,
    )

    monthly_income: Mapped[int] = mapped_column(BigInteger, nullable=False)
    existing_debt: Mapped[int] = mapped_column(BigInteger, nullable=False)
    credit_grade: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    employment_type: Mapped[str] = mapped_column(Text, nullable=False)
    collateral_owned: Mapped[bool] = mapped_column(Boolean, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_assessment_idempotency_key"),
        _status_check("status", CASE_STATUSES),
        CheckConstraint(
            "credit_grade BETWEEN 1 AND 10", name="ck_credit_grade_range"
        ),
        CheckConstraint(
            "monthly_income >= 0 AND existing_debt >= 0 AND requested_amount >= 0",
            name="ck_assessment_amounts_nonneg",
        ),
    )


class DecisionResult(Base):
    __tablename__ = "decision_result"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_case.id"),
        primary_key=True,
    )
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    repayment_band: Mapped[str] = mapped_column(Text, nullable=False)
    dsr: Mapped[float] = mapped_column(Numeric, nullable=False)
    monthly_payment: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    product_dataset_version: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        _status_check("verdict", VERDICTS),
        CheckConstraint("dsr >= 0", name="ck_dsr_nonneg"),
    )


class Recommendation(Base):
    __tablename__ = "recommendation"

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessment_case.id"), nullable=False
    )
    product_code: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_codes: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "product_code", name="uq_recommendation_product"
        ),
        # 적격 추천만 순위를 다툰다. 부적격은 순위가 없으므로 부분 인덱스로 뺀다.
        Index(
            "uq_recommendation_rank",
            "assessment_id",
            "rank",
            unique=True,
            postgresql_where=text("eligible"),
        ),
        CheckConstraint("rank >= 1", name="ck_recommendation_rank_positive"),
    )


class ExplanationRun(Base):
    __tablename__ = "explanation_run"

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessment_case.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 제공자 오류의 정규화된 코드만 — 원문은 담지 않는다(ADR-002, §10).
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Eval을 통과한 설명만 채워진다(ADR-007).
    explanation_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        _status_check("status", RUN_STATUSES),
        # 같은 심사에 진행 중 실행은 최대 하나(ADR-019). 앱은 409로 거절하고
        # 이 인덱스가 최종 방어선이다.
        Index(
            "uq_explanation_run_in_flight",
            "assessment_id",
            unique=True,
            postgresql_where=text(
                "status IN ("
                + ", ".join(f"'{s}'" for s in IN_FLIGHT_RUN_STATUSES)
                + ")"
            ),
        ),
    )


class EvalResult(Base):
    __tablename__ = "eval_result"

    explanation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("explanation_run.id"),
        primary_key=True,
    )
    parse_accuracy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verdict_consistency: Mapped[bool] = mapped_column(Boolean, nullable=False)
    disclaimer_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recommendation_consistency: Mapped[bool] = mapped_column(Boolean, nullable=False)
    numeric_grounding: Mapped[bool] = mapped_column(Boolean, nullable=False)
    conditional_language: Mapped[bool] = mapped_column(Boolean, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[uuid.UUID] = _pk()
    occurred_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    # 다른 테이블과 FK로 묶지 않는다. 감사 이력은 대상이 삭제돼도 남아야 하고, FK를
    # 걸면 삭제가 기록을 함께 지우거나 삭제 자체를 막는다(데이터 모델 §2).
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False)


__all__ = [
    "Base",
    "AssessmentCase",
    "DecisionResult",
    "Recommendation",
    "ExplanationRun",
    "EvalResult",
    "AuditEvent",
    "CASE_STATUSES",
    "RUN_STATUSES",
    "VERDICTS",
    "IN_FLIGHT_RUN_STATUSES",
]
