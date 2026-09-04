"""Loan Decision Support — HTTP 진입점.

이 패키지는 HTTP 계약만 담당한다. 금융 판정 로직은 들어오지 않는다. 판정은 결정적
계층이 산출하고 API는 그것을 실어 나를 뿐이며, 이 경계가 흐려지면 「판정은 코드,
설명은 LLM」이라는 구조가 표면에서부터 무너진다.

파일은 기능 단위로 나눈다. 계층이 아니라 기능으로 나누는 이유는, 계층으로 나누면
엔드포인트 하나를 고칠 때 세 파일을 함께 열어야 하고 각 파일이 서로 다른 이유로
바뀌게 되기 때문이다.

실행: uvicorn loan_agent.api:app --reload
문서: http://127.0.0.1:8000/docs
"""
from fastapi import FastAPI

from loan_agent.api import assessments, demo, errors, explanations, health, limits, parsing


app = FastAPI(
    title="Loan Decision Support API",
    version="2.0.0",
    description=(
        "금융상담 의사결정 지원 서비스. 적합성 판정은 결정적 규칙이 산출하고 "
        "LLM은 설명만 담당한다. 승인·거절을 확정하지 않으며 상담원이 최종 결정한다. "
        "교육용 데모이며 합성 데이터만 사용한다."
    ),
)

errors.install(app)
# 상한은 라우터보다 먼저 건다. 미들웨어는 나중에 등록된 것이 바깥에 놓이므로,
# 본문 크기·매체 타입 검사가 핸들러보다 앞서 돌아 거절이 처리 비용 없이 끝난다.
limits.install(app)
app.include_router(health.router)
app.include_router(assessments.router)
app.include_router(explanations.router)
app.include_router(parsing.router)
app.include_router(demo.router)

__all__ = ["app"]
