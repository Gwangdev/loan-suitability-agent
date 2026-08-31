# 대출 적합성 심사 — 의사결정 지원 서비스

[![CI](https://github.com/Gwangdev/loan-suitability-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Gwangdev/loan-suitability-agent/actions/workflows/ci.yml)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-loan.gwang.dev-0066cc)](https://loan.gwang.dev)

**라이브 데모: https://loan.gwang.dev**

자연어 상담 입력을 구조화하고, **결정적 규칙으로 대출 적합성을 판정**한 뒤, LLM이 그 판정을
고객이 읽을 문장으로 옮기는 교육용 데모다.

> 주의. 교육용 데모이며 실제 대출 심사·법률·금융 자문이 아니다. 상품 데이터와 입력은 합성이고,
> 실제 대출은 각 금융기관의 심사를 따른다.

---

## 핵심 설계 — LLM은 입구와 출구에만 있다

```
입구            가운데                    출구
자연어    →    적합성 판정        →    고객 안내문
              (결정적 규칙)

LLM 파서      screen_loan()            LLM 1회 호출
   +          CSV 하드규칙              확정된 판정을
규칙 파서      LLM 접근 불가             데이터로 주입
   ↓                ↓                       ↓
불일치를        같은 입력 →            공개 전 게이트
사람이 확정      같은 결과              (6지표 + 디스클레이머)
```

| 역할 | 담당 | 왜 |
|---|---|---|
| **적합성 판정** (승인가능·상담필요·어려움) | **결정적 함수** `core.screen_loan` | 같은 입력은 언제나 같은 결과. 환각에 의한 오승인·오거절이 발생할 수 없다 |
| 입력 해석 | **LLM 파서 + 규칙 파서** | 두 파서의 **불일치 자체가 검증**이다. 코드가 자동으로 화해시키지 않고 사람이 고른다 |
| 안내문 생성 | **LLM 1회 호출** | 확정된 판정·DSR·상품 상세를 데이터로 주입한다. 생성할 수치가 애초에 없다 |

**`loan_agent/core.py`에는 LLM을 부르는 코드가 한 줄도 없다.** 「판정은 코드」가 주석이 아니라
디렉터리 구조로 확인된다.

```bash
grep -c "crewai\|Agent(\|Crew(" loan_agent/core.py   # → 0
```

### 두 파서를 나란히 세우는 이유 — 실제로 걸렸다

녹화 데모를 만들 때 LLM 파서가 **"부채 200만원"을 200,000원으로, "500만원"을 500,000원으로**
읽었다. 규칙 파서는 각각 2,000,000·5,000,000으로 옳게 읽었고, 불일치가 드러나 확정 절차에서
걸러졌다. **두 파서를 나란히 세우지 않았다면 만 배 틀린 금액이 그대로 데모에 실렸다.**

그 판정 근거는 `loan_agent/demo_fixtures.json`의 `parse_check`에 남아 있다.

---

## 실행

### Docker Compose (권장)

`.env`에 PostgreSQL 자격증명을 넣는다. **LLM 키는 선택**이며, 없어도 결정적 심사와 무토큰 데모는
동작한다.

```bash
cp .env.example .env    # POSTGRES_USER·POSTGRES_PASSWORD 를 채운다
docker compose --profile local up -d --build
```

| 주소 | 내용 |
|---|---|
| http://localhost:8501 | 화면 |
| http://localhost:8000/docs | OpenAPI 문서 (Swagger) |

### 운영 배포 (AWS EC2 + Caddy)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

리버스 프록시가 **유일한 진입점**이 되어 API와 데이터 계층은 컨테이너 내부망에만 남는다. 절차는
[배포 절차서](docs/배포절차.md), 선택 근거는 [배포 계획](docs/배포계획.md)에 있다.

---

## 공개 데모에서 동작하지 않는 것

정직하게 밝힌다. 운영에는 **설명 워커와 서버 LLM 키를 두지 않는다.**

- **비동기 실행 경로가 돌지 않는다.** 아웃박스 패턴(`explanation_run(PENDING)` → 워커가 집어 실행)은
  로컬 Compose와 영상 데모에서 확인할 수 있다
- **안내문 생성에는 방문자 본인의 OpenAI 키가 필요하다.** 서버 키를 두지 않으므로 운영자의 비용이
  새지 않는다. 키는 세션 메모리에만 머물고 저장·로깅되지 않는다
- **키 없이도** 「토큰 없이 데모 보기」로 사전 녹화된 실제 출력을 열람할 수 있다(토큰 0)

근거는 [ADR-031 §31.3](docs/설계결정.md).

---

## 구조

```
loan_agent/
├── core.py            결정적 심사·규칙 파서·상품 로딩  (LLM 없음)
├── llm.py             LLM을 부르는 유일한 자리 — 입구 파싱·출구 안내문
├── decision.py        판정을 저장 가능한 형태로 옮기는 계층 + 버전 식별
├── worker.py          설명 실행기 — 아웃박스 소비자
├── eval.py            LLM 출력 품질 평가 하네스
├── api/               FastAPI — 심사·설명·파싱·데모·상태
├── db/                SQLAlchemy 모델·엔진·준비 상태
├── static/apple.css   화면 스타일 (코드가 아니라 파일)
└── demo_fixtures.json 사전 녹화 출력 (토큰 0 열람용)

alembic/versions/      스키마의 진실의 원천 — 마이그레이션 3개
docs/                  설계 결정(ADR)·데이터 모델·리스크 통제 대장·배포
```

`core`는 FastAPI·Streamlit·crewai를 import하지 않는다. 키가 필요 없는 부분(상품 로딩·심사 로직·
규칙 파서)은 무거운 의존성 없이 그대로 쓸 수 있다.

---

## API

모든 경로가 `/api/v1` 아래에 있고 오류는 RFC 9457 `application/problem+json`으로 통일한다.

| 엔드포인트 | 내용 | LLM 키 |
|---|---|---|
| `POST /assessments` | 구조화 입력 → 결정적 판정. `Idempotency-Key` 필수 | 불필요 |
| `GET /assessments` | 상태·기간 필터, 커서 페이지네이션 | 불필요 |
| `GET /assessments/{id}` | 판정·설명 상태·Eval 결과·버전 4종 | 불필요 |
| `POST /assessments/{id}/explanation-runs` | 설명 생성·재시도 | 헤더로 주면 동기 실행 |
| `GET /assessments/{id}/explanation-runs` | 실행 이력 — 모델·프롬프트 버전·지연·토큰 | 불필요 |
| `POST /parsing-preview` | **두 파서 후보와 불일치 필드**. 저장하지 않음 | 선택(없으면 규칙 파서만) |
| `GET /demo-cases` | 사전 녹화 출력 | 불필요 |
| `GET /health/live` · `GET /health/ready` | 프로세스 생존 / DB·마이그레이션 준비 | 불필요 |

공개 표면의 진실의 원천은 [`SPEC.yaml`](SPEC.yaml)이고, `tools/gate.py`가 명세와 코드를 기계 대조한다.

---

## 정합성과 운영

| 항목 | 내용 |
|---|---|
| **멱등성** | `Idempotency-Key` + 요청 해시 + **DB UNIQUE 제약**. 앱 검사와 DB 제약은 우회 경로가 달라 중복이 아니다 |
| **트랜잭션** | 심사·판정·추천·설명 작업·감사 이벤트를 한 트랜잭션에 저장 |
| **부분 실패 격리** | LLM이 실패해도 결정적 판정은 조회된다. 실행 상태와 심사 상태는 별도 어휘 |
| **아웃박스** | `explanation_run(PENDING)`을 심사와 같은 트랜잭션에 넣어 커밋과 작업 발행을 원자적으로 |
| **동시성** | `FOR UPDATE SKIP LOCKED`로 행을 집고 커밋한 뒤 LLM을 부른다 — 트랜잭션을 쥔 채 호출하지 않는다 |
| **버전 추적** | 규칙·상품 데이터·모델·프롬프트 4종을 결과에 불변 저장 |
| **계층 격리** | 3-tier 컨테이너·네트워크 분리. `postgres`는 내부망 전용, non-root + read-only |

---

## 검증

```bash
pytest                              # 110 passed
python3 -c "from loan_agent import eval; eval.run_eval_selftest()"   # 90/90
python3 tools/gate.py .             # 명세·주석·이력·보안·인프라 기계 검사
```

**Eval은 6지표 × 15케이스 = 90점**이다. 파싱정확도·판정정합성·디스클레이머·추천정합성·수치근거·
조건부표현을 사전 녹화 출력에 대해 채점하므로 **API 비용 0**이고 CI에서 돈다.

**자랑거리는 90/90이 아니라 평가기 자체를 검증한 것이다.** 디스클레이머 삭제·근거 없는 금리 삽입·
다른 상품 추천·확정 승인 표현 등 결함을 주입해 **대응 지표가 정확히 실패하는지**를 테스트한다.
[평가 리포트](docs/평가리포트.md).

---

## 한계와 미검증 범위

- 교육용 데모이며 **실제 승인·거절이나 상품 중개를 수행하지 않는다.** 상품 데이터(22건)와 입력은 합성이다
- **DSR은 단순화 모델이다.** 대표 고정금리(연 6%)·고정기간(60개월)을 가정하며 개별 상품 금리를
  반영하지 않는다. 판정 밴드 40%는 은행권 규제 상한을 참고한 값이다
- **Eval 90/90은 녹화된 15케이스와 6개 규칙 지표 안에서만 성립한다.** 표현의 자연스러움이나 실시간
  제공자 장애를 보장하지 않는다
- 인증·권한 표면이 없다. 데모에는 사칭할 두 번째 사용자가 없고, 실서비스라면 필요하다
- 법적·보안 통제의 적용 조건과 실서비스 전환 시 남는 과제는 [리스크 통제 대장](docs/리스크_통제_대장.md)에 있다

---

## 설계 기록

판단의 근거는 코드가 아니라 문서에 있다. **기각한 대안을 필수 칸으로 둔다.**

| 문서 | 내용 |
|---|---|
| [설계 결정(ADR)](docs/설계결정.md) | 33건. 왜 모놀리스인가, 왜 큐가 아닌가, 왜 금액을 `float`로 두는가 |
| [데이터 모델](docs/데이터모델.md) | ERD·상태 전이·제약·인덱스 2단계 마이그레이션 |
| [리스크 통제 대장](docs/리스크_통제_대장.md) | 법령 적용 **조건**과 데모가 그 밖에 있는 이유 — 준수 주장이 아니다 |
| [배포 계획](docs/배포계획.md) · [배포 절차](docs/배포절차.md) | TLS를 필수로 둔 이유와 실행 절차 |

---

작성자: 원광식
