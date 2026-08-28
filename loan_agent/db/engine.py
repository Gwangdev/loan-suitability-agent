"""DB 엔진과 세션 — 연결 자원의 상한을 여기서 고정한다.

값의 근거는 ADR-022에 있다. 요점만: 커넥션은 요청이 도는 동안이 아니라 트랜잭션이
DB를 점유하는 동안만 필요하고, LLM 호출을 트랜잭션 밖에 둔 덕에(ADR-003) 점유 시간이
밀리초 단위다. 그래서 인스턴스당 5+5로 충분하다. 타임아웃은 바깥이 안쪽보다 길어야
좀비 요청이 쌓이지 않으므로, 여기서 DB `statement_timeout`을 가장 짧게(5초) 건다.

엔진은 import 시점이 아니라 처음 필요할 때 만든다. `loan_agent.api`를 불러오는 것만으로
DB가 있어야 하면 liveness 확인이나 테스트가 DB에 묶이기 때문이다.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

_engine: Engine | None = None
_Session: sessionmaker | None = None


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL이 설정되지 않았습니다. 영속화 계층은 이 값 없이 동작하지 않습니다."
        )
    return url


def _build_engine() -> Engine:
    return create_engine(
        database_url(),
        pool_size=5,
        max_overflow=5,
        pool_timeout=5,
        pool_recycle=1800,
        pool_pre_ping=True,
        # 우리 쿼리는 밀리초 단위다. 5초가 걸린다면 정상 동작이 아니라 사고이므로
        # DB가 먼저 끊는 편이 낫다.
        connect_args={"options": "-c statement_timeout=5000"},
        future=True,
    )


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_sessionmaker() -> sessionmaker:
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _Session


def reset() -> None:
    """엔진을 폐기한다. 테스트가 접속처를 바꿀 때 쓴다."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


__all__ = ["database_url", "get_engine", "get_sessionmaker", "reset"]
