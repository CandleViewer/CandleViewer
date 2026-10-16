<!--
  CandleViewer pull request.
  This checklist maps 1:1 to the gates in CONSTITUTION.md. Do not delete items —
  mark them [x] (done) or [~] (N/A, with a one-line reason). Rule ids like C-4.7 are
  Constitution rules; agents: see AGENTS.md §7.

  Gate-heading contract (docs/design/E01/E01-D01.md §5, parsed by E01-T07 automation):
  `### Acceptance criteria` and `### Test plan` are always required (never delete, may be
  "N/A — <reason>" only where §5 allows it). `### QA sign-off`, `### Security review` and
  `### a11y evidence` are required only when their trigger (Kind/label/path) applies; they
  are actor-attributed sections (a `@handle` or an explicit `N/A`/`QA capacity deviation`
  token) — never a checkbox the author self-ticks.
-->

## Summary

<!-- What changed and WHY. Two to five sentences. Link the plan doc / ADR this implements. -->

## Related issues

Ticket key: <!-- e.g. EP-OMS-014, from the ticket JSON `key` field / issue title prefix -->

Closes #
<!-- Exactly one primary issue (C-4.6/C-4.7). Reference related issues below if needed. -->
<!-- A stacked slice writes `Refs #N` plus a `Partial: <reason>` line and must close nothing: no
     close/fix/resolve + issue ref anywhere in the body (checklists included) or in its commit
     messages (squash merges keep them, and they are not checked), no issue linked in the
     Development sidebar; write "the closing line is on slice N" instead (PR-BODY-003). -->

Related:

<!-- Only fill in the field below if this diff exceeds 400 changed LOC (excluding
     generated/lockfiles/snapshots, C-4.8). Delete it otherwise. -->

### Why this can't be split

<!-- One paragraph: why the work cannot land as smaller, independently mergeable PRs. -->

## Ticket brief checklist

<!-- From the ticket's `## Agent execution brief` (docs/plan/backlog/E*.json / AGENTS.md §3a). -->

- [ ] I read `## Agent execution brief` (or `## Agent guidance` for an Epic) before writing code
- [ ] Repo paths I touched match "Repo paths" in the brief; nothing outside it changed
- [ ] "Interfaces you must not break" are unchanged, or changed via the contract-first process (§6)
- [ ] I ran every command listed under "Commands" in the brief, not a substitute
- [ ] "Done means" criteria are all met; "Do NOT" items were not done
- [ ] `blocked_by` tickets were `Done` (or contract-merged) before I started (AGENTS.md §3b)

## Type of change

- [ ] `feat` — new capability
- [ ] `fix` — defect repair
- [ ] `perf` — performance
- [ ] `refactor` — no behaviour change
- [ ] `docs` — documentation / ADR
- [ ] `test` — tests only
- [ ] `build` / `ci` / `chore` — tooling, deps, pipeline
- [ ] `security` — security fix or hardening
- [ ] **Breaking change** (`!` in the commit + `BREAKING CHANGE:` footer + version/deprecation plan, §6)

### Acceptance criteria

<!-- The AC→evidence table: each acceptance criterion from the ticket, and how it was verified
     (test name / screenshot / bench output). Required on every PR — never delete this heading. -->

### Test plan

<!-- Commands run and their results; which pyramid levels; what a reviewer should re-run.
     Attach evidence: test output, screenshots/recording for UI, benchmark deltas for engine/hot paths,
     alembic up/down output for migrations. "It should work" is not testing (AGENTS.md §8.14).
     For a docs/chore PR with no user-facing effect, this section may instead read exactly:
     "N/A — no user-facing effect" (literal N/A token, not "n/a"/"NA"). -->

---

## Constitution gates

### Process (§4, §10)

- [ ] One issue → one branch → one PR; description contains `Closes #N` (C-4.6, C-4.7)
- [ ] Branch matches `<type>/<epic-key>-<slug>`; commits are Conventional with an allowed scope (C-4.4, C-4.10)
- [ ] Branch rebased on `main` (no merge commits); will be **squash**-merged (C-4.12)
- [ ] Diff ≤ 400 changed LOC, or `large-pr-approved` label with written justification (C-4.8)
- [ ] No unrelated changes / no scope creep (C-4.9, C-1.4)
- [ ] Ticket satisfied DoR before work started (C-11.1); DoD items below are complete (C-11.2)
- [ ] Feature flag added (default **off**) with a removal ticket, or N/A (C-4.13)

### Architecture & invariants (§2, §3, §6, §7)

- [ ] Module boundaries respected; no cross-module internal imports; `architecture` check green (C-2.1, §3)
- [ ] No Bybit-specific code outside `services/api/exchange/bybit/` (C-2.2)
- [ ] Contract changed **first** (OpenAPI / WS protocol) and `packages/protocol` regenerated, not hand-edited (C-6.1, C-6.6)
- [ ] Contract tests (provider + consumer) updated and green (C-6.2); versioning/deprecation policy followed (C-6.3, C-6.4)
- [ ] Shared-package change followed the protocol: announced, additive, CODEOWNER reviewed (§7)
- [ ] **Every position-opening order path still attaches a native exchange SL** (C-2.6) — or N/A
- [ ] Snapshot+delta semantics, sequence numbers and bounded queues/backpressure preserved (C-2.5, C-2.18)
- [ ] Heuristic signals labelled `(estimated)` in payload and UI (C-2.13); recorder-bounded history states handled (C-2.14)
- [ ] ADR added/updated for any architectural decision, using the MADR template (C-15.1) — or N/A
- [ ] No out-of-scope work: no mobile, other exchange/category, separate admin app, options/GEX, withdrawal, public exposure, third-party production chart lib (C-1.2)

### Statechart checklist — only if the `statechart` label is applied

<!-- Delete this section if the ticket/PR does not carry the `statechart` label. -->

- [ ] The lifecycle matches a contract in `docs/plan/28-statechart-catalogue.md` §Bn; states/events/guards/
      transitions were not invented ad hoc (C-2.19)
- [ ] Implemented via `cv.statechart.factory` using `xstate-statemachine==0.9.1` only — no bypass, no shim
      (C-2.22, ADR-0016)
- [ ] No hot-path logic lives in the machine: book deltas, bar building, footprint aggregation, per-tick
      rule evaluation, paper matching and rate-limit admission control stay outside it (C-2.20)
- [ ] The machine **records** state; it is not the enforcement point for a safety decision — the actual
      guard/flag lives elsewhere and is cited here (C-2.21)
- [ ] `docs/plan/28-statechart-catalogue.md` was regenerated from `machines/<name>.machine.json`, not
      hand-edited
- [ ] Machine JSON changes were reviewed by a CODEOWNER of `machines/`

### Data (§5)

- [ ] At most **one** migration in this PR; no previously applied migration was edited (C-5.3, C-5.4)
- [ ] Migration is additive and reversible; `downgrade()` tested; upgrade→downgrade→upgrade round-trip green (C-5.1, C-5.2, C-5.5)
- [ ] No long table locks; concurrent index creation / batched backfill where needed (C-5.6)
- [ ] Audit tables unchanged in their append-only guarantees (C-5.7, C-2.9)
- [ ] Retention / partitioning implications documented (C-5.8) — or N/A

### Security review

<!-- Gate heading — required when the `security` label applies, or a path from C-10.2's
     always-security list is touched (auth-rbac, oms-execution order paths, key storage,
     withdrawal, fan-out SL). Actor-attributed, not a checkbox:
     "Reviewed by @<security-handle>" or "N/A — <reason>". -->

- [ ] **No secrets** in code, tests, fixtures, logs, commits or this PR text (C-12.2)
- [ ] Keys still never leave `services/api/secrets/`; no endpoint returns a secret (C-2.7)
- [ ] No withdrawal/transfer/funding call introduced; key self-check untouched (C-2.8)
- [ ] Every order/auth/key/kill-switch action writes an append-only audit record (C-2.9)
- [ ] RBAC and risk caps enforced **server-side**; new endpoints deny by default and re-check ownership (C-2.12, C-12.4)
- [ ] Logging redaction verified for any new log line/field (C-12.6)
- [ ] Per-UID rate-limit budget respected; risk-critical reserve not consumed; WS subs ≤10 topics/request (C-12.7)
- [ ] Demo/live isolation preserved; no hotkey path to live (C-2.11)
- [ ] Dependencies: justified, allowlisted licence, lockfile updated, relevant required checks (CONSTITUTION §9) green (C-12.3)
- [ ] Threat-model impact considered; `security-review` label applied if C-10.2 paths are touched

### Testing (§13)

- [ ] Tests written at the correct pyramid level (unit / integration / e2e) per §13.2–13.4
- [ ] Coverage floors held: backend & engine ≥85%, frontend ≥80%; safety-critical modules ≥95% (C-13.1)
- [ ] Integration tests use **recorded Bybit fixtures**; **no live-exchange calls, no network in CI** (C-13.5)
- [ ] Bug fixes include a regression test that fails without the fix (C-13.7)
- [ ] Relevant chaos scenarios still pass / new ones added (C-13.6) — or N/A
- [ ] No `.only` / `.skip` / `xit` / sleeps / network / shared mutable state introduced (C-13.7 test-quality rules); no test left quarantined without a P1 ticket (C-9.3 flaky-test policy)

### a11y evidence

<!-- Gate heading — required when the `a11y` label applies, or `apps/web/**`,
     `packages/ui/**`, `packages/chart-engine/**` UI surfaces are touched. Actor-attributed:
     an axe-core CI run URL, or "N/A — no UI surface changed" (literal N/A token). -->

### Accessibility & performance (§14)

- [ ] WCAG 2.2 AA: keyboard reachable, visible focus, logical order, no traps (C-14.1)
- [ ] Contrast ≥4.5:1 text / ≥3:1 components; colour is not the only carrier of meaning
- [ ] `aria-live` politeness appropriate for high-frequency updates; `prefers-reduced-motion` respected
- [ ] Canvas/WebGL surfaces have the accessible alternative (data cursor / textual readout / table view)
- [ ] `axe` clean (zero serious/critical); manual screen-reader pass done for new screens
- [ ] Performance budgets met — authoritative values in CONSTITUTION §14.2, derivation in `docs/plan/06-performance-and-load-standard.md` (C-14.2)
- [ ] Engine benchmark check shows no material regression; benchmark output attached (CONSTITUTION §9) — or N/A
- [ ] Bundle-size budgets respected, no >5% regression (C-14.3)

### Observability & docs (§12.6, §15)

- [ ] Structured logs / metrics / alerts added or updated; no `print()` or `console.log` left behind
- [ ] Docs updated **in this PR**: plan docs, ADR, `AGENTS.md` (if commands/layout/standards changed), package README (C-15.2, C-15.4)
- [ ] `CHANGELOG.md` entry for user-visible change (C-15.6) — or N/A

### Reviews required (§10)

### QA sign-off

<!-- Gate heading — always required on Story/Bug PRs; required on Task/Chore only when
     labelled `qa`. Actor-attributed: "Signed off by @<handle>" or the literal string
     "QA capacity deviation" (per docs/plan/02-definition-of-ready-done.md §8). -->

- [ ] 2 approvals requested, at least 1 CODEOWNER of a touched directory (C-10.1)
- [ ] `security-review` label + `@CandleViewer/security` reviewer if C-10.2 paths touched
- [ ] `design-approved` from `@CandleViewer/design` and the design ticket is **Done** (any UI change, C-10.3)
- [ ] I understand merging moves this ticket to **In Test**; only QA or the owner sets **Done** (C-10.4)

---

## Risk & rollout

**Risk level:** <!-- low / medium / high -->
**Blast radius if wrong:** <!-- e.g. "order submission path — capital at risk" -->
**Rollback plan:** <!-- flag off / revert commit / redeploy previous tag; any data considerations -->
**Follow-ups:** <!-- issue numbers for deferred work, flag removal, deprecation removal -->

## Self-review

- [ ] I read my own diff line by line before requesting review (C-10.8)
- [ ] I ran the full local gate (task names: **AGENTS.md §4**, the single source of truth for commands) and it is green
- [ ] I did not disable, skip or weaken any required check (list of checks: **CONSTITUTION.md §9**, the single source of truth for check names) (AGENTS.md §8.4)
- [ ] Everything I claim above is something I actually verified (AGENTS.md §8.14)
- [ ] Every `C-x.y` I cite in this PR, its commits and its comments exists verbatim in `CONSTITUTION.md` (C-16.4) — I grepped, I did not guess
- [ ] I did not copy a single-source list (CI check names, command names, budget values) into another file; I linked instead (C-16.5)
- [ ] If I changed a script/task name, `AGENTS.md` §4 is updated in this same PR (C-15.4)
