"""상태 확인 — liveness와 readiness를 나눈다.

하나의 `/health`가 정적 200을 돌려주던 구조에서는 DB가 죽어도 healthy로 보여
장애 탐지가 늦어진다. 해법은 응답을 더 똑똑하게 만드는 것이 아니라 질문을 나누는
것이다. 「프로세스가 살아 있는가」와 「의존 자원까지 받을 준비가 됐는가」는 서로 다른
질문이고, 오케스트레이터가 둘에 대해 하는 일도 다르다 — 앞의 것이 실패하면 재시작하고,
뒤의 것이 실패하면 트래픽만 끊는다.

readiness는 DB 연결과 마이그레이션 상태를 실제로 확인한다 — 판정 로직은
`loan_agent/db/readiness.py`가 갖고 이 파일은 그 결과를 HTTP 상태코드로 옮긴다.
LLM 제공자 장애는 readiness 실패로 보지 않는다. 결정적 판정은 제공자와 무관하게
동작하므로, 그것까지 묶으면 멀쩡한 기능이 함께 차단된다.
"""
from fastapi import APIRouter, HTTPException

from loan_agent.db import engine as db_engine
from loan_agent.db import readiness

router = APIRouter(tags=["meta"])


@router.get("/health/live")
def live():
    """프로세스 생존만 보고한다. 의존 자원을 호출하지 않는다."""
    return {"status": "alive"}


@router.get("/health/ready")
def ready():
    """의존 자원까지 받을 준비가 됐는지 보고한다.

    DB 연결과 마이그레이션 상태를 실제로 확인한다. 어느 하나라도 준비되지 않았으면
    503으로 답해 오케스트레이터가 이 인스턴스로 트래픽을 보내지 않게 한다. 준비되지
    않은 인스턴스에 트래픽이 들어가면 첫 요청부터 500이 나기 때문이다.
    """
    result = readiness.check(db_engine.get_engine())
    if result["database"] != "ok" or result["migration"] != "ok":
        raise HTTPException(status_code=503, detail="의존 자원이 준비되지 않았습니다.")
    return {"status": "ready", **result}
