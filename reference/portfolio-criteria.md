# 포트폴리오·보고서 발행 기준

> `/handoff publish`가 생성하는 프롬프트에 포함된다. Claude가 실행 주체면 `independent-verifier`가 이 목록으로 검증하고, Codex가 실행 주체면 `python3 tools/gate.py <출력 경로>`로 기계 검증한다.
> `/verify`(개발 완료 판정) 시점에는 `project.yaml`이 존재하지 않으므로 여기서 분리해 검증한다.

## 1. 귀속·근거

- 개인 기여와 팀 기여가 구분됨
- 계획·아이디어와 실제 구현이 구분됨 (`stage: planned | implemented`)
- 모든 성과 수치에 증거와 **측정 조건**(환경·표본 수·시점)이 연결됨
- **검토한 대안에 증거가 있음** — `decisions[].alternatives_considered[].evidence`가 비어 있으면 "검토했다"고 서술하지 않는다. 실제로 시도·조사한 흔적(커밋·문서·로그) 없이 대안을 나열하는 것은 금지한다.
- `project.yaml`의 `needs_review` 항목을 사용자가 검토하고 처리함

## 2. AI 활용 기록

- `ai_usage.used`가 `null`이 아님 (사용 여부를 명시했음)
- `used: true`인 경우 `generated_scope` · `human_judgment` · `verification`이 모두 채워져 있음
- AI 생성 산출물 중 **사람 검증 근거가 없는 항목**이 `public` 문서에 포함되지 않음
- 검증 없이 게시하지 않는다. 이 항목은 은폐가 아니라 공개가 목적이다.

## 3. 트러블슈팅 서술

- 가설(`hypotheses`)과 확인된 원인(`cause`)이 분리되어 있음
- 검증되지 않은 가설(`result: untested`)이 원인으로 서술되지 않음
- 실패한 시도가 최소 1건 기록됨 (전부 성공한 서술은 신뢰도를 떨어뜨린다)
- `recurrence_prevention`이 기재됨

## 4. README–코드 일치 (기계 검증)

`readme_consistency`를 실제로 대조해 기록한다. 선언이 아니라 확인이다.

- **실행 명령:** README의 실행·빌드·테스트 명령이 `package.json` scripts / `Makefile` / `pyproject.toml` / 실제 스크립트 파일에 존재하는가
- **환경변수:** README에 문서화된 변수가 코드에서 실제로 참조되는가. 반대로 코드가 읽는데 문서에 없는 변수가 있는가
- **기능 목록:** 나열된 기능에 대응하는 구현·테스트가 있는가
- **링크:** repository·demo 링크가 비어 있거나 플레이스홀더가 아닌가

불일치가 1건이라도 있으면 `mismatches`에 기록하고 `public` 생성을 보류한다.

## 5. 산출물 기계 게이트 (public 생성 전 필수)

`python3 tools/gate.py <산출물 경로>`를 실행한다. `/verify` 시점에는 보고서·공개 초안이 존재하지 않아 문서 축이 작동하지 않으므로, 여기서 한 번 더 돌린다.

- **D1** 약어 원문 병기 — 실무 문서에서 API·DTO·CI를 풀어 쓰지 않는다
- **D2** 한계·미해결 절 부재 — §3의 "실패한 시도 최소 1건"과 같은 취지
- **D3** 문장 길이 균질 — 변동계수 0.45 미만
- **D4** 헤지 과다 — 확인된 것은 단정한다
- **H·P 축** — 도구 흔적·빌드 산출물·식별정보 잔존

BLOCK 잔존 시 `public` 생성을 보류한다. WARN은 사유를 기록하고 통과시킬 수 있다.

## 6. 민감정보·승인

- 외부 공개 대상 문서에 민감정보 없음 (`publishing-rules.md` 스캔 통과)
- `project.yaml`의 `status`가 `/verify` 판정과 일치함 (매핑은 `project-schema.yaml` 참조)
- `publication.approved: true` 이고 `approved_at`이 기록됨

## 7. 문체 (보고서·블로그 초안 대상)

- `prose-auditor` 감사 판정이 `통과`
- `reference/ai-tell-checklist.md` §4 자동 검출 결과를 처리함

## 판정

전부 충족 시 `public` 산출물 생성 허용. 하나라도 미충족이면 `internal` 초안만 생성하고 미충족 항목을 함께 출력한다.
