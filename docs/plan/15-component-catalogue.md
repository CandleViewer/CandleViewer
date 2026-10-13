# 15 — Component Catalogue (CandleViewer Design System)

Date: 2026-09-14 · Owner: basiltt · Status: **Baseline for design & engineering — single source of truth for design-system + trading + chart-engine components**

Scope (locked, see `00-planning-brief.md` + `research/24-owner-decisions.md`): web app only — React + TypeScript, custom WebGL chart engine, Electron desktop shell primary. RBAC-gated owner/admin screens live inside this app. No Android. No separate admin app. Bybit v5 USDT linear perpetuals only.

Upstream: `14-screens-catalogue.md` (screens reference components by CMP-* name), `10-personas.md`, `05-accessibility-standard.md` (component-level a11y contract, §11), `research/digests/10-frontend-tech.digest.md` (chassis: TradingView Lightweight Charts v5 primitives + dedicated WebGL/PixiJS heatmap layer), `research/digests/04-deepcharts-deepchart.digest.md` + `05-deepcharts-deepdom-gamma.digest.md` (order-flow feature surface), `research/digests/09-execution-risk-tools.digest.md` (execution/risk UX).
Downstream: `16-design-system-brief.md` (tokens, theming, Figma, handoff), `26-chart-engine-design.md` (engine internals), `backlog/*.json` (design-system tickets, one per component or tight family).

Target: the brief's stated planning target was **120–180 components**; this catalogue **locks a final count of 238** (IDs `CMP-001..238`), superseding the range for this deliverable — see §8 for the rationale and the explicit decision (no further consolidation is planned or required; 238 is the number backlog tickets are generated from). IDs are `CMP-nnn`, stable and permanent, non-contiguous numbering (gaps reserved per band).

---

## 0. How to read this catalogue

### 0.1 Entry template
Every component entry states: **ID** `CMP-nnn` · **Name** · **Tier** (Atom / Molecule / Organism / Chart-primitive) · **Purpose** · **Props** (name: type — default — notes) · **Variants** · **States** · **A11y** (role, keyboard, ARIA, focus contract) · **Tokens used** (references `16-design-system-brief.md` token names) · **Storybook stories** · **Test requirements** (unit, visual regression, axe, interaction). Trading-specific and chart-primitive components additionally state **API sketch** (TS interface) and **Data contract** (props/events tied to WS/REST shapes from `14-screens-catalogue.md` §0.4).

### 0.2 ID bands
| Band | Tier / Area |
|---|---|
| CMP-001..039 | Atoms (buttons, inputs, typography, icons, badges, indicators) |
| CMP-040..069 | Molecules (form fields, menus, tooltips, toasts, tabs, cards) |
| CMP-070..099 | Organisms — chrome & navigation (app shell, panels, dialogs, tables) |
| CMP-100..139 | Trading-specific molecules/organisms (order ticket, DOM row, footprint cell, positions grid, etc.) |
| CMP-140..159 | Rule engine & node-graph components |
| CMP-160..179 | Watchlist / alerts / journal / audit row components |
| CMP-180..199 | Chart-engine primitives (series, panes, axes, overlays, drawings) |
| CMP-200..238 | Auth surfaces, shell furniture, chart chrome, rule-editor chrome (added in the traceability reconciliation, §7A) |

### 0.3 Cross-cutting rules (apply to every component; not repeated per-entry unless overridden)
1. **Dark-first**: every component is designed against the dark theme token set first; light theme is a token swap only, never a separate layout (`16-design-system-brief.md` §4).
2. **Density-aware**: every component supports `density: "comfortable" | "compact"` (default `compact` for trading surfaces, `comfortable` for admin/settings/onboarding) driving spacing-token selection only — no layout branching.
3. **Colour-never-alone**: any component conveying buy/sell/long/short/status/risk state pairs colour with icon/shape and text per `05-accessibility-standard.md` §4.
4. **Keyboard contract**: every interactive component is reachable via `Tab`/`Shift+Tab`, operates via `Enter`/`Space`/arrows per WAI-ARIA APG pattern, ships visible focus ring (`focus-ring` token, ≥3:1, 2px offset), and documents its keyboard table in Storybook (a11y addon) as a Definition-of-Done gate (`05-accessibility-standard.md` §11.6).
5. **Motion pair**: any animated property ships `motion-safe`/`motion-reduce` variants (`16-design-system-brief.md` §7).
6. **Numeric typography**: all price/qty/PnL/percentage values render in the monospaced numeric font family with tabular-nums, right-aligned in tables, using the semantic colour tokens (`text-buy`, `text-sell`, `text-neutral`).
7. **Test requirement baseline** (all components): unit tests (props/variants/states) via Vitest + Testing Library; visual regression via Storybook + Chromatic (or equivalent) baselines per variant × theme (dark/light) × density; axe-core zero serious/critical violations in CI; interaction tests (Testing Library `user-event`) covering keyboard paths. Trading-specific/chart-primitive components additionally require a performance budget test (render/update under load) and, where canvas-backed, an accessible-DOM-mirror parity test.
8. **Storybook organisation**: `Atoms/*`, `Molecules/*`, `Organisms/*`, `Trading/*`, `RuleEngine/*`, `ChartEngine/*` — mirrors the ID bands above.

---

## 1. Atoms (CMP-001..039)

### CMP-001 Button
- **Tier**: Atom · **Purpose**: primary interactive trigger for all actions.
- **Props**: `variant: "primary"|"secondary"|"ghost"|"danger"|"buy"|"sell"` (default `secondary`) · `size: "sm"|"md"|"lg"` (default `md`) · `iconLeft?/iconRight?: IconName` · `loading?: boolean` · `disabled?: boolean` · `disabledReason?: string` (renders tooltip per RBAC-deny rule) · `fullWidth?: boolean` · `onClick`.
- **Variants**: primary, secondary, ghost, danger (destructive, requires confirm wrapper), buy (green, used only in trading contexts), sell (red).
- **States**: default, hover, focus-visible, active/pressed, disabled, disabled-with-reason, loading (spinner replaces label, width locked to prevent reflow).
- **A11y**: role `button` (native `<button>`), `aria-disabled` + `aria-describedby` pointing at reason tooltip when disabled-with-reason (never purely `disabled` attribute for RBAC denies, so the tooltip stays reachable), `aria-busy` when loading. Keyboard: `Enter`/`Space` activates; focus ring 2px offset.
- **Tokens**: `color.action.*`, `color.buy`, `color.sell`, `radius.sm`, `space.button.*`, `elevation.0`.
- **Storybook**: Default, AllVariants, AllSizes, Loading, DisabledWithReason, IconOnly, BuySellPair.
- **Tests**: unit (variant/state matrix), visual regression (all variants × dark/light), axe, keyboard activation, RBAC-disabled-tooltip interaction test.

### CMP-002 IconButton
- **Tier**: Atom · **Purpose**: icon-only affordance (toolbar actions, panel close, row actions).
- **Props**: `icon: IconName` · `label: string` (mandatory, becomes `aria-label`) · `variant`/`size` as CMP-001 · `pressed?: boolean` (toggle mode) · `disabled?/disabledReason?`.
- **States**: default, hover, focus-visible, pressed (aria-pressed true), disabled.
- **A11y**: `aria-label` required (lint-enforced, build fails without it), `aria-pressed` for toggle mode, min hit-target 24×24px compact / 44×44px comfortable (`05-accessibility-standard.md` §3.4.7 essential-exception documented for compact toolbars with adjacent spacing compensation).
- **Tokens**: `color.action.*`, `radius.sm`, `size.icon.*`.
- **Storybook**: Default, Toggle, AllSizes, DisabledWithReason.
- **Tests**: unit, visual, axe (label presence lint + runtime check), keyboard toggle.

### CMP-003 SegmentedControl
- **Tier**: Atom · **Purpose**: exclusive choice among 2–6 options (e.g. chart type, density mode, order type Market/Limit/Conditional).
- **Props**: `options: {value,label,icon?}[]` · `value` · `onChange` · `size` · `fullWidth?`.
- **A11y**: `role="radiogroup"` container, each option `role="radio"` + `aria-checked`; arrow-key roving tabindex navigation, `Home`/`End` jump to first/last.
- **Tokens**: `color.surface.raised`, `color.action.selected`, `radius.md`.
- **Storybook**: Default, IconOnly, ManyOptions, Disabled.
- **Tests**: unit, visual, axe, keyboard roving-tabindex interaction test.

### CMP-004 Toggle (Switch)
- **Tier**: Atom · **Purpose**: binary on/off (1-click trading arm, feature flags, dark/light).
- **Props**: `checked` · `onChange` · `label` · `labelPosition: "left"|"right"|"hidden"` · `size` · `disabled?/disabledReason?` · `critical?: boolean` (renders with stronger visual weight + confirm-wrapper requirement, e.g. 1-click arm).
- **A11y**: native `role="switch"` `aria-checked`. `Enter`/`Space` toggles.
- **Tokens**: `color.action.on/off`, `motion.toggle`.
- **Storybook**: Default, Critical (1-click-arm look), WithLabel, Disabled.
- **Tests**: unit, visual, axe, keyboard toggle, critical-variant confirm-wrapper composition test.

### CMP-005 Checkbox
- **Tier**: Atom · **Purpose**: multi-select, agree/confirm gates.
- **Props**: `checked` · `indeterminate?` · `onChange` · `label` · `disabled?`.
- **A11y**: native `<input type=checkbox>` semantics, `aria-checked="mixed"` for indeterminate.
- **Tokens**: `color.action.selected`, `radius.xs`.
- **Storybook**: Default, Indeterminate, Disabled.
- **Tests**: unit, visual, axe, keyboard.

### CMP-006 RadioGroup
- **Tier**: Atom · **Purpose**: exclusive choice, vertical list form (position side in some forms, sizing-rule type).
- **Props**: `options[]` · `value` · `onChange` · `orientation: "vertical"|"horizontal"`.
- **A11y**: `role="radiogroup"`, roving tabindex, arrow-key navigation.
- **Tokens**: `color.action.selected`, `space.control.gap`.
- **Storybook**: Default, Horizontal, Disabled.
- **Tests**: unit, visual, axe, keyboard.

### CMP-007 TextInput
- **Tier**: Atom · **Purpose**: base single-line text entry, wrapped by molecules (PriceInput, QtyInput, SymbolSearchInput).
- **Props**: `value` · `onChange` · `placeholder?` · `prefix?/suffix?: ReactNode` · `size` · `invalid?: boolean` · `errorMessage?` · `disabled?` · `readOnly?` · `inputMode?` · `maxLength?`.
- **States**: default, focus, invalid (red border + icon + message, not colour-only), disabled, readOnly.
- **A11y**: `<input>` with `aria-invalid`, `aria-describedby` → error message id, `aria-errormessage` where supported.
- **Tokens**: `color.border.*`, `color.text.error`, `radius.sm`, `font.mono` (numeric inputs only).
- **Storybook**: Default, WithPrefixSuffix, Invalid, Disabled.
- **Tests**: unit, visual, axe, keyboard, invalid-state announcement test (live region / aria-invalid change).

### CMP-008 NumericStepperInput
- **Tier**: Atom · **Purpose**: base numeric input with +/- step buttons; underlies PriceInput/QtyInput (CMP-100/101).
- **Props**: `value: number` · `min?/max?` · `step: number` · `precision: number` · `onChange` · `onStep(direction)` · `disabled?`.
- **A11y**: `role="spinbutton"` semantics (`aria-valuenow/min/max/text`), `↑/↓` arrow keys step by `step`, `PageUp/PageDown` step ×10, `Home/End` jump to min/max.
- **Tokens**: `font.mono`, `color.border.*`.
- **Storybook**: Default, MinMaxClamped, KeyboardStepDemo.
- **Tests**: unit (clamping/precision rounding), visual, axe, keyboard step interaction, fuzz test for float precision edge cases.

### CMP-009 Select (native-pattern dropdown)
- **Tier**: Atom · **Purpose**: single choice from a closed list (interval picker, order category).
- **Props**: `options[]` · `value` · `onChange` · `size` · `disabled?` · `searchable?: boolean`.
- **A11y**: WAI-ARIA APG "Listbox"/"Combobox" pattern (uses Radix Select primitive), `aria-expanded`, `aria-activedescendant`, type-ahead.
- **Tokens**: `color.surface.overlay`, `elevation.2`, `radius.md`.
- **Storybook**: Default, Searchable, Disabled, LongList (virtualized).
- **Tests**: unit, visual, axe, keyboard (type-ahead, arrow nav, Esc closes, focus returns to trigger).

### CMP-010 Slider
- **Tier**: Atom · **Purpose**: base range slider; underlies LeverageSlider (CMP-104).
- **Props**: `value` · `min/max/step` · `onChange` · `marks?: number[]` · `disabled?`.
- **A11y**: `role="slider"`, `aria-valuenow/min/max/text`, arrow keys ±step, `PageUp/Down` ±10×step, `Home/End`.
- **Tokens**: `color.action.*`, `color.track`, `radius.pill`.
- **Storybook**: Default, WithMarks, Disabled.
- **Tests**: unit, visual, axe, keyboard.

### CMP-011 Tag / Chip
- **Tier**: Atom · **Purpose**: compact label (tag on journal entry, symbol category, "(estimated)" chip).
- **Props**: `label` · `variant: "neutral"|"info"|"warning"|"danger"|"estimated"` · `icon?` · `removable?` · `onRemove?`.
- **A11y**: if removable, remove control is a labelled `IconButton` (CMP-002) child, not a bare `×`.
- **Tokens**: `color.chip.*`, `radius.pill`.
- **Storybook**: AllVariants, Removable, EstimatedChip (with tooltip).
- **Tests**: unit, visual, axe, keyboard remove.

### CMP-012 Badge (status dot/count)
- **Tier**: Atom · **Purpose**: small numeric/status indicator (unread count, connection dot).
- **Props**: `variant: "count"|"dot"` · `value?: number` · `tone: "neutral"|"info"|"success"|"warning"|"danger"`.
- **A11y**: `aria-label` describing meaning (e.g. "3 unread alerts"), never colour-only — dot variant always paired with adjacent text/icon at point of use.
- **Tokens**: `color.status.*`.
- **Storybook**: Count, Dot, AllTones.
- **Tests**: unit, visual, axe.

### CMP-013 Avatar / ProfileBadge base
- **Tier**: Atom · **Purpose**: initials/icon circle for accounts/managers; base for CMP-106 AccountBadge.
- **Props**: `label: string` (initials derived) · `color?: string` (deterministic per-account hash) · `size`.
- **A11y**: decorative unless only content — pairs with visible text label at point of use.
- **Tokens**: `color.avatar.palette[]`, `radius.circle`.
- **Storybook**: Default, AllSizes, ColorPalette.
- **Tests**: unit, visual.

### CMP-014 Spinner / Loader
- **Tier**: Atom · **Purpose**: indeterminate loading indicator.
- **Props**: `size` · `label?: string` (for standalone use, else decorative inside a labelled parent).
- **A11y**: `role="status"` + `aria-live="polite"` when standalone; `aria-hidden` when nested inside an already-announced busy control (e.g. CMP-001 loading state) to avoid double announcement.
- **Tokens**: `color.action.primary`, `motion.spin` (motion-reduce: pulsing opacity instead of rotation).
- **Storybook**: Default, AllSizes, Standalone(labelled), Nested(hidden).
- **Tests**: unit, visual, axe, reduced-motion snapshot.

### CMP-015 Skeleton
- **Tier**: Atom · **Purpose**: loading placeholder for panels/rows/cards.
- **Props**: `shape: "text"|"row"|"card"|"chart"` · `count?: number`.
- **A11y**: `aria-hidden="true"` (the loading state is announced once by the parent container's `aria-busy`, not per-skeleton).
- **Tokens**: `color.surface.skeleton`, `motion.shimmer` (motion-reduce: static tone, no shimmer).
- **Storybook**: AllShapes, Count.
- **Tests**: unit, visual, reduced-motion snapshot.

### CMP-016 Tooltip
- **Tier**: Atom · **Purpose**: contextual help / disabled-reason / estimated-methodology text.
- **Props**: `content: ReactNode` · `side` · `delay?: number` (default 300ms) · `triggerOnFocus?: boolean` (true always, for keyboard parity).
- **A11y**: Radix Tooltip primitive — appears on hover AND focus, dismissible via `Esc`, does not trap focus, `role="tooltip"` + `aria-describedby` linking trigger.
- **Tokens**: `color.surface.overlay`, `elevation.3`, `radius.sm`.
- **Storybook**: Default, LongContent, KeyboardTriggered.
- **Tests**: unit, visual, axe, keyboard show/dismiss.

### CMP-017 Popover
- **Tier**: Atom · **Purpose**: base floating panel for menus/pickers (underlies CMP-041 Menu, CMP-047 DatePicker etc.).
- **Props**: `open` · `onOpenChange` · `anchor` · `placement` · `modal?: boolean`.
- **A11y**: focus-trap when `modal`, returns focus to trigger on close, `Esc` closes, click-outside closes (with `pointerdown` guard to avoid mis-fire on drag).
- **Tokens**: `elevation.3`, `radius.md`.
- **Storybook**: Default, Modal, NonModal.
- **Tests**: unit, visual, axe, focus-trap/return test.

### CMP-018 Divider
- **Tier**: Atom · **Purpose**: visual/semantic separator.
- **Props**: `orientation: "horizontal"|"vertical"` · `inset?`.
- **A11y**: `role="separator"` when semantically meaningful (e.g. inside menu), decorative otherwise.
- **Tokens**: `color.border.subtle`.
- **Storybook**: Horizontal, Vertical.
- **Tests**: unit, visual.

### CMP-019 Icon
- **Tier**: Atom · **Purpose**: single glyph from the icon set (`16-design-system-brief.md` §5).
- **Props**: `name: IconName` · `size` · `decorative?: boolean` (default true → `aria-hidden`; false requires `label`).
- **A11y**: `aria-hidden="true"` by default; when `decorative=false`, renders `role="img"` + `aria-label`.
- **Tokens**: `color.icon.*`, `size.icon.*`.
- **Storybook**: FullSet (all icons grid), SizeScale.
- **Tests**: unit (icon registry completeness), visual, axe (decorative-vs-labelled lint).

### CMP-020 Typography primitives (Text, Heading, NumericText, MonoText)
- **Tier**: Atom · **Purpose**: consistent type scale application; `NumericText` enforces tabular-nums + semantic colour + sign formatting for price/qty/PnL.
- **Props** (NumericText): `value: number` · `format: "price"|"qty"|"pct"|"pnl"|"notional"` · `precision?` · `signDisplay?: "auto"|"always"|"never"` · `colorBySign?: boolean`.
- **A11y**: `NumericText` renders a visually-hidden expanded reading (`aria-label`) for screen readers when abbreviated (e.g. "1.2M" → aria-label "1,200,000") per §4.
- **Tokens**: `font.family.ui/mono`, `font.size.scale[]`, `color.text.buy/sell/neutral`.
- **Storybook**: TypeScale, NumericFormats, PnLColoring, AbbreviatedWithAriaLabel.
- **Tests**: unit (formatting matrix incl. locale-independent decimal point per trading convention), visual, axe.

### CMP-021 Link
- **Tier**: Atom · **Purpose**: in-app navigation/external link.
- **Props**: `href?` · `to?` (internal route) · `external?: boolean` (renders icon + `rel="noopener"` + opens Electron shell external browser).
- **A11y**: native `<a>`, focus-visible ring, external-link icon has `aria-hidden` with adjacent visually-hidden "(opens externally)" text.
- **Tokens**: `color.text.link`.
- **Storybook**: Internal, External.
- **Tests**: unit, visual, axe.

### CMP-022 Kbd (keyboard-shortcut glyph)
- **Tier**: Atom · **Purpose**: render a hotkey combination consistently (menus, tooltips, shortcuts settings screen).
- **Props**: `keys: string[]` (e.g. `["Ctrl","Shift","H"]`).
- **A11y**: `<kbd>` semantic element, visually-hidden expansion text for screen readers ("Control plus Shift plus H").
- **Tokens**: `color.surface.raised`, `radius.xs`, `font.mono`.
- **Storybook**: SingleKey, Combo.
- **Tests**: unit, visual, axe.

### CMP-023 Progress Bar
- **Tier**: Atom · **Purpose**: determinate progress (recorder disk usage, replay load, TWAP slice progress).
- **Props**: `value: number` (0-100) · `label?` · `tone`.
- **A11y**: `role="progressbar"` `aria-valuenow/min/max`.
- **Tokens**: `color.action.primary`, `color.track`.
- **Storybook**: Default, WithLabel, AllTones.
- **Tests**: unit, visual, axe.

### CMP-024 Sparkline
- **Tier**: Atom · **Purpose**: tiny inline trend line (Deep Stats rolling-N, watchlist row mini-chart).
- **Props**: `data: number[]` · `width/height` · `colorBySign?: boolean`.
- **A11y**: `role="img"` + `aria-label` summarising trend ("up 3.2% over 20 bars"); underlying data reachable via the parent row's DOM-mirror table (not a standalone interactive control).
- **Tokens**: `color.text.buy/sell`.
- **Storybook**: Uptrend, Downtrend, Flat.
- **Tests**: unit, visual, axe.

### CMP-025 Avatar Group / Stack
- **Tier**: Atom · **Purpose**: overlapping stack of account badges (trade-group summary).
- **Props**: `items: {label,color}[]` · `max: number` (overflow shows `+N` chip).
- **A11y**: `aria-label` listing all item labels even when visually truncated.
- **Tokens**: `space.avatar.overlap`.
- **Storybook**: Default, Overflow.
- **Tests**: unit, visual, axe.

### CMP-026 EmptyState
- **Tier**: Atom (composed) · **Purpose**: designed empty/zero-data state (recorder-dependent emptiness per `14-screens-catalogue.md` §0.5.3).
- **Props**: `icon` · `title` · `description` · `cta?: {label,onClick}` · `variant: "no-data"|"recording-not-started"|"backfill-in-progress"|"filtered-empty"|"error"`.
- **E08-D04**: `variant="backfill-in-progress"` (data-confidence `backfilling` state) pairs a determinate/indeterminate progress affordance with the description text (e.g. "Loading history — page 3 of ~9"); it is informational, not an error, and never uses `color.status.danger.*`. `variant="recording-not-started"` is confirmed unchanged for `SCR-151`.
- **A11y**: heading semantics preserved (`h3` inside panel context), CTA is a real focusable button.
- **Tokens**: `color.text.secondary`, `space.emptystate.*`.
- **Storybook**: AllVariants.
- **Tests**: unit, visual, axe.

### CMP-027 ErrorState / InlineError
- **Tier**: Atom (composed) · **Purpose**: panel-level or field-level error surface (WS disconnect, order rejection).
- **Props**: `message` · `severity: "warning"|"error"` · `retry?: {label,onClick}` · `details?: string` (collapsible technical detail).
- **A11y**: `role="alert"` for severity `error` (assertive live region), `role="status"` for `warning` (polite).
- **Tokens**: `color.status.warning/danger`.
- **Storybook**: Warning, Error, WithRetry, WithDetails.
- **Tests**: unit, visual, axe, live-region announcement test.

### CMP-028 Callout / Banner (inline, non-global)
- **Tier**: Atom (composed) · **Purpose**: inline informational/warning block inside a panel or form (distinct from the global EnvBanner CMP-078).
- **Props**: `tone: "info"|"warning"|"danger"|"success"|"connection-reconnecting"|"connection-disconnected"` · `icon?` · `dismissible?` · `retry?: {label,onClick}`.
- **E08-D04 — `connection` severity variants** (used by `SCR-152`, data-confidence vocabulary `docs/design/E08/E08-D01.md`): `tone="connection-disconnected"` renders `role="alert"` (assertive) with `color.data-confidence.disconnected.indicator` accent and a `[ Retry now ]` action; `tone="connection-reconnecting"` renders `role="status"` (polite) with `color.data-confidence.reconnecting.indicator`. Neither tone ever renders raw exchange error text — only the mapped state label plus an optional `details` string supplied by the caller (never a passthrough of the wire error). Flapping reconnect attempts within 5s collapse into a single "Connection unstable" announcement (no per-attempt re-announce).
- **A11y**: `role="status"` (info/success/connection-reconnecting) or `role="alert"` (warning/danger/connection-disconnected).
- **Tokens**: `color.callout.*`, `color.data-confidence.reconnecting.indicator`, `color.data-confidence.disconnected.indicator`.
- **Storybook**: AllTones, Dismissible, ConnectionReconnecting, ConnectionDisconnected.
- **Tests**: unit, visual, axe, live-region announcement test (assertive vs polite, flap-collapse).

### CMP-029 Skeleton-Chart placeholder
- **Tier**: Atom · **Purpose**: chart-shaped loading placeholder distinct from generic Skeleton (candlestick silhouette).
- **Props**: `paneCount?: number`.
- **A11y**: `aria-hidden`, parent panel carries `aria-busy="true"`.
- **Tokens**: `color.surface.skeleton`.
- **Storybook**: SinglePane, MultiPane.
- **Tests**: unit, visual, reduced-motion snapshot.

### CMP-030 Divider-Label ("section rule with caption")
- **Tier**: Atom · **Purpose**: labelled separator inside long forms (order ticket sections, rule condition groups).
- **Props**: `label: string`.
- **A11y**: renders as a non-interactive `role="separator"` with `aria-orientation="horizontal"`; label is visible text, not just aria.
- **Tokens**: `color.border.subtle`, `font.size.caption`.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-031 ColorSwatch / ThemeChip
- **Tier**: Atom · **Purpose**: pick/display a colour token (drawing tool colour, account colour, heatmap ramp preview).
- **Props**: `color` · `selected?` · `onSelect?`.
- **A11y**: `role="radio"` inside a `radiogroup` swatch picker; `aria-label` names the colour (not just hex).
- **Tokens**: full colour palette (`16-design-system-brief.md` §2).
- **Storybook**: Picker, StaticSwatch.
- **Tests**: unit, visual, axe.

### CMP-032 Rating/Confidence Dots ("estimated confidence indicator")
- **Tier**: Atom · **Purpose**: low/med/high confidence indicator for heuristic detectors (iceberg/stop-run/regime).
- **Props**: `level: "low"|"medium"|"high"` · `label?`.
- **A11y**: never colour-only — filled-dot-count + text label always paired.
- **Tokens**: `color.status.*`.
- **Storybook**: AllLevels.
- **Tests**: unit, visual, axe.

### CMP-033 CopyButton
- **Tier**: Atom · **Purpose**: copy-to-clipboard affordance (API key display, audit record id, order id).
- **Props**: `value: string` · `label` (a11y name) · `onCopied?`.
- **A11y**: `aria-label`, announces "Copied" via a transient polite live region on success.
- **Tokens**: `color.action.ghost`.
- **Storybook**: Default, CopiedState.
- **Tests**: unit, visual, axe, clipboard-mock interaction test.

### CMP-034 MaskedValue ("secret reveal")
- **Tier**: Atom · **Purpose**: masked API key/secret display with reveal toggle (admin key screens).
- **Props**: `value: string` · `revealed?: boolean` · `onToggleReveal` · `autoHideMs?: number` (default 10000, re-masks automatically).
- **A11y**: toggle is CMP-002 IconButton with label "Show secret"/"Hide secret"; auto-hide timer announced via polite live region ~2s before hiding ("Secret will hide in 2 seconds") satisfying WCAG 2.2.1 (no silent unannounced timing change).
- **Tokens**: `font.mono`, `color.surface.raised`.
- **Storybook**: Masked, Revealed, AutoHideCountdown.
- **Tests**: unit, visual, axe, timing-announcement test.

### CMP-035 Countdown / Timer text
- **Tier**: Atom · **Purpose**: bar-close countdown, admin re-auth token expiry countdown, secret auto-hide.
- **Props**: `expiresAt: number` (epoch ms) · `format: "mm:ss"|"words"` · `onExpire?`.
- **A11y**: `aria-live="off"` visually (updates every second would flood SR) with a discrete polite announcement only at defined thresholds (e.g. 60s, 10s, 0s) — documented pattern reused wherever a countdown appears.
- **Tokens**: `font.mono`, `color.text.warning` (under threshold).
- **Storybook**: Default, UnderThreshold, Expired.
- **Tests**: unit (threshold announcement logic), visual, axe.

### CMP-036 KeyValueRow
- **Tier**: Atom · **Purpose**: label/value pair row used across summary cards (order review, position detail).
- **Props**: `label` · `value: ReactNode` · `emphasis?: boolean` · `freshness?: DataConfidenceState` (renders CMP-239 FreshnessMarker beside `value` for live fields — see E08-D04).
- **A11y**: renders as definition-list pair (`dt`/`dd`) semantics for screen-reader table-like traversal.
- **Tokens**: `space.row.*`, `font.size.body/label`.
- **Storybook**: Default, Emphasis, LiveFreshness.
- **Tests**: unit, visual, axe.

### CMP-037 SwatchLegendItem
- **Tier**: Atom · **Purpose**: one legend row (colour + label + value), building block for CMP-113 HeatmapLegend and chart legends.
- **Props**: `color` · `label` · `value?`.
- **A11y**: grouped under parent legend's `role="group"` with `aria-label`.
- **Tokens**: `color.*` (context-dependent).
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-038 InlineSpinnerText ("Loading…" text+spinner pairing)
- **Tier**: Atom · **Purpose**: standard "loading X" composite used in buttons/rows/panels needing a text+spinner pairing without re-deriving CMP-014 usage each time.
- **Props**: `label: string`.
- **A11y**: single `role="status"` wrapping both icon and text (avoids double-announcement bug class).
- **Tokens**: inherits CMP-014/CMP-020.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-039 FocusRing (utility, non-visual export)
- **Tier**: Atom (utility) · **Purpose**: shared CSS/JS utility applying the standard focus-visible ring so every custom-drawn (canvas-adjacent) focusable surrogate element gets an identical ring — used by chart-engine DOM-mirror nodes (CMP-180+).
- **Props**: n/a (mixin/class).
- **A11y**: guarantees ≥3:1 contrast ring, 2px offset, `:focus-visible` only (not `:focus`) to avoid mouse-click ring flash.
- **Tokens**: `color.focus.ring`.
- **Storybook**: RingOnButton, RingOnCustomSurrogate.
- **Tests**: contrast-ratio automated check, visual.

---

## 2. Molecules (CMP-040..069)

### CMP-040 FormField
- **Tier**: Molecule · **Purpose**: label + control + help/error text wrapper composing any atom input.
- **Props**: `label` · `htmlFor` · `required?` · `help?` · `error?` · `children`.
- **A11y**: `<label for>` association, `aria-describedby` chains help+error ids, `aria-required`.
- **Tokens**: `space.field.*`, `color.text.secondary`.
- **Storybook**: Default, WithError, WithHelp, Required.
- **Tests**: unit, visual, axe.

### CMP-041 Menu (dropdown/context menu)
- **Tier**: Molecule · **Purpose**: action list triggered by button/right-click (row actions, panel overflow menu).
- **Props**: `trigger: ReactNode` · `items: {label,icon?,shortcut?,onSelect,danger?,disabled?}[]` · `onOpenChange`.
- **A11y**: WAI-ARIA "Menu Button" pattern, arrow-key nav, type-ahead, `Esc` closes + returns focus, danger items get `aria-describedby` "destructive action" hint.
- **Tokens**: `elevation.3`, `color.surface.overlay`.
- **Storybook**: Default, WithShortcuts, ContextMenu(right-click), Nested submenu.
- **Tests**: unit, visual, axe, keyboard nav + Esc/return-focus.

### CMP-042 Tabs
- **Tier**: Molecule · **Purpose**: panel-local section switching (order ticket tabs: Market/Limit/Conditional; settings sections).
- **Props**: `tabs: {id,label,icon?}[]` · `value` · `onChange` · `orientation`.
- **A11y**: WAI-ARIA Tabs pattern (`role=tablist/tab/tabpanel`), arrow-key nav, `aria-selected`, lazy-mount tabpanels retain focus correctly on switch.
- **Tokens**: `color.action.selected`, `space.tabs.*`.
- **Storybook**: Default, Vertical, WithIcons.
- **Tests**: unit, visual, axe, keyboard.

### CMP-043 Dialog (Modal)
- **Tier**: Molecule · **Purpose**: base modal wrapper (confirm dialogs, settings dialogs, indicator config).
- **Props**: `open` · `onOpenChange` · `title` · `description?` · `size` · `children` · `initialFocusRef?`.
- **A11y**: `role="dialog"` `aria-modal="true"` `aria-labelledby`/`aria-describedby`, focus-trap, `Esc` closes (unless a destructive-confirm variant disables Esc-as-cancel-shortcut deliberately, documented per instance), focus returns to trigger on close.
- **Tokens**: `elevation.4`, `color.surface.overlay`, `radius.lg`.
- **Storybook**: Default, Small, Large, NoEscClose.
- **Tests**: unit, visual, axe, focus-trap/return test.

### CMP-044 ConfirmDialog
- **Tier**: Molecule (composed on CMP-043) · **Purpose**: destructive/irreversible action gate (flatten all, cancel all, Demo→Live switch, delete API key).
- **Props**: `title` · `message` · `confirmLabel` · `cancelLabel` · `variant: "standard"|"typed"|"hold"` · `typedConfirmValue?: string` (must match, e.g. symbol name) · `holdDurationMs?` (with discrete keyboard fallback per `05-accessibility-standard.md` §3.1.4) · `onConfirm` · `onCancel`.
- **A11y**: `variant="hold"` always ships a keyboard-operable discrete alternative (press-and-hold OR two sequential `Enter` presses within a visible countdown) — never a mouse-only/timing-only gate.
- **Tokens**: `color.status.danger`, `elevation.4`.
- **Storybook**: Standard, TypedConfirm, HoldToConfirm(with keyboard fallback demo).
- **Tests**: unit, visual, axe, keyboard-only path for hold-variant (explicit CI gate per a11y standard §3.1.4).

### CMP-045 Toast / Notification
- **Tier**: Molecule · **Purpose**: transient system feedback (order acked, rule fired, connection restored).
- **Props**: `title` · `description?` · `tone` · `action?: {label,onClick}` · `durationMs?` · `dismissible?`.
- **A11y**: `role="status"` (polite) default, `role="alert"` (assertive) for `tone="danger"`; never auto-dismisses content the user hasn't had a chance to perceive — pauses on hover/focus, and provides a persistent-log fallback (Notification Center) so nothing is lost if missed (WCAG 2.2.1 no timing loss of info).
- **Tokens**: `elevation.3`, `color.status.*`.
- **Storybook**: AllTones, WithAction, PersistentLogLink.
- **Tests**: unit, visual, axe, live-region announcement test, pause-on-hover/focus test.

### CMP-046 Drawer (side panel)
- **Tier**: Molecule · **Purpose**: slide-in panel (footprint cell detail, rule node inspector, symbol info).
- **Props**: `open` · `onOpenChange` · `side: "left"|"right"` · `title` · `children`.
- **A11y**: same contract as Dialog (focus-trap, `Esc`, return focus) but non-modal option available (`modal?: boolean`) for drawers meant to coexist with chart interaction.
- **Tokens**: `elevation.3`, `motion.slide`.
- **Storybook**: Modal, NonModal, LeftSide, RightSide.
- **Tests**: unit, visual, axe, focus-trap test.

### CMP-047 DatePicker / DateRangePicker
- **Tier**: Molecule · **Purpose**: date/time range selection (replay session range, journal filter, recorder retention override).
- **Props**: `value` · `onChange` · `mode: "single"|"range"` · `min?/max?` · `timezone: "UTC"` (locked, 24/7 market — no user-timezone ambiguity per research digest).
- **A11y**: WAI-ARIA "Date Picker Dialog" pattern, full keyboard grid navigation (arrows move by day, `PageUp/Down` by month), live region announces selected range.
- **Tokens**: `color.surface.overlay`, `color.action.selected`.
- **Storybook**: Single, Range, WithMinMax.
- **Tests**: unit, visual, axe, keyboard grid nav.

### CMP-048 Combobox / AutoComplete
- **Tier**: Molecule · **Purpose**: base for SymbolSearchInput (CMP-160) and any type-ahead selector.
- **Props**: `value` · `onChange` · `options[]|asyncSearch(query)` · `loading?` · `placeholder?`.
- **A11y**: WAI-ARIA Combobox pattern, `aria-activedescendant`, `aria-expanded`, results count announced via polite live region on each query update (debounced to avoid flooding).
- **Tokens**: `color.surface.overlay`, `elevation.2`.
- **Storybook**: Sync, AsyncLoading, NoResults.
- **Tests**: unit, visual, axe, keyboard + debounced-announcement test.

### CMP-049 Table (base data table)
- **Tier**: Molecule · **Purpose**: base virtualized sortable table underlying PositionsGrid (CMP-107), OrdersTable, AuditLogTable, JournalTable.
- **Props**: `columns: ColumnDef[]` · `rows: T[]` · `sort?/onSortChange` · `rowKey` · `onRowSelect?` · `virtualized?: boolean` (default true above 50 rows) · `emptyState?: ReactNode`.
- **A11y**: semantic `<table>` with `scope` on headers even when virtualized (windowed rendering keeps ARIA table role structure via `role="rowgroup"/"row"/"cell"` with `aria-rowindex`/`aria-colindex` when native table elements aren't feasible in the virtualization window); sortable headers are buttons with `aria-sort`.
- **Tokens**: `color.surface.raised`, `color.border.subtle`, `font.mono` (numeric columns).
- **Storybook**: Default, Sortable, Virtualized(10k rows), Empty, Selectable.
- **Tests**: unit, visual, axe, keyboard header-sort + row navigation (`↑/↓`), performance test (scroll 10k rows @60fps).

### CMP-050 Card
- **Tier**: Molecule · **Purpose**: bordered content block (summary cards, dashboard tiles).
- **Props**: `title?` · `actions?: ReactNode` · `padding` · `children`.
- **A11y**: heading semantics if `title` present.
- **Tokens**: `color.surface.raised`, `radius.lg`, `elevation.1`.
- **Storybook**: Default, WithActions, NoPadding.
- **Tests**: unit, visual, axe.

### CMP-051 Accordion
- **Tier**: Molecule · **Purpose**: collapsible sections (order ticket advanced options, settings groups).
- **Props**: `items: {id,title,content}[]` · `allowMultiple?` · `value`.
- **A11y**: WAI-ARIA Accordion pattern (`aria-expanded`, `aria-controls`), `Enter`/`Space` toggles header.
- **Tokens**: `space.accordion.*`.
- **Storybook**: Single, MultipleOpen.
- **Tests**: unit, visual, axe, keyboard.

### CMP-052 Breadcrumb
- **Tier**: Molecule · **Purpose**: hierarchical location indicator (admin sub-sections).
- **Props**: `items: {label,href?}[]`.
- **A11y**: `nav aria-label="Breadcrumb"`, ordered list, `aria-current="page"` on last item.
- **Tokens**: `color.text.secondary`.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-053 Pagination
- **Tier**: Molecule · **Purpose**: page/cursor navigation for long lists (audit log, journal) not using infinite virtualization.
- **Props**: `page` · `pageCount?` · `cursor?/onNext/onPrev` · `pageSize?/onPageSizeChange`.
- **A11y**: `nav aria-label="Pagination"`, current page `aria-current="page"`.
- **Tokens**: `color.action.*`.
- **Storybook**: Default, CursorMode.
- **Tests**: unit, visual, axe, keyboard.

### CMP-054 SearchBox
- **Tier**: Molecule · **Purpose**: generic filter/search input with clear button (distinct from SymbolSearchInput's richer preview).
- **Props**: `value` · `onChange` · `placeholder?` · `onClear`.
- **A11y**: clear button labelled "Clear search"; `role="searchbox"`.
- **Tokens**: inherits CMP-007.
- **Storybook**: Default, WithValue.
- **Tests**: unit, visual, axe.

### CMP-055 FilterBar
- **Tier**: Molecule · **Purpose**: row of active filter chips + add-filter control (journal, audit, alerts list).
- **Props**: `filters: {id,label,onRemove}[]` · `onAddFilter`.
- **A11y**: `role="group"` `aria-label="Active filters"`; each removable chip is CMP-011 with keyboard-remove.
- **Tokens**: `space.filterbar.*`.
- **Storybook**: Empty, WithFilters.
- **Tests**: unit, visual, axe.

### CMP-056 ColumnPicker
- **Tier**: Molecule · **Purpose**: show/hide/reorder table columns (Positions grid, Deep Stats rows).
- **Props**: `columns: {id,label,visible}[]` · `onChange` · `onReorder`.
- **A11y**: checkbox list inside CMP-041 Menu pattern; reorder via keyboard (`Alt+↑/↓` moves focused item) in addition to drag.
- **Tokens**: inherits CMP-005/CMP-041.
- **Storybook**: Default, Reordering.
- **Tests**: unit, visual, axe, keyboard reorder.

### CMP-057 SplitButton
- **Tier**: Molecule · **Purpose**: primary action + adjacent dropdown of related actions (e.g. "Buy Market ▾" → Limit/Conditional).
- **Props**: `primary: {label,onClick}` · `items: MenuItem[]`.
- **A11y**: two separately-focusable controls (primary button, disclosure button), disclosure follows CMP-041 contract.
- **Tokens**: inherits CMP-001/CMP-041.
- **Storybook**: Default.
- **Tests**: unit, visual, axe, keyboard.

### CMP-058 InlineEdit
- **Tier**: Molecule · **Purpose**: click-to-edit value in place (rename workspace, edit journal tag).
- **Props**: `value` · `onSave` · `onCancel` · `validate?`.
- **A11y**: toggles between a labelled static text (button-activated) and CMP-007 input; `Enter` saves, `Esc` cancels, focus managed explicitly on each transition.
- **Tokens**: inherits CMP-007.
- **Storybook**: Default, ValidationError.
- **Tests**: unit, visual, axe, keyboard save/cancel.

### CMP-059 CommandPalette
- **Tier**: Molecule · **Purpose**: global `Ctrl+K` fuzzy command/navigation launcher (design requirement: single global hotkey layer, `05-accessibility-standard.md` §3.1.2).
- **Props**: `open` · `onOpenChange` · `commands: {id,label,group,shortcut?,onRun}[]`.
- **A11y**: Combobox+Listbox pattern inside a modal Dialog; results grouped with `role="group"` + group labels; live region announces result count.
- **Tokens**: `elevation.4`, `color.surface.overlay`.
- **Storybook**: Default, Grouped, NoResults.
- **Tests**: unit, visual, axe, keyboard, fuzzy-match unit tests.

### CMP-060 NotificationCenter (bell dropdown)
- **Tier**: Molecule · **Purpose**: persistent log of toasts/alerts (backstop for CMP-045's no-timing-loss requirement).
- **Props**: `items: Notification[]` · `unreadCount` · `onMarkRead` · `onClearAll`.
- **A11y**: `aria-label="Notifications, N unread"` on trigger button, list uses `role="log"`.
- **Tokens**: `elevation.3`.
- **Storybook**: Empty, WithUnread.
- **Tests**: unit, visual, axe.

### CMP-061 UserMenu
- **Tier**: Molecule · **Purpose**: account/profile menu in top chrome (role display, logout, settings link).
- **Props**: `userName` · `role: "owner"|"manager"|"viewer"` · `items: MenuItem[]`.
- **A11y**: inherits CMP-041 contract; role is always shown as visible text (never icon-only).
- **Tokens**: inherits CMP-013/CMP-041.
- **Storybook**: Owner, Manager, Viewer.
- **Tests**: unit, visual, axe.

### CMP-062 ThemeSwitcher
- **Tier**: Molecule · **Purpose**: dark/light/high-contrast theme selection control.
- **Props**: `value: "dark"|"light"|"high-contrast"` · `onChange`.
- **A11y**: CMP-003 SegmentedControl composition; changes announced via polite live region ("Theme changed to High Contrast").
- **Tokens**: n/a (meta-control).
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-063 DensityToggle
- **Tier**: Molecule · **Purpose**: comfortable/compact density switch, global or per-panel override.
- **Props**: `value: "comfortable"|"compact"` · `scope: "global"|"panel"` · `onChange`.
- **A11y**: CMP-003 composition; per-panel override announced with scope context.
- **Tokens**: n/a (meta-control).
- **Storybook**: Global, PanelOverride.
- **Tests**: unit, visual, axe.

### CMP-064 KeyboardShortcutRow ("Shortcuts" settings list item)
- **Tier**: Molecule · **Purpose**: one remappable hotkey row in Settings → Shortcuts (`05-accessibility-standard.md` §3.3, conflict detection).
- **Props**: `action` · `currentKeys: string[]` · `onRebind` · `conflictWith?: string`.
- **A11y**: rebind control announces "press new key combination" then confirms/reports conflict via live region.
- **Tokens**: inherits CMP-022 Kbd.
- **Storybook**: Default, Conflict, Rebinding.
- **Tests**: unit, visual, axe, keyboard rebind + conflict-detection interaction test.

### CMP-065 FormSection
- **Tier**: Molecule · **Purpose**: grouped set of FormFields with a heading (order ticket sections: Size, Risk, Advanced).
- **Props**: `title` · `description?` · `collapsible?` · `children`.
- **A11y**: `fieldset`/`legend` semantics.
- **Tokens**: `space.formsection.*`.
- **Storybook**: Default, Collapsible.
- **Tests**: unit, visual, axe.

### CMP-066 Stepper (multi-step wizard indicator)
- **Tier**: Molecule · **Purpose**: onboarding/setup wizards (first-run account connect, rule-creation wizard).
- **Props**: `steps: {label,status}[]` · `currentStep`.
- **A11y**: `aria-current="step"`, list semantics, status conveyed by icon+text not colour alone.
- **Tokens**: `color.status.*`.
- **Storybook**: Default, WithErrors.
- **Tests**: unit, visual, axe.

### CMP-067 FileDrop / Import control
- **Tier**: Molecule · **Purpose**: CSV/JSON import (journal import, rule import/export).
- **Props**: `accept` · `onFiles` · `multiple?`.
- **A11y**: native `<input type=file>` under the hood (drag-and-drop is additive, never the only path), fully keyboard-operable via the native file picker.
- **Tokens**: `color.border.dashed`.
- **Storybook**: Default, DragOver, Error.
- **Tests**: unit, visual, axe, keyboard-only file selection test.

### CMP-068 CopyableCodeBlock
- **Tier**: Molecule · **Purpose**: display JSON/YAML (rule IR export, webhook payload sample) with copy action.
- **Props**: `code: string` · `language` · `maxHeight?`.
- **A11y**: `<pre><code>` with `aria-label` describing content; CMP-033 CopyButton attached.
- **Tokens**: `font.mono`, `color.surface.code`.
- **Storybook**: JSON, YAML, LongScrollable.
- **Tests**: unit, visual, axe.

### CMP-069 InfoPanel ("i" expandable methodology note)
- **Tier**: Molecule · **Purpose**: the linked methodology drawer referenced by every "(estimated)" chip (CMP-011 estimated variant) — explains heuristic detector logic in plain language.
- **Props**: `title` · `content: ReactNode` · `relatedDetector?: string`.
- **A11y**: opens as CMP-046 Drawer (non-modal), triggerable from the chip's tooltip via `Enter`.
- **Tokens**: inherits CMP-046.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

---

## 3. Organisms — chrome & navigation (CMP-070..099)

### CMP-070 AppShell
- **Tier**: Organism · **Purpose**: root layout — top chrome, left nav rail, workspace area, global overlays.
- **Props**: `children` · `navItems` · `topChrome: ReactNode[]`.
- **A11y**: landmark regions (`header`, `nav`, `main`), skip-to-content link as first focusable element.
- **Tokens**: `color.surface.app`, `layout.shell.*`.
- **Storybook**: Default.
- **Tests**: unit, visual, axe, landmark-structure test.

### CMP-071 NavRail
- **Tier**: Organism · **Purpose**: left icon-rail primary navigation (Workspaces / Journal / Rules / Alerts / Replay / Admin).
- **Props**: `items: {id,icon,label,route,badge?}[]` · `activeId`.
- **A11y**: `nav` with `aria-label="Primary"`, current item `aria-current="page"`, each icon-only item has visible label on hover/focus tooltip + always-present `aria-label`.
- **Tokens**: `color.surface.raised`, `size.navrail.width`.
- **Storybook**: Default, WithBadges, Collapsed.
- **Tests**: unit, visual, axe, keyboard.

### CMP-072 TopBar
- **Tier**: Organism · **Purpose**: global top chrome — logo, workspace switcher, EnvBanner, ConnectionStatus, NotificationCenter, UserMenu.
- **Props**: `children` (slotted regions).
- **A11y**: `header` landmark.
- **Tokens**: `color.surface.raised`, `elevation.1`.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-073 WorkspaceSwitcher
- **Tier**: Organism · **Purpose**: switch/create/rename saved multi-panel workspaces.
- **Props**: `workspaces: {id,name}[]` · `activeId` · `onSwitch` · `onCreate` · `onRename` · `onDelete`.
- **A11y**: Combobox pattern (CMP-048); delete is a ConfirmDialog (CMP-044) gated action.
- **Tokens**: inherits CMP-048.
- **Storybook**: Default, Empty(first-run), ManyWorkspaces.
- **Tests**: unit, visual, axe.

### CMP-074 EnvBanner (Demo/Live)
- **Tier**: Organism (trading-critical) · **Purpose**: persistent global chrome band declaring Demo vs Live — the single most safety-critical visual element in the app (`14-screens-catalogue.md` §0.5.1).
- **Props**: `env: "demo"|"live"` · `onRequestSwitch`.
- **A11y**: text `DEMO`/`LIVE` always rendered (never icon/colour alone), `role="status"` region so a screen-reader user re-entering the tab hears current env on demand (`aria-label="Trading environment: Live"`); switching triggers CMP-044 ConfirmDialog `variant="typed"` (must type environment name) per `05-accessibility-standard.md` no-accidental-live-switch requirement.
- **Tokens**: `color.env.demo` (blue), `color.env.live` (red), `font.weight.bold`.
- **Storybook**: Demo, Live, SwitchConfirmFlow.
- **Tests**: unit, visual, axe, interaction test (typed-confirm gate), visual-regression snapshot both states at every theme.

### CMP-075 EnvBadgeLocal
- **Tier**: Molecule (chrome) · **Purpose**: the same Demo/Live indicator repeated locally on every trading-capable panel (order ticket, DOM ladder, positions grid) per invariant `14-screens-catalogue.md` §0.5.1 — never rely on the single global banner alone.
- **Props**: `env`.
- **A11y**: identical text contract to CMP-074 but non-interactive (read-only badge), `aria-hidden` redundant re-announcement suppressed via `role="img"` with static label so screen readers don't re-announce it on every panel re-render.
- **Tokens**: shares `color.env.*`.
- **Storybook**: Demo, Live.
- **Tests**: unit, visual, axe.

### CMP-076 ConnectionStatus
- **Tier**: Organism · **Purpose**: global WS/API connectivity indicator (connected/reconnecting/degraded/offline), feeds `system.health` topic.
- **Props**: `status: "connected"|"reconnecting"|"degraded"|"offline"` · `lastGoodTs` · `latencyMs?`.
- **A11y**: icon+text+colour triad; state changes to `degraded`/`offline` announce via `role="alert"` (assertive) once, not on every heartbeat.
- **Tokens**: `color.status.*`.
- **Storybook**: AllStates.
- **Tests**: unit, visual, axe, announcement-throttling test.

### CMP-077 ReconnectOverlay
- **Tier**: Organism · **Purpose**: full-workspace overlay during total disconnect (`14-screens-catalogue.md` §0.5.4, SCR-152).
- **Props**: `retryInSec` · `onRetryNow` · `attempt`.
- **A11y**: `role="alertdialog"`, non-dismissible (data is genuinely stale — no false "OK" affordance), keyboard-operable manual retry button.
- **Tokens**: `elevation.5`, `color.surface.scrim`.
- **Storybook**: Default, RetryExhausted.
- **Tests**: unit, visual, axe, focus-trap test.

### CMP-078 StaleDataShade
- **Tier**: Molecule (chrome) · **Purpose**: per-panel shading applied after 2s without an expected update (§0.5.4).
- **Props**: `stale: boolean` · `lastGoodTs`.
- **A11y**: shading is supplemented with a visible "Last update Xs ago" text, not opacity alone.
- **Tokens**: `color.overlay.stale`.
- **Storybook**: Fresh, Stale.
- **Tests**: unit, visual, axe.

### CMP-079 RbacGate (disabled-with-reason wrapper)
- **Tier**: Molecule (utility/organism-adjacent) · **Purpose**: standard wrapper implementing invariant §0.5.5 — controls the user may not use render disabled with a reason tooltip.
- **Props**: `allowed: boolean` · `reason?: string` · `children` (any interactive component).
- **A11y**: propagates `disabledReason` to the wrapped atom's native prop (CMP-001/002/004 etc. all accept it) rather than overlaying a separate non-semantic layer.
- **Tokens**: n/a (behavioural wrapper).
- **Storybook**: Allowed, Denied(ViewerRole), Denied(EnvMismatch).
- **Tests**: unit, visual, axe, RBAC-matrix interaction test (per role × action fixture).

### CMP-080 DockPanel (dockable container)
- **Tier**: Organism · **Purpose**: base draggable/resizable/closable panel used by the workspace docking system (chart, DOM, ticket, positions all mount inside one).
- **Props**: `id` · `title` · `icon?` · `onClose?` · `onFocus` · `children` · `minWidth/minHeight`.
- **A11y**: `role="region"` `aria-label={title}`, drag-to-reposition has a keyboard equivalent (focus panel header → `Ctrl+Shift+Arrow` moves/swaps dock position, documented in Shortcuts settings), resize handles are focusable and operable via arrow keys (`aria-valuenow` width/height announced).
- **Tokens**: `elevation.2`, `radius.md`, `color.border.panel`.
- **Storybook**: Default, Focused, Resizing(keyboard demo), Closable.
- **Tests**: unit, visual, axe, keyboard reposition/resize interaction test, performance (mount ≤150ms budget per `14-screens-catalogue.md` §0.5.7).

### CMP-081 DockGrid / Layout Manager
- **Tier**: Organism · **Purpose**: the overall docking surface arranging N DockPanels into saved layouts/presets (1x1/2x1/2x2/1+3/custom), `Ctrl+1..9` preset hotkeys.
- **Props**: `layout: LayoutTree` · `onLayoutChange` · `presets`.
- **A11y**: layout changes announced via polite live region ("Layout changed to 2 by 2"); panel focus order follows visual reading order, re-computed and exposed via `aria-owns` if DOM order can't match visual order.
- **Tokens**: `space.dockgrid.gutter`.
- **Storybook**: OnePane, TwoByTwo, OnePlusThree, CustomDrag.
- **Tests**: unit, visual, axe, keyboard preset-switch test, performance (route/layout transition ≤200ms budget).

### CMP-082 PanelHeader
- **Tier**: Molecule · **Purpose**: standard header for any DockPanel — title, symbol/interval mini-controls, overflow menu, close.
- **Props**: `title` · `subtitle?` · `actions?: ReactNode` · `onClose?`.
- **A11y**: heading (`h2`/`h3` depending on nesting) + toolbar (`role="toolbar"`) for actions with arrow-key nav between action buttons.
- **Tokens**: `color.surface.raised`, `space.panelheader.*`.
- **Storybook**: Default, WithActions.
- **Tests**: unit, visual, axe.

### CMP-083 SplitPane (resizable divider, non-dock)
- **Tier**: Molecule · **Purpose**: simple two-region resizable split (used inside a single DockPanel, e.g. chart + Deep Stats strip).
- **Props**: `direction` · `sizes` · `onChange` · `minSize`.
- **A11y**: divider is `role="separator"` `aria-orientation` `aria-valuenow` (percentage), arrow-key resize.
- **Tokens**: `color.border.subtle`.
- **Storybook**: Horizontal, Vertical.
- **Tests**: unit, visual, axe, keyboard resize.

### CMP-084 GlobalSearchTrigger (part of TopBar, launches CommandPalette)
- **Tier**: Molecule · **Purpose**: visible `Ctrl+K` affordance in TopBar.
- **Props**: none beyond `onClick`.
- **A11y**: button with visible shortcut hint (CMP-022 Kbd inline).
- **Tokens**: inherits CMP-001.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-085 SkipLink
- **Tier**: Atom (chrome) · **Purpose**: "Skip to main content" first-focusable link, WCAG 2.4.1.
- **Props**: `targetId`.
- **A11y**: visually hidden until focused, then visible at top-left.
- **Tokens**: `color.action.primary`.
- **Storybook**: Focused, Unfocused.
- **Tests**: unit, visual, axe, keyboard-first-tab test.

### CMP-086 SettingsNav / SettingsLayout
- **Tier**: Organism · **Purpose**: two-pane settings layout (nav list + content) for `/settings/*`.
- **Props**: `sections: {id,label,icon}[]` · `activeId` · `children`.
- **A11y**: `nav aria-label="Settings"`, landmark `main` for content.
- **Tokens**: `layout.settings.*`.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-087 AdminLayout (RBAC-gated shell)
- **Tier**: Organism · **Purpose**: shell for `/admin/*` routes, requires re-auth token badge and distinct visual treatment (per `14-screens-catalogue.md` §0.3 re-auth ≤15min rule).
- **Props**: `children` · `reauthExpiresAt`.
- **A11y**: distinct `aria-label="Admin area"` landmark; re-auth countdown uses CMP-035 pattern.
- **Tokens**: `color.surface.admin-tint`.
- **Storybook**: Default, ReauthExpiringSoon.
- **Tests**: unit, visual, axe.

### CMP-088 PageHeader
- **Tier**: Molecule · **Purpose**: full-page area header (Journal, Rules, Alerts, Replay, Admin sub-pages) — title + primary actions + breadcrumb.
- **Props**: `title` · `breadcrumb?` · `actions?`.
- **A11y**: single `h1` per route.
- **Tokens**: `space.pageheader.*`.
- **Storybook**: Default, WithBreadcrumb.
- **Tests**: unit, visual, axe.

### CMP-089 ForbiddenState (403)
- **Tier**: Organism · **Purpose**: full-page state for a route disallowed at the server (defence in depth alongside hidden-nav per §0.5.5).
- **Props**: `reason?`.
- **A11y**: `h1` "Access denied", explanatory text, link home.
- **Tokens**: inherits CMP-026.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-090 NotFoundState (404)
- **Tier**: Organism · **Purpose**: unmatched route fallback.
- **Props**: `path?`.
- **Tokens**: inherits CMP-026.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-091 GlobalErrorBoundaryFallback
- **Tier**: Organism · **Purpose**: React error-boundary fallback screen (uncaught render error), offers reload/report.
- **Props**: `error` · `onReload` · `onReport`.
- **A11y**: `role="alert"`, focus moves to the fallback heading on mount.
- **Tokens**: inherits CMP-027.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-092 DegradedModeBanner
- **Tier**: Molecule (chrome) · **Purpose**: system-health-driven banner (ingestion lag, recorder disk near-full, engine FPS below budget) distinct from ConnectionStatus (which is transport-only).
- **Props**: `issues: {id,severity,message}[]`.
- **A11y**: `role="status"`/`role="alert"` by severity, dismissible per-issue but reappears if condition persists (not a silent permanent dismiss).
- **Tokens**: `color.status.warning`.
- **Storybook**: SingleIssue, MultipleIssues.
- **Tests**: unit, visual, axe.

### CMP-093 AuditActionTrigger (wraps any state-changing control to guarantee audit emission)
- **Tier**: Molecule (utility) · **Purpose**: development-time contract wrapper ensuring every state-changing action emits the audit record shape from `14-screens-catalogue.md` §0.5.8; not a visual component but catalogued because it participates in the DoD checklist for every action-producing organism.
- **Props**: `action: string` · `target` · `before?/after?` · `children`.
- **A11y**: none additional (pass-through).
- **Tokens**: n/a.
- **Storybook**: n/a (documented via integration test, not visual story).
- **Tests**: integration test asserting audit POST fired with correct shape for a representative sample of wrapped actions.

### CMP-094 HotkeyOverlay ("? " cheatsheet)
- **Tier**: Organism · **Purpose**: full hotkey cheatsheet overlay, triggered by `?`.
- **Props**: `groups: {label,bindings:{keys,action}[]}[]`.
- **A11y**: modal Dialog (CMP-043) composition, content organised as a table with a caption.
- **Tokens**: inherits CMP-043.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-095 FeatureFlagChip (visible-in-UI flag indicator, admin/dev only)
- **Tier**: Atom (chrome, owner-only) · **Purpose**: small marker on screens gated by an unreleased feature flag, visible only to owner role for QA purposes.
- **Props**: `flagKey`.
- **A11y**: `aria-label="Feature flag: {flagKey}"`.
- **Tokens**: `color.chip.dev`.
- **Storybook**: Default.
- **Tests**: unit, visual.

### CMP-096 WhatsNewPanel
- **Tier**: Organism · **Purpose**: release-notes drawer surfaced after an update (ties to `07-release-and-prr.md` changelog).
- **Props**: `entries: {version,date,items}[]`.
- **A11y**: Drawer composition (CMP-046).
- **Tokens**: inherits CMP-046.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-097 OnboardingChecklist
- **Tier**: Organism · **Purpose**: first-run setup checklist (connect Bybit account, set recorder policy, create first workspace).
- **Props**: `steps: {id,label,done,onGo}[]`.
- **A11y**: list semantics with `aria-checked` per step (treated as read-only checkbox list reflecting completion state).
- **Tokens**: inherits CMP-066.
- **Storybook**: Default, PartiallyComplete.
- **Tests**: unit, visual, axe.

### CMP-098 SessionTimeoutWarning
- **Tier**: Organism · **Purpose**: warns before auth session/admin re-auth expiry, offers one-click extend.
- **Props**: `expiresInSec` · `onExtend`.
- **A11y**: `role="alertdialog"` appearing at a fixed threshold (e.g. 60s remaining), keyboard-operable extend action, never a silent auto-logout without this warning (WCAG 2.2.1). Esc = dismiss, does NOT extend; Extend is an explicit server call (POST /auth/session/extend).
- **Tokens**: inherits CMP-043.
- **Storybook**: Default.
- **Tests**: unit, visual, axe, timing-warning interaction test.

### CMP-099 PrintExportBar
- **Tier**: Molecule · **Purpose**: export controls (CSV/PDF) for journal/audit/strategy reports.
- **Props**: `formats: ("csv"|"pdf")[]` · `onExport(format)` · `loading?`.
- **A11y**: each format is a distinct labelled button, loading state per CMP-038.
- **Tokens**: inherits CMP-001.
- **Storybook**: Default, Exporting.
- **Tests**: unit, visual, axe.

---

## 4. Trading-specific components (CMP-100..139)

These are first-class design-system components per `05-accessibility-standard.md` §11.3 — same a11y bar as atoms/molecules, not exempted as "custom chart stuff." Every canvas-adjacent one (footprint cell, DOM row, heatmap legend) ships a table-alternative data contract per §6 of that standard.

### CMP-100 PriceInput
- **Tier**: Molecule (trading) · **Purpose**: price entry with exchange tick-size validation and quick nudge buttons.
- **Props**: `value: number` · `onChange` · `symbol: string` · `tickSize: number` (from `/v5/market/instruments-info`) · `side?: "buy"|"sell"` (tints on brand colour) · `referencePrice?: number` (last/mark, for %-away helper text) · `disabled?/disabledReason?`.
- **Variants**: standalone, attached-to-order-line (rendered inline on chart via chart-engine overlay, CMP-192).
- **States**: default, focus, invalid-tick (value not a multiple of `tickSize` → auto-rounds on blur with a visible "(rounded to nearest tick)" caption, never silently mutates without telling the user), disabled.
- **A11y**: extends CMP-008 NumericStepperInput contract; `aria-label="Price"`, rounding-message rendered as `aria-live="polite"` text near the field, not just a toast.
- **Tokens**: `font.mono`, `color.text.buy/sell`, `color.border.invalid`.
- **API sketch**:
```ts
interface PriceInputProps {
  value: number;
  onChange: (v: number) => void;
  symbol: string;
  tickSize: number;
  referencePrice?: number;
  side?: "buy" | "sell";
  disabled?: boolean;
  disabledReason?: string;
}
```
- **Data contract**: `tickSize`/`symbol` sourced from Bybit `/v5/market/instruments-info` (REST, cached per symbol); no live WS dependency.
- **Storybook**: Default, TickRounding, BuySideTint, SellSideTint, Disabled.
- **Tests**: unit (tick-rounding matrix across symbols with different tick sizes), visual, axe, keyboard step, interaction test for rounding-announcement.

### CMP-101 QtyInput
- **Tier**: Molecule (trading) · **Purpose**: quantity entry with exchange lot-size/min-notional validation and %-of-equity / risk-based helper.
- **Props**: `value: number` · `onChange` · `symbol` · `lotSize: number` · `minQty: number` · `minNotional?: number` · `sizingMode: "qty"|"pctEquity"|"fixedUsd"|"riskPct"` · `onSizingModeChange` · `accountEquity?: number` · `disabled?/disabledReason?`.
- **Variants**: qty mode, %-equity mode (renders derived qty read-only alongside the % input), fixed-$ mode, risk-% mode (requires a stop distance input to derive qty).
- **States**: default, focus, below-min-qty (blocks submit, inline error), below-min-notional (blocks submit), disabled.
- **A11y**: extends CMP-008; sizing-mode switch is CMP-003 SegmentedControl with `aria-describedby` explaining the active formula.
- **Tokens**: `font.mono`, `color.border.invalid`.
- **API sketch**:
```ts
interface QtyInputProps {
  value: number;
  onChange: (v: number) => void;
  symbol: string;
  lotSize: number;
  minQty: number;
  minNotional?: number;
  sizingMode: "qty" | "pctEquity" | "fixedUsd" | "riskPct";
  onSizingModeChange: (m: QtyInputProps["sizingMode"]) => void;
  accountEquity?: number;
  stopDistance?: number; // required for riskPct
}
```
- **Data contract**: `lotSize`/`minQty`/`minNotional` sourced from Bybit `/v5/market/instruments-info` (REST, cached per symbol); `accountEquity` sourced from the account-equity WS/REST feed per `14-screens-catalogue.md` §0.4.
- **Storybook**: QtyMode, PctEquityMode, FixedUsdMode, RiskPctMode, BelowMinQty, BelowMinNotional.
- **Tests**: unit (lot/min-qty/min-notional validation matrix per sizing mode), visual, axe, keyboard.

### CMP-102 SideToggle (Buy/Sell)
- **Tier**: Molecule (trading) · **Purpose**: primary long/short direction selector on the order ticket.
- **Props**: `value: "buy"|"sell"` · `onChange` · `size` · `disabled?`.
- **A11y**: CMP-003 SegmentedControl composition (`role="radiogroup"`), buy option always labelled "Buy / Long", sell "Sell / Short" (full words, not just colour-coded B/S).
- **Tokens**: `color.buy`, `color.sell`.
- **API sketch**: `interface SideToggleProps { value: "buy"|"sell"; onChange: (v:"buy"|"sell")=>void; size?: "sm"|"md"; disabled?: boolean; }`
- **Data contract**: pure UI state, no direct WS/REST dependency (value flows into CMP-107 OrderTicket's submit payload).
- **Storybook**: Default, Disabled.
- **Tests**: unit, visual, axe, keyboard.

### CMP-103 OrderTypeTabs
- **Tier**: Molecule (trading) · **Purpose**: Market/Limit/Conditional (and Emulated: Scaled/Iceberg/TWAP/Chase) order-type selector inside the order ticket.
- **Props**: `value` · `onChange` · `options: OrderTypeOption[]` (native vs emulated types flagged with an "(emulated)" tag per safety-transparency rule).
- **A11y**: CMP-042 Tabs composition; emulated-type tag rendered as visible text badge, not tooltip-only.
- **Tokens**: inherits CMP-042.
- **API sketch**: `type OrderTypeOption = { value: string; label: string; emulated?: boolean };`
- **Data contract**: `options` list is a static client-side vocabulary (native Bybit order types + CandleViewer-emulated types); no WS/REST dependency.
- **Storybook**: Default, WithEmulatedTypes.
- **Tests**: unit, visual, axe, keyboard.

### CMP-104 LeverageSlider
- **Tier**: Molecule (trading) · **Purpose**: per-account/per-symbol leverage selection with exchange-max clamp and liquidation-distance live preview.
- **Props**: `value: number` · `onChange` · `min: number` (default 1) · `max: number` (symbol/account max from Bybit) · `markPrice?: number` · `estLiqPrice?: number` (computed preview) · `disabled?/disabledReason?`.
- **A11y**: extends CMP-010 Slider contract; live liquidation-price preview announced via a debounced polite live region as the user drags (not on every pixel — throttled to ~250ms) plus always visible as text.
- **Tokens**: `color.action.*`, `color.status.warning` (near-max leverage zone shading on the track).
- **API sketch**:
```ts
interface LeverageSliderProps {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max: number;
  markPrice?: number;
  estLiqPrice?: number;
  disabled?: boolean;
}
```
- **Data contract**: `max` (per-symbol/account leverage cap) and `markPrice` sourced from Bybit `/v5/market/instruments-info` (REST) and the mark-price WS stream respectively; `estLiqPrice` is computed client-side from the current position/margin-mode inputs.
- **Storybook**: Default, NearMaxWarningZone, WithLiqPreview, Disabled.
- **Tests**: unit (clamp + preview calc), visual, axe, keyboard, throttled-announcement test.

### CMP-105 AccountMultiSelect
- **Tier**: Organism (trading) · **Purpose**: multi-account picker for trade-group fan-out — select N sub-accounts, each shown with its ProfileBadge and per-account editable overrides.
- **Props**: `accounts: {id,label,badge:ProfileBadgeProps,selected,profileSummary}[]` · `onToggle` · `onSelectAll` · `onEditProfile(accountId)` · `maxSelectable?: number` (sub-account cap 5/20).
- **A11y**: `role="group"` with a `listbox`-like multi-select pattern (`aria-multiselectable="true"`), each row a `role="option"` `aria-selected`; "select all" is a distinct labelled control, not implicit.
- **Tokens**: `color.surface.raised`, `space.list.row`.
- **API sketch**:
```ts
interface AccountMultiSelectProps {
  accounts: Array<{
    id: string; label: string; badge: ProfileBadgeProps;
    selected: boolean; profileSummary: string; // "5x, 2% risk, allowed: BTC,ETH"
  }>;
  onToggle: (id: string) => void;
  onSelectAll: (selected: boolean) => void;
  onEditProfile: (id: string) => void;
  maxSelectable?: number;
}
```
- **Data contract**: `accounts` list sourced from the account-management REST endpoint (sub-account roster + profile settings); `profileSummary` is derived client-side from each account's saved risk-profile record.
- **Storybook**: Default, AllSelected, AtCap, EditProfileInline.
- **Tests**: unit (cap enforcement), visual, axe, keyboard multi-select.

### CMP-106 ProfileBadge (account identity chip)
- **Tier**: Molecule (trading) · **Purpose**: compact per-account identity used across AccountMultiSelect, PositionsGrid, OrderRow — colour-coded avatar + account nickname + env dot.
- **Props**: `accountId` · `label` · `color` · `env: "demo"|"live"` · `role?: "main"|"sub"`.
- **A11y**: `aria-label="{label}, {env} account"`; env dot paired with the global EnvBadgeLocal contract (text-equivalent available on focus/tooltip).
- **Tokens**: `color.avatar.palette[]`, `color.env.*`.
- **API sketch**: `interface ProfileBadgeProps { accountId: string; label: string; color: string; env: "demo"|"live"; role?: "main"|"sub"; }`
- **Data contract**: `label`/`color`/`env`/`role` sourced from the account-management REST record for the given `accountId`; no live WS dependency.
- **Storybook**: Main, Sub, Demo, Live.
- **Tests**: unit, visual, axe.

### CMP-107 OrderTicket
- **Tier**: Organism (trading) · **Purpose**: the primary execution surface — side, symbol, order type, price/qty, TP/SL attach, account(s), submit. Composes CMP-100/101/102/103/104/105/106.
- **Props**: `symbol` · `side` · `orderType` · `price?/qty` · `accounts: AccountMultiSelectProps["accounts"]` · `tpSl?: {tpMode,tpValue,slMode,slValue}` · `oneClickArmed: boolean` · `onSubmit` · `env: "demo"|"live"`.
- **States**: idle, validating, submitting, submitted-ack, rejected(with reason), rate-limited(with retry countdown).
- **A11y**: submit button uses CMP-044 ConfirmDialog when `!oneClickArmed`; when armed, submit still requires an explicit press (never fires from focus/hover) and shows a persistent "1-click ARMED" text+icon indicator per §3.1.5; rejection reason rendered via CMP-027 `role="alert"`.
- **Tokens**: inherits children; `color.buy/sell` on submit button per side.
- **API sketch**:
```ts
interface OrderTicketProps {
  symbol: string;
  side: "buy" | "sell";
  orderType: string;
  price?: number; qty: number;
  accounts: AccountMultiSelectProps["accounts"];
  tpSl?: { tpMode: "ticks"|"pct"|"r"; tpValue: number; slMode: "ticks"|"pct"|"r"; slValue: number };
  oneClickArmed: boolean;
  env: "demo" | "live";
  onSubmit: (order: OrderDraft) => Promise<OrderAck | OrderRejection>;
}
```
- **Data contract**: on submit, posts an `OrderDraft` to the order-placement REST endpoint (Bybit `/v5/order/create` proxied through the backend per account); `submitted-ack`/`rejected`/`rate-limited` states are driven by the REST response and the order-update WS stream per `14-screens-catalogue.md` §0.4.
- **Storybook**: Market, Limit, Conditional, OneClickArmed, MultiAccountFanOut, Rejected, RateLimited.
- **Tests**: unit, visual, axe, keyboard end-to-end submit path, performance (order click→ack ≤500ms p95 budget instrumented in test), RBAC-disabled test (Viewer role).

### CMP-108 DomLadderRow
- **Tier**: Molecule (trading, canvas-adjacent) · **Purpose**: one price row of the DOM ladder — price, bid/ask size bars, own-order markers, click-to-trade.
- **Props**: `price: number` · `bidSize?: number` · `askSize?: number` · `isBestBid?/isBestAsk?: boolean` · `ownOrders?: OwnOrderMarker[]` · `onClickBuy/onClickSell/onDragReprice/onCancel`.
- **A11y**: implemented as a real focusable DOM row (`role="row"` inside `role="grid"` ladder) even though visually rendered on a canvas-adjacent surface — this is a DOM row, not a canvas primitive, specifically so it's natively accessible; `aria-label` composes "Price 65,432; bid size 1.2; ask size 0.8; your buy order 0.5 at this price"; roving-tabindex up/down navigates rows, `Enter`=buy (configurable), `Shift+Enter`=sell, `Delete`=cancel own order at row.
- **Tokens**: `color.buy/sell`, `font.mono`, `color.surface.ownorder`.
- **API sketch**:
```ts
interface DomLadderRowProps {
  price: number;
  bidSize?: number; askSize?: number;
  isBestBid?: boolean; isBestAsk?: boolean;
  ownOrders?: Array<{ id: string; side: "buy"|"sell"; qty: number }>;
  onClickBuy: (price: number) => void;
  onClickSell: (price: number) => void;
  onDragReprice: (orderId: string, newPrice: number) => void;
  onCancel: (orderId: string) => void;
}
```
- **Data contract**: `bidSize`/`askSize` driven by the Bybit orderbook WS stream (`orderbook.{depth}.{symbol}`, delta-merged client-side); `ownOrders` driven by the account's order-update WS stream; `onClickBuy`/`onClickSell`/`onDragReprice`/`onCancel` call the order-placement/amend/cancel REST endpoints.
- **Storybook**: Default, BestBidAsk, WithOwnOrders, HighDensity(compact).
- **Tests**: unit, visual, axe, keyboard row-nav + buy/sell/cancel, performance (row update under 10Hz book stream, virtualized list of hundreds of rows).

### CMP-109 FootprintCell
- **Tier**: Molecule (trading, canvas-adjacent, WebGL-rendered) · **Purpose**: single per-bar-per-price footprint cell (bid×ask volume, delta, imbalance colouring) — the highest-risk rendering surface per research digest 10 (text-heavy cell rendering).
- **Props**: `bidVol: number` · `askVol: number` · `delta: number` · `isImbalanced?: boolean` · `cellMode: "volume"|"bidask"|"delta"|"delta+total"` · `displayMode: "profile"|"box"` · `inputSource: "aggTrades"|"numTrades"|"orderEstimated"`.
- **A11y**: rendered on the WebGL canvas; **every cell is mirrored** by an off-screen DOM node per `05-accessibility-standard.md` §6.1 ("canvas control surrogate" pattern) — `tabindex`-able, `aria-label` composes "Price 65,430; bid 12.4; ask 8.1; delta +4.3" plus "(estimated)" when `inputSource==="orderEstimated"`; arrow keys move focus cell-to-cell (price axis / time axis), `Enter` opens the cell-detail Drawer (CMP-046).
- **Tokens**: `color.footprint.bid/ask`, `color.footprint.imbalance`, `type.num.xs`/`type.num.sm` (LOD: text hidden below the `LOD_PROFILE_M0` threshold set — `docs/design/E06/E06-D01.md` §2 — L0 ≥12px/L1 ≥10px cell height; cell still focusable and its DOM-mirror label always carries full value regardless of zoom-driven text hiding). Delta direction additionally uses a `▲`/`▼` glyph + sign; imbalance uses a border-outline in addition to `color.footprint.imbalance`; `orderEstimated` cells render a hatch overlay — see `docs/design/E06/E06-D01.md` §3 for the full non-colour encoding spec.
- **API sketch**:
```ts
interface FootprintCellData {
  price: number; bidVol: number; askVol: number; delta: number;
  isImbalanced?: boolean; inputSource: "aggTrades" | "numTrades" | "orderEstimated";
}
// Rendered by the WebGL engine; DOM-mirror node generated 1:1 per visible cell:
interface FootprintCellMirrorProps extends FootprintCellData {
  onFocus: () => void; onActivate: () => void; // Enter -> detail drawer
}
```
- **Data contract**: `bidVol`/`askVol`/`delta` computed client-side from the aggregated-trades WS stream (`publicTrade.{symbol}`) bucketed per bar/price; `inputSource` reflects which trade-classification method was used (see `14-screens-catalogue.md` §0.4 for the exact stream/topic list).
- **Storybook**: VolumeMode, BidAskMode, DeltaMode, Imbalanced, EstimatedOrderInput, LODTextHidden(zoomed-out), DomMirrorFocusDemo.
- **Tests**: unit (cell colour/threshold logic), visual regression (all cellMode × displayMode combinations), axe on the DOM-mirror layer specifically, keyboard cell-to-cell navigation test, performance test (render N cells/bar × M bars at target density, 58fps budget).

### CMP-110 ProfileBar (volume/delta profile histogram bar)
- **Tier**: Molecule (trading, chart-primitive-adjacent) · **Purpose**: one horizontal bar of the volume/delta/TPO profile histogram at a given price level.
- **Props**: `price: number` · `value: number` · `maxValue: number` (for width scaling) · `isPoc?: boolean` · `isValueArea?: boolean` · `mode: "volume"|"delta"|"tpo"`.
- **A11y**: same DOM-mirror-per-bar pattern as FootprintCell; POC and Value-Area status conveyed by border/pattern + text label, never fill-colour alone.
- **Tokens**: `color.profile.bar`, `color.profile.poc`, `color.profile.valuearea`.
- **API sketch**: `interface ProfileBarProps { price: number; value: number; maxValue: number; isPoc?: boolean; isValueArea?: boolean; mode: "volume"|"delta"|"tpo"; }`
- **Data contract**: `value` computed client-side from the same aggregated-trades WS stream as CMP-109, bucketed by price level across the profile's bar range; POC/value-area flags are a client-side derived calculation, not a Bybit-provided field.
- **Storybook**: Volume, Delta, TPO, POC, ValueArea.
- **Tests**: unit, visual, axe (mirror), performance (full profile render, hundreds of levels).

### CMP-111 HeatmapCell (DOM liquidity heatmap unit, texture-backed)
- **Responsibility split (disambiguation vs. CMP-193 HeatmapOverlay)**: CMP-111 owns the **logical data model and a11y contract** — the per-cell `{time, price, intensity, side}` shape, the windowed-accessibility-tree behaviour (§6.2), and the Storybook/test requirements for that accessible summary (sparkline+table reveal, keyboard reveal path). CMP-193 owns the **engine mount point** — the WebGL canvas element that actually paints the texture, its pane position, axis-sync, and render/upload performance contract (10Hz cadence budget). Ticket-writers: file a11y/data-shape/interaction tickets against **CMP-111**; file rendering/performance/mount-point tickets against **CMP-193**. Neither entry duplicates the other's Storybook stories or test list.
- **Tier**: Chart-primitive (trading) · **Purpose**: one time×price cell of the resting-liquidity heatmap, rendered via rolling WebGL texture (per research digest 10 §"DOM heatmap") — not an individual DOM node at the rendering layer (too dense: tens of thousands of cells at 10Hz), but exposed through a windowed accessible summary per §6.2 of the a11y standard.
- **Props** (logical unit, not literally instantiated per-cell in the DOM): `time: number` · `price: number` · `intensity: number` (0-1 normalized) · `side: "bid"|"ask"`.
- **A11y**: per §6.2 "windowed accessibility tree" — the currently-focused/hovered price row surfaces its full time-series as an accessible sparkline+table on demand (via keyboard: focus the DOM ladder row at that price, press a documented key to reveal "liquidity history at this level"), rather than mirroring every cell; this windowing strategy is the binding engine-design constraint referenced by `26-chart-engine-design.md`.
- **Tokens**: `color.heatmap.bid.ramp[]`, `color.heatmap.ask.ramp[]` (green=bid/red=ask default, user-configurable convention per owner decision #10).
- **API sketch**:
```ts
interface HeatmapFrame {
  time: number;
  levels: Array<{ price: number; bidIntensity: number; askIntensity: number }>;
}
interface HeatmapCanvasProps {
  frames: HeatmapFrame[]; // rolling buffer, engine manages texture upload
  colorConvention: "green-bid-red-ask" | "custom";
  onFocusLevel: (price: number) => LevelHistorySummary; // powers the windowed a11y reveal
}
```
- **Data contract**: `intensity`/`side` driven by the Bybit orderbook WS stream (`orderbook.{depth}.{symbol}`), rolled into the engine's texture buffer client-side; no REST dependency at render time (REST used only for initial snapshot per Bybit's orderbook sync protocol).
- **Storybook**: LowDensity(visual-only, cannot show 10Hz texture in static story — documents fallback static frame), WindowedA11yRevealDemo.
- **Tests**: visual (static-frame snapshot only, texture pipeline covered by engine perf tests instead), axe on the windowed-reveal DOM output, performance test (texture update cost, engine-level not component-level, cross-referenced to `26-chart-engine-design.md`).

### CMP-112 BigTradeBubble
- **Tier**: Chart-primitive (trading) · **Purpose**: marker for a large trade print, sized/coloured by notional.
- **Props**: `time` · `price` · `notional` · `side: "buy"|"sell"` · `sizeScale: "linear"|"log"` · `shape: "circle"|"square"|"diamond"|"text"`.
- **A11y**: DOM-mirror marker (sparse — big trades are inherently low-frequency, so full per-marker mirroring is affordable, unlike the heatmap) with `aria-label` "Big sell, 42,000 USDT, 65,410, 14:32:01".
- **Tokens**: `color.buy/sell`, `size.bubble.scale`.
- **API sketch**: `interface BigTradeBubbleProps { time: number; price: number; notional: number; side: "buy"|"sell"; sizeScale: "linear"|"log"; shape: "circle"|"square"|"diamond"|"text"; }`
- **Data contract**: driven by the aggregated-trades WS stream (`publicTrade.{symbol}`), filtered client-side by a notional threshold to flag "big trades"; no REST dependency.
- **Storybook**: Circle, Square, Diamond, TextMode, LogScale.
- **Tests**: unit, visual, axe (mirror), interaction (hover/focus detail tooltip).

### CMP-113 HeatmapLegend
- **Tier**: Molecule (trading) · **Purpose**: colour-ramp legend for the DOM heatmap explaining intensity→colour mapping and current bid/ask convention.
- **Props**: `ramp: {color,value}[]` · `convention: "green-bid-red-ask"|"red-bid-green-ask"` · `scaleType: "linear"|"log"`.
- **A11y**: composed of CMP-037 SwatchLegendItem rows; convention explicitly stated as text ("Green = bid/buy liquidity") so colour-blind or screen-reader users aren't dependent on hue.
- **Tokens**: `color.heatmap.*`.
- **API sketch**: `interface HeatmapLegendProps { ramp: Array<{color:string; value:number}>; convention: "green-bid-red-ask"|"red-bid-green-ask"; scaleType: "linear"|"log"; }`
- **Data contract**: `ramp` is a client-side derived colour scale (from tokens + current min/max intensity in view); no direct WS/REST dependency.
- **Storybook**: Default, AlternateConvention, LogScale.
- **Tests**: unit, visual, axe.

### CMP-114 PositionsGrid
- **Tier**: Organism (trading) · **Purpose**: cross-symbol/cross-account positions table (extends CMP-049 Table) with liq-proximity warning rows.
- **Props**: `positions: PositionRow[]` · `groupBy: "symbol"|"account"|"manager"` · `columns` · `onCloseAll?/onFlatten(rowId)`.
- **A11y**: extends CMP-049 contract; liq-proximity warning is a row-level Callout-style icon+text (amber/red) never a bare row-background colour change alone.
- **Tokens**: `color.status.warning/danger`, inherits CMP-049.
- **API sketch**:
```ts
interface PositionRow {
  id: string; accountId: string; symbol: string; side: "long"|"short";
  size: number; entryPrice: number; markPrice: number; liqPrice: number;
  unrealizedPnl: number; leverage: number; marginMode: "cross"|"isolated";
  liqDistancePct: number; // drives warning threshold
}
interface PositionsGridProps {
  positions: PositionRow[];
  groupBy: "symbol" | "account" | "manager";
  onFlatten: (id: string) => void;
}
```
- **Data contract**: `positions` sourced from the positions WS stream (`position.{symbol}` / private position-update topic) merged with the periodic REST position-list reconciliation snapshot per `14-screens-catalogue.md` §0.4; liq-proximity computed client-side from position + mark-price data.
- **Storybook**: Default, GroupedByAccount, LiqWarningRows, Empty.
- **Tests**: unit, visual, axe, keyboard row-nav, performance (100+ rows @60fps scroll).

### CMP-115 OrderRow
- **Tier**: Molecule (trading) · **Purpose**: one row in the open-orders table — symbol, side, type, price, qty, filled%, status, cancel/amend actions.
- **Props**: `order: OrderRowData` · `onAmend` · `onCancel`.
- **A11y**: status conveyed by icon+text (working/partially-filled/rejected/cancelling); amend/cancel are labelled IconButtons.
- **Tokens**: `color.status.*`, `font.mono`.
- **API sketch**:
```ts
interface OrderRowData {
  id: string; symbol: string; side: "buy"|"sell"; type: string;
  price?: number; qty: number; filledQty: number;
  status: "working"|"partially_filled"|"filled"|"cancelled"|"rejected";
  rejectionReason?: string;
}
```
- **Data contract**: sourced from the account's order-update WS stream (private `order` topic) merged with the periodic REST open-orders reconciliation snapshot.
- **Storybook**: Working, PartiallyFilled, Rejected, Cancelling.
- **Tests**: unit, visual, axe, keyboard.

### CMP-116 PnLBadge
- **Tier**: Atom (trading) · **Purpose**: coloured, signed PnL value display used across positions/journal/reports.
- **Props**: `value: number` · `format: "abs"|"pct"|"r"` · `size`.
- **A11y**: extends CMP-020 NumericText — sign always shown as `+`/`-` glyph plus colour, and an `aria-label` spells out "profit"/"loss" in words for screen readers ("profit 420 dollars", not just "+420").
- **Tokens**: `color.text.buy/sell`, `font.mono`.
- **API sketch**: `interface PnLBadgeProps { value: number; format: "abs"|"pct"|"r"; size?: "sm"|"md"|"lg"; }`
- **Data contract**: PnL value computed client-side from the position WS stream's entry price/size and the mark-price WS stream; refreshed at the mark-price stream's cadence.
- **Storybook**: Profit, Loss, Flat, RMultiple.
- **Tests**: unit, visual, axe.

### CMP-117 RiskLockoutBanner ("FREEZE" state)
- **Tier**: Molecule (trading, risk-critical) · **Purpose**: per-manager/per-account trading-halted state indicator on the Risk Dashboard and locally on any affected order ticket.
- **Props**: `scope: "account"|"manager"|"global"` · `reason: string` · `until?: number` (epoch, for time-boxed lockouts) · `onOwnerOverride?` (owner-only unlock).
- **A11y**: `role="alert"`, override action gated by CMP-044 ConfirmDialog, reason always full text (not a code).
- **Tokens**: `color.status.danger`.
- **Data contract**: driven by the account's risk-lockout state, which is derived server-side (rule-engine/backend risk service) and delivered via a dedicated account-status WS topic (or REST poll fallback) per `14-screens-catalogue.md` §0.4.
- **Storybook**: AccountScope, GlobalScope, TimeBoxed, OwnerOverrideAvailable.
- **Tests**: unit, visual, axe, RBAC test (override hidden/disabled for non-owner).

### CMP-118 AlgoProgressCard (emulated TWAP/Iceberg/Chase/Scaled)
- **Tier**: Molecule (trading) · **Purpose**: live progress of an emulated multi-slice algo order.
- **Props**: `algoType: "twap"|"iceberg"|"chase"|"scaled"` · `slicesDone` · `slicesTotal` · `avgFillPrice?` · `status` · `onPause/onResume/onCancelAll` · `emulated: true` (always, per safety-transparency — never hides that this is client-side emulation, not exchange-native).
- **A11y**: progress via CMP-023 ProgressBar contract, "(emulated)" text always visible not just in a tooltip.
- **Tokens**: inherits CMP-023.
- **API sketch**:
```ts
interface AlgoProgressCardProps {
  algoType: "twap" | "iceberg" | "chase" | "scaled";
  slicesDone: number; slicesTotal: number;
  avgFillPrice?: number;
  status: "running"|"paused"|"completed"|"cancelled"|"error";
  onPause: () => void; onResume: () => void; onCancelAll: () => void;
}
```
- **Data contract**: progress state sourced from the client-side emulated-algo execution engine's local state machine (TWAP/Iceberg/Chase/Scaled are client-emulated, not native Bybit order types), with each child order's fill state driven by the order-update WS stream.
- **Storybook**: Running, Paused, Completed, Error.
- **Tests**: unit, visual, axe, keyboard controls.

### CMP-119 BracketEditor (SL/TP attach widget)
- **Tier**: Molecule (trading) · **Purpose**: attach/edit stop-loss and take-profit on the order ticket or an existing position, in ticks/%/R-multiple units, with native-exchange-SL guarantee messaging (safety invariant, `24-owner-decisions.md` §3).
- **Props**: `slMode/tpMode: "ticks"|"pct"|"r"` · `slValue/tpValue` · `onChange` · `partialTpLevels?: {pct,rMultiple}[]` · `nativeSlConfirmed: boolean` (must be true before submit is enabled — reflects the always-native-SL invariant).
- **A11y**: FormSection (CMP-065) composition; the native-SL guarantee is rendered as a persistent, non-dismissible inline note, not a one-time toast.
- **Tokens**: inherits CMP-100/CMP-101.
- **API sketch**:
```ts
interface BracketEditorProps {
  slMode: "ticks"|"pct"|"r"; slValue: number;
  tpMode: "ticks"|"pct"|"r"; tpValue: number;
  partialTpLevels?: Array<{ pct: number; rMultiple: number }>;
  onChange: (bracket: BracketConfig) => void;
}
```
- **Data contract**: on save, posts SL/TP as conditional orders via the order-placement REST endpoint (Bybit `/v5/order/create` with `stopLoss`/`takeProfit` fields or separate conditional orders per exchange semantics); live SL/TP order state tracked via the order-update WS stream.
- **Storybook**: Default, PartialTpLadder, RMultipleMode.
- **Tests**: unit, visual, axe.

### CMP-120 TrailingStopEditor
- **Tier**: Molecule (trading) · **Purpose**: configure fixed-offset/%/ATR/structure/MA-based trailing stop (per research digest 09 §3).
- **Props**: `mode: "fixed"|"pct"|"atr"|"structure"|"ma"` · `params: Record<string,number>` · `onChange` · `preview?: {currentStopPrice}`.
- **A11y**: mode switch via CMP-009 Select, params rendered via CMP-040 FormField set specific to mode.
- **Tokens**: inherits CMP-100.
- **API sketch**: `interface TrailingStopEditorProps { mode: "fixed"|"pct"|"atr"|"structure"|"ma"; params: Record<string, number>; onChange: (cfg: TrailingStopConfig) => void; }`
- **Data contract**: trailing logic runs client-side (or via backend-scheduled job for closed-app resilience per owner decision) against the mark-price WS stream, re-submitting stop-order amendments via the order-amend REST endpoint as the trail advances.
- **Storybook**: Fixed, Percentage, ATR, Structure, MovingAverage.
- **Tests**: unit, visual, axe.

### CMP-121 RiskCalculatorPanel
- **Tier**: Molecule (trading) · **Purpose**: derives position size from account equity, risk %, and stop distance — feeds QtyInput's `riskPct` sizing mode.
- **Props**: `equity` · `riskPct` · `stopDistance` · `resultQty` (computed, read-only display) · `onApply`.
- **A11y**: computed result is a live-region-announced KeyValueRow (CMP-036), "Apply" button pushes value into the ticket.
- **Tokens**: `font.mono`.
- **Data contract**: pure client-side calculation from `equity` (account-equity WS/REST feed), user-entered `riskPct`, and `stopDistance`; no independent WS/REST call of its own.
- **Storybook**: Default, ZeroStopDistance(error state).
- **Tests**: unit (calc formula), visual, axe.

### CMP-122 QuickSizeButtons ("size ladder" presets)
- **Tier**: Molecule (trading) · **Purpose**: row of quick quantity/%-equity preset buttons (hotkey-bindable per digest 09 §1).
- **Props**: `presets: {label,value}[]` · `activeValue?` · `onSelect` · `hotkeyHints?: string[]`.
- **A11y**: CMP-003 SegmentedControl-like group; hotkey hints shown via CMP-022 Kbd inline.
- **Tokens**: inherits CMP-001.
- **Data contract**: `presets` are user-configured client-side/local-settings values (persisted via the settings REST endpoint); no live WS dependency.
- **Storybook**: Default, WithHotkeyHints.
- **Tests**: unit, visual, axe, keyboard.

### CMP-123 FlattenAllButton
- **Tier**: Molecule (trading, risk-critical) · **Purpose**: global panic-button — closes all positions and cancels all working orders for the active scope, gated by ConfirmDialog `hold` or `typed` variant.
- **Props**: `scope: "account"|"all-accounts"` · `onConfirm`.
- **A11y**: CMP-044 composition, always keyboard-operable (never a mouse-hold-only gate).
- **Tokens**: `color.status.danger`.
- **Data contract**: on confirm, calls the bulk cancel-all-orders and close-all-positions REST endpoints (Bybit `/v5/order/cancel-all` + market-close per position) for the given `scope`; result surfaced via the order-update/position WS streams.
- **Storybook**: AccountScope, AllAccountsScope.
- **Tests**: unit, visual, axe, keyboard-only confirm path test.

### CMP-124 TradeGroupSummaryCard
- **Tier**: Molecule (trading) · **Purpose**: aggregate view of one fan-out trade group (N accounts, aggregate fill state, per-account breakdown expandable).
- **Props**: `group: TradeGroupSummary` · `expanded?` · `onToggleExpand`.
- **A11y**: Accordion (CMP-051) composition; per-account rows use ProfileBadge (CMP-106).
- **Tokens**: inherits CMP-050.
- **API sketch**:
```ts
interface TradeGroupSummary {
  groupId: string; symbol: string; side: "buy"|"sell";
  accounts: Array<{ accountId: string; status: string; filledQty: number; avgPrice?: number }>;
}
```
- **Data contract**: `group` aggregated client-side from the order-update WS stream across the group's constituent per-account orders (fan-out orders share a client-generated `groupId` correlation key, not a Bybit-native construct).
- **Storybook**: Collapsed, Expanded, PartialFailure(one account rejected).
- **Tests**: unit, visual, axe.

### CMP-125 SymbolInfoPopover
- **Tier**: Molecule (trading) · **Purpose**: quick reference for a symbol's tick size, lot size, max leverage, funding rate, OI — surfaced from SymbolSearchInput/Watchlist.
- **Props**: `symbol` · `instrumentInfo: InstrumentInfo`.
- **A11y**: CMP-017 Popover composition; content is a KeyValueRow (CMP-036) list.
- **Tokens**: inherits CMP-017.
- **Data contract**: `instrumentInfo` sourced from Bybit `/v5/market/instruments-info` (REST, cached) plus the funding-rate and open-interest WS/REST feeds per `14-screens-catalogue.md` §0.4.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-126 FundingCountdown
- **Tier**: Atom (trading) · **Purpose**: time-to-next-funding + current funding rate display.
- **Props**: `nextFundingTime: number` · `rate: number`.
- **A11y**: extends CMP-035 Countdown pattern; rate sign conveyed via CMP-020 NumericText contract.
- **Tokens**: `font.mono`, `color.text.buy/sell`.
- **Data contract**: `nextFundingTime`/`rate` sourced from Bybit's funding-rate WS stream (`tickers.{symbol}`) or REST fallback poll.
- **Storybook**: Positive, Negative, UnderOneMinute.
- **Tests**: unit, visual, axe.

### CMP-127 LiquidationMarker (chart annotation)
- **Tier**: Chart-primitive (trading) · **Purpose**: marks a liquidation print on the chart/tape.
- **Props**: `time` · `price` · `side` · `notional`.
- **A11y**: DOM-mirror marker (sparse events), same pattern as BigTradeBubble.
- **Tokens**: `color.status.danger`.
- **Data contract**: computed client-side from the position WS stream's liquidation-price field (or client-computed estimate where the field is absent), rendered as a chart-engine overlay per CMP-197.
- **Storybook**: Default.
- **Tests**: unit, visual, axe (mirror).

### CMP-128 MarginModeToggle
- **Tier**: Molecule (trading) · **Purpose**: Cross/Isolated margin mode selector, per symbol/account.
- **Props**: `value: "cross"|"isolated"` · `onChange` · `disabled?/disabledReason?` (disabled while a position is open, per Bybit constraint).
- **A11y**: CMP-003 composition, disabled-reason explains "cannot change margin mode with an open position."
- **Tokens**: inherits CMP-003.
- **Data contract**: reads/writes the account's margin-mode setting via the account-config REST endpoint (Bybit `/v5/position/switch-isolated`); reflects the current mode from the account-config REST snapshot.
- **Storybook**: Cross, Isolated, DisabledOpenPosition.
- **Tests**: unit, visual, axe.

### CMP-129 PositionModeToggle (One-Way/Hedge)
- **Tier**: Molecule (trading) · **Purpose**: One-Way vs Hedge `positionIdx` mode selector.
- **Props**: `value: "one-way"|"hedge"` · `onChange` · `disabled?/disabledReason?`.
- **Tokens**: inherits CMP-003.
- **Data contract**: reads/writes the account's position-mode setting via the account-config REST endpoint (Bybit `/v5/position/switch-mode`).
- **Storybook**: OneWay, Hedge, Disabled.
- **Tests**: unit, visual, axe.

### CMP-130 SlippageEstimateChip
- **Tier**: Atom (trading) · **Purpose**: estimated slippage/impact preview for a given order size against current book depth.
- **Props**: `estimatedSlippageBps: number` · `confidence: "low"|"medium"|"high"` (reuses CMP-032 Rating dots).
- **A11y**: `(estimated)` chip variant (CMP-011) with InfoPanel link (CMP-069) explaining methodology.
- **Tokens**: inherits CMP-011.
- **Data contract**: estimate computed client-side from the current orderbook WS snapshot (walking the book for the entered qty) at order-entry time; not a Bybit-provided field.
- **Storybook**: Low, Medium, High.
- **Tests**: unit, visual, axe.

### CMP-131 SpeedOfTapeGauge
- **Tier**: Molecule (trading, chart-adjacent) · **Purpose**: rolling trades/sec + notional/sec gauge or strip-chart.
- **Props**: `tradesPerSec: number` · `notionalPerSec: number` · `mode: "gauge"|"strip"` · `alertThreshold?`.
- **A11y**: numeric values always shown as text alongside the gauge needle position (never gauge-angle-only); threshold breach announced via polite live region (throttled).
- **Tokens**: `color.status.warning`, `font.mono`.
- **Data contract**: computed client-side as a rolling window over the aggregated-trades WS stream (`publicTrade.{symbol}`).
- **Storybook**: Gauge, Strip, ThresholdBreach.
- **Tests**: unit, visual, axe, throttled-announcement test.

### CMP-132 ImbalanceStackIndicator
- **Tier**: Chart-primitive (trading) · **Purpose**: on-chart marker for a stacked/diagonal imbalance zone (Imbalance Tracker) with virgin-zone/zone-crossed states.
- **Props**: `zone: {priceFrom,priceTo,barsExtent}` · `state: "virgin"|"crossed"` · `direction: "bid"|"ask"`.
- **A11y**: DOM-mirror region marker with `aria-label` describing zone + state in words.
- **Tokens**: `color.buy/sell`, `pattern.hatch` (virgin vs crossed distinguished by pattern, not colour alone).
- **Data contract**: zone state computed client-side by the imbalance-detector heuristic running over the aggregated-trades/orderbook WS streams; `(estimated)`-class output per `05-accessibility-standard.md`/owner decisions on heuristic labelling.
- **Storybook**: Virgin, Crossed, BidSide, AskSide.
- **Tests**: unit, visual, axe.

### CMP-133 RegimeIndicatorChip
- **Tier**: Atom (trading) · **Purpose**: current market-regime classification chip (trend/range/volatile/calm), always `(estimated)`.
- **Props**: `regime: "trend"|"range"|"volatile"|"calm"` · `confidence`.
- **Tokens**: inherits CMP-011 estimated variant.
- **Data contract**: `regime`/`confidence` computed client-side by the regime-classifier heuristic over recent OHLCV + orderbook WS data; always rendered with the `(estimated)` chip.
- **Storybook**: AllRegimes.
- **Tests**: unit, visual, axe.

### CMP-134 DetectorEventCard (iceberg/stop-run/absorption)
- **Tier**: Molecule (trading) · **Purpose**: card describing one heuristic detector event, always carrying the `(estimated)` chip and a link to the methodology InfoPanel — used in journal auto-tags and live event feed.
- **Props**: `detectorType: "iceberg"|"stop_run"|"absorption"|"unfinished_auction"` · `time` · `price` · `confidence` · `details: Record<string,unknown>`.
- **A11y**: Card (CMP-050) composition with CMP-011 estimated chip mandatory.
- **Tokens**: inherits CMP-050.
- **Data contract**: `detectorType`/`confidence`/`details` produced client-side (or by a backend detector service, per architecture decision) from the aggregated-trades/orderbook WS streams; always `(estimated)`-flagged heuristic output, never treated as ground truth.
- **Storybook**: Iceberg, StopRun, Absorption, UnfinishedAuction.
- **Tests**: unit, visual, axe.

### CMP-135 VwapBandLegend
- **Tier**: Molecule (trading, chart-adjacent) · **Purpose**: legend explaining VWAP + 1/2/3σ envelope bands on the chart.
- **Props**: `bands: {sigma,color,visible}[]` · `onToggleVisibility`.
- **Tokens**: inherits CMP-037.
- **Data contract**: VWAP + sigma bands computed client-side from the aggregated-trades WS stream anchored per CMP-137's selected anchor mode; no direct Bybit-provided VWAP field is used.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-136 DisclosedInventoryChip ("Deep-Reload / liquidity refresh" indicator)
- **Tier**: Atom (trading) · **Purpose**: marks a book-reload event (fresh directional liquidity) at a price level, MBP-derived (not `(estimated)`, since fully derivable per digest — flagged distinctly from true heuristics).
- **Props**: `price` · `direction: "bid"|"ask"` · `magnitude`.
- **Tokens**: `color.buy/sell`.
- **Data contract**: derived client-side from Bybit's Market-By-Price (MBP) orderbook WS stream deltas (fully derivable, not a heuristic estimate, per digest 10).
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-137 SessionVwapAnchorPicker
- **Tier**: Molecule (trading) · **Purpose**: choose VWAP anchor (session/day/custom bar) given the 24/7-market redefinition need (no natural RTH).
- **Props**: `anchorMode: "utc-day"|"session"|"custom-bar"` · `customBarTime?` · `onChange`.
- **Tokens**: inherits CMP-009.
- **Data contract**: `anchorMode`/`customBarTime` are client-side/local-settings values that parameterise the VWAP calculation (CMP-135); no independent WS/REST call.
- **Storybook**: UtcDay, Session, CustomBar.
- **Tests**: unit, visual, axe.

### CMP-138 RiskCapMeter
- **Tier**: Molecule (trading, risk-critical) · **Purpose**: visual meter of current exposure/daily-loss against configured caps, per account or aggregate.
- **Props**: `current: number` · `cap: number` · `label` · `scope: "symbol"|"manager"|"portfolio"`.
- **A11y**: extends CMP-023 ProgressBar contract; breach state (current≥cap) shown with icon+text, triggers CMP-117 RiskLockoutBanner elsewhere in the app.
- **Tokens**: `color.status.warning/danger`.
- **Data contract**: `current`/`cap` sourced from the account-status/risk-service WS topic (aggregate exposure or daily-loss figures) merged with the user-configured cap from the risk-settings REST endpoint, per `14-screens-catalogue.md` §0.4.
- **Storybook**: Normal, Near-Cap, Breached.
- **Tests**: unit, visual, axe.

### CMP-139 EnvironmentAwareOrderGuard (wrapper)
- **Tier**: Molecule (utility, trading-critical) · **Purpose**: the enforcement wrapper guaranteeing no live order can be placed while the workspace-level env context is `demo` and vice versa (defence-in-depth alongside server-side checks) — wraps CMP-107 OrderTicket and CMP-108 DomLadderRow's click-to-trade handlers.
- **Props**: `activeEnv: "demo"|"live"` · `orderEnv: "demo"|"live"` · `children`.
- **A11y**: mismatch renders the wrapped control disabled-with-reason (CMP-079 RbacGate pattern) rather than silently rerouting the order.
- **Tokens**: n/a (behavioural wrapper).
- **Data contract**: `activeEnv` sourced from the workspace-level environment-context store (client-side, backed by the session/account-selection REST state); `orderEnv` derived from the wrapped order's target account's `env` field (CMP-106 ProfileBadge data).
- **Storybook**: Matched, Mismatched.
- **Tests**: integration test — attempts to submit a live order while env=demo and asserts hard block + audit log entry.

---

## 5. Rule engine & node-graph components (CMP-140..159)

Both the form/condition-list editor and the visual node-graph editor compile to the same rule IR (owner decision #11); components in this band are shared or paired across the two editors where the underlying model is identical.

### CMP-140 RuleConditionRow
- **Tier**: Molecule (rule engine) · **Purpose**: one condition line in the form/condition-list editor — metric, operator, value/reference, boolean-join to the next row.
- **Props**: `metric: string` (from the metric vocabulary, e.g. `unrealized_r_multiple`, `atr(n)`, `spread_bps`) · `operator: ">"|">="|"<"|"<="|"=="|"!="|"crosses_above"|"crosses_below"` · `value: number | MetricRef` · `joinToNext?: "AND"|"OR"` · `onChange` · `onRemove` · `invalid?: string`.
- **A11y**: FormField (CMP-040) composition per sub-control; join-operator toggle is CMP-003; remove is a labelled IconButton; row order reflects evaluation order and is announced when reordered.
- **Tokens**: `font.mono` (numeric literals), `color.border.invalid`.
- **API sketch**:
```ts
interface RuleConditionRowProps {
  metric: string;
  operator: ">"|">="|"<"|"<="|"=="|"!="|"crosses_above"|"crosses_below";
  value: number | { metricRef: string };
  joinToNext?: "AND" | "OR";
  onChange: (patch: Partial<RuleConditionRowProps>) => void;
  onRemove: () => void;
  invalid?: string;
}
```
- **Storybook**: Default, MetricRefValue, JoinAnd, JoinOr, Invalid.
- **Tests**: unit (metric/operator compatibility validation, e.g. `crosses_above` invalid for boolean metrics), visual, axe, keyboard.

### CMP-141 RuleConditionGroup
- **Tier**: Molecule (rule engine) · **Purpose**: groups CMP-140 rows under one boolean mode (implicit AND, `any_of` OR, or nested AND+OR "Advanced"), up to the documented 4-condition DeepCharts-parity default (configurable higher in CandleViewer, since it targets live execution not just visual flags).
- **Props**: `rows: RuleConditionRowProps[]` · `mode: "and"|"or"|"advanced"` · `onAddRow` · `onChangeMode`.
- **A11y**: `fieldset`/`legend` grouping (CMP-065 FormSection base), nesting depth communicated via indentation + `aria-level` on a tree-like structure for "Advanced" mode.
- **Tokens**: `space.rulegroup.indent`.
- **Storybook**: And, Or, AdvancedNested.
- **Tests**: unit, visual, axe.

### CMP-142 RuleActionRow
- **Tier**: Molecule (rule engine) · **Purpose**: one action line — action type + params (from the action vocabulary: `place_order`, `modify_stop_loss`, `move_to_breakeven`, `scale_out`, `flatten_all_positions`, `halt_new_orders`, etc.).
- **Props**: `actionType: string` · `params: Record<string,unknown>` · `onChange` · `onRemove`.
- **A11y**: dynamic param form rendered via CMP-040 FormField per action-type schema.
- **Tokens**: inherits CMP-140.
- **API sketch**: `interface RuleActionRowProps { actionType: string; params: Record<string, unknown>; onChange: (p: Record<string,unknown>) => void; onRemove: () => void; }`
- **Storybook**: PlaceOrder, ModifyStopLoss, MoveToBreakeven, ScaleOut, FlattenAll, HaltNewOrders.
- **Tests**: unit (per-action-type param validation), visual, axe.

### CMP-143 RuleTriggerPicker
- **Tier**: Molecule (rule engine) · **Purpose**: choose the rule's trigger (`on_price_update`, `on_bar_close`, `on_order_fill`, `on_timer`, `on_indicator`) and timeframe.
- **Props**: `trigger: string` · `timeframe?: string` · `onChange`.
- **Tokens**: inherits CMP-009.
- **Storybook**: OnBarClose, OnFill, OnTimer, OnIndicator.
- **Tests**: unit, visual, axe.

### CMP-144 RuleScopeSelector
- **Tier**: Molecule (rule engine) · **Purpose**: choose what the rule applies to — symbol, account(s), `open_positions`/`pending_orders`/`account` scope.
- **Props**: `symbol?` · `accounts: string[]` · `appliesTo: "open_positions"|"pending_orders"|"account"`.
- **Tokens**: inherits CMP-105 AccountMultiSelect (reused).
- **Storybook**: SingleAccount, MultiAccount, AccountScope.
- **Tests**: unit, visual, axe.

### CMP-145 RuleFormEditor (organism)
- **Tier**: Organism (rule engine) · **Purpose**: full structured-form rule editor composing Trigger/Scope/Conditions/Actions + arm/simulate controls.
- **Props**: `rule: RuleDraft` · `onChange` · `onSimulate` · `onSave` · `armMode: "disarmed"|"simulate-only"|"live-armed"` · `onArmModeChange`.
- **A11y**: `live-armed` transition gated by ConfirmDialog (CMP-044, `variant="typed"`, must type the rule name) — arming a live rule is a destructive-class action per safety framing.
- **Tokens**: inherits FormSection (CMP-065).
- **Storybook**: Draft, SimulateOnly, LiveArmed, ValidationErrors.
- **Tests**: unit, visual, axe, keyboard, interaction (arm-confirm flow).

### CMP-146 NodeGraphCanvas
- **Tier**: Organism (rule engine, canvas-adjacent) · **Purpose**: the visual node-graph editor surface (React Flow/Rete.js-based per owner decision #11) — pan/zoom canvas hosting nodes and edges that compile to the same rule IR as CMP-145.
- **Props**: `nodes: NodeGraphNode[]` · `edges: NodeGraphEdge[]` · `onNodesChange` · `onEdgesChange` · `onConnect` · `readOnly?`.
- **A11y**: the canvas graph is the second-highest a11y risk after the chart engine — implements the same three-layer strategy as chart canvases: (1) DOM-mirror per node/edge (each node is *also* a real focusable DOM element positioned via the graph library's node-renderer, not a raw canvas draw — React Flow/Rete.js both render nodes as DOM by default, which is why they were preferred candidates per research; edges get an offscreen mirrored adjacency list), (2) roving-tabindex node-to-node navigation (`Tab` enters the graph, arrow keys move between connected nodes, `Enter` opens node inspector Drawer), (3) an always-available "Switch to form view" toggle that shows the *exact same rule* in CMP-145 as a full keyboard-operable, non-spatial alternative — this is the primary accessible-equivalent mechanism for the node-graph, mandated because free-form 2D graph manipulation cannot be made fully keyboard-equivalent to mouse drag-connect at parity speed.
- **Tokens**: `color.surface.canvas`, `color.edge.default/selected`.
- **API sketch**:
```ts
interface NodeGraphNode {
  id: string; type: "trigger"|"condition"|"action"|"logicGate"|"comment";
  position: { x: number; y: number };
  data: Record<string, unknown>;
}
interface NodeGraphEdge { id: string; source: string; target: string; }
interface NodeGraphCanvasProps {
  nodes: NodeGraphNode[]; edges: NodeGraphEdge[];
  onNodesChange: (n: NodeGraphNode[]) => void;
  onEdgesChange: (e: NodeGraphEdge[]) => void;
  onConnect: (source: string, target: string) => void;
  readOnly?: boolean;
}
```
- **Storybook**: EmptyCanvas, SimpleChain, BranchingLogic, ReadOnly, KeyboardNavDemo, FormViewToggleDemo.
- **Tests**: unit, visual, axe on DOM-mirror layer, keyboard node-nav interaction test (explicit CI gate — this is a named risk area per a11y standard §6), round-trip test (node-graph→IR→form-editor produces an identical rule), performance (large graph, 50+ nodes, pan/zoom fps).

### CMP-147 NodeGraphNode — TriggerNode
- **Tier**: Chart-primitive/rule-primitive · **Purpose**: node-graph node type representing a rule trigger.
- **Props**: `trigger` · `timeframe?` · `position` · `selected?`.
- **A11y**: DOM-rendered node (see CMP-146), `role="group"` `aria-label="Trigger node: on bar close, 5m"`.
- **Tokens**: `color.node.trigger`.
- **Storybook**: OnBarClose, OnFill, OnTimer.
- **Tests**: unit, visual, axe.

### CMP-148 NodeGraphNode — ConditionNode
- **Tier**: Chart-primitive/rule-primitive · **Purpose**: node type representing one condition (metric/operator/value), with input/output handles for logic-gate wiring.
- **Props**: `metric` · `operator` · `value` · `position` · `selected?`.
- **A11y**: input/output connection handles are separately focusable with `aria-label` "Connect output of condition node"; connecting via keyboard: focus handle → `Enter` → arrow-select target node → `Enter` confirms (documented keyboard-connect flow, the equivalent of drag-to-connect).
- **Tokens**: `color.node.condition`.
- **Storybook**: Default, Connected, KeyboardConnectDemo.
- **Tests**: unit, visual, axe, keyboard-connect interaction test.

### CMP-149 NodeGraphNode — ActionNode
- **Tier**: Chart-primitive/rule-primitive · **Purpose**: node type representing an action (place order, modify SL, flatten, etc.).
- **Props**: `actionType` · `params` · `position` · `selected?`.
- **Tokens**: `color.node.action`.
- **Storybook**: PlaceOrder, ModifySl, Flatten.
- **Tests**: unit, visual, axe.

### CMP-150 NodeGraphNode — LogicGateNode (AND/OR/NOT)
- **Tier**: Chart-primitive/rule-primitive · **Purpose**: explicit boolean combinator node, multiple inputs, one output — makes the AND/OR/advanced structure visually explicit (vs. the form editor's implicit grouping).
- **Props**: `gateType: "AND"|"OR"|"NOT"` · `inputCount` · `position` · `selected?`.
- **Tokens**: `color.node.logic`.
- **Storybook**: And, Or, Not.
- **Tests**: unit, visual, axe.

### CMP-151 NodeGraphNode — CommentNode
- **Tier**: Chart-primitive/rule-primitive · **Purpose**: free-text annotation node, non-executable, for author documentation within the graph.
- **Props**: `text` · `position` · `color?`.
- **Tokens**: `color.node.comment`.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-152 NodeGraphEdge
- **Tier**: Chart-primitive/rule-primitive · **Purpose**: connector between two nodes; visually a bezier/orthogonal line, accessibly an entry in the mirrored adjacency list (per CMP-146).
- **Props**: `source` · `target` · `selected?` · `label?`.
- **A11y**: selecting an edge (via node-then-Tab-to-edge) surfaces "Delete connection" as a keyboard-reachable action (`Delete` key with focus on edge, or via its context menu).
- **Tokens**: `color.edge.default/selected`.
- **Storybook**: Default, Selected, Labelled.
- **Tests**: unit, visual, axe, keyboard delete-edge test.

### CMP-153 NodeInspectorDrawer
- **Tier**: Organism (rule engine) · **Purpose**: side drawer showing/editing the full parameter set of the currently-focused/selected node (opened via `Enter` on a node per CMP-146's keyboard contract) — this is where dense parameter editing happens, keeping on-canvas node chrome minimal.
- **Props**: `node: NodeGraphNode` · `onChange` · `onClose`.
- **Tokens**: inherits CMP-046 Drawer.
- **Storybook**: TriggerNodeInspector, ConditionNodeInspector, ActionNodeInspector.
- **Tests**: unit, visual, axe, keyboard.

### CMP-154 RuleSimulatePanel
- **Tier**: Organism (rule engine) · **Purpose**: runs the current rule draft against recorder history and shows a backtest-style result (matches DeepCharts Pattern Builder auto-backtest UX, digest 04 §15).
- **Props**: `rule: RuleDraft` · `dateRange` · `onRun` · `results?: SimulationResult` · `loading?`.
- **A11y**: results table extends CMP-049 Table contract; empty/insufficient-history state uses CMP-026 EmptyState `variant="recording-not-started"`.
- **Tokens**: inherits CMP-049.
- **Storybook**: Idle, Running, ResultsPopulated, InsufficientHistory.
- **Tests**: unit, visual, axe.

### CMP-155 RuleListRow
- **Tier**: Molecule (rule engine) · **Purpose**: one row in the rules list screen — name, symbol/scope, arm-state, last-fired, enable toggle.
- **Props**: `rule: RuleSummary` · `onToggleEnabled` · `onEdit` · `onDuplicate` · `onDelete`.
- **A11y**: arm-state (disarmed/simulate-only/live-armed) shown via CMP-011 tag variant, never colour-only; enable Toggle (CMP-004) is `critical` styled when the rule is live-armed.
- **Tokens**: inherits CMP-049 row pattern.
- **Storybook**: Disarmed, SimulateOnly, LiveArmed, RecentlyFired.
- **Tests**: unit, visual, axe.

### CMP-156 RuleEvaluationTimeline
- **Tier**: Molecule (rule engine) · **Purpose**: per-rule chronological log of evaluation/trigger/action events (feeds journal auto-tagging traceability, digest 09 §11).
- **Props**: `events: RuleEvaluationEvent[]`.
- **Tokens**: `font.mono`, `color.status.*`.
- **Storybook**: Default, WithActionFired.
- **Tests**: unit, visual, axe.

### CMP-157 MetricPickerCombobox
- **Tier**: Molecule (rule engine) · **Purpose**: searchable picker for the metric vocabulary (`price`, `atr(n)`, `cvd_divergence`, `iceberg_present_at_level`, etc.) used inside CMP-140/148.
- **Props**: `value` · `onChange` · `category?: "price"|"position"|"orderflow"|"risk"|"detector"`.
- **A11y**: extends CMP-048 Combobox; metrics sourced from heuristic detectors are tagged `(estimated)` in the option list itself, not just after selection.
- **Tokens**: inherits CMP-048.
- **Storybook**: Default, FilteredByCategory, EstimatedMetricTagged.
- **Tests**: unit, visual, axe.

### CMP-158 SafetyInvariantNotice ("native SL always attached")
- **Tier**: Atom (rule engine, safety-critical) · **Purpose**: persistent, non-dismissible notice inside both rule editors reminding the author that emulated rule-engine stops never replace the mandatory native exchange-side SL (safety invariant, `24-owner-decisions.md` §3).
- **Props**: none (static content component).
- **A11y**: `role="note"`, always visible in both CMP-145 and CMP-146 layouts.
- **Tokens**: inherits CMP-028 Callout.
- **Storybook**: Default.
- **Tests**: visual, axe, presence test (fails if removed from either editor's composition).

### CMP-159 RuleConflictWarning
- **Tier**: Molecule (rule engine) · **Purpose**: flags two enabled rules with overlapping scope/contradictory actions (e.g. one tightens SL while another widens it) at save time.
- **Props**: `conflicts: {ruleAId,ruleBId,description}[]`.
- **Tokens**: inherits CMP-028 `tone="warning"`.
- **Storybook**: SingleConflict, MultipleConflicts.
- **Tests**: unit, visual, axe.

---

## 6. Watchlist / alerts / journal / replay / audit components (CMP-160..179)

### CMP-160 SymbolSearchInput
- **Tier**: Molecule (trading) · **Purpose**: fuzzy symbol search with instrument preview (tick/lot, category, funding) — entry point for chart/DOM/watchlist symbol changes.
- **Props**: `value` · `onSelect(symbol)` · `category?: "linear"` (locked to USDT perps for v1) · `recentSymbols?: string[]`.
- **A11y**: extends CMP-048 Combobox; recent symbols shown as a labelled group before search results.
- **Tokens**: inherits CMP-048.
- **API sketch**: `interface SymbolSearchInputProps { value: string; onSelect: (symbol: string) => void; recentSymbols?: string[]; }`
- **Storybook**: Default, WithRecents, NoResults, WithPreviewPopover(CMP-125).
- **Tests**: unit, visual, axe, keyboard.

### CMP-161 WatchlistRow
- **Tier**: Molecule (trading) · **Purpose**: one row in a watchlist — symbol, last price, %chg, volume, funding-Δ, OI-Δ, quick-add-to-chart action.
- **Props**: `row: WatchlistRowData` · `onOpenChart` · `onRemove` · `columns: string[]` (configurable via CMP-056 ColumnPicker).
- **A11y**: extends CMP-049 row contract; %chg/PnL-style values use CMP-020 NumericText.
- **Tokens**: `font.mono`, `color.text.buy/sell`.
- **E08-D04**: each per-value cell carries an optional CMP-239 FreshnessMarker (rendered as a CSS class change on the existing cell — no extra DOM node — per the freshness-marker contract) reflecting the data-confidence state for that field's feed. If the row's overall connection is `disconnected`, the row shows only that state (precedence rule, `docs/design/E08/E08-D01.md` §2) — per-cell markers are suppressed rather than stacked.
- **API sketch**:
```ts
interface WatchlistRowData {
  symbol: string; lastPrice: number; pctChange24h: number;
  volume24h: number; fundingRate: number; openInterestDelta: number;
}
```
- **Storybook**: Default, Gainer, Loser, CustomColumns, StaleCell, DisconnectedRow.
- **Tests**: unit, visual, axe, keyboard.

### CMP-162 WatchlistGroupTabs
- **Tier**: Molecule (trading) · **Purpose**: saved watchlist groups (e.g. "Majors", "My Setups") as tabs above the watchlist table.
- **Props**: `groups: {id,name}[]` · `activeId` · `onSwitch` · `onCreate` · `onRename` · `onDelete`.
- **Tokens**: inherits CMP-042 Tabs.
- **Storybook**: Default, CreateNew.
- **Tests**: unit, visual, axe.

### CMP-163 AlertRow
- **Tier**: Molecule (trading) · **Purpose**: one configured alert — condition summary, delivery channel, enabled toggle, snooze/mute, last-fired.
- **Props**: `alert: AlertSummary` · `onToggleEnabled` · `onSnooze` · `onEdit` · `onDelete`.
- **A11y**: reuses CMP-140 condition-summary rendering (read-only) for consistency with the rule editor's language.
- **Tokens**: inherits CMP-049 row pattern.
- **API sketch**:
```ts
interface AlertSummary {
  id: string; conditionSummary: string; symbol?: string;
  deliveryChannels: ("in-app"|"push"|"email")[];
  enabled: boolean; oneShot: boolean; lastFiredAt?: number;
}
```
- **Storybook**: Enabled, Disabled, Snoozed, RecentlyFired, OneShot.
- **Tests**: unit, visual, axe.

### CMP-164 AlertBuilderForm
- **Tier**: Organism (trading) · **Purpose**: alert condition builder — reuses CMP-140/141/143/144/157 from the rule engine (condition editor minus the execution-action step, per digest 23 §19).
- **Props**: `conditionGroup: RuleConditionGroupProps` · `deliveryChannels` · `oneShot` · `onSave`.
- **Tokens**: inherits CMP-141.
- **Storybook**: Default, MultiCondition, MultiChannel.
- **Tests**: unit, visual, axe.

### CMP-165 AlertFiredToastGroup
- **Tier**: Molecule (trading) · **Purpose**: specialised Toast (CMP-045) variant for fired alerts, batches rapid-fire duplicates into a single "3 alerts fired for BTCUSDT" summary to avoid flooding.
- **Props**: `alerts: FiredAlert[]` · `onOpenAll` · `onDismiss`.
- **Tokens**: inherits CMP-045.
- **Storybook**: Single, Batched.
- **Tests**: unit, visual, axe, batching-logic unit test.

### CMP-166 JournalEntryRow
- **Tier**: Molecule (trading) · **Purpose**: one closed-trade journal row — entry/exit, size, side, PnL, R-multiple, MAE/MFE, tags, replay-link.
- **Props**: `entry: JournalEntry` · `onOpenReplay` · `onEditTags`.
- **Tokens**: `font.mono`, `color.text.buy/sell`.
- **API sketch**:
```ts
interface JournalEntry {
  id: string; symbol: string; side: "long"|"short";
  entryTime: number; exitTime: number; entryPrice: number; exitPrice: number;
  qty: number; realizedPnl: number; rMultiple: number;
  mae: number; mfe: number; tags: string[]; ruleSourceId?: string;
}
```
- **Storybook**: Winner, Loser, WithRuleTag, WithManualTags.
- **Tests**: unit, visual, axe.

### CMP-167 JournalEquityCurveChart
- **Tier**: Chart-primitive (trading, lightweight) · **Purpose**: cumulative equity/PnL line for the analytics dashboard — a simpler chart than the main engine, may use the same series primitive (CMP-181) in a minimal pane.
- **Props**: `points: {time,equity}[]` · `drawdownOverlay?: boolean`.
- **A11y**: table-alternative always available (CMP-049 rendering of the same points) via a "View as table" toggle.
- **Tokens**: `color.action.primary`, `color.status.danger` (drawdown fill).
- **Storybook**: Default, WithDrawdown, TableViewToggle.
- **Tests**: unit, visual, axe.

### CMP-168 JournalStatsSummaryCard
- **Tier**: Molecule (trading) · **Purpose**: win rate / expectancy / R-distribution / avg hold time summary tile.
- **Props**: `stats: JournalStats`.
- **Tokens**: inherits CMP-050 Card + CMP-036 KeyValueRow.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-169 TagEditor (journal/rule auto-tags)
- **Tier**: Molecule · **Purpose**: add/remove free-text and rule-sourced tags on a journal entry.
- **Props**: `tags: string[]` · `suggestions?: string[]` · `onAdd` · `onRemove` · `readOnlyTags?: string[]` (rule-auto-tags, non-removable by hand — traceability integrity).
- **Tokens**: inherits CMP-011 Tag.
- **Storybook**: Default, WithReadOnlyRuleTags.
- **Tests**: unit, visual, axe, keyboard.

### CMP-170 ReplayScrubber
- **Tier**: Organism (trading, chart-adjacent) · **Purpose**: playback control for tick/bar replay — play/pause, speed 0.5x–100x, scrub bar, step-bar/step-tick, bookmark markers, jump-to-realtime.
- **Props**: `currentTime: number` · `range: {from,to}` · `speed: number` · `playing: boolean` · `bookmarks?: number[]` · `onPlayPause` · `onSpeedChange` · `onScrub(time)` · `onStepBar(dir)` · `onStepTick(dir)` · `onJumpToRealtime`.
- **A11y**: transport controls are standard labelled buttons; scrub bar is `role="slider"` with `aria-valuetext` showing the human-readable timestamp (not just a raw number); hotkeys per `14-screens-catalogue.md` SCR-097 (`Space`=play/pause, `←/→`=step bar, `Shift+←/→`=step tick, `R`=jump to real-time) documented in the component's Storybook keyboard table.
- **Tokens**: `color.action.primary`, `font.mono` (timestamp/speed readout).
- **API sketch**:
```ts
interface ReplayScrubberProps {
  currentTime: number; range: { from: number; to: number };
  speed: number; playing: boolean; bookmarks?: number[];
  onPlayPause: () => void;
  onSpeedChange: (speed: number) => void;
  onScrub: (time: number) => void;
  onStepBar: (dir: 1 | -1) => void;
  onStepTick: (dir: 1 | -1) => void;
  onJumpToRealtime: () => void;
}
```
- **Storybook**: Paused, Playing, HighSpeed, WithBookmarks, KeyboardControlDemo.
- **Tests**: unit, visual, axe, keyboard (full hotkey table), performance (scrub responsiveness under load).

### CMP-171 ReplaySpeedPicker
- **Tier**: Molecule (trading) · **Purpose**: speed-preset picker (0.5x/1x/2x/5x/10x/25x/50x/100x) feeding CMP-170.
- **Props**: `value` · `onChange` · `presets: number[]`.
- **Tokens**: inherits CMP-009.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-172 ReplayRangePicker
- **Tier**: Molecule (trading) · **Purpose**: symbol + date/time range picker to start a replay session, shows recorder-availability shading (only recorded ranges are selectable, per recorder-dependent-emptiness rule).
- **Props**: `symbol` · `availableRanges: {from,to}[]` · `onSelectRange`.
- **Tokens**: inherits CMP-047 DateRangePicker.
- **Storybook**: Default, PartialAvailability, NoRecordedHistory(EmptyState).
- **Tests**: unit, visual, axe.

### CMP-173 AuditRow
- **Tier**: Molecule (owner/admin) · **Purpose**: one append-only audit log entry — actor, role, action, target, before/after diff, timestamp, IP, session.
- **Props**: `entry: AuditEntry` · `onExpand` (shows before/after diff).
- **A11y**: extends CMP-049 row contract; before/after diff rendered via CMP-068 CopyableCodeBlock inside an expandable region.
- **Tokens**: `font.mono`.
- **API sketch**:
```ts
interface AuditEntry {
  id: string; actor: string; role: string; action: string; target: string;
  before?: Record<string, unknown>; after?: Record<string, unknown>;
  ts: number; ip: string; sessionId: string;
}
```
- **Storybook**: Default, ExpandedDiff, SystemActor.
- **Tests**: unit, visual, axe.

### CMP-174 AuditFilterBar
- **Tier**: Molecule (owner/admin) · **Purpose**: filter the audit log by actor/action/target/date-range.
- **Props**: `filters` · `onChange` · `actorOptions` · `actionOptions`.
- **Tokens**: inherits CMP-055 FilterBar.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-175 KeyPermissionBadge
- **Tier**: Atom (owner/admin, security-critical) · **Purpose**: shows the permission scope of an API key (trade/read/withdraw flags, IP-whitelist state) with withdrawal-off always visually confirmed.
- **Props**: `permissions: {trade:boolean; read:boolean; withdraw:boolean}` · `ipWhitelisted: boolean`.
- **A11y**: withdrawal-off state is rendered with an affirmative "Withdrawal: OFF ✓" text, not just the absence of a chip (absence-of-danger is not a safe visual pattern — must be explicit).
- **Tokens**: `color.status.success/danger`.
- **Storybook**: Default(SafeConfig), WithdrawEnabled(dangerVariant, shown only for legacy-audit display, never settable via UI), NoIpWhitelist(warning).
- **Tests**: unit, visual, axe, "withdraw-enabled visual alarm" regression test (must never render neutrally).

### CMP-176 AccountKeyRow (admin accounts & keys table row)
- **Tier**: Molecule (owner/admin) · **Purpose**: one row in the admin Accounts & Keys screen — account nickname, env, KeyPermissionBadge, rotate/revoke actions.
- **Props**: `account: AdminAccountRow` · `onRotateKey` · `onRevoke` · `onEditProfile`.
- **Tokens**: inherits CMP-106 ProfileBadge + CMP-175.
- **Storybook**: Default, RotatingKey, Revoked.
- **Tests**: unit, visual, axe.

### CMP-177 RecorderStatusRow
- **Tier**: Molecule (owner/admin) · **Purpose**: one row in the recorder admin screen — symbol, recording state, disk usage, retention/pin controls.
- **Props**: `symbol` · `recording: boolean` · `diskUsageBytes` · `retentionDays` · `pinned: boolean` · `onToggleRecording` · `onTogglePin` · `onChangeRetention`.
- **Tokens**: inherits CMP-023 ProgressBar (disk usage vs budget ~0.5-0.75GB/day/symbol).
- **Storybook**: Recording, Stopped, Pinned, NearDiskBudget.
- **Tests**: unit, visual, axe.

### CMP-178 SystemHealthTile
- **Tier**: Molecule (owner/admin) · **Purpose**: one metric tile on the admin Health screen — ingestion lag, WS state, DB status, engine FPS, each with threshold-based tone.
- **Props**: `label` · `value` · `unit` · `tone: "ok"|"warning"|"danger"` · `sparkline?: number[]`.
- **Tokens**: inherits CMP-050 Card + CMP-024 Sparkline.
- **Storybook**: Ok, Warning, Danger.
- **Tests**: unit, visual, axe.

### CMP-179 FeatureFlagRow (admin feature flags screen)
- **Tier**: Molecule (owner/admin) · **Purpose**: one flag row — key, description, environment scope, enabled toggle, rollout note.
- **Props**: `flag: FeatureFlagRowData` · `onToggle`.
- **Tokens**: inherits CMP-004 Toggle.
- **Storybook**: Default, EnvScoped.
- **Tests**: unit, visual, axe.

---

## 7. Chart-engine primitives (CMP-180..199)

These are the building blocks of the fully custom WebGL chart engine (`26-chart-engine-design.md` owns the internal architecture; this catalogue owns the public component-level API surface, props/variants/states/a11y contract, and Storybook/test requirements, matching the same bar as every other design-system entry per `05-accessibility-standard.md` §11.3). Chassis approach per `research/digests/10-frontend-tech.digest.md`: primitive-based composition (Series/Pane/Overlay primitives) analogous to TradingView Lightweight Charts v5's `ICustomSeriesPaneView` / `ISeriesPrimitive` / `IPanePrimitive` model, generalised into CandleViewer's own engine since the engine itself is fully custom (owner decision #1).

### CMP-180 ChartRoot
- **Tier**- Chart-primitive · **Purpose**: top-level engine mount — owns the WebGL context, device-pixel-ratio handling, resize observer, and the master render loop; hosts N Panes.
- **Props**: `panes: PaneConfig[]` · `timeScale: TimeScaleConfig` · `theme: ThemeTokens` · `onReady?(api: ChartApi)`.
- **A11y**: root canvas carries `role="img"` + a computed `aria-label` summarising the whole chart state ("BTCUSDT, 5 minute, last 65,432, up 1.2%"), kept in sync every render tick but throttled to avoid live-region flooding; owns the top-level DOM-mirror container that all descendant primitives render their surrogate nodes into (per `05-accessibility-standard.md` §6.1).
- **Tokens**: `color.chart.background`, `color.chart.grid`.
- **API sketch**:
```ts
interface ChartApi {
  addPane(config: PaneConfig): PaneHandle;
  removePane(id: string): void;
  setTimeRange(from: number, to: number): void;
  subscribeCrosshairMove(cb: (point: CrosshairPoint) => void): () => void;
  getDomMirrorRoot(): HTMLElement; // a11y contract anchor
}
interface ChartRootProps {
  panes: PaneConfig[];
  timeScale: TimeScaleConfig;
  theme: ThemeTokens;
  onReady?: (api: ChartApi) => void;
}
```
- **Storybook**: EmptyChart, SinglePane, MultiPane, ThemeSwitchDemo.
- **Tests**: unit (API contract), visual, axe (root aria-label + mirror-root presence), performance (mount ≤150ms, resize responsiveness), WebGL-context-loss recovery test.

### CMP-181 CandleSeries
- **Tier**: Chart-primitive · **Purpose**: OHLC candlestick/bar/line/equi-volume/delta-volume series (chart-type settings from digest 04 §"Price chart settings").
- **Props**: `data: OhlcBar[]` · `chartType: "candle"|"bar"|"line"|"equi-volume"|"delta-volume"` · `barMode: "time"|"range"|"volume"|"tick"|"renko"|"pointfigure"` · `upColor/downColor`.
- **A11y**: bar-level DOM mirror is windowed to the visible range (per §6.2) — focused bar surfaces OHLCV via the mirror node, arrow-keys move bar-to-bar, `Home/End` jump to range start/end.
- **Tokens**: `color.candle.up/down`, `font.mono` (axis labels).
- **API sketch**:
```ts
interface OhlcBar { time: number; open: number; high: number; low: number; close: number; volume: number; }
interface CandleSeriesProps {
  data: OhlcBar[];
  chartType: "candle"|"bar"|"line"|"equi-volume"|"delta-volume";
  barMode: "time"|"range"|"volume"|"tick"|"renko"|"pointfigure";
  upColor: string; downColor: string;
}
```
- **Storybook**: Candle, Bar, Line, EquiVolume, DeltaVolume, RenkoMode.
- **Tests**: unit, visual, axe (windowed mirror), performance (100k+ bars, ≥58fps budget), keyboard bar-nav interaction test.

### CMP-182 FootprintSeries
- **Tier**: Chart-primitive · **Purpose**: per-bar grid of FootprintCell (CMP-109) instances bound to the price axis — the highest-effort chassis piece per research (digest 10: "2-3 weeks — single largest line item").
- **Props**: `data: FootprintBarData[]` · `cellMode` · `displayMode` · `lodTextThresholdPx: number` (sourced from `LOD_PROFILE_M0.L1.downSwitchPx` = 8.5px — `docs/design/E06/E06-D01.md` §2/§8 — below this per-cell pixel height, hide text but keep cell + DOM-mirror value).
- **Tokens**: inherits CMP-109.
- **API sketch**:
```ts
interface FootprintBarData { time: number; cells: FootprintCellData[]; }
interface FootprintSeriesProps {
  data: FootprintBarData[];
  cellMode: "volume"|"bidask"|"delta"|"delta+total";
  displayMode: "profile"|"box";
  lodTextThresholdPx: number;
}
```
- **Storybook**: HighZoom(text visible), LowZoom(LOD text hidden), AllCellModes.
- **Tests**: unit, visual, axe (mirror), performance (dense grid — the flagged largest-risk perf target, explicit spike-derived budget from `24-owner-decisions.md` §2.1).

### CMP-183 VolumeProfilePane
- **Tier**: Chart-primitive · **Purpose**: dedicated side/overlay pane rendering N ProfileBar (CMP-110) instances for one period.
- **Props**: `data: ProfileBarData[]` · `periodType: "composite"|"multiples"|"visible"|"personalized"` · `valueAreaPct: number` (default 70) · `showVwap?: boolean`.
- **Tokens**: inherits CMP-110.
- **Storybook**: Composite, Visible, WithVwap, ValueAreaHighlight.
- **Tests**: unit, visual, axe, performance.

### CMP-184 MarketProfileTpoPane (TPO letters)
- **Tier**: Chart-primitive · **Purpose**: TPO (Market Profile) block/profile rendering — sequential-letter periods, Initial Balance shading, 24/7 UTC-day redefinition (digest 04 §11).
- **Props**: `data: TpoPeriodData[]` · `tpoBaseMinutes: number` (default 30) · `tpoType: "blocks"|"profile"` · `dayBoundaryUtcHour: number` (default 0).
- **A11y**: each TPO letter-block is DOM-mirrored with its period/price-range/letter for screen reader traversal.
- **Tokens**: `color.tpo.letter`, `color.tpo.initialbalance`.
- **Storybook**: Blocks, Profile, InitialBalanceShaded.
- **Tests**: unit, visual, axe, performance.

### CMP-185 CvdPane
- **Tier**: Chart-primitive · **Purpose**: cumulative/per-bar delta subchart (candlestick/histogram/line display modes, divergence auto-marking).
- **Props**: `data: CvdPoint[]` · `displayMode: "candlestick"|"histogram"|"line"` · `resetAnchor: "session"|"day"|"never"|"manual"` · `divergenceMarkers?: boolean`.
- **Tokens**: `color.text.buy/sell`.
- **Storybook**: Histogram, Line, Candlestick, WithDivergenceMarkers.
- **Tests**: unit, visual, axe, performance.

### CMP-186 OiFundingLiqPane
- **Tier**: Chart-primitive · **Purpose**: combined OI/funding/liquidation context pane (digest 23 §7) — OI absolute/Δ, funding stepped-line, liquidation bars/heatmap.
- **Props**: `oi: OiPoint[]` · `funding: FundingPoint[]` · `liquidations: LiquidationBucket[]` · `displayMode` config per sub-signal.
- **Tokens**: `color.status.*`.
- **Storybook**: OiOnly, FundingOnly, LiquidationBars, Combined.
- **Tests**: unit, visual, axe, performance.

### CMP-187 SpeedOfTapePane
- **Tier**: Chart-primitive · **Purpose**: strip-chart mode of CMP-131 SpeedOfTapeGauge as a chart pane (vs. the standalone gauge widget).
- **Props**: same as CMP-131 plus `windowSec`.
- **Tokens**: inherits CMP-131.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-188 PriceAxis
- **Tier**: Chart-primitive · **Purpose**: vertical price-scale axis, shared across panes bound to the same scale; supports linear/log.
- **Props**: `min/max` · `scaleType: "linear"|"log"` · `tickFormatter` · `onDragScale?`.
- **A11y**: axis tick labels are part of the DOM-mirror (a real, if visually-hidden-when-redundant, list of tick values), draggable-to-rescale has a keyboard equivalent (focus axis, arrow keys nudge scale).
- **Tokens**: `color.chart.axis`, `font.mono`.
- **Storybook**: Linear, Log, Dragging(keyboard demo).
- **Tests**: unit, visual, axe, keyboard rescale test.

### CMP-189 TimeAxis
- **Tier**: Chart-primitive · **Purpose**: horizontal time-scale axis, shared master clock across all panes in a chart (synced pan/zoom).
- **Props**: `range: {from,to}` · `tickFormatter` · `onPan/onZoom`.
- **A11y**: keyboard pan (`←/→`) and zoom (`+/-`, `Ctrl+scroll` equivalent via keyboard modifiers) documented in the global hotkey table.
- **Tokens**: `color.chart.axis`, `font.mono`.
- **Storybook**: Default, ZoomedIn, ZoomedOut.
- **Tests**: unit, visual, axe, keyboard pan/zoom test, sync-across-panes integration test.

### CMP-190 Crosshair
- **Tier**: Chart-primitive · **Purpose**: synced crosshair across all panes + linked charts in a multi-chart layout, with an OHLCV/value readout tooltip.
- **Props**: `position: {time,price}|null` · `syncGroupId?: string` (for cross-panel/cross-chart linking, digest 23 §11).
- **A11y**: crosshair position is exposed via the currently-focused bar/cell's DOM-mirror (keyboard-driven crosshair movement is the accessible path — mouse-hover crosshair is the pointer-only convenience layer, per the "no hover-only functionality" rule in `05-accessibility-standard.md` §3.1.6).
- **Tokens**: `color.chart.crosshair`.
- **Storybook**: Default, SyncedAcrossPanes, KeyboardDriven.
- **Tests**: unit, visual, axe, keyboard test, cross-pane sync integration test.

### CMP-191 DrawingToolOverlay (base: trendline/ray/hline/rectangle/fibonacci)
- **Tier**: Chart-primitive · **Purpose**: base drawing-tools primitive kit (per digest 10: "budget dedicated 1-2 week sprint for a small kit... as reusable primitives").
- **Props**: `tool: "trendline"|"ray"|"hline"|"rectangle"|"fibonacci"` · `points: {time,price}[]` · `onChange` · `selected?` · `color/lineWidth`.
- **A11y**: each drawing object is DOM-mirrored with a focusable handle per control point; keyboard-draw flow: activate tool via toolbar button (`Enter`) → first point placed at current crosshair position via `Enter` → move crosshair via arrows → second `Enter` commits (full keyboard-operable alternative to click-drag, satisfying the no-drag-only rule).
- **Tokens**: `color.drawing.default`, `color.drawing.selected`.
- **API sketch**:
```ts
interface DrawingObject {
  id: string; tool: "trendline"|"ray"|"hline"|"rectangle"|"fibonacci";
  points: Array<{ time: number; price: number }>;
  color: string; lineWidth: number;
}
interface DrawingToolOverlayProps {
  drawings: DrawingObject[];
  activeTool: DrawingObject["tool"] | null;
  onCreate: (d: Omit<DrawingObject, "id">) => void;
  onChange: (id: string, patch: Partial<DrawingObject>) => void;
  onDelete: (id: string) => void;
}
```
- **Storybook**: Trendline, Ray, HLine, Rectangle, Fibonacci, KeyboardDrawDemo.
- **Tests**: unit, visual, axe, keyboard-draw interaction test (explicit CI gate), performance (many drawings on one chart).

### CMP-192 OrderLineOverlay (chart-trading order/position lines)
- **Tier**: Chart-primitive (trading-critical) · **Purpose**: draggable horizontal line representing a working order or open position's entry/SL/TP, directly on the price axis — chart-click/drag trading surface.
- **Props**: `lines: OrderLineData[]` · `onDragReprice(lineId, newPrice)` · `onDelete(lineId)` · `tickSize: number` (snap).
- **A11y**: each line is DOM-mirrored and independently focusable (`Tab` cycles order lines on the visible chart), reposition via focus + arrow keys (steps by `tickSize`) as the keyboard equivalent of drag; delete via `Delete` key with a ConfirmDialog for lines representing live orders above a configurable notional threshold.
- **Tokens**: `color.order.line`, `color.position.entry/sl/tp`.
- **API sketch**:
```ts
interface OrderLineData {
  id: string; kind: "order"|"position-entry"|"sl"|"tp";
  price: number; side: "buy"|"sell"; label: string; draggable: boolean;
}
interface OrderLineOverlayProps {
  lines: OrderLineData[];
  tickSize: number;
  onDragReprice: (id: string, newPrice: number) => void;
  onDelete: (id: string) => void;
}
```
- **Storybook**: WorkingOrderLine, PositionEntryLine, SlTpLines, KeyboardRepriceDemo, DeleteConfirmFlow.
- **Tests**: unit, visual, axe, keyboard reprice/delete interaction test (explicit CI gate — trading-critical), performance (many lines, e.g. scaled-order ladder of 10+ lines).

### CMP-193 HeatmapOverlay (engine-level mount point for CMP-111)
- **Responsibility split (disambiguation vs. CMP-111 HeatmapCell)**: CMP-193 owns the **rendering/mount-point/performance contract** only — the canvas layer, pane position, axis sync, and texture-upload performance budget. It does not own the data model or accessibility behaviour; those (and their Storybook/test lists) belong exclusively to **CMP-111**. If a ticket concerns what a cell means or how it's exposed to a screen reader, it belongs on CMP-111; if it concerns how/where the layer is painted or its frame budget, it belongs on CMP-193.
- **Tier**: Chart-primitive · **Purpose**: mounts the WebGL texture-based DOM heatmap layer (CMP-111 HeatmapCell logical model) behind/under the CandleSeries canvas, synced to the shared price/time axes.
- **Props**: `frames: HeatmapFrame[]` · `depthTiers: number` · `colorConvention` · `decayDurationMs`.
- **Tokens**: inherits CMP-111/CMP-113.
- **Storybook**: LowDepth, HighDepth, LongDecayTrail.
- **Tests**: performance-focused (texture upload cost, target 10Hz cadence at realistic depth — cross-referenced to the mandatory engine spike in `24-owner-decisions.md` §2.1), visual (static-frame snapshot), axe (windowed reveal, per CMP-111).

### CMP-194 IndicatorOverlay (VWAP/EMA/ADX/generic study line)
- **Tier**: Chart-primitive · **Purpose**: generic overlay-series primitive for indicator studies (VWAP+envelopes, moving averages, ADX/Aroon for market-regime, etc.).
- **Props**: `series: {time,value}[]` · `style: {color,lineWidth,dashed?}` · `bands?: {sigma,color}[]` (VWAP envelope mode).
- **Tokens**: `color.indicator.palette[]`.
- **Storybook**: SingleLine, WithBands, Dashed.
- **Tests**: unit, visual, axe, performance.

### CMP-195 AnnotationMarker (generic on-chart flag: unfinished auction, bar POC, session imbalance)
- **Tier**: Chart-primitive · **Purpose**: generic sparse-event marker primitive underlying BigTradeBubble (CMP-112), LiquidationMarker (CMP-127), ImbalanceStackIndicator (CMP-132), and simple flags like Bar POC / Unfinished Auction.
- **Props**: `time` · `price` · `icon|shape` · `color` · `tooltip: ReactNode`.
- **A11y**: base DOM-mirror marker contract reused by all sparse-event primitives listed above.
- **Tokens**: `color.marker.*`.
- **Storybook**: IconMarker, ShapeMarker.
- **Tests**: unit, visual, axe.

### CMP-196 MultiChartLinker (crosshair/level sync engine hook, non-visual)
- **Tier**: Chart-primitive (utility) · **Purpose**: the shared-sync coordinator for multi-chart layouts — crosshair-sync, level-sync (drawing a level on one pane reflects on linked panes), independent-vs-linked scaling (digest 23 §11).
- **Props**: `groupId` · `linkedPanes: string[]` · `syncModes: {crosshair:boolean; levels:boolean; scale:boolean}`.
- **A11y**: n/a directly (non-visual), but is a dependency of CMP-190's sync a11y story — sync-state changes are announced once via a shared status region ("Panes linked: crosshair, levels").
- **Tokens**: n/a.
- **Storybook**: n/a (covered via CMP-190/multi-pane integration stories).
- **Tests**: integration test (sync propagation across 2-4 panes).

### CMP-197 ChartTooltip (crosshair/hover value readout)
- **Tier**: Chart-primitive · **Purpose**: the floating readout box following the crosshair — OHLCV, footprint cell detail, indicator values at the focused time/price.
- **Props**: `content: TooltipField[]` · `position: {x,y}` · `visible: boolean`.
- **A11y**: purely a pointer/visual convenience layer; the equivalent information is always simultaneously available via the DOM-mirror for the focused element per the engine-wide accessible-equivalent rule (this tooltip itself is `aria-hidden`, preventing duplicate announcement).
- **Tokens**: `elevation.3`, `color.surface.overlay`, `font.mono`.
- **Storybook**: OhlcvTooltip, FootprintCellTooltip, IndicatorTooltip.
- **Tests**: unit, visual, axe (hidden-from-AT verification), performance (update cost during rapid crosshair movement).

### CMP-198 ChartWatermark / PaneBackground
- **Tier**: Chart-primitive · **Purpose**: symbol/interval watermark text behind chart data, and pane background fill (also carries the mandatory Lightweight-Charts-derived-license notice location if any code is adapted, per digest 10 licensing note — engine is fully custom, so this is a placeholder slot only, not a live obligation).
- **Props**: `text` · `opacity`.
- **Tokens**: `color.chart.watermark`.
- **Storybook**: Default.
- **Tests**: unit, visual.

### CMP-199 ChartLegend (per-pane series/indicator legend with visibility toggles)
- **Tier**: Chart-primitive · **Purpose**: top-left per-pane legend listing active series/overlays/indicators with colour swatch, current value, and show/hide toggle.
- **Props**: `items: {label,color,value,visible,onToggleVisible,onRemove?}[]`.
- **Tokens**: inherits CMP-037 SwatchLegendItem.
- **Storybook**: Default, ManyIndicators, AllHidden.
- **Tests**: unit, visual, axe, keyboard toggle.

---

## 7A. Auth, shell-surface, chart-chrome & editor-chrome components (CMP-200..238)

This band was added during the cross-document traceability reconciliation (see `18-traceability-matrix.md` §6). `14-screens-catalogue.md` composed 39 components that had no entry in bands 1–7: authentication surfaces (SCR-001..006), shell furniture that is distinct from `CMP-070 AppShell` (status bar, right rail, panic buttons, toast host), chart *chrome* (toolbars, pickers, chips) as opposed to chart *primitives* (CMP-180..199, which are engine-level render objects with no DOM), and rule-editor chrome shared by the form and node editors. They are first-class entries here rather than being folded into existing IDs because each has its own a11y contract, Storybook story set and test requirements — the same reasoning §8 gives for not collapsing CMP-147..151.

### CMP-200 AuthCard
- **Tier**: Organism (auth) · **Purpose**: the centred, fixed-width card chassis shared by every pre-auth screen (SCR-001, 002, 004) — product mark, title, slot for the form, error region, footer slot.
- **Props**: `title: string` · `subtitle?: string` · `error?: {message, code?}` · `footer?: ReactNode` · `busy?: boolean`.
- **A11y**: renders `<main>` with `<h1>` = title; the error region is `role="alert"` and receives focus on appearance; the card is a single tab sequence with no focus traps.
- **Tokens**: `color.surface.raised`, `space.6`, `radius.lg`, `elevation.2`.
- **Storybook**: Default, WithError, Busy, WithFooter.
- **Tests**: unit, visual (dark/light), axe, interaction (error announcement).

### CMP-201 PasswordField
- **Tier**: Atom · **Purpose**: password input with a reveal toggle, caps-lock warning and `autocomplete` wiring.
- **Props**: `value` · `onChange` · `autoComplete: "current-password"|"new-password"` · `showReveal?: boolean = true` · `error?: string`.
- **A11y**: reveal is a real `<button aria-pressed>` labelled "Show password"/"Hide password"; caps-lock warning is a polite live region; never suppresses paste.
- **Tokens**: inherits CMP-007 TextInput.
- **Storybook**: Default, Revealed, CapsLockOn, WithError.
- **Tests**: unit, visual, axe, interaction (reveal toggle, paste allowed).

### CMP-202 PasswordStrengthMeter
- **Tier**: Atom · **Purpose**: live strength feedback for new passwords (SCR-004).
- **Props**: `score: 0|1|2|3|4` · `feedback?: string[]`.
- **A11y**: strength is text ("Weak"/"Fair"/"Strong") plus a bar — never colour or bar-length alone; announced politely, debounced to 500 ms so it does not spam a screen reader per keystroke.
- **Tokens**: `color.status.*`, `radius.sm`.
- **Storybook**: Weak, Fair, Strong, WithFeedback.
- **Tests**: unit, visual, axe.

### CMP-203 RequirementChecklist
- **Tier**: Atom · **Purpose**: live-validating list of policy requirements (length, character classes, not-reused) for SCR-004.
- **Props**: `items: {label: string; met: boolean}[]`.
- **A11y**: `<ul>` where each item pairs an icon with the words "met"/"not met" in its accessible name; the list as a whole is `aria-live="polite"`.
- **Tokens**: `color.status.success`, `color.text.muted`.
- **Storybook**: NoneMet, PartiallyMet, AllMet.
- **Tests**: unit, visual, axe.

### CMP-204 OtpInput
- **Tier**: Molecule · **Purpose**: six-digit TOTP entry for SCR-002 and SCR-003.
- **Props**: `length: number = 6` · `value` · `onChange` · `onComplete` · `error?: string` · `disabled?: boolean`.
- **A11y**: exposed as **one** labelled input to assistive tech ("Six-digit authentication code"), not six unlabelled boxes; supports paste of the whole code, arrow/backspace navigation between cells, and `inputmode="numeric"` + `autocomplete="one-time-code"`.
- **Tokens**: `font.mono`, `space.2`, `radius.md`.
- **Storybook**: Empty, PartiallyFilled, Complete, Error, Disabled.
- **Tests**: unit, visual, axe, interaction (paste, backspace, arrow keys).

### CMP-205 QrCode
- **Tier**: Atom · **Purpose**: renders the TOTP enrolment `otpauth://` URI as a scannable QR (SCR-003).
- **Props**: `value: string` · `size?: number = 200` · `errorCorrection?: "M"|"Q"`.
- **A11y**: the QR image is `role="img"` with an accessible name naming what it is; the **secret is always also offered as selectable text** via CMP-033 CopyButton so QR scanning is never the only path.
- **Tokens**: `color.surface.base` (quiet zone must stay pure for scanner contrast — the QR never inherits a themed tint).
- **Storybook**: Default, LargeSize.
- **Tests**: unit, visual, axe (alt-text presence).

### CMP-206 RecoveryCodeList
- **Tier**: Molecule · **Purpose**: one-time display of the 10 single-use recovery codes with copy/download/print and a mandatory acknowledgement (SCR-003).
- **Props**: `codes: string[]` · `onAcknowledge` · `acknowledged: boolean`.
- **A11y**: codes are an ordered list in monospace; "Copy all", "Download .txt" and "Print" are real buttons; the acknowledgement checkbox blocks the continue button and states *why* it is required.
- **Tokens**: `font.mono`, `color.surface.sunken`.
- **Storybook**: Default, Acknowledged.
- **Tests**: unit, visual, axe, interaction (continue gated on acknowledgement).

### CMP-207 BuildFooter
- **Tier**: Atom · **Purpose**: version/commit/environment line on pre-auth screens and SCR-119.
- **Props**: `version: string` · `commit: string` · `environment: "demo"|"live"` · `buildTime: string`.
- **A11y**: plain text in a `<footer>`; the commit hash is selectable and copyable for support bundles.
- **Tokens**: `font.size.xs`, `color.text.muted`.
- **Storybook**: Demo, Live.
- **Tests**: unit, visual.

### CMP-208 StatusBar
- **Tier**: Organism (chrome) · **Purpose**: the persistent bottom bar — WS latency, recorder state, armed-rule count, kill-switch quick access, clock-offset chip.
- **Props**: `latencyMs` · `recorder: {state, symbolCount}` · `activeRuleCount` · `clockOffsetMs` · `onKillSwitch`.
- **A11y**: a labelled `role="status"` landmark; values update politely and are throttled to ≤1 Hz so announcements stay usable; the kill-switch control is a real button, never an icon-only affordance without a name.
- **Tokens**: `color.surface.sunken`, `font.size.xs`, `space.2`.
- **Data contract**: latency and recorder state from the `system.health` WS topic; rule count from `GET /rules?state=armed`.
- **Storybook**: Healthy, HighLatency, RecorderStopped, RulesArmed.
- **Tests**: unit, visual, axe, performance (no re-render storm at 1 Hz updates).

### CMP-209 RightRail
- **Tier**: Organism (chrome) · **Purpose**: the right-hand drawer stack hosting the notification centre (SCR-014), detector methodology (SCR-058) and detail drawers.
- **Props**: `open: boolean` · `activePanel?: string` · `panels: {id,label,content}[]` · `onClose` · `width?: number`.
- **A11y**: `role="complementary"` with an accessible name; `Esc` closes and returns focus to the trigger; it is a non-modal drawer, so focus is **not** trapped and the rest of the app stays operable.
- **Tokens**: `color.surface.raised`, `elevation.1`, `motion.drawer`.
- **Storybook**: Closed, NotificationsOpen, DetailOpen.
- **Tests**: unit, visual, axe, interaction (Esc, focus return).

### CMP-210 HealthChips
- **Tier**: Molecule · **Purpose**: compact cluster of system-health chips (WS, ingestion lag, recorder, exchange rate-limit budget) in the top bar.
- **Props**: `chips: {id,label,state:"ok"|"warn"|"error",value?:string,tooltip:string}[]`.
- **A11y**: each chip's accessible name is "`label`: `state`, `value`" — state is always a word, never a colour alone; a chip with `warn`/`error` is focusable and opens the relevant admin screen.
- **Tokens**: `color.status.*`, `radius.pill`.
- **Storybook**: AllOk, Warning, Error, Mixed.
- **Tests**: unit, visual, axe.

### CMP-211 PanicButtons
- **Tier**: Organism (trading, risk-critical) · **Purpose**: the always-reachable Flatten-all / Cancel-all / Kill-switch cluster in the top bar and system tray.
- **Props**: `scope: "account"|"group"|"global"` · `onFlattenAll` · `onCancelAll` · `onKillSwitch` · `enabled: {flatten,cancel,kill}` · `confirmMode: "hold"|"typed"|"single"`.
- **A11y**: each is a named button with an explicit scope in its accessible name ("Flatten all positions — all accounts"); never icon-only; `hold` confirmation exposes progress via `aria-valuenow` and has a keyboard equivalent (hold `Enter`).
- **Tokens**: `color.status.danger`, `space.2`.
- **Data contract**: `POST /positions/close-all`, `POST /orders/cancel-all`, `POST /trading/kill-switch`; every invocation is audited via CMP-093 AuditActionTrigger.
- **Storybook**: AccountScope, GlobalScope, KillSwitchArmed, Disabled(viewer).
- **Tests**: unit, visual, axe, interaction (confirm modes, keyboard hold), RBAC-disabled rendering.

### CMP-212 ToastHost
- **Tier**: Organism (chrome) · **Purpose**: the single global mount point that positions, stacks, de-duplicates and expires CMP-045 Toasts.
- **Props**: `position: "top-right"|"bottom-right"` · `max: number = 4` · `defaultDurationMs` · `pauseOnHover: boolean`.
- **A11y**: one `aria-live="polite"` region for informational toasts and a **separate** `role="alert"` region for errors/rejections, so a critical order rejection is not queued behind chatter; toasts are dismissible by keyboard and never steal focus.
- **Tokens**: `space.4`, `elevation.3`, `motion.toast`.
- **Storybook**: Single, Stacked, Overflow, ErrorAndInfoMixed.
- **Tests**: unit, visual, axe (dual live-region separation), interaction (dismiss, pause-on-hover).

### CMP-213 FuzzyList
- **Tier**: Molecule · **Purpose**: the ranked, grouped result list inside CMP-059 CommandPalette and CMP-160 SymbolSearchInput, with matched-substring highlighting.
- **Props**: `items: {id,label,group?,icon?,hint?,matchRanges}[]` · `activeId` · `onActivate` · `emptyMessage`.
- **A11y**: implements the listbox half of the combobox pattern — `aria-activedescendant`, result count announced, group headers as `role="group"` with labels; matched substrings use `<mark>` plus weight, never colour alone.
- **Tokens**: `color.surface.raised`, `color.text.accent`.
- **Storybook**: Default, Grouped, NoResults, LongList(virtualised).
- **Tests**: unit, visual, axe, interaction (arrow navigation, Enter), performance (1 000 items).

### CMP-214 DockDropZone
- **Tier**: Organism (layout) · **Purpose**: the drop-target overlay shown while dragging a panel — edge/centre zones with a live preview of the resulting split.
- **Props**: `zones: {id,rect,kind:"split-left"|"split-right"|"split-top"|"split-bottom"|"tabify"}[]` · `activeZoneId?` · `onDrop`.
- **A11y**: drag-and-drop has a **mandatory keyboard equivalent** — "Move panel" from CMP-216 PanelMenu opens a directional chooser (left/right/top/bottom/tab-into) so no layout operation is pointer-only.
- **Tokens**: `color.accent.subtle`, `motion.fast`.
- **Storybook**: EdgeZones, CentreTabify, ActiveZone.
- **Tests**: unit, visual, axe, interaction (keyboard move path).

### CMP-215 FloatingWindowFrame
- **Tier**: Organism (Electron) · **Purpose**: the chrome of a popped-out panel window (SCR-027) — minimal title bar, mandatory environment badge, re-dock control.
- **Props**: `title` · `environment: "demo"|"live"` · `onRedock` · `onClose` · `alwaysOnTop?: boolean`.
- **A11y**: the window title includes the environment word so the OS window list and screen-reader window switcher both disclose Demo vs Live; re-dock and close are named buttons.
- **Tokens**: `color.surface.base`, `color.env.*`.
- **Storybook**: Demo, Live, AlwaysOnTop.
- **Tests**: unit, visual, axe; Electron E2E (pop-out, re-dock, badge presence in every window).

### CMP-216 PanelMenu
- **Tier**: Molecule · **Purpose**: the per-panel overflow menu (SCR-028) — settings, pop out, duplicate, move, sync group, close.
- **Props**: `items: MenuItem[]` · `panelId` · `onSelect` · `syncGroup?: string`.
- **A11y**: built on CMP-041 Menu; opens from a named "Panel options" button and from `Shift+F10`/context-menu key; destructive items are grouped last and confirm per `US-SET-003`.
- **Tokens**: inherits CMP-041.
- **Storybook**: Default, WithSyncGroup, ViewerRestricted.
- **Tests**: unit, visual, axe, interaction (keyboard open, roving focus).

### CMP-217 LayoutPresetMenu
- **Tier**: Molecule · **Purpose**: quick-apply menu of grid presets (1×1, 2×2, 1+3, 3×1, custom saved) for SCR-022.
- **Props**: `presets: {id,label,thumbnail,paneCount}[]` · `activeId?` · `onApply` · `onSaveCurrent`.
- **A11y**: each preset's accessible name describes the arrangement in words ("Two by two, four panes"), not only a thumbnail; applying a preset that would discard unsaved panes routes through SCR-029.
- **Tokens**: `radius.md`, `space.3`.
- **Storybook**: Default, ActivePreset, WithCustomSaved.
- **Tests**: unit, visual, axe.

### CMP-218 SyncMenu
- **Tier**: Molecule · **Purpose**: per-panel cross-pane sync configuration (symbol, interval, crosshair, drawings, price scale) for SCR-023.
- **Props**: `groups: {id,color,label}[]` · `activeGroupId?` · `axes: {symbol,interval,crosshair,drawings,scale}: boolean` · `onChange`.
- **A11y**: sync-group membership is conveyed by group **name and letter badge** as well as colour; each sync axis is an independently labelled switch.
- **Tokens**: `color.sync.*`, `radius.pill`.
- **Storybook**: Unsynced, GroupA, AllAxesOn, PartialAxes.
- **Tests**: unit, visual, axe.

### CMP-219 SymbolPicker
- **Tier**: Molecule (trading) · **Purpose**: the compact in-chrome symbol selector (top bar, chart header, SCR-041) — distinct from CMP-160 SymbolSearchInput, which is the full-page search field.
- **Props**: `value: string` · `onChange` · `recent: string[]` · `favourites: string[]` · `showRecordingState?: boolean`.
- **A11y**: combobox pattern; each option announces symbol, base/quote and recording state; the current value is readable without opening the popover.
- **Tokens**: `font.mono`, `radius.sm`.
- **Data contract**: options from the cached `GET /instruments` list; recording chip from `GET /recording/symbols`.
- **Storybook**: Default, WithRecents, NotRecorded, Delisted.
- **Tests**: unit, visual, axe, interaction (type-ahead, Esc restores previous value).

### CMP-220 IntervalPicker
- **Tier**: Molecule (trading) · **Purpose**: timeframe selector with the standard ladder plus order-flow bar modes (tick/volume/range/Renko/delta).
- **Props**: `value: Interval` · `onChange` · `favourites: Interval[]` · `allowBarModes: boolean`.
- **A11y**: a menu button whose accessible name includes the current interval ("Interval: 15 minutes"); bar modes are a separate labelled group with an explanatory note, since they change the meaning of the x-axis.
- **Tokens**: `font.mono`, `space.1`.
- **Storybook**: TimeIntervals, BarModes, Favourites.
- **Tests**: unit, visual, axe.

### CMP-221 ChartToolbar
- **Tier**: Organism (chart chrome) · **Purpose**: the chart panel's top strip — symbol, interval, chart type, indicators, drawings, templates, settings, chart-trading arm toggle.
- **Props**: `symbol` · `interval` · `chartType` · `armed: boolean` · `onAction(actionId)` · `density`.
- **A11y**: `role="toolbar"` with roving tabindex and `aria-orientation="horizontal"`; every control has a text name; overflows into CMP-041 Menu at narrow widths rather than truncating silently.
- **Tokens**: `color.surface.sunken`, `space.1`.
- **Storybook**: Comfortable, Compact, Armed, Overflowing, ViewerReadOnly.
- **Tests**: unit, visual, axe, interaction (roving focus, overflow behaviour).

### CMP-222 ChartTypeToggle
- **Tier**: Molecule (chart chrome) · **Purpose**: switch between candles, bars, line, area, Heikin-Ashi, hollow candles, baseline, and the footprint overlay toggle.
- **Props**: `value: ChartType` · `onChange` · `footprintOn: boolean` · `onToggleFootprint`.
- **A11y**: CMP-003 SegmentedControl semantics; each option names the chart type in text (icons alone are insufficient); footprint is a separate `aria-pressed` toggle because it composes with any base type.
- **Tokens**: inherits CMP-003.
- **Storybook**: Candles, HeikinAshi, FootprintOn.
- **Tests**: unit, visual, axe.

### CMP-223 DrawingToolbar
- **Tier**: Organism (chart chrome) · **Purpose**: the vertical tool rail (SCR-037) — cursor, lines, shapes, Fibonacci, anchored VWAP, text, position tool, plus lock/hide/delete-all object controls.
- **Props**: `activeTool: ToolId` · `onSelectTool` · `magnetMode: "off"|"weak"|"strong"` · `lockAll: boolean` · `hideAll: boolean`.
- **A11y**: `role="toolbar"` vertical with roving tabindex; each tool has a name and a documented single-key shortcut surfaced via CMP-022 Kbd; the active tool is `aria-pressed` and also announced on change, since the chart canvas cannot convey mode visually to a screen reader.
- **Tokens**: `color.surface.raised`, `space.1`.
- **Storybook**: Default, ToolActive, MagnetStrong, AllLocked.
- **Tests**: unit, visual, axe, interaction (keyboard tool selection, Esc cancels the active tool).

### CMP-224 IndicatorChips
- **Tier**: Molecule (chart chrome) · **Purpose**: the row of active-indicator chips under the chart title — each with current value, visibility toggle, settings and remove.
- **Props**: `indicators: {id,label,params,value?,visible,error?}[]` · `onToggleVisible` · `onOpenSettings` · `onRemove`.
- **A11y**: each chip is a group whose name states the indicator and its parameters ("EMA 21"); the toggle/settings/remove are three separately named buttons, not one ambiguous chip click; an errored indicator states the error in text.
- **Tokens**: `radius.pill`, `font.size.xs`.
- **Storybook**: None, Several, Hidden, Errored, Overflowing.
- **Tests**: unit, visual, axe, interaction.

### CMP-225 DeepStatsStrip
- **Tier**: Organism (order flow) · **Purpose**: the configurable per-bar statistics strip beneath the chart (SCR-033) — volume, bid/ask volume, delta, max delta, CVD, imbalance counts, with threshold colouring and optional sparkline.
- **Props**: `rows: {id,label,unit,value,thresholdState?,sparkline?:number[]}[]` · `alignedToBars: boolean` · `onConfigure`.
- **A11y**: rendered as a real `<table>` aligned to the bar grid (not canvas), so values are readable cell by cell; threshold state is a word plus an icon; has a documented "read current bar's stats" keyboard shortcut.
- **Tokens**: `font.mono`, `color.status.*`, `space.1`.
- **Data contract**: values from the `footprint.{symbol}.{interval}` WS topic and `GET /market/footprint` bootstrap; recomputed per closed bar and on each in-progress-bar tick, coalesced to 4 Hz.
- **Storybook**: Default, AllRows, ThresholdsBreached, WithSparklines, Empty(no recording).
- **Tests**: unit, visual, axe, performance (60 visible bars × 12 rows update budget).

### CMP-226 BarCountdown
- **Tier**: Atom (chart chrome) · **Purpose**: time remaining until the current bar closes.
- **Props**: `msRemaining: number` · `interval: Interval` · `warnBelowMs?: number`.
- **A11y**: text, never a bare progress ring; updates at 1 Hz with `aria-live="off"` by default (opt-in announcement only) so it does not flood a screen reader; the warn state adds a word, not just a colour.
- **Tokens**: `font.mono`, `color.text.muted`, `color.status.warn`.
- **Storybook**: Normal, Warning, Closed.
- **Tests**: unit, visual, axe.

### CMP-227 EstimatedBadge
- **Tier**: Atom (honesty affordance, cross-cutting) · **Purpose**: the mandatory `(estimated)` chip on every heuristic-derived view, opening CMP-069 InfoPanel / SCR-058 with the methodology.
- **Props**: `detector: DetectorId` · `confidence?: "low"|"medium"|"high"` · `onOpenMethodology`.
- **A11y**: the literal word "estimated" is in the accessible name — this badge may **never** be conveyed by colour, icon or opacity alone; it is focusable and opens the methodology drawer by `Enter`.
- **E08-D04 — composition with CMP-239 FreshnessMarker (confirmed contract)**: `estimated` and data-confidence `stale`/`gapped` are different claims — one says "derived, not raw" (never changes once computed), the other says "not current" (temporal). They are never merged into one chip. When a value is both, CMP-227 renders first (leftmost) and CMP-239 renders immediately after it; each keeps its own accessible name so a screen reader announces both ("Estimated, low confidence. Stale, 4 seconds."). Visual separation: distinct shapes (pill vs dot+text) plus a minimum 4px gap — never touching or overlapping.
- **Tokens**: `color.status.info`, `radius.pill`, `font.size.xs`.
- **Storybook**: Default, LowConfidence, HighConfidence, WithStaleFreshnessMarker.
- **Tests**: unit, visual, axe; plus a **catalogue-level test** asserting that every screen listed in `14-screens-catalogue.md` §12.3 under "(estimated) labelling" renders this component, and a composition test asserting CMP-227 + CMP-239 never collapse into a single accessible name.

### CMP-228 PreviewTile
- **Tier**: Molecule · **Purpose**: the live miniature preview inside settings dialogs (footprint, heatmap, theme, density) showing the effect of the current settings on sample data.
- **Props**: `kind: "footprint"|"heatmap"|"candles"|"theme"` · `settings: object` · `sampleData?: unknown`.
- **A11y**: `role="img"` with a name describing the current configuration in words; it is decorative-adjacent, so the settings themselves always remain independently readable — the preview is never the only disclosure of a setting's effect.
- **Tokens**: `radius.md`, `color.surface.sunken`.
- **Storybook**: Footprint, Heatmap, ThemeDark, ThemeLight.
- **Tests**: unit, visual, axe.

### CMP-229 ArmToggle
- **Tier**: Molecule (trading, safety-critical) · **Purpose**: the arm/lock control (US-ORD-005) gating click-to-trade on the chart and DOM.
- **Props**: `armed: boolean` · `onChange` · `scope: "chart"|"dom"|"global"` · `autoDisarmMs?: number` · `environment: "demo"|"live"`.
- **A11y**: `aria-pressed` switch whose name states the scope and state ("Chart trading: locked"); arming in Live requires a deliberate second action and announces the change assertively; auto-disarm announces when it fires.
- **Tokens**: `color.status.danger`, `color.status.success`, `radius.pill`.
- **Storybook**: Locked, ArmedDemo, ArmedLive, AutoDisarmPending.
- **Tests**: unit, visual, axe, interaction (no accidental single-key arm in Live), E2E (no order can be placed while locked).

### CMP-230 OwnOrderMarker
- **Tier**: Molecule (trading) · **Purpose**: the marker showing the user's own working orders and position on the DOM ladder rows and heatmap (US-DOM-006).
- **Props**: `side: "buy"|"sell"` · `qty: number` · `orderType` · `accountLabel?: string` · `isGroupAggregate?: boolean` · `onCancel` · `onDrag`.
- **A11y**: within the ladder's DOM-mirror table the marker is text in a dedicated "Your orders" column ("Buy 0.5 limit, account Sub-2"), so it never depends on a canvas-drawn glyph; cancel is reachable by keyboard from that cell.
- **Tokens**: `color.buy`, `color.sell`, `font.mono`.
- **Data contract**: from `orders.{accountId}` / `positions.{accountId}` WS topics, filtered to the ladder's visible price window; drag-to-modify issues an order-amend REST call.
- **Storybook**: SingleOrder, MultipleAtPrice, GroupAggregate, PositionMarker.
- **Tests**: unit, visual, axe (DOM-mirror parity), interaction (keyboard cancel).

### CMP-231 TifSelect
- **Tier**: Atom (trading) · **Purpose**: time-in-force selector (GTC, IOC, FOK, PostOnly) with per-order-type availability.
- **Props**: `value: Tif` · `onChange` · `available: Tif[]` · `orderType`.
- **A11y**: unavailable options are disabled **with a stated reason** ("PostOnly is unavailable for market orders"), never silently absent; the expansion of each acronym is in the option's accessible description.
- **Tokens**: inherits CMP-009 Select.
- **Storybook**: Limit, Market, PostOnlyUnavailable.
- **Tests**: unit, visual, axe.

### CMP-232 LimitsChip
- **Tier**: Molecule (trading) · **Purpose**: compact display of the binding constraints on the current ticket — profile risk cap, remaining daily loss budget, max leverage, allowed-symbol status, exchange min/max qty.
- **Props**: `limits: {id,label,value,used?,max?,binding:boolean,source:"profile"|"exchange"|"global"}[]`.
- **A11y**: the **binding** limit is named in text and announced when it changes ("Blocked by daily loss cap: 480 of 500 USDT used"); each limit states which authority sets it, so the user knows whether the owner or the exchange is the constraint.
- **Tokens**: `color.status.warn`, `font.mono`, `radius.pill`.
- **Data contract**: from the per-account profile (`GET /exchange-accounts/{id}/profiles`), global risk policy, and instrument filters (`GET /instruments/{symbol}`).
- **Storybook**: NoneBinding, RiskCapBinding, DailyLossBinding, SymbolNotAllowed.
- **Tests**: unit, visual, axe.

### CMP-233 RuleOptions
- **Tier**: Molecule (rule engine) · **Purpose**: the non-condition settings block of a rule — name, enabled, priority, cooldown, max fires per day, simulate-vs-armed mode, conflict precedence.
- **Props**: `options: RuleOptions` · `onChange` · `mode: "simulate"|"armed"` · `conflictsWith?: RuleRef[]`.
- **A11y**: a labelled `<fieldset>` per group; switching to `armed` is a deliberate control that surfaces SCR-085 rather than toggling silently; declared conflicts are listed in text with links.
- **Tokens**: `space.4`, `color.surface.sunken`.
- **Storybook**: SimulateMode, ArmedMode, WithConflicts.
- **Tests**: unit, visual, axe.

### CMP-234 ValidationPanel
- **Tier**: Organism (rule engine) · **Purpose**: the shared validation surface for **both** rule editors (form mode SCR-081 and graph mode SCR-082) — errors, warnings and IR-compilation diagnostics, each anchored to the offending condition row or node.
- **Props**: `diagnostics: {id,severity:"error"|"warning"|"info",message,anchor:{kind:"row"|"node"|"edge",id},fixHint?}[]` · `onFocusAnchor`.
- **A11y**: a `role="log"` list ordered errors-first; each entry is a button that moves focus to the offending row/node (the sole mechanism by which a keyboard user navigates graph diagnostics); the error count is announced on every recompile.
- **Tokens**: `color.status.danger`, `color.status.warn`, `space.3`.
- **Data contract**: diagnostics come from `POST /rules/validate` against the shared rule IR, so form and graph modes report **identical** diagnostics for the same rule (the round-trip invariant, OD#11).
- **Storybook**: Valid, WithErrors, WithWarnings, GraphAnchored, FormAnchored.
- **Tests**: unit, visual, axe, interaction (focus-to-anchor in both modes), contract test (same IR ⇒ same diagnostics in both editors).

### CMP-235 EditorModeToggle
- **Tier**: Molecule (rule engine, safety-relevant) · **Purpose**: switch a rule between form and node-graph editing, carrying the shared IR across without loss (OD#11).
- **Props**: `mode: "form"|"graph"` · `onChange` · `lossyWarning?: {constructs: string[]}` · `dirty: boolean`.
- **A11y**: CMP-003 SegmentedControl semantics; if the current rule contains constructs the target editor cannot represent, switching is **blocked with a named explanation** listing those constructs rather than degrading the rule silently.
- **Tokens**: inherits CMP-003.
- **Storybook**: FormActive, GraphActive, LossyWarning, DirtyUnsaved.
- **Tests**: unit, visual, axe, interaction; round-trip test (form → graph → form yields an identical IR).

### CMP-236 NodePalette
- **Tier**: Organism (rule engine) · **Purpose**: the categorised, searchable palette of node types (triggers, metrics, comparators, logic gates, actions, comments) that can be dropped onto CMP-146 NodeGraphCanvas.
- **Props**: `categories: {id,label,nodes:{type,label,description,icon}[]}[]` · `query` · `onQueryChange` · `onAddNode(type, position?)`.
- **A11y**: adding a node must be possible **without dragging** — selecting a palette entry and pressing `Enter` inserts it connected to the current selection; every node type has a plain-language description, not just an icon.
- **Tokens**: `color.surface.raised`, `space.2`.
- **Storybook**: Default, Searching, NoResults, CategoryCollapsed.
- **Tests**: unit, visual, axe, interaction (keyboard-only node insertion).

### CMP-237 NodePort
- **Tier**: Molecule (rule engine) · **Purpose**: the typed input/output connection point on a node, enforcing type compatibility (boolean, number, price, side, action) at connect time.
- **Props**: `kind: "in"|"out"` · `dataType: PortType` · `connected: boolean` · `label: string` · `compatible?: boolean`.
- **A11y**: each port is individually focusable with a name stating direction, type and connection state ("Input, boolean, not connected"); connecting by keyboard is focus-port → `Enter` → focus-target-port → `Enter`, and incompatible targets are announced as such rather than merely being un-droppable.
- **Tokens**: `color.port.*`, `radius.full`.
- **Storybook**: InputUnconnected, OutputConnected, IncompatibleTarget.
- **Tests**: unit, visual, axe, interaction (keyboard connect, type rejection with a spoken reason).

### CMP-238 Minimap
- **Tier**: Molecule (rule engine) · **Purpose**: the overview/navigation minimap for large rule graphs on CMP-146.
- **Props**: `bounds` · `viewport` · `nodes: {id,rect,severity?}[]` · `onNavigate`.
- **A11y**: `aria-hidden` — it is a pointer convenience only; the equivalent keyboard navigation is the node list in CMP-153 NodeInspectorDrawer and the diagnostics anchors in CMP-234, both of which are complete alternatives.
- **Tokens**: `color.surface.sunken`, `color.accent.subtle`.
- **Storybook**: SmallGraph, LargeGraph, WithErrorNodes.
- **Tests**: unit, visual, performance (200-node graph).

### CMP-239 FreshnessMarker (E08-D04, data-confidence vocabulary)
- **Tier**: Atom (cross-cutting, safety) · **Purpose**: the per-value marker communicating a data-confidence state (`live|stale|reconnecting|disconnected|resyncing|gapped|backfilling|delisted`, precedence order in `docs/design/E08/E08-D01.md` §2) for a single cell/field, used by CMP-161 WatchlistRow, CMP-036 KeyValueRow live fields, and tape/DOM cells.
- **Props**: `state: DataConfidenceState` · `lastUpdatedAgeMs?: number` (renders as "Stale 4s" text for `stale`) · `label?: string` (override for compound rows).
- **Contract**: exactly one state is shown at a time (never stacked — a row in `disconnected` never additionally shows a `stale` marker on individual cells). State changes are a single flip on enter/exit, no pulsing/flashing, respects `prefers-reduced-motion`. `live` renders no visible chip (baseline — absence of a marker IS the live state, so it costs nothing at 4 Hz+ update rates).
- **Renderable as a pure CSS class change** — no extra DOM node per cell on hot surfaces (watchlist, tape, DOM ladder); the accessible name/text content already exists in the cell and the marker only swaps a class plus (for `stale`) appends the age text node, so the row does not gain a wrapper element per update.
- **A11y**: never colour-only — text label (mandatory for every non-`live` state) pairs with the reinforcing colour; `disconnected`/`reconnecting` states bubble to the parent CMP-028 banner (`role="alert"`/`role="status"`) rather than re-announcing per cell; a degraded state entering/exiting a *panel* (not per-row) announces once via the parent's live region, collapsing flapping within 5s into one announcement — individual FreshnessMarker instances do not each own a live region.
- **Tokens**: `color.data-confidence.{state}.text`, `color.data-confidence.{state}.indicator`, `color.data-confidence.{state}.surface` (only `stale` defines a surface tint; see `packages/ui/tokens/semantic-*.tokens.json`).
- **Composition rule with CMP-227 EstimatedBadge**: see CMP-227 entry — they are always rendered as two separate, non-overlapping elements, never merged.
- **Escalation process for an undefined state**: a later epic needing a data-confidence state not in the eight above raises a design-system change request against this entry (comment on the `16-design-system-brief.md` token PR or open a new `E08-D*`-scoped ticket) — it must **not** add a local one-off variant on a consuming screen. The precedence table in `docs/design/E08/E08-D01.md` §2 is the single source for state ordering and must be updated in the same change.
- **Storybook**: Live, Stale, Reconnecting, Disconnected, Resyncing, Gapped, Backfilling, Delisted, WithEstimatedBadgeComposition.
- **Tests**: unit (precedence/never-stacked assertion, CSS-class-only render), visual (both themes), axe (redundant non-colour channel present for every non-live state), live-region collapse test (flapping within 5s → one announcement).

---

## 8. Summary tallies

| Band | Count |
|---|---|
| Atoms (CMP-001..039) | 39 |
| Molecules (CMP-040..069) | 30 |
| Organisms — chrome & nav (CMP-070..099) | 30 |
| Trading-specific (CMP-100..139) | 40 |
| Rule engine & node-graph (CMP-140..159) | 20 |
| Watchlist/alerts/journal/replay/audit (CMP-160..179) | 20 |
| Chart-engine primitives (CMP-180..199) | 20 |
| Auth / shell-surface / chart-chrome / editor-chrome (CMP-200..239) | 40 |
| **Total catalogued components** | **239 — see E08-D04 addendum below** |

**Addendum (E08-D04, 2026-09-27):** CMP-239 FreshnessMarker was added as the design-system contribution for the
data-confidence vocabulary (`docs/design/E08/E08-D01.md`) — a genuinely new cross-cutting atom (per-value
freshness marker for WatchlistRow/KeyValueRow/tape/DOM cells) with no existing entry to extend, per the ticket's
scope. This is the only count change since the lock below; future changes still require the same rationale.

**Decision — final count was locked at 238, not 120–180 (supersedes the brief's range for this deliverable).** The count was 199 until the cross-document traceability reconciliation (`18-traceability-matrix.md`), which found 39 components composed by `14-screens-catalogue.md` that had no catalogue entry; rather than silently dropping those references or overloading existing IDs, band 7A was opened at CMP-200..238. 238 is the number backlog tickets are generated from. Rationale for not consolidating: the trading-specific, chart-engine and band-7A entries intentionally enumerate each node-graph node type, each chart primitive, each piece of chart/editor chrome and each heuristic-detector chip as its own first-class CMP-* entry (per `05-accessibility-standard.md` §11.3's requirement that trading-specific components get the same first-class a11y/test treatment as generic atoms — collapsing them would under-specify their individual contracts, e.g. CMP-147..151's distinct keyboard-connect and a11y-label behaviours per node type, or CMP-227 EstimatedBadge's catalogue-level enforcement test).

An alternative was considered and explicitly **rejected**: merging CMP-147..151 (node-graph node types) into a single parameterised `NodeGraphNode` component with a `type` discriminator, which would reduce the nominal count to ~180. This is rejected because (a) it would require the a11y and Storybook contracts for five materially different keyboard/interaction behaviours to live inside one entry's Variants table, degrading ticket-writer clarity rather than improving it, and (b) it does not change the actual implementation surface — five distinct React components would still exist either way. **Ticket generation must produce exactly 238 tickets, one per CMP-* ID in this document.**

---

## 9. Cross-references
- `14-screens-catalogue.md` — every screen entry names the CMP-* components it composes.
- `16-design-system-brief.md` — token names referenced throughout (`color.*`, `font.*`, `space.*`, `radius.*`, `elevation.*`, `motion.*`), density modes, Figma library structure, handoff spec.
- `05-accessibility-standard.md` §6, §11 — binding a11y contracts for canvas/WebGL components and the design-system enforcement mechanism this catalogue implements.
- `26-chart-engine-design.md` — internal architecture (render loop, texture pipeline, DOM-mirror sync API) behind the CMP-180..199 public component surface.
- `research/digests/10-frontend-tech.digest.md`, `04-deepcharts-deepchart.digest.md`, `05-deepcharts-deepdom-gamma.digest.md`, `09-execution-risk-tools.digest.md`, `23-views-and-screens.digest.md` — source feature inventories this catalogue operationalises into components.
- `backlog/*.json` — one design-system ticket per component or tight family, referencing its CMP-* ID, Storybook story list, and test requirements as Definition-of-Done.

