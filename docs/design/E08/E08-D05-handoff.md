# E08-D05 — Component handoff (`16` §11.4), a11y template (`05` §10) and design QA (`16` §12)

Ticket E08-D05 (#126); spec `docs/design/E08/E08-D05.md`. Six component contracts change (spec §13): one `16`
§11.4 block each for CMP-213, CMP-219 and CMP-026, and one for the input, menu and `⋯` (CMP-048 / CMP-160,
CMP-041, CMP-002). Every T2 control on these surfaces (spec §6.2, §6.3, §9.1) uses CMP-079 RbacGate and CMP-019
Icon `lock` unchanged (E09-D09 §2.2). Tables 4, 5, Density and Essential exceptions share one shape, so they are given
once, with a component column (§ "Shared tables"). **Status:** text pass and boards drawn; the Penpot and PNG lines are closed
(page `E08-D05 Symbol search & quick-switcher` · id `30d9b30e-268f-80df-8008-d47e99ea26c2`, B01–B27); the FE ticket, not yet
named (spec Q8), writes the stories. Penpot token sets = `packages/ui/tokens` at `1e495858930b5a88509e1912d86b203f74a27cab`.

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3). `[ ] PENDING` marks a line the boards step closes.

## Handoff checklist — CMP-213 FuzzyList (E08-D05, #126)

- [x] **Final Penpot link** — page `E08-D05 Symbol search & quick-switcher` · id `30d9b30e-268f-80df-8008-d47e99ea26c2`, board B01 (the shared DS library file is not touched, `docs/design/README.md`); PNG `docs/design/E08/img/cmp-213-row-variants-states.png`
- [x] **Variants × States matrix** — table 1; the Penpot variants are drawn on B01; the FE ticket writes the stories
- [x] **Keyboard table** — table 2; the keys are the host combobox's (CMP-048), checked against `keymap.json` and `reserved-keys.json` (spec §8): no global override, no unmodified trading key, `Esc` / `Ctrl+K` untouched; the host's root stops them, since the shipped dispatcher reports every binding
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: the count only; no streaming value in the list
- [x] **Motion pair** — N/A: nothing animates (spec §9.3); shared table 4
- [x] **Density notes** — shared density table: rows 24 / 32 px; no control inside a row (the `⋯` is the host's, spec §6.1)
- [x] **Essential-exceptions log** — none (shared table)
- [ ] **Tokens used** — the entry's Tokens field cites `color.text.accent`, which does not exist; patch A-D05-3 binds `font.weight.semibold`, `color.text.primary`, `color.text.secondary`, `color.surface.selected`, `color.border.selected` at `border.thick`, `color.surface.hover` (a light-value CR; in light, `color.surface.selected` until the CR lands), `color.data-confidence.delisted.*`
- [x] **Data contract confirmed** — items come from the local `GET /instruments` index and the recorder list (`GET /recording/symbols`, contract-only until E16-T08; spec §3, §16)
- [ ] **Contrast and CVD** — measured by `docs/design/_tools/e08_d05_search_audit.py` (exit 0, spec §9.5); the new pairs (`text.secondary` / `text.tertiary` on `surface.overlay` and `surface.selected`, `color.border.selected` vs `surface.selected`) are not yet in `tools/contrast/pairs.mjs`: the FE ticket adds them
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING: the owner's `approved` on #126 or the merge of the spec PR

### Table 1 — Variants × States

| Variant        | State                                   | Penpot variant | Story name                                        | Notes                                                   |
| -------------- | --------------------------------------- | -------------- | ------------------------------------------------- | ------------------------------------------------------- |
| ranked (typed) | rest, hover, active, highlighted ranges | B01 / ranked   | `Molecules/FuzzyList/Ranked` (new)                | matched characters semibold, the rest regular secondary |
| grouped (idle) | Recent then Favourites                  | B01 / grouped  | `Grouped` (catalogued)                            | group headers `role="group"`                            |
| delisted item  | `aria-disabled`, active                 | B01 / delisted | `DelistedItem` (new)                              | struck symbol, CMP-239 chip, no 24 h cells              |
| tags           | favourite ★, recent ↺                   | B01 / tags     | `WithTags` (new; A-6 or G-2 decides the slot API) | words in the option's name; no control in an option     |
| windowed       | > 32 rows, overscan 4                   | B01 note       | `LongList(virtualised)` (catalogued)              | `aria-posinset` / `aria-setsize`                        |
| loading        | skeleton rows, static                   | B01 / skeleton | `Loading` (new)                                   | `aria-busy` on the list                                 |
| empty          | via CMP-026                             | B03            | `NoResults` (catalogued)                          | copy from spec §6.2                                     |
| long symbol    | 24 characters (`22` `Symbol` maximum)   | B01 / long     | `LongSymbol` (new)                                | the symbol never truncates; base / quote does           |

### Table 2 — Keyboard

| Key                          | Action                                                          | Focus after                | Global conflict?                                    | Notes                                            |
| ---------------------------- | --------------------------------------------------------------- | -------------------------- | --------------------------------------------------- | ------------------------------------------------ |
| `↓` / `↑` (host)             | move the active option, no wrap                                 | stays in the host input    | none: widget keys, not in `keymap.json`             | the active option scrolls into view              |
| `PageDown` / `PageUp` (host) | one visible page                                                | stays in the input         | none (E13-D02 D3 proposal)                          | —                                                |
| `Enter` (host)               | activate the active option                                      | the host decides (spec §8) | none in an active context; the host's root stops it | an `aria-disabled` option is inert and announced |
| pointer click; right-click   | activate; right-click makes it active and opens the host's menu | the host decides           | —                                                   | the list is never a Tab stop                     |

### Table 3 — Accessible name / role

| Element | Role                           | Accessible name (source)                                | States / properties                                                                                                         |
| ------- | ------------------------------ | ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| list    | `listbox`                      | "Symbols" (host label)                                  | `aria-busy` while loading                                                                                                   |
| group   | `group`                        | its header ("Recent", "Favourites")                     | —                                                                                                                           |
| option  | `option` (text and chips only) | symbol, base / quote, recording state, tags (spec §9.1) | `aria-selected` (active), `aria-disabled` (delisted) + `aria-describedby` status sentence, `aria-posinset` / `aria-setsize` |

## Handoff checklist — CMP-219 SymbolPicker (E08-D05, #126)

- [x] **Final Penpot link** — page `E08-D05 Symbol search & quick-switcher` · id `30d9b30e-268f-80df-8008-d47e99ea26c2`, boards B02, B15–B23; PNGs `cmp-219-symbol-picker-states.png`, `scr-041-*.png`
- [x] **Variants × States matrix** — table 1
- [x] **Keyboard table** — table 2; checked against `keymap.json` and `reserved-keys.json`; the popover root stops every key but four Global chords, which close it first (spec §8)
- [x] **Accessible name / role table** — table 3; the catalogued combobox becomes a button that opens a dialog (A-D05-4)
- [x] **Live data** — shared table 5: nothing streams; the recording chip updates silently
- [x] **Motion pair** — N/A: the popover opens instantly (spec §9.3)
- [x] **Density notes** — shared density table: trigger, rows and radio items 24 / 32 px
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — the entry cites `font.mono` (the token is `font.family.mono`) and `radius.sm`; this spec binds `color.surface.overlay`, `elevation.popover`, `radius.card`, `color.action.selected`, `color.border.selected` at `border.thick`, `type.num.base` (patch A-D05-4)
- [x] **Data contract confirmed** — `GET /instruments` (index), `GET /instruments/{symbol}`, `GET /recording/symbols`, `GET /recording/status`, `GET /recording/storage` `level` (spec §3, §6.5); the three recorder reads are contract-only until E16-T08, so §3's "When absent" rows hold until then (spec §16)
- [ ] **Contrast and CVD** — measured (spec §9.5); the checked-interval pairs join `tools/contrast/pairs.mjs` with the FE ticket
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING: the owner's `approved` on #126 or the merge

### Table 1 — Variants × States

| Variant | State                                     | Penpot variant | Story name                                           | Notes                                |
| ------- | ----------------------------------------- | -------------- | ---------------------------------------------------- | ------------------------------------ |
| trigger | rest, focus, expanded                     | B02            | `Default` (catalogued)                               | its name carries symbol and interval |
| trigger | recording, not recorded, unknown          | B02            | `NotRecorded` (catalogued), `RecordingUnknown` (new) | unknown shows no chip                |
| trigger | delisted current value                    | B02, B19       | `Delisted` (catalogued)                              | struck, CMP-239                      |
| popover | idle with Recent, typing, preview         | B15, B16       | `WithRecents` (catalogued), `Typing` (new)           | the strip belongs to E12-D02's NC-10 |
| popover | no match, status rule, loading, failed    | B17, B22       | `States` (new)                                       | copy from spec §6.2                  |
| popover | not recorded: Owner action vs T2 sentence | B18            | `RecordingRoles` (new)                               | `rbac.owner_only`                    |
| popover | narrow, armed target                      | B20, B21       | `Narrow`, `ArmedTarget` (new)                        | the Q7 fallback is drawn too         |

### Table 2 — Keyboard

| Key                                                          | Action                                                | Focus after                                 | Global conflict?                                                                                              | Notes                        |
| ------------------------------------------------------------ | ----------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| `Enter` / `Space` on the trigger; `/` with the chart focused | open with the current symbol selected                 | the input                                   | `/` needs A-D05-2's rule; the trigger stops the `Enter` / `Space` it handles, else `Space` posts DOM's notice | a roving stop of CMP-221     |
| `Tab` / `Shift+Tab`                                          | input → interval group → More… → Record (Owner) → out | each control; leaving closes without commit | stopped at the root; native                                                                                   | no trap                      |
| `←` `→` `Home` `End`, `1`–`9` in the strip                   | check an interval                                     | the radio                                   | `chart.interval_preset`'s set, scoped to the strip; stopped at the root                                       | digits in the input are text |
| `Enter`                                                      | commit the symbol (and the interval from the strip)   | the invoker                                 | stopped at the root (Auth, Positions, Rules bind `Enter`)                                                     | shell announcement           |
| `Shift+Enter`                                                | open the active symbol in a new chart                 | the invoker                                 | stopped at the root                                                                                           | shell announcement           |
| `Esc`                                                        | close, restore symbol and interval                    | the invoker                                 | stopped at the root; universal cancel                                                                         | no subscription change       |

### Table 3 — Accessible name / role

| Element        | Role                               | Accessible name (source)              | States / properties                          |
| -------------- | ---------------------------------- | ------------------------------------- | -------------------------------------------- |
| trigger        | `button`, `aria-haspopup="dialog"` | "Symbol: BTCUSDT, 1 minute" (value)   | `aria-expanded`                              |
| popover        | `dialog` (not modal)               | "Change symbol and interval, Chart 1" | —                                            |
| interval strip | `radiogroup` / `radio`             | "Interval" / "15 minutes"             | `aria-checked`; the digit in the description |

## Handoff checklist — CMP-026 EmptyState (E08-D05, #126)

- [x] **Final Penpot link** — page `E08-D05 Symbol search & quick-switcher` · id `30d9b30e-268f-80df-8008-d47e99ea26c2`, board B03 (in context on B07–B10, B17, B22); PNG `cmp-026-search-empty-variants.png`
- [x] **Variants × States matrix** — table 1 (the existing `filtered-empty` and `error` variants, new copy and actions)
- [x] **Keyboard table** — table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: the `error` variant alerts once
- [x] **Motion pair** — N/A: nothing animates
- [x] **Density notes** — actions are CMP-001 / CMP-021 at their catalogued 24 / 32 px
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — the entry cites `space.emptystate.*`, which does not exist; bound to `space.inset.md` and `space.stack.sm` meanwhile (patch A-D05-5)
- [x] **Data contract confirmed** — copy maps by HTTP status, by `code` only when present (spec §6.2); a 503 on the list is loading, not `error`; `Problem.instance`, when present, is the reference; **Refresh from Bybit** needs `POST /instruments/refresh`, contract-only until E08-S01 (spec §16)
- [x] **Contrast and CVD** — the pairs are registered already (`text.primary`, `text.secondary` on surfaces; `text.on-action` on `action.primary.default`); the failure glyph is measured (spec §9.5)
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING

### Table 1 — Variants × States

| Variant          | State                                                                                                              | Penpot variant    | Story name                      | Notes                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------------------ | ----------------- | ------------------------------- | -------------------------------------------------------------- |
| `filtered-empty` | no matches: scope reminder + Clear search, Check again after a check (CMP-079 T2 `search.check_cooldown` for 60 s) | B03 / no-matches  | `FilteredEmptyNoMatch` (new)    | copy verbatim from spec §6.2                                   |
| `filtered-empty` | status rule: View symbol info + Clear search                                                                       | B03 / status-rule | `FilteredEmptyStatusRule` (new) | `status_reason` or the fallback                                |
| `error`          | load failed: Retry now + Refresh from Bybit (Owner) or T2                                                          | B03 / load-failed | `ErrorWithTwoActions` (new)     | the Ref line only with `instance`; over CMP-027 (spec A-D05-5) |

### Table 2 — Keyboard

| Key                 | Action                     | Focus after                           | Global conflict?                 | Notes                              |
| ------------------- | -------------------------- | ------------------------------------- | -------------------------------- | ---------------------------------- |
| `Tab` / `Shift+Tab` | reach the actions in order | each action                           | native; the host's root stops it | inside SCR-102's trap              |
| `Enter` / `Space`   | activate                   | per action (Clear search → the input) | the host's root stops them       | a T2 action is focusable and inert |

### Table 3 — Accessible name / role

| Element | Role                                            | Accessible name (source) | States / properties                             |
| ------- | ----------------------------------------------- | ------------------------ | ----------------------------------------------- |
| block   | `h3` heading + text; `role="alert"` for `error` | the heading text         | —                                               |
| actions | `button` / `link`                               | the visible label        | T2: `aria-disabled` + `aria-describedby` reason |

## Handoff checklist — CMP-048 Combobox / CMP-160 SymbolSearchInput (keyboard), CMP-041 Menu and CMP-002 IconButton (E08-D05, #126)

- [x] **Final Penpot link** — page `E08-D05 Symbol search & quick-switcher` · id `30d9b30e-268f-80df-8008-d47e99ea26c2`, boards B05, B06, B14, B23; PNGs `scr-102-typing-ranked.png`, `scr-102-row-actions.png`, `scr-102-keyboard-path.png`, `scr-041-keyboard-path.png`
- [x] **Variants × States matrix** — table 1
- [x] **Keyboard table** — table 2; each key checked against the 71 shipped commands and the 27 reserved keys; the dialog, popover and menu roots stop every key but `Ctrl+K`, `Ctrl+Shift+A`, `Ctrl+/` and `F11`, which close the surface first, since the shipped dispatcher reports every binding; A-D05-2 lets a function key, like a Ctrl or Alt chord, run in a field (spec §8)
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5
- [x] **Motion pair** — N/A for the input; the SCR-102 dialog's fade is Table 4's CMP-043 row
- [x] **Density notes** — input 24 / 32 px (`size.control.height`); the `⋯` (CMP-002) 24 / 32 px in a one-row bar, not the catalogued 44 px comfortable (A-D05-15)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — CMP-048 cites `elevation.2`; SCR-102 binds `elevation.dialog`, `color.surface.app` (the well) and the boundary CR `color.border.input` (E30-D02 CR-1; patch A-D05-6); CMP-041 keeps `elevation.3`, `color.surface.overlay`
- [x] **Data contract confirmed** — no request per keystroke; the symbol check is `GET /instruments/{symbol}` for the settled query (300 ms rest, one in flight, a list in memory), sent only when it matches `22` `Symbol` and the shipped 4–20 rule (spec §6.2); **Refresh from Bybit** is `POST /instruments/refresh`, contract-only until E08-S01, then the shipped `GET /admin/jobs/{job_id}` poll (spec §16)
- [ ] **Contrast and CVD** — the input pairs are measured (spec §9.5); `color.border.input` waits on E30-D02 CR-1
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — attached at the end
- [ ] **Sign-off** — PENDING

### Table 1 — Variants × States

| Variant            | State                                                      | Penpot variant | Story name                                         | Notes                                                                |
| ------------------ | ---------------------------------------------------------- | -------------- | -------------------------------------------------- | -------------------------------------------------------------------- |
| CMP-160 in SCR-102 | idle, typing, results, no results                          | B04, B05, B07  | `Default`, `WithRecents`, `NoResults` (catalogued) | the target chip in the header                                        |
| CMP-160            | target chip, armed target                                  | B04, B21       | `WithTarget`, `ArmedTarget` (new)                  | the E30-D02 pill                                                     |
| CMP-160            | stale, refreshing, refresh failed, checking a symbol       | B11, B24       | `CatalogueStates` (new)                            | footer and detail bar                                                |
| CMP-041            | host-opened menu (Owner, Manager, Viewer; right-click too) | B06            | `HostOpened`, `DisabledWithReason` (new)           | `open?` + `anchor?` (A-D05-13); `disabledReason?` (E11-D03 D03-CR-1) |
| CMP-048            | async loading                                              | B09            | `AsyncLoading` (catalogued)                        | input enabled, query kept                                            |

### Table 2 — Keyboard

| Key                                  | Action                              | Focus after                | Global conflict?                                                                   | Notes                            |
| ------------------------------------ | ----------------------------------- | -------------------------- | ---------------------------------------------------------------------------------- | -------------------------------- |
| `↓` `↑`, `PageDown` `PageUp`         | move the active option              | input                      | none in `keymap.json`; stopped at the root                                         | no wrap                          |
| `←` `→` `Home` `End`                 | caret                               | input                      | stopped at the root (Replay binds `←` `→`); `Alt+→` never used                     | E13-D02 D3                       |
| `Enter` / `Shift+Enter`              | open in the target / in a new chart | the invoker                | stopped at the root (Auth, Positions, Rules bind `Enter`); `Ctrl+Enter` never used | shell sentence                   |
| `Shift+F10` / Menu                   | CMP-041 menu for the active option  | the first menu item        | not reserved; the chord of E11-D02's menus; stopped at the root                    | `Esc` returns to the input       |
| `↓` `↑` `Home` `End`, `Enter` (menu) | move between items; run one         | the item; the host decides | none (APG menu keys); stopped at the menu root                                     | a T2 item is reachable and inert |
| `Esc`                                | close and restore focus             | the invoker                | stopped at the root; universal cancel (`05` §3.3 rule 3)                           | nothing changes                  |

### Table 3 — Accessible name / role

| Element   | Role                             | Accessible name (source)                 | States / properties                                                                                   |
| --------- | -------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| input     | `combobox`                       | "Search symbols" (visually hidden label) | `aria-expanded`, `aria-controls`, `aria-activedescendant`, `aria-autocomplete="list"`, `maxlength=32` |
| key hints | text                             | the footer's CMP-022 glyphs              | the input's description                                                                               |
| `⋯`       | `button`, `aria-haspopup="menu"` | "Actions for ETHUSDT"                    | in the detail bar, outside the listbox                                                                |
| menu      | `menu` / `menuitem`              | "Actions for ETHUSDT" / the item         | T2: `aria-disabled` + `aria-describedby` reason                                                       |

## Shared tables (Tables 4, 5, Density and Essential exceptions for the four blocks)

| Table 4 — Motion pair: component                | Property                                                                            | motion-safe                 | motion-reduce | Tokens                                           |
| ----------------------------------------------- | ----------------------------------------------------------------------------------- | --------------------------- | ------------- | ------------------------------------------------ |
| CMP-213, CMP-219, CMP-026, CMP-048/160, CMP-041 | none animated: SCR-041's open and close, re-rank and skeleton are instant or static | —                           | same          | none (no `motion.shimmer` exists)                |
| CMP-043 (the SCR-102 dialog)                    | open and close: opacity                                                             | `motion.duration.fast` fade | instant       | `motion.duration.fast`, `motion.easing.standard` |

| Table 5 — Live data: component | Field                              | Politeness                        | Cadence                    | Coalescing                               |
| ------------------------------ | ---------------------------------- | --------------------------------- | -------------------------- | ---------------------------------------- |
| CMP-048/160 (for CMP-213)      | count and status lines (spec §9.2) | polite, one region empty at mount | after a 300 ms typing rest | latest only                              |
| CMP-026                        | `error` heading                    | assertive (`role="alert"`)        | once per failure           | retries do not repeat it                 |
| CMP-219                        | recording chip, preview values     | none                              | on change / on rest        | latest only; the shell speaks the commit |

| Density: component | Mode        | Row / control height                             | Padding tokens   | Smallest target                 |
| ------------------ | ----------- | ------------------------------------------------ | ---------------- | ------------------------------- |
| all four           | compact     | 24 px (`size.row.height`, `size.control.height`) | `space.inset.sm` | 24 × 24 px (`⋯`, radio, action) |
| all four           | comfortable | 32 px                                            | `space.inset.md` | 32 × 32 px (A-D05-15)           |

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
    And typing "btc/usdt", arrows, Enter, Esc and Tab in either field leave the toast host empty
    And so do Del, Ctrl+A, Ctrl+Z, Ctrl+Y, Ctrl+Left/Right and Shift+Left/Right
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

- [x] Published Tier-2 / Tier-3 tokens only — yes in the spec; the missing names are change requests,
      none invented (spec §13); the boards' read-back: no stale token (`refresh-stale`, count mode: 0 on 3,564 shapes).
- [x] Three themes × two densities — measured for contrast; drawn on the boards (B25, B26).
- [x] Contrast matrix for every pair introduced — the audit script, exit 0.
- [x] CVD simulation reviewed — section C of the script; the light collapses are carried by words.
- [x] A Penpot variant and a story per state — the variants are drawn (table 1 of each block names the board); stories named above.
- [x] Disabled-with-reason (CMP-079 RbacGate, CMP-019 Icon `lock`) for role- and state-gated controls — T2 items and buttons (spec §6.3) and the cooldown's Check again (spec §6.2, `search.check_cooldown`).
- [x] Loading, empty and error designed — the catalogue states with their own copy (spec §6.2).
- [x] Keyboard table matches a keyboard path — spec §8; the test is the FE ticket's.
- [x] Accessible name / role table — spec §9.1 and the tables 3 above.
- [x] Canvas strategy — N/A: no canvas here. Motion pair — SCR-102's fade, instant under reduce (table 4).
- [x] Hit targets ≥ 24 px compact — yes; no essential exception.
- [ ] Accessibility sign-off — PENDING: the owner's approval (agent-delivery adaptations).
- [x] Order placement, positions, arming — search places no orders; an armed target is shown (spec D-10).
- [x] Estimated values chip-tagged — N/A: none here. Demo / Live unambiguous — the env band stays (D-11).
- [x] Reuses existing CMP-\* — yes (load failed is CMP-026 `error`, spec A-D05-5); CMP-213's slot change waits on A-6 / G-2.
- [ ] Stories match the matrix — PENDING the FE ticket. Published library components only — yes: no component instance on the boards.
