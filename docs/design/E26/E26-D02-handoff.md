# E26-D02 — Component handoff in context (`16` §11.4) and notes for E26-D07

Ticket E26-D02 (#509); spec `docs/design/E26/E26-D02.md`. SCR-097 uses three components whose contracts E26-D05 owns
(CMP-170 ReplayScrubber, CMP-171 ReplaySpeedPicker, CMP-172 ReplayRangePicker); each block records what SCR-097 needs of
one **in context**, and E26-D05's own blocks supersede them. **Status:** text pass; the Penpot and PNG lines are PENDING
(BLOCKED-PENPOT): no board is drawn yet, and the boards and their PNGs come in a later PR, which closes #509 (page
`E26-D02`, spec §16); E26-S02 writes the stories against E26-D05's entries. Penpot token sets = `packages/ui/tokens` at
`ced9a352b2785715ebe8ec74b3fd66443ed7ee05`.

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3). `[ ] PENDING` marks a line the boards' later PR or E26-D05 closes.

## Handoff checklist — CMP-170 ReplayScrubber (E26-D02 in context, #509)

- [ ] **Final Penpot link** — PENDING (BLOCKED-PENPOT), in a later PR: page `E26-D02`, boards 01, 07, 16, 17, 22 and 23; planned PNGs `cmp-170-coverage-scrubber-in-context-dark.png` and `-light.png`
- [x] **Variants × States matrix** — table 1: the catalogued stories plus the states SCR-097 adds (Seeking, GapAhead, EndOfRange, SessionExpired, the E26-D05 ticket's own list, and Error, CoverageClasses, ThumbStates, ViewingAs, OnHold; ReadOnlyRole only if Viewers are granted sessions, spec D-26)
- [x] **Keyboard table** — table 2; checked against `05` §3.2 and §3.3 and the keymap's Replay rows (`apps/web/src/keymap/keymap.json:730-839`): the thumb's keys mean what the page's keys mean, nothing overrides a global binding, no trading action sits on a bare key, `Esc` is only ever a cancel, a focused form control keeps `Space` (spec D-21), `Ctrl+K` untouched; a key on a T2 control changes nothing and re-shows its reason once (spec §5.3)
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5
- [ ] **Motion pair** — N/A — every change here is a state flip, instant in both modes (E11-D06 D15, D20); the thumb's position is data, not an animation; E26-D06 writes the motion pairs
- [x] **Density notes** — shared density table
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING E26-D05: `15` CMP-170 lists `color.action.primary` and `font.mono`; in context the track binds `color.surface.sunken`, `color.neutral.default`, `color.text.tertiary`, `color.text.primary`, `color.text.secondary`, `color.surface.raised`, `color.surface.overlay`, `color.focus.ring`, `type.num.xs` / `.sm` and `radius.pill`, never the primary blue (spec D-7); the coverage-state tokens and the groove hatch (E11-D02 CR-6's geometry with a 2 px `color.neutral.default` stroke, spec §11) are E26-D05's to define, the hatch with E11-D05
- [x] **Data contract confirmed** — `GET /market/data-coverage` (`DataCoverage`, spec §6.1), `ReplaySession` `from`, `to`, `state`, the control actions of spec §5.1, the `replay_seek` snaps (`23` §11) and `machines.replay:{id}.state` (`23` §6.4); the gaps are spec §15.1 (CC-1, CC-3, CC-4, CC-9, CC-15, CC-20), and the step rows depend on CC-16 (no step reaches the clock today)
- [ ] **Contrast and CVD** — computed (spec §12.2); the pairs in `tools/contrast/pairs.mjs` are on `main` (#4122, `8ccfbae06`); PENDING (BLOCKED-PENPOT): only the `cvd_sim.py` renders still come with the boards' later PR
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — at the end
- [ ] **Sign-off** — PENDING: the owner's `approved` on #509 or the merge of the later PR that closes it

### Table 1 — Variants × States

| Variant   | State                                                                                                                       | Penpot   | Story name                         | Notes                                                     |
| --------- | --------------------------------------------------------------------------------------------------------------------------- | -------- | ---------------------------------- | --------------------------------------------------------- |
| transport | paused; stepping (busy: `Play` `aria-busy`, the rest held; `Stepping…`); playing                                            | B06, B04 | `Paused`, `Playing` (catalogued)   | the step unit and the five glyphs, spec D-6, D-22         |
| transport | seeking: the four rungs, landed, cancelled, a held second target                                                            | B07      | `Seeking` (E26-D05 list)           | spec §6.3, D-16                                           |
| transport | gap ahead: the stop callout; the skipped notice                                                                             | B08      | `GapAhead` (E26-D05 list)          | spec D-13; the callout's actions come first in Tab order  |
| transport | end of range (`Play` becomes `Restart`, T1; `>` T2, `replay.end_of_range`); restart refused by the quota                    | B11      | `EndOfRange` (E26-D05 list)        | spec D-18                                                 |
| transport | session expiring (9:58 left); closed with `Resume`, the whole transport T2 on `replay.ended`                                | B12      | `SessionExpired` (E26-D05 list)    | spec D-20, §5.3                                           |
| transport | error with a mapped cause; `Play` (2a) and `>` (2b) T2 on `replay.error`                                                    | B13      | `Error` (new)                      | spec D-23, §7.1, §5.3                                     |
| transport | high speed; speed-limited                                                                                                   | B09      | `HighSpeed` (catalogued)           | spec D-8                                                  |
| transport | viewing as (one `rbac.view_as` notice, every write T2); on hold (`replay.degraded`, the starting controls T2)               | B22, B23 | `ViewingAs`, `OnHold` (new)        | spec §5.3; 2b badges with the echo, `Play` 2a             |
| transport | Viewer: drawn only if the owner grants Viewers sessions (today R-170 and a not-found R-171)                                 | —        | `ReadOnlyRole` (conditional)       | spec D-26, OQ-10                                          |
| track     | full (solid), some (half height), no data (the gap hatch: gap, not recorded), coverage unknown (bare groove), history start | B16      | `CoverageClasses` (new)            | spec D-12, §6.1; the hatch means no data, as on the chart |
| track     | bookmarks, merged markers, a bookmark over pruned data                                                                      | B16      | `WithBookmarks` (catalogued)       | needs CC-15                                               |
| thumb     | rest, hover, focus, drag with its pill, a release into a gap                                                                | B16      | `ThumbStates` (new)                | spec §6.2                                                 |
| keyboard  | the precedence and the focus order                                                                                          | B19      | `KeyboardControlDemo` (catalogued) | spec §10, §12.1                                           |

### Table 2 — Keyboard (the thumb and the transport; the page layer is spec §10)

| Key                         | Action                                       | Focus after         | Global conflict?                                                            | Notes                                                        |
| --------------------------- | -------------------------------------------- | ------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `←` / `→` (thumb)           | one bar back (a seek) / forward (a step)     | stays on the thumb  | none: the meaning of the Replay rows `:746`, `:755`                         | repeats coalesce per 250 ms or key-up                        |
| `Shift+←` / `Shift+→`       | one tick back / forward                      | stays               | none: `:764`, `:773`                                                        | as above                                                     |
| `Ctrl+←` / `Ctrl+→`         | one minute back / forward                    | stays               | none: `:782`, `:791`                                                        | as above                                                     |
| `↑` / `↓`                   | as `→` / `←`                                 | stays               | none (APG slider)                                                           | —                                                            |
| `PageUp` / `PageDown`       | ten bars forward / back                      | stays               | the chart's ±10-bar alias fires only with the chart focused (E06-D03 D6)    | —                                                            |
| `Home` / `End`              | the window's start / end (seeks)             | stays               | none                                                                        | —                                                            |
| `Enter` (the `Go to` field) | seek to the typed UTC time                   | the thumb           | none                                                                        | an invalid time names the field                              |
| `Esc`                       | cancel the seek in flight                    | stays               | proposed `replay.cancel_seek` (spec §10); elsewhere `Esc` keeps its meaning | only while seeking; in the `Go to` field it reverts the edit |
| `Space` / `Enter` (buttons) | activate the focused transport button        | stays on the button | none: native activation wins (below)                                        | —                                                            |
| `Tab` / `Shift+Tab`         | the next / previous control; no roving group | per spec §12.1      | none                                                                        | spec D-6                                                     |
| any key on a T2 target      | nothing; the reason re-shown once, politely  | stays               | none (E09-D09 §9.3)                                                         | spec §5.3; `Space`, the arrows, `Home` / `End`, `Enter`      |

`Space` (spec D-21, §10): Space is play/pause only when focus is on the page body, a panel region, the thumb or a
non-interactive element; on any focused form control (button, checkbox, switch, radio, menu item, option, text field)
the native activation wins.

### Table 3 — Accessible name / role

| Element            | Role                    | Accessible name (source)                                          | States / properties                                                                                                                                  |
| ------------------ | ----------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| thumb on the track | `slider`                | "Replay position"                                                 | `aria-valuemin` / `max` the window and `aria-valuenow` the position, in epoch seconds; `aria-valuetext` "13:38:04 UTC, 13 September 2026 — recorded" |
| thumb, gated       | `slider`                | "Replay position"                                                 | `aria-disabled="true"`; `aria-describedby` → the reason or the transport notice; a drag or key moves nothing (spec §5.3)                             |
| `\|<<`, `<`, `>`   | `button`                | "Restart from 13:00", "Step back one bar", "Step forward one bar" | `aria-keyshortcuts`; T2 2b: `aria-disabled`, the `lock` badge, `aria-describedby` → the reason, the CMP-016 echo (spec §5.3)                         |
| `Play` / `Pause`   | `button`                | the visible word (kept while busy, spec §5.3)                     | `aria-keyshortcuts="Space"`; `Cancel seek` while seeking, `Restart` at `finished`; busy (`aria-busy`) while preparing or stepping; T2 2a (spec §5.3) |
| step unit          | `radiogroup` (2 radios) | "Step by" · "Bar", "Tick"                                         | `aria-checked`; the arrows move between the two here (the page's step keys yield, spec D-21)                                                         |
| `Leave replay`     | `button`                | the visible words                                                 | `aria-keyshortcuts="R"`                                                                                                                              |
| `Go to`            | `textbox`               | "Go to time, UTC"                                                 | `aria-describedby` → "hh:mm:ss inside 13:00–15:00", the date added for a window over two days; `Esc` reverts the edit                                |
| coverage `Details` | `button` + a list       | "Coverage details"                                                | the list names each segment, its range and its cause                                                                                                 |
| bookmark marker    | `button`                | "Bookmark 1, 13:41:07, <label>"                                   | the note as plain text in its description (threat model RP-T03)                                                                                      |
| clock              | `timer`                 | "Replay clock"                                                    | `aria-live="off"`; text at most once a second (spec D-19)                                                                                            |
| transport status   | `status` / `alert`      | "Replay status"                                                   | polite for discrete events; `alert` once for a gap stop, expiry, error, the hold (spec §12.1)                                                        |
| transport notice   | `status` / `alert`      | the notice's sentence (spec §5.3)                                 | one node for viewing as, the hold, no session and an ended session (no live role); every gated control's `aria-describedby` points at it             |

## Handoff checklist — CMP-171 ReplaySpeedPicker (E26-D02 in context, #509)

- [ ] **Final Penpot link** — PENDING (BLOCKED-PENPOT), in a later PR: page `E26-D02`, boards 04, 09, 10, 17, 22 and 23; planned PNGs `cmp-171-transport-and-speed-states-dark.png` and `-light.png`
- [x] **Variants × States matrix** — table 1
- [x] **Keyboard table** — table 2; the arrows move only inside the picker (a radio group, spec D-21); `.` and `,` work page-wide and are proposed (spec §10); a T2 preset is reached, never skipped, and re-shows its reason once (spec §5.3); Space is play/pause only when focus is on the page body, a panel region, the thumb or a non-interactive element; on any focused form control (button, checkbox, switch, radio, menu item, option, text field) the native activation wins.
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: the achieved-rate readout
- [ ] **Motion pair** — N/A — the readout and the selection change in one frame; E26-D06 writes the motion pairs
- [x] **Density notes** — shared density table
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING E26-D05: `15` CMP-171 "inherits CMP-009" (a select) and CMP-003 allows 2–6 options, while the canonical list is seven presets shown at once (spec X-10); in context: `color.surface.selected` (a T2 preset drops it, spec §5.3), `color.border.strong`, `color.text.primary`, `color.text.secondary`, `color.status.warning.subtle` / `.strong`, `type.num.sm` / `.base`, `size.icon.sm`
- [x] **Data contract confirmed** — `ReplaySession.speed`; `play` with `speed` and `set_speed` (`22`; CC-11); the 0.1–100 range (`replay/playback.py:29-30`); the achieved rate from the engine once CC-3 lands, from the frames' `ts` / `wt` until then (spec D-8)
- [ ] **Contrast and CVD** — computed (spec §12.2); PENDING (BLOCKED-PENPOT): `cvd_sim.py` with the boards' later PR
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — at the end
- [ ] **Sign-off** — PENDING: as CMP-170

### Table 1 — Variants × States

| Variant      | State                                                                    | Penpot | Story name             | Notes                 |
| ------------ | ------------------------------------------------------------------------ | ------ | ---------------------- | --------------------- |
| presets row  | rest; selected (fill, border, check)                                     | B04    | `Default` (catalogued) | seven presets, D01 §4 |
| presets row  | paused with a new preset held for `Play`                                 | B06    | `HeldUntilPlay` (new)  | spec D-7              |
| presets row  | above 25×: T2 while this page's simulated orders or open positions exist | B10    | `PaperLimit` (new)     | spec D-9, §5.3        |
| custom field | empty, valid, invalid, clamped                                           | B17    | `Custom` (new)         | 0.1–100, one decimal  |
| readout      | at the request; below it (warning); unknown                              | B09    | `AchievedRate` (new)   | spec D-8, §5.2        |

### Table 2 — Keyboard

| Key                          | Action                               | Focus after         | Global conflict?                                        | Notes                                      |
| ---------------------------- | ------------------------------------ | ------------------- | ------------------------------------------------------- | ------------------------------------------ |
| `Tab`                        | into the group (the selected preset) | the selected preset | none                                                    | one stop for the seven                     |
| `←` / `→` (inside the group) | the previous / next preset, applied  | the new preset      | the page's step keys yield inside the group (spec D-21) | changes are coalesced per 250 ms           |
| `.` / `,` (page-wide)        | the next / previous preset           | unchanged           | proposed (spec §10); alternative `Ctrl+↑` / `Ctrl+↓`    | stops at a T2 preset — re-shows its reason |
| `Enter` (custom field)       | apply the typed speed                | stays in the field  | none                                                    | out of range: clamped, said once           |

### Table 3 — Accessible name / role

| Element      | Role         | Accessible name (source)                         | States / properties                                                                             |
| ------------ | ------------ | ------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| presets      | `radiogroup` | "Playback speed"                                 | each `radio` named "4 times"; `aria-checked`; T2: `aria-disabled` + arrow-reachable (spec §5.3) |
| custom field | `textbox`    | "Custom speed, 0.1 to 100 times"                 | `aria-invalid` with the error text linked                                                       |
| readout      | text         | inside the transport's status region on a change | announced once when it enters or leaves the warning form (spec §5.2)                            |

## Handoff checklist — CMP-172 ReplayRangePicker (E26-D02 in context, #509)

SCR-097 does not render CMP-172 itself: it opens SCR-098 (E26-D03, which owns the range picker's use) in the
configuring state, pre-seeded for `Extend window` (the same symbol and streams; `from` = the old `to`, the same length,
cut at 24 h, `CV_REPLAY_MAX_WINDOW_HOURS`) and for `Resume` (the same window and cursor).

- [ ] **Final Penpot link** — N/A — SCR-097 draws no CMP-172 frame; board 02 shows SCR-098 as an outline (E26-D03)
- [ ] **Variants × States matrix** — N/A — E26-D03 and E26-D05 own them; SCR-097 adds none
- [ ] **Keyboard table** — N/A — no key of SCR-097 acts inside the picker
- [ ] **Accessible name / role table** — N/A — as above
- [ ] **Live data** — N/A — no streaming value
- [ ] **Motion pair** — N/A — no motion
- [ ] **Density notes** — N/A — the picker lives in SCR-098
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — N/A — none bound here
- [ ] **Data contract confirmed** — PENDING CC-14: the pre-seed uses `ReplaySession` `symbols`, `from`, `to`, `cursor_ts`, `speed`, `streams`, `depth` and `paper_account_id`, but the shipped row stores one symbol and no `streams` or `depth`; a destroyed session's fields need CC-6, and a resume costs two buffering phases until CC-19
- [ ] **Contrast and CVD** — N/A — no colour pair introduced
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — at the end (for SCR-097)
- [ ] **Sign-off** — PENDING: as CMP-170

## Shared tables (CMP-170, CMP-171)

No Table 4: nothing animates (each block's Motion line).

### Table 5 — Live data

| Field                             | Politeness             | Cadence                                          | Coalescing                      | Notes                                              |
| --------------------------------- | ---------------------- | ------------------------------------------------ | ------------------------------- | -------------------------------------------------- |
| CMP-170 · clock (`timer`)         | none (`aria-live` off) | text at most once a second                       | the latest second               | spec D-19; the visual readout may change per frame |
| CMP-170 · thumb value text        | none while playing     | on a user action or on pause                     | the latest position             | spec §12.1                                         |
| CMP-170 · transport status        | polite                 | once per discrete event                          | none needed                     | play, pause, step, seek landed, end of range       |
| CMP-170 · gap stop, expiry, error | assertive (`alert`)    | once per event                                   | none                            | spec §7                                            |
| CMP-170 · transport notice        | polite / `alert` once  | once on entry; an ended session: none            | none                            | spec §5.3: viewing as polite, the hold `alert`     |
| CMP-171 · achieved rate           | polite                 | once on entering and once on leaving the warning | two 1 s windows, 3 s to recover | spec D-8                                           |

### Density

| Mode        | Row / control height                                | Padding tokens                                | Smallest target                   |
| ----------- | --------------------------------------------------- | --------------------------------------------- | --------------------------------- |
| compact     | controls 24, track row 40, options 24               | `space.inset.sm`, `space.stack.xs`, `space.1` | 24 × 24 (thumb, markers, buttons) |
| comfortable | controls 32 (40 hit band), track row 48, options 32 | `space.inset.md`, `space.stack.sm`, `space.2` | 32 × 40                           |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Design QA checklist (`16` §12) — SCR-097

- [x] Tokens: published semantic tokens only (spec §11); `color.replay.border` is E11-D02's proposed token, named as such
- [ ] Themes and densities: dark, light and high contrast at both densities — PENDING (BLOCKED-PENPOT): the boards' later PR (high contrast by table)
- [x] Contrast matrix for every pair introduced (spec §12.2)
- [ ] CVD renders — PENDING (BLOCKED-PENPOT): the boards' later PR (`docs/design/_tools/cvd_sim.py` on the exports)
- [ ] Every state has a variant and a story — PENDING (BLOCKED-PENPOT): the boards' later PR, E26-D05 and E26-S02 (states: spec §7)
- [x] Disabled with a reason (T2), never hidden: CMP-079 with the CMP-019 `lock`, `aria-disabled`, 2a or 2b per control, every reason keyed (spec §5.3, D-26); busy is `aria-busy`, not T2; loading, empty, error and not-replayed designed
- [x] Keyboard and name/role tables (tables 2, 3); canvas alternatives stay the panels' own; the track is DOM
- [x] Motion: none here (E26-D06); targets 24 compact and a 40 comfortable band (spec §11)
- [ ] Accessibility sign-off — PENDING: E26-D06 review and the owner
- [x] Trading safety: on `/replay` the ticket binds only to the paper account and its panels show only `is_paper` rows (D-11); the environment is unambiguous wherever an order can be placed (D-4, D-10); no estimated value introduced
- [x] Reuse: CMP-001, 002, 003, 016, 019 (`lock`), 026, 028, 035, 043, 044, 079 and the three replay components; no near-duplicate

## Accessibility acceptance criteria (`05` §10) — SCR-097

```gherkin
Feature: SCR-097 replay page — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    When the user steps back through a trade, scrubs to a gap, skips it and leaves replay without a pointer
    Then every control is reachable by Tab and the arrows (spec §12.1), dragging has its key and typed-time paths
    And no data update moves the focus, and a focus ring of at least 3:1 shows at every step

  Scenario: Screen-reader operation (NVDA)
    When the user plays, pauses, steps and seeks
    Then the clock is a named timer that does not speak each second
    And play, pause, a step, a landed seek and the end of range are announced once; a gap stop, the expiry and an
      error once, assertively; the position reads as an absolute time with its date and coverage class

  Scenario: Colour-independence
    Then replay is told by the word, the date, the frame width, the dimmed future and the glyph, coverage by full,
      half-height and hatched marks and by text, and the frames pass the three colour-vision renders

  Scenario: Contrast, reduced motion and the automated gates
    Then chrome text meets 4.5:1 and indicators 3:1 in dark and high contrast (spec §12.2)
    And every chrome change stays a one-frame change under prefers-reduced-motion (E26-D06 confirms)
    And axe-core reports no serious or critical violation and the keyboard-only E2E passes (E26-Q02)
```

Screen readers: NVDA by E26-D06 and E26-Q05; no exception is claimed.

## Notes for E26-D07 (the replay handoff pack)

- **State-to-contract map:** spec §7 (each state → B12 / `replay_state`, the signal, the copy, the actions, the
  announcement) and spec §5.1 (each control → its `22` action, payload and B12 event); board 21 draws both, with spec
  §5.3's legs. The client
  conditions are seeking, stepping's held controls, the gap stop until CC-1, the speed-limited readout and disconnected.
- **Copy deck:** every string of SCR-097 is in spec §5.3 (the T2 reasons and their keys), §5.2 (speed), §6.1 (classes
  and cause words), §6.3 (seeking), §7 and §7.1 (states, errors), D-15 (not replayed), D-17 (leave confirm) and D-20
  (expiry). None carries a path, dataset id, session id or account id; the server's `error` token is never shown (D-23;
  D07 Security notes).
- **Load-bearing (return to design before changing):** D-2 (frame and chip on every panel, the date on every chip),
  D-3, D-4, D-9, D-10, D-11, D-12 (the coverage carriers), D-16, D-19 (the 1 Hz clock), D-21, D-22 (the stepping hold).
- **Performance constraints:** the 1 Hz clock text and the fixed 27-character timestamp (D-5, D-19); one seek per release
  and coalesced back-steps (D-16); the thumb moved by transform; motion suppressed above a stated speed (E26-D06, D01 Q8).
- **Analytics:** spec §13 (`replay.started`, `replay.seek`, `replay.paper_fill`).
- **Before E26-S02 is Ready:** the owner's OQ-1 to OQ-10 and OQ-12; CC-1 to CC-21 (their owners) and D01's open
  G-list; the contradictions X-1 to X-12 routed; E26-D05's entries for CMP-170 and CMP-171; D01 C3 for any panel
  that renders a row's `environment`.
- **Design-QA checklist for E26-D08** (from the SCR-097 sign-off checklist):
  1. Transport: the five glyphs, the step unit, the seven presets and custom, `Go to`; each gated control's T2 form
     and key (spec §5.3) appear with its state, and busy shows `aria-busy`.
  2. Chrome: every replaying panel has the 4 px frame and the chip with the date; the header carries the date to the
     millisecond; a single-panel crop in greyscale is still identifiable (spec §14.3).
  3. Every order-flow panel works under replay; not-replayed panels say so and never show live data (spec §9).
  4. Simulated: the five carriers on board 10; the private panels show only `is_paper` rows (D-11); no account id, UID
     or balance anywhere on `/replay`.
  5. History bounds: "Recorded from" at the track's history start; the five coverage classes by full, half-height and
     hatched marks and by text; the hatch means no data on the track and on the chart alike.
  6. Preparation and seeking: the three rungs and the cancel at the times of spec §6.3; panels change together.
  7. Speed limits: the achieved-rate readout appears and recovers per D-8; paper fills off above 25× per D-9.
  8. The gap callout naming what is missing, with the exact range and both actions; the skipped notice under `skip`.
  9. End of range, expiry with resume, error and disconnected as spec §7 draws them.
  10. The keyboard layer of spec §10 in each region; `Esc` cancels a seek only from the transport or the thumb.
  11. Viewing as, the hold and an ended session: one notice on the transport, every gated control pointing at it
      (boards 22, 23 and 12); at expiry the whole transport is T2 and the notice has no live role, so the closed
      state's alert is the one announcement.
