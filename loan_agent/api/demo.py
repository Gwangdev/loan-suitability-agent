"""GET /api/v1/demo-cases — 사전 녹화된 3-Agent 출력을 돌려준다.

키가 없는 방문자도 실제 파이프라인 출력을 볼 수 있어야 한다는 요구사항의 표면이다.
녹화된 결과를 파일에서 읽을 뿐이므로 LLM을 부르지 않고 토큰도 쓰지 않는다.

이 경로가 키나 DB에 묶이면 「키 없이 열람 가능」이라는 약속이 깨진다. 의존을 늘릴
일이 생기면 그 약속을 먼저 확인한다.
"""
from fastapi import APIRouter

from loan_agent import core

router = APIRouter(tags=["demo"])


@router.get("/api/v1/demo-cases")
def demo_cases():
    return core.load_demo_fixtures()
