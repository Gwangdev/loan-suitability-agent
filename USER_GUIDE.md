# 사용자 설명서 — AI 서비스 개발 프롬프트 메이커 (Claude Code 하네스)

> 이 문서는 `prompt-maker-harness`를 Claude Code에 설치하고 실제 서비스 기획부터 개발 완료·검증·발표자료까지 진행하는 방법을 설명한다.

---

## 1. 이게 뭔가

서비스를 기획할 때 AI에게 "알아서 잘 만들어줘"라고 맡기면 두 가지 문제가 생긴다. 규제·리스크 검토가 누락되거나, 대화가 길어지면서 초반에 정한 제약(법규, 금지 행위, 데이터 취급 규정)이 흐려진다.

이 하네스는 그 문제를 구조로 막는다. **판단이 필요한 검토를 설계 단계 하나에 모으고**, 거기서 나온 `SPEC.yaml`을 기준으로 개발 중에는 기계가 명세와 코드를 대조한다. 핵심 제약은 파일에 저장해 대화가 길어져도 사라지지 않는다. 마지막에 보고서·포트폴리오 초안·발표자료를 증거 기반으로 생성한다.

검증을 단계마다 반복하지 않는 이유는 단순하다. **같은 모델이 같은 컨텍스트에서 자기 산출물을 다시 보는 일에는 새 정보가 없다.** 비용만 단계 수에 비례해 늘어난다. 그래서 반복되는 것은 사람의 재검토가 아니라 게이트다.

---

## 2. 설치

### 2.1 채팅에서 한 마디 — `/harness-init` (권장)

**터미널에 아무것도 입력하지 않는다.** 새 세션을 그 프로젝트 폴더에서 열고(작업 디렉터리가 이미 지정된 상태) 채팅에서 이렇게만 요청한다.

```
/harness-init
```

이건 프로젝트 전용이 아니라 **개인 전역 커맨드**(`~/.claude/commands/harness-init.md`)라서, `.claude`가 아직 없는 새 프로젝트에서도 작동한다. 세션의 현재 작업 디렉터리를 그대로 설치 대상으로 쓰므로 경로를 알려줄 필요가 없다.

내부적으로 하는 일은 2.2와 같다. 처음 쓰는 컴퓨터라 `harness-init` 셸 명령이 없으면 AI가 설치를 제안하고 승인 후 진행한다.

### 2.2 터미널에서 한 줄 — `harness-init`

**새 프로젝트 루트로 이동해서 한 번만 실행한다. 경로를 손볼 필요가 없다.**

```bash
cd ~/dev/my-service     # 새 프로젝트 폴더로 이동 (없으면 mkdir 먼저)
harness-init
```

내부적으로 하는 일:

1. `~/.harness-src`에 하네스 원본이 있으면 `git pull`로 최신화하고, 없으면 GitHub private 저장소에서 clone한다
2. 현재 폴더(`$PWD`)로 복사한다. `MAINTENANCE.md`·`CHANGELOG.md`·하네스의 `.git`은 가져오지 않는다
3. **`PROJECT_STATE.md`·`PROJECT_LOG.md`·`SPEC.yaml`이 이미 있으면 건드리지 않는다.** 진행 중인 프로젝트에서 실수로 다시 실행해도 작업 데이터가 지워지지 않는다
4. `.gitignore`는 덮어쓰지 않고 없는 줄만 덧붙인다

GitHub 인증이 안 돼 있으면(`gh auth status`로 확인) clone 단계에서 실패한다. `gh auth login`으로 먼저 인증한다.

**명령을 아직 설치하지 않았다면** 아래를 한 번만 실행한다. private 저장소라 `curl`로 직접 받을 수 없으므로 `git clone`을 쓴다(`gh auth login` 상태면 별도 인증 없이 된다).

```bash
git clone https://github.com/Gwangdev/prompt-maker-harness.git ~/.harness-src
mkdir -p ~/.local/bin
cp ~/.harness-src/scripts/harness-init ~/.local/bin/harness-init
chmod +x ~/.local/bin/harness-init
# ~/.local/bin이 PATH에 없으면: echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

`~/.harness-src`에 미리 clone해두면 `harness-init`이 다음부터 이 폴더를 그대로 캐시로 재사용한다(다시 clone하지 않고 `git pull`만 한다).

### 2.3 수동 복사 (harness-init을 쓸 수 없을 때)

GitHub 접근이 안 되는 환경이거나 하네스 자체를 고치는 중이라 로컬 작업본을 바로 반영해야 할 때만 쓴다.

```bash
HARNESS=~/harness-src                # clone한 경로(또는 로컬 작업본 경로)
PROJECT=~/dev/my-service

rsync -a --exclude MAINTENANCE.md --exclude CHANGELOG.md \
         --exclude .gitignore --exclude .DS_Store --exclude .git \
  "$HARNESS/" "$PROJECT/"

# .gitignore는 덮어쓰지 않고 없는 줄만 덧붙인다
touch "$PROJECT/.gitignore"
while IFS= read -r line; do
  grep -qxF "$line" "$PROJECT/.gitignore" || echo "$line" >> "$PROJECT/.gitignore"
done < "$HARNESS/.gitignore"
```

복사 후 구조:

```
my-service/                 ← 프로젝트 루트
├── (기존 프로젝트 파일)
├── CLAUDE.md               불변 규칙 (매 턴 로드)
├── PROJECT_STATE.md        상태 (매 단계 로드, 100줄 이하)
├── PROJECT_LOG.md          누적 기록 (필요한 커맨드만)
├── SPEC.yaml               공개 표면 명세
├── README.md · USER_GUIDE.md
├── .claude/
│   ├── commands/           design · build · verify · handoff · compact
│   └── agents/
├── reference/
└── tools/                  gate.py · test_gate.py
```

**Finder로 끌어다 복사하지 않는다.** `.claude`와 `.gitignore`는 점으로 시작해 Finder에서 기본으로 숨겨지므로 빠뜨리기 쉽다.

이미 프로젝트에 `CLAUDE.md`가 있다면 내용을 이어 붙이되, 이 하네스의 "불변 규칙 카드"가 파일 상단에 오도록 배치한다.

### 2.4 설치 확인

프로젝트 루트에서 Claude Code를 실행하고 `/`를 입력한다. 다음 5개 커맨드가 보이면 성공이다.

```
/design    /build    /verify    /handoff    /compact
```

게이트도 함께 확인한다.

```bash
python3 tools/test_gate.py     # 모든 자기 테스트가 통과해야 한다
```

보이지 않으면 3장 "문제 해결"을 참고한다.

---

## 3. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| 슬래시 커맨드가 안 뜬다 | `.claude/`가 복사되지 않음 (Finder가 숨김 처리) | `ls -a`로 확인. 없으면 `rsync`로 다시 복사 |
| 커맨드가 안 뜬다 (복사 후에도) | 프로젝트 루트가 아닌 하위 폴더에서 Claude Code 실행 | 루트에서 다시 실행 |
| `/verify`가 에이전트를 못 찾는다 | `.claude/agents/independent-verifier.md`가 없거나 경로가 틀림 | 파일 위치 확인 |
| 커맨드 실행해도 규칙을 무시하는 것 같다 | `CLAUDE.md`가 프로젝트 루트에 없음 | 루트에 있는지, 다른 `CLAUDE.md`에 덮어써지지 않았는지 확인 |
| 이전 대화 내용을 기억 못 한다 | 정상 동작 | `PROJECT_STATE.md`가 상태를 담당하므로 컨텍스트 초기화는 문제 없음 |
| `/handoff publish`가 생성한 프롬프트를 실행해도 `public/`을 안 만든다 | `needs_review`·`[미검증]` 잔존 또는 민감정보 검출 | 프롬프트가 지정한 미충족 목록을 처리 후 재실행 |
| `/handoff report`가 생성한 프롬프트가 스타일을 무시한다 | `reference/report-style.md` 경로 확인 | 파일이 없으면 생성을 멈추고 올바른 경로를 지정 |
| 보고서에 슬라이드 스타일이 적용된다 | 스타일 파일을 잘못 지정 | `/handoff report`는 `report-style.md`, `/handoff ppt`는 `ppt-style.md` |
| Codex로 프롬프트를 실행했는데 스타일이 안 먹는다 | 프롬프트에 스타일 파일 경로가 없거나 Codex가 그 경로를 못 읽음 | 프롬프트 안의 "읽을 파일" 절에 경로가 있는지, 실행 환경에서 그 경로가 실제로 열리는지 확인 |

---

## 4. 사용 전 준비 — PROJECT_STATE.md 채우기

`/design`을 실행하기 전에 `PROJECT_STATE.md`의 아래 3개 항목을 채운다. 비어 있으면 1단계가 진행을 멈추고 질문한다.

- **적용 법령·인허가·감독규정** (예: 금융이면 자본시장법·신용정보법, 계약이면 변호사법, 전 도메인 개인정보보호법)
- **금지 자동화 행위** (예: 자동 매매·송금, 전자서명, 프로덕션 배포, 외부 전송)
- **데이터 등급** (공개 / 내부 / 기밀 / 개인정보 / 영업비밀)

직접 채우기 어렵다면 Claude에게 "PROJECT_STATE.md 채우게 질문해줘"라고 요청하면 인터뷰 형식으로 채워준다.

---

## 5. 사용 흐름

```
/design           → 사람이 검토 후 승인   ← 판단이 필요한 검토는 전부 여기
/compact
/build            → 반복 (검사는 첫 항목 1회) → 체크포인트에서 커밋 시나리오
  └ /debug        → 버그를 만났을 때만. 원인 규명 후 /build로 복귀
/insight          → 순서 밖. 파이프라인 없이도 단독으로 돈다 (read·add·promote)
/compact
/verify           → 완료 판정 확인
/handoff document → 검토본 확인 후 승인
[ 아래는 순서 무관, 필요한 것만. 전부 프롬프트만 생성한다 ]
/handoff report   → 프롬프트 → Claude 또는 Codex로 실행 → gate.py 검증
/handoff publish  → 프롬프트 → Claude 또는 Codex로 실행 → gate.py 검증
/handoff ppt      → 프롬프트 → Claude 또는 Codex로 실행
```

### 사용자가 실제로 하는 일

게이트 코드(`S4`·`L1`·`K1`…)는 **외울 필요 없다.** AI가 읽고 조치하며, 당신이 보는 것은 마지막 판정 한 줄이다.

| 시점 | 당신이 하는 것 |
|---|---|
| 시작 | `PROJECT_STATE.md`에 규제·금지행위·데이터등급 3줄 |
| `/design` 끝 | 산출물 읽고 **승인** |
| 체크포인트 | `gate.py . --commit` 한 번, 나온 커밋 블록 실행 |
| `/verify` 후 | 완료 판정 확인 |
| `/handoff` 후 | 프롬프트를 Claude나 Codex로 실행 |

나머지는 커맨드가 알아서 돈다.

**승인 지점은 `/design` 끝과 `/handoff document` 끝 두 곳이다.** 개발 중에는 승인을 묻지 않는다 — 판단할 것이 없기 때문이다. 명세와 코드가 어긋나면 사람이 아니라 게이트가 막는다.

**단, 커밋은 매번 사용자가 직접 실행한다.** 하네스는 커밋 명령을 제시만 하고 멈춘다(6장 참조).
`/handoff report`·`publish`·`ppt`는 프롬프트만 쓰고 멈춘다. 실행은 그때 Claude로 할지 Codex로 할지 정한다.

### 5.1 `/design` — 설계

이 하네스에서 **판단이 필요한 검토가 있는 유일한 단계**다. 나오는 것은 네 가지다.

1. **범위와 규제** — 문제 정의, 요구사항과 수용 기준, 포함·제외 범위, 적용 규제, 데이터 등급, 금지 행위. 규제·데이터 등급이 비어 있으면 여기서 멈춘다
2. **기술 선택** — 프레임워크가 제공하는 기능은 기본 채택한다. 직접 구현하려면 사유를 적는다
3. **`SPEC.yaml`** — 공개 표면 목록. 이 파일이 개발의 틀이다
4. **논리 검토** — 상태 전이가 닫혀 있는가, 요구사항과 명세가 1:1로 대응하는가, 형제 자원이 대칭인가, 오류 응답이 정합적인가, 권한 표면에 구멍이 없는가

**확인할 것:**
- 요구사항 하나하나가 `SPEC.yaml`의 어느 항목으로 충족되는지 대응이 보이는가
- **대응이 없는 엔드포인트가 있는가.** 있으면 지운다. 「있으면 좋을 것」이 나중에 과잉 구현으로 남는다
- 수용 기준이 그대로 테스트가 될 만큼 구체적인가

여기서 걸러내지 못한 것은 개발 단계에서 걸러지지 않는다. **시간을 여기에 쓴다.**

### 5.2 `/build` — 개발

`SPEC.yaml`의 항목 하나가 한 번의 반복이다.

```
첫 항목      테스트 작성 → 실패 확인 → 구현 → 통과 확인 → gate.py .   ← 관례 확정. 1회만
이후 항목    테스트 작성 → 실패 확인 → 구현 → 통과 확인               ← 검사하지 않는다
체크포인트   품질 판정 + 커밋 분할 + 시나리오
```

**테스트를 먼저 쓰는 이유:** 실패하는 것을 본 적 없는 테스트는 무엇을 검사하는지 알 수 없다. 구현을 먼저 하면 테스트가 수용 기준이 아니라 **구현을 베낀다** — 구현이 요구사항을 잘못 읽었어도 테스트는 그 잘못을 옮겨 적고 통과한다. 새로 쓴 테스트가 곧바로 통과하면 이미 구현됐거나 아무것도 검사하지 않는 것이므로, 어느 쪽인지 확인하기 전에는 넘어가지 않는다.

**검사를 첫 항목에서만 도는 이유:** 같은 검사를 반복해도 새 정보가 나오지 않는다. 다만 첫 항목에서 파일 배치·주석 형식·오류 처리 모양 같은 **관례가 정해지고 이후 항목이 그것을 복제**하므로, 거기서 한 번 확인해 잘못된 관례가 굳는 것을 막는다.

**체크포인트 위치는 사용자가 정한다.** 전체 개발 완료 시점이든, 일정상 끊기로 한 파트든. 절차는 **6장 「커밋 — 사용법」**에 있다.

| 코드 | 뜻 | 대응 |
|---|---|---|
| `T2` | 명세 항목에 그 경로를 쓰는 테스트가 없다 | 수용 기준을 테스트로 옮긴다. 경로를 상수로 조립했다면 미탐 |
| `S3` | 명세에 있는데 코드에 없다 | 개발 중이면 정상 |
| `S4` | 코드에 있는데 명세에 없다 | **과잉 구현.** 지우거나 `/design` §5 |
| `A1` | URI에 동사가 들어갔다 | `POST /create-order` → `POST /orders` |
| `A4` | 컬렉션 전체를 지우는 `PUT`·`DELETE` | 지우거나 명세 항목에 사유를 단다 |
| `L1`·`L2` | 라벨·내부 태그가 제출물에 잔존 | 제거 |
| `X1` | 코드·설정에 자격증명이 박혀 있다 | 환경변수로 옮기고 **해당 키를 폐기·재발급**. 지워도 git 이력에는 남는다 |
| `X2` | `semgrep`이 찾은 취약 패턴 | 고친다. WARN이면 도구가 없어 **미검사**인 상태다 |
| `X3` | 의존성의 알려진 취약점 | 올리거나 교체. 못 하면 사유를 문서에 남긴다 |
| `V1` | 기능 테스트 실행 결과 | 실패면 커밋 불가 |

**확인할 것:** 완료 보고가 아니라 `python3 tools/gate.py . --commit`의 실제 출력. `COMMIT READY`인지.

**내장 `/code-review`·`/security-review`는 어디에 두는가.** 없애지 않는다 — 보는 것이 다르다. `/verify`는 명세·증거·상태를 보고, 내장 커맨드는 diff의 코드 라인을 본다. 대신 **자리를 고정**해서 항목마다 반복되는 것을 막는다.

| 커맨드 | 자리 | 횟수 |
|---|---|---|
| `gate.py` | 첫 항목 · 체크포인트 | 제한 없음 (비용이 없다) |
| `/code-review` | 체크포인트, 커밋 직전 | 커밋 범위당 1회 |
| `/security-review` | **외부 표면이 추가·변경된 체크포인트만** | 해당 범위당 1회 |
| `/verify` | 개발 완료 후 (격리 컨텍스트) | 전체 1회 |

축 `X`가 통과했다는 것과 권한 설계가 옳다는 것은 다른 사실이다. 전자는 기계가, 후자는 `/security-review`가 본다.

### 5.2.1 `/debug` — 버그를 만났을 때

`/design`·`/build`·`/verify`는 **만드는** 절차다. `/debug`는 **이미 만든 것이 왜 그렇게 동작하는지 알아내는** 절차이고, 만드는 절차의 규칙을 그대로 쓰면 추측으로 코드를 읽게 된다. 디버깅에서 시간과 토큰이 가장 많이 새는 자리다.

`/build` 중 테스트가 실패하거나 동작이 예상과 다르면 자동으로 이 절차로 들어간다. 직접 부를 수도 있다.

**핵심 규칙 넷**

| 규칙 | 이유 |
|---|---|
| 재현을 먼저 고정한다 | 재현하지 못하면 고쳤다고 판단할 근거가 없다. 그 절차가 그대로 회귀 테스트가 된다 |
| 한 번에 하나만 바꾼다 | 두 곳을 함께 고치고 통과하면 무엇이 고친 것인지 모른다 |
| **3회 실패하면 멈추고 `/compact`** | 실패한 시도가 컨텍스트에 쌓이면 이후 판단이 끌려간다. 배제된 원인을 `PROJECT_LOG.md`로 내리고 다시 시작한다 |
| 증상만 없애지 않는다 | 재시도·타임아웃 늘리기·예외 삼키기는 버그를 숨기는 것이다. 우회할 수밖에 없으면 그것이 우회임을 주석에 남긴다 |

**고칠 때도 테스트가 먼저다.** 고친 뒤에 쓴 테스트는 고친 코드를 베끼므로, 그 버그가 다시 들어와도 잡지 못할 수 있다.

**설계를 바꿔야 한다는 결론이 나오면 `/design`으로 되돌아간다.** 디버깅 중에 명세를 늘리면 게이트 대조가 무의미해진다.

**확인할 것:** 원인을 한 문장으로 말할 수 있는지. 「고쳤다」만 있고 원인이 없으면 증상이 이동한 것이다.

### 5.2.2 `/insight` — 축적한 판단 꺼내 쓰기·모으기

순서 밖 커맨드다. `/design`·`/build`를 쓰지 않는 작은 프로젝트에서도 **단독으로 돈다.**
`PROJECT_STATE.md`나 `SPEC.yaml`이 없어도 되고, 없다고 만들지도 않는다.

| 입력 | 하는 일 |
|---|---|
| `/insight` | `reference/insights/`를 현재 코드에 대조한다. **결함과 후보를 나눠서** 보고한다 |
| `/insight add <내용>` | 이번 작업에서 나온 판단을 규칙 문장으로 기록한다 |
| `/insight promote` | 기록된 항목이 하네스 자산이 될 자격이 있는지 네 질문으로 판정한다 |

**결함과 후보는 다르게 다룬다.** 원칙 자산의 미적용은 결함이라 처리 상태(고침/사유/미결)가 붙고,
후보 자산의 미채택은 정상이라 고르지 않으면 사라져도 된다. 파이프라인을 쓰는 프로젝트에서는
같은 자산이 `/design`과 `/verify`에서 이미 로드되므로 여기서 다시 판정하지 않는다.

`add`로 모은 것은 그 프로젝트의 것이고, `promote`를 통과해 **하네스 저장소**에 반영해야
다음 프로젝트로 전달된다. 설치된 복사본의 `reference/`만 고치면 그 프로젝트에서 끝난다.

### 5.3 `/compact` — 상태 압축 (생략 금지)

`PROJECT_STATE.md`가 **100줄을 넘으면** 실행한다. 개발 착수 직전과 `/verify` 직전에는 줄수와 무관하게 실행한다.
규제·승인·현재 유효한 설계·미해결 라벨은 보존하고, 이력·증거·완료된 피드백은 `PROJECT_LOG.md`로 **내린다**(삭제가 아니다).

**바빠도 생략하지 않는다.** 상태 파일이 커진 채로 남으면 이후 모든 단계가 그 파일을 반복해서 읽는다. 비용은 남은 단계 수만큼 곱해진다.

### 5.4 `/verify` — 독립 검증

`independent-verifier` 서브에이전트가 별도 컨텍스트에서 개발 결과를 검증한다. 개발한 주체가 스스로 "완료했다"고 말하는 것을 그대로 믿지 않고, 실제 증거(로그·출력 파일)와 `reference/completion-criteria.md` 기준으로 판정한다.

**결과:** `완료 / 조건부 완료 / 배포 보류 / 검증 필요 / 사용자 결정 필요` 중 하나로 나온다. `완료`가 아니면 해당 단계로 돌아가 보완한다.

### 5.5 `/handoff document` — 프로젝트 기록 구조화

근거(`PROJECT_STATE.md`·`PROJECT_LOG.md`·코드·테스트·Git 기록·사용자가 넣은 대화 요약)에서 사실을 뽑아 `docs/portfolio/`에 `evidence.yaml`·`project.yaml`·`PROJECTS.md` 검토본을 만든다.

**이 유형만 산출물을 직접 만든다.** 증거 정리는 실행 주체를 가리지 않는 데이터 작업이기 때문이다.

**확인할 것:** `needs_review` 항목. 근거가 없어 판단을 보류한 부분이므로 사용자가 확인해야 다음으로 간다.

### 5.6 산출물 프롬프트 3종 (순서 무관)

`/handoff document` 승인 후 필요한 것만 실행한다. **셋 다 산출물을 만들지 않고 `prompts/`에 자립형 프롬프트만 쓴다.** Claude로 실행할지 Codex로 실행할지는 그때 정한다.

| 유형 | 출력 프롬프트가 지시하는 것 | 문체·판단 파일 | 시각 디자인 |
|---|---|---|---|
| `report` | 자동 선택한 프로필에 따른 보고서. 브리프와 경량 프롬프트를 함께 생성 | `reference/report-style.md` | `reference/report.css`(색·조판) |
| `publish` | `generated/internal/`(이력서·면접질문)과 `generated/public/`(README·Notion·블로그) 분리 생성 | — | — |
| `ppt` | 슬라이드 구성안 | `reference/ppt-style.md` | 동일 파일 |

기본값은 자동 선택이다. 필요하면 `/handoff report technical-project`, `/handoff report business-strategy`,
`/handoff report policy-research`, `/handoff report brief`로 프로필을 지정한다. 색·조판은
`/handoff report technical-project orange modern`처럼 `black`·`orange`·`blue`·`vermilion` ×
`classic`·`modern`·`formal` 인자로 고른다. 둘 다 없으면 임의로 고르지 않고 확인을 묻는다.
논문체가 필요하면 `/handoff report policy-research reference/examples/report-style-academic.md`
처럼 일곱 값(색 4·조판 3·프로필 자체)과 겹치지 않는 경로를 인자로 주면 문체 파일로 해석한다.
색·조판과 독립이라 함께 지정할 수 있다.

`formal`은 관공서 용역보고서 판면을 실측 이식한 축이다. 본문 `<section class="sheet">`마다
`g2`를 함께 붙이는 것이 표준이며, 이 경우 기본 판단 규칙과 셋이 충돌하므로(위계 4단계·불릿
중심·러닝 헤더 없음) 문체 파일을 반드시 함께 준다.

```
/handoff report technical-project reference/examples/report-style-formal.md formal vermilion
``` `publish`는 발행 기준 검증에 실패하면 `public/`을 만들지 말라는 지시를 프롬프트에 담는다.

**산출물이 돌아오면 검증은 한 곳에서 한다.**

```bash
python3 tools/gate.py <산출물 경로>
```

브리프를 만든 직후 `python3 tools/gate.py prompts`로 R0~R4를 검사하고, 완성본이 돌아오면
`python3 tools/gate.py report`로 D1~D6을 검사한다. PDF가 있으면 D7·D8·E1~E7이 Markdown·HTML·
PDF의 일관성과 `report.css` 준수를 함께 검사한다. 같은 항목을 두 단계에서 반복 검사하지 않는다.

`E7`(판면 좌표 실측)은 `pymupdf`가 있을 때만 돈다. 없으면 INFO로 건너뛴다고 알린다 —
하단 여백 침범은 렌더 PNG를 육안으로 넘겨봐도 안 보이는 결함이라 좌표로만 잡힌다.

```bash
pip install pymupdf
```

이미지가 있는 보고서는 **렌더하기 전에** 배치를 계산한다. 이미지를 열지 않고 판독성·쪽
넘침을 판정하므로 PNG를 눈으로 확인하는 루프가 없어진다.

```bash
python3 tools/image_plan.py <계획.json>
```

### 5.7 스타일 바꾸기 — 파일만 갈아끼운다

| 바꾸고 싶은 것 | 고칠 파일 |
|---|---|
| 슬라이드 디자인·톤 | `reference/ppt-style.md` |
| 보고서 문체·판단(평서형·헤지·한계 절 등) | `reference/report-style.md` |
| 보고서 시각 디자인(판형·글꼴·색·조판) | `reference/report.css` — 또는 `/handoff report`의 색·조판 인자 |
| 보고서 공통 판단·근거 규칙 | `reference/report-contract.md` |
| 보고서 유형별 구성 | `reference/report-profiles/` |

커맨드를 수정할 필요가 없다. `reference/examples/`에 예시가 있으면 복사해 덮어쓰면 된다.

```bash
cp reference/examples/ppt-style-nordic-simple.md reference/ppt-style.md
```

특정 경로를 일회성으로 쓰려면 인자로 넘긴다.

```
/handoff ppt reference/examples/ppt-style-nordic-simple.md
/handoff report technical-project reference/examples/report-style-academic.md
```

---

## 6. 커밋 — 사용법

### 6.1 왜 AI가 커밋하지 않는가

AI가 자동으로 커밋하면 단기간에 수십 개가 쌓인다. 그러면 팀 리더가 히스토리로 진행 상황을 읽을 수 없다.
팀 개발에서 커밋은 **작업 로그가 아니라 리뷰 단위**다. 그래서 이 하네스는 `git commit`·`git push`를 실행하지 않는다.

사람이 직접 하던 방식(작업하고 → 어디까지를 한 커밋으로 묶을지 정하고 → 메시지를 쓴다)에서
**"어디까지 묶을지"와 "메시지"를 AI가 제안하고, 실행 결정은 사람이 갖는다.**

### 6.2 언제 커밋하는가 — 체크포인트

개발 중에는 커밋하지 않는다. **체크포인트에서 한 번에 나눠 커밋한다.**

체크포인트 위치는 사용자가 정한다.

| 방식 | 언제 | 특징 |
|---|---|---|
| 전체 완료 후 | 모든 명세 항목 구현 후 | 기본값. 검사가 1회로 끝난다 |
| 파트 단위 | 일정상 끊기로 한 지점 | 결함을 일찍 발견. 검사 횟수만큼 비용 |

"이제 체크포인트야" 또는 "커밋할 준비 해줘"라고 말하면 된다.

### 6.3 실제 흐름

**1단계 — 품질 판정**

```bash
python3 tools/gate.py . --commit
```

```
▶ [S3] 2 endpoints in spec but not implemented — pending, normal during build
▶ [V1] tests passed: ./gradlew test
╰─ COMMIT READY — 0 blockers, 0 warning(s)
```

`COMMIT READY`면 다음 단계로, `NOT READY`면 `■` 항목을 해소하고 다시 돌린다.

- 여기서 **테스트가 실제로 실행된다.** `SPEC.yaml`에 `test_command: "./gradlew test"`를 적어둬야 한다
- `▶`로 표시된 `S3`(미구현 명세 항목)는 **차단이 아니다.** 아직 안 만든 기능이 남은 건 개발 중 정상이다

**2단계 — 변경을 기능별로 묶어 보기**

`COMMIT READY`면 위 명령이 **이어서 자동으로 출력한다.** 따로 칠 필요 없다.

```
│ ● GET /api/orders
│     ?? src/order/OrderListController.java
│ ○ 공통·기반 / 미분류 — 어느 기능에 속하는지 사람이 판단한다
│     ?? src/config/DataSourceConfig.java
```

`●`는 코드에서 **실제로 추출한 엔드포인트** 기준이라 추측이 아니다.
`○`는 엔드포인트를 선언하지 않는 파일(설정·공통 모듈·테스트)이다. 어느 커밋에 실을지는 사람이 정한다.

**3단계 — 커밋 시나리오를 받아 실행**

AI가 번호 붙은 블록으로 제시한다.

````
**2/3 — 주문 목록 조회 (GET /api/orders)**
```bash
git add src/order/OrderListController.java tests/order/OrderListTest.java
git commit -m "feat: 주문 목록 조회 API 추가

정렬 기준을 서버가 고정해, 호출부가 순서를 신뢰할 수 있게 했다."
```
````

**위에서부터 순서대로 실행한다.** 공통·기반이 먼저여야 중간 커밋이 깨지지 않고, 테스트는 대응하는 기능 커밋에 함께 실려야 그 사이 커밋이 테스트 없는 상태로 남지 않는다.

블록을 나눠 주는 이유는 중간에서 멈추거나, 메시지를 고치거나, 순서를 바꿀 수 있게 하기 위해서다.

### 6.4 자주 겪는 상황

| 상황 | 조치 |
|---|---|
| `NOT READY`가 뜬다 | 출력의 `■` 항목을 해소한다. `S4`는 명세에 없는 걸 만든 것, `L1`·`L2`는 내부 표기가 남은 것 |
| `S4`가 예제·픽스처 코드의 컨트롤러를 잡는다 | 그 코드는 공개 표면이 아니다. `SPEC.yaml`에 `code_roots`로 서비스 본체 경로를 적으면 그 밖은 대조 대상에서 빠진다. `exclude`에 넣지 않는다 — 그건 「우리 표면인데 관리하지 않는다」는 뜻이라 의미가 다르고, 픽스처가 늘 때마다 목록이 길어진다 |
| `S0` — `code_roots`에 없는 경로 | 오타이거나 아직 만들지 않은 디렉터리다. 이 검사가 없으면 스캔 대상이 비어 「미구현(`S3`)」으로 보고돼 원인을 못 찾는다 |
| `V1` WARN — `test_command` 없음 | `SPEC.yaml`에 테스트 명령을 적는다. 안 적으면 테스트 통과를 기계로 확인하지 못한 채 커밋하게 된다 |
| `X2`·`X3` WARN — 도구 없음 | `pipx install semgrep pip-audit`. **WARN은 통과가 아니라 미검사다** — 그대로 커밋하면 보안 축이 비어 있는 채로 나간다 |
| `X1` BLOCK — 키가 박혀 있다 | 코드에서 지우는 것으로 끝내지 않는다. **이미 커밋된 키는 폐기·재발급**해야 한다. git 이력은 코드 수정으로 지워지지 않는다 |
| `○` 미분류에 뭘 넣을지 모르겠다 | AI가 추측하지 않고 묻도록 되어 있다. 답해주면 시나리오에 반영된다 |
| 커밋을 나중에 하고 싶다 | 그냥 실행하지 않으면 된다. 변경은 작업 트리에 그대로 남는다 |
| 이미 커밋해버렸는데 나누고 싶다 | `git reset --soft HEAD~1`로 되돌린 뒤 다시 `--changeset`을 돌린다 |
| 커밋 메시지가 마음에 안 든다 | 블록의 메시지를 고쳐서 실행하면 된다. 제안일 뿐이다 |

### 6.5 커밋 메시지 형식

```
<타입>: <무엇을 했는가 — 한 줄>

<왜 이렇게 했는가. 판단이 갈렸던 지점이 있으면 그것>
```

타입은 저장소의 기존 관례를 따르고, 없으면 `feat`·`fix`·`refactor`·`test`·`docs`를 쓴다.

**"제거·정리·삭제"를 표방하는 메시지는 실제 삭제가 있을 때만 쓴다.** 게이트 `G4`가 커밋 메시지의 주장과 실제 diff를 대조해서, 삭제를 표방했는데 2줄 이하만 지운 커밋을 잡아낸다.

### 6.6 git 신원

커밋 author 이메일은 개인 이메일이 아니라 GitHub noreply 주소를 쓴다. 게이트 `P2`가 개인 이메일 노출을 경고한다.

```bash
git config --get user.email          # 현재 저장소에 적용되는 값 확인
```

전역 기본값은 이미 noreply로 설정되어 있다. 다만 **저장소에 로컬 설정이 따로 있으면 그쪽이 우선**하므로, 새 저장소에서 한 번 확인하는 편이 안전하다.

---

## 7. 파일별 역할 요약

| 파일 | 역할 | 사용자가 할 일 |
|---|---|---|
| `CLAUDE.md` | 매 턴 자동 로드되는 불변 규칙(우선순위·규제·금지행위·근거규칙) | 보통 수정 불필요. 조직 공통 규칙 추가 시만 수정 |
| `PROJECT_STATE.md` | 현재 상태(진실의 원천). 매 단계 읽으므로 **100줄 이하** | 최초 규제·데이터등급 입력, 이후는 AI가 갱신 |
| `PROJECT_LOG.md` | 피드백 대장·요구사항 이력·테스트 증거·포트폴리오 상태 | 수정 불필요. 길어져도 문제없다 |
| `SPEC.yaml` | 공개 표면 명세. `gate.py`가 코드와 집합 비교 | `/design`에서 작성, 개발 중에는 고정 |
| `reference/commit-protocol.md` | 체크포인트 절차 — 품질 판정·커밋 분할·시나리오 | 그대로 사용 |
| `reference/debug-protocol.md` | 진단 절차 — 재현 고정·가설과 반증·컨텍스트 정리 | 그대로 사용 |
| `reference/insights/` | 인사이트 자산 — 원칙과 채택 후보를 분리 보관. `/insight`로 단독 사용 가능 | 새 인사이트는 `/insight add`로 모으고 `promote`로 승격 판정 |
| `.claude/commands/*.md` | 단계별 슬래시 커맨드 | 그대로 사용 |
| `.claude/agents/*.md` | 독립 검증자·증거 추출자·문체 감사자 | 그대로 사용 |
| `reference/*-schema.yaml` · `portfolio-criteria.md` | 데이터 구조·발행 기준 | 그대로 사용 |
| `.claude/agents/independent-verifier.md` | 독립 검증 서브에이전트 (`/verify`) | 그대로 사용 |
| `reference/completion-criteria.md` | 완료 판정 기준 | 도메인에 맞게 항목 추가 가능 |
| `reference/ml-lstm-controls.md` | ML/LSTM 사용 서비스 전용 통제 | ML을 안 쓰면 무시해도 됨 |
| `reference/ppt-style.md` | **슬라이드 스타일(교체용)** | 원하는 스타일로 내용 교체 |
| `reference/report-style.md` | **보고서 문체·판단(교체용)** | 기본 의사결정 중심 실무체. 논문체는 `examples/report-style-academic.md`, 관공서 조판은 `examples/report-style-formal.md` |
| `reference/report.css` | **보고서 시각 디자인 — 판형·글꼴·색·조판 값의 단일 원본** | `black`·`orange`·`blue` × `classic`·`modern`은 인자로 선택 |
| `reference/report-contract.md` | 보고서 공통 판단·근거·검증 계약 | 그대로 사용 |
| `reference/report-profiles/` | 보고서 유형별 구성 | 선택된 프로필 하나만 자동 로드 |
| `reference/stack-spring.md` | Spring Boot 실행형 보고서의 조사·실행·캡처 절차 | 해당 스택일 때만 자동 로드 |
| `reference/stack-db-tool.md` | DB 클라이언트 스크린샷 크롭 절차 | 해당 스택일 때만 자동 로드 |
| `reference/ai-tell-checklist.md` | AI 문체 흔적 제거 기준 | 거슬리는 표현을 발견하면 추가 |
| `reference/publishing-rules.md` | 발행 규칙·민감정보 스캔 패턴 | 사내 도메인 등 패턴 추가 |

---

## 8. 자주 묻는 질문

**Q. 중간에 새 대화(세션)를 열어도 되나?**
된다. `PROJECT_STATE.md`에 상태가 저장되어 있으므로 새 세션에서 `/design`처럼 이어질 단계를 실행하면 파일을 읽어 이어간다.

**Q. 승인 없이 AI가 다음 단계로 넘어갔다.**
설계상 각 커맨드 끝에 "승인 요청" 후 멈추도록 되어 있다. 넘어갔다면 결과를 되돌리고 재확인을 요구한다. 이는 지시일 뿐 기술적으로 강제되는 락(lock)은 아니므로, 사용자가 승인 여부를 실제로 검토하는 것이 중요하다.

**Q. AI로 개발한 걸 포트폴리오에 밝혀야 하나?**
하네스는 밝히는 쪽을 기본으로 한다. `project.yaml`의 `ai_usage`에 생성 범위·사람의 판단·검증 방법을 기록하고, README와 블로그에 명시한다. 숨기는 것보다 검증 과정을 보여주는 편이 신뢰를 얻는다. `used`가 비어 있으면 발행이 보류된다.

**Q. 보고서는 Claude가 쓰고 PPT는 Codex가 만들어도 되나?**
된다. `/handoff`는 실행 주체를 지정하지 않는다. 유형마다 다른 도구를 써도 되고, 같은 프로젝트 안에서 섞어도 된다. 스타일 파일 경로가 프롬프트에 있으면 어느 쪽이 실행하든 같은 스타일이 적용된다.

**Q. Codex로 프롬프트를 실행했는데 결과를 하네스가 어떻게 아나?**
모른다. 자동으로 알지 못한다. 산출물을 프로젝트 폴더에 넣고 `python3 tools/gate.py <경로>`를 사용자가 직접 실행해 검증한다. `PROJECT_LOG.md`의 포트폴리오 자동화 상태도 사용자가 갱신한다.

**Q. 보고서가 여전히 AI가 쓴 것 같다.**
`reference/ai-tell-checklist.md`에 거슬리는 표현을 직접 추가한다. 이 파일이 `prose-auditor`의 감사 기준이므로 추가하면 다음 실행부터 반영된다. 다만 문체를 아무리 다듬어도 증거가 빈약하면 내용이 공허해 보인다. 그 경우는 문체 문제가 아니라 `evidence.yaml`의 근거 부족이다.

**Q. `/handoff report`를 다시 돌리면 수정한 내용이 날아가나?**
`/handoff report` 자체는 프롬프트만 새로 쓰므로 기존 산출물에 영향이 없다. 그 프롬프트를 실행해 보고서를 다시 만들 때는 자동 생성 구간(`<!-- AUTO-GENERATED -->`)만 갱신하고 `<!-- manual -->` 구간과 백업 파일(`*.bak.md`)은 유지하라는 지시가 프롬프트에 담긴다.

**Q. 여러 서비스를 동시에 진행할 수 있나?**
`PROJECT_STATE.md`는 프로젝트 1개당 1개다. 서비스별로 별도 폴더(별도 프로젝트 루트)를 두고 이 하네스를 각각 복사해 사용한다.
복사 대상 목록은 하네스 폴더의 `MAINTENANCE.md` §4에 있다(`MAINTENANCE.md`·`CHANGELOG.md`는 복사하지 않는다).

---

## 9. 한계

이 하네스는 Claude Code처럼 파일 읽기/쓰기와 서브에이전트 실행이 가능한 환경을 전제로 한다. 승인 게이트는 AI에게 내리는 지시이지 시스템이 강제하는 잠금장치가 아니므로, 실제 효과는 사용자가 각 단계 산출물을 검토하고 승인 여부를 판단하는 데 달려 있다.

---
