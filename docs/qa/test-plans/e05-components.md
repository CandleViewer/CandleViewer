# E05 Design system v0: component black-box test plan and exploratory charter

Ticket: E05-Q01 (#261). Status: v1.0, the deliverable of #261, with the orchestrator's ruling of record applied (#261 comment
6535944497, 2026-10-30, under the owner's 2026-10-29 delegation, on the before-writing question list BQ-01 to BQ-24, comment
6533789549, read from `main` `174c691e1`): all 24 stand as proposed, with riders; section R carries every BQ as `RULED`. The plan
holds the conventions, the scope and the lateness report, the test matrix, the cases per component family of the v0 set, the six
composition scenarios, the keyboard-only pass and the delegated screen-reader pass, the two abuse legs and the jank observation,
the exploratory charter, the time-control table, the environment and reset protocol, the surface catalogue, the entry and exit
criteria with the regression subset, what it references, the traceability and the open questions with the † table. It contains
no code and adds no story, hook, tag, probe or test (BQ-15, ruled).

## 0. Conventions

- **Base and READY sha.** The ruling folded in on `origin/main` `b8575c6f1b71bbb480490768aaf439047a39c861` (`b8575c6f1`), fetched
  and rebased onto before the ruling's commit; **this is the READY sha**. The first draft was written at `b8575c6f1` and the BQ
  list read `174c691e1`; the commits since touch no file under `packages/ui/`, `apps/web/` or `docs/plan/15-*`. Every † and
  blocked row of section 10 was re-grepped at `b8575c6f1`: **no status changed** (CMP-062 ThemeSwitcher, CMP-063 DensityToggle,
  CMP-228 PreviewTile, `FormTooltip`, `FormNotice`, a 500-row story, an advisory state: still none under `packages/ui/src` or
  `apps/web/src`; `pattern.hatch.unprotected` still named only by `Callout.tsx`; 4,356 VR baselines). The visual-regression
  baselines cited throughout were merged at `6dc942aff` (#5104, E05-T04), an ancestor of the base.

- **Lateness report (no waiver claimed; BQ-23, ruled: reported, no waiver).** The ticket is Sprint 04, 2026-10-16 to 2026-10-22
  (`docs/plan/backlog/_tools/calendar_cv.py`:13–15: one-week sprints from Friday 2026-09-25). Its blocker E05-S03 (#266) closed
  on 2026-10-29 02:46Z and was declared Done on its engineering evidence and the delegated Security sign-off in the orchestrator's
  note of 2026-10-29 07:56Z (#261 comment 6491190592), so no work on this ticket could start before Sprint 05's last day. The
  plan is written on 2026-10-30, day 1 of Sprint 06 (2026-10-30 to 2026-11-05), eight days past the ticket's sprint, and READY is
  targeted inside Sprint 06. E05-Q02 (#262) and E05-Q03 (#263), also Sprint 04, are open and unassigned at the base: the epic's QA
  lane is late as a whole, not this ticket alone. The calendar is the owner's; this paragraph reports, it does not excuse.

- **Expectations come from the merged specification, not the implementation.** Each case cites its source:
  - `S01.k` to `S04.k` is scenario k, in ticket order, of E05-S01 to E05-S04's `## Acceptance criteria` in
    `docs/plan/backlog/E05.json` (seven each, 28 in all); `#261` is this ticket's body (Scope, Technical notes, Security notes,
    Accessibility notes, Performance notes);
  - `15` is `docs/plan/15-component-catalogue.md`, cited by `CMP-nnn` entry and line (Props, States, A11y, Storybook and the
    "As built" lines: 58 at the base); `16` is `docs/plan/16-design-system-brief.md`; `05` is
    `docs/plan/05-accessibility-standard.md`; `03` is `docs/plan/03-testing-strategy.md`; `02` is
    `docs/plan/02-definition-of-ready-done.md`;
  - `D02` is the merged E05-D02 slice plan: `docs/design/E05/E05-D02.md` (actions and selection), `E05-D02-data-display.md`,
    `E05-D02-form-controls.md`, `E05-D02-feedback-overlays.md`, `E05-D02-rest.md`; `D03` is `docs/design/E05/E05-D03.md`; `A-nn`
    is an A-row of `docs/design/E05/E05-S01-catalogue-a-rows.md`; T2 is the gated-control treatment of
    `docs/design/E09/E09-D09.md` §2.2 (the control keeps its role and full label, takes `aria-disabled="true"`, never `disabled`,
    and its reason as the description);
  - `HO-S01` and `HO-S03` are the hand-offs `docs/plan/qa/E05-S01-qa-handoff.md` and `docs/plan/qa/E05-S03-qa-handoff.md`
    (scenario-name to test index; white-box evidence this plan cites and never re-runs); `SR-S03` is
    `packages/ui/src/docs/screen-reader-spot-check-e05-s03.md` and `SR-S02` is `packages/ui/src/docs/screen-reader-spot-check.md`;
  - `store` is `packages/ui/src/theme/store.ts`; `preview` is `packages/ui/.storybook/preview.ts`; `vr/*` is `packages/ui/vr/*`;
    `Atoms.mdx` and `Molecules.mdx` are `packages/ui/src/docs/*.mdx` (the keyboard tables: `Atoms.mdx`:11–479,
    `Molecules.mdx`:23–622); a story is `Title` `Name` as `packages/ui/src/components/<Component>.stories.tsx` exports it, cited
    with the export's line; `E13` is the template plan `docs/qa/test-plans/e13-indicators.md` and `E16` is
    `docs/qa/test-plans/e16-recorder.md` (their form is followed, never their content).
- **Where the ticket text and the merged design differ**, the case follows the merged design (`E16`'s rule, `E13` BQ-03;
  ruled here as BQ-08): each difference is a row in section 10 and the case is marked **blocked on** its owner. Nothing is
  guessed: a component, story, string, token or number that no merged source states is a † or a blocked row with an owner, never
  a value of this plan's.
- **Environment:** the built Storybook of `packages/ui` served on loopback (section 5): no backend, no network, no fixture from
  `packages/fixtures`, no key, account or production data. Every surface is a story and the story's inline data is its fixture
  (ruled as BQ-13). No host, key, account, user name or private record id appears in a step or an evidence file.
- **Case ids:** `E05-Q01-Cnn`, numbered in section order (ruled as BQ-05; the ticket names no scheme; E05-Q03 (#263) references
  these ids for its "one story per fixed composition defect"). The line under the id names the layer (`03` §2: `e2e`, `a11y`,
  `perf`, `security`; every case here is black-box against the built Storybook), the family and owning story (section 1) and what
  it mirrors. **[R]** joins the regression subset (section 7); **[F]** marks a failure path; every case ends with a **Blocked on**
  line naming an owner, or `none`.
- **Oracles, in order (ruled as BQ-08):** (1) the merged `15` entry — Props, States, A11y, the Storybook list and the "As built"
  lines — and the `D02` slice text; (2) the story's play assertion or the hand-off's named test, cited as white-box evidence,
  never re-run by the plan; (3) the VR baseline PNG for the at-rest look (presentation; the next bullet); (4) the `storybook`
  job's axe result for the story (`.github/workflows/_job-a11y.yml`:188–296: zero serious or critical) where the case touches
  semantics. A case that reads and changes nothing names its secondary oracle as "none (a read)". **Strings:** there is no E05
  copy deck. A string is asserted verbatim only where `15`, an A-row, `RBAC_REASONS` (`packages/ui/src/components/rbacReasons.ts`
  :8–14) or `SKIP_LINK_COPY` (`packages/ui/src/components/SkipLink.tsx`:10–14) states it; otherwise the case asserts presence and
  role, not words.
- **The VR baselines as the visual oracle (ruled as BQ-09).** `vr/baselines/{story-id}--{theme}--{density}.png`: 4,356 cells
  at the base, 726 stories × the 3 × 2 of `store`:9–10 (`dark | light | high-contrast` × `compact | comfortable`), committed and
  compared by `pnpm --filter @candleviewer/ui vr` (`vr/vr.spec.ts` through `vr/playwright.config.ts`) against the built
  Storybook's `storybook-static/index.json`, the matrix's only source (`vr/settings.ts`:12–14). The plan **never re-captures**: a
  story's six cells are its at-rest visual oracle and the plan's visual legs are the states VR cannot hold. What VR does not cover,
  so the plan runs it by hand: the viewport is 1920 × 1080 at one device pixel per CSS pixel only (`vr/settings.ts`:70–72;
  ADR-0019 `docs/plan/27-adrs/ADR-0019-visual-regression-tooling.md`:102), so 1280 × 800 and 200 % browser zoom are manual; the
  shot is taken under `prefers-reduced-motion: reduce`, which the runtime writes as `data-motion="reduce"` (`REDUCED_MOTION`,
  `vr/settings.ts`:52), so motion-safe frames are manual; hover and mid-transition states are not captured (the settle rule
  freezes the page after the story's last 1 s timer, `vr/settings.ts`:61); `Date` is frozen at `2026-10-27T14:02:00Z` (:43); the
  `perf`-tagged stories are excluded by tag (`vr/matrix.ts`:41 `EXCLUDED_TAGS`: Table `Perf200Rows`, ThemeRuntime
  `StyleRecalcBenchmark`, FuzzyList `Perf1000Items`, Sparkline `Perf200Points`); the tolerance is 2 % of the clip or 25 px at
  colour distance 0.2 (:35). The pinned-global matrix stories (`AllAtoms` and `AllMolecules` `DarkCompact` …
  `HighContrastComfortable`, plus `AllMolecules`' Dialog, ConfirmDialog, Drawer and CommandPalette sets) are crossed with the
  globals again by the harness, so of their 36 cells each the plan cites only the six whose story cell equals the global cell.
  Diff triage and baseline updates are `packages/ui/README.md`'s "Visual regression (E05-T04)" workflow (a CODEOWNER of
  `vr/baselines/` approves; `vr_update` on `_job-a11y.yml`), referenced, not restated.
- **Time:** section 4 binds every case. The only clocks are the components' own; every manual case waits real time ≤ 20 s and
  no case sleeps in automation (C-13.7, `CONSTITUTION.md`:890) — automation is E05-Q03's and the stories' own.

## 1. Scope, families and deviations

**In scope (ruled as BQ-01, BQ-02):** the **v0 set**, the 62 CMP ids of E05-D02's Scope (`docs/plan/backlog/E05.json` E05-D02
"Scope / Deliverables"): atoms CMP-001 to CMP-039 (39); molecules CMP-040, 041, 042, 043, 044, 045, 046, 047, 048, 049, 050,
054, 059, 062, 063, 065, 069 (17); cross-band CMP-079, 085, 089, 090, 091, 228 (6). **Built at the base: 59** — every export of
`packages/ui/src/components/index.ts` (the fifteen E05-S03 molecules `HO-S03`:3 names; the Organisms band holds ForbiddenState,
NotFoundState and GlobalErrorBoundaryFallback). **Not built: 3** — CMP-062 ThemeSwitcher (`15`:702), CMP-063 DensityToggle
(`15`:712), CMP-228 PreviewTile (`15`:2920); E05-S04 (#267, open) ships them, its merged slices A–D being CMP-085 (#4773), CMP-079
(#4865), CMP-089 / CMP-090 (#4867) and CMP-091 (#4872). The 28 Gherkin scenarios S01.1 to S04.7, the ticket's six composition
scenarios, its two abuse steps, its mandatory keyboard-only pass, its jank observation, and the orchestrator's 2026-10-29 charter
line (the NVDA + Chromium screen-reader pass on CMP-043, CMP-048 and CMP-049 that fills `SR-S03`'s blank log) are all covered.

**Out of scope (referenced only, section 8):** E05-Q02 (#262) the a11y audit, E05-Q03 (#263) the VR regression pack and the epic
sign-off, E05-X02 (#272) the security review, E05-D04 (#259) and E05-D05 (#260); automated test implementation (the stories' and
E05-Q03's); application screens. Components in `packages/ui` outside the set — SymbolPicker (CMP-219), SymbolSearchInput
(CMP-160), FuzzyList (CMP-213), ColorConventionLegend (`Trading/*`) and the `Foundations/Placeholder` story — are E08-S09's and the
shell's and are not cases here.

**Families (ruled as BQ-03).** The five slices of the merged E05-D02 plan, each component block naming its owning story so
the ticket's "grouped by band" traceability holds in section 9:

| Section | Family (D02 slice)                                           | Components                                                                                                                                                                                                                                                                                               | Owning stories                                                          | VR stories · cells at the base |
| ------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------ |
| 3.1     | actions and selection (`E05-D02.md`:9–11)                    | CMP-001 Button, 002 IconButton, 003 SegmentedControl, 004 Toggle, 005 Checkbox, 006 RadioGroup, 010 Slider, 014 Spinner, 019 Icon, 031 ColorSwatch / ThemeChip, 039 FocusRing                                                                                                                            | S01 (001–006, 010); S02 (014, 019, 031, 039)                            | 132 · 792                      |
| 3.2     | data display and text (`E05-D02-data-display.md`:10–12)      | CMP-011 Tag, 012 Badge, 013 Avatar, 018 Divider, 020 Typography, 021 Link, 024 Sparkline, 025 AvatarGroup, 030 Divider-Label, 032 ConfidenceDots, 033 CopyButton, 037 SwatchLegendItem                                                                                                                   | S02                                                                     | 94 · 564                       |
| 3.3     | form controls (`E05-D02-form-controls.md`:10–13)             | CMP-007 TextInput, 008 NumericStepperInput, 009 Select, 034 MaskedValue, 040 FormField, 047 DatePicker / DateRangePicker, 048 Combobox, 049 Table, 054 SearchBox, 065 FormSection, 079 RbacGate                                                                                                          | S01 (007–009); S02 (034); S03 (040–065); S04 (079)                      | 164 · 984                      |
| 3.4     | feedback and overlays (`E05-D02-feedback-overlays.md`:11–14) | CMP-015 Skeleton, 016 Tooltip, 017 Popover, 023 ProgressBar, 026 EmptyState, 027 ErrorState / InlineError, 028 Callout, 029 SkeletonChart, 038 InlineSpinnerText, 041 Menu, 043 Dialog, 044 ConfirmDialog, 045 Toast, 046 Drawer, 089 ForbiddenState, 090 NotFoundState, 091 GlobalErrorBoundaryFallback | S02 (015–038); S03 (041–046); S04 (089–091)                             | 190 · 1,140                    |
| 3.5     | the rest (`E05-D02-rest.md`:21–22)                           | CMP-022 Kbd, 035 Countdown, 036 KeyValueRow, 042 Tabs, 050 Card, 059 CommandPalette, 062 ThemeSwitcher†, 063 DensityToggle†, 069 InfoPanel, 085 SkipLink, 228 PreviewTile†                                                                                                                               | S02 (022, 035, 036); S03 (042, 050, 059, 069); S04 (062, 063, 085, 228) | 67 · 402 († none)              |
| —       | the pinned matrix stories                                    | `Atoms/All atoms matrix` (6), `Molecules/All molecules matrix` (30)                                                                                                                                                                                                                                      | S01, S03                                                                | 36 · 216                       |

The counts are the baseline PNGs under each `Title` at the base divided by six; Divider-Label's stories live under
`Atoms/Divider` (`Labelled`, `Divider.stories.tsx`:67). Sections 3.6 to 3.9 hold the compositions, the keyboard-only and
screen-reader passes, the abuse legs with the jank observation, and the exploratory charter.

**Read first:** `03` §11.1–11.3 and §16; `02` §3.2 (`02`:72–77); `16` §4 and §8 (`16`:165–167, :266–269); `05` §3.1, §5.7, §7
and §8.1 (`05`:30–33, :131, :202–221); `15` §0.3 (`15`:33–42) and the 62 entries; the five `D02` slices; `HO-S01`, `HO-S03`,
`SR-S03`, `SR-S02`; `packages/ui/README.md` "Visual regression (E05-T04)".

**Deviations from the ticket** (repeated in the PR; ruled as BQ-04, BQ-05, BQ-21, BQ-22): the path is
`docs/qa/test-plans/e05-components.md` (the ticket says "under `docs/plan/` or the QA space"; the template's folder); the case ids
are `E05-Q01-Cnn` (the ticket names none); the branch is `test/e05-q01-components-plan` (the ticket's
`chore/design-system-test-plan` is a `chore` type for a `type/test` ticket) and the PR title is a conventional commit (the
ticket's `E05-Q01: …` form is not, C-4.10); the PR closes #261 on the document, with section 7 stating what runs today and what
waits, the execution pass following on #261 as comments in the same sprint (Reading A of BQ-22; Reading B, that #261 stays open
until the runnable set has recorded results, was not taken: the ruling is Reading A, and the execution pass is owed, not waived). Items the merged design reads differently from
the ticket, each a section 10 row: the "500-row table story" (none; `15`:585 bounds v0 at 200 rows), the below-1280 × 800
advisory state (the shell's, not a `packages/ui` state), "Chromium at the Electron version" (no pin), the Combobox-inside-Dialog
and Menu-inside-Drawer stories (none), RbacGate's `FormTooltip` / `FormNotice` stories (not exported), A-12 (no visible reason
echo on an atom), the S04 trio (unbuilt), the D03 motion recipes (#3174 open).

## R. Rulings applied

The before-writing question list (BQ-01 to BQ-24, #261 comment 6533789549, read from `main` `174c691e1`) was ruled by the
orchestrator on 2026-10-30 under the owner's 2026-10-29 delegation (ruling of record, #261 comment 6535944497): all 24 stand as
proposed, with riders; each row below states the ruling and carries its stamp, and the sections named in the last-but-one column
carry the wording. Eight BQs had been named for confirmation: BQ-02, BQ-07, BQ-10, BQ-16, BQ-20, BQ-21, BQ-22, BQ-23.

| BQ    | Question                             | As ruled                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Sections    | Status                                                                        |
| ----- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ----------------------------------------------------------------------------- |
| BQ-01 | stories and scenarios covered        | as proposed, plus the delegated NVDA pass on CMP-043 / 048 / 049; the unbuilt CMP-062 / 063 / 228 (#267) are cases marked blocked on E05-S04, never asserted                                                                                                                                                                                                                                                                                                                          | 1, 3, 9     | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-02 | the v0 set by CMP id                 | as proposed: the 62-id v0 set; 59 built, the three unbuilt blocked on E05-S04, never asserted                                                                                                                                                                                                                                                                                                                                                                                         | 1, 3, 6     | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-03 | families                             | as proposed: the five E05-D02 families, the owning story on every block                                                                                                                                                                                                                                                                                                                                                                                                               | 1, 3        | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-04 | path                                 | as proposed: `docs/qa/test-plans/e05-components.md`; the ticket's path wording is a deviation row                                                                                                                                                                                                                                                                                                                                                                                     | 1           | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-05 | case ids                             | as proposed: `E05-Q01-Cnn` in section order                                                                                                                                                                                                                                                                                                                                                                                                                                           | 0, 1        | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-06 | sections and case shape              | as proposed: the template's ten sections plus R; section 5 renamed with its reason; the components' own clocks are the only clocks, no sleep in anything automated (C-13.7)                                                                                                                                                                                                                                                                                                           | all         | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-07 | the matrix                           | as proposed: the 3 × 2 runs through the VR baselines, never re-captured, what VR does not cover stated in section 0; motion / zoom / viewport as named cells; the below-1280 × 800 advisory state is the shell's (†, blocked on the E15 / E10 owner)                                                                                                                                                                                                                                  | 2, 3        | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-08 | oracle ladder                        | as proposed: the oracle ladder `15` + slice text, then the play / hand-off test (cited, not re-run), then the VR PNG, axe secondary; the merged design wins over the ticket text, each difference a section 10 row; strings asserted only where a source words them                                                                                                                                                                                                                   | 0, 3        | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-09 | VR as the visual oracle              | as proposed: the 4,356 VR cells cited, never re-captured; what VR does not cover is manual and stated in section 0                                                                                                                                                                                                                                                                                                                                                                    | 0, 2, 6     | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-10 | a11y split with E05-Q02              | as proposed; the delegation is not extended: `SR-S02` and S04's screen-reader DoD pass stay with E05-Q02 and are listed under section 8 as Q02's; this plan keeps the keyboard-only pass, the three `SR-S03` cases (results written back into that log, one line per component) and one colour-redundancy smoke leg per family                                                                                                                                                        | 3.7, 8      | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-11 | what runs today                      | as proposed; the NVDA pass and any human charter are "blocked on a human tester" until run; the owner is the likely tester and is asked through the #2701 digest, never assumed                                                                                                                                                                                                                                                                                                       | 7           | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-12 | the exploratory charter              | two 90-minute charters C-1 and C-2 in E09's form; an agent-driven Playwright session counts as one of the two timeboxed sessions only with the honest-scope line (E09's precedent) and never stands in for the human pass; session notes land under `docs/qa/charters/` in the execution pass, not in this PR                                                                                                                                                                         | 3.9         | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-13 | fixtures                             | as proposed: no fixtures, no network                                                                                                                                                                                                                                                                                                                                                                                                                                                  | 5, 6        | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-14 | the † policy                         | as proposed: the † table in `E16`'s form, every candidate row named, re-grepped at the READY sha (section 0)                                                                                                                                                                                                                                                                                                                                                                          | 10          | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-15 | new hooks, stories or tests          | as proposed: no new hook, story or test; no throwaway composition stories, so no outside dry run                                                                                                                                                                                                                                                                                                                                                                                      | 6, 10       | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-16 | the six compositions' surfaces       | as proposed: CMP-059 CommandPalette plus `Dialog` `EscTopmost` as the Combobox-in-Dialog surface, with a † row for the missing CMP-048-in-CMP-043 story; Menu-in-Drawer a † row and a C-2 probe; the other four compositions on their named stories; a † surface records "blocked on", never a guessed pass                                                                                                                                                                           | 3.6, 10     | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-17 | the abuse legs and `security-review` | as proposed: two black-box legs citing the controls' executors, findings to E05-X02 (#272); no `security-review` label                                                                                                                                                                                                                                                                                                                                                                | 3.8, 8      | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-18 | the human legs                       | as proposed: results are never written unobserved; defects are rows in the execution record and filing waits for the orchestrator's go under the 2026-10-19 freeze (a gate defect or a P0 / P1 on `main` is filed at once when told); sign-off comments on #264 / #265 / #266 and the S04 rows that ran on #267; a "For E05-Q03 (#263)" table in section 8                                                                                                                            | 3.7, 3.9, 7 | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-19 | the performance observation          | as proposed: the observation on `Table` `Scrolling` / `Perf200Rows` (perf env) and the matrix toolbar switch, escalated against E05-T02's budget by cite; the 500-row gap is a section 10 row                                                                                                                                                                                                                                                                                         | 3.8, 10     | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-20 | defects, sign-offs, hand-over        | as proposed: defects are rows in the execution record, filing waits for the orchestrator's go; sign-off comments on #264 / #265 / #266, the S04 rows that ran on #267; the "For E05-Q03 (#263)" table in section 8                                                                                                                                                                                                                                                                    | 7, 8        | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-21 | PR shape                             | as proposed: one PR, one file, `Closes #261`, the branch-name deviation row, labels `type/test` `area/design-system` `priority/p1` `qa`; `large-pr-approved` applied by the orchestrator on #5127 (1,741 lines); review = the Sonnet one-look plus the orchestrator's read                                                                                                                                                                                                            | PR          | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-22 | closing on the document              | Reading A: the PR closes #261 on the document, as #404 and #422 did; section 7 states what runs today and what waits; the execution pass of the runnable set is owed on #261 as comments inside Sprint 06 and is not waived; the human and S04 legs are blocked and named; E05-Q03 (#263) assembles the epic sign-off; the DoD's "executed; results recorded per scenario" is read as the section 7 ledger plus that execution pass (the same reading as E13-Q01's, 6532529903 BQ-21) | 1, 7        | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-23 | lateness                             | reported, no waiver: the dates in section 0's lateness report and the PR body; READY falls inside Sprint 06                                                                                                                                                                                                                                                                                                                                                                           | 0, PR       | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |
| BQ-24 | open questions carried               | as proposed; nothing re-decided                                                                                                                                                                                                                                                                                                                                                                                                                                                       | 10          | RULED (orchestrator, 2026-10-30, #261 ruling of record — 6533789549's answer) |

## 2. The test matrix

**The axes (ruled as BQ-07).** **Theme** `dark | light | high-contrast` and **density** `compact | comfortable` (`store`:9–10;
the toolbar globals `theme` and `density` of `preview`:44–53, written as `data-theme` and `data-density` on the document root,
`16`:167). **Motion** `system | on | off` (`store`:12; the `motion` toolbar global, `preview`:54–60; the runtime writes
`data-motion="safe|reduce"`, `16`:167; `on` means the in-app override forces `reduce`, as `ConfirmDialog` `HoldReducedMotion`
and `Spinner` `ReducedMotion` set it, `ConfirmDialog.stories.tsx`:404–405, `Spinner.stories.tsx`:101–102). **Zoom** 100 % and
200 % browser zoom (#261 Technical notes; `05`:131 rule 7) and the in-app **text scale** 100 / 112 / 125 / 150 (`store`:11,
`data-text-scale`; there is no 200 in-app scale, so "200 %" is browser zoom only, or the story's own root font size where a story
sets it: `Table` `Reflow`, `Table.stories.tsx`:325). **Viewport** 1920 × 1080 (the primary target, `vr/settings.ts`:71) and
1280 × 800 (the minimum, `16`:269; the frame `Table` `Reflow` and `Dialog` `Reflow` draw, `Table.stories.tsx`:329,
`Dialog.stories.tsx`:254).

**2.1 Family by axis.** Theme × density is run for every story through the VR cells and never by hand; the other axes name the
cells the manual cases run. **VR** = the six committed cells per story; **M** = a manual cell of the case named; **n/a** = no
story in the family changes on that axis (a static component; the case says so); **—** = not run here (E05-Q02's, section 8).

| Family                    | theme × density               | motion `system / on / off`                                                                                                        | zoom 100 % / 200 %                                | text scale 112 / 125 / 150                                        | viewport 1280 × 800 / 1920 × 1080      |
| ------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------- | -------------------------------------- |
| 3.1 actions and selection | VR, 792 cells (C01)           | M: Spinner `MotionSafe` / `ReducedMotion` (C07); the rest n/a                                                                     | M: C02 at 200 % (focus ring and labels unclipped) | —                                                                 | M: C02 at 1280 × 800                   |
| 3.2 data display and text | VR, 564 cells (C08)           | n/a (no animated property; Sparkline is a static `img`, `Atoms.mdx`:321)                                                          | M: C10 at 200 % (tabular columns still align)     | —                                                                 | M: C08's `TabularColumn` at 1280 × 800 |
| 3.3 form controls         | VR, 984 cells (C15)           | M: Combobox `SettleUnanimated` under `on` (C21)                                                                                   | M: C22 (Table `Reflow`) at 200 %; C16 at 200 %    | M: `AllMolecules` stacked cell at 200 % text scale (C22)          | M: C22 at 1280 × 800 and 640 px        |
| 3.4 feedback and overlays | VR, 1,140 cells (C27)         | M: Skeleton `Static`, SkeletonChart `Static`, ProgressBar `ReducedMotion` (C31); Dialog, Drawer, Toast entrances under `on` (C28) | M: Dialog `Reflow` at 200 % (C34); C28 at 200 %   | —                                                                 | M: Dialog `Reflow` at 1280 × 800 (C34) |
| 3.5 the rest              | VR, 402 cells (C42)           | M: SkipLink `FocusedReducedMotion` (C47); Tabs, CommandPalette under `on` (C43)                                                   | M: C43 at 200 %                                   | M: ThemeRuntime `TextScaleReflow` at each scale (C48, a stand-in) | M: C43 at 1280 × 800                   |
| the matrix stories        | VR, 216 cells (C01, C27, C42) | n/a (captured under `reduce`)                                                                                                     | —                                                 | —                                                                 | —                                      |

**2.2 Composition by axis.** Each composition case names the cell it runs in; a composition with no story records "blocked on"
its owner (section 3.6), never a guessed pass.

| Composition (#261 Scope)                              | Surface at the base                                                                          | theme · density                             | motion                 | zoom · viewport                         | Case |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------- | ---------------------- | --------------------------------------- | ---- |
| Combobox inside Dialog (focus trap vs listbox portal) | `CommandPalette` `Default`, `Gated`; `Dialog` `EscTopmost`; CMP-048-in-CMP-043 story: none † | dark · compact; high-contrast · comfortable | `system`, `on`         | 100 % · 1920 × 1080; 200 % · 1280 × 800 | C53  |
| Toast while a Dialog is open                          | `Toast` `RegionUnderModal`                                                                   | dark · compact                              | `system`, `on`         | 100 % · 1920 × 1080                     | C54  |
| Menu inside a scrollable Drawer                       | none †: `Drawer` `LongText` and `Menu` `Scrolling` exist apart                               | dark · compact                              | `system`               | 100 % · 1920 × 1080; 1280 × 800         | C55  |
| Table reflow at 200 % zoom, compact, high-contrast    | `Table` `Reflow`; `AllMolecules` `HighContrastCompact` (the stacked cell)                    | high-contrast · compact                     | `system`, `on`         | 200 % · 1280 × 800 and 640 px           | C56  |
| Hold-to-confirm under reduced motion                  | `ConfirmDialog` `HoldReducedMotion`, `HoldKeyboard`                                          | dark · compact; light · comfortable         | `on` (and OS `reduce`) | 100 % · 1920 × 1080                     | C57  |
| Tooltip on a disabled-with-reason control             | `Tooltip` `EchoReason`; `IconButton` `DisabledWithReason`; `RbacGate` `FormTooltip`: none †  | dark · compact; high-contrast · compact     | `system`               | 100 % and 200 % · 1920 × 1080           | C58  |

## 3. Cases by component family

Each case runs against the built Storybook of section 5 at the cells its header names, with the toolbar globals (`theme`,
`density`, `motion`) set from `preview`:44–60 and nothing else configured. A case is: preconditions, steps, expected, oracle,
and a Blocked-on line. A tester who did not write the plan can run any case from sections 4 to 6 alone. "Its six cells" means
the story's `vr/baselines/{story-id}--{theme}--{density}.png` for every theme × density (section 0). The family at-rest cases
(C01, C08, C15, C27, C42) each carry a table naming every component of the family with the stories the case reads, so every
component of the v0 set is named by at least one case (section 9).

### 3.1 Actions and selection (CMP-001–006, 010, 014, 019, 031, 039; S01 and S02)

**E05-Q01-C01 The family's full matrix is rendered and snapshot-stable [R]** (`e2e`; 3.1 · S01, S02; mirrors S01.1 "Full matrix
is rendered and snapshot-stable" and `15`:41 rule 7; `HO-S01`:9; `AllAtoms.stories.tsx` `DarkCompact` … `HighContrastComfortable`)

- Pre: the built Storybook; the VR run of section 5 green at the base (every cell compared, no diff past the tolerance).
- Steps: open each component's Storybook page and read its stories against the `15` Storybook list and "As built" lines; for
  each theme × density read the committed cell rather than the screen; open `Atoms/All atoms matrix` at the six pinned stories
  and read the cell whose globals equal the pinned pair.

  | Component                       | Stories read (`<Component>.stories.tsx` exports)                                                                                                                                                                                                           | `15` list and as-built                                                                                                |
  | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
  | CMP-001 Button                  | Default, AllVariants, BuySellPair, WithIcons, AllSizes, Loading, Disabled, DisabledWithReason, FullWidth, LongLabel, GatedContrastLight / HighContrast, FocusVisible, Hover, Active, KeyboardActivation (`Button.stories.tsx`:21–181)                      | `15`:56; `15`:53–54 states                                                                                            |
  | CMP-002 IconButton              | Default, AllVariants, AllSizes, Toggle, PressedGated, PressedDisabled, Disabled, DisabledWithReason, HitTarget, RowTarget, the Gated contrast pair, FocusVisible, PressedFocusVisible, Hover, Active, KeyboardActivation (`IconButton.stories.tsx`:33–199) | `15`:66; `15`:63 (the `locked` badge in the corner, the box never grows)                                              |
  | CMP-003 SegmentedControl        | Default, Small, IconOnly, IconAndText, ManyOptions, FullWidth, NoSelection, Disabled, GatedGroup, AllStates, the Gated contrast pair, FocusVisible, Hover, KeyboardNavigation, ClickSegment (`SegmentedControl.stories.tsx`:52–200)                        | `15`:77; `15`:74–75                                                                                                   |
  | CMP-004 Toggle                  | Default, Checked, LabelLeft, LabelHidden, Critical, Disabled, DisabledWithReason, AllStates, LongLabel, the Gated contrast pair, FocusVisible, Hover, KeyboardToggle (`Toggle.stories.tsx`:20–125)                                                         | `15`:87; `15`:84 (hover adds a 1 px inner outline, off and on alike)                                                  |
  | CMP-005 Checkbox                | Default, Checked, Indeterminate, Disabled, DisabledWithReason, AllStates, LongLabel, the Gated contrast pair, FocusVisible, Hover, KeyboardToggle (`Checkbox.stories.tsx`:20–114)                                                                          | `15`:97; `15`:95 (`aria-checked="mixed"` paired with the visible word "Mixed")                                        |
  | CMP-006 RadioGroup              | Default, Horizontal, NoSelection, Disabled, GatedGroup, OptionLocked, LongLabel, AllStates, the Gated contrast pair, FocusVisible, Hover, KeyboardNavigation, ClickWholeRow (`RadioGroup.stories.tsx`:48–190)                                              | `15`:107; `15`:104–105                                                                                                |
  | CMP-010 Slider                  | Default, WithMarks, CrowdedMarks, Disabled, DisabledWithReason, AllStates, LongSuffix, the Gated contrast pair, FocusVisible, Hover, KeyboardSteps, RailJump (`Slider.stories.tsx`:42–133)                                                                 | `15`:147; `15`:144–145                                                                                                |
  | CMP-014 Spinner                 | Labelled, Sizes, Decorative, MotionSafe, ReducedMotion, ThemeLight, ThemeHighContrast (`Spinner.stories.tsx`:59–101)                                                                                                                                       | `15`:189; `15`:187 (`role="status"` when labelled, `aria-hidden` when nested)                                         |
  | CMP-019 Icon                    | FullSet, SizeScale, TradingGlyphs (`icons/Icons.stories.tsx`:19–54)                                                                                                                                                                                        | `15`:241 (47 base glyphs); `15`:239 (`aria-hidden` by default)                                                        |
  | CMP-031 ColorSwatch / ThemeChip | Picker, NoSelection, Hover, HoverSelected, FocusVisible, KeyboardNavigation, Disabled, SwatchLocked, PickerLocked, LockedSelected, StaticSwatch, StaticDecorative, AllStates, ThemeLight, ThemeHighContrast, Wrapping (`ColorSwatch.stories.tsx`:65–217)   | `15`:373; `15`:370–371 (the swatch keeps its true colour while gated; the picker is a radiogroup)                     |
  | CMP-039 FocusRing               | Normal, Inset, ThemeLight, ThemeHighContrast (`FocusRing.stories.tsx`:51–64)                                                                                                                                                                               | `15`:457 says RingOnButton / RingOnCustomSurrogate; as built (`15`:459) "Normal and Inset … are not separate stories" |

- Expected: every component has a story per `15` state it documents, read against the as-built line where the list and the
  build differ (Spinner's `Standalone(labelled)` / `Nested(hidden)` are `Labelled` / `Decorative`; FocusRing's two are
  `Normal` / `Inset`; ColorSwatch's `Picker, StaticSwatch, Mixed, Custom, Disabled` are the sixteen above). Every cell of every
  story exists in `vr/baselines/` (132 stories × 6 = 792 for this family, section 1) and the VR run reports no diff. In the
  `AllAtoms` cell for each pinned pair the family's components render in one page with no clipping, overlap or missing control.
  No story shows a raw colour that does not follow the theme (the same story's dark and light cells differ in every component
  that paints a surface; a component painted identically in both is a finding to read against its tokens, never a pass).
- Oracle: the `15` list and as-built lines > the VR cells (presentation). 2nd: the `storybook` job's axe result for every story
  of the family (zero serious or critical).
- Blocked on: none.

**E05-Q01-C02 The family's keyboard-only walk, scripted by the Atoms tables [R]** (`e2e`, `a11y`; 3.1 · S01, S02; mirrors S01.2
"Keyboard contract" and `15`:38 rule 4; `Atoms.mdx`:15–131 Button to TextInput, :177 FocusRing, :188 Spinner, :396 ColorSwatch;
`HO-S01`:10, :30 "Atoms/Overview tables are the script"; `05`:30 rule 1)

- Pre: the built Storybook at dark · compact, then light · comfortable; the pointer unplugged or untouched for the whole case;
  the browser at 100 %, then at 200 % zoom on a 1280 × 800 window.
- Steps: for each component, open the stories `KeyboardActivation` (Button, IconButton), `KeyboardNavigation` (SegmentedControl,
  RadioGroup, ColorSwatch), `KeyboardToggle` (Toggle, Checkbox), `KeyboardSteps` (Slider) and `FocusVisible`, and walk the
  component's `Atoms.mdx` key table row by row: `Tab` / `Shift+Tab` in and out, `Enter` / `Space`, the arrows, `Home` / `End`,
  `PageUp` / `PageDown` where the table lists them. On SegmentedControl `Default`: `Tab` to the group, `ArrowRight`, then `Tab`
  again. Read the focus ring at every stop.
- Expected: every interactive control is reached by `Tab` in reading order and leaves by `Tab`; a group (SegmentedControl,
  RadioGroup, the ColorSwatch picker) is one `Tab` stop with a roving tabindex: `ArrowRight` moves selection to the next option
  and checks it, wrapping, and the next `Tab` leaves the group rather than moving between options (`15`:75; S01.2); `Enter` /
  `Space` activates a button and toggles a switch or checkbox (`15`:85, :95); the Slider moves by `step` on the arrows, by
  10 × `step` on `PageUp` / `PageDown`, to the bounds on `Home` / `End` (`15`:145); a disabled-with-reason control stays
  focusable and its reason is read (C03), a plain disabled one is out of the order (`15`:104, :144). The focus ring is visible
  at every stop, at every theme, at 200 % zoom and at 1280 × 800, with no clipped ring and no label cut; nothing needs a
  pointer. Anything unreachable is a defect whatever axe says (#261 Accessibility notes).
- Oracle: the `Atoms.mdx` tables and the `15` A11y lines > the story's play (`SegmentedControl.test.tsx` "arrows move focus and
  check, wrapping, in both directions" and "Tab leaves the group in both directions and re-enters on the checked segment",
  `HO-S01`:10, white-box evidence) > the focus target at each step (UI only). 2nd: none (a read).
- Blocked on: none.

**E05-Q01-C03 Disabled states explain themselves, through the accessible description [F]** (`e2e`, `a11y`; 3.1 · S01; mirrors
S01.3 "Disabled states explain themselves"; `15`:53–55 Button, :63 IconButton, :84 Toggle, :95 Checkbox, :104 RadioGroup, :370
ColorSwatch; A-12 (`E05-S01-catalogue-a-rows.md`:18); `HO-S01`:11, :26; T2)

- Pre: dark · compact; the stories `DisabledWithReason` of Button (`Button.stories.tsx`:101), IconButton (:85), Toggle (:46),
  Checkbox (:38), Slider (:61), `GatedGroup` of SegmentedControl (:112) and RadioGroup (:64), `OptionLocked` of RadioGroup (:87),
  `PickerLocked` / `SwatchLocked` of ColorSwatch (:134, :116).
- Steps: `Tab` to each gated control; read its name, state and description through the accessibility tree; hover it; press
  `Enter`, `Space` and the arrows; click it.
- Expected: the control keeps its role and full label, carries `aria-disabled="true"` and never the `disabled` attribute, is
  focusable, and its reason is its accessible description at mount (not only on hover or focus); no handler fires on any key or
  click; only the fill, track, box or rings dim and the label stays at full opacity (`15`:53, :63, :84, :95, :104); IconButton
  shows the `locked` badge in its corner and the box does not grow (`15`:63); a gated swatch keeps its true colour (`15`:370). The
  ticket's "the reason is shown" on hover or focus is **visible to assistive technology only** at the base: no atom renders an
  inline reason or a tooltip of its own (A-12, accepted 2026-10-27; the visible echo is CMP-016's and CMP-040's — C58, C20). The
  story's reason strings are the story's, not asserted; where a story uses an `RBAC_REASONS` key its sentence is asserted
  verbatim (`rbacReasons.ts`:8–14).
- Oracle: the `15` States and A11y lines and T2 > the tests `Button.test.tsx` "disabled with a reason: focusable,
  aria-disabled, reason described at mount, no activation" and its per-atom equivalents (`HO-S01`:11, white-box evidence) > the
  tree. 2nd: axe for the stories (zero serious or critical).
- Blocked on: the visible echo half — CMP-016 / CMP-040 (A-12; section 10 OQ-6). The description half runs today.

**E05-Q01-C04 A loading button cannot double-submit [R] [F]** (`e2e`; 3.1 · S01; mirrors S01.6 "Loading button cannot
double-submit"; `15`:53 loading, :54 `aria-busy`; `Button.stories.tsx`:89 `Loading`; `HO-S01`:14)

- Pre: dark · compact and light · comfortable; `Button` `Loading` and `AllVariants`; motion `system`, then `on`.
- Steps: read the button's name, `aria-busy` and width; click it twice; `Tab` to it and press `Enter` twice; switch the toolbar
  motion to `on` and read the spinner.
- Expected: the label is replaced by the spinner but the accessible name is unchanged and `aria-busy="true"` is set; the width
  is locked (no reflow of the row); the control stays focusable; no activation fires on either click or either `Enter`; the
  nested spinner is `aria-hidden` (one busy announcement, `15`:187); under reduced motion the spinner is a static arc, not a
  rotation (`Spinner.stories.tsx`:100–101). The `Loading` cells show the locked width at every theme and density.
- Oracle: `15`:53–54 > `Button.test.tsx` "loading keeps the name, sets aria-busy, stays focusable and suppresses activation"
  (`HO-S01`:14) > the six `Loading` cells. 2nd: axe for `Loading`.
- Blocked on: none.

**E05-Q01-C05 No hardcoded values: the lint oracle and the theme swap** (`e2e`; 3.1 · S01; mirrors S01.7 "No hardcoded values";
`HO-S01`:15; `15`:35 rule 1, :36 rule 2)

- Pre: the base checked out; the built Storybook.
- Steps: run `pnpm --filter @candleviewer/ui lint` and read the `candleviewer/no-raw-design-values` rule's result for
  `packages/ui/src/components/`; then, in Storybook, switch the toolbar theme across the three values and the density across the
  two on `Button` `AllVariants`, `Toggle` `AllStates`, `Slider` `WithMarks` and `ColorSwatch` `Picker`.
- Expected: the lint passes with zero raw hex or px reports in these files (the rule is `error` for them, `HO-S01`:15); every
  surface, text and ring colour follows the theme and every spacing follows the density, with no component keeping a colour or
  a size across the swap except the ColorSwatch's own colour, which is its value (`15`:370). The in-app text scale changes the
  controls' text (`ThemeRuntime` `TextScaleReflow`, C48's stand-in).
- Oracle: the lint output (a command, black-box to the plan) > the VR cells per theme and density (presentation). 2nd: none (a
  read).
- Blocked on: none.

**E05-Q01-C06 Colour is never the only signal in the family (smoke)** (`a11y`; 3.1 · S01, S02; mirrors `15`:37 rule 3 and `05`
§4; ruled as BQ-10 (c); `Button.stories.tsx`:40 `BuySellPair`, `Toggle.stories.tsx`:34 `Critical`, `Checkbox.stories.tsx`:24
`Indeterminate`, `ColorSwatch.stories.tsx`:65 `Picker`, `Spinner.stories.tsx`:59 `Labelled`)

- Pre: high-contrast · compact; then the same stories rendered in greyscale (the browser's rendering emulation; no story
  change).
- Steps: read each story in greyscale and through the accessibility tree.
- Expected: a buy and a sell button are told apart by their labels, not their fill alone; the Critical toggle carries its word;
  the indeterminate checkbox shows the word "Mixed" beside its label (`15`:95); a checked swatch is marked by its outline and
  its radio state, and named by ordinal, hue word and token (`15`:371), not by colour alone; a labelled spinner is a
  `role="status"` region with its text (`15`:187). Every state that colour marks is also carried by text, glyph or shape.
- Oracle: `15`:37 rule 3 and the entries' A11y lines > the tree (UI only). 2nd: axe (zero serious or critical).
- Blocked on: none.

**E05-Q01-C07 Spinner and FocusRing under the motion and theme axes** (`e2e`; 3.1 · S02; `15`:187 Spinner, :455–459 FocusRing;
`Spinner.stories.tsx`:88 `MotionSafe`, :101 `ReducedMotion`; `FocusRing.stories.tsx`:51 `Normal`, :64 `Inset`)

- Pre: dark · compact; motion `system` with the OS preference off, then `on`, then `off` with the OS preference set to reduce.
- Steps: open `Spinner` `MotionSafe` and `ReducedMotion` and read the root's `data-motion` and the arc; open `FocusRing`
  `Normal` and `Inset` at each theme and `Tab` onto the sample.
- Expected: `motion="on"` writes `data-motion="reduce"` and the arc stands still; `motion="off"` writes `safe` and the arc rotates
  even with the OS preference set to reduce (the in-app override wins, `16`:167; `store`:12); the ring is drawn at ≥ 3 : 1 with a
  2 px offset on `:focus-visible` only (no ring after a mouse click, `15`:455), inside the element for `Inset` (`15`:459), at
  every theme. The `ReducedMotion` cells are the at-rest oracle; the `MotionSafe` frame is manual (VR captures under `reduce`).
- Oracle: `15`:455–459 and `16`:167 > the root attribute and the computed styles (UI only). 2nd: none (a read).
- Blocked on: none.

### 3.2 Data display and text (CMP-011, 012, 013, 018, 020, 021, 024, 025, 030, 032, 033, 037; S02)

**E05-Q01-C08 The family's full matrix is rendered and snapshot-stable [R]** (`e2e`; 3.2 · S02; mirrors `15`:41 rule 7 and the
S02 Test plan's "Visual regression: baseline captured by E05-T04"; `AllAtoms` matrix)

- Pre: as C01.
- Steps: as C01, over this table.

  | Component                | Stories read                                                                                                                                                                                                                                       | `15` list and as-built                                                                                     |
  | ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
  | CMP-011 Tag / Chip       | Default, WithIcon, AllVariants, Info, Warning, Danger, Removable, RemovableGeometry, RemovableHover, RemovableFocusVisible, RemovableDisabled, RemovableDisabledWithReason, LongText, KeyboardRemove, the contrast pair (`Tag.stories.tsx`:27–141) | `15`:159 lists EstimatedChip; as built (`15`:161) "Storybook has no EstimatedChip (#265 ruling 3)"         |
  | CMP-012 Badge            | Default, Count, OnLabelledControl, Dot, AllTones, the contrast pair (`Badge.stories.tsx`:41–71)                                                                                                                                                    | `15`:169; `15`:167 (a dot is `aria-hidden` and never alone)                                                |
  | CMP-013 Avatar           | Default, AllSizes, WithVisibleName, LongLabel, the contrast pair (`Avatar.stories.tsx`:25–56)                                                                                                                                                      | `15`:179 lists ColorPalette; as built (`15`:181) "ColorPalette waits" (no `color` prop)                    |
  | CMP-018 Divider          | Horizontal, Vertical, Decorative, Labelled, the contrast pair (`Divider.stories.tsx`:18–67)                                                                                                                                                        | `15`:231; `15`:233 (a plain `div`, `role="separator"` or `none`)                                           |
  | CMP-020 Typography       | TypeScale, HeadingLevelVsStyle, NumericFormats, PnLColoring, AbbreviatedWithExpandedReading, TabularColumn, LongText, the contrast pair (`Typography.stories.tsx`:48–224)                                                                          | `15`:252 (AbbreviatedWithAriaLabel is AbbreviatedWithExpandedReading: `15`:250, no `aria-label` on a span) |
  | CMP-021 Link             | Default, Internal, External, Hover, FocusVisible, ExternalFocusVisible, Disabled, LongText, ExternalNarrowWrap, the contrast pair (`Link.stories.tsx`:38–130)                                                                                      | `15`:262; `15`:259–260, :264 (always underlined; `rel="noopener noreferrer"`)                              |
  | CMP-024 Sparkline        | Uptrend, UptrendColorBySign, Downtrend, DowntrendColorBySign, Flat, FlatColorBySign, Empty, SinglePoint, Sized, InRow, Light, HighContrast (`Sparkline.stories.tsx`:30–61; `Perf200Points` is `perf`-tagged, excluded from VR)                     | `15`:293; `15`:295                                                                                         |
  | CMP-025 AvatarGroup      | Default, Overflow, OnRaisedSurface, the contrast pair (`AvatarGroup.stories.tsx`:20–32)                                                                                                                                                            | `15`:303; `15`:301 (`role="img"` naming every label, `+N` hidden)                                          |
  | CMP-030 Divider-Label    | `Divider` `Labelled` (`Divider.stories.tsx`:67)                                                                                                                                                                                                    | `15`:362; `15`:360, :364 (named by `aria-labelledby`, the label a sibling)                                 |
  | CMP-032 ConfidenceDots   | Low, Medium, High, NumericLabel, LongText, AllLevels, Light, HighContrast (`ConfidenceDots.stories.tsx`:17–48)                                                                                                                                     | `15`:383; `15`:385 (adds Low, Medium, High, NumericLabel, LongText)                                        |
  | CMP-033 CopyButton       | Default, Hover, FocusVisible, CopiedState, Failed, Disabled, LongText, the contrast pair (`CopyButton.stories.tsx`:44–99)                                                                                                                          | `15`:394; `15`:391–392, :396                                                                               |
  | CMP-037 SwatchLegendItem | Default, WithoutValue, WithGlyph, the contrast pair (`SwatchLegendItem.stories.tsx`:26–40)                                                                                                                                                         | `15`:436; `15`:434                                                                                         |

- Expected: as C01 over 94 stories × 6 = 564 cells; in the `AllAtoms` cells the static components sit beside the controls with
  no overlap; a `LongText` or `LongLabel` story wraps or truncates as its as-built line says and never overflows its cell.
- Oracle: `15` > the VR cells. 2nd: axe for every story of the family.
- Blocked on: none.

**E05-Q01-C09 The family's keyboard-only walk [R]** (`e2e`, `a11y`; 3.2 · S02; `Atoms.mdx`:142 Tag, :159 Badge, :165 Avatar,
:171 AvatarGroup, :207 Typography, :221 Divider, :233 Link, :258 KeyValueRow is 3.5's, :264 SwatchLegendItem, :321 Sparkline,
:327 ConfidenceDots, :333 CopyButton)

- Pre: as C02 (no pointer; 100 % then 200 % zoom; 1280 × 800).
- Steps: `Tab` through `Tag` `Removable` and `KeyboardRemove`, `Link` `Internal` / `External` / `Disabled`, `CopyButton`
  `Default`; then through the static stories (Badge, Avatar, AvatarGroup, Divider, Typography, Sparkline, ConfidenceDots,
  SwatchLegendItem) and count the stops.
- Expected: the removable chip's remove control is a labelled IconButton reached by `Tab`, and `Enter` / `Space` fires the
  remove, after which focus never lands on `<body>` (`15`:156); a link is a native `<a>` with a visible ring at its square corners
  (`15`:260, :264) and a disabled link is not focusable (`15`:260); CopyButton is one stop; the static components add **no** stop
  (a `role="img"` sparkline, a hidden dot, a separator). Rings and text stay unclipped at 200 % and at 1280 × 800.
- Oracle: the `Atoms.mdx` tables and `15` A11y lines > the focus target at each step. 2nd: none (a read).
- Blocked on: none.

**E05-Q01-C10 Tabular numerics are enforced centrally [R]** (`e2e`; 3.2 · S02; mirrors S02.1 "Tabular numerics are enforced
centrally"; `15`:40 rule 6, :249–250; `Typography.stories.tsx`:131 `NumericFormats`, :152 `PnLColoring`, :203 `TabularColumn`,
:178 `AbbreviatedWithExpandedReading`)

- Pre: dark · compact and light · comfortable; browser zoom 100 % and 200 %.
- Steps: open `TabularColumn` and read the computed `font-variant-numeric` and `font-family` of each value and the right edges of
  the digits down the column; open `NumericFormats` and `PnLColoring` and read the sign display; open
  `AbbreviatedWithExpandedReading` and read the tree.
- Expected: every glyph advances identically and the digits align on the right with `tabular-nums` applied by the component (the
  story sets none itself); the family is the monospaced numeric face (`15`:40); `format="pnl"` and `colorBySign` show the sign
  always and zero unsigned (`15`:249); an abbreviation is `aria-hidden` with a visually hidden expanded reading and no `aria-label`
  on the span (`15`:250). Alignment holds at 200 % zoom.
- Oracle: `15`:40, :249–250 > the story's play (white-box) > the `TabularColumn` cells. 2nd: none (a read).
- Blocked on: none.

**E05-Q01-C11 Estimated confidence is not colour-only [R]** (`a11y`; 3.2 · S02; mirrors S02.5 "Estimated confidence is not
colour-only"; `15`:381, :385; `ConfidenceDots.stories.tsx`:17 `Low`, :48 `AllLevels`, :33 `NumericLabel`)

- Pre: high-contrast · compact, in greyscale, then dark · comfortable.
- Steps: read `Low`, `Medium`, `High` and `AllLevels` in greyscale and through the tree; read `NumericLabel`.
- Expected: the level is carried by the filled-dot count and an accessible text label that names the level (the word low /
  medium / high is always present, `15`:381); the dots are `aria-hidden` and the visible label is the accessible text; a label
  without a level word gets ", {level} confidence" appended and one naming a different level is replaced (`15`:385). Nothing
  depends on hue.
- Oracle: `15`:381–385 > the tree. 2nd: axe for `AllLevels`.
- Blocked on: none.

**E05-Q01-C12 Colour is never the only signal in the family (smoke)** (`a11y`; 3.2 · S02; `15`:37 rule 3; `Badge.stories.tsx`:71
`AllTones`, :68 `Dot`; `Tag.stories.tsx`:32 `AllVariants`; `Sparkline.stories.tsx` the `ColorBySign` trio; `Typography`
`PnLColoring`; `SwatchLegendItem.stories.tsx`:40 `WithGlyph`; `Link.stories.tsx`:60 `External`)

- Pre: as C06 (high-contrast, greyscale).
- Steps: read each story in greyscale and through the tree.
- Expected: a dot badge sits beside a visible word and, for a tone, the tone's glyph (`15`:167); a tone chip carries its word or
  glyph; a sparkline's trend is in its name ("up 3.2% over 20 bars"-form, `15`:291) and `colorBySign` requires the sign shown;
  a PnL value shows its sign; a directional legend swatch carries its glyph (`15`:438 requires one for a directional token); an
  external link has the visually hidden "(opens externally)" and the link text is underlined (`15`:259–260).
- Oracle: the A11y lines > the tree. 2nd: axe.
- Blocked on: none.

**E05-Q01-C13 CopyButton's copied and failed states, announced once and never with the value [F]** (`e2e`, `a11y`; 3.2 · S02;
`15`:391–392, :396; `CopyButton.stories.tsx`:63 `CopiedState`, :77 `Failed`; `vr/settings.ts`:58 the 2 s reset frozen before
it fires)

- Pre: dark · compact; the browser clipboard permitted for the Storybook origin, then denied.
- Steps: press the copy control; read the glyph, the live region's text and the clipboard; wait 2 s and read again; deny the
  clipboard and press again.
- Expected: on success the `check` glyph and "Copied" spoken once, politely, the announcement never containing the value
  (`15`:392); the state reverts after 2 s (`15`:391); on a refused write the `error` glyph and "Copy failed", reverting after 2 s;
  a repeat press is a new announcement (`15`:396). The `CopiedState` and `Failed` cells show the glyph states (VR freezes the
  page before the 2 s reset, `vr/settings.ts`:58–59).
- Oracle: `15`:391–396 > the live region and the clipboard (UI only). 2nd: axe.
- Blocked on: none.

**E05-Q01-C14 Links, avatars and groups: names, external behaviour and the disabled link [F]** (`e2e`, `a11y`; 3.2 · S02;
`15`:259–260, :264 Link; `15`:177, :181 Avatar; `15`:301, :305 AvatarGroup; `15`:233 Divider; `Link.stories.tsx`:60 `External`,
:109 `Disabled`, :43 `Internal`; `Avatar.stories.tsx`:43 `WithVisibleName`; `AvatarGroup.stories.tsx`:23 `Overflow`;
`Divider.stories.tsx`:53 `Decorative`, :67 `Labelled`)

- Pre: dark · compact; light · comfortable.
- Steps: read `External`'s anchor attributes, its hidden text and its glyph; `Tab` to `Disabled` and read; read `Internal`'s
  rendered element; read `WithVisibleName` and `Overflow` through the tree; read `Decorative` and `Labelled`.
- Expected: an external link is a native `<a>` with `rel="noopener noreferrer"` and `target="_blank"`, its icon `aria-hidden`
  beside the visually hidden "(opens externally)", the text underlined (`15`:259–260, :264); a disabled link is `role="link"`
  `aria-disabled="true"` with no `href` and is not focusable (`15`:260); an internal link renders through the host's `as`
  component with no `rel` or `target` (`15`:264); an avatar beside visible text is `aria-hidden`, and alone it is `role="img"`
  named by the full label (`15`:177, :181); a group is `role="img"` named "{n} accounts: {every label}" with the avatars and the
  `+N` chip hidden (`15`:301); a decorative divider is `role="none"`, a labelled one `role="separator"` named by the sibling
  label (`15`:233, :360).
- Oracle: the `15` A11y and as-built lines > the tree and the anchor attributes. 2nd: axe for `External` and `Overflow`.
- Blocked on: none.

### 3.3 Form controls (CMP-007, 008, 009, 034, 040, 047, 048, 049, 054, 065, 079; S01, S02, S03, S04)

**E05-Q01-C15 The family's full matrix is rendered and snapshot-stable [R]** (`e2e`; 3.3 · S01–S04; mirrors S01.1, the S03
Test plan's "Visual regression via E05-T04 incl. the reflowed table state" and `HO-S03`:23; `AllAtoms` and `AllMolecules`
`DarkCompact` … `HighContrastComfortable`)

- Pre: as C01.
- Steps: as C01, over this table; in `Molecules/All molecules matrix` read the six at-rest cells, including the
  "CMP-049 Table, stacked (200 % text scale)" cell (`AllMolecules.stories.tsx`:290–291).

  | Component                            | Stories read                                                                                                                                                                                                                                                                                                                                                                                                                                    | `15` list and as-built                                                                                                 |
  | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
  | CMP-007 TextInput                    | Default, Empty, WithPrefixSuffix, Hover, FocusVisible, Invalid, Disabled, DisabledWithReason, ReadOnly, LongValue, AllStates, the Gated contrast pair (`TextInput.stories.tsx`:22–105)                                                                                                                                                                                                                                                          | `15`:117; `15`:114–115                                                                                                 |
  | CMP-008 NumericStepperInput          | Default, WithUnit, Hover, FocusVisible, Tabular, MinMaxClamped, KeyboardStepDemo, OutOfRangeEntry, RoundedEntry, Invalid, Disabled, DisabledWithReason, ReadOnly, LongValue, AllStates, the Gated contrast pair (`NumericStepperInput.stories.tsx`:36–260)                                                                                                                                                                                      | `15`:127; `15`:124–125                                                                                                 |
  | CMP-009 Select                       | Default, Placeholder, Hover, FocusVisible, Open, KeyboardChoose, Invalid, Disabled, DisabledWithReason, LongValue, LongList, UnavailableOption, TypeAhead, LongListUnavailable, AllStates, the Gated contrast pair (`Select.stories.tsx`:52–261)                                                                                                                                                                                                | `15`:137 lists Searchable, LongList (virtualized), WithSpecimen, Mixed; the exports above are the base                 |
  | CMP-034 MaskedValue                  | Masked, FocusVisible, Hover, Revealed, AutoHideCountdown, Expiring, Copyable, CopiedState, LongText, OneRevealedPerPage, the contrast pair (`MaskedValue.stories.tsx`:48–174)                                                                                                                                                                                                                                                                   | `15`:405; `15`:402–403, :407                                                                                           |
  | CMP-040 FormField                    | Default, WithError, WithHelp, Required, Optional, Inline, InlineNarrow, ReadOnly, Disabled, DisabledWithReason, WithSelect, DisabledSelect, SelectWithReason, WithStepper, AllStates (`FormField.stories.tsx`:38–211)                                                                                                                                                                                                                           | `15`:475; `15`:472–473, :477                                                                                           |
  | CMP-047 DatePicker / DateRangePicker | DatePicker: Single, Empty, Hover, Focused, Open, KeyboardPick, WithMinMax, WithTime, Invalid, TypedError, Disabled, DisabledWithReason, ReadOnly, AllStates, the contrast pair (`DatePicker.stories.tsx`:52–202); DateRangePicker: Range, Empty, Open, RangeOpen, KeyboardRange, WithMinMax, WithTime, Narrow, Invalid, TypedError, Disabled, DisabledWithReason, ReadOnly, AllStates, the contrast pair (`DateRangePicker.stories.tsx`:58–200) | `15`:558; `15`:555–556, :560 (two exports, ISO strings, UTC)                                                           |
  | CMP-048 Combobox                     | Default, Hover, FocusVisible, Sync, AsyncLoading, NoResults, SearchFailed, Invalid, Disabled, DisabledWithReason, GatedOption, LongLabel, LongReason, Paging, SettleUnanimated (`Combobox.stories.tsx`:79–267)                                                                                                                                                                                                                                  | `15`:569; `15`:566–567, :571                                                                                           |
  | CMP-049 Table                        | Default, Sortable, SortPending, Loading, Empty, FilteredEmpty, ErrorStory, LongText, Scrolling, CaptionHidden, Compact, Reflow, Selectable, Grid, RowActions (`Table.stories.tsx`:95–521; `Perf200Rows` :381 is `perf`-tagged, excluded from VR)                                                                                                                                                                                                | `15`:583 lists Virtualized(10k rows), MergedCell, SortUnavailable; as built (`15`:585–587) none ships: a 200-row bound |
  | CMP-054 SearchBox                    | Default, WithValue, ClearReturnsFocus, Focused, Hover, Disabled, LongText, AllStates (`SearchBox.stories.tsx`:47–116)                                                                                                                                                                                                                                                                                                                           | `15`:633; `15`:630–631, :635                                                                                           |
  | CMP-065 FormSection                  | Default, HeadingLevel2, Collapsible, Collapsed, WithErrors, Disabled, DisabledWithReason, LongText, OpensOnSubmit, OpensOnNativeInvalid, AllStates (`FormSection.stories.tsx`:41–192)                                                                                                                                                                                                                                                           | `15`:738; `15`:735–736, :740                                                                                           |
  | CMP-079 RbacGate                     | Allowed, DeniedPermission, DeniedOwnerOnly, DeniedAccount, DeniedAccountReadOnly, DeniedEnv, DeniedReadOnly, DeniedViewAs, FormInline (`RbacGate.stories.tsx`:43–93)                                                                                                                                                                                                                                                                            | `15`:888 lists Denied(EnvMismatch), FormTooltip, FormNotice too: **not exported at the base** († section 10)           |

- Expected: as C01 over 164 stories × 6 = 984 cells; every `Invalid` cell shows the 2 px danger boundary, the `danger` glyph
  and the message, never colour alone (`15`:114); every `DisabledWithReason` cell shows the `lock` leading the value inside the
  well (`15`:124, :134, :472, :555); the stacked Table cell of `AllMolecules` shows one block per row with every header label
  present and no sideways overflow at every theme × density.
- Oracle: `15` > the VR cells; the `AllMolecules` play's stacked assertion (`HO-S03`:23, white-box). 2nd: axe for every story.
- Blocked on: the three RbacGate stories `15`:888 lists and the base does not export (E05-S04 #267; OQ-4). The rest runs today.

**E05-Q01-C16 The family's keyboard-only walk, scripted by the Atoms and Molecules tables [R]** (`e2e`, `a11y`; 3.3 · S01–S04;
`Atoms.mdx`:40 NumericStepperInput, :99 Select, :131 TextInput, :346 MaskedValue; `Molecules.mdx`:28 FormField, :54 FormSection,
:76 SearchBox, :109 Combobox, :385 Table, :422 Table grid mode, :532 DatePicker, :573 DateRangePicker; `HO-S03`:66–78, :138)

- Pre: as C02 (no pointer; dark · compact then light · comfortable; 100 % then 200 % zoom; 1280 × 800).
- Steps: walk each table row by row on `NumericStepperInput` `KeyboardStepDemo`, `Select` `KeyboardChoose` and `TypeAhead`,
  `DatePicker` `KeyboardPick`, `DateRangePicker` `KeyboardRange`, `Combobox` `Sync` and `Paging`, `Table` `Grid`, `Selectable`
  and `RowActions`, `SearchBox` `ClearReturnsFocus`, `FormSection` `Collapsible` and `OpensOnSubmit`, `MaskedValue` `Masked`,
  `FormField` `WithStepper`; read the focus ring at every stop.
- Expected: the spin button steps by `step` on the arrows, by 10 × `step` on `Shift+↑/↓`, by `largeStep` on `PageUp/Down`, to the
  bounds on `Home/End`, and its `[−]` / `[+]` buttons are out of the `Tab` order (`15`:125); the select is a select-only combobox
  whose trigger keeps focus while `aria-activedescendant` moves, type-ahead jumps to the next matching label and `Esc` closes with
  the value unchanged (`15`:135; `Select.stories.tsx`:210); the date grid moves by day and week on the arrows, by month on
  `PageUp/Down`, `Enter` picks and focus returns to the calendar button (`15`:556; `DatePicker.stories.tsx`:94); the table is one
  `Tab` stop in grid mode, the arrows move by cell with the header row included, `Home/End` and `Ctrl+Home/End` clamp, an
  interactive cell's controls leave the `Tab` order and `Enter` or `F2` moves in, `Esc` back (`HO-S03`:17, :76); `Shift+F10` on
  a row opens its actions menu and `Esc` returns focus to the cell (`Table.stories.tsx`:518–520); `Esc` in a SearchBox clears a
  non-empty query and keeps focus, bubbling only once empty (`15`:631); the collapsible section's disclosure toggles on `Enter`
  and focus stays; a submit around a collapsed invalid field opens the section and focus reaches the field
  (`FormSection.stories.tsx`:148); the masked value's toggle and Copy are `Tab` stops and Copy is skipped while masked (`SR-S02`
  M8's expectation; `15`:403). Rings and labels unclipped at 200 % and 1280 × 800; nothing needs a pointer.
- Oracle: the mdx tables and the `15` A11y lines > the hand-off's named tests (`HO-S03`:16–17, :70–78, white-box evidence) > the
  focus target at each step. 2nd: none (a read).
- Blocked on: none.

**E05-Q01-C17 Numeric input is tabular [R]** (`e2e`; 3.3 · S01; mirrors S01.4 "Numeric input is tabular"; `15`:40 rule 6;
`NumericStepperInput.stories.tsx`:66 `Tabular`; `HO-S01`:12)

- Pre: dark · compact; `Tabular` with the value 1234.50; then 200 % zoom.
- Steps: read the computed `font-family`, `font-variant-numeric` and `text-align` of the value; read the digits' right edges
  against `WithUnit` beside it.
- Expected: the value renders in the monospaced numeric family with tabular numerals, right-aligned (`15`:40; S01.4), the
  suffix unit after it; at 200 % the alignment holds and nothing clips.
- Oracle: `15`:40 > the `Tabular` play (computed `font-variant-numeric` and mono family, `HO-S01`:12) > the six `Tabular` cells.
  2nd: none (a read).
- Blocked on: none.

**E05-Q01-C18 Invalid numeric entry is shown, never coerced [R] [F]** (`e2e`, `a11y`; 3.3 · S01; mirrors S01.5 "Invalid numeric
entry"; `15`:125 (parsed, rounded, range-checked on blur); `NumericStepperInput.stories.tsx`:114 `OutOfRangeEntry` (min 0, type
−5, blur), :128 `RoundedEntry`, :80 `MinMaxClamped`; `HO-S01`:13)

- Pre: dark · compact; `OutOfRangeEntry`.
- Steps: type `-5` and `Tab` away; read the field, the message and the tree; press `↓` at the minimum on `MinMaxClamped`.
- Expected: the error state shows with a message, the typed value is **not** silently coerced (the field keeps `-5`), and
  `aria-invalid="true"` is set with `aria-describedby` pointing at the message, which was in the DOM at mount and is announced
  politely once (`15`:115, :125); at a bound the matching step button is plain disabled, availability not T2 (`15`:124). The
  `Invalid` cells show the 2 px danger boundary and the `danger` glyph with the message.
- Oracle: `15`:124–125 > `NumericStepperInput.test.tsx` "an out-of-range entry is invalid, never clamped: error shown, value
  unchanged (AC)" (`HO-S01`:13) > the tree. 2nd: axe for `OutOfRangeEntry`.
- Blocked on: none.

**E05-Q01-C19 A masked value never leaks by default [R] [F]** (`e2e`, `a11y`, `security`; 3.3 · S02; mirrors S02.4 "Masked value
never leaks by default"; `15`:401–403, :407; `MaskedValue.stories.tsx`:48 `Masked`, :70 `Revealed`, :96 `Expiring`
(`autoHideMs: 3000`), :129 `Copyable`, :174 `OneRevealedPerPage`; `SR-S02` M1–M9 as E05-Q02's; section 4 the 3–30 s clamp)

- Pre: dark · compact; the stories above; the clipboard permitted for the origin.
- Steps: on `Masked` read the DOM and the tree without pressing anything; press the toggle, read the value and the toggle's
  name; on `Expiring` press the toggle, read the live region during the last 2 s and after the timeout (≤ 5 s of waiting);
  on `Copyable` press Copy while masked, then while revealed, and read the clipboard and the live region; on
  `OneRevealedPerPage` reveal the first, then the second.
- Expected: at mount the value is masked with an 8-character mask whatever its length and the DOM holds the mask only, never the
  value (`15`:402–403); reveal is an explicit press of the toggle, named "Show {label}" then "Hide {label}" (`15`:403); the
  revealed value re-masks after `autoHideMs` (3 s in the story; the default 10 s and the 3–30 s clamp, `15`:401, :407) with one
  polite announcement about 2 s before ("{label} will hide in 2 seconds"-form) and no per-second count; Copy is disabled while
  masked, copies without the live region ever speaking the value, and "Copied" is announced once; revealing a second value masks
  the first in the same step (`15`:407). `revealed={true}` never reveals at mount (`15`:407).
- Oracle: `15`:401–407 > the DOM scanned for the value (a presentation check) and the live region's text. 2nd: axe for `Masked`
  and `Revealed`. A value found in the DOM while masked, or spoken by the live region, is **P0** (section 5; `03` §11.3
  "security breach").
- Blocked on: none.

**E05-Q01-C20 A form field wires label, help and error [R] [F]** (`e2e`, `a11y`; 3.3 · S03; mirrors S03.1 "Form field wires
label, help and error"; `15`:472–473, :477; `FormField.stories.tsx`:45 `WithError` (`help` and `error` together), :82 `Inline`,
:125 `DisabledWithReason`, :168 `SelectWithReason`; `HO-S03`:9, :53)

- Pre: dark · compact and high-contrast · comfortable; `WithError`, then `DisabledWithReason`.
- Steps: read the control's accessible name, `aria-describedby` chain and `aria-invalid`; type a value and read the label; on
  `DisabledWithReason` read the chain and press keys.
- Expected: the control's name comes from the persistent `<label for>` (never a placeholder, `15`:473; S03.1), `aria-describedby`
  references the error then the help id, `aria-invalid="true"` is set, and the error line shows the `danger` glyph and the words,
  announced politely once (`FormField.stories.tsx`:44); while T2 the chain holds the reason id alone and the field never validates
  (`15`:473; `HO-S03`:53), the `lock` leading the value and the reason under the control in the secondary colour (`15`:472). This is
  the visible reason line A-12 defers to (C03).
- Oracle: `15`:472–477 > `FormField.test.tsx` "wires the label, the help and the error to the control" and "keeps the label when
  a value is typed" (`HO-S03`:9) > the tree. 2nd: axe for `WithError`.
- Blocked on: none.

**E05-Q01-C21 Combobox keyboard follows the APG pattern and announces once per settled query [R]** (`e2e`, `a11y`; 3.3 · S03;
mirrors S03.7 "Combobox keyboard"; `15`:567 (the count once per settled query, 500 ms after the last keystroke), :571 (a gated
option reached, never chosen; the listbox portals into the topmost layer); `Combobox.stories.tsx`:107 `Sync`, :196 `GatedOption`,
:248 `Paging`, :267 `SettleUnanimated`; `HO-S03`:15, :59)

- Pre: dark · compact; motion `system`, then `on`.
- Steps: `Tab` to `Sync`, type a query and wait for the settle (≤ 1 s); press `↓`, `↓`, `↑`, `Enter`; reopen, press `Esc`, then
  `Esc` again; `Alt+↓`, `Alt+↑`; on `Paging` press `PageDown`; on `GatedOption` arrow onto the gated row and press `Enter`; on
  `SettleUnanimated` under motion `on` read the list's entrance.
- Expected: the APG editable combobox: `aria-expanded`, the active option named by `aria-activedescendant` and announced with its
  position, `↓` opens a closed list on the first option, `Alt+↓` opens without moving, `Alt+↑` closes, `Enter` chooses and shows
  the label, the first `Esc` closes the list and keeps the text, a second `Esc` bubbles, leaving never chooses (`HO-S03`:15); one
  polite results count once the query settles (500 ms by default, 300 ms with CMP-160's tuning), never per keystroke (`15`:567);
  status rows ("Searching…", the host's no-results and failed sentences) are not options (`15`:566); `PageDown` moves by the
  visible rows with no wrap (`15`:572); the gated option is reached, its reason read, and `Enter` says the reason once and chooses
  nothing (`15`:571; `HO-S03`:59); under reduced motion the list appears with no fade.
- Oracle: `15`:566–572 > `Combobox.test.tsx` "Gherkin 'Combobox keyboard' …" and the three beside it (`HO-S03`:15) > the tree
  and the live region. 2nd: axe for `Sync`.
- Blocked on: none.

**E05-Q01-C22 Table reflow at 200 % zoom, compact [R]** (`e2e`; 3.3 · S03; mirrors S03.5 "Table reflow at 200% zoom"; `15`:580
(stacked below the fit width and at 200 % zoom), :586; `Table.stories.tsx`:281 (44 em of column minimums: 704 px at 16 px,
1,408 px at 200 %), :325 `Reflow`, :329 the 1280 × 800 frame, :335–354 the play's four steps; `AllMolecules.stories.tsx`:290;
`HO-S03`:13; `05`:131 rule 7)

- Pre: compact density at each theme; a 1280 × 800 browser window; `Table` `Reflow`.
- Steps: at 100 % browser zoom read the table; set the browser zoom to 200 % and read it again; narrow the frame to 640 px (the
  story's own step) and read; return to 100 %. Then open `Default` at 200 % browser zoom in a 1920 × 1080 window.
- Expected: at 100 % on the 1280 px frame a table; at 200 % the rows reflow to a stacked layout, one block per row, each value
  preceded by its column header, with no horizontal clipping and no column's data lost (S03.5; `15`:586); the same at 640 px;
  back at 100 % a table again; the explicit table roles are kept while stacked (`HO-S03`:13); the `AllMolecules` stacked cell is
  the committed at-rest look of the same layout at a 200 % text scale (`AllMolecules.stories.tsx`:290–291). The browser-zoom leg
  is manual: the story's play scales the root font size, and VR captures at 100 % only (section 0). The high-contrast and
  compact composition is C56.
- Oracle: `15`:580–586 > the `Reflow` play and `Table.test.tsx` "tracks a font-size change at the same width (200 % zoom) through
  the em probe" (`HO-S03`:13, white-box) > the layout read (UI only) > the six `Reflow` cells and the `AllMolecules` stacked cell.
  2nd: none (a read).
- Blocked on: none.

**E05-Q01-C23 The table's states, sort and grid mode [F]** (`e2e`, `a11y`; 3.3 · S03; `15`:580–581, :585–587;
`Table.stories.tsx`:115 `Sortable`, :151 `Loading`, :161 `Empty`, :181 `FilteredEmpty`, :202 `ErrorStory`, :245 `Scrolling`,
:446 `Selectable`, :473 `Grid`, :521 `RowActions`; `HO-S03`:17, :60; `SR-S03` B1–B11 as C62's)

- Pre: dark · compact and light · comfortable.
- Steps: on `Sortable` `Tab` to a header and press `Enter`, then `Enter` again, then `Space`; read `aria-sort` and the live
  region; read `Loading`, `Empty`, `FilteredEmpty` and `ErrorStory`; on `Scrolling` `Tab` into the region and scroll by keyboard;
  on `Selectable` press `Space` on a row, then on select-all; on `RowActions` open the row menu and arrow onto "Edit risk caps".
- Expected: sortable headers are buttons with `aria-sort` cycling ascending then descending, the result said once politely
  (`15`:581); loading keeps the header row over skeleton rows with `aria-busy`; empty and filtered-empty keep the header row with
  the CMP-026 block across every column; error keeps the header row with the CMP-027 block and Retry, announced politely
  (`15`:580); the scrolling region is a `Tab` stop named by the caption and the header stays on top (`Table.stories.tsx`:244);
  selection is a grid: `Space` toggles the focused row and the count is said once, select-all reads mixed then checked
  (`Table.stories.tsx`:441–443); the T2 row action is reachable by the arrows with its reason as the second line and never
  activates (`Table.stories.tsx`:518–519; `HO-S03`:60). The `Virtualized(10k rows)`, `MergedCell` and `SortUnavailable` stories
  `15`:583 lists do not exist at the base (`15`:585–587): not asserted.
- Oracle: `15`:580–587 > `Table.test.tsx` "keyboard header-sort …", "T2 items are arrow-reachable, never activated …"
  (`HO-S03`:17, :60) > the tree and live region. 2nd: axe for `ErrorStory` and `Grid`.
- Blocked on: none.

**E05-Q01-C24 Disabled-with-reason through RbacGate [R] [F]** (`e2e`, `a11y`; 3.3 · S04; mirrors S04.5 "Disabled-with-reason";
`15`:883–886 (`allowed`, `reason`, `form`; T2: role and full label kept, `aria-disabled="true"`, the description); `15`:888;
`RbacGate.stories.tsx`:6 ("each story is one wrapped Button, T1 or T2"), :56 `DeniedPermission`, :93 `FormInline`;
`rbacReasons.ts`:8–14; `HO-S03`:47–49)

- Pre: dark · compact and high-contrast · compact; `Allowed`, the seven `Denied*` stories, `FormInline`.
- Steps: on `Allowed` read the control and its description; on each `Denied*` `Tab` to the control, read its name, state and
  description, hover it, press `Enter`, `Space`, click it; on `FormInline` read the two atoms' described-by nodes.
- Expected: `Allowed` wraps the control unchanged with no description (`RbacGate.stories.tsx`:52); a denied control is
  non-operable yet focusable, keeps its role and full label, carries `aria-disabled="true"` and its reason as the accessible
  description, present at mount and so on hover and focus (S04.5; T2); the reason is the vocabulary sentence of its key, verbatim
  — `rbac.permission` "Your role can't {verb}.", `rbac.owner_only` "Only the owner can {verb}.", `rbac.account` "This account
  isn't assigned to you.", `rbac.account_read_only` "You can view this account, not trade it.", `rbac.env` "Live trading isn't
  enabled for you.", `rbac.read_only` "Read-only after three wrong codes.", `rbac.view_as` "Read-only while viewing as {user}."
  (`rbacReasons.ts`:8–14) — with the story's fills; `FormInline` renders the reason as each atom's own described-by node
  (`RbacGate.stories.tsx`:91). No handler fires on any key or click (the abuse leg is C64). The `tooltip` and `notice` forms
  (`15`:884–885) have no story at the base.
- Oracle: `15`:883–886 and T2 > `RbacGate.test.tsx` (white-box; the S04 Test plan's "RbacGate blocks handler invocation") > the
  tree. 2nd: axe for `DeniedPermission`.
- Blocked on: the `FormTooltip`, `FormNotice` and `Denied(EnvMismatch)` legs — E05-S04 (#267; OQ-4). The rest runs today.

**E05-Q01-C25 Select, DatePicker, SearchBox and FormSection states [F]** (`e2e`, `a11y`; 3.3 · S01, S03; `15`:134–135, :555–556,
:630–631, :735–736; `Select.stories.tsx`:189 `UnavailableOption`, :126 `DisabledWithReason`; `DatePicker.stories.tsx`:170
`TypedError`, :186 `DisabledWithReason`, :146 `WithTime`; `SearchBox.stories.tsx`:57 `WithValue`; `FormSection.stories.tsx`:89
`WithErrors`, :74 `Collapsed`, :108 `DisabledWithReason`; `HO-S03`:54, :58)

- Pre: dark · compact.
- Steps: on `UnavailableOption` arrow onto the unavailable and the T2 options and press `Enter`; on Select `DisabledWithReason`
  press `↓`; on DatePicker `TypedError` type text that does not parse and `Tab` away; on DatePicker `DisabledWithReason` press
  the calendar button; on `WithTime` type `9:05`; on `WithValue` read the clear button and press it; on `WithErrors` collapse the
  section and read its legend; on FormSection `DisabledWithReason` read every field's described-by target.
- Expected: an unavailable or T2 option is arrow-reachable, `aria-disabled`, described by its reason, and `Enter` never chooses
  (`Select.stories.tsx`:187); a T2 select's listbox never opens and the `lock` leads the value (`15`:134); unparseable date text
  shows the picker's own message on blur (`DatePicker.stories.tsx`:168) and a T2 picker's fields are `readonly`, its button
  `aria-disabled` and the dialog never opens (`15`:555; `HO-S03`:58); the time well takes `H:MM` or `HH:MM` 24-hour UTC
  (`15`:560); the clear button renders only with a value, is labelled "Clear search" and returns focus to the field (`15`:631);
  a collapsed section with an invalid field names its count and opens on submit (`15`:735–736); a T2 section has one notice that
  every gated field's `aria-describedby` points at, with no reason line per field (`HO-S03`:54).
- Oracle: the `15` States and A11y lines > the hand-off's tests (`HO-S03`:54, :58) > the tree. 2nd: axe for `UnavailableOption`
  and `WithErrors`.
- Blocked on: none.

**E05-Q01-C26 Colour is never the only signal in the family (smoke)** (`a11y`; 3.3 · S01–S04; `15`:37 rule 3; `TextInput`
`Invalid`, `NumericStepperInput` `Invalid`, `Select` `Invalid`, `DatePicker` `Invalid`, `FormField` `WithError`, `Table`
`Sortable` and `Selectable`, every `DisabledWithReason`, `MaskedValue` `Expiring`)

- Pre: as C06 (high-contrast, greyscale).
- Steps: read each story in greyscale and through the tree.
- Expected: invalid is the glyph plus the message, never the boundary colour alone (`15`:114); T2 is the `lock` glyph plus the
  reason, never the dimmed fill alone; sort state is the glyph plus `aria-sort`; selection is the checkbox state plus the said
  count, never the row fill alone (`15`:581); the expiring mask is announced, never shown only by a colour.
- Oracle: `15`:37 and the A11y lines > the tree. 2nd: axe.
- Blocked on: none.

### 3.4 Feedback and overlays (CMP-015, 016, 017, 023, 026, 027, 028, 029, 038, 041, 043, 044, 045, 046, 089, 090, 091; S02, S03, S04)

**E05-Q01-C27 The family's full matrix is rendered and snapshot-stable [R]** (`e2e`; 3.4 · S02–S04; mirrors `15`:41 rule 7 and
`HO-S03`:23 ("Dialog, ConfirmDialog, Drawer and CommandPalette each open in their own story per theme × density");
`AllMolecules.stories.tsx` the Dialog, ConfirmDialog and Drawer sets)

- Pre: as C01.
- Steps: as C01, over this table; in `Molecules/All molecules matrix` read the eighteen Dialog / ConfirmDialog / Drawer cells at
  their equal-global cell.

  | Component                           | Stories read                                                                                                                                                                                                                                                                   | `15` list and as-built                                                                                                                        |
  | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
  | CMP-015 Skeleton                    | Default, Row, Card, Chart, OnOverlay, Static, LongCount, AllShapes, Light, HighContrast (`Skeleton.stories.tsx`:46–97)                                                                                                                                                         | `15`:199; `15`:196–197, :201                                                                                                                  |
  | CMP-016 Tooltip                     | Default, LongContent, KeyboardTriggered, EscDismiss, EchoName, EchoReason, Right, Bottom, Left, EdgeFlip, the contrast pair (`Tooltip.stories.tsx`:47–126)                                                                                                                     | `15`:209 lists Echo; the build splits it into EchoName and EchoReason                                                                         |
  | CMP-017 Popover                     | Default, NonModal, Modal, EscDismiss, OutsideClick, Above, Flipped, Scrolling, the contrast pair (`Popover.stories.tsx`:108–224)                                                                                                                                               | `15`:219; `15`:217, :222–223                                                                                                                  |
  | CMP-023 ProgressBar                 | Default, Empty, Complete, Unlabelled, Meter, Success, Warning, Danger, LongText, AllTones, Light, HighContrast, ReducedMotion (`ProgressBar.stories.tsx`:21–102)                                                                                                               | `15`:283 lists Running, Failed, Unknown, InWizard too; `15`:280–281 (determinate only)                                                        |
  | CMP-026 EmptyState                  | Default, FocusVisible, RecordingNotStarted, BackfillInProgress, FilteredEmpty, ErrorVariant, SentenceForm, FilteredEmptyNoMatch, FilteredEmptyStatusRule, ErrorWithTwoActions, AllVariants, LongText, LongActionAndReason, the contrast pair (`EmptyState.stories.tsx`:24–238) | `15`:315; `15`:312–313, :317                                                                                                                  |
  | CMP-027 ErrorState / InlineError    | ErrorSeverityStory, Warning, WithRetry, Polite, WithDetails, Inline, InlineWithRetry, Banner, BannerWarning, Summary, LiveOff, LongText, the contrast pair (`ErrorState.stories.tsx`:28–184)                                                                                   | `15`:327; `15`:324–325, :329 ("Storybook names Error as ErrorSeverityStory")                                                                  |
  | CMP-028 Callout / Banner            | Default, AllTones, ConnectionReconnecting, ConnectionDisconnected, LivePolite, Band, Dismissible, DismissFocusVisible, ProtectionPendingSolidEdge, CustomIcon, LongText, the contrast pair (`Callout.stories.tsx`:51–188)                                                      | `15`:339 lists ChartStrip, BarRebuildProgress too; `15`:336–337, :341 (`edge` not built; the Unprotected story is ProtectionPendingSolidEdge) |
  | CMP-029 SkeletonChart               | Default, ThreePanes, Static, Light, HighContrast (`SkeletonChart.stories.tsx`:40–59)                                                                                                                                                                                           | `15`:352 (SinglePane / MultiPane are Default / ThreePanes, `15`:354)                                                                          |
  | CMP-038 InlineSpinnerText           | Default, SlowPath, SlowPathWithCancel, SubmitNeverCancels, LongText, the contrast pair (`InlineSpinnerText.stories.tsx`:31–84)                                                                                                                                                 | `15`:447; `15`:444–445, :449                                                                                                                  |
  | CMP-041 Menu                        | Default, Hover, FocusVisible, Active, WithShortcuts, Checkable, PickOne, Disabled, DisabledWithReason, LongLabelAndReason, Danger, Busy, Scrolling, NestedSubmenu, ContextMenu, ContextMenuKeyboard, HostOpened, EscTopmost, the contrast pair (`Menu.stories.tsx`:94–567)     | `15`:487; `15`:484–485, :489                                                                                                                  |
  | CMP-043 Dialog                      | Default, Small, Large, AlertDialog, Scrolling, Busy, Reflow, ExemptRegion, EscTopmost, StackedDiscard, NoLayoutShift, the contrast pair (`Dialog.stories.tsx`:99–406)                                                                                                          | `15`:509; `15`:506–507, :511                                                                                                                  |
  | CMP-044 ConfirmDialog               | Standard, Guard, Typed, TypedMatch, Busy, PartialFailure, ConfirmGated, OrderConfirm, Hold, HoldReleasedEarly, Holding, Armed, HoldKeyboard, HoldReducedMotion, CountingDown, TimedOut, LongText, the contrast pair (`ConfirmDialog.stories.tsx`:103–463)                      | `15`:520 lists Rung1–4, TwoChoice, TwoChoiceUnknown, RuleDisarm too (E42 / E35 design rows); `15`:517–518, :522                               |
  | CMP-045 Toast                       | Default, AllTones, Success, WithAction, Persistent, PersistentLogLink, Focused, ActionGated, Undo, UndoOutcome, LongText, Region, RegionUntilDismissed, RegionUnderModal (`Toast.stories.tsx`:63–270)                                                                          | `15`:532; `15`:529–530, :534                                                                                                                  |
  | CMP-046 Drawer                      | Modal, NonModal, LeftSide, RightSide, Loading, Narrow, HostWidthAndName, LongText, FallbackReturn, the contrast pair (`Drawer.stories.tsx`:75–215)                                                                                                                             | `15`:544; `15`:541–542, :546                                                                                                                  |
  | CMP-089 ForbiddenState              | Default, NoRef, Withdrawn, AccountVariant (`ForbiddenState.stories.tsx`:21–39)                                                                                                                                                                                                 | `15`:991; `15`:987, :989                                                                                                                      |
  | CMP-090 NotFoundState               | Default, Admin, Deleted (`NotFoundState.stories.tsx`:21–30)                                                                                                                                                                                                                    | `15`:1000; `15`:996, :998                                                                                                                     |
  | CMP-091 GlobalErrorBoundaryFallback | PanelLevel, RouteLevel, AppLevel, RepeatedCrash, WithDetails, Details, LongDetails (`GlobalErrorBoundaryFallback.stories.tsx`:28–47)                                                                                                                                           | `15`:1009; `15`:1005, :1007                                                                                                                   |

- Expected: as C01 over 190 stories × 6 = 1,140 cells; every overlay cell shows the card over the scrim at its size, the
  skeleton cells the static two-tone (captured under `reduce`), the alert and status regions their glyph and words.
- Oracle: `15` > the VR cells. 2nd: axe for every story.
- Blocked on: none.

**E05-Q01-C28 The family's keyboard-only walk, scripted by the Molecules tables [R]** (`e2e`, `a11y`; 3.4 · S02–S04;
`Atoms.mdx`:290 Tooltip, :305 Popover, :418 Callout, :441 EmptyState, :463 ErrorState; `Molecules.mdx`:214 Dialog, :244
ConfirmDialog, :307 Toast, :334 Drawer, :466 Menu; `HO-S03`:71–73, :78)

- Pre: as C02 (no pointer; dark · compact then high-contrast · comfortable; 100 % then 200 % zoom; 1280 × 800; motion `system`
  then `on`).
- Steps: walk the tables on `Menu` `WithShortcuts`, `NestedSubmenu`, `ContextMenuKeyboard` and `Checkable`; `Dialog` `Default`
  and `Scrolling`; `Drawer` `Modal` and `NonModal`; `ConfirmDialog` `Standard` and `HoldKeyboard`; `Toast` `Region`; `Popover`
  `NonModal` and `Modal`; `Tooltip` `KeyboardTriggered`; `Callout` `Dismissible`; `EmptyState` `Default`; `ErrorState`
  `WithRetry`; `GlobalErrorBoundaryFallback` `PanelLevel`.
- Expected: a menu opens on `Enter`, `Space` or `↓`, the arrows and type-ahead move, `Enter` activates and closes, `Space`
  toggles a checkable item and keeps it open, `Tab` closes every menu and moves on, `Esc` closes and returns focus, `Shift+F10`
  or the Menu key opens a context menu at the row, `←` or `Esc` closes a submenu alone (`15`:485; `Menu.stories.tsx`:397, :465); a
  dialog traps `Tab` both ways and cycles at the edges, a body that scrolls with no control is a `Tab` stop, `Esc` closes and
  returns focus (`15`:507; `HO-S03`:72); a non-modal drawer lets `Tab` flow on to the page after the opener and stays open
  (`Drawer.stories.tsx`:96); the hold gate has its discrete keyboard path (C35); a focused toast pauses every timer and `Esc`
  moves focus on (`Toast.stories.tsx`:233–234); a non-modal popover closes on `Tab` past its last control and `Shift+Tab` before
  the first returns to the trigger, a modal one cycles (`Popover.stories.tsx`:122, :139); a tooltip shows on focus and `Esc` hides
  it with focus kept (`Tooltip.stories.tsx`:70, :81); the dismiss, retry and reload controls are reachable and named. Rings and
  text unclipped at 200 % and 1280 × 800; under motion `on` every entrance is a cut and nothing is lost.
- Oracle: the mdx tables and `15` A11y lines > the hand-off's named tests (`HO-S03`:71–73, :78, white-box) > the focus target at
  each step. 2nd: none (a read).
- Blocked on: none.

**E05-Q01-C29 Tooltip keyboard and dismissal [R]** (`e2e`, `a11y`; 3.4 · S02; mirrors S02.2 "Tooltip keyboard and dismissal";
`15`:206–207, :211; `Tooltip.stories.tsx`:73 `KeyboardTriggered`, :84 `EscDismiss`, :47 `Default`; `SR-S02` T1–T6 as E05-Q02's)

- Pre: dark · compact; motion `system`, then `on`.
- Steps: `Tab` to the trigger; read the tooltip node, its role and the trigger's `aria-describedby`; press `Esc`; read focus;
  press `Esc` again; `Tab` away and back; hover the trigger with the pointer and wait the 300 ms delay.
- Expected: on keyboard focus the tooltip appears at once beside the ring, `role="tooltip"`, linked by `aria-describedby`
  (S02.2; `15`:207); in `describes` mode its node is in the DOM at mount, `hidden` until shown, so the description is there when
  focus lands (`15`:207); `Esc` hides it while focus stays on the trigger, and a second `Esc` reaches the host (`Tooltip.stories.tsx`
  :81; `SR-S02` T3's expectation); it never traps focus; hover shows it after the 300 ms default delay (`15`:206); an empty
  `content` renders no node (`15`:211). It flips rather than clips at an edge (`EdgeFlip`).
- Oracle: `15`:206–211 > the two stories' plays (white-box) > the tree. 2nd: axe for `KeyboardTriggered`.
- Blocked on: none.

**E05-Q01-C30 Popover focus management [R]** (`e2e`, `a11y`; 3.4 · S02; mirrors S02.3 "Popover focus management"; `15`:217,
:222–223; `Popover.stories.tsx`:124 `NonModal`, :141 `Modal`, :162 `EscDismiss`, :178 `OutsideClick`; `SR-S02` P1–P6 as
E05-Q02's)

- Pre: dark · compact.
- Steps: open `NonModal` from its trigger by `Enter`; read focus; `Tab` past the last control; reopen and `Shift+Tab` before the
  first; open `Modal` and `Tab` around both ends; press `Esc`; on `OutsideClick` press outside with the pointer.
- Expected: focus moves into the popover on open (its first control, `initialFocusRef` or its heading, `15`:217); it is a
  `role="dialog"` named by its heading, `aria-modal="true"` only when `modal` (`15`:217); in a non-modal popover `Tab` past the
  last control closes it and moves on from the trigger and `Shift+Tab` before the first returns (`Popover.stories.tsx`:122); a
  modal one contains `Tab` both ways (S02.3's "where the catalogue specifies a trap"); `Esc` closes and returns focus to the
  trigger (`Popover.stories.tsx`:160); click-outside closes with the `pointerdown` guard (`15`:217); the trigger carries
  `aria-haspopup`, `aria-expanded` and `aria-controls` (`15`:222). Inside a Dialog it portals into the dialog's layer (C53).
- Oracle: `15`:217–223 > the stories' plays > the tree. 2nd: axe for `Modal`.
- Blocked on: none.

**E05-Q01-C31 Skeletons and the progress bar respect reduced motion [R]** (`e2e`; 3.4 · S02; mirrors S02.6 "Skeleton respects
reduced motion"; `15`:196 (one sweep per 1,200 ms, stopped at 5 s; static under reduced motion from the first frame), :349,
:280–281; `Skeleton.stories.tsx`:84 `Static`, :46 `Default`; `SkeletonChart.stories.tsx`:59 `Static`; `ProgressBar.stories.tsx`
:102 `ReducedMotion`; `16`:167; `05`:205–209 §7)

- Pre: dark · compact; motion `system` with the OS preference off, then `on`, then the OS preference set to reduce with
  motion `system`.
- Steps: open `Skeleton` `Default` and read the fill for 6 s; open `Static` and `SkeletonChart` `Static` and read the root's
  `data-motion` and the fill from the first frame; on `ProgressBar` `ReducedMotion` change the value and watch the bar.
- Expected: motion-safe: the band sweeps once per 1,200 ms and stops at 5 s, after which the two-tone fill stands (`15`:196);
  under `data-motion="reduce"` (the in-app override or the OS preference) the shimmer loop does not run and the static two-tone
  shows from the first frame (S02.6; `Skeleton.stories.tsx`:83); the skeleton is `aria-hidden` and the parent carries `aria-busy`
  (`15`:197, :350); a new progress value is a step, not a slide (`ProgressBar.stories.tsx`:101). The `Static` cells are the
  committed at-rest look; the motion-safe sweep is manual (VR captures under `reduce`).
- Oracle: `15`:196–197, :280–281 > the root attribute and the fill over time (UI only). 2nd: none (a read).
- Blocked on: none.

**E05-Q01-C32 Empty and error states are first-class [R] [F]** (`e2e`, `a11y`; 3.4 · S02; mirrors S02.7 "Empty and error states
are first-class"; `15`:310–313, :317 EmptyState; `15`:323–325, :329 ErrorState; `EmptyState.stories.tsx`:24 `Default`, :85
`ErrorVariant`, :101 `SentenceForm`, :190 `AllVariants`; `ErrorState.stories.tsx`:28 `Warning`, :52 `Polite`, :84 `Inline`,
:160 `Summary`, :174 `LiveOff`)

- Pre: dark · compact and high-contrast · comfortable.
- Steps: read each story's heading, description, action and live role through the tree; on `Summary` read the links; on
  `SentenceForm` look for a button.
- Expected: an empty state renders a heading (`h3` by default), a description and an optional real button or link (`15`:313);
  the error variant is CMP-027's panel with `live="polite"` (`15`:310; `EmptyState.stories.tsx`:83); the sentence form carries the
  host's reason in the description with **no** button when the sole CTA is gated (`15`:312); an error-severity ErrorState is
  `role="alert"` and a warning `role="status"`, `live` overriding (`polite`, or `off` with no live role), the region mounted with
  its host and the text inserted when the failure begins (`15`:325); the error summary is a `banner` with a title and one link
  per field in document order, and its heading takes focus after a failed submit (`15`:323, :329); the message is the
  component's own text, never a raw server body (`15`:325). Transient errors are announced via `role="alert"` (S02.7).
- Oracle: `15`:310–329 > the tree and live roles. 2nd: axe for `ErrorVariant` and `Summary`.
- Blocked on: none.

**E05-Q01-C33 Callout, InlineSpinnerText and ProgressBar: live roles and the 5 s slow path** (`e2e`, `a11y`; 3.4 · S02;
`15`:336–337, :341 Callout; `15`:444–445, :449 InlineSpinnerText; `15`:280–281 ProgressBar; `Callout.stories.tsx`:76
`ConnectionDisconnected`, :98 `LivePolite`, :108 `Band`, :141 `Dismissible`, :169 `ProtectionPendingSolidEdge`;
`InlineSpinnerText.stories.tsx`:40 `SlowPath`, :51 `SlowPathWithCancel`, :71 `SubmitNeverCancels`; `ProgressBar.stories.tsx`:51
`Meter`, :34 `Unlabelled`)

- Pre: dark · compact; the slow-path stories (their `beforeEach` shortens the 5 s wait; the real wait is ≤ 5 s, section 4).
- Steps: read each callout's role, its glyph and words, its dismiss button's name; on `ProtectionPendingSolidEdge` try to
  dismiss; on the spinner-text stories wait for the slow text and read the status region once; on `Meter` and `Unlabelled` read
  the role, `aria-valuetext` and the visible value.
- Expected: info, success and connection-reconnecting are `role="status"`, warning, danger and connection-disconnected
  `role="alert"`, `live="off"` renders no live role, each state entry announced once (`15`:337); the dismiss button is "Dismiss
  {title}" (`15`:336); the unprotected banner draws the solid 2 px edge and is not dismissible while the stop is missing
  (`15`:341); the spinner text is one `role="status"` wrapping icon and text, mounted empty and filled when the wait begins, the
  slow text replacing the label at 5 s with no elapsed counter (`15`:445); Cancel shows only on the slow path and only for
  `load`, `export` and `replay`, never for a submit (`15`:449; `InlineSpinnerText.stories.tsx`:68); the progress bar is
  `role="progressbar"` or `role="meter"` with `aria-valuetext` equal to the visible text and is never a live region (`15`:281).
- Oracle: the `15` lines > the tree and live roles (UI only). 2nd: axe for `ConnectionDisconnected` and `Meter`.
- Blocked on: none.

**E05-Q01-C34 Dialog focus contract [R]** (`e2e`, `a11y`; 3.4 · S03; mirrors S03.2 "Dialog focus contract"; `15`:506–507,
:511; `Dialog.stories.tsx`:99 `Default` ("focus in, Tab trapped, Escape closes, focus returns, the page inert"), :182
`AlertDialog`, :254 `Reflow`, :280 `ExemptRegion`, :385 `StackedDiscard`, :406 `NoLayoutShift`; `HO-S03`:10, :22; `SR-S03` D1–D10
as C60's)

- Pre: dark · compact and light · comfortable; a 1280 × 800 window for the `Reflow` leg; a scrolling page for `NoLayoutShift`.
- Steps: open `Default` by keyboard; read focus, `aria-modal`, the title and description wiring; `Tab` and `Shift+Tab` past both
  ends; try to click and to read the page behind; press `Esc`; read focus. Open `AlertDialog`, `StackedDiscard` (edit, `Esc`,
  `Esc`), `ExemptRegion`, `NoLayoutShift`; open `Reflow` at 200 % browser zoom.
- Expected: focus moves to the dialog, `Tab` is trapped inside and cycles, `Esc` closes it and focus returns to the invoking
  element (S03.2); the background is inert to pointer and screen reader — native `inert` where the engine has it, with
  `data-cv-inert-exempt` regions spared (`HO-S03`:10; `Dialog.stories.tsx`:277); `role="dialog"` `aria-modal="true"` named by
  its title and described (`15`:507); `AlertDialog` is `role="alertdialog"` with focus on the least destructive choice (`SR-S03`
  D5's expectation); the discard prompt stacks over the dirty form and `Esc` on it returns to the form with focus where it was
  (`SR-S03` D9's expectation); the scroll lock gives the scrollbar's width back so nothing under the scrim moves
  (`Dialog.stories.tsx`:404; `HO-S03`:22); at 200 % on 1280 × 800 the card fills the viewport, the header and footer stay, the body
  scrolls (`15`:506; `Dialog.stories.tsx`:251–252); `onOpenChange` carries the reason `escape | scrim | close` (`15`:511; a read of
  the story's log).
- Oracle: `15`:506–511 > `Dialog.test.tsx` "Gherkin 'Dialog focus contract' …", "native inert …", "locks page scroll …"
  (`HO-S03`:10, :22) > the focus target, the tree and the layout. 2nd: axe for `Default` and `AlertDialog`.
- Blocked on: none.

**E05-Q01-C35 Hold-to-confirm gate [R] [F]** (`e2e`, `a11y`; 3.4 · S03; mirrors S03.3 "Hold-to-confirm gate"; `15`:516 (800 ms
default within a 300–2,000 ms setting; `confirmDelayMs` 400), :516–517 (idle, holding with its ring and percentage, armed; the
keyboard alternative: a hold, or two `Enter` / `Space` presses at least 250 ms apart within 5 s); `ConfirmDialog.stories.tsx`:297
`Hold`, :321 `HoldReleasedEarly` ("a release at 400 of 800 ms fires nothing and the ring resets"), :342 `Holding`, :358 `Armed`,
:378 `HoldKeyboard`, :103 `Guard`; `HO-S03`:11, :18, :88–92; `05`:33 rule 4; section 4)

- Pre: dark · compact; `HoldReleasedEarly`, `Hold`, `HoldKeyboard`, `Guard`; the pointer for the hold legs, the keyboard alone
  for the others.
- Steps: on `HoldReleasedEarly` press Confirm and release after about 400 ms; read the ring and the outcome. On `Hold` press and
  hold past 800 ms; read. On `HoldKeyboard`, with no pointer, hold `Enter` for the duration; then, after a reset, press `Enter`,
  wait between 250 ms and 5 s, press `Enter` again; try `Space` as a hold. On `Guard` click Confirm within the first 400 ms of the
  dialog opening, then once after.
- Expected: a release before the duration fires nothing and the progress indicator resets (S03.3); a full hold fires once, at the
  duration, never before (`HO-S03`:18 H1); the ring is a `progressbar` with its percentage text (`ConfirmDialog.stories.tsx`:294–296);
  the keyboard-only path achieves the gate without a pointer — held `Enter` with its repeats fires key-hold, or a second
  non-repeat `Enter` 250 ms to 5 s after the first fires double-press, the first arming and renaming the button "Press again to
  {effect}" (`15`:518, :522 `armedLabel`); `Space` never holds (`ConfirmDialog.stories.tsx`:375); inside the 400 ms guard a click or
  a single `Enter` does nothing (`ConfirmDialog.stories.tsx`:100). The `Hold`, `Holding` and `Armed` cells are the at-rest looks;
  the sweep is C57's under reduced motion. Focus starts on Cancel (`15`:522).
- Oracle: `15`:516–522 > `ConfirmDialogHold.test.tsx` "Gherkin 'Hold-to-confirm gate': a release at 400 ms fires nothing and
  resets the progress", H1, H2, H3 (`HO-S03`:11, :118–120) > the outcome text and the ring (UI only). 2nd: axe for `Hold`.
- Blocked on: none.

**E05-Q01-C36 Typed confirm [F] [R]** (`e2e`, `a11y`; 3.4 · S03; mirrors S03.4 "Typed confirm"; `15`:517 (typed: Confirm
natively disabled until the summary has loaded and the field matches exactly: form validity, not a gate), :522
(`typedInstruction` default "Type {token} to confirm"); `ConfirmDialog.stories.tsx`:125 `Typed`, :147 `TypedMatch`; `HO-S03`:12,
:109 A3)

- Pre: dark · compact; `Typed` requiring FLATTEN.
- Steps: read Confirm's state and the instruction; type `flatten`, `FLATTEN `, `FLAT`, then `FLATTEN`; press `Enter` inside the
  field each time; read Confirm.
- Expected: with any other text Confirm stays disabled with the stated instruction "Type FLATTEN to confirm" (`15`:522; S03.4);
  case, spaces and a short match stay disabled; `Enter` in the field never confirms (`HO-S03`:12); the exact token enables Confirm
  (`TypedMatch`); the disabled state is native availability, not T2 (`15`:517).
- Oracle: `15`:516–522 > `ConfirmDialog.test.tsx` "Gherkin 'Typed confirm' …" (A3) > the control state. 2nd: axe for `Typed`.
- Blocked on: none.

**E05-Q01-C37 A toast does not steal focus and is announced at the right politeness [R]** (`e2e`, `a11y`; 3.4 · S03; mirrors
S03.6 "Toast does not steal focus"; `15`:529–530, :534 (`ToastRegion` owns timing; default 5,000 ms, `null` until dismissed);
`Toast.stories.tsx`:235 `Region`, :265 `RegionUntilDismissed`, :103 `Focused`, :112 `ActionGated`, :130 `Undo`, :63 `Default`;
`HO-S03`:14, :57; section 4)

- Pre: dark · compact; `Region` with the cursor in its typing field.
- Steps: while typing, raise a timed info toast and a danger toast; read focus, the polite and assertive regions and each
  toast's own roles; hover and focus the stack and watch the timers; press `Esc` on a focused toast; raise `Undo` and read its
  window; on `ActionGated` read the two actions and press one.
- Expected: focus never moves from the field (S03.6); the sentence lands once in the polite region, or the assertive one for
  `danger` or an error, `politeness` overriding (`15`:530; `HO-S03`:14); a toast is a `group` named by its title and never its own
  live region (`Toast.stories.tsx`:62–65); hover or focus pauses every timer in the stack and a toast with an action or `danger`
  never times out (`Toast.stories.tsx`:233–234); `Esc` on a focused toast moves focus on; a timed toast leaves after 5 s by default
  and never under `durationMs={null}`; gated actions keep their names, stay focusable, point at one reason line and a press says
  the reason politely once (`15`:529; `HO-S03`:57).
- Oracle: `15`:529–534 > `Toast.test.tsx` "Toast does not steal focus …" and "speaks assertively only for danger or an error …"
  (`HO-S03`:14) > the focus target and the live regions. 2nd: axe for `Region`.
- Blocked on: none.

**E05-Q01-C38 Menu and Drawer states [F]** (`e2e`, `a11y`; 3.4 · S03; `15`:484–485, :489 Menu; `15`:541–542, :546 Drawer;
`Menu.stories.tsx`:229 `DisabledWithReason`, :289 `Danger`, :316 `Busy`, :356 `Scrolling` (60 rows outgrow 1920 × 1080 at the
compact 24 px row), :399 `NestedSubmenu`, :534 `HostOpened`; `Drawer.stories.tsx`:138 `Loading`, :154 `Narrow`, :192 `LongText`
(80 paragraphs), :215 `FallbackReturn`; `HO-S03`:56)

- Pre: dark · compact; a 1920 × 1080 window, then 1280 × 800.
- Steps: on `DisabledWithReason` arrow onto the gated item and press `Enter` twice; read `Danger`'s hint and `Busy`'s item; open
  `Scrolling` and arrow to the 60th row; on `NestedSubmenu` open the submenu, press `←`, reopen, press `Esc`; open `Drawer`
  `Loading`, `Narrow`, `LongText` (`Tab` into the body and scroll by keyboard); on `FallbackReturn` remove the opener and close.
- Expected: a gated item is reached by the arrows, keeps its full label in the tertiary colour with the `lock` and its reason as
  the second line, present at mount, re-shown once per press, never activated (`15`:484; `HO-S03`:56); a danger item carries the
  "destructive action" hint (`15`:485); a busy item shows the spinner and never acts; the menu caps its height to the room below
  the trigger and scrolls, the focused item kept in view, `Tab` closing it (`Menu.stories.tsx`:352–353); `←` or `Esc` closes the
  submenu alone (`Menu.stories.tsx`:397); a loading drawer shows skeleton rows with `aria-busy` on the body (`15`:541, :546); a
  narrow drawer is full width; a long body with no control is a `Tab` stop (`Drawer.stories.tsx`:191); with the opener gone focus
  returns to the host's fallback (`15`:546; `Drawer.stories.tsx`:213). Nothing clips at 1280 × 800.
- Oracle: the `15` lines > `Menu.test.tsx` "disabled, busy and gated items are reached by the arrows and never activated"
  (`HO-S03`:56) and `Drawer.test.tsx` > the tree. 2nd: axe for `DisabledWithReason` and `LongText`.
- Blocked on: none.

**E05-Q01-C39 Error boundary fallback [F] [R]** (`e2e`, `a11y`; 3.4 · S04; mirrors S04.7 "Error boundary fallback"; `15`:1003–1007;
`GlobalErrorBoundaryFallback.stories.tsx`:28 `PanelLevel`, :30 `RouteLevel`, :32 `AppLevel`, :34 `RepeatedCrash`, :47 `Details`)

- Pre: dark · compact and high-contrast · compact; the four scope stories and `Details`.
- Steps: read each fallback's heading, description, actions and the reference id; read the announcement role per scope; open
  "Technical detail"; read `RepeatedCrash`'s actions.
- Expected: the fallback renders a description, a retry (or reload) action and a selectable reference id, and the crash does
  not blank the whole shell (S04.7): a panel's or a route's fallback keeps the rest of the page, the app scope alone takes the
  page (`15`:1007); one assertive announcement per crash — a panel's or a route's through the shell's pre-rendered region, the app
  scope as its own `role="alert"` (`15`:1007); the stack sits behind a "Technical detail" disclosure
  (`GlobalErrorBoundaryFallback.stories.tsx`:45); three crashes in a row show the repeated-crash heading and offer the app reload
  in place of the panel's reload (`GlobalErrorBoundaryFallback.stories.tsx`:37–40). The words are the component's copy module's,
  read as presence and role (no deck); the reference id's format is not asserted.
- Oracle: `15`:1003–1007 > the stories' plays (white-box; the S04 Test plan's "error boundary catches and renders fallback") >
  the tree. 2nd: axe for `AppLevel`.
- Blocked on: none.

**E05-Q01-C40 Forbidden and not-found landings** (`e2e`, `a11y`; 3.4 · S04; `15`:985–989 ForbiddenState (T4 route landing,
never a T2 lock; `h1` "You don't have access to this" / "Your access changed", never "Access denied"; "Ref {instance}" only when
a 403 body was received); `15`:994–998 NotFoundState (`h1` "Page not found"; "There's nothing at {route}."; "Try:" as a list);
`ForbiddenState.stories.tsx`:21 `Default`, :33 `NoRef`, :36 `Withdrawn`; `NotFoundState.stories.tsx`:21 `Default`, :27 `Admin`,
:30 `Deleted`)

- Pre: dark · compact; light · comfortable.
- Steps: read each story's `h1`, sentence, actions and Ref line; compare `Default` and `Admin` of NotFoundState; read where focus
  lands on mount.
- Expected: ForbiddenState's `h1` is "You don't have access to this" (`Default`, `NoRef`) or "Your access changed" (`Withdrawn`),
  never "Access denied"; "Back to your workspace" and "Copy details" are present; the "Ref {instance}" line is selectable and
  present only in `Default` (a 403 body received), absent in `NoRef` and `Withdrawn` (`15`:989; `ForbiddenState.stories.tsx`:30–36);
  NotFoundState's `h1` is "Page not found" with "There's nothing at {route}." echoing the route as plain text and "Try:" as a list,
  the admin and unknown routes identical but for the echoed route (`15`:998; `NotFoundState.stories.tsx`:25–27), `Deleted` carrying
  its own sentence; `AccountVariant` carries the account form of the sentence (`ForbiddenState.stories.tsx`:39); focus moves to
  the `h1` on navigation (`15`:989, :998). The S04 Test plan's "403/404 states render their documented content" is the white-box
  pair.
- Oracle: `15`:985–998 (the strings are the catalogue's) > the tree. 2nd: axe for `Default` of each.
- Blocked on: none.

**E05-Q01-C41 Colour is never the only signal in the family (smoke)** (`a11y`; 3.4 · S02–S04; `15`:37 rule 3; `Toast`
`AllTones` ("each with its glyph and its kicker word, never colour alone", `Toast.stories.tsx`:73); `Callout` `AllTones`;
`ErrorState` `Warning` / `ErrorSeverityStory`; `ProgressBar` `AllTones`; `ConfirmDialog` `Hold` (the ring plus the percentage
text); `Menu` `Danger`; `EmptyState` `AllVariants`)

- Pre: as C06 (high-contrast, greyscale).
- Steps: read each story in greyscale and through the tree.
- Expected: every tone carries its glyph and its kicker word (toast) or its glyph and role (callout, error state); a danger
  item has its hint; progress and hold are read from their text, not their fill alone (`15`:280, :517); every empty-state variant
  is told by its glyph and words (`15`:317).
- Oracle: `15`:37 and the A11y lines > the tree. 2nd: axe.
- Blocked on: none.

### 3.5 The rest (CMP-022, 035, 036, 042, 050, 059, 062†, 063†, 069, 085, 228†; S02, S03, S04)

**E05-Q01-C42 The family's full matrix is rendered and snapshot-stable [R]** (`e2e`; 3.5 · S02–S04; mirrors `15`:41 rule 7 and
`HO-S03`:23; `AllMolecules.stories.tsx` the CommandPalette set)

- Pre: as C01.
- Steps: as C01, over this table; in `Molecules/All molecules matrix` read the six CommandPalette cells at their equal-global cell.

  | Component              | Stories read                                                                                                                                                                  | `15` list and as-built                                                                                                                                                                |
  | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
  | CMP-022 Kbd            | Combo, SingleKey, Range, PointerChord, InMenuRow, Remapped, Unbound, the contrast pair (`Kbd.stories.tsx`:19–81)                                                              | `15`:272; `15`:270, :274                                                                                                                                                              |
  | CMP-035 Countdown      | Default, UnderThreshold, Expired, HhMmSs, Words, Approx, InGrid, Live, Light, HighContrast (`Countdown.stories.tsx`:28–116; `Date` frozen for the cells, `vr/settings.ts`:43) | `15`:415; `15`:413, :417                                                                                                                                                              |
  | CMP-036 KeyValueRow    | Default, Emphasis, TextValue, Missing, Stale, Stacked, the contrast pair (`KeyValueRow.stories.tsx`:27–61)                                                                    | `15`:425 lists LiveFreshness; as built (`15`:427) "LiveFreshness waits for CMP-239"                                                                                                   |
  | CMP-042 Tabs           | Default, Hover, FocusVisible, Selected, Vertical, WithIcons, GatedTab, ManualActivation, Overflow, AllStates, the Gated contrast pair (`Tabs.stories.tsx`:69–184)             | `15`:498; `15`:496, :500                                                                                                                                                              |
  | CMP-050 Card           | Default, Flat, NoHeader, WithActions, NoPadding, RegionTile, InOption, LongTitle, AllStates (`Card.stories.tsx`:27–126)                                                       | `15`:595; `15`:593, :597                                                                                                                                                              |
  | CMP-059 CommandPalette | Default, Filtered, NoResults, WithConfirms, Gated, LongText (`CommandPalette.stories.tsx`:86–168)                                                                             | `15`:679 lists Default, Grouped, NoResults, EmptyQuery, RbacDisabled, Destructive; the build's names map as the story comments say (`CommandPalette.stories.tsx`:83, :98, :122, :138) |
  | CMP-062 ThemeSwitcher  | **none** at the base                                                                                                                                                          | `15`:709 lists Default, MatchSystem, Light, HighContrast — † (E05-S04 #267)                                                                                                           |
  | CMP-063 DensityToggle  | **none** at the base                                                                                                                                                          | `15`:719 lists Global, PanelOverride, ChartPanelDense, MenuForm — † (E05-S04 #267)                                                                                                    |
  | CMP-069 InfoPanel      | Default, Inline, InlineCollapsed, Loading, LoadError ("Error"), InlineLoading, the contrast pair (`InfoPanel.stories.tsx`:69–126)                                             | `15`:776; `15`:773, :778                                                                                                                                                              |
  | CMP-085 SkipLink       | Unfocused, Focused, FocusedThenEnter, Several, FocusedReducedMotion (`SkipLink.stories.tsx`:66–114)                                                                           | `15`:954; `15`:952, :956                                                                                                                                                              |
  | CMP-228 PreviewTile    | **none** at the base                                                                                                                                                          | `15`:2926 lists Footprint, Heatmap, ThemeDark, ThemeLight, Sample, Empty, Error, Ladder, … — † (E05-S04 #267)                                                                         |

- Expected: as C01 over 67 stories × 6 = 402 cells; the three unbuilt components have no story and no cell, and the plan asserts
  nothing about them until #267 lands (C48–C51).
- Oracle: `15` > the VR cells. 2nd: axe for every story.
- Blocked on: CMP-062, CMP-063, CMP-228 — E05-S04 (#267). The eight built components run today.

**E05-Q01-C43 The family's keyboard-only walk [R]** (`e2e`, `a11y`; 3.5 · S02–S04; `Atoms.mdx`:252 Kbd, :258 KeyValueRow, :282
SkipLink, :390 Countdown; `Molecules.mdx`:97 Card, :135 CommandPalette, :190 Tabs, :364 InfoPanel; `HO-S03`:70, :77, :78)

- Pre: as C02 (no pointer; dark · compact then light · comfortable; 100 % then 200 % zoom; 1280 × 800; motion `system` then `on`).
- Steps: walk the tables on `Tabs` `Default`, `ManualActivation`, `Vertical` and `Overflow`; `CommandPalette` `Default` and
  `Filtered`; `InfoPanel` `Default` and `Inline`; `Card` `WithActions` and `RegionTile`; `SkipLink` `Focused` and `Several`; count
  the stops on `Kbd`, `Countdown` and `KeyValueRow`.
- Expected: one `Tab` stop on the selected tab; automatic activation moves and selects on the arrows, `Home` and `End`, wrapping;
  manual activation moves focus only and `Enter` or `Space` selects; horizontal answers `←` / `→` only and vertical `↑` / `↓` only;
  a switch never moves focus off the tab (`15`:496; `HO-S03`:70); the overflow strip scrolls in one row and hides no tab
  (`Tabs.stories.tsx`:162); in the palette focus never leaves the input, `↓` / `↑` wrap and skip group headers, `Home` / `End` and
  `PageUp` / `PageDown` by ten move the active row, `Esc` returns to the opener (`15`:677; `HO-S03`:77); the info chip's trigger
  opens a non-modal drawer with focus on its heading, or the inline disclosure, `Esc` inside closing it with focus back
  (`15`:773; `InfoPanel.stories.tsx`:90; `HO-S03`:78); a card is never a stop as a whole and its actions are (`15`:593); the skip
  link is the first stop and `Several` adds one per mounted region (`SkipLink.stories.tsx`:93); Kbd, Countdown and KeyValueRow add
  no stop. Rings unclipped at 200 % and 1280 × 800.
- Oracle: the mdx tables and `15` A11y lines > the hand-off's tests (`HO-S03`:70, :77, :78) > the focus target at each step.
  2nd: none (a read).
- Blocked on: none.

**E05-Q01-C44 Tabs: roving tabindex, panels and the gated tab [R]** (`e2e`, `a11y`; 3.5 · S03; mirrors the S03 Test plan's
"tabs roving tabindex"; `15`:496, :500; `Tabs.stories.tsx`:69 `Default`, :128 `GatedTab`, :147 `ManualActivation`; `HO-S03`:16,
:55)

- Pre: dark · compact; `Default`, `GatedTab`, `ManualActivation`.
- Steps: read the tablist's name and each tab's `aria-selected`, `aria-controls` and `tabindex`; arrow across; read the panel; on
  `GatedTab` arrow onto the gated tab, press `Enter`, read.
- Expected: a named tablist, each tab wired to its panel by `aria-controls` / `aria-labelledby`, one tab stop on the selected
  tab, only the selected panel mounted, a panel with nothing focusable taking `tabindex="0"` (`15`:496, :500); the gated tab keeps
  `role="tab"` with `aria-disabled`, its reason as its description and one shared reason line, a press refusing with the reason
  (`HO-S03`:55); a switch never moves focus off the tab.
- Oracle: `15`:496–500 > `Tabs.test.tsx` "renders a named tablist …", "automatic: …", "manual: …", "a gated tab: …"
  (`HO-S03`:16, :55) > the tree. 2nd: axe for `GatedTab`.
- Blocked on: none.

**E05-Q01-C45 CommandPalette: the gated row, the destructive row and the result count** (`e2e`, `a11y`; 3.5 · S03; `15`:676,
:677, :681; `CommandPalette.stories.tsx`:86 `Default`, :101 `Filtered`, :115 `NoResults`, :125 `WithConfirms`, :139 `Gated`;
`HO-S03`:19, :61, :77)

- Pre: dark · compact; motion `system`.
- Steps: open `Default` and read the groups; type on `Filtered` and read the live region once settled; on `NoResults` read the
  sentence; on `WithConfirms` arrow onto a destructive row and press `Enter`; on `Gated` arrow onto the gated row, press `Enter`
  twice, click it; press `Ctrl+Enter`.
- Expected: the host's empty-query groups show with `role="group"` and labels (`15`:677); results are ranked under their groups
  with empty groups dropped and one polite result count per settled query (`15`:677; `CommandPalette.stories.tsx`:98); no results
  shows the host's sentence, shown and said, with no listbox (`CommandPalette.stories.tsx`:112); a destructive row is tagged
  "confirms" and `Enter` asks the host's confirm and never runs (`15`:676; `CommandPalette.stories.tsx`:122); a gated row is
  reachable and `aria-disabled`, `Enter` or a click re-shows its reason once per press and never runs (`15`:677; `HO-S03`:61);
  `Ctrl+Enter` runs the group action and closes, the footer showing it (`15`:681). The palette sits in a CMP-043 Dialog at 640 px
  (`15`:681) — the composition leg is C53.
- Oracle: `15`:676–681 > `CommandPalette.test.tsx` "a gated row is reachable and aria-disabled; …", "keyboard: ↓ / ↑ wrap …"
  (`HO-S03`:61, :77) > the tree and live region. 2nd: axe for `Gated` (`HO-S03`:19 names the explicit axe test).
- Blocked on: none.

**E05-Q01-C46 Kbd, Countdown, KeyValueRow, Card and InfoPanel states [F]** (`e2e`, `a11y`; 3.5 · S02, S03; `15`:270, :274 Kbd;
`15`:413, :417 Countdown; `15`:423, :427 KeyValueRow; `15`:593 Card; `15`:773, :778 InfoPanel; `Kbd.stories.tsx`:27 `SingleKey`,
:69 `Remapped`, :81 `Unbound`; `Countdown.stories.tsx`:37 `UnderThreshold`, :40 `Expired`, :116 `Live`; `KeyValueRow.stories.tsx`
:41 `Missing`, :49 `Stale`; `Card.stories.tsx`:80 `RegionTile`, :95 `InOption`; `InfoPanel.stories.tsx`:116 `Loading`, :126
`LoadError`)

- Pre: dark · compact; the `Live` countdown waits ≤ 20 s (section 4).
- Steps: read `SingleKey`'s `<kbd>` nesting and hidden expansion; read `Remapped`'s word and `Unbound`'s render; read
  `UnderThreshold` and `Expired`; on `Live` listen at the 10 s and 0 s thresholds; read `Missing`'s value and its reading; read
  `RegionTile`'s landmark and `InOption`'s title; on `LoadError` read the static text, the error and Retry.
- Expected: one `<kbd>` per key inside an outer `<kbd>`, the caps `aria-hidden` and the outer's visually hidden expansion taking
  its words from the keymap's names (`15`:270, :274); "remapped" beside the user's own binding; an unbound command renders nothing
  (`Kbd.stories.tsx`:66, :78); the countdown's visible digits are `aria-hidden` with `aria-live="off"`, a discrete polite
  announcement only at the thresholds (10 s and 0 s once each on `Live`), and a grid countdown announces nothing (`15`:413); under
  the threshold the number alone carries it, no colour step (`Countdown.stories.tsx`:34); a missing value "—" is read as the state
  word (default "no value"), never "dash" (`15`:423, :427); a card with `region` is a landmark named by its heading and is never
  clickable as a whole, and inside a listbox option its title is plain text (`15`:593; `Card.stories.tsx`:77, :92); the info panel's
  load error keeps the static text and replaces the values with a polite CMP-027 and Retry (`InfoPanel.stories.tsx`:123).
- Oracle: the `15` lines > the tree and live regions. 2nd: axe for `RegionTile` and `LoadError`.
- Blocked on: none.

**E05-Q01-C47 Skip link [R]** (`e2e`, `a11y`; 3.5 · S04; mirrors S04.6 "Skip link"; `15`:950–952, :956; `SkipLink.tsx`:10–14
`SKIP_LINK_COPY`; `SkipLink.stories.tsx`:66 `Focused`, :79 `FocusedThenEnter`, :95 `Several`, :114 `FocusedReducedMotion`)

- Pre: dark · compact and high-contrast · comfortable; motion `system`, then `on`; the pointer untouched.
- Steps: from the document start press `Tab`; read the link's visibility, text and `href`; press `Enter`; read focus and the
  target's `tabindex`; press `Tab` again; read the target's `tabindex`; on `Several` `Tab` through the links; on
  `FocusedReducedMotion` repeat the first `Tab`.
- Expected: the skip link is visually hidden until focused (its box ≤ 1 px wide before, `SkipLink.stories.tsx`:61), then visible
  at the top-left as the first focusable element (S04.6; `15`:952); its text is "Skip to main content" (`SKIP_LINK_COPY.main`,
  `SkipLink.tsx`:11; the other two strings are "Skip to order ticket" and "Skip to chart"); activating it moves focus to the main
  landmark, which takes `tabindex="-1"` and shows the ring, the next `Tab` continues from it and the attribute is removed
  (`15`:952; `SkipLink.stories.tsx`:79–91); `Several` offers main content first, then one link per mounted region, each shown only
  while focused (`SkipLink.stories.tsx`:93); under reduced motion the pill appears as a cut (`SkipLink.stories.tsx`:113).
- Oracle: `15`:950–956 and `SKIP_LINK_COPY` > the `FocusedThenEnter` play (white-box) > the focus target. 2nd: axe for
  `Focused` and `FocusedReducedMotion`.
- Blocked on: none.

**E05-Q01-C48 Theme switch is immediate and complete — blocked on CMP-062** (`e2e`; 3.5 · S04; mirrors S04.1 "Theme switch is
immediate and complete"; `15`:702–710; E05-S04 Performance notes ("inherits E05-T02's one-frame budget"); the stand-in:
`ThemeRuntime.stories.tsx`:173 `Default` ("switching theme and density leaves the mount count unchanged"), :195 `TextScaleReflow`;
`16`:166–167; `store`:9–10)

- Pre: dark · compact; the toolbar's `theme` global as the stand-in for the unbuilt switcher.
- Steps (stand-in, runs today): on `ThemeRuntime` `Default` read the mount count, switch the runtime to `high-contrast`, read
  the root's `data-theme`, a buy and a sell token's resolved colour and the mount count; switch density; switch back.
- Steps (the scenario, waits): once CMP-062 ships, in its `Default` story select high-contrast and read the same.
- Expected (stand-in): the root `data-theme` becomes `high-contrast`, the buy and sell tokens resolve to their `.hc` variants
  (`16`:166), and no component remounts (the mount count unchanged, `ThemeRuntime.stories.tsx`:172); the swap is a CSS
  custom-property change, within one frame (E05-T02's budget, cited, never measured here; C65). Expected (the scenario): the same
  through CMP-062's control, with the polite announcement "Theme changed to High Contrast" once per committed change and nothing
  spoken on the initial load (`15`:706; J16). The `appearance.theme_changed` analytics callback (S04 Observability) is a † row.
- Oracle: `16`:166–167 > the `ThemeRuntime` play (white-box, E05-T02's no-remount assertion) > the root attribute and computed
  colours. 2nd: none (a read).
- Blocked on: E05-S04 (#267), CMP-062 ThemeSwitcher (OQ-7). The stand-in runs today and is recorded as such, never as the
  scenario's pass.

**E05-Q01-C49 Match-system is opt-in — blocked on CMP-062** (`e2e`; 3.5 · S04; mirrors S04.2 "Match-system is opt-in";
`15`:705 (a separate CMP-004 Toggle "match system" beside the three values, off by default; choosing a value turns it off: J13,
RULED); E05-T02 Scope ("Optional 'match system' mode for theme, off by default"); `store`:26 `DARK_QUERY`)

- Pre: a fresh profile (the Storybook origin's storage cleared, section 5); the OS colour scheme set to light.
- Steps (stand-in, runs today): load any story with no stored preference and read the root's `data-theme`; flip the OS scheme.
- Steps (the scenario, waits): once CMP-062 ships, read the "match system" toggle on a fresh profile, flip the OS scheme, choose
  a value, read the toggle.
- Expected (stand-in): the root stays on the explicit default `dark` and does not follow the OS scheme while no in-app choice
  says so (E05-T02 Scope; `16`:166). Expected (the scenario): "match system" is off on a fresh profile, the explicit user choice
  governs, and choosing a value turns the toggle off (`15`:705); a match-system flip speaks nothing (`15`:706). J15 (who may
  change the appearance; PROPOSED, `15`:706) is asserted only once ruled and built (OQ-7).
- Oracle: `15`:705–706 and the E05-T02 Scope > the root attribute. 2nd: none (a read).
- Blocked on: E05-S04 (#267), CMP-062 (OQ-7).

**E05-Q01-C50 Preview before commit — blocked on CMP-228** (`e2e`; 3.5 · S04; mirrors S04.3 "Preview before commit";
`15`:2920–2924 (`role="img"` named in words; never the only disclosure; five states, never a spinner); E05-S04 Performance notes
(re-render ≤ 16.6 ms; no GL context in v0))

- Pre: waits for CMP-228's stories (`15`:2926 lists Footprint, Heatmap, ThemeDark, ThemeLight, Sample, Empty, Error, Ladder and
  the ladder states).
- Steps: once built, in the theme-kind story select a candidate CVD-safe palette in the preview; read the tile and the root.
- Expected: the tile updates to show a chart cell, a ladder row and a positions row in that palette without applying it globally
  — the root's `data-theme` and the page outside the tile unchanged (S04.3; the S04 Test plan's "preview palette override does
  not leak to the document root"); the tile is `role="img"` named by the configuration in words and the settings stay readable
  beside it (`15`:2924); no spinner while recomputing (`15`:2924); the re-render budget is cited, never measured here.
- Oracle: `15`:2920–2924 > the root attribute and the tile's name. 2nd: none (a read).
- Blocked on: E05-S04 (#267), CMP-228 PreviewTile (OQ-7).

**E05-Q01-C51 Contrast warning on a failing combination — blocked on CMP-228 [F]** (`e2e`, `a11y`; 3.5 · S04; mirrors S04.4
"Contrast warning on a failing combination"; `15`:2925 (empty and error text in the caption style); `05`:131 rule 7 and §5
(4.5 : 1 body text))

- Pre: waits for CMP-228 and the palette controls that feed it.
- Steps: once built, preview a candidate custom palette whose text pair falls below 4.5 : 1.
- Expected: a warning is shown stating that the combination fails contrast (S04.4), carried in text and glyph, never colour
  alone (`15`:37 rule 3); the global theme is unchanged (C50). The warning's words are the owner's: presence and role are
  asserted, not words.
- Oracle: S04.4 and `15`:2925 > the tree. 2nd: axe for the story once it exists.
- Blocked on: E05-S04 (#267), CMP-228 (OQ-7).

**E05-Q01-C52 Colour is never the only signal in the family (smoke)** (`a11y`; 3.5 · S02–S04; `15`:37 rule 3; `Tabs` `GatedTab`
(the `lock` and the reason, not the dimmed tab alone); `Countdown` `UnderThreshold` ("no colour step, no glyph yet": the number
carries it); `KeyValueRow` `Missing` and `Stale`; `CommandPalette` `Gated` and `WithConfirms` (the "confirms" tag); `Kbd`
`Remapped` (the word))

- Pre: as C06 (high-contrast, greyscale).
- Steps: read each story in greyscale and through the tree.
- Expected: every state is told by text or glyph: the gated tab's lock and reason, the destructive row's tag, the remapped
  word, the missing value's state word, the stale slot's word; the under-threshold countdown is the number itself.
- Oracle: `15`:37 and the A11y lines > the tree. 2nd: axe.
- Blocked on: none.

### 3.6 The six composition scenarios (#261 Scope)

Each composition is the ticket's sentence run on the surface the base offers (ruled as BQ-16). A composition with no story
records "blocked on" its owner and the charter probes it (section 3.9); nothing is guessed. E05-Q03 (#263) adds "one story per
fixed composition defect" from what these cases find.

**E05-Q01-C53 Combobox inside Dialog: the focus trap against the listbox portal [R]** (`e2e`, `a11y`; composition 1; `15`:571
("the listbox portals into the topmost layer, so inside a Dialog `Esc` closes the list first"), :677, :681 (CMP-059 is a combobox
inside the APG Dialog (Modal); `Molecules.mdx`:135); `15`:223 (a popover inside a Dialog portals into the dialog's layer);
`CommandPalette.stories.tsx`:86 `Default`, :139 `Gated`; `Dialog.stories.tsx`:300 `EscTopmost` (Tooltip + Popover inside a Dialog);
`HO-S03`:72 ("Esc closes the topmost layer only: Tooltip, then Popover, then Dialog"))

- Pre: dark · compact at 100 % · 1920 × 1080, then high-contrast · comfortable at 200 % · 1280 × 800; motion `system`, then `on`.
- Steps: open `CommandPalette` `Default`; type to open the list; `Tab` and `Shift+Tab` around the dialog's ends; press `Esc` once,
  read the list and the dialog; press `Esc` again; read focus. Open `Dialog` `EscTopmost`; show the tooltip and the popover
  inside; press `Esc` three times, reading after each.
- Expected: the listbox renders inside the dialog's layer (inside the trap, outside the inert page): `Tab` never reaches the page
  behind and never lands in a portal outside the dialog; the first `Esc` closes the list and keeps the query, the second closes
  the dialog and returns focus to the opener (`15`:571, :681; `CommandPalette.stories.tsx`:83); in `EscTopmost` each `Esc` closes
  only the topmost layer — the tooltip, then the popover, then the dialog (`Dialog.stories.tsx`:299; `HO-S03`:72); the active option
  stays visible when the list opens near the dialog's edge; at 200 % on 1280 × 800 the dialog fills the viewport and the list
  still fits inside it with no clipped row. A stand-alone **CMP-048 Combobox composed in a CMP-043 Dialog has no story at the
  base**: the Combobox half of the scenario is read through CMP-059 (built on the same pattern) and is a † row; the charter's C-2
  probes it on its stand-ins, `CommandPalette` `Default` / `Gated` and `Dialog` `EscTopmost`; no ad-hoc composition is mounted (BQ-15, ruled: no throwaway story), so the composition itself waits.
- Oracle: `15`:571, :681, :223 > `Dialog.test.tsx` "Esc closes the topmost layer only …" and `CommandPalette.test.tsx`
  (`HO-S03`:72, :77) > the focus target and the layer order. 2nd: axe for `CommandPalette` `Default`.
- Blocked on: the CMP-048-in-CMP-043 story (none; owner E05-Q03 #263 for a composition story, a † row per BQ-16, ruled; OQ-5). The
  CMP-059 and `EscTopmost` legs run today.

**E05-Q01-C54 Toast while a Dialog is open [R]** (`e2e`, `a11y`; composition 2; `15`:530 (a toast never auto-dismisses content
the user has not perceived), :534 (`ToastRegion` owns timing); `Toast.stories.tsx`:270 `RegionUnderModal` ("while a dialog is
open the stack is inert and every timer in it is paused"); `15`:507 the inert page)

- Pre: dark · compact; motion `system`, then `on`.
- Steps: raise a timed info toast, then open the dialog; read the region's `inert` and `data-paused` attributes and the toast's
  remaining time; try to `Tab` to the toast; press `Esc` on the dialog; read the region again and watch the toast time out.
- Expected: with the dialog open the toast stack is inert — not reachable by `Tab`, not announced — and every timer in it is
  paused (`data-paused` set, `Toast.stories.tsx`:275–277), so no toast times out behind a modal; the dialog's own announcement is
  the only one; closing the dialog un-pauses the stack and the toast resumes its remaining time and leaves on schedule; a danger
  toast raised behind a modal is not lost (it is persistent, `15`:528). Under reduced motion both entrances are cuts.
- Oracle: `15`:528–534 > the `RegionUnderModal` play (white-box) > the attributes and the live regions. 2nd: axe for the story.
- Blocked on: none.

**E05-Q01-C55 Menu inside a scrollable Drawer — blocked on a story** (`e2e`, `a11y`; composition 3; `15`:484–485 (the menu
caps its height to the room below its trigger and scrolls; `Tab` closes it), :541–542; `Menu.stories.tsx`:356 `Scrolling`
(60 rows outgrow 1920 × 1080 at the compact 24 px row), :567 `EscTopmost` (a menu inside a Dialog); `Drawer.stories.tsx`:192
`LongText` (80 paragraphs; the body a `Tab` stop); `15`:223 the shared overlay layer stack)

- Pre: dark · compact at 1920 × 1080, then 1280 × 800.
- Steps (stand-ins, run today): on `Drawer` `LongText` `Tab` into the body and scroll it by keyboard to the end and back; on
  `Menu` `Scrolling` open the menu, arrow to the 60th row and back, press `Tab`; on `Menu` `EscTopmost` open the menu inside
  the dialog, press `Esc`, then `Esc`.
- Steps (the composition, waits): once a story mounts a Menu trigger inside a scrolling Drawer body, scroll the body so the
  trigger sits near the bottom, open the menu, arrow through it, scroll the body with the wheel, press `Esc`.
- Expected (stand-ins): the drawer body scrolls by keyboard with the header and footer fixed; the menu scrolls within the room
  below its trigger keeping the focused row in view and `Tab` closes it (`15`:485); inside a dialog `Esc` closes the menu first,
  then the dialog (`15`:223). Expected (the composition): the menu is a layer above the drawer, flips above the trigger when the
  room below is short, stays attached to its trigger (or closes) when the body scrolls, never opens inside the body's clip, and
  `Esc` closes the menu alone, the drawer staying open with focus on the trigger. **No story composes a Menu in a Drawer at the
  base**; the charter's C-2 probes the stand-ins and the plan records "blocked on" for the composition itself.
- Oracle: `15`:484–485, :541–542, :223 > the tree and the layer geometry (UI only). 2nd: axe for `Scrolling` and `LongText`.
- Blocked on: the Menu-in-Drawer story (none; owner E05-Q03 #263; a † row and a C-2 probe per BQ-16, ruled; OQ-5).

**E05-Q01-C56 Table reflow at 200 % zoom, compact density, high-contrast theme [R]** (`e2e`, `a11y`; composition 4; `15`:580,
:586; `Table.stories.tsx`:325 `Reflow` (compact; root font size 200 % on the 1280 × 800 frame and at 640 px); `AllMolecules.stories.tsx`
:290 the stacked cell; the `high-contrast` theme, `16`:166 (`.hc` body-text tokens, ≥ 7 : 1))

- Pre: the toolbar at `high-contrast` · `compact`; a 1280 × 800 window; motion `system`, then `on`.
- Steps: open `Table` `Reflow`; set the browser zoom to 200 %; read the layout, every header label and value, the focus ring on
  a sort button, and the contrast of the header and the cell text against their fills; narrow to 640 px; return to 100 %. Read
  the `AllMolecules` `HighContrastCompact` cell's stacked table (`molecules-all-molecules-matrix--high-contrast-compact--high-contrast--compact.png`).
- Expected: the rows reflow to the stacked layout with no horizontal clipping and no column's data lost (S03.5) **and** in
  high-contrast the stacked blocks keep their header labels and values at the `.hc` contrast, the ring visible, the odd / even
  row fills still distinguishable or the row boundary drawn; nothing overlaps at 640 px; back at 100 % a table. The committed
  cell is the at-rest oracle for the same layout at a 200 % text scale in that theme and density.
- Oracle: `15`:580–586 and `16`:166 > the `Reflow` play > the layout read > the `AllMolecules` cell. 2nd: axe for `Reflow` at
  `high-contrast` (the `storybook` job runs the toolbar's default cell; the high-contrast axe run is a manual leg here).
- Blocked on: none.

**E05-Q01-C57 Hold-to-confirm under reduced motion: progress stays perceivable [R]** (`e2e`, `a11y`; composition 5; `15`:517
(holding with its ring and percentage); `ConfirmDialog.stories.tsx`:404 `HoldReducedMotion` ("no sweep, the percentage text
alone"; `globals: { motion: "on" }`; the arc's `display` is `none`), :378 `HoldKeyboard`; `05`:33 rule 4, :205–209 §7; `16`:167;
`D03` (motion is never the sole carrier of information))

- Pre: dark · compact and light · comfortable; motion `on` (the in-app override), then `system` with the OS preference set to
  reduce.
- Steps: open `HoldReducedMotion`; read the root's `data-motion` and the arc; press and hold Confirm for the duration, reading the
  percentage text as it rises; release early once and read; with no pointer, on `HoldKeyboard` under the same motion setting, hold
  `Enter` and read.
- Expected: `data-motion="reduce"`; the sweep is not drawn (`ConfirmDialog.stories.tsx`:411–412) and the percentage text alone
  carries the progress, rising through the hold and resetting on an early release, so the gate is perceivable without animation
  (the ticket's sentence; `05`:209 rule 4); a full hold fires once at the duration; the keyboard path fires the same under
  reduced motion; the `progressbar` role and value are present whatever the motion setting (`ConfirmDialog.stories.tsx`:294).
  Both the override and the OS preference produce the same frames (`16`:167).
- Oracle: `15`:517 and `05`:209 > the `HoldReducedMotion` play (white-box) > the text and the arc's computed style. 2nd: axe for
  the story under `motion: "on"`.
- Blocked on: none.

**E05-Q01-C58 Tooltip on a disabled-with-reason control: the echo, never the only copy [R]** (`e2e`, `a11y`; composition 6;
`15`:54 (a tooltip may echo the reason on hover and focus but is never the only copy), :63 (the IconButton `locked` badge), :207
(`echo` mode: `aria-hidden`, the trigger keeps its own description), :885 (`form="tooltip"`: a lock badge on the icon, the
description visually hidden and echoed by CMP-016); `Tooltip.stories.tsx`:126 `EchoReason` ("the reason node is always rendered
and is the description; the tooltip only repeats it"), :98 `EchoName`; `IconButton.stories.tsx`:85 `DisabledWithReason`; A-12;
`SR-S02` T4–T5 as E05-Q02's)

- Pre: dark · compact and high-contrast · compact; 100 % then 200 % zoom; motion `system`.
- Steps: on `EchoReason` `Tab` to the gated icon trigger; read its name, `aria-disabled`, its description and the tooltip node's
  `aria-hidden`; hover it; press `Esc`; press `Enter`; on `IconButton` `DisabledWithReason` read the badge and the description
  with no tooltip present.
- Expected: the reason is the control's accessible description from an always-rendered node, present before any hover or
  focus; the tooltip appears on focus and on hover and repeats the reason, is `aria-hidden` in `echo` mode so the reason is never
  read twice (`15`:207; `Tooltip.stories.tsx`:122–124); `Esc` hides the echo with focus kept; `Enter` fires nothing; the `lock`
  badge sits in the icon's corner and the box does not grow (`15`:63); at 200 % the tooltip flips rather than clips. On the bare
  atom (`IconButton` `DisabledWithReason`) the reason is the hidden description only — **no visible echo at the base** (A-12):
  the visible echo is the composition's, through the host's CMP-016 (or RbacGate `form="tooltip"`, whose story is absent, C24).
- Oracle: `15`:54, :63, :207, :885 > the `EchoReason` play (white-box) > the tree and the tooltip node. 2nd: axe for `EchoReason`.
- Blocked on: the RbacGate `FormTooltip` leg (E05-S04 #267; OQ-4) and the atom-level visible echo (A-12; OQ-6). The CMP-016 echo
  runs today.

### 3.7 The keyboard-only full pass and the delegated screen-reader pass

**E05-Q01-C59 The keyboard-only full pass over the five families [R]** (`e2e`, `a11y`; #261 Accessibility notes ("Keyboard-only
execution of at least one full pass (no mouse) is mandatory; anything unreachable is a defect regardless of axe result");
`05`:30 rule 1, :33 rule 4; `15`:38 rule 4; `HO-S01`:30 and `HO-S03`:138 ("the … Overview tables are the script"); ruled as
BQ-10 (a))

- Pre: one session, the pointer unplugged or untouched throughout; dark · compact at 100 % · 1920 × 1080 for the whole pass, then
  the spot re-checks of C02, C09, C16, C28 and C43 at 200 % and 1280 × 800; motion `system`.
- Steps: run C02, C09, C16, C28 and C43 in order in the one session, then C35's keyboard path, C21, C34, C47, C53 and C57's
  keyboard leg, recording every control reached and every control not reached, and every stop with no visible ring.
- Expected: every interactive control of the 59 built components is reached and operated by keyboard alone, with a visible
  ring at every stop; the hold gate, the combobox, the table's row navigation and the skip link are included (the four E05-Q02
  names; the pass here is the ticket's own); nothing needs a pointer. **Any control unreachable or inoperable is a defect whatever
  axe reports**, recorded in the execution record with its WCAG criterion (2.1.1, 2.1.2, 2.4.7) and `03` §11.3 severity.
- Oracle: the `Atoms.mdx` and `Molecules.mdx` tables > the focus target at every step (UI only). 2nd: none (a read); the axe
  result is not the oracle here.
- Blocked on: none.

**E05-Q01-C60 NVDA + Chromium on CMP-043 Dialog: `SR-S03` D1–D10 — blocked on a human tester** (`a11y`; the orchestrator's
2026-10-29 line (#261 comment 6491190592: "the manual screen-reader pass on CMP-043 Dialog, CMP-048 Combobox and CMP-049 Table …
is run here, once … NVDA + Chromium at minimum, keyboard-only, against the Storybook cells named in `E05-S03-qa-handoff.md`; the
hand-off's blank SR log is filled from this run (one line per component: reader, browser, date, pass / findings)"); `SR-S03`:7–15
the protocol and tester row, :17–30 rows D1–D10; `05`:221 §8.1 row 3 (Windows 11, Chromium, NVDA 2024.x); `HO-S03`:130–132)

- Pre: a human tester on Windows 11 with NVDA 2024.x and Chromium, keyboard only; Storybook at dark · compact, default verbosity
  (`SR-S03`:9–10); the tester fills `SR-S03`:15 (tester, date, reader and browser versions, OS) first.
- Steps: run rows D1 to D10 as `SR-S03`:21–30 states them, on the stories they name (`Default`, `AlertDialog`, `Scrolling`,
  `Busy`, `EscTopmost`, `StackedDiscard`, `ExemptRegion`), writing Pass / Fail / N/A and a note into each row's Result and Notes
  columns; then one line for the component (reader, browser, date, pass / findings) in the hand-off's log, and the Sign-off
  rows (`SR-S03`:65–68).
- Expected: the expectations of `SR-S03`:21–30, verbatim (named by title then description, focus on the first field; focus
  stays inside; the page behind not read; `Esc` closes and the opener is read again; the alert dialog announced with focus on the
  least destructive choice; the scrolling body read in order; busy and read-only read; each `Esc` closing one layer; the discard
  prompt an alert dialog; the exempt region still read).
- Oracle: `SR-S03`'s Expected column (which carries `15`:506–507 and T2) > what the reader speaks, written down by the tester.
  2nd: the axe result for the same stories (not a substitute: `packages/ui/README.md` "Snapshot review never replaces the manual
  screen-reader pass").
- Blocked on: **a human tester** (an agent cannot run NVDA; `05`:221 pins NVDA 2024.x on Windows 11). The likely tester is the
  owner, who is asked through the #2701 digest and never assumed (BQ-11, ruled). Until run, the row in the execution record is "blocked on a human tester", never a result.

**E05-Q01-C61 NVDA + Chromium on CMP-048 Combobox: `SR-S03` C1–C10 — blocked on a human tester** (`a11y`; as C60; `SR-S03`:32–45
rows C1–C10 on `Sync`, `AsyncLoading`, `NoResults`, `SearchFailed`, `DisabledWithReason`)

- Pre: as C60.
- Steps: rows C1 to C10 as `SR-S03`:36–45 state them; the component's line in the log.
- Expected: `SR-S03`:36–45 verbatim ("Symbol", combobox, collapsed; one polite count once typing settles, never per keystroke;
  each active option read with its position and `↑` on the first returning to the text; the chosen label read and the list
  collapsed; the first `Esc` collapsing and the second leaving the field; `Tab` away choosing nothing; "Searching…" shown but not
  announced; the host's sentences read once and not as options; the T2 field's name, lock, read-only and reason once).
- Oracle: `SR-S03`'s Expected column (carrying `15`:566–571) > what the reader speaks. 2nd: axe for the same stories.
- Blocked on: a human tester (as C60).

**E05-Q01-C62 NVDA + Chromium on CMP-049 Table: `SR-S03` B1–B11 — blocked on a human tester** (`a11y`; as C60; `SR-S03`:47–61
rows B1–B11 on `Default`, `Sortable`, `Loading`, `Empty`, `Error`, `Reflow`, `Grid`, `Selectable`, `RowActions`)

- Pre: as C60; B8 sets the browser zoom to 200 % (`SR-S03`:58).
- Steps: rows B1 to B11 as `SR-S03`:51–61 state them; the component's line in the log; the Sign-off rows once all three
  components are done.
- Expected: `SR-S03`:51–61 verbatim ("Open positions", table, with its counts and each cell read with its header; the full
  number with its sign; the sort state read and the result said once; only the sort buttons taking focus; the loading words once
  and the skeleton rows not read; the empty state read inside the table; the error said once with Retry named; the stacked rows
  still a table with each value and its header, nothing missing or twice; one `Tab` stop in the grid with each move read; the
  selected row and the count said once; the row menu named "Actions for {first cell}" and `Esc` returning to the cell).
- Oracle: `SR-S03`'s Expected column (carrying `15`:580–587) > what the reader speaks. 2nd: axe for the same stories.
- Blocked on: a human tester (as C60).

### 3.8 The abuse legs and the jank observation

The two abuse legs are the ticket's two sentences (#261 Security notes) run as black-box legs that assert only the answer and
name the controls' executors (ruled as BQ-17; `E13`'s rider 2): the plan carries no step beyond the ticket's sentence, adds no
control, and its findings go to E05-X02 (#272), which executes the controls' verification (`HO-S03`:80–128 is the gate matrix it
lifts). No `security-review` label: nothing here is a control of this plan's own.

**E05-Q01-C63 A single synthetic click cannot satisfy the hold-to-confirm gate [F]** (`security`, `e2e`; #261 Security notes
("attempt to satisfy the hold-to-confirm gate with a single synthetic click event"); `15`:517–518 (a hold, or two presses; a
click, a pointer pair and two clicks are rejected); `ConfirmDialog.stories.tsx`:297 `Hold`; `HO-S03`:20, :121 H4 ("a synthetic
click(), a pointerdown/pointerup pair and two clicks never confirm nor arm"); the delegated Security sign-off on #266 (2026-10-29))

- Pre: dark · compact; `ConfirmDialog` `Hold` open past its 400 ms guard.
- Steps: dispatch one synthetic `click` on Confirm from the browser console; read the outcome, the ring and the button's label.
- Expected: nothing fires: the outcome stays empty, the ring stays at 0 %, the button is not armed and its label unchanged;
  the gate still needs the full hold or the two discrete presses (`15`:518). The step is the ticket's sentence and no more; the
  pointer-pair and two-click variants are the white-box H4's and E05-X02's.
- Oracle: `15`:517–518 > `ConfirmDialogHold.test.tsx` H4 (`HO-S03`:121, white-box) > the outcome text. 2nd: none (nothing
  fires). A confirm fired by the synthetic click is **P0** (section 5; `03` §11.3 "incorrect order execution").
- Blocked on: none. Findings, if any, to E05-X02 (#272).

**E05-Q01-C64 A click dispatched on a RbacGate-wrapped control fires no handler [F]** (`security`, `e2e`; #261 Security notes
("attempt to trigger an RbacGate-wrapped action by dispatching a click directly on the disabled control"); `15`:886 (T2: the
wrapped control keeps its role, takes `aria-disabled`, never acts); `RbacGate.stories.tsx`:56 `DeniedPermission`; the S04 Test
plan's "RbacGate blocks handler invocation"; `HO-S03`:49 (a gated control "never acts"))

- Pre: dark · compact; `RbacGate` `DeniedPermission`.
- Steps: dispatch one synthetic `click` on the wrapped control from the browser console; read the story's handler log, the
  control's state and the live region.
- Expected: the handler is not invoked; the control stays `aria-disabled` with its reason; the reason is re-spoken once,
  politely, as for a real press (T2). The step is the ticket's sentence and no more.
- Oracle: `15`:886 and T2 > `RbacGate.test.tsx` (white-box) > the handler log. 2nd: none (nothing fires). RbacGate is an
  affordance, not an authorisation control (the S04 DoD's note; E05-X02's component check): a fired handler is a defect of the
  component, and the server-side RBAC (C-12.4) is never asserted here.
- Blocked on: none. Findings, if any, to E05-X02 (#272).

**E05-Q01-C65 Subjective jank during theme and density switching (recorded, escalated against E05-T02's budget)** (`perf`;
#261 Performance notes ("Record subjective jank observations during theme/density switching on the 500-row table story; any
observed stall is escalated against E05-T02's measured budget"); E05-T02 Performance notes ("≤ 16.6 ms style recalculation on
the 500-row benchmark; zero component remounts; zero WebGL context loss"); S04 Performance notes ("inherits E05-T02's one-frame
budget"); `15`:585–586 (v0 renders a bound of 200 rows); `Table.stories.tsx`:245 `Scrolling`, :381 `Perf200Rows` (`perf`-tagged,
skipped unless `CV_STORYBOOK_PERF=1`, `vitest.config.mjs`:8–9); `ThemeRuntime.stories.tsx`:227 `StyleRecalcBenchmark` (the
median of 30 warmed switches over 500 rows within 16.6 ms; `perf`-tagged); `AllMolecules` `DarkCompact`; ruled as BQ-19)

- Pre: a quiet machine; dark · compact; `Table` `Scrolling`, then `Perf200Rows` with `CV_STORYBOOK_PERF=1` set for the Storybook
  run, then `AllMolecules` `DarkCompact`.
- Steps: on each story switch the toolbar theme dark → light → high-contrast → dark and the density compact → comfortable →
  compact, three times each, watching for a visible stall, a flash of unstyled content or a remount; record what was seen, the
  story, the machine and the Chromium version run (section 7).
- Expected: the switch is a CSS custom-property swap with no remount (C48's stand-in) and no perceptible stall; a stall seen is
  **recorded** as an observation with the story and the cell and **escalated against E05-T02's budget** — cited from E05-T02
  (#268, Done) and never re-measured here; `ThemeRuntime` `StyleRecalcBenchmark` is the measuring artefact and runs only on a
  quiet machine. **There is no 500-row table story**: the ticket's words are read against the merged bound of 200 rows
  (`15`:585), so the observation runs on `Scrolling` and `Perf200Rows` (OQ-1).
- Oracle: E05-T02's budget (cited) > the observation (subjective, recorded as such). 2nd: none.
- Blocked on: none for the observation; the 500-row story is OQ-1's.

### 3.9 The exploratory charter

Two session-based charters of 90 min each (#261 Scope "2 × 90 min"; `03` §11.2's 60–120 min time box with mission, areas,
oracles and a debrief; ruled as BQ-12). The charter text lives here; the session notes, when run, land as
`docs/qa/charters/E05-charter-1-theme-density-motion-zoom.md` and `docs/qa/charters/E05-charter-2-layers-and-composition.md`
in the execution pass, in the format of `docs/qa/charters/E09-charter-1-auth-state-machine.md` (ticket and format line, the
charter, oracles defined up front, areas covered with evidence, not probed, anomalies with a dismissal reason for their absence,
follow-ups) — with E09's **"Deviation (honest scope)"** line whenever a session is an agent driving the built Storybook through
Playwright rather than a human at a desk, stating what was not available (no screen reader, no human time box, no recording).
An agent-driven session counts as one of the two timeboxed sessions only with that honest-scope line and never stands in for the
human pass (BQ-12, ruled); a human session is "blocked on a human tester" until run, the owner being asked through the #2701
digest and never assumed (BQ-11). The orchestrator's 2026-10-29 line is part of this ticket's charter: the NVDA +
Chromium pass on CMP-043, CMP-048 and CMP-049 (C60–C62) is run once, here, filling `SR-S03`'s blank log.

**Charter C-1 — theme × density × motion × zoom × viewport over the five families.** Mission (the ticket's words): "explore theme
× density × motion × zoom combinations looking for clipping, unreadable text, lost focus and stuck overlays". Areas: every
family's `AllStates`, `LongText` / `LongLabel` / `LongValue` and contrast-pair stories, the five family walks' stops, the
`AllAtoms` and `AllMolecules` matrix pages, at every cell of section 2.1 that VR does not hold (motion `on` and `off`, 200 %
browser zoom, 1280 × 800, text scale 112 / 125 / 150 through the runtime); the toolbar switched **while** an overlay is open,
a tooltip shown, a hold in progress, a toast timing out. Oracles (what looks wrong): O1 any text clipped, overlapping or
unreadable at any cell; O2 any focus ring lost, hidden under a sticky header or drawn off-screen; O3 any overlay left open,
detached from its trigger or unreachable by `Esc` after a theme, density or zoom change; O4 any component that keeps a colour
or size across a theme or density swap (a raw value); O5 any animation still running under `data-motion="reduce"` or any
information carried by motion alone; O6 any remount during a switch (a field losing its typed value, a hold resetting). Debrief:
areas covered with the cell and story per probe, not probed, anomalies (each with its `03` §11.3 severity and the case it
belongs to), follow-ups for E05-Q03's composition stories.

**Charter C-2 — layer stacking and composition.** Mission: "layers inside Dialog and Drawer, toasts over modals, T2 inside
overlays, keyboard-only" (the ticket's composition point, section 3.6). Areas: `Dialog` `EscTopmost`, `StackedDiscard` and
`ExemptRegion`; `Menu` `EscTopmost` and `Scrolling`; `Drawer` `LongText`, `NonModal` and `FallbackReturn`; `CommandPalette` `Gated`
and `WithConfirms`; `Toast` `RegionUnderModal` and `ActionGated`; `ConfirmDialog` `ConfirmGated`, `HoldKeyboard` and
`CountingDown`; `Popover` `Modal` inside a dialog (`EscTopmost`); every T2 control inside an overlay (a gated menu item, a gated
palette row, a gated toast action, a gated Confirm), operated by keyboard only; the two missing compositions (C53's Combobox-in-
Dialog, C55's Menu-in-Drawer) probed on their stand-ins (BQ-16, ruled: a † row each, Menu-in-Drawer also a C-2 probe), never on an ad-hoc composition.
Oracles: O1 `Esc` ever closing more than the topmost layer, or nothing; O2 focus ever reaching the inert page or a portal outside
the trap; O3 a timer running behind a modal, or a toast lost; O4 a T2 control that acts, loses its reason, or speaks it more than
once per press; O5 a layer opening inside a scrolling body's clip, or detaching when the body scrolls; O6 focus returned to
`<body>` or lost when a trigger unmounts. Debrief as C-1; every anomaly on a composition becomes a candidate for E05-Q03's "one
story per fixed composition defect" (section 8).

## 4. Time control

The only clocks in this plan are the components' own; no case moves a clock, sleeps in automation, or waits more than 20 s of
real time in a manual step (C-13.7, `CONSTITUTION.md`:890; ruled as BQ-06). Automation of these cases is E05-Q03's and the
stories' own, where the plays use their story clocks (`ConfirmDialog.stories.tsx` `clock.t`, `Countdown.stories.tsx` `T0`) and
VR freezes `Date` at `2026-10-27T14:02:00Z` outside a play (`vr/settings.ts`:37–43). No `CV_TEST_CLOCK` and no server clock
exists here: there is no server.

| Need                               | The component's clock (source)                                                                                                                                        | How the manual case waits                                                                                                                    | Cases         |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| the hold duration and the guard    | `holdDurationMs` default 800 within a 300–2,000 ms setting; `confirmDelayMs` default 400 (`15`:516); H2 clamps (`HO-S03`:18)                                          | a real hold of about 1 s; an early release at about 400 ms read against the ring (`HoldReleasedEarly` sets 400 of 800); never at the instant | C35, C57, C63 |
| the double-press window            | two presses at least 250 ms apart within 5 s (`15`:518)                                                                                                               | a second press after about 1 s                                                                                                               | C35, C57      |
| an order confirm's auto-cancel     | `autoCancelMs` (`15`:516; `CountingDown` "Cancels in 0:20" frozen on the story clock, `ConfirmDialog.stories.tsx`:415)                                                | read at rest; not waited out (E05-X02's C1–C4 are white-box)                                                                                 | C27, C-2      |
| toast timing                       | `durationMs` default 5,000 ms, `null` until dismissed; timers paused on hover, focus and under a modal (`15`:534; `Toast.tsx`:277; `Toast.stories.tsx`:230–234, :270) | one 5 s wait; the pause read by attribute, not by timing                                                                                     | C37, C54      |
| the combobox and search-box settle | 500 ms after the last keystroke by default, 300 ms with CMP-160's tuning (`15`:567, :572; `Combobox.stories.tsx`:266)                                                 | type, then wait ≤ 1 s before reading the count                                                                                               | C21, C25, C45 |
| the tooltip delay                  | 300 ms on hover; at once on focus (`15`:206; `Tooltip.stories.tsx`:70)                                                                                                | hover, wait ≤ 1 s                                                                                                                            | C29, C58      |
| the skeleton sweep and stop        | one sweep per 1,200 ms, stopped at 5 s (`15`:196)                                                                                                                     | watch 6 s                                                                                                                                    | C31           |
| the slow path                      | 5 s, then the slow text (`15`:445); the stories shorten it with `beforeEach` (`InlineSpinnerText.stories.tsx`:39)                                                     | wait ≤ 5 s                                                                                                                                   | C33           |
| the masked value's re-mask         | `autoHideMs` default 10,000, clamped 3–30 s, announced about 2 s before (`15`:401, :403, :407; `Expiring` sets 3,000)                                                 | wait ≤ 5 s on `Expiring`; the default is read, not waited                                                                                    | C19           |
| the copy status reset              | 2 s (`15`:391)                                                                                                                                                        | wait 3 s                                                                                                                                     | C13           |
| the countdown thresholds           | discrete announcements at the thresholds (10 s and 0 s on `Live`; `15`:413; `Countdown.stories.tsx`:114)                                                              | listen through `Live`'s last 10 s (≤ 20 s)                                                                                                   | C46           |
| theme, density and motion switches | one frame (E05-T02's budget, cited; S04 Performance notes)                                                                                                            | not timed: observed (C65) or read by attribute (C48)                                                                                         | C48, C65      |

No assertion sits on an exact instant: a release "at 400 ms" is read as "before the duration, the ring reset", the pause as
`data-paused`, the re-mask as "masked again within the clamp".

## 5. Environment and reset protocol

There is **nothing to destroy** (ruled as BQ-06, BQ-13): the surface is a static Storybook with no backend, no database, no
fixture file and no network, so this section replaces `E13`'s destructive protocol with the environment and the reset between
cells.

- **The surface.** `pnpm --filter @candleviewer/ui storybook:build` writes `packages/ui/storybook-static/`
  (`packages/ui/package.json` scripts; `vr/settings.ts`:8–14); the plan runs against that build served on loopback as the VR
  harness serves it (`http://127.0.0.1:6007`, `vr/settings.ts`:22–24; the dev server `storybook` binds `127.0.0.1:6006`). Never a
  published or internet-reachable build (E05-X02's check; the E05 threat model's A4 residual, `_job-a11y.yml`:291–292).
- **No network.** The VR context proxies every request but the local Storybook's to a closed loopback port and fails a cell
  that asks, naming the URL (`vr/settings.ts`:66–68, :76). The manual run keeps the same rule: the browser offline or behind the
  same proxy; a request to any host is a finding. No fixture from `packages/fixtures` and no recorded Bybit capture is used
  (C-13.5): every story's inline data (the table's positions, the palette's commands, the toast's titles) is its own fixture.
- **No secrets, no real data.** No key, account, user name, order or production row appears in a story or in evidence;
  `MaskedValue`'s stories hold a made-up string (C19 asserts it never reaches the DOM while masked). A value found in a DOM
  scan while masked is P0.
- **Reset between cells.** The theme runtime persists its choice in `localStorage` under `cv.theme.v1` (`store`:22); a case that
  starts "fresh" clears the Storybook origin's storage first (C49). The toolbar globals are set per case from `preview`:44 (the
  initial globals `dark`, `compact`, `system`) and read back from the root attributes before the first step. A page left with an
  overlay open is reloaded, never carried into the next case.
- **The pointer rule.** A keyboard-only case (C02, C09, C16, C28, C43, C59; the keyboard legs of C35 and C57; C60–C62) is run with
  the pointer untouched for its whole duration; a pointer use is recorded as a deviation of that run, and the case is re-run.
- **Severities (`03` §11.3).** P0: a masked value in the DOM or spoken (C19); a hold confirmed by a synthetic click (C63); a
  RbacGate-wrapped handler fired (C64); a focus trap that lets focus reach the inert page (C34, C53). P1: a control unreachable
  by keyboard (C59); a composition that loses a toast or a timer behind a modal (C54); clipping that hides a value at a supported
  cell (C22, C56). Anything else is P2 or P3 by `03` §11.3's definitions, each with a WCAG criterion or a `15` line.
- **Defects.** Rows of the execution record with the severity, the case id, the cell, the story and the cite; **filing them as
  issues waits for the orchestrator's go** (the plan-first filing freeze of 2026-10-19; ruled as BQ-20). An accepted-risk note
  on a failing scenario is the owner's, never this plan's (#261 "Sign-off blocks Done").

## 6. The surface catalogue

All surfaces are stories of the built Storybook at the base (ruled as BQ-13); none is added by this plan (BQ-15). `index.json`
of the build is the matrix's only source (`vr/settings.ts`:12–14): 726 stories, of which 683 belong to the v0 set and its two
matrix pages and 43 to components outside it (section 1).

| Handle    | Surface                                                                                                                                                                                                             | Used by                                     |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| SF-BUILD  | `packages/ui/storybook-static/` from `storybook:build`, served on loopback (section 5)                                                                                                                              | every case                                  |
| SF-VR     | `packages/ui/vr/baselines/*.png`, 4,356 cells; compared by `pnpm --filter @candleviewer/ui vr` (`vr/vr.spec.ts`; tolerance `vr/settings.ts`:35)                                                                     | C01, C08, C15, C27, C42; every at-rest read |
| SF-GLOB   | the toolbar globals `theme`, `density`, `motion` (`preview`:44–60), read back as `data-theme`, `data-density`, `data-motion` on the root (`16`:167)                                                                 | every case                                  |
| SF-SCALE  | the runtime's `data-text-scale` 100 / 112 / 125 / 150 (`store`:11; `ThemeRuntime` `TextScaleReflow`, `ThemeRuntime.stories.tsx`:195)                                                                                | C05, C48, C-1                               |
| SF-ZOOM   | the browser's zoom at 100 % and 200 %; the story's own root font size where it sets one (`Table` `Reflow`, `Dialog` `Reflow`)                                                                                       | C02, C09, C16, C22, C28, C34, C43, C56, C-1 |
| SF-VIEW   | a 1920 × 1080 window and a 1280 × 800 window; the 1280 × 800 and 640 px frames `Table` `Reflow` and `Dialog` `Reflow` draw (`Table.stories.tsx`:329, :349; `Dialog.stories.tsx`:251)                                | the walks, C22, C34, C56, C-1               |
| SF-MATRIX | `Atoms/All atoms matrix` (6 stories) and `Molecules/All molecules matrix` (30: the at-rest page and the Dialog, ConfirmDialog, Drawer and CommandPalette sets), each pinned to a theme × density pair (`HO-S03`:23) | C01, C08, C15, C27, C42, C56                |
| SF-REFLOW | `Table` `Reflow`: 44 em of column minimums (704 px at 16 px, 1,408 px at 200 %; `Table.stories.tsx`:281), compact, the four-step play (:335–354); `AllMolecules`' stacked cell at a 200 % text scale (:290)         | C22, C56                                    |
| SF-LONG   | `Drawer` `LongText` (80 paragraphs, `Drawer.stories.tsx`:193), `Menu` `Scrolling` (60 rows, `Menu.stories.tsx`:352–353), `Table` `Scrolling` (:245), every `LongText` / `LongLabel` / `LongValue` story             | C38, C55, C65, C-1                          |
| SF-PERF   | the `perf`-tagged stories, run only with `CV_STORYBOOK_PERF=1` on a quiet machine (`vitest.config.mjs`:8–9): `Table` `Perf200Rows`, `ThemeRuntime` `StyleRecalcBenchmark`                                           | C65                                         |
| SF-SR     | `SR-S03`'s rows D1–D10, C1–C10, B1–B11 and their stories; the tester row and sign-off (`SR-S03`:13–15, :63–68)                                                                                                      | C60–C62                                     |
| SF-KEYS   | the keyboard tables `Atoms.mdx`:11–479 and `Molecules.mdx`:23–622, one per component (`HO-S03`:27–43 names each molecule's)                                                                                         | the walks, C59                              |
| SF-AXE    | the `storybook` job's per-story axe result (`_job-a11y.yml`:188–296; the `storybook-a11y-report` artifact)                                                                                                          | every case's secondary oracle               |

**Surface gaps** (each a section 10 row; nothing is filed from here): SG-1 a CMP-048 Combobox composed in a CMP-043 Dialog
(C53); SG-2 a Menu in a scrolling Drawer (C55); SG-3 the CMP-062, CMP-063 and CMP-228 stories (C48–C51); SG-4 RbacGate
`FormTooltip`, `FormNotice`, `Denied(EnvMismatch)` (C24, C58); SG-5 a 500-row table story (C65); SG-6 the shell's below-1280 × 800
advisory state (section 2); SG-7 a Chromium pinned to the Electron version (section 7).

## 7. Entry and exit criteria, and the regression subset

**Entry (`03` §16), per group — what runs today against the built Storybook at the base, and what waits (ruled as BQ-11).**

| Group                                          | Cases                                                                  | At the base `b8575c6f1`                                                                                                                                                                                             |
| ---------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| the 21 S01–S03 scenarios                       | C01–C05, C10, C11, C17–C22, C29–C32, C34–C37                           | **runs today**: 59 components built, the build and the VR run green at `6dc942aff`                                                                                                                                  |
| the family matrix, walk and smoke cases        | C06–C09, C12–C16, C23, C25–C28, C33, C38, C41–C46, C52                 | **runs today**                                                                                                                                                                                                      |
| the three S04 scenarios whose components exist | C24 (RbacGate), C47 (SkipLink), C39 (GlobalErrorBoundaryFallback), C40 | **runs today**, except C24's `FormTooltip` / `FormNotice` / `Denied(EnvMismatch)` legs                                                                                                                              |
| the four S04 scenarios on CMP-062 / 063 / 228  | C48, C49, C50, C51                                                     | **waits** for E05-S04 (#267, open; slices A–D merged, the trio not); the C48 / C49 stand-ins run today and are recorded as stand-ins                                                                                |
| the six compositions                           | C53, C54, C56, C57, C58 run; C55 blocked                               | **runs today** on BQ-16's surfaces; C53's CMP-048 half and C55 **blocked on a story**; C58's `FormTooltip` leg blocked on #267                                                                                      |
| the keyboard-only full pass                    | C59                                                                    | **runs today**                                                                                                                                                                                                      |
| the delegated screen-reader pass               | C60, C61, C62                                                          | **blocked on a human tester** (NVDA 2024.x on Windows 11, `05`:221)                                                                                                                                                 |
| the abuse legs                                 | C63, C64                                                               | **runs today**                                                                                                                                                                                                      |
| the jank observation                           | C65                                                                    | **runs today** on a quiet machine with `CV_STORYBOOK_PERF=1`                                                                                                                                                        |
| the charters                                   | C-1, C-2                                                               | an agent-driven session runs today with the honest-scope line and counts as one of the two sessions only with it, never standing in for the human pass (BQ-12, ruled); a human session is blocked on a human tester |

Environment at entry: the build from `storybook:build` served on loopback (section 5); the Chromium that runs it is Playwright
`^1.64.1`'s (`packages/ui/package.json`), while the desktop pins `electron ^45.0.0` (`apps/desktop/package.json`): the ticket's
"Chromium at the Electron version" has **no pin on `main`**, so every execution record states the Chromium version actually run
and claims no match (OQ-3). This PR closes #261 on the document (ruled as BQ-22, Reading A, as #404 and #422 did); the
execution pass of the runnable set is owed on #261 as comments inside Sprint 06 and is **not waived**; the human and S04 legs stay blocked and named, and E05-Q03 (#263) assembles the epic sign-off. The DoD's "executed; results recorded per scenario" is read as this section's ledger plus that execution pass (BQ-22, ruled; the same reading as E13-Q01's, 6532529903 BQ-21).

**Exit (the ticket's "Sign-off blocks Done"; `02`:77 QA sign-off).** Every case has a recorded result (pass, fail, blocked with
its owner, or "stand-in" where the plan says so), the build sha, the cell and the Chromium version; no P0 or P1 is open (section
5); every **[R]** case ran and every **[F]** case ran; the six compositions each have a result or a named blocker (#261
"Composition defects are hunted deliberately"); the two charter sessions have notes in `docs/qa/charters/` with areas covered,
found and not covered (#261 "Exploratory charter produces evidence"); `SR-S03`'s log is filled or its rows are "blocked on a human
tester"; section 9 has no gap. **Sign-off comments** (ruled as BQ-20) go on #264 (S01), #265 (S02) and #266 (S03) — closed and
Done on their QA records, where `02`:77's per-scenario sign-off was recorded as owed to E05-Q01 — with pass / fail per scenario,
and on #267 for the S04 rows that ran; a failing scenario without an accepted-risk note blocks the owning story's Done (#261).
This plan's sign-off is necessary, not sufficient: E05-Q03 (#263) assembles the epic's.

**Regression subset.** The **[R]** cases (37 of 65: C01, C02, C04, C08–C11, C15–C22, C24, C27–C32, C34–C37, C39, C42–C44, C47,
C53, C54, C56–C59) run every sprint after exit and on any change to `packages/ui/src/components/`, `packages/ui/src/theme/`,
`packages/ui/tokens/`, `packages/ui/.storybook/`, `packages/ui/vr/` or `docs/plan/15-component-catalogue.md`'s E05 entries: the
at-rest cases through the VR job, the rest in the sprint's QA pass until E05-Q03 automates them. A flaky member is quarantined
within 24 h with an owner (C-9.3), never retried silently. Every family has an **[F]** case: 3.1 C03, C04; 3.2 C13, C14; 3.3 C18,
C19, C20, C23, C24, C25; 3.4 C32, C35, C36, C38, C39; 3.5 C46, C51; 3.8 C63, C64.

## 8. What this plan references and does not contain

- **E05-Q02 (#262), the a11y audit** (BQ-10, ruled; the delegation is not extended): the full axe-core sweep over every story at
  every theme and density and the `pa11y-ci` complementary sweep; the §8.1 screen-reader coverage matrix beyond the three
  components delegated here. **Q02's, not this plan's:** `SR-S02` (Tooltip, Popover, MaskedValue: T1–T6, P1–P6, M1–M9, "not
  run") and S04's DoD screen-reader pass on ThemeSwitcher, PreviewTile and SkipLink; also the 125 % text-scale pass, the
  reduced-motion information-loss pass and findings with WCAG references (its Scope). This plan keeps exactly three a11y legs:
  the keyboard-only pass (C59), the three `SR-S03` cases (C60–C62, results written back into that log, one line per component)
  and one colour-redundancy smoke leg per family (section 3.7).
- **E05-Q03 (#263), the regression pack and the epic sign-off:** the curated VR / interaction / a11y subset per PR and the
  nightly sweep; "one story per fixed composition defect" found here; the VR diff triage workflow; the epic-level regression run
  and the epic QA sign-off comment with pass / fail per story group; the "how to not break the design system" note. **For
  E05-Q03 (#263)** — the table of regression candidates handed over (BQ-20, ruled):

  | Candidate                                                           | From        | Why                                                                                                                                                              |
  | ------------------------------------------------------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
  | Combobox-in-Dialog: a story composing CMP-048 in CMP-043            | C53, SG-1   | the ticket's composition 1 has no story; the Esc-order rule (`15`:571) needs a direct surface                                                                    |
  | Menu-in-Drawer: a story mounting a Menu trigger in a scrolling body | C55, SG-2   | composition 3 has no story                                                                                                                                       |
  | Toast under a modal (`RegionUnderModal`)                            | C54         | already a play; keep it in the per-PR subset                                                                                                                     |
  | Table `Reflow` at `high-contrast` · `compact`                       | C56         | the composition's cell is not the toolbar default the `storybook` job runs                                                                                       |
  | `HoldReducedMotion`, `HoldKeyboard`                                 | C57, C35    | the gate's two perceivable paths                                                                                                                                 |
  | `EchoReason` on a gated icon                                        | C58         | the echo-never-the-only-copy rule (`15`:54)                                                                                                                      |
  | D4: `Checkbox` `Indeterminate` shows no visible word "Mixed"        | C06, pass 2 | `15`:95 pairs `aria-checked="mixed"` with the word; the glyph carries the state, so a row, not filed (coordinator ruling 2026-10-31; pass 2 on #261, 6537431192) |
  | D5: the stacked `Table` at `high-contrast` · `compact`              | C56, pass 2 | the row fills step about 1.07 : 1 with no drawn boundary; a row, not filed (coordinator ruling 2026-10-31; pass 2 on #261, 6537431192)                           |
  | every case that fails in the execution pass                         | the record  | one story per fixed defect (#263 Scope)                                                                                                                          |

- **E05-X02 (#272), the security review:** the dependency review, the CSP hash of the pre-paint script, Storybook hosting, the
  gitleaks path rule, and the component-level checks — MaskedValue, the ConfirmDialog gates ("cannot be satisfied by a single
  synthetic event"), RbacGate "documented as an affordance, not an authorisation control", no `dangerouslySetInnerHTML` (its
  Scope). C19, C63 and C64 assert only the black-box answer and name #272 as the controls' executor; `HO-S03`:80–128 is the gate
  matrix it lifts.
- **E05-S04 (#267):** CMP-062, CMP-063, CMP-228 and the RbacGate `tooltip` / `notice` forms; its own Test plan (keyboard operation
  of ThemeSwitcher and DensityToggle; the preview override not leaking; the no-remount story with a 500-row table) is white-box.
- **E05-D04 (#259), E05-D05 (#260):** the a11y sign-off and the design QA of the bands against the boards; not claimed here
  (`HO-S01`:31, `HO-S03`:139).
- **E05-T02 (#268, Done):** the runtime and its budget (≤ 16.6 ms style recalculation on the 500-row benchmark; zero remounts;
  zero WebGL context loss), cited by C48 and C65 and never re-measured. **#3174 (open):** the E05-D03 motion recipes as CSS
  pairs, blocked by E05-D03 (#162, open); the reduce path the plan tests is E05-T02's `data-motion` (C07, C31, C57).

## 9. Traceability

Scenarios are numbered in ticket order. Every scenario of E05-S01 to E05-S04 (28) maps to a case: **28 of 28**, four of them
(S04.1–S04.4) blocked on E05-S04 (#267) and still mapped, their stand-ins marked in the case. Every story has at least one **[F]**
case: S01 C03, C04, C18; S02 C13, C14, C19, C32; S03 C20, C23, C35, C36, C38; S04 C24, C39, C51. The six compositions, the two
abuse steps, the keyboard-only pass, the jank observation and the 2026-10-29 charter line each map to a case.

| Source                   | Scenario to cases                                                                                                                                                                                                                                                                   |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| E05-S01 (#264)           | 1 Full matrix C01 · 2 Keyboard contract C02 · 3 Disabled states explain themselves C03 · 4 Numeric input is tabular C17 · 5 Invalid numeric entry C18 · 6 Loading button cannot double-submit C04 · 7 No hardcoded values C05                                                       |
| E05-S02 (#265)           | 1 Tabular numerics C10 · 2 Tooltip keyboard and dismissal C29 · 3 Popover focus management C30 · 4 Masked value never leaks C19 · 5 Estimated confidence not colour-only C11 · 6 Skeleton respects reduced motion C31 · 7 Empty and error states C32                                |
| E05-S03 (#266)           | 1 Form field wires label, help and error C20 · 2 Dialog focus contract C34 · 3 Hold-to-confirm gate C35 · 4 Typed confirm C36 · 5 Table reflow at 200 % zoom C22 · 6 Toast does not steal focus C37 · 7 Combobox keyboard C21                                                       |
| E05-S04 (#267)           | 1 Theme switch C48 (blocked) · 2 Match-system C49 (blocked) · 3 Preview before commit C50 (blocked) · 4 Contrast warning C51 (blocked) · 5 Disabled-with-reason C24 · 6 Skip link C47 · 7 Error boundary fallback C39                                                               |
| #261 Scope, compositions | 1 Combobox inside Dialog C53 · 2 Toast while a Dialog is open C54 · 3 Menu inside a scrollable Drawer C55 (blocked on a story) · 4 Table reflow at 200 %, compact, high-contrast C56 · 5 Hold-to-confirm under reduced motion C57 · 6 Tooltip on a disabled-with-reason control C58 |
| #261 Security notes      | the synthetic click on the hold gate C63 · the dispatched click on a RbacGate-wrapped control C64                                                                                                                                                                                   |
| #261 Accessibility notes | the keyboard-only full pass C59 (with the family walks C02, C09, C16, C28, C43)                                                                                                                                                                                                     |
| #261 Performance notes   | the jank observation C65                                                                                                                                                                                                                                                            |
| #261 Scope, charter      | C-1, C-2 (section 3.9)                                                                                                                                                                                                                                                              |
| #261 comment 6491190592  | the NVDA + Chromium pass on CMP-043 C60 · CMP-048 C61 · CMP-049 C62, filling `SR-S03`                                                                                                                                                                                               |
| #261 Acceptance criteria | "Plan covers every story AC" this table · "Composition defects are hunted deliberately" C53–C58 · "Exploratory charter produces evidence" section 3.9 · "Sign-off blocks Done" section 7                                                                                            |

**Components to cases (grouped by band, the ticket's "grouped by band").** Every one of the 62 ids is named by its family's
at-rest case and at least one more: atoms CMP-001 C01–C06; 002 C01–C03, C58; 003 C01, C02, C06; 004 C01–C03, C06; 005 C01–C03,
C06; 006 C01–C03; 007 C15, C16, C26; 008 C15–C18; 009 C15, C16, C25, C26; 010 C01–C03; 011 C08, C09, C12; 012 C08, C12; 013 C08,
C14; 014 C01, C04, C06, C07; 015 C27, C31; 016 C27–C29, C58; 017 C27, C28, C30, C53; 018 C08, C14; 019 C01; 020 C08, C10; 021
C08, C09, C14; 022 C42, C43, C46, C52; 023 C27, C31, C33, C41; 024 C08, C12; 025 C08, C14; 026 C27, C28, C32, C41; 027 C27, C28,
C32, C41; 028 C27, C28, C33, C41; 029 C27, C31; 030 C08, C14; 031 C01–C03, C05, C06; 032 C08, C11; 033 C08, C09, C13; 034 C15, C16,
C19, C26; 035 C42, C43, C46, C52; 036 C42, C43, C46, C52; 037 C08, C12; 038 C27, C33; 039 C01, C02, C07; molecules 040 C15, C16,
C20, C26; 041 C27, C28, C38, C41, C55; 042 C42–C44, C52; 043 C27, C28, C34, C53, C54, C60; 044 C27, C28, C35, C36, C41, C57, C63;
045 C27, C28, C37, C41, C54; 046 C27, C28, C38, C55; 047 C15, C16, C25; 048 C15, C16, C21, C53, C61; 049 C15, C16, C22, C23, C26,
C56, C62, C65; 050 C42, C43, C46; 054 C15, C16, C25; 059 C42, C43, C45, C53; 062 C42†, C48, C49; 063 C42†; 065 C15, C16, C25; 069
C42, C43, C46; cross-band 079 C15, C24, C58, C64; 085 C42, C43, C47; 089 C27, C40; 090 C27, C40; 091 C27, C28, C39; 228 C42†,
C50, C51.

## 10. Open questions

Each row is a question for the owner of the source it names, with both readings, never a guess (ruled as BQ-24); a case it
blocks says so, and the other cases of the same family run. Nothing is re-decided here; the merged design wins meanwhile
(BQ-08).

- **OQ-1 The 500-row table story** (C65; the S04 Test plan's no-remount story; owner: the #261 and E05-S04 ticket text against
  `15`'s E05-S03 as-built). Reading A (#261 Performance notes; S04 Test plan "a story containing a 500-row table plus these
  controls"; E05-T02's "500-row benchmark"): a 500-row story exists to observe. Reading B (`15`:585–586: "v0 renders every row
  with a bound of 200, above which it warns in development"; `Perf200Rows`): v0's table is bounded at 200 and the 500-row surface
  is E05-T02's benchmark page (`ThemeRuntime` `StyleRecalcBenchmark`, "over 500 rows"), not a Table story. The plan observes on
  `Scrolling`, `Perf200Rows` and `StyleRecalcBenchmark`.
- **OQ-2 The below-1280 × 800 advisory state** (section 2, C-1; owner: the shell, E15 / E10 — `16`:269's minimum viewport and the
  dock's transform). Reading A (#261 Technical notes: "Below 1280×800 the advisory state is expected rather than a reflow — verify
  that too"): a state this plan can render. Reading B (`16`:269; no `packages/ui` component or story renders an advisory, `git grep
advisory` over `packages/ui/src` and `apps/web/src` finds none at the base): it is the shell's, outside the library's black-box
  surface; the plan verifies only that no component clips at 1280 × 800 (C22, C34, the walks).
- **OQ-3 "Chromium at the Electron version"** (section 7; owner: the #261 text with the desktop lane and E05-X02). Reading A
  (#261 Technical notes): the Storybook run happens in a Chromium matching `electron ^45.0.0`'s (`apps/desktop/package.json`).
  Reading B (`packages/ui/package.json` `playwright ^1.64.1`; `05`:221 row 3 "matches Electron's Chromium version" as a goal of the
  protocol): no pin ties the two on `main`; the plan records the version run and claims no match.
- **OQ-4 RbacGate `FormTooltip`, `FormNotice`, `Denied(EnvMismatch)`** (C15, C24, C58; owner: E05-S04 #267). Reading A
  (`15`:888): twelve stories exist. Reading B (`RbacGate.stories.tsx`:43–93: nine exports; `git grep FormTooltip` finds none): the
  `tooltip` and `notice` forms have no story at the base; the tooltip form is read through `Tooltip` `EchoReason` and the notice
  form through `FormSection` `DisabledWithReason` (one notice, many pointers, `HO-S03`:54).
- **OQ-5 The two missing composition stories** (C53, C55; owner: E05-Q03 #263; BQ-16, ruled). Reading A (#261 Scope): the
  compositions are run as written, which needs a Combobox-in-Dialog and a Menu-in-Drawer story or an ad-hoc mount. Reading B
  (BQ-15, ruled: this plan adds no story): CMP-059 is the built Combobox-in-Dialog and the Menu-in-Drawer is probed on its stand-ins;
  a committed composition story is E05-Q03's "one story per fixed composition defect"; Reading B is ruled (BQ-16), each a † row.
- **OQ-6 A-12, the atom's visible reason echo** (C03, C58; owner: CMP-016 / CMP-040 per the accepted A-row, 2026-10-27). Reading A
  (S01.3 "the reason is shown" on hover or focus; `15`:51's "rendered inline or echoed by a focus+hover CMP-016 tooltip"): every
  atom shows its reason visibly. Reading B (A-12, `E05-S01-catalogue-a-rows.md`:18; `HO-S01`:26): the atom carries a hidden
  description only, the visible echo being the host's CMP-016 or CMP-040 — accepted. The plan asserts Reading B and records the
  visible half as "assistive technology only" at the atom.
- **OQ-7 The S04 trio** (C42, C48–C51; owner: E05-S04 #267). Reading A (`15`:702, :712, :2920 with their Storybook lists; S04.1–S04.4):
  the components and their stories exist to test. Reading B (`index.ts` at the base; `git grep ThemeSwitcher|DensityToggle|PreviewTile`
  over `packages/ui/src` finds none): unbuilt; #267's merged slices are CMP-085, 079, 089 / 090 and 091. With them: CMP-062's
  J15 role rule (PROPOSED, owner approval pending on #2701, `15`:706) and J13's "match system" toggle (RULED) are asserted only
  once built and, for J15, ruled.
- **OQ-8 The D03 motion recipes** (C07, C31, C57, C-1; owner: #3174, blocked by E05-D03 #162). Reading A (E05-T02 Scope: "Motion
  recipes from E05-D03 implemented as CSS custom properties"): named recipe pairs exist in `theme.css`. Reading B (#3174's body:
  E05-T02 "shipped the reduce-motion mechanism … but descoped the motion recipes"; `theme.css`:48–52 holds `--cv-motion-scale`
  only): the reduce path exists and the named recipes do not. The plan tests the path (`data-motion`) and names no recipe.
- **OQ-9 The S04 analytics callbacks** (C48, C49; owner: E05-S04 #267 with the analytics owner). Reading A (S04 Observability:
  "CMP-062/CMP-063 invoke the injectable analytics callback with `appearance.theme_changed` and `appearance.density_changed`"): a
  control invokes it to observe. Reading B (`store`:56–59, :238: the runtime's `emit` names the events and the sink is a no-op by
  default): the emitter exists in the runtime, the controls that invoke it from a user action do not; a black-box observation
  needs an injected sink, which is the host's, so the plan asserts the root attribute and marks the callback †.
- **OQ-10 Does the PR close #261 on the plan alone?** (section 1, 7; ruled, BQ-22, Reading A). The document closes the ticket, as
  #404 and #422 did; the DoD's "All scenarios executed; results recorded per scenario" is read as section 7's ledger plus the
  execution pass owed on #261 as comments inside Sprint 06, not waived; the human and S04 legs are blocked and named; E05-Q03
  (#263) assembles the epic sign-off. Section 7 is the execution's entry sheet.

**Known gaps: hooks, stories and states a case names that nothing provides at the base** (a `git grep` over `packages/ui/src`
and `apps/web/src` at `b8575c6f1` finds no emitter for each, except where the row says what exists; a † marks each use in a
case; re-grepped at the READY sha `b8575c6f1`, section 0). A case asserts the stand-in until the owner ships it or amends its
ticket. Stories that **exist** and are asserted directly are the 683 of section 1; the analytics events `appearance.*` and
`a11y.preference_changed` exist as the runtime's `emit` (`store`:56–59, :231, :238) and are listed below only for the control that
is missing.

| Hook, story or state                                                                                                                                                                                                                                                         | Cases              | Named by (owner)                                                                                                                 | Assert meanwhile                                                                                       |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| a 500-row Table story (`Perf500*`, "500-row": none)                                                                                                                                                                                                                          | C65                | #261 Performance notes; the S04 Test plan (E05-S04 #267); E05-T02's benchmark                                                    | `Table` `Scrolling` and `Perf200Rows`; `ThemeRuntime` `StyleRecalcBenchmark` as the measuring artefact |
| the below-1280 × 800 advisory state (`advisory`: none in `packages/ui/src`, `apps/web/src`)                                                                                                                                                                                  | section 2, C-1     | #261 Technical notes; `16`:269 (the shell: E15 / E10)                                                                            | no component clips at 1280 × 800 (`Table` `Reflow`, `Dialog` `Reflow`, the walks)                      |
| a Chromium pinned to the Electron version                                                                                                                                                                                                                                    | section 7          | #261 Technical notes (the desktop lane; E05-X02 #272)                                                                            | the Chromium version actually run, recorded                                                            |
| `RbacGate` `FormTooltip`, `FormNotice`, `Denied(EnvMismatch)` (none)                                                                                                                                                                                                         | C15, C24, C58      | `15`:888 (E05-S04 #267)                                                                                                          | `Tooltip` `EchoReason`; `FormSection` `DisabledWithReason`; `FormInline`                               |
| a CMP-048 Combobox composed in a CMP-043 Dialog                                                                                                                                                                                                                              | C53                | #261 Scope composition 1 (E05-Q03 #263; † per BQ-16, ruled)                                                                      | `CommandPalette` `Default` / `Gated`; `Dialog` `EscTopmost`                                            |
| a Menu in a scrolling Drawer                                                                                                                                                                                                                                                 | C55                | #261 Scope composition 3 (E05-Q03 #263; † per BQ-16, ruled)                                                                      | `Drawer` `LongText`; `Menu` `Scrolling`, `EscTopmost`                                                  |
| CMP-062 ThemeSwitcher and its stories Default, MatchSystem, Light, HighContrast (none)                                                                                                                                                                                       | C42, C48, C49      | `15`:702–709; S04.1, S04.2 (E05-S04 #267)                                                                                        | the toolbar `theme` global; `ThemeRuntime` `Default` (no remount); the root `data-theme`               |
| CMP-063 DensityToggle and its stories Global, PanelOverride, ChartPanelDense, MenuForm (none)                                                                                                                                                                                | C42                | `15`:712–719 (E05-S04 #267)                                                                                                      | the toolbar `density` global; the root `data-density`                                                  |
| CMP-228 PreviewTile and its stories (none)                                                                                                                                                                                                                                   | C42, C50, C51      | `15`:2920–2926; S04.3, S04.4 (E05-S04 #267)                                                                                      | —                                                                                                      |
| a control invoking `appearance.theme_changed` / `appearance.density_changed`                                                                                                                                                                                                 | C48, C49           | S04 Observability (E05-S04 #267); the emitter exists in `store`:238                                                              | the root attribute; the runtime's `emit` as white-box evidence                                         |
| the E05-D03 motion recipes as CSS pairs (`theme.css` holds `--cv-motion-scale` only)                                                                                                                                                                                         | C07, C31, C57, C-1 | E05-T02 Scope; #3174 (open, blocked by E05-D03 #162)                                                                             | the `data-motion="reduce"` path                                                                        |
| an atom's visible disabled-reason echo                                                                                                                                                                                                                                       | C03, C58           | S01.3; `15`:51 (CMP-016 / CMP-040 per A-12, accepted 2026-10-27)                                                                 | the hidden `aria-describedby` description; the host's `Tooltip` `EchoReason`                           |
| `Table` `Virtualized(10k rows)`, `MergedCell`, `SortUnavailable` (none)                                                                                                                                                                                                      | C15, C23           | `15`:583; deferred by `15`:585–587 ("the epic that first needs 10k+ rows")                                                       | not asserted; the 200-row bound                                                                        |
| `ProgressBar` `Running`, `Failed`, `Unknown`, `InWizard`; `Callout` `ChartStrip`, `BarRebuildProgress`; `Tag` `EstimatedChip`; `Avatar` `ColorPalette`; `KeyValueRow` `LiveFreshness`; `ConfirmDialog` `Rung1`–`Rung4`, `TwoChoice`, `TwoChoiceUnknown`, `RuleDisarm` (none) | C08, C27, C42      | `15`:283, :339, :159, :179, :425, :520 — their design rows (E25-D05 / CMP-227, the avatar palette E2, CMP-239, E42-D02, E35-D02) | not asserted; the as-built lines (`15`:161, :181, :341, :427) say they wait                            |
| the `pattern.hatch.unprotected` token (`Callout.tsx` names it; the edge is not built)                                                                                                                                                                                        | C33                | `15`:341 (#265 ruling 6)                                                                                                         | `ProtectionPendingSolidEdge`: the solid 2 px edge                                                      |
| a human NVDA tester                                                                                                                                                                                                                                                          | C60–C62, C-1, C-2  | the 2026-10-29 line; `05`:221 (the owner, asked through the #2701 digest, never assumed; BQ-11)                                  | "blocked on a human tester"; never a result                                                            |
