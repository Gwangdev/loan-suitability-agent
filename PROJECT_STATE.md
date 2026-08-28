# Project State (source of truth — re-read every step)

> Every command reads this on start. On conflict with context memory, this file wins.
> **Keep it at 100 lines or fewer.** If exceeded, run `/compact`.
> Operational file — English. Korean stays in `PROJECT_LOG.md` and user-facing output.

- **Version:** v4
- **Updated:** 2026-08-26
- **Harness version:** v9.17
- **Goal:** Rebuild Loan into **Loan Decision Support — a verifiable loan-consultation decision-support platform**, the single flagship portfolio piece for the 2026 Hanwha Finance Platform-IT application. Submit by 2026-09-18; everything but the SQLD result done by 2026-09-10.
- **Current step:** `/build` item 1 done (`GET /health/live` — conventions fixed, gate S4/L2/C3 all 0). Design closeout in progress: data model + ERD + state diagram done, ADR-020…022 added. Remaining design item: architecture diagram (deferred until code settles).

## Spine (never dilute — user-confirmed)

> Rather than trying to improve an untrustworthy technology, **narrow where it is applied** so the result is guaranteed, and **compose it with a trustworthy technology** that covers what was taken away.

Subtraction and addition are a pair: whenever a doc says "the LLM was not given X", the same sentence says "Y took that role". Full table, the four portfolio axes, and the 3-step narration rule: `PROJECT_LOG.md`.

## Invariants (cell state — never delete arbitrarily)

- **Applicable regulations.** Educational demo, deliberately scoped **outside** every trigger below. **Nothing here is claimed as "complied with"** — recording the conditions is the deliverable. Full 3-step table: `docs/리스크_통제_대장.md`.
  - Binding approve/decline → PIPA Art. 37-2, automated-decision refusal & explanation rights. **This is the load-bearing one**: a loan decision is the textbook case, so "we do not auto-approve" is both a product-scope choice and the avoidance of the condition.
  - Recommending/brokering a loan product → Financial Consumer Protection Act (suitability, duty to explain)
  - Real personal credit data → PIPA Arts. 15/16/21/30 + Credit Information Act
  - Offshore transfer to an LLM provider → PIPA cross-border transfer provisions
  - Audit response → Electronic Financial Supervision Regulation, where the service qualifies as an electronic financial business

- **Forbidden automated actions.** ①binding approve/decline ②accepting or storing real personal/credit data ③persisting or logging raw free text or full prompts ④letting LLM output alter verdict, recommendation, or DSR ⑤emitting any figure not obtained through a tool from the CSV ⑥publishing guidance lacking the disclaimer or failing Eval ⑦storing/logging an API key or writing it to the global env ⑧connecting to a real financial-institution product API ⑨external transmission, production or permission changes without approval.

- **Data classification.** Public = synthetic product CSV, rules, verdict logic, fixtures (label as synthetic on screen). **Not collected** = real names, RRN, account numbers, contacts. **Not persisted** = raw natural-language input, full prompts. Operational secret = OpenAI keys, session memory only, passed as an argument, never `os.environ`, never logged. Non-sensitive metadata = audit events, correlation IDs, latency, token counts, error codes — must contain no raw input.

- **Compliance status.** Demo scope confirmed outside the triggers. Article numbers appear only where confirmed. No legal review obtained and none claimed.

## Approvals

| Approval point | Status | Time |
|---|---|---|
| Portfolio composition (Loan flagship, SKALA supporting) | approved | 2026-08-26 |
| Spine + four portfolio axes | approved | 2026-08-26 |
| T1 backend gap list (11 items) | approved | 2026-08-26 |
| Invariants (regulations / forbidden / data) | approved | 2026-08-26 |
| **Scope & regulations fixed (design approval)** | **approved** | 2026-08-26 |
| **Build start** | **approved** | 2026-08-26 |
| Record & publication (handoff approval) | pending | |

## Completion Verdict

- **Verdict:** none · **Basis:** verification section in `PROJECT_LOG.md`

## Active Design Decisions

Full text with rejected alternatives: **`docs/설계결정.md` (ADR-001…022)**. Reversing any of these means deleting it here and moving it to `PROJECT_LOG.md` **with the scope of specs it invalidates**.

- **ADR-001** FastAPI modular monolith; Spring rewrite rejected. Its only drawback ("no Java/Spring evidence") is void because SKALA Code Review Lab covers that axis as a supporting artifact. Reverse only for independent deployment, process-boundary fault isolation, diverging scale/security needs, or real load — **never to show more technology**.
- **ADR-004 / ADR-019** Double enforcement: app-level check **plus** a DB constraint. Different bypass paths, so it is not duplication.
- **ADR-009** No auth surface. A demo has no second user to impersonate; faking auth would protect nothing while looking protective. **Guessability is not access control.**
- **ADR-011** 3-tier as container/network boundaries; `postgres` internal-only, no host port. **No CORS config because the structure makes it unnecessary** (Streamlit is server-side rendered).
- **ADR-012** API uses English enums (`ELIGIBLE`/`CONDITIONAL`/`INELIGIBLE`), screen uses Korean. `RECEIVED`/`REJECTED_INPUT` deleted as dead states.
- **ADR-018 / ADR-022** LLM retry uses the SDK's built-in (max_retries 2), never a hand-rolled loop. Resource caps: pool 5+5, timeouts nest outward (UI 15s > app 10s > DB 5s), explanation-run cap 200s.
- **ADR-020** Local sLLM is added as a comparison axis, not a replacement — the spine makes a testable prediction (swap the model, the verdict must not move) and the comparison is what turns that claim into evidence.
- **Data model is frozen:** `docs/데이터모델.md` (ERD, state diagram, constraints, two-stage index migration). It supersedes 세부기술서 §8.
- **`G3`** bulk voice-normalization is cleared by rewriting the docs in stage 5, **never by silencing the gate axis**.
- **P0 split into P0-a (never cut) / P0-b (cut to a stated floor).** Cut order when stop criteria fire: 14 → 13 → 12 → 11 → 10. **If P0-a is at risk, cut the submission scope, not the P0-a items.** Table in `PROJECT_LOG.md`.
- The v8 harness copy is deleted; v9.17 at the repo root is the only harness.

## Open Labels (blocks completion)

- (none). The three pending article numbers were resolved 2026-08-26 by dropping the numbers and keeping the law name and intent, per the policy the risk register itself states. Only PIPA Art. 37-2 keeps a number — it is the one the whole register hangs on.

## Open Feedback (numbers → ledger in `PROJECT_LOG.md`)

- **#3** `G3` voice-normalization — clears in the stage-5 doc rewrite
- **#4** `I3` static `/health` — clears when `/health/live`+`/health/ready` land
- **#5** `D2` README has no limitations section — clears in the doc rewrite
- **#6** `P2` commit author email in the 28 pre-rebuild commits — **decided: leave it.** Config already uses the noreply address, so new commits are clean
- **#8** `C1` why-comments at 33% vs 40% — re-measure after the rebuild

## Next Action

- `/build` item 2 — `GET /health/ready` + the persistence layer (SQLAlchemy, Alembic, models per `docs/데이터모델.md`). The first-item gate already ran; next gate is at the checkpoint.
- Track B (compose hardening, CI postgres, Eval expansion) is handed to Codex via `prompts/codex-track-b.md`. File ownership is fixed in `PROJECT_LOG.md`; Track A never edits Track B's files.
- Gate state: `S0` 0, **`S4` 0** (old surface fully removed). `S3` 8 is the intended spec-vs-code gap that drives the build. `X1` is a false positive (ledger #2).

## Halt Reason

- **Halted:** no
