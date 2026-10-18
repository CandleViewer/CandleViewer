# Worker-agent handoff — CandleViewer parallel-development brief

> Written 2026-10-13 by the main-orchestrator (persona Atlas, RelayRoom part `main-orchestrator`) for
> any new worker agent. **Volatile state (lanes, PR numbers, counts) lives on GitHub #1778 and in the
> RelayRoom roster — this file is the stable part; §2 and §4 are snapshots dated at the top of each.** Read this top to bottom before touching anything. Everything here is a
> **pointer**: the authoritative rules live in `CONSTITUTION.md`, `AGENTS.md`, `CLAUDE.md` and
> `docs/plan/*`. Where this file and those disagree, those win.

## 0. Thirty-second version

- CandleViewer is a private, self-hosted trading terminal (React + WebGL2 chart engine + Electron
  shell; Python 3.12 FastAPI modular monolith; Bybit v5 USDT-perps only). **It moves real money.**
- Work is tracked as GitHub issues mirrored in `docs/plan/backlog/E*.json`, on GitHub Project #10
  ("the board"). Three AI agents now work it in parallel; the owner is away for ~3 days.
- **Your lane is assigned by the orchestrator over RelayRoom** (your hello thread) and reserved by
  comment on each issue; §4 shows the shape of a lane. Only touch the tickets and paths you were given.
  Collisions are the #1 risk of adding agents.
- **Coordination channel is GitHub issue #1778** (section 5). Post there before claiming anything
  outside your lane, and read it at the start of every session.
- Every PR needs **two independent agent reviews** (`code-reviewer` + `security-reviewer` on
  security paths), green CI, and then the **owner merges** `security-review`-labelled PRs. You never
  merge your own PR, never approve a design PR, never mark a ticket Done.

## 0a. Who is who (as of 2026-10-15)

| RelayRoom part      | Persona | Laptop        | Historical GitHub name |
| ------------------- | ------- | ------------- | ---------------------- |
| `main-orchestrator` | Atlas   | l01 (Windows) | Agent A                |
| `hcl-worker-1`      | Forge   | HCL (WSL)     | Agent B                |
| `hpe-worker-1`      | Beacon  | HPE (WSL)     | Agent C                |
| `hpe-worker-2`      | Comet   | HPE (WSL)     | —                      |
| `hcl-worker-2`      | Anvil   | HCL (WSL)     | —                      |

Sign GitHub comments and PR records with your **RelayRoom part name**. Coordination happens on
RelayRoom (hub `https://relay.candleviewer.com`, project `candleviewer`, alias `candleviewer-relayroom`);
GitHub #1778 remains the durable ledger for owner decisions and lane announcements.

## 1. Project background

| Topic                                                                                                                               | Where to read                                                                                                     |
| ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| What the product is, hard boundaries (no mobile, no other exchange, **no withdrawals**)                                             | `CLAUDE.md` §1, `CONSTITUTION.md` C-1.x                                                                           |
| Non-negotiables (trunk-based, conventional commits, native stop-loss invariant, append-only audit, no secrets, no network in tests) | `CLAUDE.md` §5, `CONSTITUTION.md` §2                                                                              |
| Architecture (modular monolith, module dependency table, hot-path rules)                                                            | `docs/plan/20-architecture.md`, CONSTITUTION §3                                                                   |
| Storage tiers (QuestDB hot / Parquet+DuckDB cold / Postgres relational)                                                             | `docs/plan/21-database-schema.md`, ADR-0003                                                                       |
| REST contract (contract-first; regenerate `packages/protocol`, never hand-edit)                                                     | `docs/plan/22-api-openapi.yaml`                                                                                   |
| WS protocol                                                                                                                         | `docs/plan/23-ws-protocol.md`                                                                                     |
| Internal schemas / domain events                                                                                                    | `docs/plan/24-internal-schemas.md`                                                                                |
| Statecharts (B1–B20; only via `cv.statechart.factory`; never on hot paths)                                                          | `docs/plan/28-statechart-catalogue.md`, ADR-0016, `.claude/rules/21-statecharts.md`                               |
| Testing strategy (pyramid, fixtures only, determinism, coverage floors ≥85% backend)                                                | `docs/plan/03-testing-strategy.md`, `.claude/rules/40-testing.md`                                                 |
| Security programme (STRIDE per epic, SR-nnn requirements, role matrix §13)                                                          | `docs/plan/04-security-program.md`, `.claude/rules/50-security.md`                                                |
| Definition of Ready / Done                                                                                                          | `docs/plan/02-definition-of-ready-done.md` (C-11.1 / C-11.2)                                                      |
| Branching, PR template, review rules                                                                                                | `docs/plan/01-sdlc-and-branching.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.claude/rules/10-branching-and-prs.md` |
| Multi-agent protocol                                                                                                                | `.claude/rules/70-multi-agent.md`, `CLAUDE.md` §10                                                                |

Sprint calendar: 1-week sprints Fri→Thu, Sprint 01 = 2026-09-25, GA cut 2027-03-25. Today is
Sprint 03. Many later-sprint tickets are already unblocked; sprint labels are placement, not a gate.

## 2. Board snapshot (2026-10-13 — historical; run `board_snapshot.py` for the live numbers)

| Column      | Count                     | Notes                                                                                                                                 |
| ----------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Done        | 226                       |                                                                                                                                       |
| In Test     | 18                        | All have an independent QA verdict (Agent B, 2026-10-12). 16 FAIL with listed gaps; fix PRs are in flight (Agent A/B). **Not yours.** |
| In Review   | 1 + many draft design PRs | Design PRs wait for the owner.                                                                                                        |
| In Progress | ~25                       | Claimed by A or B (see §4.3).                                                                                                         |
| Ready       | ~68                       | Agent A moved every ticket whose `blocked_by` are all ≥Ready. **Your pick-list is §4.1.**                                             |
| Blocked     | 3                         | #230, #877, #1016 — real blockers, leave them.                                                                                        |
| Backlog     | ~1060                     | Blocked on something still in Backlog.                                                                                                |

Open PR count is ~45. Several are stacks (E27-T02 10 PRs, E26-T02 8 PRs, #2144 3 PRs). The owner
merges `security-review` PRs personally; the orchestrator (Agent B's session, per #1778
2026-10-12) may approve/merge other code PRs after two agent reviews.

## 3. Environment and access

### 3.1 Machine setup (once)

1. Clone `https://github.com/basiltt/CandleViewer` (default branch `main`); `gh auth login` with the
   owner's account. All agents commit as `basiltt`, so provenance lives in text: **sign every issue
   comment and PR body "<your RelayRoom part> (session <id>)"** and use the commit trailer
   `Co-Authored-By: Claude <noreply@anthropic.com>` (the harness adds it).
2. Backend: `cd services/api && uv sync --frozen --all-groups` (Python 3.12 via `uv`).
   Frontend/hooks: `pnpm install` at the repo root (installs commitlint, lint-staged, branch-name
   hook — `test/` prefixes are rejected; use `feat fix chore design spike hotfix docs`).
3. Learn "green" on `main` first. Commands are owned by `AGENTS.md` §4 — never invent one.
   Backend gate: `ruff check . && ruff format --check . && black --check . && mypy --strict . &&
lint-imports && pytest -p no:cacheprovider -m "not exchange_smoke and not (chaos and integration)
and not roundtrip and not fuzz and not harness and not perf and not flaky"`. JS/TS: `pnpm verify`.
   Semgrep custom rules: run each `.semgrep/cv-*.yml` as its own `--config` on your touched files;
   0 findings, and **never add `nosemgrep`/`noqa`/`type: ignore` without a coded, justified reason**.
4. Known quirks (both other laptops hit all of these):
   - **Never use `/tmp` for worktrees** (7.7 GB tmpfs, fills). Use `%TEMP%\wt-<ticket>` or
     `~/wt/<ticket>`; one `git worktree` per ticket; never code in the main checkout.
   - Something deletes 0-byte files under `%TEMP%` (venv `py.typed`, a commitlint template). If
     mypy or hooks suddenly fail: `uv sync --reinstall` / `pnpm install`. Repo files are unaffected.
   - On Windows `secrets/_kek.py` imports the Unix-only `resource` module (since #2245/#2246), so a
     few `create_app()` tests only run in CI. State it in the PR; do not skip or xfail them.
   - `gh` is slow under load: wrap calls in `timeout 120`. Set `PYTHONUTF8=1` for backlog tools.
   - Full backend unit suite ≈17 min on an i7-8550U. Run only the directories you touched; let CI
     run the rest. Never more than two heavy pytest/mypy jobs at once on a 16 GB machine.
   - The `pr-metadata` CI gate is new and strict: title scope must be in `commitlint.config.cjs`
     scope-enum (`docs(docs)`, not `docs(security)`); body needs `Closes #N` **or** `Refs #N` plus a
     separate `Partial: <reason>` line; >400 LOC needs a "Why this can't be split" note; >800 or
     any change to `.github/CODEOWNERS` needs `large-pr-approved` (ask on #1778). A `Partial:` PR
     closes nothing: it carries `Refs #N` only, with no close/fix/resolve keyword before an issue
     reference anywhere in the body (prose, checklists, code spans and comments included), or
     PR-BODY-003 fails it (#2964; owner: `tools/ci/check_pr_metadata.py`). The PR's GraphQL
     `closingIssuesReferences` must be empty too (`gh pr view <N> --json closingIssuesReferences`,
     gh >= 2.72; older gh: `gh api graphql` with `CLOSING_QUERY` from the owner file), which also
     catches Development-sidebar links. Write "the closing line is on slice N" instead;
     the closing line lives on the last slice only. Keep commit messages free of a closing keyword
     plus issue reference too: squash merges keep them, and the gate does not check them.

### 3.2 Board tools (`docs/plan/backlog/_tools/`, run with `PYTHONUTF8=1`)

- `board_snapshot.py` → refreshes `_board_snapshot.json` (status, sprint, assignees per issue).
- `set_status.py <KEY> "<Status>" ["comment"]` → sets Status, optionally comments. You may set
  **In Progress / In Review / Blocked / Ready**. **Never Done** (QA + owner only, C-10.4).
- `validate.py` → mandatory after any `E*.json` edit (edit JSON only via Python load→dump).
- `all-tickets.json` → every ticket body with `blocked_by`, `estimate`, `kind`, `sprint`.

### 3.3 Design tooling — not yours

Design tickets (`E*-D*`) are built in Penpot through an MCP plugin that needs a browser tab kept
awake on the owner's machine; it has flapped all day. **Workers do not take design tickets**
unless the orchestrator hands some over. Rules, if that happens: `docs/design/README.md`.

## 4. Your lane

### 4.1 Example lane (the original 2026-10-13 hpe-worker-1 assignment; **your** lane arrives on RelayRoom)

These were Ready, unassigned and non-overlapping at the time; several are now done (#402, #838) or in flight. Treat the table as the _shape_ of a lane, not a pick-list.
Claim: `gh issue edit N --add-assignee basiltt` then
`set_status.py <KEY> "In Progress" "claimed by <your-part> (session <id>) — branch <name>"`.

| #    | Key     | Pts | What                                                             | Repo paths (yours exclusively)                                                                                                                   | Notes                                                                                                                                                                                                                                                |
| ---- | ------- | --- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #357 | E14-T01 | 5   | `drawings` table migration + owner-scoped `/drawings` REST       | ONE new Alembic revision; `candleviewer/drawings/**`; `api/drawings.py`; `22-api-openapi.yaml` drawings paths; `packages/protocol` (regenerated) | Contract-first (C-6.1): OpenAPI + generated types as a small PR, implementation second. Single-head rule: `gh pr list --search "migrations/versions"` first; re-parent if one landed. Forbidden-role + cross-account (IDOR) tests mandatory.         |
| #402 | E15-T01 | 5   | `workspaces/layouts/layout_panes` migration + `/workspaces` REST | same pattern; `candleviewer/workspaces/**`; `api/workspaces.py`                                                                                  | **Migration PR only after #357's migration merges** (one in flight at a time, C-5.3). Do its contract PR meanwhile.                                                                                                                                  |
| #889 | E42-T02 | 5   | Audit query, hash-chain verify, signed export endpoints          | `candleviewer/audit/query*.py` (new), `api/audit*.py`, OpenAPI audit paths                                                                       | **`security-review` label mandatory.** Read paths only — audit is append-only (C-3.3, C-5.7). Do NOT touch `audit/writer.py` or `audit/actions.py` (both now merged). Export signing uses the secrets module only via the interfaces C-3.2 allows.   |
| #838 | E27-X01 | 3   | STRIDE threat model: accounts, sub-accounts, API-key vault       | `docs/security/threat-models/E27-accounts.md`; `04-security-program.md` (index row + Area block); `32-risk-register.md`                          | Docs only. Copy the format of `E17-ws-gateway.md` / `E12-bars.md` (both just passed QA). Run `python scripts/check_rule_refs.py` and `scripts/check_threat_model_ticket_map.py` (GOV-008). Status stays **Draft** until the owner accepts residuals. |
| #409 | E17-Q01 | 5   | WS protocol conformance suite + black-box test plan              | `services/api/tests/contract/ws/**`; `qa/plans/e17-ws-conformance.md`                                                                            | Tests only, every frame validated against `23-ws-protocol.md` §13 schemas. Good filler while waiting on migrations.                                                                                                                                  |
| #414 | E17-T08 | 3   | Statechart-backed WS topic `machines.{entity}.state`             | `candleviewer/ws/topics_machines.py` (new); `statechart/gateway.py` read-side; `23-ws-protocol.md` new topic section                             | #2265/#2263 merged; **only after #2318 merges** (it owns `ws/permissions.py`, `ws/gateway.py`); the ws/ lane is now hpe-worker-2's. Contract PR for 23-ws-protocol first. Never import the statechart library outside `statechart/factory.py`.       |
| #579 | E50-C17 | 1   | Upstream liaison chore (xstate-statemachine)                     | `docs/research/xstate/**` note                                                                                                                   | Tiny; filler.                                                                                                                                                                                                                                        |

**Do not take anything reserved for another part** (check the issue comments). Historically: E12-T06 #399 / E17-T03 (hpe-worker-2), E26-T01 #624 and E16-T07/E26-T02
(main-orchestrator recorder/replay lane), E47-_/E49-_ (not actually startable — target screens don't
exist), anything in **In Test**, anything with an assignee.

### 4.2 When the list is exhausted

Post on RelayRoom to `main-orchestrator`: "<part>: lane empty, proposing <keys>" and wait ≤1 h for an ack. If none,
take only tickets whose **epic** no one has touched in 48 h (`gh issue list --search "<EPIC>
in:title" --state open --json assignees,updatedAt`). Next-wave candidates (Backlog, blockers all
≥Ready) by epic: E27 (3), E42 (1), E14 (1), E15 (1), E36 (1).

### 4.3 Other agents' lanes (do not enter)

- **Live lane map:** the latest "Lanes as of …" comment on GitHub #1778 and the RelayRoom roster. Do not rely on this file for who owns what today.

- **Shared hotspots — never edit without a #1778 ack:** `22-api-openapi.yaml` outside your own
  paths, `23-ws-protocol.md`, `packages/protocol`, Alembic `versions/`, `machine_hashes.lock`,
  `audit/actions.py`, `CONSTITUTION.md`,
  `AGENTS.md`, `.github/workflows/**`, `.github/CODEOWNERS`.

## 5. Communication protocol between agents

**Channel:** GitHub issue **#1778** ("agent coordination / owner decisions"). It already holds the
A↔B exchange and every owner decision. Why an issue and not a file: it is visible to all three
laptops without a pull, it is time-stamped, the owner reads it, and nothing in the repo churns.

Rules:

1. **Start of every session:** read the last ~10 comments on #1778 and your lane's issues.
2. **Before claiming anything outside §4.1**, post `<part> → main-orchestrator: proposing <keys>, paths <…>`
   and wait for an ack (≤1 h). Silence after 1 h = proceed, say so.
3. **Before editing a shared hotspot** (§4.3 list), post what and why; wait for an ack.
4. **On finishing a PR** that another lane must rebase onto (contract, migration, generated
   types), post `<part> → all: #<pr> merged/ready — <file> changed; rebase if you touch it`.
5. **On a blocker:** use the `BLOCKER:` format from `.claude/rules/70-multi-agent.md` §5 on the
   ticket, set Status Blocked, and link it from #1778 in one line.
6. **Addressing:** prefix every comment `<part> → <part>` / `→ all` / `→ owner`.
   One topic per comment; ≤15 lines. Decisions you need from the owner go under a bold
   `**Owner decision needed:**` line so they can be found when the owner returns.
7. **Ticket-level coordination** (e.g. "I'm leaving your purge row alone in matrix.yaml") goes on
   the _ticket or PR_, not on #1778 — keep #1778 for cross-lane and owner items only.
8. **Never** message another agent to do something your own permissions/gates blocked; route it to
   the owner instead (no permission laundering).

Standing owner delegations recorded on #1778 (read the originals before relying on them):

- 2026-10-09 "AA": agents may set Status merged→In Test and In Test→Done **only after an
  independent QA-agent sign-off** (author never signs its own ticket).
- 2026-10-12: PR approval delegated to the orchestrator **after** two independent agent reviews
  on the final head; `security-review` PR **merges** and `large-pr-approved` labels still need the
  owner personally (ruling of 2026-10-13); repo settings, secrets and constitution amendments are
  owner-only.

## 6. Workflow for every ticket (the only acceptable loop)

1. **Read** `CLAUDE.md`, `AGENTS.md`, the `.claude/rules/*` that match your paths, then the ticket
   in full (`gh issue view N` — Context, Scope, Out of scope, Gherkin AC, Technical notes, Test
   plan, Security/A11y/Observability notes, DoD, **Agent execution brief**) and every doc it links.
2. **Definition of Ready check** (C-11.1). Missing AC, contract or design sign-off → comment the gap
   on the issue, set Blocked, pick the next ticket. Do not guess scope.
3. **Claim** (§4.1 command). **Overlap check:** `gh pr list --state open --search "<path>"`.
4. **Branch** from fresh `origin/main` into a new worktree: `<type>/<epic-key>-<slug>` (lowercase,
   ≤60 chars). Rebase, never merge main in; `--force-with-lease` only on your own branch.
5. **Contract first** if REST/WS/DB/statechart surface changes: tiny PR with the schema/migration
   stub + generated types + a fake; consumers come after (C-6.1). One migration per PR (C-5.3).
6. **Tests first** from the Gherkin AC at the right pyramid level (C-13.2–13.4): unit for pure
   logic (hypothesis for invariants), `@pytest.mark.integration` for DB/process boundaries,
   recorded fixtures only, fake clocks, no sleeps, no network. Every endpoint: forbidden-role and
   cross-account (IDOR) cases. Every bug fix: a regression test that fails without the fix.
7. **Implement the minimum**; read two neighbouring files and copy their patterns. Decimal for
   money/price/qty; tz-aware UTC; pydantic v2 `extra="forbid"` at the edge; typed domain errors;
   bounded queues; every external await under a timeout; no `Any` in public signatures.
8. **Run the gate** locally on touched dirs (ruff, format, black, mypy --strict, lint-imports,
   pytest for your dirs, semgrep cv-*). **Mutation check**: break the logic once and confirm a
   test fails; say which mutant in the PR. Never open an unrun PR.
9. **Commit** conventionally (`type(scope): summary`, scope from the allowed list, ≤100-char
   lines, hooks on — never `--no-verify`).
10. **PR** via `.github/PULL_REQUEST_TEMPLATE.md`, fully filled: AC → evidence table, test
    output, `Closes #N` (or `Refs #N` + `Partial:`), chaos scenario numbers if you touch reconnect/
    OMS/recorder/storage/backpressure, labels (`type/*`, `area/*`, `priority/*`, `security-review`
    where applicable), why-not-split note if >400 LOC. Set Status **In Review**.
11. **Reviews:** request two independent agent reviews yourself (Claude Code `Agent` tool, `model`
    set explicitly — owner rule 2026-10-15: **`fable`** for `security-reviewer` on auth/audit/secrets/ws/OMS
    paths and for any PR >400 LOC; **`sonnet`** for `code-reviewer` and for docs/test-only PRs). Fix
    findings on the same branch; re-run the reviewer on the final head; **record both verdicts as a
    PR comment** ("Review record: code-reviewer APPROVE …; security-reviewer APPROVE …").
12. **Merge:** never your own. Post on RelayRoom `<part> → main-orchestrator: ready #<pr> at <sha> (2 APPROVEs, green)`; non-security-review PRs are merged by the orchestrator, security-review ones by the owner.
    After squash-merge the ticket is **In Test**; an independent QA agent (not you) moves it Done.
13. **Hand-off if you stop:** push the WIP branch, comment what is done / left / next step on the
    issue, unassign, Status back to Ready.

### 6.1 NEVER (full list `AGENTS.md` §8 — violations are incidents)

force-push or push `main` · edit a merged migration · touch `secrets/`, `auth/`, `audit/`, `infra/`,
CI workflows or dependency manifests without `security-review` · skip or weaken any check
(`--no-verify`, bare `noqa`/`type: ignore`/`eslint-disable`, `.skip`/`.only`, lowering coverage,
moving a bench baseline) · widen scope · handle real credentials or `.env` values · call a live
exchange from tests/CI/dev · bypass a safety invariant (native stop-loss, RBAC/risk server-side,
audit write-ahead, withdrawal check, rate reserve, demo/live isolation) · approve or merge a design
PR or any PR you authored · mark a ticket Done · invent UI not in a signed-off design · implement
a `retired` ticket · call the statechart library outside `cv.statechart.factory`.

### 6.2 Quality bar the other agents are held to (so reviews pass first time)

- Coverage ≥85% line / ≥75% branch for `services/api/**` on touched packages; ≥95% + mutation
  evidence for OMS, risk, rules, secrets, book.
- Reviewers reject: random seeds in tests, test-to-test imports (shared fakes go in `conftest.py`
  or a `_fakes.py`), duplicated fixtures, magic numbers where a named constant exists, unregistered
  audit action strings, unshielded audit writes on unauthenticated paths, `float` for price/qty,
  Bybit vocabulary outside `exchange/bybit/`, undocumented fail-open behaviour.
- Honest reporting beats green: if a test only runs in CI, or a number is an estimate, say so in
  the PR under **Deviations**. Reviewers have been catching PR bodies that overstate test scope.

## 7. Current open items you may bump into

- **Penpot bridge flapping** → design lane paused; irrelevant to your tickets.
- **Metrics catalogue golden** (#2743) is one sorted row per metric, no longer a single-writer hash: if
  your PR adds a metric, rewrite `services/api/tests/unit/observability/golden/metrics_catalogue.jsonl`
  with `CV_REGEN_GOLDEN=1` (never by hand). `packages/protocol`'s hash manifest is no longer committed.
- **`pr-metadata` gate** rejects `test/` branch names and `docs(security)` scope; see §3.1(4).
- **Open owner decisions** (do not resolve yourself): F-4 WS auth-frame replay (#298), E16-T07 95%
  semantics (recorded on #491 by the orchestrator — follow it), password-policy
  contract #2330, Penpot tab.
- **Private security advisory** GHSA-wxvj-xh4h-mpg2 (mid-handshake WS revocation gap) — never
  discuss its content on public issues (C-12.13, `SECURITY.md`).

## 8. First hour checklist for a new worker

- [ ] Read `CONSTITUTION.md` Appendix A, `AGENTS.md` §0–§9, `CLAUDE.md`, `.claude/rules/*`.
- [ ] Read the last 10 comments on #1778; send a RelayRoom `[HELLO]` to `main-orchestrator` + `human`
      (part, persona, run8, folder, `whoami`); wait for the lane reply in that thread.
- [ ] Clone, `uv sync`, `pnpm install`, run the backend gate on `main` once.
- [ ] `PYTHONUTF8=1 python docs/plan/backlog/_tools/board_snapshot.py`.
- [ ] Claim your first assigned ticket; read it in full; check migrations single-head if it adds one; open the **contract** PR first.
