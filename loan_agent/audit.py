"""감사 이벤트 — 요청과 실행 결과를 같은 기록 줄기에 남긴다.

데이터 모델은 이 테이블의 인덱스를 「요청 하나를 API→AI→Eval로 추적」하는 용도로 정의했는데,
기록하는 곳은 심사 생성 하나뿐이었다. 설명 실행을 요청한 사실도 그 결과도 남지 않아 추적이 API 한
칸에서 끊겼다. 실행 행을 대상으로 요청과 결과를 남기면 요청 식별자에서 실행 행을 거쳐 결과까지
이어진다.

식별자는 요청이 정한 값을 그대로 쓴다. 워커처럼 요청 밖에서 도는 실행은 자기 실행에 값을 묶고
들어오므로, 여기서는 묶여 있는 값을 읽기만 한다. 묶인 값이 없을 때만 새로 만든다 — 그 경우는 어느
요청에도 속하지 않는 기록이다.

메타데이터는 허용 목록으로 거른다. 이 테이블은 원문 입력·프롬프트·키를 담지 않는다(금지 행위 ③⑦).
호출자가 무엇을 넘기든 목록 밖 키는 저장되지 않으므로, 실수로 안내문을 넘겨도 기록 단계에서 버려진다.
"""
import uuid

from loan_agent import logs
from loan_agent.db import models

ASSESSMENT_CREATED = "assessment.created"
EXPLANATION_RUN_REQUESTED = "explanation_run.requested"
EXPLANATION_RUN_FINISHED = "explanation_run.finished"
EXPLANATION_RUN_RECLAIMED = "explanation_run.reclaimed"

ALLOWED_METADATA_KEYS = ("verdict", "status", "error_code", "passed", "executor")


def allowed_metadata(metadata: dict | None) -> dict:
    return {key: value for key, value in (metadata or {}).items() if key in ALLOWED_METADATA_KEYS}


def record(
    session,
    *,
    action: str,
    actor_type: str,
    target_type: str,
    target_id: uuid.UUID,
    metadata: dict | None = None,
) -> None:
    """감사 이벤트 하나를 호출자의 트랜잭션에 넣는다.

    커밋하지 않는다. 상태 전이와 그 기록이 한 트랜잭션에서 함께 확정돼야, 상태만 바뀌고 기록이 없는
    순간이 생기지 않는다.
    """
    session.add(
        models.AuditEvent(
            correlation_id=logs.current_correlation_id() or uuid.uuid4(),
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_=allowed_metadata(metadata),
        )
    )


__all__ = [
    "ASSESSMENT_CREATED",
    "EXPLANATION_RUN_FINISHED",
    "EXPLANATION_RUN_RECLAIMED",
    "EXPLANATION_RUN_REQUESTED",
    "allowed_metadata",
    "record",
]
