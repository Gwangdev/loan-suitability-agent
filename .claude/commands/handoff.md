---
description: 산출물 프롬프트 생성 — 개발 컨텍스트를 담은 자립형 프롬프트를 만든다. 실행은 Claude·Codex 아무나.
argument-hint: document | report [technical-project|business-strategy|policy-research|brief] [black|orange|blue|vermilion] [classic|modern|formal] [문체 파일 경로(선택)] | publish | ppt
---

# /handoff — 산출물 프롬프트 생성

## 이 커맨드가 하는 일과 하지 않는 일

**한다:** 개발 컨텍스트를 증거와 함께 모아 실행용 프롬프트를 쓴다. `report`는 판단 브리프를 함께 쓴다.
**하지 않는다:** 보고서·슬라이드·문서를 직접 만들지 않는다.

생성된 프롬프트는 **Claude와 Codex 어느 쪽에서 실행해도 같은 결과가 나오도록** 쓴다. 실행 주체를 가정하는 표현(서브에이전트 호출, 특정 커맨드 실행)을 프롬프트에 넣지 않는다.

**문체·구성·디자인은 프롬프트에 옮기지 않는다.** 문체·디자인은 스타일 파일, 보고서 구성은
콘텐츠 계약과 선택된 프로필이 맡는다. 실행 주체가 해당 파일을 직접 읽으며 프롬프트에는
**어느 파일을 읽으라는 지시**만 넣는다. 옮겨 적으면 사본이 생긴다.

## 유형별 대응표

| `$ARGUMENTS` | 스타일 파일(기본) | 추가로 읽을 파일 | 출력물 |
|---|---|---|---|
| `document` | — | `reference/project-schema.yaml`, `reference/evidence-schema.yaml`, `reference/publishing-rules.md` | `docs/portfolio/evidence.yaml`·`project.yaml`·`PROJECTS.md` |
| `report` | `reference/report-style.md` + `reference/report.css` | `reference/report-contract.md`, 선택된 `reference/report-profiles/` 파일, `reference/ai-tell-checklist.md`, 실행형이면 `reference/report-exec-harness.md`(+ 스택별 파일, 예: `reference/stack-spring.md`) | `prompts/report-brief.json`·`report-prompt.md` → `report/보고서.md` → `output/보고서.html`·`보고서.pdf` |
| `publish` | — | `reference/publishing-rules.md`, `reference/portfolio-criteria.md`, `reference/ai-tell-checklist.md` | `generated/internal/`·`generated/public/` |
| `ppt` | `reference/ppt-style.md` | **`reference/deck-contract.md`** | `deck.json` → 슬라이드 |

`report`의 두 번째 인자가 `technical-project`, `business-strategy`, `policy-research`, `brief` 중
하나면 보고서 프로필이다. 세 번째부터는 두 축을 **독립적으로** 인식한다.

- `black`·`orange`·`blue`·`vermilion`, `classic`·`modern`·`formal` 중 하나에 해당하는 값은
  조판 값(색·레이아웃)이다. 순서는 무관하다. 둘 다 없으면 **임의로 고르지 말고** 사용자에게
  확인한다. `layout`을 생략하면 `classic`이 기본이다.
- `formal`은 관공서 용역보고서 판면을 실측 이식한 축이다. 기본 판단 규칙과 넷이 충돌하므로
  (위계 4단계·불릿 중심·주석열 좌측·러닝 헤더 없음) **문체 파일로
  `reference/examples/report-style-formal.md`를 함께 지정한다.** 그 파일 없이 이 축만 켜면
  본문 규칙과 조판이 어긋난다. 기본 색은 `vermilion`이다.
- 위 일곱 값 중 어느 것과도 일치하지 않는 값은 **문체 파일 경로**로 해석한다(하위 호환).
  `reference/report-style.md`를 대체해 문체·판단 규칙만 바꾸며, 색·조판 선택에는 영향을 주지
  않는다. 지정 경로에 파일이 없으면 **임의로 지어내지 말고** 사용자에게 확인한다.
  예: `/handoff report policy-research reference/examples/report-style-academic.md orange`

## `report` 유형의 추가 규약

사용자는 기본적으로 `/handoff report` 한 번만 실행한다. 내부에서는 보고서 설계와 작성을
분리하되 계획을 중복하지 않는다.

```text
증거 추출 + 보고서 판단 1회 → prompts/report-brief.json
→ 경로만 담은 prompts/report-prompt.md → 실행 주체가 작성 1회 → 통합 감사 1회
```

### 프로필 선택

명시하지 않으면 다음 순서로 하나만 자동 선택한다.

1. 1~4쪽 요약, 브리핑, 메모 요구가 있으면 `brief`
2. `SPEC.yaml`, 코드, 테스트, 실행 증빙이 주된 근거면 `technical-project`
3. 법·정책·공공 쟁점, 국가 비교, 찬반 대안 분석이면 `policy-research`
4. 시장·산업·전략·사업 선택이면 `business-strategy`
5. 여전히 모호하면 현재 하네스의 기본 용도인 `technical-project`

선택된 `reference/report-profiles/<프로필>.md` 하나만 프롬프트에 지정한다. 나머지 프로필은
읽거나 비교하지 않는다. 자동 선택 근거를 브리프의 `profile_reason` 한 줄에 기록한다.

### 질문 최소화

파일과 증거에서 추론할 수 있으면 질문하지 않는다. 결과를 크게 바꾸는 아래 정보가 없을 때만
한 번에 하나씩 묻는다.

1. 구체적 독자
2. 독자가 보고서를 읽은 뒤 내릴 결정
3. 제출처가 강제한 분량 또는 형식

목차, 차트 종류, 문체, 색상은 묻지 않는다. 프로필·계약·스타일 파일에서 결정한다.

### 브리프 생성과 검증

`reference/report-contract.md`의 스키마로 `prompts/report-brief.json`을 만든다. 원문 문단이나
스타일 규칙을 복사하지 않고 주장, 근거 위치, 반대 근거, 구성, 시각화 메시지만 기록한다.
핵심 주장은 12개 이하를 기본으로 하되 복잡한 보고서에서 근거를 잃으면서 줄이지 않는다.

다음 명령이 통과해야 프롬프트를 만든다.

```bash
python3 tools/gate.py prompts
```

`R0~R3` BLOCK은 브리프만 고친 뒤 한 번 다시 실행한다. 최종 보고서의 문체나 한계 절을
브리프 단계에서 중복 검사하지 않는다. `R4`는 원문 복사로 브리프가 12,000자를 넘었을 때만
경고한다.

## `ppt` 유형의 추가 규약

`ppt`는 슬라이드 구성안을 산문으로 쓰지 않는다. **`deck.json`을 먼저 만들게 한다.**
게이트 `K1~K9`이 대조할 수 있는 형태여야 검증이 의견이 아니라 판정이 된다. 코드에 `SPEC.yaml`이 있는 것과 같은 이유다.

- 구조·판단 규칙은 `reference/deck-contract.md`(교체 불가), 시각·톤은 `reference/ppt-style.md`(교체 가능). **둘 다 경로만 프롬프트에 싣는다**
**시작 시 사용자에게 5개를 묻는다.** 답을 받아야 프롬프트를 쓴다. 사용자가 `deck.json` 스키마를 직접 볼 일이 없게 하는 것이 목적이다.

| # | 질문 | 채우는 곳 |
|---|---|---|
| 1 | 주제와 슬라이드 수 | `meta.title` |
| 2 | 대상 — **직군·연차까지** | `meta.audience` |
| 3 | 강의 **주제** 도메인 | `meta.subject_domain` |
| 4 | **예시**를 몰아넣을 도메인 | `meta.home_domain` |
| 5 | **반드시 담아야 할 실무 판단 3가지** | 본문 전체 |

- 2번에 「실무자」·「개발자」처럼 뭉뚱그린 답이 오면 **다시 묻는다.** 대상이 흐리면 교과서 난이도로 쓰인다
- 3번이 IT 강의인데 비어 있으면 `it`을 제안한다. 빠지면 `K8`이 무력해진다
- **5번이 비면 프롬프트를 쓰지 않고 멈춘다.** 게이트는 형식만 보므로 이것이 유일한 방어선이다
- 실행 후 검증: `python3 tools/gate.py <deck.json 경로>`

## 시작 조건

`PROJECT_STATE.md` read. **「완료 판정」이 `미판정`이면 사용자에게 확인한다.** 미완료 상태로도 만들 수 있으나 판정 상태를 프롬프트에 그대로 싣는다(`조건부 완료`·`배포 보류`를 `완료`로 바꾸지 않는다).

## 컨텍스트 수집

`project-evidence-extractor`(읽기 전용)로 다음에서 사실을 모은다. Git 로그가 필요하면 먼저 `git log --oneline`·`git log --stat` 결과를 파일로 저장해 전달한다.

- `PROJECT_STATE.md`, `PROJECT_LOG.md`, `SPEC.yaml`
- 코드·테스트·실행 로그
- Git commit·PR·Issue
- 사용자가 제공한 대화 요약·기획 문서

**모든 사실에 근거 위치(파일·커밋·로그)를 붙인다.** `report`는 검증된 사실과 검증 범위가
명확한 부분 검증 사실만 `report-brief.json`의 주장으로 승격한다. 부분 검증은 확인된 범위와
한계를 함께 기록한다. 근거가 없으면 브리프에 넣지 않고 질문 또는 중단
사유로 남긴다. 다른 유형은 기존처럼 `[미검증]`·`[확인 필요]` 라벨을 유지한 채 분리한다.

## 프롬프트 파일 구성

`prompts/<유형>-prompt.md`로 쓴다. `report`를 제외한 유형은 아래 순서를 지킨다.

1. **역할과 목표** — 무엇을 만드는가, 출력 파일 경로
2. **읽을 파일** — 스타일 파일과 추가 참조 파일의 **경로**. 내용을 옮기지 않는다
3. **개발 컨텍스트** — 아래 항목을 근거와 함께. 이 절이 이 커맨드의 산출물이다
   - 문제 정의·범위·제외 범위
   - 적용 규제·데이터 등급·금지 자동화 행위
   - 주요 설계 결정과 근거, **뒤집은 결정과 그 이유**
   - `SPEC.yaml` 공개 표면과 각 항목이 충족하는 요구사항
   - 구현 상태·테스트 결과(실행 증거 위치 포함)
   - 검증 판정과 피드백 대장 요약
   - 실패·폐기한 접근·한계·미해결 라벨
   - 명세 개정 이력(있으면)
4. **불변 규칙** — 아래 §불변 규칙을 그대로 싣는다. 스타일 파일로 덮어쓸 수 없다
5. **완료 확인** — 산출물을 프로젝트로 되돌린 뒤 `python3 tools/gate.py <출력 경로>` 실행. BLOCK 잔존 시 완료 아님

`report` 프롬프트는 중복 컨텍스트를 피하기 위해 아래 다섯 항목만 쓴다.

1. **역할과 출력 경로** — 보고서 작성자, `report/보고서.md`(단일 사실 원본), 실행형이면
   `output/보고서.html`·`보고서.pdf`도 만든다. `theme`·`layout` 값을 명시한다
2. **읽을 파일 경로** — `report-brief.json`, `report-contract.md`, 선택 프로필, `report-style.md`,
   `report.css`, `ai-tell-checklist.md`, 실행형일 때만 `report-exec-harness.md`(+ 스택 파일)
3. **실행 지시** — 브리프를 다시 기획하지 말고 근거 원문을 확인한 뒤 본문 작성,
   Executive Summary는 본문 뒤 한 번 작성. 기존 보고서가 있으면 실행 전에 `*.bak.md`로
   백업하고 `<!-- manual -->` 구간은 보존. 실행형이면 HTML까지 만든 뒤 **PDF 렌더 전 사용자
   승인**을 받는다(`reference/report-exec-harness.md` §2)
4. **통합 감사** — 계약 §6을 한 번 실행하고 검출된 부분만 수정. 별도 감사 에이전트와
   자체 감사를 연속 실행하지 않음
5. **완료 확인** — 브리프는 `python3 tools/gate.py prompts`, 완성본은
   `python3 tools/gate.py report`로 각 단계에서 한 번씩 실행. PDF가 있으면 렌더 검수

`PROJECT_STATE.md`, `PROJECT_LOG.md`, `SPEC.yaml`의 내용을 프롬프트에 다시 복사하지 않는다.
필요한 판단과 근거 위치는 이미 브리프가 갖는다.

## 불변 규칙 (프롬프트에 반드시 포함)

- 증거 없는 수치·성과를 만들지 않는다. `[미검증]`·`[확인 필요]`가 본문에 남으면 완료가 아니다
- 개인 기여와 팀 기여를 구분한다
- 계획·아이디어와 실제 구현을 구분한다
- **실패·폐기한 접근·한계를 반드시 포함한다. 최소 1건.** 없다고 쓰지 말고 찾는다
- 약어를 원어로 풀어 쓰지 않는다
- 민감정보(키·내부 URL·개인정보)는 `reference/publishing-rules.md`의 스캔을 통과해야 한다
- 스타일 파일이 위 규칙과 충돌하면 **위 규칙이 우선**하고, 무엇을 조정했는지 출력 서두에 한 줄로 밝힌다

## 완료 점검

- `report`면 `prompts/report-brief.json`과 `prompts/report-prompt.md`, 그 밖의 유형은
  `prompts/<유형>-prompt.md`를 생성한다. **자립형인지 확인한다** — 대화 맥락 없이도 파일 경로와
  작업을 이해할 수 있는가
- 스타일 내용이 프롬프트 본문에 복사되지 않았는지 확인한다. 경로 참조만 있어야 한다
- `PROJECT_LOG.md`의 "포트폴리오 자동화 상태"에 생성한 프롬프트와 실행 주체 예정을 기록한다
- `PROJECT_STATE.md`는 다음 작업만 갱신하고 버전+1

**프롬프트를 만들고 멈춘다. 실행하지 않는다.** 실행 주체는 사용자가 그때 정한다.

## 산출물이 돌아왔을 때

외부에서 만든 산출물을 프로젝트에 넣은 뒤 `python3 tools/gate.py <경로>`를 실행한다.
브리프 축(R0 파싱·R1 판단 구조·R2 주장 근거·R3 시각화 근거)과 문서 축(D1~D6)은 서로 다른
단계만 검사한다. PDF가 있으면 report artifacts 축(D7·D8·E1~E9)이 Markdown·HTML·PDF의
일관성과 `report.css` 준수, 판면 침범까지 함께 검사한다.
**BLOCK이 남으면 산출물을 되돌려 고친다.** 누가 만들었는지는 판정에 영향을 주지 않는다.
