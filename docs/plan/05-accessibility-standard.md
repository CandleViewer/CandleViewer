# 05 — Accessibility Standard (WCAG 2.2 AA)

Status: locked for planning phase. Owner: Accessibility lead (UI/UX org) + Frontend team. Applies to the CandleViewer web app (React + custom WebGL chart engine, Electron shell) including all owner/admin screens. No Android/mobile scope.

This document is the single source of truth for accessibility acceptance criteria referenced by `11-user-stories.md`, `14-screens-catalogue.md`, `15-component-catalogue.md`, `16-design-system-brief.md`, and every ticket in `docs/plan/backlog/*.json` tagged `a11y`.

---

## 1. Scope and conformance target

- **Conformance target**: WCAG 2.2 Level AA, plus selected AAA success criteria where cheap and high-value for a trading terminal (non-text contrast ≥7:1 for critical buy/sell state where feasible, no timing limits).
- **Applies to**: every screen in `12-sitemap.md` — charting workspace, DOM/heatmap, order ticket, positions/orders, risk dashboard, rule builder, journal, watchlist, account/environment switcher, admin/users screens. Applies inside Electron (primary shell) and in a plain-browser dev target used for automated testing.
- **Does not relax for "power-user" surfaces**: the DOM ladder, footprint grid and rule node-graph editor are dense, high-information-density surfaces; WCAG AA still applies — density is solved via information architecture (§4), not by exempting a screen.
- **Exclusions (documented, not silent)**: raw WebGL canvas pixels are not natively accessible; every canvas-rendered data surface MUST have an accessible-equivalent mechanism per §5. This is the primary architectural risk this document manages.
- **Legal/compliance framing**: this is an internal tool (owner + a few managers), not a public-facing product, so there is no external legal AA mandate. The bar is set at full AA anyway because (a) the owner may develop RSI/motor or vision conditions over the tool's long lifetime, (b) keyboard-first operation is also a _speed_ requirement for trading (mouse-only trading is a latency and RSI risk), and (c) it is dramatically cheaper to build in from Sprint 01 than retrofit onto a bespoke WebGL engine later.

## 2. Principles mapped to trading UI (POUR)

| WCAG principle     | CandleViewer-specific interpretation                                                                                                                                                                                                                                            |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Perceivable**    | Buy/sell/long/short state is never colour-only (shape + text + colour). Dark theme meets contrast minimums. Canvas content has a text/DOM equivalent. Live-updating prices are announced via ARIA live regions without flooding the screen reader.                              |
| **Operable**       | Every trading action (submit order, cancel, flatten, arm/disarm rule, switch demo/live) is reachable and executable from keyboard alone, with visible focus, without incidental timing traps, and with confirm-before-destructive-action gates that are also keyboard-operable. |
| **Understandable** | Consistent hotkey map across all views (single global layer, not per-view schemes — per `23-views-and-screens.digest.md`). Predictable focus order. Errors (rejected orders, WS disconnects) are announced in plain language, not just a colour change.                         |
| **Robust**         | Semantic HTML/ARIA for all chrome (panels, dialogs, menus, tables); custom WebGL surfaces expose parallel accessible representations that pass axe-core and screen-reader testing, not just visual review.                                                                      |

## 3. Keyboard-first operation

### 3.1 Design rules

1. Every interactive element (buttons, chart drawing tools, DOM ladder cells, footprint cell tooltip, rule-graph nodes, dialog controls) must be reachable via `Tab`/`Shift+Tab` in a logical order and operable via `Enter`/`Space`/arrow keys as semantically appropriate (WCAG 2.1.1, 2.1.2 — no keyboard trap).
2. A **single global hotkey layer** governs the whole app (confirmed design requirement from views research) — no view silently overrides a global binding. View-local hotkeys are additive and only active while that view/pane has focus.
3. Hotkeys are **user-remappable** (Options → Settings → Shortcuts, mirroring the DeepCharts precedent) with conflict detection at bind-time (§3.3) and a "restore defaults" action.
4. Destructive/irreversible actions (submit market order, flatten all, cancel all, Live-armed rule trigger, Demo→Live switch) require either (a) a second keystroke/confirm dialog operable by keyboard, or (b) an explicit "hold to confirm" pattern that also has a discrete-press keyboard fallback (never a mouse-hold-only or timing-only gate — WCAG 2.2.1 no keyboard-only timing trap).
5. 1-click/no-confirm trading is an explicit opt-in toggle (already in scope per `23-views-and-screens.digest.md` View 13) and must show a persistent, non-colour-only "1-click ARMED" indicator (icon + text) whenever active.
6. No functionality may depend on hover-only or drag-only interaction: every drag-to-modify order line, drawing tool, or rule-graph edge has a keyboard-operable equivalent (e.g. select line with `Tab`/click → arrow keys nudge by tick size → `Enter` commits, `Esc` cancels).
7. Chart pan/zoom/crosshair must be fully keyboard operable: arrow keys move crosshair by one bar/one tick, `Shift+arrows` pans the viewport, `+`/`-` zoom, `Home`/`End` jump to oldest/latest bar, matching WCAG 2.1.1 for the "canvas control surrogate" pattern in §5.

### 3.2 Default hotkey map (v1)

Research found no reusable default keymap (DeepCharts ships user-defined-only, TradingView differs per product) — CandleViewer defines its own defaults below. All are remappable per §3.1.3. Categories mirror the DeepCharts precedent (General / Chart / Drawing / Scroll / Trading) plus Navigation and A11y.

| Category                      | Action                                              | Default key                                             | Notes                                                                                                  |
| ----------------------------- | --------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **Global / Navigation**       | Command palette / search-anything                   | `Ctrl+K`                                                | Opens searchable command list — critical a11y escape hatch when a hotkey is forgotten or remapped away |
|                               | Switch workspace layout preset                      | `Ctrl+1`..`Ctrl+9`                                      | Per View 11                                                                                            |
|                               | Toggle sidebar / panel focus cycle                  | `Ctrl+\`                                                | Cycles focus between major regions (chart, DOM, order ticket, positions) — see §4.2 landmark model     |
|                               | Open Watchlist / symbol search                      | `/`                                                     | Only active when focus is not inside a text input                                                      |
|                               | Toggle keyboard-hotkey cheat-sheet overlay          | `Shift+/` (i.e. `?`)                                    | Always available, shows current (possibly remapped) bindings                                           |
|                               | Escape / cancel current action                      | `Esc`                                                   | Universal cancel: closes dialogs, cancels in-progress order draft, exits drawing-tool mode             |
| **Chart**                     | Zoom in / out                                       | `+` / `-`                                               |                                                                                                        |
|                               | Pan left / right                                    | `←` / `→`                                               | Also moves crosshair by 1 bar when crosshair mode active                                               |
|                               | Jump to latest bar (resume live)                    | `End`                                                   |                                                                                                        |
|                               | Jump to oldest loaded bar                           | `Home`                                                  |                                                                                                        |
|                               | Cycle chart type                                    | `Alt+C`                                                 |                                                                                                        |
|                               | Cycle timeframe                                     | `Alt+↑` / `Alt+↓`                                       |                                                                                                        |
|                               | Toggle footprint / heatmap / profile overlay        | `F` / `H` / `P`                                         |                                                                                                        |
|                               | Toggle data-table alternative view (§5.4)           | `Alt+T`                                                 | Screen-reader / low-vision escape hatch, always available                                              |
| **Drawing**                   | Trendline / horizontal line / rectangle / Fibonacci | `Alt+1..4`                                              | Enters drawing mode; arrow keys place points, `Enter` commits, `Esc` cancels                           |
|                               | Delete selected drawing                             | `Delete`/`Backspace`                                    |                                                                                                        |
| **Trading**                   | Buy market / Sell market                            | `B` / `S`                                               | Only active when order ticket or chart-trading focus context is active, per view scoping in §3.1.2     |
|                               | Size preset 1–5                                     | `1`..`5`                                                | Context-scoped to trading views only (does not clash with `Ctrl+1..9` layouts, which require `Ctrl`)   |
|                               | Submit order                                        | `Ctrl+Enter`                                            | Two-key combo deliberately avoids accidental submit                                                    |
|                               | Cancel focused order                                | `Esc` (when order row focused)                          |                                                                                                        |
|                               | Flatten all (this account)                          | `Ctrl+Shift+F`                                          | Always shows confirm dialog (§3.1.4)                                                                   |
|                               | Toggle 1-click trading                              | `Ctrl+Shift+1`                                          | Shows persistent armed indicator                                                                       |
| **DOM Ladder**                | Zoom price step                                     | `+` / `-` (ladder-focused)                              |                                                                                                        |
|                               | Place limit at focused row                          | `Enter`                                                 |                                                                                                        |
|                               | Place market (aggressive) at focused row            | `Ctrl+Enter`                                            |                                                                                                        |
|                               | Cancel all at focused row                           | `Ctrl+Delete`                                           |                                                                                                        |
| **Replay**                    | Play/pause                                          | `Space`                                                 |                                                                                                        |
|                               | Step bar                                            | `←` / `→`                                               |                                                                                                        |
|                               | Step tick                                           | `Shift+←` / `Shift+→`                                   |                                                                                                        |
|                               | Jump to real-time                                   | `R`                                                     |                                                                                                        |
| **Rule builder (node graph)** | Add node                                            | `Ctrl+Shift+N`                                          |                                                                                                        |
|                               | Connect focused ports                               | `Enter` (after `Tab`-selecting source then target port) | Node-graph keyboard operability detailed in `14-screens-catalogue.md`                                  |
|                               | Delete focused node/edge                            | `Delete`                                                |                                                                                                        |
| **Accessibility**             | Increase/decrease UI text scale                     | `Ctrl+=` / `Ctrl+-`                                     | Independent of browser zoom, affects density mode too (§4.1)                                           |
|                               | Toggle reduced-motion override                      | `Ctrl+Shift+M`                                          | Session override on top of OS-level `prefers-reduced-motion` (§6)                                      |
|                               | Toggle high-contrast theme                          | `Ctrl+Shift+H`                                          |                                                                                                        |

### 3.3 Conflict resolution rules

1. **Precedence order** when a user tries to bind an already-used key: (1) global/navigation bindings cannot be overridden by view-local bindings — the remap UI blocks this at save-time with an inline error; (2) trading-critical bindings (submit, cancel, flatten) cannot be bound to a single unmodified letter key without at least one modifier, to reduce accidental-trigger risk — enforced by the remap UI, not just documented; (3) view-local bindings may shadow each other only within mutually-exclusive focus contexts (e.g. `+`/`-` means "zoom chart" when chart has focus and "zoom ladder price step" when DOM ladder has focus — this is not a conflict because only one is active at a time, but the remap UI must show both bindings side-by-side when the user edits `+`/`-` so they understand the dual meaning).
2. **Detection algorithm**: on every rebind attempt, compute the new key-combo's active focus-context set; if it intersects with an existing binding's focus-context set for a _different_ action, block the save and show which existing action conflicts, with a one-click "swap" option.
3. **Reserved, non-remappable keys**: `Esc` (universal cancel) and `Ctrl+K` (command palette, the recovery mechanism if a user breaks their own hotkey config) are permanently reserved and excluded from the remap UI.
4. **OS/Electron-reserved combos are blocklisted** (e.g. `Ctrl+W`, `Ctrl+Q`, `Alt+F4`, `Ctrl+N` if it would conflict with OS window management) — the remap UI filters these out of the pickable set entirely rather than allowing-then-failing silently.
5. **Cross-account/hotkey-size-preset ambiguity**: when multiple trade-group accounts are targeted by one ticket, size-preset keys (`1`-`5`) apply to the _ticket's_ configured per-account sizing rule, not a literal shared quantity — this is a UX/data-model concern documented here to prevent an a11y-adjacent "silent multi-account fat-finger" failure mode; the order-confirm dialog (keyboard operable) always lists the resolved per-account quantities before submit.
6. **Tracking note — rule-builder node-graph keyboard spec**: the rule-engine's visual node-graph editor (drag-connect rule nodes/edges) will define its own keyboard interaction model (arrow-key node navigation, `Enter`/`Space` to connect, `Delete` to remove an edge) in `14-screens-catalogue.md` once that screen is specced. That spec MUST cross-link back to this §3.3's precedence/detection rules rather than defining an independent conflict-resolution scheme, to avoid duplication drift between the two documents; `14-screens-catalogue.md`'s node-graph section is required to open with an explicit "see `05-accessibility-standard.md` §3.3 for global conflict rules" pointer, and this file's §12 Cross-references entry for `14-screens-catalogue.md` (once added) must reciprocally reference this rule.

### 3.4 Focus management in dense layouts

CandleViewer screens are unusually dense (multi-pane chart + footprint + DOM heatmap + order ticket + positions table simultaneously visible). Rules:

1. **Landmark regions**: each major panel (Chart, DOM/Heatmap, Order Ticket, Positions & Orders, Watchlist, Rule Builder canvas) is a labelled ARIA landmark (`role="region"` + `aria-label`) reachable via `Ctrl+\` region-cycling and via the browser's native landmark navigation (screen-reader "regions" list).
2. **Roving tabindex** within composite widgets (DOM ladder rows, footprint cell grid, positions table, watchlist rows, rule-graph nodes): only one cell/row is in the natural Tab order at a time (`tabindex="0"`), all siblings `tabindex="-1"`, arrow keys move the roving focus — per WAI-ARIA APG grid/treegrid pattern. This prevents 200+ Tab presses to cross a DOM ladder.
3. **Focus is never silently stolen**: a live price update, a new fill notification, or an incoming WS push must NOT move keyboard focus. Only explicit user action or an explicit modal alert (e.g. "position auto-flattened by risk engine" — a `role="alertdialog"`) may move focus, and it must be announced first (§5.3) before any focus shift.
4. **Modal dialogs** (order confirm, flatten-all confirm, Demo→Live switch confirm, rule-arm confirm) trap focus per WAI-ARIA APG dialog pattern, return focus to the triggering element on close, and are dismissible via `Esc` (except one-time irreversible confirms which still allow `Esc`=cancel, matching "cancel is always safe").
5. **Skip links**: a visually-hidden-until-focused "Skip to order ticket" / "Skip to chart" link set at the top of the DOM lets keyboard/SR users bypass the watchlist/nav chrome, satisfying WCAG 2.4.1 (Bypass Blocks).
6. **Visible focus indicator**: WCAG 2.2 SC 2.4.11 (Focus Not Obscured, Minimum) — a focused element is never fully hidden behind a sticky toolbar/panel; focus ring uses a ≥2px outline with ≥3:1 contrast against adjacent colours (SC 1.4.11 non-text contrast), consistent across the dark theme and high-contrast theme. Focus ring style is a design-system token (`16-design-system-brief.md`), never removed via `outline: none` without a replacement that meets the same contrast bar.
7. **Target size**: WCAG 2.2 SC 2.5.8 (Target Size, Minimum, AA) — all clickable controls, including individual DOM-ladder rows and footprint cells at default zoom, are ≥24×24 CSS px OR have ≥24px spacing to the next target, OR fall under the "inline"/"essential" exception (footprint cells at max chart zoom-out are documented as the "essential exception" — dense financial data display — but MUST provide the zoomed/table alternative in §5.4 for anyone who cannot hit small targets).
8. **Dragging alternatives**: WCAG 2.2 SC 2.5.7 (Dragging Movements, AA) — every drag interaction (order-line reprice, drawing-tool node move, rule-graph node move, panel resize) has a non-drag alternative: click-to-select then arrow-key nudge, or a keyboard-accessible "..." menu offering the same repositioning as discrete steps/values.
9. **Consistent help mechanism**: WCAG 2.2 SC 3.2.6 (Consistent Help, A) — the hotkey cheat-sheet (`?`) and a "Help/Docs" entry point appear in the same relative location/order across every screen.
10. **Redundant entry**: WCAG 2.2 SC 3.3.7/3.3.8 (Redundant Entry / Accessible Authentication, AA) — order tickets pre-fill from last-used values/defaults where safe; login/API-key entry never requires a cognitive-function test (no CAPTCHA puzzle; 2FA via standard TOTP/WebAuthn is exempt as "object recognition"/allowed alternative).

## 4. Colour-independence for buy/sell and all status signalling

**Rule (non-negotiable, applies everywhere)**: colour is always a _reinforcing_ channel, never the _only_ channel, for: buy vs sell/long vs short, bid vs ask (heatmap), profit vs loss, order status (working/filled/rejected/cancelled), connection/health status, demo vs live, risk-limit breach severity, imbalance/delta sign.

1. **Shape + text + colour triad**:
   - Buy/long: green fill/text AND an upward-pointing glyph (▲) AND the word "Buy"/"Long" in any tooltip, row label, or confirm dialog — never a bare colon-coloured number.
   - Sell/short: red fill/text AND a downward glyph (▼) AND "Sell"/"Short" text.
   - Heatmap bid/ask (green=bid, red=ask per owner decision): colour + an axis-side convention (bids always render on the price-below/left visual convention, asks above/right — configurable but with a persistent legend, never colour-only) + on-hover/focus text readout of side.
   - Order status: colour (amber=working, green=filled, red=rejected, grey=cancelled) + a status-word label + a status icon (clock/check/x/slash) in every row, not just a coloured dot.
   - P&L: colour + explicit `+`/`-` sign + text ("Profit"/"Loss" in screen-reader-only text where a bare signed number might be ambiguous in a dense table).
   - Connection/health (View 15 risk dashboard, WS status chip): colour + icon (✓/⚠/✕) + text state ("Connected"/"Degraded"/"Disconnected").
   - Demo vs Live: colour (documented owner decision: Live = red-accented chrome) + a persistent, non-dismissible text badge reading "LIVE" or "DEMO" in the title bar/header, present on every screen, and included in the accessible name of the window region so a screen-reader user always has environment context announced on focus entry.
2. **Deuteranopia/protanopia/tritanopia validation**: the design-system colour tokens (`16-design-system-brief.md`) must be run through a colour-blindness simulator (e.g. Able, Stark, Chrome DevTools vision-deficiency emulation) for all 3 common CVD types as part of design sign-off for every screen that uses the buy/sell or heatmap palette; this is a Definition-of-Done gate for design tickets, checked before "design-ahead" sign-off per the brief's 2-sprint rule.
3. **Imbalance/delta sign** (footprint cells, CVD, imbalance tracker): sign is shown via `+`/`-` prefix and/or explicit up/down glyph in addition to red/green cell shading; imbalance-flagged cells get a distinct border/pattern (not just brighter colour) so pattern-based flagging survives grayscale/high-contrast mode.
4. **Alert/toast severity** (rule triggers, risk breaches, WS disconnects): severity communicated via icon + text + colour, and critical severity additionally uses a persistent (non-auto-dismissing) banner rather than colour-coded auto-dismiss toast alone, so severity is legible even to a screen-reader user who doesn't perceive colour-coded timing.

## 5. Contrast in the dark theme

CandleViewer's default and primary theme is dark (trading-terminal convention); a high-contrast theme variant is also required.

1. **Text contrast (WCAG 1.4.3, AA)**: body text and labels ≥4.5:1 against their background; large text (≥24px regular or ≥19px bold) ≥3:1. Applies inside dense tables (positions, orders, journal) at whatever zoom level ships as default.
2. **Non-text/UI component contrast (WCAG 1.4.11, AA)**: buttons, form-field borders, focus rings, icon-only controls, chart axis lines/gridlines that carry meaning (not pure decoration), and the buy/green vs sell/red state indicators themselves ≥3:1 against adjacent colours.
3. **AAA stretch target for critical state**: buy/sell primary action buttons and the LIVE/DEMO badge target ≥7:1 text contrast where the dark-theme palette allows, as a deliberate over-conformance given the cost of a misread order side.
4. **Chart data-ink contrast**: candle body/wick colours, footprint cell background+text pairs, heatmap gradient stops, and profile-histogram bars must each independently meet 3:1 against the chart background at every point in the gradient/theme — this is validated with an automated contrast-check script run against the design-system token palette (not just spot-checked visually), producing a pass/fail matrix per token pair, gated in CI on token-file changes.
5. **No pure-black-on-pure-white or vice versa**: the dark theme uses near-black (not #000) backgrounds and off-white (not #FFF) primary text to reduce eye strain/halation, consistent with reduced-motion/photosensitivity goals in §6; exact tokens defined in `16-design-system-brief.md`.
6. **User-adjustable contrast**: a high-contrast theme toggle (`Ctrl+Shift+H`, §3.2) swaps the whole token set to a WCAG-AAA-leaning palette (≥7:1 body text) for low-vision users, validated with the same automated contrast matrix.
7. **Text resize (WCAG 1.4.4, AA)**: UI must remain usable with 200% browser/OS zoom or the in-app text-scale control (`Ctrl+=`/`Ctrl+-`) without loss of content/functionality (reflow where feasible; dense tables may switch to a card/stacked layout at extreme zoom rather than clipping, per WCAG 1.4.10 Reflow at 400% zoom / 320 CSS px equivalent width — documented as a graceful-degradation, not a hard requirement, for the highest-density trading screens which are inherently desktop-only, but the reflow behaviour must not lose data, only re-lay-out it).

## 6. Canvas/WebGL accessibility strategy

This is the highest-risk area: the chart engine, footprint grid, DOM heatmap, and profile panels render to a WebGL canvas, which is opaque to assistive technology by default (no DOM, no accessibility tree). Strategy has three complementary layers, all mandatory (not "either/or"):

### 6.1 Layer 1 — Offscreen DOM mirror (structural accessibility tree)

- For every canvas-rendered view, the engine maintains a **parallel, visually-hidden (`clip-path`/off-screen positioned, not `display:none`) DOM structure** that mirrors the currently-relevant data: visible bar range (OHLCV), focused footprint cell's values, focused heatmap cell's price/size, focused DOM ladder row.
- This mirror is what keyboard focus actually lands on: the "canvas control surrogate" pattern — a `tabindex`-able, ARIA-labelled DOM element per logical unit (bar, cell, row) sits invisibly aligned over/behind the canvas region it represents, sized to match the visual target for pointer users using it too (satisfies target-size and focus-visible rules in §4 simultaneously).
- The mirror is windowed/virtualized (only currently-visible/currently-focusable items are materialized in the DOM — not all 100k bars) to avoid a11y-tree bloat and to keep it in sync with WebGL's own LOD/culling, per the performance standard (`06-performance-and-load-standard.md`).
- Engine architecture requirement (feeds `26-chart-engine-design.md`): the rendering engine's public API must expose a "current visible window + current focused unit" query surface that the React layer consumes to keep the DOM mirror and the WebGL draw calls frame-synchronized — this is an explicit chart-engine-design requirement, not an afterthought bolted on later.

### 6.2 Layer 2 — ARIA live regions for streaming updates

- **Price/position/order updates** are announced via `aria-live` regions, but with strict throttling/summarization to avoid "announcement flooding" at 10Hz+ tick rates (a screen reader reading every tick aloud is unusable):
  - `aria-live="polite"` region for ambient updates (best bid/ask, mark price, unrealized P&L) — updated at a throttled cadence (default 1 update / 2s per field, user-configurable in Settings → Accessibility), always presenting the _latest_ value rather than queuing every intermediate tick.
  - `aria-live="assertive"` (or `role="alert"`) reserved for discrete, low-frequency, high-importance events only: order filled, order rejected, position auto-flattened by risk engine, rule triggered, WS disconnected/reconnected, Demo/Live environment switch confirmed. These are never throttled/coalesced — each is announced once, in full.
  - A user-facing "Announcements" settings panel lets the user choose which event classes go to which live-region politeness level, and a master "reduce announcements" toggle for screen-reader users who prefer to poll the DOM mirror manually instead of ambient narration.
- **Region hygiene**: live regions are pre-rendered empty containers on page load (per best practice) and only their _text content_ is swapped, never the whole node destroyed/recreated, so screen readers reliably pick up updates.

### 6.3 Layer 3 — Data-table alternative for footprint/profile/heatmap

- Every canvas-rendered data surface has a **"View as table" toggle** (`Alt+T`, §3.2) that renders the same data as a real, semantic `<table>` with `<th scope="col/row">`, sortable columns, and standard table screen-reader navigation (Ctrl+Alt+arrows in NVDA/JAWS table mode). The exact column set per surface is fixed (below) so implementers and QA need no clarification.

**Footprint table** (one row per price level within the currently-focused bar):

| Column          | Content                                                                                       | Sortable                  | Notes                                              |
| --------------- | --------------------------------------------------------------------------------------------- | ------------------------- | -------------------------------------------------- |
| Price           | Level price, formatted per instrument tick size                                               | Yes (default: descending) | Row header (`<th scope="row">`)                    |
| Bid vol         | Resting/traded bid-side volume at level                                                       | Yes                       |                                                    |
| Ask vol         | Resting/traded ask-side volume at level                                                       | Yes                       |                                                    |
| Delta           | Ask vol − bid vol at level                                                                    | Yes                       | Sign shown as text (`+`/`−`), never colour-only    |
| Imbalance flag  | "Bid-stacked" / "Ask-stacked" / "—" (per the configured imbalance-ratio threshold, e.g. 300%) | Yes (groups flagged rows) | Text label, not icon-only                          |
| Estimated badge | "(estimated)" footnote marker + reason (`iceberg`, `stop-run`, `order-count proxy`) or blank  | Filter-only (see below)   | Satisfies WCAG 1.3.1 for the heuristic-data caveat |

**Profile table** (one row per price level within the currently-visible profile, e.g. Volume Profile / TPO):

| Column     | Content                                            | Sortable                  | Notes              |
| ---------- | -------------------------------------------------- | ------------------------- | ------------------ |
| Price      | Level price                                        | Yes (default: descending) | Row header         |
| Volume     | Total traded volume at level                       | Yes                       |                    |
| Delta      | Net delta at level                                 | Yes                       | Text sign as above |
| % of POC   | Volume as % of the point-of-control level's volume | Yes                       |                    |
| Value area | "In VA" / "Outside VA"                             | Filter-only               |                    |

**DOM ladder table** (one row per price level of the currently-focused book, up to 200-depth):

| Column           | Content                                                       | Sortable                              | Notes      |
| ---------------- | ------------------------------------------------------------- | ------------------------------------- | ---------- |
| Price            | Level price                                                   | Yes (default: best-bid/ask outward)   | Row header |
| Bid size         | Resting bid size at level                                     | Yes                                   |            |
| Ask size         | Resting ask size at level                                     | Yes                                   |            |
| Cumulative depth | Running total from best price to this level (bid or ask side) | Yes                                   |            |
| My orders        | Own working order(s) at this level, if any (size/side)        | Filter-only ("My levels only" toggle) |            |

- **Sort behaviour**: clicking/activating (`Enter`/`Space`) a column header sorts ascending, then descending, then back to the surface's natural default order (tri-state), announced via `aria-sort` on the `<th>`; sort state persists while the table stays open but resets to default when the underlying bar/level focus changes (new focused unit = new default view, avoiding stale-sort confusion).
- **Filter behaviour**: each table exposes a toolbar above the table (standard combobox/checkbox controls, keyboard-operable) for the filter-only columns above (e.g. "Show flagged rows only", "Show estimated rows only", "My levels only") — filters narrow rows shown, never remove columns, and the active-filter state is announced via a live region ("Showing 6 of 40 rows, filtered by: Bid-stacked").
- **Live-data sync**: the table reads from the same windowed data-window query surface as the DOM mirror (§6.1) — it is not a snapshot/export. On each throttled update tick (same cadence as §6.2's ambient live-region throttle, default 1 update/2s, user-configurable), row values are patched in place (cell text content updated, row identity/DOM node preserved) rather than the table being destroyed/rebuilt, so screen-reader focus and any active sort/filter state survive live updates. If the focused bar/level itself is no longer visible (user scrolled the underlying chart away), the table shows a clear "Data is for bar/level X, no longer in view — press Alt+T to refresh to current" banner rather than silently going stale.
- The table alternative is not a stripped-down "compliance minimum" — it exposes the **same data fidelity** as the visual cell so a screen-reader/keyboard-only user is not second-class.
- Table alternative is windowed/paginated for the same performance reasons as the DOM mirror; "load more rows" is a standard, keyboard-operable, focus-preserving control.

### 6.4 Layer 4 — Canvas semantics fallback

- The `<canvas>` element itself carries `role="img"` with a dynamic `aria-label` summarizing current state (e.g. "BTCUSDT 1m chart, 480 bars visible, last close 63,201.5, delta +120") for any AT path that reaches the canvas node directly despite the DOM-mirror overlay, so there is no silent/empty node in the accessibility tree.
- Chart engine unit tests include a check that the canvas's `aria-label` is present and updates on data change (automatable, feeds `03-testing-strategy.md`).

### 6.5 Non-canvas chrome

- All surrounding chrome (toolbars, dialogs, forms, order ticket, admin screens, journal, watchlist) is built with semantic HTML/native controls or full ARIA-pattern-compliant custom components (WAI-ARIA APG patterns for combobox, listbox, tabs, dialog, menu, grid) — **not** re-implemented as unlabeled `<div>` soup. This is a design-system requirement (§8).

## 7. Reduced motion

1. The app respects OS-level `prefers-reduced-motion: reduce` by default (WCAG 2.3.3, AAA — adopted here as a hard requirement given trading-UI seizure/vestibular risk from flashing price/heatmap updates).
2. When reduced motion is active (OS setting or the in-app override `Ctrl+Shift+M`, §3.2):
   - Heatmap "decay/trail" fade animations, big-trade-bubble pop/scale-in, price-flash-on-tick colour pulses, and panel-open/close slide/scale transitions are replaced with instant state changes or a single low-amplitude cross-fade (≤ small opacity delta, no motion/scale).
   - Auto-scrolling/auto-panning behaviours (e.g. chart auto-following live price at the right edge) remain functional (they are not purely decorative) but must not exceed WCAG 2.2.2 (Pause, Stop, Hide) requirements — any auto-moving content lasting >5s has an accessible pause control (this covers replay auto-play, ticker-tape scrollers, and any auto-rotating alert carousel).
3. **No content flashes more than 3 times per second** (WCAG 2.3.1, seizure threshold) — audited explicitly for: big-trade bubble bursts, liquidation-heatmap flash, alert-toast entrance animation, price-flash-on-tick. This is a hard automated + manual gate (see §9), not just a style guideline, given how easy it is for a naive "flash green/red on every tick" implementation to exceed 3Hz on a fast-moving symbol.
4. Reduced-motion is a **design-system token/mode**, not a per-component ad hoc CSS override — every animated component consumes a shared `motion-safe`/`motion-reduce` variant pair (feeds `16-design-system-brief.md`).

## 8. Screen-reader test protocol

### 8.1 Coverage matrix

Combos are pinned versions, not "latest" floating targets, to keep results reproducible; the Accessibility role updates the pinned versions quarterly (or on a forcing NVDA/JAWS/VoiceOver major release) via a dated changelog entry in the regression checklist (§8.2 item 4).

| #   | Platform + OS version | Browser/shell (pinned)                                                   | Screen reader (pinned)                                     | Priority                                                                                                                                    | Cadence                                                                                               | Sign-off owner                                                                                                                                                                 |
| --- | --------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Windows 11 23H2+      | Electron shell (production build, primary AT surface)                    | NVDA 2024.x (latest stable at freeze)                      | P0 — release blocker                                                                                                                        | Every release candidate (RC) and every PR touching an in-scope screen at design/dev handoff           | Accessibility role (named individual in `24-owner-decisions.md` RACI); QA/SDET co-signs the RC checklist                                                                       |
| 2   | Windows 11 23H2+      | Electron shell (production build)                                        | JAWS 2024.x (latest stable at freeze)                      | P1 — must fully pass before R4 (Live-enablement) release, spot-checked (smoke script only, §8.2 item 3 tasks 1-3) every release before that | Full pass: once per R4 gate + every 2 releases thereafter; smoke: every RC from R2 onward             | Accessibility role signs full pass; QA/SDET runs and logs smoke checks                                                                                                         |
| 3   | Windows 11 23H2+      | Chromium (dev/CI headless + manual, matches Electron's Chromium version) | NVDA 2024.x                                                | P0 — fast-iteration gate                                                                                                                    | Automated portion (axe/keyboard-E2E, §9) every PR; manual NVDA spot-check every sprint (not every PR) | Frontend a11y champion (delegate of Accessibility role) for the sprint spot-check                                                                                              |
| 4   | macOS 14 Sonoma+      | Electron shell (production build)                                        | VoiceOver (OS-bundled, version tracks macOS point release) | P1 — full pass before GA (R5); smoke script every release from R4 onward                                                                    | Full pass: once before R5 GA; smoke: every release from R4                                            | Accessibility role signs full pass; owner (primary macOS user, per `24-owner-decisions.md`) does an informal usage check each release as a secondary signal, not a formal gate |

(No mobile/Android screen readers in scope, per locked decision. Safari-direct or non-Electron-browser testing is out of scope — the shipped product surface is exclusively the Electron shell, so all P0/P1 gates test that shell; Chromium-headless (#3) exists only to give CI/dev fast feedback before a full Electron manual pass, not as an independent production target.)

### 8.2 Manual test protocol (run each release candidate, and per new/changed screen at design/dev handoff)

1. **Setup**: fresh profile, default hotkey map, default theme, screen reader at default verbosity. Tester uses keyboard only (no mouse) for the entire pass.
2. **Landmark/structure pass**: open each top-level screen; verify SR "regions"/"landmarks" list matches §3.4.1; verify heading structure is logical (h1 per screen, nested subsection headings, no skipped levels).
3. **Task-based pass** — the tester performs, keyboard+SR only, each of a fixed script of representative tasks per release, e.g.:
   - Switch symbol via Watchlist search, confirm chart updates are announced appropriately (not flooded).
   - Place a limit order via the Order Ticket, confirm size/side/price are announced correctly before submit-confirm, confirm fill/rejection is announced via the assertive live region.
   - Navigate the footprint grid via the DOM mirror (Layer 1) and independently via the "View as table" alternative (Layer 3); confirm data parity between the two.
   - Trigger a rule-engine flatten (simulated) and confirm the resulting position-closed event is announced and focus is not silently stolen.
   - Switch Demo→Live and confirm the confirm-dialog is fully operable and the environment badge change is announced.
   - Open Admin/Users screen, add a manager, assign a permission scope — confirm every form control has a correct accessible name/role/value.
4. **Regression checklist** carried from prior passes is re-run every release (a living checklist file maintained alongside this doc, referenced from `03-testing-strategy.md`).
5. **Defect severity bar**: any task in the script that cannot be completed keyboard+SR-only is a release blocker (P0) for that screen; any awkward-but-completable flow is P1/P2 backlog per normal triage.

### 8.3 Ownership

- The dedicated **Accessibility** role in the UI/UX org owns this protocol, signs off screen-reader passes, and is a required reviewer (or delegates) on any PR touching the chart-engine DOM-mirror layer, live-region logic, or the design-system's a11y primitives.
- QA/SDET incorporates the task script into the manual regression suite before each release per `03-testing-strategy.md` / `07-release-and-prr.md` PRR gates.

## 9. Automated gates (CI-enforced)

1. **axe-core**: run against every screen's DOM (Playwright + `@axe-core/playwright`) in CI on every PR touching frontend code. Zero new "serious"/"critical" axe violations is a merge-blocking check; existing "moderate"/"minor" violations are tracked as backlog tickets with a burn-down target before R3 (Trading on demo).
2. **Lighthouse Accessibility score ≥ 95** on every top-level screen (chart workspace, order ticket, positions, admin/users, journal, watchlist), run in CI against the built Electron-renderer web bundle in headless Chromium; a drop below 95 on any tracked screen fails the build. Score is tracked over time as a dashboard metric (ties into `06-performance-and-load-standard.md`'s CI regression-gate philosophy).
3. **Colour-contrast token linter**: automated script (§5.4) validates every design-token colour pair used for text/UI-components/chart data-ink against the applicable WCAG ratio; runs on any token file change, part of the design-system package's own CI. Implemented by `tools/contrast/generate.mjs` (E05-T05): a declarative pair registry (`tools/contrast/pairs.mjs`) plus a CVD-collapse check emit three CI-gating error codes — `A11Y-C001` (below-threshold pair: measured ratio under the required 4.5:1/3:1/7:1 threshold), `A11Y-C002` (undeclared token: a `color.*` token with no pair-registry entry and no `tools/contrast/exemptions.json` exemption), `A11Y-C003` (CVD collapse: the buy/sell pair or adjacent heatmap ramp stops become indistinguishable, CIE76 dE below the JND floor, under simulated deuteranopia/protanopia/tritanopia). Exemptions require a written `reason` and `owner`, and the gate prints the full exemption list on every run. Output is `packages/ui/build/reports/contrast-matrix.json` + `.md`.
4. **Keyboard-only E2E smoke test**: a Playwright suite that never dispatches a mouse event, driving the task script in §8.2 items 2–3 programmatically (submit an order, switch symbol, toggle table view, trigger the reduced-motion override) — catches keyboard-trap and focus-loss regressions on every PR without needing a human SR pass for every commit.
5. **Motion/flash audit script**: automated check (frame-capture + luminance-delta analysis) run against the heatmap, big-trade-bubble, and price-flash components at a fixed representative high-tick-rate scenario, asserting flash rate stays below the 3/sec threshold (§7.3); run in CI on any change to those components' animation code, and manually spot-checked before each release.
6. **Focus-order/landmark regression snapshot**: an automated snapshot test of the accessibility tree (Playwright `accessibility.snapshot()` or equivalent) per top-level screen, diffed on every PR — unintentional landmark/heading/label changes surface as a reviewable diff rather than silent regressions.
7. **Shipped state (E47-T02)**: the gates are aggregated in the required `a11y` check (`.github/workflows/_job-a11y.yml`; `branch-protection.json` `contexts`). Pass/fail logic is `tools/a11y/gates.py` (codes `A11Y-G001` axe regression, `G002` Lighthouse <0.95, `G003` contrast = `A11Y-C00x`, `G004` keyboard, `G005` flash >=3/s, `G006` a11y-tree drift). Exit 1 = violation, exit 3 = `A11Y-INFRA` (runner failure, never a score failure). axe blocks _new_ serious/critical findings against the shrink-only `tools/a11y/axe-baseline.json` (every entry cites an `A11Y-F…` finding id; CODEOWNERS = Accessibility role). **Break-glass** for an infrastructure outage only: set repo variable `CV_A11Y_INFRA_WAIVER_UNTIL` to an ISO-8601 UTC time at most 24 h ahead; it waives exit 3 only and never a violation. Budgets: per-PR job `timeout-minutes: 12`; nightly sweep < 20 min. Collectors for gates without a landed screen/runner are reported as CI notices (not silently green) until their owning tickets land.
   Collectors (`apps/web/e2e/a11y/*.collect.ts`, `playwright.a11y.config.ts`, `lighthouse.collect.mjs`) emit `reports/a11y/`; a missing collector output is `A11Y-INFRA` (exit 3), never a silent pass. `A11Y-G007` enforces the runtime budget (PR 12 min, measured in-job; nightly full sweep `a11y-nightly.yml` 20 min). The PR screen set lives in `apps/web/e2e/a11y/screens.ts`: the axe, tree, keyboard and flash collectors visit the four screens that render without a session (R-001, R-901, R-902, R-903), because a guarded route visited bare is bounced to `/login` and would be audited as the login page; axe and tree also visit the signed-in R-203 `/settings/appearance`, entered through the shell bootstrap with `/api/v1/me` stubbed at the network layer, and the collector fails if it lands anywhere but that path or its h1 does not render (#3470). Local measurement on the four-screen set: Playwright collectors ~34 s, Lighthouse ~52 s. Tree baselines: `tools/a11y/tree-snapshots/`. The same required check also fails on its `storybook` job (E05-T03), beside the collectors: the design system's Storybook Vitest project runs every story's play function and axe (serious and critical block), proves the gate fails closed on its low-contrast fixture and holds a 10 min budget (`CI-A11Y-002..004`, `docs/ci-runbook.md`).
8. **Gate placement in SDLC**: these checks are "required checks" on `main` per `01-sdlc-and-branching.md`; a PR cannot merge with a failing axe/Lighthouse/keyboard-E2E/motion-audit gate, mirroring the security-scan gates in `04-security-program.md`.

## 10. Accessibility acceptance-criteria template

Every screen/feature ticket in `docs/plan/backlog/*.json` MUST include an `a11y_acceptance_criteria` block using this template (Gherkin-style, consistent with `11-user-stories.md`'s INVEST/Gherkin convention). Ticket authors copy and fill this per feature; blank/boilerplate templates without concrete specifics are a Definition-of-Ready failure per `02-definition-of-ready-done.md`.

```gherkin
Feature: <feature/screen name> — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user performs <primary task> using only the keyboard
    Then every control involved is reachable via Tab/arrow-key navigation
    And every action (including any drag-based interaction) has a documented
      non-drag keyboard equivalent
    And focus is never silently moved by a background data update
    And a visible focus indicator meeting >=3:1 contrast is present at every step

  Scenario: Screen-reader operation
    Given the user is using <NVDA|JAWS|VoiceOver> with the keyboard
    When the user performs <primary task>
    Then all labels, roles, and current values are announced correctly
    And live/streaming data is announced per the polite/assertive rules in
      05-accessibility-standard.md §6.2, without flooding
    And any canvas-rendered data involved has a working DOM-mirror and/or
      "View as table" equivalent with full data parity

  Scenario: Colour-independence
    Given the feature displays buy/sell, bid/ask, P&L, or status state
    When the state is rendered
    Then the state is also conveyed via shape/icon and text, not colour alone
    And the feature passes deuteranopia/protanopia/tritanopia simulation review

  Scenario: Contrast
    Given the feature is rendered in the default dark theme and the
      high-contrast theme
    Then all text meets >=4.5:1 (or >=3:1 for large text) and all meaningful
      non-text UI/chart elements meet >=3:1, per the token contrast matrix

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override)
    When the feature would normally animate
    Then the feature uses the motion-reduce variant with no flashing content
      exceeding 3 times per second and no motion lasting >5s without a pause
      control

  Scenario: Automated gates
    Given the feature's PR is opened
    Then axe-core reports zero new serious/critical violations
    And the affected screen's Lighthouse Accessibility score remains >= 95
    And the keyboard-only E2E smoke test covering this feature's primary
      task passes
```

Each ticket also states: which screen-reader(s) it was manually spot-tested with (may be deferred to the release-level pass in §8 for low-risk tickets, but must say so explicitly), and any documented, owner-approved exception (e.g. "essential exception" dense-data target-size cases per §3.4.7) with its compensating control.

## 11. Design-system requirements (feeds `16-design-system-brief.md`)

The design system is the enforcement mechanism for most of the above — component-level a11y is a design-system responsibility so individual feature teams don't reinvent it:

1. **Token layer**: colour tokens ship pre-validated against contrast ratios (§5) and CVD simulation (§4.2); a token cannot be added to the shared palette without passing the automated contrast linter (§9.3).
2. **Component layer — built-in, not bolted-on**: every design-system atom/molecule/organism (buttons, inputs, selects, tabs, dialogs, menus, tables, tooltips) ships with correct ARIA roles/states/properties, keyboard interaction per WAI-ARIA APG, and a documented focus-management contract, as a condition of being added to the shared library (Definition-of-Done for a design-system component ticket).
3. **Trading-specific components** (order ticket, DOM ladder row, footprint cell, heatmap cell, position row, rule-graph node/edge) are treated as first-class design-system components with the same a11y bar — not exempted as "custom chart stuff"; their a11y contract (roving tabindex, ARIA live wiring, table-alternative data contract) is specified once in the component catalogue (`15-component-catalogue.md`) and reused everywhere the pattern repeats.
4. **Motion tokens**: every animatable property change ships a `motion-safe` and `motion-reduce` pair (§7.4); a component cannot ship with only a hard-coded animation.
5. **Density modes**: the design system defines at least "comfortable" and "compact" density modes; compact mode (used for dense multi-pane trading layouts) must still meet the ≥24px target-size rule or document its essential-exception + alternative per §3.4.7 — density is not an excuse to silently drop below AA.
6. **Documentation requirement**: every component's entry in the design-system docs includes a "keyboard interaction" table and an "accessible name/role" table, generated/checked as part of the component's own test suite (Storybook + axe addon or equivalent) — this is the mechanism that keeps §9's CI gates meaningful at the component level, not just the screen level.
7. **Sign-off gate**: per the brief's "design-ahead" rule, a screen's design ticket cannot move to Status "Done" (unblocking frontend work) without the Accessibility role's sign-off against §4.2 (CVD simulation) and a completed acceptance-criteria template (§10) attached to the design ticket — accessibility is reviewed at design time, not discovered at QA time.

## 12. Cross-references

- `03-testing-strategy.md` — incorporates axe-core, Lighthouse, keyboard-E2E, and manual SR-pass cadence into the test pyramid.
- `04-security-program.md` — authentication/2FA accessibility (WCAG 3.3.8) coordinated with security requirements for login/API-key flows.
- `06-performance-and-load-standard.md` — DOM-mirror/live-region throttling budgets share the same frame-budget discipline as the rendering engine.
- `14-screens-catalogue.md` (not yet written) — the rule-builder node-graph screen's keyboard interaction spec must cross-link to §3.3's hotkey conflict-resolution rules rather than duplicating them (see §3.3 item 6). **Tracking note**: validate this cross-reference resolves correctly once `14-screens-catalogue.md` exists.
- `16-design-system-brief.md` (not yet written) — §11 of this document specifies requirements this brief must satisfy (token layer, component a11y contract, motion tokens, density modes, documentation/sign-off gates). **Tracking note**: validate §11's requirements are fully reflected in that brief once it is written; any gap is a Definition-of-Ready failure for the design-system backlog.
- `14-screens-catalogue.md` — per-screen hotkeys, states, and a11y notes are the concrete instantiation of this standard.
- `15-component-catalogue.md` / `16-design-system-brief.md` — component-level a11y contracts and tokens.
- `26-chart-engine-design.md` — DOM-mirror sync API, canvas `aria-label` requirement, and windowed accessibility-tree strategy are binding engine-design constraints, not optional nice-to-haves.
