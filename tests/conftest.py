"""DB 통합 테스트용 픽스처.

ADR-008에 따라 테스트는 실제 PostgreSQL에서 돈다 — SQLite로 검증하고 PostgreSQL
동작을 주장하면 거짓이 되기 때문이다. 로컬은 이 파일이 가리키는 DB, CI는
`services: postgres`가 같은 `DATABASE_URL`로 접속처만 바꿔 준다.

스키마는 세션당 한 번 Alembic 마이그레이션으로 만든다. `metadata.create_all`을 쓰지
않는 이유는, 이 프로젝트가 검증하려는 것이 마이그레이션 자체이기 때문이다. 테스트
사이의 격리는 각 테스트를 하나의 트랜잭션으로 감싸 끝에 롤백하는 방식으로 얻는다.
"""
import os

import pytest
from sqlalchemy import create_engine, text

# DATABASE_URL을 명시했다는 것은 「여기에 DB가 있다」는 단언이다. 그 단언이 틀렸으면
# 오류이지 건너뛸 일이 아니다. 반대로 변수가 없으면 로컬 기본값을 짐작한 것뿐이므로,
# 닿지 않아도 개발자의 편의를 위해 건너뛴다.
#
# 이 구분이 없으면 CI 설정이 어긋나도 전부 skip으로 바뀌어 초록으로 통과한다. skip은
# 실패로 보이지 않으므로 커버리지가 0이 된 것을 아무도 눈치채지 못한다.
_DB_URL_EXPLICIT = "DATABASE_URL" in os.environ
TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2:///loan_suitability_test"
)


def _alembic_config():
    from alembic.config import Config

    root = os.path.dirname(os.path.dirname(__file__))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return cfg


@pytest.fixture(scope="session")
def _migrated_db():
    """마이그레이션을 head까지 올린 상태의 테스트 DB를 준비한다."""
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        if _DB_URL_EXPLICIT:
            pytest.fail(
                f"DATABASE_URL이 지정됐는데 접속할 수 없습니다: {exc}\n"
                "지정된 DB에 닿지 못하는 것은 환경 문제가 아니라 오류다. "
                "건너뛰면 DB 검증이 0건인 채로 통과한다."
            )
        pytest.skip(f"테스트 DB에 접속할 수 없습니다(DATABASE_URL 미지정): {exc}")

    from alembic import command

    cfg = _alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(_migrated_db):
    """테스트 하나를 트랜잭션으로 감싸고 끝에 되돌린다."""
    from sqlalchemy.orm import sessionmaker

    conn = _migrated_db.connect()
    trans = conn.begin()
    session = sessionmaker(bind=conn)()
    try:
        yield session
    finally:
        session.close()
        # 제약 위반 테스트는 예외 시점에 트랜잭션이 이미 풀려 있을 수 있다.
        if trans.is_active:
            trans.rollback()
        conn.close()


@pytest.fixture()
def db_url():
    return TEST_DATABASE_URL
