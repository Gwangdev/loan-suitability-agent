# 대출 적합성 심사 3-Agent 파이프라인

[![CI](https://github.com/Gwangdev/loan-suitability-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Gwangdev/loan-suitability-agent/actions/workflows/ci.yml)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://loan-suitability-agent.streamlit.app/)

**라이브 데모:** https://loan-suitability-agent.streamlit.app/
— OpenAI 키 없이도 사이드바의 "토큰 없이 데모 보기"로 실제 3-Agent 출력을 열람할 수 있다.

자연어 상담 입력을 **정보 파싱 → 심사 판단 → 결과 안내**의 3단계 에이전트가 순차 처리하여,
적합 대출 상품과 심사 판정을 산출하는 교육용 데모다. [CrewAI](https://docs.crewai.com/)
멀티에이전트 프레임워크와 Streamlit으로 구현하였다.

> 🛠 **개발 이력(설계 결정·이슈 해결·검증·고도화 경과):** [docs/개발이력.md](docs/개발이력.md)

> 주의. 본 프로젝트는 교육용 데모이며 실제 대출 심사·법률·금융 자문이 아니다.
> 실제 대출은 각 금융기관의 심사를 따른다.

---

## 핵심 설계: 판정은 코드, 설명은 LLM

본 설계의 핵심은 **최종 판정을 LLM에 위임하지 않는다**는 점이다.

| 역할 | 담당 | 근거 |
|------|------|------|
| **적합성 판정** (승인가능/상담필요/어려움) | CSV 하드규칙 기반 **결정적 함수** (`screen_loan`) | 재현성·감사가능성 확보. 동일 입력은 항상 동일 판정을 산출하며, LLM 환각에 의한 오승인·오거절이 발생하지 않는다 |
| **자연어 파싱·근거 설명·안내문 생성** | LLM (3-Agent) | 유연한 입력 처리와 설명 생성은 LLM의 강점이다 |

즉 LLM은 판정하지 않고 **파싱·설명·전달**만 담당한다. 오류 비용이 큰 금융 도메인에서
LLM을 안전하게 활용하는 방법을 제시하는 것이 본 데모의 목적이다.

## 3-Agent 아키텍처

```
고객 자연어 입력
      │
      ▼
┌─────────────────┐   Agent 1 · 정보 파싱가
│  정보 파싱가      │   자연어 → 6개 필드 JSON (월소득/부채/신용등급/희망금액/직장유형/담보)
└─────────────────┘   기법: 구조화 추출  (규칙기반 파서로 교차검증)
      │
      ▼
┌─────────────────┐   Agent 2 · 심사 판단가
│  심사 판단가      │   assess_loan_eligibility 도구(결정적 로직) 호출 → 판정 확정
└─────────────────┘   기법: CoT(4단계 근거) + Self-Consistency(3관점 교차검증)
      │
      ▼
┌─────────────────┐   Agent 3 · 결과 안내가
│  결과 안내가      │   판정 라벨별 톤 조정 + lookup 도구로 금리·한도 재확인
└─────────────────┘   기법: ReAct(도구로 수치 검증) + 디스클레이머 강제 삽입
      │
      ▼
고객용 안내문
```

- **도구(Tool):** `assess_loan_eligibility`(결정적 판정), `lookup_loan_product`(상품 조회).
  두 도구 모두 CSV를 진실의 원천으로 사용하며 CSV 외의 값을 생성하지 않는다.
- **안전장치:** 필수 입력 검증(`missing_required_fields`)으로 정보 부족을 거절로 오판하지 않으며,
  모든 안내문에 디스클레이머를 강제 삽입한다.

## 프로젝트 구조

```
loan-suitability-agent/
├── README.md
├── requirements.txt
├── .env.example              # 키 설정 템플릿 (복사해 .env 로 사용)
├── loan_products.csv         # 22개 대출상품 데이터 (진실의 원천)
├── loan_agent/
│   ├── core.py               # 심사 로직·파서·도구·Agent/Crew 정의 (UI-무관, 단일 진실 원천)
│   ├── api.py                # FastAPI 서비스 계층 (REST API)
│   └── app.py                # Streamlit 프론트엔드
├── tests/                    # pytest (결정적 로직·파서·랭킹·API)
├── docs/                     # 기획서·기술노트·개선계획
└── loan_agent_demo.ipynb     # 단계별 설명·실행 노트북
```

모든 로직을 `core.py`에 집약하고 API·앱·노트북이 이를 공통 import하는 **단일 진실 원천** 구조다.
`core`는 Streamlit·FastAPI를 import하지 않으므로 프론트엔드는 교체 가능한 얇은 계층이다
([기술노트](docs/기술노트_FastAPI서비스화.md)). API 키가 불필요한 부분(상품 로딩·심사 로직·규칙기반
파서)은 import 즉시 사용 가능하며, 키가 필요한 Agent/Crew는 호출 시점에 지연 생성한다.

## 실행

```bash
# 1) 런타임 의존성 설치 (앱/API)
pip install -r requirements.txt
#    노트북·테스트를 포함한 전체 개발 환경:  pip install -r requirements-dev.txt

# 2) (LLM 파이프라인 실행 시) 키 설정
cp .env.example .env      # .env 에 OPENAI_API_KEY 입력

# 3) Streamlit 웹앱 실행
streamlit run loan_agent/app.py

# 노트북으로 단계별 확인 (requirements-dev.txt 설치 필요)
jupyter lab loan_agent_demo.ipynb
```

### REST API 서비스 (FastAPI)

로직을 서비스로 노출하여 외부 시스템이 호출할 수 있다. 배경은 [기술노트](docs/기술노트_FastAPI서비스화.md) 참조.

```bash
uvicorn loan_agent.api:app --reload      # http://127.0.0.1:8000/docs (OpenAPI 자동 문서)

# 결정적 심사 호출 (키 불필요)
curl -X POST http://127.0.0.1:8000/screen -H "Content-Type: application/json" \
  -d '{"월소득":7000000,"부채":0,"신용등급":1,"희망금액":30000000,"직장유형":"정규직"}'
```

| 엔드포인트 | 설명 | LLM 키 |
|---|---|---|
| `GET /health`·`GET /products` | 상태 / 상품 목록 | 불필요 |
| `GET /demo`·`GET /demo/{i}` | 사전 녹화된 데모 결과(토큰 0) | 불필요 |
| `POST /parse`·`POST /screen` | 자연어 파싱 / 결정적 심사 판정 | 불필요 |
| `POST /advise` | 3-Agent 파이프라인 전체 | 필요 |

### Docker 실행

이식 가능한 컨테이너 이미지를 제공한다([Dockerfile](Dockerfile)).

```bash
docker build -t loan-suitability-agent .
docker run -p 8501:8501 loan-suitability-agent    # http://localhost:8501
```

키는 이미지에 포함하지 않는다(`.dockerignore`로 `.env` 제외). 키 없이도 무토큰 데모가 동작하며,
직접 실행은 앱 사이드바의 방문자 키 입력으로 수행한다.

### 무토큰 데모 (키 없는 방문자용)

공개 데모에서 어떤 토큰도 소모하지 않고 '입력 → 실제 3-Agent 출력'을 열람할 수 있다.
실제 파이프라인을 사전 1회 실행해 저장한 결과([demo_fixtures.json](loan_agent/demo_fixtures.json))를
Streamlit 사이드바의 "토큰 없이 데모 보기" 버튼과 API `GET /demo`로 제공한다.
직접 실행하려는 방문자는 자신의 OpenAI 키를 입력한다.

### 결정적 심사 로직 검증 (키 불필요)

핵심 안전장치인 결정적 심사 로직은 키 없이 검증할 수 있다.

```bash
python3 -c "from loan_agent import core; core.run_logic_selftest(core.TEST_CASES + core.EDGE_CASES)"
```

실행 결과 (5/5 전체 통과):

```
[승인 케이스]          판정 승인가능 (상환 여유, DSR 0.083)
[상담필요 케이스]      판정 상담필요 (상환 보통, DSR 0.348)
[어려움 케이스]        판정 어려움   (상환 부족, DSR 0.430)
[담보 보유 저신용]     판정 승인가능 (담보로 저신용 구간 적격 상품 확보)
[계약직 소액]          판정 승인가능 (직장조건·소액 한도 하드규칙 검증)
============================================================
결과: 전체 통과 (5/5)
```

기본 3개 케이스(승인/상담필요/어려움)에 담보·직장조건 하드규칙을 검증하는 엣지케이스 2종을
추가하여 규칙 커버리지를 확장하였다.

### 자동화 테스트 (pytest + CI)

단위 테스트는 `tests/`에 있으며 crewai·streamlit 등 무거운 의존성 없이 동작한다
(결정적 로직·파서·다기준 랭킹·경계값·API). push·PR마다 [GitHub Actions](.github/workflows/ci.yml)가
자동 실행한다.

```bash
pip install -r requirements-dev.txt
pytest
```

### LLM 출력 품질 평가 (Eval)

3-Agent 출력을 결정적 정답과 대조해 정량 채점한다(파싱정확도·판정정합성·디스클레이머·추천정합성·수치근거·조건부표현).
사전 녹화 출력을 채점하므로 **API 비용 0**이며 CI에서 실행된다. 결함을 주입해 평가가 실제로 회귀를 잡는지도 검증했다.
자세한 방법·결과는 [평가 리포트](docs/평가리포트.md).

```bash
python3 -c "from loan_agent import eval; eval.run_eval_selftest()"   # 현재 30/30 (100%)
```

## 로드맵

- [x] **DSR 심사 고도화** — 간이 DTI(`기존부채 ÷ 연소득`)를 금융위 정의인
  **DSR(연간 원리금상환액 ÷ 연소득)**로 교체하였다. 기존부채와 신규 희망금액을 모두
  원리금균등상환으로 월상환액을 산출·합산하므로, 종전에 반영되지 않던 '기존부채 0 + 거액 신청'도
  상환부담으로 정확히 반영된다(예: 월소득 300만·부채 0·희망 1억 → 종전 "여유" → 현재 "부족").
  판정 밴드 40%는 은행권 DSR 규제 상한을 반영한다. *(남은 단순화: 대표 고정금리·기간 가정)*
- [x] **다기준 상품 랭킹** — 최저금리 단일 기준을 금리·승인여유·중도상환수수료의 3단 정렬로 확장하고
  상위 3위 후보를 제시한다. CSV에 금감원 「금융상품 한눈에」 공시 컬럼(상환방식·금리방식·중도상환수수료)을 추가하였다.
- [x] **pytest + CI(GitHub Actions)** — 인라인 자체 테스트를 `pytest`로 분리하고 push마다 자동 검증한다.
  단위·API 테스트가 무거운 LLM 의존성 없이 동작하도록 `core`를 crewai 없이 import 가능하게 개선하였다.
- [x] **FastAPI 서비스 계층** — `core`를 REST API(`/screen`·`/advise` 등)로 노출하였다. 결정적/LLM 경로를
  URL로 분리하고, OpenAPI 자동 문서를 제공하며, 값비싼 호출 전 방어(422/503)를 둔다. [기술노트](docs/기술노트_FastAPI서비스화.md).
- [x] **방문자 키 입력 + 비용 보호장치** — 세션 한정 키(누출 방지), 입력·횟수 상한, 쿨다운.
- [x] **무토큰 데모** — 키 없는 방문자도 사전 녹화된 실제 결과를 열람한다(토큰 0).
- [x] **Docker화** — 이식 가능한 컨테이너 이미지([Dockerfile](Dockerfile)). 로컬 빌드·기동 검증 완료.
- [x] **Streamlit Community Cloud 라이브 데모** — 공개 URL 제공: https://loan-suitability-agent.streamlit.app/
- [x] **LLM 출력 품질 평가(Eval 하네스)** — 3-Agent 출력을 결정적 정답과 대조해 6개 지표로 정량 채점(현재 30/30).
  사전 녹화 출력 채점이라 비용 0·CI 실행 가능하며, 결함 주입 테스트로 회귀 탐지력을 검증하였다. [평가 리포트](docs/평가리포트.md).
- [ ] **재입력 UX 하이브리드(C-3)** · **성능 최적화 캐싱(C-1)** — v2 후속.

---

작성자: 원광식
