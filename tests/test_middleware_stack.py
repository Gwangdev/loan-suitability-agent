"""API 미들웨어 스택 — 요청마다 도는 계층이 같은 비용을 다시 들이지 않게 고정한다.

413·415·429 검사와 요청 로그를 Starlette `BaseHTTPMiddleware`로 만들었을 때 각각 처리량이
약 10% 줄었다. 그 방식은 요청마다 하위 앱을 별도 태스크로 띄우고 응답을 스트림으로 다시
흘려보낸다. 부하 측정은 CI에서 돌지 않으므로, 새 미들웨어가 같은 방식으로 들어오면 여기서
먼저 깨지게 한다.
"""
from starlette.middleware.base import BaseHTTPMiddleware

from loan_agent.api import app


def test_no_api_middleware_is_built_on_base_http_middleware():
    classes = [middleware.cls for middleware in app.user_middleware]
    assert classes, "등록된 미들웨어가 없다 — 검사할 대상이 사라졌다"

    offenders = [
        cls.__name__ for cls in classes
        if isinstance(cls, type) and issubclass(cls, BaseHTTPMiddleware)
    ]
    assert offenders == []
