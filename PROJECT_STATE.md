# Project State (source of truth — re-read every step)

> Every command reads this on start. On conflict with context memory, this file wins.
> **Keep it at 100 lines or fewer.** If exceeded, run `/compact`.
> Operational file — English. Korean stays in `PROJECT_LOG.md` and user-facing output.

- **Version:** v15 (2026-08-29 · Codex build reviewed · **session handoff — read `docs/긴급/세션인계.md` FIRST**)
- **Updated:** 2026-08-29 · **Harness:** v9.19
- **Goal:** **Loan Decision Support — a verifiable loan-consultation decision-support platform**, the single flagship portfolio piece for the 2026 Hanwha Finance **Platform-IT** application. Deadline 2026-09-18 15:00 (H-FIT 09-20); all but the SQLD result done by 09-10.
- **Current step:** Codex executed the approved design; **the work sits UNCOMMITTED in the working tree (15 modified + 1 new migration).** First pass: every item implemented, invariants hold. Second pass found 4 defects; **#33–#36 all closed 2026-08-29.** The 3-Agent pipeline and the notebook are gone. 17 defects open (#40–#46 fixed same-session, uncommitted).

## Spine (never dilute — user-confirmed)

> Rather than trying to improve an untrustworthy technology, **narrow where it is applied** so the result is guaranteed, and **compose it with a trustworthy technology** that covers what was taken away.

Subtraction and addition are a pair. Full table, four portfolio axes, 3-step narration rule: `PROJECT_LOG.md`.

## Invariants (cell state — never delete arbitrarily)

- **Applicable regulations.** Educational demo, deliberately scoped **outside** every trigger. **Nothing is claimed as "complied with"** — recording the conditions is the deliverable. 3-step tables: `docs/리스크_통제_대장.md`.
  - Binding approve/decline → **PIPA Art. 37-2** (automated decision). **The load-bearing one.**
  - Recommending/brokering a product → Financial Consumer Protection Act **Arts. 17, 19**
  - Real personal credit data → **PIPA Arts. 15/16/21/30** + Credit Information Act
  - Offshore transfer to an LLM provider → PIPA cross-border transfer provisions
  - **Electronic Financial Transactions Act Arts. 2(1), 21** (ledger A7). The Supervision Regulation is a delegated notice *under Art. 21*, so citing it without the statute was a structural gap. **Three of four definitional elements fail here, and the third — "used automatically without communicating with staff" — fails for the same reason 37-2 does: a human decides. One boundary, two statutes.**
- **Forbidden automated actions.** ①binding approve/decline ②accepting or storing real personal/credit data ③persisting or logging raw free text or full prompts ④letting LLM output alter verdict, recommendation, or DSR ⑤emitting any figure not obtained from the CSV ⑥publishing guidance lacking the disclaimer or failing Eval ⑦storing/logging an API key or writing it to the global env ⑧connecting to a real financial-institution product API ⑨external transmission, production or permission changes without approval.
- **Data classification.** Public = synthetic CSV, rules, verdict logic, fixtures (labelled synthetic on screen). **Not collected** = real names, RRN, account numbers, contacts. **Not persisted** = raw free text, full prompts. Operational secret = OpenAI keys — session memory only, passed as an argument, never `os.environ`, never logged, **and never over plaintext HTTP (ADR-031 §31.5)**. Non-sensitive metadata = audit events, correlation IDs, latency, tokens, error codes.
- **Reference standards (ADR-033).** IEEE 754's limits acknowledged and measured (ADR-032). `ISO/IEC/IEEE 29148`/`42010`, the Supervision Regulation and ISMS-P are used for their **intent**. **"IEEE compliance" is never claimed** — 830/1471/829 were superseded.

## Approvals

| Approval point | Status | Time |
|---|---|---|
| Portfolio composition · Spine + four axes · T1 gap list · Invariants | approved | 2026-08-26 |
| **Scope & regulations fixed (design)** · **Build start** | **approved** | 2026-08-26 |
| **Design re-run — ADR-029/030 (안 B) · ADR-031 (AWS+TLS) · ADR-024 §24-R** | **approved (all three)** | 2026-08-29 |
| Record & publication (handoff) | pending | |

## Completion Verdict

**배포 보류** (2026-08-28, unchanged). Grounds: (1) gate BLOCK 1 (`G3`, unclearable), (2) README / CI / container each contradict the implementation, (3) the remaining defects carry no 조치. Basis: `PROJECT_LOG.md` 검증 결과.

## Active Design Decisions

Full text with rejected alternatives: **`docs/설계결정.md` (ADR-001…033)**. Reversing any means deleting it here and moving it to `PROJECT_LOG.md` **with the scope it invalidates**.

- **ADR-001** FastAPI modular monolith. Reverse only for independent deployment, process-boundary fault isolation, diverging scale/security needs, or real load — **never to show more technology.** Also the answer to "the target org runs EKS, why a monolith?"
- **ADR-004 / 019** App-level check **plus** DB constraint. Different bypass paths, so not duplication.
- **ADR-009** No auth surface. **Guessability is not access control**, but a demo has no second user to impersonate.
- **ADR-011** 3-tier as container/network boundaries; `postgres` internal-only. No CORS config because the structure removes the need.
- **ADR-012** English enums in the API, Korean on screen. Run status and case status are **separate vocabularies**.
- **ADR-018 / 022** SDK-built-in LLM retry. Timeouts nest outward (UI 15s > app 10s > DB 5s); explanation-run cap 200s. **Never introduce a second number for the same thing.**
- **ADR-020** Local sLLM is a comparison axis, not a replacement. **P1 — prepare the interview answer even if unimplemented**; the target org plans its own Llama-based model.
- **ADR-023** Worker claims with `FOR UPDATE SKIP LOCKED`, not a queue. **Claim and execute are separate** — mark RUNNING and commit before the LLM call. Never add a scheduler or leader election.
- **ADR-024 §24-R** **Whoever holds the key executes.** Server key → worker, async. Visitor key → **`app`, synchronous, on the existing R6 POST** (innermost place a key reaches; storing it is forbidden ⑦). Both paths claim the **same** `explanation_run` row, so the audit trail does not fork. Sync path **claims an existing PENDING row** (a 409 there would fire on every visitor) **and reclaims RUNNING past 200s** — no worker in prod, so nothing else would. Cap overrun exits **503**; no new 504.
- **ADR-029** `parsing-preview` runs **two independent parsers; their disagreement is the check.** Code never reconciles them — a human picks. Degrades to the rule parser alone without a key. The one remaining boundary where a deterministic check fits.
- **ADR-030** Explanation is **one LLM call**; decision/DSR/product detail injected as data. Removes 4 tool round trips (30s problem) and **tightens** the guarantee. ADR-025 is its precondition. **Streaming deliberately not decided — measure first.**
- **ADR-031** **AWS EC2 single instance + the existing compose.** EKS rejected. Prod carries **no server key and no worker**. **TLS is mandatory** — without it the visitor-key feature stays off. Stop: no deploy by 09-06 → video demo becomes primary evidence, README badge comes down.
- **ADR-032** Money stays `float`, **measured** at the DSR band boundary. **Valid only while** inputs are integer won, there is no accumulation, and thresholds are 2-decimal. Any of those breaking reopens it.
- **ADR-033** Reference-standard scope fixed. **IEEE compliance is never claimed.**
- **Data model frozen:** `docs/데이터모델.md`. **Never merge the two index migrations.**
- **`G3` can never be cleared.** Recorded, not clearable. **Never silence the axis.**

## Open Labels (blocks completion)

**17 open (#13–#37 minus closed). Codex fixed #14·#15·#18·#21·#26·#29 + ADR-024/029/030 — all UNCOMMITTED, so no hashes yet. **#33–#36 closed. #37 (7 fixture comments) waits on the owner-key fixture regeneration.**

## Open Feedback (ledger in `PROJECT_LOG.md`)

- **#3** `G3` · **#6** `P2` author email (leave it) · **#8** `C1` 35% vs 40% — observations, not blockers
- **Routing:** `/build` #13·#14·#15·#21·#26·#29 · `/debug`-first #18·#19·#25 · **closed by design** #16·#17·#20·#22·#23·#24·#27·#28·#30·#31
- **#32 closed 2026-08-29** — 12 harness tags removed at the source (`~/.harness-src`, self-test 91/91) and copied back; harness **v9.18**. `L2` missing them was not a bug: `is_deliverable()` exempts harness files and `b_leak_harness_ok` tests that. **The exemption is correct and stays** — it covers a different axis (do not BLOCK) than this fix (do not publish). **`gate.py:1049` is the detection regex, never remove it**
- **#29** `db/models.py:107` `Mapped[float]` vs `Numeric(asdecimal=True)` — write float, read Decimal, no precision/scale. **Needs a round-trip integration test, not just a type fix**

## Next Action

0. **Refactor done (#38·#39)** — CSS→`static/apple.css`, LLM path→`loan_agent/llm.py` (**core.py has zero LLM references**), key header→`api/contract.py`. Pure relocation. Further core.py split deferred: 15 files, 90 sites, and 355 lines reads fine.
1. **`#33`·`#34` closed 2026-08-29** — notebook deleted, all 3-Agent code removed (`core.py` −255, `app.py` −56). Two call-guard tests became a **structural absence assertion**, which is the stronger guarantee.
2. **Reviews done.** Both slots used for this commit range; #40–#46 fixed. — this commit range's slot. **`/security-review` also applies**: the visitor key is a new external input path.
3. **Then commit** (no trailer, split by feature).
4. **AWS deploy** — ADR-031. **TLS gates the visitor-key feature.**
5. **README last** (#13) — it can only state facts once 1–4 land.

**Blocked on the user (owner key required):** `demo_fixtures.json` is still 3-Agent-shaped output. Regenerating it also flips the 7 remaining "3-Agent" comments (#37) — same commit.

**Missing measurement:** ADR-030 per-stage timing was never reported and the instrument died with #33. Measure total single-call latency instead.

**Compose verified for the first time 2026-08-29** — 4/4 healthy, `/health/ready` ok, assessment + parsing-preview answer. It had never been started before; two blockers (#47 alpine uid 70≠999, #48 no migration step in image or compose) had to be fixed first.

**Reviews done.** `/code-review` 7 findings (#40–#46, all fixed — incl. a worker crash on provider timeout and the root cause of #19). `/security-review`: nothing reportable; the visitor-key path never stores, logs, env-writes, or echoes the key.

**Next Codex handoff must fix one prompt defect:** "do not edit `endpoints:`" was read literally, so header/shape/status-code contracts never reached `SPEC.yaml` (#35). Write it as "`endpoints:` is frozen; update every other contract comment."

## Halt Reason

**Halted: no.** Session handoff only. **`docs/긴급/세션인계.md` is the cold-start entry point**; `미결이슈.md` beside it is superseded and kept as history.

## Machine State (2026-08-29)

`pytest 99 passed` (was 89) · `test_gate 91/91` · `gate BLOCK 1 (G3) · WARN 9` · `S0` clean · `S3`·`S4` 0 · **`S2` 8 → 9 (that is #33)** · env `pytest` / `python3.11`
