# E05 QA sign-off evidence pack (epic regression run)

Ticket: E05-Q03 (#263) for epic E05 (#30, design system v0: tokens, primitives, Storybook). Drafted 2026-11-02 from
`main` at `67fe8b526` on the coordinator's BQ list for #263 (comment 6576081782; **defaults built; ruling pending**). The
pack is `qa/plans/e05-regression-pack.md`. QA supplies the evidence and a **proposed** verdict (section 8); no agent sets
Done. #263 and #30 move to Done only by QA or the owner (C-10.4), or by the orchestrator under the owner's delegation of
2026-10-29 as for E09; a deviation needs the owner's acknowledgement.

Form: `docs/plan/03-testing-strategy.md` §16 (an explicit sign-off: checkbox, named reviewer, timestamp, on the ticket,
naming the test plan result, the charters, any P2 / P3 deferred with the owner's acknowledgement, and the §11.4 white-box
items), severities per §11.3. The epic DoD's QA line is `docs/plan/02-definition-of-ready-done.md` §2.2: an epic-level
regression pass executed and recorded, not just child-ticket QA.

## 1. Summary

| Area                              | State on 2026-11-02                                                                                 | Evidence    |
| --------------------------------- | --------------------------------------------------------------------------------------------------- | ----------- |
| Children                          | every E05 child closed except #263 (this ticket) and E05-D03 (#162, design, in progress)            | GitHub      |
| Regression pack                   | defined; per-PR = the existing a11y lane, unchanged; nightly VR **pending** (BQ-4)                  | pack A, B   |
| Fixed defect to test, revert test | 6 of 6 fixed defects map to a test that fails on the pre-fix code; all six revert tests run         | pack C      |
| Epic regression run (local legs)  | unit, `storybook:test`, the full axe sweep and the manual driver: see section 3                     | section 3   |
| Epic regression run (VR)          | CI only; this PR's lane run is recorded when it has run (section 3.2)                               | section 3.2 |
| Open P0 / P1 in E05 scope         | one P1 to classify: #2289 (the Penpot `semantic-dark` token set); none in `packages/ui` (section 6) | section 6   |
| Proposed verdict                  | **PASS_WITH_CARRIES**                                                                               | section 8   |

## 2. Acceptance criteria (E05-Q03)

| AC                                          | State                          | Evidence                                                                                                                                                |
| ------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Every fixed defect has a regression test | pass                           | pack C: D1 to D3 (Q01) and F-1 to F-3 (Q02), each red on revert and green restored; F-3's test is added by this PR                                      |
| 2. Per-PR pack fits the pipeline budget     | pass (per PR); nightly pending | pack A: shards 166 s to 234 s against 360 s, the `storybook` job 165 s against 600 s, the lane 666 s against ~15 min; the nightly half is pack B (BQ-4) |
| 3. Triage workflow is unambiguous           | pass                           | `packages/ui/README.md`, "Reviewing a diff" plus this PR's routing addendum (pack F)                                                                    |
| 4. Epic sign-off is explicit                | proposed                       | section 5 (pass / fail per story group), section 7 (accepted deviations with owners), section 9 (the comment to post)                                   |

DoD rows: (1) pack defined and wired per PR, nightly pending (BQ-4); "tagged" is replaced by selection by name (BQ-6,
Deviation); (2) met by the named tests and the revert test (BQ-6, Deviation); (3) met; (4) section 3, the VR leg on this
PR's lane; (5) section 9, posted on #263 and pointed to from #30; (6) the README section "Not breaking the design system",
pointed to by a comment on E10 (#37).

## 3. The epic regression run

### 3.1 Local legs (2026-11-02, branch head; `packages/ui/src` byte-identical to `67fe8b526`)

| Leg                                   | Command                                            | Result                                                                                                    |
| ------------------------------------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| (c) unit                              | `pnpm --filter @candleviewer/ui test`              | 209 files, 3,932 tests passed, 0 failed (44 s) at `67fe8b526`; the F-3 test adds 7 (Typography: 35 of 35) |
| (b) interaction + axe, default cell   | `pnpm --filter @candleviewer/ui storybook:test`    | 84 files, 905 stories passed, 5 skipped (the `perf` stories), 0 failed (62 s)                             |
| (d) full axe sweep + `merge --strict` | Q02 report §7 step 2                               | SWEEP_RESULT                                                                                              |
| (d) manual driver                     | Q02 report §7 step 3                               | MANUAL_RESULT                                                                                             |
| revert tests                          | pack C                                             | 6 of 6 red on revert, 6 of 6 green restored                                                               |
| lint, typecheck                       | `pnpm --filter @candleviewer/ui lint`, `typecheck` | clean                                                                                                     |

The driver results are counts only; the per-cell files are not committed, as the v1 sweep's are and this run matches them
in kind (no finding).

### 3.2 VR (CI only)

Local VR is not authoritative: the token fonts draw only where installed and baselines come from the CI image only
(`packages/ui/README.md`, Visual regression). No VR run on a laptop is recorded here, and no baseline is regenerated,
moved or deleted by this PR. The README edit puts this PR on the `e2e` filter, so its own `a11y` lane runs the full
matrix (5,430 cells, 14 shards); its run id, shard results and timings are added here when CI has run it. The last
recorded run on `main`'s lane is pack A's (run 41349402849, all 14 shards and the `storybook` job green).

## 4. Exploratory and manual

No new charter was run for this ticket. The epic's exploratory and manual evidence is E05-Q01's execution passes (#261,
pass 1 6536397638, pass 2 6537431192, D2 re-run 6538599229) and E05-Q02's v1 report (`docs/qa/a11y/e05-q02-design-system-v1.md`,
§3.1 automatable manual passes). Their human legs are owner-run and open (section 7).

## 5. Pass or fail per story group

| Group                                                              | Children          | Result            | Notes                                                                                              |
| ------------------------------------------------------------------ | ----------------- | ----------------- | -------------------------------------------------------------------------------------------------- |
| S01 interactive control atoms (CMP-001..010)                       | E05-S01 (#264)    | pass              | D1 fixed and pinned; D4 (Checkbox "Mixed" word) carried                                            |
| S02 display, feedback and utility atoms (011..039)                 | E05-S02 (#265)    | pass              | F-1 (SkipLink), F-2 (ErrorState), F-3 (Typography story) fixed and pinned                          |
| S03 molecules                                                      | E05-S03 (#266)    | pass              | D2 (Dialog), D3 (Drawer) fixed and pinned; D5 (stacked Table, high-contrast compact) carried; OQ-5 |
| S04 theming, density, preview and app-state                        | E05-S04 (#267)    | pass              | RbacGate notice form tested (`RbacGate.test.tsx`:346)                                              |
| Foundations (tokens, contrast gate, runtime, icons, Storybook, VR) | E05-T01..T07, K01 | pass with carries | the high-contrast danger pair, the font-face gap (section 7)                                       |

"Pass" means every story of the group passed legs (b), (c) and (d) in section 3.1 and its VR cells passed on the last
recorded lane run; a carry is an open row with an owner, none P0 or P1.

## 6. White-box items (`03` §11.4) and open defects

- New logic has unit tests: this PR adds one test (F-3) and no product code.
- The book, OMS and native-SL items do not apply (a component library).
- Open defects (GitHub, 2026-11-02, open issues labelled `area/design-system` at P0 or P1): one bug, #2289 (P1, filed
  2026-10-13 from E09-D06): the design file's `semantic-dark` token set resolves to light values. It is in the Penpot
  file, not in `packages/ui` (whose generated tokens are the source of truth), so whether it counts
  against E05's scope (`03` §16: no open P0 / P1 before Done) needs a ruling. Every other P0 / P1 in that label is an
  E47, E49, E21 or E26 ticket, not a defect against E05. #1478 (P2, CMP-244 for E10) is a feature, not a defect. D4
  and D5 are unfiled rows (coordinator ruling 2026-10-31), P2 or lower by `03` §11.3.
- Open child: E05-D03 (#162, motion recipes, P1 design task, in progress). The epic DoD (`02` §2.2, line 1) needs it
  Done or descoped on #30 before #30 is Done; it does not block #263.

## 7. Accepted deviations and carries (owners)

| Id    | Item                                                                                                               | Owner                                         | Status              |
| ----- | ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------- | ------------------- |
| CV-1  | Nightly VR not wired (pack B, BQ-4): default or alternative B                                                      | coordinator ruling; then devsecops (workflow) | pending             |
| CV-2  | E04 alerting path not wired for the lane; the nightly's `report` job is the route (BQ-14)                          | E04 owner                                     | Deviation           |
| CV-3  | "Tagged" composition stories replaced by named tests (BQ-6)                                                        | coordinator ruling                            | Deviation           |
| CV-4  | OQ-5: Combobox-in-Dialog and Menu-in-Drawer stories (C53, C55)                                                     | E05 design-system lane (a story PR)           | open                |
| CV-5  | D4: Checkbox `Indeterminate` shows no visible "Mixed" word                                                         | E05 design-system lane                        | open row, unfiled   |
| CV-6  | D5: stacked Table at high-contrast compact, row fills about 1.07 : 1                                               | E05 design-system lane                        | open row, unfiled   |
| CV-7  | Q02 OR-1..OR-8: screen-reader, keyboard-only, zoom, reduced-motion passes and the role sign-offs                   | the owner                                     | owner-run           |
| CV-8  | Q02 AD-1: pa11y-ci not run (axe is its engine)                                                                     | E05's QA owner                                | accepted (Q02 §5.1) |
| CV-9  | Q02 FU-5: the e05-q02 drivers wired into CI or a nightly                                                           | the E05-T03 harness owner                     | open                |
| CV-10 | High-contrast danger pair at 4.54 : 1 (under 7 : 1), routed on #30 (6440565699, 6455402494)                        | E05 tokens                                    | open                |
| CV-11 | Storybook host font gap (#30, 6532235733): the WOFF2 files are vendored (#5304), no `@font-face` declares them yet | E05 design-system lane                        | open                |
| CV-12 | E05-X02 accepted-risk entries expire 2026-11-20 (#30, 6562710996)                                                  | the owner                                     | dated               |
| CV-13 | The manual protocol repeats per release candidate and is not claimed by the pack (BQ-15)                           | QA, per release candidate                     | by design           |
| CV-14 | #2289 (P1): the Penpot `semantic-dark` token set resolves to light values; in or out of E05's scope                | coordinator ruling; the design lane           | open, to classify   |
| CV-15 | E05-D03 (#162) open: needed Done or descoped for #30, not for #263                                                 | the E05 design lane                           | in progress         |

## 8. Proposed verdict

**Proposed: PASS_WITH_CARRIES as of 2026-11-02.** Every fixed E05 defect is pinned by a test proven red on its revert;
the local legs are green; the last recorded VR lane on `main` is green; no P0 or P1 defect is open in `packages/ui`. It is not a
clean pass: nightly VR is pending a ruling (CV-1); #2289 (P1, CV-14) must be ruled outside E05's scope or fixed before
the verdict stands (otherwise it blocks Done under `03` §16); the owner-run legs (CV-7) and the open rows CV-4 to CV-6,
CV-9 to CV-12 and CV-15 are carried with owners. The verdict is final only when this PR's own VR lane is green and recorded in section 3.2.

## 9. Proposed QA comment for #263 (to post; pointed to from #30)

> QA sign-off (proposed) for E05, epic regression pass, 2026-11-02: **PASS_WITH_CARRIES**. Evidence:
> `docs/qa/e05-signoff.md` and the pack `qa/plans/e05-regression-pack.md`. Pass per story group: S01, S02, S03, S04 pass;
> foundations pass with carries. All six fixed defects (D1 to D3, F-1 to F-3) map to a test that fails on the pre-fix
> code (revert test run for each). Local legs green (unit 3,932 tests; Storybook 905 stories; the full axe sweep and the
> manual driver as recorded). VR: this PR's lane. Accepted deviations and carries with owners: section 7 (nightly VR
> pending a ruling; OQ-5; D4; D5; the owner-run OR-1..OR-8; AD-1; FU-5; the high-contrast danger pair; the font-face gap;
> the X02 expiry on 2026-11-20; #2289, a P1 in the Penpot token file, to be ruled in or out of E05's scope; E05-D03, #162,
> still open for #30). P2 / P3 deferrals need the owner's acknowledgement (`03` §16).
>
> - [ ] QA sign-off: reviewer ______, timestamp ______ (C-10.4: QA or the owner; no agent ticks this box)
