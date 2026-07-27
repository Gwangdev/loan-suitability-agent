# 대출 적합성 심사 데모 — Streamlit 앱 컨테이너 이미지
#   [디벨롭: 배포] Streamlit Cloud 종속을 벗어나 어디서든(로컬·클라우드) 동일하게 실행하기 위한 이식성 확보.
#   기본 실행은 Streamlit 데모 UI. FastAPI 서비스가 필요하면 CMD를 uvicorn으로 바꿔 실행한다.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 일부 의존성의 소스 빌드에 대비한 최소 빌드 도구 + 헬스체크용 curl
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 설치(레이어 캐시 활용) — requirements.txt는 런타임 전용(노트북/테스트 제외)
COPY requirements.txt .
RUN pip install -r requirements.txt

# 애플리케이션 코드·데이터 (core.BASE_DIR = /app 이므로 CSV는 /app 루트에 위치해야 함)
COPY loan_agent/ ./loan_agent/
COPY loan_products.csv ./
# 주의: .env·secrets는 이미지에 넣지 않는다(.dockerignore). 키는 런타임에 주입(방문자 키/시크릿).

# 비루트 사용자로 실행(보안)
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8501

# Streamlit 컨테이너 헬스체크(내장 엔드포인트)
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

# 컨테이너 환경에 맞춘 Streamlit 실행 옵션
CMD ["streamlit", "run", "loan_agent/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
