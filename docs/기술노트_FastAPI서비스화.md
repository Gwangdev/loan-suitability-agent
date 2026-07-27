# 기술 노트 — FastAPI 서비스 계층 도입

> 프론트엔드 선택 근거와 유지관리 진화 전략을 코드로 증명한 기록.
> 관련: [기술 선정 기획서](기술선정_기획서.md) · [기술부채·보안·개선 계획](기술부채_보안_개선계획.md)

---

## 1. 왜 서비스 계층을 추가했나 (문제의식)

초기 MVP는 **Streamlit 단일 앱**이었다. Streamlit은 "가장 빠르고 가볍게 MVP를 만든다"는 목표엔
최적이었지만, 실제 서비스/포트폴리오 관점에서 두 가지가 걸렸다.

1. **통합 불가** — 로직이 Streamlit 프로세스 안에 갇혀 있어, 다른 시스템(모바일·사내 툴·타 프론트)이
   호출할 방법이 없다. 엔터프라이즈/SI 맥락에서 AI 로직의 가치는 **"고객 시스템에 붙일 수 있는가"**에서 나온다.
2. **실행 모델 마찰** — Streamlit은 상호작용마다 스크립트를 재실행한다. 단계별 진행 표시를 위해
   `app.py`에서 **스레드+큐로 우회**해야 했던 것이 이 한계의 증거다.

## 2. 핵심 전제 — 로직은 이미 UI-무관했다

이 전환이 저비용이었던 이유는, 비즈니스 로직(`loan_agent/core.py`)에 **UI 의존성이 처음부터 없었기**
때문이다(`import`는 표준 라이브러리 + dotenv + crew(선택)뿐, **Streamlit·FastAPI 어느 것도 import하지 않음**).

```
[초기]   Streamlit app  ──▶  core.py (로직)
[현재]   Streamlit app ─┐
         (미래) React   ─┼──▶  FastAPI (api.py) ──▶ core.py (로직)
         cURL/타서비스  ─┘
```

→ **프론트는 언제든 교체 가능한 얇은 층**이다. Streamlit 선택이 "안전한 MVP 선택"이었음을 코드가 증명한다.

## 3. 무엇을 만들었나 — `loan_agent/api.py`

| 메서드 · 경로 | 설명 | LLM 키 |
|---|---|---|
| `GET /health` | 상태 + LLM 준비 여부 | 불필요 |
| `GET /products` | 대출상품 목록(CSV 진실의 원천) | 불필요 |
| `POST /parse` | 자연어 → 구조화 필드 + 부족 필수필드 | 불필요 |
| `POST /screen` | 구조화 고객정보 → **결정적 심사 판정** | 불필요 |
| `POST /advise` | 자연어 → **3-Agent 파이프라인** 전체 실행 | 필요 |

**설계 포인트**
- **결정적/LLM 경로 분리를 URL로 표현** — `/screen`(재현성 있는 코드 판정, 무료·오프라인)과
  `/advise`(LLM)를 별도 리소스로 노출. "판정은 코드, 설명은 LLM" 설계가 API 표면에도 드러난다.
- **값비싼 호출 전 방어** — `/advise`는 LLM을 부르기 전에 필수필드를 검증해 **422**로 거르고,
  키가 없으면 **503**으로 안내한다(정보부족을 '거절'로 오판하거나 비용을 낭비하지 않음).
- **Pydantic 스키마** — 요청을 타입으로 검증(예: 신용등급 1~10 범위, 입력 2000자 상한 → 비용 폭증 방지).

## 4. 왜 FastAPI인가 (REST 스타일 + FastAPI 프레임워크)

`REST`(HTTP+JSON 스타일)를 파이썬으로 구현하는 프레임워크 중 FastAPI를 택한 이유:

| 근거 | 우리 프로젝트와의 접점 |
|---|---|
| **async 네이티브** | 파이프라인이 이미 `async`(`run_service`/`kickoff_async`). LLM 대기(I/O)가 길어 async가 유리 |
| **자동 OpenAPI 문서(/docs)** | 코드만으로 Swagger UI 생성 → 자기문서화, 데모 포인트 |
| **Pydantic 검증** | 구조화 JSON(월소득·신용등급 등) + 필수필드 검증과 직결 |
| **AI/ML 서빙 표준** | LLM·모델 서빙 백엔드의 사실상 표준 → 채용시장 인지도 |

**대안 기각:** Flask(sync 우선·검증/문서 수동) · Django REST(DB/ORM 중심, DB 없는 규모엔 과함).

## 5. 유지관리·테스트 관점의 이득

- **테스트 가능성↑** — API 계층은 `TestClient`로 엔드투엔드 검증(키 불필요 경로 + 방어 경로). 
  `tests/test_api.py` 8개가 CI에서 자동 실행된다.
- **의존성 경량 CI** — `core`가 crewai 없이 import되고 테스트가 LLM을 호출하지 않으므로,
  CI는 `pytest·python-dotenv·fastapi·httpx`만 설치해 빠르게 돈다.
- **이식성** — 다음 단계로 Docker화하면 Streamlit Cloud(데모)와 무관하게 어디서든 배포 가능.

## 6. 실행 방법

```bash
# 서비스 계층(API)
uvicorn loan_agent.api:app --reload      # http://127.0.0.1:8000/docs

# 결정적 심사 호출 예시 (키 불필요)
curl -X POST http://127.0.0.1:8000/screen -H "Content-Type: application/json" \
  -d '{"월소득":7000000,"부채":0,"신용등급":1,"희망금액":30000000,"직장유형":"정규직"}'

# 데모 UI(API와 병행)
streamlit run loan_agent/app.py
```

## 7. 다음 단계

- Streamlit을 `/advise`·`/screen` **API의 클라이언트로 리팩터**(현재는 `core` 직접 호출 병행).
- **방문자 키 입력 + 비용 보호장치**(§개선계획 C-4), **Docker화**, 배포.
- 스트리밍(SSE/WebSocket)으로 실시간 에이전트 진행 표시.

*문서 버전 v1 · FastAPI 서비스 계층 도입 시점*
