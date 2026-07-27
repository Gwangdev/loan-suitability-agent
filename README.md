# 대출 적합성 심사 3-Agent 파이프라인

[![CI](https://github.com/Gwangdev/loan-suitability-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Gwangdev/loan-suitability-agent/actions/workflows/ci.yml)

자연어로 상담 내용을 입력하면 **정보 파싱 → 심사 판단 → 결과 안내** 3단계 에이전트가
협업해, 고객에게 맞는 대출 상품과 심사 판정을 안내하는 교육용 데모입니다.
[CrewAI](https://docs.crewai.com/) 멀티에이전트 프레임워크와 Streamlit으로 구현했습니다.

> ⚠️ **본 프로젝트는 교육용 데모입니다.** 실제 대출 심사·법률·금융 자문이 아니며,
> 실제 대출은 각 금융기관의 심사를 따릅니다.

---

## 핵심 설계 — "판정은 코드가, 설명은 LLM이"

이 프로젝트의 가장 중요한 설계 결정은 **최종 판정을 LLM에게 맡기지 않는다**는 것입니다.

| 역할 | 담당 | 이유 |
|------|------|------|
| **적합성 판정** (승인가능/상담필요/어려움) | CSV 하드규칙 기반 **결정적 함수** (`screen_loan`) | 재현성·감사가능성. 같은 입력엔 항상 같은 판정. LLM 환각으로 잘못된 승인/거절이 나오지 않음 |
| **자연어 파싱·근거 설명·고객 안내문** | LLM (3-Agent) | 사람이 이해하기 쉬운 설명과 유연한 입력 처리는 LLM의 강점 |

즉 LLM은 "판단"하지 않고 **읽고(파싱), 설명하고(근거), 전달(안내)** 하는 역할만 맡습니다.
금융처럼 실수가 치명적인 도메인에서 LLM을 어떻게 안전하게 쓰는지를 보여주는 것이 이 데모의 핵심입니다.

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

- **도구(Tool):** `assess_loan_eligibility`(결정적 판정), `lookup_loan_product`(상품 조회) — 모두 CSV를 진실의 원천으로 사용하며 CSV 밖 값을 만들지 않음.
- **안전장치:** 필수 입력 검증(`missing_required_fields`)으로 "정보 부족"을 "거절"로 오판하지 않음, 모든 안내문에 디스클레이머 강제 삽입.

## 프로젝트 구조

```
loan-suitability-agent/
├── README.md
├── requirements.txt
├── .env.example              # 키 설정 템플릿 (복사해서 .env 로)
├── loan_products.csv         # 22개 대출상품 데이터 (진실의 원천)
├── loan_agent/
│   ├── core.py               # 심사 로직·파서·도구·Agent/Crew 정의 (UI-무관, 단일 진실 원천)
│   ├── api.py                # FastAPI 서비스 계층 (REST API)
│   └── app.py                # Streamlit 프론트엔드
├── tests/                    # pytest (결정적 로직·파서·랭킹·API)
├── docs/                     # 기획서·기술노트·개선계획
└── loan_agent_demo.ipynb     # 단계별 설명·실행 노트북
```

`core.py` 하나에 모든 로직을 모으고 API·앱·노트북이 함께 import하는 **단일 진실 원천** 구조입니다
(`core`는 Streamlit·FastAPI 어느 것도 import하지 않아, 프론트는 교체 가능한 얇은 층입니다 —
[기술노트](docs/기술노트_FastAPI서비스화.md)). API 키가 필요 없는 부분(상품 로딩·심사 로직·규칙기반
파서)은 import 즉시 사용 가능하고, 키가 필요한 Agent/Crew는 호출 시점에 지연 생성합니다.

## 빠른 시작

```bash
# 1) 런타임 의존성 설치 (앱/API)
pip install -r requirements.txt
#    노트북·테스트까지 포함한 전체 개발환경은:  pip install -r requirements-dev.txt

# 2) (LLM 파이프라인 실행 시) 키 설정
cp .env.example .env      # .env 를 열어 OPENAI_API_KEY 입력

# 3) Streamlit 웹앱 실행
streamlit run loan_agent/app.py

# 노트북으로 단계별 확인 (requirements-dev.txt 설치 필요)
jupyter lab loan_agent_demo.ipynb
```

### REST API 서비스 (FastAPI)

로직을 서비스로 노출해 다른 시스템이 호출할 수 있습니다. 자세한 배경은 [기술노트](docs/기술노트_FastAPI서비스화.md).

```bash
uvicorn loan_agent.api:app --reload      # http://127.0.0.1:8000/docs (OpenAPI 자동 문서)

# 결정적 심사 호출 (키 불필요)
curl -X POST http://127.0.0.1:8000/screen -H "Content-Type: application/json" \
  -d '{"월소득":7000000,"부채":0,"신용등급":1,"희망금액":30000000,"직장유형":"정규직"}'
```

| 엔드포인트 | 설명 | LLM 키 |
|---|---|---|
| `GET /health`·`GET /products` | 상태 / 상품 목록 | 불필요 |
| `GET /demo`·`GET /demo/{i}` | **사전 녹화된 데모 결과(토큰 0)** | 불필요 |
| `POST /parse`·`POST /screen` | 자연어 파싱 / 결정적 심사 판정 | 불필요 |
| `POST /advise` | 3-Agent 파이프라인 전체 | 필요 |

### Docker로 실행

어디서든 동일하게 실행할 수 있는 컨테이너 이미지를 제공합니다([Dockerfile](Dockerfile)).

```bash
docker build -t loan-suitability-agent .
docker run -p 8501:8501 loan-suitability-agent    # http://localhost:8501
```

키는 이미지에 넣지 않습니다(`.dockerignore`로 `.env` 제외). 키 없이도 무토큰 데모가 동작하며,
직접 실행은 앱 사이드바에 방문자 키를 입력하면 됩니다.

### 📽️ 무토큰 데모 (키 없는 방문자용)

공개 데모에서 **누구의 토큰도 소모하지 않고** '입력 → 실제 3-Agent 출력'을 볼 수 있습니다.
실제 파이프라인을 미리 1회 실행해 구운 결과([demo_fixtures.json](loan_agent/demo_fixtures.json))를
Streamlit 사이드바의 "📽️ 토큰 없이 데모 보기" 버튼과 API `GET /demo`로 제공합니다.
직접 실행하려는 방문자는 자기 OpenAI 키를 입력하면 됩니다.

### API 키 없이 심사 로직만 검증

핵심 안전장치인 결정적 심사 로직은 키 없이 바로 테스트할 수 있습니다.

```bash
python3 -c "from loan_agent import core; core.run_logic_selftest(core.TEST_CASES + core.EDGE_CASES)"
```

**실행 결과 (5/5 전체 통과):**

```
[승인 케이스]          ✅  판정 승인가능 (상환 여유, DSR 0.083)
[상담필요 케이스]      ✅  판정 상담필요 (상환 보통, DSR 0.348)
[어려움 케이스]        ✅  판정 어려움   (상환 부족, DSR 0.430)
[담보 보유 저신용]     ✅  판정 승인가능 (담보로 저신용 구간 적격 상품 확보)
[계약직 소액]          ✅  판정 승인가능 (직장조건·소액 한도 하드규칙 검증)
============================================================
결과: 전체 통과 (5/5)
```

기본 3케이스(승인/상담필요/어려움)에 더해, 담보·직장조건 하드규칙을 검증하는
엣지케이스 2종을 추가로 실행해 규칙 커버리지를 넓혔습니다.

### 자동화 테스트 (pytest + CI)

단위 테스트는 `tests/`에 있으며 **crewai/streamlit 등 무거운 의존성 없이** 동작합니다
(결정적 로직·파서·다기준 랭킹·경계값). push·PR마다 [GitHub Actions](.github/workflows/ci.yml)가 자동 실행합니다.

```bash
pip install -r requirements-dev.txt
pytest
```

## 로드맵

- [x] **DSR 심사 고도화** — 간이 DTI(`기존부채 ÷ 연소득`)를 금융위 실제 정의인
  **DSR(연간 원리금상환액 ÷ 연소득)**로 교체. 기존부채와 신규 희망금액을 모두
  원리금균등상환으로 월상환액을 산출해 합산하므로, 예전엔 못 잡던 '기존부채 0 + 거액 신청'도
  정확히 상환부담으로 반영됩니다(예: 월소득 300만·부채 0·희망 1억 → 예전 "여유" → 현재 "부족").
  판정 밴드 40%는 은행권 실제 DSR 규제 상한을 반영. *(남은 단순화: 대표 고정금리·기간 가정)*
- [x] **다기준 상품 랭킹** — 최저금리 단일 → 금리·승인여유·중도상환수수료 3단 정렬 + 상위 3위 후보.
  CSV에 금감원 「금융상품 한눈에」 공시 컬럼(상환방식·금리방식·중도상환수수료)을 추가.
- [x] **pytest + CI(GitHub Actions)** — 인라인 자체 테스트를 `pytest`로 분리(37개), push마다 자동 검증.
  단위·API 테스트는 무거운 LLM 의존성 없이 동작하도록 `core`를 crewai 없이 import 가능하게 개선.
- [x] **FastAPI 서비스 계층** — `core`를 REST API(`/screen`·`/advise` 등)로 노출. 결정적/LLM 경로를
  URL로 분리, OpenAPI 자동 문서, 값비싼 호출 전 방어(422/503). [기술노트](docs/기술노트_FastAPI서비스화.md).
- [x] **방문자 키 입력 + 비용 보호장치** — 세션 한정 키(누출 방지), 입력/횟수 상한·쿨다운.
- [x] **무토큰 데모** — 키 없는 방문자도 사전 녹화된 실제 결과 열람(토큰 0).
- [x] **Docker화** — 이식 가능한 컨테이너 이미지([Dockerfile](Dockerfile)), 로컬 빌드·기동 검증 완료.
- [ ] **Streamlit Community Cloud 라이브 데모** — GitHub 연동으로 공개 URL 제공(예정).

---

작성자: 원광식 · 교육 과정 실습 프로젝트를 포트폴리오용으로 정리
