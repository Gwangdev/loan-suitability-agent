"""요청 상한 — 본문 크기(413), 매체 타입(415), 실행 빈도(429).

`SPEC.yaml`의 오류 정책이 셋을 이미 약속했는데 코드에는 `errors.py`의 제목 문자열만
있고 실제로 그 코드를 내는 자리가 없었다. 명세가 「구현된 통제」처럼 적혀 있었고
게이트는 엔드포인트 목록만 대조하므로 동작 부재를 원리상 잡지 못한다. 명세를 줄이는
대신 코드를 명세에 맞춘다.

세 가지를 한 파일에 두는 이유는 셋 다 **핸들러에 닿기 전에 요청을 거절하는 일**이고,
거절 형식이 같아야 하기 때문이다. 라우터마다 흩으면 같은 성격의 실패가 경로에 따라
다른 모양으로 나가게 된다.

**429의 실효 범위에 한계가 있다.** 명세는 「클라이언트 주소 기준」이라 적었고 여기서도
그대로 구현하지만, 배포 형상이 브라우저 → Caddy → `ui` 컨테이너 → `app`이라
`app`이 보는 주소는 언제나 `ui` 하나다. 즉 방문자별 구분이 되지 않고 실질적으로
인스턴스 전체 상한으로 동작한다. 그래서 한도를 방문자 한 명 기준으로 좁게 잡으면
한 사람이 다른 모든 사람을 막게 되므로, 폭주를 끊되 정상 사용을 막지 않는 수준으로
넉넉히 잡았다. 방문자 한 명의 실행 횟수 제한은 화면이 세션 단위로 따로 갖는다.
"""
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware

from loan_agent.api import errors

# 본문 상한. `parsing-preview`가 허용하는 자연어가 10,000자이고 UTF-8 한글이 글자당
# 3바이트이므로 30KB면 그 경로의 정상 최대치를 담는다. 나머지 경로는 숫자 몇 개짜리
# JSON이다. 256KB는 정상 입력의 여덟 배로, 오탐 없이 대용량 전송만 끊는 자리다.
MAX_BODY_BYTES = 256 * 1024

# LLM을 부를 수 있는 경로만 빈도 상한을 건다. 조회나 헬스체크에까지 걸면 화면이
# 폴링하다 스스로 막힌다.
TOKEN_SPENDING_SUFFIXES = ("/parsing-preview", "/explanation-runs")

RATE_LIMIT_WINDOW_SEC = 3600
RATE_LIMIT_MAX_REQUESTS = 60

JSON_MEDIA_TYPE = "application/json"


class RequestLimitMiddleware(BaseHTTPMiddleware):
    """본문 크기·매체 타입·실행 빈도를 핸들러 앞에서 거른다."""

    def __init__(self, app, *, max_body_bytes: int = MAX_BODY_BYTES,
                 window_sec: int = RATE_LIMIT_WINDOW_SEC,
                 max_requests: int = RATE_LIMIT_MAX_REQUESTS):
        super().__init__(app)
        self._max_body_bytes = max_body_bytes
        self._window_sec = window_sec
        self._max_requests = max_requests
        # 주소별 최근 요청 시각. 단일 인스턴스이므로 프로세스 메모리로 충분하고,
        # 분산 저장소를 두면 지금 없는 운영 부품이 하나 늘어난다. 인스턴스가 둘
        # 이상이 되는 순간 이 가정이 깨지므로 그때 다시 판단한다.
        self._hits: dict[str, deque] = {}

    async def dispatch(self, request, call_next):
        rejection = (
            self._body_too_large(request)
            or self._unsupported_media_type(request)
            or self._rate_limited(request)
        )
        if rejection is not None:
            return rejection
        return await call_next(request)

    def _body_too_large(self, request):
        raw = request.headers.get("content-length")
        if raw is None:
            return None
        try:
            declared = int(raw)
        except ValueError:
            # 길이를 숫자로 읽을 수 없으면 상한을 판정할 수 없다. 크기 문제가 아니라
            # 형식 문제이므로 413이 아니라 400으로 낸다.
            return errors.problem(request, 400, detail="Content-Length를 읽을 수 없습니다.")
        if declared > self._max_body_bytes:
            return errors.problem(
                request, 413,
                detail=f"요청 본문이 상한({self._max_body_bytes:,}바이트)을 넘었습니다.",
            )
        return None

    def _unsupported_media_type(self, request):
        """본문이 있는 요청은 JSON만 받는다.

        본문이 없는 요청까지 검사하면 GET과 헬스체크가 막힌다. 판단 기준은 메서드가
        아니라 본문의 존재다 — 본문 없는 POST도 있고, 그건 매체 타입을 말할 것이
        없으므로 여기서 거절할 대상이 아니다.
        """
        if not self._has_body(request):
            return None
        # `application/json; charset=utf-8`처럼 파라미터가 붙어 오므로 앞부분만 본다.
        media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if media_type != JSON_MEDIA_TYPE:
            return errors.problem(
                request, 415,
                detail=f"이 API는 {JSON_MEDIA_TYPE}만 받습니다.",
            )
        return None

    @staticmethod
    def _has_body(request) -> bool:
        raw = request.headers.get("content-length")
        if raw is not None:
            try:
                return int(raw) > 0
            except ValueError:
                return False
        # 길이를 안 보내는 청크 전송도 본문이 있는 요청이다.
        return request.headers.get("transfer-encoding", "").lower() == "chunked"

    def _rate_limited(self, request):
        if not self._spends_tokens(request):
            return None
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        hits = self._hits.setdefault(client, deque())
        cutoff = now - self._window_sec
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self._max_requests:
            retry_after = max(1, int(hits[0] + self._window_sec - now))
            response = errors.problem(
                request, 429,
                detail=f"실행 요청이 상한({self._max_requests}회/{self._window_sec // 60}분)을 넘었습니다.",
            )
            # 언제 다시 시도할 수 있는지 알려 준다. 이것이 없으면 클라이언트가
            # 재시도 간격을 추측하게 되고, 추측은 대개 너무 짧다.
            response.headers["Retry-After"] = str(retry_after)
            return response
        hits.append(now)
        return None

    @classmethod
    def _spends_tokens(cls, request) -> bool:
        if request.method != "POST":
            return False
        return request.url.path.endswith(TOKEN_SPENDING_SUFFIXES)


def install(app) -> None:
    """앱에 요청 상한을 건다."""
    app.add_middleware(RequestLimitMiddleware)


__all__ = [
    "RequestLimitMiddleware",
    "install",
    "MAX_BODY_BYTES",
    "RATE_LIMIT_WINDOW_SEC",
    "RATE_LIMIT_MAX_REQUESTS",
]
