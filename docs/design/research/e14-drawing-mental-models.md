# E14-D01 — UX research: drawing, magnet and object-management mental models

- **Ticket:** E14-D01 (#204) · **Status:** Draft, text pass; boards follow · **Owner approval pending** (Agent-delivery
  adaptations, owner decision 2026-09-25) · **Method:** heuristic evaluation and documentation review; **no sessions were run**
- **Scope:** SCR-037 drawing rail and properties popover, the drawings branch of SCR-036, the SCR-045 keyboard entry point;
  CMP-191, CMP-223; US-DRAW-001..009. Feeds E14-D02 wireframes (#247), then E14-D03 (#317), D04 (#318), D06 (#350), D07 (#351),
  D09 (#353), D10 (#354), the K01 spike (#356) and the S-stories. **Companion:**
  [`e14-d01-session-protocol.md`](e14-d01-session-protocol.md).
- **Out of scope (ticket, unchanged):** visual design, colour and tokens (hi-fi starts at E14-D03); indicator management (E13);
  chart-trading order lines (CMP-192, E31); the `/api/v1/drawings` persistence design.
- **Deviations to record in the PR:** (1) the three moderated sessions were not run: a documented deviation pending owner
  approval (DoD item 1; OQ-8). (2) The magnet harness is specified (protocol §6), not built: this PR is docs-only. (3) Stale
  ticket pointers: benchmark B8 is in `26` §13 with 200 drawings (not §14, 120); the screen-reader protocol is `05` §8 (§9 is
  the automated gates); no drawing generator exists on `main` (`packages/chart-engine/bench/fixtures/` holds bars, footprint and
  heatmap only), so Probe D uses a seeded 200-drawing set the protocol specifies. (4) Figma becomes Penpot.
- **In plain words.** Nothing here is observed: each finding is a heuristic prediction for the owner run to confirm or overturn.
  Act first on §1's Pri 0 rows; every open question carries a **recommended default** (§3, §14), so the owner approves by
  exception. Ids: **F** finding · **AD** adopted decision (pending confirmation) · **AM** amendment proposal · **OQ** open
  question · **H1–H10** Nielsen heuristics · **Pri 0–2** priority · bare numbers such as `14` or `26 §3.9` =
  `docs/plan/NN-*.md`; keys such as E14-S02 = ticket bodies in `docs/plan/backlog/E14.json`.

## Locked, not relitigated

Inputs, not questions: (1) no function depends on hover or drag alone (`05` §3.1 rule 6; the ticket's "Do NOT"); (2) anchors are
chart-space (time, price), never pixels (US-DRAW-002 NFR); (3) note and label text is plain text at every boundary (E14-S06;
E14-D04; `22` `DrawingGeometry`); (4) the position tool never places an order: send-to-ticket pre-fills an unarmed ticket, any
order it leads to carries a native stop-loss (C-2.6), and sizing and caps are enforced server-side (C-2.12; E14-S07); (5) RBAC
is server-side (C-12.4): a Viewer's drawing writes are refused whatever the rail shows
(`docs/security/threat-models/E14-drawings.md` DR38); (6) sync never crosses symbols (US-DRAW-009 NFR); (7) `Esc` is reserved,
not remappable (`05` §3.3 item 3).

## Acceptance-criteria trace (issue #204)

Status key as in E13-D01 and E30-D01: **done** = delivered as worded; **heuristic-only** = delivered by the adaptation, pending
the owner run; **open** = needs sessions or an owner decision; **deviation** = replaced by the adaptation, pending approval.

| Ticket AC or deliverable                                                                   | Where                                                                | Status                                |
| ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------- | ------------------------------------- |
| AC1: expected hotkey per participant per tool                                              | §2 table (participant columns "not yet observed"); protocol Probe A  | heuristic-only (sources) · open       |
| AC1: every divergence from SCR-037 adopted as an amendment or kept with a reason           | §2 verdict column; AM-1                                              | done                                  |
| AC2: mis-snap counts and correction time per mode                                          | protocol Probe B and the harness (protocol §6)                       | open                                  |
| AC2: default mode and snap radius in px, backed by observation                             | §3 Q1 (weak, 12 CSS px) with a pre-registered flip rule              | heuristic-only                        |
| AC3: mis-drag recovery recorded verbatim; a failed recovery becomes a ranked friction item | §4; F1 pre-registered as that item for E14-D02; AD-8                 | heuristic-only · open (verbatim)      |
| AC4: screen-reader path: completable unaided, where it broke, what was announced           | §6 step walk (predicted breaks); protocol §5                         | heuristic-only · open                 |
| AC5: contradictions filed as amendment proposals; no wireframe against them until decided  | §10 AM-1..AM-15 and the gate                                         | done                                  |
| Scope: probe sets A–E; five open questions; ranked friction list                           | protocol §4; §3; §1                                                  | done (protocol) · heuristic-only      |
| Scope: 8–12 adopted decisions, each testable                                               | §9 AD-1..AD-12                                                       | heuristic-only (pending confirmation) |
| Scope: verbatim quotes                                                                     | none exist; empty quote bank in protocol §7                          | open                                  |
| Security notes: paste and link expectations recorded                                       | §12; protocol Probe CI-4                                             | heuristic-only · open                 |
| Accessibility notes: keyboard-only SR session; what a mode change announces                | §6; protocol §5                                                      | heuristic-only · open                 |
| Performance notes: harness ≥58 fps; snap-feedback latency tolerance                        | §13; protocol §6                                                     | open                                  |
| Observability: annotated events reviewed, new events proposed                              | §11                                                                  | done                                  |
| DoD: 3 sessions, one keyboard-only with a screen reader                                    | protocol; OQ-8                                                       | deviation                             |
| DoD: findings presented, Architect review of engine implications, CDO sign-off             | §13 list; the owner's `approved` comment on #204 replaces both roles | open                                  |
| DoD: recordings redacted, retention noted                                                  | protocol §1 (rules; nothing recorded yet)                            | done (rules)                          |
| Penpot boards and PNGs (`docs/design/README.md` "Approval rule")                           | "Research boards" below                                              | open (boards pass follows the text)   |

## Research boards (Penpot)

Page **`E14-D01 Drawing UX research`** in the project's Penpot file; its link, page id and board ids are recorded here when the
boards are built. Greyscale research boards (neutral semantic tokens only, no hue): a low-fidelity research artefact, not visual
design. One frame per board, named `E14-D01 / 0n <slug>`, exported with `docs/design/_tools/penpot_export.py` to
`docs/design/E14/img/` and embedded here and in the PR body once it exists. Boards 03 to 06 double as probe stimulus.

| #   | Board and planned PNG                                                       | Illustrates                                                         |
| --- | --------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| 01  | `E14-D01 / 01 journey` · `E14-D01-01-journey.png`                           | pick → place → adjust → recover → curate → plan, P1 / P2 / SR lanes |
| 02  | `E14-D01 / 02 hotkeys-and-gestures` · `E14-D01-02-hotkeys-and-gestures.png` | §2 tables, collisions flagged                                       |
| 03  | `E14-D01 / 03 magnet-and-handles` · `E14-D01-03-magnet-and-handles.png`     | §3 Q1 and Q3: modes, pixel numbers, occlusion arithmetic            |
| 04  | `E14-D01 / 04 object-management` · `E14-D01-04-object-management.png`       | §4, §5, §3 Q4: recovery paths, bulk actions, the sync marker        |
| 05  | `E14-D01 / 05 position-tool` · `E14-D01-05-position-tool.png`               | §3 Q5: two drag orders step by step, read-out hierarchy, states     |
| 06  | `E14-D01 / 06 keyboard-sr-flow` · `E14-D01-06-keyboard-sr-flow.png`         | §6: the CMP-191 walk with focus and announcement per step           |
| 07  | `E14-D01 / 07 findings-decisions` · `E14-D01-07-findings-decisions.png`     | §1, §9, §10: friction list, decisions, amendments                   |

## Method note (Agent-delivery adaptation, owner decision 2026-09-25)

The ticket asks for three moderated 60-minute sessions (owner plus up to two account managers), half contextual inquiry and half
against a greyscale prototype of SCR-037, and a throwaway magnet harness. Delivery is a solo AI agent with one human owner; no
prototype exists (wireframes are E14-D02, which waits for this report) and no drawing code exists on `main`
(`packages/chart-engine/src/plugins/index.ts` is a placeholder; `git grep -i magnet` over `apps`, `packages` and `services`
finds nothing). Per the ticket's **Agent-delivery adaptations**, the sessions become (1) a **heuristic evaluation** of the
locked specs, (2) a **written session protocol** ready for the owner (the companion file) and (3) an **owner walkthrough
checklist** posted on #204. Heuristics: Nielsen's ten (https://www.nngroup.com/articles/ten-usability-heuristics/), cited
H1–H10; the trading rules of `05` (§3.1–§3.4 keyboard, §4 colour independence, §6.2 live regions, §7 motion); WCAG 2.2
(https://www.w3.org/TR/WCAG22/).

**Honest limits.** No participant, quote, timing, count or success rate exists here, and none is invented. One evaluator (NN/g
recommends three to five, https://www.nngroup.com/articles/how-to-conduct-a-heuristic-evaluation/); the object evaluated is
specs and tickets, not a running interface; no screen reader was run, so every announcement below is a proposal to test.
Competitor statements come only from the public pages linked in §8 (read 2026-10-21); what they do not state is "not stated".
The ticket's premise that the owner's habits are TradingView's is unverified: the repo's TradingView research lists no drawing
hotkey (`docs/research/01-tradingview-charting.md` §6.4). Every finding is `(heuristic)` with a confidence: **High** = stated in
a locked plan, threat-model, keymap or token file, or reproduced with the repo's own `scripts/keymap_lint.py`; **Med** = sound
reasoning from cited sources; **Low** = persona inference. **Pri 0** = can silently change a level or an order field the trader
acts on, or blocks the keyboard and screen-reader path (a P0 under `05` §8.2 item 5); **Pri 1** = slows or misleads the main
draw and edit path; **Pri 2** = clarity. The ticket's traceability bar (two observations or one strong owner directive) is unmet
for every AD: the only owner-level directive in play is "TradingView-grade charting UX + DeepCharts-grade order-flow visibility"
(`00-planning-brief.md` Product), so each AD is a recommendation pending confirmation, not a decision.

## 1. Ranked friction list (findings register; all `(heuristic)`)

Ranked by priority, then confidence; F1–F14 are user-facing friction, F15–F18 plan defects that would mislead E14-D02.

| #   | Pri | Finding                                                                                                                                                                                                                                                                              | H      | Confidence (basis)                                                                           | Feeds          |
| --- | --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ | -------------------------------------------------------------------------------------------- | -------------- |
| F1  | 0   | (heuristic) A mis-drag silently moves a level the trader may trade against: a plain drag pans, but a press within a drawing's pick tolerance moves it, the move reaches every pane of the symbol, nothing says what moved from where, and US-DRAW-008's undo covers a delete only    | H5, H9 | Med — mechanism High (`26` §3.9, §3.11; E14-T04; US-DRAW-001), frequency unknown             | §4, AD-8       |
| F2  | 0   | (heuristic) `Esc` cannot leave an armed tool with no anchors: `chart.cancel_drawing` is valid only "drawing in progress", while CMP-223's test and `05` §3.2 say `Esc` exits the tool                                                                                                | H3     | High — `apps/web/src/keymap/keymap.json`; `15` CMP-223 Tests; `05` §3.2                      | AD-3, AM-2     |
| F3  | 0   | (heuristic) The keyboard-draw flow breaks for the tool AC4 tests: after arming from the rail, focus is unspecified (the next `Enter` would re-toggle the rail button), and the horizontal line has one anchor (E14-S01), two `Enter`s (CMP-191) and "≥2 anchors" (SCR-037)           | H4, H1 | High — three texts disagree; Med on the exact behaviour                                      | §6, AD-9, AM-3 |
| F4  | 0   | (heuristic) SCR-037's keys cannot ship as written: `Alt+T` is the data-table escape hatch, `Alt+F` is footprint mode in the same context, `Alt+M` is ticket snap-to-mid; the lint reports two errors, three with the table registered                                                | H4     | High — lint run on `main` (§2)                                                               | §2, AD-1, AM-1 |
| F5  | 0   | (heuristic) Modifier-clicks are documented three ways for chart trading (`Alt+click` market in the keymap; `Ctrl+Click` market and `Shift+Click` limit in `13` §6 and `17` §7), and E14-T04 makes `Ctrl+click` drawing multi-select: an armed chart can read a selection as an order | H5     | High — the texts; Med on frequency                                                           | §2.2, AD-1     |
| F6  | 0   | (heuristic) A position-tool plan can exist without a stop: no text fixes the drag order or keeps send-to-ticket disabled in the intermediate state; the API stores three unlabelled points                                                                                           | H5     | High — US-DRAW-007; `22` `DrawingTool`; C-2.6                                                | §3 Q5, AD-11   |
| F7  | 1   | (heuristic) The magnet is specified three ways (binary toggle, off/weak/strong, a per-drawing checkbox drawn ticked) with no default mode; 12 px (E14-S02) vs the crosshair's 8 px (E11-S07); the API cannot store a per-drawing magnet                                              | H4, H2 | High — `11`, `14`, `15`, `22` `DrawingStyle`                                                 | §3 Q1, AD-4    |
| F8  | 1   | (heuristic) Strong snapping makes a level one tick beyond a high unplaceable; weak snapping moves it onto the high unless the snap shows before commit; the forming bar's high can still change after a snap                                                                         | H3, H5 | Med — `26` §3.10; E14-S02; TV1                                                               | AD-4, AD-5     |
| F9  | 1   | (heuristic) "≥24 px handles" is read four ways; a 24 px visible handle covers 2 footprint rows at the 12 px L0 cell, 2.4 at 10 px and 4 at the 6 px floor, and drawings are never decimated                                                                                          | H8     | High — arithmetic from `26` §3.6; `11` US-DRAW-001; E14-T04; WCAG 2.5.8                      | §3 Q3, AD-6    |
| F10 | 1   | (heuristic) An armed sticky tool is an invisible mode: a stray click or `Enter` creates a persisted drawing that syncs to every pane; CMP-223 has no keep-active prop although E14-S10 specifies one                                                                                 | H1, H5 | Med — E14-S10; `15` CMP-223; TV4; SC1                                                        | §3 Q2, AD-2    |
| F11 | 1   | (heuristic) No single-pointer path without dragging for move, resize, Fibonacci, channel or position tool, and no anchor price or time fields; the keyboard nudge is not a 2.5.7 alternative                                                                                         | H7     | High — WCAG 2.5.7 Understanding; `05` §3.4 item 8; `14` SCR-037 wireframe                    | §7, AD-7       |
| F12 | 1   | (heuristic) Arrow keys mean six things by mode (pan, bar, price level, tick nudge, replay step, rail); a stale selection turns navigation keys into silent level edits                                                                                                               | H4, H5 | High that the sources disagree (`05` §3.1 rule 7, §3.2; SCR-030; US-DRAW-001); Med on impact | §6, AD-9       |
| F13 | 1   | (heuristic) Bulk actions are half-ruled: E14-S10 gives delete-all a confirm with count and symbol and one undo, but no document rules delete-all versus locked drawings or hidden versus empty, and one undo above the 200-operation batch cap is unplanned                          | H1, H5 | High — `14` SCR-037; E14-S10; `22` `/drawings/batch`; TV14, NT1, SC1                         | §5, AD-12      |
| F14 | 1   | (heuristic) The sync default is ambiguous: US-DRAW-001 says "every BTCUSDT chart", US-DRAW-009 makes it conditional, and "local to that pane" has no data-model home                                                                                                                 | H1, H4 | High — `11`; `21` §3.8.3 (`layout_id` is the only scope); E14-S09                            | §3 Q4, AD-10   |
| F15 | 2   | (heuristic) Redo is `Ctrl+Y` (keymap, SCR-030) and `Ctrl+Shift+Z` (US-DRAW-008, E14-S08); delete is `Del` (keymap) and `Delete`/`Backspace` (`05` §3.2, E14-S01)                                                                                                                     | H4     | High — the texts                                                                             | §2, AM-12      |
| F16 | 2   | (heuristic) Draw-mode announcements are unspecified; the engine's bar summary (`26` §12) would bury the price being chosen                                                                                                                                                           | H1, H8 | Med — WCAG 4.1.3 Understanding ("too chatty")                                                | §6             |
| F17 | 2   | (heuristic) Event names drift across nine concepts and no sink is documented for `drawing.*` product events                                                                                                                                                                          | —      | High — E14 ticket bodies; `22` `/telemetry/frontend`                                         | §11            |
| F18 | 2   | (heuristic) Tool inventories differ (SCR-037's 19 tools, `26` §3.10, the API's 25 values); SCR-037 has no States line and its sign-off list omits the position tool and anchored VWAP                                                                                                | H4     | High — `14` SCR-037; `26` §3.10; `21` §3.8.3                                                 | AM-8           |

## 2. Tool selection and hotkeys (Probe A; AC1)

**2.1 Expected-hotkey table.** Participant cells stay "not yet observed" until Probe A runs. Collisions were reproduced on
`main` by adding keys to a copy of `keymap.json` and calling `scripts/keymap_lint.py`'s `lint_keymap`: SCR-037's set gives two
errors (`Alt+F`, `Alt+M`), three with the data table on `Alt+T`; the set below, with the table on `Alt+T` and footprint mode on
`Shift+F`, gives none. Rule (AD-1): **TradingView's letters where free; no drawing chord takes a registered, ticket or
accessibility binding, or sits one modifier from a trading chord** (`Ctrl+Shift+T` arm, keymap; `Ctrl+Shift+F` flatten all, `05`
§3.2), which rules out the `Alt+Shift` variants.

| Action          | SCR-037   | Registered and other plan uses                                                                                                      | TradingView library (LIB1)                         | NinjaTrader 8 (NT1) | P1 · P2 · SR     | Verdict (recommended default)                                                                                                   |
| --------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- | ------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Trendline       | `Alt+T`   | **collision:** data-table toggle, the screen-reader escape hatch (`05` §3.2; SCR-030; SCR-045) E11-D07 chose as "clear in all four" | `Alt+T`                                            | `F2`                | not yet observed | **Amend → `Alt+L`** (AM-1). A TradingView habit opens the table, visibly; `Alt+Shift+T` is one modifier from arm one-click      |
| Horizontal line | `Alt+H`   | free                                                                                                                                | `Alt+H` (TV5: places a line at the picked point)   | `F6`                | not yet observed | **Keep `Alt+H`.** Divergence kept: the key arms the tool and never places a line, so a stray press cannot create a synced level |
| Fibonacci       | `Alt+F`   | **collision:** `chart.footprint_mode`, same Chart context → lint error                                                              | `Alt+F`                                            | `F8`                | not yet observed | **Keep `Alt+F`** (TradingView); **amend SCR-030:** footprint mode moves to `Shift+F`, beside `F` (toggle footprint)             |
| Rectangle       | `Alt+R`   | free                                                                                                                                | `Alt+Shift+R` (`Alt+R` is Reset chart)             | `Ctrl+F12`          | not yet observed | **Keep `Alt+R`.** Divergence from TradingView kept: no conflict, one modifier fewer; the reset habit arms the tool, visibly     |
| Measure         | `Alt+M`   | **collision:** `ticket.snap_mid` (Ticket) → undeclared reuse                                                                        | hold `Shift` + click                               | `Ctrl+F3`           | not yet observed | **Amend → `Alt+D`** ("distance"): with focus left in the ticket, `Alt+M` would move a draft order's price to mid                |
| Magnet          | `Ctrl+M`  | free, unregistered                                                                                                                  | toolbar; hold `Ctrl` while moving a point flips it | Snap Mode menu      | not yet observed | **Keep `Ctrl+M`** = off ↔ last on-mode (AD-4); no momentary modifier, every modifier is taken (§2.2)                            |
| Cancel          | `Esc`     | registered only "drawing in progress"                                                                                               | not stated                                         | `Esc`, right click  | not yet observed | **Keep; widen the condition** (AM-2) for the `Esc` ladder (AD-3)                                                                |
| Delete          | `Del`     | `Del` registered; `05` §3.2 and E14-S01 add `Backspace`                                                                             | not stated                                         | `Delete`            | not yet observed | Keep `Del`; register `Backspace` as a second Chart command (a command carries one default binding)                              |
| Redo            | `Ctrl+Y`  | `Ctrl+Y` registered (SCR-030); US-DRAW-008 says `Ctrl+Shift+Z`                                                                      | `Ctrl+Y`                                           | not stated          | not yet observed | **Keep `Ctrl+Y`; amend US-DRAW-008** (AM-12)                                                                                    |
| Hide all        | rail only | —                                                                                                                                   | `Ctrl+Alt+H`                                       | not stated          | not yet observed | No default key (rail, tree, command palette); bindable in SCR-113                                                               |

Also: E06-D03 (merged, §8 item 10) records the `Alt+T` collision and that `05` §3.2 wins over SCR-037; yet `05` §3.2's own
`Alt+1..4` scheme shadows the Global `Alt+1..9` rail (four lint errors), as does the in-flight E11-D04 hint "Alt+2 then Enter"
(draft PR #3929), so both follow AD-1 (AM-1). SCR-037's line lacks the `**Interactions/hotkeys:**` marker the lint parses and
the lint maps no context to SCR-037, so no drawing key is machine-checked today. E11-D01 (draft PR #3828) reports that the
Electron shell keeps the default application menu, so a bare `Alt` may focus the menu bar: every `Alt` chord, shipped ones
included, is pressed in the Electron build on Windows 11 before E14-D03 draws it (owner checklist; E11-D07 #330 checks
screen-reader collisions).

**2.2 Gesture and modifier collisions** (input to E14-D02's collision audit):

| Gesture                     | Meaning today                                                           | Drawing use                 | Recommended precedence                                                                                                                                 |
| --------------------------- | ----------------------------------------------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| plain drag on the plot      | pan (`26` §3.11)                                                        | move or resize              | the press decides: within a drawing's pick tolerance it moves that drawing (past a small travel threshold, AD-8); elsewhere it pans                    |
| `Alt+click`                 | market order while chart trading is armed (keymap)                      | none                        | never a drawing modifier                                                                                                                               |
| `Ctrl+click`, `Shift+click` | market and limit order in `13` §6 and `17` §7; multi-select (E14-T04)   | multi-select                | while chart trading is armed no drawing gesture uses a modifier-click on the plot; multi-select moves to the tree until E31 reconciles the three texts |
| `Shift` while dragging      | angle constraint (`26` §3.10)                                           | angle constraint            | keep                                                                                                                                                   |
| `Space` + drag              | pan modifier (`26` §3.11)                                               | none                        | keep                                                                                                                                                   |
| double-click                | axis auto-fit (SCR-030); plot behaviour proposed by E11-D01 (in flight) | open the properties popover | a drawing within its pick tolerance wins                                                                                                               |

## 3. Recommendations on the five open questions

**Q1 — Default magnet mode and snap radius (→ E14-S02 #471; OQ-2).** One chart-level drawing magnet with CMP-223's three modes,
**default `weak`, radius 12 CSS px**, separate from the crosshair readout magnet (E11-S07: weak 8 px; E11-D01, in flight, keeps
them apart). `weak` snaps to the nearest OHLC value of the bar under the pointer or its neighbours within 12 px (E14-S02);
`strong` always snaps (E11-S07; TV1); `Ctrl+M` toggles off ↔ the last on-mode; keyboard placement and nudges never snap (AD-5);
the position tool's stop and target snap to the tick only (Sierra Chart's Reward/Risk tool has its own "No Auto Snap" option,
SC1). _Reasons:_ the SCR-037 mock draws the magnet on; `weak` keeps levels between OHLC values placeable (footprint rows, round
numbers, a stop beyond a high), which `strong` forbids (H3); 12 px is E14-S02's default and half the 24 px target; no vendor
page states a pixel radius (TV1; SC1 in percent; NT1; AT3), so the harness must measure it. _Trade-off:_ `weak` mis-snaps where
precision matters most (a level meant one tick above a swing high lands on the high); AD-5's pre-commit readout, exact keyboard
placement and AD-7's price field mitigate it. _Flip rule:_ two of three participants ending Probe B in `strong` or `off` make
that mode the default; more `weak` than `off` mis-snaps for two participants sends the harness to 8 px. Confidence Med.

**Q2 — Sticky tool or revert to the cursor (→ E14-S10 #432; OQ-3).** **Revert to the cursor after each committed drawing**
(E14-S10's default), with a visible, announced **"keep tool active"** toggle on the rail persisted with the chart preferences,
and a text chip on the chart naming an armed tool and its keep-active state. _Reasons:_ every documented product makes
stickiness a toggle and TradingView's off state reverts (TV3, NT1, SC1, AT2); Sierra Chart and TradingView document the "every
click draws" complaint (SC1, TV4); a stray drawing costs more here because it persists and appears on every pane of the symbol
(US-DRAW-001; E14-T02) (H5); an armed tool is invisible to a screen reader (CMP-223 A11y) (H1). _Trade-off:_ ten levels cost ten
arming keystrokes unless the toggle is on. _Flip rule:_ two of three participants keeping keep-active on to the end make sticky
the default. Confidence Med.

**Q3 — Handle size versus occlusion on dense footprint charts (→ E14-T04 #359, E14-D08 #352; OQ-9).** **Decouple the glyph from
the hit region:** every handle's pointer target is at least 24×24 CSS px (WCAG 2.5.8 measures the target, not the glyph); the
visible glyph is smaller than one L0 footprint row (12 px, `26` §3.6) and its look is E14-D03/D08's; handles show only on the
selected or keyboard-focused drawing; a handle wins where it overlaps its own line; AD-7's anchor fields are the 2.5.8
"equivalent" control. _Reasons:_ F9's arithmetic; `16` §3 rule 2 already allows "a larger click-tolerance zone than the visual
glyph (invisible padding)"; E14-T04's "≥24 px visual" handle occludes the cells, and its 10 px tolerance read as a radius is a
20 px target. _Trade-off:_ a small glyph is harder to find; a "larger handles" option and the selection emphasis carry it. _Flip
rule:_ two participants missing a visible handle at the 6 px floor raise the glyph floor, with the occlusion cost recorded.
Confidence High on the target rule, Med on findability.

**Q4 — Cross-chart level sync default (→ E14-S09 #548, with E15-D01 #205; OQ-4).** **On:** a new drawing appears on every pane
of the layout showing the symbol; a sync-off pane marks its drawings "this pane only" in text and icon, on the canvas and in the
tree; turning sync on offers an explicit copy (E14-S09). _Reasons:_ US-DRAW-001 (Must) promises "every BTCUSDT chart",
persistence is per user and symbol (`26` §3.10) and E14-T02 subscribes a pane to the whole symbol; a level on 1m missing from 4h
is a silent omission a trader can act on (H1); SCR-023's mock ticks "Drawings (same symbol only)". _Trade-off:_ sync makes slips
global (a delete is "removed from all panes"), so AD-8 is a condition of this default; no vendor states a default (TV22, TV24,
NT1, SC4); "local to that pane" has no scope in `21` §3.8.3 (`layout_id` only), hence AM-11; defaults for new sync groups stay
E15-D01's. _Flip rule:_ two participants expecting a level to stay on its pane flip the default to off with an explicit "share
to all panes". Confidence Med.

**Q5 — Position tool: drag order and primary read-out (→ E14-D06 #350, E14-S07 #546; OQ-5).** **Entry → stop → target**, and
**risk in USDT is the primary read-out** (first in reading order); size, R:R and reward show without hover (E14-D06) and name
the account (for a Manager, an assigned one: C-12.4) and environment the size came from. After two anchors the tool shows risk
and size, with R:R and reward as "— set a target"; send-to-ticket stays disabled with its reason until the stop is on the
protective side, the target exists and the cap holds (US-DRAW-007; E14-S07). _Reasons:_ risk-based sizing needs the stop
distance (US-PROF-002; `24` §9.3), so this order gives the safety-relevant numbers at the second anchor; the cap error is
expressed in risk, so the primary number is the one the error names (H9); no plan exists without a stop (C-2.6); two of three
documented products set the stop or the risk before the target (SC1 stop, entry, target; NT1 entry, maximum risk, typed ratio;
TradingView not stated, TV19); drawings carry no environment (`21` §3.8.3), so a demo-sized plan must say so before it pre-fills
a ticket (C-2.11); long, short, risk and reward are labelled in text, never by colour alone (`05` §4). _Trade-off:_ setup-first
traders read R:R first, but R:R says nothing about money at risk. _Flip rule:_ two of three participants naming R:R first make
it primary. Confidence Med.

## 4. Editing, undo and mis-drag recovery (Probe C; AC3)

**Mechanism (High, plan text).** A plain drag pans (`26` §3.11), but a press within a drawing's 10 px grab tolerance or on its
body moves it (`26` §3.9; E14-T04), and the move reaches every pane of the symbol (US-DRAW-001). US-DRAW-008's undo covers a
delete only; E14-T02 makes every mutation a reversible command and E14-S08 names the next one ("Undo: delete trendline"); the
depth is ≥50 per symbol (US-DRAW-008 NFR) or 100 (`26` §3.10).

**Pre-registered recovery paths (not observed).** First action `Ctrl+Z` (TradingView documents it for an accidental drawing
move, TV3), then redraw, then the object tree. Predicted failures: (a) which of two nearby lines moved, and from where, is not
shown (H9); (b) `Ctrl+Z` with focus in another panel does nothing, since undo is a Chart-context binding; (c) undo restores one
pane but not the others, an edge TradingView (TV23) and Sierra Chart (SC4) document; (d) `Esc` mid-drag does nothing (WCAG 2.5.2
asks for abort or undo). **Ranked friction item for E14-D02: F1** (Pri 0), resolved by AD-8: a move starts only past a small
travel threshold (Sierra Chart's "Minimum Pixels for Chart Drawing Adjustment", SC1); the drawing shows "64,000 → 64,120 · Undo"
during and after the move; `Esc` mid-drag restores it; one `Ctrl+Z` restores it in every synced pane. Undo restores every
property of every operation in E14-T02's command list, one entry per drag, nudge burst or bulk action. Note for E14-T02 (#400):
a deleted id stays unavailable until it is purged 90 days later (`22` `/drawings/batch`, `id_unavailable`), so an undo after the
server delete re-creates the drawing under a new id, and nothing in the UI may depend on id stability.

## 5. Accumulation and object management (Probe D)

Whether users curate or accumulate cannot be read from documents: competitors document tools (TradingView nested groups and hide
options, TV12, TV17; Sierra Chart type and "with alerts" filters, SC1; NinjaTrader and ATAS object lists, NT1, AT1), not usage.
Pre-registered prediction (Low): on a cluttered chart the first action is hide-all, not the tree; it flips if two of three
participants open the tree first. Recommendations: **hide-all is a per-pane view state**, not 200 persisted writes hiding the
set on every pane (`visible` is persisted, `21` §3.8.3), and the rail and tree say "200 drawings hidden" so a hidden set never
reads as an empty one (H1); **lock-all** is persisted protection, stated in text; **delete-all** sits apart from routine toggles
behind E14-S10's confirm (count, symbol, one undo), which also keeps locked drawings (TradingView asks, TV14; NinjaTrader and
Sierra Chart skip locked objects, NT1, SC1) and stays one undo step above the 200-operation batch cap (`22` `/drawings/batch`);
tree rows name type, anchor and label ("Horizontal line 64,120.5"), not "Trendline #3" (`14` SCR-036 mock; E14-S08); the
virtualised tree announces "item X of Y" (`aria-setsize`). Per-interval visibility (TV15, TV16; SC1) is a likely accumulation
driver; `drawings.interval_scope` exists unexposed and no story names it (OQ-10). Probe D uses 200 drawings (B8, SCR-037), not 120.

## 6. Keyboard-draw flow (CMP-191) and the screen-reader path (AC4)

CMP-191's flow (`15` CMP-191 A11y) walked for a horizontal line. Announcements are proposals to test: polite, in a pre-rendered
`role="status"` region (`05` §6.2), the long form on a session's first arm and the short form after.

| Step             | Spec (source)                                                           | Focus                         | Proposed announcement                                                                                                       | Where it breaks                                                                                                                                                              |
| ---------------- | ----------------------------------------------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0 Reach the rail | vertical `role="toolbar"`, roving tabindex (CMP-223)                    | Tab or region cycling         | native: "Horizontal line, toggle button, not pressed"                                                                       | no registered key moves focus chart ↔ rail (Pri 2)                                                                                                                           |
| 1 Arm            | `Enter` on the tool (CMP-191) or the hotkey (AD-1)                      | unspecified after rail arming | "Horizontal line tool on. Enter places it at the cursor. Escape cancels."                                                   | F3: if focus stays on the rail, `Enter` re-toggles the button                                                                                                                |
| 2 Start position | "current crosshair position"; CMP-190's `position` may be `null`        | chart keyboard surface (AD-9) | the start price (and time for multi-anchor tools)                                                                           | undefined when null; pointer and keys drive one crosshair (`26` §3.11)                                                                                                       |
| 3 Move           | arrows (CMP-191): ←/→ bar, ↑/↓ price level (SCR-030 A11y)               | chart                         | the price, plus "high" or "low" on one, at E06-D03 D5's cadence (`26` §12: ≤2 per second held, settled value within 250 ms) | the full cursor summary (time, close, delta, imbalance) is not the price being placed; at 10 ticks per `Shift+↑` (the nudge rule), 60 USDT on a 0.1 tick is 60 presses (F11) |
| 4 Commit         | one `Enter` (E14-S01) vs two (CMP-191) vs "≥2 anchors" (SCR-037)        | the new drawing's surrogate   | "Horizontal line at 64,210.5 created on all BTCUSDT panes. Selected."                                                       | F3; AM-3                                                                                                                                                                     |
| 5 After commit   | revert or keep (§3 Q2)                                                  | as step 4                     | "Tool off" or "Horizontal line tool still on"                                                                               | unspecified today (F10)                                                                                                                                                      |
| 6 Cancel         | `Esc` (`05` §3.2; CMP-223); keymap: "drawing in progress" only          | unchanged                     | "Cancelled, tool still on" → "Drawing tool off" → "Selection cleared"                                                       | F2                                                                                                                                                                           |
| 7 Undo           | `Ctrl+Z` "Undo drawing" (keymap); E14-S08 announces the operation       | unchanged                     | "Horizontal line creation undone"                                                                                           | between two `Enter`s it is undefined; it must drop only the pending point                                                                                                    |
| 8 Edit           | a focusable handle per control point; nudge 1 or 10 ticks (US-DRAW-001) | handle                        | the new price, coalesced                                                                                                    | F12: arrows on a stale selection edit silently                                                                                                                               |
| 9 Live chart     | auto-follow while live (`05` §7)                                        | —                             | "Auto-follow paused while placing"                                                                                          | a new bar can shift the viewport under a pending anchor (WCAG 2.2.2)                                                                                                         |

**The screen-reader path the protocol tests** (protocol §5): NVDA 2024.x with Chromium (`05` §8.1 row 3; no Electron build with
drawing exists), keyboard only, default verbosity (`05` §8.2 item 1), recording per step completed unaided, with a hint or not
completed, where it broke, the speech verbatim and the reading mode. The participant must be able to write drawings (an Owner or
a Manager: a Viewer has no `workspaces:write`, `services/api/candleviewer/auth/rbac_seed.json`), and P3, the persona most likely
to use a screen reader (`10` §4), is read-only, so the sheet records whether the participant habitually uses one. **Mode-change
announcement (recommended):** arming, disarming and the keep-active state are polite status messages (WCAG 4.1.3; `05` §6.2
keeps assertive for order and connection events), and a "Drawing" class in the Announcements panel (`05` §6.2) lets step
announcements be muted without losing commit, cancel and save-failure messages.

## 7. WCAG 2.2 AA applied, and the states E14-D02 must draw

| Criterion                       | What it demands of drawing                                                                                                         | Plan today                                                                                                                           | Recommendation                                                                     |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| 2.5.7 Dragging Movements        | a single-pointer path without dragging for every drag; keyboard equivalence alone does not meet it (Understanding)                 | `05` §3.4 item 8 names a keyboard nudge or a keyboard "…" menu; creation is drag-only in US-DRAW-003, 004, 007                       | AD-7; amend E14-Q07's audit question (§10)                                         |
| 2.5.8 Target Size (Minimum)     | a 24×24 CSS px target per handle; overlapping targets excluded                                                                     | "drag handles ≥24 px", unit and subject unstated                                                                                     | AD-6                                                                               |
| 4.1.3 Status Messages           | armed tool, snap, commit, cancel, undo, save failure                                                                               | "announced on change" (CMP-223); vocabulary deferred to E14-D10                                                                      | §6 vocabulary, polite                                                              |
| 1.4.11 Non-text Contrast, 1.4.1 | handle, snap marker, selection and keyboard cursor ≥3:1 against the data ink behind them; no hue-only state                        | `tools/contrast/pairs.mjs` checks `color.drawing.default/selected` against `surface.canvas` only; default and selected differ by hue | two-tone glyphs (WCAG technique C40) plus shape or text cues; tokens are E14-D08's |
| 2.4.3, 2.4.7, 2.4.11 Focus      | rail → chart → drawing surrogates in a meaningful order; a ring visible over data ink; the popover never covers the focused handle | roving tabindex (`05` §3.4 item 2); popover placement undrawn                                                                        | surrogates in one roving set ordered by time then price, announced "item X of Y"   |
| 2.1.2, 2.5.2, 2.2.2             | `Esc` leaves the armed mode; `Esc` aborts a drag; nothing moves under a pending anchor                                             | unspecified                                                                                                                          | AD-3, AD-8, §6 step 9                                                              |
| 2.1.4, 2.5.1                    | focus-scoped single keys (tree `L`, `Space`, E14-S08) comply; the brush is a path gesture                                          | the brush has no keyboard path                                                                                                       | document the essential exception, or offer a polyline placed with `Enter`          |

| State                         | What E14-D02 draws for drawings                                                                                             | Source                                                |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| loading                       | "Loading drawings" in the chart status while the symbol's drawings load; tools stay armable                                 | E14-T02 initial load                                  |
| empty                         | the tree's drawings branch empty state ("No drawings on BTCUSDT")                                                           | `14` SCR-036 checklist                                |
| error, unsaved                | the "changes not saved" chip is a polite status message and the unsaved drawing is marked in text and icon                  | E14-T02; E14-S01 "Save fails"                         |
| disconnected, stale feed      | drawings stay visible; snaps use last-good bars; the forming bar's values are announced "so far"                            | SCR-030 States; F8                                    |
| demo vs live                  | drawings are environment-agnostic; the position tool names the sizing account and environment                               | `21` §3.8.3; C-2.11                                   |
| reduced motion, high contrast | snap, selection and undo emphasis are static and keep their information; no `color.drawing.*` high-contrast override exists | E14-D09; `packages/ui/tokens/semantic-hc.tokens.json` |
| keyboard-only, screen reader  | the §6 flow; the tree is the complete alternative (`14` SCR-036 A11y)                                                       | CMP-191; SCR-036                                      |
| Viewer (read-only role)       | tools shown disabled with the reason; the server refuses writes regardless                                                  | C-12.4; threat model DR38                             |
| multi-monitor, display scale  | radius, targets and glyphs in CSS px; the harness records the scale factor (P1 runs two or three monitors, `10` §2)         | WCAG 2.5.8                                            |

## 8. Competitive review (public documentation only, read 2026-10-21)

| Aspect              | TradingView                                                                              | Sierra Chart                                                | NinjaTrader 8                                                | ATAS, Quantower, Bookmap, Jigsaw                                        | CandleViewer plan and gap                                                                   |
| ------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Sticky tool         | "Keep drawing" toggle; off returns to the cursor (TV3, TV4)                              | an after-use setting; warns that every click draws          | "Stay in Draw Mode" toggle                                   | ATAS "keep drawing mode"; the others not stated                         | a toggle only in E14-S10 → AD-2                                                             |
| Magnet              | off, weak, strong; hold `Ctrl` flips it; snap to indicators (TV1, TV2)                   | snap on creation and on adjust; sensitivity in percent      | five snap modes, no radius                                   | ATAS "Magnet Sensitivity"; the others not stated                        | three conflicting models, no default → AD-4; **weaker:** no momentary override (kept, §2.2) |
| Precise placement   | Coordinates and Displacement tabs (TV5, TV10)                                            | Adjust, Properties                                          | typed time and price (Data)                                  | not stated                                                              | **weaker:** no anchor fields → AD-7                                                         |
| Object list, bulk   | object tree, nested groups, z-order; a locked-delete dialog (TV14, TV17, TV18)           | type and "with alerts" filters; Erase All keeps locked ones | object list in Properties; Remove All keeps locked, confirms | ATAS objects list; a Quantower lock (release notes)                     | **weaker:** a flat tree, no bulk rule → AD-12                                               |
| Interval visibility | per drawing and per group (TV15, TV16)                                                   | Visibility tab by bar period                                | not stated                                                   | not stated                                                              | **weaker:** none (`interval_scope` unexposed) → OQ-10                                       |
| Sync across charts  | by layout or global, per-object override, same symbol only (TV22, TV24)                  | pull from listed charts; per-drawing opt-out (SC4)          | "Attach to" one chart or the instrument                      | Quantower: video only                                                   | no default stated anywhere → AD-10                                                          |
| Position tool       | entry placed, zones adjusted; Reverse; "Always show stats" (TV19–TV21)                   | stop, entry, target by three clicks                         | entry, maximum risk, typed ratio                             | ATAS: images only                                                       | **ahead:** send-to-ticket with cap gating; **weaker:** no reverse → AD-11                   |
| Hotkeys             | `Alt+T/H/F`, `Alt+Shift+R`, `Ctrl+Y` (LIB1)                                              | any command assignable (SC3)                                | `F2`–`F12` defaults, remappable                              | ATAS remappable with a conflict warning (AT4); Quantower per tool (QT2) | remap in SCR-113 only for registered keys → AD-1                                            |
| Keyboard and SR     | toolbar keyboard navigation and named screen readers; anchor placement not stated (LIB6) | not stated                                                  | not stated                                                   | not stated                                                              | **ahead:** keyboard anchor placement and an announced mode (§6)                             |

Sources, accessed 2026-10-21. TradingView pages were read on its regional help-centre host, which serves the same articles,
because the main host was not reachable from the delivery network: [TV1](https://in.tradingview.com/support/solutions/43000722509-magnet-mode/),
[TV2](https://in.tradingview.com/support/solutions/43000472715-drawing-points-don-t-snap-to-ohlc-values-correctly/), [TV3](https://in.tradingview.com/support/solutions/43000703396-drawing-tools-available-on-tradingview/),
[TV4](https://in.tradingview.com/support/solutions/43000762939-my-drawing-tool-keeps-placing-new-drawings-every-time-i-click-on-the-chart/), [TV5](https://in.tradingview.com/support/solutions/43000518124-horizontal-line-drawing-tool/),
[TV10](https://in.tradingview.com/support/solutions/43000682552-how-to-move-multiple-drawing-objects-at-the-same-time/), [TV12](https://in.tradingview.com/support/solutions/43000484608-how-to-show-hide-all-drawings-on-the-chart/),
[TV14](https://in.tradingview.com/support/solutions/43000760814-how-to-set-removal-of-locked-drawings/), [TV15](https://in.tradingview.com/support/solutions/43000660419-i-want-to-customize-the-visibility-for-several-objects/),
[TV16](https://in.tradingview.com/support/solutions/43000686263-how-to-quickly-adjust-visibility-of-a-drawing-or-indicator/), [TV17](https://in.tradingview.com/support/solutions/43000795451-how-to-create-nested-groups-of-drawings/),
[TV18](https://in.tradingview.com/support/solutions/43000474299-how-can-i-change-the-visual-order-layer-of-indicators-drawings-candles/), [TV19](https://in.tradingview.com/support/solutions/43000475660-how-to-use-long-and-short-position-drawing-tools/),
[TV20](https://in.tradingview.com/support/solutions/43000517002-long-position-drawing-tool/), [TV21](https://in.tradingview.com/support/solutions/43000744866-how-to-reverse-a-position-drawn-on-a-chart-with-the-long-or-short-position-tool/),
[TV22](https://in.tradingview.com/support/solutions/43000629998-my-drawings-do-not-get-synchronized-across-charts-or-layouts/), [TV23](https://in.tradingview.com/support/solutions/43000692404-layouts-charts-drawings-indicators-and-their-interaction/),
[TV24](https://in.tradingview.com/support/solutions/43000629992-how-to-sync-the-charts-of-my-layout/), [LIB1](https://in.tradingview.com/charting-library-docs/latest/configuration/Shortcuts/),
[LIB6](https://in.tradingview.com/charting-library-docs/latest/configuration/accessibility/). Sierra Chart [SC1](https://www.sierrachart.com/index.php?page=doc/Tools.html),
[SC3](https://www.sierrachart.com/index.php?page=doc/KeyboardCommands.html), [SC4](https://www.sierrachart.com/index.php?page=doc/CopyingChartDrawingsFromOtherChartsAutomatically.html).
NinjaTrader [NT1](https://ninjatrader.com/support/helpGuides/nt8/working_with_drawing_tools__ob.htm). ATAS [AT1](https://help.atas.net/en/support/solutions/articles/72000602378-drawing-objects-management),
[AT2](https://help.atas.net/en/support/solutions/articles/72000602255-chart-window), [AT3](https://help.atas.net/en/support/solutions/articles/72000602496-visual-settings-of-the-chart),
[AT4](https://help.atas.net/en/support/solutions/articles/72000602396-hot-keys-configuration). Quantower [QT2](https://help.quantower.com/quantower/analytics-panels/chart/chart-settings/hotkeys),
[release notes](https://www.quantower.com/release-notes). Bookmap [drawing tools](https://bookmap.com/learning-center/en/bookmap-features/drawing-tools/drawing-tools)
(video lessons, nothing readable). Jigsaw [daytradr charts](https://daytradr.jigsawtrading.com/V4-Manual/charts.html) (a drawing-tools toggle only).
Bybit and Binance web terminals: their help pages were not reachable from the delivery network, so nothing is claimed about
them; what an embedded TradingView chart exposes there is the owner's hands-on check.

## 9. Adopted decisions AD-1..AD-12 (pending owner confirmation; testable by E14-D02)

Twelve decisions (ticket: 8–12); the last column gives the findings and basis (plan text or public pages, never observation).

| #     | Decision                                                                                                                                                                                                                                                                                                       | Wireframe violates it if...                                                                                                    | F / basis                                    |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------- |
| AD-1  | Drawing keys follow §2: `Alt+L` trendline, `Alt+H`, `Alt+F` (footprint mode on `Shift+F`), `Alt+R`, `Alt+D` measure, `Ctrl+M`, each registered in `keymap.json` before a frame shows it; no drawing gesture uses `Alt+click`, a price-axis drag or, while chart trading is armed, a modifier-click on the plot | a frame labels `Alt+T` or `Alt+M` as a drawing tool, shows an unregistered key as settled, or gives drawing a trading gesture  | F4, F5 — High (lint run; keymap)             |
| AD-2  | Arming never places an anchor; after a commit the tool reverts to the cursor unless "keep tool active" is on; the rail and an on-chart text chip state the armed tool and the keep-active state                                                                                                                | a hotkey creates a drawing directly, the armed state is shown by highlight or colour alone, or no keep-active control is drawn | F10 — Med (TV3, NT1, SC1; E14-S10)           |
| AD-3  | `Esc` backs out one level at a time (pending anchors, then the armed tool, then the selection) and each level is announced                                                                                                                                                                                     | one `Esc` both discards anchors and disarms, or `Esc` does nothing with a tool armed and no anchors                            | F2 — High (keymap; CMP-223; `05` §3.2)       |
| AD-4  | One chart-level drawing magnet: off, weak (12 CSS px, the default), strong; `Ctrl+M` toggles off ↔ the last on-mode; no per-drawing magnet; separate from the crosshair magnet                                                                                                                                 | the popover shows a per-drawing magnet, the default is not weak, or the mode is shown by colour alone                          | F7, F8 — Med (E14-S02; E11-S07; TV1)         |
| AD-5  | With the magnet on, the snap target is shown by a marker shape and value text ("High 65,400") before the anchor is committed and is announced politely; keyboard placement and nudges never snap; the forming bar's values say "so far"                                                                        | snapping appears only after commit or by colour alone, or a nudge jumps to an OHLC value                                       | F8 — High (US-DRAW-002; E14-S02)             |
| AD-6  | Handles appear only on the selected or keyboard-focused drawing; each has a pointer target ≥24×24 CSS px whatever the glyph; the glyph is smaller than one L0 footprint row; a handle wins over its own line                                                                                                   | every drawing shows handles, a handle is specified by visual size only, or a glyph covers more than one L0 row                 | F9 — High (WCAG 2.5.8; `26` §3.6; `16` §3)   |
| AD-7  | Every drag has a single-pointer path without dragging: click-click placement for multi-anchor tools, and anchor price and time fields in the properties popover                                                                                                                                                | any creation, move or resize needs a drag, or the only alternative drawn is a keyboard nudge                                   | F11 — High (WCAG 2.5.7; `05` §3.4 item 8)    |
| AD-8  | A press moves a drawing only past a small travel threshold; a move shows "from → to · Undo"; `Esc` mid-drag restores the pre-drag geometry; one `Ctrl+Z` restores it in every synced pane                                                                                                                      | a move has no from→to feedback, undoing a move is undrawn, or `Esc` mid-drag commits                                           | F1 — Med (SC1; TV3; TV23; WCAG 2.5.2)        |
| AD-9  | Keyboard creation is stated per anchor count (one-anchor tools commit on the first `Enter`, n-anchor tools on the n-th); arming moves focus to the chart's keyboard surface; the start is the data cursor, else the last close                                                                                 | a one-anchor tool needs two `Enter`s, focus stays on the rail after arming, or the start position is unstated                  | F3, F12 — High (CMP-191; E14-S01; SCR-037)   |
| AD-10 | New drawings are shared by every pane showing the symbol; a sync-off pane marks its drawings "this pane only" in text and icon; turning sync on offers an explicit copy                                                                                                                                        | the default is off, a pane-local drawing is unmarked, or anything syncs across symbols                                         | F14 — Med (US-DRAW-001; `26` §3.10; E14-T02) |
| AD-11 | Position tool: entry → stop → target; risk in USDT is the primary read-out; size, R:R and reward show without hover and name the sizing account and environment; send-to-ticket stays disabled with its reason until a protective stop and a target exist and the cap holds                                    | any frame enables send-to-ticket without a stop, makes a read-out hover-only, or omits the sizing account or environment       | F6 — High (C-2.6; US-DRAW-007; US-PROF-002)  |
| AD-12 | Delete-all sits apart from routine toggles behind a confirm naming the count and symbol and keeping locked drawings, and is one undo step; hide-all is a per-pane view state stated in text ("200 drawings hidden")                                                                                            | delete-all is adjacent to hide or lock, its confirm has no count, it removes locked drawings, or a hidden set looks empty      | F13 — Med (E14-S10; TV14, NT1, SC1)          |

## 10. Amendment proposals (AC5; the gate for E14-D02)

**Gate:** no E14-D02 frame is drawn against a contradicted behaviour until the owner rules on its amendment (plan docs
untouched).

| AM    | Document · entry                                  | Contradiction                                                                                    | Proposed change                                                                                                                              |
| ----- | ------------------------------------------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| AM-1  | `14` SCR-037 Interactions; SCR-030 hotkeys        | `Alt+T`, `Alt+F`, `Alt+M` collide; the line escapes the lint                                     | AD-1 keys (SCR-030: footprint mode on `Shift+F`); the `**Interactions/hotkeys:**` marker; `05` §3.2's `Alt+1..4` and the E11-D04 hint follow |
| AM-2  | `14` SCR-030 hotkeys (`Esc`) and `keymap.json`    | `Esc` cancels only an in-progress drawing                                                        | the `Esc` ladder (AD-3); `chart.cancel_drawing` also valid while a tool is armed                                                             |
| AM-3  | `14` SCR-037 Validation                           | "a drawing needs ≥2 anchors" vs one-anchor tools (`22` `DrawingTool`)                            | "a drawing persists once it has its tool's anchor count"                                                                                     |
| AM-4  | `14` SCR-037 wireframe                            | a per-drawing "snap to OHLC (magnet)" checkbox the API cannot store                              | remove it; a chart-level magnet with its mode menu on the rail (AD-4)                                                                        |
| AM-5  | `14` SCR-037 Type                                 | no "keep tool active" control although E14-S10 specifies one                                     | add it to the rail (AD-2) and to CMP-223's props                                                                                             |
| AM-6  | `14` SCR-045 Interactions                         | SCR-037 relies on "Create horizontal line at focused price"; SCR-045 lists no such action        | add the row action, hinting the AD-1 key                                                                                                     |
| AM-7  | `14` SCR-037 Data                                 | "shared across synced panels" leaves the default and the pane-local case open                    | shared by default (AD-10), with the pane-local marker                                                                                        |
| AM-8  | `14` SCR-037 (no States line; sign-off checklist) | no states; the checklist omits the position tool and anchored VWAP                               | add the §7 states; add both tools and the keyboard flow per anchor count                                                                     |
| AM-9  | `14` SCR-036 drawings branch                      | tree `Space` = visibility (E14-S08) vs `Space` = selection (E13-D01, APG)                        | one key map with E13; the "this pane only" marker; "item X of Y"                                                                             |
| AM-10 | `11` US-DRAW-001 NFR                              | "drag handles ≥24 px": unit and subject unstated                                                 | "pointer target ≥24×24 CSS px; the visible glyph may be smaller" (AD-6); E14-T04 follows                                                     |
| AM-11 | `11` US-DRAW-001 and US-DRAW-009                  | "every BTCUSDT chart" vs conditional sync; "local to that pane" has no scope in `21` §3.8.3      | shared by default (AD-10); pane-local becomes layout-scoped or gains a pane identity (engineering, E14-S09 with E15)                         |
| AM-12 | `11` US-DRAW-008                                  | redo `Ctrl+Shift+Z` vs `Ctrl+Y`; undo specified for delete only; delete-all and hide-all unruled | `Ctrl+Y`; undo restores every operation (E14-T02's command list); AD-12's delete-all rule                                                    |
| AM-13 | `11` US-DRAW-007                                  | "Drag entry, stop and target" has no `When`; read-out and intermediate state unstated            | AD-11's order, primary read-out and send-to-ticket rule                                                                                      |
| AM-14 | `11` US-DRAW-002                                  | a binary magnet with no radius and no default                                                    | AD-4 and AD-5                                                                                                                                |
| AM-15 | `11` US-DRAW-003 and US-DRAW-004                  | the channel's "third drag" and the Fibonacci "drag from swing low" are drag-only                 | click-click placement (AD-7)                                                                                                                 |

**Other documents, noted for their owners (not edited):** `15` CMP-191 (flow per anchor count, focus after arming) and CMP-223
(keep-active, magnet semantics); `26` §3.10–§3.11 (magnet modes, `Esc` ladder); `13` §6 and `17` §7 against the keymap's
chart-trading gestures (E31); `04` §7.2 row 6 lets a Viewer save "own drawings" though the matrix and the seed deny
`workspaces:write`; E14-Q07 audits the keyboard as the 2.5.7 alternative; E14-D10 calls 2.4.11 "Focus Appearance" (it is
2.4.13).

## 11. Observability

The annotated events (`14` SCR-037 Analytics: `drawing.created`, `drawing.edited`, `drawing.deleted`,
`drawing.cloned_to_synced_charts`) count drawings per tool but answer none of the open questions. Every event carries ids and
counts only, never `label` or `text` (threat model SR-E14-06), with small closed label sets
(`docs/plan/observability-contract.md`). No sink is documented for `drawing.*` product events (`22` `/telemetry/frontend` takes
pre-bucketed performance data only) and `04` §15.3 limits analytics to operating the system, so where they go is OQ-6. Canonical
names (with the drift they replace) go to E14-D12 (#355), and E14-D11 (#541) verifies them in the built app; `drawing.created`
replaces `chart.drawing_created` (SCR-030) and `drawing.deleted` replaces `drawing.removed` (SCR-036).

| Question after release                | Event (canonical name; the drift it replaces)                                                                                                                      | Status                      |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------- |
| Which tools are used, and picked how? | `drawing.tool_selected{tool, entry_method}` (E14-S10's `drawing.tool_armed`); `entry_method` on `drawing.created`: rail, hotkey, palette, keyboard_flow, table_row | proposed (E14-D03, E14-D10) |
| Where are drawings abandoned?         | `drawing.cancelled{tool, anchors_placed, cause}`, cause one of esc, tool_switch, focus_loss, symbol_switch, interval_switch                                        | new                         |
| Is the magnet default right?          | `drawing.magnet_mode_changed{from, to, source}` (E14-S02's `drawing.magnet_toggled`); `drawing.snap_applied{ohlc_field}`                                           | proposed                    |
| Is keep-active used?                  | `drawing.keep_active_toggled{on}`                                                                                                                                  | new                         |
| How often do mis-drags happen?        | `drawing.undone{op}` with a closed `op` set and a bucketed time since the operation; a move undone within seconds is the proxy                                     | new                         |
| Curate or accumulate?                 | `drawing.bulk_action{action, count_bucket}` (E14-S08's `drawing.bulk_deleted`, E14-S10's `drawing.delete_all`); the per-user drawing-count gauge (#2727)           | proposed                    |
| Is sync wanted?                       | `drawing.sync_toggled{enabled}`; `drawing.cloned_to_synced_charts`                                                                                                 | named (E14-S09, SCR-037)    |
| Is the position tool capped or sent?  | `drawing.position_tool_blocked_by_cap`, `drawing.position_tool_sent_to_ticket` (E14-S07's `_capped`, `send_to_ticket`); counts only, never risk or cap amounts     | named (E14-D06)             |

## 12. Security: drawing text notes

Plain text is decided at every boundary (E14-S06 Out of scope: "Rich text, markdown, links or images in notes"; E14-D04: no
rich-text toolbar, no paste-as-HTML, no auto-linkification, the cap shown). The server strips control and bidi characters on
write and does not HTML-encode, so safety lives at each render sink (`22` `DrawingGeometry`; threat model SR-E14-01..03). The
users' expectation is unobserved, so the protocol records it (Probe CI-4): formatted paste, a pasted URL, line breaks, and the
1,000-code-point text and 120-code-point label caps (`22` `DrawingGeometry`, `DrawingInput`). Recommendations `(heuristic,
Med)`: a paste becomes plain text at once with a visible "pasted as plain text" cue (H1, H9); a URL stays inert text; the
characters left show near the cap. **A participant who expects clickable links or rich text raises new scope** for the owner and
E14-X02 (#474), never a silent relaxation (OQ-7). Seam: notes are "included in journal snapshots" (US-DRAW-006 NFR) and journal
bodies are markdown by default (`21` `notes.body_format`), so E41's render path must escape a plain-text note.

## 13. Performance inputs and engine implications

No snap-feedback latency tolerance was observed. The input to the picking budget (≤1 ms for 200 drawings and 50 lines, `26`
§3.9) and B8 (`26` §13) is a design target of **same-frame feedback** (the snap marker drawn in the frame that handles the
pointer move, which E14-S02's O(1) snap test allows); the harness logs pointer-to-marker latency and frame time against
SCR-037's ≥58 fps with 200 drawings (protocol §6). **Engine capabilities implied beyond `26` §3.10** (for the Architect review
the owner's `approved` substitutes, OQ-9): a chart-level three-mode magnet with a radius; tick-only snapping for the position
tool; keep-tool-active re-arming; the `Esc` ladder; handle targets decoupled from glyphs (a 24 px square, or at least a 12 px
radius); a drag travel threshold; auto-follow paused while an anchor is pending; OHLC-only snap candidates in R1 (E14-S02).

## 14. Open questions, each routed to a decision

| OQ    | Question (decider; consumer)                                                                     | Recommended default                                                                                      |
| ----- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| OQ-1  | the hotkey scheme (owner, with E11-D07 #330's registry check, which E11-D01 wants by 2026-10-29) | AD-1; TradingView's `Alt+T` for the trendline would move the screen-reader escape hatch: not recommended |
| OQ-2  | magnet default and radius (owner; E14-S02 #471)                                                  | weak, 12 CSS px (§3 Q1)                                                                                  |
| OQ-3  | sticky or revert (owner; E14-S10 #432)                                                           | revert, with a keep-active toggle (§3 Q2)                                                                |
| OQ-4  | the sync default and how "this pane only" is stored (owner, with E15-D01 #205; E14-S09 #548)     | shared by default; storage per AM-11 (§3 Q4)                                                             |
| OQ-5  | position-tool order, primary read-out and snapping (owner; E14-D06 #350, E14-S07 #546)           | entry → stop → target; risk in USDT; tick-only snapping (§3 Q5)                                          |
| OQ-6  | where `drawing.*` events go, if anywhere (owner; E14-D12 #355)                                   | no sink until one is specified; the names are fixed now (§11)                                            |
| OQ-7  | links or rich text in notes (owner; E14-X02 #474)                                                | plain text; a "yes" in the sessions is new scope (§12)                                                   |
| OQ-8  | the three-session deviation, the run and the owner's own moderator (owner, before E14-D02)       | approve; run once E14-D02's frames and the harness exist                                                 |
| OQ-9  | engine implications and the handle rule (owner as Architect; E14-T04 #359, E14-D08 #352)         | accept §13 and §3 Q3                                                                                     |
| OQ-10 | per-interval visibility, clone and multi-select, which no story names (owner; §5, §8)            | not in R1; record usage in the sessions first                                                            |
| OQ-11 | the Viewer drawing-permission conflict in `04` §7.2 (owner; §10)                                 | the matrix and the seed win: the Viewer stays read-only                                                  |

## 15. References

`CONSTITUTION.md` C-2.6, C-2.11, C-2.12, C-12.4 · `docs/plan/00-planning-brief.md` · `04-security-program.md` §7.2, §15.3 ·
`05-accessibility-standard.md` §3.1–§3.4, §4, §6.2, §7, §8 · `10-personas.md` §1–§4 · `11-user-stories.md` US-DRAW-001..009,
US-CHART-008, US-PROF-002 · `13-user-flows.md` §6 · `14-screens-catalogue.md` SCR-023, 030, 036, 037, 045, 060, 113 ·
`15-component-catalogue.md` CMP-190, 191, 223 · `16-design-system-brief.md` §3 · `17-ux-diagrams.md` §7 ·
`21-database-schema.md` §3.8.3 · `22-api-openapi.yaml` `DrawingTool`, `DrawingGeometry`, `DrawingInput`, `DrawingStyle`,
`/drawings/batch`, `/telemetry/frontend` · `24-internal-schemas.md` §9.3 · `26-chart-engine-design.md` §3.6, §3.9–§3.11, §12,
§13 · `docs/plan/observability-contract.md` · `docs/security/threat-models/E14-drawings.md` ·
`docs/generated/default-keymap.md`, `apps/web/src/keymap/keymap.json`, `scripts/keymap_lint.py` · `tools/contrast/pairs.mjs`,
`packages/ui/tokens/` · `services/api/candleviewer/auth/rbac_seed.json` · `docs/research/01-tradingview-charting.md` · backlog
`E14.json`, `E11.json`, `E15.json` (keys cited inline) · `docs/design/E06/E06-D03.md` (D5, §8) · precedents
`e13-indicator-mental-models.md`, `e30-order-entry-under-time-pressure.md`, `e30-d01-session-protocol.md` · in flight: E11-D01
(draft PR #3828), E11-D04 (draft PR #3929) · public URLs in §8.
