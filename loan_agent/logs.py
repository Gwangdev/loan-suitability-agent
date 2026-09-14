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
그 traceback은 두 번 기록된다. 앱의 예외 처리기가 한 번 남기고, 처리기가 응답을 만든 뒤에도
Starlette가 예외를 다시 던지므로 uvicorn이 `uvicorn.error` 로거와 자기 포매터로 한 번 더 쓴다.
그래서 가림은 포매터가 아니라 핸들러 필터로 두고, 앱 핸들러와 uvicorn·루트 로거의 핸들러에
함께 건다. 필터는 직렬화하기 전의 원래 문자열(메시지·예외·스택)에서 키 형태(`sk-`로 시작하는
OpenAI 키)를 가리므로 어느 포매터가 쓰든 가린 값이 나간다.

필터는 설정하는 순간 붙어 있는 핸들러에만 걸린다. uvicorn은 앱 모듈을 import하기 전에 자기
로그 설정을 끝내므로 그 핸들러는 포함되지만, 나중에 붙는 핸들러는 포함되지 않는다. 다른 형태의
자격증명도 이 규칙이 잡지 않는다. 가림은 안전장치이고, 기록하지 않는다는 원칙이 먼저다.
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
# 왼쪽 경계가 없으면 `risk-assessment`·`task-scheduler`처럼 단어 끝의 `sk-`까지 가린다.
# 인코딩된 문자열에서는 구분 기호가 영숫자로 바뀌어 뒤따르는 키가 영숫자 뒤에 붙은 것처럼 보인다.
# `repr`의 줄바꿈은 `\` `n` 두 글자가 되고, URL의 `=`·공백은 `%3D`·`%20`이 되므로 이 둘 바로 뒤도
# 경계로 인정한다.
_API_KEY_SHAPED = re.compile(
    r"(?:(?<![A-Za-z0-9])|(?<=\\[nrt])|(?<=%[0-9A-Fa-f]{2}))sk-[A-Za-z0-9_\-]{8,}"
)
_MASKED_KEY = "sk-***"

# `correlation_id`는 필터가 따로 다루므로 목록에서 뺀다.
EXTRA_FIELDS = ("run_id", "method", "path", "status", "latency_ms")

# 이 모듈이 붙인 핸들러를 알아보는 표식. 다시 설정할 때 앞서 붙인 것만 떼어 내고
# 다른 곳에서 붙인 핸들러는 건드리지 않는다.
_HANDLER_MARK = "_loan_agent_json"

# 이 모듈 밖에서 핸들러를 붙이는 로거 중 가림을 거쳐야 하는 곳. `uvicorn.error`는 핸들러 없이
# `uvicorn` 로거로 전파되지만, 설정을 바꿔 직접 핸들러를 붙인 경우도 함께 덮는다. 빈 이름은 루트다.
_FOREIGN_LOGGERS = ("uvicorn", "uvicorn.error", "")

# 예외 문자열을 미리 만들 때 쓴다. 표준 포매터와 uvicorn 포매터 모두 `formatException`을 바꾸지
# 않으므로 같은 모양이 나온다.
_TRACEBACK_FORMATTER = logging.Formatter()


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


def _mask(text: str) -> str:
    return _API_KEY_SHAPED.sub(_MASKED_KEY, text)


def _printable(value) -> str:
    """값을 문자열로 옮기되, 옮기다 예외가 나면 형식 이름만 남긴다."""
    try:
        return str(value)
    except Exception:
        return f"<unprintable {type(value).__name__}>"


class _MaskApiKeys(logging.Filter):
    """레코드의 메시지·예외·스택 문자열에서 키 형태를 가린다.

    예외 문자열은 여기서 만들어 `exc_text`에 넣는다. 표준 `Formatter.format`은 `exc_text`가 있으면
    traceback을 다시 만들지 않으므로, 뒤에서 어떤 포매터가 쓰든 가린 문자열을 쓴다. 메시지는 키가
    들어 있을 때만 바꾼다. uvicorn 접근 로그 포매터처럼 `args`를 튜플로 읽는 포매터가 있어,
    바꿀 필요가 없는 레코드는 그대로 둔다.

    핸들러 필터는 `emit`의 오류 처리보다 앞서 돈다. 여기서 메시지를 만들다 난 예외를 놓치면 형식이
    틀린 로그 호출 하나가 호출한 코드로 예외를 던져 요청 처리를 실패시킨다. 그렇다고 레코드를 그대로
    넘기면 `logging`의 오류 보고가 인자를 가리지 않고 표준 오류에 찍는다. 그래서 어떤 예외든 잡아
    형식 문자열과 인자를 각각 안전하게 문자열로 옮긴 뒤 가려서 메시지로 쓴다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = f"{_printable(record.msg)} {_printable(record.args)}"
            record.msg, record.args = _mask(message), None
        else:
            masked = _mask(message)
            if masked != message:
                record.msg, record.args = masked, None
        if record.exc_info and not record.exc_text:
            record.exc_text = _TRACEBACK_FORMATTER.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = _mask(record.exc_text)
        if record.stack_info:
            record.stack_info = _mask(record.stack_info)
        return True


_MASK_FILTER = _MaskApiKeys()


def _attach_mask(handler: logging.Handler) -> None:
    if not any(isinstance(existing, _MaskApiKeys) for existing in handler.filters):
        handler.addFilter(_MASK_FILTER)


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
            entry["exception"] = record.exc_text or self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure(level: int = logging.INFO, stream=None) -> logging.Handler:
    """`loan_agent` 로거에 JSON 핸들러를 걸고, 이미 붙어 있는 서버 로거 핸들러에 가림을 건다.

    여러 번 불러도 JSON 핸들러는 하나이고, 한 핸들러에 가림 필터가 두 번 붙지 않는다.
    """
    logger = logging.getLogger("loan_agent")
    for existing in [h for h in logger.handlers if getattr(h, _HANDLER_MARK, False)]:
        logger.removeHandler(existing)

    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_stamp_correlation_id)
    _attach_mask(handler)
    setattr(handler, _HANDLER_MARK, True)
    logger.addHandler(handler)
    logger.setLevel(level)

    for name in _FOREIGN_LOGGERS:
        for foreign in logging.getLogger(name).handlers:
            _attach_mask(foreign)
    return handler


__all__ = [
    "JsonFormatter",
    "bind",
    "configure",
    "current_correlation_id",
    "unbind",
]
