# E42-D05 — handoff checklists (SCR-143, SCR-144, SCR-146 and its restore wizard, the onboarding wizard, SCR-017, SCR-062's governance layer and the statechart inspector; #960)

Per `docs/plan/16-design-system-brief.md` §11.4 and §13.3 item 8 (`02` §4.2): this SCR ticket changes four component
contracts (`docs/design/E42/E42-D05.md` §17, D05:806-815) —
**CMP-178 SystemHealthTile**, **CMP-210 HealthChips**, **CMP-023 Progress Bar** and **CMP-066 Stepper** (`16:487`) — so
each gets a block below; the components it only composes get one placement line each and link their own checklists.
**Shape:** E42-D04's (E30-D03's and E39-D02's): Tables 1–5, the Density table and the Essential-exceptions table
appear once each with a leading `Component` column instead of once per block. **This file decides nothing:** every row
cites the spec line that decides it. Prop and story names are Appendix A's text (D05:969-987), which lands in `15`
in a later commit of the boards PR; they are PROPOSED until owner approval (D05:3-13).

**Key.** `D05:n` = a line of `docs/design/E42/E42-D05.md` at this branch; `D03` = `docs/design/E42/E42-D03.md`;
`D04` = `docs/design/E42/E42-D04.md`; `D09` = `docs/design/E09/E09-D09.md`; `Y`, `W`, `M`, `svc/` and `tok` as D05's
key (D05:15-23). `15` entries are read at `origin/main` `8603fce18`, the boards PR's base. There CMP-178
and CMP-066 are still the text D05 quotes as "Old"; CMP-023 is the entry #4414 rewrote, which already carries
`valueText?`, determinate-only progress, no live region and the `color.surface.hover` track, and CMP-210 has an
As-built line (E10-S01, `15:2544`): both are §21's C-rows (D05:901). CMP-178's base is E42-D03's Appendix A text,
which reaches `15` with E42-D03's boards PR (#886). Every board below is PENDING (§0, D05:51-123).

## Handoff checklist — CMP-178 SystemHealthTile (E42-D05, #960)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0, D05:53-55): page `E42-D05` in the file `E42-D05 boards`, its page
      id pinned in §0 once it exists (never a host, team, file id or URL); the tile is drawn on boards 01
      `e04-continuity` (HL-2, HL-5, HL-14 at 1280), 03 `scr143-144-populated` (HL-2 [06] with the client-tile inset,
      HL-5 [09], HL-6 [10] with the HL-7 inset), 04 `scr143-outage` (HL-11 [14], HL-12 [15], HL-14 [17]) and 10
      `light-representatives` (HL-20 [22]); PNGs `docs/design/E42/img/E42-D05-NN-<slug>.png`; [03] `component-sheet`
      and [04] `redlines` are not drawn — the text binds (D05:100-112)
- [ ] **Variants × States matrix** — PENDING with the boards: D03's nine stories and Appendix A's five (NotDeployed,
      WithHistory, HistoryTable, NumberStale, WithHint; D05:981), each mapped to its §5.3 state in Table 1
- [x] **Keyboard table** — Table 2: tiles in DOM order, each heading link, then its Runbook link, Retry and history
      disclosure, no roving grid; `Alt+T` toggles the Table view (`05:57`); history and Table view tables are CMP-049
      focusable scroll regions named by their caption (D05:374-376); no key binding is added (D02 D18)
- [x] **Accessible name / role table** — Table 3: `role="region"` labelled by its heading, "{plain label} ({name})",
      which is the link (D4, D05:166); the state word with one glyph shape (D2, D05:164); the number's unit in words
      ("probe 210 milliseconds", D05:735-744); the sparkline CMP-024 `role="img"` with its trend label and
      "View as table" (D13, D05:175)
- [x] **Live data** — Table 5: entering degraded or down is announced assertive once, recovery polite once; "as of"
      and ages never (D05:374-376; D11, D05:173)
- [x] **Motion pair** — Table 4: a state flips in one frame, words first (M9); the skeleton static under reduced
      motion (M12); a sparkline sample one frame, §14's A-row (2) (D05:746-752)
- [x] **Density notes** — Density table: comfortable; three columns of ≈307 px at 1280, five of 400 px at 2560,
      `space.3` gaps (D1, D05:163); one column at 200 % (§4.2, D05:263-271)
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Appendix A's Tokens row (D05:981): `color.surface.raised`, `radius.card`,
      `color.text.primary`/`secondary`/`tertiary`, `color.status.success.strong`, `color.status.warning.strong`,
      `color.status.danger.strong`, `color.data-confidence.stale.indicator`, `color.neutral.default` (the ring; the
      "neutral" stand-in, CG-30), `type.num.base`; none invented (§16, D05:770-777); Penpot token
      sets = `packages/ui/tokens` at `origin/main` `8603fce18ed5c186c178174e88dccd21bf117bed`
- [x] **Data contract confirmed** — `HealthReport.components[]`
      `{name, state, latency_ms, latency_unit, detail, last_good_at}` from `GET /admin/health` (`admin:read`, executed) and the `system` topic's `health` frames, words
      only (§5.1, D05:317-331); the five states verbatim, `not_deployed` "not built yet"
      (D2); gaps named: CG-17, CG-18, CG-19 (D05:922-924)
- [ ] **Contrast and CVD** — PENDING: every pair is §16's (D05:768-804), re-run by
      `docs/design/_tools/e42_d05_admin_audit.py` in this PR (exit 0, FAIL 0, every §16 number matched); registering the
      gated pairs in `tools/contrast/pairs.mjs` is a `tools/` change outside a design PR, routed as E42-D04 routes its
      own; the greyscale and deuteranopia renders of boards 02, 03 and 04 ship with the boards (D05:65-67)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#960)

## Handoff checklist — CMP-210 HealthChips (E42-D05, #960)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0): page `E42-D05`; the chips sit in the TopBar of the SCR-143
      frames as the shell draws them (§5's anatomy, D05:310); their Stale, Unknown and NonOwner variants
      were [03] `component-sheet`'s, not drawn — the text binds (D05:100-112); `15`'s
      As-built line puts two chips in the CMP-208 status bar, with no admin link or focus yet (§21's C-row (4))
- [ ] **Variants × States matrix** — PENDING with the boards: AllOk, Warning, Error, Mixed and Appendix A's Stale,
      Unknown, NonOwner (D05:983); Table 1
- [x] **Keyboard table** — Table 2: for the owner a `warn`, `error` or `stale` chip is a link to its component on
      SCR-143; for any other session it is focusable text with no link (D09:44; D05:982)
- [x] **Accessible name / role table** — Table 3: "`label`: `state`, `value`"; `stale` reads "stale since
      {hh:mm:ss}", `unknown` "unknown"; `description` in the DOM, `tooltip` only its echo (D05:811)
- [x] **Live data** — Table 5: ages are never live (D05:982); a component's own announcement is the page's
      (D11, D05:173)
- [x] **Motion pair** — Table 4: a chip's state flips in one frame (M9, D05:746)
- [ ] N/A — **Density notes**: the chips keep the shell's TopBar geometry (D03 §4); D05 names no chip size
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Appendix A's Tokens row (D05:983): `color.status.*`,
      `color.data-confidence.stale.indicator`, `color.text.primary`, `radius.pill`; Penpot token sets as CMP-178's line
- [x] **Data contract confirmed** — the `system` topic's `health` frames,
      `components[] {name, state, detail, last_good_at}`, 1 000 ms throttle, `detail` Owner-only (§5.1, D05:323); the owner-only `href` follows
      SCR-143's RBAC (M:129-134; D05:378)
- [ ] **Contrast and CVD** — PENDING: as CMP-178's line; the glyph rows (D05:785) and the stale-versus-warning
      pair, which collapses and so is carried by the clock and the words (D05:799)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#960)

## Handoff checklist — CMP-023 Progress Bar (E42-D05, #960)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0): page `E42-D05`; the bar is drawn on board 05
      `scr146-list-download` (BK-4 [38]'s Running row); BK-6 [40], RW-2 [53] and RW-9 [60] are not drawn — the text
      binds (D05:463, 554)
- [ ] **Variants × States matrix** — PENDING with the boards: `main`'s Default, WithLabel, AllTones, Meter, Unlabelled
      and Appendix A's Running, Failed, Unknown, InWizard, re-read on `main` in the later commit (§21's C-row (3)); Table 1
- [ ] N/A — **Keyboard table**: the bar takes no focus and binds no key; its host's controls are CMP-001's (Table 2
      states it)
- [x] **Accessible name / role table** — Table 3: `role="progressbar"` with `aria-valuenow/min/max`; `aria-valuetext`
      (the merged `valueText`) equals the visible "{n} %"; a failed, cancelled or unknown status is a word beside the bar
      (D05:812, 984)
- [x] **Live data** — Table 5: never a live region; its host announces "{n} %" politely at 25 % steps while the job is
      readable; a failed poll keeps the last % (D05:282-289, 481)
- [x] **Motion pair** — Table 4: progress is D04's M15 (D05:746); never an indeterminate loop for a job
      with `progress_pct`
- [ ] N/A — **Density notes**: `main`'s 8 px track (`15:277`); D05 adds no size
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Appendix A's Tokens row (D05:985) and `main`'s: fill
      `color.action.primary.default`, track `color.surface.hover` (the `color.track` stand-in, CG-30), text
      `color.text.secondary`; Penpot token sets as CMP-178's line
- [x] **Data contract confirmed** — `Job.{status, progress_pct, error}` from `GET /admin/jobs/{jobId}` (`admin:read`;
      memory only, lost on restart; D05:456), polled every 2 s as D04 proposes (D36, D05:198; CG-28)
- [ ] **Contrast and CVD** — PENDING: as CMP-178's line; the progress row (D05:791)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#960)

## Handoff checklist — CMP-066 Stepper (E42-D05, #960)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0): page `E42-D05`; the restore stepper is drawn on boards 06
      `restore-gate-impact` (RW-1 [52], RW-3 [54], RW-4 [55], RW-5 [56], RW-6 [57]) and 07 `restore-outcomes` (RW-8
      [59], RW-10 [61], RW-12 [63], and RW-14 [65]'s collapsed form at 200 %), the owner's on board 08 `onboard-key`
      (WZ-1 [67], WZ-4 [70], WZ-5 [71] blocked, WZ-6 [72], WZ-11 [77], WZ-12 [78] resumed) and both light twins on board 10
      (RW-15 [66], WZ-16 [81])
- [ ] **Variants × States matrix** — PENDING with the boards: Default, WithErrors and Appendix A's Blocked, Resumed,
      Navigable, Collapsed (D05:987); Table 1
- [x] **Keyboard table** — Table 2: on a step change focus moves to the step heading (`tabindex="-1"`, D27); Tab: the
      step's content → Back → Next or the confirm; the owner's stepper links reach any step (`navigable`); Esc on
      restore steps 1–3 is "Cancel restore", inert on 4–6 (D05:563-566, 635-637)
- [x] **Accessible name / role table** — Table 3: a `<nav>` with an `aria-label` holding an ordered list,
      `aria-current="step"`, each status a word with one glyph (check done, dot current, clock blocked, octagon error,
      ring not started); a blocked step states its reason and its until-time in text and never blocks later steps (D27,
      D29; D05:189, 191, 986)
- [x] **Live data** — Table 5: the stepper announces nothing itself; saved steps, the resume and a refusal speak once
      through the page (D05:735-744)
- [x] **Motion pair** — Table 4: a status flips in one frame (§14's A-row (2)); the step change moves focus, never
      animates (A-row (1); D05:746-752)
- [x] **Density notes** — Density table: a 240 px column left of the step body (D1, D27; D05:163); at 200 % "Step
      {n} of {m}: {name}" with a disclosure (§4.2, D05:263-271)
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Appendix A's Tokens row (D05:987): `color.text.primary`/`secondary`,
      `color.status.success.strong`, `color.status.warning.strong`, `color.status.danger.strong`,
      `color.status.info.strong`, `color.neutral.default`, `color.border.selected`, `color.focus.ring`; Penpot token
      sets as CMP-178's line
- [x] **Data contract confirmed** — the owner wizard renders `steps[] {key, status, completedAt, blockedUntil}` from
      a server record, a target (CG-3; D28, D05:190); the 48-hour time from the checklist's `unblock_at`, a proxy
      (CG-4); the restore's steps are client-side over `restoreBackup` and `getJob` (§8.1, D05:493-515)
- [ ] **Contrast and CVD** — PENDING: as CMP-178's line; the stepper-glyph and current-step rows (D05:786, 787)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#960), with the blocking security look on the restore copy (AC-3,
      D05:849)

**Placement lines (contract unchanged here; their own checklists apply).** CMP-024 Sparkline — CMP-178's history,
`role="img"` with its trend label (`15:285`), drawn in `color.text.secondary` (§16), where `main`'s Tokens say
`color.text.tertiary` without `colorBySign` (§21's C-row (5); D13, D05:175). CMP-049 Table — the Table view, the history
table, SCR-144's APG grid (one tab stop, `aria-rowindex` when windowed, `15:555`), SCR-146's grid, the machine table and
the timeline; SCR-062's few rows are a table, not a grid (D05:425, 478, 674).
CMP-043 Dialog and CMP-044 ConfirmDialog (the entry #4414 merged) — every rung of §12 (D05:717-733):
Cancel focused first, the confirm ignoring `event.repeat`, a typed token in the download, delete and restore. CMP-079
RbacGate + CMP-019 Icon `lock` (`decorative=false`, "Not available") — every T2 control (§4.1,
D05:231-251); one reason shared by a page's controls is one notice every control points at. CMP-092
DegradedModeBanner — `health.banner_down`, static `role="status"` (D11, HL-5). CMP-028 Callout / Banner — D04's
maintenance banner in the shell slot (D12). CMP-239 FreshnessMarker — "stale since {time}" (D6, HL-11, HL-14).
CMP-177 RecorderStatusRow — HL-17's rows, the proposed `variant: "summary"` an A-row to E16-D02's owner,
`variant: "table"` until then (D05:814). CMP-146 NodeGraphCanvas `readOnly` — the inspector's diagram beside its normative
text list (D35, SI-4). CMP-040 FormField — the onboarding secret, write-only, no reveal (D30). CMP-105 — step 4's
accounts (WZ-7). CMP-001 Button `loading` — a control whose own job runs or that waits on a read in
flight is busy, never T2 (§4.1). CMP-015 Skeleton, CMP-026 EmptyState, CMP-027 ErrorState, CMP-033 CopyButton, CMP-065
FormSection, CMP-076 (E17's chip), CMP-087, CMP-088, CMP-093 AuditActionTrigger, CMP-207 BuildFooter — as §5–§11
place them.

### Table 1 — Variants × States (stories from Appendix A; boards PENDING)

| Component | Story                                           | D05 state (cite)                                                      | Board ([old id] → drawn board NN, PENDING; or not drawn) | Notes                                         |
| --------- | ----------------------------------------------- | --------------------------------------------------------------------- | -------------------------------------------------------- | --------------------------------------------- |
| CMP-178   | Ok                                              | HL-2 every component `healthy` (D05:354)                              | [06] → 03; 01 (1280)                                     | D03's story; the client tile beside it        |
| CMP-178   | Warning                                         | HL-3 degraded, HL-4 warning: triangle and the word (D05:355-356)      | [07], [08] not drawn                                     | D03's story; the word tells them apart        |
| CMP-178   | Danger                                          | HL-5 down, no number, "last good" (D05:357)                           | [09] → 03 (1280); 01                                     | D03's story                                   |
| CMP-178   | Loading                                         | HL-1 its own skeleton (D05:353)                                       | [05] not drawn                                           | D03's story; no page spinner                  |
| CMP-178   | Error                                           | HL-12 report fails on first mount (D05:364)                           | [15] → 04 (1280)                                         | D03's story; `health.report_failed` + [Retry] |
| CMP-178   | Unavailable                                     | HL-15 `503 audit_unavailable` (D05:367)                               | on [15] → 04 (inset on HL-12)                            | D03's story                                   |
| CMP-178   | Stale                                           | HL-11, HL-14: "stale since {time}" (D05:363, 366)                     | [14] → 04; [17] → 04, 01 (1280)                          | D03's story; greyscale render on 04           |
| CMP-178   | WithEnvBadge                                    | D03's `env?`; §5's tiles draw no badge                                | —                                                        | D03's story                                   |
| CMP-178   | NotReceived                                     | HL-10 `501`, HL-12: "— not received" (D05:362)                        | [13] not drawn; [15] → 04                                | D03's story                                   |
| CMP-178   | NotDeployed                                     | HL-7 ring + "not built yet", neutral (D05:359)                        | on [10] → 03 (inset on HL-6)                             | ranks healthy                                 |
| CMP-178   | WithHistory                                     | HL-16 sparkline with its trend label (D05:368)                        | [18] not drawn                                           | the target series, annotated (CG-17)          |
| CMP-178   | HistoryTable                                    | HL-16's CMP-049 time · value · unit (D05:368)                         | [18] not drawn                                           | AC-5                                          |
| CMP-178   | NumberStale                                     | HL-11 a number older than its word, its own "as of" (D5, D05:167)     | [14] → 04                                                | `valueAsOf`                                   |
| CMP-178   | WithHint                                        | HL-3–HL-5 `hint.*` and "Runbook →" (D9, D05:171)                      | [09] → 03 (1280)                                         | `health.safe` withheld on its inset           |
| CMP-210   | AllOk                                           | every chip `ok` (D05:983)                                             | the TopBar of [06] → 03                                  | as the shell draws it                         |
| CMP-210   | Warning                                         | a `warn` chip                                                         | —                                                        | unchanged                                     |
| CMP-210   | Error                                           | an `error` chip                                                       | —                                                        | unchanged                                     |
| CMP-210   | Mixed                                           | chips in several states                                               | —                                                        | unchanged                                     |
| CMP-210   | Stale                                           | the feed behind the chips down: "stale since {hh:mm:ss}" (D05:982)    | [03] not drawn                                           | §21's C-row (4)                               |
| CMP-210   | Unknown                                         | no state received: "unknown" (D05:982)                                | [03] not drawn                                           | —                                             |
| CMP-210   | NonOwner                                        | focusable text, no link (D09:44; D05:811)                             | [03] not drawn                                           | —                                             |
| CMP-023   | Default, WithLabel, AllTones, Meter, Unlabelled | `main`'s (`15:271-279`)                                               | —                                                        | re-read in the later commit (C-row (3))       |
| CMP-023   | Running                                         | BK-4's and BK-6's running row "{n} %" (D05:463, 465)                  | [38] → 05; [40] not drawn                                | polite at 25 % steps                          |
| CMP-023   | Failed                                          | RW-13 the restore failed (D05:558)                                    | [64] not drawn                                           | the word beside the bar                       |
| CMP-023   | Unknown                                         | a lost job, `404 job_unknown` (RW-10, D05:555)                        | [61] → 07 (1280)                                         | the row is read instead                       |
| CMP-023   | InWizard                                        | RW-9 step 4 "Restoring… {n} % — trading is off" (D05:554)             | [60] not drawn                                           | `restore.progress`                            |
| CMP-066   | Default                                         | RW-1 step 1 of the restore (D05:546)                                  | [52] → 06                                                | six steps                                     |
| CMP-066   | WithErrors                                      | RW-8 refused after admission (D05:553)                                | [59] → 07                                                | "Needs attention" (octagon)                   |
| CMP-066   | Blocked                                         | WZ-5 "Blocked until 2026-10-24 09:15 UTC", later steps open (D05:603) | [71] → 08 (1280)                                         | AC-4                                          |
| CMP-066   | Resumed                                         | WZ-12 the first incomplete step current (D05:610)                     | [78] → 08 (1280)                                         | `onboard.resume`                              |
| CMP-066   | Navigable                                       | the owner wizard's stepper links (D05:635)                            | [67] → 08 (1280)                                         | `navigable`                                   |
| CMP-066   | Collapsed                                       | RW-14 "Step 2 of 6: What a restore does" at 200 % (D05:559)           | [65] → 07 (1280)                                         | §4.2                                          |

### Table 2 — Keyboard

| Component | Key                                     | Action                                                                                               | Focus after                                                     | Global conflict?           | Cite            |
| --------- | --------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | -------------------------- | --------------- |
| CMP-178   | Tab / Shift+Tab                         | tiles in DOM order: the heading link, then Runbook, Retry and the history disclosure; no roving grid | the next control                                                | none                       | D05:374-376     |
| CMP-178   | Enter on the heading link               | opens the component's detail (HL-17 for the recorder)                                                | the detail (a page change)                                      | none                       | D05:369         |
| CMP-178   | Enter / Space on the history disclosure | shows the sparkline and its CMP-049 table                                                            | stays on the disclosure; the table is a focusable scroll region | none                       | D05:368; 374    |
| CMP-178   | `Alt+T` (page)                          | toggles the Table view of every component                                                            | unchanged                                                       | none (`05:57`'s binding)   | D05:165; 376    |
| CMP-210   | Tab, then Enter (owner)                 | a `warn`, `error` or `stale` chip opens its component on SCR-143                                     | SCR-143 (a page change)                                         | none                       | D05:982         |
| CMP-210   | Tab (any other session)                 | focusable text, no link                                                                              | the next control                                                | none                       | D09:44; D05:811 |
| CMP-023   | —                                       | no stop                                                                                              | —                                                               | none                       | D05:984         |
| CMP-066   | (a step change)                         | focus moves to the step's `h2` (`tabindex="-1"`), so the impact copy is read before any control      | the step heading                                                | none                       | D27; D05:189    |
| CMP-066   | Tab / Shift+Tab                         | the step's content in reading order → Back → Next or the confirm                                     | the next control                                                | none                       | D05:563; 635    |
| CMP-066   | Enter on a stepper link (owner wizard)  | opens that step (`navigable`)                                                                        | the step heading                                                | none                       | D05:635         |
| CMP-066   | Esc (restore steps 1–3)                 | "Cancel restore": back to the list, nothing sent; inert on steps 4–6                                 | the list (§8.1)                                                 | none (Esc is the wizard's) | D05:566         |

### Table 3 — Accessible name / role

| Component | Element       | Role                          | Accessible name (source)                                                     | States / properties                                                                                                                     |
| --------- | ------------- | ----------------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-178   | the tile      | `region`                      | its heading, "{plain label} ({name})", which is the link (D4)                | the state word always rendered with one glyph shape (D2); "Attention:" prefixes a warning; no number for a field not received (D05:980) |
| CMP-178   | the number    | text                          | "probe 210 milliseconds" (the unit in words, §13)                            | its own "as of" when older than the word (D5); an age carries its absolute UTC time in its description (D02:119)                        |
| CMP-178   | the sparkline | `img` (CMP-024)               | its trend label, "probe latency, last hour: rising, 120 to 210 milliseconds" | "View as table" discloses a CMP-049 of the same series (D13, D05:175)                                                                   |
| CMP-210   | a chip        | text, or a link for the owner | "`label`: `state`, `value`"                                                  | `stale` "stale since {hh:mm:ss}", `unknown` "unknown"; `description` in the DOM, `tooltip` its echo (D05:982)                           |
| CMP-023   | the bar       | `progressbar`                 | its label (or `aria-labelledby`)                                             | `aria-valuenow/min/max`; `aria-valuetext` = the visible "{n} %"; never a live region (D05:984)                                          |
| CMP-066   | the stepper   | `navigation` with an `ol`     | its `aria-label`                                                             | `aria-current="step"`; each status a word with one glyph; a blocked step's reason and until-time in text (D27, D29; D05:986)            |
| CMP-066   | a step's body | `region`                      | its `h2`                                                                     | the heading `tabindex="-1"` takes focus on a step change (D27)                                                                          |

### Table 4 — Motion pair

| Component | Property                         | motion-safe                                          | motion-reduce  | Duration / easing tokens | Cite                       |
| --------- | -------------------------------- | ---------------------------------------------------- | -------------- | ------------------------ | -------------------------- |
| CMP-178   | the state word, glyph and number | one frame, words first (M9)                          | the same       | none                     | D05:746; §5.2's motion row |
| CMP-178   | the skeleton                     | D04 M12                                              | static         | D04's                    | D05:353                    |
| CMP-178   | a sparkline sample               | one frame (§14's A-row (2))                          | the same       | none                     | D05:746-752                |
| CMP-210   | a chip's state                   | one frame (M9)                                       | the same       | none                     | D05:746                    |
| CMP-023   | the fill                         | D04 M15                                              | D04 M15's twin | D04's                    | D05:746                    |
| CMP-066   | a step's status                  | one frame (§14's A-row (2))                          | the same       | none                     | D05:746-752                |
| CMP-066   | a step change                    | focus to the step heading, no slide (A-row (1), M22) | the same       | none                     | D27; D05:189               |

### Table 5 — Live data

| Component | Field                    | Politeness                                             | Cadence                                  | Coalescing                                      | Cite                  |
| --------- | ------------------------ | ------------------------------------------------------ | ---------------------------------------- | ----------------------------------------------- | --------------------- |
| CMP-178   | the state                | assertive once on degraded or down; polite on recovery | per `system` frame (1 000 ms throttle)   | one voice per outage: the component's own (D11) | D05:374-376; 173      |
| CMP-178   | "as of", ages            | never                                                  | —                                        | —                                               | D05:376               |
| CMP-178   | `health.report_failed`   | polite once                                            | per failed read                          | —                                               | HL-11, HL-12; D05:363 |
| CMP-210   | a chip                   | none (ages never live)                                 | per `system` frame                       | —                                               | D05:982               |
| CMP-023   | "{n} %"                  | polite at 25 % steps, by the host                      | per `getJob` poll (2 s, PROPOSED in D04) | a failed poll keeps the last %                  | D05:282-289; 198      |
| CMP-066   | a saved step, the resume | polite once, by the page                               | per save; on return                      | —                                               | WZ-12; D05:610        |

### Density

| Component        | Mode                | Row / control height                               | Padding tokens      | Smallest target                      |
| ---------------- | ------------------- | -------------------------------------------------- | ------------------- | ------------------------------------ |
| CMP-178          | comfortable (admin) | three ≈307 px columns at 1280, five 400 px at 2560 | `space.3` gaps (D1) | a 32 px heading link or button (§13) |
| CMP-066          | comfortable (admin) | a 240 px column left of the step body (D1, D27)    | —                   | a 32 px stepper link (§13)           |
| CMP-210, CMP-023 | comfortable         | the shell's and `main`'s (`15:277`)                | —                   | —                                    |
| all four         | compact             | not specified by D05 (open point for the owner)    | —                   | —                                    |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all four  | none      | —                    | —        | —    |

## §A — Design QA checklist (`16` §12), filled

- [x] Only published Tier-2 / Tier-3 tokens; the missing ones take named stand-ins, never invented (§16,
      D05:770-777; CG-30, D05:935).
- [ ] Three themes × two densities verified visually — PENDING with the boards: dark draws boards 01–09; light draws
      board 10 (HL-20, RW-15, WZ-16), and light and high contrast are proven by §16's computed matrix and board 02's
      columns (deviation 4, OQ-2; D05:44, 119); compact is not specified (Density table).
- [x] Contrast matrix for every pair introduced — §16 (D05:768-804), re-run by
      `docs/design/_tools/e42_d05_admin_audit.py` in this PR: FAIL 0, every §16 number matched; the
      `tools/contrast/pairs.mjs` registration is routed (blocks above).
- [ ] CVD simulation for every new colour-carrying state — PENDING: §16's colour-vision table is computed (the audit's
      section C); the greyscale and deuteranopia renders of boards 02, 03, 04 and 06 ship with the boards.
- [ ] Every State has a Penpot variant and a Storybook story — PENDING: Table 1 maps every story to its state; ten
      boards (PENDING) draw 57 frames and the rest bind as text (§0, D05:71); the stories are E42-S06's and
      E42-S07's.
- [x] Disabled states use disabled-with-reason (§4.1 T2: CMP-079, the CMP-019 `lock`, `aria-disabled`, the reason in
      the DOM at mount; never `color.text.disabled` or `opacity.disabled`; D05:231-251); busy is never T2.
- [x] Loading, empty and error states designed: HL-1, HL-10–HL-15, IL-1, IL-7, IL-8, BK-1–BK-3, BK-16, RW-13, SI-2
      (§5.3–§11).
- [x] Keyboard table completed (Table 2; §5–§11 Keys, §13).
- [x] Accessible-name / role table completed (Table 3).
- [x] No canvas-adjacent component except CMP-146's read-only diagram, whose keyboard path is its normative text list
      (D35, D05:197).
- [x] Motion-safe / motion-reduce pair specified (Table 4; §14, D04 §13 by reference).
- [ ] Hit targets — PENDING: D05 binds 32 px targets (≥ 24 px, §13); [04] `redlines` is not drawn — the text binds.
- [ ] Accessibility role sign-off — owner `approved` on #960 (agent-delivery adaptations); E42-D06 reviews §13, §16
      and this file (D05:900).
- [x] Confirm-gate variant stated: §12's rungs (download, delete, restore and the latch acknowledge at rung 4 with a
      fresh code; the restore and delete with a typed token).
- [ ] N/A — estimated values chip-tagged: these screens show no estimate.
- [x] Demo / Live context unambiguous: accounts carry LIVE or DEMO (C-2.11; the onboarding environment word joins the
      step title, WZ-2).
- [x] Reuses existing CMP ids; no new CMP (the inspector reuses CMP-146, CG-1).
- [ ] Storybook stories match the matrix — PENDING: the implementing tickets' (E42-S06, E42-S07, E42-S08).
- [ ] Composes only published-library components in Penpot — PENDING with the boards.

## §B — Accessibility acceptance criteria (`05` §10), filled per screen

| Screen         | Primary task (keyboard-only, screen-reader)           | Keyboard-only                                                                                                | Screen reader                                                           | Colour-independence                                              | Contrast                | Reduced motion                     | Automated gates                    |
| -------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- | ---------------------------------------------------------------- | ----------------------- | ---------------------------------- | ---------------------------------- |
| SCR-143        | find what is down, what stops and what to do          | incidents link → Re-read → Export → tiles (heading, Runbook, Retry, history) → Table view; `Alt+T` (D05:374) | one voice per outage, assertive once; recovery polite; ages never (D11) | words and glyph shapes per state (D2; §16's colour-vision table) | §16                     | states flip in one frame (M9)      | axe 0 serious / critical — E42-S06 |
| SCR-144        | acknowledge an open incident                          | segmented radios → T2 filters → the grid (one stop) → Load more; Enter on Acknowledge once (D05:425)         | the outcome line replaces the button; refusals assertive once           | Resolution as words with glyphs                                  | §16's words and T2 rows | a row added or removed per D04 M23 | axe 0 serious / critical — E42-S06 |
| SCR-146        | verify a backup and download it safely                | Back up now → Restore… → the grid (← → to row actions) → Load more; dialogs focus Cancel (D05:478)           | "{n} %" polite at 25 % steps; the link never announced (D21)            | statuses as words with glyphs; "Not encrypted" with the octagon  | §16                     | progress per D04 M15               | axe 0 serious / critical — E42-S06 |
| Restore wizard | restore a backup knowing what it changes              | step heading on each step → content → Back → Next or the confirm; Esc cancels on 1–3 (D05:563)               | the impact copy read before any control (D27); refusals assertive once  | stepper statuses as words with glyphs                            | §16's stepper rows      | status flips one frame             | axe 0; keyboard E2E — E42-S06      |
| Owner wizard   | onboard a manager while the key waits                 | step heading → fields → Save → Back → Continue; stepper links (D05:635)                                      | saved steps polite once; the secret never announced (D30)               | "Blocked until …" in words with the clock                        | §16's stepper rows      | status flips one frame             | axe 0; keyboard E2E — E42-S07      |
| SCR-017        | accept an invite and enrol two-factor                 | as the owner wizard's (D05:635)                                                                              | the progress list's `aria-current="step"` (`14:464`)                    | no colour-only state                                             | §16                     | —                                  | axe 0 serious / critical — E42-S07 |
| SCR-062 layer  | disable a group and see that it leaves ticket targets | Tab walks the buttons in row order; Move up / Move down once per press (D05:674)                             | buttons named with their scope; the move polite once                    | status words "Enabled" / "Disabled"                              | §16                     | a moved row is a cut (A-row (3))   | axe 0 serious / critical — E42-S07 |
| Inspector      | find a latched machine and acknowledge it             | the machine grid; the diagram's keyboard path is its text list (D05:712)                                     | latching assertive once, clearing polite once                           | "Latched" with the octagon; "current" in words                   | §16's current-state row | one frame (M9)                     | axe 0 serious / critical — E42-S08 |
