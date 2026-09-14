"""구조화 로그 — 요청 하나를 로그와 감사 이벤트에서 같은 식별자로 따라가게 한다.

데이터 모델은 `audit_event (correlation_id, occurred_at)` 인덱스를 「요청 하나를
API→AI→Eval로 추적」하는 용도로 정의했다. 그런데 식별자는 감사 이벤트를 쓰는 순간
새로 뽑혔고 로그에는 찍히지 않았다. 인덱스는 있는데 이을 대상이 없어, 장애 로그를
보고 어느 심사였는지 되짚을 수 없었다. 요청마다 식별자를 하나 정해 두고 로그와 감사
이벤트가 같은 값을 쓰게 한다.

형식은 한 줄에 JSON 하나다. Caddy 접근 로그가 이미 JSON이라 앱 로그만 평문이면 두
계층의 기록을 시간순으로 합쳐 볼 수 없다. 필요한 것이 필드 몇 개의 직렬화뿐이라 표준
라이브러리 `logging`과 `json`으로 충분하고, 로깅 라이브러리를 새로 들이지 않는다.

내보내는 필드는 허용 목록으로 고정한다. 이 서비스는 원문 입력·프롬프트·API 키를
로그에 남기지 않는다(금지 행위 ③⑦). 호출자가 `extra`로 무엇을 넘기든 목록에 없는
키는 나가지 않으므로, 실수로 요청 본문을 넘겨도 형식 단계에서 버려진다.

식별자는 기록하는 순간에 핸들러 필터가 찍는다. 전역 레코드 팩토리로 찍으면 누군가
`extra`로 같은 키를 넘길 때 `logging`이 기존 속성을 덮어쓰려 한다며 예외를 낸다.

허용 목록은 필드 이름을 막을 뿐 메시지와 예외 문자열의 내용은 막지 못한다. 처리되지 않은
예외는 traceback 전체가 기록되는데, 끝에 줄바꿈이 붙은 키처럼 형식이 틀린 키로 요청을 만들면
전송 계층 오류 메시지에 키 원문이 들어가고 제공자 SDK가 그 오류를 감싸 연쇄 traceback에 남는다.
그래서 완성된 한 줄에서 키 형태(`sk-`로 시작하는 OpenAI 키)를 가린 뒤 내보낸다. 다른 형태의
자격증명은 이 규칙이 잡지 않으므로, 기록하지 않는다는 원칙이 먼저다.
"""
import contextvars
import json
import logging
import re
import uuid
from datetime import datetime, timezone

_correlation_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "correlation_id", default=None
)

# OpenAI 키 형태. `sk-proj-…`처럼 접두 뒤에 영숫자·`-`·`_`가 이어진다.
_API_KEY_SHAPED = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")

# `correlation_id`는 필터가 따로 다루므로 목록에서 뺀다.
EXTRA_FIELDS = ("run_id", "method", "path", "status", "latency_ms")

# 이 모듈이 붙인 핸들러를 알아보는 표식. 다시 설정할 때 앞서 붙인 것만 떼어 내고
# 다른 곳에서 붙인 핸들러는 건드리지 않는다.
_HANDLER_MARK = "_loan_agent_json"


def bind(correlation_id: uuid.UUID) -> contextvars.Token:
    """현재 실행 흐름에 식별자를 묶는다. 돌려받은 토큰으로 `unbind`한다."""
    return _correlation_id.set(correlation_id)


def unbind(token: contextvars.Token) -> None:
    _correlation_id.reset(token)


def current_correlation_id() -> uuid.UUID | None:
    return _correlation_id.get()


def _stamp_correlation_id(record: logging.LogRecord) -> bool:
    if getattr(record, "correlation_id", None) is None:
        record.correlation_id = _correlation_id.get()
    return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id is not None:
            entry["correlation_id"] = str(correlation_id)
        for key in EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return _API_KEY_SHAPED.sub("sk-***", json.dumps(entry, ensure_ascii=False, default=str))


def configure(level: int = logging.INFO, stream=None) -> logging.Handler:
    """`loan_agent` 로거에 JSON 핸들러를 건다. 여러 번 불러도 핸들러는 하나다."""
    logger = logging.getLogger("loan_agent")
    for existing in [h for h in logger.handlers if getattr(h, _HANDLER_MARK, False)]:
        logger.removeHandler(existing)

    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_stamp_correlation_id)
    setattr(handler, _HANDLER_MARK, True)
    logger.addHandler(handler)
    logger.setLevel(level)
    return handler


__all__ = [
    "JsonFormatter",
    "bind",
    "configure",
    "current_correlation_id",
    "unbind",
]
