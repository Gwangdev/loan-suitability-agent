"""요청 로그 — 요청마다 식별자를 정하고, 끝날 때 한 줄을 남긴다.

식별자는 서버가 정한다. 클라이언트가 보낸 값을 받아 쓰면 남이 고른 값이 감사 이벤트의
추적 키가 되어, 서로 다른 요청이 같은 식별자로 묶이는 것을 막을 수 없다. 응답에 싣지도
않는다. 헤더 하나라도 공개 계약이 늘어나는 일이라 명세를 거치지 않고는 더하지 않는다.

한 줄에 담는 것은 메서드·경로·상태·지연뿐이다. 쿼리 문자열·헤더·본문은 넣지 않는다.
방문자 키는 헤더로, 금액은 본문으로 들어오기 때문이다.

처리되지 않은 예외는 이 미들웨어 바깥에서 500으로 바뀌므로, 응답 시작을 보지 못한 요청은
500으로 적는다. 바깥의 예외 처리기가 같은 식별자로 기록할 수 있도록 식별자를 요청 상태
(`scope["state"]`, 처리기에서는 `request.state`)에도 남긴다 — 그 처리기가 돌 때는 이
미들웨어의 실행 흐름이 이미 끝나 묶어 둔 값이 풀려 있다.

`BaseHTTPMiddleware`를 쓰지 않는 이유는 `limits.py`와 같다. 요청마다 태스크와 스트림을
하나씩 더 만드는 방식이라, 이 한 줄을 남기려고 그렇게 감싸자 처리량이 약 10% 줄었다.
"""
import logging
import time
import uuid

from loan_agent import logs

logger = logging.getLogger(__name__)


class RequestLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        correlation_id = uuid.uuid4()
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        token = logs.bind(correlation_id)
        started = time.perf_counter()
        status = 500

        async def send_with_status(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            logs.unbind(token)


def install(app) -> None:
    """앱에 요청 로그를 건다."""
    app.add_middleware(RequestLogMiddleware)


__all__ = ["RequestLogMiddleware", "install"]
