# Service Development Harness — Invariant Rules (always loaded)

> Claude Code loads this file every turn. It is the **invariant rule card**, an anchor against context decay (lost-in-the-middle). Keep it short. Detailed procedures live in each slash command / reference file.
> **Language:** operational files (this card, `PROJECT_STATE.md`, `SPEC.yaml`, gate output) are in English for token efficiency. **All user-facing output — approval requests, reports, the feedback ledger, and conversation — stays in Korean.**

## Invariant Rule Card

- **Priority order:** (1) legal/regulatory compliance (2) error-risk prevention (3) goal completeness (4) speed
- **Applicable regulations/licenses:** see `PROJECT_STATE.md` (if undetermined, halt and ask)
- **Forbidden automated actions:** see `PROJECT_STATE.md` (e.g. auto-trading/transfers, e-signature, external transmission, production changes) — never execute without approval
- **Data classification:** never store or transmit confidential / personal / trade-secret data verbatim in prompts, memory, or logs — masked only
- **Credentials never live in code:** keys, tokens, and passwords go to environment variables or a secret store — never a source or config literal. Gate `X1` blocks it. A key that was ever committed is compromised — rotate it, because deleting the line does not remove it from git history
- **Evidence rule:** link every factual claim to a primary source. If absent mark `[미검증]`; if post-cutoff or unverifiable mark `[확인 필요]`. Any remaining label blocks completion
- **Approval & halt:** destructive changes, external transmission, permission changes, and forbidden automated actions require user approval
- **Source of truth:** `PROJECT_STATE.md` outranks context memory. On conflict, the file wins
- **Dependencies:** **adopt by default** whatever the framework or standard library provides. To implement it yourself, record the reason in the docs
- **Spec first:** never create a public surface absent from `SPEC.yaml`. If you need one, return to `/design` and amend the spec. The spec does not follow the code
- **Context budget:** keep `PROJECT_STATE.md` at 100 lines or fewer. If exceeded, run `/compact` before the next step. Never skip it under deadline pressure
- **Commits are the user's:** never run `git commit` or `git push`. At a checkpoint, load `reference/commit-protocol.md` and follow it. Develop in parts, commit per feature — history is a human review surface, not an activity log
- **SRP:** one feature, one file. If a file would change for two different reasons, split it. Split by feature first, layer second
- **No internal markers in deliverables:** never write `[피드백N]`-style tags into code or docs. Write comments as cause → process → conclusion for a third-party reader. Gate `L1`/`L2` blocks leaks
- **Machine gate:** run `python3 tools/gate.py .` before submitting or publishing any artifact. Any remaining BLOCK prevents completion and publication
- **Review commands have fixed slots:** built-in `/code-review` and `/security-review` read the diff — an information source `/verify` never sees — so they complement it rather than duplicate it. But each runs **once per commit range, at the checkpoint**, never per spec item during `/build`. Re-running one over unchanged code returns no new information. Slots are in `.claude/commands/verify.md`

## Context-Decay Protocol (harness rules)

1. Never keep the whole framework resident in one context. Only this `CLAUDE.md` stays resident.
2. Each step runs **independently** as a slash command. Commands read `PROJECT_STATE.md` on start and write on completion. Cumulative records live in `PROJECT_LOG.md`, read **only by the commands that need it** — not every step.
3. Place critical constraints (regulations, forbidden actions, halt criteria) at both the start and end of each output. Never bury them in the middle.
4. At every step transition run a **boundary integrity check**: confirm regulations, forbidden actions, core requirements, and approval status survived. On loss or mutation, stop and restore from `PROJECT_STATE.md`.
5. Independent verification runs through the `independent-verifier` subagent (isolated context). Never judge completion from the builder's self-report alone. Re-verify against `reference/portfolio-criteria.md` immediately before publication.
6. **Style is a file, not code.** Voice lives in `ppt-style.md`/`report-style.md`; report layout values (color, pt, mm) live only in `report.css`. Never hardcode either into a command or renderer.
7. **Artifacts are handed off as prompts.** `/handoff` writes a self-contained prompt; execution goes to Claude or Codex. The executor reads style files directly — never copy their contents into the prompt. Report: `md + html → user approval → pdf → gate.py`; PDF renders only after approval.

## File Map

| Purpose | File |
|---|---|
| Invariant rules (this file) | `CLAUDE.md` |
| State (source of truth — read every step) | `PROJECT_STATE.md` |
| Cumulative record (feedback ledger, evidence, history — read as needed) | `PROJECT_LOG.md` |
| **Public surface spec (gate comparison target)** | `SPEC.yaml` |
| Design — scope, regulations, spec, logic review | `/design` |
| Build — iterate per spec item | `/build` |
| Verify — isolated context, once | `/verify` |
| **Diagnose — reproduce, hypothesize, refute. Not a pipeline step; interrupts `/build`** | `/debug` · `reference/debug-protocol.md` |
| Artifact prompt generation (document, report, drafts, slides) | `/handoff` |
| State compaction (LSTM gate) | `/compact` |
| Completion criteria | `reference/completion-criteria.md` |
| Portfolio / publication criteria | `reference/portfolio-criteria.md` |
| ML/LSTM-specific controls | `reference/ml-lstm-controls.md` |
| Project metadata schema | `reference/project-schema.yaml` |
| Evidence schema | `reference/evidence-schema.yaml` |
| Publication rules & sensitive-data scan | `reference/publishing-rules.md` |
| **PPT style (swappable — visual/tone only)** | `reference/ppt-style.md` |
| **Deck content contract (not swappable)** | `reference/deck-contract.md` |
| **Report voice** `report-style.md` (judgment) **+ layout tokens** `report.css` (color × classic/modern/formal) | `reference/` |
| Report layout exception — formal (4-level hierarchy, left aside, no running head) | `reference/examples/report-style-formal.md` |
| **Report content contract (not swappable)** | `reference/report-contract.md` |
| Report profiles (load one) · stack exec steps (load if that stack) | `reference/report-profiles/` · `reference/stack-spring.md` |
| AI-tell checklist (prose) | `reference/ai-tell-checklist.md` |
| AI-tell checklist (code & repo) | `reference/code-tell-checklist.md` |
| **Design review criteria (symmetry, dead surface, permissions)** | `reference/design-review-checklist.md` |
| **Insight assets — principles (violation = defect) vs. adoption candidates (non-adoption is normal)** | `reference/insights/` · `INDEX.md` first |
| Insight assets outside the pipeline — read, collect, promote | `/insight` |
| **Commit protocol (checkpoint only)** | `reference/commit-protocol.md` |
| Machine gate (hygiene, comments, history, docs, spec diff, **API design rules**, leak, **secrets · SAST · vulnerable deps**, **infra hardening**, commit readiness, **report brief**, **report artifacts**, **page-box coordinates**, **line-break unit**, **deck contract**) | `tools/gate.py` |
| Gate self-test | `tools/test_gate.py` |
| **Image slot planner (pre-render; decides layout without opening the images)** | `tools/image_plan.py` |
| **Executable report (run, capture, PDF, ZIP)** | `reference/report-exec-harness.md` |

## Execution Order

```text
environment check (dry-run) → create PROJECT_STATE.md · PROJECT_LOG.md
→ /design   ← all judgment-requiring review happens here. one approval at the end
→ /compact
→ /build    ← iterate per spec item; gate on the first item only, then checkpoint
→ /compact
→ /verify   ← isolated context, once
→ /handoff document → user review & approval
→ [artifact prompts: /handoff report · /handoff publish · /handoff ppt — any order, only what you need]
→ [execute: Claude or Codex → md + html → user approval → pdf → gate.py]
```

**What design review fails to catch will not be caught by self-review during build.** Re-examination inside the same context yields no new information. So judgment concentrates in `/design`, and during build only the machine diff (`gate.py` S3·S4) runs.
If the design must change mid-build, **return to `/design`.** Quietly growing the spec to match the code makes the diff catch nothing.

All `/handoff` types are generated after `/handoff document` is approved, and they do not depend on each other. `report` is the closing report, `publish` the channel drafts, `ppt` the slide prompt. **Whoever produced the result, verify it with `gate.py` against the same criteria.**
**`/debug` is not part of this chain either.** It interrupts `/build` when a test fails or behavior surprises you, and returns to it. If the fix requires changing the design, go back to `/design` — never widen the spec from inside a debugging session.

**`/insight` is not part of this chain either.** It reads `reference/insights/` against the current code, collects new insights, and judges promotion. It runs on its own in projects that use no pipeline at all, so it must not require `PROJECT_STATE.md` or `SPEC.yaml`.

**Review commands are not part of this chain.** They attach to the checkpoint inside `/build`, once per commit range — see the slot table in `.claude/commands/verify.md`. Do not insert them between the steps above.

**On every command run: obey this card + re-read `PROJECT_STATE.md` + run the boundary integrity check.**
