# E05 QA sign-off evidence pack (epic regression run)

Ticket: E05-Q03 (#263) for epic E05 (#30, design system v0: tokens, primitives, Storybook). Drafted 2026-11-02 from
`main` at `67fe8b526` and rebased onto `d5bc8e57e`; every count, leg and lane run is at `1c4f51bb5` unless a row
says otherwise (`packages/ui` is byte-identical between `1c4f51bb5` and `d5bc8e57e`). The BQ list
for #263 (comment 6576081782) is **RULED** by the orchestrator's ruling of record, comment 6576569496 (ACCEPT 10;
OVERRIDE BQ-3, BQ-4, BQ-5, BQ-8, BQ-10, BQ-11), folded in here and in the pack, `qa/plans/e05-regression-pack.md`.

QA supplies the evidence and a verdict that is **only proposed** (section 9): `approved: pending (owner)`. Nothing in this
record is the sign-off. #263 and #30 move to Done only by QA or the owner, or by the orchestrator under the owner's
delegation of 2026-10-29 (C-10.4); a deviation needs the owner's acknowledgement.

Form: `docs/plan/03-testing-strategy.md` §16 (an explicit sign-off: checkbox, named reviewer, timestamp, on the ticket,
naming the test plan result, the charters, any P2 / P3 deferred with the owner's acknowledgement, and the §11.4 white-box
items), severities per §11.3; the shape is `docs/qa/e09-signoff.md`'s. The epic DoD's QA line is
`docs/plan/02-definition-of-ready-done.md` §2.2: an epic-level regression pass executed and recorded, and coverage
thresholds met (≥ 80 % for frontend packages, `02` :34).

**(heuristic)** marks every pass an agent ran and judged: an agent is not a human QA rater, so the result is evidence
for the owner, not a QA judgement (precedent `docs/qa/a11y/e47-t01-sweep.md`:15, :34). CI runs are not marked.

## 1. Summary

| Area                             | State on 2026-11-02                                                                                        | Evidence    |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------- | ----------- |
| Children                         | every E05 child closed except #263 (this ticket) and E05-D03 (#162, design, in progress)                   | GitHub      |
| Regression pack                  | defined; per-PR = the existing a11y lane, unchanged; no nightly VR, a named deviation (CV-1, ruling BQ-4)  | pack A, B   |
| Fixed defect to red evidence     | 6 of 6 fixed defects have named red evidence on the pre-fix code (F-3: the sweep driver's `heading-order`) | pack C      |
| Epic regression run (local legs) | unit, `storybook:test`, the full axe sweep, coverage (heuristic): section 3.1                              | section 3.1 |
| Epic regression run (VR)         | CI: the merge-group lane at `1c4f51bb5` green, 5,736 cells, 0 diffs; this PR's lane added when run         | section 3.2 |
| Coverage (`packages/ui`)         | 99.51 % lines, 95.07 % branches (floor 80 %, `02` :34); heuristic, local run                               | section 6   |
| Open P0 / P1 in E05 scope        | none in `packages/ui`; #2289 (P1, Penpot `semantic-dark` token set) is an open in / out-of-scope question  | section 7   |
| Verdict                          | **PROPOSED: PASS_WITH_CARRIES, `approved: pending (owner)`**                                               | section 9   |

## 2. Acceptance criteria (E05-Q03)

| AC                                          | State                                 | Evidence                                                                                                                        |
| ------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| 1. Every fixed defect has a regression test | pass                                  | pack C: D1 to D3 (Q01), F-1 and F-2 (Q02) red on a unit-test revert; F-3 red on the sweep driver; the F-3 unit test an addition |
| 2. Per-PR pack fits the pipeline budget     | pass (per PR); no nightly VR, CV-1    | pack A: at `1c4f51bb5` shards 189 s to 270 s against 360 s, the `storybook` job 166 s against 600 s                             |
| 3. Triage workflow is unambiguous           | pass                                  | `packages/ui/README.md`, "Reviewing a diff" plus this PR's routing addendum (pack F); the VR quarantine-tag gap is CV-16        |
| 4. Epic sign-off is explicit                | proposed, `approved: pending (owner)` | section 5 (pass / fail per story group), section 8 (deviations and carries with owners), section 10 (the proposed comment)      |

DoD rows: (1) pack defined and wired per PR; no nightly VR is the named deviation CV-1 (row 1 counts as landed with it,
ruling BQ-2 / BQ-4); "tagged" is replaced by selection by name (BQ-6, Deviation); (2) met by the named red evidence
(BQ-5, BQ-6, Deviation); (3) met; (4) section 3; (5) section 10, posted on #263 as a proposal and pointed to from #30;
(6) the README section "Not breaking the design system", pointed to by a comment on E10 (#37).

## 3. The epic regression run

### 3.1 Local legs (2026-11-02, branch head on `1c4f51bb5`)

| Leg                                               | Command                                            | Result                                                                                                                                                                                                                                                                        |
| ------------------------------------------------- | -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| (c) unit (heuristic)                              | `pnpm --filter @candleviewer/ui test`              | 219 files, 4,139 tests passed, 0 failed (38 s); the F-3 test adds one per Typography story (9)                                                                                                                                                                                |
| (b) interaction + axe, default cell (heuristic)   | `pnpm --filter @candleviewer/ui storybook:test`    | 89 files, 956 stories passed, 5 skipped (the `perf` stories), 0 failed (53 s)                                                                                                                                                                                                 |
| (d) full axe sweep + `merge --strict` (heuristic) | Q02 report §7 step 2                               | 956 stories (5 `perf` excluded), 11,190 cells (956 x 6 at no-preference, 909 x 6 at reduce), 0 errored, 0 off-site; critical / serious / moderate / minor 0 / 0 / 0 / 0; negative control tripped (`image-alt`, `button-name`); `merge --strict` exit 0 (6 workers, 38.1 min) |
| (d) manual driver (heuristic)                     | Q02 report §7 step 3                               | at `67fe8b526` (905 stories): 91 of 91 driver tests, 10,774 check records, all pass; not re-run                                                                                                                                                                               |
| revert tests (heuristic)                          | pack C                                             | 6 of 6 red on revert, 6 of 6 green restored (F-3 on the sweep driver and on the added test)                                                                                                                                                                                   |
| coverage (heuristic)                              | `pnpm --filter @candleviewer/ui test:cov`          | 4,139 tests; `src/**` lines 99.51 %, statements 98.34 %, functions 99.04 %, branches 95.07 %; thresholds met (section 6)                                                                                                                                                      |
| lint, typecheck (heuristic)                       | `pnpm --filter @candleviewer/ui lint`, `typecheck` | clean at `67fe8b526`                                                                                                                                                                                                                                                          |

The driver results are counts only, no per-cell file is committed: the sweep does not differ from v1's in kind (no
finding at any impact). The manual driver was not re-run on the new base: the ruling asks for a re-run of the unit,
Storybook and axe legs only when the counts change; its result stands at `67fe8b526` (842 to 905 stories since v1).

### 3.2 VR (CI only)

Local VR is not authoritative: the token fonts draw only where installed and baselines come from the CI image only
(`packages/ui/README.md`, Visual regression). No VR run on a laptop is recorded here, and no baseline is regenerated,
moved or deleted by this PR. At the base, the merge-group run 41442501010 of `1c4f51bb5` (2026-11-02): all 14 `vr`
shards green, the summary "VR matrix: 5736 cells (956 stories x 3 themes x 2 densities)", 5,751 tests (5,736 cells, 14
font probes, 1 baseline audit), 0 diffs, shards 189 s to 270 s; the `storybook` job green in 166 s. The README edit puts
this PR on the `e2e` filter, so its own `a11y` lane runs the same matrix; its run id and shard results are added here
when CI has run it.

## 4. Exploratory and manual

No new charter was run for this ticket. The epic's exploratory and manual evidence is E05-Q01's execution passes (#261,
pass 1 6536397638, pass 2 6537431192, D2 re-run 6538599229; heuristic) and E05-Q02's v1 report
(`docs/qa/a11y/e05-q02-design-system-v1.md`, §3.1 automatable manual passes; heuristic). Their human legs are owner-run
and open (CV-7).

## 5. Pass or fail per story group

| Group                                                              | Children          | Result                        | Notes                                                                                              |
| ------------------------------------------------------------------ | ----------------- | ----------------------------- | -------------------------------------------------------------------------------------------------- |
| S01 interactive control atoms (CMP-001..010)                       | E05-S01 (#264)    | pass (heuristic)              | D1 fixed and pinned; D4 (Checkbox "Mixed" word) carried                                            |
| S02 display, feedback and utility atoms (011..039)                 | E05-S02 (#265)    | pass (heuristic)              | F-1 (SkipLink), F-2 (ErrorState), F-3 (Typography story) fixed and pinned                          |
| S03 molecules                                                      | E05-S03 (#266)    | pass (heuristic)              | D2 (Dialog), D3 (Drawer) fixed and pinned; D5 (stacked Table, high-contrast compact) carried; OQ-5 |
| S04 theming, density, preview and app-state                        | E05-S04 (#267)    | pass (heuristic)              | RbacGate notice form tested (`RbacGate.test.tsx`:346)                                              |
| Foundations (tokens, contrast gate, runtime, icons, Storybook, VR) | E05-T01..T07, K01 | pass with carries (heuristic) | the high-contrast danger pair, the font-face gap (section 8)                                       |

"Pass" means every story of the group passed legs (b), (c) and (d) in section 3.1 and its VR cells passed on the lane run
of section 3.2; a carry is an open row with an owner, none P0 or P1.

## 6. Coverage and the white-box statement (`docs/plan/03-testing-strategy.md` §11.4)

Coverage (heuristic), 2026-11-02, branch head on `1c4f51bb5`: the floor for `packages/ui` is 80 % (`02` :34, C-9.4; the
package's `vitest.config.ts` thresholds are lines, statements and functions 80 %, branches 70 %), the same reading as
`docs/qa/e09-signoff.md`:74.

| Package       | Lines   | Statements | Functions | Branches | Source                                                      |
| ------------- | ------- | ---------- | --------- | -------- | ----------------------------------------------------------- |
| `packages/ui` | 99.51 % | 98.34 %    | 99.04 %   | 95.07 %  | `pnpm --filter @candleviewer/ui test:cov` (local; `src/**`) |

White-box statement (heuristic). This is QA's reading of the §11.4 checklist for E05 from the records cited here, not a
fresh code review; the reviewers' own checklist runs on every PR:

- New or changed logic has tests at the right layer: this PR adds one unit test (F-3) and no product code; each fixed
  defect has named red evidence (pack C); the two abuse checks C63 / C64 are permanent tests (pack D).
- Every UI component has a Storybook story that passes axe: 956 stories in leg (b), every story at 6 cells in leg (d),
  every story at 6 cells in VR (section 3.2).
- No test relies on a live endpoint: the legs run loopback-only; the sweep counts off-site requests (0).
- Book engine, bar math, OMS and native stop-loss, new WS topics or REST endpoints, `x-db-enum`: not applicable (a
  component library with no order path, no network and no contract surface).

## 7. Open defects in E05 scope (GitHub, 2026-11-02)

- Open issues labelled `area/design-system` at P0 or P1: one bug, #2289 (P1, filed 2026-10-13 from E09-D06): the design
  file's `semantic-dark` token set resolves to light values. It is in the Penpot file, not in `packages/ui` (whose
  generated tokens are the source of truth). **Open question for the owner:** is #2289 in or out of E05's scope? In
  scope, it blocks Done under `03` §16 (no open P0 / P1) until fixed; out of scope, it is routed to the design lane.
  CV-14. Every other P0 / P1 in that label is an E47, E49, E21 or E26 ticket, not a defect against E05. #1478 (P2,
  CMP-244 for E10) is a feature, not a defect. D4 and D5 are unfiled rows (coordinator ruling 2026-10-31), P2 or lower
  by `03` §11.3.
- Open child: E05-D03 (#162, motion recipes, P1 design task, in progress). The epic DoD (`02` §2.2, line 1) needs it
  Done or descoped on #30 before #30 is Done; it does not block #263.

## 8. Accepted deviations and carries (owners)

| Id    | Item                                                                                                                    | Owner                                     | Status                   |
| ----- | ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- | ------------------------ |
| CV-1  | No nightly VR (pack B; ruling BQ-4: no workflow edit). If the owner wants it literally, it is the one allowed second PR | the owner                                 | Deviation                |
| CV-2  | E04 alerting path not wired for the lane; the nightly's `report` job is the route (BQ-14)                               | E04 owner                                 | Deviation                |
| CV-3  | "Tagged" composition stories replaced by named tests (BQ-6, ruled ACCEPT)                                               | the owner (acknowledgement)               | Deviation                |
| CV-4  | OQ-5: Combobox-in-Dialog and Menu-in-Drawer stories (C53, C55)                                                          | E05 design-system lane (a story PR)       | open                     |
| CV-5  | D4: Checkbox `Indeterminate` shows no visible "Mixed" word                                                              | E05 design-system lane                    | open row, unfiled        |
| CV-6  | D5: stacked Table at high-contrast compact, row fills about 1.07 : 1                                                    | E05 design-system lane                    | open row, unfiled        |
| CV-7  | Q02 OR-1..OR-8: screen-reader, keyboard-only, zoom, reduced-motion passes and the role sign-offs                        | the owner                                 | owner-run                |
| CV-8  | Q02 AD-1: pa11y-ci not run (axe is its engine)                                                                          | E05's QA owner                            | accepted (Q02 §5.1)      |
| CV-9  | Q02 FU-5: the e05-q02 drivers wired into CI or a nightly                                                                | the E05-T03 harness owner                 | open                     |
| CV-10 | High-contrast danger pair at 4.54 : 1 (under 7 : 1), routed on #30 (6440565699, 6455402494)                             | E05 tokens                                | open                     |
| CV-11 | Storybook host font gap (#30, 6532235733): the WOFF2 files are vendored (#5304), no `@font-face` declares them yet      | E05 design-system lane                    | open                     |
| CV-12 | E05-X02 accepted-risk entries expire 2026-11-20 (#30, 6562710996)                                                       | the owner                                 | dated                    |
| CV-13 | The manual protocol repeats per release candidate and is not claimed by the pack (BQ-15)                                | QA, per release candidate                 | by design                |
| CV-14 | #2289 (P1): the Penpot `semantic-dark` token set resolves to light values; in or out of E05's scope (section 7)         | the owner (the question); the design lane | open question            |
| CV-15 | E05-D03 (#162) open: needed Done or descoped for #30, not for #263                                                      | the E05 design lane                       | in progress              |
| CV-16 | `vr/matrix.ts` :40-43 has no quarantine tag, so C-9.3's quarantine cannot apply to a VR cell (pack F, ruling BQ-8)      | the VR harness owner (E05-T04)            | gate change, not this PR |

## 9. Proposed verdict

**PROPOSED: PASS_WITH_CARRIES as of 2026-11-02. `approved: pending (owner)`.** This is a proposal for the owner, not a
sign-off; the §16 checkbox, named reviewer and timestamp are the owner's or QA's act (C-10.4; e08 precedent,
`docs/qa/e08-signoff.md`:194). Every fixed E05 defect has named red evidence on its revert; the local legs (heuristic)
are green; the VR lane at the base is green; no P0 or P1 defect is open in `packages/ui`. It is not a clean pass: no
nightly VR (CV-1, a named deviation); #2289 (P1, CV-14) is an open in / out-of-scope question for the owner and, if in
scope, blocks Done under `03` §16; the owner-run legs (CV-7) and the open rows CV-4 to CV-6, CV-9 to CV-12, CV-15 and
CV-16 are carried with owners. This PR's own VR lane is added to section 3.2 when CI has run it.

`approved: pending (owner)`

## 10. Proposed QA comment for #263 (a proposal to post; pointed to from #30)

> QA verdict for E05, epic regression pass, 2026-11-02: **PROPOSED: PASS_WITH_CARRIES, `approved: pending (owner)`**.
> This is not the sign-off. Evidence: `docs/qa/e05-signoff.md` and the pack `qa/plans/e05-regression-pack.md`. Per
> story group (heuristic): S01, S02, S03, S04 pass; foundations pass with carries. All six fixed defects (D1 to D3, F-1
> to F-3) have named red evidence on their revert (F-3: the sweep driver's `heading-order`). Local legs (heuristic):
> unit 4,139 tests; Storybook 956 stories; the full axe sweep 11,190 cells at 0 / 0 / 0 / 0 with the negative control tripped; coverage `packages/ui` 99.51 % lines (floor 80 %). VR (CI): 5,736 cells, 0 diffs at the base;
> this PR's lane when run. Deviations and carries with owners: section 8 (no nightly VR; OQ-5; D4; D5; the owner-run
> OR-1..OR-8; AD-1; FU-5; the high-contrast danger pair; the font-face gap; the X02 expiry on 2026-11-20; #2289, a P1
> in the Penpot token file, an open in / out-of-scope question for the owner; E05-D03, #162, still open for #30; the
> VR quarantine-tag gap). P2 / P3 deferrals need the owner's acknowledgement (`03` §16).
>
> `approved: pending (owner)`
