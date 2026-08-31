"""상태 확인 엔드포인트와 전 구간 오류 응답 형식.

liveness와 readiness를 나누는 이유는 둘이 서로 다른 질문에 답하기 때문이다.
liveness는 「프로세스가 살아 있는가」만 보므로 의존 자원을 호출하지 않는다.
의존 자원까지 확인하는 것은 readiness의 몫이고, 그쪽은 DB가 붙은 뒤 별도 항목에서 다룬다.

이 파일은 오류 응답 형식(RFC 9457 problem+json)도 함께 고정한다. 형식이 경로마다
다르면 클라이언트가 어느 엔드포인트가 실패했는지에 따라 파서를 분기해야 한다.
"""
from fastapi.testclient import TestClient

from loan_agent.api import app

client = TestClient(app)


def test_live_reports_process_alive():
    r = client.get("/health/live")

    assert r.status_code == 200
    assert r.json()["status"] == "alive"


def test_live_does_not_touch_dependencies():
    """liveness는 의존 자원 상태를 보고하지 않는다.

    정적 200을 돌려주는 헬스체크가 DB 장애를 healthy로 가려 장애 탐지를 늦춘다는
    지적이 있었고, 그 해법은 liveness를 더 똑똑하게 만드는 것이 아니라 질문을
    나누는 것이었다. liveness가 의존 자원을 언급하기 시작하면 readiness와 책임이
    겹치므로, 여기서는 그런 필드가 없다는 것 자체를 고정한다.
    """
    r = client.get("/health/live")

    # 200을 먼저 확인하지 않으면 엔드포인트가 없을 때도 통과한다. 없는 응답에는
    # 당연히 database 키가 없기 때문이다.
    assert r.status_code == 200

    body = r.json()
    assert "database" not in body
    assert "migration" not in body


def test_unknown_path_returns_problem_json():
    """오류 본문은 전 구간에서 RFC 9457 problem+json 하나로 나간다."""
    r = client.get("/api/v1/no-such-path")

    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")

    body = r.json()
    assert body["status"] == 404
    assert body["title"]
    assert body["instance"] == "/api/v1/no-such-path"


def test_error_body_does_not_leak_internals():
    """오류 본문에 스택 트레이스·내부 경로가 실려 나가지 않는다."""
    r = client.get("/api/v1/no-such-path")

    # problem+json으로 바뀐 뒤에도 유출이 없는지를 보는 것이 목적이다. 형식 확인을
    # 함께 두지 않으면 기본 404 본문에서도 통과해 검사가 성립하지 않는다.
    assert r.headers["content-type"].startswith("application/problem+json")

    assert "Traceback" not in r.text
    assert "loan_agent/" not in r.text


def test_ready_reports_ready_when_db_and_migrations_current(_migrated_db, monkeypatch):
    """readiness는 DB 연결과 마이그레이션 상태를 실제로 확인하고, 둘 다 최신이면 200."""
    from loan_agent.db import engine as db_engine

    monkeypatch.setattr(db_engine, "get_engine", lambda: _migrated_db)

    r = client.get("/health/ready")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"
    assert body["migration"] == "ok"


def test_ready_returns_503_when_db_unreachable(monkeypatch):
    """의존 자원이 없으면 트래픽을 받을 준비가 안 된 것이므로 503 problem+json."""
    from sqlalchemy import create_engine

    from loan_agent.db import engine as db_engine

    dead = create_engine("postgresql+psycopg2://127.0.0.1:1/nope")
    monkeypatch.setattr(db_engine, "get_engine", lambda: dead)

    r = client.get("/health/ready")

    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 503


def test_ready_returns_503_when_migration_behind(_migrated_db, monkeypatch):
    """DB는 붙지만 스키마가 head보다 뒤처져 있으면 준비되지 않은 것이다."""
    from alembic import command

    from loan_agent.db import engine as db_engine
    from tests.conftest import _alembic_config

    monkeypatch.setattr(db_engine, "get_engine", lambda: _migrated_db)
    command.downgrade(_alembic_config(), "-1")
    try:
        r = client.get("/health/ready")
        assert r.status_code == 503
        assert r.json()["status"] == 503
    finally:
        command.upgrade(_alembic_config(), "head")


def test_ready_ignores_llm_provider(_migrated_db, monkeypatch):
    """LLM 제공자 장애는 readiness 실패로 보지 않는다.

    결정적 판정은 제공자와 무관하게 동작하므로, 키가 없어도 readiness는 통과해야
    한다. 그렇지 않으면 멀쩡한 판정 경로가 함께 차단된다.
    """
    from loan_agent.db import engine as db_engine

    monkeypatch.setattr(db_engine, "get_engine", lambda: _migrated_db)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    r = client.get("/health/ready")

    assert r.status_code == 200
