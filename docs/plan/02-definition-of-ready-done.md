# 02 — Definition of Ready (DoR) & Definition of Done (DoD)

Status: locked. Companion to `01-sdlc-and-branching.md`. These checklists gate the **Ready** and **Done** Status transitions on the board for every Kind (Epic, Story, Task, Spike, Bug, Chore) and are enforced by the ticket owner, reviewers, and (for Done) QA/Security/CDO sign-off as applicable. A ticket may not move to a gated Status until every applicable checkbox for its Kind is true; "N/A" must be stated explicitly with a one-line reason, not silently skipped.

---

## 1. How to read this document

- Each Kind has a **DoR** (enter Ready) and **DoD** (enter Done) checklist.
- Checklists reference labels from `01-sdlc-and-branching.md` §5.2 (`design`, `ux-research`, `design-qa`, `handoff`, `security`, `a11y`, `perf`, `qa`) — a checklist item that's conditional on a label is marked **[if labelled X]**.
- "Coverage", "docs", "a11y", "perf", "security", "QA sign-off", "demo" are called out explicitly per the planning brief's non-negotiable SDLC requirements; they are not optional line items anywhere they apply.
- Universal rule for **all Kinds, all Statuses**: the ticket has a Kind, one `area/*` label, one `priority/*` label, and a clear one-paragraph description before it can leave Backlog into Refinement.

---

## 2. Epic

### 2.1 DoR (Backlog → Ready)

- [ ] Problem statement and business/user value written (why this Epic exists, who benefits).
- [ ] Scope boundaries stated: explicit "In scope" and "Out of scope" bullet lists (e.g., "Android: out of scope per owner decision 2026-09-14").
- [ ] Linked research: relevant `docs/research/digests/*.digest.md` and/or `docs/research/24-owner-decisions.md` items referenced.
- [ ] High-level architecture impact noted (which of `20-architecture.md` C4 components/`24-internal-schemas.md` domains are touched) — Architect has reviewed.
- [ ] STRIDE threat-model kickoff scheduled **[if labelled `security`, default-on for any Epic touching auth, keys, OMS, fan-out, or money movement]**.
- [ ] Design-ahead check: if the Epic has user-facing screens, a design Epic/tickets exist and are tracked ≥2 sprints ahead **[if labelled `design`]**.
- [ ] Initial rough sizing done (T-shirt or 13-point epic-level estimate) for roadmap placement in `30-release-roadmap.md`.
- [ ] Dependencies on other Epics recorded (`blocked_by`).
- [ ] Owner (a named engineer/lead, not just a team) assigned for decomposition.

### 2.2 DoD (→ Done)

- [ ] Every child Story/Task/Spike/Bug is Done (100% rollup) or explicitly descoped with a Won't/Later disposition recorded on this Epic.
- [ ] Acceptance criteria at the Epic level (the outcome, not each child's AC) verified end-to-end, not just per-child.
- [ ] Cross-cutting quality gates rolled up and green: coverage thresholds met across all touched packages (≥85% backend/engine, ≥80% frontend), no open P0/P1 bugs against this Epic's scope.
- [ ] Docs updated: relevant `docs/plan/2x-*` architecture/schema docs and `docs/plan/1x-*` product docs reflect final shipped behavior (not the original proposal) if they diverged during implementation.
- [ ] a11y: WCAG 2.2 AA verified for all new screens/components introduced by this Epic (axe-core CI green + at least one manual screen-reader pass) **[if the Epic has UI surface]**.
- [ ] perf: engine FPS / API+WS load numbers recorded against the budgets in `06-performance-and-load-standard.md` **[if labelled `perf`, default-on for chart-engine or high-throughput Epics]**.
- [ ] security: STRIDE model finalized, findings triaged (fixed or accepted-risk with Owner sign-off), sign-off comment from Security engineer **[if labelled `security`]**.
- [ ] QA sign-off: an Epic-level regression/exploratory pass executed and recorded, not just child-ticket QA.
- [ ] Demoed to Owner at a Sprint Review (or an ad hoc demo if the Epic spans past its target sprint) with explicit acceptance recorded in the ticket.
- [ ] Retro note: any process learnings captured as Chore/action-item tickets.

---

## 3. Story

### 3.1 DoR (Backlog → Ready)

- [ ] Written in INVEST form (Independent, Negotiable, Valuable, Estimable, Small ≤8pts, Testable).
- [ ] Acceptance criteria written in **Gherkin** (`Given/When/Then`), covering the happy path plus at least one edge case and one error/failure case.
- [ ] Design-ready **[if labelled `design` or the Story has any UI surface]**:
  - [ ] Linked design ticket/artifact (hi-fi screen(s) in the relevant `docs/plan/14-screens-catalogue.md` entry, or Figma link) is Status=Done.
  - [ ] Design has been Done for ≥2 sprints (design-ahead rule) OR an explicit Architect/CDO waiver is recorded with reason.
  - [ ] Component(s) used are in `15-component-catalogue.md`; any new component has a design-system entry, not an ad hoc one-off.
  - [ ] States enumerated (empty, loading, error, populated, edge-density e.g. extreme footprint density) per `14-screens-catalogue.md` conventions.
  - [ ] The design ticket carries its completed per-component handoff checklist (`16-design-system-brief.md` §11.4: Penpot link, Variants × States, keyboard table, accessible-name/role table, motion pair, density notes, essential-exceptions log), every line ticked or marked N/A with a reason, and this ticket links it.
- [ ] Security-ready **[if labelled `security`, default-on for Stories touching auth/RBAC, API keys, OMS/order placement, withdrawal settings, or any admin screen]**:
  - [ ] Threat considerations noted on the ticket (what could go wrong: injection, privilege escalation, key leakage, replay).
  - [ ] Data classification noted (does this touch secrets/PII/financial data).
- [ ] Test-ready:
  - [ ] Test plan outline present: which test pyramid layers apply (unit/contract/integration/E2E/perf/security/a11y) and what fixtures/mocks are needed (e.g., recorded Bybit fixture name).
  - [ ] For backend↔frontend Stories: the interface-first contract (`22-api-openapi.yaml` / `23-ws-protocol.md` delta) is already merged or is itself a prerequisite Task marked `blocked_by`.
- [ ] Dependencies (`blocked_by`) and sub-issue parent (Epic) set.
- [ ] Estimate agreed via planning poker (§11 of `01-sdlc-and-branching.md`), ≤8 points.
- [ ] Out-of-scope notes present if the Story is deliberately narrow (e.g., "single symbol only, multi-symbol is a follow-up Story").

### 3.2 DoD (→ Done)

- [ ] All Gherkin acceptance criteria pass, demonstrated by an automated test (unit/integration/E2E) referencing the specific scenario, or by an executed manual QA test-plan step for scenarios that cannot yet be automated (with a Task filed to automate it).
- [ ] Coverage: new/changed lines meet or exceed package threshold (≥85% backend/engine packages, ≥80% frontend) — CI coverage gate green, no regression to package baseline.
- [ ] Docs: any new endpoint/topic/schema reflected in `22-api-openapi.yaml`/`23-ws-protocol.md`/`24-internal-schemas.md`; any new screen/component reflected in `14-screens-catalogue.md`/`15-component-catalogue.md` if design changed during implementation; user-facing behavior changes noted in changelog fragment (see `07-release-and-prr.md` changelog automation).
- [ ] a11y **[if UI Story]**: axe-core CI check green on the touched screen(s); manual screen-reader spot-check performed for any new interactive control; keyboard-only path verified; focus order and visible focus states checked against `05-accessibility-standard.md`.
- [ ] perf **[if labelled `perf`, default-on for chart-engine/order-flow/high-frequency-update Stories]**: benchmark run recorded (engine fps at target bar/density count, or API/WS latency under k6/Locust profile) against `06-performance-and-load-standard.md` budget; no regression beyond the agreed threshold.
- [ ] security **[if labelled `security`]**: SAST/SCA/secrets-scan clean or findings triaged with accepted-risk sign-off; Security engineer review comment present; for anything touching keys/withdrawal/RBAC, a manual abuse-case check performed (e.g., attempt privilege escalation, attempt withdrawal toggle).
- [ ] design-qa **[if labelled `design-qa`, default-on for net-new UI Stories]**: built screen compared against design spec (spacing/tokens/type/color/states) by a designer or design-system-trained reviewer; discrepancies either fixed or filed as follow-up Bug with `priority/*` set.
- [ ] design handoff **[if the Story consumes a `CMP-*`/`SCR-*` design ticket]**: the built component matches the design ticket's handoff checklist (`16-design-system-brief.md` §11.4: Variants × States, keyboard and accessible-name/role tables, motion pair, density notes, logged essential exceptions); any design change after sign-off went through `16-design-system-brief.md` §11.5 (design ticket re-opened, this Story flagged for re-sync) rather than being absorbed silently.
- [ ] QA sign-off: black-box test plan executed by QA/SDET (or ticket owner if QA capacity constrained — recorded explicitly as a deviation), sign-off comment posted with pass/fail per scenario.
- [ ] Demo: Story demoed at Sprint Review (screen recording acceptable if live demo infeasible) OR explicitly marked "non-demoable infra-adjacent" with Architect concurrence.
- [ ] PR(s) implementing the Story are merged to `main` via the merge queue with required approvals and checks (per `01-sdlc-and-branching.md` §7).
- [ ] Feature flag state recorded: which flag gates this Story's behavior and its default-on/off state per environment.

---

## 4. Task

### 4.1 DoR (Backlog → Ready)

- [ ] Clear technical description of the change and why (what breaks/what's missing without it).
- [ ] Acceptance criteria stated (may be technical, e.g. "p99 ingestion latency < 50ms under 2x expected tick rate" rather than Gherkin, but must be objectively checkable).
- [ ] Interface-first check: if this Task defines or changes a contract consumed by another area (API/WS schema, internal event schema, exchange-adapter interface), the schema diff is drafted and reviewed **before** implementation starts, per `01-sdlc-and-branching.md` §10.
- [ ] Test plan outline (which layers: unit/contract/integration/perf) present.
- [ ] Security note **[if labelled `security`]**: any threat surface touched (e.g., "adds a new Postgres migration touching the `api_keys` table — must remain encrypted at rest").
- [ ] Dependencies/parent set, estimate ≤8 points agreed.

### 4.2 DoD (→ Done)

- [ ] Acceptance criteria objectively verified (test or measurement attached).
- [ ] Coverage threshold met for touched package.
- [ ] Docs updated (schema/architecture doc, code comments/docstrings, ADR if a design decision was made mid-implementation).
- [ ] a11y **[if the Task touches shared UI primitives/design-system code]**: axe-core CI green.
- [ ] design handoff **[if the Task is a `design`-labelled `CMP-*`/`SCR-*` ticket]**: the per-component handoff checklist (`16-design-system-brief.md` §11.4) is attached to the ticket and committed beside the spec, every line ticked or marked N/A with a reason; QA or the owner checks it before setting Done (`16-design-system-brief.md` §13.3 item 4).
- [ ] perf **[if labelled `perf`]**: benchmark recorded.
- [ ] security **[if labelled `security`]**: SAST/SCA clean or triaged, reviewed by Security engineer.
- [ ] QA sign-off **[if labelled `qa`, or if the Task is user-observable indirectly]**: verification recorded.
- [ ] Demo **[if the Task has an observable effect, e.g. a perf improvement or new internal tool]**: shown at Sprint Review or documented with before/after evidence; purely internal refactors with no observable behavior change may skip demo with a one-line note.
- [ ] PR merged via merge queue with required approvals/checks.

---

## 5. Spike

### 5.1 DoR (Backlog → Ready)

- [ ] Question(s) to be answered stated precisely (e.g., "Can the custom WebGL engine render footprint cells + DOM heatmap at 100ms cadence, 100k bars, 60fps in Electron, Chromium, and Tauri/WebView2?").
- [ ] Timebox stated (days), agreed with the Architect.
- [ ] Success/decision criteria stated up front (what result leads to which decision — e.g., "if <45fps in Tauri, Electron is chosen outright without a second spike").
- [ ] Links to relevant research (`docs/research/*`) that motivate the spike.
- [ ] Explicitly NOT expected to produce production-shippable code (stated on the ticket) unless the ticket says otherwise.

### 5.2 DoD (→ Done)

- [ ] Question(s) answered with recorded evidence (benchmark numbers, prototype repo/branch link, comparison table).
- [ ] Decision recorded as an ADR in `27-adrs/` (even if the decision is "defer, need more data" — that itself is an ADR entry).
- [ ] Follow-up tickets filed for whichever path was chosen (new Epics/Stories/Tasks), with the spike's findings linked as context so implementers don't re-derive them.
- [ ] Spike code either promoted (with normal Task/Story DoD then applying to the promoted portion) or explicitly marked throwaway and the branch left unmerged/archived.
- [ ] Findings presented at Sprint Review or Design/Security Review as relevant.
- [ ] `32-risk-register.md` updated if the spike surfaced a new risk or retired an existing one.

---

## 6. Bug

### 6.1 DoR (Backlog → Ready)

- [ ] Reproduction steps documented (exact steps, environment: dev/staging/prod, symbol/account context if relevant).
- [ ] Expected vs actual behavior stated.
- [ ] Severity/Priority assessed (`priority/p0-critical` for anything touching live money/safety invariants — e.g., missing native SL on fan-out — through `priority/p3-low`).
- [ ] Root cause hypothesis or "needs investigation" flag set; if investigation itself is nontrivial, a Spike is filed first.
- [ ] Regression test gap identified: which test layer should have caught this and didn't (informs the fix's test plan).
- [ ] Linked to the original Story/Epic if it's a regression of prior work.

### 6.2 DoD (→ Done)

- [ ] Root cause fixed (not just symptom-patched) or, if a symptom patch is deliberate/temporary, that's stated with a follow-up Task filed.
- [ ] Regression test added that would have caught this bug, at the appropriate pyramid layer, and it fails on the pre-fix code / passes on post-fix code.
- [ ] Coverage threshold maintained.
- [ ] Docs updated if the bug revealed a docs/spec inaccuracy.
- [ ] a11y **[if the bug is an a11y defect]**: axe-core/manual re-check confirms resolution.
- [ ] perf **[if the bug is a perf regression]**: benchmark re-run confirms budget restored.
- [ ] security **[if labelled `security`, default-on for any bug with a security/safety implication e.g. fan-out SL, key handling, RBAC bypass]**: Security engineer confirms the fix and reviews for related exposure elsewhere.
- [ ] QA sign-off: QA re-verifies the exact repro steps no longer reproduce, plus a quick regression sweep of adjacent functionality.
- [ ] For `priority/p0-critical`/`p1-high` bugs: incident note written (even if no formal outage) capturing detection-to-fix timeline, feeding `32-risk-register.md`.
- [ ] PR merged via merge queue (or hotfix flow if already Live-affecting, per `01-sdlc-and-branching.md` §8).

---

## 7. Chore

### 7.1 DoR (Backlog → Ready)

- [ ] What's changing and why is stated in one or two sentences (e.g., "bump Playwright 1.4x→1.5x to fix known flaky selector API").
- [ ] Risk assessed as low (if a "chore" turns out to have real behavior risk, it should be reclassified as a Task).
- [ ] Estimate ≤3 points agreed.

### 7.2 DoD (→ Done)

- [ ] Change applied, CI green (build/lint/typecheck/unit at minimum).
- [ ] Coverage not regressed.
- [ ] Docs updated if the chore changes a documented version/process (e.g., CONTRIBUTING.md tooling versions).
- [ ] Changelog fragment included if the chore is user-observable in any way (e.g., a dependency bump that changes runtime behavior, a perf-relevant library upgrade, a security patch) per the changelog automation rules in `07-release-and-prr.md` §3; purely internal/no-user-impact chores (tooling-only, CI config, doc typo fixes) may state "N/A — no user-facing effect" instead, but this must be stated explicitly, not silently omitted.
- [ ] security **[if labelled `security`, e.g. a dependency bump fixing a CVE]**: confirmed the CVE is actually resolved (SCA re-scan clean).
- [ ] No demo required by default; PR merged via merge queue.

---

## 8. Cross-Kind gating notes

- **QA sign-off** for Story/Bug is never silently skipped: if QA capacity is constrained, the ticket owner performs and records the black-box test plan themselves and states "QA capacity deviation" explicitly — Status still cannot reach Done without _some_ recorded sign-off.
- **Security sign-off**: any ticket touching `area/auth-rbac`, `area/oms-execution` order-placement paths, API-key storage/handling, withdrawal-permission settings, or the fan-out safety invariant (every fanned-out order carries a native exchange-side SL) is **always** treated as `security`-labelled for DoD purposes, whether or not the label was applied at creation — reviewers must add the label and block Done if missing.
- **a11y**: default-on (WCAG 2.2 AA) for any ticket that ships or changes a UI surface, including owner/admin screens — there is no "internal tool, a11y doesn't matter" exception, since owner/admin screens are inside the same web app and RBAC-gated, not absent of users with accessibility needs.
- **perf**: default-on for anything in `area/chart-engine`, `area/order-flow`, ingestion, WS fan-out paths, or DOM heatmap/footprint rendering, per the mandatory-spike findings in `24-owner-decisions.md`.
- **Demo**: every Story and Epic must be demoed; Tasks/Chores demo only when they have an observable effect; Spikes present findings instead of a demo. "Demo" always happens against **staging (demo)**, never directly against **prod (live)**, except for a live-enablement PRR walkthrough which is a controlled exception documented in `07-release-and-prr.md`.
