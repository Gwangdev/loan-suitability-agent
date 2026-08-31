"""오류 응답 형식 — RFC 9457 problem+json 하나로 통일한다.

경로마다 오류 본문 모양이 다르면 클라이언트가 어느 엔드포인트가 실패했는지에 따라
파서를 분기해야 한다. FastAPI 기본값은 `{"detail": ...}`이고 Pydantic 검증 실패는
또 다른 모양이라, 그대로 두면 한 서비스 안에 형식이 둘 이상 생긴다. 그래서 진입점에서
예외 처리기를 갈아 끼워 전 구간을 같은 모양으로 되돌린다.

본문에는 스택 트레이스·내부 경로·쿼리를 담지 않는다. 예외 원문에 조직 식별자나
접속 정보가 섞여 나갈 수 있으므로, 처리되지 않은 예외는 고정 문구로 덮고 상세는
서버 로그에만 남긴다.
"""
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

CONTENT_TYPE = "application/problem+json"

# 상태 코드별 기본 제목. 「같은 성격의 실패는 같은 코드로 나간다」는 정책을 한자리에
# 모아 두어야 새 엔드포인트가 임의의 코드를 쓰기 시작하는 것을 눈으로 잡을 수 있다.
TITLES = {
    400: "Bad Request",
    404: "Not Found",
    409: "Conflict",
    413: "Payload Too Large",
    415: "Unsupported Media Type",
    422: "Unprocessable Content",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def problem(request: Request, status: int, detail=None, **extra) -> JSONResponse:
    """RFC 9457 형태의 오류 응답을 만든다.

    `type`은 문제 유형을 가리키는 URI 자리인데, 공개된 문서 URI를 아직 두지 않았으므로
    규격이 정한 기본값 `about:blank`를 쓴다. 존재하지 않는 URI를 적어 두면 클라이언트가
    따라갔을 때 깨진 링크가 되므로, 문서를 실제로 발행하기 전까지는 기본값이 정확하다.
    """
    body = {
        "type": "about:blank",
        "title": TITLES.get(status, "Error"),
        "status": status,
        "instance": request.url.path,
    }
    if detail is not None:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(status_code=status, content=body, media_type=CONTENT_TYPE)


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return problem(request, exc.status_code, detail=exc.detail)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic 검증 실패를 422로 낸다.

    어느 필드가 왜 거절됐는지는 호출자가 고쳐야 할 정보이므로 `errors`로 함께 준다.
    다만 Pydantic이 붙이는 `input` 값은 그대로 되돌리면 요청에 담겼던 값이 응답과
    로그에 다시 실린다. 이 서비스는 소득·부채 같은 금액을 다루므로 그 되울림을
    만들지 않기 위해 필드 위치와 사유만 남기고 값은 버린다.
    """
    errors = [
        {"field": ".".join(str(p) for p in e.get("loc", ())), "reason": e.get("msg", "")}
        for e in exc.errors()
    ]
    return problem(request, 422, detail="요청 값이 올바르지 않습니다.", errors=errors)


async def unhandled_exception_handler(request: Request, exc: Exception):
    """처리되지 않은 예외는 고정 문구로 덮는다. 상세는 로그에만 남는다."""
    logger.exception("unhandled error on %s", request.url.path)
    return problem(request, 500, detail="내부 오류가 발생했습니다.")


def install(app) -> None:
    """앱에 오류 처리기를 등록한다."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
