# Handoff — Agent B (second Claude Code session, second laptop)

> Written 2026-10-08 by Agent A (the autonomous orchestrator running since 2026-10-05). Agent A keeps
> running on the owner's main laptop. This document gives you everything that is **not** in the tickets:
> the operating procedure that has worked for 92 merged PRs / 27 Done tickets, the traps that cost us
> hours, the lane split so we never collide, and a 50-ticket work queue. **Every ticket's full story,
> acceptance criteria and agent execution brief are in its GitHub issue** — read the issue, not a summary.

---

## 0. Before anything else (30 minutes, non-negotiable)

1. Read, in order: `CLAUDE.md`, `CONSTITUTION.md` (Appendix A), `AGENTS.md` §3–§9, `.claude/rules/*.md`,
   `docs/plan/01-sdlc-and-branching.md`, `02-definition-of-ready-done.md`, `03-testing-strategy.md`.
2. Read `docs/plan/backlog/_tools/_autonomous_run_2026-10-05.md` **from "Lessons" sections onward** — it is
   Agent A's append-only run log. Every incident below is recorded there with the PR number.
3. Confirm your environment: `git clone`, `pnpm install --frozen-lockfile`, `cd services/api && uv sync`,
   and a working `gh auth status`. Install `semgrep` (v1.178) system-wide; `ruff`, `mypy`, `black`,
   `lint-imports` come from the venv. Confirm `python docs/plan/backlog/_tools/board_snapshot.py` runs.
4. Post one comment on `#1778` (the owner decision queue): `Agent B online on <hostname>, lanes per
   HANDOFF-agent-B-2026-10-08.md §3`. That is how Agent A knows you exist.

---

## 1. Operating model (the loop that works)

Agent A's cadence, which you should copy exactly:

```
tick (every ~5 min while work is in flight; ~10–20 min when only CI is pending):
  1. gh pr list --author "@me" --state open         # re-derive truth; never trust memory
  2. merge any PR with: CLEAN + 2 independent APPROVE verdicts on the CURRENT head
     (security APPROVE additionally required when the PR has label security-review)
  3. process finished agents (fix rounds → re-verdicts; QA → qa_close.py)
  4. launch new work only while total agents ≤ 7 and opus agents ≤ 2
  5. git branch --show-current == main; git status --short shows only untracked tool files
  6. append to the run log
```

### 1.1 Build → review → fix → re-verdict → merge → QA → Done

| Step | Who | Rule |
|---|---|---|
| Build | 1 subagent (`backend-implementer` / `frontend-implementer` / `test-writer` / `statechart-author`) | Works in `$TEMP/wt-<issue>`, never in the main checkout. Claims the issue first. |
| Review | **2 independent** subagents (`code-reviewer`; `security-reviewer` on security paths) | Posted as PR **comments** titled `Code review — VERDICT: APPROVE\|REQUEST CHANGES` and `Security review — VERDICT: …`. GitHub refuses approve/request-changes on your own PR — comments are the record; `done_gate.py` parses them. |
| Fix round | the ORIGINAL build agent via `SendMessage` (keeps its context) | One combined commit per round; map every finding → fix/test in a PR comment. Wait for both reviews before dispatching so it is one round. |
| Re-verdict | the ORIGINAL reviewer via `SendMessage` | Must say `(re-verdict)` and the head SHA it checked. |
| Merge | you (orchestrator), `gh pr merge N --squash --delete-branch` | Only after step 2 conditions. Code PRs: orchestrator merges. **Design PRs (#1458/#1473/#1475 and any `design/*`): never.** |
| QA | 1 `test-writer` subagent, black-box, independent of the PR's tests | Posts `Recorded demo (C-10.4 black-box run on main <sha>)` then `QA verification (C-10.4) — VERDICT: PASS` with an AC→evidence table, then runs `python docs/plan/backlog/_tools/qa_close.py <KEY> <issue#>`. |

### 1.2 Model ladder (owner policy, mandatory)
`sonnet` default for everything. `opus` only for genuinely hard design/concurrency work (BarBuilderSet,
E13-K01 spike, E12-S05 were opus). Never `haiku`. Always pass `model` explicitly to every `Agent` call.

### 1.3 Dynamic workflows vs. plain parallel agents
Use the `Workflow` tool (`workflow-authoring` skill) when a batch has the **same shape** — e.g. "security
review these 4 PRs", "QA black-box these 3 merged tickets", "STRIDE-check these 5 modules". Pipeline
pattern: `review → verify` per item so dimension N verifies while N+1 reviews. Keep ≤ 8 agents per
workflow on a laptop. For heterogeneous work (one build, one QA, one fix round) use plain `Agent` calls in
one message so they run concurrently. Never run a workflow AND 7 agents at once — RAM.

### 1.4 Concurrency budget on a laptop
16 GB / 8 threads: ≤ 7 concurrent agents, ≤ 2 opus, pytest runs under coverage take 10–17 min for the
whole `services/api` suite — tell agents to run **package-scoped** tests (`pytest tests/unit/<pkg>`) and
only CI runs the full suite. Never run two full-suite pytest runs at once.

---

## 2. Traps that cost Agent A hours — every one is now a rule

Put these verbatim into **every** subagent prompt you write (copy the block in §6).

| # | Trap | Rule |
|---|---|---|
| T1 | An agent whose `git worktree add` failed ran `git checkout <branch>` **in the main checkout** (PR #2036). | "If `git worktree add` fails, STOP and report — never `git checkout` in the main checkout." After every agent: `git branch --show-current` must print `main`. |
| T2 | PowerShell `Set-Content -Encoding utf8` writes a **UTF-8 BOM**; a BOM-prefixed commit subject makes commitlint read an empty type (#2036). | Commit-message edits only via bash + `-F` from a BOM-free file. |
| T3 | Dictated commit subjects > 100 chars; body lines > 100 chars (#2025, #2044, #2062). | Count. `awk '{ if (length($0)>100) print "LONG" }' msg.txt` before committing. |
| T4 | `black` passes but CI runs **`ruff format`** (#2044). | Format gate is `ruff format --check`, not black. |
| T5 | GitHub GraphQL intermittently rejects `gh pr create --label` / `gh issue create --label` ("Something went wrong"). | Create without labels, then `gh pr edit N --add-label …`. |
| T6 | `gh issue comment -F file` fails on non-UTF-8 files (cp1252 mojibake) (#343 QA). | Post with `Get-Content -Raw -Encoding UTF8 f \| gh issue comment N -R CandleViewer/CandleViewer --body-file -`. |
| T7 | Fetching a force-pushed PR head without `+` leaves the old ref (#2041 security re-check stalled 9 h). | `git fetch origin +refs/pull/N/head:refs/remotes/pr/N`. |
| T8 | Agents run `semgrep --config .semgrep/` on the whole dir — it **errors** on the malformed `.semgrep/tests/cv-unpinned-action.yml` and the exit code is unreliable. | Run the 33 `.semgrep/cv-*.yml` rules **individually** and read the output, not the exit code. |
| T9 | Stacked PR auto-closed when its base branch was deleted at merge (#1947). | `gh pr edit <stacked> --base main` **before** merging the base PR; then `rebase --onto` locally (GitHub's update-branch refuses). |
| T10 | Pre-push hook rejects the `test/` branch prefix although C-4.4 allows it (#2066). | If the hook rejects the prefix, push via a `tmp/<name>` branch with `--force-with-lease`. Never `--no-verify`. |
| T11 | `Closes #N` on a QA-gated ticket auto-closed it at merge, skipping QA (#720, #394). | Use `Closes` only when the PR is the whole ticket AND you will reopen+QA immediately; otherwise `Refs #N` and let `qa_close.py` close it (gate now links merged `Refs` PRs — PR #2070). |
| T12 | A PR's CI ran on a head that predated a hotfix on main, or a lane was **skipped** by the path filter and `ci-required` still passed (#2007). | Before merging: confirm the head contains current main and that the relevant lane actually RAN (not SKIPPED). |
| T13 | Agents reported "all tests pass" after running a subset, or "semgrep clean" from an erroring run. | Reviewers re-run gates themselves. Treat agent self-reports as claims. |
| T14 | Perf/wall-clock asserts flake on shared runners (`test_reaper_loop_lag`, `test_stage_recorder_overhead…`). | Ratio/complexity asserts + generous sanity bound, gc disabled, fastest-of-N, non-zero baseline; `@pytest.mark.perf` excluded from the default lane. Recurrence → quarantine + P1 issue (C-9.3), never retry-until-green. |
| T15 | Module-level `structlog.get_logger()` + `cache_logger_on_first_use` made `capture_logs()` miss events depending on test order (6 fixes). | Now a Semgrep rule (`cv-module-level-structlog-logger`, #2069) + autouse reset fixture (#2058). Use per-call `_log()` at emit sites. |
| T16 | QA agents went silent for hours without posting (#720). | A QA agent must post within its run or report the blocker; replace after ~2 h of silence. |
| T17 | Agent left stray local branches / `$TEMP/wt-*` dirs. | After each agent: `git branch --list` and delete leftovers (only if not in `git worktree list`); `git worktree prune`; delete orphan `$TEMP/wt-*`. |
| T18 | `qa_close.py` on Windows: `UnicodeDecodeError` in a subprocess reader. | Run with `PYTHONUTF8=1`. |

---

## 3. Lane split — how we avoid colliding

**Agent A owns (do not touch):** E12 bars/klines follow-ups (#398 E12-T05, #2067, #2055, #2066, #2071,
#2068 fix round), E22 big trades, E13 indicators, E16 storage, anything under
`services/api/candleviewer/{bars,ingestion,orderflow,storage}`, `docs/plan/2{0,1,4}-*.md` bars sections,
the owner decision queue `#1778`, and the run log `_autonomous_run_2026-10-05.md`.

**Agent B owns (this document):** the **auth → WS gateway → accounts/key-vault → OMS foundations** chain
and the GA-phase QA packs. Paths: `services/api/candleviewer/{auth,accounts,secrets,ws,audit,oms,risk}`,
`apps/web/e2e/**`, `tests/contract/rbac/**`, `tests/chaos/**`, `docs/security/**` for those epics,
`docs/plan/23-ws-protocol.md` (sections your tickets name), `docs/plan/22-api-openapi.yaml` paths under
`/auth`, `/accounts`, `/audit`, `/ws`.

**Shared hotspots — comment on the ticket and wait for the other agent's ack before editing:**
`packages/protocol/**` (generated — regenerate, never hand-edit), `services/api/candleviewer/app.py` /
`main.py` lifespan wiring, `observability/metrics_catalogue.py` (golden hash — one PR at a time),
`security/accepted-risks.yaml`, Alembic `versions/` (single head — one migration PR in flight repo-wide),
`machine_hashes.lock`, `.github/workflows/**`, `CONSTITUTION.md`/`AGENTS.md`/`CLAUDE.md`.

**Coordination channel:** comments on the ticket (claim, blocker, ack) — not chat. Claim format:
`claimed by agent-B/<session> — branch <name>`. Both agents re-derive open PRs from GitHub each tick, so
a PR you open is visible to Agent A within minutes and vice-versa. If you see a PR from Agent A touching
your lane, do not review or merge it — comment and wait.

**Owner-gated items (do NOT start, do NOT work around):** anything whose `blocked_by` includes a design
ticket (`E*-D*`), items R/S/T on #1778, E06-T01 (reference machine), E08-Q04 (24 h soak), and
**E09-X04's owner sign-off step** — you can execute everything in E09-X04 except the sign-off itself.

---

## 4. The work queue — 50 tickets in dependency order

Each entry: `KEY #issue · kind/pts · title` → **why it's yours / what unlocks** → **steps beyond the
issue's own Agent execution brief** → **gotchas**. The issue body is the contract: Context, Scope,
Gherkin, Agent execution brief (Read first / Repo paths / Interfaces / Commands / Branch & PR / Done means
/ Do NOT / If blocked). Always `gh issue view N` and read ALL comments — scope additions from STRIDE models
and the orchestrator live there.

Status legend: **READY** start now · **NEXT** starts when its named blocker merges · **GATED** needs the owner.

### Wave 1 — E09 auth closure (READY). Unlocks all of E17, E27, E42-T02.

The whole chain below hangs off E09. Note **#230 E09-S03 is "Blocked" only on its FRONTEND half**
(#1640, design-gated); the backend half merged in PR #1638. Every E09 ticket below depends on the
BACKEND behaviour, so treat E09-S03's backend as Done. Record that reasoning in your claim comment.

1. **E09-X02 #298 · Task 5 · Abuse cases and adversarial testing of auth, session and RBAC boundaries** — READY
   - Unlocks E09-X04, E17-S01, E27-*, E42-T02. Highest-leverage ticket in this document.
   - Steps: build `docs/security/abuse-cases/e09-auth.md` from the E09-X01 threat table (#196) — one case
     per threat with precondition/capability/steps/expected/observed/verdict/control-id. Automate the
     durable subset under `tests/security/auth/` (fixed-clock, no network, no sleep). Timing-enumeration
     test: 500 samples, statistical test, record the threshold used. Any privilege escalation found → P0
     issue + regression test BEFORE the fix, and comment on #1778.
   - Gotchas: Argon2id params must be read from the DB, not config. CSRF cases need the double-submit token
     from `auth/`. Use `security-reviewer` + `code-reviewer`; label `security-review`.
2. **E09-Q03 #294 · Task 5 · RBAC allow/deny matrix regression pack** — READY (parallel with X02)
   - Steps: `tests/contract/rbac/matrix.yaml` (route|topic × 5 roles → outcome + permission string from
     the 36-string vocabulary); `test_route_matrix.py` discovers routes from the FastAPI app and topics
     from the WS registry (23 §6), asserts totality both ways, executes each cell with real sessions.
     Two-layer SR-050 and scope-at-construction SR-051 assertions. Making `rbac-matrix` a required check
     touches CONSTITUTION C-9.1 → that part is **owner-gated**: implement the test, propose the check
     addition on #1778, do not edit the required-check list yourself.
3. **E09-Q02 #293 · Task 5 · Playwright E2E: login, TOTP, idle lock, step-up, onboarding** — READY (parallel)
   - Steps: six specs under `tests/e2e/auth/` (web; two tagged for Electron). Fake clock for idle-lock and
     step-up expiry. Deterministic (3× run). Every automatable `E09-TC-*` from E09-Q01 (#227) covered or
     deferred with an issue id in the plan.
   - Gotchas: frontend screens from #1640 are NOT merged (design-gated) — specs that need SCR-005/SCR-112
     UI must be written against the existing SCR-001/004 screens or deferred with `deferred → #1640`.
4. **E09-Q05 #296 · Task 3 · Auth perf profile + chaos (k6, clock skew, Postgres restart)** — READY (parallel)
   - Steps: `perf/k6/auth.js`, `tests/chaos/auth/` (5 scenarios, `@pytest.mark.chaos` + integration),
     `docs/qa/perf/e09-auth-perf-report.md` with numbers. Follow T14 for any wall-clock assert.
5. **E09-Q06 #297 · Task 3 · Exploratory charters, regression pack, QA sign-off** — NEXT after 2–4
   - Four charters under `docs/qa/charters/`, `qa/plans/e09-regression-pack.md`. The "sign-off" is QA's, not
     the owner's — you may run it. Coverage rollup must show auth/rbac/audit ≥85 %.
6. **E09-X04 #300 · Task 3 · Security review, break-glass drill, Owner sign-off** — NEXT after 1
   - Do everything except the owner's signature: `docs/security/reviews/e09-auth-review.md`, both drill
     reports, triage table, break-glass runbook corrections. Then post on #1778 as **item U** with ★
     "approve as recorded" default. Mark the ticket In Test, not Done.
7. **E09-K02 #292 · Chore 2 · Auth/RBAC operator runbook + ADR-0010 addendum** — NEXT after 5–6
   - Eight procedures in `docs/ops/runbooks/auth-rbac.md`; the "executed on staging by a non-author"
     DoD line → `deferred → #1778 item U`.

### Wave 2 — E17 WS gateway (NEXT after E09-X02/X04 land as In Test). The biggest lane: 11 tickets.

The CVWB binary codec (E17-T02, #380) is **Done** — `candleviewer/ws/binary.py`, the layout declaration
`packages/protocol/cvwb-layout.json`, the TS decoder, the 61-seed corpus, nightly fuzz and §16.3 benches
all exist. `BarCoalescer` (`ws/bar_coalescer.py`, #2033) exists but is unconsumed. **Build on them; do
not re-implement framing.** Contract-first (C-6.1): any change to `docs/plan/23-ws-protocol.md` is its own
small PR, regenerated via the REAL generator (`cd packages/protocol && pnpm run generate` — turbo caches
it, #1940 — and `python tools/contracts/extract_ws_schemas.py`), merged before the consumer PR.

8. **E17-S01 #377 · Story 3 · WS connection lifecycle: negotiation, auth handshake, re-auth, heartbeats** — NEXT
   - Blockers E09-K02/X02/X04: treat as satisfied once X02 is merged and X04 is In Test (owner signature
     pending) — say so in the claim. Endpoint `wss://<host>/api/v1/ws` in `services/api/candleviewer/ws/`.
     Close codes per 23 §9.5 (4401 revoked/bye). Query-string tokens must be rejected (test). Heartbeat
     watchdog with fake clock. Reuse the E09 session/RBAC primitives — never a second auth path.
9. **E17-S02 #378 · Story 5 · Subscriptions, topic registry, per-topic authorisation, live revocation** — NEXT after 8
   - The topic registry is what E09-Q03's matrix discovers; coordinate: the registry interface must expose
     `(topic pattern, permission string)`. Live revocation hooks into `ws/revocation.py` (exists).
     Spec-cap check: `BarBuilderSet.register(user=<principal>)` from #2030 — this is the first production
     caller of `register()`; `user` MUST be the authenticated principal id (never client-supplied).
     Agent A owns `bars/`; if you need a change there, comment on #397 and wait.
10. **E17-X01 #381 · Task 3 · STRIDE threat model for the client WS protocol and gateway** — NEXT after 9
    - `docs/security/threat-models/E17-ws.md` following `E12-bars.md`'s row format (SR-E17-NN ids, BR rows).
      Status **Draft → Approved requires owner risk acceptance** (lesson from #1992): leave it Draft and
      post the acceptance request on #1778. Register its ticket map in
      `scripts/check_threat_model_ticket_map.py` or the governance check fails.
11. **E17-S03 #411 · Story 5 · Snapshot+delta sequencing, resync triggers, snapshot chunking** — NEXT after 9
    - Per-topic sequence numbers (23 §7); gap → resync from snapshot (C-2.5). The bars topic's coalescing
      key is `(generation, index)` with the §8.2 `amended` carve-out (#2033) — consume `BarCoalescer`.
12. **E17-T03 #412 · Task 5 · Per-topic coalescing, adaptive throttling, bounded-queue backpressure** — NEXT after 11
    - `CoalescingQueue` per (connection, topic) with per-family rules (23 §8.2: trades/liquidations
      append-never-merge; bars replace-by-key). Bounded memory chaos scenario with measured peak on the
      ticket. Overflow ladder order asserted by test. Every queue `maxsize`d (C-2.18). This is the fan-out
      primitive #1016/E40-T04 and E22-T02 are waiting on — announce the merge on both issues.
13. **E17-X02 #415 · Task 3 · Security review, abuse cases, decoder fuzzing, SAST/DAST for WS** — NEXT after 10, 12
    - Decoder fuzzing ALREADY EXISTS (nightly `fuzz-nightly.yml`, #2062) — extend the corpus for the new
      control frames rather than adding a second harness. Abuse suite `tests/security/ws/` mapped 1:1 to
      E17-X01 rows. New semgrep rules → `.semgrep/cv-*.yml` + fixture under `.semgrep/tests/` + each rule
      demonstrated failing on a deliberate violation; label `security-review`.
14. **E17-Q01 #409 · Task 5 · WS protocol conformance suite + black-box plan** — NEXT after 11
    - `tests/conformance/ws/` protocol-level client speaking both subprotocols; S1–S12 each a named test;
      §16.4 contract rows; `heatmap_bucket_selection` against every recorded fixture (no network).
15. **E17-Q02 #410 · Task 3 · WS chaos: upstream loss, slow consumer, burst, restart** — NEXT after 12
    - `tests/chaos/ws/` deterministic fault injection; six scenarios; nightly job (SHA-pinned actions,
      `permissions: contents: read`, `concurrency` group — copy `fuzz-nightly.yml`).
16. **E17-T06 #571 · Task 2 · Instrument the gateway: metrics, budget-#6 spans, connection quality** — NEXT after 12
    - Metric names go through `observability/metrics_catalogue.py` (golden hash — ask Agent A before
      editing; one catalogue PR at a time) and `docs/plan/20-architecture.md` §12.1. Labels must be in
      `.semgrep/cv-obs-metric-label-allowlist.yml` — use existing names (`kind`, `reason`, `topic`,
      `result`…); never widen the allow-list yourself.
17. **E17-Q03 #568 · Task 2 · k6 WS load profile + §16.3 budgets** — NEXT after 12, 16
    - `tests/load/ws/`; profiles A/B/C; results + W5 recommendation. Runs in the nightly/perf lane only.
18. **E17-T08 #414 · Task 3 · Statechart-backed topic `machines.{entity}.state`** — NEXT after 9, 11
    - Reads the plain state enum the machines publish on entry (C-2.20: never query an interpreter per
      message). Per-entity RBAC via the registry. Statechart runtime imports only via
      `cv.statechart.factory` — a hook blocks anything else.
19. **E42-T02 #889 · Task 5 · Audit query, hash-chain verify, signed export endpoints** — NEXT after E09-X02
    - `audit/` is append-only (C-2.9, C-5.7): READ paths only; never `UPDATE`/`DELETE`. Hash-chain verify
      must stream (bounded memory). Routes under `/audit` in 22-api-openapi.yaml — contract-first PR.
      RBAC: owner-only + forbidden-role test + cross-account test.

### Wave 3 — E27 accounts & key vault (NEXT after E09-X02/X04). Unlocks E28, E29, E39.

This is the most security-sensitive lane in the product (C-2.7, C-2.8, C-12.2, ADR-0009). Every PR
here carries `security-review` and gets BOTH reviewers. Plaintext key material exists only inside
`services/api/candleviewer/secrets/` and only in memory. Keys with withdrawal permission are rejected
(C-2.8, Semgrep-enforced). No real credentials ever — fixtures use fixed test vectors.

20. **E27-K01 #832 · Spike 2 · KEK custody, injection and rotation for WSL and VPS** — NEXT
    - Output is a FINDING (ADR amendment or `docs/plan/spikes/e27-kek.md`) on a `docs/` branch + a
      throwaway `spike/` branch deleted after ratification (C-4.5, as E13-K01 did). Owner ratifies → post
      as an item on #1778 with ★ default. Ticket goes In Test after the finding PR merges.
21. **E27-T01 #834 · Task 3 · `exchange_accounts`, `api_keys`, `api_key_rotations` migrations + domain models** — NEXT (parallel with K01)
    - **ONE Alembic migration per PR repo-wide** (C-5.3). Before creating it, check
      `services/api/candleviewer/migrations/versions/` on `origin/main` and `gh pr list` for any open PR
      adding a migration (Agent A's #2016 bars migration is owner-gated and NOT open — but check). Comment
      on the ticket "taking the migration slot" before you start. Reversible `downgrade()`, round-trip
      test, `21-database-schema.md` updated in the same PR with C-5.9 classification of the credential
      columns (envelope-encrypted blobs only).
22. **E27-X01 #838 · Task 3 · STRIDE threat model for accounts, sub-accounts and the API-key vault** — NEXT after 20
    - Same rules as E17-X01 (#10): Draft status, owner accepts risk, ticket map registered.
23. **E27-T02 #835 · Task 5 · M2 credential broker: envelope encryption, KEK loader, degraded mode** — NEXT after 20, 21
    - DEK-per-key wrapped by KEK; plaintext only inside `secrets/` for the duration of signing; degraded
      mode when the KEK is unavailable must fail CLOSED for signing and surface in health. Import-linter:
      only the modules C-3.2 allows may import `secrets`. Tests: fixed vectors, no real keys, redaction
      filter asserted on every log path. Consider `opus` for this one.
24. **E27-T03 #836 · Task 5 · Mandatory API-key verification pipeline + key self-check service** — NEXT after 23
    - Verify-on-add and hourly: permissions must exclude withdrawal (C-2.8) — reject otherwise; uses the
      REST client's public/private buckets per C-12.7 (never the stop/cancel reserve). Recorded fixtures
      only (`packages/fixtures/bybit/…`, `tests/fixtures/bybit/`); the REST body cap from #2051 applies.
25. **E27-T04 #837 · Task 2 · Per-account health, key-age policy, wallet snapshot cache** — NEXT after 24
    - Health reasons via the registry probe pattern (`register_*_probe` in app.py, see
      `register_bars_probe` from #2030 as the template).

### Wave 4 — Cross-cutting security/QA tickets that are READY now (parallel with Waves 1–3)

26. **E13-X01 #428 · Task 3 · STRIDE threat model + abuse cases for the indicator framework** — READY
    - Input is ADR-0034 (merged in #2050, Proposed) and `docs/plan/spikes/e13-o4.md`. Format per
      `docs/security/threat-models/E12-bars.md`. Register the ticket map. Draft status.
27. **E12-X03 #453 · Task 3 · SAST/DAST rules and CI security gates for bar and market-data surfaces** — READY
    - Agent A owns the bars CODE; you own the RULES. New `.semgrep/cv-*.yml` + fixtures + demonstrate each
      failing on a violation. Coordinate the list of surfaces with Agent A via a comment on #453 (Agent A
      will reply with the current module list). The DAST part needs a running stack → integration lane.
28. **E12-Q01 #393 · Task · Black-box test plan for the E12 bar-builder story groups** — NEXT, not READY
    - `blocked_by` includes E12-T05 (#398), which is Agent A's next ticket. Take it only after #398 merges;
      the plan is docs + charters (§11.2), no code. Ask Agent A on #393 before starting.
29. **E14-T01 #357 · Task · `drawings` table migration + owner-scoped `/drawings` REST endpoints** — NEXT after E09-X02/X04
    - Backend-only (migration + OpenAPI + routes); migration slot rule (#21); contract-first on
      22-api-openapi.yaml; RBAC owner-scoped + IDOR test. Same E09 gating as Wave 2.
30. **E14-X01 #433 · Task · STRIDE threat model for drawings persistence, sync, annotation content** — NEXT after 29
    - The issue's Repo paths mention `packages/chart-engine` — that is a template artefact; the model is a
      `docs/security/threat-models/E14-drawings.md` document. Draft status; ticket map registered.
31. **E15-T01 #402 · Task · `workspaces`/`layouts`/`layout_panes` migration + `/workspaces` REST API** — NEXT after E09-X02/X04
    - Backend-only; migration slot rule; contract-first; owner/manager scoping tests. Do NOT touch the
      workspace UI (E15-D02 design-gated).
32. **E37-K01 #877 · Spike 2 · Validate the graph library for 200-node fps + keyboard connect** — GATED
    - Blocked only on the Electron/reference-hardware AC (#1778 group A). Do not start; if the owner
      accepts the headless measurement, the spike is effectively done — then E37-T01 #951 becomes READY.

### Wave 5 — OMS / risk / profiles foundations (NEXT after E27-T01..T04). Real-money code: C-2.6/2.8/2.9/2.10.

Every order path needs an explicit native-SL assertion in its tests (C-2.6). Every submit/amend/cancel
writes an audit record write-ahead (C-2.9). `orderLinkId` deterministic and reused on retry (C-2.10).
Safety-critical modules ≥95 % coverage + mutation testing (AGENTS §6). Nothing here calls a live exchange.

33. **E29-K01 #843 · Spike 2 · Measure the Bybit demo order path + private-WS parity** — GATED-ish
    - The spike wants a demo-account run, which needs the owner's demo credentials → NOT available to
      agents (C-2.7, AGENTS §8). Do the offline half (fixture-driven parity model, measurement harness,
      the finding note skeleton) and post the credential-dependent half as an owner item on #1778.
34. **E29-T01 #845 · Task 2 · OMS schema migration + repositories (orders, events, executions, positions)** — NEXT after E27-T01
    - Migration slot rule (#21). Audit tables: no UPDATE/DELETE grants (C-5.7). `Decimal` columns for
      prices/qty, never float.
35. **E29-T02 #846 · Task 1 · `orderLinkId` generator, collision check, adoption rules** — NEXT after 34
    - Deterministic from (intent id, leg, attempt); ≤36 chars; Bybit charset; property test for
      collision-freedom; duplicate-id rejection = "already accepted" → reconcile, never resubmit under a
      new id.
36. **E29-X01 #849 · Task 3 · STRIDE threat model for the OMS and order placement** — NEXT after 33's offline half
37. **E39-X01 #883 · Task 3 · STRIDE threat model for risk caps, lockouts, kill-switch** — NEXT after E27-X01
38. **E39-T02 #882 · Task 2 · Migrations + internal schemas for `risk_lockouts`, `risk_policy`, `kill_switch_state`** — NEXT after 37 (migration slot rule)
39. **E28-X01 #910 · Task 2 · STRIDE threat model for per-account profiles and trade groups** — NEXT after E27-X01
40. **E28-T01 #905 · Task 2 · `account_profiles`, `trade_groups`, `trade_group_legs` migrations + models** — NEXT after 39 and E27-T04 (migration slot rule)
41. **E28-Q01 #904 · Task 2 · Black-box test plan + fixture set for profiles, sizing, trade groups** — NEXT after 40
42. **E28-T02 #906 · Task 2 · Profile CRUD routes with exchange-limit validation + audited step-up saves** — NEXT after 40
    - Contract-first (`/accounts/*/profiles` in 22-api-openapi.yaml → regenerate → implement). Step-up
      reuses E09's primitive. Forbidden-role + cross-account tests on every route.
43. **E28-T03 #907 · Task 5 · Server-side leg sizer: sizing rules, stop resolution, lot/notional rounding** — NEXT after 42
    - `Decimal` throughout; round via the instrument-info cache tick/lot/min-notional; hypothesis tests on
      rounding invariants; risk is enforced server-side (C-12.5). Consider `opus`.
44. **E28-K01 #968 · Spike 1 · Per-trade override semantics + profile-change propagation** — NEXT after 40 (finding note, C-4.5)
45. **E28-T05 #909 · Task 2 · Trade-group definition, preview endpoint, `trade_groups` WS projection** — NEXT after 43 and E17-S02
46. **E28-X03 #976 · Task 2 · Abuse-case + RBAC assertion suite for every profile/trade-group route** — NEXT after 42, 45

### Wave 6 — GA-phase packs (READY in principle, but mostly premature — pick only when nothing else is open)

47. **E47-T01 #1323 · Task 3 · Full WCAG 2.2 AA sweep SCR-001..SCR-159 → findings register** — READY but most
    screens are not built; a sweep of the built subset (SCR-001/004 auth, E47 preference screens) with
    the rest marked "not built" is honest work; do not pad.
48. **E47-S04 #1318 · Story 3 · Reduced-motion coverage + three-flashes-per-second ceiling** — READY; the
    flash gate (`tools/a11y/gates.py` G005) and `prefers-reduced-motion` plumbing exist (E47-S07).
49. **E49-X02 #1396 · Task · Verify the abuse cases + GA security scan sweep on the candidate** — GATED
    - `blocked_by` E49-X01/S02/S03 are open; it is a GA-candidate activity. Do not start. Listed so you
      know where the Wave 1–5 abuse suites eventually roll up.
50. **E35-S03 #863 · Story 5 · Execute rule actions through the OMS under per-rule safety limits** — **DO NOT START.**
    Its `blocked_by` lists only E35-S02, but every AC routes through the OMS (E29-T01..T03) and native SL.
    Your task here is a 5-minute hygiene fix: comment the real dependency list on #863 and edit
    `docs/plan/backlog/E35.json` `blocked_by` via Python (load → modify → `json.dump(ensure_ascii=False,
    indent=2)`), run `validate.py`, open a `docs(backlog)` PR. Agent A has already noted this on the issue.

---

## 5. Suggested parallel plan for your first 48 hours

```
Hour 0   §0 checklist; post "Agent B online" on #1778.
Hour 1   Launch Wave 1 in ONE message (4 agents, all sonnet):
           E09-X02 (security abuse cases)      E09-Q03 (RBAC matrix)
           E09-Q02 (Playwright auth suite)      E09-Q05 (perf+chaos)
         + 2 READY cross-cutting docs tickets as a 5th/6th slot: E13-X01, E12-Q01.
Hour 2+  Review each PR as it lands with a 2-reviewer Workflow (see §1.3): dimensions
         ["code-correctness", "security"] → verify. Fix rounds back to the builder. Merge on CLEAN+2.
Day 1 pm Wave 1 QA closures via qa_close.py; launch E09-Q06, E09-X04 (minus signature), E12-X03.
Day 2 am E09-X04 In Test + item U posted → launch E17-S01 and E27-K01 + E27-T01 (migration slot!).
Day 2 pm E17-S02 when S01 merges; E27-X01; E42-T02. Keep ≤7 agents; opus only for E27-T02 / E28-T03.
```

Expected throughput at Agent A's measured rate (≈ 15 PRs/day with reviews): Waves 1–2 in ~4 days,
Wave 3 by day 6, Wave 5 by day 9 — assuming the owner answers item U (E09 sign-off) and the E17/E27
threat-model risk acceptances within a day of being posted.

---

## 6. Prompt block to paste into EVERY subagent you launch

```
Rules (non-negotiable):
- Work ONLY in a worktree: `git fetch origin && git worktree add -b <branch> "$TEMP/wt-<issue>" origin/main`.
  If `git worktree add` fails for ANY reason, STOP and report — never `git checkout` in the main checkout.
- Claim first: `gh issue edit N --add-assignee @me` + comment `claimed by agent-B/<id> — branch <name>`.
  If an issue already has an assignee or is In Progress, STOP — it is not available.
- No network in tests (C-13.5); recorded fixtures only; never a live exchange; never real credentials.
- Format gate is `ruff format --check` (CI runs ruff-format, not black); plus ruff check, mypy --strict,
  lint-imports, package-scoped pytest, and the 33 `.semgrep/cv-*.yml` rules run INDIVIDUALLY on changed
  files (whole-dir runs error and lie about exit codes).
- Commit via bash + `-F` from a BOM-free file; subject ≤100 chars; every body line ≤100 chars; trailer
  `Co-Authored-By: Claude <noreply@anthropic.com>`. Never --no-verify. If the pre-push hook rejects the
  branch prefix, push via a `tmp/<name>` branch with `--force-with-lease`.
- PR: body uses the template; `Closes #N` ONLY if this PR is the whole ticket (else `Refs #N`); labels
  added AFTER create (`gh pr edit --add-label`) because GraphQL rejects labels on create; end the body
  with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`; >400 LOC needs a why-note.
- Post comments with UTF-8 stdin: `Get-Content -Raw -Encoding UTF8 f | gh issue comment N -R CandleViewer/CandleViewer --body-file -`.
- Fetch PR heads with `git fetch origin +refs/pull/N/head:refs/remotes/pr/N`.
- Keep file writes chunked (several small edits; nothing >~150 lines per call).
- Remove your worktree and local branch when done; never kill processes you did not start.
- Report concisely: what you did, what you did NOT run, exact test counts, PR URL, deviations.
```

---

## 7. QA closure procedure (exact)

1. Merge the PR(s). If a `Closes #N` auto-closed a QA-gated ticket, `gh issue reopen N --comment "…C-10.4…"`
   and `python docs/plan/backlog/_tools/set_status.py <KEY> "In Test" "<note>"`.
2. Launch ONE `test-writer` QA agent (independent of the PR's tests) with: the issue, PR bodies, the
   `done_gate.py` grammar, a throwaway black-box script, package-scoped pytest counts, and the posting
   rules. It posts `Recorded demo (C-10.4 black-box run on main <sha>)` then
   `QA verification (C-10.4) — VERDICT: PASS` with an AC→evidence table mapping EVERY DoD line
   (≥2 shared words or `DoD#n`; `n/a` for UI lines; numbers for measurement lines; `deferred → #N`).
3. From the main checkout root: `PYTHONUTF8=1 python docs/plan/backlog/_tools/qa_close.py <KEY> <issue#>`.
   It runs `done_gate.py`; on PASS it moves the board to Done and closes the issue. On FAIL it names the
   missing evidence kind — fix the comment wording or the real gap; never fake evidence.
4. Security-labelled tickets need the latest `Security review … VERDICT: APPROVE` on every linked PR
   (merged `Refs` PRs link since #2070). Design-labelled tickets need the owner — park them.

---

## 8. What Agent A is doing while you work (so you can predict collisions)

- #2068 fix round → merge (klines boundary + tape-lookup refusal) — touches `bars/`, `ingestion/kline_*`,
  `storage/retention/kline_boundary.py`, `app.py` (bars wiring block only).
- #398 E12-T05 `/market/klines` + `/market/bars` route (absorbing the missing route per item R default).
- E12/E22/E13 follow-ups: #2055, #2067, #2071, #2066 (tooling), #2057 cleanup.
- Owner-gated items parked on #1778: R (bars migration 0004), S (ADR-0034), T (E06-T01 matrix), plus the
  design queue. Agent A posts ★ defaults; the owner's reply unblocks both of us.

If you need something in Agent A's lane, comment on the owning ticket and move to your next item — do not
wait and do not fork a parallel implementation (C-6.1 / `.claude/rules/70-multi-agent.md` §3).

---

## 9. Numbers at handoff (2026-10-08 13:30)

Board: 211 Done · 5 In Test · 8 Ready · 1147 Backlog · 8 Blocked. Agent A this run: 92 PRs merged,
27 tickets Done. Dependency-unblocked now: 50 (38 design/owner, 12 agent-executable). Reachable without
any design/owner ticket: 75 — this document hands you ~50 of them. The remaining ~25 are E47/E49 GA sweeps
and E12 QA packs that depend on screens not yet built.
