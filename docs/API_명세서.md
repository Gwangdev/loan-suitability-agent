# API 명세서

[개발자 가이드](개발자_가이드.md) · [데이터 흐름](데이터_흐름.md) · [데이터 모델](데이터모델.md)

이 명세서는 2026-09-13 작업 트리의 라우터·직렬화 함수·미들웨어를 기준으로 한다. 요구사항 계약은 [SPEC.yaml](../SPEC.yaml)에 있다. `SPEC.yaml`은 자체 명세 형식이며 OpenAPI 파일은 아니다. FastAPI의 OpenAPI는 로컬 `/openapi.json`, Swagger는 `/docs`에서 제공한다. 현재 여러 응답이 `dict`로 반환되어 자동 OpenAPI에는 상세 응답 필드가 충분히 기술되지 않으므로 아래 표를 함께 읽는다.

## 1. 접속과 공통 규칙

| 항목 | 계약 |
|---|---|
| 로컬 Base URL | `http://localhost:8000` |
| 업무 경로 | `/api/v1` |
| 운영 공개 URL | `https://loan.gwang.dev`는 Streamlit 화면. 공개 API Base URL이 아님 |
| 본문 | JSON. 본문이 있으면 `Content-Type: application/json` 사용 |
| 성공 응답 | `application/json` |
| 오류 응답 | `application/problem+json` |
| 인증 | 사용자 인증·자원 소유권 검증 없음. 방문자 모델 키는 서비스 인증 토큰이 아님 |
| 식별자 | 심사·설명 UUID, 경로의 잘못된 UUID는 422 |
| 금액과 비율 | 입력 금액은 원 단위 정수. `dsr=0.155`는 15.5%, `연금리=0.06`은 6% |

| 요청 헤더 | 적용 경로 | 의미 |
|---|---|---|
| `Idempotency-Key` | `POST /api/v1/assessments`에 필수 | 같은 키·같은 검증 후 입력은 기존 심사, 다른 입력은 409. 비어 있지 않은 고유값 사용을 권장하나 현재 구현은 문자열 길이를 제한하지 않음 |
| `X-OpenAI-API-Key` | `POST /api/v1/parsing-preview`, `POST /api/v1/assessments/{assessment_id}/explanation-runs`에 선택 | 값이 있으면 방문자 키로 LLM 실행. 현재 분기는 헤더의 존재만이 아니라 비어 있지 않은 값인지로 결정 |

제약 근거: [라우터](../loan_agent/api/), [키 헤더 상수](../loan_agent/api/contract.py), [오류 처리](../loan_agent/api/errors.py), [상한 미들웨어](../loan_agent/api/limits.py).

## 2. 엔드포인트 목록

| 메서드 | 경로 | 정상 HTTP | 결과 |
|---|---|---|---|
| POST | `/api/v1/assessments` | 201 새 심사 / 200 재전송 | 심사 상세 |
| GET | `/api/v1/assessments` | 200 | `{items, next_cursor}` |
| GET | `/api/v1/assessments/{assessment_id}` | 200 | 심사 상세 |
| POST | `/api/v1/parsing-preview` | 200 | 독립 파싱 후보·불일치·누락 |
| POST | `/api/v1/assessments/{assessment_id}/explanation-runs` | 200 방문자 키 / 201 키 없는 작업 생성 | 설명 실행 한 건 |
| GET | `/api/v1/assessments/{assessment_id}/explanation-runs` | 200 | `{items: [설명 실행]}` |
| GET | `/api/v1/demo-cases` | 200 | 녹화 픽스처 객체 |
| GET | `/health/live` | 200 | 프로세스 생존 |
| GET | `/health/ready` | 200 | DB·마이그레이션 준비 |

## 3. 심사 생성과 상세 조회

`POST /api/v1/assessments`는 LLM 호출 없이 입력을 판정하고 심사·판정·추천·PENDING 설명 작업·감사 이벤트를 한 트랜잭션에 저장한다. 추가 입력 필드는 금지한다.

| JSON 필드 | 타입 | 필수 | 검증 / 기본값 |
|---|---|---|---|
| `monthly_income` | integer | 예 | > 0 |
| `existing_debt` | integer | 예 | ≥ 0. 미입력을 무부채 0으로 대체하지 말 것 |
| `credit_grade` | integer | 예 | 1..10 |
| `requested_amount` | integer | 예 | > 0 |
| `employment_type` | string | 예 | `정규직`, `계약직`, `제한없음` |
| `collateral_owned` | boolean | 아니오 | 기본 `false` |

아래는 합성 입력을 사용하는 로컬 호출이다. 같은 명령을 다시 보내면 같은 심사가 반환된다. 새 심사를 만들려면 키를 바꾼다.

```bash
curl -i http://localhost:8000/api/v1/assessments \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: docs-synthetic-assessment-001' \
  -d '{"monthly_income":3500000,"existing_debt":8000000,"credit_grade":3,"requested_amount":20000000,"employment_type":"정규직","collateral_owned":false}'
```

`POST`와 `GET /api/v1/assessments/{assessment_id}`는 아래와 같은 심사 표현을 사용한다.

| 응답 필드 | 타입 | 의미 |
|---|---|---|
| `assessment_id` | UUID string | 심사 ID |
| `status` | string | `SCREENED`, `COMPLETED`, `EXPLANATION_FAILED`, `REVIEW_REQUIRED` |
| `created_at` | datetime string | 생성 시각 |
| `decision` | object | 아래 결정적 결과 |
| `recommendations` | array | 현재 코어가 산출하는 적격 추천 0..3건, 순위순 |
| `explanation_runs` | array | 실행 시도와 각 Eval. §6의 표현 |

`decision`의 필드:

| 필드 | 타입 | 의미 |
|---|---|---|
| `verdict` | string | `ELIGIBLE` 승인가능 / `CONDITIONAL` 상담필요 / `INELIGIBLE` 어려움. 실제 대출 승인 여부가 아님 |
| `repayment_band` | string | `COMFORTABLE` 여유 / `MODERATE` 보통 / `STRAINED` 부족 |
| `dsr` | number | 코어가 소수 셋째 자리로 반올림한 비율. 밴드 판정은 반올림 전 값으로 수행 |
| `monthly_payment` | object | `기존부채`, `신규대출`, `합계`는 원 단위 숫자, `가정`은 `{연금리, 기간개월}` |
| `rule_version` | string | 규칙 버전 |
| `product_dataset_version` | string | 합성 CSV 내용에서 산출한 버전 해시 |

앞의 요청을 현재 코어로 계산한 `decision` 예시다. 전체 HTTP 응답이 아니라 해당 필드만 발췌했다. UUID·시각은 실행마다 달라지고 상품 CSV를 변경하면 버전도 달라진다.

```json
{
  "verdict": "ELIGIBLE",
  "repayment_band": "COMFORTABLE",
  "dsr": 0.155,
  "monthly_payment": {
    "기존부채": 154662,
    "신규대출": 386656,
    "합계": 541318,
    "가정": {"연금리": 0.06, "기간개월": 60}
  },
  "rule_version": "screening-2026.08",
  "product_dataset_version": "csv-fcd53a57bef4"
}
```

추천 한 건의 필드:

| 필드 | 타입 | 의미 |
|---|---|---|
| `product_code`, `product_name`, `bank` | string | 합성 상품 코드·명칭·기관 |
| `rank` | integer | 1부터 시작하는 추천 순위 |
| `eligible` | boolean | 현재 생성 경로는 적격 추천만 저장하므로 `true` |
| `interest_rate_range` | string | 예: `4.2%~7.5%` |
| `maximum_limit` | integer | 원 단위 한도 |
| `repayment_method`, `rate_type` | string | 상환방식·금리방식 |
| `early_repayment_fee` | number | CSV의 수수료 값. `1.0`은 1.0% |
| `approval_margin` | integer | 상품 필요신용등급 - 입력 신용등급. 실제 승인 확률이 아님 |

같은 키의 재전송은 이전 응답 본문을 캐시해서 복제하지 않는다. **기존 자원의 현재 표현**을 반환하므로 그 사이 설명이 끝났다면 상태·설명 배열이 달라질 수 있다. 같은 내용이라도 다른 키는 새로운 심사다. 근거: [assessments](../loan_agent/api/assessments.py), [decision](../loan_agent/decision.py), [core](../loan_agent/core.py).

## 4. 심사 목록

`GET /api/v1/assessments`

| 쿼리 | 타입 | 기본 / 규칙 |
|---|---|---|
| `status` | string | 선택. 심사 상태 네 값만 허용 |
| `from` | datetime | 선택. 생성 시각 ≥ 값 |
| `to` | datetime | 선택. 생성 시각 ≤ 값 |
| `cursor` | string | 선택. 이전 응답의 `next_cursor`를 그대로 전달 |
| `limit` | integer | 기본 20, 1..100 |

```bash
curl -G http://localhost:8000/api/v1/assessments \
  --data-urlencode 'status=SCREENED' \
  --data-urlencode 'from=2026-09-01T00:00:00+09:00' \
  --data-urlencode 'limit=20'
```

응답은 `{ "items": [{"assessment_id": "UUID", "status": "SCREENED", "created_at": "시각"}], "next_cursor": "문자열 또는 null" }` 형식이다. `items`에는 요약만 있고 상세 판정은 상세 조회로 읽는다. `(created_at DESC, id DESC)`로 정렬하며 `next_cursor=null`이면 다음 페이지가 없다. 빈 결과는 아래처럼 200으로 응답한다.

```json
{"items": [], "next_cursor": null}
```

커서는 같은 필터 조건으로 이어서 사용한다. 날짜에는 시간대 포함을 권장한다. 현재 구현은 `from <= to`를 별도로 검사하지 않으므로 역전된 기간을 422로 기대하지 않는다. 근거: [list_assessments](../loan_agent/api/assessments.py).

## 5. 파싱 미리보기

`POST /api/v1/parsing-preview`

본문은 `{"text": "합성 상담 내용"}`이다. `text`는 필수 문자열로 1..10,000자이며, 추가 필드는 금지한다. 이 요청은 DB에 저장하지 않는다.

```bash
curl http://localhost:8000/api/v1/parsing-preview \
  -H 'Content-Type: application/json' \
  -d '{"text":"월급 350만원 정규직, 부채 800만원, 신용등급 3등급, 2000만원 대출 희망"}'
```

키 없는 호출을 로컬 TestClient로 확인한 응답:

```json
{
  "rule_candidate": {
    "월소득": 3500000,
    "부채": 8000000,
    "신용등급": 3,
    "희망금액": 20000000,
    "직장유형": "정규직",
    "담보보유": false
  },
  "llm_candidate": null,
  "mismatched_fields": [],
  "parse_accuracy": null,
  "missing_fields": [],
  "degraded": true
}
```

| 필드 | 타입 | 의미 |
|---|---|---|
| `rule_candidate` | object | 규칙 파서의 한글 키 후보. 읽지 못한 부채는 `null`, 부채 0은 유효 입력 |
| `llm_candidate` | object 또는 null | 방문자 키가 있으면 LLM JSON 후보. 키 없으면 null |
| `mismatched_fields` | string array | 두 후보가 다른 필드 이름 |
| `parse_accuracy` | boolean 또는 null | 후보 비교 결과. 비교할 LLM 후보가 없으면 null |
| `missing_fields` | string array | 규칙 후보 기준 필수 입력 누락 이름 |
| `degraded` | boolean | LLM 후보가 없으면 true |

두 후보는 자동 병합하지 않는다. 후보의 키는 한글이고 심사 요청의 키는 영문이므로 호출자는 §3의 필드로 옮기고 값을 확인해야 한다. LLM 후보는 현재 JSON 객체 여부만 확인하며, 응답을 검증된 `AssessmentRequest`로 간주하지 않는다. **키가 없는 경우의 정상 축소 경로와, 키가 있는데 제공자 호출·JSON 파싱이 실패하는 경우는 다르다.** 후자는 현재 자동 폴백 없이 공통 500 처리로 이어질 수 있다. 근거: [parsing](../loan_agent/api/parsing.py), [parse_with_llm](../loan_agent/llm.py), [후보 평가](../loan_agent/eval.py).

## 6. 설명 생성·재시도·이력

`POST /api/v1/assessments/{assessment_id}/explanation-runs`는 요청 본문이 없다.

| 키 / 기존 상태 | 실제 처리 | HTTP |
|---|---|---|
| 방문자 키 있음 / PENDING | 기존 행을 확보해 app 안에서 동기 실행 | 200 |
| 방문자 키 있음 / 200초가 지난 RUNNING | 기존 실행 행을 회수해 동기 실행 | 200 |
| 방문자 키 있음 / 유효한 RUNNING | 기존 실행과 충돌 | 409 |
| 방문자 키 있음 / 진행 중 실행 없음 | 새 실행 행 생성 후 동기 실행 | 200 |
| 키 없음 / 진행 중 실행 없음 | 새 PENDING 생성, 로컬 워커 처리 대기 | 201 |
| 키 없음 / PENDING 또는 RUNNING 있음 | 진행 중 작업과 충돌 | 409 |

심사 생성 자체가 PENDING을 만들기 때문에, **생성 직후 키 없이 이 POST를 호출하면 일반적으로 409**다. 로컬 비동기 흐름에서는 기존 작업을 워커가 처리하게 두고 GET으로 관측한다. 공개 배포에는 워커가 없어 키 없는 새 작업은 자동 처리되지 않는다.

응답과 `GET /api/v1/assessments/{assessment_id}/explanation-runs`의 `items` 요소는 다음 필드를 가진다.

| 필드 | 타입 | 의미 |
|---|---|---|
| `id` | UUID string | 설명 실행 ID |
| `status` | string | `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `REVIEW_REQUIRED` |
| `model_name`, `prompt_version` | string 또는 null | 실행 모델·프롬프트 버전 |
| `started_at`, `finished_at` | datetime string 또는 null | 실행 시작·완료 시각 |
| `latency_ms` | integer 또는 null | 실행 처리 시간 |
| `input_tokens`, `output_tokens` | integer 또는 null | 사용량. 제공자 정보가 없으면 null |
| `error_code` | string 또는 null | 현재 `PROVIDER_ERROR`, `PROVIDER_TIMEOUT` |
| `explanation_text` | string 또는 null | Eval을 통과해 저장한 안내문 |
| `eval_result` | object 또는 null | 아래 평가 표현 |

Eval 표현은 `parse_accuracy`, `verdict_consistency`, `disclaimer_present`, `recommendation_consistency`, `numeric_grounding`, `conditional_language`, `passed` 불리언과 `detail` 객체다.

**채점 결과:** 동기 POST 응답도 저장된 Eval을 함께 반환하며, 같은 실행을 실행 이력 GET이나 심사 상세 GET으로 읽은 값과 같다. 키 없이 만든 PENDING 실행은 아직 채점 전이라 `eval_result=null`이다. 또한 설명 실행 경로의 `parse_accuracy=true`는 독립 파싱 측정치가 아니다. [데이터 흐름](데이터_흐름.md#저장-여부와-실패-결과)의 적용 범위를 참고한다.

클라이언트는 HTTP 코드 다음에 업무 상태를 확인한다.

1. 200이어도 `status=FAILED`·`REVIEW_REQUIRED`이면 새 안내문 생성 성공이 아니다.
2. `COMPLETED`와 `explanation_text`를 확인한 후 본문을 표시한다.
3. 생성 타임아웃은 `FAILED / PROVIDER_TIMEOUT`을 기록한 뒤 동기 요청에서 503으로 반환한다. 일반 제공자 오류는 `FAILED / PROVIDER_ERROR`인 실행 표현을 200으로 반환한다.
4. 통신 실패 후 무조건 재생성 POST를 보내지 않는다. 먼저 GET으로 실행 상태를 확인해 중복 비용을 줄인다. 설명 POST 자체는 멱등 요청 계약이 아니다.

이력은 `started_at DESC NULLS LAST, id DESC` 순서다. PENDING에는 시작 시각이 없어 뒤로 정렬된다. UUID 순서는 생성 시간 순서를 보장하지 않는다. 근거: [explanations](../loan_agent/api/explanations.py), [worker](../loan_agent/worker.py).

## 7. 녹화 데모와 헬스체크

`GET /api/v1/demo-cases`는 [demo_fixtures.json](../loan_agent/demo_fixtures.json)의 객체를 그대로 반환한다. 목록 페이지 계약이 아니며 DB·LLM 호출이 없다. 상위 필드는 `generated_at`·`model`·`note` 문자열과 `cases` 배열이다. 각 케이스에는 `name`·`input`·`expected` 문자열, `parse_check`·`result` 객체가 있다. 중첩된 녹화 내용은 해당 픽스처 파일이 기준이다. 화면은 이 결과를 사전 녹화라고 구분한다.

`GET /health/live`:

```json
{"status": "alive"}
```

`GET /health/ready`의 성공 응답:

```json
{"status": "ready", "database": "ok", "migration": "ok"}
```

ready는 DB 연결과 Alembic head 일치를 검사한다. 실패하면 공통 오류 형식의 503을 반환하며, LLM 제공자 상태는 검사하지 않는다. 근거: [demo](../loan_agent/api/demo.py), [health](../loan_agent/api/health.py), [readiness](../loan_agent/db/readiness.py).

## 8. 오류·상한

| HTTP | 조건 | 호출자의 처리 |
|---|---|---|
| 400 | Content-Length를 숫자로 해석할 수 없음 | 요청 헤더 수정 |
| 404 | 심사 없음·경로 없음 | ID·경로 확인 |
| 409 | 멱등키의 본문 충돌, 진행 중 설명과 충돌 | 입력 변경 의도 확인 또는 기존 실행 조회 |
| 413 | 선언된 Content-Length > 262,144바이트 | 본문 크기 축소 |
| 415 | 본문이 있는 요청의 타입이 JSON 아님 | Content-Type 수정 |
| 422 | 필수값·범위·UUID·쿼리 검증 실패 | `errors`의 필드·사유 확인 |
| 429 | 토큰 사용 가능 POST 경로의 주소별 요청 상한 | `Retry-After` 초만큼 대기 |
| 500 | 처리되지 않은 내부 오류, 파싱 LLM 예외 등 | 동일 요청 무한 반복 금지, 로그로 원인 확인 |
| 503 | ready 실패 또는 동기 설명 타임아웃 | 대상 경로에 따라 의존 상태·실행 이력 확인 |

422 응답 예시:

```json
{
  "type": "about:blank",
  "title": "Unprocessable Content",
  "status": 422,
  "instance": "/api/v1/assessments",
  "detail": "요청 값이 올바르지 않습니다.",
  "errors": [{"field": "body.monthly_income", "reason": "Input should be greater than 0"}]
}
```

`errors`는 입력 검증 오류에 붙는다. 입력값 원문은 포함하지 않으며, `instance`는 요청 경로다. 요청 correlation ID는 서버 로그에서 생성하고 응답 헤더에는 제공하지 않는다.

API 빈도 제한은 `parsing-preview`·`explanation-runs`로 끝나는 POST에 대해 **동일 주소에서 두 경로 합계 60회/3,600초**다. 키 유무와 무관하게 집계하며 프로세스 메모리 기준이다. 공개 경로에서는 app이 보는 주소가 UI 컨테이너로 모이므로 방문자별 할당량으로 해석하지 않는다. UI의 세션별 10회·5초 간격 제한은 별도다.

본문 상한은 현재 **Content-Length 헤더 검사**다. 실제 스트림 수신량을 누적 검사하지 않으므로 이 설명을 청크 전송까지 포함한 절대 본문 크기 보장으로 해석하지 않는다. 근거: [limits](../loan_agent/api/limits.py), [errors](../loan_agent/api/errors.py), [request_log](../loan_agent/api/request_log.py), [UI](../loan_agent/app.py).
