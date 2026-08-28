# 대출 적합성 심사 데모 이미지. Compose가 UI와 API에 같은 이미지를 사용하고 각 서비스가
# 실행 명령만 바꾼다. 의존성 설치와 코드 배치를 한 곳에 두어 두 경로의 런타임 차이를 없앤다.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp

WORKDIR /app

# 일부 의존성의 소스 빌드와 컨테이너 내부 상태 확인에 필요한 도구만 설치한다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# 의존성을 코드보다 먼저 설치해 소스만 바뀌는 빌드에서 레이어 캐시를 재사용한다.
COPY requirements.txt .
RUN pip install -r requirements.txt

# core.BASE_DIR가 /app을 기준으로 데이터를 찾으므로 CSV를 애플리케이션 루트에 둔다.
COPY loan_agent/ ./loan_agent/
COPY loan_products.csv ./
# .env와 시크릿은 이미지에 복사하지 않고 런타임 환경으로만 전달한다.

# 읽기 전용 루트 파일시스템에서 실행해도 동작하도록 홈은 Compose의 tmpfs에 둔다. 고정 UID는
# Compose의 user 설정과 이미지 내부 계정을 일치시켜 파일 권한이 환경마다 달라지는 일을 막는다.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501

# Streamlit 컨테이너 헬스체크(내장 엔드포인트)
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

# 컨테이너 환경에 맞춘 Streamlit 실행 옵션
CMD ["streamlit", "run", "loan_agent/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
