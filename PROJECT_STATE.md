# Project State (source of truth — re-read every step)

> Every command reads this on start. On conflict with context memory, this file wins.
> **Keep it at 100 lines or fewer.** If exceeded, run `/compact`.
> Operational file — English. Korean stays in `PROJECT_LOG.md` and user-facing output.

- **Version:** v27 (2026-09-12 · re-run findings #94–#98 fixed; v26 recorded the re-run; v25 fixed the first run's defects; v23 compacted from v22 on 09-11 · plan stages 1–4 done, stage 5 next · **SQLD failed (56) — the portfolio is the sole credential**)
- **Updated:** 2026-09-12 · **Harness:** v9.19, with `tools/gate.py`·`tools/test_gate.py`·`reference/commit-protocol.md` synced from v9.21 (origin files edited, origin not committed — #81)
- **Goal:** **Loan Decision Support — a verifiable loan-consultation decision-support platform**, the single flagship portfolio piece for the 2026 Hanwha Finance **Platform-IT** application. Deadline 2026-09-18 15:00 (H-FIT 09-20). **SQLD came back 56 (fail) on 2026-09-04, so that credential is gone and this project carries the application alone** — quality bar rises accordingly.
- **Current step:** **Deployed — https://loan.gwang.dev is live**; Caddy (TLS) is the only entrypoint and `gwang.dev` serves the static portfolio independent of the app containers. **PIPELINE STAGE: `/build`.** Plan stages 1–4 were deployed and verified by 09-04 (narrative moved to `PROJECT_LOG.md` 압축 v22→v23). **2026-09-12: `a24d4e6` deployed, then `9a2ff53` (landing page live on gwang.dev; public test count 153) and `e265094` (four Streamlit fixes; `ui` rebuilt only, no worker) pushed and deployed** — both checked with curl and Playwright desktop/mobile.

## Spine (never dilute — user-confirmed)

> Rather than trying to improve an untrustworthy technology, **narrow where it is applied** so the result is guaranteed, and **compose it with a trustworthy technology** that covers what was taken away.

Subtraction and addition are a pair. Full table, four portfolio axes, 3-step narration rule: `PROJECT_LOG.md`.

## Invariants (cell state — never delete arbitrarily)

- **Applicable regulations.** Educational demo, deliberately scoped **outside** every trigger. **Nothing is claimed as "complied with"** — recording the conditions is the deliverable. 3-step tables: `docs/리스크_통제_대장.md`.
  - Binding approve/decline → **PIPA Art. 37-2** (automated decision). **The load-bearing one.**
  - Recommending/brokering a product → Financial Consumer Protection Act **Arts. 17, 19**
  - Real personal credit data → **PIPA Arts. 15/16/21/30** + Credit Information Act
  - Offshore transfer to an LLM provider → PIPA cross-border transfer provisions
  - **Electronic Financial Transactions Act Arts. 2(1), 21** (ledger A7). The Supervision Regulation is a delegated notice *under Art. 21*, so citing it without the statute was a structural gap. **Of its definitional elements only "via electronic means" holds; operator, financial product/service, and "used automatically without communicating with staff" all fail — the last for the same reason 37-2 does: a human decides. One boundary, two statutes.**
- **Forbidden automated actions.** ①binding approve/decline ②accepting or storing real personal/credit data ③persisting or logging raw free text or full prompts ④letting LLM output alter verdict, recommendation, or DSR ⑤emitting any figure not obtained from the CSV ⑥publishing guidance lacking the disclaimer or failing Eval ⑦storing/logging an API key or writing it to the global env ⑧connecting to a real financial-institution product API ⑨external transmission, production or permission changes without approval.
- **Data classification.** Public = synthetic CSV, rules, verdict logic, fixtures (labelled synthetic on screen). **Not collected** = real names, RRN, account numbers, contacts. **Not persisted** = raw free text, full prompts. Operational secret = OpenAI keys — session memory only, passed as an argument, never `os.environ`, never logged, **and never over plaintext HTTP (ADR-031 §31.5)**. Non-sensitive metadata = audit events, correlation IDs, latency, tokens, error codes.
- **Reference standards (ADR-033).** IEEE 754's limits acknowledged and measured (ADR-032). `ISO/IEC/IEEE 29148`/`42010`, the Supervision Regulation and ISMS-P are used for their **intent**. **"IEEE compliance" is never claimed** — 830/1471/829 were superseded.

## Approvals

| Approval point | Status | Time |
|---|---|---|
| Portfolio composition · Spine + four axes · T1 gap list · Invariants | approved | 2026-08-26 |
| **Scope & regulations fixed (design)** · **Build start** | **approved** | 2026-08-26 |
| **Design re-run — ADR-029/030 (안 B) · ADR-031 (AWS+TLS) · ADR-024 §24-R** | **approved (all three)** | 2026-08-29 |
| **`/design` §5 — portfolio host `gwang.dev` as a non-HTTP surface (scope expansion)** | **approved** | 2026-09-03 |
| **Landing publication (`gwang.dev`) · Streamlit four fixes · both production deploys** | **approved (user, in chat)** | 2026-09-12 |
| Record & publication (handoff) | pending | |

## Completion Verdict

**조건부 완료** (re-run 2026-09-12, `independent-verifier`, HEAD `f55b75e`; kept). No user-facing defect in the public deploy. Not 「완료」: the gate exits 1 on `G3` (the user's permanent exception still counts as a BLOCK for the verifier), open defects remain, and #94–#97 were raised. First-run defects: #85·#88·#91 resolved, #84 resolved in code, #86·#87 partial. **Its findings #94–#98 are fixed since; the verdict stands until `/verify` re-runs.** Basis: `PROJECT_LOG.md` 검증 결과.

## Active Design Decisions

Full text with rejected alternatives: **`docs/설계결정.md` (ADR-001…034)**. Reversing any means deleting it here and moving it to `PROJECT_LOG.md` **with the scope it invalidates**.

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
- **ADR-031** **AWS EC2 single instance + the existing compose.** EKS rejected. Prod carries **no server key and no worker**. **TLS is mandatory** — without it the visitor-key feature stays off. Stop: no deploy by 09-06 → video demo becomes primary evidence, README badge comes down. **Amended 2026-09-01:** the instance now serves **two** hosts — `loan.gwang.dev` proxies the app, `gwang.dev` root serves the static portfolio **directly from Caddy**, so app failure cannot take the submission link down. Caddy stays the sole entrypoint.
- **ADR-032** Money stays `float`, **measured** at the DSR band boundary. **Valid only while** inputs are integer won, there is no accumulation, and thresholds are 2-decimal. Any of those breaking reopens it.
- **ADR-033** Reference-standard scope fixed. **IEEE compliance is never claimed.**
- **ADR-034** **An unread amount is absent, not zero.** The rule parser returns `None` for a 부채 it could not read, and 부채 joins the required set with a predicate of its own — absence is missing, `0` is not. 부채 is the only field where `0` is a valid answer, so filling an unread one with `0` turned a parse failure into "no debt" and flipped a verdict toward approval. The other required fields keep 0/99 because those values are impossible for them by domain. **Hangul-numeral support is a separate matter** — it would shrink the cases, not remove the cause. **No new endpoint; response shape unchanged.**
- **Data model frozen:** `docs/데이터모델.md`. **Never merge the two index migrations.**
- **`G3` is a permanent exception (user decision 2026-09-12).** It scans past commit titles, so no commit can clear it; it no longer blocks completion or publication. **Never silence the axis** — it keeps printing.

## Open Labels (blocks completion)

Ledger runs to **#99**, recounted 2026-09-12. **Open defects:** #18 · #25 (worker, `/debug` first) · #38 partial (`core.py` split) · #55 (progress indicator — before the video) · #70 partial (worker correlation ID — `/design`, data model frozen) · #78 (`parsing-preview` LLM failure → unhandled 500). **Accepted limit:** #66. **Observations:** #3 `G3` (permanent exception) · #6 `P2` · #7 · #8 `C1` · #89 · #90 · #99 (prod revision recorded from SSH).
**Closed 2026-09-12:** #5 · #24 · #59 · #82–#88 · #91–#98 (#84 `228caaa`, deployed `81ded59`; #88·#91 `a566fce`, deployed `f55b75e`; #95·#97·#98 `525e5c3`, **not deployed**).
**Deferred past submission, with reasons:** #18·#25·#70 (worker path — prod runs no worker) · #78 (API not exposed; UI uses the rule parser) · #38 (refactor only).

## Open Feedback (ledger in `PROJECT_LOG.md`)

- **Routing:** `/debug` #18·#25 · `/design` #70 · `/build` #55 (before the video) · #78 after submission.
- **Stage 0 credential rotation closed as 미조치 by the user's decision.** EC2 `.env` carries no `OPENAI_API_KEY` (checked 09-01), so ADR-031 §31.3 holds.

## Next Action

**Cold start: `docs/긴급/세션인계.md` (2026-09-12) first** — both approved tasks with exact steps.

1. **Done 2026-09-12:** landing page published (`596c5c8`·`9a2ff53`, server ff-only, no rebuild); draft moved to `archive/`.
2. **Done 2026-09-12:** Streamlit four fixes (`6a147ff`·`9090651`·`a49097a`·`e265094`), `ui` rebuilt only. Open: 「gpt-4o-mini」 still wraps at its hyphen — a normal break opportunity `keep-all` does not govern.
3. **`/verify` re-run 2026-09-12 → 조건부 완료 (kept); its findings #94–#98 are fixed** (`525e5c3` and the record commit after it). **The server still runs `f55b75e`** — the landing shows 169 and the `settings.read` change is undeployed. Next: deploy, then re-run `/verify`. 「완료」 also needs `G3` to stop counting as a BLOCK.
4. **Tomorrow:** `#55` progress indicator → video → add the video to the landing page only once it exists.
5. **Deferred past submission:** `/debug` #18·#25 · `/design` #70 · #78 · #59 · `core.py` split (#38), dual-parser UI wiring, internal mTLS, dependency lock — each with a reopen condition. **Vue rewrite: after link submission (user decision 2026-09-12, reverses the 09-12 「no rewrite」).** In place on the same URLs so late reviewers see it: `/design` first (expose the API via Caddy `/api`, move the per-session run cap and cooldown to the server, #78) · blue/green cutover with instant rollback · landing/README text that names Streamlit updated in the same release · `index.html` served no-cache.

## Halt Reason

**Halted: no.** `docs/긴급/미결이슈.md` is superseded and kept as history.

## Machine State (2026-09-12, MacBook)

`PGPORT=5433 pytest` → **171 collected on 2026-09-12 (recounted after #97·#98)** (the summary line does not print: judge by exit code, count with a collection hook) · `gate --commit` COMMIT READY (G3 info · WARN 11 · X2 semgrep 0 · X3 pip-audit 0 — both installed via brew 2026-09-11) · `S3`·`S4` 0 · load 547/532/535 req/s, p95 24/165/268 ms at c=10/50/100 (`5257504`, clean hash; ±14% run to run).
**The MacBook needs `PGPORT=5433`** (Homebrew Postgres moved off 5432; non-interactive shells never read `~/.zshrc`, so the 41 DB tests skip silently). Python with deps: `/opt/homebrew/opt/python@3.11/bin/python3.11`.
**Windows desktop:** no docker, no `~/.ssh/loan-demo.pem`; run the gate as `PYTHONUTF8=1 python tools/gate.py .` (cp949 console).
**Personal notes live outside ROOT** (`~/Documents/portfolio/`) — gate `L1` walks all of ROOT regardless of `.gitignore` (#73).
