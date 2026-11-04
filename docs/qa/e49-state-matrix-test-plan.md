# E49 State matrix: black-box test plan per panel and failure mode (slice A1)

**Ticket:** E49-Q04 (#1362) · Task · Sprint 24 · labels `qa`, `type/chore`, `area/qa`, `priority/p2`, `a11y` · parent
E49 · blocked by E49-D02 (#1331). **Status: v0.2, slice A1 — a draft for the QA lead and E49-S05 (#1385); BQ-0 …
BQ-9 RULED (comment 6643527392 on the list 6642015197).** Branch `chore/e49-state-matrix`. Every slice carries
`Refs #1362` and `Partial:`; only the last slice may carry the closing line, and only once #1331 has closed.

**Base.** Every plan and repo cite is to `main` at `1708e0ad3`; the plan documents cited are byte-identical at the
ruling's pre-check base `d5f2e0bc1`. The contracts in flight are pinned at their heads, each **if it merges as is**
and re-pinned at its merge (BQ-0 a): E49-D02 as `D02` from PR #5877 at `bc0c643e9`; the E49-Q01 pack (#1335) from
#5850 at `eda159017` (`GAP`, `GAT`), #5851 at `9d6613be7` and #5853 at `960dd7bd7`; E49-D01's protocol from #5860 at
`6138f6f81` (since moved; re-pinned at its merge); the Draft #5829 at `3eebfe684`, whose chart probe this plan
leaves untouched (C-4.15).

**Honest scope.** Agent-authored. Nothing here has run: no cell is claimed passing, no harness exists yet, no
timing was measured. The plan writes the oracle E49-S05 builds against and E49-D05 (#1394) signs from; the
assertions encode E49-D02's spec, never the current build (T Dependencies). Findings are rows for their owners
(section 10), never edits to `14`, `15`, `16`, a spec or a merged test.

## Acceptance-criteria and DoD trace

States: **written** (this text specifies it), **pending** (a later slice builds it), **open** (people, the owner).

| Row    | Asks                                                                      | State   | Where                                                     |
| ------ | ------------------------------------------------------------------------- | ------- | --------------------------------------------------------- |
| AC 1   | AC "The matrix is complete and honest" — a row per panel, N/A with reason | written | §3 (149 rows, RN and NR rules); the audit's G-SCRSET      |
| AC 1b  | a catalogued panel missing from the matrix fails the self-check           | pending | §8.1 (slice A2's vitest self-check); the audit now        |
| AC 2   | AC "Every state can be driven deterministically" — within 5 s             | pending | §7 (slice B); SA-X-6                                      |
| AC 3   | AC "The harness cannot ship" — the build assertion fails the release      | pending | §7.3 (slice B); X01 :96, :122                             |
| AC 4   | AC "Trading is asserted blocked where required"                           | written | §5 SA-T2-1 … SA-T2-8; C-2                                 |
| AC 5   | AC "The baseline is actionable" — panel, state, assertion, SCR clause     | pending | §9 (slice C, the baseline folded in)                      |
| DoD 1  | matrix data complete; self-check green                                    | pending | §3 is the data's text; §8.1 the JSON and its vitest check |
| DoD 2  | harness with the production-absence assertion green                       | pending | §7 (slice B)                                              |
| DoD 3  | assertions per cell, a11y semantics and analytics payloads                | written | §4, §5, §6; implemented in slice C                        |
| DoD 4  | meta-test proves assertions can fail                                      | pending | §8.3 (slice C)                                            |
| DoD 5  | baseline published for E49-S05                                            | pending | §9 (slice C)                                              |
| DoD 6  | specs in E49-Q01's pack within budget                                     | open    | §8.2: `@ga-regression` `@ga-area-state-matrix`; GAP :8–11 |
| DoD 7  | security-engineer review of the harness gating                            | open    | slice B's `security-reviewer` lens; §12 item 9            |
| DoD 8  | coverage ≥ 80 %                                                           | pending | slices B and C                                            |
| DoD 9  | QA sign-off: fit to be E49-S05's oracle and E49-D05's evidence            | open    | §12 walkthrough                                           |
| DoD 10 | matrix documented in `03` §11                                             | written | a pointer paragraph in `03` §11.1, this slice (BQ-0 e)    |
| DoD 11 | demo at Sprint Review                                                     | open    | §12 item 10                                               |
| DoD 12 | PRs merged via the merge queue                                            | open    | the orchestrator                                          |

## The questions BQ-0 … BQ-9 — RULED (comment 6643527392)

The list is comment 6642015197 on #1362; the ruling of record is comment 6643527392 (AGREE +rider 6, AMEND 4,
ESCALATE 0). Each AMEND replaced its default here; each rider is applied where the bullet names.

- **BQ-0 — standing rules.** RULED AGREE +rider: the contracts in flight pinned at their heads "if it merges as
  is" (header); the title form `docs(frontend-platform)` / `test(frontend-platform)`, never a `qa` scope (§13); the
  helper's blob pin holds because this slice ships a Python plan checker (§14), the matrix's self-check is a vitest
  test (§8.1); spec and data files named by SCR id, never by slug (§8.2); the `03` §11 pointer paragraph (§1).
- **BQ-1 — the slices.** RULED AMEND: the plan sits flat at `docs/qa/e49-state-matrix-test-plan.md` beside
  `docs/qa/e49-exploratory-harness.md`, no new directory and no CODEOWNERS line, E40 §0's conventions kept; the
  ticket's `## Test plan` stays inline (`03` :314); the baseline folds into slice C where its run can be recorded
  there; slice B stays separate for its review lens (§1).
- **BQ-2 — every SCR id is a row.** RULED AGREE +rider: 149 rows, compared both ways with `14`; a route row's build
  status read from the route manifest (§0, G-ROUTE); host-owned modals, menus and banners take one row-level reason
  (RN-4, §3.1); the type counts are not load-bearing.
- **BQ-3 — D02's ten patterns as columns.** RULED AGREE +rider: SCR-151 expanded into its three classes and CMP-026
  `error`; rate-limited sits under SCR-158 only, no RL cell under SCR-153 (§2); one Deviation line (§13).
- **BQ-4 — the oracle and the analytics contract.** RULED AMEND: the sink is one `window` listener on `cv:analytics`
  installed by an init script (§6); SCR-154 asserts `error.403_shown` by name and leaves `rbac.denied` to the server
  (SA-403-4, C-7); AD-10 split into the §9 table's stories (checkable where built) and `States/<frame>` (G-4).
- **BQ-5 — T2, not `disabled`.** RULED AGREE +rider: SA-T2-1 … SA-T2-8 (§5); a cell asserts structure and the
  reason key, never a copy string; a T2 control is asserted only where `14` §0.5 rule 5 routes it to T2; the
  negative cells while disconnected and while rate-limited (SA-T2-8); SCR-153's banner as structure (SA-DG-4).
- **BQ-6 — the harness.** RULED AMEND: the fixture gateway and the network stubs drive every state they reach; the
  in-bundle module shrinks to a named panel's throw; a new main-entry build plus the sentinel check on the one
  define; refusal on a non-loopback API origin; `forceState` forces only degraded, empty, error and loading states;
  the flagged lane's wiring proposed on #1362; the GL and subscription counters in the test process (§7).
- **BQ-7 — the host pack.** RULED AMEND: `@ga-regression` plus exactly one `@ga-area-state-matrix`; the
  `state-matrix` area row turned `covered`; `candidate (n/10)` until ten green nightlies; `.flagged.ts` specs are not
  members; a `pending` cell emits no test; literal tagged titles (§8.2).
- **BQ-8 — data as JSON.** RULED AGREE +rider: JSON or a typed TS module, no new dependency; the self-check a vitest
  test reading `14` with `node:fs`; the generator an `.mjs` run as `node <path> --check` (§8.1, §8.2).
- **BQ-9 — the baseline.** RULED AGREE +rider: a findings list, no visual baseline; one run after #5877 merges, axe
  through `e2e/support/axe.ts`; a recorded local run until the lane is wired; E08-D14 and E10's deferred rows cited,
  not re-run (§9).

## 0. Conventions

- **Expectations come from the specification, never the build** (the E40 plan's rule, E40Q :9). Sources:
  - `T` is the ticket text of #1362; `D02` is `docs/design/E49/E49-D02.md` at `bc0c643e9` (PR #5877);
  - `X01` is `docs/security/threat-models/e49-defect-fix-path.md`; `R32` is `.claude/rules/32-design-specs.md`;
  - `14`, `15`, `03`, `05`, `22`, `24` are the plan documents, cited `file :line`;
  - `WSW` is the shared socket entry `wsWorker.ts` (`apps/web/src/lib/ws/…`), `FCFG` the fault lane's config
    `apps/web/e2e/playwright.fault.config.ts`, `BUNDLE` its bundle test
    `apps/web/test/lib/ws/faultInjection.bundle.test.ts`, `SEV` `apps/web/src/features/symbol-search/searchEvents.ts`,
    `D14E08` `docs/design/E08/E08-D14.md` and `E40Q` `docs/qa/test-plans/e40-alerts.md`;
  - `THS` is `apps/web/src/shell/bootstrap/themeStore.ts`, `ADN` `apps/web/src/features/admin/shell/AdminDenied.tsx`,
    `MAN` `apps/web/src/routes/manifest.ts`, `TREE` `apps/web/src/routes/tree.tsx`, `WSH` the fixture gateway
    `apps/web/e2e/support/wsHarness.ts`, `SYS` `apps/web/e2e/shell/system-states.spec.ts`, `MRS`
    `apps/web/e2e/motion-reduce.spec.ts`, `E17P` `qa/plans/e17-regression-pack.md`, `D17` `docs/design/E17/E17-D02.md`
    and `D30` `docs/design/E30/E30-D03.md`;
  - `GAP` is `docs/qa/e49-ga-regression-pack.md` and `GAT` `apps/web/e2e/support/gaPack.ts`, both from #5850 at
    `eda159017`, **if it merges as is**.
- **Where sources differ, nothing is guessed.** The cell follows the source this plan names, the difference is a row
  of section 10, and a cell whose answer rests on an open question is **blocked on** its owner and not executed.
- **Case ids:** `E49-TC-<nnn>-<col>`, e.g. `E49-TC-063-DC` is SCR-063's disconnected cell; assertion ids are
  `SA-<col>-<k>` (section 4). A cell runs every `SA-X-*` row plus its column's rows plus, for a `/T2` cell, §5.
- **Build-status tag** (the E40 convention, E40Q :9): `shipped` is a module under `apps/web/src` at the base that
  names the SCR id (the path is relative to `apps/web/src`); `pending` is none. **A route row** (its `14` entry names a
  `**Route:**` path) takes its tag from the route manifest (MAN :27), the source the a11y screen set derives from: the
  route's entry is `shipped` when the element `TREE` resolves for its id (TREE :44–83) is a screen, `pending` when it
  is a stub or a placeholder, an alias taking its target's; a shipped route with a `pending` row, or the reverse,
  fails the check (G-ROUTE; the slice A2 self-check after it). The tag is a pointer, not a
  claim that the surface mounts: slice C's run re-tags any `shipped` row whose surface does not mount as `pending`. A
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
contract per pattern, and the contracts of the harness (slice B), the generator, specs, meta-test and baseline
(slice C). **Out of scope (T):** fixing a non-conformance (E49-S05), pixel comparison (E49-S04), reconnect and
load-shedding behaviour (E45, E46).

**The slices** (BQ-1 as ruled; C-4.8: the counted figure is reported at each first push, a why-not-split note above
400, `large-pr-approved` asked above 800, ≈ 1,500 hard). Slice A splits at a named seam so it stays under the
ceiling: A1 the plan, A2 the data and its self-check.

| Slice | Carries                                                                                     | Title scope               | Closing line           |
| ----- | ------------------------------------------------------------------------------------------- | ------------------------- | ---------------------- |
| A1    | this plan, its audit and the `03` §11.1 pointer paragraph                                   | `docs(frontend-platform)` | never (`Partial:`)     |
| A2    | the matrix JSON and its vitest self-check (§8.1)                                            | `docs(frontend-platform)` | never (`Partial:`)     |
| B     | the panel-throw module, `forceState`, the main-entry build and sentinel check (§7)          | `test(frontend-platform)` | never (`Partial:`)     |
| C     | the generator, the specs, the meta-test and the recorded baseline run (§8, §9; D folded in) | `test(frontend-platform)` | yes, once #1331 closed |

The baseline lands at the ticket's own path, `docs/plan/backlog/artifacts/e49-state-matrix-baseline.md`; if its run
cannot be recorded in slice C's PR, it ships as a last slice D (`docs(frontend-platform)`), which then carries the
closing line instead (C-4.6 justifies a split only by the ceiling). The ticket's `## Test plan` stays as written
(`03` :312, :314: plans live in the ticket body); this document is its expansion, as the E40 and E42 plans are, and
`03` §11.1 carries one pointer paragraph to it (DoD 10; C-16.5: a pointer, no restated rule).

**Build status when written** (`origin/main` `1708e0ad3`, 2026-11-04): 28 of the 149 rows are `shipped`, 18 of
them cell rows (§3.3); the order ticket, the positions grid, the DOM ladder and every algo builder are `pending` — most
`/T2` cells will report "not built" in slice C's run, not failures (F-12). The pattern components on `main` live in
`apps/web/src/features/system-states/` and `apps/web/src/features/app-shell/`.

## 2. The columns (the state set; BQ-3)

`14` closes the set at ten patterns (`14` :3088; D02 C-1): the columns are D02's ten, SCR-151 expanded into its
three classes and CMP-026's `error` variant, so thirteen column codes; the ticket's eleven states and its harness's
version mismatch map onto them (C-1). Loading is one column whose cell names its D02 §4 row (D02 :315–325).
Rate-limited sits under SCR-158 only (D02 C-5, A-6): no rate-limited cell is drawn under SCR-153.

| Col | Ticket state                      | Pattern and component                                            | Injection (§7)                        | Assertions |
| --- | --------------------------------- | ---------------------------------------------------------------- | ------------------------------------- | ---------- |
| LD  | loading                           | D02 §4 row L-1 … L-11 (L-1 is SCR-150, SCR-010's row only)       | a held network-layer response         | §4.2       |
| E1  | empty: nothing created yet        | CMP-026 `no-data`, reason `nothing_created` (D02 §2.1, D02 :196) | an empty source (a network stub)      | §4.3       |
| E2  | empty: nothing matches the filter | CMP-026 `filtered-empty`, reason `no_matches`                    | a stub + a filter that matches none   | §4.3       |
| E3  | empty: data not recorded yet      | CMP-026 `recording-not-started`, reason `not_recorded`           | a stub with no recorded coverage      | §4.3       |
| ER  | error (a failed request)          | CMP-026 `error` → CMP-027 panel form (`15` :313); never SCR-156  | a network-layer `500` or abort        | §4.4       |
| DC  | stale / disconnected              | SCR-152 (D02 :394); stale under it by D02 §1.5's PROPOSED ladder | the fixture gateway (WSH :45–51)      | §4.5       |
| DG  | degraded                          | SCR-153 (D02 :424)                                               | the health stub or `sendSystem` (G-3) | §4.6       |
| 403 | permission denied                 | SCR-154 (D02 :450)                                               | a network-layer `403` Problem         | §4.7       |
| 404 | not found                         | SCR-155 (D02 :471)                                               | a route, or a network-layer `404`     | §4.8       |
| CR  | crashed                           | SCR-156 (D02 :489)                                               | the module throws in the named panel  | §4.9       |
| VM  | version mismatch (harness list)   | SCR-157 (D02 :513)                                               | the gateway's `welcome` (WSH :233)    | §4.10      |
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
| RN-4 | host-owned: a modal, menu or banner over the host row named; its states and gated controls are that host's  | the 32 rows marked RN-4 in §3.3 |

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

A row whose `14` type is a modal, a menu or a banner is row-level N/A (BQ-2 b; G-HOST): RN-1 or RN-2 where those
hold, RN-3 where it has no data source, else RN-4 naming its host, which must be a cell row; a gated control in an
RN-4 modal is asserted on its host's `/T2` cell (so SCR-080 carries `DG/T2` for SCR-085's arming), and the modal's own
empty, failed or held states with no host cell are G-5. 78 rows carry cells; 71 are row-level N/A.

Token forms in §3.3: `LD:L-n` names the D02 §4 row; `/T2` marks a cell whose controls are gated (§5); `404` on
an admin row is D-1's identical 404, elsewhere a deleted or unknown object id under the row's route.

### 3.3 The matrix

| SCR     | Surface                                           | Tag                                                         | Cells                                                         | N/A by                                                               |
| ------- | ------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------- | -------------------------------------------------------------------- |
| SCR-001 | Login                                             | `shipped` (`features/auth/LoginScreen.tsx`)                 | `ER` `CR` `RL` `OF`                                           | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-10, NR-13                     |
| SCR-002 | Two-factor (TOTP) challenge                       | `shipped` (`features/auth/TwoFactorStep.tsx`)               | `ER` `CR` `RL`                                                | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-10, NR-12, NR-13              |
| SCR-003 | TOTP enrolment (first login / re-enrol)           | `pending`                                                   | `LD:L-7` `ER` `CR` `RL`                                       | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-10, NR-12                     |
| SCR-004 | Forced password change                            | `shipped` (`features/auth/ChangePasswordScreen.tsx`)        | `ER` `CR` `RL`                                                | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-10, NR-12, NR-13              |
| SCR-005 | Session expired / re-auth modal                   | `shipped` (`features/session/SessionLockDialog.tsx`)        | —                                                             | RN-4 (host SCR-010)                                                  |
| SCR-006 | Step-up authentication modal (S)                  | `shipped` (`features/stepUp/StepUpDialog.tsx`)              | —                                                             | RN-4 (host SCR-010)                                                  |
| SCR-010 | App shell (global chrome)                         | `shipped` (`features/app-shell/ShellLayout.tsx`)            | `LD:L-1` `ER` `DC` `DG` `404` `CR` `VM` `RL` `OF`             | NR-2, NR-4, NR-7                                                     |
| SCR-011 | Navigation rail (expanded) & workspace switcher   | `shipped` (`features/app-shell/NavRail.tsx`)                | `LD:L-6` `E1` `ER`                                            | NR-3, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12        |
| SCR-012 | Command palette                                   | `pending`                                                   | —                                                             | RN-4 (host SCR-010)                                                  |
| SCR-013 | Hotkey cheatsheet overlay                         | `shipped` (`keymap/Cheatsheet.tsx`)                         | `LD:L-7` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12        |
| SCR-014 | Notification centre (right-rail drawer)           | `shipped` (`features/app-shell/RightRail.tsx`)              | `LD:L-6` `E1` `ER` `DC`                                       | NR-3, NR-4, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12              |
| SCR-015 | Global toast host                                 | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-016 | First-run onboarding wizard (owner)               | `pending`                                                   | `LD:L-6` `ER` `403` `CR` `RL`                                 | NR-2, NR-4, NR-5, NR-6, NR-8, NR-10, NR-12                           |
| SCR-017 | Manager/viewer onboarding (invited user)          | `shipped` (`features/invites/InviteAcceptScreen.tsx`)       | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-7, NR-10, NR-11, NR-12                    |
| SCR-018 | Guided tour / coach marks                         | `shipped` (`features/onboarding/CoachMarkTour.tsx`)         | —                                                             | RN-3                                                                 |
| SCR-019 | Setup checklist card                              | `shipped` (`features/onboarding/SetupChecklistCard.tsx`)    | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12        |
| SCR-020 | Workspace (terminal) page                         | `pending`                                                   | `LD:L-6` `E1` `ER` `DC` `DG` `404` `CR` `RL`                  | NR-3, NR-4, NR-7, NR-10, NR-12                                       |
| SCR-021 | Dock / panel system (drag, split, float)          | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-022 | Layout preset gallery                             | `pending`                                                   | —                                                             | RN-4 (host SCR-020)                                                  |
| SCR-023 | Multi-chart sync configuration                    | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-024 | Panel picker ("Add panel")                        | `pending`                                                   | —                                                             | RN-4 (host SCR-020)                                                  |
| SCR-025 | Workspace settings modal                          | `pending`                                                   | —                                                             | RN-4 (host SCR-020)                                                  |
| SCR-026 | Workspace import                                  | `pending`                                                   | —                                                             | RN-4 (host SCR-020)                                                  |
| SCR-027 | Floating panel window (Electron)                  | `pending`                                                   | `CR`                                                          | NR-1, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12                          |
| SCR-028 | Panel context menu                                | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-029 | Unsaved-changes / layout-conflict dialog          | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-030 | Chart panel (price + footprint)                   | `shipped` (`features/chart-errors/ChartErrorSurface.tsx`)   | `LD:L-2` `E3` `ER` `DC/T2` `DG` `CR` `VM/T2` `RL/T2`          | NR-3, NR-7, NR-8, NR-12, NR-15                                       |
| SCR-031 | Chart settings dialog (general)                   | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-032 | Footprint settings dialog                         | `pending`                                                   | —                                                             | RN-4 (host SCR-030)                                                  |
| SCR-033 | Deep Stats rows configuration                     | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-034 | Indicator library / add-indicator dialog          | `pending`                                                   | —                                                             | RN-4 (host SCR-030)                                                  |
| SCR-035 | Indicator settings dialog                         | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-036 | Indicator manager (object tree)                   | `pending`                                                   | `E1`                                                          | NR-3, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-16 |
| SCR-037 | Drawing toolbar & drawing properties              | `pending`                                                   | `LD:L-7` `ER` `RL`                                            | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-12               |
| SCR-038 | Profile panel (volume / delta profile + TPO)      | `pending`                                                   | `LD:L-6` `E3` `ER` `DC` `DG` `CR`                             | NR-3, NR-7, NR-8, NR-10, NR-11, NR-12, NR-15                         |
| SCR-039 | Profile settings dialog                           | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-040 | Chart trading overlay settings                    | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-041 | Symbol/interval quick-switcher (in-chart)         | `shipped` (`features/symbol-search/QuickSwitcher.tsx`)      | `LD:L-7` `E2` `E3` `ER`                                       | NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-15             |
| SCR-042 | Interval / bar-mode menu                          | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-043 | Price-scale / time-scale context menus            | `shipped` (`features/chart-price-scale/PriceScaleMenu.tsx`) | —                                                             | RN-3                                                                 |
| SCR-044 | "Go to date" dialog                               | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-045 | Chart data-table alternative (a11y)               | `shipped` (`chart/a11y/ChartDataTable.tsx`)                 | `DC` `CR`                                                     | NR-2, NR-4, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12, NR-16             |
| SCR-046 | Chart engine diagnostics overlay                  | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-047 | Chart empty / no-data state                       | `pending`                                                   | —                                                             | RN-2                                                                 |
| SCR-048 | Chart error state                                 | `pending`                                                   | —                                                             | RN-2                                                                 |
| SCR-049 | Multi-chart grid panel                            | `pending`                                                   | `CR`                                                          | NR-1, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12                          |
| SCR-050 | Heatmap + DOM ladder panel (the DeepDOM analogue) | `pending`                                                   | `LD:L-6` `ER` `DC/T2` `DG` `CR` `VM/T2` `RL/T2`               | NR-2, NR-4, NR-7, NR-8, NR-12                                        |
| SCR-051 | Heatmap & ladder settings dialog                  | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-052 | CVD / delta panel                                 | `pending`                                                   | `LD:L-6` `E3` `ER` `DC` `DG` `CR`                             | NR-3, NR-7, NR-8, NR-10, NR-11, NR-12, NR-15                         |
| SCR-053 | Tape / Time & Sales + big-trade bubbles panel     | `pending`                                                   | `LD:L-6` `E2` `ER` `DC` `DG` `CR`                             | NR-4, NR-7, NR-8, NR-10, NR-11, NR-12, NR-15                         |
| SCR-054 | OI / funding / liquidations panel                 | `pending`                                                   | `LD:L-6` `E3` `ER` `DC` `DG` `CR`                             | NR-3, NR-7, NR-8, NR-10, NR-11, NR-12, NR-15                         |
| SCR-055 | Speed-of-tape panel                               | `pending`                                                   | `DC` `DG` `CR`                                                | NR-2, NR-4, NR-7, NR-8, NR-10, NR-11, NR-12, NR-16                   |
| SCR-056 | Imbalance tracker panel                           | `pending`                                                   | `DC` `DG` `CR`                                                | NR-2, NR-4, NR-7, NR-8, NR-10, NR-11, NR-12, NR-16                   |
| SCR-057 | Market regime panel                               | `pending`                                                   | `LD:L-7` `ER` `DC` `DG` `CR`                                  | NR-2, NR-4, NR-7, NR-8, NR-10, NR-11, NR-12                          |
| SCR-058 | Detector methodology drawer ("Why estimated?")    | `pending`                                                   | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12        |
| SCR-059 | Detector settings dialog                          | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-060 | Order ticket panel (single account)               | `pending`                                                   | `LD:L-6` `ER` `DC/T2` `DG/T2` `403` `CR` `VM/T2` `RL/T2`      | NR-2, NR-4, NR-8, NR-12                                              |
| SCR-061 | Trade-group ticket (multi-account fan-out)        | `pending`                                                   | `LD:L-6` `ER` `DC/T2` `DG/T2` `403` `CR` `VM/T2` `RL/T2`      | NR-2, NR-4, NR-8, NR-12                                              |
| SCR-062 | Trade-group manager                               | `pending`                                                   | `LD:L-6` `E1` `ER` `404` `CR` `VM/T2` `RL/T2`                 | NR-3, NR-4, NR-5, NR-6, NR-12, NR-14                                 |
| SCR-063 | Positions & orders grid panel                     | `pending`                                                   | `LD:L-6` `E1` `ER` `DC/T2` `DG/T2` `403` `CR` `VM/T2` `RL/T2` | NR-3, NR-4, NR-8, NR-12                                              |
| SCR-064 | Position SL/TP editor (modal)                     | `pending`                                                   | —                                                             | RN-4 (host SCR-063)                                                  |
| SCR-065 | Scaled / ladder order builder                     | `pending`                                                   | —                                                             | RN-4 (host SCR-060)                                                  |
| SCR-066 | TWAP builder                                      | `pending`                                                   | —                                                             | RN-4 (host SCR-060)                                                  |
| SCR-067 | Iceberg (emulated) builder                        | `pending`                                                   | —                                                             | RN-4 (host SCR-060)                                                  |
| SCR-068 | Chase-limit builder                               | `pending`                                                   | —                                                             | RN-4 (host SCR-060)                                                  |
| SCR-069 | Emulated OCO / bracket builder                    | `pending`                                                   | —                                                             | RN-4 (host SCR-060)                                                  |
| SCR-070 | Algo monitor panel                                | `pending`                                                   | `LD:L-6` `E1` `ER` `DC/T2` `DG` `CR` `VM/T2` `RL/T2`          | NR-3, NR-4, NR-7, NR-8, NR-12                                        |
| SCR-071 | Risk dashboard                                    | `pending`                                                   | `LD:L-6` `ER` `DC/T2` `DG` `403` `CR` `VM/T2` `RL/T2`         | NR-2, NR-4, NR-8, NR-12                                              |
| SCR-072 | Kill-switch / freeze confirmation modal           | `pending`                                                   | —                                                             | RN-4 (host SCR-071)                                                  |
| SCR-073 | Lockout notice (manager view)                     | `pending`                                                   | —                                                             | RN-2                                                                 |
| SCR-074 | Environment switcher (Demo ↔ Live)                | `pending`                                                   | —                                                             | RN-4 (host SCR-010)                                                  |
| SCR-075 | Demo / Live banner & per-panel badges             | `pending`                                                   | —                                                             | RN-2                                                                 |
| SCR-076 | Order confirmation modal                          | `pending`                                                   | —                                                             | RN-4 (host SCR-060)                                                  |
| SCR-077 | Order rejection detail drawer                     | `pending`                                                   | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12        |
| SCR-078 | Fills / executions detail                         | `pending`                                                   | `LD:L-6` `E1` `ER` `DC`                                       | NR-3, NR-4, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12              |
| SCR-079 | Account detail drawer (trading-side)              | `pending`                                                   | `LD:L-6` `ER` `DC` `403`                                      | NR-2, NR-4, NR-6, NR-8, NR-9, NR-10, NR-11, NR-12                    |
| SCR-080 | Rules list                                        | `pending`                                                   | `LD:L-6` `E1` `E2` `ER` `DC` `DG/T2` `CR` `RL`                | NR-4, NR-7, NR-8, NR-10, NR-12                                       |
| SCR-081 | Rule editor — form mode                           | `pending`                                                   | `LD:L-6` `ER` `DG` `404` `CR` `RL`                            | NR-2, NR-4, NR-5, NR-7, NR-10, NR-12                                 |
| SCR-082 | Rule editor — node-graph mode                     | `pending`                                                   | `LD:L-6` `ER` `DG` `404` `CR` `RL`                            | NR-2, NR-4, NR-5, NR-7, NR-10, NR-12                                 |
| SCR-083 | Rule templates gallery                            | `pending`                                                   | —                                                             | RN-4 (host SCR-080)                                                  |
| SCR-084 | Rule simulation / backtest panel                  | `pending`                                                   | `LD:L-8` `E3` `ER` `DC` `DG` `CR` `RL`                        | NR-2, NR-7, NR-8, NR-10, NR-12                                       |
| SCR-085 | Rule arming dialog                                | `pending`                                                   | —                                                             | RN-4 (host SCR-080)                                                  |
| SCR-086 | Rule conflict resolver                            | `pending`                                                   | —                                                             | RN-4 (host SCR-080)                                                  |
| SCR-087 | Rule fire history / execution log                 | `pending`                                                   | `LD:L-6` `E1` `ER` `DC` `DG` `404` `CR`                       | NR-3, NR-4, NR-7, NR-10, NR-11, NR-12                                |
| SCR-088 | Rule IR inspector (advanced)                      | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-089 | Rule import / export                              | `pending`                                                   | —                                                             | RN-4 (host SCR-080)                                                  |
| SCR-090 | Alerts centre                                     | `shipped` (`features/alerts/AlertsScreen.tsx`)              | `LD:L-6` `E1` `E2` `ER` `DC` `DG` `CR` `RL`                   | NR-4, NR-7, NR-8, NR-10, NR-12                                       |
| SCR-091 | Alert editor                                      | `pending`                                                   | —                                                             | RN-4 (host SCR-090)                                                  |
| SCR-092 | Alert triggered toast / detail                    | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-093 | Journal (trade list)                              | `pending`                                                   | `LD:L-6` `E1` `E2` `E3` `ER` `CR`                             | NR-5, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12                          |
| SCR-094 | Trade detail / post-mortem                        | `pending`                                                   | `LD:L-6` `E3` `ER` `404` `CR`                                 | NR-2, NR-5, NR-6, NR-7, NR-10, NR-11, NR-12                          |
| SCR-095 | Journal analytics dashboard                       | `pending`                                                   | `LD:L-6` `E1` `E2` `ER` `CR`                                  | NR-4, NR-5, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12                    |
| SCR-096 | Journal tag manager                               | `pending`                                                   | —                                                             | RN-4 (host SCR-093)                                                  |
| SCR-097 | Replay page                                       | `pending`                                                   | `LD:L-8` `E3` `ER` `DC` `DG` `CR` `RL`                        | NR-2, NR-7, NR-8, NR-10, NR-12                                       |
| SCR-098 | Replay session setup modal                        | `pending`                                                   | —                                                             | RN-4 (host SCR-097)                                                  |
| SCR-099 | Replay paper-trading results                      | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-100 | Watchlist panel                                   | `pending`                                                   | `LD:L-6` `E1` `ER` `DC` `DG` `CR`                             | NR-3, NR-4, NR-7, NR-8, NR-10, NR-11, NR-12                          |
| SCR-101 | Watchlist manager                                 | `pending`                                                   | —                                                             | RN-4 (host SCR-100)                                                  |
| SCR-102 | Symbol search (global)                            | `shipped` (`features/symbol-search/SymbolSearch.tsx`)       | —                                                             | RN-4 (host SCR-010)                                                  |
| SCR-103 | Symbol info / instrument detail                   | `pending`                                                   | `LD:L-6` `E3` `ER` `DC`                                       | NR-2, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12                    |
| SCR-104 | Scanner / screener panel                          | `pending`                                                   | `LD:L-6` `E2` `ER` `DG` `CR` `RL`                             | NR-4, NR-5, NR-7, NR-8, NR-10, NR-12, NR-15                          |
| SCR-110 | Settings home                                     | `shipped` (`features/settings/SettingRow.tsx`)              | `CR`                                                          | NR-1, NR-6, NR-7, NR-8, NR-10, NR-11, NR-12                          |
| SCR-111 | Profile settings                                  | `pending`                                                   | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13 |
| SCR-112 | Security settings                                 | `shipped` (`features/session/SessionsSection.tsx`)          | `LD:L-6` `ER` `RL`                                            | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-12               |
| SCR-113 | Hotkey editor                                     | `shipped` (`keymap/HotkeyEditor.tsx`)                       | `LD:L-7` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12        |
| SCR-114 | Trading defaults settings                         | `pending`                                                   | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13 |
| SCR-115 | Notifications settings                            | `pending`                                                   | `ER`                                                          | NR-2, NR-4, NR-5, NR-6, NR-7, NR-8, NR-9, NR-10, NR-11, NR-12, NR-13 |
| SCR-116 | Appearance & density settings                     | `shipped` (`features/appearance/AppearanceScreen.tsx`)      | —                                                             | RN-3                                                                 |
| SCR-117 | Accessibility settings                            | `shipped` (`features/a11y-preferences/model.ts`)            | —                                                             | RN-3                                                                 |
| SCR-118 | Data & performance settings                       | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-119 | Help & about                                      | `pending`                                                   | —                                                             | RN-3                                                                 |
| SCR-120 | Admin home / overview                             | `shipped` (`features/admin/overview/OverviewPage.tsx`)      | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                   |
| SCR-121 | Admin: users list                                 | `pending`                                                   | `LD:L-6` `E1` `ER` `404` `CR`                                 | NR-3, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                   |
| SCR-122 | Admin: user detail / edit                         | `pending`                                                   | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                   |
| SCR-123 | Admin: invite user                                | `shipped` (`features/invites/AdminInviteScreen.tsx`)        | —                                                             | RN-4 (host SCR-121)                                                  |
| SCR-124 | Admin: "view as" (read-only impersonation)        | `shipped` (`features/view-as/ViewAsBanner.tsx`)             | —                                                             | RN-2                                                                 |
| SCR-125 | Admin: Bybit accounts list                        | `pending`                                                   | `LD:L-6` `E1` `ER` `404` `CR` `RL`                            | NR-3, NR-4, NR-5, NR-6, NR-10, NR-12, NR-14                          |
| SCR-126 | Admin: add / edit Bybit account                   | `pending`                                                   | `ER` `404` `RL`                                               | NR-2, NR-4, NR-5, NR-6, NR-9, NR-10, NR-12, NR-13, NR-14             |
| SCR-127 | Admin: API key rotation                           | `pending`                                                   | —                                                             | RN-4 (host SCR-125)                                                  |
| SCR-128 | Admin: key health & secrets policy panel          | `pending`                                                   | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-8, NR-9, NR-10, NR-11, NR-12, NR-14       |
| SCR-129 | Admin: account disable / delete confirmation      | `pending`                                                   | —                                                             | RN-4 (host SCR-125)                                                  |
| SCR-130 | Admin: per-account profiles list                  | `pending`                                                   | `LD:L-6` `E1` `ER` `404` `CR`                                 | NR-3, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                   |
| SCR-131 | Admin: profile editor                             | `pending`                                                   | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                   |
| SCR-132 | Admin: profile templates                          | `pending`                                                   | —                                                             | RN-4 (host SCR-130)                                                  |
| SCR-133 | Admin: symbol permissions matrix                  | `pending`                                                   | `LD:L-6` `E2` `ER` `404` `CR`                                 | NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14, NR-15                  |
| SCR-134 | Admin: risk policy (global)                       | `pending`                                                   | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                   |
| SCR-135 | Admin: audit log                                  | `pending`                                                   | `LD:L-6` `E2` `ER` `404` `CR`                                 | NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14, NR-15                  |
| SCR-136 | Admin: audit event detail                         | `pending`                                                   | `LD:L-6` `ER`                                                 | NR-2, NR-4, NR-5, NR-6, NR-8, NR-9, NR-10, NR-11, NR-12, NR-14       |
| SCR-137 | Admin: security centre                            | `pending`                                                   | `LD:L-6` `ER` `404` `CR`                                      | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                   |
| SCR-140 | Admin: recorder & storage                         | `pending`                                                   | `LD:L-6` `E1` `ER` `DC` `DG` `404` `CR`                       | NR-3, NR-4, NR-10, NR-11, NR-12, NR-14                               |
| SCR-141 | Admin: retention policy editor                    | `shipped` (`features/recorder/RecorderChrome.tsx`)          | —                                                             | RN-4 (host SCR-140)                                                  |
| SCR-142 | Admin: storage & database panel                   | `shipped` (`features/recorder/RecorderScreen.tsx`)          | `LD:L-6` `ER` `DG`                                            | NR-2, NR-4, NR-5, NR-8, NR-9, NR-10, NR-11, NR-12, NR-14             |
| SCR-143 | Admin: system health                              | `pending`                                                   | `LD:L-6` `ER` `DC` `DG` `404` `CR`                            | NR-2, NR-4, NR-10, NR-11, NR-12, NR-14                               |
| SCR-144 | Admin: incident / connectivity log                | `pending`                                                   | `LD:L-6` `E1` `E2` `ER` `404` `CR`                            | NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                         |
| SCR-145 | Admin: feature flags                              | `pending`                                                   | `LD:L-6` `ER` `DC` `404` `CR`                                 | NR-2, NR-4, NR-6, NR-10, NR-11, NR-12, NR-14                         |
| SCR-146 | Admin: backups & restore                          | `pending`                                                   | `LD:L-8` `E1` `ER` `404` `CR`                                 | NR-3, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-14                   |
| SCR-147 | Admin: exchange connectivity & rate limits        | `pending`                                                   | `LD:L-6` `ER` `DC` `DG` `404` `CR` `RL`                       | NR-2, NR-4, NR-10, NR-12, NR-14                                      |
| SCR-148 | Admin: maintenance mode                           | `pending`                                                   | `ER` `404` `CR`                                               | NR-2, NR-4, NR-5, NR-6, NR-10, NR-11, NR-12, NR-13, NR-14            |
| SCR-149 | Admin re-authentication gate                      | `pending`                                                   | `ER` `RL`                                                     | NR-2, NR-4, NR-5, NR-6, NR-8, NR-9, NR-10, NR-12, NR-13, NR-14       |
| SCR-150 | Global loading / app boot                         | `pending`                                                   | —                                                             | RN-1                                                                 |
| SCR-151 | Empty state pattern                               | `pending`                                                   | —                                                             | RN-1                                                                 |
| SCR-152 | Disconnected / reconnecting state                 | `pending`                                                   | —                                                             | RN-1                                                                 |
| SCR-153 | Degraded-mode state                               | `pending`                                                   | —                                                             | RN-1                                                                 |
| SCR-154 | Permission denied (403)                           | `pending`                                                   | —                                                             | RN-1                                                                 |
| SCR-155 | Not found (404)                                   | `pending`                                                   | —                                                             | RN-1                                                                 |
| SCR-156 | Application error boundary (500 / crash)          | `pending`                                                   | —                                                             | RN-1                                                                 |
| SCR-157 | Version mismatch / update available               | `pending`                                                   | —                                                             | RN-1                                                                 |
| SCR-158 | Rate-limited state                                | `pending`                                                   | —                                                             | RN-1                                                                 |
| SCR-159 | Offline / shell-specific states                   | `pending`                                                   | —                                                             | RN-1                                                                 |

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
| SA-X-6  | the cell's driver (§7.1) reaches the state within 5 s (a ceiling, polled on the tree; no sleep)                                                                                                                                                                                              | T AC 2                      | ruled    |
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

| SA      | Assertion                                                                                                                                          | Source                     | Status   |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | -------- |
| SA-EM-1 | CMP-026's `variant` and `reason` equal D02 §2.1's row for the column's class                                                                       | D02 :196                   | PROPOSED |
| SA-EM-2 | a heading stating the fact (at the host's level, none skipped), one cause sentence, and an action or an explicit no-action sentence for the role   | `14` :3107; `05` :273      | ruled    |
| SA-EM-3 | never an icon alone, never a bare "No data" (AP-2, AP-3)                                                                                           | `14` :3107; D02 :586       | ruled    |
| SA-EM-4 | `empty_state_shown` `{surface, reason}` once per reason entry, read at the `cv:analytics` sink; never for a load or a failure                      | `14` :3109; THS :20        | ruled    |
| SA-EM-5 | no WebGL context and no subscription for the panel under test: an init-script `getContext` counter and the gateway's subscribe frames stay at zero | `14` :3108                 | ruled    |
| SA-EM-6 | "{heading} {cause}" is announced once, politely, in the host's status region                                                                       | D02 :247                   | PROPOSED |
| SA-EM-7 | E3: the owner sees the recorder action; another role sees the sentence; the recording-start time is shown                                          | `14` :3112; D02 :202 (E-3) | ruled    |

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

| SA      | Assertion                                                                                             | Source                 | Status |
| ------- | ----------------------------------------------------------------------------------------------------- | ---------------------- | ------ |
| SA-DG-1 | a `role="status"` banner with one node for the degraded capability and one for what still works       | `14` :3151             | ruled  |
| SA-DG-2 | each affected panel's badge repeats the specific degradation in its accessible name                   | `14` :3151; D02 :230   | ruled  |
| SA-DG-3 | a blocking row is announced once as an alert; an info or warning row once as a status                 | `15` :1040             | ruled  |
| SA-DG-4 | order entry's permission is a node of the banner's structure with its reason key, never a copy string | `14` :3156; `14` :3151 | ruled  |
| SA-DG-5 | shedding is disclosed; the environment badge, positions, orders and the stale marks are never shed    | `14` :3152             | ruled  |
| SA-DG-6 | `degraded.entered` `{cause, sheddedFeatures}`, `degraded.exited` `{durationMs}`                       | `14` :3153             | ruled  |

### 4.7 403 — permission denied (SCR-154)

| SA       | Assertion                                                                                                                                                                                                  | Source                     | Status         |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | -------------- |
| SA-403-1 | a heading (one `h1` on the route form, none skipped), a sentence naming the missing capability (never a resource name), a link to a permitted page whose text names it; the route form sets the page title | `14` :3164; D02 :600 (D-2) | PROPOSED       |
| SA-403-2 | the correlation id is selectable text (a DOM text node, not an image or a pseudo-element, never `user-select: none`), rendered only when a 403 body arrived, never synthesised                             | `14` :3164; D02 :600 (D-4) | PROPOSED       |
| SA-403-3 | rendered from the 403 with no additional fetch (the request counter does not move)                                                                                                                         | `14` :3165                 | ruled          |
| SA-403-4 | `error.403_shown` by name at the sink (no payload in `14`; ADN :34 carries `variant` as built); the server's `rbac.denied` is not a client event                                                           | `14` :3166; `22` :3273     | ruled (C-7)    |
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

| SA      | Assertion                                                                                                                                                                                                                                                                                         | Marker          |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| SA-T2-1 | the control keeps its native role and its full label                                                                                                                                                                                                                                              | G-T2.1a         |
| SA-T2-2 | `aria-disabled="true"`, never `disabled`: the control stays in the Tab order                                                                                                                                                                                                                      | G-T2.1b         |
| SA-T2-3 | its reason node is in the DOM at mount and linked by `aria-describedby` (never tooltip-only); the cell asserts the reason **key**, never a copy string (D02 R-4): `feed.disconnected`, `feed.private_down` (both PROPOSED), `health.protocol_incompatible`, `ratelimit.held`, `ratelimit.scope.*` | G-T2.1c, G-T2.4 |
| SA-T2-4 | CMP-079 wraps it and the CMP-019 `lock` glyph named "Not available" leads the accessible name                                                                                                                                                                                                     | G-T2.1d         |
| SA-T2-5 | the label never takes `color.text.disabled`, never `opacity.disabled` (read from the computed token class, not pixels)                                                                                                                                                                            | G-T2.2          |
| SA-T2-6 | `Enter` or `Space` changes nothing and re-shows the reason with one polite announcement: the live region is in the DOM before the key press and exactly one text change lands in it per press (repeated presses counted, never coalesced); a read-only panel carries one notice                   | G-T2.3, G-T2.5  |
| SA-T2-7 | the cell **fails** if any new-order control is operable (an enabled, focusable control whose activation sends a request)                                                                                                                                                                          | T AC 4          |
| SA-T2-8 | negative cells: cancel, close and the kill switch stay **enabled** while disconnected (D17 :9, :429; D02 :406–407); while rate-limited, cancel, close, flatten and stop changes stay enabled and are never held (D30 :265, :268; `24` :2318, :2320–2324, :2326)                                   | C-2.6, C-12.7   |

A T2 control is asserted only where `14` §0.5 rule 5 routes it to T2 (`14` :85): a hidden admin destination, a
server refusal and form-validity disabling are not T2. Degraded (DG) asserts the banner as structure (SA-DG-4); a
blocking DG row's controls are `/T2`. Under an IP-level `10018` hold the reserve cell of SA-T2-8 is **blocked on**
E30-D03 #851 (F-1). AC 4's "reason in the accessible name" is read as name + description (C-2). The words are
E49-D03's (#1332 feeds keys, not strings) and their exact-text tests E49-S06's. Every `/T2` cell runs against the
loopback stub network only (C-2.11).

## 6. The analytics contract and the sink (BQ-4)

The contract per pattern is `14`'s entry, verbatim; a field `14` lacks is a C-row, as #1331 BQ-9 ruled (D02 :769).

| Pattern | Events and payload (`14`)                                                                                           | `14` line  | Status                            |
| ------- | ------------------------------------------------------------------------------------------------------------------- | ---------- | --------------------------------- |
| SCR-150 | `app.boot_started`, `app.boot_completed` `{durationMs, stages}`, `app.boot_failed` `{stage, reason}`                | `14` :3097 | ruled                             |
| SCR-151 | `empty_state_shown` `{surface, reason}`                                                                             | `14` :3109 | ruled                             |
| SCR-152 | `ws.disconnected`, `ws.reconnect_attempt`, `ws.reconnected`, `order.blocked_offline`                                | `14` :3137 | ruled; `ws.banner_suppressed` C-5 |
| SCR-153 | `degraded.entered` `{cause, sheddedFeatures}`, `degraded.exited` `{durationMs}`                                     | `14` :3153 | ruled                             |
| SCR-154 | `error.403_shown` by name (the server audit is not a client event)                                                  | `14` :3166 | ruled (C-7)                       |
| SCR-155 | `error.404_shown` `{route}`                                                                                         | `14` :3177 | ruled; pattern `route` C-6        |
| SCR-156 | `app.error_boundary_triggered` `{component, correlationId, stackHash}`                                              | `14` :3188 | ruled                             |
| SCR-157 | `app.version_mismatch` `{clientVersion, serverVersion, blocking}`, `app.update_applied`                             | `14` :3199 | ruled                             |
| SCR-158 | `ratelimit.hit` `{scope, endpointClass, retryAfterMs}`, `order.blocked_ratelimited`                                 | `14` :3211 | blocked on E30-D03 #851           |
| SCR-159 | `shell.offline_detected` `{cause}`, `shell.tailscale_unreachable`, `shell.gpu_unavailable`, `shell.window_restored` | `14` :3222 | ruled                             |

**The sink.** The app has one analytics seam: `cv:analytics` (`THEME_ANALYTICS_EVENT`, THS :20), a `window`
CustomEvent its emitters dispatch through (SEV :2–3 says so; ADN :34 is one). The test sink is **one `window`
listener on that event, installed by an init script** — no per-feature tap and no second sink. A surface that emits
nothing at the seam is G-1 to E49-S05, and its analytics assertion is `blocked on` E49-S05 until it does. AD-10
(D02 :739) splits: the §9 table's stories (D02 :674–703) are checked now where their CMP is built; only the composed
`States/<frame>` stories (D02 :671) are `pending` until E49-S05 builds them (G-4).

## 7. The state-injection harness (slice B's contract; BQ-6)

### 7.1 The drivers (one switch)

| Driver                                                          | Drives                                                                                   | On `main`           |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------- |
| the fixture gateway (`kill`, `restore`, `closeWith`, `desync`)  | DC (severed, desync), `err` frames (`sendErr`), DG's system causes (`sendSystem`)        | WSH :45–51, :67–74  |
| the gateway's `welcome` frame                                   | VM (SCR-157 reads it)                                                                    | WSH :233; SYS :6–10 |
| Playwright's network layer (`@candleviewer/fixtures/e2e` stubs) | LD (held), E1–E3 (an empty source), ER, 403, 404, RL (`429`; `10018`, `22` :811–814), OF | FCFG :3–6           |
| one test-only module behind the one define                      | CR only: a named panel's throw, the one state the gateway and the stubs cannot reach     | BUNDLE :14, :34     |

The module's first consumers are E10's deferred panel and route crash rows (SYS :6–10); the WS fault channel (WSW
:32–36) is used only where the gateway cannot reach. Each cell names its automation: an existing spec where one
already drives the state — `e17/transport-states.spec.ts` for SCR-152, `auth/denied.spec.ts` for SCR-154 and
SCR-155, `shell/system-states.spec.ts` for SCR-157 and SCR-159 — or the generated one, never a second copy. No
second sink, WS driver, GL probe, axe helper or route table is built.

`forceState(panelId, state)` is the typed test-process entry over the matrix's panel ids; its `state` admits only
**degraded, empty, error and loading** states, never a healthier one (connected, armed, live): the harness can
never make the UI claim a capability it lacks. It never bypasses server RBAC (T Security notes).

### 7.2 Gating and what the harness is not

- **One switch.** This ticket decides the define and the sentinel pattern and lands first; E49-D04's hook (#1333
  BQ-8) and E11-T07's island reuse them, and X01 gets D04's hook as an A-row (A-1).
- **Refusal.** The module refuses to arm unless the API origin is loopback; it cannot key on the session's
  `environment`, because the e2e stubs answer `demo` (MRS :22).
- **Placement.** The module sits outside `apps/web/src/features/auth*` and the session code.
- **No server-side hook** (a Deviation from the ticket's Technical and Security notes, C-4): X01's T-E2 and AC-16
  (X01 :97, :123) move to E49-X02, with the reason posted on #1362. AC-15 names three artefacts (X01 :122): the web
  bundle carries the module's check; the API image holds no harness; T-E1 (b)'s `CV_ENV=test` and startup-refusal
  clause (X01 :96) is server-side and N/A for a client-only module.
- **Counters in the test process.** The no-WebGL-context and no-subscription assertion (SA-EM-5) is an init-script
  `getContext` counter plus the gateway's subscribe frames; nothing is added to the bundle.

### 7.3 The production-absence assertion (AC 3; X01 T-E1, AC-15)

The bundle test builds the socket entry only (BUNDLE :14, :34), so a main-thread module needs a **new main-entry
production build plus the sentinel check**, reusing the one define (a second define would also need
`apps/web/turbo.json` and `vite.config.ts` edits). The production build holds no harness sentinel, the flagged build
does (the proof is not vacuous), and a release build that holds it fails (X01 :96, :122, :140). Slice B carries the
`security-reviewer` lens the DoD names; if AC-15 cannot land with the harness, X01 :176–178's risk entry is raised,
never waived.

### 7.4 The flagged lane

The flagged lane runs in no job (E17P :23; nothing names the fault config), so wiring it is a `_job-e2e.yml` edit:
a C-10.2 path with `security-review`, **proposed on #1362 first** (the #1335 BQ-3 / BQ-4 form; #5853 edits the same
workflows, C-4.15). Until it lands, the baseline and the shard runtime are recorded local runs, command and output
attached.

## 8. The generator, the specs and the meta-test (slices A2 and C; BQ-7, BQ-8)

### 8.1 The matrix data and its self-check (slice A2)

The matrix of §3.3 is mirrored as JSON, or a typed TS module, with the row × column × cell shape (`cells` or
`rowNa`, `naBy`), beside the specs and named by nothing but the matrix (no SCR slug in a file name). A vitest
self-check reads `14` with `node:fs`, as the pack's gate test reads `11` (`apps/web/test/e2e-ga-pack.test.ts`, if
#5850 merges as is), and fails on a missing or an unknown id both ways (T AC 1), on a column neither listed nor
excused, on an NR rule that names a listed column, and on a route row whose tag disagrees with the manifest (§0). No
YAML parser and no new dependency (C-3).

### 8.2 The generated specs (slice C)

The generator is an `.mjs` run as `node <path> --check` (Node `>=20.19.0 <21`, no TS runner); its output is the
committed specs with literal titles, and `--check` keeps them byte-equal to the data. Spec files are named by SCR id
(`scr-063.spec.ts`), never by slug: C-10.2's name globs would add `security-review` to the key and hotkey surfaces,
as would any `package.json` or workflow edit. A `pending` cell emits **no test**; it stays a data row in the matrix
report.

A test joins E49-Q01's pack by its title: **`@ga-regression` plus exactly one `@ga-area-state-matrix`** (GAP :8–11;
`state-matrix` is a reserved slug, GAT :9), never a bare `@state-matrix`; the gate reads titles with a source
regex (GAT :13), so the titles are literal. The gate reads only `*.spec.ts` and `*.real.ts` (GAT :31–37): the cells
the gateway and the stubs drive are `*.spec.ts` and eligible; the panel-throw cells are `.flagged.ts` and are not
members until the flagged lane is wired (§7.4). The gate rejects any `fixme`, `skip`, `fail`, `@flaky` or
file-level conditional skip (GAT :49–67). The contribution is the page's `state-matrix` area row (GAP :52,
`parked`) turned `covered`; a tagged test is `candidate (n/10)` until ten consecutive green nightlies with zero
retries (GAP :15–17), so "within budget" is a measured shard runtime, not membership. If the pack has not merged by
slice C, DoD 6 stays open in the `Partial:` line.

### 8.3 The meta-test (T Test plan)

A deliberately non-conformant fixture panel must fail, each on its own row: a bare spinner (SA-LD-2), a bare "No
data" (SA-EM-3), a `disabled` order button (SA-T2-2), two announcements of one condition (SA-X-5), an empty state
that opens a subscription (SA-EM-5). A suite in which any of the five passes is itself a failure.

## 9. The baseline (slice C, D folded in; BQ-9)

A findings list, not a visual-regression baseline: no `vr_update`, no pixel compared (E49-S04's). One run on `main`
after #5877 merges (re-pinned), deterministic (fake clock, no sleeps; the 5 s is a ceiling), axe on every cell
through `e2e/support/axe.ts`. Each entry names the panel, the state, the failed `SA-` id and the SCR clause it cites
(T AC 5). `pending` rows are listed as "not built", never as failures. Each failure is a row for E49-S05 #1385; a
design-QA-only finding is a row for E49-D01's ledger (#1330); nothing is fixed here. While the flagged lane runs in
no job (§7.4), the ticket's "run in CI" is a recorded local run with its command and output attached. E08-D14's
forced-state evidence (D14E08 :80) and E10's deferred rows (SYS :6–10) are cited, not re-run.

## 10. Findings and rows for owners (never edits here)

### 10.1 F-rows

| F    | Finding                                                                                                                       | Evidence             | Routed to           |
| ---- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------------------- |
| F-1  | `10018` is an IP-level hold that gates every REST path, stop, cancel and SL included; C-12.7's reserve cell cannot hold there | `24` :2255; SA-T2-8  | E30-D03 #851 (C-8)  |
| F-2  | AC 4 asks the reason "in the accessible name"; R-2 puts it in the description                                                 | T AC 4; D02 :127–136 | C-2                 |
| F-3  | the ticket lists eleven states; the closed set is ten patterns                                                                | `14` :3088           | C-1                 |
| F-4  | `14` names `authz.denied` as the 403's audit; the server records `rbac.denied`, not a client event                            | `22` :3273           | C-7                 |
| F-5  | the ticket asks server-side hooks; this ticket ships none, and T-E2 / AC-16 move to E49-X02                                   | X01 :97, :123        | C-4                 |
| F-6  | the boot's reload offer: 15 s in `14`, earlier as built                                                                       | `14` :3092; D02 F-4  | E10-D03 #197        |
| F-7  | one analytics seam (`cv:analytics`), so one sink; a surface emitting nothing there is a gap                                   | THS :20; SEV :2–3    | G-1                 |
| F-8  | the host pack (E49-Q01) is not on `main`                                                                                      | #1335                | DoD 6 open          |
| F-9  | "matrix documented in `03` §11" is a pointer paragraph, not a restated rule                                                   | T DoD; `03` :310     | this slice          |
| F-10 | the ticket's `## Test plan` and this document both describe the plan                                                          | `03` :312, :314      | this doc expands it |
| F-11 | a degraded cause has no injection mechanism named by the defaults                                                             | §7.1                 | G-3                 |
| F-12 | the order ticket, positions grid, DOM ladder and algo builders are `pending` at the base                                      | §3.3                 | slice C "not built" |
| F-13 | the manifest's `owner` is not a build flag: R-001 names an owner while its screen renders                                     | MAN :29; TREE :48    | C-10                |
| F-14 | the flagged lane runs in no job                                                                                               | E17P :23             | §7.4 (proposal)     |

### 10.2 C-rows (contradictions; the reading taken)

| C    | Ticket says                                                           | Sources say                                                         | Reading taken                                    |
| ---- | --------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------ |
| C-1  | eleven states, plus version mismatch                                  | ten patterns (`14` :3088)                                           | D02's ten, SCR-151 expanded (§2)                 |
| C-2  | the reason in the accessible name                                     | the reason in the description (D02 :127–136)                        | name + description (SA-T2-3, SA-T2-4)            |
| C-3  | the matrix as YAML                                                    | no parser in `apps/web`; no dependency without an ADR (T Do NOT)    | JSON (§8.1)                                      |
| C-4  | server-side hooks for 403, 404 and `10018`                            | the network layer forces them; X01 :97                              | client-only; T-E2 / AC-16 to E49-X02 (§7.2)      |
| C-5  | analytics per `14`                                                    | `ws.banner_suppressed` is PROPOSED (`14` :3139; D02 :769)           | PROPOSED; asserted once E49-S05 wires it         |
| C-6  | `error.404_shown` `{route}`                                           | the matched pattern, never the raw path (D02 :600, D-7)             | PROPOSED (SA-404-4)                              |
| C-7  | the 403's analytics                                                   | the server records `rbac.denied` whatever the UI shows (`22` :3273) | the client asserts `error.403_shown` only        |
| C-8  | the reserve stays usable under a rate limit                           | `10018` gates stop, cancel and SL (`24` :2255)                      | the `10018` reserve cell blocked on E30-D03 #851 |
| C-9  | SCR-154 offers "Request access" which notifies the owner (`14` :3161) | no request path; no endpoint notifies the owner (D02 :617, D-3)     | PROPOSED (SA-403-5); no such control asserted    |
| C-10 | a route row's build status from the manifest                          | `owner` marks the epic, not the build (MAN :18; TREE :48)           | the element the tree resolves (§0)               |

### 10.3 A-rows (amendments for owners; not applied)

| A   | Target              | Proposed                                                                    | Owner         |
| --- | ------------------- | --------------------------------------------------------------------------- | ------------- |
| A-1 | X01 T-E1            | E49-D04's hook and E11-T07's island reuse this ticket's define and sentinel | E49-X01       |
| A-2 | E49-Q01's pack page | the `state-matrix` area row turned `covered` (GAP :52), if it merges as is  | E49-Q01 #1335 |
| A-3 | X01 T-E2 and AC-16  | carried by E49-X02, not E49-Q04 (posted on #1362)                           | E49-X02       |

### 10.4 G-rows (gaps; no shape proposed)

| G   | Gap                                                                           | Owner         |
| --- | ----------------------------------------------------------------------------- | ------------- |
| G-1 | a surface that emits nothing at the `cv:analytics` seam                       | E49-S05 #1385 |
| G-2 | `ratelimit.hit` and `order.blocked_ratelimited` are not registered (D02 :777) | E30-D03 #851  |
| G-3 | the health source per degraded cause, for the stub to force                   | E49-S05 #1385 |
| G-4 | the composed `States/<frame>` stories AD-10 checks for do not exist yet       | E49-S05 #1385 |
| G-5 | an RN-4 modal's own empty, failed or held state with no host cell to carry it | the owner     |

## 11. Open questions (owners are tickets or the owner)

| OQ   | Question                                                                                   | Owner         |
| ---- | ------------------------------------------------------------------------------------------ | ------------- |
| OQ-1 | is an SL/TP amend or an algo cancel while disconnected protective (enabled) or entry (T2)? | the owner     |
| OQ-2 | is replay paper trading a trading surface under a blocking version mismatch?               | the owner     |
| OQ-3 | do the composed `States/<frame>` stories live in `packages/ui` or `apps/web` (D02 OQ-5)?   | E49-S05 #1385 |
| OQ-4 | Stale vs Resyncing for SA-DC-7                                                             | E17-D01 (Q-G) |

## 12. Owner walkthrough checklist (≤ 10 items; posted on the issue at READY)

1. The columns: D02's ten with SCR-151 expanded, thirteen codes (§2, C-1).
2. The row set: 149 rows; 71 row-level N/A with RN-1 … RN-4, host-owned modals by RN-4 (§3.1, G-5).
3. Route rows' build status from the manifest, and the `owner` field read as the epic (§0, C-10).
4. The `/T2` cells and the negative safety cells; the `10018` reserve cell blocked on E30-D03 (§5, F-1, C-8).
5. The harness gating: a panel throw only, the loopback refusal, `forceState` limited to degraded, empty, error
   and loading, the main-entry build and sentinel check (§7).
6. AC-16 and T-E2 moved to E49-X02, no server-side hook here (§7.2, C-4; the reason posted on #1362).
7. The flagged-lane wiring: a `_job-e2e.yml` proposal under C-10.2; recorded runs until it lands (§7.4).
8. The tag form: `@ga-regression` plus `@ga-area-state-matrix`; `.flagged.ts` specs are not members (§8.2).
9. The Security-engineer sign-off of the harness gating (DoD 7; slice B's `security-reviewer` lens).
10. The baseline's routing, a screen-reader pass on SCR-152 and SCR-156 kept human, and the Sprint Review demo:
    one panel driven through its state set (DoD 11).

## 13. Deviations (recorded, not hidden)

- **The title form** (BQ-0 b): `docs(frontend-platform): …` (A1, A2) and `test(frontend-platform): …` (B, C); never
  "E49-Q04: …" and never a `qa` scope (a label, not a commit scope).
- **YAML → JSON or a typed TS module** (BQ-8, C-3): the same row × column × cell shape; no new dependency.
- **The flat `docs/qa/` path** (BQ-1): `docs/qa/e49-state-matrix-test-plan.md`, beside E49's QA pages.
- **`@ga-area-state-matrix`** (BQ-7): the pack's tag form, not the ticket's `@state-matrix`.
- **No server-side hook** (BQ-6 c, C-4): AC-16 and T-E2 move to E49-X02.
- **Name + description** (BQ-5, C-2): AC 4's "reason in the accessible name".
- **Ten columns** (BQ-3, C-1): the ticket's eleven read as D02's ten with SCR-151 expanded.
- **The brief's `Closes` line** (BQ-0): `Refs #1362` + `Partial:` on every slice; only the last may close.

## 14. The audit `docs/design/_tools/e49_q04_audit.py`

Stdlib only; it imports the shared helper `docs/design/_tools/spec_audit_lib.py` (blob `15793f79cf92`) and keeps
only this plan's rows; the pin holds because this slice ships a Python plan checker (BQ-0 c), while the matrix's
self-check is slice A2's vitest test. `--check` must give FAIL 0 on the branch; `--self-test` runs every mutation
below and each must fail only its own gate.

### 14.1 Gates

G-CITE (every cite resolves, non-blank, at its pin), G-PINS (each ruled cite is in the plan and its line carries
the ruled text), G-SCRSET (the matrix's ids equal `14`'s, both ways), G-CELLS (every cell row covers the thirteen
columns exactly once; RN rows by rule), G-HOST (a modal, menu or banner in `14` is row-level N/A; RN-4 names a
host that is a cell row), G-TOKENS (cell tokens and D02 §4 rows valid; L-1 on SCR-010 only; `OF` on SCR-010 and
SCR-001 only), G-BUILD (each `shipped` path names its id at the base), G-ROUTE (a route row's tag equals the
manifest's status, §0), G-ASSERT (every column has its assertion section and every SA row a source and a status),
G-ANALYTICS (each pattern's event names stand on the cited `14` line), G-T2 (§5 names every G-T2 marker),
G-HARNESS (§7 states the ruled gating), G-PACK (§8.2's tag form, no test for a `pending` cell, no bare tag),
G-RULING (the RULED form, each bullet's verdict), G-CHECKLIST (≤ 10 items), G-NOCLOSE, G-PUBLIC, G-UNTOUCHED (the
plan and the tool, and the `03` pointer at exactly two added lines) and G-MUTLIST (14.2 equals the tool's list).

### 14.2 Mutations

| M    | Gate        | Mutation                                |
| ---- | ----------- | --------------------------------------- |
| M-1  | G-CITE      | a cite past the end of `24`             |
| M-2  | G-SCRSET    | a catalogue row dropped                 |
| M-3  | G-SCRSET    | an id not in `14`                       |
| M-4  | G-CELLS     | a column neither listed nor excused     |
| M-5  | G-CELLS     | an NR rule names a listed column        |
| M-6  | G-CELLS     | RN-1 on a surface row                   |
| M-7  | G-TOKENS    | L-1 outside SCR-010                     |
| M-8  | G-TOKENS    | an unknown token                        |
| M-9  | G-BUILD     | a shipped path that names no id         |
| M-10 | G-BUILD     | an unknown build tag                    |
| M-11 | G-ASSERT    | an assertion without a status           |
| M-12 | G-ASSERT    | a column loses its section              |
| M-13 | G-ASSERT    | the column list drifts                  |
| M-14 | G-ANALYTICS | a payload field renamed                 |
| M-15 | G-ANALYTICS | an event not on its line                |
| M-16 | G-T2        | the T2 rows lose the opacity ban        |
| M-17 | G-RULING    | the heading loses the ruling            |
| M-18 | G-RULING    | an AMEND read as an AGREE               |
| M-19 | G-CHECKLIST | an eleventh item                        |
| M-20 | G-NOCLOSE   | a closing keyword                       |
| M-21 | G-PUBLIC    | a URL                                   |
| M-22 | G-PUBLIC    | an HTML comment                         |
| M-23 | G-PUBLIC    | a hex pin beside a sensitive word       |
| M-24 | G-UNTOUCHED | an owner document edited                |
| M-25 | G-UNTOUCHED | the shared helper edited                |
| M-26 | G-UNTOUCHED | over the counted ceiling                |
| M-27 | G-MUTLIST   | the list drifts                         |
| M-28 | G-PINS      | a ruled cite moved off its line         |
| M-29 | G-HOST      | a host-owned modal given cells          |
| M-30 | G-HOST      | an RN-4 host that is no cell row        |
| M-31 | G-ROUTE     | a stub route tagged shipped             |
| M-32 | G-HARNESS   | the harness may force a healthier state |
| M-33 | G-PACK      | a bare pack tag                         |
| M-34 | G-UNTOUCHED | the `03` pointer grows                  |
