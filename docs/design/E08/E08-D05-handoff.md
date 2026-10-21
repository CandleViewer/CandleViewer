# E08-D05 — Component handoff (`16` §11.4), a11y template (`05` §10) and design QA (`16` §12)

Ticket E08-D05 (#126); spec `docs/design/E08/E08-D05.md`. Four component contracts change (spec §13): one
`16` §11.4 block each for CMP-213, CMP-219, CMP-026 and CMP-048 / CMP-160. Tables 4, 5, Density and
Essential exceptions are the same shape for all four, so they are given once, with a component column
(§ "Shared tables"). **Status:** text pass; Penpot and PNG lines are PENDING until the boards step (page
`E08-D05 Symbol search & quick-switcher`, B01–B27); the stories belong to the consuming FE ticket, not yet
named (spec Q8). Penpot token sets = `packages/ui/tokens` at `1e495858930b5a88509e1912d86b203f74a27cab`.

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3). `[ ] PENDING` marks a line the boards step closes.

## Handoff checklist — CMP-213 FuzzyList (E08-D05, #126)

- [ ] **Final Penpot link** — PENDING: page `E08-D05 Symbol search & quick-switcher`, board B01 (the shared DS library file is not touched, `docs/design/README.md`); PNG `docs/design/E08/img/cmp-213-row-variants-states.png`
- [x] **Variants × States matrix** — table 1; the Penpot variants are PENDING on B01; the FE ticket writes the stories
- [x] **Keyboard table** — table 2; the keys are the host combobox's (CMP-048), checked against `keymap.json` and `reserved-keys.json` (spec §8): no global override, no unmodified trading key, `Esc` / `Ctrl+K` untouched
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: the count only; no streaming value in the list
- [x] **Motion pair** — N/A: nothing animates (spec §9.3); shared table 4
- [x] **Density notes** — shared density table: rows 24 / 32 px; smallest target the 24 × 24 `⋯` button
- [x] **Essential-exceptions log** — none (shared table)
- [ ] **Tokens used** — the entry's Tokens field cites `color.text.accent`, which does not exist; patch A-D05-3 binds `font.weight.semibold`, `color.text.primary`, `color.text.secondary`, `color.surface.selected`, `color.border.selected`, `color.surface.hover`, `color.data-confidence.delisted.*`
- [x] **Data contract confirmed** — items come from the local `GET /instruments` index and the recorder list (spec §3)
- [ ] **Contrast and CVD** — measured by `docs/design/_tools/e08_d05_search_audit.py` (exit 0, spec §9.5); the new pairs (`text.secondary` / `text.tertiary` on `surface.overlay` and `surface.selected`, `border.selected` vs `surface.selected`) are not yet in `tools/contrast/pairs.mjs`: the FE ticket adds them
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING: the owner's `approved` on #126 or the merge of the spec PR

### Table 1 — Variants × States

| Variant           | State                                        | Penpot variant | Story name                                        | Notes                                                   |
| ----------------- | -------------------------------------------- | -------------- | ------------------------------------------------- | ------------------------------------------------------- |
| ranked (typed)    | rest, hover, active, highlighted ranges      | B01 / ranked   | `Molecules/FuzzyList/Ranked` (new)                | matched characters semibold, the rest regular secondary |
| grouped (idle)    | Recent then Favourites                       | B01 / grouped  | `Grouped` (catalogued)                            | group headers `role="group"`                            |
| delisted item     | `aria-disabled`, active                      | B01 / delisted | `DelistedItem` (new)                              | struck symbol, CMP-239 chip, no 24 h cells              |
| tags and trailing | favourite ★, recent ↺, `⋯` on the active row | B01 / tags     | `WithTags` (new; A-6 or G-2 decides the slot API) | words in the option's name                              |
| windowed          | > 32 rows, overscan 4                        | B01 note       | `LongList(virtualised)` (catalogued)              | `aria-posinset` / `aria-setsize`                        |
| loading           | skeleton rows, static                        | B01 / skeleton | `Loading` (new)                                   | `aria-busy` on the list                                 |
| empty             | via CMP-026                                  | B03            | `NoResults` (catalogued)                          | copy from spec §6.2                                     |
| long symbol       | 19 characters                                | B01 / long     | `LongSymbol` (new)                                | the symbol never truncates; base / quote does           |

### Table 2 — Keyboard

| Key                          | Action                              | Focus after                | Global conflict?                         | Notes                                            |
| ---------------------------- | ----------------------------------- | -------------------------- | ---------------------------------------- | ------------------------------------------------ |
| `↓` / `↑` (host)             | move the active option, no wrap     | stays in the host input    | none: widget keys, not in `keymap.json`  | the active option scrolls into view              |
| `PageDown` / `PageUp` (host) | one visible page                    | stays in the input         | none (E13-D02 D3 proposal)               | —                                                |
| `Enter` (host)               | activate the active option          | the host decides (spec §8) | none: other `Enter`s are never co-active | an `aria-disabled` option is inert and announced |
| pointer click                | activate; `⋯` opens the host's menu | the host decides           | —                                        | the list is never a Tab stop                     |

### Table 3 — Accessible name / role

| Element | Role      | Accessible name (source)                                | States / properties                                                                                                         |
| ------- | --------- | ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| list    | `listbox` | "Symbols" (host label)                                  | `aria-busy` while loading                                                                                                   |
| group   | `group`   | its header ("Recent", "Favourites")                     | —                                                                                                                           |
| option  | `option`  | symbol, base / quote, recording state, tags (spec §9.1) | `aria-selected` (active), `aria-disabled` (delisted) + `aria-describedby` status sentence, `aria-posinset` / `aria-setsize` |

## Handoff checklist — CMP-219 SymbolPicker (E08-D05, #126)

- [ ] **Final Penpot link** — PENDING: page `E08-D05 Symbol search & quick-switcher`, boards B02, B15–B23; PNGs `cmp-219-symbol-picker-states.png`, `scr-041-*.png`
- [x] **Variants × States matrix** — table 1
- [x] **Keyboard table** — table 2; checked against `keymap.json` and `reserved-keys.json` (spec §8)
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: nothing streams; the recording chip updates silently
- [x] **Motion pair** — N/A: the popover opens instantly (spec §9.3)
- [x] **Density notes** — shared density table: trigger, rows and radio items 24 / 32 px
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — the entry cites `font.mono` (the token is `font.family.mono`) and `radius.sm`; this spec binds `color.surface.overlay`, `elevation.popover`, `radius.card`, `color.action.selected`, `color.border.selected`, `type.num.base` (patch A-D05-4)
- [x] **Data contract confirmed** — `GET /instruments` (index), `GET /instruments/{symbol}`, `GET /recording/symbols`, `GET /recording/status` (spec §3)
- [ ] **Contrast and CVD** — measured (spec §9.5); the checked-interval pairs join `tools/contrast/pairs.mjs` with the FE ticket
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING: the owner's `approved` on #126 or the merge

### Table 1 — Variants × States

| Variant | State                                     | Penpot variant | Story name                                           | Notes                                |
| ------- | ----------------------------------------- | -------------- | ---------------------------------------------------- | ------------------------------------ |
| trigger | rest, focus, expanded                     | B02            | `Default` (catalogued)                               | its name carries symbol and interval |
| trigger | recording, not recorded, unknown          | B02            | `NotRecorded` (catalogued), `RecordingUnknown` (new) | unknown shows no chip                |
| trigger | delisted current value                    | B02, B19       | `Delisted` (catalogued)                              | struck, CMP-239                      |
| popover | idle with Recent, typing, preview         | B15, B16       | `WithRecents` (catalogued), `Typing` (new)           | the strip is CMP-220's               |
| popover | no match, status rule, loading, failed    | B17, B22       | `States` (new)                                       | copy from spec §6.2                  |
| popover | not recorded: Owner action vs T2 sentence | B18            | `RecordingRoles` (new)                               | `rbac.owner_only`                    |
| popover | narrow, armed target                      | B20, B21       | `Narrow`, `ArmedTarget` (new)                        | the Q7 fallback is drawn too         |

### Table 2 — Keyboard

| Key                                                          | Action                                                | Focus after                                 | Global conflict?                                   | Notes                        |
| ------------------------------------------------------------ | ----------------------------------------------------- | ------------------------------------------- | -------------------------------------------------- | ---------------------------- |
| `Enter` / `Space` on the trigger; `/` with the chart focused | open with the current symbol selected                 | the input                                   | `/` is free in both files (A-D05-2)                | a roving stop of CMP-221     |
| `Tab` / `Shift+Tab`                                          | input → interval group → More… → Record (Owner) → out | each control; leaving closes without commit | native                                             | no trap                      |
| `←` `→` `Home` `End`, `1`–`9` in the strip                   | check an interval                                     | the radio                                   | `chart.interval_preset`'s set, scoped to the strip | digits in the input are text |
| `Enter`                                                      | commit the symbol (and the interval from the strip)   | the invoker                                 | never co-active with other `Enter`s                | shell announcement           |
| `Esc`                                                        | close, restore symbol and interval                    | the invoker                                 | universal cancel                                   | no subscription change       |

### Table 3 — Accessible name / role

| Element        | Role                               | Accessible name (source)              | States / properties                          |
| -------------- | ---------------------------------- | ------------------------------------- | -------------------------------------------- |
| trigger        | `button`, `aria-haspopup="dialog"` | "Symbol: BTCUSDT, 1 minute" (value)   | `aria-expanded`                              |
| popover        | `dialog` (not modal)               | "Change symbol and interval, Chart 1" | —                                            |
| interval strip | `radiogroup` / `radio`             | "Interval" / "15 minutes"             | `aria-checked`; the digit in the description |

## Handoff checklist — CMP-026 EmptyState (E08-D05, #126)

- [ ] **Final Penpot link** — PENDING: board B03 (in context on B07–B10, B17, B22); PNG `cmp-026-search-empty-variants.png`
- [x] **Variants × States matrix** — table 1 (the existing `filtered-empty` and `error` variants, new copy and actions)
- [x] **Keyboard table** — table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: the `error` variant alerts once
- [x] **Motion pair** — N/A: nothing animates
- [x] **Density notes** — actions are CMP-001 / CMP-021 at their catalogued 24 / 32 px
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — the entry cites `space.emptystate.*`, which does not exist; bound to `space.inset.md` and `space.stack.sm` meanwhile (patch A-D05-5)
- [x] **Data contract confirmed** — 503, 429 and network failures map to fixed copy (spec §6.2); `Problem.instance` is the reference
- [x] **Contrast and CVD** — the pairs are registered already (`text.primary`, `text.secondary` on surfaces; `text.on-action` on `action.primary.default`); the failure glyph is measured (spec §9.5)
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING

### Table 1 — Variants × States

| Variant          | State                                                     | Penpot variant    | Story name                      | Notes                           |
| ---------------- | --------------------------------------------------------- | ----------------- | ------------------------------- | ------------------------------- |
| `filtered-empty` | no matches: scope reminder + Clear search                 | B03 / no-matches  | `FilteredEmptyNoMatch` (new)    | copy verbatim from spec §6.2    |
| `filtered-empty` | status rule: View symbol info + Clear search              | B03 / status-rule | `FilteredEmptyStatusRule` (new) | `status_reason` or the fallback |
| `error`          | load failed: Retry now + Refresh from Bybit (Owner) or T2 | B03 / load-failed | `ErrorWithTwoActions` (new)     | the reference id is selectable  |

### Table 2 — Keyboard

| Key                 | Action                     | Focus after                           | Global conflict? | Notes                              |
| ------------------- | -------------------------- | ------------------------------------- | ---------------- | ---------------------------------- |
| `Tab` / `Shift+Tab` | reach the actions in order | each action                           | native           | inside SCR-102's trap              |
| `Enter` / `Space`   | activate                   | per action (Clear search → the input) | none             | a T2 action is focusable and inert |

### Table 3 — Accessible name / role

| Element | Role                                            | Accessible name (source) | States / properties                             |
| ------- | ----------------------------------------------- | ------------------------ | ----------------------------------------------- |
| block   | `h3` heading + text; `role="alert"` for `error` | the heading text         | —                                               |
| actions | `button` / `link`                               | the visible label        | T2: `aria-disabled` + `aria-describedby` reason |

## Handoff checklist — CMP-048 Combobox / CMP-160 SymbolSearchInput (keyboard; E08-D05, #126)

- [ ] **Final Penpot link** — PENDING: boards B05, B06, B14, B23; PNGs `scr-102-typing-ranked.png`, `scr-102-row-actions.png`, `scr-102-keyboard-path.png`
- [x] **Variants × States matrix** — table 1
- [x] **Keyboard table** — table 2; each key checked against the 71 shipped commands and the 27 reserved keys (spec §8)
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5
- [x] **Motion pair** — N/A: nothing animates
- [x] **Density notes** — input 24 / 32 px (`size.control.height`)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — CMP-048 cites `elevation.2`; SCR-102 binds `elevation.dialog`, `color.surface.app` (the well) and the boundary CR `color.border.input` (E30-D02 CR-1; patch A-D05-6)
- [x] **Data contract confirmed** — no request per keystroke; the symbol check is `GET /instruments/{symbol}` (spec §3)
- [ ] **Contrast and CVD** — the input pairs are measured (spec §9.5); `color.border.input` waits on E30-D02 CR-1
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING

### Table 1 — Variants × States

| Variant            | State                                     | Penpot variant | Story name                                         | Notes                         |
| ------------------ | ----------------------------------------- | -------------- | -------------------------------------------------- | ----------------------------- |
| CMP-160 in SCR-102 | idle, typing, results, no results         | B04, B05, B07  | `Default`, `WithRecents`, `NoResults` (catalogued) | the target chip in the header |
| CMP-160            | target chip, armed target                 | B04, B21       | `WithTarget`, `ArmedTarget` (new)                  | the E30-D02 pill              |
| CMP-160            | stale, refreshing, checking a symbol      | B11, B24       | `CatalogueStates` (new)                            | footer and detail bar         |
| CMP-160            | action menu open (Owner, Manager, Viewer) | B06            | `ActionMenu` (new)                                 | T2 items                      |
| CMP-048            | async loading                             | B09            | `AsyncLoading` (catalogued)                        | input enabled, query kept     |

### Table 2 — Keyboard

| Key                          | Action                              | Focus after         | Global conflict?                                           | Notes                      |
| ---------------------------- | ----------------------------------- | ------------------- | ---------------------------------------------------------- | -------------------------- |
| `↓` `↑`, `PageDown` `PageUp` | move the active option              | input               | none (widget keys)                                         | no wrap                    |
| `←` `→` `Home` `End`         | caret                               | input               | `Alt+→` is reserved and never used                         | E13-D02 D3                 |
| `Enter` / `Shift+Enter`      | open in the target / in a new chart | the invoker         | never co-active; `Ctrl+Enter` (`ticket.submit`) never used | shell sentence             |
| `Shift+F10` / Menu           | CMP-041 menu for the active option  | the first menu item | not reserved; the chord of E11-D02's menus                 | `Esc` returns to the input |
| `Esc`                        | close and restore focus             | the invoker         | universal cancel (`05` §3.3 rule 3)                        | nothing changes            |

### Table 3 — Accessible name / role

| Element   | Role       | Accessible name (source)                 | States / properties                                                                                   |
| --------- | ---------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| input     | `combobox` | "Search symbols" (visually hidden label) | `aria-expanded`, `aria-controls`, `aria-activedescendant`, `aria-autocomplete="list"`, `maxlength=32` |
| key hints | text       | the footer's CMP-022 glyphs              | the input's description                                                                               |

## Shared tables (Tables 4, 5, Density and Essential exceptions for the four blocks)

| Table 4 — Motion pair: component       | Property                                                               | motion-safe | motion-reduce | Tokens                            |
| -------------------------------------- | ---------------------------------------------------------------------- | ----------- | ------------- | --------------------------------- |
| CMP-213, CMP-219, CMP-026, CMP-048/160 | none animated: open, close, re-rank and skeleton are instant or static | —           | same          | none (no `motion.shimmer` exists) |

| Table 5 — Live data: component | Field                              | Politeness                        | Cadence                    | Coalescing                               |
| ------------------------------ | ---------------------------------- | --------------------------------- | -------------------------- | ---------------------------------------- |
| CMP-048/160 (for CMP-213)      | count, loading, checking, no match | polite, one region empty at mount | after a 300 ms typing rest | latest only                              |
| CMP-026                        | `error` heading                    | assertive (`role="alert"`)        | once per failure           | retries do not repeat it                 |
| CMP-219                        | recording chip, preview values     | none                              | on change / on rest        | latest only; the shell speaks the commit |

| Density: component | Mode        | Row / control height                             | Padding tokens   | Smallest target                 |
| ------------------ | ----------- | ------------------------------------------------ | ---------------- | ------------------------------- |
| all four           | compact     | 24 px (`size.row.height`, `size.control.height`) | `space.inset.sm` | 24 × 24 px (`⋯`, radio, action) |
| all four           | comfortable | 32 px                                            | `space.inset.md` | 32 × 32 px                      |

| Essential exceptions: component | Exception | Compensating control | Reviewer | Date |
| ------------------------------- | --------- | -------------------- | -------- | ---- |
| all four                        | none      | —                    | —        | —    |

## `05` §10 accessibility acceptance criteria (SCR-102, SCR-041)

```gherkin
Feature: SCR-102 symbol search and SCR-041 quick-switcher — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user opens search with "/", types "eth", presses Down and Enter
    Then every control is reachable by Tab or arrows, the list being driven from the input
    And the action menu opens with Shift+F10 or the Menu key, never on hover alone
    And focus never moves on a catalogue refresh, a recorder update or a re-rank
    And the input ring, the active option's bar and every focused control meet 3:1

  Scenario: Screen-reader operation
    Given NVDA on the Electron shell (spec §9.6, a script not yet run)
    Then the dialog, the target line, the option name and the result count are announced
    And the count is polite, once after a 300 ms rest; a load failure alerts once; nothing streams

  Scenario: Colour-independence, contrast and reduced motion
    Then matched characters, the active option, recording, delisted and armed states carry weight, shape or words
    And the 34 gated pairs pass in dark, light and high contrast (text 4.5:1, non-text 3:1, HC text 7:1)
    And under prefers-reduced-motion nothing animates

  Scenario: Automated gates
    Given the consuming FE ticket's PR
    Then axe-core reports no serious or critical violation, the keyboard-only E2E covers the path above
    And Lighthouse stays at 95 or more
```

Screen reader: written, not run; the release-level pass (`05` §8) runs it. Exceptions: none.

## `16` §12 design QA checklist

- [ ] Published Tier-2 / Tier-3 tokens only — yes in the spec; seven missing names are change requests,
      none invented (spec §13); PENDING the boards' read-back.
- [ ] Three themes × two densities — measured for contrast; PENDING on the boards (B25, B26).
- [x] Contrast matrix for every pair introduced — the audit script, exit 0.
- [x] CVD simulation reviewed — section C of the script; the light collapses are carried by words.
- [ ] A Penpot variant and a story per state — variants PENDING (boards); stories named above.
- [x] Disabled-with-reason (CMP-079) for RBAC-gated actions — T2 items and buttons (spec §6.3).
- [x] Loading, empty and error designed — the catalogue states with their own copy (spec §6.2).
- [x] Keyboard table matches a keyboard path — spec §8; the test is the FE ticket's.
- [x] Accessible name / role table — spec §9.1 and the tables 3 above.
- [x] Canvas strategy — N/A: no canvas here. Motion pair — N/A: nothing animates.
- [x] Hit targets ≥ 24 px compact — yes; no essential exception.
- [ ] Accessibility sign-off — PENDING: the owner's approval (agent-delivery adaptations).
- [x] Order placement, positions, arming — search places no orders; an armed target is shown (spec D-10).
- [x] Estimated values chip-tagged — N/A: none here. Demo / Live unambiguous — the env band stays (D-11).
- [x] Reuses existing CMP-\* — yes; CMP-213's slot change waits on E13-D02's A-6 / G-2 choice.
- [ ] Stories match the matrix — PENDING the FE ticket. Published library components only — PENDING boards.
