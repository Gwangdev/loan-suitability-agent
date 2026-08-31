"""영속화 계층 — 모델·엔진·readiness 판정.

기능 단위로 파일을 나눈다. `models`는 스키마 매핑, `engine`은 연결 자원과 그 상한,
`readiness`는 그 연결을 실제로 찔러 보는 판정. 서로 다른 이유로 바뀌므로 한 파일에
두지 않는다.
"""
from loan_agent.db import engine, models, readiness

__all__ = ["engine", "models", "readiness"]
