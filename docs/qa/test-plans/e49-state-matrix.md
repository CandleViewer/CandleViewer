# E49 State matrix: black-box test plan per panel and failure mode (slice A)

**Ticket:** E49-Q04 (#1362) · Task · Sprint 24 · labels `qa`, `type/chore`, `area/qa`, `priority/p2`, `a11y` · parent
E49 · blocked by E49-D02 (#1331). **Status: v0.1, slice A of four — a draft for the QA lead and E49-S05 (#1385);
BQ-0 … BQ-9 defaults built, ruling pending (comment 6642015197).** Branch `chore/e49-state-matrix`. This slice
carries `Refs #1362` and `Partial:`; only slice D may carry the closing line, and only once #1331 has closed.

**Base.** Every plan and repo cite is to `main` at `d5f2e0bc1`; the plan documents cited are byte-identical at the
BQ list's base `4c0821e73`. E49-D02 is cited as `D02` from PR #5877 at `bc0c643e9`, **if it merges as is**; it is
re-pinned at its merge.

**Honest scope.** Agent-authored. Nothing here has run: no cell is claimed passing, no harness exists yet, no
timing was measured. The plan writes the oracle E49-S05 builds against and E49-D05 (#1394) signs from; the
assertions encode E49-D02's spec, never the current build (T Dependencies). Findings are rows for their owners
(section 10), never edits to `14`, `15`, `16`, a spec or a merged test.

## Acceptance-criteria and DoD trace

States: **written** (this text specifies it), **pending** (a later slice builds it), **open** (people, the owner).

| Row    | Asks                                                                      | State   | Where                                                   |
| ------ | ------------------------------------------------------------------------- | ------- | ------------------------------------------------------- |
| AC 1   | AC "The matrix is complete and honest" — a row per panel, N/A with reason | written | §3 (149 rows, RN and NR rules); the audit's G-SCRSET    |
| AC 1b  | a catalogued panel missing from the matrix fails the self-check           | pending | §8 self-check (slice A's data push); the audit now      |
| AC 2   | AC "Every state can be driven deterministically" — within 5 s             | pending | §7 harness (slice B); SA-X-6                            |
| AC 3   | AC "The harness cannot ship" — the build assertion fails the release      | pending | §7.3 (slice B); X01 :96, :122                           |
| AC 4   | AC "Trading is asserted blocked where required"                           | written | §5 SA-T2-1 … SA-T2-8; C-2                               |
| AC 5   | AC "The baseline is actionable" — panel, state, assertion, SCR clause     | pending | §9 (slice D)                                            |
| DoD 1  | matrix data complete; self-check green                                    | pending | §3 is the data's text; §8 the JSON and its vitest check |
| DoD 2  | harness with the production-absence assertion green                       | pending | §7 (slice B)                                            |
| DoD 3  | assertions per cell, a11y semantics and analytics payloads                | written | §4, §5, §6; implemented in slice C                      |
| DoD 4  | meta-test proves assertions can fail                                      | pending | §8.3 (slice C)                                          |
| DoD 5  | baseline published for E49-S05                                            | pending | §9 (slice D)                                            |
| DoD 6  | specs in E49-Q01's pack as the `@state-matrix` shard within budget        | open    | §8.2; the pack (#1335) is not on `main` (BQ-7)          |
| DoD 7  | security-engineer review of the harness gating                            | open    | slice B carries the lens (BQ-6)                         |
| DoD 8  | coverage ≥ 80 %                                                           | pending | slices B and C                                          |
| DoD 9  | QA sign-off: fit to be E49-S05's oracle and E49-D05's evidence            | open    | §12 walkthrough                                         |
| DoD 10 | matrix documented in `03` §11                                             | open    | A-1 (an owner-document edit, never made here)           |
| DoD 11 | demo at Sprint Review                                                     | open    | §12 item 10                                             |
| DoD 12 | PRs merged via the merge queue                                            | open    | the orchestrator                                        |

## The questions BQ-0 … BQ-9 — defaults built; ruling pending (comment 6642015197)

The list is comment 6642015197 on #1362. Each ORCH-default is built as written; each bullet names where. A ruling
that amends a default replaces its text here and flips this heading to RULED.

- **BQ-0 — standing rules.** ORCH-default built: drafted against #5877 "if it merges as is"; `Refs` + `Partial:`
  (header); the ticket's branch; G-T2 on every gated cell (§5, R32 :17); rows, never owner edits (§10); C-2.11 (§0,
  §7); the size plan (§1); the helper imported by blob (§14); E47-D04 / D08 / D09 outrank, no hotkey added (§0).
- **BQ-1 — four slices.** ORCH-default built: A this plan + the matrix data + its self-check, B the harness, C the
  generator + specs + meta-test, D the baseline; the ticket's `## Test plan` untouched (§1, `03` :312, :314).
- **BQ-2 — every SCR id is a row.** ORCH-default built: 149 rows, compared both ways with `14` (§3.3, G-SCRSET);
  a row is cells or one row-level N/A with its reason; `pending` rows are written and never count as passing.
- **BQ-3 — D02's ten patterns as columns.** ORCH-default built: thirteen columns — SCR-151 split into D02 §2.1's
  three classes, loading by D02 §4's rows, error as CMP-026 `error` → CMP-027; Stale-vs-Resyncing `blocked on` (§2).
- **BQ-4 — the oracle and the analytics contract.** ORCH-default built: each assertion cites its D02 row or `14`
  clause; `14`'s analytics per pattern; PROPOSED fields are C-rows; `error.403_shown` only; G-3 `blocked on` (§6).
- **BQ-5 — T2, not `disabled`.** ORCH-default built: SA-T2-1 … SA-T2-8 (§5) with the negative safety cells;
  degraded's permission asserted as the banner's words; C-2 reads "name" as name + description.
- **BQ-6 — client-only harness, one switch.** ORCH-default built: network-layer statuses and `10018`, the WS
  fault channel, one test-only module behind the same define; no server hook; T-E2 / AC-16 N/A with the reason (§7).
- **BQ-7 — the host pack is not on `main`.** ORCH-default built: `apps/web/e2e/state-matrix/`, `@state-matrix`, a
  flagged config in the fault config's form; one tag-map row "if it merges as is"; DoD 6 stays open (§8.2).
- **BQ-8 — data as JSON.** ORCH-default built: JSON with the row × column × cell shape, a TypeScript generator, a
  vitest self-check reading `14`'s id set; one Deviation line; no new dependency (§8.1, §13).
- **BQ-9 — the baseline.** ORCH-default built: one run after #5877 merges, deterministic, axe on every cell,
  `pending` rows "not built", failures routed to E49-S05 as rows, E08-D14 cited, no pixel comparison (§9).

## 0. Conventions

- **Expectations come from the specification, never the build** (the E40 plan's rule, E40Q :9). Sources:
  - `T` is the ticket text of #1362; `D02` is `docs/design/E49/E49-D02.md` at `bc0c643e9` (PR #5877);
  - `X01` is `docs/security/threat-models/e49-defect-fix-path.md`; `R32` is `.claude/rules/32-design-specs.md`;
  - `14`, `15`, `03`, `05`, `22`, `24` are the plan documents, cited `file :line`;
  - `WSW` is the shared socket entry `wsWorker.ts` (`apps/web/src/lib/ws/…`), `FCFG` the fault lane's config
    `apps/web/e2e/playwright.fault.config.ts`, `BUNDLE` its bundle test
    `apps/web/test/lib/ws/faultInjection.bundle.test.ts`, `SEV` `apps/web/src/features/symbol-search/searchEvents.ts`,
    `D14E08` `docs/design/E08/E08-D14.md` and `E40Q` `docs/qa/test-plans/e40-alerts.md`.
- **Where sources differ, nothing is guessed.** The cell follows the source this plan names, the difference is a row
  of section 10, and a cell whose answer rests on an open question is **blocked on** its owner and not executed.
- **Case ids:** `E49-TC-<nnn>-<col>`, e.g. `E49-TC-063-DC` is SCR-063's disconnected cell; assertion ids are
  `SA-<col>-<k>` (section 4). A cell runs every `SA-X-*` row plus its column's rows plus, for a `/T2` cell, §5.
- **Build-status tag** (the E40 convention, E40Q :9): `shipped` is a module under `apps/web/src` at the base that
  names the SCR id (the path is relative to `apps/web/src`); `pending` is none. The tag is a pointer, not a
  claim that the surface mounts: slice D re-tags any `shipped` row whose surface does not mount as `pending`. A
  `pending` cell is written now and never counts as passing. **PROPOSED** marks an expectation from a D02 row not
  yet approved by the owner.
- **Environment (C-2.11, C-13.5):** recorded fixtures and network-layer stubs only; no cell, stub or fixture reaches
  a live or demo host. No account id, balance or credential appears in a step, a fixture or a sink capture.
- **Time:** a fake clock drives every countdown and threshold; no sleeps. AC 2's 5 s is a ceiling on reaching the
  state, never a wait (SA-X-6).
- **Oracles, in order:** the accessibility tree (role, name, description, live region) > the DOM contract
  (attributes, CMP root, request and context counters) > the analytics sink. No pixel or screenshot oracle (T Out of
  scope; E49-S04).
- **Precedence of the cross-cutting specs:** E47-D04 (focus), E47-D08 (announcements) and E47-D09 (keys) outrank
  any row here; a disagreement is an F-row, never a silent merge. No cell adds or asserts a new hotkey.
- **Defects** follow `03` §11.3; a flaky cell is quarantined with a filed Bug, never deleted (C-9.3).

## 1. Scope, slices and build status

**In scope:** every `14` SCR id × the thirteen columns of §2, the T2 and negative safety cells, the analytics
contract per pattern, and the contracts of the harness (slice B), the generator, specs and meta-test (slice C) and
the baseline (slice D). **Out of scope (T):** fixing a non-conformance (E49-S05), pixel comparison (E49-S04),
reconnect and load-shedding behaviour (E45, E46).

**The four slices** (BQ-1; C-4.8: the counted figure is reported at each first push, a why-not-split note above
400, `large-pr-approved` asked above 800, ≈ 1,500 hard):

| Slice | Carries                                                                                  | Closing line           |
| ----- | ---------------------------------------------------------------------------------------- | ---------------------- |
| A     | this plan and its audit; then the matrix JSON and its vitest self-check (§8.1)           | never (`Partial:`)     |
| B     | the harness: `forceState`, the test-only module, the bundle assertion (§7)               | never (`Partial:`)     |
| C     | the generator, the `@state-matrix` specs, the meta-test (§8)                             | never (`Partial:`)     |
| D     | `docs/plan/backlog/artifacts/e49-state-matrix-baseline.md` (E49's ledger home, D02 :8–9) | yes, once #1331 closed |

The ticket's `## Test plan` stays as written (`03` :312, :314: plans live in the ticket body); this document is
its expansion, as the E40 and E42 plans are.

**Build status when written** (`origin/main` `d5f2e0bc1`, 2026-11-04): 29 of the 149 rows are `shipped`, 24 of
them cell rows (§3.3); the order ticket, the positions grid, the DOM ladder and every algo builder are `pending` — most `/T2`
cells will report "not built" in slice D, not failures (F-12). The pattern components on `main` live in
`apps/web/src/features/system-states/` and `apps/web/src/features/app-shell/`.

## 2. The columns (the state set; BQ-3)

`14` closes the set at ten patterns (`14` :3088; D02 C-1); the ticket's eleven states and its harness's version
mismatch map onto them (C-1). Loading is one column whose cell names its D02 §4 row (D02 :315–325).

| Col | Ticket state                      | Pattern and component                                            | Injection (§7)                        | Assertions |
| --- | --------------------------------- | ---------------------------------------------------------------- | ------------------------------------- | ---------- |
| LD  | loading                           | D02 §4 row L-1 … L-11 (L-1 is SCR-150, SCR-010's row only)       | a held network-layer response         | §4.2       |
| E1  | empty: nothing created yet        | CMP-026 `no-data`, reason `nothing_created` (D02 §2.1, D02 :196) | an empty source (stub or module)      | §4.3       |
| E2  | empty: nothing matches the filter | CMP-026 `filtered-empty`, reason `no_matches`                    | a stub + a filter that matches none   | §4.3       |
| E3  | empty: data not recorded yet      | CMP-026 `recording-not-started`, reason `not_recorded`           | a stub with no recorded coverage      | §4.3       |
| ER  | error (a failed request)          | CMP-026 `error` → CMP-027 panel form (`15` :313); never SCR-156  | a network-layer `500` or abort        | §4.4       |
| DC  | stale / disconnected              | SCR-152 (D02 :394); stale under it by D02 §1.5's PROPOSED ladder | the WS fault channel                  | §4.5       |
| DG  | degraded                          | SCR-153 (D02 :424)                                               | the health stub or the module (G-3)   | §4.6       |
| 403 | permission denied                 | SCR-154 (D02 :450)                                               | a network-layer `403` Problem         | §4.7       |
| 404 | not found                         | SCR-155 (D02 :471)                                               | a route, or a network-layer `404`     | §4.8       |
| CR  | crashed                           | SCR-156 (D02 :489)                                               | the module throws in the named panel  | §4.9       |
| VM  | version mismatch (harness list)   | SCR-157 (D02 :513)                                               | the module                            | §4.10      |
| RL  | rate-limited                      | SCR-158 (D02 :537)                                               | a network-layer `429` (`22` :807–814) | §4.11      |
| OF  | offline (shell)                   | SCR-159 (D02 :563)                                               | the network layer refuses every route | §4.12      |

`backfill-in-progress` is a loading treatment, never an empty class (D02 §2.1). A cell whose answer rests on
E17-D01 Q-G (Stale vs Resyncing, D02 F-12) is **blocked on** E17-D01, never decided here.

## 3. The row set and its N/A rules (BQ-2)

Every `### SCR-` entry of `14` is one row (149). A row is either **cells** (the columns it lists) or **one
row-level N/A** with its RN reason. In a cell row, every column not listed is N/A by one of the NR rules the row
names; no NR rule names a listed column. Both are mechanical (the audit's G-CELLS).

### 3.1 Row-level N/A (RN)

| RN   | Reason                                                                                                      | Rows                            |
| ---- | ----------------------------------------------------------------------------------------------------------- | ------------------------------- |
| RN-1 | a pattern, not a surface: its rules are §4's oracle; its app-level cells sit on SCR-010 and SCR-001         | SCR-150 … SCR-159               |
| RN-2 | a state or treatment of another row: asserted on that row's cells (R-1's band and badge on every cell, Q10) | SCR-047, 048, 073, 075, 124     |
| RN-3 | no data source of its own: a menu, a local setting or static content; a gated item is its host row's        | the 24 rows marked RN-3 in §3.3 |

### 3.2 Cell-level N/A (NR)

| NR    | Reason                                                                                    | Columns           |
| ----- | ----------------------------------------------------------------------------------------- | ----------------- |
| NR-1  | no data of its own: renders its host's or local state                                     | LD E1 E2 E3 ER DC |
| NR-2  | not a collection: a single object, form, detail or wizard                                 | E1 E2             |
| NR-3  | a collection with no filter or query control                                              | E2                |
| NR-4  | not recorder-backed                                                                       | E3                |
| NR-5  | shows no WS-fed value                                                                     | DC                |
| NR-6  | none of SCR-153's causes feeds it (`14` :3151)                                            | DG                |
| NR-7  | every role that reaches it may use all of it: no role- or account-scoped resource         | 403               |
| NR-8  | its route carries no object id, or it has no route (modal, drawer, panel, section, menu)  | 404               |
| NR-9  | no boundary of its own: a crash is its host panel's or route's (`14` :3187)               | CR                |
| NR-10 | no trading control: read-only under an incompatible protocol (`14` :3198)                 | VM                |
| NR-11 | issues no rate-limitable action                                                           | RL                |
| NR-12 | an app-level shell state, asserted on SCR-010 (and SCR-001 before sign-in)                | OF                |
| NR-13 | no wait of its own: its only busy state is a control's (D02 §4's one exclusion, D02 :299) | LD                |
| NR-14 | the admin area: a session without `admin:read` gets SCR-155 by D-1, never SCR-154         | 403               |
| NR-15 | nothing to create: a fixed catalogue or a search result                                   | E1                |
| NR-16 | issues no request of its own                                                              | LD ER             |

Token forms in §3.3: `LD:L-n` names the D02 §4 row; `/T2` marks a cell whose controls are gated (§5); `404` on
an admin row is D-1's identical 404, elsewhere a deleted or unknown object id under the row's route.

### 3.3 The matrix

| SCR     | Surface                                           | Tag                                                         | Cells                                                         | N/A by                                                                |
| ------- | ------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------- | --------------------------------------------------------------------- |
| SCR-001 | Login                                             | `shipped` (`features/auth/LoginScreen.tsx`)                 | `ER` `CR` `RL` `OF`                                           | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-10, NR-13                      |
| SCR-002 | Two-factor (TOTP) challenge                       | `shipped` (`features/auth/TwoFactorStep.tsx`)               | `ER` `CR` `RL`                                                | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-10, NR-12, NR-13               |
| SCR-003 | TOTP enrolment (first login / re-enrol)           | `pending`                                                   | `LD:L-7` `ER` `CR` `RL`                                       | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-10, NR-12                      |
| SCR-004 | Forced password change                            | `shipped` (`features/auth/ChangePasswordScreen.tsx`)        | `ER` `CR` `RL`                                                | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-10, NR-12, NR-13               |
| SCR-005 | Session expired / re-auth modal                   | `shipped` (`features/session/SessionLockDialog.tsx`)        | `ER` `RL`                                                     | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-12, NR-13         |
| SCR-006 | Step-up authentication modal (S)                  | `shipped` (`features/stepUp/StepUpDialog.tsx`)              | `ER` `RL`                                                     | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-12, NR-13         |
| SCR-010 | App shell (global chrome)                         | `shipped` (`features/app-shell/ShellLayout.tsx`)            | `LD:L-1` `ER` `DC` `DG` `404` `CR` `VM` `RL` `OF`             | NR-2, NR-4, NR-7                                                      |
| SCR-011 | Navigation rail (expanded) & workspace switcher   | `shipped` (`features/app-shell/NavRail.tsx`)                | `LD:L-6` `E1` `ER`                                            | NR-3, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12         |
| SCR-012 | Command palette                                   | `pending`                                                   | `LD:L-7` `E2` `ER`                                            | NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-15        |
| SCR-013 | Hotkey cheatsheet overlay                         | `shipped` (`keymap/Cheatsheet.tsx`)                         | `LD:L-7` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12         |
| SCR-014 | Notification centre (right-rail drawer)           | `shipped` (`features/app-shell/RightRail.tsx`)              | `LD:L-6` `E1` `ER` `DC`                                       | NR-3, NR-4, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12               |
| SCR-015 | Global toast host                                 | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-016 | First-run onboarding wizard (owner)               | `pending`                                                   | `LD:L-6` `ER` `403` `CR` `RL`                                 | NR-2, NR-4, NR-5, NR-6, NR-8, NR-10, NR-12                            |
| SCR-017 | Manager/viewer onboarding (invited user)          | `shipped` (`features/invites/InviteAcceptScreen.tsx`)       | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-7, NR-10, NR-11, NR-12                     |
| SCR-018 | Guided tour / coach marks                         | `shipped` (`features/onboarding/CoachMarkTour.tsx`)         | —                                                             | RN-3                                                                  |
| SCR-019 | Setup checklist card                              | `shipped` (`features/onboarding/SetupChecklistCard.tsx`)    | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12         |
| SCR-020 | Workspace (terminal) page                         | `pending`                                                   | `LD:L-6` `E1` `ER` `DC` `DG` `404` `CR` `RL`                  | NR-3, NR-4, NR-7, NR-10, NR-12                                        |
| SCR-021 | Dock / panel system (drag, split, float)          | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-022 | Layout preset gallery                             | `pending`                                                   | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12         |
| SCR-023 | Multi-chart sync configuration                    | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-024 | Panel picker ("Add panel")                        | `pending`                                                   | `LD:L-7` `E2` `ER`                                            | NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-15        |
| SCR-025 | Workspace settings modal                          | `pending`                                                   | `ER` `RL`                                                     | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-12, NR-13         |
| SCR-026 | Workspace import                                  | `pending`                                                   | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13  |
| SCR-027 | Floating panel window (Electron)                  | `pending`                                                   | `CR`                                                          | NR-1, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12                           |
| SCR-028 | Panel context menu                                | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-029 | Unsaved-changes / layout-conflict dialog          | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-030 | Chart panel (price + footprint)                   | `shipped` (`features/chart-errors/ChartErrorSurface.tsx`)   | `LD:L-2` `E3` `ER` `DC/T2` `DG` `CR` `VM/T2` `RL/T2`          | NR-3, NR-7, NR-8, NR-12, NR-15                                        |
| SCR-031 | Chart settings dialog (general)                   | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-032 | Footprint settings dialog                         | `pending`                                                   | `LD:L-8` `ER` `RL`                                            | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-12                |
| SCR-033 | Deep Stats rows configuration                     | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-034 | Indicator library / add-indicator dialog          | `pending`                                                   | `LD:L-6` `E2` `ER`                                            | NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-15        |
| SCR-035 | Indicator settings dialog                         | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-036 | Indicator manager (object tree)                   | `pending`                                                   | `E1`                                                          | NR-3, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-16  |
| SCR-037 | Drawing toolbar & drawing properties              | `pending`                                                   | `LD:L-7` `ER` `RL`                                            | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-12                |
| SCR-038 | Profile panel (volume / delta profile + TPO)      | `pending`                                                   | `LD:L-6` `E3` `ER` `DC` `DG` `CR`                             | NR-3, NR-7, NR-8, NR-10, NR-11, NR-12, NR-15                          |
| SCR-039 | Profile settings dialog                           | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-040 | Chart trading overlay settings                    | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-041 | Symbol/interval quick-switcher (in-chart)         | `shipped` (`features/symbol-search/QuickSwitcher.tsx`)      | `LD:L-7` `E2` `E3` `ER`                                       | NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-15              |
| SCR-042 | Interval / bar-mode menu                          | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-043 | Price-scale / time-scale context menus            | `shipped` (`features/chart-price-scale/PriceScaleMenu.tsx`) | —                                                             | RN-3                                                                  |
| SCR-044 | "Go to date" dialog                               | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-045 | Chart data-table alternative (a11y)               | `shipped` (`chart/a11y/ChartDataTable.tsx`)                 | `DC` `CR`                                                     | NR-2, NR-4, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12, NR-16              |
| SCR-046 | Chart engine diagnostics overlay                  | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-047 | Chart empty / no-data state                       | `pending`                                                   | —                                                             | RN-2                                                                  |
| SCR-048 | Chart error state                                 | `pending`                                                   | —                                                             | RN-2                                                                  |
| SCR-049 | Multi-chart grid panel                            | `pending`                                                   | `CR`                                                          | NR-1, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12                           |
| SCR-050 | Heatmap + DOM ladder panel (the DeepDOM analogue) | `pending`                                                   | `LD:L-6` `ER` `DC/T2` `DG` `CR` `VM/T2` `RL/T2`               | NR-2, NR-4, NR-7, NR-8, NR-12                                         |
| SCR-051 | Heatmap & ladder settings dialog                  | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-052 | CVD / delta panel                                 | `pending`                                                   | `LD:L-6` `E3` `ER` `DC` `DG` `CR`                             | NR-3, NR-7, NR-8, NR-10, NR-11, NR-12, NR-15                          |
| SCR-053 | Tape / Time & Sales + big-trade bubbles panel     | `pending`                                                   | `LD:L-6` `E2` `ER` `DC` `DG` `CR`                             | NR-4, NR-7, NR-8, NR-10, NR-11, NR-12, NR-15                          |
| SCR-054 | OI / funding / liquidations panel                 | `pending`                                                   | `LD:L-6` `E3` `ER` `DC` `DG` `CR`                             | NR-3, NR-7, NR-8, NR-10, NR-11, NR-12, NR-15                          |
| SCR-055 | Speed-of-tape panel                               | `pending`                                                   | `DC` `DG` `CR`                                                | NR-2, NR-4, NR-7, NR-8, NR-10, NR-11, NR-12, NR-16                    |
| SCR-056 | Imbalance tracker panel                           | `pending`                                                   | `DC` `DG` `CR`                                                | NR-2, NR-4, NR-7, NR-8, NR-10, NR-11, NR-12, NR-16                    |
| SCR-057 | Market regime panel                               | `pending`                                                   | `LD:L-7` `ER` `DC` `DG` `CR`                                  | NR-2, NR-4, NR-7, NR-8, NR-10, NR-11, NR-12                           |
| SCR-058 | Detector methodology drawer ("Why estimated?")    | `pending`                                                   | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12         |
| SCR-059 | Detector settings dialog                          | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-060 | Order ticket panel (single account)               | `pending`                                                   | `LD:L-6` `ER` `DC/T2` `DG/T2` `403` `CR` `VM/T2` `RL/T2`      | NR-2, NR-4, NR-8, NR-12                                               |
| SCR-061 | Trade-group ticket (multi-account fan-out)        | `pending`                                                   | `LD:L-6` `ER` `DC/T2` `DG/T2` `403` `CR` `VM/T2` `RL/T2`      | NR-2, NR-4, NR-8, NR-12                                               |
| SCR-062 | Trade-group manager                               | `pending`                                                   | `LD:L-6` `E1` `ER` `404` `CR` `VM/T2` `RL/T2`                 | NR-3, NR-4, NR-5, NR-6, NR-12, NR-14                                  |
| SCR-063 | Positions & orders grid panel                     | `pending`                                                   | `LD:L-6` `E1` `ER` `DC/T2` `DG/T2` `403` `CR` `VM/T2` `RL/T2` | NR-3, NR-4, NR-8, NR-12                                               |
| SCR-064 | Position SL/TP editor (modal)                     | `pending`                                                   | `ER` `DC/T2` `VM/T2` `RL/T2`                                  | NR-2, NR-4, NR-6, NR-7, NR-8, NR-9, NR-12, NR-13                      |
| SCR-065 | Scaled / ladder order builder                     | `pending`                                                   | `ER` `DC/T2` `VM/T2` `RL/T2`                                  | NR-2, NR-4, NR-6, NR-7, NR-8, NR-9, NR-12, NR-13                      |
| SCR-066 | TWAP builder                                      | `pending`                                                   | `ER` `DC/T2` `VM/T2` `RL/T2`                                  | NR-2, NR-4, NR-6, NR-7, NR-8, NR-9, NR-12, NR-13                      |
| SCR-067 | Iceberg (emulated) builder                        | `pending`                                                   | `ER` `DC/T2` `VM/T2` `RL/T2`                                  | NR-2, NR-4, NR-6, NR-7, NR-8, NR-9, NR-12, NR-13                      |
| SCR-068 | Chase-limit builder                               | `pending`                                                   | `ER` `DC/T2` `VM/T2` `RL/T2`                                  | NR-2, NR-4, NR-6, NR-7, NR-8, NR-9, NR-12, NR-13                      |
| SCR-069 | Emulated OCO / bracket builder                    | `pending`                                                   | `ER` `DC/T2` `VM/T2` `RL/T2`                                  | NR-2, NR-4, NR-6, NR-7, NR-8, NR-9, NR-12, NR-13                      |
| SCR-070 | Algo monitor panel                                | `pending`                                                   | `LD:L-6` `E1` `ER` `DC/T2` `DG` `CR` `VM/T2` `RL/T2`          | NR-3, NR-4, NR-7, NR-8, NR-12                                         |
| SCR-071 | Risk dashboard                                    | `pending`                                                   | `LD:L-6` `ER` `DC/T2` `DG` `403` `CR` `VM/T2` `RL/T2`         | NR-2, NR-4, NR-8, NR-12                                               |
| SCR-072 | Kill-switch / freeze confirmation modal           | `pending`                                                   | `ER` `DC/T2` `VM/T2` `RL/T2`                                  | NR-2, NR-4, NR-6, NR-7, NR-8, NR-9, NR-12, NR-13                      |
| SCR-073 | Lockout notice (manager view)                     | `pending`                                                   | —                                                             | RN-2                                                                  |
| SCR-074 | Environment switcher (Demo ↔ Live)                | `pending`                                                   | `LD:L-8` `ER` `RL`                                            | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-12                |
| SCR-075 | Demo / Live banner & per-panel badges             | `pending`                                                   | —                                                             | RN-2                                                                  |
| SCR-076 | Order confirmation modal                          | `pending`                                                   | `ER` `DC/T2` `VM/T2` `RL/T2`                                  | NR-2, NR-4, NR-6, NR-7, NR-8, NR-9, NR-12, NR-13                      |
| SCR-077 | Order rejection detail drawer                     | `pending`                                                   | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12         |
| SCR-078 | Fills / executions detail                         | `pending`                                                   | `LD:L-6` `E1` `ER` `DC`                                       | NR-3, NR-4, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12               |
| SCR-079 | Account detail drawer (trading-side)              | `pending`                                                   | `LD:L-6` `ER` `DC` `403`                                      | NR-2, NR-4, NR-6, NR-8, NR-9, NR-10, NR-11, NR-12                     |
| SCR-080 | Rules list                                        | `pending`                                                   | `LD:L-6` `E1` `E2` `ER` `DC` `DG` `CR` `RL`                   | NR-4, NR-7, NR-8, NR-10, NR-12                                        |
| SCR-081 | Rule editor — form mode                           | `pending`                                                   | `LD:L-6` `ER` `DG` `404` `CR` `RL`                            | NR-2, NR-4, NR-5, NR-7, NR-10, NR-12                                  |
| SCR-082 | Rule editor — node-graph mode                     | `pending`                                                   | `LD:L-6` `ER` `DG` `404` `CR` `RL`                            | NR-2, NR-4, NR-5, NR-7, NR-10, NR-12                                  |
| SCR-083 | Rule templates gallery                            | `pending`                                                   | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12         |
| SCR-084 | Rule simulation / backtest panel                  | `pending`                                                   | `LD:L-8` `E3` `ER` `DC` `DG` `CR` `RL`                        | NR-2, NR-7, NR-8, NR-10, NR-12                                        |
| SCR-085 | Rule arming dialog                                | `pending`                                                   | `ER` `DG/T2` `RL`                                             | NR-2, NR-4, NR-5, NR-7, NR-8, NR-9, NR-10, NR-12, NR-13               |
| SCR-086 | Rule conflict resolver                            | `pending`                                                   | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13  |
| SCR-087 | Rule fire history / execution log                 | `pending`                                                   | `LD:L-6` `E1` `ER` `DC` `DG` `404` `CR`                       | NR-3, NR-4, NR-7, NR-10, NR-11, NR-12                                 |
| SCR-088 | Rule IR inspector (advanced)                      | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-089 | Rule import / export                              | `pending`                                                   | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13  |
| SCR-090 | Alerts centre                                     | `shipped` (`features/alerts/AlertsScreen.tsx`)              | `LD:L-6` `E1` `E2` `ER` `DC` `DG` `CR` `RL`                   | NR-4, NR-7, NR-8, NR-10, NR-12                                        |
| SCR-091 | Alert editor                                      | `pending`                                                   | `ER` `RL`                                                     | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-12, NR-13         |
| SCR-092 | Alert triggered toast / detail                    | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-093 | Journal (trade list)                              | `pending`                                                   | `LD:L-6` `E1` `E2` `E3` `ER` `CR`                             | NR-5, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12                           |
| SCR-094 | Trade detail / post-mortem                        | `pending`                                                   | `LD:L-6` `E3` `ER` `404` `CR`                                 | NR-2, NR-5, NR-6, NR-7, NR-10, NR-11, NR-12                           |
| SCR-095 | Journal analytics dashboard                       | `pending`                                                   | `LD:L-6` `E1` `E2` `ER` `CR`                                  | NR-4, NR-5, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12                     |
| SCR-096 | Journal tag manager                               | `pending`                                                   | `E1` `ER`                                                     | NR-3, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13  |
| SCR-097 | Replay page                                       | `pending`                                                   | `LD:L-8` `E3` `ER` `DC` `DG` `CR` `RL`                        | NR-2, NR-7, NR-8, NR-10, NR-12                                        |
| SCR-098 | Replay session setup modal                        | `pending`                                                   | `LD:L-6` `E3` `ER`                                            | NR-2, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12               |
| SCR-099 | Replay paper-trading results                      | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-100 | Watchlist panel                                   | `pending`                                                   | `LD:L-6` `E1` `ER` `DC` `DG` `CR`                             | NR-3, NR-4, NR-7, NR-8, NR-10, NR-11, NR-12                           |
| SCR-101 | Watchlist manager                                 | `pending`                                                   | `LD:L-6` `E1` `ER` `RL`                                       | NR-3, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-12                |
| SCR-102 | Symbol search (global)                            | `shipped` (`features/symbol-search/SymbolSearch.tsx`)       | `LD:L-7` `E2` `ER`                                            | NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-15        |
| SCR-103 | Symbol info / instrument detail                   | `pending`                                                   | `LD:L-6` `E3` `ER` `DC`                                       | NR-2, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12                     |
| SCR-104 | Scanner / screener panel                          | `pending`                                                   | `LD:L-6` `E2` `ER` `DG` `CR` `RL`                             | NR-4, NR-5, NR-7, NR-8, NR-10, NR-12, NR-15                           |
| SCR-110 | Settings home                                     | `shipped` (`features/settings/SettingRow.tsx`)              | `CR`                                                          | NR-1, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12                           |
| SCR-111 | Profile settings                                  | `pending`                                                   | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13  |
| SCR-112 | Security settings                                 | `shipped` (`features/session/SessionsSection.tsx`)          | `LD:L-6` `ER` `RL`                                            | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-12                |
| SCR-113 | Hotkey editor                                     | `shipped` (`keymap/HotkeyEditor.tsx`)                       | `LD:L-7` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12         |
| SCR-114 | Trading defaults settings                         | `pending`                                                   | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13  |
| SCR-115 | Notifications settings                            | `pending`                                                   | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13  |
| SCR-116 | Appearance & density settings                     | `shipped` (`features/appearance/AppearanceScreen.tsx`)      | —                                                             | RN-3                                                                  |
| SCR-117 | Accessibility settings                            | `shipped` (`features/a11y-preferences/model.ts`)            | —                                                             | RN-3                                                                  |
| SCR-118 | Data & performance settings                       | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-119 | Help & about                                      | `pending`                                                   | —                                                             | RN-3                                                                  |
| SCR-120 | Admin home / overview                             | `shipped` (`features/admin/overview/OverviewPage.tsx`)      | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                    |
| SCR-121 | Admin: users list                                 | `pending`                                                   | `LD:L-6` `E1` `ER` `404` `CR`                                 | NR-3, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                    |
| SCR-122 | Admin: user detail / edit                         | `pending`                                                   | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                    |
| SCR-123 | Admin: invite user                                | `shipped` (`features/invites/AdminInviteScreen.tsx`)        | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13, NR-14 |
| SCR-124 | Admin: "view as" (read-only impersonation)        | `shipped` (`features/view-as/ViewAsBanner.tsx`)             | —                                                             | RN-2                                                                  |
| SCR-125 | Admin: Bybit accounts list                        | `pending`                                                   | `LD:L-6` `E1` `ER` `404` `CR` `RL`                            | NR-3, NR-4, NR-5, NR-6, NR-10, NR-12, NR-14                           |
| SCR-126 | Admin: add / edit Bybit account                   | `pending`                                                   | `ER` `404` `RL`                                               | NR-2, NR-4, NR-5, NR-6, NR-9, NR-10, NR-12, NR-13, NR-14              |
| SCR-127 | Admin: API key rotation                           | `pending`                                                   | `ER` `RL`                                                     | NR-2, NR-4, NR-5, NR-6, NR-8, NR-9, NR-10, NR-12, NR-13, NR-14        |
| SCR-128 | Admin: key health & secrets policy panel          | `pending`                                                   | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-8, NR-9, NR-10, NR-11, NR-12, NR-14        |
| SCR-129 | Admin: account disable / delete confirmation      | `pending`                                                   | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13, NR-14 |
| SCR-130 | Admin: per-account profiles list                  | `pending`                                                   | `LD:L-6` `E1` `ER` `404` `CR`                                 | NR-3, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                    |
| SCR-131 | Admin: profile editor                             | `pending`                                                   | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                    |
| SCR-132 | Admin: profile templates                          | `pending`                                                   | `LD:L-6` `E1` `ER`                                            | NR-3, NR-4, NR-5, NR-6, NR-8, NR-9, NR-10, NR-11, NR-12, NR-14        |
| SCR-133 | Admin: symbol permissions matrix                  | `pending`                                                   | `LD:L-6` `E2` `ER` `404` `CR`                                 | NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14, NR-15                   |
| SCR-134 | Admin: risk policy (global)                       | `pending`                                                   | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                    |
| SCR-135 | Admin: audit log                                  | `pending`                                                   | `LD:L-6` `E2` `ER` `404` `CR`                                 | NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14, NR-15                   |
| SCR-136 | Admin: audit event detail                         | `pending`                                                   | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-8, NR-9, NR-10, NR-11, NR-12, NR-14        |
| SCR-137 | Admin: security centre                            | `pending`                                                   | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                    |
| SCR-140 | Admin: recorder & storage                         | `shipped` (`features/recorder/RecorderScreen.tsx`)          | `LD:L-6` `E1` `ER` `DC` `DG` `404` `CR`                       | NR-3, NR-4, NR-10, NR-11, NR-12, NR-14                                |
| SCR-141 | Admin: retention policy editor                    | `shipped` (`features/recorder/RecorderChrome.tsx`)          | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13, NR-14 |
| SCR-142 | Admin: storage & database panel                   | `shipped` (`features/recorder/RecorderScreen.tsx`)          | `LD:L-6` `ER` `DG`                                            | NR-2, NR-4, NR-5, NR-8, NR-9, NR-10, NR-11, NR-12, NR-14              |
| SCR-143 | Admin: system health                              | `pending`                                                   | `LD:L-6` `ER` `DC` `DG` `404` `CR`                            | NR-2, NR-4, NR-10, NR-11, NR-12, NR-14                                |
| SCR-144 | Admin: incident / connectivity log                | `pending`                                                   | `LD:L-6` `E1` `E2` `ER` `404` `CR`                            | NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                          |
| SCR-145 | Admin: feature flags                              | `pending`                                                   | `LD:L-6` `ER` `DC` `404` `CR`                                 | NR-2, NR-4, NR-6, NR-10, NR-11, NR-12, NR-14                          |
| SCR-146 | Admin: backups & restore                          | `pending`                                                   | `LD:L-8` `E1` `ER` `404` `CR`                                 | NR-3, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                    |
| SCR-147 | Admin: exchange connectivity & rate limits        | `pending`                                                   | `LD:L-6` `ER` `DC` `DG` `404` `CR` `RL`                       | NR-2, NR-4, NR-10, NR-12, NR-14                                       |
| SCR-148 | Admin: maintenance mode                           | `pending`                                                   | `ER` `404` `CR`                                               | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-13, NR-14             |
| SCR-149 | Admin re-authentication gate                      | `pending`                                                   | `ER` `RL`                                                     | NR-2, NR-4, NR-5, NR-6, NR-8, NR-9, NR-10, NR-12, NR-13, NR-14        |
| SCR-150 | Global loading / app boot                         | `pending`                                                   | —                                                             | RN-1                                                                  |
| SCR-151 | Empty state pattern                               | `pending`                                                   | —                                                             | RN-1                                                                  |
| SCR-152 | Disconnected / reconnecting state                 | `pending`                                                   | —                                                             | RN-1                                                                  |
| SCR-153 | Degraded-mode state                               | `pending`                                                   | —                                                             | RN-1                                                                  |
| SCR-154 | Permission denied (403)                           | `pending`                                                   | —                                                             | RN-1                                                                  |
| SCR-155 | Not found (404)                                   | `pending`                                                   | —                                                             | RN-1                                                                  |
| SCR-156 | Application error boundary (500 / crash)          | `pending`                                                   | —                                                             | RN-1                                                                  |
| SCR-157 | Version mismatch / update available               | `pending`                                                   | —                                                             | RN-1                                                                  |
| SCR-158 | Rate-limited state                                | `pending`                                                   | —                                                             | RN-1                                                                  |
| SCR-159 | Offline / shell-specific states                   | `pending`                                                   | —                                                             | RN-1                                                                  |

## 4. The assertion sets (the oracle per column; BQ-4)

Each row: id, assertion, source, status. **PROPOSED** = a D02 row the owner has not approved; **blocked on** =
not executed until its owner answers. D02's adopted decisions handed to this ticket are AD-3 (D02 :732), AD-5
(D02 :734), AD-7 (D02 :736) and AD-10 (D02 :739).

### 4.1 Every cell (SA-X)

| SA      | Assertion                                                                                                                                                                                                                                                                                    | Source                      | Status   |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- | -------- |
| SA-X-1  | axe-core with `AXE_GATE_TAGS` (`apps/web/e2e/a11y/tags.ts`; WCAG 2.0, 2.1 and 2.2, A and AA) returns an empty violations list at serious and critical impact, per cell, closed and open (every disclosure, Details and dialog opened), in each shipped theme including the high-contrast set | `05` :298, :164; D02 §9     | ruled    |
| SA-X-2  | the surface renders exactly one pattern's root, the highest rank of the ladder whose condition holds                                                                                                                                                                                         | D02 :150, :156–167 (AD-1)   | PROPOSED |
| SA-X-3  | the environment band and badge stay where the chrome stays; nothing shown before the environment is known                                                                                                                                                                                    | D02 :123–126 (R-1 precedes) | ruled    |
| SA-X-4  | a keyboard-only play (Tab, Shift+Tab, arrows) reaches every action in a logical order (2.4.3), with no trap (2.1.2) and a visible focus ring of at least 2 px; the tab order is recorded in the cell trace; focus lands on D02 §3.2's target for the pattern                                 | D02 :265; `05` :103         | PROPOSED |
| SA-X-5  | one announcement per condition: a fake-clock run counts live-region updates per condition                                                                                                                                                                                                    | D02 :736 (AD-7)             | PROPOSED |
| SA-X-6  | `forceState` reaches the state within 5 s (a ceiling, polled on the tree; no sleep)                                                                                                                                                                                                          | T AC 2                      | ruled    |
| SA-X-7  | no sink capture, log or trace holds a credential, a session value or an account id outside the redaction                                                                                                                                                                                     | T Security notes; C-12.6    | ruled    |
| SA-X-8  | focus not obscured (2.4.11): each action is focused in turn and its bounding box is never fully under a sticky banner, the SCR-152 region or a toast; a measured check, axe cannot judge it                                                                                                  | `05` :103                   | ruled    |
| SA-X-9  | target size (2.5.8): each action's computed box is at least 24 × 24 CSS px, or it has 24 px spacing to the next target                                                                                                                                                                       | `05` :104                   | ruled    |
| SA-X-10 | text resize (1.4.4): at 200 % zoom every action and its reason stay reachable, nothing lost                                                                                                                                                                                                  | `05` :165                   | ruled    |
| SA-X-11 | under emulated `prefers-reduced-motion: reduce` no skeleton, SCR-150 progress or countdown animates                                                                                                                                                                                          | `05` :248                   | ruled    |
| SA-X-12 | colour is never the only signal: every state mark and the DG and RL badges carry a word or a named glyph                                                                                                                                                                                     | `05` :21                    | ruled    |

### 4.2 LD — loading (SCR-150 on SCR-010; D02 §4 elsewhere)

| SA      | Assertion                                                                                                 | Source                      | Status                  |
| ------- | --------------------------------------------------------------------------------------------------------- | --------------------------- | ----------------------- |
| SA-LD-1 | the rendered treatment equals the cell's D02 §4 row (T-1 … T-4)                                           | D02 :315–325 (AD-3)         | PROPOSED                |
| SA-LD-2 | never a bare spinner: CMP-014 only nested in CMP-038 or a busy CMP-001                                    | `14` :3093; D02 :586 (AP-1) | ruled                   |
| SA-LD-3 | a skeleton (T-2) sits under the host's `aria-busy` with CMP-038's words outside the hidden node           | D02 :299                    | PROPOSED                |
| SA-LD-4 | progress is announced politely per phase, never per tick                                                  | `14` :3093; D02 :247        | ruled                   |
| SA-LD-5 | L-1: the four named stages; the slow words at 5 s on the fake clock                                       | `14` :3092, :3099           | ruled                   |
| SA-LD-6 | L-1: the reload offer at 15 s                                                                             | `14` :3092; D02 F-4         | blocked on E10-D03 #197 |
| SA-LD-7 | L-1: `app.boot_started`, `app.boot_completed` `{durationMs, stages}`, `app.boot_failed` `{stage, reason}` | `14` :3097                  | ruled                   |

### 4.3 E1, E2, E3 — empty (SCR-151)

| SA      | Assertion                                                                                                                                        | Source                     | Status   |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------- | -------- |
| SA-EM-1 | CMP-026's `variant` and `reason` equal D02 §2.1's row for the column's class                                                                     | D02 :196                   | PROPOSED |
| SA-EM-2 | a heading stating the fact (at the host's level, none skipped), one cause sentence, and an action or an explicit no-action sentence for the role | `14` :3107; `05` :273      | ruled    |
| SA-EM-3 | never an icon alone, never a bare "No data" (AP-2, AP-3)                                                                                         | `14` :3107; D02 :586       | ruled    |
| SA-EM-4 | `empty_state_shown` `{surface, reason}` once per reason entry; never for a load or a failure                                                     | `14` :3109; SEV :90        | ruled    |
| SA-EM-5 | no WebGL context and no subscription is created for the panel under test (the counters stay at zero)                                             | `14` :3108                 | ruled    |
| SA-EM-6 | "{heading} {cause}" is announced once, politely, in the host's status region                                                                     | D02 :247                   | PROPOSED |
| SA-EM-7 | E3: the owner sees the recorder action; another role sees the sentence; the recording-start time is shown                                        | `14` :3112; D02 :202 (E-3) | ruled    |

### 4.4 ER — error (a failed request)

| SA      | Assertion                                                                                            | Source         | Status |
| ------- | ---------------------------------------------------------------------------------------------------- | -------------- | ------ |
| SA-ER-1 | CMP-026 `variant="error"` renders CMP-027's panel form with a retry action; never SCR-156's fallback | `15` :313      | ruled  |
| SA-ER-2 | the error is announced once (`role="alert"` for an error severity)                                   | `15` :328      | ruled  |
| SA-ER-3 | `empty_state_shown` is not emitted for a failure                                                     | D02 :196 (F-7) | ruled  |

### 4.5 DC — disconnected / stale (SCR-152)

| SA      | Assertion                                                                                                                                                                                   | Source                  | Status                   |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- | ------------------------ |
| SA-DC-1 | `role="alert"` once per Disconnected episode, then a persistent region named "Connection"                                                                                                   | `14` :3133; `15` :877   | ruled                    |
| SA-DC-2 | the countdown is never announced: CMP-035 sits under `aria-live="off"` or no live region (the attribute read), and zero text mutations land in any live ancestor across a fake-clock minute | `14` :3133; D02 :247    | ruled                    |
| SA-DC-3 | every affected panel shows its last-good time, exposed by `aria-describedby`, in no live region                                                                                             | `15` :889; D02 :247     | ruled                    |
| SA-DC-4 | the region is non-modal: no focus trap, focus unchanged; the positions grid's box minus its intersection with the region's box is never empty, measured at 1280 × 720 and at 200 % zoom     | `15` :877; D02 :406–407 | ruled                    |
| SA-DC-5 | `ws.disconnected` `{reason, subscriptions}`, `ws.reconnect_attempt` `{attempt}`, `ws.reconnected` `{outageMs, gapFilled}`; an order attempted offline records `order.blocked_offline`       | `14` :3137              | ruled                    |
| SA-DC-6 | `ws.banner_suppressed` on a suppressed flap                                                                                                                                                 | `14` :3139; D02 :769    | PROPOSED (C-5)           |
| SA-DC-7 | a stale panel that is also resyncing shows one of the two                                                                                                                                   | D02 F-12                | blocked on E17-D01 (Q-G) |

### 4.6 DG — degraded (SCR-153)

| SA      | Assertion                                                                                          | Source                 | Status |
| ------- | -------------------------------------------------------------------------------------------------- | ---------------------- | ------ |
| SA-DG-1 | a `role="status"` banner names exactly which capability is degraded and what still works           | `14` :3151             | ruled  |
| SA-DG-2 | each affected panel's badge repeats the specific degradation in its accessible name                | `14` :3151; D02 :230   | ruled  |
| SA-DG-3 | a blocking row is announced once as an alert; an info or warning row once as a status              | `15` :1040             | ruled  |
| SA-DG-4 | whether order entry is permitted is stated as words in the banner (never ambiguous)                | `14` :3156; `14` :3151 | ruled  |
| SA-DG-5 | shedding is disclosed; the environment badge, positions, orders and the stale marks are never shed | `14` :3152             | ruled  |
| SA-DG-6 | `degraded.entered` `{cause, sheddedFeatures}`, `degraded.exited` `{durationMs}`                    | `14` :3153             | ruled  |

### 4.7 403 — permission denied (SCR-154)

| SA       | Assertion                                                                                                                                                                                                  | Source                     | Status         |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | -------------- |
| SA-403-1 | a heading (one `h1` on the route form, none skipped), a sentence naming the missing capability (never a resource name), a link to a permitted page whose text names it; the route form sets the page title | `14` :3164; D02 :600 (D-2) | PROPOSED       |
| SA-403-2 | the correlation id is selectable text (a DOM text node, not an image or a pseudo-element, never `user-select: none`), rendered only when a 403 body arrived, never synthesised                             | `14` :3164; D02 :600 (D-4) | PROPOSED       |
| SA-403-3 | rendered from the 403 with no additional fetch (the request counter does not move)                                                                                                                         | `14` :3165                 | ruled          |
| SA-403-4 | `error.403_shown` is emitted; the server's audit record is not a client event and is not asserted here                                                                                                     | `14` :3166                 | ruled (C-7)    |
| SA-403-5 | no "Request access" control                                                                                                                                                                                | D02 :617 (D-3)             | PROPOSED (C-9) |
| SA-403-6 | the account variant's copy differs from the role variant's                                                                                                                                                 | `14` :3164                 | ruled          |

### 4.8 404 — not found (SCR-155)

| SA       | Assertion                                                                                                                                                                         | Source                   | Status   |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ | -------- |
| SA-404-1 | a heading (one `h1`, none skipped), a plain sentence, the attempted pathname echoed as text, likely destinations as a list of links that name their pages; the page title changes | `14` :3175               | ruled    |
| SA-404-2 | no network call                                                                                                                                                                   | `14` :3176               | ruled    |
| SA-404-3 | `error.404_shown` `{route}`                                                                                                                                                       | `14` :3177               | ruled    |
| SA-404-4 | `route` is the matched pattern, never the raw path; the echo drops the query and the hash                                                                                         | D02 :600 (D-7); D02 :769 | PROPOSED |
| SA-404-5 | admin rows: copy, title and analytics byte-identical to an unknown route's, and no admin chunk is requested                                                                       | D02 :600 (D-1)           | PROPOSED |

### 4.9 CR — crashed (SCR-156)

| SA      | Assertion                                                                                                                                                                                                                                           | Source                 | Status   |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | -------- |
| SA-CR-1 | a fallback with a heading, a plain statement, a selectable correlation id and two named actions; a panel or route fallback carries no `role="alert"` (the shell's region announces it), the app scope's is its own `role="alert"`                   | `14` :3186; `15` :1028 | ruled    |
| SA-CR-2 | the stack sits behind a disclosure labelled as technical detail                                                                                                                                                                                     | `14` :3186             | ruled    |
| SA-CR-3 | a panel crash leaves the workspace alive; the positions grid and the order ticket survive                                                                                                                                                           | `14` :3187             | ruled    |
| SA-CR-4 | `app.error_boundary_triggered` `{component, correlationId, stackHash}`                                                                                                                                                                              | `14` :3188             | ruled    |
| SA-CR-5 | one assertive announcement per crash: panel or route through the shell's pre-rendered region, the app scope through its own alert; focus moves to the fallback heading only when the crash unmounted the focused element, otherwise it is unchanged | `15` :1028             | ruled    |
| SA-CR-6 | the technical detail holds no server body, header or exchange message; Copy diagnostics is redacted                                                                                                                                                 | D02 :489               | PROPOSED |

### 4.10 VM — version mismatch (SCR-157)

| SA      | Assertion                                                                                             | Source     | Status |
| ------- | ----------------------------------------------------------------------------------------------------- | ---------- | ------ |
| SA-VM-1 | non-blocking: a `role="status"` banner; blocking: a dialog; each states current and required versions | `14` :3197 | ruled  |
| SA-VM-2 | blocking: trading surfaces are T2 (§5); read-only views stay usable                                   | `14` :3198 | ruled  |
| SA-VM-3 | `app.version_mismatch` `{clientVersion, serverVersion, blocking}`                                     | `14` :3199 | ruled  |

### 4.11 RL — rate-limited (SCR-158)

| SA      | Assertion                                                                                                        | Source                        | Status                  |
| ------- | ---------------------------------------------------------------------------------------------------------------- | ----------------------------- | ----------------------- |
| SA-RL-1 | a `role="status"` message names the throttled capability, the retry time absolute and relative, what still works | `14` :3209                    | ruled                   |
| SA-RL-2 | the countdown is announced at most once per 10 s on the fake clock, counted as text mutations in its live region | `14` :3209; `15` :416         | ruled                   |
| SA-RL-3 | the client honours `Retry-After`: zero requests on that scope before the retry time                              | `14` :3210; `22` :18362–18366 | ruled                   |
| SA-RL-4 | held actions are replayed only after the explicit confirmation, never silently                                   | `14` :3210                    | ruled                   |
| SA-RL-5 | `ratelimit.hit` `{scope, endpointClass, retryAfterMs}`; `order.blocked_ratelimited` on a refused order           | `14` :3211; D02 :777          | blocked on E30-D03 #851 |

### 4.12 OF — offline (SCR-159; SCR-010 and SCR-001 only)

| SA      | Assertion                                                                                                   | Source             | Status |
| ------- | ----------------------------------------------------------------------------------------------------------- | ------------------ | ------ |
| SA-OF-1 | a page or banner with a heading and a plain sentence; the tailnet case reads "Not connected to the tailnet" | `14` :3220         | ruled  |
| SA-OF-2 | detected from request failure within 5 s on the fake clock, not from `navigator.onLine` alone               | `14` :3221         | ruled  |
| SA-OF-3 | `shell.offline_detected` `{cause}`, `shell.tailscale_unreachable`, `shell.gpu_unavailable`                  | `14` :3222         | ruled  |
| SA-OF-4 | the backend-unreachable takeover shows no environment                                                       | D02 :123–126 (R-1) | ruled  |

## 5. Trading safety (T2 and the negative cells; BQ-5)

A `/T2` cell asserts D02's R-2 (D02 :127–136), the G-T2 gate of R32 :17, on every new-order control of the row:

| SA      | Assertion                                                                                                                                                                                                                                                                       | Marker          |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| SA-T2-1 | the control keeps its native role and its full label                                                                                                                                                                                                                            | G-T2.1a         |
| SA-T2-2 | `aria-disabled="true"`, never `disabled`: the control stays in the Tab order                                                                                                                                                                                                    | G-T2.1b         |
| SA-T2-3 | its reason node is in the DOM at mount and linked by `aria-describedby` (never tooltip-only); the key is registered (`feed.disconnected`, `feed.private_down`, `health.protocol_incompatible`, `ratelimit.held`, `ratelimit.scope.*`)                                           | G-T2.1c, G-T2.4 |
| SA-T2-4 | CMP-079 wraps it and the CMP-019 `lock` glyph named "Not available" leads the accessible name                                                                                                                                                                                   | G-T2.1d         |
| SA-T2-5 | the label never takes `color.text.disabled`, never `opacity.disabled` (read from the computed token class, not pixels)                                                                                                                                                          | G-T2.2          |
| SA-T2-6 | `Enter` or `Space` changes nothing and re-shows the reason with one polite announcement: the live region is in the DOM before the key press and exactly one text change lands in it per press (repeated presses counted, never coalesced); a read-only panel carries one notice | G-T2.3, G-T2.5  |
| SA-T2-7 | the cell **fails** if any new-order control is operable (an enabled, focusable control whose activation sends a request)                                                                                                                                                        | T AC 4          |
| SA-T2-8 | negative cells: cancel, close and the kill switch stay **enabled** while disconnected (D02 :406–407; C-2.6); the stop and cancel reserve paths stay enabled under a per-UID or per-user limit (C-12.7)                                                                          | C-2.6, C-12.7   |

Degraded (DG) asserts permission as words in the banner (SA-DG-4); a blocking DG row's controls are `/T2`. Under
an IP-level `10018` hold the reserve cell of SA-T2-8 is **blocked on** E30-D03 #851 (F-1). AC 4's "reason in the
accessible name" is read as name + description (C-2). Every `/T2` cell runs in DEMO configuration of the stub
network only (C-2.11).

## 6. The analytics contract and the sink (BQ-4)

The contract per pattern is `14`'s entry, verbatim; a field `14` lacks is a C-row, as #1331 BQ-9 ruled (D02 :769).

| Pattern | Events and payload (`14`)                                                                                           | `14` line  | Status                            |
| ------- | ------------------------------------------------------------------------------------------------------------------- | ---------- | --------------------------------- |
| SCR-150 | `app.boot_started`, `app.boot_completed` `{durationMs, stages}`, `app.boot_failed` `{stage, reason}`                | `14` :3097 | ruled                             |
| SCR-151 | `empty_state_shown` `{surface, reason}`                                                                             | `14` :3109 | ruled                             |
| SCR-152 | `ws.disconnected`, `ws.reconnect_attempt`, `ws.reconnected`, `order.blocked_offline`                                | `14` :3137 | ruled; `ws.banner_suppressed` C-5 |
| SCR-153 | `degraded.entered` `{cause, sheddedFeatures}`, `degraded.exited` `{durationMs}`                                     | `14` :3153 | ruled                             |
| SCR-154 | `error.403_shown` (the server's audit record is not asserted)                                                       | `14` :3166 | ruled (C-7)                       |
| SCR-155 | `error.404_shown` `{route}`                                                                                         | `14` :3177 | ruled; pattern `route` C-6        |
| SCR-156 | `app.error_boundary_triggered` `{component, correlationId, stackHash}`                                              | `14` :3188 | ruled                             |
| SCR-157 | `app.version_mismatch` `{clientVersion, serverVersion, blocking}`, `app.update_applied`                             | `14` :3199 | ruled                             |
| SCR-158 | `ratelimit.hit` `{scope, endpointClass, retryAfterMs}`, `order.blocked_ratelimited`                                 | `14` :3211 | blocked on E30-D03 #851           |
| SCR-159 | `shell.offline_detected` `{cause}`, `shell.tailscale_unreachable`, `shell.gpu_unavailable`, `shell.window_restored` | `14` :3222 | ruled                             |

**The sink.** No shared analytics sink exists on `main`: each feature reports through its own seam (for example
SEV :90). The test sink taps each feature's seam; a surface with no seam is a G-row to E49-S05 (G-1), and its
analytics assertion is `blocked on` E49-S05 until the seam exists. AD-10 (D02 :739) is a story-id existence check,
`pending` until E49-S05 builds the stories (G-4).

## 7. The state-injection harness (slice B's contract; BQ-6)

### 7.1 The mechanisms (one switch)

| Mechanism                                                       | Drives                                                                                      | Precedent on `main` |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | ------------------- |
| Playwright's network layer (`@candleviewer/fixtures/e2e` stubs) | LD (held), ER, 403, 404, RL (`429`, `exchange_rate_limited` for `10018`, `22` :811–814), OF | FCFG :3–6           |
| the WS fault channel                                            | DC (sever, stale snapshot, drop)                                                            | WSW :6–8, :32–36    |
| one test-only module behind the same define                     | CR (throw in a named panel), E1–E3 (empty source), VM, DG where no health stub exists       | WSW :32–36          |

`forceState(panelId, state, options)` is typed over §2's thirteen columns and the matrix's panel ids; it renders
only a state the server already sanctioned in a test context and never bypasses server RBAC (T Security notes).

### 7.2 What the harness is not

No server-side hook ships in this ticket, so X01's T-E2 and AC-16 (X01 :97, :123) are N/A for E49-Q04 with that
reason (C-4). The module fails closed when the configuration names a live or demo environment (C-2.11).

### 7.3 The production-absence assertion (AC 3; X01 T-E1, AC-15)

The existing sentinel test (BUNDLE :2–6) is extended to the new module: the production build holds no harness
sentinel, the development or flagged build does (the proof is not vacuous), and a release build that holds it
fails (X01 :96, :122, :140). Slice B carries the security lens the DoD names; if AC-15 cannot land with the
harness, X01 :176–178's risk entry is raised, never waived.

## 8. The generator, the specs and the meta-test (slices A and C; BQ-7, BQ-8)

### 8.1 The matrix data and its self-check (slice A, the data push)

The matrix of §3.3 is mirrored as JSON (row × column × cell: `cells` or `rowNa`, `naBy`) beside the specs. A vitest
self-check reads `14`'s `### SCR-` id set and fails on a missing or an unknown id (T AC 1), on a column neither
listed nor excused, and on an NR rule that names a listed column. No YAML parser and no new dependency (C-3).

### 8.2 The generated specs (slice C)

A TypeScript generator emits one Playwright spec per row under `apps/web/e2e/state-matrix/`, tagged
`@state-matrix`, run by a flagged config in FCFG's form. The contribution to E49-Q01's pack (#1335; PRs #5850,
#5851, #5853) is one tag-map row, cited "if it merges as is"; the shard's runtime is measured and reported against
the pack's 45 min (T Performance notes). If the pack has not merged by slice C, DoD 6 stays in the `Partial:` line.

### 8.3 The meta-test (T Test plan)

A deliberately non-conformant fixture panel must fail, each on its own row: a bare spinner (SA-LD-2), a bare "No
data" (SA-EM-3), a `disabled` order button (SA-T2-2), two announcements of one condition (SA-X-5), an empty state
that opens a subscription (SA-EM-5). A suite in which any of the five passes is itself a failure.

## 9. The baseline (slice D; BQ-9)

One run on `main` after #5877 merges (re-pinned), deterministic (fake clock, no sleeps), axe on every cell. Each
entry names the panel, the state, the failed `SA-` id and the SCR clause it cites (T AC 5). `pending` rows are
listed as "not built", never as failures. Each failure is a row for E49-S05 #1385; a design-QA-only finding is a
row for E49-D01's ledger (#1330); nothing is fixed here. E08-D14's forced-state evidence (D14E08 :80) is cited,
not re-run. No pixel comparison (E49-S04).

## 10. Findings and rows for owners (never edits here)

### 10.1 F-rows

| F    | Finding                                                                                                                       | Evidence             | Routed to           |
| ---- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------------------- |
| F-1  | `10018` is an IP-level hold that gates every REST path, stop, cancel and SL included; C-12.7's reserve cell cannot hold there | `24` :2255; SA-T2-8  | E30-D03 #851 (C-8)  |
| F-2  | AC 4 asks the reason "in the accessible name"; R-2 puts it in the description                                                 | T AC 4; D02 :127–136 | C-2                 |
| F-3  | the ticket lists eleven states; the closed set is ten patterns                                                                | `14` :3088           | C-1                 |
| F-4  | `14` names `authz.denied` as the 403's audit; it is the server's, not a client event                                          | `14` :3166           | C-7                 |
| F-5  | the ticket asks server-side hooks; the default ships none                                                                     | X01 :97, :123        | C-4                 |
| F-6  | the boot's reload offer: 15 s in `14`, earlier as built                                                                       | `14` :3092; D02 F-4  | E10-D03 #197        |
| F-7  | no shared analytics sink: each feature reports through its own seam                                                           | SEV :90              | G-1                 |
| F-8  | the host pack (E49-Q01) is not on `main`                                                                                      | #1335                | DoD 6 open          |
| F-9  | "matrix documented in `03` §11" is an owner-document edit                                                                     | T DoD; `03` :310     | A-1                 |
| F-10 | the ticket's `## Test plan` and this document both describe the plan                                                          | `03` :312, :314      | this doc expands it |
| F-11 | a degraded cause has no injection mechanism named by the defaults                                                             | §7.1                 | G-3                 |
| F-12 | the order ticket, positions grid, DOM ladder and algo builders are `pending` at the base                                      | §3.3                 | slice D "not built" |

### 10.2 C-rows (contradictions; the reading taken)

| C   | Ticket says                                                           | Sources say                                                            | Reading taken                                    |
| --- | --------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------ |
| C-1 | eleven states, plus version mismatch                                  | ten patterns (`14` :3088)                                              | thirteen columns over the ten (§2)               |
| C-2 | the reason in the accessible name                                     | the reason in the description (D02 :127–136)                           | name + description (SA-T2-3, SA-T2-4)            |
| C-3 | the matrix as YAML                                                    | no parser in `apps/web`; no dependency without an ADR (T Do NOT)       | JSON (§8.1)                                      |
| C-4 | server-side hooks for 403, 404 and `10018`                            | the network layer forces them; X01 :97                                 | client-only; T-E2 / AC-16 N/A (§7.2)             |
| C-5 | analytics per `14`                                                    | `ws.banner_suppressed` is PROPOSED (`14` :3139; D02 :769)              | PROPOSED; asserted once E49-S05 wires it         |
| C-6 | `error.404_shown` `{route}`                                           | the matched pattern, never the raw path (D02 :600, D-7)                | PROPOSED (SA-404-4)                              |
| C-7 | the 403's analytics                                                   | the server records its audit record whatever the UI shows (`14` :3166) | the client asserts `error.403_shown` only        |
| C-8 | the reserve stays usable under a rate limit                           | `10018` gates stop, cancel and SL (`24` :2255)                         | the `10018` reserve cell blocked on E30-D03 #851 |
| C-9 | SCR-154 offers "Request access" which notifies the owner (`14` :3161) | no request path; no endpoint notifies the owner (D02 :617, D-3)        | PROPOSED (SA-403-5); no such control asserted    |

### 10.3 A-rows (amendments for owners; not applied)

| A   | Target                 | Proposed                                                          | Owner             |
| --- | ---------------------- | ----------------------------------------------------------------- | ----------------- |
| A-1 | `03` §11 (DoD 10)      | one pointer line to this plan and the baseline once slice D lands | the owner of `03` |
| A-2 | E49-Q01's pack tag map | one `@state-matrix` row, if the pack merges as is                 | E49-Q01 #1335     |

### 10.4 G-rows (gaps; no shape proposed)

| G   | Gap                                                                           | Owner         |
| --- | ----------------------------------------------------------------------------- | ------------- |
| G-1 | a surface with no analytics seam for the test sink to tap                     | E49-S05 #1385 |
| G-2 | `ratelimit.hit` and `order.blocked_ratelimited` are not registered (D02 :777) | E30-D03 #851  |
| G-3 | the health source per degraded cause, for the stub to force                   | E49-S05 #1385 |
| G-4 | the stories AD-10 checks for do not exist yet                                 | E49-S05 #1385 |

## 11. Open questions (owners are tickets or the owner)

| OQ   | Question                                                                                   | Owner         |
| ---- | ------------------------------------------------------------------------------------------ | ------------- |
| OQ-1 | is an SL/TP amend or an algo cancel while disconnected protective (enabled) or entry (T2)? | the owner     |
| OQ-2 | is replay paper trading a trading surface under a blocking version mismatch?               | the owner     |
| OQ-3 | do the composed `States/<frame>` stories live in `packages/ui` or `apps/web` (D02 OQ-5)?   | E49-S05 #1385 |
| OQ-4 | Stale vs Resyncing for SA-DC-7                                                             | E17-D01 (Q-G) |

## 12. Owner walkthrough checklist (≤ 10 items; posted on the issue at READY)

1. The columns: thirteen over the ten patterns (§2, C-1).
2. The row set: 149 rows; 39 row-level N/A with RN-1 … RN-3 (§3.1).
3. The NR rules read as true for the rows that cite them (§3.2; spot-check SCR-060 and SCR-140).
4. The `/T2` cells and the negative safety cells (§5, SA-T2-8).
5. The `10018` reserve cell blocked on E30-D03 (F-1, C-8).
6. The analytics contract per `14` and the PROPOSED fields (§6, C-5, C-6).
7. The harness's one switch and no server hook (§7, C-4).
8. The four slices and which one closes (§1).
9. The baseline's routing: E49-S05 rows, E49-D01's ledger, nothing fixed here (§9); a screen-reader pass
   (NVDA or VoiceOver) on SCR-152 and SCR-156 stays a human check that axe and this matrix do not replace.
10. The Sprint Review demo: one panel driven through its state set (DoD 11).

## 13. Deviations (recorded, not hidden)

- **YAML → JSON** (BQ-8, C-3): the same row × column × cell shape; no new dependency.
- **The brief's `Closes` line** (BQ-0): `Refs #1362` + `Partial:` on slices A–C; only slice D may close.
- **The single `apps/web` path** (BQ-0): this slice writes `docs/qa/` and `docs/design/_tools/`; slices B–C write
  `apps/web`; slice D writes `docs/plan/backlog/artifacts/`.
- **The PR title and scope** (C-4.10): a conventional commit; `qa` is not a commit scope, so `docs(docs): …` as
  E49-Q02 used; the ticket's "E49-Q04: …" form is not used.

## 14. The audit `docs/design/_tools/e49_q04_audit.py`

Stdlib only; it imports the shared helper `docs/design/_tools/spec_audit_lib.py` (blob `15793f79cf92`) and keeps
only this plan's rows. `--check` must give FAIL 0 on the branch; `--self-test` runs every mutation below and each
must fail only its own gate.

### 14.1 Gates

G-CITE (every cite resolves, non-blank, at its pin), G-SCRSET (the matrix's ids equal `14`'s, both ways),
G-CELLS (every cell row covers the thirteen columns exactly once; RN rows by rule), G-TOKENS (cell tokens and
D02 §4 rows valid; L-1 on SCR-010 only; `OF` on SCR-010 and SCR-001 only), G-BUILD (each `shipped` path names its
id at the base), G-ASSERT (every column has its assertion section and every SA row a source and a status),
G-ANALYTICS (each pattern's event names stand on the cited `14` line), G-T2 (§5 names every G-T2 marker),
G-RULING (the BQ section's pending form), G-CHECKLIST (≤ 10 items), G-NOCLOSE, G-PUBLIC, G-UNTOUCHED and
G-MUTLIST (14.2 equals the tool's list).

### 14.2 Mutations

| M    | Gate        | Mutation                            |
| ---- | ----------- | ----------------------------------- |
| M-1  | G-CITE      | a cite past the end of `24`         |
| M-2  | G-SCRSET    | a catalogue row dropped             |
| M-3  | G-SCRSET    | an id not in `14`                   |
| M-4  | G-CELLS     | a column neither listed nor excused |
| M-5  | G-CELLS     | an NR rule names a listed column    |
| M-6  | G-CELLS     | RN-1 on a surface row               |
| M-7  | G-TOKENS    | L-1 outside SCR-010                 |
| M-8  | G-TOKENS    | an unknown token                    |
| M-9  | G-BUILD     | a shipped path that names no id     |
| M-10 | G-BUILD     | an unknown build tag                |
| M-11 | G-ASSERT    | an assertion without a status       |
| M-12 | G-ASSERT    | a column loses its section          |
| M-13 | G-ASSERT    | the column list drifts              |
| M-14 | G-ANALYTICS | a payload field renamed             |
| M-15 | G-ANALYTICS | an event not on its line            |
| M-16 | G-T2        | the T2 rows lose the opacity ban    |
| M-17 | G-RULING    | the heading claims a ruling         |
| M-18 | G-RULING    | a bullet loses its verdict          |
| M-19 | G-CHECKLIST | an eleventh item                    |
| M-20 | G-NOCLOSE   | a closing keyword                   |
| M-21 | G-PUBLIC    | a URL                               |
| M-22 | G-PUBLIC    | an HTML comment                     |
| M-23 | G-PUBLIC    | a hex pin beside a sensitive word   |
| M-24 | G-UNTOUCHED | an owner document edited            |
| M-25 | G-UNTOUCHED | the shared helper edited            |
| M-26 | G-UNTOUCHED | over the counted ceiling            |
| M-27 | G-MUTLIST   | the list drifts                     |
