"""요청 상한 테스트 — 413·415·429가 실제로 나오는지 고정한다.

`SPEC.yaml`의 오류 정책이 셋을 약속했는데 코드에는 제목 문자열만 있고 그 코드를 내는
자리가 없었다. 게이트는 엔드포인트 목록만 대조하므로 **동작 부재를 원리상 잡지 못한다.**
명세가 약속한 통제를 그 통제 자체를 겨냥한 테스트로 고정해, 다음에 미들웨어가 빠지면
여기가 먼저 깨지게 한다.
"""
import pytest
from fastapi.testclient import TestClient

from loan_agent.api import app as fastapi_app
from loan_agent.api import errors, limits


@pytest.fixture()
def client():
    return TestClient(fastapi_app)


def test_body_over_the_cap_exits_413(client):
    """상한을 넘긴 본문은 핸들러에 닿기 전에 413으로 끝난다."""
    oversized = "가" * (limits.MAX_BODY_BYTES + 1)

    response = client.post("/api/v1/parsing-preview", json={"text": oversized})

    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Payload Too Large"


def test_non_json_body_exits_415(client):
    """본문이 있는데 JSON이 아니면 415다."""
    response = client.post(
        "/api/v1/parsing-preview",
        content=b"text=hello",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 415
    assert response.json()["title"] == "Unsupported Media Type"


def test_json_content_type_with_charset_is_accepted(client):
    """`application/json; charset=utf-8`은 정상 JSON이다.

    파라미터가 붙었다고 415를 내면 표준을 지키는 클라이언트가 막힌다.
    """
    response = client.post(
        "/api/v1/parsing-preview",
        content='{"text": "월급 300만원"}'.encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    assert response.status_code == 200


def test_bodiless_get_is_not_media_type_checked(client):
    """본문 없는 요청까지 매체 타입을 따지면 조회와 헬스체크가 막힌다."""
    assert client.get("/health/live").status_code == 200


def _isolated_app(**limit_kwargs):
    """상한만 검사하는 최소 앱.

    운영 앱에 미들웨어를 덧끼우면 Starlette이 기동 후 추가를 막고, 통과하더라도
    한 테스트가 좁힌 한도가 다른 테스트로 샌다. 상한은 라우터와 무관한 관심사이므로
    격리된 앱에서 미들웨어 자체를 겨냥한다.
    """
    from fastapi import FastAPI

    app = FastAPI()
    errors.install(app)
    app.add_middleware(limits.RequestLimitMiddleware, **limit_kwargs)

    @app.post("/api/v1/parsing-preview")
    def _spend():
        return {"ok": True}

    @app.get("/health/live")
    def _read():
        return {"status": "alive"}

    return app


def test_rate_limit_exits_429_with_retry_after():
    """토큰을 쓰는 경로가 상한을 넘기면 429와 재시도 시각이 함께 나간다."""
    client = TestClient(_isolated_app(max_requests=2, window_sec=3600))
    payload = {"text": "월급 300만원"}

    assert client.post("/api/v1/parsing-preview", json=payload).status_code == 200
    assert client.post("/api/v1/parsing-preview", json=payload).status_code == 200

    blocked = client.post("/api/v1/parsing-preview", json=payload)

    assert blocked.status_code == 429
    assert blocked.json()["title"] == "Too Many Requests"
    assert int(blocked.headers["Retry-After"]) > 0


def test_read_paths_are_not_rate_limited():
    """조회에까지 상한을 걸면 화면이 폴링하다 스스로 막힌다."""
    client = TestClient(_isolated_app(max_requests=1, window_sec=3600))

    for _ in range(5):
        assert client.get("/health/live").status_code == 200


def test_the_running_app_actually_carries_the_limit():
    """운영 앱에 미들웨어가 실제로 걸려 있는지 확인한다.

    미들웨어를 격리해 검사하면 그 동작은 증명되지만 **배선은 증명되지 않는다.**
    `install()` 호출이 빠져도 위 테스트는 전부 통과한다.
    """
    assert any(
        m.cls is limits.RequestLimitMiddleware
        for m in fastapi_app.user_middleware
    ), "운영 앱에 RequestLimitMiddleware가 걸려 있지 않다"
