# 16 — Design System Brief (CandleViewer)

Date: 2026-09-14 · Owner: basiltt · Status: **Baseline for design & engineering — single source of truth for tokens, theming, motion, density, a11y, Figma, and handoff**

Scope (locked, see `00-planning-brief.md` + `research/24-owner-decisions.md`): web app only — React + TypeScript, custom WebGL chart engine, Electron desktop shell primary. Dark-first, dense professional trading UI. Desktop-only (no responsive/mobile breakpoints; minimum viewport enforced, see §8). Brand-neutral: this brief defines the _system_, not a final brand skin — colours/logo can be swapped without restructuring tokens.

Upstream: `15-component-catalogue.md` (every CMP-* references the token names defined here), `05-accessibility-standard.md` (binding contrast/motion/density requirements this brief must satisfy), `research/digests/10-frontend-tech.digest.md` (chassis/rendering stack), `research/24-owner-decisions.md` decision #10 (heatmap colour convention, configurable).
Downstream: component implementation (Style Dictionary token build), Figma library, `26-chart-engine-design.md` (engine consumes colour/typography tokens for canvas rendering).

---

## 0. How to read this brief

Sections: 1 Design principles · 2 Token architecture · 3 Density modes · 4 Theming (dark-first + light) · 5 Iconography · 6 Data-viz rules · 7 Motion · 8 Layout grid, docking & responsive minimums · 9 Accessibility requirements (brief-level, cross-refs the standard) · 10 Figma library structure & naming · 11 Handoff spec (tokens JSON → code) · 12 Design QA checklist · 13 Design-ahead process & sign-off definition.

---

## 1. Design principles

CandleViewer's UI serves one owner and a handful of account managers running a professional crypto-derivatives trading operation for years. The system optimises for the following principles, in priority order when they conflict:

1. **Legibility of numbers over decoration.** Every pixel spent on chrome is a pixel not spent on price/qty/PnL. Numeric density and scanning speed beat visual flourish. Monospaced tabular numerics everywhere numbers appear in a column.
2. **Never lie by omission.** Estimated/heuristic values are always labelled `(estimated)`. Demo vs Live is never ambiguous. Disabled controls always say why. This is a safety-critical trading tool — the design system is a safety system as much as an aesthetic one.
3. **Density is a mode, not a compromise.** The default working density is _compact_: professional traders want more information per screen, not more whitespace. Compact must still clear WCAG AA — density is achieved via information architecture and typographic scale, never via silently shrinking hit targets below the accessible minimum (see `05-accessibility-standard.md` §3.4.7 and §3 below).
4. **Dark-first, not dark-only.** The primary working environment (multi-hour chart-watching sessions) is dark to reduce eye strain and let colour-coded signal (buy/sell, heatmap, alerts) pop. Light theme exists for admin/settings/daytime use and is a first-class token swap, not an afterthought.
5. **Consistency over novelty.** One button, one input, one table, one dialog pattern reused everywhere (`15-component-catalogue.md`). A trading terminal's speed advantage comes from muscle memory — the system actively resists one-off bespoke controls per screen.
6. **Keyboard and mouse are equally first-class.** Every mouse-driven interaction (chart drag, node-graph connect, drawing tool) ships a keyboard-operable equivalent, not as a compliance afterthought but because keyboard operation is also _faster_ for a power user once learned (§9, `05-accessibility-standard.md` §3).
7. **The chart engine's visual language IS the design system's visual language.** Because everything (candles, footprint, heatmap, profiles, drawings) is fully custom WebGL, there is no separate "charting library skin" to reconcile — chart colours/typography draw from the exact same token set as the rest of the UI, so a themed screenshot of any panel looks native next to any other.

---

## 2. Token architecture

> Architectural record: [`27-adrs/ADR-0024-design-token-architecture-and-theming.md`](27-adrs/ADR-0024-design-token-architecture-and-theming.md) records the binding decisions in this section and §11 (tier model, Style Dictionary build, theming-as-alias-repointing, density-as-alias-step, WebGL/Electron delivery formats) against the merged E05-T01 implementation, plus the alternatives explicitly rejected.

Three-tier token model (industry-standard "global → alias → component" pattern), authored as source-of-truth JSON and compiled via Style Dictionary (§11):

- **Tier 1 — Global/primitive tokens**: raw values, no semantic meaning (`palette.blue.500 = #2B6CE8`, `size.4 = 4px`). Never referenced directly by components.
- **Tier 2 — Alias/semantic tokens**: meaning-carrying names components actually consume (`color.action.primary = {palette.blue.500}`, `color.buy = {palette.green.500}`). This is the layer `15-component-catalogue.md` entries reference (e.g. `color.buy`, `font.mono`, `space.field.gap`).
- **Tier 3 — Component tokens**: rare, only where a component needs an override the semantic layer doesn't express (`button.primary.background = {color.action.primary}`). Used sparingly to avoid token sprawl; most components consume Tier 2 directly.

Naming convention: `category.subcategory.variant.state` all-lowercase dot-delimited (e.g. `color.text.buy`, `color.surface.overlay`, `color.action.primary.hover`). This maps 1:1 to CSS custom properties (`--color-text-buy`) and to the Figma Variables naming (§10).

### 2.1 Colour

**Dark theme is the source of truth**; light theme (§4) is derived by re-mapping the same semantic token names to a different palette, never by introducing new token names.

- **Neutrals (surface/border/text ladder)**: near-black background (`#0B0E11`, not pure `#000000`, per `05-accessibility-standard.md` §5.5 halation/eye-strain guidance), 4-step surface elevation ladder (`surface.app` → `surface.raised` → `surface.overlay` → `surface.canvas` for chart backgrounds specifically, since charts want a very slightly distinct near-black from chrome panels to visually separate data from UI), off-white primary text (`#E8EAED`, not pure `#FFFFFF`), secondary/tertiary text steps down in opacity-equivalent lightness (not literal alpha, to keep contrast math predictable against varying surface tiers).
- **Semantic buy/sell/neutral (the single most important colour decision in the system)**:
  - `color.buy` (green family) / `color.sell` (red family) / `color.neutral` (grey/blue-grey) drive: SideToggle, PriceInput/QtyInput tint, PnLBadge, candle up/down, CVD, order lines, position rows.
  - Two colour-blind-safe green/red pairs are pre-validated (deuteranopia/protanopia/tritanopia simulation, per `05-accessibility-standard.md` §4.2) and every buy/sell instance in the system additionally carries a non-colour cue (▲/▼ glyph, `+`/`-` sign, or explicit "Buy"/"Sell" text) — colour is reinforcement, never the sole signal. **Confirmed unchanged by E05-D07** (2026-09-25): `color.buy.default`/`color.sell.default` (dark default) and `color.buy.hc`/`color.sell.hc` (high-contrast theme) are the two validated pairs; both heatmap ramps' adjacent stops remain separable under all 3 dichromacies — programmatic evidence in `docs/research/artifacts/E05-D07/cvd_simulation.md`, script at `docs/research/_tools/cvd_simulate.py`.
  - Both `color.buy`/`color.sell` and their AAA-stretch high-contrast variants (`color.buy.hc`, `color.sell.hc`, ≥7:1) are defined; the high-contrast theme toggle (`Ctrl+Shift+H`) swaps to the `.hc` variants app-wide.
- **Heatmap colour ramps (configurable convention, owner decision #10)**: two named ramps ship, `heatmap.convention.green-bid-red-ask` (default: green=bid/buy liquidity, red=ask/sell) and `heatmap.convention.red-bid-green-ask` (alternate, user-selectable in Settings, mirroring the DOM ladder screen's own colour-convention setting per `14-screens-catalogue.md`). Each ramp is a 6-stop sequential scale from `surface.canvas` (zero liquidity) through a mid saturation point to a fully-saturated "hot" stop, independently contrast-validated at every stop against the chart background (`05-accessibility-standard.md` §5.4) via an automated per-stop contrast-check script gated in CI on token-file changes (§12).
- **Status/tone ramp**: `color.status.{success,warning,danger,info}` × `{subtle,default,strong}` — used for banners, badges, connection states, risk lockouts. `danger` and `sell` are deliberately distinct hues in the default palette (danger = amber-red, sell = pure red) so "order rejected" (status.danger) is never visually confusable with "you are short" (color.sell) at a glance — this distinction is called out explicitly because both are red-family and is a common trading-UI confusion bug.
- **Chart-specific**: `color.candle.up/down`, `color.footprint.bid/ask/imbalance`, `color.profile.bar/poc/valuearea`, `color.node.{trigger,condition,action,logic,comment}` (rule node-graph), `color.drawing.default/selected`, `color.order.line`, `color.position.entry/sl/tp`. All independently validated at ≥3:1 against `surface.canvas` per `05-accessibility-standard.md` §5.4.
- **Env accent**: `color.env.demo` (blue) / `color.env.live` (red) — reused nowhere else in the palette to keep the Demo/Live signal visually unambiguous and never confusable with buy/sell or status colours.
- **Focus/interaction**: `color.focus.ring` (≥3:1 against every adjacent surface tier, validated per tier, not just once).

### 2.1a Data-confidence tokens (E08-D04, `docs/design/E08/E08-D01.md` vocabulary)

A dedicated `color.data-confidence.<state>.{text,indicator,surface}` semantic-token group (defined in
`packages/ui/tokens/semantic-{dark,light,hc}.tokens.json`) covers the eight states — `live`, `stale`,
`reconnecting`, `disconnected`, `resyncing`, `gapped`, `backfilling`, `delisted` — that every live-data
surface (watchlist, tape, DOM heatmap, chart series, CVD, positions) must express identically. Per the
research handoff, no new primitive colour values were required: each state aliases an existing
`color.status.*` / `color.text.*` / `color.surface.*` token so theming stays a single re-map. `stale` is
the only state with a distinct `surface` tint (`color.surface.sunken`); the rest carry `text` +
`indicator` only, since the indicator is reinforcing and text is the mandatory primary signal
(`docs/design/E08/E08-D01.md` §7). Contrast for every pair is verified programmatically alongside the
existing token proof (`packages/ui/tokens/tests/verify_tokens.py`).

**Precedence and composition rule**: a surface is in exactly one state at a time (highest-severity wins,
order in §2 of the vocabulary doc above); `estimated` (CMP-227) and a data-confidence state are never
merged into one chip — see CMP-227/CMP-239 in `15-component-catalogue.md`. A later ticket needing a state
outside this set of eight opens a design-system change request against `CMP-239`/this section rather than
inventing a local variant (`02-definition-of-ready-done.md` §3.1).

### 2.2 Typography

- **UI family** (`font.family.ui`): **Inter** (variable, OFL-1.1; https://github.com/rsms/inter) — **locked by owner decision 2026-09-25**. Fallback stack `Inter, system-ui, "Segoe UI", sans-serif`. Chosen for x-height and legibility at the 11–13 px sizes dense trading rows use; also Penpot's default font, so design and code share the exact family.
- **Numeric/mono family** (`font.family.mono`): **JetBrains Mono** (variable, OFL-1.1; https://github.com/JetBrains/JetBrainsMono) — **locked 2026-09-25**. Fallback `"JetBrains Mono", ui-monospace, Consolas, monospace`. Used for **every** price, quantity, PnL, percentage, timestamp, and axis label in the app — this is a hard rule (`15-component-catalogue.md` §0.3 cross-cutting rule 6) because columns of numbers must align digit-for-digit for fast scanning, and mixed-width digits in a proportional font actively slow down a trader reading a ladder or positions grid. Chosen over alternatives for its unambiguous `0/O`, `1/l/I` and slightly narrow advance width (more digits per footprint cell).
- **Files shipped** (`packages/ui/src/fonts/`, self-hosted, no CDN — the app has no public-internet dependency): `InterVariable.woff2`, `InterVariable-Italic.woff2`, `JetBrainsMono[wght].woff2`, `JetBrainsMono-Italic[wght].woff2`. The same variable TTFs are uploaded to the Penpot team fonts (`docs/design/README.md`). Weight tokens map to axes: regular 400 · medium 500 · semibold 600 · bold 700.
- **Type scale**: `font.size.{2xs,xs,sm,base,md,lg,xl,2xl}` (8-step, ~1.125 ratio, tuned for dense UI rather than editorial content — the largest step is used only for page `h1`s, never for chart/data content). Line-height tokens (`font.lineHeight.{tight,normal,relaxed}`) — dense trading rows always use `tight`.
- **Weight**: `font.weight.{regular,medium,semibold,bold}` — bold reserved for critical state (Live badge, danger banners, PnL emphasis), not general headings, to keep bold's alarm value meaningful.
- **Tabular numerals**: `font.feature.tabularNums` applied globally to any element consuming `font.family.mono`; this is enforced at the CMP-020 NumericText component level, not left to per-usage CSS.

### 2.3 Spacing

- 4px base unit, scale `space.{0,1,2,3,4,6,8,12,16,24,32,48,64}` (px), i.e. 0/4/8/12/16/24/32/48/64/96/128/192/256 — a single geometric-ish scale shared by both density modes; density modes (§3) select _which_ scale steps a given component's padding/gap tokens resolve to, rather than defining a second parallel scale, keeping the token count bounded.
- Component-level spacing aliases (`space.button.paddingX`, `space.field.gap`, `space.row.height.compact/comfortable`) resolve to specific scale steps per density mode — this indirection is what makes CMP-* "density-aware" per the component catalogue's cross-cutting rule 2.

### 2.4 Radii

- `radius.{none,xs,sm,md,lg,xl,pill,circle}` — xs/sm for inputs and chips, md for cards/dialogs/dock panels, lg for larger surfaces (settings cards, onboarding), pill for tags/toggles, circle for avatars. A single consistent radius scale reused everywhere avoids the "every team invents its own corner rounding" drift common in ad-hoc dashboards.

### 2.5 Elevation

- `elevation.{0,1,2,3,4,5}` — a combined shadow+z-index+(dark-theme-appropriate) subtle-lightening recipe per step, since drop-shadows alone read poorly on near-black surfaces; each step instead primarily raises `surface` lightness slightly and adds a restrained shadow, keeping elevation legible without a "glowing box" look. 0=flush chrome, 1=cards/panels, 2=dock-panel focused state, 3=popovers/tooltips/toasts, 4=dialogs, 5=full-screen scrims (ReconnectOverlay).

### 2.6 Motion

- `motion.duration.{instant,fast,normal,slow}` (0/100/200/400ms) and `motion.easing.{standard,decelerate,accelerate}` — every animatable token pairs with `motion-safe`/`motion-reduce` alternates (§7). No animation is ever load-bearing for information (i.e. a user with `prefers-reduced-motion` never misses information, only the transition polish).

---

## 3. Density modes

Two supported density modes, selectable globally (Settings → Appearance) and per-panel (DensityToggle, CMP-063):

| Mode                                                    | Row height | Field height | Base spacing step | Default surfaces                                                                                  |
| ------------------------------------------------------- | ---------- | ------------ | ----------------- | ------------------------------------------------------------------------------------------------- |
| **Compact** (default for trading surfaces)              | 24px       | 24px         | `space.2` (8px)   | Chart panels, DOM ladder, footprint, positions grid, order ticket, watchlist                      |
| **Comfortable** (default for admin/onboarding/settings) | 32px       | 32px         | `space.3` (12px)  | Admin screens, onboarding wizard, settings, journal analytics (reading-heavy, not scanning-heavy) |

> **UX-research amendment (E05-D07, 2026-09-25):** row/field heights above are the _final, validated_
> values, revised down from an earlier 24/28px and 36/40px proposal to 24/24px and 32/32px to match the
> `size.row.*` / `size.control.*` primitive tokens already shipped in `packages/ui/tokens/primitives.tokens.json`
> (E05-D01). Compact remains exactly the WCAG 2.2 §2.5.8 minimum (24×24px); comfortable clears it with
> +33% headroom. Full rationale, CVD simulation evidence and the essential-exception list:
> `docs/research/density-legibility-cvd-e05-d07.md`.

Rules:

1. Density changes spacing-token resolution only — never component structure, never which information is shown. A component must render identically in both modes except for the spacing/row-height token values it resolves.
2. Compact mode's minimum interactive target is **24×24px** per WCAG 2.2 §2.5.8 (Target Size Minimum). Where a compact-mode control (e.g. a DOM ladder row's inline buy/sell buttons) cannot reach 24px without breaking the row's information density, the **essential-exception** clause applies (dense financial-data UI is an explicitly cited AA exception category) — but only with a documented compensating control: adjacent spacing that prevents accidental mis-taps, and a larger click-tolerance zone than the visual glyph (invisible padding), never a shrink of the true minimum below what a pointer can reliably hit. This exception must be logged per-component in that component's Storybook a11y notes and reviewed by the Accessibility role at design sign-off (§13).
3. Comfortable mode has no exceptions — it always meets the 24px (in practice 40-44px) minimum cleanly, which is precisely why it is the default for lower-frequency, higher-consequence flows like admin/key-management where a mis-click is costlier per action but less frequent overall.
4. Zoom/text-scale (`Ctrl+=`/`Ctrl+-`, up to 200%) composes with density: at high zoom, compact-mode dense tables reflow toward a card/stacked layout per `05-accessibility-standard.md` §5.7 rather than clipping — this reflow behavior is a required state for every CMP-049-based table, tested explicitly (§12).

---

## 4. Dark-first theming + light theme

- **Dark is canonical.** All component design, all contrast validation, and all Figma component variants are authored dark-first; light is generated by re-pointing the same alias tokens (§2.1) at a light-appropriate primitive palette. No component may ship a light-only visual detail that dark lacks or vice versa — parity is enforced by the visual-regression suite running both themes for every component story (`15-component-catalogue.md` §0.3 rule 7).
- **Three theme presets** ship at v1: `dark` (default), `light`, `high-contrast` (a dark-based AAA-leaning variant per `05-accessibility-standard.md` §5.6, swapping body-text and buy/sell tokens to their `.hc` variants, ≥7:1). Theme selection persists per-user (not per-workspace) and is instant (no reload) via CSS-custom-property re-assignment at the document root — the chart engine's WebGL renderer subscribes to the same theme-change event and re-uploads its colour uniforms on switch (a binding requirement passed to `26-chart-engine-design.md`).
- **Runtime contract (E05-T02, `packages/ui/src/theme/`).** The runtime writes `data-theme` (`dark|light|high-contrast`), `data-density` (`compact|comfortable`), `data-motion` (`safe|reduce`) and `data-text-scale` (`100|112|125|150`) on `document.documentElement` and never on a React-owned wrapper, so a switch is a CSS custom-property swap with no remount. Preferences persist in `localStorage["cv.theme.v1"]`; "match system" is off by default; the in-app reduced-motion override (`system|on|off`) wins over `prefers-reduced-motion` in both directions. Text scale sets the root font size (112%, 125%, 150%), so everything sized in `rem` or `em` follows by itself; a unitless or `px` font size in the tokens must multiply by `--cv-text-scale` (1, 1.12, 1.25, 1.5) to follow. No `candleviewer:themechange` event fires for a text-scale-only change, so the chart engine's canvas text cannot follow it yet (open item for #3174 and E11). The legacy `--cv-font-scale` that `apps/web` sets in `preferencesApply.ts` coexists with it until #3139 rewires the app onto this runtime.
- **Engine event (binding for E11).** Once per committed change of the resolved theme, density or motion, `document` receives `CustomEvent("candleviewer:themechange", { detail: { theme, density, motion, themeUniforms } })`: `theme` is `dark|light|high-contrast`, `density` is `compact|comfortable`, `motion` is `safe|reduce`, and `themeUniforms` is the constant `"theme-uniforms"` naming the artefact (`build/engine/theme-uniforms.json`, §11.1) the host adapter reloads for `detail.theme`. The event is not fired for the initial state (read `store.getSnapshot()`), except that `connect()` fires it when the OS preference changed since the store was created and match-system or the `system` motion override resolves differently; it is not fired for text-scale-only changes. Events are delivered oldest first, so the last one matches the final state, except when the 100-event cut-off trips (a handler that keeps changing the theme is cut off and reported); a change made from inside a handler of this event is announced after the current handlers have run, so nested changes coalesce into one event for the final state.
- **Pre-paint snippet and CSP.** To avoid a flash of the wrong theme the shell embeds `THEME_PREPAINT_SCRIPT` byte-for-byte as the only inline script and allows it with `script-src 'self' 'sha256-<THEME_PREPAINT_SCRIPT_SHA256>'`; `'unsafe-inline'` is never acceptable (STRIDE `E05-X01` L3). The hash is pinned by a unit test, so a script edit forces a visible CSP change.
- **Light theme is not an inverted dark theme.** Surfaces don't simply invert lightness; the light palette is separately tuned so text/data contrast ratios hold at the same AA (and AAA-stretch for buy/sell) minimums as dark, because naive inversion routinely produces washed-out or over-saturated results, particularly for the heatmap ramps and candle colours which get re-tuned (not just relit) for light backgrounds.
- **System/OS theme following**: optional "match system" mode is available but not the default (a trading terminal should not silently flip to light mid-session because the OS clock hit sunset while the user is mid-position) — explicit user choice is the default, matching the "no surprising context changes" spirit of WCAG 3.2.

---

## 5. Iconography

- Single icon set, outline style at 16/20/24px optical sizes (`size.icon.sm/md/lg`), 1.5px stroke weight, square-ish bounding boxes for grid alignment in toolbars/menus. Brand-neutral placeholder set: a well-established open icon library (e.g. Lucide/Phosphor-equivalent) as the starting point, swappable as a set at brand-application time since every icon is referenced by semantic `IconName` string (`heart`, `close`, `flatten`, `iceberg`, `chase`, etc.), never by raw SVG inline in component code.
- Trading-domain icons requiring custom authorship (not in generic icon sets): flatten-all, chase-limit, iceberg-order, TWAP, one-click-arm, native-SL-shield, estimated/heuristic-badge glyph, node-graph node-type glyphs (trigger/condition/action/logic-gate/comment), heatmap-convention swap. These are drawn to the same 1.5px-stroke grid as the base set and contributed to the same icon registry.
- Every icon is registered with a canonical name + a short semantic description in the icon registry (feeds CMP-019 Icon's completeness test and Figma's icon component page, §10).
- Decorative-vs-meaningful icon usage is a binding rule, not a style guide suggestion: an icon paired with adjacent visible text is `aria-hidden` (decorative); an icon-only control always carries `aria-label` (meaningful) — enforced by CMP-002/CMP-019's lint rules.

---

## 6. Data-viz rules

These rules bind every chart-engine primitive (CMP-180..199) and every non-canvas chart-adjacent component (sparklines, journal equity curve):

1. **Colour is never the sole encoding.** Direction (buy/sell), status (estimated/confirmed), and category (drawing tool type, node type) always pair colour with shape, icon, pattern-fill, or text.
2. **Sequential ramps (heatmap) are perceptually uniform.** Both heatmap conventions (§2.1) use a ramp interpolated in a perceptually-uniform colour space (e.g. OKLCH/CIELAB-based interpolation, not naive RGB lerp) so equal data-steps look like equal visual-intensity steps — this matters specifically for the liquidity heatmap where a trader is judging relative depth by eye.
3. **Diverging data (delta/CVD/imbalance) uses a diverging ramp anchored at zero**, not two independent sequential ramps stitched together — buy-side and sell-side intensity must be visually comparable at equal magnitude.
4. **Every canvas-rendered data view has a table/list equivalent**, reachable via a documented control (not buried), per `05-accessibility-standard.md` §6 — this is a data-viz rule as much as an a11y rule: if a value can't be expressed in a table row, it's not really been designed yet.
5. **Estimated/heuristic series are visually distinguished at the series level**, not just via a chip — dashed vs solid line, or a lower base opacity for the confirmed-vs-estimated portion of a series (e.g. Deep-M-style regime line rendered dashed while confidence is "low").
6. **No 3D, no unnecessary chart-junk.** No 3D bars/pies, no gratuitous gradients on data marks beyond the deliberate heatmap/diverging ramps above, no drop-shadows on data ink. Every non-data pixel in a chart pane is chrome (axis, legend, grid) and is visually subordinate (lower contrast) to data ink.
7. **Gridlines are structural, not decorative**, and therefore must independently meet the 3:1 non-text contrast minimum where they carry meaning (e.g. session boundaries, POC reference lines) — purely aesthetic background gridlines are minimised/removed rather than exempted, following the density principle (§1.3) that undifferentiated chrome competes with data-ink legibility.
8. **Consistent semantic colour across every surface.** `color.buy`/`color.sell` used in the order ticket are the exact same tokens used in candle colouring, CVD, PnL, and position rows — a trader should never have to re-learn "which red means what" between panels.

---

## 7. Motion

- **Purposeful motion only**: transitions communicate state change (panel focus, value update, dialog open/close) — motion is never purely decorative in a dense trading UI where distracting animation actively costs attention during fast markets.
- **Every animated property ships a `motion-safe`/`motion-reduce` pair** (per `05-accessibility-standard.md` §7.4 and `15-component-catalogue.md` §0.3 rule 5): `motion-reduce` either removes the transition (instant state change) or substitutes a non-motion cue (opacity-only pulse instead of scale+rotate for spinners, static tone-shift instead of shimmer for skeletons).
- **No flashing content exceeding 3 times per second**, and no motion lasting more than 5 seconds without a pause control — binding for any looping animation (connection-reconnecting spinner, live-price pulse).
- **Standard motion recipes** (each with explicit safe/reduce pair):
  - Panel focus/mount: `fast` fade+8px slide, reduce → instant opacity swap.
  - Dialog/drawer open: `normal` scale+fade (dialog) / slide (drawer), reduce → instant.
  - Value flash (price tick up/down): `instant`→`fast` background flash decaying to neutral, reduce → no flash, colour-only momentary text tint instead.
  - Toast enter/exit: `fast` slide+fade, reduce → instant.
  - Node-graph edge draw: `fast` line-draw animation, reduce → instant full-line render.
  - Loading shimmer (Skeleton): `slow` looping shimmer, reduce → static two-tone fill, no loop.
- **Respects `prefers-reduced-motion`** at the OS/browser level automatically, plus an explicit in-app override (Settings → Appearance → Reduce Motion) for users on shared/unconfigured machines (Electron shell) where the OS-level signal may not be set.

---

## 8. Layout grid, docking rules, responsive & minimum sizes (desktop-only)

- **No responsive breakpoints below desktop.** This is a desktop-only professional tool (Electron shell primary, browser dev target secondary) — there is no tablet/mobile layout, no hamburger-menu collapse, no Android (locked scope). The system instead defines a **minimum supported viewport**: **1280×800px**, below which the app shows a "increase window size" advisory state rather than attempting a cramped reflow; **recommended/primary target 1920×1080 and above**, with dense multi-pane layouts (footprint + heatmap + positions + ticket simultaneously visible) assuming ≥2560×1440 as the "comfortable multi-pane" reference resolution cited in the performance budget (`14-screens-catalogue.md` §0.5.7: engine ≥58fps at 2560×1440 with footprint+heatmap).
- **Base layout grid**: a 4px spacing grid underlies all component spacing (§2.3); the docking system itself is **not** a fixed column grid (unlike a marketing site) — panels resize freely along a flexible split-pane tree, snapping to the 4px grid for pixel-perfect alignment between adjacent panel edges only.
- **Docking rules** (implemented by CMP-080 DockPanel / CMP-081 DockGrid):
  1. The workspace is a binary split-tree (each split is horizontal or vertical, recursively nestable) — this is the same model used by VS Code/Dockview-style layout managers, chosen because it's well-understood, keyboard-navigable, and serializable to a saved-workspace JSON.
  2. Panels have a documented `minWidth`/`minHeight` (component-level prop, §"CMP-080") below which they refuse to shrink further — the split-tree instead scrolls or the sibling panel absorbs the constraint, never rendering a panel below its legible minimum (e.g. a footprint pane's minimum width is derived from one legible cell-column plus its axis).
  3. Preset layouts (`Ctrl+1..9`) are named, saved split-trees; a user can save any current arrangement as a new preset. Presets are per-workspace, workspaces are per-user (not shared across managers, since each manager's monitor setup/symbol focus differs).
  4. Floating/undocked panels (e.g. a detached DOM ladder on a second monitor) are supported by the same panel component rendered inside a separate OS-level window (Electron `BrowserWindow`) sharing the same app state via the existing WS/state layer — this is a docking-system requirement, not a separate component.
  5. Panel focus (which panel receives global hotkeys like Buy/Sell/Flatten) is always visually indicated (elevation step-up + accent border, never colour-alone) and is keyboard-settable (`Ctrl+Alt+Arrow` cycles panel focus) independent of mouse hover.
- **Multi-window (multi-monitor) support**: explicitly in scope for the Electron shell given the professional multi-monitor trading-desk use case — the workspace model (§ above) is monitor-count-agnostic; a workspace's split-tree can span declared "window" nodes at the tree root, each opening as its own OS window.

---

## 9. Accessibility requirements

This brief is a _design-time enforcement mechanism_ for `05-accessibility-standard.md`, not a duplicate of it — the standard is binding; this section states what the design system specifically contributes:

1. **Conformance target**: WCAG 2.2 AA baseline, AAA-stretch for buy/sell/critical contrast (§2.1) — inherited directly, not re-derived here.
2. **Token-level enforcement**: no colour token may enter the shared palette without passing the automated contrast linter (checks every token pair that co-occurs in a real component — text-on-surface, chart-mark-on-canvas, heatmap-ramp-stop-on-canvas) and the CVD (colour-vision-deficiency) simulation pass. This gate lives in the token build pipeline (§11), not as a manual design-review step, so it can't be skipped under sprint pressure.
3. **Component-level enforcement**: every CMP-* is delivered with its keyboard-interaction table and accessible-name/role table as part of its own Storybook + axe-addon test suite (`15-component-catalogue.md` §0.3 rule 4/7) — this is the Definition-of-Done for a design-system ticket, not a separate a11y ticket bolted on afterward.
4. **Canvas/WebGL is the highest-risk area** (chart engine, footprint, heatmap, node-graph) and is governed by the three-layer strategy owned by `05-accessibility-standard.md` §6 (DOM-mirror, windowed accessibility tree, always-available non-spatial alternative view) — this brief's obligation is to ensure the _visual_ design of every canvas primitive has a design-time-specified DOM-mirror equivalent (stated per component in `15-component-catalogue.md`), so a designer never ships a canvas mockup without its accessible-equivalent counterpart already sketched.
5. **Motion/density/contrast** requirements are stated in §2, §3, §7 above and are binding equally to §1-8 of `05-accessibility-standard.md`.
6. **Design sign-off is the enforcement checkpoint** (§13) — no screen or component moves to "Done" without the Accessibility role's explicit sign-off against the acceptance-criteria template in `05-accessibility-standard.md` §10, attached to the ticket.

---

## 10. Figma library structure & naming

- **File structure** (separate Figma files, linked via published libraries, mirroring the token/component tiers):
  1. `CandleViewer — Foundations` — Figma Variables for every Tier-1/Tier-2 token (§2), organised into Variable Collections: `Color/Dark`, `Color/Light`, `Color/HighContrast` (three modes of one Colour collection, matching the token build's theme-swap model), `Typography`, `Spacing`, `Radius`, `Elevation`, `Motion`. Variables are named identically to the code token names (`color/text/buy`, not a separate design-only naming scheme) so the Figma→code diff is mechanical, not interpretive.
  2. `CandleViewer — Components (Atoms & Molecules)` — one page per catalogue band (`Atoms`, `Molecules`), one Figma component (with variants for every documented Variant/State) per CMP-* ID, named `CMP-0xx / ComponentName` in the layer/component name so the mapping to the catalogue is unambiguous; component descriptions in Figma copy the catalogue's Props/A11y summary verbatim.
  3. `CandleViewer — Components (Organisms & Trading)` — same pattern for the chrome/organism and trading-specific bands; trading components additionally carry a "Data contract" note block linking to the relevant WS/REST topic from `14-screens-catalogue.md` §0.4.
  4. `CandleViewer — Chart Engine Primitives` — static representative frames for CMP-180..199 (since these are rendered, not literally Figma-vector components) — these are annotated reference mockups (one static frame per state: e.g. footprint at 3 zoom levels showing LOD text-hiding) used to brief the engine team, not literal design-to-code components.
  5. `CandleViewer — Screens` — one frame per SCR-* from `14-screens-catalogue.md`, assembled from published components only (no local overrides/detaches permitted outside a documented "spike" page) — this is the enforcement mechanism keeping design and the component library from drifting apart.
  6. `CandleViewer — Rule Engine & Node Graph` — dedicated file for the dual rule-editor UX (form editor + node-graph editor) given its scope, cross-referencing CMP-140..159.
- **Naming conventions**:
  - Figma pages: `00 Cover`, `01 Foundations`, `02 Components`, `03 Patterns`, `04 Screens`, mirroring the doc numbering style used across `docs/plan/`.
  - Component naming: `CMP-0xx · ComponentName / Variant=X, Size=Y, State=Z` using Figma's native variant-property syntax so the variant matrix is inspectable directly in the Figma "Variants" panel, matching the catalogue's Props/Variants/States fields exactly.
  - Auto-layout is mandatory on every component (no absolutely-positioned component internals) so resizing behaviour in Figma matches the CSS flex/grid behaviour in code — this is what makes the density-mode token-swap (§3) demonstrable in Figma via variable-mode switching alone, without separate compact/comfortable component variants.
  - Icons library: one Figma component per `IconName` in the registry (§5), named `icon/{name}`, matching the code registry key 1:1.
- **Worked naming examples** (concrete, so a designer can start a new component file today without a follow-up question):
  1. **CMP-001 Button** (atom): Figma component named `CMP-001 · Button / Variant=Primary, Size=Md, State=Default`, living on page `02 Components` inside file `CandleViewer — Components (Atoms & Molecules)`, frame group `Atoms/Button`. Every documented Variant (`primary/secondary/ghost/danger/buy/sell`) × Size (`sm/md/lg`) × State (`default/hover/focus-visible/active/disabled/disabled-with-reason/loading`) combination is one entry in that single component's Figma variant matrix — not separate top-level components — so the "AllVariants" Storybook story and the Figma variant grid are the same enumeration.
  2. **CMP-107 OrderTicket** (trading organism): Figma component named `CMP-107 · OrderTicket / Env=Live, OrderType=Limit, State=Idle`, living on page `02 Components` inside file `CandleViewer — Components (Organisms & Trading)`, frame group `Trading/OrderTicket`; its description field is copied verbatim from the catalogue's Props/A11y/Data-contract summary, and it carries a red `LIVE` frame-border annotation (matching the code's env-banner treatment) whenever `Env=Live` is selected, so a reviewer scanning the page never mistakes a Live-env mock for a Demo one.
  3. **CMP-193 HeatmapOverlay** (chart-engine primitive): since this is a static representative frame rather than a literal Figma component, it is named `CMP-193 · HeatmapOverlay — ref frame (zoom=1x)`, `CMP-193 · HeatmapOverlay — ref frame (zoom=4x, LOD-hidden-text)`, etc. (one ref-frame per state), living on page `01 Chart Primitives` inside file `CandleViewer — Chart Engine Primitives`; each ref frame's Figma description explicitly restates the CMP-111/CMP-193 responsibility split from `15-component-catalogue.md` so engine-team readers land on the correct owning entry.
- **Interactive prototyping**: key flows (order submission with confirm-gate, Demo→Live switch, rule arm flow, replay scrub) are wired as Figma prototypes for design-review walkthroughs, but prototypes are a review aid, not a spec — the written component entries in `15-component-catalogue.md` remain the binding source of truth for behaviour.

---

## 11. Handoff spec: tokens JSON → code via Style Dictionary

> Architectural record: [`27-adrs/ADR-0024-design-token-architecture-and-theming.md`](27-adrs/ADR-0024-design-token-architecture-and-theming.md) — see §2 above for the cross-link note.

- **Source of truth**: a single `tokens/` directory of JSON files (one file per Tier-1 category: `color.tokens.json`, `typography.tokens.json`, `spacing.tokens.json`, `radius.tokens.json`, `elevation.tokens.json`, `motion.tokens.json`) using the [W3C Design Tokens Community Group format](https://design-tokens.github.io/community-group/format/) (`$value`/`$type`/`$description` keys) so the format is tool-agnostic and importable by both Figma's Variables (via a Tokens Studio-compatible plugin) and Style Dictionary.
- **Build pipeline** (Style Dictionary, run in CI on every `tokens/` change):
  1. **CSS custom properties** output (`build/css/tokens.css`) — one file per theme mode (`tokens.dark.css`, `tokens.light.css`, `tokens.high-contrast.css`), each defining the full `--color-*`/`--space-*`/etc. custom-property set under a `[data-theme="dark"]` selector root; the app's theme switch (§4) is a single `data-theme` attribute change on `<html>`.
  2. **TypeScript token object** output (`build/ts/tokens.ts`) — typed `const tokens = {...} as const` plus generated `type ColorToken = keyof typeof tokens.color` etc., so component prop types (e.g. `NumericText`'s `format`/colour props) can be statically checked against real token names, catching typo'd token references at compile time rather than as a silent CSS custom-property miss at runtime.
  3. **Chart-engine uniform buffer** output (`build/engine/theme-uniforms.json`) — a flattened numeric-RGBA representation of every `color.chart.*`/`color.candle.*`/`color.footprint.*`/`color.heatmap.*`/`color.node.*` token, consumed directly by the WebGL renderer's shader uniforms (per `26-chart-engine-design.md`'s binding requirement in §4 above) — this is the one output format that exists specifically because the chart engine can't consume CSS custom properties directly inside a WebGL context.
  4. **Contrast-matrix report** (`build/reports/contrast-matrix.json` + human-readable `.md`) — generated by the automated contrast-check script (§9.2, `05-accessibility-standard.md` §5.4) as part of the same build step; CI fails the token-file PR if any required pair drops below its threshold (4.5:1 text, 3:1 non-text/chart-ink, 7:1 buy/sell-hc). Implemented at `tools/contrast/generate.mjs` (E05-T05, run via `pnpm --filter @candleviewer/ui contrast:gate`, wired into the `js` CI lane's `build` job on `packages/ui/tokens/**`/`tools/contrast/**` changes) — see `05-accessibility-standard.md` §9 item 3 for the `A11Y-C001`/`A11Y-C002`/`A11Y-C003` error codes and the exemption policy.
  5. **Electron main-process JSON** output (`build/electron/tokens.main.json`) — a plain flattened key→value JSON (no CSS/TS syntax) consumed by the Electron main process for chrome that isn't rendered by the React renderer (native window title-bar colour, tray-icon theme, OS-level dark/light hint), so the main process never has to parse CSS or import TypeScript to know the current theme's surface colour.
  - **Exact Style Dictionary config** (`style-dictionary.config.json`, top-level shape, illustrative of the real repo file):

```json
{
  "source": ["tokens/*.tokens.json"],
  "platforms": {
    "css": {
      "transformGroup": "css",
      "buildPath": "build/css/",
      "files": [
        {
          "destination": "tokens.dark.css",
          "format": "css/variables",
          "filter": { "theme": "dark" },
          "options": { "selector": "[data-theme=\"dark\"]" }
        },
        {
          "destination": "tokens.light.css",
          "format": "css/variables",
          "filter": { "theme": "light" },
          "options": { "selector": "[data-theme=\"light\"]" }
        },
        {
          "destination": "tokens.high-contrast.css",
          "format": "css/variables",
          "filter": { "theme": "high-contrast" },
          "options": { "selector": "[data-theme=\"high-contrast\"]" }
        }
      ]
    },
    "ts": {
      "transformGroup": "js",
      "buildPath": "build/ts/",
      "files": [{ "destination": "tokens.ts", "format": "typescript/es6-declarations" }]
    },
    "engine": {
      "transformGroup": "js",
      "buildPath": "build/engine/",
      "files": [
        {
          "destination": "theme-uniforms.json",
          "format": "json/flat-rgba",
          "filter": { "category": "chart" }
        }
      ]
    },
    "electron": {
      "transformGroup": "js",
      "buildPath": "build/electron/",
      "files": [{ "destination": "tokens.main.json", "format": "json/flat" }]
    }
  }
}
```

This config is the binding contract for what "run the token build" produces; `json/flat-rgba` and `json/flat` are project-custom Style Dictionary formats registered in `tools/style-dictionary/formats/` (not built-in SD formats), documented alongside the config file itself so a new engineer can find both in one place.

- **Build-target summary** (every output artefact produced by one `style-dictionary build` run, one row per consumer):

| Target                   | Output path                                  | Format                        | Consumer                                                    |
| ------------------------ | -------------------------------------------- | ----------------------------- | ----------------------------------------------------------- |
| CSS vars (dark)          | `build/css/tokens.dark.css`                  | `css/variables`               | React app, `[data-theme="dark"]`                            |
| CSS vars (light)         | `build/css/tokens.light.css`                 | `css/variables`               | React app, `[data-theme="light"]`                           |
| CSS vars (high-contrast) | `build/css/tokens.high-contrast.css`         | `css/variables`               | React app, `[data-theme="high-contrast"]`                   |
| TS token object          | `build/ts/tokens.ts`                         | `typescript/es6-declarations` | React components, Storybook, type-checked imports           |
| Engine uniform buffer    | `build/engine/theme-uniforms.json`           | custom `json/flat-rgba`       | WebGL chart-engine shader uniforms                          |
| Electron main JSON       | `build/electron/tokens.main.json`            | custom `json/flat`            | Electron main process (title-bar, tray icon, OS theme hint) |
| Contrast report          | `build/reports/contrast-matrix.json` + `.md` | custom `json`/`markdown`      | CI gate + human review                                      |

- **Versioning**: the `tokens/` directory is versioned independently (its own CHANGELOG, semver) from the component library, since a token-only change (e.g. re-tuning the heatmap ramp after a spike finding) should be shippable and reviewable without touching component code.
- **Consumption contract**: React components import from the generated `build/ts/tokens.ts` (never hardcode a hex/px value); Storybook's theme-switch addon toggles the `data-theme` attribute using the generated CSS bundles for visual-regression parity across themes (`15-component-catalogue.md` §0.3 rule 7).
- **Figma↔code sync direction**: tokens flow **design→code** as the primary direction (designer edits Figma Variables via the Tokens Studio plugin, exports to the `tokens/` JSON, opens a PR) with an occasional **code→design** reverse sync for engineering-driven token additions (e.g. a new chart-engine-only token discovered during the WebGL spike) re-imported into Figma Variables — both directions go through the same JSON files and the same PR/review process, so there is exactly one source of truth file format regardless of which side initiates a change.

### 11.1 Handoff contract detail (E02-D01)

The following is the ratified handoff contract agreed ahead of `packages/ui` scaffolding
(`E02-T03`), so E05's authored token values land in a pipeline shaped by agreement, not guesswork.
Full rationale and open questions: `docs/design/E02/E02-D01.md`.

**Directory layout** (`packages/ui/tokens/`): one Tier-1 file (`primitives.tokens.json`), one Tier-2
file per theme (`semantic-dark.tokens.json` — source of truth, `semantic-light.tokens.json`,
`semantic-high-contrast.tokens.json`), one Tier-3 file (`component.tokens.json`), one file per density
mode (`density-compact.tokens.json`, `density-comfortable.tokens.json`), and `themes.json` declaring
which files compose each named theme. A theme file re-maps the _same_ Tier-2 names to different Tier-1
references — it never introduces new token names. A density file overrides only spacing/sizing Tier-2
tokens, never colour or typography; theme and density compose independently.

**Naming edge case**: where a Tier-2 group needs both children and a base value (e.g. `color.buy` needs
`.hover`/`.subtle`/`.hc` _and_ a default), the base leaf is named `color.buy.default` — a token path
cannot be both an object and a value.

**Lint rule (Tier 1 isolation)**: a build-time lint step (`tools/style-dictionary/lint-tier1-refs.*`,
implemented in E02-T03, run in the `packages/ui` package CI) fails the build if any component/screen
spec, Tier-3 file, or generated-`tokens.ts` consumer references a Tier-1 path (`palette.*`, `space.<n>`,
`size.<n>`, `radius.<n>`, `border.<n>`, `font.<n>`, `opacity.<n>`) outside of a Tier-2/Tier-3 `$value`
alias, or hardcodes a hex/px literal where a token exists.

**Engine export shape** (binding on `E02-T03`): `build/engine/theme-uniforms.json` is flat and fully
resolved (no `{alias}` left unresolved); every colour token relevant to the engine
(`color.chart.*`/`color.candle.*`/`color.footprint.*`/`color.heatmap.*`/`color.node.*`/`color.buy.*`/
`color.sell.*`) is an object carrying both a hex string and normalised float RGBA:

```json
{ "color.buy.default": { "hex": "#2EBD59", "rgba": [0.1804, 0.7412, 0.349, 1.0] } }
```

Spacing/typography tokens not needed for canvas rendering are excluded from this export (layout spacing
is a host-adapter/DOM concern). **Theme switching for the engine is a data swap, not a CSS cascade**:
the host adapter loads the resolved uniform file for the active theme and calls the engine's typed
"set theme" API; the engine never reads `data-theme` or any DOM/CSS state (C-2.16). Downstream tickets
(e.g. E11) must not assume a CSS cascade drives engine colour.

**Two worked examples** (Tier 1 → Tier 2 → every output, using the values already shipped in
`packages/ui/tokens/primitives.tokens.json` / `semantic-dark.tokens.json` by E05-D01):

|          | `color.buy`                                                                                                                                              | `space.field.gap`                     |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| Tier 1   | `palette.green.500 = "#2EBD59"`                                                                                                                          | `space.2 = "8"`                       |
| Tier 2   | `color.buy.default = "{palette.green.500}"` (+ `.hover→palette.green.400 #4FC86F`, `.subtle→palette.green.900 #0E3D1F`, `.hc→palette.green.300 #6BD48A`) | `space.field.gap = "{space.2}"`       |
| CSS      | `--color-buy-default: #2EBD59;` under `[data-theme="dark"]`                                                                                              | `--space-field-gap: 8px;`             |
| TS       | `tokens.color.buy.default === "#2EBD59"`                                                                                                                 | `tokens.space.field.gap === "8"`      |
| Engine   | `{ "hex": "#2EBD59", "rgba": [0.1804, 0.7412, 0.3490, 1.0] }`                                                                                            | not exported (colour/typography only) |
| Contrast | `.default` ≥3:1 on `surface.canvas` (chart data-ink); `.hc` ≥7:1 (AAA stretch, high-contrast theme)                                                      | N/A                                   |

**Accessibility gate**: every semantic colour pair carries its stated minimum ratio per
`05-accessibility-standard.md` §5 (4.5:1 body text / 3:1 large text / 3:1 non-text-UI / 3:1 chart
data-ink / 7:1 buy-sell-hc AAA stretch); the contrast-matrix report (§11 build table) is generated on
every token-file PR and CI fails if a required pair drops below threshold. The high-contrast theme is a
first-class theme file (`semantic-high-contrast.tokens.json`), not an overlay/filter.

**Sign-off** (recorded on issue #88, gating this ticket's own Done per §13.3): CDO or delegate, chart-
engine owner, frontend lead, accessibility specialist.

---

## 12. Design QA checklist

Applied to every component ticket and every screen ticket before it can move to Status "Done" (feeds `02-definition-of-ready-done.md`'s design-specific DoD clause):

**Tokens & visual**

- [ ] Uses only published Tier-2/Tier-3 tokens — zero hardcoded hex/px values in the spec or the implementation.
- [ ] Verified in all three themes (dark, light, high-contrast) at both density modes (compact, comfortable) — visual parity confirmed, no theme/density-specific layout breakage.
- [ ] Passes the automated contrast-matrix check for every colour pair it introduces or touches.
- [ ] CVD (colour-blindness) simulation reviewed for any new colour-carrying state.

**Behaviour & states**

- [ ] Every documented State (default/hover/focus/active/disabled/loading/error/empty) has a corresponding Figma variant and Storybook story.
- [ ] Disabled states use the disabled-with-reason pattern (CMP-079), never a bare disabled control, for any RBAC/env-gated action.
- [ ] Loading/empty/error states are explicitly designed, not left as "the same as default but greyed out."

**Accessibility**

- [ ] Keyboard-interaction table completed and matches an implemented, tested keyboard path (not aspirational).
- [ ] Accessible-name/role table completed.
- [ ] For any canvas/WebGL-adjacent component: DOM-mirror/windowed-tree/non-spatial-alternative strategy explicitly specified per `05-accessibility-standard.md` §6, not deferred to "engineering will figure it out."
- [ ] Motion-safe/motion-reduce pair specified for any animated property.
- [ ] Hit targets meet the 24px minimum (compact) / 40-44px (comfortable), or an essential-exception is logged with its compensating control.
- [ ] Accessibility role has signed off (§13).

**Trading-specific safety**

- [ ] Any component touching order placement, position modification, or rule arming states its confirm-gate variant (standard/typed/hold) explicitly and the keyboard-only path for that gate is tested.
- [ ] Any heuristic/estimated value is chip-tagged and links to its methodology InfoPanel.
- [ ] Demo/Live env context is visually unambiguous wherever the component can trigger a trading action.

**Consistency**

- [ ] Reuses an existing CMP-* rather than introducing a near-duplicate (checked against the catalogue index before a new ID is requested).
- [ ] Storybook stories match the full Variants × States matrix stated in the catalogue entry.
- [ ] Component or screen composes only published-library Figma components (no local detached overrides).

---

## 13. Design-ahead process & sign-off definition

Per `00-planning-brief.md` §"Team & cadence": **design runs ahead of engineering by ≥2 sprints; no frontend screen work starts until its design ticket is Status "Done."** This section defines exactly what "Done" means for a design ticket, since that gate is the mechanism enforcing the whole design-ahead rule.

### 13.1 Design ticket lifecycle

`Backlog → Ready → In Progress → In Review → In Test → Done` (same board/statuses as engineering tickets, per the project schema in `00-planning-brief.md` — design and engineering share one Kanban so dependency/blocking relationships between a design ticket and its downstream engineering ticket are visible in one place, not tracked in a separate design tool).

### 13.2 Definition of Ready (a design ticket may enter "In Progress")

- Linked user story/stories (`11-user-stories.md`) with acceptance criteria exist.
- Linked screen entry in `14-screens-catalogue.md` (or component entry in `15-component-catalogue.md`) exists with at least a draft purpose/data/interaction sketch.
- Any research open-question blocking the design (e.g. an unresolved Bybit API behaviour) is either resolved or explicitly flagged as an assumption the design proceeds under.

### 13.3 Definition of Done (a design ticket may move to "Done," unblocking engineering)

A design ticket is **Done** only when **all** of the following are true and attached to the ticket:

1. **Figma artefact** complete: all states/variants for the screen or component, composed only from published-library components (§10, §12 consistency checklist).
2. **Component catalogue / screen catalogue entry updated** to match the final Figma artefact exactly (this document and `15-component-catalogue.md`/`14-screens-catalogue.md` are living documents kept in lockstep with design output, not a one-time snapshot).
3. **Accessibility role sign-off** attached: completed acceptance-criteria template (`05-accessibility-standard.md` §10) plus CVD-simulation review (§4.2 of that standard) — this is the specific, named gate the standard itself declares mandatory (§11.7 of `05-accessibility-standard.md`), restated here as the operational sign-off step.
4. **Design QA checklist (§12) completed** and attached, with any essential-exceptions explicitly logged rather than silently accepted.
5. **Data/API contract confirmed** for trading-specific and chart-primitive components: the Figma spec's data fields match the WS topic/REST endpoint shape named in `14-screens-catalogue.md` §0.4 or the component's own "Data contract"/API sketch in `15-component-catalogue.md` — prevents a design that quietly assumes data the backend doesn't (yet) provide.
6. **Chief Design Officer (or delegated design lead) sign-off** — final design-quality gate, confirming principle alignment (§1) and cross-screen consistency.
7. Ticket's linked downstream engineering ticket(s) are updated with a link to the now-final Figma artefact and catalogue entry, and are moved from "Backlog" to "Ready" (this is the literal unblocking action — engineering's own Definition of Ready, per `02-definition-of-ready-done.md`, requires this link to exist before an engineering ticket can start).

### 13.4 Spike-first exception

Per `research/24-owner-decisions.md` §2 ("mandatory spikes before design sign-off"), four engineering spikes (WebGL engine core, QuestDB vs TimescaleDB, Bybit WS client, multi-account fan-out latency) must complete **before** the corresponding chart-engine-primitive (CMP-180..199) and trading-critical (CMP-100..139 fan-out-related) component designs can be marked Done — a design ticket in this category carries an explicit `blocked_by: SPIKE-*` dependency and cannot reach "Done" while its spike is open, since the spike's findings (e.g. actual achievable footprint-cell density) are load-bearing inputs to the component's final prop/API surface.

### 13.5 Change control after sign-off

Once Done, a component/screen design is versioned like code: a change request re-opens the ticket (or opens a new linked ticket referencing the CMP-_/SCR-_ ID), goes through the same §13.3 checklist again, and any already-in-progress engineering work is flagged for re-sync rather than silently diverging from an updated Figma artefact — the catalogue documents (`15-component-catalogue.md`, this file) are the arbitration source when Figma and shipped code disagree, pending the next sync PR.

---

## 14. Cross-references

- `15-component-catalogue.md` — every token named here is consumed by a CMP-* entry; the catalogue's "Tokens used" field is the enforcement checkpoint that no component invents its own ad-hoc styling.
- `05-accessibility-standard.md` — binding a11y requirements this brief operationalises into tokens, density rules, and the sign-off gate (§13.3.3).
- `14-screens-catalogue.md` — screens consume components per §10's Figma "Screens" file discipline; §0.4's WS/REST topic table is the data-contract reference for §13.3.5.
- `26-chart-engine-design.md` — receives the theme-uniform token output (§11.2c) and the DOM-mirror/windowed-a11y binding constraints (§9.4).
- `02-definition-of-ready-done.md` — this brief's §13.3 is the design-specific instantiation of that document's cross-discipline Definition of Done.
- `research/24-owner-decisions.md` — heatmap colour convention (decision #10, §2.1 here) and mandatory pre-sign-off spikes (§13.4 here).

### Validated palette status (E47-T03)

The data-ink palette (heatmap bid/ask ramps, delta divergence ramp, profile histogram, liquidation intensity, plus
candle/footprint/buy-sell/imbalance CVD pairs) is validated by `tools/contrast/data-ink.mjs` across 3 themes x 2 densities.
Gradients are sampled at N>=16 stops (`--stops`); high-contrast holds body text to 7:1; compact density raises the
large-text axis label to 4.5:1. CVD transform: Brettel/Vienot dichromacy projection (`tools/contrast/color-math.mjs`,
seeded by `docs/research/_tools/cvd_simulate.py`) with discriminability = CIE76 dE >= `CVD_JND_FLOOR` (5.0).
The matrix (`packages/ui/contrast/data-ink-matrix.{json,md}`) is generated, checked in, and a stale copy fails the
`contrast:gate` (A11Y-C007). Current failures are listed in `tools/contrast/data-ink-baseline.json` and are fixed by
E47-S06; the gate fails on any failure not in that baseline. Palette status: not yet fully conformant (see matrix).
Gradient sampling uses the shared sRGB piecewise-linear ramp until chart-engine layers (E06/E11) export their own.

### E47-S06 palette remediation and no-hue-alone gate

All T03 failing pairs/stops are fixed by token retune (no per-component overrides): heatmap ramps are monotonic and >= 3:1 from the first visible stop in all themes; high-contrast tertiary text, on-action text and primary action reach 7:1; a CVD-safe palette (`color.cvd.*`, blue/orange, selectable on SCR-116) is validated by `tools/contrast/data-ink.mjs`. `tools/contrast/encodings.json` is the encoding inventory; `tools/contrast/no-hue-alone.mjs` fails the build naming surface and encoding (A11Y-C008). The known-failing baseline is now empty.
