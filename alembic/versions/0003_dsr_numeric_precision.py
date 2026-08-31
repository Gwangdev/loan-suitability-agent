"""DSR Numeric의 저장 정밀도를 명시한다.

모델의 ``Numeric(asdecimal=True)``은 읽을 때 Decimal을 돌려주므로 타입 힌트도 그
사실을 따르게 한다. 판정 계산을 Decimal로 전환하는 변경은 아니며 ADR-032의 float
판정 범위를 유지한다.

Revision ID: 0003_dsr_numeric_precision
Revises: 0002_performance_indexes
Create Date: 2026-08-29
"""
import sqlalchemy as sa

from alembic import op

revision = "0003_dsr_numeric_precision"
down_revision = "0002_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "decision_result",
        "dsr",
        existing_type=sa.Numeric(),
        type_=sa.Numeric(18, 12),
        postgresql_using="dsr::numeric(18, 12)",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "decision_result",
        "dsr",
        existing_type=sa.Numeric(18, 12),
        type_=sa.Numeric(),
        existing_nullable=False,
    )
