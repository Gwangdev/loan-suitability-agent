"""상태 확인 — liveness와 readiness를 나눈다.

하나의 `/health`가 정적 200을 돌려주던 구조에서는 DB가 죽어도 healthy로 보여
장애 탐지가 늦어진다. 해법은 응답을 더 똑똑하게 만드는 것이 아니라 질문을 나누는
것이다. 「프로세스가 살아 있는가」와 「의존 자원까지 받을 준비가 됐는가」는 서로 다른
질문이고, 오케스트레이터가 둘에 대해 하는 일도 다르다 — 앞의 것이 실패하면 재시작하고,
뒤의 것이 실패하면 트래픽만 끊는다.

readiness는 DB 연결과 마이그레이션 상태를 실제로 확인해야 하므로 영속화 계층이
붙는 항목에서 구현한다. LLM 제공자 장애는 readiness 실패로 보지 않는다. 결정적 판정은
제공자와 무관하게 동작하므로, 그것까지 묶으면 멀쩡한 기능이 함께 차단된다.
"""
from fastapi import APIRouter

router = APIRouter(tags=["meta"])


@router.get("/health/live")
def live():
    """프로세스 생존만 보고한다. 의존 자원을 호출하지 않는다."""
    return {"status": "alive"}
