"""채점하지 않은 파싱정확도를 통과가 아니라 NULL로 저장한다.

설명 실행은 저장된 구조화 값으로 안내문을 한 번 생성할 뿐 파싱을 하지 않으므로 파싱정확도를 채점할 수 없다.
그런데 컬럼이 NOT NULL이라 그 경로는 이 값을 통과로 채웠고, 공용 채점기가 남긴 「파싱 실패」 근거가 같은 행의
detail에 함께 저장됐다. 이 테이블을 쓰는 경로는 설명 실행 하나뿐이었으므로 기존 행의 통과 값은 전부 채점의
부재였다. 그래서 행마다 판단하지 않고 일괄로 NULL로 되돌리고 근거의 파싱 항목을 지운다.

passed는 건드리지 않는다. 파싱정확도가 늘 통과로 고정돼 있었으므로 passed는 이미 나머지 지표만으로 정해진
값이다. 컬럼을 NULL 허용으로 먼저 바꾸는 방식은 반영 도중 이전 프로세스가 통과 값을 써도 실패하지 않는다.

downgrade는 이전 스키마가 기대하던 모양으로 되돌린다 — NULL을 통과로 채우고 NOT NULL을 복원한다. 지운 근거
문구는 되살리지 않는다. 사실이 아니었고 이전 코드도 읽지 않는다.

리비전 ID는 alembic_version 컬럼(varchar 32)에 들어가야 하므로 32자 이내로 짓는다.

Revision ID: 0004_eval_parse_accuracy_null
Revises: 0003_dsr_numeric_precision
Create Date: 2026-09-15
"""
import sqlalchemy as sa

from alembic import op

revision = "0004_eval_parse_accuracy_null"
down_revision = "0003_dsr_numeric_precision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("eval_result", "parse_accuracy", existing_type=sa.Boolean(), nullable=True)
    op.execute("UPDATE eval_result SET parse_accuracy = NULL, detail = detail - '파싱정확도'")


def downgrade() -> None:
    op.execute("UPDATE eval_result SET parse_accuracy = TRUE WHERE parse_accuracy IS NULL")
    op.alter_column("eval_result", "parse_accuracy", existing_type=sa.Boolean(), nullable=False)
