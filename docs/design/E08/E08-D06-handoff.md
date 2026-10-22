# E08-D06 — Component handoff (`16` §11.4), a11y template (`05` §10) and design QA (`16` §12)

Ticket E08-D06 (#174); spec `docs/design/E08/E08-D06.md`. Five component contracts change (spec §16.4, A-2..A-6): one
`16` §11.4 block each for CMP-036, CMP-046, CMP-125, CMP-126 and CMP-177. Tables 4, 5, Density and Essential exceptions
share one shape, so they are given once with a component column. **Status:** text pass; Penpot and PNG lines are PENDING
until the boards step (page `E08-D06 SCR-103 Symbol info`, boards 1–24, spec §15); the FE ticket, not yet named (spec
Q8), writes the stories, a deviation recorded in spec §17.1. Penpot token sets = `packages/ui/tokens` at
`bf628c8c8b520309c6951e3a17b4c40329acb64d`.

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3). `[ ] PENDING` marks a line the boards step closes.

## Handoff checklist — CMP-036 KeyValueRow (E08-D06, #174)

- [ ] **Final Penpot link** — PENDING: page `E08-D06 SCR-103 Symbol info`, boards 1, 9, 19 (the shared DS library file is not touched, `docs/design/README.md`); PNGs `scr-103-populated-recorded-owner-dark.png`, `scr-103-anatomy-dark.png`
- [x] **Variants × States matrix** — table 1; Penpot variants PENDING; the FE ticket writes the stories
- [ ] **Keyboard table** — N/A — not focusable: a `dt` / `dd` pair read in the browse order (`dl` navigation); binds no key
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: values are read on demand, never spoken; the band's state is spoken once by the drawer
- [ ] **Motion pair** — N/A — nothing animates (shared table 4)
- [x] **Density notes** — shared density table: rows 24 / 32 px
- [x] **Essential-exceptions log** — none (shared table)
- [ ] **Tokens used** — the entry cites `space.row.*`, which resolves (`space.row.height.compact` / `.comfortable` in `semantic-dark.tokens.json`, density aliases per `packages/ui/tokens/themes.json`), and `font.size.body/label`, which do not exist; patch A-2 binds `size.row.height` (the density-resolved alias `themes.json` names), `type.ui.body`, `type.num.base`, `type.ui.caption`, `color.text.primary` / `.secondary` / `.tertiary` and the `color.data-confidence.stale.*` set
- [x] **Data contract confirmed** — `InstrumentDetail` fields (spec §4.1), and `TickerUpdate` fields (`ticker.{symbol}`) with the `getTicker` bootstrap (§4.2, §11.2), as decimal strings (spec F1); confirmed against `22` / `23` as shipped; fields the server leaves empty are drawn as their §4.1 / §4.2 fallbacks: 24 h high and low (CR-11), risk-limit tiers (CR-4), no WS producer yet (H-7)
- [ ] **Contrast and CVD** — PENDING `cvd_sim.py` on the exports (boards step); computed (spec §13: values, labels, units on `surface.overlay` and `surface.sunken`); the pairs go into `tools/contrast/pairs.mjs` in PR #4085, `contrast:gate` green there
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING: the owner's `approved` on #174 or the merge of the spec PR

### Table 1 — Variants × States

| Variant                | State                                                                                  | Penpot variant | Story name                                   | Notes                                                                       |
| ---------------------- | -------------------------------------------------------------------------------------- | -------------- | -------------------------------------------- | --------------------------------------------------------------------------- |
| label, value, unit     | rest                                                                                   | B19 / row      | `Default` (catalogued)                       | one value per row (spec F8), right-aligned, tabular; unit in its own column |
| rule row               | rest, with a sentence and an example                                                   | B19 / rule-row | `WithRuleExample` (new)                      | second line `type.ui.caption`, `color.text.tertiary`                        |
| live row in a band     | live, stale T1, stale T2, disconnected                                                 | B3, B4         | `LiveFreshness` (catalogued, now band-level) | rows inherit the band's state; no per-row CMP-239                           |
| changed                | "Changed · was 0.01"                                                                   | B9             | `Changed` (new)                              | a static tag until the drawer closes                                        |
| unavailable, malformed | "not available yet", "—"                                                               | B1, B14        | `Unavailable` (new)                          | name "not available"                                                        |
| stacked                | label over value, under 400 px of width or for a value wider than its column (spec F8) | B18, B20       | `Stacked` (new)                              | no value is cut or scrolled sideways                                        |

### Table 3 — Accessible name / role

| Element | Role | Accessible name (source)                             | States / properties                                     |
| ------- | ---- | ---------------------------------------------------- | ------------------------------------------------------- |
| label   | `dt` | the label text                                       | —                                                       |
| value   | `dd` | one value and its unit as one text ("82,751.2 USDT") | the rule sentence and example inside it (contract rows) |

## Handoff checklist — CMP-046 Drawer (E08-D06, #174)

- [ ] **Final Penpot link** — PENDING: boards 1, 20, 21; PNGs `scr-103-context-min-viewport-dark.png`, `scr-103-keyboard-focus-order-dark.png`
- [x] **Variants × States matrix** — table 1
- [x] **Keyboard table** — table 2; checked against `05` §3.2 and `05` §3.3: no global override; the Accessibility bindings (`Ctrl+=`, `Ctrl+-`, `Ctrl+Shift+H`, `Ctrl+Shift+M`) and `?` run with the drawer open, every other Global `Ctrl` / `Alt` / F-key binding closes it first; `Esc` and `Ctrl+K` untouched; the root stops the keys it handles because the shipped dispatcher reports every binding (spec §10.1)
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: the drawer's one polite region
- [x] **Motion pair** — shared table 4: the slide, instant under reduced motion
- [x] **Density notes** — shared density table: header, rows and footer controls 24 / 32 px
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — the entry cites `elevation.3` (a primitive) and `motion.slide` (no such token); patch A-3 binds `elevation.dialog`, `color.surface.overlay`, `space.dialog.padding`, `motion.duration.normal`, `motion.easing.decelerate` / `.accelerate`, and the scrim `color.surface.sunken` at `opacity.scrim`; a width token is requested (Q7)
- [ ] **Data contract confirmed** — N/A — the shell carries no data; its content's contracts are spec §4
- [x] **Contrast and CVD** — `focus.ring` on `surface.overlay` 6.15 / 5.39 / 15.99 (spec §13); no colour-only state
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING

### Table 1 — Variants × States

| Variant             | State                          | Penpot variant | Story name                        | Notes                                                     |
| ------------------- | ------------------------------ | -------------- | --------------------------------- | --------------------------------------------------------- |
| modal, right        | opening, open, closing         | B1, B20        | `Modal`, `RightSide` (catalogued) | 480 px; below the TopBar and the SCR-152 slot (spec D-14) |
| full width          | viewport of 720 CSS px or less | B20            | `FullWidth` (new)                 | the 200 % zoom case                                       |
| opened at a section | `section: "coverage"`          | B21            | `OpenAtSection` (new)             | focus on that band's heading, scrolled into view          |
| pop-out window      | opener in a pop-out window     | — (text only)  | `PopOutHost` (new)                | scrim per window; one drawer per window (spec D-16)       |

### Table 2 — Keyboard

| Key                                             | Action                       | Focus after                                          | Global conflict?                    | Notes                          |
| ----------------------------------------------- | ---------------------------- | ---------------------------------------------------- | ----------------------------------- | ------------------------------ |
| `Tab` / `Shift+Tab`                             | move through the controls    | next control; wraps inside the drawer (trap)         | none; stopped at the root           | order in spec §10.1            |
| `Esc`                                           | close                        | the opener, or the opener of the surface that closed | universal cancel (`05` §3.3 rule 3) | releases the live subscription |
| `Enter` / `Space`                               | activate the focused control | stays, or the target of a navigation                 | stopped at the root                 | —                              |
| `Ctrl+=` `Ctrl+-` `Ctrl+Shift+H` `Ctrl+Shift+M` | run; the drawer stays open   | stays; the scroll position kept                      | none; the binding keeps its meaning | re-lays out in place (§10.1)   |
| `?` (`Shift+/`)                                 | opens the cheat sheet        | the sheet; on close, back to the drawer              | none; always available              | over the drawer (§10.1)        |
| any other Global `Ctrl`, `Alt`, F-key binding   | closes the drawer, then runs | its target                                           | the binding keeps its meaning       | as E08-D05 §8                  |

### Table 3 — Accessible name / role

| Element | Role                          | Accessible name (source)                                   | States / properties                  |
| ------- | ----------------------------- | ---------------------------------------------------------- | ------------------------------------ |
| drawer  | `dialog`, `aria-modal="true"` | "Symbol info: BTCUSDT" (title; the prefix visually hidden) | `aria-describedby` the identity line |
| close   | `button` (CMP-002)            | "Close symbol info"                                        | —                                    |
| bands   | `section` + `h3`              | the heading text                                           | `aria-busy` while a band loads       |

## Handoff checklist — CMP-125 SymbolInfoPopover (E08-D06, #174)

- [ ] **Final Penpot link** — PENDING: board 16; PNG `cmp-125-symbol-info-popover-states-dark.png`
- [x] **Variants × States matrix** — table 1
- [x] **Keyboard table** — table 2; the trigger stops the `Enter` / `Space` it handles; no hover-only opening
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: none spoken; the band marker is text
- [ ] **Motion pair** — N/A — opens and closes instantly (shared table 4)
- [x] **Density notes** — trigger and link 24 / 32 px
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — the entry inherits CMP-017; patch A-4 adds `color.surface.overlay`, `elevation.popover`, `radius.card`, the CMP-036 row tokens and CMP-239 for the live rows
- [ ] **Data contract confirmed** — A-4: `GET /api/v1/instruments/{symbol}` and `ticker.{symbol}` from the client's stores replace Bybit's `/v5/market/instruments-info`, pending the `15` patch
- [x] **Contrast and CVD** — the CMP-036 pairs (spec §13)
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING

### Table 1 — Variants × States

| Variant | State                                                     | Penpot variant    | Story name             | Notes                                 |
| ------- | --------------------------------------------------------- | ----------------- | ---------------------- | ------------------------------------- |
| summary | default: four rules, last and funding, the recording word | B16 / default     | `Default` (catalogued) | the same three band labels as SCR-103 |
| summary | stale (band marker on the live rows)                      | B16 / stale       | `Stale` (new)          | "Stale 7s"                            |
| summary | not trading (status heading, no live rows)                | B16 / not-trading | `NotTrading` (new)     | E11-D04 heading                       |
| summary | unavailable ("Contract rules not loaded")                 | B16 / unavailable | `Unavailable` (new)    | "Open full details" still offered     |

### Table 2 — Keyboard

| Key                         | Action                                   | Focus after                     | Global conflict?       | Notes                    |
| --------------------------- | ---------------------------------------- | ------------------------------- | ---------------------- | ------------------------ |
| `Enter` / `Space` (trigger) | open                                     | stays on the trigger            | stopped at the trigger | never on hover alone     |
| `Tab`                       | into "Open full details"; leaving closes | the link, then the next control | native                 | non-modal: no trap       |
| `Enter` (link)              | open SCR-103                             | SCR-103's title                 | —                      | the popover closes first |
| `Esc`                       | close                                    | the trigger                     | universal cancel       | —                        |

### Table 3 — Accessible name / role

| Element | Role                                         | Accessible name (source)        | States / properties |
| ------- | -------------------------------------------- | ------------------------------- | ------------------- |
| trigger | `button` (CMP-002), `aria-haspopup="dialog"` | "Symbol summary, BTCUSDT"       | `aria-expanded`     |
| popover | `dialog` without `aria-modal`                | "BTCUSDT summary"               | —                   |
| link    | `a` (CMP-021)                                | "Open full details for BTCUSDT" | —                   |

## Handoff checklist — CMP-126 FundingCountdown (E08-D06, #174)

- [ ] **Final Penpot link** — PENDING: board 15; PNG `cmp-126-funding-countdown-states-dark.png`
- [x] **Variants × States matrix** — table 1 (spec §7)
- [ ] **Keyboard table** — N/A — not focusable: text read in the browse order; binds no key
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: digits `aria-live="off"`; polite once at 5 min and 1 min
- [ ] **Motion pair** — N/A — a 1 Hz text swap, no animation (shared table 4)
- [x] **Density notes** — one row, 24 / 32 px; fixed-width `hh:mm:ss`, tabular figures
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — the entry cites `font.mono` and `color.text.buy/sell`, which do not exist; patch A-5 binds `type.num.base`, `color.text.primary` and, under 5 min, the `color.status.warning.strong` glyph
- [ ] **Data contract confirmed** — A-5: `next_funding_time_ms` and `funding_rate` from `ticker.{symbol}` (the app topic, `23` §14.8), not Bybit's `tickers.{symbol}`; `rate` as a decimal string; the clock-skew state from SCR-152 and `welcome.clock_skew_ms`; until H-7, the `getTicker` bootstrap's ISO `next_funding_time` as epoch ms (spec §11.2)
- [x] **Contrast and CVD** — the warning glyph on `surface.overlay` is 10.17 / 3.78 / 10.17 and carries words; `text.primary` pairs in spec §13
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING

### Table 1 — Variants × States

| Variant                             | State                                              | Penpot variant    | Story name                                        | Notes                                                                        |
| ----------------------------------- | -------------------------------------------------- | ----------------- | ------------------------------------------------- | ---------------------------------------------------------------------------- |
| rate sign: positive, negative, zero | ≥ 1 h, < 1 h                                       | B15 / sign        | `Positive`, `Negative` (catalogued), `Zero` (new) | the sign in text (CMP-020), never colour alone; where CMP-126 carries `rate` |
| rate at its cap                     | —                                                  | —                 | PENDING E24-D01 G5                                | `fundingCap` is not mapped                                                   |
| no `rate` (SCR-103)                 | ≥ 1 h, < 1 h                                       | B15 / normal      | `NoRate` (new)                                    | `next in 01:24:13 · 08:00 UTC`; the rate is its own row (spec §4.2)          |
| any                                 | < 5 min                                            | B15 / under-5-min | `UnderFiveMinutes` (replaces `UnderOneMinute`)    | glyph and words; no charge line in SCR-103                                   |
| any                                 | settlement restart; elapsed, waiting for an update | B15 / settlement  | `Settlement`, `Elapsed` (new)                     | never negative, never a frozen 00:00:00                                      |
| any                                 | clock skew on, or offset unknown                   | B15 / clock       | `ClockSkew` (new)                                 | the absolute UTC time; no seconds                                            |
| any                                 | next funding time unknown                          | B15 / unknown     | `Unknown` (new)                                   | "Next funding time not available"; no countdown (spec §7)                    |
| any                                 | stale or disconnected; not trading                 | B15 / band, B6    | `InBandState`, `Suppressed` (new)                 | counts on inside the band; suppressed with reason                            |

### Table 3 — Accessible name / role

| Element   | Role                    | Accessible name (source)                          | States / properties    |
| --------- | ----------------------- | ------------------------------------------------- | ---------------------- |
| countdown | text, `aria-live="off"` | "Next funding in 1 hour 24 minutes, at 08:00 UTC" | minutes, never seconds |

## Handoff checklist — CMP-177 RecorderStatusRow, summary variant (E08-D06, #174)

- [ ] **Final Penpot link** — PENDING: boards 1, 2, 12, 13, 17; PNG `cmp-177-recorder-status-row-summary-states-dark.png`
- [x] **Variants × States matrix** — table 1 (spec §4.3)
- [ ] **Keyboard table** — N/A — the summary row is text and binds no key; its link and button are CMP-021 and CMP-001, with their own keys
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: state changes spoken once by the drawer's region
- [ ] **Motion pair** — N/A — nothing animates (shared table 4)
- [x] **Density notes** — rows 24 / 32 px
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — the entry inherits CMP-023 for the admin row; patch A-6 binds the CMP-036 row tokens and `color.text.secondary` for the state word; no new token
- [x] **Data contract confirmed** — the E16-S02 store (`recorder` topic, `RecorderUpdate`, `23` §15.8; `GET /recording/symbols`, `RecordedSymbol`) and `GET /market/data-coverage` (`DataCoverage`, spec §4.3); `role_restricted` read as "restricted"; confirmed against `22` / `23` as shipped; what the server leaves empty or limits is drawn as its §4.3 fallback or label: first recorded time (CR-8), archive label (CR-12), not-trading coverage (CR-13), the 90-day window (#2216), no session rows yet (#2188) and the `recorder` topic's server (E16-T08, #492)
- [x] **Contrast and CVD** — words carry every state; glyphs are decorative (spec §13); the Recorder settings link misses high contrast's 7:1 on `surface.overlay` until spec H-8's token retune
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING

### Table 1 — Variants × States

| Variant           | State                                                                                                       | Penpot variant   | Story name                 | Notes                                   |
| ----------------- | ----------------------------------------------------------------------------------------------------------- | ---------------- | -------------------------- | --------------------------------------- |
| summary, Owner    | recording (5 reasons), lingering, starting, stopping, degraded, error                                       | B17 / owner      | `SummaryStates` (new)      | words per spec §4.3; final copy E16-D05 |
| summary, Owner    | not recorded, symbol cap, disk pressure, gated (its cause in words, spec §4.3)                              | B17 / owner-not  | `SummaryNotRecorded` (new) | "Record this symbol…" (Q6) and the link |
| summary, others   | the same states, gated as "may be gated" in a `role_restricted` set (spec §4.3); no internals; one sentence | B12, B13, B17    | `SummaryNonOwner` (new)    | "Recording is set up by the owner."     |
| summary, any role | restricted (absent from a `role_restricted` set)                                                            | B17 / restricted | `SummaryRestricted` (new)  | never "Not recorded"                    |

### Table 3 — Accessible name / role

| Element | Role                           | Accessible name (source)    | States / properties    |
| ------- | ------------------------------ | --------------------------- | ---------------------- |
| state   | `dd` text; glyph `aria-hidden` | "Recording, added manually" | —                      |
| link    | `a` (CMP-021), Owner only      | "Recorder settings"         | absent for others (T3) |

## Shared tables (Tables 4, 5, Density and Essential exceptions for the five blocks)

| Table 4 — Motion pair: component   | Property      | motion-safe                                  | motion-reduce | Tokens                                                               |
| ---------------------------------- | ------------- | -------------------------------------------- | ------------- | -------------------------------------------------------------------- |
| CMP-046                            | open, close   | slide from the right (`16` §7 drawer recipe) | instant       | `motion.duration.normal`, `motion.easing.decelerate` / `.accelerate` |
| CMP-036, CMP-125, CMP-126, CMP-177 | none animated | —                                            | same          | none (no `motion.shimmer` exists; skeleton rows are static)          |

| Table 5 — Live data: component | Field                                        | Politeness                         | Cadence                         | Coalescing  |
| ------------------------------ | -------------------------------------------- | ---------------------------------- | ------------------------------- | ----------- |
| CMP-036 (live rows)            | ticker values                                | none: read on demand               | text swap at the topic's 250 ms | latest only |
| CMP-046 (its region)           | band entry and exit, rules changed, failures | polite, one region, empty at mount | once per event, ≤ 1 line / 2 s  | latest wins |
| CMP-126                        | countdown                                    | `off`; polite at 5 min and 1 min   | ≤ 1 Hz visual                   | —           |
| CMP-177, CMP-125               | state word, band marker                      | none of their own                  | on change                       | latest only |

| Density: component | Mode        | Row / control height                                                                                                                               | Padding tokens                                  | Smallest target                   |
| ------------------ | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- | --------------------------------- |
| all five           | compact     | 24 px (`size.row.height`, `size.control.height`)                                                                                                   | `space.inset.sm`; drawer `space.dialog.padding` | 24 × 24 px (close, link, actions) |
| all five           | comfortable | 32 px (`size.row.comfortable`, `size.control.comfortable`; the density mode re-points `size.row.height` / `size.control.height` per `themes.json`) | `space.inset.md`                                | 32 × 32 px                        |

| Essential exceptions: component | Exception | Compensating control | Reviewer | Date |
| ------------------------------- | --------- | -------------------- | -------- | ---- |
| all five                        | none      | —                    | —        | —    |

## `05` §10 accessibility acceptance criteria (SCR-103)

```gherkin
Feature: SCR-103 symbol info drawer — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user opens the drawer from the search menu and presses Tab through it
    Then focus starts on the title, visits every control in the spec §10.1 order and stays inside the drawer
    And Esc closes it and returns focus to the opener
    And the `05` §3.2 Accessibility bindings and `?` work with the drawer open, which stays open (spec §10.1)
    And a live update, a recorder update or a rules change never moves focus
    And every focused control shows a ring of at least 3:1

  Scenario: Screen-reader operation
    Given NVDA on the Electron shell (spec §14.3, a script not yet run)
    When the user reads the drawer from the title down
    Then the dialog name, the three band headings and every fact as a term and definition with its unit are announced
    And a band's state change is spoken once, politely; the countdown is never spoken per second
    And a contract load failure alerts once
    And no canvas is involved, so no DOM mirror or table view is needed

  Scenario: Colour-independence
    Given the drawer shows recording, stale, not-trading, 24 h change and funding sign states
    When the state is rendered
    Then bands are told apart by headings, and each state by words, glyphs or a sign, never colour alone
    And the drawer passes deuteranopia/protanopia/tritanopia simulation review (PENDING `cvd_sim.py` on the exports)

  Scenario: Contrast
    Given the drawer is rendered in the dark, light and high-contrast themes
    Then text meets 4.5:1 and meaningful non-text elements 3:1, per the computed pairs (spec §13)

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override)
    When the drawer would slide in or out
    Then it opens and closes instantly, nothing flashes and no motion lasts over 5 s

  Scenario: Automated gates
    Given the consuming FE ticket's PR
    Then axe-core reports no serious or critical violation
    And the affected screen's Lighthouse Accessibility score remains >= 95
    And the keyboard-only E2E covers the path above
```

Screen reader: written, not run; the release-level pass (`05` §8) runs it. Exceptions: none.

## `16` §12 design QA checklist

- [ ] Published Tier-2 / Tier-3 tokens only — yes in the spec; the catalogue's missing names are patches, none invented
      (spec §16.4); PENDING the boards' read-back.
- [ ] Three themes × two densities — contrast computed (spec §13); PENDING on the boards (board 24 and the twins).
- [x] Contrast matrix for every pair introduced — spec §13; rows in PR #4085 (not H-8's link); script with the boards.
- [ ] CVD simulation reviewed — no state is carried by hue (spec §13); PENDING `cvd_sim.py` on the exports.
- [ ] A Penpot variant and a story per state — variants PENDING (boards); stories named above.
- [x] Disabled-with-reason for RBAC-gated actions — the SCR-140 link is a T3 navigation affordance (hidden, sentence
      form); "Record this symbol…" follows `recording:write` in E09-D09's T2 sentence form (CMP-026, `cta` omitted);
      nothing else is gated (spec §8).
- [x] Loading, empty and error designed — per dependency (spec §6).
- [x] Keyboard table matches a keyboard path — spec §10.1; the test is the FE ticket's.
- [x] Accessible name / role table — spec §10.2 and the tables 3 above.
- [x] Canvas strategy — N/A: no canvas here. Motion pair — the drawer's slide, instant under reduced motion.
- [x] Hit targets ≥ 24 px compact — yes; no essential exception.
- [ ] Accessibility sign-off — PENDING: the owner's approval (agent-delivery adaptation).
- [x] Order placement, positions, arming — the drawer places no orders; both actions open a new panel (spec D-15).
- [x] Estimated values chip-tagged — N/A: the funding rate reads "predicted" in words; no CMP-227 chip until E24-D01's
      C7 (spec §4.2). Demo / Live unambiguous — the env band stays live above the scrim (spec D-14); what differs per
      environment is the spec §6 "Demo / live" row (Q10).
- [x] Reuses existing CMP-\* — yes; no new component id.
- [ ] Stories match the matrix — PENDING the FE ticket. Published library components only — PENDING the boards.
