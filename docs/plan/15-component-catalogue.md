# 15 — Component Catalogue (CandleViewer Design System)

Date: 2026-09-14 · Owner: basiltt · Status: **Baseline for design & engineering — single source of truth for design-system + trading + chart-engine components**

Scope (locked, see `00-planning-brief.md` + `research/24-owner-decisions.md`): web app only — React + TypeScript, custom WebGL chart engine, Electron desktop shell primary. RBAC-gated owner/admin screens live inside this app. No Android. No separate admin app. Bybit v5 USDT linear perpetuals only.

Upstream: `14-screens-catalogue.md` (screens reference components by CMP-* name), `10-personas.md`, `05-accessibility-standard.md` (component-level a11y contract, §11), `research/digests/10-frontend-tech.digest.md` (chassis: TradingView Lightweight Charts v5 primitives + dedicated WebGL/PixiJS heatmap layer), `research/digests/04-deepcharts-deepchart.digest.md` + `05-deepcharts-deepdom-gamma.digest.md` (order-flow feature surface), `research/digests/09-execution-risk-tools.digest.md` (execution/risk UX).
Downstream: `16-design-system-brief.md` (tokens, theming, Figma, handoff), `26-chart-engine-design.md` (engine internals), `backlog/*.json` (design-system tickets, one per component or tight family).

Target: the brief's stated planning target was **120–180 components**; this catalogue **locks a final count of 238** (IDs `CMP-001..238`), superseding the range for this deliverable — see §8 for the rationale and the explicit decision (no further consolidation is planned or required; 238 is the number backlog tickets are generated from). IDs are `CMP-nnn`, stable and permanent, non-contiguous numbering (gaps reserved per band).

---

## 0. How to read this catalogue

### 0.1 Entry template

Every component entry states: **ID** `CMP-nnn` · **Name** · **Tier** (Atom / Molecule / Organism / Chart-primitive) · **Purpose** · **Props** (name: type — default — notes) · **Variants** · **States** · **A11y** (role, keyboard, ARIA, focus contract) · **Tokens used** (references `16-design-system-brief.md` token names) · **Storybook stories** · **Test requirements** (unit, visual regression, axe, interaction). Trading-specific and chart-primitive components additionally state **API sketch** (TS interface) and **Data contract** (props/events tied to WS/REST shapes from `14-screens-catalogue.md` §0.4). Any entry may also state the optional fields **Forbidden** (states a consumer may not produce, each with its source), **Security**, **Performance** and **Observability**; entries without them are not back-filled.

### 0.2 ID bands

| Band         | Tier / Area                                                                                                                                                                                                                                                       |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-001..039 | Atoms (buttons, inputs, typography, icons, badges, indicators)                                                                                                                                                                                                    |
| CMP-040..069 | Molecules (form fields, menus, tooltips, toasts, tabs, cards)                                                                                                                                                                                                     |
| CMP-070..099 | Organisms — chrome & navigation (app shell, panels, dialogs, tables)                                                                                                                                                                                              |
| CMP-100..139 | Trading-specific molecules/organisms (order ticket, DOM row, footprint cell, positions grid, etc.)                                                                                                                                                                |
| CMP-140..159 | Rule engine & node-graph components                                                                                                                                                                                                                               |
| CMP-160..179 | Watchlist / alerts / journal / audit row components                                                                                                                                                                                                               |
| CMP-180..199 | Chart-engine primitives (series, panes, axes, overlays, drawings)                                                                                                                                                                                                 |
| CMP-200..248 | Auth surfaces, shell furniture, chart chrome, rule-editor chrome (added in the traceability reconciliation, §7A); 240 and 243 added by E36-D05 (#947) from E13-D02 G-1 / G-4 (A-2); 248 added by E12-D09 (#244) from E12-D02 NC-2; 241–242 and 244–247 unassigned |

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
- **Props**: `variant: "primary"|"secondary"|"ghost"|"danger"|"buy"|"sell"` (default `secondary`) · `size: "sm"|"md"|"lg"` (default `md`) · `iconLeft?/iconRight?: IconName` · `loading?: boolean` · `disabled?: boolean` · `disabledReason?: string` (the visible reason per `14-screens-catalogue.md` §0.5.5, rendered inline or echoed by a focus+hover CMP-016 tooltip; `docs/design/E09/E09-D09.md` §2.2) · `fullWidth?: boolean` · `onClick`.
- **Variants**: primary, secondary, ghost, danger (destructive, requires confirm wrapper), buy (green, used only in trading contexts; the label always contains the word "Buy" and `iconLeft` defaults to `arrow-up`), sell (red; the label always contains the word "Sell" and `iconLeft` defaults to `arrow-down`); buy and sell cannot clear their arrow (`05-accessibility-standard.md` §4.1).
- **States**: default, hover, focus-visible, active (pointer or key held; Penpot `State=active`), disabled, disabled-with-reason (CMP-079: only the fill dims; the label stays at full opacity in `color.text.primary`; a trailing `locked` glyph in `color.text.secondary`; reason tooltip; superseded by E09-D09 §2.2 T2 (the E05-D02 boards PR restates it)), loading (spinner replaces label, width locked to prevent reflow; buy/sell keep the label and the arrow visible with the spinner after the label, so the side is never colour-only; activation suppressed while busy; no time cap: after 5 s the host shows slow-path text, "Checking with the exchange…" on an order submit, which stays busy with no Cancel until the exchange resolves the order, while only a load, an export or a replay adds a Cancel action).
- **A11y**: role `button` (native `<button>`), `aria-disabled` + `aria-describedby` pointing at the always-rendered reason text when disabled-with-reason (never the `disabled` attribute for an RBAC deny, so the control stays focusable and the reason reachable; a CMP-016 tooltip may echo it on hover and focus but is never the only copy), `aria-busy` when loading. Keyboard: `Enter`/`Space` activates; focus ring 2px offset.
- **Tokens**: `color.action.primary.default`, `color.action.primary.hover`, `color.action.primary.active`, `color.action.secondary.default`, `color.action.secondary.hover`, `color.surface.hover`, `color.surface.selected`, `color.status.danger.default`, `color.buy.default`, `color.buy.hover`, `color.sell.default`, `color.sell.hover`, `color.text.primary`, `color.text.secondary`, `color.text.on-action`, `color.text.inverse`, `color.focus.ring`, `radius.control`, `size.control.height`, `size.icon`, `space.button.paddingX`, `space.inset.xs`, `space.inset.sm`, `space.inset.lg`, `type.ui.label`, `type.ui.body-strong`, `type.ui.heading-sm`, `elevation.chrome`, `opacity.disabled` (disabled states), `border.focus` (focus-ring width).
- **Storybook**: Default, AllVariants, AllSizes, Loading, DisabledWithReason, BuySellPair (icon-only actions use CMP-002 IconButton; a Button always shows its label).
- **Tests**: unit (variant/state matrix), visual regression (all variants × dark/light), axe, keyboard activation, RBAC-disabled-reason interaction test (reason text in the DOM at mount and referenced by `aria-describedby`; control stays focusable; activation does nothing; a tooltip echo, if present, is not the only copy).

### CMP-002 IconButton

- **Tier**: Atom · **Purpose**: icon-only affordance (toolbar actions, panel close, row actions).
- **Props**: `icon: IconName` · `label: string` (mandatory, becomes `aria-label`) · `variant: "primary"|"secondary"|"ghost"|"danger"` (default `secondary`; danger requires the CMP-044 confirm wrapper, as CMP-001; no buy/sell, since an icon-only control cannot carry the Buy/Sell word) · `size: "sm"|"md"|"lg"` (default `md`; scales the nested CMP-019 Icon, the box stays `size.control.height` square) · `pressed?: boolean` (toggle mode, secondary and ghost only) · `disabled?/disabledReason?`.
- **States**: default, hover, focus-visible, disabled, disabled-with-reason (CMP-079: only the fill dims; the glyph stays at full opacity in `color.text.primary`; a `size.icon.sm` `locked` badge in the bottom-right corner, so the box never grows; reason tooltip; superseded by E09-D09 §2.2 T2 (the E05-D02 boards PR restates it)); toggle mode adds pressed (aria-pressed true), drawn as `Pressed=true` with each state: a `color.action.selected` fill with a 2 px inner `color.border.selected` outline and a `color.text.primary` icon, unchanged on hover; when gated, only the fill dims and the outline stays.
- **A11y**: `aria-label` required (lint-enforced, build fails without it), `aria-pressed` for toggle mode (the name does not change with the state), min hit-target 24×24px compact / 32×32px comfortable (`size.control.height`, square; meets WCAG 2.5.8 with no essential exception).
- **Tokens**: `color.action.primary.default`, `color.action.primary.hover`, `color.action.secondary.default`, `color.action.secondary.hover`, `color.surface.hover`, `color.status.danger.default`, `color.action.selected` + `color.border.selected` (pressed), `color.text.primary`, `color.text.secondary`, `color.text.on-action`, `color.focus.ring`, `radius.control`, `size.control.height`, `size.icon` (sm/lg via CMP-019 Icon sizes), `size.icon.sm` (gated `locked` badge), `space.inset.xs`, `opacity.disabled`, `border.focus`, `border.thick` (pressed outline).
- **Storybook**: Default, Toggle, AllSizes, DisabledWithReason.
- **Tests**: unit, visual, axe (label presence lint + runtime check), keyboard toggle.
- **E08-D05 (A-D05-15)**: met as built, with no variant: the box is `size.control.height` square, and a control step is a row step at each density (24 and 32 px, `16` §3), so the `⋯` in a bar one row high (SCR-102's detail bar) keeps 24 × 24 px compact and 32 × 32 px comfortable (`05` §3.4 item 7). Storybook adds RowTarget.

### CMP-003 SegmentedControl

- **Tier**: Atom · **Purpose**: exclusive choice among 2–6 options (e.g. chart type, density mode, order type Market/Limit/Conditional).
- **Props**: `options: {value,label,icon?}[]` (2–6; `label` is the visible text, or the `aria-label` when the control is icon-only) · `value` · `onChange` · `size: "sm"|"md"` (default `md`) · `fullWidth?` · `disabled?/disabledReason?`.
- **States**: default, hover (an unselected option takes `color.surface.hover` with `color.text.primary` text; the selected option does not change), focus-visible, disabled (radiogroup and every radio `aria-disabled`, all `tabindex="-1"`), disabled-with-reason (CMP-079: the track and the selected fill dim; the selected outline and the option labels stay at full opacity, the selected label in `color.text.primary`; a trailing `locked` glyph after the last option; the checked radio stays focusable and carries the reason via `aria-describedby`; superseded by E09-D09 §2.2 T2 (the E05-D02 boards PR restates it)); each option is unselected or selected (`aria-checked`; selected = `color.action.selected` fill with a 2 px inner `color.border.selected` outline and `color.text.primary` text).
- **A11y**: `role="radiogroup"` container, each option `role="radio"` + `aria-checked`; arrow-key roving tabindex navigation, `Home`/`End` jump to first/last.
- **Tokens**: `color.surface.raised`, `color.surface.hover`, `color.action.selected`, `color.border.selected`, `color.text.primary`, `color.text.secondary`, `color.focus.ring`, `radius.control`, `size.control.height`, `size.icon`, `space.button.paddingX`, `space.inset.xs`, `space.inset.sm`, `type.ui.label`, `type.ui.body`, `type.ui.body-strong`, `opacity.disabled`, `border.focus`, `border.thick` (selected outline).
- **Storybook**: Default, IconOnly, ManyOptions, Disabled.
- **Tests**: unit, visual, axe, keyboard roving-tabindex interaction test.

### CMP-004 Toggle (Switch)

- **Tier**: Atom · **Purpose**: binary on/off (1-click trading arm, feature flags, dark/light).
- **Props**: `checked` · `onChange` · `label` · `labelPosition: "left"|"right"|"hidden"` · `size` · `disabled?/disabledReason?` · `critical?: boolean` (renders with stronger visual weight + confirm-wrapper requirement, e.g. 1-click arm).
- **States**: default, hover (the track keeps its fill and gains a 1 px inner `color.text.secondary` outline, off and on alike), focus-visible, disabled, disabled-with-reason (CMP-079: only the track dims; the label and the knob stay at full opacity in `color.text.primary`; a trailing `locked` icon; `aria-disabled` + `aria-describedby`, CMP-016 reason tooltip; superseded by E09-D09 §2.2 T2 (the E05-D02 boards PR restates it)); `checked` false/true is shown by knob position and track colour.
- **A11y**: native `role="switch"` `aria-checked`. `Enter`/`Space` toggles.
- **Tokens**: `color.action.primary.default` (on track), `color.text.tertiary` (off track), `color.text.secondary` (hover outline, `locked` icon), `color.text.on-action` (knob), `color.text.primary` (label; knob when disabled-with-reason), `radius.badge`, `size.icon` (knob, travel), `space.inset.xs` (track padding), `space.field.gap`, `size.control.height`, `type.ui.body`, `opacity.disabled`, `color.focus.ring`; motion: knob slide + track colour fade over `motion.duration.fast` / `motion.easing.standard`, motion-reduce = instant (no semantic motion token yet).
- **Storybook**: Default, Critical (1-click-arm look), WithLabel, Disabled.
- **Tests**: unit, visual, axe, keyboard toggle, critical-variant confirm-wrapper composition test.

### CMP-005 Checkbox

- **Tier**: Atom · **Purpose**: multi-select, agree/confirm gates; the boolean fields of a properties popover (a mixed selection needs `indeterminate`) (E14-D04 A4).
- **Props**: `checked` · `indeterminate?` · `onChange` · `label` · `disabled?/disabledReason?`.
- **States**: default, hover (unchecked: the outline steps to `color.text.secondary`; checked and indeterminate: the fill stays and a 1 px inner `color.text.secondary` outline appears), focus-visible, disabled, disabled-with-reason (CMP-079: only the box dims; the label and the glyph stay at full opacity in `color.text.primary`; a trailing `locked` icon; `aria-disabled` + `aria-describedby`, stays focusable, the value cannot change; CMP-016 reason tooltip; superseded by E09-D09 §2.2 T2 (the E05-D02 boards PR restates it)); `checked` false / true (`check` glyph) / indeterminate (`minus` glyph, `aria-checked="mixed"`); the glyph, not the colour, carries the state.
- **A11y**: native `<input type=checkbox>` semantics, `aria-checked="mixed"` for indeterminate. `aria-checked="mixed"` is paired with the visible word "Mixed" beside the label (E14-D04 A4).
- **Tokens**: `color.action.primary.default` (checked/indeterminate box fill and outline), `color.text.on-action` (`check` / `minus` glyph), `color.surface.raised` + `color.text.tertiary` 1 px outline (unchecked box, ≥3:1 on every surface; `color.text.secondary` as the hover outline, unchecked and checked), `radius.control`, `size.icon` (box, glyph, `locked` icon), `size.control.height` (row and hit target), `space.field.gap`, `type.ui.body`, `color.text.primary` (label; glyph when disabled-with-reason), `color.text.secondary` (`locked` icon), `opacity.disabled`, `color.focus.ring`.
- **Storybook**: Default, Indeterminate, Disabled.
- **Tests**: unit, visual, axe, keyboard.

### CMP-006 RadioGroup

- **Tier**: Atom · **Purpose**: exclusive choice, vertical list form (position side in some forms, sizing-rule type).
- **Props**: `options: {value,label,description?,disabled?,disabledReason?}[]` (`description`: one line under the label, the option's accessible description; E12-D05 §3.1) · `value` · `onChange` · `orientation: "vertical"|"horizontal"` (default `"vertical"`) · `disabled?/disabledReason?` · `aria-label?/aria-labelledby?` (one is required: the group's accessible name).
- **States**: default, hover (an unselected option's ring outline steps to `color.text.secondary`; the selected ring keeps its fill and gains a 1 px inner `color.text.secondary` outline), focus-visible (ring on the checked radio, which holds the roving tab stop), disabled (whole group, out of the tab order), disabled-with-reason (whole group, CMP-079: the rings dim, the labels and the dot stay at full opacity in `color.text.primary`, a trailing `locked` icon after the checked option's label, `aria-disabled` + `aria-describedby`, the checked radio keeps the tab stop, CMP-016 reason tooltip; superseded by E09-D09 §2.2 T2 (the E05-D02 boards PR restates it)); an option with `disabledReason` dims only its ring and shows its own trailing `locked` icon and reason, reachable by the arrows but never checked.
- **A11y**: `role="radiogroup"`, roving tabindex, arrow-key navigation.
- **Tokens**: `color.action.primary.default` (selected ring), `color.text.on-action` (selected dot), `color.surface.raised` + `color.text.tertiary` 1 px outline (unselected ring, ≥3:1; `color.text.secondary` as the hover outline, unselected and selected), `radius.badge`, `size.icon` (ring, `locked` icon), `space.inset.xs` (dot inset), `size.control.height` (option row and hit target), `space.field.gap` (ring to label), `space.stack.sm` (vertical option gap) / `space.inset.lg` (horizontal option gap), `type.ui.body`, `color.text.primary` (labels; dot when disabled-with-reason), `color.text.secondary` (`locked` icon), `opacity.disabled`, `color.focus.ring`.
- **Storybook**: Default, Horizontal, Disabled.
- **Tests**: unit, visual, axe, keyboard.

### CMP-007 TextInput

- **Tier**: Atom · **Purpose**: base single-line text entry, wrapped by molecules (PriceInput, QtyInput, SymbolSearchInput).
- **Props**: `value` · `onChange` · `placeholder?` (an example, never the label) · `prefix?/suffix?: ReactNode` · `size` · `invalid?: boolean` · `errorMessage?` · `disabled?` · `disabledReason?` (`docs/design/E09/E09-D09.md` §2.2 T2, through CMP-040 or CMP-079) · `readOnly?` · `inputMode?` · `maxLength?`.
- **States**: default; hover (the 1 px boundary steps from `color.text.tertiary` to `color.text.secondary`); focus-visible (the CMP-039 ring, on pointer focus too); invalid (a 2 px `color.status.danger.default` boundary, the `danger` glyph and the message under the field, never colour alone); disabled (unavailable to everyone in this state: the whole field at `opacity.disabled`, native `disabled`; never for a gate or for validity); disabled-with-reason (`docs/design/E09/E09-D09.md` §2.2 T2 through CMP-079: `aria-disabled` + `readonly`, never `disabled`; the well `color.surface.raised` with a `color.border.default` hairline; the CMP-019 `lock` glyph leads the value inside the well, both `color.text.tertiary`, and the label is unchanged (`docs/design/E30/E30-D04.md` §2.5); the reason sits under the field, through CMP-040); read-only (no fill, a `color.border.default` hairline, the value `color.text.primary`, focusable).
- **A11y**: `<input>` with `aria-invalid`, `aria-describedby` → error message id (the only reference to the message: no `aria-errormessage`); the message is in the DOM at mount and announced politely once when blur validation shows or changes it; a T2 field keeps its Tab stop and its `aria-describedby` points at the reason alone.
- **Tokens**: well `color.surface.app` with a 1 px `color.text.tertiary` boundary (hover `color.text.secondary`; invalid 2 px `color.status.danger.default`, `border.thick`; read-only and T2 a `color.border.default` hairline, T2 on `color.surface.raised`), `radius.control`, `size.control.height` (min-height), `space.inset.sm` (padding), `space.inset.xs` (gap); value `type.ui.body` + `color.text.primary` (numeric inputs `type.num.base`); placeholder and affixes `color.text.tertiary`; `size.icon` (prefix glyph, T2 `lock`); `color.focus.ring` + `border.focus`; `opacity.disabled`. (Replaces `color.border.*`, `color.text.error`, `radius.sm` and `font.mono`, which are not shipped semantic tokens.)
- **Storybook**: Default, WithPrefixSuffix, Invalid, Disabled, ReadOnly, DisabledWithReason.
- **Tests**: unit, visual, axe, keyboard, invalid-state announcement test (live region / aria-invalid change).

### CMP-008 NumericStepperInput

- **Tier**: Atom · **Purpose**: base numeric input with +/- step buttons; underlies PriceInput/QtyInput (CMP-100/101).
- **Props**: `value: number` · `min?/max?` · `step: number` · `largeStep?: number` (default 10 × `step`) · `precision: number` · `suffix?` (the unit) · `onChange` · `onStep(direction)` · `invalid?` · `disabled?` · `disabledReason?` · `readOnly?` · `maxLength?: number` (typed characters; E12-D03 DS-4).
- **States**: default, hover, focus-visible, invalid, disabled, disabled-with-reason (`docs/design/E09/E09-D09.md` §2.2 T2 through CMP-079, as CMP-007: the CMP-019 `lock` leads the value inside the well; the step buttons share the field's reason), read-only (as CMP-007); at a bound the matching step button is plain disabled (availability, not T2).
- **A11y**: `role="spinbutton"` semantics (`aria-valuenow/min/max/text`, the unit in `aria-valuetext`), `↑/↓` arrow keys step by `step`, `Shift+↑/↓` by 10 × `step`, `PageUp/PageDown` by `largeStep` (default ×10), `Home/End` jump to min/max; the `[−]`/`[+]` buttons are `tabindex="-1"` and named "Decrease {label}"/"Increase {label}"; typed text is parsed, rounded to `precision` and range-checked on blur, never mid-keystroke, and a value out of range is invalid, never silently clamped; typed group separators (commas, spaces) are accepted and dropped, and with `precision: 0` no decimal point is accepted (whole-number mode; E12-D03 D3-13, DS-4). A mixed value shows the first value visually neutral with `aria-valuetext="Mixed"` until touched (E14-D04 A5).
- **Tokens**: the CMP-007 well and its states; value `type.num.base`, end-aligned; step buttons CMP-002 ghost (`color.text.secondary`; hover `color.surface.hover` + `color.text.primary`), `size.control.height` square, `space.inset.xs` apart and from the well. (Replaces `font.mono` and `color.border.*`.)
- **Storybook**: Default, MinMaxClamped, KeyboardStepDemo, Invalid, DisabledWithReason, Mixed.
- **Tests**: unit (clamping/precision rounding), visual, axe, keyboard step interaction, fuzz test for float precision edge cases.

### CMP-009 Select (native-pattern dropdown)

- **Tier**: Atom · **Purpose**: single choice from a closed list (interval picker, order category).
- **Props**: `options[]` (each may carry `disabled?`, `unavailableReason?` or `disabledReason?`) · `value` · `onChange` · `placeholder?` · `size` · `invalid?` · `disabled?` · `disabledReason?` · `searchable?: boolean` (renders CMP-048's editable combobox) · `renderOption?` (an option may show a specimen — a 24 px stroke sample — beside its word; E14-D04 A7).
- **States**: default, hover, focus-visible, open (the listbox on `color.surface.overlay`), invalid, disabled, disabled-with-reason (`docs/design/E09/E09-D09.md` §2.2 T2 through CMP-079 and CMP-040: the CMP-019 `lock` leads the value in the trigger; the listbox never opens); options: active (`color.surface.hover`), selected (the `check` glyph), disabled (skipped by the arrows), unavailable (`docs/design/E30/E30-D04.md` §2.5's validity look with only the label dimmed, `docs/design/E05/E05-D02-form-controls.md` §5.2: the label at `opacity.disabled`, `unavailableReason` as the second line at full opacity, reachable by the arrows, never chosen, no lock), disabled-with-reason (T2: the `lock` glyph and the full label in `color.text.tertiary`, the reason as the second line, reachable by the arrows, never chosen).
- **A11y**: WAI-ARIA APG "Listbox"/"Combobox" pattern (any primitive that meets the select-only combobox, `docs/design/E05/E05-D02-form-controls.md` §6 G9), `aria-expanded`, `aria-activedescendant`, type-ahead; the trigger keeps focus and `aria-activedescendant` names the active option (the APG select-only combobox); `Esc` closes with the value unchanged; an unavailable or T2 option takes `aria-disabled` + `aria-describedby` → its reason line, and neither `Enter` nor `Tab` chooses it; an option's name is its label; its second line and its reason line are its description (a T2 option's, the reason alone). A mixed selection reads "Mixed" in the trigger (E14-D04 A7).
- **Tokens**: trigger the CMP-007 well with a `chevron-down` (`size.icon`, `color.text.secondary`); listbox `color.surface.overlay`, `elevation.popover`, `radius.card`, a 1 px `color.border.default` edge, at most 10 rows; options `size.row.height`, `space.inset.sm`, `type.ui.body` + `color.text.primary`, active `color.surface.hover`, `check` glyph `color.text.primary`; an unavailable option's label at `opacity.disabled`, its reason `type.ui.caption` + `color.text.secondary`. (Replaces `elevation.2` and `radius.md`, which are primitives.)
- **Storybook**: Default, Searchable, Disabled, LongList (virtualized), Open, UnavailableOption, DisabledWithReason, WithSpecimen, Mixed.
- **Tests**: unit, visual, axe, keyboard (type-ahead, arrow nav, Esc closes, focus returns to trigger).

### CMP-010 Slider

- **Tier**: Atom · **Purpose**: base range slider; underlies LeverageSlider (CMP-104).
- **Props**: `value` · `min/max/step` · `onChange` · `marks?: number[]` · `disabled?/disabledReason?` · `aria-label?/aria-labelledby?` (one is required: the slider's accessible name).
- **States**: default, hover (the unfilled track steps to `color.text.secondary`; the thumb does not change), focus-visible (ring on the thumb), disabled (out of the tab order), disabled-with-reason (CMP-079: only the two tracks dim; the thumb stays at full opacity in `color.text.primary` and the marks stay readable; `aria-disabled` + `aria-describedby`, the thumb stays focusable and no key or pointer changes the value, a trailing `locked` icon after the rail, CMP-016 reason tooltip; superseded by E09-D09 §2.2 T2 (the E05-D02 boards PR restates it)); with `marks`, numeric labels sit under the rail at each mark value and collapse to min and max where they would collide.
- **A11y**: `role="slider"`, `aria-valuenow/min/max/text`, arrow keys ±step, `PageUp/Down` ±10×step, `Home/End`. A mixed value: `aria-valuetext="Mixed"` (E14-D04 A6).
- **Tokens**: `color.action.primary.default` (filled track and thumb), `color.text.tertiary` (unfilled track, ≥3:1; `color.text.secondary` on hover), `radius.badge`, `size.icon` (thumb, mark slots, `locked` icon), `space.inset.xs` (track thickness, as the vertical padding of an empty track segment), `size.control.height` (rail, pointer target and lock slot), `space.stack.xs`, `space.field.gap` (gap before the `locked` icon), `type.num.sm` + `color.text.secondary` (mark labels and `locked` icon), `color.text.primary` (thumb when disabled-with-reason), `opacity.disabled`, `color.focus.ring`.
- **Storybook**: Default, WithMarks, Disabled, Mixed.
- **Tests**: unit, visual, axe, keyboard.

### CMP-011 Tag / Chip

- **Tier**: Atom · **Purpose**: compact label (tag on journal entry, symbol category, "(estimated)" chip).
- **Props**: `label` · `variant: "neutral"|"info"|"warning"|"danger"|"estimated"` · `icon?` · `removable?` · `onRemove?`.
- **Variants**: neutral (default), info, warning, danger, estimated. info/warning/danger always render their fixed registry glyph (colour-never-alone); `icon?` applies to neutral only and is ignored otherwise. estimated renders the literal "(estimated)" with a dashed outline and no icon; superseded by CMP-227 (E25-D05 §3–§4, the E25-D05 line of this entry): the estimated variant renders CMP-227's look and states. Only neutral chips may be removable.
- **States**: default; focus-visible and disabled only for the interactive configurations (the removable chip's remove IconButton; the estimated chip). Disabled is the chip's own state and is never stacked on a disabled parent; for the estimated chip, superseded by CMP-227 (E25-D05 §3–§4, the E25-D05 line of this entry): the estimated variant renders CMP-227's look and states. RBAC/env-gated removal uses CMP-079 on the remove IconButton, or omits the control; superseded by E09-D09 §2.2 T2 (the E05-D02 boards PR restates it), and the omission by `14-screens-catalogue.md` §0.5.5 / E09-D09 §2.1 (never hidden; read-only tags, a data property, may still omit it).
- **A11y**: if removable, remove control is a labelled `IconButton` (CMP-002) child, not a bare `×`. Enter/Space on the remove button fires `onRemove`; the owning group (CMP-169, CMP-055) moves focus to the next chip, else the previous one, else its input, never to `<body>`.
- **Tokens**: `radius.badge`, `size.control.height` (height), `space.inset.sm` (paddingX; paddingLeft when removable), `space.inset.xs` (gap; paddingRight when removable), `size.icon`, `type.ui.caption`; neutral: `color.neutral.subtle` fill + `color.border.default` 1 px stroke + `color.text.secondary` label/icon; info/warning/danger: `color.status.{tone}.subtle` fill + `color.text.primary` label + mandatory `info`/`warning`/`danger` glyph in `color.status.{tone}.strong`; estimated: no fill + dashed 1 px `color.status.info.strong` outline + `color.text.secondary` label "(estimated)"; superseded by CMP-227 (E25-D05 §3–§4, the E25-D05 line of this entry): the estimated variant renders CMP-227's look and states; focus ring `color.focus.ring`. (Replaces `color.chip.*` and `radius.pill`, which are not shipped semantic tokens.)
- **E25-D05**: the `estimated` variant is a deprecated alias that renders CMP-227 EstimatedBadge (the one canonical badge, bound to the methodology drawer by its provider) — new consumers use CMP-227 directly.
- **Storybook**: AllVariants, Removable, EstimatedChip (with tooltip).
- **Tests**: unit, visual, axe, keyboard remove.
- **As built (E05-S02)**: the `estimated` variant is omitted until CMP-227 exists, so no second estimated look ships and Storybook has no EstimatedChip (#265 ruling 3); `density?` emits `data-density`; a removable chip takes `disabled?` / `disabledReason?` for its remove CMP-002.

### CMP-012 Badge (status dot/count)

- **Tier**: Atom · **Purpose**: small numeric/status indicator (unread count, connection dot).
- **Props**: `variant: "count"|"dot"` · `value?: number` · `tone: "neutral"|"info"|"success"|"warning"|"danger"`.
- **A11y**: `aria-label` describing meaning (e.g. "3 unread alerts"), never colour-only — dot variant always paired with adjacent text/icon at point of use. A dot is always `aria-hidden` and never rendered alone. It sits beside a visible word and, for info/success/warning/danger, the tone's registry glyph. A standalone count is `role="img"` + `aria-label` naming what is counted and any condition ("3 unread alerts"; ARIA 1.2 prohibits `aria-label` on a generic span). On a labelled control (e.g. the notifications IconButton) the count is `aria-hidden` and joins the control's name ("Notifications, 3 unread"). Tone never carries the condition alone.
- **Tokens**: dot `color.status.{info|success|warning|danger}.default` (neutral: `color.neutral.default`), 8 px = `space.inset.xs` padding, centred in a `size.icon` slot, `radius.badge`, placed on `color.surface.app` or `color.surface.canvas`; count `color.status.{tone}.subtle` fill + 1 px `color.status.{tone}.strong` outline (neutral: `color.neutral.subtle` + `color.neutral.default`), numeral `type.num.xs` in `color.text.primary`, height and min-width `size.icon`, paddingX `space.inset.xs`, `radius.badge`.
- **Storybook**: Count, Dot, AllTones.
- **Tests**: unit, visual, axe.
- **E40-D02 (#1013; [E40-D02.md](../design/E40/E40-D02.md) §7.4; owner approval pending)**: the notifications bell's and SCR-090 Fired tab's `count` badge is a filled count: `color.status.info.strong` fill with a `color.text.inverse` numeral (CP-14: 10.92 / 5.05 / 10.92), never `color.status.info.default`, which fails 4.5:1 in light and 7:1 in high contrast (CP-15); "99+" above 99; on the labelled bell the count is `aria-hidden` and joins its name ("Notifications, 3 unread").

### CMP-013 Avatar / ProfileBadge base

- **Tier**: Atom · **Purpose**: initials/icon circle for accounts/managers; base for CMP-106 AccountBadge.
- **Props**: `label: string` (initials derived) · `color?: string` (deterministic per-account hash) · `size: "sm"|"md"` (default `md`; sm = `size.icon`, one initial; md = `size.control.height`, two initials).
- **A11y**: decorative unless only content — pairs with visible text label at point of use. Decorative → `aria-hidden="true"`; only content → `role="img"` + `aria-label` = the full label.
- **Tokens**: `radius.badge` (circle on a square box), `size.control.height` (md) / `size.icon` (sm), initials `type.ui.label` (md) / `type.ui.caption` (sm) in `color.text.primary`, fill `color.neutral.subtle` until an avatar palette is approved. (Replaces `color.avatar.palette[]`, which is not shipped, and `radius.circle`, which is a primitive.)
- **Storybook**: Default, AllSizes, ColorPalette.
- **Tests**: unit, visual.
- **As built (E05-S02)**: no `color` prop until an avatar palette is approved (§5 E2), so ColorPalette waits; `standalone?: boolean` selects the only-content form (`role="img"` named by the full label), decorative otherwise.

### CMP-014 Spinner / Loader

- **Tier**: Atom · **Purpose**: indeterminate loading indicator.
- **Props**: `size: "sm"|"md"` (default `md`; sm = `size.icon` for nested and inline use, md = `size.control.height` standalone) · `label?: string` (for standalone use, else decorative inside a labelled parent).
- **A11y**: `role="status"` + `aria-live="polite"` when standalone; `aria-hidden` when nested inside an already-announced busy control (e.g. CMP-001 loading state) to avoid double announcement. `label` selects the mode. With `label`, the spinner is standalone: a `role="status"` region containing `label` as a visually hidden text node (live regions announce content, not `aria-label`), mounted before the text is inserted. Without `label`, it is nested: `aria-hidden`, allowed only inside a host with `aria-busy` or its own `role="status"` (lint/test-enforced), so an unlabelled standalone spinner cannot ship. Slow path: a spinner bound to a request never stops while its host is busy; after 5 s the host shows visible slow-path text next to it through CMP-038, announced once (polite). An order submit shows "Checking with the exchange…" and stays busy until the exchange resolves the order, with no Cancel (retries reuse its `orderLinkId` and the OMS reconciles it, C-2.10); only a load, an export or a replay may add a Cancel action. A long-lived status spinner (e.g. reconnecting) stops moving after 5 s or offers a pause control (`16-design-system-brief.md` §7).
- **Tokens**: arc `color.action.primary.default` (a host on a filled surface overrides it with its label token, e.g. CMP-001 primary → `color.text.on-action`; not used on `color.surface.selected`); `size.icon` (sm) / `size.control.height` (md); motion-safe: one turn per 800 ms, linear, for as long as a request keeps the host busy (no time cap; a status spinner follows the A11y line's 5 s rule); motion-reduce: no rotation; the arc pulses without dimming below 3:1: a standalone arc cross-fades between `color.action.primary.default` and `color.text.secondary` every 1.6 s, an arc in its host's label token (inside a button) pulses opacity 1 ↔ 0.8. (Replaces `color.action.primary` and `motion.spin`, which are not shipped.)
- **Storybook**: Default, AllSizes, Standalone(labelled), Nested(hidden), SlowPath (the 5 s host text: "Checking with the exchange…" on an order submit, without Cancel; a load's text with Cancel).
- **Tests**: unit, visual, axe, reduced-motion snapshot.

### CMP-015 Skeleton

- **Tier**: Atom · **Purpose**: loading placeholder for panels/rows/cards.
- **Props**: `shape: "text"|"row"|"card"|"chart"` · `count?: number`. `shape="chart"` is a plain block for a chart-sized slot in a card, a row or a tile; a chart pane uses CMP-029.
- **States**: shimmer (a band sweeping the fill to `color.surface.raised` and back, one sweep per 1,200 ms, stopped at 5 s, after which the host's slow-path words carry the wait); static (the two-tone fill, under reduced motion from the first frame and after the stop).
- **A11y**: `aria-hidden="true"` (the loading state is announced once by the parent container's `aria-busy`, not per-skeleton). The host's own words (CMP-038 or a table caption) carry the wait.
- **Tokens**: blocks `color.surface.hover` (`color.surface.selected` on an overlay host); the shimmer's band `color.surface.raised` (`color.surface.hover` on an overlay host), a 1,200 ms period (3 × `motion.duration.slow`) (motion-reduce: static tone, no shimmer); `radius.control` (text and row blocks), `radius.card` (card and chart); rows `size.row.height`; `space.stack.xs`, `space.inset.sm`, `space.inset.md`. (Replaces `color.surface.skeleton` and `motion.shimmer`, which are not shipped tokens.)
- **Storybook**: AllShapes, Count, Static, OnOverlay.
- **Tests**: unit, visual, reduced-motion snapshot.
- **As built (E05-S02)**: `surface?: "base"|"overlay"` (default `base`) selects the overlay tones; `count` is a whole number from 1 to 50.

### CMP-016 Tooltip

- **Tier**: Atom · **Purpose**: contextual help / disabled-reason / estimated-methodology text.
- **Props**: `content: string` (text only; a link or a control needs CMP-017 Popover) · `mode?: "describes"|"echo"` (default `describes`; `echo` duplicates a name or a reason that lives elsewhere) · `side` · `delay?: number` (default 300ms) · `triggerOnFocus?: boolean` (true always, for keyboard parity).
- **A11y**: appears on hover AND focus, dismissible via `Esc`, does not trap focus, `role="tooltip"` + `aria-describedby` linking trigger. In `describes` mode the tooltip node is in the DOM at mount (`hidden` until shown), so the description is there when focus lands; in `echo` mode it is `aria-hidden="true"` and the trigger keeps its own `aria-label` or its `aria-describedby` → the always-rendered reason (`docs/design/E09/E09-D09.md` §9.2), so nothing is read twice; it is never the only copy of a reason and never the `title` attribute. As T2's 2b echo it shows the reason of a trigger wrapped in CMP-079 RbacGate (`form="tooltip"`), whose CMP-019 `lock` badge is the visible marker. Hover shows it after `delay`; keyboard focus (`:focus-visible`) shows it at once; it stays while the pointer is on the trigger or the tooltip (WCAG 1.4.13) and hides on leave after a 100 ms grace, on blur and on `Esc`, which stops there; never on a timer.
- **Tokens**: `color.surface.overlay`, `elevation.popover`, `radius.card`, a 1 px `color.border.default` edge; `type.ui.caption` + `color.text.primary`; padding `space.inset.xs` (block) and `space.inset.sm` (inline); `space.inset.xs` from the trigger; at most 320 px wide. (Replaces `elevation.3` and `radius.sm`, which are primitives.)
- **Storybook**: Default, LongContent, KeyboardTriggered, Echo.
- **Tests**: unit, visual, axe, keyboard show/dismiss.
- **As built (E05-S02)**: positioned by `@floating-ui/dom` (positioning only) through one internal anchored-position hook shared with CMP-017, which flips rather than clips and listens only while shown; the ARIA and behaviour are ours (#265 ruling 1). Empty or whitespace-only `content` renders no node and never shows, so a host keeps one stable tree while its echo comes and goes; content that arrives while the trigger holds keyboard focus or the pointer shows at once, unless `Esc` dismissed it or the trigger has since gone natively disabled. `triggerOnFocus` admits only `true`; a trigger that cannot take focus never shows it and warns in development (ruling 8). A pointer focus waits for the hover delay; a 300 ms skip window opens the next trigger's tooltip at once. On CMP-002 the D10 name echo of a gated control joins "name · reason". Storybook splits Echo into EchoName and EchoReason and adds EscDismiss, Right, Bottom, Left and EdgeFlip.

### CMP-017 Popover

- **Tier**: Atom · **Purpose**: base floating panel for menus/pickers (underlies CMP-041 Menu, CMP-047 DatePicker etc.).
- **Props**: `open` · `onOpenChange` · `anchor` · `placement` · `modal?: boolean` · `aria-label?/aria-labelledby?` (one required) · `initialFocusRef?`.
- **A11y**: focus-trap when `modal`, returns focus to trigger on close, `Esc` closes, click-outside closes (with `pointerdown` guard to avoid mis-fire on drag). It is a `role="dialog"` (`aria-modal="true"` only when `modal`) named by its heading or `aria-label`; focus moves into it on open (its first control, `initialFocusRef` or its heading); in a non-modal popover Tab past its last control closes it and moves on from the trigger, and `Shift+Tab` before its first returns to the trigger; an outside press closes it only when it starts and ends outside; the trigger carries `aria-haspopup="dialog"`, `aria-expanded` and `aria-controls`.
- **Tokens**: `color.surface.overlay`, `elevation.popover`, `radius.card`, a 1 px `color.border.default` edge; padding `space.inset.sm`; `space.inset.xs` from the anchor. (Replaces `elevation.3` and `radius.md`, which are primitives.)
- **Storybook**: Default, Modal, NonModal, Flipped, Scrolling.
- **Usage (E14-D08)**: the SCR-037 properties popover is a composition on this entry — `modal: false`, `Esc` returns focus to the drawing's surrogate, `Tab` past the last field leaves, click-outside with the `pointerdown` guard, `elevation.popover`, `radius.card` (E14-D02 §7.1, E14-D04 §2); the read-only forms: one notice under the title (`rbac.view_as` / `notice.panel_read_only` / `drawing.locked`), every gated control T2 — the CMP-019 `lock`, `aria-disabled`, `aria-describedby` → the notice, the role legs in CMP-079 RbacGate (E14-D04 §8.1); its stories ride under `Organisms/DrawingPropertiesPopover` as a story-band name, not an id (E14-D08 §3).
- **Tests**: unit, visual, axe, focus-trap/return test.
- **As built (E05-S02)**: `anchor` is the trigger element itself (one CMP-001 or CMP-002), onto which the popover composes `aria-haspopup`, `aria-expanded`, `aria-controls` and the toggle; `open` / `defaultOpen` / `onOpenChange` work controlled or not; `placement?: "below"|"above"` (default `below`, flipped when there is no room); `heading?` names it through `aria-labelledby` (one of `aria-label`, `aria-labelledby` or `heading` is required); `footer?` is an end-aligned CMP-001 row. Focus leaving a non-modal popover closes it; an outside press moves focus to the pressed control, else the trigger. It appears at once and the exit fades over `fast` (a cut under reduced motion); closed, it is an empty `hidden` shell so `aria-controls` stays valid. Known limits: a non-modal popover closes when focus enters another portalled layer, and a Popover inside a future CMP-043 Dialog is portalled outside its trap. Storybook adds EscDismiss, OutsideClick and Above.
- **As built (E05-S03)**: it is a layer of the shared overlay stack: `Esc` closes the topmost layer only, focus or a press in a layer opened above it (a nested popover or menu) does not close it, and inside a CMP-043 Dialog it portals into the dialog's layer, inside its trap and outside the inert page. The two E05-S02 known limits are gone.

### CMP-018 Divider

- **Tier**: Atom · **Purpose**: visual/semantic separator.
- **Props**: `orientation: "horizontal"|"vertical"` (default `horizontal`) · `inset?: boolean` (default false; insets both ends: horizontal `space.inset.md`, vertical `space.inset.xs`) · `decorative?: boolean` (default false; true removes it from the accessibility tree).
- **A11y**: `role="separator"` when semantically meaningful (e.g. inside menu), decorative otherwise.
- **Tokens**: rule fill `color.border.subtle`, 1 px thick (equal to primitive `border.hairline`; no semantic width token); inset `space.inset.md` (horizontal) / `space.inset.xs` (vertical); vertical default length `size.control.height`.
- **Storybook**: Horizontal, Vertical.
- **Tests**: unit, visual.
- **As built (E05-S02)**: a plain `div` drawn as a border (forced colours keep it), not Radix Separator: `role="separator"` by default and `role="none"` when `decorative`; `aria-orientation` is set only when vertical. Storybook adds Decorative and Labelled.

### CMP-019 Icon

- **Tier**: Atom · **Purpose**: single glyph from the icon set (`16-design-system-brief.md` §5).
- **Props**: `name: IconName` · `size` · `decorative?: boolean` (default true → `aria-hidden`; false requires `label`).
- **A11y**: `aria-hidden="true"` by default; when `decorative=false`, renders `role="img"` + `aria-label`.
- **Tokens**: stroke = `currentColor` from the context's text token (`color.text.*`; on a filled action, the host label's token) or the tone's `color.status.*.strong` token (Penpot masters bind `color.text.primary`); 1.5 px stroke at every size, no fill; size `size.icon` by default, or `size.icon.sm` / `size.icon.md` / `size.icon.lg` (12/16/20 px as shipped) via `size`.
- **Storybook**: FullSet (every registry icon; Penpot components `icon/{name}`, 47 base glyphs), SizeScale (sm / md / lg).
- **Trading glyphs** (`docs/design/E05/E05-D02-rest.md` §7.12; §6 J22–J25, RULED 6438042003; drawn, registered and tested by E05-T06, #271): the registry adds 13 custom glyphs on the base set's 24-unit grid with the same 1.5 px stroke, registered as `icon/{name}` with §7.12's descriptions: `flatten-all`, `chase-limit`, `iceberg-order`, `twap`, `one-click-arm`, `native-sl-shield`, `estimated`, `node-trigger`, `node-condition`, `node-action`, `node-logic-gate`, `node-comment`, `heatmap-convention-swap` (J22); `one-click-arm` marks only the 1-click trading toggle and its armed indicator, never CMP-229 ArmToggle, which keeps `unlock` / `lock` (J23); each has one 24-unit master, and a glyph whose detail closes up at 12 px has a reduced 12 px form (`estimated`) or is 16 px minimum, per §7.12's table (J24); every one strokes in `currentColor` and never carries a category or side hue, so the node glyphs never take `color.node.*` (J25). Decorative beside a word; standalone, `decorative=false` with §7.12's name. FullSet and the completeness test grow by these 13.
- **Usage (E14-D08)**: the drawing glyphs (E14-D03 §2.1, 34 PROPOSED `IconName`s on the base set's 24-unit grid, 1.5 px stroke, designed at 16 px; E14-D07 G-10's two; vendored by E14-S10 with the design-system CODEOWNER): `cursor`, `crosshair`, `select-area`, `trendline`, `ray`, `extended-line`, `horizontal-line`, `vertical-line`, `rectangle`, `ellipse`, `triangle`, `parallel-channel`, `fib-retracement`, `fib-extension`, `fib-timezone`, `anchored-vwap`, `measure`, `long-position`, `short-position`, `text-note`, `callout`, `arrow`, `polyline`, `magnet-off`, `magnet-weak`, `magnet-strong`, `pin`, `lock-open`, `eye`, `eye-off`, `trash`, `more-horizontal`, `pencil`, `check` (`lock` reused), plus `pane` and `viewport-out`; Tokens: `color.text.*` (the glyph takes the text ink of its state), `size.icon.*`.
- **Tests**: unit (icon registry completeness), visual, axe (decorative-vs-labelled lint).

### CMP-020 Typography primitives (Text, Heading, NumericText, MonoText)

- **Tier**: Atom · **Purpose**: consistent type scale application; `NumericText` enforces tabular-nums + semantic colour + sign formatting for price/qty/PnL.
- **Props** (NumericText): `value: number` · `format: "price"|"qty"|"pct"|"pnl"|"notional"` · `precision?` · `signDisplay?: "auto"|"always"|"never"` (zero is always unsigned; `format="pnl"` and `colorBySign` both require `"always"`, per `05-accessibility-standard.md` §4) · `colorBySign?: boolean` (default false). Heading: `level: 1–6` (independent of its visual style).
- **A11y**: when abbreviated, `NumericText` renders the visible abbreviation `aria-hidden="true"` plus a visually-hidden expanded reading (e.g. "1.2M" → "1,200,000"); it does not put `aria-label` on the span (ARIA 1.2 prohibits naming generic elements) per §4. `Heading` renders `h1`–`h6` by `level`.
- **Tokens**: `type.ui.{caption,body,body-strong,label}` (Text) · `type.ui.{heading-sm,heading-md,heading-lg,display}` (Heading) · `type.num.{xs,sm,base,md,lg,xl}` (NumericText, MonoText; JetBrains Mono, fixed-width digits) · `color.text.primary` · `colorBySign`: `color.buy.default` / `color.sell.default` / `color.neutral.default` (below 4.5:1 as text on some surface tiers until §5 E1 of `docs/design/E05/E05-D02-data-display.md`).
- **Storybook**: TypeScale, NumericFormats, PnLColoring, AbbreviatedWithAriaLabel.
- **Tests**: unit (formatting matrix incl. locale-independent decimal point per trading convention), visual, axe.

### CMP-021 Link

- **Tier**: Atom · **Purpose**: in-app navigation/external link.
- **Props**: `href?` · `to?` (internal route) · `external?: boolean` (renders icon + `rel="noopener noreferrer"` + opens Electron shell external browser).
- **States**: default, focus-visible, disabled; the link text is always underlined (`color.text.link` is 2.16:1 against body text, so colour alone cannot mark a link, WCAG 1.4.1).
- **A11y**: native `<a>`, focus-visible ring, external-link icon has `aria-hidden` with adjacent visually-hidden "(opens externally)" text; disabled renders `<a role="link" aria-disabled="true">` with no `href` (not focusable).
- **Tokens**: `color.text.link` (text, underline, external-link icon), `type.ui.body`, `size.icon`, `space.inset.xs`, `color.focus.ring`, `opacity.disabled`, `border.focus`.
- **Storybook**: Internal, External.
- **Tests**: unit, visual, axe.
- **As built (E05-S02)**: `rel="noopener noreferrer"` and `target="_blank"` on every external link (E25, #265 ruling 5: no opener handle and no Referer for the private host); the CMP-039 ring sits at the link's own square corners, with no radius (E8); `to` requires `as`, the app's router link component (`packages/ui` never imports a router), which gets no `rel` or `target`; ungated (E27 held). Storybook adds Default, Hover, FocusVisible, ExternalFocusVisible, Disabled, LongText and ExternalNarrowWrap.

### CMP-022 Kbd (keyboard-shortcut glyph)

- **Tier**: Atom · **Purpose**: render a hotkey combination consistently (menus, tooltips, shortcuts settings screen).
- **Props**: `keys: string[]` (e.g. `["Ctrl","Shift","H"]`). `keys` holds the active keymap profile's display form of the binding: a digit range ("Alt+1..9") renders its two ends as caps with an en dash between them, a pointer chord ("Ctrl+click") its key caps and the pointer word as text; an unbound command renders nothing (`docs/design/E05/E05-D02-rest.md` §6 J5, RULED 6438042003).
- **A11y**: `<kbd>` semantic element, visually-hidden expansion text for screen readers ("Control plus Shift plus H"). One `<kbd>` per key nested in an outer `<kbd>`, no visible "+"; the visible caps are `aria-hidden="true"` and the outer `<kbd>`'s visually hidden expansion takes its key words from the keymap's name table (E10/E49), never written per screen; inside a menu item the whole Kbd is hidden and the item's `aria-keyshortcuts` carries the keys (J5).
- **Tokens**: cap `color.surface.raised` with a 1 px `color.border.strong` edge (`border.hairline`, decorative), `radius.xs`, padding `space.inset.xs` inline, at least square; key text `type.num.xs` in `color.text.secondary`; caps `space.inset.xs` apart (`docs/design/E05/E05-D02-rest.md` §6 J4, RULED 6438042003). (Replaces `font.mono`, which is not a shipped token.)
- **Storybook**: SingleKey, Combo, Range, InMenuRow, Remapped (J4, J5).
- **Tests**: unit, visual, axe.
- **As built (E05-S02)**: `names?` takes the keymap's name table from its owner (Ctrl and Shift have built-in words; any other key is read as written). Storybook adds PointerChord and Unbound.

### CMP-023 Progress Bar

- **Tier**: Atom · **Purpose**: determinate progress (recorder disk usage, replay load, TWAP slice progress).
- **Props**: `value: number` (0-100) · `label?` (or `aria-labelledby`; one is required) · `valueText?` (`aria-valuetext`, e.g. "page 3 of ~9") · `kind?: "progress"|"meter"` (default `progress`; `meter` for a gauge such as disk usage or a budget share) · `tone: "default"|"success"|"warning"|"danger"`.
- **States**: determinate only (an unknown total uses CMP-038, never an indeterminate loop); empty, partial and complete; the value text always shown, led by the tone's glyph on warning and danger.
- **A11y**: `role="progressbar"` `aria-valuenow/min/max`. `role="meter"` when `kind="meter"`; `aria-valuetext` from `valueText`; the value text and the glyph are `aria-hidden`; never a live region: the host announces the start, the completion or a failure once.
- **Tokens**: track `color.surface.hover`, 8 px from `space.inset.xs` padding, `radius.badge`; fill `color.action.primary.default` (default), `color.status.success.default`, `color.status.warning.strong`, `color.status.danger.default`; label `type.ui.label` and value `type.num.sm`, both `color.text.secondary`; `space.stack.xs`, `space.inset.xs`; a new value moves the fill over `motion.duration.normal` (motion-reduce: a step). (Replaces `color.track`, which is not a shipped token; `color.action.primary` read as `.default`.)
- **Storybook**: Default, WithLabel, AllTones, Meter, Unlabelled.
- **Tests**: unit, visual, axe.
- **Motion spec**: [E42-D04.md](../design/E42/E42-D04.md) (E42-D04 §13, after E08-D11 M7; `transform: scaleX` per sample over `normal`, steps under reduce; the "{n} %" text carries it — PROPOSED).

### CMP-024 Sparkline

- **Tier**: Atom · **Purpose**: tiny inline trend line (Deep Stats rolling-N, watchlist row mini-chart).
- **Props**: `data: number[]` · `width/height` · `colorBySign?: boolean`.
- **A11y**: `role="img"` + `aria-label` summarising trend ("up 3.2% over 20 bars"); underlying data reachable via the parent row's DOM-mirror table (not a standalone interactive control).
- **Tokens**: stroke `color.buy.default` (net up) / `color.sell.default` (net down) / `color.neutral.default` (flat) when `colorBySign`, otherwise `color.text.tertiary` (as E06-D02 §2.3); 1.5 px stroke (icon-grid weight), no fill, transparent background.
- **Storybook**: Uptrend, Downtrend, Flat (each with `colorBySign` on and off).
- **Tests**: unit, visual, axe.
- **As built (E05-S02)**: `floorRatio?` sets E22's y-range floor (at least ± `floorRatio` × the first value's magnitude); a series over 200 points keeps its latest 200; below two points the name is "no trend over 1 bar" or "no data". Storybook names the variants UptrendColorBySign, DowntrendColorBySign and FlatColorBySign and adds Empty, SinglePoint, Sized and InRow, plus a `perf`-tagged Perf story.

### CMP-025 Avatar Group / Stack

- **Tier**: Atom · **Purpose**: overlapping stack of account badges (trade-group summary).
- **Props**: `items: {label,color}[]` · `max: number` (overflow shows `+N` chip).
- **A11y**: `aria-label` listing all item labels even when visually truncated. The container is `role="img"` with `aria-label="{n} accounts: {every label}"`; avatars and the `+N` chip are `aria-hidden`.
- **Tokens**: CMP-013 Avatar (md) instances, each in a fixed `size.icon`-wide slot, so each avatar overlaps the next by the difference (8 px compact); 2 px `color.surface.canvas` cut-out ring; `+N` chip `color.neutral.subtle` + `type.num.sm` in `color.text.secondary`, `radius.badge`, height and min-width `size.control.height`, paddingX `space.inset.xs`. (Replaces `space.avatar.overlap`, which is not shipped.)
- **Storybook**: Default, Overflow.
- **Tests**: unit, visual, axe.
- **As built (E05-S02)**: `items: {label}[]`, with no `color` until an avatar palette is approved (§5 E2).

### CMP-026 EmptyState

- **Tier**: Atom (composed) · **Purpose**: designed empty/zero-data state (recorder-dependent emptiness per `14-screens-catalogue.md` §0.5.3).
- **Props**: `icon` · `title` · `description` · `cta?: {label,onClick}` · `link?: {label,href}` (one secondary link) · `headingLevel?` (default 3) · `variant: "no-data"|"recording-not-started"|"backfill-in-progress"|"filtered-empty"|"error"`. `variant="error"` renders CMP-027's panel form with `live="polite"`.
- **E08-D04**: `variant="backfill-in-progress"` (data-confidence `backfilling` state) pairs a determinate/indeterminate progress affordance with the description text (e.g. "Loading history — page 3 of ~9"); it is informational, not an error, and never uses `color.status.danger.*`. `variant="recording-not-started"` is confirmed unchanged for `SCR-151`.
- **States**: no-data, recording-not-started, backfill-in-progress, filtered-empty and error, each with its CTA; the sentence form (`docs/design/E09/E09-D09.md` §8): when the sole CTA is gated, `cta` is omitted and `description` carries the host's reason, with no button.
- **A11y**: heading semantics preserved (`h3` inside panel context), CTA is a real focusable button.
- **Tokens**: glyph CMP-019 `size="lg"` in `color.text.tertiary`; heading `type.ui.heading-sm` + `color.text.primary`; description `type.ui.body` + `color.text.secondary`; padding `space.inset.xl`; gaps `space.stack.sm` and `space.stack.md`; actions `space.inset.sm` apart. (Replaces `space.emptystate.*`, which is not a shipped token.)
- **Storybook**: AllVariants, SentenceForm.
- **Tests**: unit, visual, axe.
- **As built (E05-S02)**: `icon?` is optional over a glyph per variant (`info` for no-data, `pending` for recording-not-started and backfill-in-progress, `search` for filtered-empty); a `progress?` slot under the description takes the host's CMP-023, or CMP-038 when the total is unknown (backfill only); `variant="error"` admits no `link` or `progress` and maps `title`, `description` and `cta` to CMP-027's title, message and `retry`, with no heading when there is no description; the 480 px column cap (shared with CMP-027's panel) is written as 30rem because no layout token exists yet. Storybook adds Default, FocusVisible, RecordingNotStarted, BackfillInProgress, FilteredEmpty, ErrorVariant and LongText.
- **E08-D05 (A-D05-5)**: `actions?: {label, onClick, variant?, disabledReason?}[]` (one or two, in order) replaces `cta`, which stays a deprecated alias with its as-built look (CMP-027's secondary Retry on `error`; ignored beside `actions`); the first action is `primary` and the second `secondary` unless `variant` says otherwise (B03 draws SCR-102's list-region actions secondary). An action with `disabledReason` is T2 as CMP-079 hands it (`docs/design/E09/E09-D09.md` §2.2, rendering 2a; a sole gated action is the sentence form instead, §8): CMP-001's own T2, in one wrapper whether gated or not so the gate lifts in place, with the reason as a caption line under the button (`color.text.secondary`); a press says it again through a polite region rendered only while an action is gated. `variant="error"` adds `live?` (CMP-027's: default `polite`, E05-D02 H13; `assertive` is SCR-102's `role="alert"`) and `reference?` (a problem's `instance`: "Ref …" in `type.num.sm` and `color.text.secondary`, selectable, after the actions and outside the live region); with `actions` or `reference`, CMP-027's panel holds the glyph and the words and this block the actions and the Ref. Storybook adds FilteredEmptyNoMatch, FilteredEmptyStatusRule and ErrorWithTwoActions.

### CMP-027 ErrorState / InlineError

- **Tier**: Atom (composed) · **Purpose**: panel-level or field-level error surface (WS disconnect, order rejection).
- **Props**: `message` · `severity: "warning"|"error"` · `form?: "panel"|"inline"|"banner"` (default `panel`; `banner` for a rejected order's class line, `docs/design/E30/E30-D03.md` §4) · `title?` and `headingLevel?` (a heading over the message, e.g. an error summary's "Can't submit — 2 problems") · `items?: {label,href}[]` (an error summary's links, one per field, in document order) · `live?: "assertive"|"polite"|"off"` (default by severity) · `retry?: {label,onClick}` · `action?: {label,onClick}` · `details?: string` (collapsible technical detail).
- **States**: panel, inline and banner; error and warning; details closed and open; the error summary (`banner` with `title` and `items`, `docs/design/E30/E30-D02.md` D16).
- **A11y**: `role="alert"` for severity `error` (assertive live region), `role="status"` for `warning` (polite). `live` overrides it: `polite` for an in-panel load failure, `off` (no live role) when another node already announced it; the region is mounted with its host and its text inserted when the failure begins; the message is CandleViewer's own text (a mapped class line, `LegError.message` or the problem's `detail`), never the exchange's `ret_msg` or a wire payload (`docs/design/E30/E30-D03.md` D5; `docs/design/E30/E30-D04.md` C9); an error summary keeps `role="alert"` and its host moves focus to its heading (`tabindex="-1"`), whose links move focus to their fields (E30-D02 D16); `details` sit behind a "Technical details" disclosure (`aria-expanded`), selectable and never in the live region.
- **Tokens**: glyph CMP-019 `error` / `warning` in `color.status.danger.strong` / `color.status.warning.strong` (`error` is the registry's circle-x, the shape of the PROPOSED `icon/x-circle`, `docs/design/E30/E30-D04.md` §3.3); message `type.ui.body` + `color.text.primary` (`type.ui.body-strong` in the banner); the banner CMP-028's inline box in the error or warning tone (`color.status.danger.subtle` / `color.status.warning.subtle`, a 2 px `border.thick` start edge in `.strong`, `radius.card`, `space.inset.sm`, `space.inset.md`); a summary's heading `type.ui.heading-sm` over CMP-021 links, `space.stack.xs`; details `type.num.sm` + `color.text.secondary` on `color.surface.raised`, `radius.control`, `space.inset.sm`; inline gap `space.inset.xs`; the panel form lays out as CMP-026. (Replaces the bare `color.status.warning/danger`.)
- **Storybook**: Warning, Error, WithRetry, WithDetails, Inline, Polite, Banner, Summary.
- **Tests**: unit, visual, axe, live-region announcement test.
- **As built (E05-S02)**: the `error` glyph (circle-x) replaces the interim `danger`; `headingId?` gives the title heading an id and `tabindex="-1"`, so an error summary's host moves focus to it after a failed submit; the "Technical details" box carries a CMP-033 copy. Storybook names Error as ErrorSeverityStory and adds BannerWarning, InlineWithRetry, LiveOff and LongText.

### CMP-028 Callout / Banner (inline, non-global)

- **Tier**: Atom (composed) · **Purpose**: inline informational/warning block inside a panel or form (distinct from the global EnvBanner CMP-074).
- **Props**: `tone: "info"|"warning"|"danger"|"success"|"connection-reconnecting"|"connection-disconnected"` · `placement?: "inline"|"band"|"chart-strip"` (default `inline`; `band` is full width under the TopBar, in the shell's slot; `chart-strip` is the chart's third chrome row under E11-D02's status row, one message at a time under the SCR-030 precedence, each notice with its action and `Dismiss`, cleared when a new load or build starts, E12-D02 NC-1) · `live?: "assertive"|"polite"|"off"` (default by tone) · `icon?` (a registered glyph replacing the tone's) · `dismissible?` · `retry?: {label,onClick}` · `actions?: {label,onClick}[]` (after `retry`: Details, Flatten now, Set stop by hand) · `edge?: "solid"|"hatched"` (default `solid`; `hatched` only for the `unprotected` banner, `docs/design/E30/E30-D04.md` §2.3).
- **E08-D04 — `connection` severity variants** (used by `SCR-152`, data-confidence vocabulary `docs/design/E08/E08-D01.md`): `tone="connection-disconnected"` renders `role="alert"` (assertive) with `color.data-confidence.disconnected.indicator` accent (on `color.surface.*`; on the callout's fill the edge and the glyph bind `color.status.danger.strong`, Tokens, `docs/design/E17/E17-D02.md` C21) and a `[ Retry now ]` action; `tone="connection-reconnecting"` renders `role="status"` (polite) with `color.data-confidence.reconnecting.indicator` (on `color.surface.*`, by the same rule). Neither tone ever renders raw exchange error text — only the mapped state label plus an optional `details` string supplied by the caller (never a passthrough of the wire error). Flapping reconnect attempts within 5s collapse into a single "Connection unstable" announcement (no per-attempt re-announce).
- **States**: the six tones; inline and band; dismissible (a close button named "Dismiss {title}"); content at 0 ms; the `unprotected` banner (`tone="danger"`, `edge="hatched"`: a sustained `role="alert"` announced once per step, not dismissible while the stop is missing; it appears, persists and leaves in one frame, never animated; `docs/design/E30/E30-D04.md` §2.3).
- **A11y**: `role="status"` (info/success/connection-reconnecting) or `role="alert"` (warning/danger/connection-disconnected). `live` overrides the default (`off` renders no live role, for a banner whose announcement another region makes); each state entry is announced once; the region is mounted with its host and its text inserted when the state begins.
- **Tokens**: fill `color.status.{tone}.subtle`, a 2 px `border.thick` start edge and the glyph in `color.status.{tone}.strong`; `edge="hatched"` replaces that edge with a 4 px start edge hatched 45°, 1 px `color.status.danger.strong` lines at 6 px pitch on `color.status.danger.subtle` (PROPOSED `pattern.hatch.unprotected`, E30-D04 CR-5); the two connection tones on `color.status.danger.subtle` and `.strong` (the `color.data-confidence.*.indicator` accents measure 2.88:1 dark and 2.81:1 light on that fill and stay on `color.surface.*`); title `type.ui.body-strong` + `color.text.primary`; body `type.ui.body` + `color.text.secondary`; `radius.card` (inline), `space.inset.sm`, `space.inset.md`. (Replaces `color.callout.*`, which is not a shipped token.)
- **Storybook**: AllTones, Dismissible, ConnectionReconnecting, ConnectionDisconnected, Band, LivePolite, ProtectionPendingSolidEdge, ChartStrip, BarRebuildProgress.
- **Tests**: unit, visual, axe, live-region announcement test (assertive vs polite, flap-collapse).
- **As built (E05-S02)**: `edge` is not built: the hatched edge waits for the PROPOSED `pattern.hatch.unprotected` token and is deferred (#265 ruling 6), so every callout draws the solid 2 px edge and the Unprotected story is ProtectionPendingSolidEdge (the solid edge, not dismissible while the stop is missing); the flap-collapse ("Connection unstable") is owned by CMP-077, which holds the connection state, and the callout announces each state entry it is given once; both connection tones draw the `disconnected` glyph until E17-D02 CR-8's glyphs are registered; the "What changed" disclosure (E05-D02 §6 H15 (3)) is held and the dismissal is a cut until the E05-D03 motion recipe.
- **Motion spec**: [E08-D11.md](../design/E08/E08-D11.md) (E08-D11; the `connection-*` tones appear at 0 ms and dismiss with a `fast` opacity fade; fill and announcements are debounced on the clearing side only — PROPOSED) · [E42-D04.md](../design/E42/E42-D04.md) (E42-D04 §13; the tamper, maintenance and `fail_closed` banners appear and clear at 0 ms in both modes, never sliding or fading — PROPOSED).
- **Named pattern — Bar rebuild progress (E12-D09)**: in `placement="chart-strip"`: from 0 to 600 ms nothing but the toolbar's pending mark; from 600 ms to 2 s CMP-038 text; after 2 s CMP-023 determinate with a CMP-001 `Cancel` on the strip and the time left; total unknown: CMP-038 text with its explanation (E12-D02 D-5); `Esc` cancels last in E12-D02 D-11's chain; updates at most 4 Hz (PROPOSED), never per frame; the panel's polite region speaks once each at the build's start ("Building the chart as Volume 75 BTC bars. Escape cancels."), completion, cancel or refusal, never progress (E12-D02 §7; CMP-023 is never a live region); Cancel restores instantly from the series already on screen, and the parameter field shows the previous value with an explanation (E12-D02 D-6); `Cancel` is the strip's, never CMP-038's `onCancel`; tokens and stories are CMP-023's, CMP-038's and CMP-001 `ghost` `sm`'s; who may start a shared build stays the build contract's (G-2).

### CMP-029 Skeleton-Chart placeholder

- **Tier**: Atom · **Purpose**: chart-shaped loading placeholder distinct from generic Skeleton (candlestick silhouette).
- **Props**: `paneCount?: number`.
- **States**: shimmer (CMP-015's sweep, stopped at 5 s); static (under reduced motion, and after the stop).
- **A11y**: `aria-hidden`, parent panel carries `aria-busy="true"`. The host's CMP-038 words ("Loading 5,000 bars…") sit over it, outside the hidden node.
- **Tokens**: candle, wick and axis blocks `color.surface.hover` on `color.surface.canvas`; CMP-015's sweep. (Replaces `color.surface.skeleton`, which is not a shipped token.)
- **Storybook**: SinglePane, MultiPane, Static.
- **Tests**: unit, visual, reduced-motion snapshot.
- **As built (E05-S02)**: Storybook names SinglePane and MultiPane as Default and ThreePanes.

### CMP-030 Divider-Label ("section rule with caption")

- **Tier**: Atom · **Purpose**: labelled separator inside long forms (order ticket sections, rule condition groups).
- **Props**: `label: string`.
- **A11y**: renders as a non-interactive `role="separator"` with `aria-orientation="horizontal"`, named by `aria-labelledby` pointing at the visible label, which is a sibling of the separator (never a child: a separator's children are presentational); label is visible text, not just aria.
- **Tokens**: label `type.ui.caption` + `color.text.secondary`; gap `space.inset.sm`; rule = CMP-018 Divider (horizontal) in `color.border.subtle`.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.
- **As built (E05-S02)**: the separator's horizontal orientation is implicit (`role="separator"` defaults to horizontal), so no `aria-orientation` attribute is written.

### CMP-031 ColorSwatch / ThemeChip

- **Tier**: Atom · **Purpose**: pick/display a colour token (drawing tool colour, account colour, heatmap ramp preview).
- **Props**: `color` · `selected?` · `onSelect?` · `disabled?/disabledReason?`.
- **States**: default, hover (a 1 px `color.text.secondary` outline around the swatch; the colour never changes), focus-visible, disabled, disabled-with-reason (CMP-079: `aria-disabled` + `aria-describedby`, stays in the roving order but cannot be selected; the swatch keeps its true colour, because the colour is the value; a `locked` badge in the bottom-right corner, beside the `check` of a selected swatch; CMP-016 reason tooltip; superseded by E09-D09 §2.2 T2 (the E05-D02 boards PR restates it)); `selected` shows the `check` glyph (never colour alone).
- **A11y**: `role="radio"` inside a `radiogroup`; each radio is named by its ordinal, the hue word of the active theme and its token ("Slot 2, cyan — color.drawing.palette.2" — E13-D03 §13's grammar); the anatomy is E13-D03 §2's: a 16 × 16 `color.surface.canvas` tile with the hue drawn across it inside a 24 × 24 radio, the checked radio on `color.surface.selected` with a 2 px inner `color.border.selected` ring + a `color.text.primary` check (never hue alone); the focus ring sits outside the radio; a mixed selection shows no checked radio and the word "Mixed"; a value outside the closed set shows no checked radio and the word "Custom colour"; the T2 state (E09-D09 §2.2): the CMP-019 `lock` glyph ("Not available") leads the group name; `aria-disabled` on the group and each radio, never `disabled`; `aria-describedby` → the reason node, in the DOM at mount; the checked radio keeps its check (`color.text.tertiary` on the raised radio, no selected fill or ring; `aria-checked` kept); the role legs wrapped in CMP-079 RbacGate by the host; an arrow moves nothing and re-shows the reason (E14-D04 A3).
- **Tokens**: swatch fill = the closed set the host passes — for drawings `color.drawing.default` + `color.drawing.palette.1..8` (PROPOSED, E14-D04 CR-1 / E14-D08 TP-1 … TP-8; Penpot master: `color.drawing.default`); selected `check` glyph and the `locked` badge in `color.text.inverse` or `color.text.on-action`, whichever is ≥3:1 on that swatch; hover outline `color.text.secondary`; `radius.control`, `size.control.height` (swatch = 24×24 compact hit target), `size.icon` (check glyph), `size.icon.sm` (`locked` badge), `space.inset.xs` (picker gap), `opacity.disabled`, `color.focus.ring`.
- **Storybook**: Picker, StaticSwatch, Mixed, Custom, Disabled (T2).
- **Tests**: unit, visual, axe.
- **As built (E05-S02)**: two exports replace `selected?` / `onSelect?`: `ColorSwatch` (`color`, `label`, `decorative?`, `density?`), a static named `img` or `aria-hidden` beside text that names the colour, never focusable; and `ColorSwatchPicker` (`swatches: {value,label,color,glyphTone?,disabled?,disabledReason?}[]`, `value?`, `onChange?`, `disabled?` / `disabledReason?` for the whole picker, `density?`, named by `aria-label` or `aria-labelledby`), a `radiogroup` with roving focus. `glyphTone?: "inverse"|"on-action"` (default `inverse`) picks the check and lock colour per swatch. Storybook adds NoSelection, Hover, HoverSelected, FocusVisible, KeyboardNavigation, Disabled, SwatchLocked, PickerLocked, LockedSelected, StaticDecorative, AllStates and Wrapping.

### CMP-032 Rating/Confidence Dots ("estimated confidence indicator")

- **Tier**: Atom · **Purpose**: low/med/high confidence indicator for heuristic detectors (iceberg/stop-run/regime).
- **Props**: `level: "low"|"medium"|"high"` · `label?` (default "{Level} confidence"; an override must still name the level).
- **A11y**: never colour-only — filled-dot-count + text label always paired. The dots are a supplement to a numeric confidence value the consumer renders adjacent (or passes as `label`), never its replacement; the word low / medium / high is always present in the text (E25-D05 §9). The dots are `aria-hidden`; the visible label is the accessible text.
- **Tokens**: filled dot `color.status.info.default`, empty dot 1 px `color.text.tertiary` outline, dot 8 px = `space.inset.xs` padding, `radius.badge`, dot gap `space.inset.xs`, dots-to-label gap `space.inset.sm`, label `type.ui.caption` in `color.text.secondary`.
- **Storybook**: AllLevels.
- **Tests**: unit, visual, axe.
- **As built (E05-S02)**: a `label` without a level word gets ", {level} confidence" appended, and one that names a different level is replaced by "{Level} confidence" with a development warning. Storybook adds Low, Medium, High, NumericLabel and LongText.

### CMP-033 CopyButton

- **Tier**: Atom · **Purpose**: copy-to-clipboard affordance (API key display, audit record id, order id).
- **Props**: `value: string` · `label` (a11y name) · `onCopied?`.
- **States**: default, copied (`check` glyph in `color.status.success.default`, reverts to default after 2 s), failed (`error` glyph in `color.status.danger.default`, "Copy failed", reverts after 2 s), focus-visible, disabled.
- **A11y**: `aria-label`, announces "Copied" via a transient polite live region on success; the announcement never contains the copied value.
- **Tokens**: inherits CMP-002 IconButton `variant="ghost"`, `size="md"` (`color.text.secondary`, `color.text.primary`, `color.surface.hover`, `radius.control`, `size.control.height`, `size.icon`); copied glyph `color.status.success.default`.
- **Storybook**: Default, CopiedState.
- **Tests**: unit, visual, axe, clipboard-mock interaction test.
- **As built (E05-S02)**: the failed state is E20's (a refused write, or no clipboard API outside a secure context); the internal `useCopy` hook is exported (`copy(value)`, `status`, `message`) so hosts share the write and the 2 s status, which never speaks or stores the value (#265 ruling 9); the last press wins, and a repeat press empties the status so it is a new announcement; held-Enter repeats are ignored; `disabled?` and `density?` reach the nested CMP-002. Storybook adds Hover, FocusVisible, Failed, Disabled and LongText.

### CMP-034 MaskedValue ("secret reveal")

- **Tier**: Atom · **Purpose**: masked API key/secret display with reveal toggle (admin key screens).
- **Props**: `value: string` (a value the client holds in the current flow, never a stored secret: C-2.7) · `label: string` (what it is, e.g. "API secret"; names the group and the buttons) · `revealed?: boolean` (never `true` at mount) · `onToggleReveal?` · `autoHideMs?: number` (default 10000, re-masks automatically) · `copyable?: boolean` (default `false`; CMP-033).
- **States**: masked (default, at every mount: an 8-character mask whatever the value's length), revealed (only after a press of the toggle), expiring (the last 2 s, announced once), copied (CMP-033).
- **A11y**: toggle is CMP-002 IconButton with label "Show {label}"/"Hide {label}" ("Show secret"/"Hide secret" when `label` is "secret"); auto-hide timer announced via polite live region ~2s before hiding ("Secret will hide in 2 seconds") satisfying WCAG 2.2.1 (no silent unannounced timing change). A route change, window blur, the idle lock and sign-out re-mask; while masked the DOM holds the mask only, never the value; copy logs nothing and the live region never holds the value; the value never enters browser storage (`docs/design/E05/E05-D02-form-controls.md` §7, rules S1–S7; flagged for E05-X02; recovery codes are CMP-206's).
- **Tokens**: box `color.surface.raised` with a 1 px `color.border.default` hairline, `radius.control`, `size.control.height`, `space.inset.sm`; value `type.num.base` + `color.text.primary`; mask `color.text.secondary`; countdown (CMP-035) `type.ui.caption` + `color.text.tertiary`; buttons `space.inset.xs` apart. (Replaces `font.mono`.)
- **Storybook**: Masked, Revealed, AutoHideCountdown, Copyable.
- **Tests**: unit, visual, axe, timing-announcement test.
- **As built (E05-S02)**: `revealed` is a veto only: `false` masks, `true` never reveals (only a press of the toggle does); `onToggleReveal` is optional; `autoHideMs` is clamped to 3–30 s (30 s is G19's cap); an exported `maskAllValues()` re-masks the revealed value one microtask after its caller returns (committed synchronously there), for the host's route change, idle lock and sign-out. At most one value is revealed per page: pressing a second value's toggle masks the first in the same commit (the press-time handoff), so no frame paints two values. A timed re-mask that finds focus on Copy moves it to the toggle, never to `<body>`. `copyable` copies the value only while it is revealed, with no clipboard-clearing promise; the copied cell on `docs/design/E05/E05-D02-form-controls.md` CMP-034 (specimen board 05, `E05-D02-05-text-inputs`) is drawn masked, but copy works only while revealed. Residuals the component cannot close, recorded per #265 ruling 12 for E05-X02: clipboard history and sync, screen capture, React fiber props (readable by any page script, masked or not; the strict CSP of C-12.10 is the mitigation), accessibility-tree exposure while revealed, DOM-reading extensions, manual selection and heap retention.

### CMP-035 Countdown / Timer text

- **Tier**: Atom · **Purpose**: bar-close countdown, admin re-auth token expiry countdown, secret auto-hide.
- **Props**: `expiresAt: number` (epoch ms) · `format: "mm:ss"|"words"` · `onExpire?`. `format` adds `"hh:mm:ss"` and `"approx"` ("~4 s") (`docs/design/E05/E05-D02-rest.md` §6 J6, RULED 6438042003); `thresholds?: number[]` (seconds, default `[60, 10, 0]`) and `announce?: (s) => string`, the host's key for each threshold sentence (J7).
- **A11y**: `aria-live="off"` visually (updates every second would flood SR) with a discrete polite announcement only at defined thresholds (e.g. 60s, 10s, 0s) — documented pattern reused wherever a countdown appears, except countdowns in a grid column, which announce nothing (SCR-100 "Funding in", E08-D07 D22, §4.5). The visible digits are `aria-hidden="true"` and a visually hidden twin holds the words; each threshold speaks once, politely, and a crossing of several at once speaks the latest only (J7); a running clock that is not a deadline is the host's `role="timer"` region, outside this component (J6).
- **Tokens**: the digits `type.num.*` (`type.num.sm` by default), tabular, in the host sentence's colour; no colour change under the threshold. Under the threshold a CMP-019 `clock` glyph at `size.icon` in `color.status.warning.strong` leads the digits, `space.inset.xs` before them (J1 (c), PROPOSED, owner approval pending (#2701); until then the number alone carries the threshold). (Replaces `font.mono` and `color.text.warning`, which are not shipped tokens; J1.)
- **Storybook**: Default, UnderThreshold, Expired, HhMmSs, Approx, InGrid (J6).
- **Tests**: unit (threshold announcement logic), visual, axe.
- **As built (E05-S02)**: `size?` picks the digits' `type.num.*` step (default `sm`) and `now?` injects the clock (default `Date.now`) for tests and frozen stories; the `clock` glyph is not drawn while J1 (c) is pending. Storybook adds Words and Live.

### CMP-036 KeyValueRow

- **Tier**: Atom · **Purpose**: label/value pair row used across summary cards (order review, position detail).
- **Props**: `label` · `value: ReactNode` · `emphasis?: boolean` · `freshness?: DataConfidenceState` (renders CMP-239 FreshnessMarker beside `value` for live fields — see E08-D04). `layout?: "inline" | "stacked"` (default `inline`; `stacked` puts the value under its label for a narrow host or 150 % text) (`docs/design/E05/E05-D02-rest.md` §6 J8 (a), RULED 6438042003).
- **A11y**: renders as definition-list pair (`dt`/`dd`) semantics for screen-reader table-like traversal. Rows render `<div>` + `<dt>` + `<dd>` inside the host's `<dl>` (one per group; a single row is a `dl` of one), and an unavailable value "—" is read as the state word, never "dash" (J8 (a)); a live row's value keeps `color.text.primary` while disconnected or reconnecting and CMP-239's marker carries the state (J8 (c), a request to E08-D11 M25).
- **Tokens**: row min-height `size.row.height`, gap `space.inset.sm`, rows `space.stack.xs` apart; label `type.ui.label` + `color.text.secondary`; value `color.text.primary`, a number `type.num.base` (or the host's `type.num.*`), any other value `type.ui.body`; a missing value "—" in `color.text.secondary` (J8). (Replaces `space.row.*` and `font.size.body/label`, which are not shipped tokens.)
- **Storybook**: Default, Emphasis, LiveFreshness, Missing, Stale, Stacked (J8).
- **Tests**: unit, visual, axe.
- **As built (E05-S02)**: `freshness?` is a `ReactNode` slot (the host's CMP-239 marker) until CMP-239 exists, then the typed state (#265 ruling 10); `missingLabel?` (default "no value") is what "—" is read as. LiveFreshness waits for CMP-239; Storybook adds TextValue.
- **Motion spec**: [E08-D11.md](../design/E08/E08-D11.md) (E08-D11; a live field settles once through CMP-239; no value-change emphasis while stale).

### CMP-037 SwatchLegendItem

- **Tier**: Atom · **Purpose**: one legend row (colour + label + value), building block for CMP-113 HeatmapLegend and chart legends.
- **Props**: `color` (a semantic `color.*` token reference) · `label` · `value?` · `glyph?: string` (non-colour channel, e.g. `▲`/`▼`, `aria-hidden`; required when `color` encodes direction: buy/sell, up/down) · `shape?: "square" | "disc" | "pair"`; `pair` draws two `size.icon` swatches side by side (36 × 16 px with a `space.1` gap), each with the 1 px `color.border.strong` outline: a disc in `color` carrying `glyph` and a square of equal area in `color2?` carrying `glyph2?` (the ▲ / ▼ in `color.text.inverse`, `type.num.xs`).
- **A11y**: grouped under parent legend's `role="group"` with `aria-label`; each item is an `li` of the legend's `ul`; swatch and glyph are `aria-hidden`, so the label text carries the meaning.
- **Tokens**: swatch `size.icon` square, fill = the keyed data token (context-dependent `color.*`), 1 px `color.border.strong` outline; gap `space.inset.sm`; row min-height `size.row.height`; label `type.ui.caption` + `color.text.secondary`; value = CMP-020 NumericText `type.num.sm` + `color.text.primary`.
- **Storybook**: Default, WithoutValue, WithGlyph.
- **Tests**: unit, visual, axe.
- **As built (E05-S02)**: `format?` (any CMP-020 format but `pnl`, default `notional`) and `precision?` pass to the value's NumericText; `glyph` is required by type when `color` is a directional token.

### CMP-038 InlineSpinnerText ("Loading…" text+spinner pairing)

- **Tier**: Atom · **Purpose**: standard "loading X" composite used in buttons/rows/panels needing a text+spinner pairing without re-deriving CMP-014 usage each time.
- **Props**: `label: string` · `slowLabel?: string` (replaces `label` after 5 s) · `kind?: "load"|"export"|"replay"|"wait"|"submit"` (default `wait`) · `onCancel?` and `cancelLabel?` (a load, an export or a replay only; never an order submit).
- **States**: waiting; slow (after 5 s, the slow-path text, e.g. a slow boot's "Still loading… the server is slow to answer"); slow with Cancel. An order submit's slow path is its host's, never CMP-038's: the button reads `submit.awaiting` at 2 s and stays busy, with no spinner (CMP-107; `docs/design/E30/E30-D04.md` M1).
- **A11y**: single `role="status"` wrapping both icon and text (avoids double-announcement bug class). It is mounted empty with its host and its text inserted when the wait begins; the label is announced once and the slow text once, with no time cap and no elapsed counter.
- **Tokens**: CMP-014 `sm` (its arc `color.action.primary.default`); text `type.ui.body` + `color.text.secondary`; gap `space.inset.xs`; Cancel a CMP-001 `ghost` `sm`, `space.inset.sm` apart. (Replaces "inherits CMP-014/CMP-020".)
- **Storybook**: Default, SlowPath, SlowPathWithCancel.
- **Tests**: unit, visual, axe.
- **As built (E05-S02)**: the new `kind` prop types the Cancel rule: `onCancel` is accepted only for `load`, `export` and `replay`, and the Cancel shows only from the 5 s slow path; a new `label` or `kind` is a new wait and restarts the 5 s. Storybook adds SubmitNeverCancels and LongText.

### CMP-039 FocusRing (utility, non-visual export)

- **Tier**: Atom (utility) · **Purpose**: shared CSS/JS utility applying the standard focus-visible ring so every custom-drawn (canvas-adjacent) focusable surrogate element gets an identical ring — used by chart-engine DOM-mirror nodes (CMP-180+).
- **Props**: n/a (mixin/class).
- **A11y**: guarantees ≥3:1 contrast ring, 2px offset, `:focus-visible` only (not `:focus`) to avoid mouse-click ring flash.
- **Tokens**: `color.focus.ring` (colour) · `border.focus` (2 px width) · 2 px `outline-offset`; the ring follows the element's corner radius (CSS outline).
- **Storybook**: RingOnButton, RingOnCustomSurrogate.
- **Tests**: contrast-ratio automated check, visual.
- **As built (E05-S02)**: the hook is `useFocusRing({ inset? })` returning `{ className }`, `inset` drawing the ring inside the element (#265 ruling 11; D11's halo held). Storybook shows it on a plain sample as Normal and Inset; RingOnButton and RingOnCustomSurrogate are not separate stories.
- **On canvas-adjacent surrogates (`docs/design/E11/E11-D05.md` §9.1):** on a DOM-mirror surrogate aligned over canvas content (`05-accessibility-standard.md` §6.1; E06-D03; E11-D02 §7) the ring is **2 px `color.focus.ring` at 2 px offset with a 1 px pane-colour halo** (`color.surface.canvas`) between ring and content, so it stays visible over data ink of any luminance; the keyboard cursor column is E06-D03 D10's double ring (core ≥2 px plus halos), drawn on the canvas in `color.chart.focus.ring` with a `color.chart.pane.bg.default` halo (= `color.focus.ring` / `color.surface.canvas` — the engine-prefix aliases of `docs/design/E11/E11-D05.md` §4.1b, because the engine never reads CSS), and the chart draws **one** CMP-039 ring at the chart boundary, never two; measured on the canvas 7.05 / 6.30 / 18.32 and on raised chrome 6.66 / 5.86 / 17.30 (dark / light / high-contrast — the high-contrast ring is `palette.white` since #3896); in high-contrast the ring is ≥20 CIE76 ΔE from the primary and selected fills (`16` §2.1). Storybook adds RingOnCanvasData (the ring over candles in three themes; PROPOSED).

---

## 2. Molecules (CMP-040..069)

### CMP-040 FormField

- **Tier**: Molecule · **Purpose**: label + control + help/error text wrapper composing any atom input.
- **Props**: `label` · `htmlFor` · `labelId?` (generated when absent) · `required?` (sets `aria-required`; no asterisk) · `optional?` (shows "(optional)" in a form that mixes both) · `help?` · `error?` · `disabledReason?` (`docs/design/E09/E09-D09.md` §2.2 T2) · `layout?: "stacked"|"inline"` (default `stacked`) · `children`.
- **Variants**: stacked (the label over the control), inline (a label column the host sizes, then the control; it stacks below its fit width).
- **States**: default, invalid (the error line: the `danger` glyph and the message), disabled, disabled-with-reason (`docs/design/E09/E09-D09.md` §2.2 T2 through CMP-079: the label unchanged and the CMP-019 `lock` glyph leading the child's value inside its well, `docs/design/E30/E30-D04.md` §2.5; the reason sits under the control in `color.text.secondary`), read-only.
- **A11y**: `<label for>` association (a child that is not a native labelable element — a radiogroup, a slider, a grid, a div combobox — takes `aria-labelledby` → `labelId`), `aria-describedby` chains the error then the help id (while T2, the reason id alone), `aria-required`; the error node is in the DOM at mount, a polite live region announced once when blur validation shows or changes the message.
- **Tokens**: label `type.ui.label` + `color.text.secondary`, T2 included ("(optional)" `color.text.tertiary`); help and reason `type.ui.caption` + `color.text.secondary`; error `type.ui.caption` + `color.text.primary` with the `danger` glyph in `color.status.danger.strong`; `space.stack.xs` (label to control, control to lines, between lines), `space.inset.xs` (glyph to text), `space.field.gap` (inline column gap). (Replaces `space.field.*`, of which `space.field.gap` is the one shipped token.)
- **Storybook**: Default, WithError, WithHelp, Required, Optional, Inline, ReadOnly, DisabledWithReason.
- **Tests**: unit, visual, axe.
- **As built (E05-S03)**: `htmlFor` is optional (generated when absent; a field atom takes it over any id of its own, so the label always points at the control); adds `disabled?` (plain disabled), `labelWidth?` (the inline label column, a CSS length the host sizes) and `density?`. Plain disabled dims the label and the child (natively disabled, `opacity.disabled`); the help line keeps full contrast, unlike `docs/design/E05/E05-D02-form-controls.md`'s "label, field and lines", because it is text that often says why.

### CMP-041 Menu (dropdown/context menu)

- **Tier**: Molecule · **Purpose**: action list triggered by button/right-click (row actions, panel overflow menu).
- **Props**: `trigger: ReactNode` · `items: {label,icon?,shortcut?,onSelect,danger?,disabled?,disabledReason?,busy?,kind?: "action"|"radio"|"checkbox",checked?,group?: {id,label},description?}[]` · `contextTarget?` (opened by a right-click, `Shift+F10` or the Menu key) · `onOpenChange`.
- **Variants**: chip items (rows wrap, never truncate) · row items with a description · a trailing secondary zone (the pointer twin of `→`, no Tab stop) · content slots outside the `menu` subtree (an editor, a disclosure panel) — E12-D03 DS-1.
- **States**: items: default, hover, focus-visible (the CMP-039 ring drawn 2 px inside the item), active, checked (the `check` glyph), disabled (`opacity.disabled`; reached by the arrows, never activated), disabled-with-reason (`docs/design/E09/E09-D09.md` §2.2 T2 through CMP-079: the CMP-019 `lock`, the full label in `color.text.tertiary`, the reason as its second line), busy (CMP-014 leading the label, `aria-busy`; reached by the arrows, never activated; no `lock` and no reason: busy, not a gate, `docs/design/E29/E29-D02.md` §10.1), danger (the last group, after a separator); a submenu open.
- **A11y**: WAI-ARIA "Menu Button" pattern, arrow-key nav, type-ahead, `Esc` closes + returns focus, danger items get `aria-describedby` "destructive action" hint. `Enter` activates an item and closes the menu; `Space` toggles a checkbox or radio item and keeps it open; `Tab` closes every open menu and moves on from the trigger; disabled, busy and T2 items are reached by the arrows and never activated (a busy item takes `aria-busy`; a T2 item takes `aria-disabled` + `aria-describedby` → its second line and re-shows its reason with one polite announcement); a danger item's label ends with "…" when it opens CMP-044.
- **Tokens**: `color.surface.overlay`, `elevation.popover`, `radius.card`, a 1 px `color.border.default` edge and separators; items `size.row.height`, `space.inset.sm`, `space.inset.xs`, `type.ui.body` + `color.text.primary`; hover `color.surface.hover`, active `color.surface.selected`; second lines `type.ui.caption` + `color.text.secondary`; shortcuts `type.num.sm` + `color.text.tertiary`; a danger item's glyph `color.status.danger.strong`; the inset ring `color.focus.ring`; `opacity.disabled`. (Replaces `elevation.3`, a primitive.)
- **Storybook**: Default, WithShortcuts, ContextMenu(right-click), Nested submenu, Checkable, DisabledWithReason, Danger, Busy, ChipItems, WithDescription, TrailingZone, ContentSlot, Groups.
- **Tests**: unit, visual, axe, keyboard nav + Esc/return-focus.
- **As built (E05-S03)**: `trigger` is one button element (CMP-001 or CMP-002), not any `ReactNode`, onto which the menu composes `aria-haspopup="menu"`, `aria-expanded`, `aria-controls` and the toggle; it names the menu unless `aria-label` is given. `open` / `defaultOpen` / `onOpenChange` work controlled or not. Each item adds a required `id` (a stable key), takes `shortcut` as the keymap's display keys (`string[]`, a trailing CMP-022 and `aria-keyshortcuts`) and `opensConfirm?` (the label ends with "…"), and `group` is `{id,label?}`, consecutive items with one id forming a group. `now?` injects the type-ahead clock. An item that is both gated and disabled or busy shows one state, in the order gated > disabled > busy (a spec gap: the T2 reason is the one a user can act on). A pointer click activates like `Enter`, so it closes on a checkable item too; hover moves focus to any item, gated, disabled and busy ones included. Focus leaving the menu, or a press outside it, closes it (focus stays where it went); focus or a press in a layer opened above it does not. `Tab` with no tab stop beyond the trigger leaves focus on the trigger. Deviation: a T2 reason is re-announced through the menu's own polite `role="status"` region, rendered only when some item has a reason, not the shell's polite region; a host that owns its surface's one live region passes `announceReason?: (reason) => void` instead, and the menu renders no region and hands each re-shown reason to the host (CMP-049's row menus do, G12). An item with `items` (a `MenuSubmenuItem`, no `onSelect`) opens a submenu on `→`, Enter, Space or a click; `Space` opening it is a spec gap filled from APG. `contextTarget` is a `RefObject` to the target element, exclusive with `trigger`, and a context menu then requires `aria-label`; a right-click opens it at the pointer, the keys below the focused element, and focus returns to the focused control inside the target, else the pressed control, else the target; the target should mount with the menu (one swapped or mounted later is bound on the menu's next render). Submenu decisions: hover does not open a submenu and there is no safe triangle (the pointer on another parent item closes it); a gated submenu item never opens, and only a press (Enter, Space or a click), not `→`, re-shows its reason; a submenu opens on its first item, never on a checked radio item; no RTL mirroring of `→`/`←` or of the `right-start` placement yet (a known deferral, to be tracked in its own issue). Storybook adds ContextMenuKeyboard, Hover, FocusVisible, Active, PickOne, Disabled, Scrolling, EscTopmost, ContrastLight and ContrastHighContrast.
- **E08-D05 (A-D05-13)**: a host-opened menu: `anchor: Element | {x, y, width, height}` with the controlled `open` and `aria-label` both required, and neither `trigger` nor `contextTarget`, so a host opens it from its own `Shift+F10`, Menu key or right-click, below the anchor's start (the active option of a list whose focus stays in its input, or the pointer as a zero-size rect), read as it opens (keep an element anchor mounted while open, or pass its rect); focus returns to the element that held it when it opened, and any focus leaving it closes it. Items keep `disabledReason?` (E11-D03 D03-CR-1): T2 through CMP-079, the `lock` leading the label and the reason its second line, reached by the arrows, never activated. Storybook adds HostOpened.

### CMP-042 Tabs

- **Tier**: Molecule · **Purpose**: panel-local section switching (order ticket tabs: Market/Limit/Conditional; settings sections).
- **Props**: `tabs: {id,label,icon?}[]` · `value` · `onChange` · `orientation`. `activation?: "automatic" | "manual"` (default `automatic`; `manual` for a host whose switch re-shapes a form or costs a fetch) and a per-tab `disabledReason?`, rendered T2 through CMP-079 (`docs/design/E05/E05-D02-rest.md` §6 J9, RULED 6438042003).
- **A11y**: WAI-ARIA Tabs pattern (`role=tablist/tab/tabpanel`), arrow-key nav, `aria-selected`, lazy-mount tabpanels retain focus correctly on switch. One `tabpanel` per tab, `aria-labelledby` its tab, the inactive panels `hidden` or not mounted; a panel with nothing focusable takes `tabindex="0"`; a switch never moves focus off the tab (J10). A gated tab keeps `role="tab"` with `aria-disabled="true"` and `aria-describedby` → its reason; an arrow, `Home` or `End` landing on it selects nothing and announces nothing beyond its name, "unavailable" and the reason; `Enter` / `Space` on it re-show the reason with one polite announcement (`docs/design/E09/E09-D09.md` §9.3; J9).
- **Tokens**: selected tab a 2 px `color.border.selected` bottom rule (`border.thick`) with the label `color.text.primary`, no fill; unselected labels `color.text.secondary`; tab padding `space.inset.sm` inline (compact) / `space.inset.md` (comfortable), `type.ui.label`; a 1 px `color.border.default` line under the strip (J9). (Replaces `color.action.selected` and `space.tabs.*`.)
- **Storybook**: Default, Vertical, WithIcons, ManualActivation, GatedTab (J9).
- **Tests**: unit, visual, axe, keyboard.
- **As built (E05-S03)**: the tablist takes a required name, `aria-label` or `aria-labelledby`; panels come from `renderPanel(id)`, and only the selected tab's panel is mounted; adds `density?` (`data-density`). Storybook adds Hover, FocusVisible, Selected, Overflow, AllStates and a GatedContrastLight / GatedContrastHighContrast pair.

### CMP-043 Dialog (Modal)

- **Tier**: Molecule · **Purpose**: base modal wrapper (confirm dialogs, settings dialogs, indicator config).
- **Props**: `open` · `onOpenChange` · `title` · `description?` · `size: "sm"|"md"|"lg"` (default `md`; at most 420 / 560 / 960 px wide) · `role?: "dialog"|"alertdialog"` (default `dialog`) · `aria-label?` (the host's name, in place of the title's: an order confirm's names its environment, symbol and account, SCR-076's `confirm.name` "Confirm order - BTCUSDT - LIVE - Main", `docs/design/E30/E30-D03-handoff.md` Table 3) · `children` · `initialFocusRef?`.
- **States**: default; scrolls (the card at most 80 % of the viewport, its body scrolling between a fixed header and footer); busy (the primary action `loading`); reflow (at 200 % zoom the dialog fills the viewport).
- **A11y**: `role="dialog"` `aria-modal="true"` `aria-labelledby` (the title) or the host's `aria-label`, `aria-describedby`, focus-trap, `Esc` always cancels before the confirmed send (once it is sent, `Esc` closes the view and cancels nothing; a blocking dialog with no Cancel takes it as its one dismiss, the safe action, and a lock, which has none, ignores it: `docs/design/E09/E09-D06.md` §5), focus returns to trigger on close. Initial focus: `initialFocusRef`, else the first field, else the heading; an `alertdialog` focuses Cancel (with no Cancel, the least-destructive choice its host names through `initialFocusRef`) and has no close button, and a `dialog`'s close button is named "Close {title}"; a modal the system raises, not the user, is an `alertdialog`, the explicit modal alert of `05-accessibility-standard.md` §3.4 item 3; a press on the scrim cancels a `dialog` and does nothing for an `alertdialog`; the TopBar (the env band, CMP-211), the StatusBar and the shell's live regions stay outside the inert page; CMP-212's toasts render above the scrim, outside the trap and never over the footer, but stay inert, their timers paused: they are seen and announced through CMP-212's regions, and their actions are reached after the dialog closes (`docs/design/E40/E40-D02.md` §4.3); when the trigger has gone, focus returns to the host's named fallback.
- **Tokens**: card `color.surface.overlay`, `elevation.dialog`, `radius.dialog`, a 1 px `color.border.default` edge, `space.dialog.padding`, `space.stack.md`; title `type.ui.heading-sm`; description `type.ui.body` + `color.text.secondary`; the scrim black at `opacity.scrim` (`palette.black`; PROPOSED `color.surface.scrim`, `docs/design/E09/E09-D08.md` A-2), fading in over `motion.duration.normal` while the card appears at once. (Replaces `elevation.4` and `radius.lg`, which are primitives.)
- **Storybook**: Default, Small, Large, AlertDialog, Scrolling, Busy.
- **Tests**: unit, visual, axe, focus-trap/return test.
- **As built (E05-S03)**: `onOpenChange(open, reason)` adds the reason, `"escape"|"scrim"|"close"`, so a host with unsaved changes can ask first (H36); `footer?` is the CMP-001 row, Cancel first; `fallbackFocusRef?` takes focus back when the trigger has gone; `busy?` sets `aria-busy` on the card only, and the host sets its primary action's `loading` itself. A body that scrolls with no control in it becomes a Tab stop (`role="group"`, named like the card; WCAG 2.1.1), re-measured as the body resizes or its content changes. `initialFocusRef` on an element that is no tab stop (a wrapper around a CMP-001, which takes no ref) focuses its first tab stop. A Popover, Tooltip or nested Dialog inside portals into its layer; elements marked `data-cv-inert-exempt` stay outside the inert page, and so does a Popover or Tooltip anchored in one. Stacked dialogs count their holds on the inert page, so they close in any order; a node hidden before any dialog opened is never made visible. PROPOSED: the exit fades both scrim and card over the scrim's duration with no pointer events, as CMP-017's exit does (a cut under reduced motion); the entrance stays as specified. Storybook adds Reflow, ExemptRegion, EscTopmost, StackedDiscard, NoLayoutShift, ContrastLight and ContrastHighContrast.

### CMP-044 ConfirmDialog

- **Tier**: Molecule (composed on CMP-043) · **Purpose**: destructive/irreversible action gate (flatten all, cancel all, Demo→Live switch, delete API key). **E35-D02 —** the rule arming dialog SCR-085 is **not** a ConfirmDialog — it composes CMP-043 with its own footer (E35-D02 §4), the card appearing at once while the scrim fades (E35-D04 F-13, T-01); the rule disarm confirm is `variant="standard"` (CA-31).
- **Props**: `title` · `message` · `role?` (CMP-043's: `alertdialog` for a destructive confirm, `dialog` with the close button for an order confirm) · `restatement?` (what the confirm does, the dialog's description: the "What this does" group, or an order's environment sentence and full-intent line) · `legs?` (a fan-out's leg table) · `confirmLabel` (names the effect, never "Confirm") · `cancelLabel` · `variant: "standard"|"typed"|"hold"` · `typedConfirmValue?: string` (must match, e.g. symbol name; the object's own name, or a fixed word where the scope has none: `FLATTEN`, `LIVE`; it also gates a `hold` Confirm, whose hold starts only on a match) · `holdDurationMs?` (with discrete keyboard fallback per `05-accessibility-standard.md` §3.1.4; default 800 ms, PROPOSED `motion.duration.hold-confirm`, within a 300–2,000 ms setting) · `confirmDelayMs?` (default 400; Confirm ignores any activation before it) · `autoCancelMs?` (an inactivity time-out that cancels, never confirms, with the CMP-035 countdown; SCR-076 sets 20,000 from SCR-114's setting) · `initialFocus?: "cancel"` · `busy?` · `onConfirm` · `onCancel` · `rung?: 0|1|2|3|4` (`variant` derives from it: 0 hold, 1–2 standard, 3 typed, 4 typed where a token exists, else standard; passing both is an error) · `blastRadius?` (counts fetched before render) · `choices?: {id, label, consequence, disabledReason?}[]` (the two-choice block: none pre-selected, Esc = nothing changed; `disabledReason` is a key of the vocabulary in `docs/design/E09/E09-D09.md` §3, of a state vocabulary it registers, or one proposed to it until registered, rendered as the option's second line) · `acknowledge?` (the unknown-positions tick) · `stepUpState?: "none"|"grace"|"code"|"fresh"` · `auditCodes: string[]`.
- **States**: standard; typed (Confirm natively disabled until the summary has loaded and the field matches exactly: form validity, not a gate); hold (idle, holding with its ring and percentage, armed by a first key press); busy (after Confirm); partial failure (a CMP-027 inline error with Retry); a gated Confirm (CMP-079 RbacGate; `docs/design/E09/E09-D09.md` §2.2 T2: the CMP-019 `lock` leads the full label in `color.text.tertiary`, the fill becomes `color.surface.raised` with a `color.border.default` hairline, the host's reason sits under the footer in `color.text.secondary`, `aria-disabled` + `aria-describedby`; in place, when the session loses its leg while the dialog is open); counting down (`autoCancelMs`: the countdown, restarted by any key or pointer event inside the dialog); timed out (at 0:00 the dialog cancels, never confirms, and focus returns to the trigger).
- **A11y**: `variant="hold"` always ships a keyboard-operable discrete alternative (press-and-hold OR two sequential `Enter` presses within a visible countdown) — never a mouse-only/timing-only gate. `role="alertdialog"` for a destructive confirm, `role="dialog"` with the close button for an order confirm (`docs/design/E30/E30-D03.md` §2, A10); focus starts on Cancel; Confirm ignores an activation — `Enter`, `Space` or a pointer — in the first `confirmDelayMs` after the dialog opens (E30-D03 D3 (2)) and ignores key repeats; `Enter` in the typed field never confirms; the hold keyboard paths are a held `Enter` or two non-repeat presses of `Enter` or `Space` at least 250 ms apart within 5 s (the first arms and renames the button "Press again to …"; `Space` has no hold path), and `Esc` or blur disarms; under reduced motion the ring does not sweep and its percentage text carries the progress; an `autoCancelMs` countdown restarts on any key or pointer event inside the dialog, is `aria-live="off"`, is announced politely at 0:10 and 0:00, and cancels, never confirms (E30-D03 D3 (6)); a gated Confirm keeps focus and announces once. With `choices`, DOM and Tab order: the `role="radiogroup"` (labelled by the lead, `aria-required="true"`, none checked; Tab enters without selecting, Space selects, arrows move and select, except that a disabled-with-reason option keeps `role="radio"` and `aria-disabled`, the CMP-019 `lock` glyph leads its label, its reason is its second line by `aria-describedby` (`docs/design/E09/E09-D09.md` §2.2); the option is wrapped in CMP-079 RbacGate once its key is registered (until then its `disabledReason` carries the reason), and it is focused without being checked and never checked by Space) → `acknowledge` → Cancel → Confirm; Confirm stays natively disabled (form validity, as the typed state, not a gate) until a choice is made, then until `acknowledge` is ticked, then with `variant="typed"` until the value matches, and the visible hint names the first unmet input ("Choose an option first.", "Tick the acknowledgement first.", then the typed-confirm hint); a disabled choice never enables it; Enter in the group never confirms.
- **Tokens**: CMP-043's; Confirm a CMP-001 `danger` (`color.status.danger.default`, `color.text.on-action`), or the side's CMP-001 `buy` / `sell` for an order confirm (`color.buy.default` / `color.sell.default`, `color.text.inverse`; `docs/design/E30/E30-D03.md` §2); the restatement box (a "What this does" group) `color.surface.raised`, `radius.card`, `space.inset.md`; the hold ring `color.status.danger.default` over `color.border.strong`, its percentage `type.num.sm` + `color.text.secondary`; the countdown CMP-035 in `color.text.primary`, its number swapped once a second, no colour change (`docs/design/E30/E30-D04.md` M7). (Replaces `color.status.danger`, read as `.default`, and `elevation.4`, a primitive.)
- **Storybook**: Standard, TypedConfirm, HoldToConfirm(with keyboard fallback demo), Busy, PartialFailure, ConfirmGated, OrderConfirm, Rung1, Rung2, Rung3, Rung4, TwoChoice, TwoChoiceUnknown. **E35-D02 —** RuleDisarm.
- **Tests**: unit, visual, axe, keyboard-only path for hold-variant (explicit CI gate per a11y standard §3.1.4).
- **As built (E05-S03)**: no `initialFocus` prop: focus always starts on Cancel (H32). Adds `confirmVariant?: "danger"|"buy"|"sell"|"primary"` (default `danger`), `restatementLabel?` (default "What this does"), `typedInstruction?` (default "Type {token} to confirm"), `armedLabel?` (default "Press again to {effect}"), `summaryLoading?` (Confirm natively disabled until the summary loads), `failure?: {message, retry?, details?}` (the partial-failure state), `confirmDisabledReason?` (the gated Confirm), `size?`, `fallbackFocusRef?` and an injected `now?` clock. `onConfirm(meta)` carries `{variant, gate, elapsedMs}`, where `gate` is `click`, `typed`, `pointer-hold`, `key-hold` or `double-press` (the audit hook under Observability); `onCancel(reason)` adds `cancel` and `timeout` to CMP-043's reasons. Storybook ships Standard, Guard, Typed, TypedMatch, Hold, HoldReleasedEarly, Holding, Armed, HoldKeyboard (the keyboard path), HoldReducedMotion, Busy, PartialFailure, ConfirmGated, OrderConfirm, CountingDown, TimedOut, LongText and a contrast pair; no RuleDisarm story yet. The gate × state matrix for E05-X02 is in `docs/plan/qa/E05-S03-qa-handoff.md`.
- **Motion spec**: [E42-D04.md](../design/E42/E42-D04.md) (E42-D04 §13, after E09-D08 D2; the scrim fades over `normal`, the card is a cut focused in frame 0, the exit `fast` — PROPOSED).

### CMP-045 Toast / Notification

- **Tier**: Molecule · **Purpose**: transient system feedback (order acked, rule fired, connection restored).
- **Props**: `title` · `description?` · `kicker?` (the tone's word and the kind) · `tone` (`info`|`success`|`warning`|`danger`) · `action?: {label,onClick}` · `durationMs?` · `persistent?` · `politeness?: "polite"|"assertive"` · `dismissible?`. By default a toast with an `action`, a `danger` tone or an error is persistent, and any other follows the user's toast duration (5 / 10 / 20 s / until dismissed).
- **States**: the four tones; timed and persistent; focused (every timer in the stack paused); a gated action (CMP-079 RbacGate; `docs/design/E09/E09-D09.md` §2.2 T2: `aria-disabled`, the CMP-019 `lock` leading the full label in `color.text.tertiary`, a filled action's fill `color.surface.raised` with a `color.border.default` hairline, and one reason line under the actions, in `color.text.secondary`, that every gated action's `aria-describedby` points at; `Enter` or `Space` on it re-shows the line with one polite announcement); an Undo and its outcome line.
- **A11y**: a toast is never its own live region: its sentence is written once into CMP-212's polite region, or its assertive region for `tone="danger"`, and `politeness` overrides; never auto-dismisses content the user hasn't had a chance to perceive — pauses on hover/focus, and provides a persistent-log fallback (Notification Center) so nothing is lost if missed (WCAG 2.2.1 no timing loss of info). A toast never takes focus; `Esc` on a focused toast dismisses it; an order cancel offers no Undo.
- **Tokens**: `color.surface.overlay`, `elevation.popover`, `radius.card`, `space.inset.md`, `space.stack.sm`; a 2 px `border.thick` start edge in `color.status.{tone}.default` and the glyph in `color.status.{tone}.strong`; kicker `type.ui.caption` + `color.text.secondary`, title `type.ui.body-strong` + `color.text.primary`, body `type.ui.body` + `color.text.secondary`, meta `type.num.sm` + `color.text.tertiary`; 360 px wide. (Replaces `elevation.3`, a primitive, and the bare `color.status.*`.)
- **Storybook**: AllTones, WithAction, PersistentLogLink, Persistent, Focused, ActionGated, Undo.
- **Tests**: unit, visual, axe, live-region announcement test, pause-on-hover/focus test.
- **As built (E05-S03)**: two parts. `Toast` renders one toast: `actions?: {label, onClick, variant?, loading?, disabledReason?}[]` replaces `action?`, with gated actions sharing one reason line per distinct reason; `undo?: {label?, onUndo, outcome}` with `undoClosed?`; `meta?`; `onDismiss(reason)` and `onRefuse(reason)`. `ToastRegion` owns timing and speech: `toasts` (each with `id`, `durationMs?: number | null`, `persistent?`, `error?`, `politeness?`), `onDismiss(id, reason)`, an injected `announce(politeness, text, key)` into the shell's announcer, `durationMs?` (default 5,000 ms; `null` is until dismissed) and `label?` (default "Notifications", a region landmark that exists only while a toast shows). `error?` makes a non-`danger` toast persistent and assertive. A pause keeps the time left and resumes from it; a timer fires once. An Undo toast never times out (`persistent: false` does not change that); only its Undo window follows the duration, then the outcome line replaces Undo and is spoken once. Under a modal layer the stack stays visible, inert through the layer's inert-outside pass. A gated action mirrors CMP-001's gated markup with the lock leading the label; the catalogued fill and label colours for a gated filled action are not yet built (a CMP-001 follow-up). The storm summary, count and "Focus toasts" stay with CMP-212. Storybook adds Default, Success, UndoOutcome, LongText, Region, RegionUntilDismissed and RegionUnderModal.
- **E40-D02 (#1013; [E40-D02.md](../design/E40/E40-D02.md) §7.4; owner approval pending)**: two deltas to the built toast, which wins everywhere else (`kicker`, `persistent`, `politeness`, the `border.thick` edge, the 360 px width): (1) a fired user alert is spoken in CMP-212's polite region at every severity, `tone="danger"` included: the host passes `politeness: "polite"` (AM-11, UA-A), so a user alert never takes the assertive region that order rejects and risk events keep; (2) no countdown bar, ever (X-17; motion over 5 s with no pause control for a keyboard user).

### CMP-046 Drawer (side panel)

- **Tier**: Molecule · **Purpose**: slide-in panel (footprint cell detail, rule node inspector, symbol info).
- **Props**: `open` · `onOpenChange` · `side: "left"|"right"` · `title` · `modal?: boolean` (default `true`; `false` beside a live chart) · `initialFocusRef?` · `aria-label?` (as CMP-043's: SCR-077's `drawer.name` "Order rejected - BTCUSDT - LIVE - Main", `docs/design/E30/E30-D03-handoff.md` Table 3) · `children`; the width is host data (480 px for detail, 420 / 480 px by density for an order's rejection drawer, 320 / 360 px for docked inspectors; full width at a viewport of 720 CSS px or less, except a docked inspector, which keeps its width and wraps, then takes its host's narrow mode: `docs/design/E13/E13-D02.md` §11.7).
- **States**: default; loading (CMP-015 rows, `aria-busy`); narrow (full width; a docked inspector's is its host's narrow mode).
- **A11y**: same contract as Dialog (focus-trap, `Esc`, return focus) but non-modal option available (`modal?: boolean`) for drawers meant to coexist with chart interaction. On open, focus moves to `initialFocusRef`, else the heading (`tabindex="-1"`). A non-modal drawer is a `role="dialog"` without `aria-modal`: Tab moves through it and on to the page after its opener; focus returns to the opener, or to the host's fallback when the opener has gone; a modal drawer's scrim leaves the TopBar, the StatusBar and the shell's live regions outside the inert page, and CMP-212's toasts are as under CMP-043 (above the scrim, inert).
- **Tokens**: `color.surface.overlay`; `elevation.dialog` (modal, over the scrim) or `elevation.popover` (non-modal); a 1 px `color.border.default` inner edge and header rule; `space.panel.padding`, `space.stack.md`; title `type.ui.heading-sm`; it slides over `motion.duration.normal` with `motion.easing.decelerate` (closing `accelerate`; a docked drawer that reflows its host arrives in one frame; motion-reduce: instant). (Replaces `elevation.3`, a primitive, and `motion.slide`, which is not a shipped token.)
- **Storybook**: Modal, NonModal, LeftSide, RightSide, Loading, Narrow.
- **Tests**: unit, visual, axe, focus-trap test.
- **As built (E05-S03)**: `width?` is the host's width in CSS px (default 480); `busy?` sets `aria-busy` on the body while the host renders its CMP-015 rows; adds `footer?`, `fallbackFocusRef?`, `id?` and `className?`; `onOpenChange(open, reason)` adds the reason, `"escape"|"scrim"|"close"`, as CMP-043's. Storybook adds HostWidthAndName, LongText, FallbackReturn and a contrast pair.
- **E40-D02 (#1013; [E40-D02.md](../design/E40/E40-D02.md) §7.4; owner approval pending)**: the `alert-detail` drawer (SCR-092): non-modal (`modal: false`, `role="dialog"`), the built default width of 480 px, sliding over the right edge of the workspace and the docked CMP-209 rail at `elevation.popover`, never a wider dock, so the chart never lays out again; focus moves to its heading on a user action and returns to the opener, or to the bell when the opener has gone.
- **Motion spec**: [E42-D04.md](../design/E42/E42-D04.md) (E42-D04 §13, after E40-D02 §8; `translateX` over `normal`, focus placed in frame 0, instant under reduce — PROPOSED).

### CMP-047 DatePicker / DateRangePicker

- **Tier**: Molecule · **Purpose**: date/time range selection (replay session range, journal filter, recorder retention override).
- **Props**: `value` · `onChange` · `mode: "single"|"range"` · `min?/max?` · `rangeCaption?` (the host's sentence naming `min`–`max`) · `withTime?: boolean` (an `HH:MM` field beside each date) · `formatHint?` (default "YYYY-MM-DD") · `timezone: "UTC"` (locked, 24/7 market — no user-timezone ambiguity per research digest) · `invalid?` · `disabled?` · `disabledReason?` · `readOnly?`.
- **Variants**: single, range (Start and End fields, one calendar button); each with or without time.
- **States**: field: default, hover, focus-visible, invalid, disabled, disabled-with-reason (`docs/design/E09/E09-D09.md` §2.2 T2 through CMP-079: the CMP-019 `lock` leads each field's value inside its well, the fields `readonly`, the calendar button `aria-disabled`, the dialog never opens), read-only, open; days: today (a 1 px `color.text.tertiary` ring), selected and range ends (`color.action.selected` with a 2 px `color.border.selected` outline), in range (`color.surface.selected`), out of range (`aria-disabled`, at `opacity.disabled`, the caption naming the range).
- **A11y**: WAI-ARIA "Date Picker Dialog" pattern, full keyboard grid navigation (arrows move by day, `PageUp/Down` by month), live region announces selected range. The dialog is modal: focus moves to the selected day (else today, else the first allowed day) and returns to the calendar button on close; `Home`/`End` move to the week's first and last day, `Shift+PageUp/Down` by year; weeks start on Monday; every value is UTC.
- **Tokens**: the CMP-007 well for each field (a "UTC" suffix, the calendar button flush at its end); dialog `color.surface.overlay`, `elevation.popover`, `radius.card`, `space.inset.md`; month `type.ui.heading-sm`; weekdays `type.ui.caption` + `color.text.tertiary`; day cells `size.control.height`, `type.num.base` + `color.text.primary`; selected `color.action.selected` + `color.border.selected` (`border.thick`) + `color.text.primary`; in range `color.surface.selected`; caption `type.ui.caption` + `color.text.secondary`.
- **Storybook**: Single, Range, WithMinMax, WithTime, Invalid, DisabledWithReason.
- **Tests**: unit, visual, axe, keyboard grid nav.
- **As built (E05-S03)**: `mode` is two exports: `DatePicker` (single, `value: string | null`, ISO `YYYY-MM-DD`, never a `Date`) and `DateRangePicker` (`value: {start, end, startTime?, endTime?}`, ISO strings); `timezone` is not a prop, every value being UTC. `withTime` adds an `HH:MM` (24-hour UTC) well after each date, typed only (`H:MM` or `HH:MM`, parsed on blur), with the single form's own `time` / `onTimeChange`; the calendar button then ends the last well, so the Tab order is date, time, button. The range's Start and End (`startLabel` / `endLabel`) are a `group` named by CMP-040's label; each typed field commits on its own (a reversed range is the host's check); in the calendar the first pick sets the start, the second the end and closes, a second pick before the start replaces it, and Esc drops a pending start. The band previews to the pointer's day, else the focused day, while the end is pending. The two sentences: "Start {start}. Choose the end date." in the dialog, then "{start} to {end}, {n} days." from the group after the dialog closes. The fields wrap, so End stacks under Start when narrow. Typed text is parsed on blur or `Enter` and never clamped: unparsable or out-of-range text keeps its words, is invalid with a typed error ("Enter a date as {formatHint}." or the range caption), and never reaches `onChange`. The format hint line is always drawn under the field (an empty `formatHint` drops it and the placeholder). Without `rangeCaption` a caption is composed from `min`/`max`; it is spoken on every press of an out-of-range day. The dialog opens on the selected day, else today, else the nearest allowed day (today clamped into `min`–`max`, so `max` when today is past it). The modal CMP-017 Popover is anchored to the calendar button, not the whole field, since Popover's `anchor` is the trigger itself. A read-only field's calendar button is natively disabled; `aria-disabled` is for T2 only. Storybook adds Empty, Hover, Focused, Open, KeyboardPick, TypedError, Disabled, ReadOnly, AllStates, ContrastLight and ContrastHighContrast; `Molecules/DateRangePicker` holds Range, RangeOpen, KeyboardRange, WithTime, Narrow and the range states.

### CMP-048 Combobox / AutoComplete

- **Tier**: Molecule · **Purpose**: base for SymbolSearchInput (CMP-160) and any type-ahead selector.
- **Props**: `value` · `onChange` · `options[]|asyncSearch(query, signal)` (`signal` aborts a superseded search) · `loading?` · `placeholder?` · `noResultsText: string` (the host's sentence; required with `asyncSearch`) · `searchFailedText: string` (the host's sentence; required with `asyncSearch`) · `invalid?` · `disabled?` · `disabledReason?`.
- **States**: default, hover, focus-visible, open, loading (busy: a "Searching…" status row, the listbox `aria-busy`), no results (availability: the host's sentence), search failed (the `danger` glyph and the host's sentence), invalid, disabled, disabled-with-reason (`docs/design/E09/E09-D09.md` §2.2 T2 through CMP-079 and CMP-040: the CMP-019 `lock` leads the value inside the well).
- **A11y**: WAI-ARIA Combobox pattern, `aria-activedescendant`, `aria-expanded`, results count announced via polite live region on each query update (debounced to avoid flooding): once per settled query, 500 ms after the last keystroke; status rows are not options; `Esc` closes the listbox and keeps the text.
- **Tokens**: input the CMP-007 well; listbox `color.surface.overlay`, `elevation.popover`, `radius.card`, at most 10 rows; options as CMP-009's, the matched text `type.ui.body-strong`; status rows `type.ui.body` + `color.text.secondary`. (Replaces `elevation.2`.)
- **Storybook**: Sync, AsyncLoading, NoResults, SearchFailed, DisabledWithReason.
- **Tests**: unit, visual, axe, keyboard + debounced-announcement test.
- **As built (E05-S03)**: `onChange(value, option?)` passes the chosen option; options are `{value, label, disabledReason?}`, and a gated option is reached but never chosen; `asyncSearch(query, signal)` takes an `AbortSignal` (a stale request is aborted) and needs `searchFailedText` beside `noResultsText`; a source is local `options` or `asyncSearch`, never both; adds `prefix?` (a CMP-007 well prefix) and `aria-label?` / `aria-labelledby?`. The listbox portals into the topmost layer, so inside a Dialog `Esc` closes the list first.
- **E08-D05 (A-D05-6)**: `PageUp`/`PageDown` move the active option by the visible rows (the list's height over a row's; 10 when nothing is laid out) within an open list: no wrap, and `PageUp` never back to the text. `settleMs?` (default 500, E05-D02's debounce; CMP-160 passes 300) sets the settle and the count's rest, and `animated={false}` drops the popup's fade (default `true`; E08-D05's hand-off, Table 4: none animated; a cut under reduced motion either way). `onKeyDown?(event, active)` runs first on every key outside an IME composition, with the active option, and its `preventDefault()` skips the combobox's own handling, so a host binds `Shift+Enter`, `Shift+F10`, the Menu key or its own `Esc`. Storybook adds Paging and SettleUnanimated.
- **As built (E08-S09)**: CMP-160 is CMP-048's sibling, not built on it: it keeps the well, the `search` prefix, T2 and the refused keys, and draws CMP-213 in place (CMP-160's as-built).

### CMP-049 Table (base data table)

- **Tier**: Molecule · **Purpose**: base virtualized sortable table underlying PositionsGrid (CMP-107), OrdersTable, AuditLogTable, JournalTable.
- **Props**: `columns: ColumnDef[]` · `rows: T[]` · `sort?/onSortChange` · `rowKey` · `onRowSelect?` (renders the select column; the table becomes a grid) · `virtualized?: boolean` (default true above 50 rows) · `emptyState?: ReactNode` · `grid?: boolean` (the APG grid pattern; default `false`) · `sortPending?: string` (the column whose requested sort waits on rows the consumer is still reading; its header is busy) · `caption: string` · `loading?: boolean` · `error?: {message, onRetry}` · `virtualizeAbove?: number` (default 50; SCR-100 passes 60).
- **Variants**: table (static cells, the APG Table pattern: no control in a body row; default), grid (interactive cells, the APG Grid pattern; implied whenever a body column is interactive — `onRowSelect`'s select column, an actions column, an inline control — and forced by `grid` for a static table).
- **States**: populated; loading (the header row kept, CMP-015 skeleton rows, `aria-busy`); empty and filtered-empty (the header row kept, CMP-026 across every column); error (the header row kept, CMP-027 with Retry, announced politely); sorting (the `sortPending` header busy, never T2); reflow (stacked below the fit width and at 200 % zoom, one row element per record); rows: hover (`color.surface.hover`), selected (`color.action.selected` with the checked box), focused (the CMP-039 ring); a gated row action is `docs/design/E09/E09-D09.md` §2.2 T2 through CMP-079 (the CMP-019 `lock` leads a row-menu item, whose second line is the reason, or badges an inline IconButton, 2b).
- **A11y**: semantic `<table>` with `scope` on headers even when virtualized (windowed rendering keeps ARIA table role structure via `role="rowgroup"/"row"/"cell"` with `aria-rowindex`/`aria-colindex` when native table elements aren't feasible in the virtualization window); sortable headers are buttons with `aria-sort`; with `grid`, `role="grid"` with `row`/`columnheader`/`gridcell`, one Tab stop and a roving tabindex (`05-accessibility-standard.md` §3.4 item 2), `↑`/`↓` by row including the header row, `←`/`→` by cell, `Enter` activates the focused cell's control; the header button of the `sortPending` column keeps its label and its `aria-sort`, a spinner replaces its sort glyph, it takes `aria-busy="true"` and stays focusable (with `grid`, arrow-reachable), and pressing it again changes nothing (`docs/design/E09/E09-D09.md` §9.1, loading). The header row is sticky and a focused cell (grid mode) scrolls below it (`scroll-margin-top`); table mode's Tab stops are the scroll region (focusable, named by the caption) and the header buttons, and its body rows carry no controls; an interactive body column makes the table a grid (one Tab stop, `05-accessibility-standard.md` §3.4 item 2): selection is a CMP-005 column with a mixed select-all, `aria-selected` and `Space`; `Shift+F10` opens the row menu, whose T2 items stay arrow-reachable; one polite live region for sort, filter, selection and load results. With `grid`, the grid also carries `aria-rowcount` (rows + header) with absolute `aria-rowindex`, `aria-colcount`, `aria-current` on the active row, and merged cells by `aria-colspan`. A sortable `columnheader` whose sort is gated may be T2 (E08-D07 §6.6): `aria-disabled`, a CMP-019 `lock` glyph before the label, `aria-describedby` to a host note. With `grid`, a T2 key press on a cell (`Enter`, `Space`, `Alt+↑/↓`, `Del`) changes nothing and opens a CMP-016 echo of its reason on that cell (E08-D07 §6.6).
- **Tokens**: header `color.surface.hover` + `type.ui.label` + `color.text.primary`, a 1 px `color.border.subtle` rule; sort glyph `size.icon` + `color.text.tertiary`; rows `size.row.height`, odd `color.surface.canvas`, even `color.surface.raised`, hover `color.surface.hover`, selected `color.action.selected`; cells `space.inset.sm`, `type.ui.body` + `color.text.primary` or `color.text.secondary`, numbers `type.num.base` end-aligned (numeric columns); caption `type.ui.label` + `color.text.secondary`. (Replaces `font.mono`.)
- **Storybook**: Default, Sortable, Virtualized(10k rows), Empty, Selectable, Grid, SortPending, Loading, Error, FilteredEmpty, Reflow, MergedCell, SortUnavailable.
- **Tests**: unit, visual, axe, keyboard header-sort + row navigation (`↑/↓`), performance test (scroll 10k rows @60fps).
- **As built (E05-S03)**: no `virtualized?` or `virtualizeAbove?` prop, no Virtualized(10k rows) story and no 10k-row 60 fps test: #266 puts virtualised rendering out of scope ("v0 Table renders a bounded row count"). v0 renders every row with a bound of 200, above which it warns in development; the epic that first needs 10k+ rows adds virtualisation. Columns are declarative (`id`, `header`, `cell`, `sortable?`, `numeric?: NumericFormat` through CMP-020 with `precision?`); `rowKey` is a function; the consumer sorts `rows`; `captionHidden?`, `loadingText?` and `density?` are added; the scroll region takes its Tab stop only while it scrolls; the error panel is not live and the table's one polite region says it.
- **As built (E05-S03), stories and live region**: slice 15 ships Default, Sortable, SortPending, Loading, Empty, FilteredEmpty and Error (plus LongText, Scrolling, CaptionHidden and Compact); slice 16 ships Reflow (compact, root font size 200 % on the 1280 × 800 frame and at 640 px: stacked, no sideways overflow, every value present) and the `perf`-tagged Perf200Rows (a 200-row first render within one frame); slice 17 ships Selectable, Grid and RowActions; MergedCell and SortUnavailable stay deferred (merged cells and a T2 sort header are outside #266's slice 17). The reflow threshold is the sum of the columns' `minWidthEm?` (default 8) at the table's font size, watched by a ResizeObserver that sets `data-layout="stacked"`; stacked rows keep explicit table roles, the first cell is the heading line and the others show their header as a visible label hidden from AT. The polite line clears as a load, a pending sort or a Retry starts, so an identical result (the same row count after a reload, the same failure after a Retry) is said again. The default empty title "No rows to show" is PROPOSED copy for E05-D05 review.
- **As built (E05-S03), grid mode, selection and row actions (slice 17)**: `grid?` (default `false`) forces grid mode, which any interactive column implies (`onRowSelect`'s select column, a `rowActions?: (row) => MenuItem[]` actions column, or a text column with `interactive: true`). Selection is controlled: `selected?: ReadonlySet<string>` of `rowKey`s with `onRowSelect(next)`, called with the whole next set (not a row). `rowLabel?` names the row in "Select {row}" and "Actions for {row}" (default: the first column's text or number, else the key). One Tab stop remembers the last focused cell (at first the first body cell); a cell's built-in control (the select box, a sort button, the actions button) takes focus in the cell's place, so `Enter`/`Space` act on it natively; an `interactive` cell takes focus itself, its controls leave the Tab order, `Enter` or `F2` moves into the first of them and `Esc` back. `↑`/`↓` on the actions button move rows instead of opening its menu. Arrows stop at the edges (no wrap); Ctrl+Home / Ctrl+End go to the header's first cell and the last row's last cell; Page Up / Page Down move by the rows that fit the visible region less the header (10 when nothing is laid out). Each row's actions button is its own CMP-041 menu button; `Shift+F10` / the Menu key and a right-click on the body open one shared context menu for the focused row (the CMP-041 point/element anchor), so `Esc` returns focus to the cell or button it opened from. A press on a cell makes it the remembered cell before the `contextmenu`, so a right-click opens the pressed row's menu; a press on the select or actions cell's padding focuses its control. `rowActions(row)` is called only while that row's menu (or the context menu) is open. The table keeps one live region: the selection count ("2 selected", counting only selected keys among `rows`; nothing while loading, empty or in error) goes through its polite line once per new count, and the row menus pass CMP-041's `announceReason`, so a re-shown T2 reason is said by that line once per press and no menu renders a region of its own. Not built: `aria-current` on the active row, `aria-colindex`, a T2 sort header and merged cells. Stacked, a grid degrades to a table: explicit table roles, no roving `tabindex`, every control its own Tab stop in reading order (the heading line is the first data cell, the select and actions cells their own lines). The select and actions columns add 3 em each to the reflow threshold. The icon is `more-horizontal` per D02F G21 (the registry describes `more-vertical` as the row-menu glyph: a design question).

### CMP-050 Card

- **Tier**: Molecule · **Purpose**: bordered content block (summary cards, dashboard tiles).
- **Props**: `title?` · `actions?: ReactNode` · `padding` · `children`. `surface?: "elevated" | "flat"` (default `elevated`), `headingLevel?: 2 | 3 | 4 | 0` (0 renders the title as plain text inside a listbox option) and `region?: boolean` (a landmark tile labelled by its heading); actions sit in the header's trailing slot (`docs/design/E05/E05-D02-rest.md` §6 J11, RULED 6438042003).
- **A11y**: heading semantics if `title` present. The title is a heading at `headingLevel`; with `region` the card is a `region` `aria-labelledby` its heading; inside a listbox option the title is plain text and the option owns the states (J11). A card is never clickable as a whole; its gated actions take T2 themselves.
- **Tokens**: `color.surface.raised`, `radius.card`; `elevated` lifts by `elevation.card`, `flat` takes a 1 px `color.border.default` hairline (`border.hairline`); title `type.ui.heading-sm` + `color.text.primary`; body padding `space.panel.padding` (J11). (Replaces `radius.lg` and `elevation.1`, which are primitives.)
- **Storybook**: Default, WithActions, NoPadding, Flat, RegionTile, InOption (J11).
- **Tests**: unit, visual, axe.
- **As built (E05-S03)**: `padding` is `"panel"|"none"` (default `panel`). Storybook adds NoHeader, LongTitle and AllStates.

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
- **Props**: `page` · `pageCount?` · `cursor?/onNext/onPrev` · `onNewest?` (cursor mode: back to the newest page) · `blockedReason?` (every button disabled with it, as after a `429`) · `pageSize?/onPageSizeChange`.
- **A11y**: `nav aria-label="Pagination"`, current page `aria-current="page"`; in cursor mode no page is current, so no `aria-current`, and the buttons read Newest, Newer and Older (E42-D04 §4); a button with nothing in its direction, or every button given `blockedReason`, stays focusable, disabled with its reason through CMP-079, a CMP-019 `lock` leading the label (`docs/design/E09/E09-D09.md` §2.2).
- **Tokens**: `color.action.*`.
- **Storybook**: Default, CursorMode, CursorKeyset, RateLimited.
- **Tests**: unit, visual, axe, keyboard.

### CMP-054 SearchBox

- **Tier**: Molecule · **Purpose**: generic filter/search input with clear button (distinct from SymbolSearchInput's richer preview).
- **Props**: `value` · `onChange` · `label: string` (mandatory: becomes `aria-label`; a placeholder is never the name) · `placeholder?` · `onClear` · `disabled?`.
- **States**: default, hover, focus-visible, filled (the clear button shows), disabled.
- **A11y**: clear button labelled "Clear search"; `role="searchbox"`. The clear button renders only with a value and returns focus to the field; `Esc` clears a non-empty query, then bubbles; the host announces the result count politely, once per settled query (as CMP-048).
- **Tokens**: inherits CMP-007; the leading `search` glyph `size.icon` + `color.text.tertiary`; the clear button a CMP-002 ghost, flush in the well.
- **Storybook**: Default, WithValue, Disabled.
- **Tests**: unit, visual, axe.
- **As built (E05-S03)**: takes the native input props besides these (so `placeholder` is the input's own) and adds `density?` (`data-density`); the field is a native `type="search"` input. Storybook adds ClearReturnsFocus, Focused, Hover, LongText and AllStates.

### CMP-055 FilterBar

- **Tier**: Molecule · **Purpose**: row of active filter chips + add-filter control (journal, audit, alerts list).
- **Props**: `filters: {id,label,onRemove}[]` · `onAddFilter`.
- **A11y**: `role="group"` `aria-label="Active filters"`; each removable chip is CMP-011 with keyboard-remove.
- **Tokens**: `space.filterbar.*`.
- **Storybook**: Empty, WithFilters.
- **Tests**: unit, visual, axe.

### CMP-056 ColumnPicker

- **Tier**: Molecule · **Purpose**: show/hide/reorder table columns (Positions grid, Deep Stats rows) and watchlist columns (SCR-100, SCR-101).
- **Props**: `columns: {id,label,visible}[]` · `onChange` · `onReorder` · `locked?`.
- **A11y**: checkbox list inside CMP-041 Menu pattern; reorder via keyboard (`Alt+↑/↓` moves focused item) in addition to drag; "Move <column> up/down" buttons where the list sits in a dialog, a `locked` item shown checked and T2 with its reason (E09-D09 §2.2: `aria-disabled`, a CMP-019 `lock` glyph), the move buttons at the ends of the movable range T2 (2b) with "Already first." or "Already last.", every item and move button T2 in CMP-079 RbacGate without `workspaces:write` or while viewing as, described by the host's notice (E08-D07 §6.6), and one polite "Funding % moved to position 4 of 9."
- **Tokens**: inherits CMP-005/CMP-041.
- **Storybook**: Default, Reordering, Locked, ReadOnly.
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
- **Props**: `open` · `onOpenChange` · `commands: {id,label,group,shortcut?,onRun}[]`. Each command adds `disabledReason?` (the host's `docs/design/E09/E09-D09.md` key: a gated command renders T2 with the reason as its second line) and `destructive?` (the `warning` glyph and the tag "confirms"; running it opens its confirmation); `shortcut` renders the active keymap profile's binding through CMP-022; rows are 32 px compact and 40 px comfortable, E10-D03's host data (`docs/design/E05/E05-D02-rest.md` §6 J12, J3, RULED 6438042003).
- **A11y**: Combobox+Listbox pattern inside a modal Dialog; results grouped with `role="group"` + group labels; live region announces result count. Focus stays in the input (`aria-activedescendant`); ↓ / ↑ skip group headers and wrap, and land on a gated option silently (its `aria-describedby` reason is read); `Enter` or `Ctrl+Enter` on it runs nothing and re-shows the reason once, politely; an option's name is its label then its tag; the count speaks once per settled query; the dialog title, the input label, the listbox name and the count sentence are E15's SCR-012 keys (J12).
- **Tokens**: `color.surface.overlay`, `elevation.dialog`, `radius.dialog`, 640 px wide; rows `type.ui.body` + `color.text.primary`, the active row `color.surface.selected`; group headers and the placeholder `color.text.tertiary`; the footer hint `color.text.secondary` (J3, J12). (Replaces `elevation.4`, which is a primitive.)
- **Storybook**: Default, Grouped, NoResults, EmptyQuery, RbacDisabled, Destructive (J12).
- **Tests**: unit, visual, axe, keyboard, fuzzy-match unit tests.
- **As built (E05-S03)**: `packages/ui` `CommandPalette` in a CMP-043 Dialog (640 px); `commands[]` adds `disabledReason?` / `destructive?` / `shortcut?` (display keys); `sections?` are the host's empty-query groups; `onRequestConfirm(command, scope)` replaces running a destructive row (the palette stays open); `onRunGroup?` is `Ctrl+Enter` and shows the footer; ↓ / ↑ wrap, Home / End and PageUp / PageDown move the active option; an in-house fuzzy scorer (`internal/fuzzy.ts`); every string a prop with an English default for stories; the dialog keeps CMP-043's close button as a second Tab stop; no Loading story (no source names one). Stories: Default (EmptyQuery), Filtered (Grouped), NoResults, WithConfirms (Destructive), Gated (RbacDisabled), LongText.

### CMP-060 NotificationCenter (bell dropdown)

- **Tier**: Molecule · **Purpose**: persistent log of toasts/alerts (backstop for CMP-045's no-timing-loss requirement).
- **Props**: `items: Notification[]` · `unreadCount` · `onMarkRead` · `onClearAll`.
- **A11y**: `aria-label="Notifications, N unread"` on trigger button, list uses `role="log"`.
- **Tokens**: `elevation.3`.
- **Storybook**: Empty, WithUnread.
- **Tests**: unit, visual, axe.
- **E40-D02 (#1013; [E40-D02.md](../design/E40/E40-D02.md) §7.4; owner approval pending)**: SCR-014's content: the kinds Alert, Rule, Order and System with glyph + word (NC-1, NC-2); repeat groups ("12 similar alerts") and the storm row; the muted-category line; "Showing the newest 500" with `Load older`; `Mark all read` and `Shift+click` (everything above as read, KM-4); read state on alert rows only; the panel `color.surface.raised` in CMP-209, the unread dot `color.status.info.default`, the count badge per CMP-012's E40-D02 line. The roles of the list and the bell follow `14` SCR-014's A11y.

### CMP-061 UserMenu

- **Tier**: Molecule · **Purpose**: account/profile menu in top chrome (role display, logout, settings link).
- **Props**: `userName` · `role: "owner"|"manager"|"viewer"` · `items: MenuItem[]`.
- **A11y**: inherits CMP-041 contract; role is always shown as visible text (never icon-only).
- **Tokens**: inherits CMP-013/CMP-041.
- **Storybook**: Owner, Manager, Viewer.
- **Tests**: unit, visual, axe.

### CMP-062 ThemeSwitcher

- **Tier**: Molecule · **Purpose**: dark/light/high-contrast theme selection control.
- **Props**: `value: "dark"|"light"|"high-contrast"` · `onChange`. A separate CMP-004 Toggle "match system" sits beside the three values, off by default; choosing a value turns it off (`docs/design/E05/E05-D02-rest.md` §6 J13, RULED 6438042003).
- **A11y**: CMP-003 SegmentedControl composition; changes announced via polite live region ("Theme changed to High Contrast"). A committed change (a segment, the toggle, `Ctrl+Shift+H` from anywhere) speaks once; the initial load, a server-fed apply and a match-system flip speak nothing (J16). Every role, view-as included, changes the theme on this device; a session without `settings:write` skips the server save, with no T2 (J15 (a), PROPOSED, owner approval pending (#2701)).
- **Analytics**: `appearance.theme_changed`, once per committed user change; never on the initial load, a server-fed apply or a match-system flip; the payload is the analytics owner's (#161 Observability; J16).
- **Tokens**: n/a (meta-control).
- **Storybook**: Default, MatchSystem, Light, HighContrast (J13).
- **Tests**: unit, visual, axe.

### CMP-063 DensityToggle

- **Tier**: Molecule · **Purpose**: comfortable/compact density switch, global or per-panel override.
- **Props**: `value: "comfortable"|"compact"` · `scope: "global"|"panel"` · `onChange`. `value` adds `"dense"`, offered only with `scope: "panel"` on a chart panel; `22`'s `spacious` is not offered and maps to Comfortable; `form?: "segmented" | "menu"` (the menu form is CMP-041 `menuitemradio` items) (`docs/design/E05/E05-D02-rest.md` §6 J14, RULED 6438042003).
- **A11y**: CMP-003 composition; per-panel override announced with scope context. With `scope: "panel"` the group's name names the panel and the sentence the scope ("Chart panel density: dense"); a committed change speaks once, and the initial load or a server-fed apply speaks nothing (J16); every role changes it on this device, with no T2 (J15 (a), PROPOSED, owner approval pending (#2701)).
- **Analytics**: `appearance.density_changed`, once per committed user change, global or per panel; never on the initial load or a server-fed apply; the payload, scope included, is the analytics owner's (#161 Observability; J16).
- **Tokens**: n/a (meta-control).
- **Storybook**: Global, PanelOverride, ChartPanelDense, MenuForm (J14).
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
- **Props**: `title` · `description?` · `collapsible?` · `headingLevel?: 2|3|4` (default 3) · `disabled?` · `disabledReason?` (`docs/design/E09/E09-D09.md` §2.2: one notice for the section) · `children`.
- **States**: default, collapsed, errors within (a collapsed section names its count and opens on submit), disabled (`<fieldset disabled>`), disabled-with-reason (`docs/design/E09/E09-D09.md` §2.2 T2 through CMP-079's notice form: one notice, many pointers; each field's value led by the CMP-019 `lock` inside its well).
- **A11y**: `fieldset`/`legend` semantics; the legend wraps a heading (`h{headingLevel}`); a collapsible section's toggle is a button inside the heading (APG Disclosure, `aria-expanded`); a collapsed section that holds an invalid field opens on submit; a T2 section's one notice is every gated field's `aria-describedby` target.
- **Tokens**: heading `type.ui.heading-sm` + `color.text.primary`; description and notice `type.ui.caption` + `color.text.secondary`; `space.stack.xs` (heading to description), `space.stack.md` (between fields), `space.stack.lg` (between sections). (Replaces `space.formsection.*`.)
- **Storybook**: Default, Collapsible, WithErrors, DisabledWithReason.
- **Tests**: unit, visual, axe.
- **As built (E05-S03)**: `collapsible` takes `open?` / `defaultOpen?` / `onOpenChange?` (controlled or not); `errorCount?` overrides the count of invalid FormFields a collapsed section names; adds `density?`. Storybook adds HeadingLevel2, Collapsed, Disabled, LongText, OpensOnSubmit, OpensOnNativeInvalid and AllStates.

### CMP-066 Stepper (multi-step wizard indicator)

- **Tier**: Molecule · **Purpose**: onboarding/setup wizards (first-run account connect, rule-creation wizard).
- **Props**: `steps: {label,status}[]` · `currentStep`.
- **A11y**: `aria-current="step"`, list semantics, status conveyed by icon+text not colour alone.
- **Tokens**: `color.status.*`.
- **Storybook**: Default, WithErrors.
- **Tests**: unit, visual, axe.

### CMP-067 FileDrop / Import control

- **Tier**: Molecule · **Purpose**: CSV/JSON import (journal import, rule import/export) and plain-text symbol lists (SCR-101).
- **Props**: `accept` · `onFiles` · `multiple?` · `maxBytes` with its rejection text, and a preview step before applying (SCR-026's pattern); file content is rendered as text, never interpreted.
- **A11y**: native `<input type=file>` under the hood (drag-and-drop is additive, never the only path), fully keyboard-operable via the native file picker. Without `workspaces:write`, or while viewing as, the import control is T2 in CMP-079 RbacGate, and a full apply target ("Add to Majors" at 200) is T2 with its reason, each with a CMP-019 `lock` glyph (E08-D07 §6.6).
- **Tokens**: `color.border.dashed`.
- **Storybook**: Default, DragOver, Error, Oversized, NotText, ImportPreview, ReadOnly, TargetFull.
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
- **Props**: `title` · `content: ReactNode` · `relatedDetector?: string`. `variant?: "drawer" | "inline"` (default `drawer`; `inline` is an APG Disclosure inside its host that stays open while read) (`docs/design/E05/E05-D02-rest.md` §6 J17, RULED 6438042003).
- **A11y**: opens as CMP-046 Drawer (non-modal), triggerable from the chip's tooltip via `Enter`; or inline, in place: a disclosure control with `aria-expanded` showing a `region` labelled by its heading (E12-D03 DS-3), or a static note with no control (E12-D02:248; E12-D05 §2.1). The trigger is the chip itself, not its tooltip: `Enter` / `Space` on the CMP-227 chip (a `button` with `aria-haspopup="dialog"`) opens it, focus moves to its heading (`tabindex="-1"`), and `Esc` returns focus to the chip; the body is `aria-busy="true"` while the parameter values load (J18).
- **E25-D05**: the chip that references this panel is CMP-227 EstimatedBadge (CMP-011's `estimated` variant is its alias); every badge opens this drawer at its detector's section through the CMP-227 provider.
- **Tokens**: inherits CMP-046.
- **Storybook**: Default, Inline, Loading, Error (J17).
- **Tests**: unit, visual, axe.
- **As built (E05-S03)**: `trigger` is a render prop that receives `aria-expanded`, `aria-controls`, `aria-haspopup` and `onClick`, so the host's chip (CMP-227 later) stays the trigger; adds `values?` (the parameter values under the static text), `loading?`, `error?` with `onRetry?`, `open?` / `defaultOpen?` / `onOpenChange?`, `side?` and `width?` (the drawer form, default `right` and 480 px), `headingLevel?` (the inline form, default 3) and `fallbackFocusRef?`. Storybook ships Default, Inline, InlineCollapsed, Loading, LoadError, InlineLoading and a contrast pair.

---

## 3. Organisms — chrome & navigation (CMP-070..099)

### CMP-070 AppShell

- **Tier**: Organism · **Purpose**: root layout — top chrome, left nav rail, workspace area, global overlays.
- **Props**: `children` · `navItems` · `topChrome: ReactNode[]`.
- **A11y**: landmark regions (`header`, `nav`, `main`), skip-to-content link as first focusable element.
- **Tokens**: `color.surface.app`, `layout.shell.*`.
- **Storybook**: Default.
- **Tests**: unit, visual, axe, landmark-structure test.
- **As built (E10-S01, #304)**: in `apps/web` (`features/app-shell/AppShell.tsx`), props only, not yet in `packages/ui`; mounted by the pathless `ShellLayout` route around every non-public route. Props are slots, not `navItems` / `topChrome`: `mainId`, `nav`, `connection`, `topBar`, `panic`, `banner`, `canvasOverlay`, `rightRail` + `rightRailLabel`, `status`, `children`. Landmarks `banner`, `navigation` "Primary", one `main` (`tabIndex=-1`; screens render a `div`, never a second `main`), `complementary`, `contentinfo`; a full-width banner row sits under the top bar. On a route change focus moves to the first `h1` in `main`. Storybook: none yet (apps/web has no Storybook); covered by RTL, axe and the `shell-chrome` e2e.

### CMP-071 NavRail

- **Tier**: Organism · **Purpose**: left icon-rail primary navigation (Workspaces / Journal / Rules / Alerts / Replay / Admin).
- **Props**: `items: {id,icon,label,route,badge?}[]` · `activeId`.
- **A11y**: `nav` with `aria-label="Primary"`, current item `aria-current="page"`, each icon-only item has visible label on hover/focus tooltip + always-present `aria-label`.
- **Tokens**: `color.surface.raised`, `size.navrail.width`.
- **Storybook**: Default, WithBadges, Collapsed.
- **Tests**: unit, visual, axe, keyboard.
- **As built (E10-S01, #304)**: in `apps/web`. Seven items, not the ten of the ticket and sitemap §1.1 (Terminal, Rules, Journal, Replay, Alerts, Settings, Admin; Watchlist, Positions / Orders and Risk Dashboard PROPOSED, on the owner queue). Each item names a manifest route and is filtered before render through `evaluateAccess`, so every denied item, not only Admin, is absent from the DOM (a Viewer has no Rules). A `nav` of links with `aria-current="page"` plus a 3 px leading bar, fill and weight, not `role="tree"`; the arrows, `Home` and `End` also move focus. Fixed `Alt+1..7` per item (a role without an item leaves a gap). Collapsed 64 px / expanded 240 px: the width snaps, only the labels move by `transform` and opacity; a toggle under the items carries `aria-expanded`; the choice persists per device. Stand-ins: no nav glyphs (the label's initial when collapsed), a `title` instead of CMP-016, a plain badge span with no count source yet (the words join the accessible name, "Alerts, 2 new").

### CMP-072 TopBar

- **Tier**: Organism · **Purpose**: global top chrome — logo, workspace switcher, EnvBanner, ConnectionStatus, NotificationCenter, UserMenu.
- **Props**: `children` (slotted regions).
- **A11y**: `header` landmark.
- **Tokens**: `color.surface.raised`, `elevation.1`.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.
- **As built (E10-S01, #304)**: in `apps/web`, one row in DOM and focus order: wordmark, CMP-075 badge, the Account / Symbol / Interval pickers as disabled-with-reason placeholders ("Not available in this build."), the CMP-084 search trigger (disabled with its reason until E10-S03 registers the palette), the CMP-076 chip, the user's name and role as text and a Sign out button (CMP-061 stand-in), then the CMP-211 slot. No workspace switcher or notification centre here: notifications are the CMP-209 launcher. The badge is announced politely on every route change through the shell's one announcer.

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
- **As built (E10-S01, #304)**: also the TopBar's environment badge in place of CMP-074 (no switch flow): `role="img"` named "Trading environment: Live", word + glyph + weight + a 2 px env border. It takes no prop, class or style that could hide it. TESTNET and ENV UNKNOWN looks are PROPOSED; an unknown environment shows a dashed warning "ENV UNKNOWN", never a defaulted DEMO (the show-or-omit ruling is pending). The status bar repeats the environment in words.

### CMP-076 ConnectionStatus

- **Tier**: Organism · **Purpose**: the global connection-state chip in the TopBar (CMP-072): the client↔backend transport and the feed's freshness as one of five values (E17-D01 §4, architect ruling A4; `docs/design/E17/E17-D02.md` §3, §5), with the last-good time and the client's own `ping` RTT. Read-only is a permission overlay (CMP-117, the SCR-152 region), never a chip state; Resyncing is panel-only.
- **Props**: `status: "live"|"delayed"|"stale"|"reconnecting"|"offline"` · `lastGoodTs` (relative age; absolute UTC on hover and focus) · `latencyMs?` (≤1 Hz, never announced) · `attempt?` · `nextAttemptAtMs?` · `staleAgeMs?` · `oldestTopic?` · `throttleMultiplier?` · `serverStale?` · `upstreamDown?` · `resyncStorm?` · `strong?` (T2) · `detail?` (the `connection_quality` numbers, tooltip only) · `density`.
- **Variants**: compact (a 20 px pill in the 24 px row) · comfortable (a 24 px pill in the 32 px row).
- **States**: live · delayed · stale · stale strong (T2) · reconnecting (a retry scheduled or in flight — a shell-cause `offline` and a reattempt's `connecting` included, E17-D01 §4) · offline (a fatal close or `bye.reconnect: false` only) · connecting before the session's first `auth_ok` (no counter, "Connecting…", PROPOSED) · upstream-down · stale (server) · resync storm (tooltip detail) × default / hover / focus-visible / tooltip-open / hc / greyscale.
- **A11y**: a native `<button>`; icon + text + colour triad per state; name "Connection: Stale 7 seconds, last data 13:42:05 UTC"; `Enter`/`Space` opens the details popover, `Esc` closes it; **owns no live region** — the connection announcements are the SCR-152 region's (E17-D01 §7: `delayed` polite once on entry and exit, `reconnecting`/`offline` assertive once per Disconnected episode — the first `transitionSeq` change out of a live value; the attempt cycle inside it re-announces nothing — never per heartbeat); the age and latency are `aria-live="off"`.
- **Tokens**: `color.text.primary`, `color.surface.raised`/`.hover`, `color.status.{danger,warning,info}.{subtle,strong}`, `color.status.info.default` (Delayed, pending E17-D01 A7), `color.data-confidence.{live,stale}.indicator`, `color.border.default`, `color.focus.ring`, `radius.badge`, `border.hairline`/`.focus`, `size.control.{compact,comfortable}`, `size.target.min`, `size.icon.sm`, `space.inset.{xs,sm}`, `type.ui.{caption,label}`, `font.family.{ui,mono}`, `elevation.popover`.
- **Storybook**: Live, Delayed, Stale, StaleEscalated, StaleServer, UpstreamDown, Reconnecting, Offline, Compact, Comfortable, TooltipOpen, HighContrast, Greyscale.
- **Tests**: unit (the selector and the precedence), visual, axe, announcement-throttling test (one announcement per Disconnected episode, never per reattempt or heartbeat), retry-state test (a shell-cause `offline` and a reattempt's `connecting` render `reconnecting`; "Offline — retry stopped" only for `fatal` / `bye.reconnect: false`), Stale-over-Delayed test (a stale, server-stale or upstream-down public topic under a `saturated` transport shows Stale, never "Reduced rate ×N" — E17-D01 D2), no-live-region-on-the-chip test.
- **Motion spec**: [E08-D11.md](../design/E08/E08-D11.md) (E08-D11; the chip follows the title's ≤ 1 / s slots and latch, never the transport; `latencyMs` ≤ 1 Hz, never in a live region — PROPOSED).
- **As built (E10-S01, #304)**: in `apps/web`, fed from the shell store: the chip shows Live (with latency), Connecting… and Reconnecting (n). A shell-cause `offline` (`startShell`) renders Reconnecting per the retry-state rule; the fatal "Offline — retry stopped", Delayed and Stale have no source in the shell yet. A native `<button>` with no action: no details popover, no CMP-016 tooltip (the UTC time is in the name and a `title`), one compact density. It owns no live region.

### CMP-077 ReconnectOverlay

- **Tier**: Organism · **Purpose**: the connection **region** in the reserved SCR-152 banner slot (0–96 px below the TopBar; E08-D02 §3, E08-D03 §2): Disconnected (reconnecting / offline), session ended, `recovered`, `long-outage` and the Read-only reason slot (`shutdown_notice` and the E17-D01 §6 reasons that the routing table of `docs/design/E17/E17-D02.md` §6 assigns to the region; the backend-health causes are CMP-092's). Re-specified by E17-D01 A1 as **non-modal**: it never covers the positions grid (SCR-063), cancel / close controls or CMP-211; the per-panel scrims are CMP-078's. The name is kept for id stability; a rename (ConnectionRegion) is PROPOSED (`docs/design/E17/E17-D02.md` §6).
- **Props**: `state: "reconnecting"|"offline"|"session-ended"|"recovered"|"long-outage"|"read-only"` · `offlineCause?` (`fatal` → `offline`; a shell cause → `reconnecting` with the cause sentence) · `inFlight?` · `attempt?` · `nextAttemptAtMs?` · `lastGoodTs` · `onRetryNow` (one manual new handshake, never a loop) · `onSignIn` · `onDetails` · `reason?: {message, scope, stillWorks, countdownMs?}` · `role: "owner"|"manager"|"viewer"` (selects the bound Details instance — never a conditional string, E08-D03 §4) · `recoveredSummary?` · `unstable?` (T5 latch).
- **Variants**: Owner Details · Manager / Viewer Details (two bound instances).
- **States**: reconnecting · retrying now · unstable (T5) · offline (retry stopped: a fatal close or `bye.reconnect: false` only; a shell-cause `offline` is a `reconnecting` instance with the cause sentence and no counter until the client carries one) · session ended (`bye.reconnect: false`; `Sign in`, never a retry — `23-ws-protocol.md` §4.4) · the 30 s step · long-outage (5 min; strong fill, `color.text.inverse`) · recovered (dismissible, never auto-hidden before 10 s) · read-only (per reason) × default / focus-visible / hc / greyscale.
- **A11y**: `role="region"` named "Connection"; **no `alertdialog`, no focus trap**; the state change never moves focus (`05-accessibility-standard.md` §3.4 item 3); the CMP-028 `connection-disconnected` callout inside it fires `role="alert"` once per Disconnected episode (never per reattempt); `Retry now`, `Sign in` and `Details` are buttons in the Tab order (`Enter`/`Space`; `Esc` closes Details and returns focus); `RetryExhausted` = the `offline` chip state; the countdown is CMP-035 `aria-live="off"`.
- **Tokens**: `color.status.{danger,warning,success}.{subtle,strong}`, `color.text.{primary,secondary,inverse,link,on-action}`, `color.action.primary.default`, `color.focus.ring`, `radius.control`, `border.thick`/`.focus`, `size.icon.md`, `space.inset.sm`, `type.ui.{body,body-strong}`, `elevation.chrome`, `motion.duration.{instant,fast}`, `motion.easing.accelerate`. Not this component's: `elevation.5` (= `elevation.scrim`, the per-panel scrim layer) and the requested `color.surface.scrim` alias (`color.surface.overlay` at `opacity.scrim`).
- **Storybook**: Reconnecting, OfflineFatal, ReconnectingUnreachable, SessionEnded, Recovered, LongOutage, ReadOnlyShutdown, ReadOnlyKillSwitch, DetailsOwner, DetailsViewer, Keyboard, ReducedMotion.
- **Tests**: unit, visual, axe, **no-trap test** (`Tab` leaves the region; SCR-063's controls stay reachable while Disconnected), one-alert-per-episode test, no-retry-on-`reconnect: false` test (the `session-ended` state renders `Sign in` and no `Retry now`), Details-split test (no Owner field renders in the Viewer instance).
- **As built (E10-S04, #306; mounted by E10-S01, #304)**: in `apps/web`, as the non-modal connection region in the shell's banner slot (`ShellBanner`, above CMP-092's rows), never over the canvas or CMP-211. A `region` named "Connection" that owns no live region: its container writes the alert once per Disconnected episode through the shell announcer. Deferred: Retry now, Details (Owner / Viewer), recovered, unstable; the left border is 2 px and there is no 96 px minimum height (no tokens).

### CMP-078 StaleDataShade

- **Tier**: Molecule (chrome) · **Purpose**: per-panel freshness shade applied at the per-topic T1 threshold (book 2 s, ticker 5 s, trades 10 s; E17-D01 A2 / §4.1, superseding the blanket 2 s) and escalated at T2 (3×), plus the frozen Disconnected / Resyncing scrim (`docs/design/E17/E17-D02.md` §7).
- **Props**: `state: "fresh"|"stale"|"escalated"|"stale-server"|"disconnected"` · `lastGoodTs` · `ageMs` · `topic` · `symbol` · `sinceTs?` (`meta.stale`) · `blocksLadder?` (the SCR-050 ladder's T2 block from T1 — `docs/design/E17/E17-D02.md` §7, §13.1).
- **Variants**: panel (chart, DOM / heatmap, tape, watchlist) · grid row (positions / orders, de-emphasised in place, never re-sorted).
- **States**: fresh (nothing rendered) · stale (the 15 % dim + chip "Stale 7s" + "Last update 7 s ago") · escalated (header strip "Stale 15 s — new orders blocked on BTCUSDT", the T2 notice row and the lock cursor on SCR-050, strong chip) · stale-server ("Stale (server) — since 14:02:11") · disconnected (held last frame under the 0.6 scrim, "Disconnected — last data 00:12"; "Resyncing book…" while the book has no consumable state).
- **A11y**: shading is supplemented with the visible "Last update Xs ago" text and the absolute UTC time on hover / focus, never opacity alone; the shade is `aria-hidden` with its text exposed via `aria-describedby` on the panel region (E08-D03 §5); `role="img"` canvases keep their summary; the `Alt+T` table alternative carries the same state word and age (E11-D04 D15); stale enter / exit announce polite once at panel level; the Disconnected and escalated blocks are E09-D09 §2.2's T2 — CMP-079 with the `feed.*` reason in a notice row under the panel header and the CMP-019 `lock` glyph, every row's `aria-describedby` pointing at it, the lock cursor as reinforcement, no tooltip — never `inert`: the ladder keeps its roving focus and a keystroke re-shows E17-D01 D13's sentence inline with one polite announcement (`docs/design/E17/E17-D02.md` §13.1); **never pulses**.
- **Tokens**: `color.data-confidence.stale.{text,indicator,surface}` (the surface composited at 0.15 = the requested `color.overlay.stale` alias), `color.data-confidence.resyncing.indicator`, `color.surface.overlay` at `opacity.scrim` (the requested `color.surface.scrim` alias), `elevation.scrim`, `color.status.warning.{subtle,strong}`, `color.text.{primary,secondary}`, `border.thick`, `type.ui.{caption,body-strong}`, `font.family.mono`, `motion.duration.{normal,fast,instant}`, `motion.easing.{standard,accelerate}`.
- **Storybook**: Fresh, Stale, Escalated, StaleServer, Disconnected, ReducedMotion.
- **Tests**: unit (T1 / T2 per topic; the block lifts in the `snap` frame), visual, axe, never-stacked test, no-animation-on-stale test (E08-D11 D16), focus-retention test (focus inside a blocked ladder is kept; the Tab order is unchanged while Disconnected).
- **Motion spec**: [E08-D11.md](../design/E08/E08-D11.md) (E08-D11; the 15 % panel dim settles once in and cuts out after a clearing window; the T2 `escalated` strip and lock cursor are cuts — PROPOSED).

### CMP-079 RbacGate (disabled-with-reason wrapper)

- **Tier**: Molecule (utility/organism-adjacent) · **Purpose**: standard wrapper implementing invariant §0.5.5 — controls the session may not use render disabled with a visible reason (inline, or echoed by a focus+hover tooltip; `docs/design/E09/E09-D09.md` §2.2).
- **Props**: `allowed: boolean` · `reason: string` (required when `allowed` is false; a key of the vocabulary in `docs/design/E09/E09-D09.md` §3) · `form?: "inline"|"tooltip"|"notice"` (default `inline`; `tooltip` only for icon-only controls and toolbar segments) · `noticeId?` (required with `notice`) · `children` (any interactive component).
- **Variants**: inline (the reason under the control), tooltip (a lock badge on the icon, the description visually hidden and echoed by CMP-016 on hover and focus), notice (one notice node that every gated control points at).
- **A11y**: propagates `disabledReason` to the wrapped atom's native prop (CMP-001/002/004 etc. all accept it) rather than overlaying a separate non-semantic layer. T2 (`docs/design/E09/E09-D09.md` §2.2, §9): the wrapped control keeps its role and full label, takes `aria-disabled="true"` (never `disabled`) and `aria-describedby` → the reason rendered at mount (a text-like field also `readonly`); the CMP-019 `lock` glyph ("Not available") leads the label (inline; on a field, the value inside the well, `docs/design/E30/E30-D04.md` §2.5) or badges the icon (tooltip); a key re-shows the reason with one polite announcement; it emits nothing.
- **Tokens**: n/a (behavioural wrapper; the wrapped control's T2 look binds `color.text.tertiary`, `color.text.secondary`, `color.surface.raised` and `color.border.default`).
- **Storybook**: Allowed, Denied(Permission), Denied(OwnerOnly), Denied(Account), Denied(AccountReadOnly), Denied(Env), Denied(ReadOnly), Denied(ViewAs), Denied(EnvMismatch), FormInline, FormTooltip, FormNotice.
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
- **Props**: `targetId`. `targets: { id, label }[]` supersedes it: "Skip to main content" always first, further links only for regions the route mounts (the order ticket, the chart), each its own link in DOM order before the TopBar (`docs/design/E05/E05-D02-rest.md` §6 J19, RULED 6438042003).
- **A11y**: visually hidden until focused, then visible at top-left. Activation moves focus to the target, which takes `tabindex="-1"` (removed on blur) and shows the CMP-039 ring; the next Tab continues from it (J20).
- **Tokens**: pill `color.action.primary.default` (hover `color.action.primary.hover`), `radius.control`, min-height `size.control.height`, padding `space.button.paddingX`; label `type.ui.label` + `color.text.on-action`; the `color.focus.ring` ring (E10-D03 A5; J19). (Replaces `color.action.primary`, read as `.default`.)
- **Storybook**: Focused, Unfocused, Several (J19).
- **Tests**: unit, visual, axe, keyboard-first-tab test.
- **As built (E10-S01, #304)**: the shell first shipped a temporary single-target stand-in in `apps/web` ("Skip to main content" → the shell's `main`), the first Tab stop on every shell page, until the `packages/ui` component (E05-S04, #267) replaces it.

### CMP-086 SettingsNav / SettingsLayout

- **Tier**: Organism · **Purpose**: two-pane settings layout (nav list + content) for `/settings/*`.
- **Props**: `sections: {id,label,icon}[]` · `activeId` · `children`.
- **A11y**: `nav aria-label="Settings"`, landmark `main` for content.
- **Tokens**: `layout.settings.*`.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-087 AdminLayout (RBAC-gated shell)

- **Tier**: Organism · **Purpose**: shell for `/admin/*` routes: the "Admin area" band with the route, a 4 px rule, the "Needs your action" strip and comfortable density, distinct from the trading app without colour; the re-auth badge with an admin window or the step-up grace line with per-action step-up (the re-auth decision, #1085) (`docs/design/E42/E42-D03.md` §4).
- **Props**: `children` · `routeLabel` · `env` · `strip` (the "Needs your action" slot) · `reauthExpiresAt?` (variant (a) only; a server value, never a client clock) · `grace?: {classLabel, expiresAt}` (variant (b), from the step-up answer).
- **A11y**: the band is the first child of `<main>`, `role="region"` `aria-label="Admin area"`, never focusable; the strip is a `role="region"` list, not live; the route announcer reads "Admin · <route> · <ENV>"; the countdown (CMP-035 pattern) is never live: one announcement at 5 min (polite), 1 min and expiry (assertive); never a second alertdialog (CMP-098 stays the idle warning).
- **Tokens**: `color.surface.admin-tint` (→ `color.surface.raised`), `color.border.admin` (→ `color.text.tertiary`, 4 px), `color.surface.hover`, `color.text.secondary`, `color.status.warning.subtle`/`.strong`, `color.status.danger.subtle`/`.strong`, `size.control.comfortable`, `space.inset.lg`, `type.ui.heading-md`, `type.num.base`.
- **Storybook**: Default, ReauthExpiringSoon, ReauthFinalMinute, ReauthExpired, PerActionOnly, PerActionGrace, AfterIdleUnlock, StripEmpty, StripWithItems — each in dark, light and high contrast.
- **Tests**: unit, visual, axe.

### CMP-088 PageHeader

- **Tier**: Molecule · **Purpose**: full-page area header (Journal, Rules, Alerts, Replay, Admin sub-pages) — title + primary actions + breadcrumb.
- **Props**: `title` · `breadcrumb?` (omitted in admin: the CMP-087 band carries the route) · `actions?` · `meta?` (one plain line, e.g. "All times UTC · as of 14:02:11") · `marker?` (a CMP-093 audited-read marker).
- **A11y**: single `h1` per route, the skip-link target; `meta` and `marker` are plain text, never live; the primary action follows the `h1` in Tab order.
- **Tokens**: `type.ui.heading-md`, `type.ui.caption`, `color.text.tertiary`, `space.inset.lg`, `space.stack.sm`.
- **Storybook**: Default, WithBreadcrumb, Admin, AdminWithMeta, AdminAuditedRead.
- **Tests**: unit, visual, axe.

### CMP-089 ForbiddenState (403)

- **Tier**: Organism · **Purpose**: full-page state for a route disallowed at the server (defence in depth alongside hidden-nav per §0.5.5). It renders `docs/design/E09/E09-D09.md`'s T4 route landing and the step-3 never-had landing, never a T2 lock.
- **Props**: `code` · `requiredPermissions?` · `instance?` · `variant: "never-had"|"withdrawn"` · `backHref` · `copyDetails` (`docs/design/E09/E09-D09.md` §8 DS-3).
- **A11y**: `h1` per `docs/design/E09/E09-D09.md` §10 ("You don't have access to this" / "Your access changed"), never "Access denied"; the vocabulary sentence; "Back to your workspace" and "Copy details"; "Ref {instance}", selectable, only when a 403 body was received; focus moves to the `h1` on navigation and, after an in-place replacement, only to restore focus the replacement unmounted; the replacement is announced once (§4.4).
- **Tokens**: inherits CMP-026, plus `type.ui.heading-lg` (the `h1`), `type.num.base` (the account echo) and `type.num.sm` (the Ref).
- **Storybook**: Default, Withdrawn, AccountVariant, NoRef.
- **Tests**: unit, visual, axe.

### CMP-090 NotFoundState (404)

- **Tier**: Organism · **Purpose**: unmatched route fallback.
- **Props**: `path` (echoed as text) · `tryRoutes` (the session's permitted top-level routes) · `variant?: "unknown"|"deleted"`.
- **A11y**: `h1` "Page not found"; "There's nothing at {route}." with the route as plain text; "Try:" with the links as a list; identical copy, title and analytics for an admin route without `admin:read` and for an unknown route (`docs/design/E09/E09-D09.md` §6); focus to the `h1` on navigation.
- **Tokens**: inherits CMP-026, plus `type.ui.heading-lg` and `type.num.sm` (the route).
- **Storybook**: Default, Deleted.
- **Tests**: unit, visual, axe.

### CMP-091 GlobalErrorBoundaryFallback

- **Tier**: Organism · **Purpose**: React error-boundary fallback screen (uncaught render error), offers reload/report.
- **Props**: `error` · `scope: "panel"|"route"|"app"` (`route` keeps the chrome, `docs/design/E10/E10-D03.md` §9.4; `app` is the root boundary when the shell itself fails) · `correlationId` · `onReload` · `onReport` · `onRemovePanel?` (panel) · `onSafeMode?` (route and app) · `repeated?` · `protectionNote?` (the host's sentence where true).
- **A11y**: one assertive announcement per crash — a panel's or a route's through the shell's pre-rendered region, the app scope as its own `role="alert"`; focus moves to the fallback heading only when the crash unmounted the focused element (a restoration, `docs/design/E09/E09-D09.md` §9.4); the stack sits behind a "Technical detail" disclosure; the error id is selectable; three crashes in two minutes stop the automatic reload (`docs/design/E10/E10-D03.md` §9.4, PROPOSED).
- **Tokens**: inherits CMP-027, plus `type.ui.heading-sm` (panel), `type.ui.heading-lg` (route and app), `type.num.xs` + `color.text.tertiary` (the error id) and `color.surface.raised` (the details); the panel on `color.surface.canvas`, the route and app scopes on `color.surface.app`.
- **Storybook**: PanelLevel, RouteLevel, AppLevel, Details, RepeatedCrash.
- **Tests**: unit, visual, axe.

### CMP-092 DegradedModeBanner

- **Tier**: Molecule (chrome) · **Purpose**: SCR-153's banner for **backend-health causes** — upstream exchange down, the upstream private reconnect, E04 ingestion lag, recorder down or its disk near-full, rule engine down, GPU fallback, cold tier, engine FPS below budget, the `23-ws-protocol.md` §15.9 process read-only notices and `maintenance.enabled`, the E17-D01 D17 conditions — each row stating what still works; a row blocks — the gated controls T2 per E09-D09 §2.2 (CMP-079 + the CMP-019 `lock` glyph with a `health.*` reason, `docs/design/E17/E17-D02.md` §10 J, §13.1) — only where the order path refuses on the cause (`24-internal-schemas.md` §8.10), every other degradation is an info or warning row (first match wins), with the CMP-210 chip beside it (one reason → one surface: the routing table in `docs/design/E17/E17-D02.md` §6 — never also the SCR-152 region). Distinct from ConnectionStatus (transport) and from the SCR-152 region (Disconnected); degraded cadence (Delayed) is **not** an issue here (E17-D01 D4 / A5; `docs/design/E17/E17-D02.md` §8).
- **Props**: `issues: {id, severity: "info"|"warning"|"blocking", message, stillWorks, scope?, dismissible, href?, chip?}[]` · `onDismiss(id)`.
- **Variants**: single-issue · multiple-issue (one row per issue, `space.stack.sm`; three or more collapse the stillWorks sentences behind "Show details", PROPOSED).
- **States**: info · warning · blocking (per row) · dismissed-for-the-episode (reappears when the condition re-asserts) × default / focus-visible / hc.
- **A11y**: `role="status"` for info and warning rows, `role="alert"` once for a blocking row (it refuses new risk) — the one announcement for that condition, never also the SCR-152 region's; severity by glyph + word + colour; dismissible per-issue but reappears while the condition persists (never a silent permanent dismiss); the dismiss control is in the Tab order (≥24 px), the CMP-210 chip only with its admin link — without `admin:read` it is a status display, never T2 (E09-D09 §2.1 step 1); no row ever says "Trading is off" where cancel / close remain.
- **Tokens**: `color.status.{info,warning,danger}.{subtle,strong}`, `color.status.info.default`, `color.text.{primary,secondary}`, `color.surface.raised`, `color.focus.ring`, `space.stack.sm`, `space.inset.sm`, `size.target.min`, `type.ui.{body,caption}`, `motion.duration.{instant,fast}`.
- **Storybook**: SingleIssue, MultipleIssues, Blocking, DismissedReappears, HighContrast.
- **Tests**: unit (dismissal reappears on a new `system` frame), visual, axe, live-region test (status vs alert by severity).

### CMP-093 AuditActionTrigger (wraps any state-changing control to guarantee audit emission)

- **Tier**: Molecule (utility) · **Purpose**: development-time contract wrapper ensuring every state-changing action emits the audit record shape from `14-screens-catalogue.md` §0.5.8; not a visual component but catalogued because it participates in the DoD checklist for every action-producing organism.
- **Props**: `action: string` · `target` · `before?/after?` · `marker?: {label, codes}` (renders "Recorded in the audit log · <label> (<code>)") · `children`.
- **A11y**: pass-through; a `marker` is plain text that joins the wrapped control's `aria-describedby`; a disabled control keeps its marker.
- **Tokens**: n/a.
- **Storybook**: Marker (the visible line); otherwise documented via integration test.
- **Tests**: integration test asserting audit POST fired with correct shape for a representative sample of wrapped actions.

### CMP-094 HotkeyOverlay ("? " cheatsheet)

- **Tier**: Organism · **Purpose**: full hotkey cheatsheet overlay, triggered by `?`.
- **Props**: `groups: {label,bindings:{keys,action}[]}[]`.
- **A11y**: modal Dialog (CMP-043) composition, content organised as a table with a caption.
- **Tokens**: inherits CMP-043.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-095 FeatureFlagChip (visible-in-UI flag indicator, admin/dev only)

- **Tier**: Atom (chrome, owner-only) · **Purpose**: small marker on screens gated by an unreleased feature flag, visible only to owner role for QA purposes. It is not drawn on SCR-145, whose rows carry the flag itself (CMP-179).
- **Props**: `flagKey`.
- **A11y**: visible text "Flag: {flagKey}", which is also its accessible name; never colour or an icon alone.
- **Tokens**: `color.status.info.subtle` (fill), `color.status.info.strong` (glyph) and `color.text.primary` (text) until `color.chip.dev` exists (E42-D02 DS-4).
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-096 WhatsNewPanel

- **Tier**: Organism · **Purpose**: release-notes drawer surfaced after an update (ties to `07-release-and-prr.md` changelog).
- **Props**: `entries: {version,date,items}[]`.
- **A11y**: Drawer composition (CMP-046).
- **Tokens**: inherits CMP-046.
- **Storybook**: Default.
- **Tests**: unit, visual, axe.

### CMP-097 OnboardingChecklist

- **Tier**: Organism · **Purpose**: first-run setup checklist (connect Bybit account, set recorder policy, create first workspace).
- **Props**: `steps: {id,label,done,onGo,disabledReason?}[]`.
- **A11y**: list semantics with `aria-checked` per step (treated as read-only checkbox list reflecting completion state); a step the session's role cannot complete is `aria-disabled` with its `disabledReason` as visible text (`14-screens-catalogue.md` SCR-019, §0.5.5), never removed.
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

- **Tier**: Molecule · **Purpose**: export controls (CSV/PDF) for journal and strategy reports. Not used for the audit log, whose export is one signed format of a time window run as a job behind a step-up (`docs/design/E42/E42-D04.md` §8).
- **Props**: `formats: ("csv"|"pdf")[]` · `onExport(format)` · `loading?`.
- **A11y**: each format is a distinct labelled button, loading state per CMP-038.
- **Tokens**: inherits CMP-001.
- **Storybook**: Default, Exporting.
- **Tests**: unit, visual, axe.

---

## 4. Trading-specific components (CMP-100..139)

These are first-class design-system components per `05-accessibility-standard.md` §11.3 — same a11y bar as atoms/molecules, not exempted as "custom chart stuff." Every canvas-adjacent one (footprint cell, DOM row, heatmap legend) ships a table-alternative data contract per §6 of that standard.

### CMP-100 PriceInput

- **Tier**: Molecule (trading) · **Purpose**: price entry with exchange tick-size validation and quick nudge buttons; the committed value never re-renders on a tick (the helpers are an isolated region, E30-D02 D6).
- **Props**: `value: number` · `onChange` · `symbol: string` · `tickSize: number` (from `/v5/market/instruments-info`) · `side?: "buy"|"sell"` (tints the ▲ / ▼ glyph only — never the value text, never the focus halo) · `referencePrice?: number` (last/mark, for %-away helper text) · `disabled?/disabledReason?` (CMP-001's semantics; the reason is a key of `docs/design/E09/E09-D09.md` §3).
- **Variants**: standalone, attached-to-order-line (rendered inline on chart via chart-engine overlay, CMP-192).
- **States**: default, focus, invalid-tick (value not a multiple of `tickSize` → auto-rounds on blur with a visible "(rounded to nearest tick)" caption; an exact half-tick tie rounds to the nearest even tick, E30-D02 A-5; never silently mutates), invalid (2 px `color.status.danger.default` boundary + `color.status.danger.strong` glyph + `color.text.primary` text), stale-helpers, read-only (E09-D09 §2.2 T2: `aria-disabled`, lock glyph, full label, reason linked).
- **A11y**: extends CMP-008 NumericStepperInput contract; `aria-label="Price"`, rounding-message rendered as `aria-live="polite"` text near the field, not just a toast; focus is never moved by a tick; T2 per E09-D09 §2.2 for the view-as, viewer and read-only-account legs (CMP-079 RbacGate on the role legs; CMP-019 Icon `lock`, `decorative=false`, "Not available", leading the label).
- **Tokens**: `font.family.mono` + `type.num.base` (tabular figures), `color.text.primary` on `color.surface.app`, `color.text.tertiary` as the 1 px rest boundary (= `color.border.input`, pending as E30-D04 CR-1; `color.border.strong` measures 1.91 / 1.57 / 1.91 and is not bound), `color.status.danger.default` / `color.status.danger.strong`, `color.text.secondary` (caption), `color.surface.raised` + `radius.control` (nudge buttons, 24 × 24 / 32 × 32), `space.inset.sm`, `color.focus.ring`.
- **API sketch**: `interface PriceInputProps { value: number; onChange: (v: number) => void; symbol: string; tickSize: number; side?: "buy" | "sell"; referencePrice?: number; disabled?: boolean; disabledReason?: string }`
- **Data contract**: `tickSize`/`symbol` sourced from Bybit `/v5/market/instruments-info` (REST, cached per symbol); no live WS dependency.
- **Storybook**: Default, TickRounding, BuySideTint, SellSideTint, Invalid, FocusVisible, StaleHelpers, ReadOnlyT2, Comfortable, HighContrast.
- **Tests**: unit (tick-rounding matrix across symbols with different tick sizes, the half-tick tie), visual, axe, keyboard step, interaction test for rounding-announcement, the T2 interaction test (reason in the DOM at mount, focusable, a press changes nothing), no re-render on a tick.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §4 (E30-D04; owner approval pending).

### CMP-101 QtyInput

- **Tier**: Molecule (trading) · **Purpose**: quantity entry with exchange lot-size/min-notional validation and the E30-D02 D7 hybrid sizing control: one input, a unit switch and a read-out line that always shows the other three framings.
- **Props**: `value: number` · `onChange` · `symbol` · `lotSize: number` · `minQty: number` · `minNotional?: number` · `sizingMode: "fixed_qty"|"fixed_notional"|"pct_equity"|"risk_based"` (`24-internal-schemas.md` §9.2; E30-D02 A-7) · `onSizingModeChange` · `accountEquity?: number` · `stopDistance?: number` (required for `risk_based`) · `disabled?/disabledReason?`.
- **Variants**: fixed-qty mode, fixed-notional mode, %-equity mode (renders derived qty read-only alongside the % input), risk-% mode (requires a stop distance to derive qty); hedge-mode leg radiogroup (E30-D02 D27).
- **States**: default, focus, below-min-qty (blocks submit, inline error), below-min-notional (blocks submit), stale-wallet (the `% eq` and `risk %` units `aria-disabled` with "Equity not available — wallet data is {n} s old", dimmed at `opacity.disabled`, focusable — the validity look of E30-D04 §2.5), preview-in-flight (the read-out greyed under the `(provisional)` hatch), server-size-replaced (the value-change highlight, E30-D04 M5), read-only (T2).
- **A11y**: extends CMP-008; sizing-mode switch is CMP-003 SegmentedControl with `aria-describedby` explaining the active formula; the read-out line is one polite live region at ≤ 1 update per 2 s, latest value only; T2 per E09-D09 §2.2 (CMP-079 RbacGate on the role legs; CMP-019 Icon `lock` leading the label).
- **Tokens**: `font.family.mono` + `type.num.base` / `type.num.sm`, `color.text.primary`, `color.surface.app`, `color.surface.raised` / `color.surface.selected` (the unit switch), `color.text.tertiary` (the 1 px rest boundary; = `color.border.input`, CR-1 pending), `color.status.danger.default`, `color.status.info.subtle` (the highlight overlay at 0.25), `radius.control`, `space.inset.sm`, `color.focus.ring`.
- **API sketch**: `interface QtyInputProps { value: number; onChange: (v: number) => void; symbol: string; lotSize: number; minQty: number; minNotional?: number; sizingMode: "fixed_qty" | "fixed_notional" | "pct_equity" | "risk_based"; onSizingModeChange: (m: QtyInputProps["sizingMode"]) => void; accountEquity?: number; stopDistance?: number; disabled?: boolean; disabledReason?: string }`
- **Data contract**: `lotSize`/`minQty`/`minNotional` sourced from Bybit `/v5/market/instruments-info` (REST, cached per symbol); `accountEquity` sourced from the account-equity WS/REST feed per `14-screens-catalogue.md` §0.4; the authoritative size from `POST /trade-groups/preview` (`resolved.qty`).
- **Storybook**: FixedQty, FixedNotional, PctEquity, RiskBased, BelowMinQty, BelowMinNotional, StaleWalletUnits, PreviewInFlight, ServerSizeHighlight, ReadOnlyT2, Comfortable, HighContrast, ReducedMotion.
- **Tests**: unit (lot/min-qty/min-notional validation matrix per sizing mode; `risk_based` without `stopDistance` is an error), visual, axe, keyboard, the live-region cadence and teardown test, the highlight twin test, the T2 test.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §5 (E30-D04; owner approval pending).

### CMP-102 SideToggle (Buy/Sell)

- **Tier**: Molecule (trading) · **Purpose**: primary long/short direction selector on the order ticket.
- **Props**: `value: "buy"|"sell"` · `onChange` · `size?: "sm"|"md"` · `disabled?/disabledReason?` (the reason per E09-D09 §3).
- **Variants**: `sm` (24 px halves), `md` (28 px halves — E30-D02 D2).
- **States**: default, hover, focus-visible (the double ring: 2 px `color.focus.ring` outside a 1 px `color.surface.canvas` halo — never the ring directly on a fill), pressed, read-only (T2: both halves on `color.surface.raised` with a hairline, full labels in `color.text.tertiary`, the lock leading the group, one reason).
- **A11y**: CMP-003 SegmentedControl composition (`role="radiogroup"`), buy option always labelled "Buy / Long", sell "Sell / Short" (full words, not just colour-coded B/S); the ▲ / ▼ glyph `aria-hidden`; `B` / `S` set the side only while the ticket region has focus and no text field is active; T2 per E09-D09 §2.2 on the group (CMP-079 RbacGate; CMP-019 Icon `lock` leading the group).
- **Tokens**: `color.buy.default` / `color.sell.default` (the selected half's fill; `color.buy.hover` / `color.sell.hover` on hover), `color.text.inverse` (labels), `color.surface.raised` + `color.text.primary` (the unselected half), `radius.control`, `type.ui.label`, `color.focus.ring`.
- **API sketch**: `interface SideToggleProps { value: "buy"|"sell"; onChange: (v:"buy"|"sell")=>void; size?: "sm"|"md"; disabled?: boolean; disabledReason?: string; }`
- **Data contract**: pure UI state, no direct WS/REST dependency (value flows into CMP-107 OrderTicket's submit payload).
- **Storybook**: Default, SellSelected, Hover, FocusVisibleDoubleRing, Pressed, ReadOnlyT2, SizeSm, SizeMd, Comfortable, HighContrast, Greyscale.
- **Tests**: unit, visual, axe, keyboard (the roving stop; `B` / `S` scoping), the greyscale assertion (word + glyph on both halves), the T2 test.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §6 (E30-D04; owner approval pending).

### CMP-103 OrderTypeTabs

- **Tier**: Molecule (trading) · **Purpose**: Market/Limit/Conditional (and Emulated: Scaled/Iceberg/TWAP/Chase) order-type selector inside the order ticket.
- **Props**: `value` · `onChange` · `options: OrderTypeOption[]` (native vs emulated types flagged with an "(emulated)" tag per safety-transparency rule; an unavailable type carries `unavailableReason`).
- **Variants**: native only; with emulated types.
- **States**: default, selected (`color.surface.selected` + a 2 px `color.text.primary` rule — never the action blue, E30-D02 D5), hover, focus-visible, emulated-unavailable (the validity look of E30-D04 §2.5: the tab at `opacity.disabled` with its reason "Available with E33 emulated algos" as its description, `aria-disabled`, focusable, no lock), read-only (T2).
- **A11y**: CMP-042 Tabs composition; emulated-type tag rendered as visible text badge, not tooltip-only; manual activation (`Enter` / `Space`) because a switch re-shapes the form (E30-D04 §7, PROPOSED); T2 per E09-D09 §2.2 (CMP-079 RbacGate; CMP-019 Icon `lock` leading the first tab); an emulated tab takes the validity look (E30-D04 §2.5).
- **Tokens**: inherits CMP-042; `color.surface.selected`, `color.text.primary` (the rule), `color.text.secondary` (unselected text, the tag), `type.ui.label`, `type.ui.caption`, `radius.control`, `color.focus.ring`.
- **API sketch**: `type OrderTypeOption = { value: string; label: string; emulated?: boolean; unavailableReason?: string };`
- **Data contract**: `options` list is a static client-side vocabulary (native Bybit order types + CandleViewer-emulated types); no WS/REST dependency.
- **Storybook**: Default, WithEmulatedTypes, Selected, FocusVisible, EmulatedValidity, ConditionalSelected, ReadOnlyT2, Comfortable, HighContrast.
- **Tests**: unit, visual, axe, keyboard, the emulated-tab test (focusable, a press changes nothing, the sentence announced once), the T2 test.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §7 (E30-D04; owner approval pending).

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

- **Tier**: Organism (trading) · **Purpose**: multi-account picker for trade-group fan-out — select N sub-accounts, each shown with its ProfileBadge and per-account editable overrides; the account / trade-group selector of SCR-061 (E30-D03 §8).
- **Props**: `accounts: {id,label,badge:ProfileBadgeProps,selected,profileSummary}[]` · `onToggle` · `onSelectAll` · `onEditProfile(accountId)` · `maxSelectable?: number` (sub-account cap 5/20) · `mode: "account" | "group"` · group rows (`memberCount`, `readiness`) · per-leg rows (`wouldSubmit`, `rejection`, `skip`, `override`) (E30-D03 A11).
- **Variants**: `account`, `group`.
- **States**: default, selected row, hover, focus-visible, at-cap, narrowed, read-only-member (T2: the include box `aria-disabled`, the lock leading the full label, one shared reason "You can view this account, not trade it."), view-as read-only (one notice per frame), disclosure open / closed.
- **A11y**: `role="group"` with a `listbox`-like multi-select pattern (`aria-multiselectable="true"`), each row a `role="option"` `aria-selected`; "select all" is a distinct labelled control, not implicit; `Shift+F10` opens the row menu, the read-only member's too; the read-only member row is T2 (CMP-079 RbacGate on the role legs; CMP-019 Icon `lock` leading the label; `aria-describedby` → the shared reason).
- **Tokens**: `color.surface.raised` / `color.surface.selected` / `color.surface.hover`, `space.row.height.compact` / `space.row.height.comfortable`, `color.text.primary` / `color.text.secondary`, `color.env.live` / `color.env.demo` (the dot), `radius.control`, `color.focus.ring`, `color.surface.overlay` + `elevation.popover` (the popover).
- **API sketch**: `interface AccountMultiSelectProps { accounts: Array<{ id: string; label: string; badge: ProfileBadgeProps; selected: boolean; profileSummary: string }>; onToggle: (id: string) => void; onSelectAll: () => void; onEditProfile: (id: string) => void; maxSelectable?: number; mode: "account" | "group" }`
- **Data contract**: `accounts` list sourced from the account-management REST endpoint (sub-account roster + profile settings); `profileSummary` is derived client-side from each account's saved risk-profile record; the leg rows from `POST /trade-groups/preview` (E30-D03 §8).
- **Storybook**: Default, AllSelected, AtCap, EditProfileInline, GroupMode, NarrowedGroup, ReadOnlyMemberT2, ViewAsReadOnly, DisclosureOpen, Comfortable, HighContrast, ReducedMotion.
- **Tests**: unit (cap enforcement), visual, axe, keyboard multi-select, the T2 row test, the motion twin test (the disclosure reveals by clip + translate at its final geometry; instant under reduce).
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §8 (E30-D04; owner approval pending); [E30-D03-handoff.md](../design/E30/E30-D03-handoff.md) (the contract block).

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

- **Tier**: Organism (trading) · **Purpose**: the primary execution surface — side, symbol, order type, price/qty, TP/SL attach, account(s), submit. Composes CMP-100/101/102/103/105/106 and CMP-119/121/122/130/139/158/229/231/232; CMP-079 RbacGate wraps every role leg and CMP-019 Icon `lock` leads every gated label (E09-D09 §2.2).
- **Props**: `symbol` · `side` · `orderType` · `price?/qty` · `accounts: AccountMultiSelectProps["accounts"]` · `tpSl?: {tpMode,tpValue,slMode,slValue}` · `oneClickArmed: boolean` · `onSubmit` · `env: "demo"|"live"`.
- **States**: idle, validating, submitting, awaiting_confirmation (2 s after `202` without a terminal update), submitted-ack, partially_filled, rejected(with reason), rate-limited(with retry countdown), protective_stop_pending (the unprotected banner, E30-D04 §2.3), blocked_by_profile (split: a per-field cap excess is a field error with the submit in the validity look; a whole-ticket block is T2 `profile.blocked`, PROPOSED), blocked_by_lockout, frozen, disconnected, viewer_read_only, account_read_only (the panel notice), live_not_enabled (`rbac.env`), live_locked (a LIVE submit while the arm store is locked / unknown — T2 with `arm.locked`'s description, E30-D04 §2.5), and the arm triple `locked | armed | unknown` from CMP-229 (E30-D02 A-8; the inventory is E30-D02 §10).
- **A11y**: the submit confirms through CMP-044 ConfirmDialog per the SCR-114 confirmation policy (E30-D03 D9; LIVE always confirms); when armed, submit still requires an explicit press (never fires from focus/hover) and shows the persistent "1-click ARMED" text+icon indicator per §3.1.5 — CMP-229 in `scope: "global"`; rejection reason rendered via CMP-027 `role="alert"`; the panel is a `role="region"` named "Order ticket - {symbol} - {env} - {account}"; every role-, environment- or state-gated control is E09-D09 §2.2 T2 (view-as first, the account leg ahead of the guards; CMP-079 RbacGate, CMP-019 `lock`), a form-validity block is the E30-D04 §2.5 validity look; banners: `role="alert"` once for filled / partially filled, rejected, disconnected and the protective-stop banner, `role="status"` for accepted-not-yet-filled, pending-key and stale.
- **Tokens**: inherits children; `color.buy.default` / `color.sell.default` with `color.text.inverse` on the submit button per side (the progress strip `color.text.inverse`, a 3 px `::before` along the bottom edge — E30-D04 M1); `color.status.success.subtle` / `color.status.danger.subtle` (banners); `color.surface.canvas` (panel), `color.surface.app` (wells); `radius.card`, `space.inset.sm`, `space.stack.sm`.
- **API sketch**: `interface OrderTicketProps { symbol: string; side: "buy" | "sell"; orderType: string; price?: number; qty: number; accounts: AccountMultiSelectProps["accounts"]; tpSl?: { tpMode: "ticks" | "pct" | "r" | "price"; tpValue: number; slMode: "ticks" | "pct" | "price"; slValue: number }; oneClickArmed: boolean; onSubmit: (draft: OrderDraft) => void; env: "demo" | "live" }`
- **Data contract**: on submit, posts an `OrderDraft` to the order-placement REST endpoint (Bybit `/v5/order/create` proxied through the backend per account); `submitted-ack`/`rejected`/`rate-limited` states are driven by the REST response and the order-update WS stream per `14-screens-catalogue.md` §0.4; the arm state from `POST /settings/arm`; the stop state from the WS `positions` `native_stop_present` and the order machine's `regions.protection` tag (`protected` / `naked`, `23`).
- **Storybook**: Ready, Validating, InvalidSummary, Submitting, AwaitingConfirmation, Accepted, PartiallyFilled, RejectedCorrectable, RejectedLimit, RejectedTransient, RejectedExchange, OneLotMismatch, BlockedByProfile, BlockedByProfileT2, BlockedByLockout, Frozen, Disconnected, ReturnedFromDisconnect, PendingKey, ViewerReadOnly, ViewAsReadOnly, AccountReadOnly, LiveNotEnabled, LiveLocked, Locked, Armed, Unknown, HotkeysPaused, StaleHelpers, StaleWallet, PreviewInFlight, ReduceOnly, ProtectiveStopPending, Demo, Live, Comfortable, HighContrast, ReducedMotion.
- **Tests**: unit, visual, axe, keyboard; the native-SL assertion on every submit path; the RBAC-disabled test; the submit lifecycle test (width locked, a second press does nothing and says so, the banner at frame 0); the reduce test; the live-region hygiene test.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §9 (E30-D04; owner approval pending); the screen: [E30-D02.md](../design/E30/E30-D02.md).

### CMP-108 DomLadderRow

- **Tier**: Molecule (trading, canvas-adjacent) · **Purpose**: one price row of the DOM ladder — price, bid/ask size bars, own-order markers, click-to-trade.
- **Props**: `price: number` · `bidSize?: number` · `askSize?: number` · `isBestBid?/isBestAsk?: boolean` · `ownOrders?: OwnOrderMarker[]` · `onClickBuy/onClickSell/onDragReprice/onCancel`.
- **A11y**: implemented as a real focusable DOM row (`role="row"` inside `role="grid"` ladder) even though visually rendered on a canvas-adjacent surface — this is a DOM row, not a canvas primitive, specifically so it's natively accessible; `aria-label` composes "Price 65,432; bid size 1.2; ask size 0.8; your buy order 0.5 at this price"; roving-tabindex up/down navigates rows, `Enter`=buy (configurable), `Shift+Enter`=sell, `Delete`=cancel own order at row.
- **Tokens**: `color.buy/sell`, `font.mono`, `color.surface.ownorder`.
- **API sketch**:

```ts
interface DomLadderRowProps {
  price: number;
  bidSize?: number;
  askSize?: number;
  isBestBid?: boolean;
  isBestAsk?: boolean;
  ownOrders?: Array<{ id: string; side: "buy" | "sell"; qty: number }>;
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
  price: number;
  bidVol: number;
  askVol: number;
  delta: number;
  isImbalanced?: boolean;
  inputSource: "aggTrades" | "numTrades" | "orderEstimated";
}
// Rendered by the WebGL engine; DOM-mirror node generated 1:1 per visible cell:
interface FootprintCellMirrorProps extends FootprintCellData {
  onFocus: () => void;
  onActivate: () => void; // Enter -> detail drawer
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

- **Tier**: Chart-primitive (trading) · **Purpose**: the big-trade mark on the chart — a disc (buy) or a square of equal area (sell) sized by notional under a bounded law, with an age band, an above-cap label or outline, a cluster count badge, a sparse DOM mirror and a CMP-197 tooltip; the legend row is CMP-199's.
- **Props**: `time` · `price` · `notional` · `side: "buy"|"sell"` · `sizeScale: "sqrt"|"log"|"linear"` (`sqrt` = the area-linear law, the default) · `shape: "circle"|"square"|"diamond"|"text"` — buy → `circle`, sell → `square` of equal area; `diamond` available, unused by SCR-053; `text` = the above-cap label mode · `rMinPx` (3) · `rMaxPx` (24) · `ageBand: "fresh"|"aged"` · `capped: boolean` · `clusterSize?: number` (≥ 2 shows the badge) · `estimated?: boolean` (clusters).
- **A11y**: DOM-mirror marker (sparse — big trades are inherently low-frequency, so full per-marker mirroring is affordable, unlike the heatmap) with `aria-label` "Big sell, 42,000 USDT, 65,410, 14:32:01"; the format is fixed as `"Big {side}, {notional} USDT, {price}, {time}"`; a cluster node reads `"Cluster of {n}, {notional} USDT, {side}, {time}, estimated"` (PROPOSED: D02 Table 3's name plus the literal word, D03-C10); the abbreviated notional expands per CMP-020 in both names (`1.2M` → "1,200,000", `1.9M` → "1,900,000"); each node is a `button`, `Enter` locates and moves focus to the plot (D02 Table 2), focus shows the CMP-197 tooltip, `Esc` dismisses it; the badge's name carries the literal word "estimated".
- **Tokens**: `color.buy.default` / `color.sell.default` (fills; `.hc` via the theme), `color.cvd.buy` / `color.cvd.sell` (the CVD palette), `color.text.inverse` (the ▲ / ▼ glyph), `type.num.xs` (the glyph's fixed 10 px box, bold), `color.text.primary` (label, badge), `color.surface.canvas` (the halo), `opacity.bubble.aged` (PROPOSED, CR-1), `type.num.sm`, `border.thick`, `space.1`, `color.focus.ring` + `border.focus`; `size.bubble.scale` retired in favour of `rMinPx` / `rMaxPx`.
- **API sketch**: `interface BigTradeBubbleProps { time: number; price: number; notional: number; side: "buy"|"sell"; sizeScale: "sqrt"|"log"|"linear"; shape: "circle"|"square"|"diamond"|"text"; rMinPx: number; rMaxPx: number; ageBand: "fresh"|"aged"; capped: boolean; clusterSize?: number; estimated?: boolean; }`
- **Data contract**: driven by the engine's `BigTradeEvent` / `TradeClusterEvent` once E22-T02 echoes them on `trades.{symbol}`; never a client-side threshold; no REST dependency.
- **Storybook**: `ChartEngine/BigTradeBubble` — Circle, Square, Diamond, TextMode, LogScale, SqrtScale, LinearScale, Aged, Capped, CappedOutline, Clustered, ClusterBadgeSmall, Hover, FocusVisible, Stale, Hidden, LodShed, CvdPalette, HighContrast, Light, Greyscale, ReducedMotionIdentical.
- **Tests**: unit, visual, axe (mirror), interaction (hover/focus detail tooltip), the one-draw-call assertion (`bench/bubbles-sdf-labels`), the shape-carries-side assertion in greyscale, the `aria-label` format test, the "(estimated)" word test on cluster tooltips and the legend row, the aged-band contrast assertion (≥ 3:1 on the canvas in three themes).

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
  id: string;
  accountId: string;
  symbol: string;
  side: "long" | "short";
  size: number;
  entryPrice: number;
  markPrice: number;
  liqPrice: number;
  unrealizedPnl: number;
  leverage: number;
  marginMode: "cross" | "isolated";
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
  id: string;
  symbol: string;
  side: "buy" | "sell";
  type: string;
  price?: number;
  qty: number;
  filledQty: number;
  status: "working" | "partially_filled" | "filled" | "cancelled" | "rejected";
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

- **Tier**: Molecule (trading, risk-critical) · **Purpose**: the lockout (B20) or frozen (B18) notice for one account, one manager or every account — on SCR-071 (owner), at the top of the manager's terminal (SCR-073) and locally on any affected order ticket; it says in one sentence what was done and what was NOT done, when it ends and what still works (E39-D01 D1 / D5; hi-fi contract `docs/design/E39/E39-D02.md` §5).
- **Props**: `scope: "account"|"manager"|"global"` · `reason: string` (full text, never a code) · `until?: number` (epoch ms — the server's `until`, rendered and never computed client-side; absent = open-ended) · `onOwnerOverride?` (owner-only unlock). PROPOSED by E39-D02 §5, owned by E39-S04 (additive, optional): `kind?: "locked"|"frozen"` · `reasonCode?: "daily_loss"|"consecutive_losses"|"max_positions"|"manual"` · `since?: number` · `acknowledgedAt?: number` + `onAcknowledge?` · `overrideRequestedAt?: number` + `onRequestOverride?` · `facts?: {threshold, actualValue, actionsTaken}` (target, OD-12).
- **Variants**: `scope` account / manager / global × `kind` locked (B20) / frozen (B18) × time-boxed (`until` set; CMP-035 countdown "until 00:00 UTC (in 9 h 58 m)") / open-ended (`until` NULL: "until the owner releases it; no clock will clear it") × override available (owner: "Override lockout…") / requestable (manager: "Ask the owner for an override") / requested ("Override requested at 13:52 UTC — waiting for the owner") / acknowledged ("Read at 13:43 UTC"); the owner (account) scope on SCR-071 carries a restatement line (account label + CMP-075) and a body ending with the owner's action (E39-D02 S21); a `max_positions` cap refusal renders as `role="status"` with no clock and no override (E39-D01 OD-15) and the bar + "CAP" glyph + word (PROPOSED, E39-D02 C23).
- **States**: appearing (a cut; the single assertive announcement is CMP-212's `role="alert"` region — `docs/design/a11y/e40-alerts-a11y-review.md` LR-0 / LR-5) · persistent (the same named `role="region"`, never re-created; no dismiss control while the condition holds) · acknowledged · requested · cleared (assertive once, only after the authoritative re-read; with or without the D-4 allowance sentence; `role="status"`, dismissible once cleared) · expired (`role="status"`; dismissible) · frozen (role-neutral; no close / reduce promise — E39-D01 OD-11).
- **A11y**: a named `role="region"` from its first frame — the lockout's one assertive announcement is CMP-212's, never a second live node (E40-D01 LR-0 / LR-5; this is how SCR-073's "`role="alert"` on appearance" is met); **never dismissible while the lockout holds** (`Esc` never dismisses it); reason always full text (not a code); the countdown is CMP-035 (`aria-live="off"`, polite at 60 s / 10 s / 0 s); the override action is owner-only and step-up gated (SCR-006 composed via CMP-044; `04-security-program.md` SR-025) — a manager sees "Ask the owner for an override", a viewer the disabled-with-reason control (`docs/design/E09/E09-D09.md` §2.2 T2: CMP-079 RbacGate wraps it, CMP-019 Icon `lock` "Not available" leads the full label, `aria-disabled` + `aria-describedby`, never hidden); under a B20 lockout the surrounding close / reduce, cancel and stop-tightening controls stay enabled and in the Tab order (`14-screens-catalogue.md` §0.5 item 5; E39-D01 D10; `24-internal-schemas.md` §8.10).
- **Tokens**: `color.status.danger.{subtle,default,strong}`, `color.status.warning.{subtle,strong}`, `color.status.success.{subtle,strong}`, `color.text.{primary,secondary,tertiary}`, `color.focus.ring`, `radius.card`, `space.inset.md`, `size.control.height`, `type.ui.body-strong`, `type.ui.body`, `type.num.base`.
- **Data contract**: `GET /risk/summary` `RiskSummary.accounts[].{frozen, lockout{reason, since, until}}` and `kill_switch` (`22-api-openapi.yaml`) plus the machine topics `machines.risk_lockout:{account_id}.state` (B20) and `machines.kill_switch.state` (B18) (`23-ws-protocol.md` §6.4); the owner's override is `POST /risk/lockouts/{accountId}/override` (step-up; the response is a `RiskSummary`); the manager's request-override path has no route yet (E39-D01 OD-4). A lockout cancels only working orders that open or add exposure — position TP/SL and reduce-only stops are never cancelled (SR-E39-06); `threshold`, `actual_value` and `actions_taken` are `risk_lockouts` columns not yet in the client contract (OD-12).
- **Storybook**: AccountScope, ManagerScope, GlobalScope, TimeBoxed, OpenEnded, OwnerOverrideAvailable, OverrideRequestable, OverrideRequested, Acknowledged, Cleared, ClearedWithAllowance, Expired, ExpiredInDay, Frozen, CapRefusal, Compact, Comfortable, ReducedMotion.
- **Tests**: unit, visual, axe, live-region test (CMP-212 announces once; the banner is one region, never re-created; not dismissible while the lockout holds), RBAC test (override disabled-with-reason for a non-owner, never hidden; request only for a manager), close-stays-enabled test (a B20 lockout never disables the reduce-only close, the blotter's Cancel or the grid's stop-tightening amend — `24-internal-schemas.md` §8.10).

### CMP-118 AlgoProgressCard (emulated TWAP/Iceberg/Chase/Scaled)

- **Tier**: Molecule (trading) · **Purpose**: live progress of an emulated multi-slice algo order.
- **Props**: `algoType: "twap"|"iceberg"|"chase"|"scaled"` · `slicesDone` · `slicesTotal` · `avgFillPrice?` · `status` · `onPause/onResume/onCancelAll` · `emulated: true` (always, per safety-transparency — never hides that this is client-side emulation, not exchange-native).
- **A11y**: progress via CMP-023 ProgressBar contract, "(emulated)" text always visible not just in a tooltip.
- **Tokens**: inherits CMP-023.
- **API sketch**:

```ts
interface AlgoProgressCardProps {
  algoType: "twap" | "iceberg" | "chase" | "scaled";
  slicesDone: number;
  slicesTotal: number;
  avgFillPrice?: number;
  status: "running" | "paused" | "completed" | "cancelled" | "error";
  onPause: () => void;
  onResume: () => void;
  onCancelAll: () => void;
}
```

- **Data contract**: progress state sourced from the client-side emulated-algo execution engine's local state machine (TWAP/Iceberg/Chase/Scaled are client-emulated, not native Bybit order types), with each child order's fill state driven by the order-update WS stream.
- **Storybook**: Running, Paused, Completed, Error.
- **Tests**: unit, visual, axe, keyboard controls.

### CMP-119 BracketEditor (SL/TP attach widget)

- **Tier**: Molecule (trading) · **Purpose**: attach/edit stop-loss and take-profit on the order ticket or an existing position, the stop in ticks/%/price (R read out) and the take-profit in ticks/%/R/price, with native-exchange-SL guarantee messaging (safety invariant, `24-internal-schemas.md` §8.8; C-2.6). There is no stop toggle: "Stop-loss (required)" (E30-D02 D10).
- **Props**: `slMode: "ticks"|"pct"|"price"` · `tpMode: "ticks"|"pct"|"r"|"price"` · `slValue/tpValue` · `onChange` · `partialTpLevels?: {pct,rMultiple}[]` · `nativeSlConfirmed: boolean` (true only once a valid stop is resolved from the typed value, the profile ticks or the fallback — never a user toggle; the submit gate).
- **Variants**: ticket, existing position; reduce-only (the stop and TP rows collapsed to one sentence each).
- **States**: default (the source line: typed · "from your profile: {n} ticks" · "fallback 2 % — ATR warming up"), focus, rounded-away (the caption), wrong-side or empty stop (a drawn blocked state with the field outlined), TP on / off, reduce-only-collapsed, read-only (T2).
- **A11y**: FormSection (CMP-065) composition; the native-SL guarantee is rendered as a persistent, non-dismissible inline note (CMP-158, `role="note"`), not a one-time toast; the stop field's `aria-describedby` names the source and the holder ("held by Bybit (exchange)"); T2 per E09-D09 §2.2 on the section's controls (CMP-079 RbacGate; CMP-019 Icon `lock`).
- **Tokens**: inherits CMP-100/CMP-101; the unit radiogroup CMP-003 (`color.surface.raised` / `color.surface.selected`); `font.family.mono` + `type.num.sm` (the R read-out); `type.ui.label` (legend); `color.text.secondary` (source line); `color.status.danger.default` / `color.status.danger.strong` (the blocked state); `space.inset.sm`, `space.field.gap`.
- **API sketch**: `interface BracketEditorProps { slMode: "ticks" | "pct" | "price"; tpMode: "ticks" | "pct" | "r" | "price"; slValue: number; tpValue?: number; onChange: (b: Bracket) => void; partialTpLevels?: { pct: number; rMultiple: number }[]; nativeSlConfirmed: boolean }`
- **Data contract**: on save, posts SL/TP as conditional orders via the order-placement REST endpoint (`POST /orders` `stop_loss` / `take_profit` — `22`, `ResolvedLegParams.stop_loss_price`; the backend maps them to Bybit's `/v5/order/create` fields); live SL/TP order state tracked via the order-update WS stream; the stop rounds away from the entry per `24` §9.3.1.
- **Storybook**: Default, TypedStop, ProfileStop, FallbackStop, RoundedAwayCaption, WrongSideStop, PartialTpLadder, TpPriceMode, ReduceOnlyCollapsed, ReadOnlyT2, Comfortable, HighContrast.
- **Tests**: unit (unit conversions, away-from-entry rounding), visual, axe, keyboard, the native-SL assertion (no render path yields `nativeSlConfirmed` true without a resolved stop; no toggle in the DOM), the T2 test.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §10 (E30-D04; owner approval pending).
- **Design (hi-fi):** [E32-D03.md](../design/E32/E32-D03.md) §5 · [E32-D03-handoff.md](../design/E32/E32-D03-handoff.md) (E32-D03; owner approval pending; the four consumers, the T2 / validity split, the mode matrix, the per-step TP ladder rows and the risk restatement block, as deltas on E30-D04 §10).

### CMP-120 TrailingStopEditor

- **Tier**: Molecule (trading) · **Purpose**: configure fixed-offset/%/ATR/structure/MA-based trailing stop (per research digest 09 §3).
- **Props**: `mode: "fixed"|"pct"|"atr"|"structure"|"ma"` · `params: Record<string,number>` · `onChange` · `preview?: {currentStopPrice}`.
- **A11y**: mode switch via CMP-009 Select, params rendered via CMP-040 FormField set specific to mode.
- **Tokens**: inherits CMP-100.
- **API sketch**: `interface TrailingStopEditorProps { mode: "fixed"|"pct"|"atr"|"structure"|"ma"; params: Record<string, number>; onChange: (cfg: TrailingStopConfig) => void; }`
- **Data contract**: trailing logic runs client-side (or via backend-scheduled job for closed-app resilience per owner decision) against the mark-price WS stream, re-submitting stop-order amendments via the order-amend REST endpoint as the trail advances.
- **Storybook**: Fixed, Percentage, ATR, Structure, MovingAverage.
- **Tests**: unit, visual, axe.
- **Design (DS spec):** [E32-D05-handoff.md](../design/E32/E32-D05-handoff.md) (E32-D05; owner approval pending).

### CMP-121 RiskCalculatorPanel

- **Tier**: Molecule (trading) · **Purpose**: derives position size from account equity, risk %, and stop distance — feeds QtyInput's `risk_based` sizing mode; its result is the ticket's read-out line ("= {notional} USDT · {pct} % eq · risk {risk} USDT ({riskpct} %) · 1 R = {risk}", E30-D02 D7).
- **Props**: `equity` · `riskPct` · `stopDistance` · `resultQty` (computed, read-only display) · `onApply` · per row `freshness?: DataConfidenceState` (CMP-239 beside wallet-fed values) and `estimated?: boolean` (CMP-227 `inline` `sm` on estimated rows).
- **Variants**: the read-out line (one line, compact); the preview block (CMP-036 rows, E30-S06).
- **States**: default, computing (≤ 8 ms, no spinner), value-changed (the value-change highlight, E30-D04 M5), provisional (the client's number under the hatch), stale-wallet (CMP-078 shade + the age), zero-stop-distance (error row), read-only (T2 on "Apply" — E09-D09 §2.2: CMP-079 RbacGate on the role legs, CMP-019 Icon `lock` leading "Apply"; the rows static text).
- **A11y**: computed result is a live-region-announced KeyValueRow (CMP-036) — one polite region at ≤ 1 update per 2 s, latest value only, never per tick; "Apply" button pushes value into the ticket; T2 per E09-D09 §2.2 on "Apply" (CMP-079 RbacGate; CMP-019 Icon `lock`, `decorative=false`, "Not available").
- **Tokens**: `font.family.mono` + `type.num.sm` (every value, right-aligned, tabular figures), `color.text.primary` (values), `color.text.secondary` (labels), `color.status.info.subtle` (the highlight overlay at peak 0.25), `color.border.strong` (the provisional hatch texture), `space.row.height.compact` / `space.row.height.comfortable`.
- **API sketch**: `interface RiskCalculatorPanelProps { equity: number; riskPct: number; stopDistance: number; resultQty: number; onApply: (qty: number) => void }`
- **Data contract**: pure client-side calculation from `equity` (account-equity WS/REST feed), user-entered `riskPct`, and `stopDistance`; the authoritative numbers arrive from `POST /trade-groups/preview` and replace the client's with the highlight; no independent WS/REST call of its own.
- **Storybook**: Default, ZeroStopDistance(error state), ValueChangeHighlight, Provisional, StaleWallet, EstimatedRows, ApplyReadOnlyT2, Comfortable, HighContrast, ReducedMotion.
- **Tests**: unit (calc formula), visual, axe, the cadence test (≤ 1 announcement per 2 s under a 10 Hz feed), the highlight spacing test (≥ 500 ms per cell; the 1 Hz / 10 s stop), the reduce twin test, the teardown test, the T2 test on Apply.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §11 (E30-D04; owner approval pending).

### CMP-122 QuickSizeButtons ("size ladder" presets)

- **Tier**: Molecule (trading) · **Purpose**: row of quick quantity/%-equity preset buttons (hotkey-bindable per digest 09 §1); presets set the size in every arm state — sizing is preparation, not execution (E30-D02 A-18).
- **Props**: `presets: {label,value}[]` · `activeValue?` (derived by the host from the current size) · `onSelect` · `hotkeyHints?: string[]` · `minQty?: number` (a preset below it is `aria-disabled` with "min {min}").
- **Variants**: quantity presets, %-equity presets (the resolved quantity shown); with / without hints.
- **States**: default, active (`color.surface.selected` + ✓ + "active" in the name), hover, focus-visible, below-minimum (the validity look of E30-D04 §2.5: own fill and label at `opacity.disabled`, the minimum beside it, focusable, no lock), read-only (T2).
- **A11y**: CMP-003 SegmentedControl-like group of native buttons named "{label} — preset {n}" with `aria-pressed`; hotkey hints shown via CMP-022 Kbd inline; `1`..`4` act only while the ticket region has focus and no text field is active; T2 per E09-D09 §2.2 on the group (CMP-079 RbacGate; CMP-019 Icon `lock` leading the group).
- **Tokens**: inherits CMP-001 (`color.surface.raised`, `color.surface.selected`, `color.surface.hover`, `color.text.primary`, `radius.control`, `space.button.paddingX`); CMP-022 (`color.surface.raised`, `radius.xs`, `font.family.mono`); `color.focus.ring`; `opacity.disabled` (the validity look only).
- **API sketch**: `interface QuickSizeButtonsProps { presets: { label: string; value: number }[]; activeValue?: number; onSelect: (v: number) => void; hotkeyHints?: string[]; minQty?: number }`
- **Data contract**: `presets` are user-configured client-side/local-settings values (persisted via the settings REST endpoint); no live WS dependency.
- **Storybook**: Default, WithHotkeyHints, ActiveDerived, PercentPresets, BelowMinimumValidity, ReadOnlyT2, Locked, Comfortable, HighContrast.
- **Tests**: unit (the derived active preset; the minimum rule), visual, axe, keyboard (digit scoping; suppressed in text fields), the validity-look press test, the T2 test.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §12 (E30-D04; owner approval pending).

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
  groupId: string;
  symbol: string;
  side: "buy" | "sell";
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

- **Tier**: Atom (trading) · **Purpose**: estimated slippage/impact preview for a given order size against current book depth; composes the bps value, the CMP-032 confidence dots and CMP-227 EstimatedBadge (`inline`, `sm`) — the one estimated treatment (E30-D04 §2.4).
- **Props**: `estimatedSlippageBps: number` · `confidence: "low"|"medium"|"high"` (reuses CMP-032 Rating dots) · the badge's subject (CMP-227's key; see E25-D05 and E30-D04 A19).
- **Variants**: footer chip on a market order ("slippage ≈ {n} ticks (estimated)"), the est. slip row of the preview.
- **States**: default (low / medium / high), badge hover / focus-visible / tooltip-open (CMP-227), stale-book (CMP-239 beside the value), absent (no book snapshot: the chip is absent).
- **A11y**: the methodology opens from CMP-227's native button ("Estimated, slippage[, {confidence} confidence]", `aria-haspopup="dialog"`, `aria-describedby` → the tooltip); the confidence word is always present beside the dots; two accessible names in the composition; never colour, icon or opacity alone.
- **Tokens**: `color.surface.raised` + `radius.pill` (the host chip), `font.family.mono` + `type.num.sm` + `color.text.primary` (the value), CMP-032's dots, CMP-227's `color.status.info.subtle` / `color.status.info.default` / `radius.badge`, `space.inset.xs` (composition gaps).
- **API sketch**: `interface SlippageEstimateChipProps { estimatedSlippageBps: number; confidence: "low" | "medium" | "high" }`
- **Data contract**: estimate computed client-side from the current orderbook WS snapshot (walking the book for the entered qty) at order-entry time; not a Bybit-provided field.
- **Storybook**: Low, Medium, High, FocusVisibleBadge, TooltipOpen, StaleBook, Absent, Comfortable, HighContrast, Greyscale.
- **Tests**: unit, visual, axe, the composition test (two accessible names; "estimated" in the badge's name), the greyscale assertion.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §13 (E30-D04; owner approval pending); the badge: [E25-D05.md](../design/E25/E25-D05.md) §4.

### CMP-131 SpeedOfTapeGauge

- **Tier**: Molecule (trading, chart-adjacent) · **Purpose**: rolling trades/sec and notional/sec readout with a gauge and a strip chart; the text readout is the first-class element, never a tooltip (`docs/design/E25/E25-D05.md` §5).
- **Props**: `tradesPerSec: number | null` · `notionalPerSec: number | null` · `windowSec: 1|5|30` (default 5) · `primaryUnit: "trades"|"notional"` (default `trades`) · `sideSplit?: {buy, sell}` · `zScore: number | null` · `band: "calm"|"elevated"|"extreme"|null` (pushed by the backend with its hysteresis and ≥1 s dwell applied there; extreme = the alert threshold `z > 3`) · `baselineWindowSec` (from the series `params` echo; the readout names it) · `baselineStat: "mean"|"median"` (a PROPOSED key of the `params` echo; the readout's last word — E25-D01 Q13, E25-D05 §17 Q10) · `warmupRemainingSec?` · `state: "loading"|"warming"|"live"|"delayed"|"idle-zero"|"stale"|"disconnected"|"error"` · `throttleMultiplier?: number` (`connection_quality.applied`; `delayed` only — E17-D01 D5) · `peakSinceReset?: {value, atMs}` (the Q13 display lever, PROPOSED) · `mode: "gauge"|"strip"|"number"` · `alertThreshold?: number` (z).
- **Variants**: `mode` gauge / strip / number (the composite shows all three); side split; the peak marker (`peakSinceReset`: a 2 px `color.text.secondary` tick on the arc and the caption "peak 61/s · 14:02" — decorative chrome, the caption carries it; PROPOSED, E25-D05 §5.3).
- **States**: loading ("Loading…"), warming ("Warming up — 4 min 52 s to go": the remaining time, never the elapsed), live with the band word calm / elevated / extreme (the band is pushed by the backend with its hysteresis — extreme in at `z > 3`, out below the elevated edge — and a ≥1 s dwell applied there, so the chip, the segment and the word flip at most once per second and the component never classifies; PROPOSED, E25-D05 §5.2), delayed (the exact value stays live, needle and strip step at the applied cadence, the tag "Updates every 1 s, ×4 slower" from `connection_quality.applied` beside the readout, shown ≥5 s, polite once on entry and exit — E17-D01 D5 / T3 / §7), idle-zero ("0 /s · quiet", never the last value held), stale ("—" + CMP-239 "Stale 12s"), disconnected ("—" + the panel's CMP-028 banner), error ("Detector error — last value 13:58:02"), focus-visible (the window control's segment or the alert affordance; the ring never clipped), hc, reduced-motion.
- **A11y**: the readout "42 trades/s over 5 s · 3.1 σ above the 5-min mean" (the last word is `baselineStat`'s) is the panel's primary accessible value (`aria-live="off"`); the Delayed tag is text beside it; numeric values always shown as text beside the needle position (never gauge-angle-only); the band is a word on a chip (CMP-011, not CMP-227 — the metric is exact) plus the needle's position on a stepped scale and a thicker extreme segment, never hue alone; band crossings announced politely from the panel's one `role="status"` region at most once every 5 s; digits swap at ≤2 Hz, the needle and the strip step at 4 Hz with nothing animated; the window control is CMP-003 (roving `←`/`→`); table alternative via `Alt+T`. Pattern (hollow, dashed, hatched) marks estimated or absent, never a side (E25-D01 §9.5, PROPOSED for `16` §6; binding today under `16` §6 rules 1 and 5): the usual-rate reference line is solid.
- **Tokens**: `font.family.mono`, `type.num.lg`, `type.ui.label`, `type.ui.caption`, `color.text.primary/secondary/tertiary`, `color.surface.raised`, `color.border.strong` (the track, decorative), `color.border.default`, `color.status.warning.default` + `color.status.warning.subtle` (extreme, always with the word; on the panel the outline and the segment measure 7.98 / 2.9992 / 7.98 and are decorative — the word and the 2 px thicker segment carry the band), `color.buy.default`/`color.sell.default` (side split), `border.thick`, `space.inset.sm/md`.
- **API sketch**: `interface SpeedOfTapeGaugeProps { tradesPerSec: number | null; notionalPerSec: number | null; windowSec: 1 | 5 | 30; primaryUnit?: "trades" | "notional"; sideSplit?: { buy: number; sell: number }; zScore: number | null; band: "calm" | "elevated" | "extreme" | null; baselineWindowSec: number; baselineStat: "mean" | "median"; warmupRemainingSec?: number; state: "loading" | "warming" | "live" | "delayed" | "idle-zero" | "stale" | "disconnected" | "error"; throttleMultiplier?: number; peakSinceReset?: { value: number; atMs: number }; mode: "gauge" | "strip" | "number"; alertThreshold?: number; }`
- **Data contract**: computed **backend-side** and pushed on `metrics.{symbol}` at 4 Hz (`MetricsUpdate` series items `trades_per_sec`, `volume_per_sec`, `tape_acceleration`; `GET /market/metrics` for history); the window, the baseline and the PROPOSED `baselineStat` come from the per-series `params` echo (E25-D05 G7); the `band` is pushed with its edges, hysteresis and dwell applied backend-side (PROPOSED, E25-D05 G4); `connection_quality.applied` drives `delayed` (E17-D01 D5); the shipped ids are `tape_speed` / `tape_speed_zscore` (shared: XG-METRICCODE, E25-D05 G3); never a client recompute over `trades.{symbol}` (E25-D01 C6). Exact data: no `(estimated)` chip.
- **Storybook**: Gauge, Strip, Number, Composite, WindowOneSec, WindowFiveSec, WindowThirtySec, SideSplit, BandCalm, BandElevated, BandExtreme, WarmingUp, IdleZero, Loading, Stale, Delayed, Disconnected, DetectorError, HighWaterMarker, FocusVisible, AlertAffordanceDisabled, LongReadout, HighContrast, ReducedMotion, BandFlapGuard.
- **Tests**: unit, visual (three themes × two densities), axe, throttled-announcement test (≤1 per 5 s), digits-≤2-Hz test, band-flap guard (a render test over a pushed sequence: ≤1 band flip per second at a 4 Hz oscillation; the backend's hysteresis / dwell is a contract test), focus-visible at compact density (the ring unclipped), performance budget (SCR-055: 1 ms at ≤4 Hz), table-alternative parity.

### CMP-132 ImbalanceStackIndicator

- **Tier**: Chart-primitive (trading) · **Purpose**: on-chart mark for a stacked/diagonal imbalance zone (Imbalance Tracker) with its status active / tested / broken; exact data (`docs/design/E25/E25-D05.md` §6).
- **Props**: `id` (the zone id focus follows) · `zone: {priceFrom, priceTo, barsExtent}` · `direction: "bid"|"ask"` (rendered ▲ BUY / ▼ SELL: glyph + word + hue, never hue alone) · `depth: number` ("×4") · `ratio: number` (percent, "420 %"; spoken "ratio 4.2 to 1") · `age` ("13:58 (12 m)") · `status: "active"|"tested"|"broken"` (mapped from `imbalance_zone_mitigated` / `imbalance_zone_retest_count`: not mitigated and never retested = active, not mitigated and retested = tested, mitigated = broken — E25-D01 F14; the former `virgin`/`crossed` pair is retired) · `distanceTicks?` ("150 ticks below") · `estimated?: boolean` (default false; inherited from a resyncing book, `25` §1) · `selected?` (the SCR-056 cross-highlight).
- **Variants**: `status` active / tested / broken × `direction` bid / ask.
- **States**: active (solid 1 px outline in the side hue over the `.subtle` fill), tested (dashed outline in the side hue, fill at `opacity.muted` — a status, never a side; E25-D05 C17), broken (no side fill; a neutral `color.text.tertiary` hatch, 45°, 6 px pitch, clipped to a `color.border.default` outline, device-snapped — E11-D02 §4.4), selected (+2 px `color.border.selected`), inherited-estimated (+ the CMP-227 `marker` affordance at the left edge, ", estimated" appended in the mirror, the `inline` chip on the row), focus-visible, hc (fills change, patterns do not), greyscale.
- **A11y**: DOM-mirror surrogate per visible zone (CMP-195's contract) with `aria-label` "Sell stack ×3, 64,060 to 64,090, ratio 310 percent, tested, 350 ticks above"; the surrogates are one roving stop per pane ordered nearest-first, `↑`/`↓` between zones, `Enter` selects the matching SCR-056 row and cross-highlights, `Esc` back to the plot; the cross-highlighted surrogate carries `aria-current="true"` (never `aria-selected`); focus follows the zone id through a re-rank and never moves on a push; surrogate ≥24×24 CSS px. Every prop has a text carrier in the row and the mirror; no hover state by design (parity by construction). Pattern (hollow, dashed, hatched) marks estimated or absent, never a side (E25-D01 §9.5, PROPOSED for `16` §6; binding today under `16` §6 rules 1 and 5): the pattern carries `status`; the glyph, the word and the hue carry `direction`.
- **Tokens**: `color.buy.default`/`color.sell.default` (outline), `color.buy.subtle`/`color.sell.subtle` (fill), `color.text.tertiary` (hatch ink — `color.border.strong` measures 1.91 / 1.57 / 1.91 on the canvas and fails 1.4.11 for a meaning-carrying pattern), `color.border.default`, `color.border.selected`, `opacity.muted`, `border.hairline`, `color.focus.ring`; pattern ids `pattern.dashed.estimated` (the CMP-227 marker), `pattern.dashed.tested` and `pattern.hatch.absent` (E25-D05 CR-1, PROPOSED; `pattern.hatch` is not a token). The hatch is +1 draw call per pane (E11-D02 D19); the dashed outline is a stroke style.
- **API sketch**: `interface ImbalanceStackIndicatorProps { id: string; zone: { priceFrom: number; priceTo: number; barsExtent: number }; direction: "bid" | "ask"; depth: number; ratio: number; age: number; status: "active" | "tested" | "broken"; distanceTicks?: number; estimated?: boolean; selected?: boolean; }`
- **Data contract**: zone events computed **backend-side** and appended on `metrics.{symbol}` (SCR-056: a bounded 2,000-event ring buffer, ≤4 Hz, 1.5 ms): the shipped exact codes `nearest_imbalance_zone_distance`, `imbalance_zone_side` / `_strength` / `_mitigated` / `_retest_count` (none is a `MetricCode` member — shared: XG-METRICCODE, E25-D05 G3; the per-zone item shape is G8). Imbalance is **exact** (`24` §7.2; the shipped vocabulary): **no `(estimated)` chip** unless an input carries `estimated=True` (`25` §1 Derived); `imbalance_hold_rate`'s scoreboard chip is E25-D01 C18's, not this component's.
- **Storybook**: ActiveBuy, ActiveSell, TestedBuy, TestedSell, BrokenBuy, BrokenSell, Selected, InheritedEstimated, FocusVisible, HighContrast, Greyscale.
- **Tests**: unit, visual, axe (mirror), DOM-mirror parity, keyboard (roving, `Enter`, `Esc`), performance budget.

### CMP-133 RegimeIndicatorChip

- **Tier**: Atom (trading) · **Purpose**: the market-regime classification chip, always `(estimated)`: the L3 form "Trending up (estimated) · medium" over an evidence row led by the labelled number (E25-D01 R3; `docs/design/E25/E25-D05.md` §7).
- **Props**: `regime: "trending_up"|"trending_down"|"ranging"|"volatile_expansion"|"compression"` (`22` `RegimeExplanation.regime`, rendered through one display-label map — Trending up / Trending down / Ranging / Volatile / Calm — never a raw enum token; the enum itself is the owner's, E25-D01 C8) · `confidence: number | null` (0..1; optional in `22`) · `warmup?: {have, need}` (the hurst window in force, from the `params` echo) · `signals?: string` (sub-signal text appended to the confidence line) · `confidenceLabelId?: string` (an adjacent element that already renders the labelled number; then the component omits its own line and points `aria-describedby` at it) · `size: "sm"|"md"`.
- **Variants**: the five regimes.
- **States**: default, hover, focus-visible, confidence-absent (chip "Trending up (estimated)", cell "Confidence — not supplied"), insufficient-data (chip "Insufficient data (estimated)", cell "210 of 512 bars"), hc, greyscale.
- **A11y**: the chip **is** the badge's host — the only host today: one native `<button>` consuming CMP-227's provider through the `EstimatedBadgeHost` context, which requires a button whose activation calls `openMethodology(detector)` and throws otherwise (E25-D05 §7.4), accessible name starting with the visible text (WCAG 2.2 SC 2.5.3) "Trending up (estimated) · medium — market regime, medium confidence", `Enter`/`Space` opens SCR-058 at the regime section (focus to its heading and back on close), `Esc` closes the tooltip; the chip text is ≤40 characters on one line and the label and "(estimated)" are never truncated; the confidence word on the chip and the labelled number rendered by the component itself ("Confidence 0.71 (sub-signal agreement)", a CMP-036 row; `confidenceLabelId` points at an adjacent one instead) beside CMP-032's dots — a standalone chip never shows the word without the number, never a bare number beside the direction word; regime colour is never `color.buy.*`/`color.sell.*`, no direction arrow in a side hue, no imperative verb; ≤1 Hz, rendered only on change, the change announced politely once (≤1 per 5 s). Pattern (hollow, dashed, hatched) marks estimated or absent, never a side (E25-D01 §9.5, PROPOSED for `16` §6; binding today under `16` §6 rules 1 and 5): low-confidence strip segments are dashed.
- **Tokens**: CMP-227's — `color.status.info.subtle`, `color.status.info.default`, `color.text.primary`, `radius.badge`, `type.ui.caption`/`type.ui.label`; `type.num.base` for the evidence number.
- **API sketch**: `interface RegimeIndicatorChipProps { regime: "trending_up" | "trending_down" | "ranging" | "volatile_expansion" | "compression"; confidence: number | null; warmup?: { have: number; need: number }; signals?: string; confidenceLabelId?: string; size?: "sm" | "md"; }`
- **Data contract**: computed **backend-side**: `regime` on `metrics.{symbol}` (shipped `market_regime` and `hurst`, both `estimated`; shared: XG-METRICCODE, E25-D05 G3) and `GET /market/regime/explain` (`RegimeExplanation`: `regime`, optional `confidence` 0..1, `signals[]`), fetched once per change; the hurst window from the `params` echo (512 shipped, 256 in `22` — E25-D01 C16); the 0..1 → low / medium / high bands are PROPOSED (E25-D05 G5). Always rendered as the `(estimated)` badge (E25-D01 C6).
- **Storybook**: TrendingUp, TrendingDown, Ranging, Volatile, Calm, LowConfidence, MediumConfidence, HighConfidence, ConfidenceAbsent, InsufficientData, Hover, FocusVisible, LongLabelGuard, HighContrast, Greyscale.
- **Tests**: unit (the display map; the ≤40-character guard; the host's accessible name; the number renders whenever `confidence` is non-null), visual, axe, keyboard, copy lint (no imperative verb).

### CMP-134 DetectorEventCard (iceberg/stop-run/absorption)

- **Tier**: Molecule (trading) · **Purpose**: card describing one heuristic detector event — the `(estimated)` chip first and mandatory, the parameter snapshot in force, observed vs inferred copy — used in the SCR-056 event feed and journal auto-tags (`docs/design/E25/E25-D05.md` §8).
- **Props**: `detectorType: "iceberg"|"stop_run"|"absorption"|"exhaustion"|"big_trade"|"regime"|"unfinished_auction"` (`DetectorMethodology.detector` plus `unfinished_auction`, E25-D05 G2) · `time` · `price` · `side?: "buy"|"sell"` · `confidence: number | null` · `params: Record<string, number | string | boolean>` (the `DetectorConfig` names in force at detection — `window_ms`, `min_reloads`, `price_tolerance_ticks`, `lookback_bars`, `penetration_ticks`, `reversal_pct`, `min_volume_multiple`, `max_price_move_ticks`, `min_delta_divergence`; shared: XG-DETECTORCONFIG, E25-D05 G4) · `observed: string` · `inferred: string` · `unknown?: string` · `freshness?: DataConfidenceState` · `presentation?: "static"|"flat"` (default `static`) · `state?: "live"|"detector-off-flag"|"detector-off-user"|"error"` (default `live`; stale rides on `freshness`; loading / empty are list states) · `selected?` · `actions?` · `onOpen`. The chip is not a prop: it cannot be omitted.
- **Variants**: `detectorType` × `presentation` (`static`: `elevation.card`; `flat`: a 1 px `color.border.default` border, no shadow, no transition — for ≤4 Hz lists).
- **States**: static, flat, stale (CMP-239 after the chip, ≥4 px), selected, focus-visible, detector-off-flag ("Not available on this server — the stop-run detector is behind a feature flag"; the platform flag wins), detector-off-user ("Off — turn on in Detector settings"), error ("Detector error — last value 13:58:02"), loading and empty (list states), hc, reduced-motion.
- **A11y**: Card (CMP-050) composition with **CMP-227 `inline` mandatory as the first element**, then CMP-239 when stale, then the header (detector name, time, price, ▲ BUY / ▼ SELL glyph + word); `article` inside a `role="feed"` (WAI-ARIA APG Feed: `aria-labelledby` → the header sentence, `aria-describedby` → the chip, the freshness marker and the copy, `aria-posinset`/`aria-setsize`, `tabindex="0"`; the feed `aria-busy` only during a batch insert): `↑`/`↓` and `Page Up`/`Page Down` between cards, `Home`/`End` to the first / last loaded card, `Ctrl+Home`/`Ctrl+End` leave the feed, `Enter` opens the detail, `Tab` enters the chip then `actions` (a feed's articles are in the Tab sequence), `Esc` returns to the card, `Shift+F10` the row menu; the name starts with the visible header (SC 2.5.3: "Iceberg, 13:58:02, 63,118.0, BUY, estimated"); the cross-highlighted card carries `aria-current="true"`, never `aria-selected`; nothing is hover-only (the parameter snapshot and the copy are always rendered); new cards never move focus and the panel's `role="status"` summarises at most once per 5 s ("2 new detector events — iceberg 63,118, absorption 63,090"; imbalance events are CMP-049 rows, never cards — E25-D05 C19); confidence as number + CMP-032 dots + word, never dots alone; a role-gated action renders CMP-079 disabled-with-reason, never hidden. Pattern (hollow, dashed, hatched) marks estimated or absent, never a side (E25-D01 §9.5, PROPOSED for `16` §6; binding today under `16` §6 rules 1 and 5): the card's marker glyphs are hollow.
- **Tokens**: `color.surface.raised`, `radius.card`, `elevation.card` (static; CMP-050's `elevation.1` is its primitive), `color.border.default` (flat), `color.surface.selected`, `color.text.primary/secondary/tertiary`, `type.ui.label`, `type.ui.body`, `type.ui.caption`, `type.num.base`, `color.buy.default`/`color.sell.default`, `space.inset.sm/md`, `space.stack.sm`, `color.focus.ring`.
- **API sketch**: `interface DetectorEventCardProps { detectorType: "iceberg" | "stop_run" | "absorption" | "exhaustion" | "big_trade" | "regime" | "unfinished_auction"; time: number; price: number; side?: "buy" | "sell"; confidence: number | null; params: Record<string, number | string | boolean>; observed: string; inferred: string; unknown?: string; freshness?: DataConfidenceState; presentation?: "static" | "flat"; state?: "live" | "detector-off-flag" | "detector-off-user" | "error"; selected?: boolean; actions?: ReactNode; onOpen?: () => void; }`
- **Data contract**: detector events produced **backend-side** and pushed on `metrics.{symbol}` (event-like `MetricsUpdate` items: `v` the confidence, `unit: "confidence"`, `estimated: true`, `meta {price, side, reloads}`; `GET /market/metrics` for history); `params` is the per-series echo; never run client-side (E25-D01 C6). Always `estimated` heuristic output, never ground truth; the health / error field is E25-D05 G6.
- **Storybook**: Iceberg, StopRun, Absorption, Exhaustion, UnfinishedAuction, Flat, Static, Stale, DetectorOffFlag, DetectorOffUser, DetectorError, Loading, Empty, Selected, FocusVisible, LongText, HighContrast, ReducedMotion.
- **Tests**: unit (the chip cannot be omitted; the snapshot renders every `params` key), visual, axe (the feed structure: no `aria-required-children` or `aria-allowed-attr` finding), keyboard (the feed keys, inner stops), hover/focus parity, performance budget (SCR-056: 1.5 ms at ≤4 Hz in `flat`).

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

- **Tier**: Molecule (trading, risk-critical) · **Purpose**: meter of a current figure against its cap (daily loss, open positions, orders per minute, notional) per account, symbol, manager or aggregate — always paired with the numeric text, the cap and the as-of time; the fill is reinforcement, the glyph + word carry the state (E39-D01 D8; hi-fi contract `docs/design/E39/E39-D02.md` §6).
- **Props**: `current: number` · `cap: number` · `label` · `scope: "symbol"|"manager"|"portfolio"`. PROPOSED by E39-D02 §6, owned by E39-S04 (additive, optional): `scope` gains `"account"` · `asOf?: number` (the last-known timestamp) · `state?: "ok"|"warn"|"lock"|"stale"|"unknown"` (the server's band — B20 `warning`; the 80 % tick is a reading aid, never the decision) · `capChangedAt?: number`.
- **Variants**: ok (< 80 %) · near-cap (≥ 80 %: WARN diamond + word) · breached (≥ 100 % on a B20-locked account's daily-loss / streak meter: LOCK square + word; the bar clipped at 100 %, the number not; a refusal cap at 100 % reads bar + "CAP" — PROPOSED by E39-D02 C23, never LOCK) · unknown / stale (stale: the value kept, dimmed × 0.85, "as of hh:mm:ss" under it — E42-D02 D4 "old"; unknown: no fill, a hatched track, "—"; down: "Unavailable · last good hh:mm:ss" — D4 "down") · over-cap-after-tightening (the clipped fill plus an overflow marker; "112 % of the new cap · cap tightened at 14:10 UTC"; no position is force-closed by a tightened cap).
- **States**: live · stale (as-of shown, the figure dimmed) · unknown (no figure); density compact 8 px track in a 24 px row, comfortable 12 px in a 32 px row.
- **A11y**: PROPOSED `role="meter"` with `aria-valuenow/min/max` and `aria-valuetext` ("212 of 250 USD, 85 percent"), the state word in the accessible name — the CMP-023 ProgressBar contract it extends is a task-progress role and is kept as the fallback (E39-D02 C5); the numeric value is always rendered as text; the 80 % tick on every variant; never announced per tick (the host's state cell announces the band change); breach state (current ≥ cap) shown with glyph + word, triggers CMP-117 RiskLockoutBanner elsewhere in the app.
- **Tokens**: `color.status.warning.{default,strong}`, `color.status.danger.{default,strong}`, `color.surface.sunken` (the track — PROPOSED while `color.track` exists in no theme), `color.text.{primary,secondary,tertiary}`, `type.num.base`, `type.ui.caption`, `radius.pill`.
- **Data contract**: `GET /risk/summary` `RiskSummary.accounts[].{daily_loss_cap_usd, cap_utilisation_pct, open_positions}` and `totals.*` per environment (`22-api-openapi.yaml`; the numerator is `daily_loss_cap_usd × cap_utilisation_pct`, derived — a served per-row `daily_loss_usd` is E39-D02 G16, and `realised_pnl_today_usd` is not it: US-RULE-012's NFR counts realised plus unrealised PnL); `GET /me/limits` `EffectiveLimits.accounts[]` for the caller's own orders-per-minute and open-positions headroom; the caps from `RiskCaps` (`max_open_positions` 0..100, `max_orders_per_minute` 1..600, `max_consecutive_losses` 1..50) and the per-account profile; the warning band from the server (B20 `warning`), per `14-screens-catalogue.md` §0.4.
- **Storybook**: Ok, NearCap, Breached, Stale, Unknown, OverCapAfterTightening, AccountScope, PortfolioScope, Compact, Comfortable, ReducedMotion.
- **Tests**: unit (clipping at 100 %, the 80 % tick position, the as-of rule), visual, axe (the `meter` name and `aria-valuetext`), never-per-tick live-region test.

### CMP-139 EnvironmentAwareOrderGuard (wrapper)

- **Tier**: Molecule (utility, trading-critical) · **Purpose**: the presentation wrapper that renders a submit affordance disabled-with-reason while the workspace-level env context is DEMO and the order targets LIVE, and vice versa (defence-in-depth alongside the server-side check, which is the enforcement) — wraps CMP-107 OrderTicket and CMP-108 DomLadderRow's click-to-trade handlers.
- **Props**: `activeEnv: "demo"|"live"` · `orderEnv: "demo"|"live"` · `accountVisible: boolean` (false when the target account is outside the session's `account_scope`: the `rbac.account` leg renders and the guard is skipped) · `children`.
- **Variants**: matched (renders the child untouched), mismatched, an unseen account (the `rbac.account` leg, ahead of the guard).
- **States**: matched, mismatched (E09-D09 §2.2 T2 on the child: full label, lock glyph, `aria-disabled`, the reason `guard.mismatch` "Order is for a LIVE account while the workspace is DEMO"), unseen-account (T2 with `rbac.account` "This account isn't assigned to you." — E09-D09 §2.1 step 3(c); never the account's name, environment, balance or count).
- **A11y**: mismatch renders the wrapped control disabled-with-reason (CMP-079 RbacGate pattern; CMP-019 `lock`, `decorative=false`, "Not available") rather than silently rerouting the order; the reason is in the DOM at mount and linked by `aria-describedby`; a press re-shows it once, politely; the view-as leg precedes the guard.
- **Tokens**: n/a (behavioural wrapper; the T2 look's tokens apply to the child).
- **API sketch**: `interface EnvironmentAwareOrderGuardProps { activeEnv: "demo" | "live"; orderEnv: "demo" | "live"; accountVisible: boolean; children: React.ReactNode }`
- **Data contract**: `activeEnv` sourced from the workspace-level environment-context store (client-side, backed by the session/account-selection REST state); `orderEnv` derived from the wrapped order's target account's `env` field (CMP-106 ProfileBadge data); `accountVisible` from the session's `account_scope`.
- **Storybook**: Matched, Mismatched, Mismatched(Demo→Live), Mismatched(Live→Demo), UnseenAccountT2, ViewAsReadOnly, HighContrast, ReducedMotion.
- **Tests**: integration test — attempts to submit a live order while env=demo and asserts hard block + audit log entry; the T2 test on the wrapped submit; the account-leg test (no account label and no environment word in the DOM when `accountVisible` is false; the reason is `rbac.account`); no transition between gated and enabled.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §14 (E30-D04; owner approval pending).

---

## 5. Rule engine & node-graph components (CMP-140..159)

Both the form/condition-list editor and the visual node-graph editor compile to the same rule IR (owner decision #11); components in this band are shared or paired across the two editors where the underlying model is identical.

### CMP-140 RuleConditionRow

- **Tier**: Molecule (rule engine) · **Purpose**: one condition line in the form/condition-list editor — metric, operator, value/reference, boolean-join to the next row. **E36-D03 —** the join is CMP-141's (the group reads "and" / "either … or …", DCR-4); the row is metric · operator · value form · row menu, with its sentence fragment beneath (E36-D02 §5).
- **Props**: **E36-D03 —** `metric: string` (a vocabulary id rendered as its `display_name`, never shown raw) · `operator`: one of the vocabulary's 15 operator ids (`OPERATORS` in `rules/vocabulary/catalogue.py`), rendered as its verb (`gte` → "is at least"; arity 1 / 2 / 3 and the unit class filter the list) · `value: number | MetricRef` · `right2?` (`between` / `outside`) · `setValues?: string[]` (`in_set` / `not_in_set`) · `tolerance?` · `sustainedForMs?` ("for at least {w}") · `onChange` · `onRemove` · `diagnostics?: Diagnostic[]` (CMP-234's shape, anchored by the row id — memo G11); `joinToNext` is dropped (DCR-5).
- **A11y**: FormField (CMP-040) composition per sub-control; remove is a labelled IconButton; row order reflects evaluation order and is announced when reordered. **E36-D03 —** the row is a `group` named "Condition N of M", described by its fragment; the CMP-227 chip follows the metric title when the metric is estimated; an unavailable metric reads "(not available — {reason} · Start recording)" inline (P9) — its Start recording wraps in CMP-079 RbacGate with the CMP-019 `lock` for a session without `recording:write`, `aria-disabled` + `aria-describedby` → the reason `rbac.owner_only` "Only the owner can start recording." (E09-D09 §2.2; E36-D02 §16, §14); `Shift+F10` opens the row menu (move up / down, duplicate, remove); `aria-invalid` + the message when invalid.
- **Tokens**: **E36-D03 —** `font.family.mono` via `type.num.sm` (numeric literals), `color.status.danger.default` at `border.thick` (the invalid outline), `color.status.danger.strong` (the invalid glyph); `font.mono` and `color.border.invalid` do not exist in `packages/ui/tokens` (E36-D02 §15 request 1).
- **API sketch**:

```ts
interface RuleConditionRowProps {
  metric: string;
  operator: ">" | ">=" | "<" | "<=" | "==" | "!=" | "crosses_above" | "crosses_below";
  value: number | { metricRef: string };
  joinToNext?: "AND" | "OR";
  onChange: (patch: Partial<RuleConditionRowProps>) => void;
  onRemove: () => void;
  invalid?: string;
}
```

- **Storybook**: **E36-D03 —** Default, MetricRefValue, Between, InSet, Predicate, Estimated, Unavailable, UnavailableT2, Invalid, ReadOnly (the API sketch above is the pre-amendment shape; the Props line supersedes it until E36-T01 types the interface).
- **Tests**: unit (metric/operator compatibility validation, e.g. `crosses_above` invalid for boolean metrics), visual, axe, keyboard.

### CMP-141 RuleConditionGroup

- **Tier**: Molecule (rule engine) · **Purpose**: groups CMP-140 rows under one boolean mode. **E36-D03 —** two levels, said aloud (DCR-4, memo R3 DECIDED by the shipped form subset): a root "all of" of comparisons and `any_of` groups of comparisons, or a root "any of" of comparisons, or a single comparison; up to 32 children (`MAX_BOOLEAN_CHILDREN`); no nested "Advanced" mode — a graph-only subtree renders as the read-only card in place (E36-D02 §4, §6).
- **Props**: **E36-D03 —** `rows: RuleConditionRowProps[]` · `mode: "and"|"or"` · `onAddRow` · `onAddAnyOfGroup` · `onChangeMode`.
- **A11y**: **E36-D03 —** `fieldset`/`legend` grouping (CMP-065 FormSection base); the group's accessible name is "Condition group — either {A} or {B}" with the legend "any of"; its rows are indented and joined by a 2 px bracket in `color.text.tertiary` (≥3:1 non-text), attached flush; a count "12 of 32" in the legend from 24 children.
- **Tokens**: **E36-D03 —** `space.inset.lg` (the group indent, 16 px, as E36-D02 §16 names it) with `space.rulegroup.indent` PROPOSED as a Tier-2 alias → `{space.6}` (24 px) in both densities so the bracket column is one square target (E36-D03 §9; the token lands by the DS CODEOWNER per `16` §11.2); `color.text.tertiary` (the bracket ink).
- **Storybook**: **E36-D03 —** And, Or, WithAnyOfGroup, ReadOnlyCard.
- **Tests**: unit, visual, axe.

### CMP-142 RuleActionRow

- **Tier**: Molecule (rule engine) · **Purpose**: one action line — action type + params. **E36-D03 —** the action picker shows the vocabulary's `display_name`s of `rules/vocabulary/catalogue.py` **except `widen_stop`, omitted for every role** (#4137 — a rule fire never loosens a stop; E36-D02 §8; retired on `main` by PR #4246, merged via `35efcf28`: `RETIRED_ACTIONS` in `rules/vocabulary/catalogue.py`, the action kept in the IR enum so stored rules keep their hashes — E36-D03 G15's loosening half closed); each option's `notes` as its second line, except the `modify_stop_loss` note "Never loosens: only_tighten=false is refused.", which reads "The stop only ever tightens."; **the `only_tighten` parameter is never rendered as a control** — it is fixed true and read out as "The stop only ever tightens."; each row ends with its sentence fragment (memo §5.6); the six named parameter forms are E36-D02 §8's (`place_order`, `modify_stop_loss`, `move_to_breakeven`, `scale_out`, `flatten_all_positions`, `halt_new_orders`); the native stop field of `place_order` is non-emptiable (E32-D01 §5.2 Arm A) and every stop-management row carries E32-D01's `sl.note` sentence; the other `available: false` / `simulate_only` actions are disabled-with-reason (E09-D09 T2), never hidden — gated items wrap in CMP-079 RbacGate with the CMP-019 `lock` (E09-D09 §2.2; E36-D02 §16); the destructive class (`places_orders` ∪ `flatten_*`) carries a `color.status.danger.strong` glyph + the word "places orders" / "flattens".
- **Props**: **E36-D03 —** `actionType: string` (an `ActionSpec` id, rendered as its `display_name`; never `widen_stop`) · `params: Record<string,unknown>` (per the spec's `params_schema`, except `only_tighten`, fixed true and never a control) · `onChange` · `onRemove` · `available?: boolean` · `simulateOnly?: boolean` · `restriction?: string` (shown in the details disclosure, the T2 sentence mapped client-side — E36-D02 G14).
- **A11y**: **E36-D03 —** a `group` named "Action N of M", described by its fragment; the parameter form is CMP-040 fields per `params_schema`; `on_error`, `targets` and `dry_run_only` sit in an "Advanced" disclosure (CMP-051 Accordion).
- **Tokens**: inherits CMP-140. **E36-D03 —** `color.status.danger.strong` (the destructive-class glyph), `color.status.info.subtle` (the `sl.note` note).
- **API sketch**: `interface RuleActionRowProps { actionType: string; params: Record<string, unknown>; onChange: (p: Record<string,unknown>) => void; onRemove: () => void; }`
- **Storybook**: **E36-D03 —** PlaceOrder, ModifyStopLoss, MoveToBreakeven, ScaleOut, FlattenAll, HaltNewOrders, SimulateOnlyDisabled, PermissionT2, ReadOnly.
- **Tests**: unit (per-action-type param validation), visual, axe.

### CMP-143 RuleTriggerPicker

- **Tier**: Molecule (rule engine) · **Purpose**: choose the rule's trigger (`on_price_update`, `on_bar_close`, `on_order_fill`, `on_timer`, `on_indicator`) and timeframe. **E36-D03 —** the trigger and its parameter: the vocabulary's 13 triggers (`TRIGGERS` in `rules/vocabulary/catalogue.py`) with their `description`s as the second line — there is no `on_indicator` (DCR-8 / memo C14); one trigger per rule; the parameter per `required_fields` (timeframe, interval, cron "(UTC)", metric); `debounce_ms` as "at most once every {d}".
- **Props**: **E36-D03 —** `trigger: string` (a trigger id, rendered by its description) · `timeframe?: string` · `intervalMs?: number` · `cron?: string` · `metric?: string` · `debounceMs?: number` · `onChange`.
- **Tokens**: inherits CMP-009.
- **Storybook**: **E36-D03 —** OnBarClose, OnPriceUpdate, OnPositionChange, OnTimer, OnSchedule, OnMetricChange, OnBookUpdate.
- **Tests**: unit, visual, axe.

### CMP-144 RuleScopeSelector

- **Tier**: Molecule (rule engine) · **Purpose**: choose what the rule applies to — symbol, account(s), `open_positions`/`pending_orders`/`account` scope. **E36-D03 —** the `RuleScope` level and `applies_to` (with `any`); `environments` is shown as the scope chip's segment ("2 accounts · BTCUSDT · demo") and the chrome's band, never a local badge; the chip is the compact form on SCR-080 rows (US-RULE-007).
- **Props**: **E36-D03 —** `symbol?` · `accounts: string[]` · `level: "global"|"account"|"symbol"|"position"|"trade_group"` · `appliesTo: "open_positions"|"pending_orders"|"account"|"any"` (`any` is the shipped default, `24` §11.2; E36-D02 C7) · `environments: ("demo"|"live")[]`.
- **Tokens**: inherits CMP-105 AccountMultiSelect (reused).
- **Storybook**: **E36-D03 —** SingleAccount, MultiAccount, AccountScope, AppliesToAny, LiveEnvironment.
- **Tests**: unit, visual, axe.

### CMP-145 RuleFormEditor (organism)

- **Tier**: Organism (rule engine) · **Purpose**: full structured-form rule editor composing Trigger/Scope/Conditions/Actions + arm/simulate controls. **E36-D03 —** the header carries the round-trip indicator (its home per E36-D02 §16): a focusable chip, glyph + word + fill, never colour alone.
- **Props**: `rule: RuleDraft` · `onChange` · `onSimulate` · `onSave` · `armMode: "disarmed"|"simulate-only"|"live-armed"` · `onArmModeChange`. **E36-D03 —** `roundTrip: {result: "identical"|"graph_only_construct"|"mismatch"|"unverified", checking: boolean, staleSince?: string}` · `onViewDiff()` (→ SCR-088's Diff segment) · `onResolve(choice: "keep_form"|"keep_graph")` (E36-D02 §4; `result` is derived client-side from `compileRule`'s `round_trip`, E36-D02 G13); `armMode` keeps its three values — the wire's `RuleMode` is `disabled | simulate | armed` with live = `armed` and `scope.environments` including `live` (a note, E36-D03 C10).
- **States**: **E36-D03 —** draft · validating · valid · invalid · armed · vocabulary-unavailable (the six `14` SCR-081 states, E36-D02 §3) × the indicator's RoundTripsOk · GraphOnlyConstruct · Mismatch · NotVerified · Checking · Stale (E36-D02 §4); the gated controls (Arm…, Save draft, Validate, Simulate) wrap in CMP-079 RbacGate with the CMP-019 `lock` (E09-D09 §2.2) while the role, the new-rule gate (`rule.arm.simulate_first`), `unverified` (`rule.arm.unverified`) or a mismatch (`rule.save.mismatch`) holds; the view-as notice (`rbac.view_as`) is the one node while the session views as another user; form-validity disabling (invalid, no action, the flatten-all box) is `aria-disabled` + the visible reason without the lock (E09-D09 §9.1), the control at `opacity.disabled` with the reason full-opacity beside it (E30-D02 D3; E36-D02 §1, §14, §16).
- **A11y**: **E35-D02 (PROPOSED) —** arming opens SCR-085 (E35-D02); a LIVE arm takes the one-shot `live_enablement` step-up in SCR-006's `no-grace-live-enable` frame (password + code + the typed word LIVE — `22` `setRuleMode` / `authStepUp` as written, LIVE only; the typed LIVE is SCR-006's form reused by name, not a second confirmation grammar); no typed rule name (E35-D01 SC-12) — arming a live rule is a destructive-class action per safety framing. **E36-D03 —** the typed confirm is SCR-085 (E35-D02's dialog); the indicator is `role="status"` for the word, one polite announcement per `result` change; CMP-158 is pinned above the action bar (E36-D02 §2).
- **Tokens**: inherits FormSection (CMP-065). **E36-D03 —** the indicator's fills `color.status.success.subtle` / `color.status.warning.subtle` / `color.status.danger.subtle` / `color.surface.hover` with their `.strong` glyphs and `color.text.primary` words (E36-D02 §15).
- **Storybook**: **E36-D03 —** Draft, Validating, Valid, Invalid, Armed, VocabularyUnavailable, RoundTripsOk, GraphOnlyConstruct, Mismatch, NotVerified, Checking, Stale, ViewAsReadOnly.
- **Tests**: unit, visual, axe, keyboard, interaction (arm-confirm flow).

### CMP-146 NodeGraphCanvas

- **Tier**: Organism (rule engine, canvas-adjacent) · **Purpose**: the visual node-graph editor surface (React Flow/Rete.js-based per owner decision #11) — pan/zoom canvas hosting nodes and edges that compile to the same rule IR as CMP-145.
- **Props**: `nodes: NodeGraphNode[]` · `edges: NodeGraphEdge[]` · `onNodesChange` · `onEdgesChange` · `onConnect` · `readOnly?`.
- **A11y**: the canvas graph is the second-highest a11y risk after the chart engine — implements the same three-layer strategy as chart canvases: (1) DOM-mirror per node/edge (each node is _also_ a real focusable DOM element positioned via the graph library's node-renderer, not a raw canvas draw — React Flow/Rete.js both render nodes as DOM by default, which is why they were preferred candidates per research; edges get an offscreen mirrored adjacency list), (2) roving-tabindex node-to-node navigation (`Tab` enters the graph, arrow keys move between connected nodes, `Enter` opens node inspector Drawer), (3) an always-available "Switch to form view" toggle that shows the _exact same rule_ in CMP-145 as a full keyboard-operable, non-spatial alternative — this is the primary accessible-equivalent mechanism for the node-graph, mandated because free-form 2D graph manipulation cannot be made fully keyboard-equivalent to mouse drag-connect at parity speed.
- **Tokens**: `color.surface.canvas`, `color.edge.default/selected`.
- **API sketch**:

```ts
interface NodeGraphNode {
  id: string;
  type: "trigger" | "condition" | "action" | "logicGate" | "comment";
  position: { x: number; y: number };
  data: Record<string, unknown>;
}
interface NodeGraphEdge {
  id: string;
  source: string;
  target: string;
}
interface NodeGraphCanvasProps {
  nodes: NodeGraphNode[];
  edges: NodeGraphEdge[];
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

- **Tier**: Organism (rule engine) · **Purpose**: runs the current rule draft against recorder history and shows a behaviour preview over recorded history — when the rule would have fired, what it saw, what it would have done and what would have blocked it; never a profit figure (E35-D01 SC-1) (E35-D02 D02-A1).
- **Props**: `rule: RuleDraft` · `dateRange` · `onRun` · **E35-D02 —** `result?: RuleSimulationResult` · `run?: RuleRun` · `coverage?: DataCoverage` · `gateProgress?: {simulatedOnVersion: boolean, blocksArming: boolean}` · `onCancel?` (D02-G3) · `onExportCsv?` (D02-G12) · `loading?`.
- **States**: **E35-D02 —** idle · running · completed · partial · failed · no-history (the six `14` states) plus the view-as, gate-met and stale-run treatments.
- **A11y**: results table extends CMP-049 Table contract; empty/insufficient-history state uses CMP-026 EmptyState `variant="recording-not-started"`. **E35-D02 —** the timeline is a CMP-049 `grid: true` (CMP-156's simulation variant; E35-D04 F-02) with the timeline's `<ol>` text list; the progress region polite, at most once per 5 s, the latest value (E35-D04 F-11, §8.4); Run T2 while viewing as (CMP-079 RbacGate + CMP-019 `lock`); the drawer that hosts it is a non-modal `role="dialog"` named "Simulation — {rule name}" (E35-D04 F-07) and arrives in one frame (E35-D04 F-14, T-03).
- **Tokens**: inherits CMP-049.
- **Storybook**: Idle, Running, ResultsPopulated, InsufficientHistory. **E35-D02 —** one story per state (idle · running · completed · partial · failed · no-history).
- **Tests**: unit, visual, axe.

### CMP-155 RuleListRow

- **Tier**: Molecule (rule engine) · **Purpose**: one row in the rules list screen (SCR-080). **E36-D03 —** eight cells: name · scope chip · trigger summary (the sentence's first clause plus the CMP-227 chip when a metric is estimated; the full sentence on hover / focus — memo Q3) · state (the status word + glyph: DRAFT · SIMULATING · ARMED-DEMO · ARMED-LIVE · DISARMED · PAUSED · OFF · DONE · ERROR, with its reason line — E36-D03 §3, PROPOSED) · environment (the DEMO / LIVE pill, E11-D02 row 415) · last fired (UTC) · author · active version; **no one-click arm**: arming needs the server's gate (`22` `setRuleMode`) and surfaces SCR-085 from the row menu.
- **Props**: **E36-D03 —** `rule: Rule` (`22`'s list item — `environments`, the estimated flag, the author's name, the B9 state and the summary are **not** on `Rule`: E36-D03 G4–G7, G13; the row reads them from the detail or derives them client-side until then) · `onOpen` · `onArm` (→ SCR-085) · `onDisarm` (CMP-044 `standard`) · `onEdit` · `onEditGraph` · `onDuplicate` · `onSimulate` · `onExport` · `onDelete` · `onFireHistory` · `selected` · `onSelect` · `systemRule?: boolean` (a protected built-in: the lock glyph, the tag "System · always on", Edit / Disarm / Delete T2 "System rules cannot be changed."; no wire field carries it — derived client-side by mirroring `is_reserved_name`, NFKC + casefold + trim on `name`, until one ships); `onToggleEnabled` and the enable toggle are removed (E36-D03 C11).
- **A11y**: **E36-D03 —** the state is text + glyph, the word in `color.text.primary` with the hue on the glyph, never colour-only (the CMP-011 tag and the `critical` Toggle are gone); the row is a roving `row` named "{name}, {spoken state}, last fired {HH:MM:SS} UTC" (the spoken forms of E36-D03 §3: "armed on demo", "off, 5 errors in a row", …) and described by the full sentence; `Shift+F10` opens the nine-item row menu whose gated items are CMP-079 RbacGate's T2 (E09-D09 §2.2): the full label led by a CMP-019 `lock` glyph "Not available", `aria-disabled` never `disabled`, the reason as the item's second line and its `aria-describedby` target, never hidden; a state flip is announced once, politely; every timestamp reads UTC; "never" when the rule has not fired, "—" only for a stale cell.
- **Tokens**: inherits CMP-049 row pattern. **E36-D03 —** `color.status.success.strong` / `color.status.info.strong` / `color.status.warning.strong` / `color.status.danger.strong` and `color.text.secondary` (the state glyphs), `color.env.demo` / `color.env.live` (the pill border on `color.surface.raised`), `color.border.selected` (the current row), `color.text.secondary` (the version cell and every in-row caption — `color.text.tertiary` fails 4.5:1 on `color.surface.selected`), `type.num.sm` + `font.family.mono` (timestamps, counts), `size.row.height`, `size.target.min`.
- **Storybook**: **E36-D03 —** Draft, Simulating, ArmedDemo, ArmedLive, Disarmed, PausedDegraded, Off, Done, Error, Estimated, SystemRule.
- **Tests**: unit, visual, axe.

### CMP-156 RuleEvaluationTimeline

- **Tier**: Molecule (rule engine) · **Purpose**: per-rule chronological log of evaluation/trigger/action events (feeds journal auto-tagging traceability, digest 09 §11).
- **Props**: `events: RuleEvent[]` (`22`; E35-D03 D03-C10). **E35-D02 / E35-D03 —** `variant: "live" | "simulation"` · `textList: true` (required: the simulation variant's text-list equivalent) · `expandedRowId` · `onOpenOrder` · `onOpenAudit` · `onOpenReplay` · `onExport`.
- **Variants**: **E35-D02 —** simulation: the row's columns time UTC · trigger · condition values · action + params · outcome (`would_have_succeeded` / `blocked_by` as text + glyph) · "open in chart at this moment"; a CMP-049 `grid: true` (E35-D04 F-02). **E35-D03 —** live: columns time UTC · version · trigger (display words) · conditions · action (E35-D02's "stop {from} → {to}" form) · result (text + glyph: Done · Failed · Error · Skipped; the exchange reason from E35-D03 §6) · environment (word + glyph) · links (Order · Audit · Replay, named "Order, firing {time}" · "Audit, firing {time}" · "Replay, firing {time}", E35-D04 F-18; a T2 link keeps the lock + full label, a role-level reason as one notice under the caption with `aria-describedby` from every such link, a row-level reason visually hidden per row with the CMP-016 echo and the sentence in the expanded row — D03-A13); the expanded row's nested condition table (Condition · Saw · Needed · Result), the actions-attempted list with Copy as a CMP-033 cell (named "Copy, {action}", E35-D04 F-18), and the cross-reference line to a superseded partner (new-47).
- **States**: **E35-D03 —** populated · streaming (the pill) · failed rows · skipped rows · restart marker · empty (both forms) · loading · error · reflow.
- **A11y**: the simulation variant and the live variant are CMP-049 `grid: true` grids with one Tab stop; the live variant's rows never announce one by one; the pill announces the latest count (E35-D04 §6.3, §8.2). **E35-D03 —** `role="grid"` (APG grid) with `aria-rowindex`.
- **Tokens**: `font.family.mono` (not `font.mono`, E35-D03 D03-C9), `color.status.*`. **E35-D03 —** inherit CMP-049 + `color.status.danger.subtle` / `.strong`, `color.status.success.strong`, `color.status.info.subtle` / `.strong`, `color.surface.app` (in place of `color.surface.sunken`, E35-D04 F-06; or the owner's recorded exception, C-24), `font.family.mono`.
- **Storybook**: Default, WithActionFired. **E35-D02 —** SimulationRows, TextList. **E35-D03 —** LiveRows, FailedRow, RestartMarker, Expanded, Streaming.
- **Tests**: unit, visual, axe.

### CMP-157 MetricPickerCombobox

- **Tier**: Molecule (rule engine) · **Purpose**: searchable picker for the metric vocabulary used inside CMP-140/148. **E36-D03 —** options are grouped under seven categories derived from the signal's scope and inputs (memo R2, DCR-10): `price` · `orderflow` · `book` · `derivatives` · `position` · `account` · `replay` (last); "(estimated)" is a CMP-227 tag on the option, never a category; the option reads `display_name` · unit, with the `description` as the second line, and an unavailable option reads "(not available — {reason} · Start recording)" (E36-D02 §7); a gated option or recorder action wraps in CMP-079 RbacGate with the CMP-019 `lock` (E09-D09 §2.2; E36-D02 §16).
- **Props**: **E36-D03 —** `value` · `onChange` · `category?: "price"|"orderflow"|"book"|"derivatives"|"position"|"account"|"replay"` · per option `estimated`, `available`, `unavailableReason`, `recorderAction`.
- **A11y**: extends CMP-048 Combobox; metrics sourced from heuristic detectors are tagged `(estimated)` in the option list itself, not just after selection. **E36-D03 —** the chip inside an option is a second roving stop reached by `→`; the results count is announced politely per query.
- **Tokens**: inherits CMP-048.
- **Storybook**: **E36-D03 —** Default, SevenCategories, EstimatedMetricTagged, UnavailableWithStartRecording, StartRecordingT2, NoResults.
- **Tests**: unit, visual, axe.

### CMP-158 SafetyInvariantNotice ("native SL always attached")

- **Tier**: Atom (rule engine and trading, safety-critical) · **Purpose**: persistent, non-dismissible notice inside both rule editors and every order ticket (SCR-060 / 061; SCR-076 already lists it) reminding the author that emulated rule-engine stops never replace the mandatory native exchange-side SL (safety invariant, `24-internal-schemas.md` §8.8; C-2.6). **E36-D03 —** placement and sentence per E36-D02 §2 (PROPOSED): pinned directly above the action bar so it is in view at the moment of Arm; the sentence "Every position keeps a native stop — you can move it, not delete it. Rules can tighten it, never remove it — the stop is held by the exchange, not by this app." (the first sentence is `14` SCR-064 Validation / E32-D01 `sl.note`; the second keeps `sl.note`'s holder clause).
- **Props**: `profileTicks: number` (the "{n}" of the ticket variant's sentence); otherwise static content — the rule-editor variant takes no prop (its sentence is E36-D03's, static).
- **Variants**: ticket (inside the bracket section; its sentence is E30-D02 §14 `sl.note` "Every entry carries a native exchange stop: typed here, else your profile's {n} ticks, else the 2 % fallback. It is placed with the order, not after it."), rule editor (CMP-145 / CMP-146; its sentence and placement are E36-D03's above), **E35-D02 —** arming dialog (SCR-085, block 5; its static sentence CA-26 "Every position keeps its own stop-loss at Bybit, whatever this rule does. A rule can move that stop but never remove it; everything else it does needs CandleViewer's server running.", binding pending the owner; it inherits CMP-028 `info` as the rule-editor variant does); compact one line / comfortable two lines.
- **States**: default only (always visible; no hover, no dismiss, no loading).
- **A11y**: `role="note"`, always visible in both CMP-145 and CMP-146 layouts and in every ticket; not a live region; the glyph `aria-hidden`. **E36-D03 —** CMP-028 `tone="info"`, not in the Tab order; `color.text.primary` on `color.status.info.subtle`.
- **Tokens**: inherits CMP-028 Callout (`info`): `color.status.info.subtle`, `color.text.primary`, `color.status.info.strong` (glyph), `radius.card`, `space.inset.sm`, `type.ui.caption` / `type.ui.body`.
- **API sketch**: `interface SafetyInvariantNoticeProps { profileTicks: number }`
- **Data contract**: `profileTicks` from the account's profile (`GET /exchange-accounts/{id}/profiles`) — the ticket variant only.
- **Storybook**: Default, Comfortable, HighContrast, InRuleEditor (E36-D03's sentence and placement), InArmingDialog (E35-D02's CA-26 sentence in SCR-085).
- **Tests**: visual, axe, presence test (fails if removed from either editor's composition or from the ticket); each variant renders its own source string (E30-D02 `sl.note` / E36-D03).
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §15 (E30-D04; owner approval pending); the rule-editor variant's sentence and placement: E36-D03 (#4198).

### CMP-159 RuleConflictWarning

- **Tier**: Molecule (rule engine) · **Purpose**: flags two enabled rules with overlapping scope/contradictory actions at save time. **E36-D03 —** two armed rules that target the same position / scope with overlapping actions (e.g. two rules move the same stop — no rule widens one, #4137), detected at arming time (US-RULE-011 sc. 1) and on save (`14` SCR-086), and surfaced on SCR-080 before arming as a CMP-028 `tone="warning"` banner — "2 rules target the same position — resolve precedence" with a second line naming the two rules — whose action **Set priority** opens SCR-086 (E35); a list row is never amber.
- **Props**: **E36-D03 —** `conflicts: {ruleA: {id, name}, ruleB: {id, name}, target: string, actions: [string, string]}[]` (the names are shown, the ids never — P1; no conflict shape exists on `Rule` / `RuleUpdate` yet, E36-D03 G8) · `onSetPriority(conflict)`. **E35-D03 —** the resolver variant: `conflicts[].kind` ∈ the four kinds, `resolution: "set_priority" | "narrow_scope" | "disarm_one" | "arm_anyway"`, `order: rule_id[]`, `acknowledged: boolean`, `onApply`.
- **Variants**: **E35-D02 —** the SCR-085 inline line: CA-21's sentence, `role="status"` off (it is static in the dialog), the action "Choose which goes first" → SCR-086 (`onSetPriority`); props unchanged. **E35-D03 —** the resolver variant (SCR-086): the consequence sentences of E35-D03 §2 as the component's copy contract (CA-28 for the stop pair; the three `new` sets).
- **A11y**: **E36-D03 —** `role="status"` on SCR-080 (`14` SCR-080 A11y); one polite announcement on arrival; the action is a button in the Tab order; the second line is `color.text.secondary` on the amber fill (never `color.text.tertiary`). **E35-D03 —** the resolver variant: one `radiogroup` per conflict named "Resolution for {A} and {B}", the consequence in `aria-describedby`, Move up / Move down (named "Move up: {rule}" / "Move down: {rule}", E35-D04 F-18) announce "{rule}, 1st of 2", the acknowledgement a CMP-005; a partner the caller may not read renders "a rule you can't see" with Set priority / Disarm one T2 through CMP-079 (CMP-019 `lock`).
- **Tokens**: inherits CMP-028 `tone="warning"`. **E36-D03 —** `color.status.warning.subtle` (fill), `color.status.warning.strong` (glyph), `color.text.primary` / `color.text.secondary`, `color.focus.ring`.
- **Storybook**: **E36-D03 —** SingleConflict, MultipleConflicts, OnList. **E35-D03 —** the resolver variant: StopPair, MultipleConflicts, RiskBand, ArmAnyway, OtherOwnersRule, NoConflict.
- **Tests**: unit, visual, axe.

---

## 6. Watchlist / alerts / journal / replay / audit components (CMP-160..179)

### CMP-160 SymbolSearchInput

- **Tier**: Molecule (trading) · **Purpose**: fuzzy symbol search with instrument preview (tick/lot, category, funding) — entry point for chart/DOM/watchlist symbol changes.
- **Props**: `value` · `onSelect(symbol)` · `category?: "linear"` (locked to USDT perps for v1) · `recentSymbols?: string[]`.
- **A11y**: extends CMP-048 Combobox; recent symbols shown as a labelled group before search results; the input may be T2 (E08-D07 §6.6: a CMP-019 `lock` glyph, the reason).
- **Tokens**: inherits CMP-048.
- **API sketch**: `interface SymbolSearchInputProps { value: string; onSelect: (symbol: string) => void; recentSymbols?: string[]; }`
- **Storybook**: Default, WithRecents, NoResults, WithPreviewPopover(CMP-125).
- **Tests**: unit, visual, axe, keyboard.
- **E08-D05 (A-D05-6)**: keys `PageUp`/`PageDown`; host-defined `Shift+Enter`, `Shift+F10` and `Esc` (here one press closes and reverts; E13-D02's SCR-034 clears a non-empty query first); the host root stops every key but four Global chords, which close it first (E08-D05 §8); the count debounce is 300 ms; CMP-160 gains `target` (the chip; an armed pane adds E30-D02's ARMED pill, D-10) and keeps `category?: "linear"`.
- **As built (E08-S09)**: CMP-048's combobox half (its well, the `search` prefix, T2 and the refused keys) over CMP-213 drawn in place, not in CMP-048's portalled popup: E08-D05 §6.1 and §9.1 keep the list on the surface and §5 wants ≤ 50 ms from a keystroke to the painted list, so the list follows every keystroke and only the count waits for the 300 ms rest (`settleMs?`). A blur closes nothing and keeps the active option, so `Esc` in a host's `Shift+F10` CMP-041 menu returns to the input on the same option (E08-D05 §6.3). Props: `value` / `onChange` (the query, `maxlength` 32), `onSelect(symbol, item)`, `items` (the host's ranked CMP-213 rows; it fetches nothing), `total?` (the count before the host's cap), `recentSymbols?` (rows, not strings, so a delisted recent shows; a "Recent" group only while the query is empty), `category?: "linear"` (USDT linear perpetuals only, C-1.2 item 3: the one category, so nothing reads it), `target?: {label, armed?, id?}`, `message?` (the host's sentence, said instead of the count at once, an empty query too, and again only when it changes), `loading?`, `emptyMessage?`, `visibleRows?` (default 8; the page), `onKeyDown?(event, active)` (as CMP-048's), `onActiveChange?` (a change, never the mount), `onContextMenu?`, `placeholder?`, `disabled?`, `disabledReason?`, `aria-label?` ("Search symbols"), `aria-describedby?`, `listLabel?` ("Symbols"). Storybook: Default, WithRecents, NoResults, WithTarget, ArmedTarget, Loading, DisabledWithReason, HostMenu; WithPreviewPopover waits on CMP-125, and the catalogue states (footer, detail bar) are SCR-102's.

### CMP-161 WatchlistRow

- **Tier**: Molecule (trading) · **Purpose**: one interactive-grid row over the E08-D07 §4.1 column registry.
- **Props**: `row` · `columns: WatchlistColumnId[]` · `freshness` (ticker, OI baseline and recorder, each a CMP-239 state with an age) · `rowState` (live, initialising, not live or delisted) · `active` · `onActivate` · `onMenu` · `onMove` · `onRemove`.
- **A11y**: extends CMP-049 row contract; %chg/PnL-style values use CMP-020 NumericText. A delisted row's activation and drag are T2 (E08-D07 §6.6): `aria-disabled`, a CMP-019 `lock` glyph, the merged cell's reason by `aria-describedby`. `onMove` (`Alt+↑/↓`) is T2 while sorted or filtered and at the ends, and `onMove` and `onRemove` (`Del`) are T2 in CMP-079 RbacGate without `workspaces:write` or while viewing as (E08-D07 §6.6).
- **Tokens**: `font.family.mono`, `color.text.buy/sell/neutral` (E08-D07 DS-CR-2).
- **E08-D04**: each per-value cell carries an optional CMP-239 FreshnessMarker (rendered as a CSS class change on the existing cell — no extra DOM node — per the freshness-marker contract) reflecting the data-confidence state for that field's feed. If the row's overall connection is `disconnected`, the row shows only that state (precedence rule, `docs/design/E08/E08-D01.md` §2) — per-cell markers are suppressed rather than stacked.
- **API sketch**:

```ts
interface WatchlistRowData {
  symbol: string;
  lastPrice: number;
  pctChange24h: number;
  volume24h: number;
  fundingRate: number;
  openInterestDelta: number;
}
```

- **API**: `WatchlistRowData` adds `priceScale`, `turnover24h`, `nextFundingTimeMs`, `spreadBps`, `rec`, and `openInterestChangePct24h` in place of `openInterestDelta`.
- **Storybook**: Default, Gainer, Loser, CustomColumns, StaleCell, DisconnectedRow, Initialising, NotLive, StaleRow, StaleRowEscalated, StaleServer, StaleColumn, Delisted, Active, RecStates, ReadOnly.
- **Tests**: unit, visual, axe, keyboard.
- **Motion spec**: [E08-D11.md](../design/E08/E08-D11.md) (E08-D11; the per-cell settle vs the container-class mass transition; the value-change emphasis cap — PROPOSED).

### CMP-162 WatchlistGroupTabs

- **Tier**: Molecule (trading) · **Purpose**: saved watchlist groups (e.g. "Majors", "My Setups") as tabs above the watchlist table.
- **Props**: `groups: {id,name}[]` · `activeId` · `onSwitch` · `onCreate` · `onRename` · `onDelete` · `counts` · `onDuplicate` · `onManage`.
- **A11y**: the CMP-042 Tabs pattern with manual activation (arrows move focus; `Enter`/`Space` switch, because a switch changes subscriptions, `23` L1190); each tab named with its count ("Majors, 12 symbols"); a tab menu on `Shift+F10` (Rename, Duplicate, Delete…, Manage watchlists…); overflow into "More lists". Without `workspaces:write`, or while viewing as, the tab menu's Rename, Duplicate and Delete… and the "+" (`onCreate`) are T2 in CMP-079 RbacGate (E08-D07 §6.6), with a CMP-019 `lock` glyph.
- **Tokens**: inherits CMP-042 Tabs.
- **Storybook**: Default, CreateNew, Overflow, TabMenu, ReadOnly.
- **Tests**: unit, visual, axe.

### CMP-163 AlertRow

- **Tier**: Molecule (trading) · **Purpose**: one alert definition in SCR-090: its condition with the evaluate-on and firing-mode words, its status in words, its delivery health and its actions; a compact form lists alerts elsewhere (the indicator manager's "Used by", E13-D02).
- **Props** (the served `Alert`, never a client summary; `deliveryChannels` of the placeholder did not match `AlertChannel`, E40-D02 X-19):

```ts
interface AlertRowProps {
  alert: Alert; // 22 `Alert`, as served; its `condition_hash` is never rendered
  account?: { label: string; env: "demo" | "live" }; // an account-scoped alert (CMP-075)
  stale: boolean; // Disconnected or resyncing (CMP-078)
  status: "armed" | "disarmed" | "fired" | "disabled" | "expired" | "snoozed"; // E40-D02 §2.3
  disarmReason?: string; // the disarm notice's title until CC-3
  estimated: boolean; // the vocabulary's `estimated` over the condition's metrics
  deliveryProblem?: {
    outcome: "blocked" | "failed";
    permission: "granted" | "denied" | "default" | "unsupported";
  };
  unacked: number;
  muted: boolean; // after CC-8
  readOnly?: { reason: string }; // an E09-D09 sentence
  variant: "table" | "compact";
  density: "compact" | "comfortable";
  selected: boolean;
  onSelect(): void;
  onToggleEnabled(): void;
  onSnooze(preset: "15m" | "30m" | "1h" | "tomorrow"): void;
  onEdit(): void;
  onDuplicate(): void;
  onDelete(): void;
  onShowOnChart(): void;
  onViewHistory(): void;
}
```

- **States**: armed, disarmed with its reason, fired one-shot, disabled, expired, snoozed, delivery problem, partial delivery, estimated, muted, unacknowledged firings, account-scoped, stale, selected, hover, focus, read-only, loading; the condition cell with its evaluate-on and firing-mode words in every state; another stored trigger.
- **A11y**: a `<tr>` whose name cell is `th scope="row"`; status is a word with a glyph, never colour alone; the checkbox label and the menu button name the alert ("More actions for BTC above 65k"); the condition reuses CMP-140's read-only wording.
- **Tokens**: rows on `color.surface.canvas`, hover `color.surface.hover`, selection `color.surface.selected`; text `color.text.primary` / `.secondary` / `.tertiary`; glyphs `color.status.*.strong`; the delivery chip `color.status.danger.default`; `size.row.compact` / `.comfortable`; `type.ui.body`, `type.num.base`.
- **Storybook**: Armed, ArmedEstimated, IntrabarEveryTime, BarCloseOncePerBar, Disarmed, FiredOneShot, Disabled, Expired, Snoozed, DesktopBlocked, PartialDelivery, Unacknowledged, Muted, AccountScoped, Stale, Selected, Hover, Focus, Loading, ViewerReadOnly, Compact, Comfortable, LongName (120 characters), OtherTrigger.
- **Tests**: unit (status derivation incl. precedence), visual, axe, keyboard (row menu, `Space` select).
- **Design (hi-fi spec):** [E40-D02.md](../design/E40/E40-D02.md) §7.1, §2; hand-off [E40-D02-handoff.md](../design/E40/E40-D02-handoff.md) (E40-D02; owner approval pending).

### CMP-164 AlertBuilderForm

- **Tier**: Organism (trading) · **Purpose**: SCR-091's form: CMP-141, CMP-140, CMP-157, CMP-143 and CMP-144 in `mode: "alert"`, with CMP-219, CMP-220, CMP-006, CMP-008, CMP-047, CMP-009, CMP-005, CMP-007, CMP-041 and CMP-234. **No actions slot exists**: the action vocabulary is empty in `mode: "alert"` and Delivery takes the Actions section's place with the persistent line "Alerts notify; to act automatically, create a rule." (E40-D02 D-1).
- **Props**:

```ts
interface AlertBuilderFormProps {
  mode: "create" | "edit" | "duplicate";
  draft: AlertDraft; // E40-D02 §3.10, a client type
  vocabulary: RuleVocabulary | "unavailable"; // GET /rules/vocabulary
  desktopPermission: "granted" | "denied" | "default" | "unsupported";
  shell: "desktop" | "browser";
  readOnly?: { reason: string };
  serverIssues?: unknown[]; // the 422 `errors` items, shown verbatim
  pending: boolean; // a save in flight
  onSave(input: AlertInput): void; // 22 `AlertInput`, unchanged
  onCancel(): void;
  onTest(): void;
}
```

- **Slots**: restatement · name · scope · condition · evaluate on · fire · expiry · severity · delivery (with the boundary line) · message (with the preview) · validation · footer.
- **States**: default, prefilled, validating, invalid, estimated warning, vocabulary unavailable (read-only, saving disabled), metric needs recording, saving, name taken, may already exist, changed elsewhere, server error, read-only, browser (the sound note), desktop blocked, test shown, a refused body (one server line), a stored trigger read-only.
- **A11y**: inline errors under their field (`aria-describedby`); on a failed save CMP-234 lists them, errors first, each a button that moves focus to its field, and takes focus itself; the preview is `role="status"`, written at most once per 500 ms.
- **Tokens**: `color.surface.overlay`, `elevation.dialog`, `radius.dialog`, `space.dialog.padding`, `space.field.gap`; the preview `color.surface.sunken`; callouts `color.status.warning.subtle` / `color.status.info.subtle`; checked boxes `color.action.primary.default`.
- **Storybook**: Default, PriceCross, IndicatorBarClose, StackedImbalance, EstimatedDetector, MultiCondition, AccountMetric, OncePerBar, EveryTimeCooldown, Expiry, PerAlertSound, ValidationErrors, Pending, VocabularyUnavailable, MetricNeedsRecording, NameTaken, MayAlreadyExist, ChangedElsewhere, ServerError, BrowserSoundNote, DesktopBlocked, ReadOnlyViewer, TestFire, Zoom200, RefusedValues, StoredTriggerReadOnly.
- **Tests**: unit (the action vocabulary is empty in `mode: "alert"`, E40-S01; the validation mirror against E40-D02 §3.6's table), visual, axe, keyboard-complete authoring.
- **Design (hi-fi spec):** [E40-D02.md](../design/E40/E40-D02.md) §7.2, §1, §3; hand-off [E40-D02-handoff.md](../design/E40/E40-D02-handoff.md) (E40-D02; owner approval pending).

### CMP-165 AlertFiredToastGroup

- **Tier**: Molecule (trading), a CMP-045 variant mounted by CMP-212 · **Purpose**: the fired-alert toast in all its forms: single, repeat, symbol batch, overflow, storm summary, disarm notice, after a gap, test.
- **Props**:

```ts
type FiringKind = "single" | "repeat" | "symbolBatch" | "overflow" | "stormSummary"; // E40-D02 §4.5
interface AlertFiredToastGroupProps {
  kind: FiringKind | "disarmed" | "reconnected" | "test"; // E40-D02 §4.2
  items: { delivery: AlertUpdateItem; name: string; estimated: boolean }[]; // 23 §15.7 items + the alert list
  severity: "info" | "warning" | "error" | "critical";
  persistent: boolean; // Error, Critical; disarmed, symbol batch, overflow, storm summary, reconnected (T-3)
  oneShot: boolean; // a fired `once` alert: `Enable again` replaces Snooze and Disable
  live: boolean; // shown on the replay page
  durationMs?: number; // SCR-115's setting
  readOnly?: { reason: string };
  onOpenChart(): void;
  onSnooze(preset: "15m" | "30m" | "1h" | "tomorrow"): void;
  onDisable(): void;
  onEnableAgain(): void;
  onWhy(): void;
  onDetails(): void;
  onExpand(): void;
  onOpenAll(): void;
  onDismiss(): void;
}
```

- **States**: info, warning, error, critical, estimated, repeat (×n), symbol batch, mixed-severity batch, expanded, overflow, storm summary, disarm notice, fired while disconnected, one-shot, snoozed confirmation, disabled confirmation, test, live on the replay page, paused, read-only, reduced motion.
- **A11y**: `role="status"` through CMP-212's polite region, whatever the severity; the toast never takes focus; the announcer (E40-D01 AR-1..AR-7) decides what is spoken; every action has a text label.
- **Tokens**: inherits CMP-045 (`color.surface.overlay`, `elevation.popover`, `radius.card`, `space.inset.md`, `space.stack.sm`, the `border.thick` edge in `color.status.*.default`, light warning `.strong`).
- **Storybook**: Info, Warning, Error, Critical, Estimated, Repeat, SymbolBatch, SymbolBatchExpanded, SymbolBatchMixedSeverity, Overflow, StormSummary, Disarmed, Reconnected, OneShotEnableAgain, SnoozedConfirm, DisabledConfirm, Test, LiveOnReplay, Paused, ViewerReadOnly, ReducedMotion, LongNameAndMessage.
- **Tests**: unit (the item classes, grouping windows and the overflow arithmetic), visual, axe, interaction (pause on hover and focus, `Esc` dismisses and acknowledges).
- **Design (hi-fi spec):** [E40-D02.md](../design/E40/E40-D02.md) §7.3, §4; hand-off [E40-D02-handoff.md](../design/E40/E40-D02-handoff.md) (E40-D02; owner approval pending).

### CMP-166 JournalEntryRow

- **Tier**: Molecule (trading) · **Purpose**: one closed-trade journal row — entry/exit, size, side, PnL, R-multiple, MAE/MFE, tags, replay-link.
- **Props**: `entry: JournalEntry` · `onOpenReplay` · `onEditTags`.
- **Tokens**: `font.mono`, `color.text.buy/sell`.
- **API sketch**:

```ts
interface JournalEntry {
  id: string;
  symbol: string;
  side: "long" | "short";
  entryTime: number;
  exitTime: number;
  entryPrice: number;
  exitPrice: number;
  qty: number;
  realizedPnl: number;
  rMultiple: number;
  mae: number;
  mfe: number;
  tags: string[];
  ruleSourceId?: string;
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
  currentTime: number;
  range: { from: number; to: number };
  speed: number;
  playing: boolean;
  bookmarks?: number[];
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

- **Tier**: Molecule (trading) · **Purpose**: speed-preset picker (0.5x/1x/2x/4x/10x/25x/100x plus a custom value within the API's 0.1–100 range — the canonical list decided in E26-D01, `docs/research/ux/replay-study-sessions.md` §4; the readout pairs the requested preset with the achieved rate) feeding CMP-170.
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
- **Props**: `entry: AuditEntry` (the generated type from `packages/protocol`, never hand-written) · `variant: "row" | "compact"` · `onExpand` (row only; shows before/after diff).
- **A11y**: `row` extends CMP-049 row contract; before/after diff rendered via CMP-068 CopyableCodeBlock inside an expandable region; `compact` rows form a list — time (UTC), actor, action label and code, subject label, outcome and severity as words — each linking to SCR-136.
- **Tokens**: `type.num.sm` (`font.family.mono`), `color.text.primary`, `color.text.secondary`, `color.text.tertiary`.
- **Data contract**: `AuditEntry` of `22-api-openapi.yaml`, the generated type, not restated here; compact rows use `ts`, `actor_username`, `action`, `subject_label`, `outcome` and `severity`.
- **Storybook**: Default, ExpandedDiff, SystemActor, Compact, CompactDenied, CompactElided.
- **Tests**: unit, visual, axe.

### CMP-174 AuditFilterBar

- **Tier**: Molecule (owner/admin) · **Purpose**: filter the audit log by date range (UTC), actor, action, subject, outcome, severity, IP and full-text search, and the loaded rows by environment; the filter set is URL state and a change resets the cursor.
- **Props**: `filters` (the generated `queryAuditLog` query parameters) · `onChange` · `actorOptions` · `actionOptions: {code, label}[]` (the registered vocabulary) · `view: "raw" | "own"` (`own` fixes Actor to the caller and renders IP, Search and Environment disabled with a reason through CMP-079, never removed) · `environmentScope: "page"` · `blockedReason?` (a reason-vocabulary key: every control disabled with it, as after a `429`) · `errors?` (`422` field errors).
- **A11y**: `<form role="search" aria-label="Filter the audit log">`; every control has a visible label; From and To say UTC; a `422` moves focus to its field, which carries the error by `aria-describedby`, and announces nothing; the result count is announced once, politely; there is no page-number control; in the `own` view Actor, IP, Search and Environment stay, and given `blockedReason` every control does, each disabled with its reason through CMP-079 (`aria-disabled`, never `disabled`), a CMP-019 `lock` leading the label; a disabled field or picker is also read-only (`readonly`, `aria-readonly`), so typing, arrows, paste, Enter and Space change nothing (`docs/design/E09/E09-D09.md` §2.2; E42-D04 §12.1).
- **Tokens**: inherits CMP-055 FilterBar; `space.field.gap`, `color.text.secondary` (labels; a disabled control's reason), `color.text.tertiary` (a disabled control's label and `lock`), `color.surface.raised` with a `color.border.default` hairline (a disabled control), `color.text.primary` with the `color.status.danger.strong` octagon (errors).
- **Storybook**: Default, Applied, OwnView, Invalid, EnvironmentFacet, RateLimited.
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

- **Tier**: Molecule (owner/admin) · **Purpose**: one recorded symbol in the recorder admin screen (SCR-140, inside CMP-049) or standalone (SCR-103 drawer): the symbol, why it is recorded, its recording state in words, what it costs (size, rate, share of the recording budget), retention and keep-forever, and the actions the server allows. **Shipped spec:** [E16-D02](../design/E16/E16-D02.md) §4 (#323); handoff checklist [E16-D02-handoff](../design/E16/E16-D02-handoff.md).
- **Props**: `symbol` · `reason: "manual"|"chart_open"|"position_open"|"rule_dependency"|"alert_dependency"` · `state: "starting"|"recording"|"lingering"|"degraded"|"gated"|"refused"|"silent"|"error"|"stopping"|"stopped"` · `lingerUntil?` · `refusal?: "symbol_cap"|"disk_pressure"` · `stopBlockedReason?: "chart_open"|"position_open"` · `recordAgainBlockedReason?: "symbol_cap"` · `startedAt` · `stoppedAt` · `depth: 1|50|200|500` · `dailyGrowthBytes` · `growthEstimated` · `diskUsageBytes` · `budgetShare` · `diskLevel: 0|1|2|3` · `retentionDays` · `pinned: boolean` · `writeReason?: "rbac.owner_only"|"rbac.view_as"` · `stale` · `variant: "table"|"standalone"` · `onStop` · `onKeepRecording` · `onRecordAgain` · `onTogglePin` · `onChangeRetention` · `onOpenDetail`. E16-D02 replaced `recording: boolean` and `onToggleRecording`: the recorder lingers, refuses, gates and errors, and a stop is limited while a chart or a position needs the symbol.
- **Tokens**: inherits CMP-023 ProgressBar (share of the recording budget), CMP-004 Toggle (keep forever) and CMP-001 Button; state words in `color.text.primary`, tone on the state icon (`color.status.success.strong`, `color.status.warning.strong`, `color.status.danger.default`, `color.status.info.strong`; on a stale row, `color.surface.sunken`, the success icon is `color.status.success.default`); a T2 action (E16-D02 §10.5): fill `color.surface.raised` + `color.border.default` hairline, label and CMP-019 `lock` `color.text.tertiary`, reason `color.text.secondary`, never `color.text.disabled` or `opacity.disabled`.
- **A11y**: a blocked action (`stopBlockedReason`, `recordAgainBlockedReason`, `writeReason`) is T2 per E09-D09 §2.2: `aria-disabled="true"`, never `disabled`; the reason node in the DOM at mount as its `aria-describedby`; a CMP-019 `lock` (`decorative=false`, "Not available") leading the full label; role legs through CMP-079 RbacGate. In the CMP-049 grid CMP-016 echoes the reason (2b, E16-D02 D-15); standalone it is inline (2a). Enter or Space re-shows it, announces it once, politely, and sends nothing (E16-D02 §10.5). `ReadOnly` has one `notice.panel_read_only` node.
- **Storybook**: Recording, Stopped, Pinned, NearDiskBudget, AutoChartOpen, AutoPositionOpen, ManualWithPosition, Lingering, Starting, Degraded, Gated, RefusedSymbolCap, RefusedDiskPressure, Silent, Error, Stopping, ReadOnly, Standalone, Stale.
- **Tests**: unit, visual, axe.

### CMP-178 SystemHealthTile

- **Tier**: Molecule (owner/admin) · **Purpose**: one metric tile on the admin Health screen or the SCR-120 overview — ingestion lag, WS state, DB status, engine FPS, a slice's counts — each with threshold-based tone and its own loading, error, unavailable and stale state.
- **Props**: `label` · `value` · `unit` · `state: "loading"|"ready"|"error"|"unavailable"` · `tone: "ok"|"warning"|"danger"|"stale"` · `asOf?` · `lastGoodAt?` · `detail?` · `stopsWorking?` · `onRetry?` · `href` · `env?` · `sparkline?: number[]`.
- **A11y**: `role="region"` labelled by its heading, which is the link; the state word always rendered with one glyph shape per tone (check, triangle, octagon, clock); "Attention:" prefixes a warning; no number for a field not received; age text never live; the shell announces transitions once (degraded or down assertive, recovery polite).
- **Tokens**: inherits CMP-050 Card + CMP-024 Sparkline; `color.surface.raised`, `radius.card`, `color.text.primary`/`secondary`/`tertiary`, `color.status.success.strong`, `color.status.warning.strong`, `color.status.danger.strong`, `color.data-confidence.stale.indicator`, `type.num.base`.
- **Storybook**: Ok, Warning, Danger, Loading, Error, Unavailable, Stale, WithEnvBadge, NotReceived.
- **Tests**: unit, visual, axe.

### CMP-179 FeatureFlagRow (admin feature flags screen)

- **Tier**: Molecule (owner/admin) · **Purpose**: one flag row — the served description, the key, the deployment value and, when it differs, the caller's own value, the derived scope, who changed it and when, notes (overrides, fail-closed, unreadable, requires reload) and one Change control that opens the rung dialog; a blocked flag keeps that control, disabled with its reason and link, never removed.
- **Props**: `flag: FeatureFlag` (generated; the row shows `default_value` and, when it differs, `value`) · `group: "safety" | "gated" | "rollout" | "other"` · `resolution: "stored" | "fail_closed"` · `blockedReason?` (a reason-vocabulary key) · `blockedHref?` · `changeHref?` (a link in place of the Change control, as "→ Maintenance" on `maintenance.mode`) · `affectsOrderEntry?` · `affectsDesktop?` · `requiresReload?` · `state: "idle" | "saving" | "refused" | "unknown"` (`saving`, `refused` and `unknown` render in the rung dialog; the row's values stay as they are) · `onChange` (opens the rung dialog; the row never flips on its own) · `onHistory` · `onRevert?`.
- **A11y**: a CMP-049 table row; the Change control is a button named by the description, the key and the deployment value ("… deployment OFF"), never "on/off"; the values are text; a blocked flag's control is `aria-disabled="true"` (never `disabled`) with its reason in the DOM by `aria-describedby` and a visible link; a CMP-019 `lock` (`decorative=false`, "Not available") leads its label; CMP-079 wraps it with `blockedReason` as `reason`; Enter or Space re-shows the reason and sends nothing; group headings are `h2`; the CMP-093 marker joins the control's description only while it is enabled.
- **Tokens**: `color.surface.raised`, `color.text.primary`, `color.text.secondary` (a blocked control's reason), `color.text.tertiary` (its label and `lock`), `color.border.default` (its hairline), `color.status.warning.subtle` and `.strong` (fail-closed and unreadable notes; the "Affects …" marks, a CMP-011 Tag with the triangle), `color.status.info.subtle` and `.strong` ("Requires reload"), `type.num.sm` (the key), `size.control.comfortable`.
- **Storybook**: Default, SafetyFlag, Gated, AffectsOrderEntry, AffectsDesktop, Overrides, OwnerOverride, YourResolved, Unreadable, FailClosed, RequiresReload, MaintenanceLink, Revert, Saving, Refused, OutcomeUnknown.
- **Tests**: unit, visual, axe.

---

## 7. Chart-engine primitives (CMP-180..199)

These are the building blocks of the fully custom WebGL chart engine (`26-chart-engine-design.md` owns the internal architecture; this catalogue owns the public component-level API surface, props/variants/states/a11y contract, and Storybook/test requirements, matching the same bar as every other design-system entry per `05-accessibility-standard.md` §11.3). Chassis approach per `research/digests/10-frontend-tech.digest.md`: primitive-based composition (Series/Pane/Overlay primitives) analogous to TradingView Lightweight Charts v5's `ICustomSeriesPaneView` / `ISeriesPrimitive` / `IPanePrimitive` model, generalised into CandleViewer's own engine since the engine itself is fully custom (owner decision #1).

### CMP-180 ChartRoot

- **Tier**: Chart-primitive · **Purpose**: top-level engine mount — owns the WebGL2 context, device-pixel-ratio handling, the resize observer, the master render loop and the worker / inline run mode (`26-chart-engine-design.md` §2); hosts N Panes under one TimeAxis (§3.1); owns the DOM-mirror root and the two live regions (`docs/design/E11/E11-D02.md` §10; E06-D03 D1).
- **Props**: `panes: PaneConfig[]` · `timeScale: TimeScaleConfig` · `theme: ThemeTokens` (the resolved `theme-uniforms.json` of the active theme, `16-design-system-brief.md` §11.1 — a data swap, never a CSS cascade) · `density: "comfortable" | "compact" | "dense"` (`docs/design/E11/E11-D05.md` §6; `dense` is chart-only) · `runMode?: "worker" | "inline"` (`26` §8; default `worker` when OffscreenCanvas exists) · `syncGroup?: string` · `onReady?(chart: Chart)`.
- **Variants**: single pane · multi pane (splitters, collapsed stubs, pane focus bar — E11-D02 D14).
- **States** (E11-D02 D16): loading (skeleton grid + "Loading 5 000 bars…") · streaming · stale (data-ink × 0.85 + the `Stale Ns · last hh:mm:ss` chip) · disconnected (frozen chart, DOM scrim, "Disconnected — last data hh:mm") · replay (4 px `color.chart.replay.border` frame + REPLAY chip with clock) · reduced detail (corner badge: "Reduced detail — footprint text hidden" / "Reduced detail — colour only" / "Reduced live detail — background pane" / "Basic rendering — WebGL unavailable") · aggregated (the status-row chip, "Zoomed out · 1 column = N bars" or the PROPOSED "Zoomed out · high–low only", updated on range change, never per tick; E12-D06 §6) · loading band failed ("Couldn't load older bars · Retry", E12-D02 NC-4) · context lost / recovering.
- **A11y**: the canvas carries `role="img"` with a rolling, throttled `aria-label` (symbol, interval, last, change — E06-D03 D4; `05-accessibility-standard.md` §6.4); the root wrapper's role (`application` per E06-D03 D4 vs `img` + an APG-grid mirror per E11-D01 Q4-e) is **open — E11-D07's call**; owns the top-level DOM-mirror container every descendant primitive renders its surrogate nodes into (`05` §6.1; windowed and cursor-centred, E06-D03 D1) and the two pre-rendered live regions (polite ambient values ≤1 per 2 s per field; `role="alert"` for discrete events — E11-D02 §10 "Ambient live-region policy"); Tab order per E11-D02 §12 (toolbar → status chips → per pane: legend → left gutter → plot → handles → right gutter → lock badge → splitter; `Ctrl+\` leaves the region); the focus ring is CMP-039 **once** at the chart boundary with the E06-D03 D10 cursor column inside (E11-D05 §9.1).
- **Tokens**: `color.chart.pane.bg.default`, `color.chart.pane.bg.focused` (both = `color.surface.canvas`), `color.chart.grid.major` (= `color.border.default`), `color.chart.grid.minor` (= `color.grid.line`; off in high-contrast), `color.chart.replay.border`, `color.focus.ring`, `color.surface.raised` (chrome rows, badges, chips), `color.text.primary`, `color.status.warning.strong` (badge glyph) — the `color.chart.*` names are E11-D05 slots (`docs/design/E11/E11-D05.md` §4), PROPOSED aliases until the token PR lands (E11-T04).
- **API sketch** (`26` §8's `Chart`, which supersedes this entry's earlier `ChartApi`):

```ts
interface ChartOptions {
  container: HTMLElement;
  runMode?: "worker" | "inline";
  theme: ThemeTokens;
  density?: "comfortable" | "compact" | "dense";
  syncGroup?: string;
  timeZone?: "UTC" | string;
}
interface Chart {
  readonly panes: readonly Pane[];
  addPane(opts: PaneOptions): Pane;
  removePane(id: PaneId): void;
  readonly timeScale: TimeScale;
  setTheme(theme: ThemeTokens): void;
  setDensity(d: Density): void; // one call sets the whole record (E11-D05 §6)
  subscribe<E extends keyof ChartEvents>(e: E, cb: (p: ChartEvents[E]) => void): Unsubscribe;
  getStats(): FrameStats; // renderProfile, lod tiers, draw calls (26 §8)
  dispose(): void;
}
```

- **Data contract**: the `26` §6 worker protocol — `init { canvas, dpr, theme, chartConfig }` · `resize { width, height, dpr }` · `command { setTheme | setLod | … }` · `frame { frameTimeMs, drawCalls, triangles, uploadedBytes, lod }` · `viewport { timeStart, timeEnd, priceLow, priceHigh, barSpacing }` · `a11y { cursorSummary }` · `error`; market data through the host from `bars.{symbol}.{bar_type}.{param}` and `ticker.{symbol}` (`14-screens-catalogue.md` §0.4, SCR-030).
- **Storybook**: `ChartEngine/ChartRoot` — EmptyChart, SinglePane, MultiPane, ThemeSwitchDemo, DensityComfortable, DensityCompact, DensityDense, HighContrast, ReducedMotion, DegradedTwoD, ContextLostRecovery, SyncAnnouncement (the E11-D05 §9.2 harness: `runMode: "inline"`, the seeded bench fixture, a fixed viewport and DPR).
- **Tests**: unit (API contract), visual (goldens per theme × density on SwiftShader, E11-T08), axe (root label, mirror root, live regions), performance budget (mount ≤150 ms, resize within one frame, ≤18 draw calls per pane — `26` §4), DOM-mirror parity (the mirror's rows equal the fixture's bars at every LOD tier, `26` §12), WebGL-context-loss recovery.

### CMP-181 CandleSeries

- **Tier**: Chart-primitive · **Purpose**: OHLC candlestick/bar/line/equi-volume/delta-volume series (chart-type settings from digest 04 §"Price chart settings").
- **Props**: `data: OhlcBar[]` · `chartType: "candle"|"hollow"|"bar"|"line"|"area"|"baseline"|"heikin-ashi"|"equi-volume"|"delta-volume"` · `barMode: "time"|"tick"|"volume"|"range"|"delta"|"renko"|"pnf"` (the wire `bar_type` names without `heikin_ashi`; `pnf` held: not offered in R1, E12-D03 §2) · `baseline?: { mode: "first-visible" } | { mode: "price"; price: string }` · `upColor/downColor` (theme tokens; swapped only by the convention and the CVD-safe palette, never by account state).
- **States**: forming (`confirm: false`: a static `dash.2-2` (PROPOSED, E11-D05 §7.2) ring in `color.candle.wick`, never the hollow encoding, never motion; at L1 / L2 the word only) · stale (no canvas change; the word "stale" in the readout, the mirror row and the cursor text) · corrected (`amended: true`: E12-D06 §7.3's square in `color.candle.wick` above the high until the next close, plus the word "corrected") · doji and zero-range ("no range") · width capped (equi-volume, delta-volume) · the density ladder L0 / L1 / L2 (L1 hairline wicks and no chip; L2 the aggregated mark with CMP-180's chip) · gap and break (no line, area or baseline bridges an absent slot, a coverage hole or a quiet interval) — E12-D06 §5, §7–§10.
- **A11y**: the DOM mirror is E06-D03's cursor-centred window of bar rows with one polite cursor region (E06-D03 D1, D4, D5; `26` §12); arrow keys move bar to bar; `Home` = oldest loaded bar, `End` = latest bar and resume live (E06-D03 D6; `05` §3.2); row cells, short form and full summary per chart type, Heikin-Ashi announcing real OHLCV first and "Heikin-Ashi close X (derived)" second; on every non-time bar mode (tick, volume, range, delta, Renko) a row names the bar's position and open time ("bar 3 of 5, opened …") before the candle cells, and the mode's progress word stays CMP-226's; the state words "forming", "stale", "corrected", "width capped", "no range" are appended to the row that the polite cursor region reads — E12-D06 §13.
- **Tokens**: `color.candle.up` / `.down` / `.wick` (wick neutral, never remapped), `color.surface.canvas` (tint base, E12-D06 §14.2), `color.axis.text` (sub-pane and delta labels), `color.chart.line` (PROPOSED, E12-D09), `dash.2-2` (PROPOSED, E11-D05 §7.2; the forming ring), `dash.1-1` (PROPOSED, E12-D09; the up span on the narrow marks of E12-D06 §4.3), `pattern.hatch.gap` (PROPOSED, E11-D05 §7), `font.family.mono` via `type.num.*` (axis labels; `font.mono` is not a shipped token).
- **API sketch**:

```ts
interface OhlcBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
interface CandleSeriesProps {
  data: OhlcBar[];
  chartType:
    | "candle"
    | "hollow"
    | "bar"
    | "line"
    | "area"
    | "baseline"
    | "heikin-ashi"
    | "equi-volume"
    | "delta-volume";
  barMode: "time" | "tick" | "volume" | "range" | "delta" | "renko" | "pnf";
  baseline?: { mode: "first-visible" } | { mode: "price"; price: string };
  upColor: string;
  downColor: string;
}
```

- **Storybook**: `ChartEngine/CandleSeries` — Candle, Hollow, Bar, Line, Area, Baseline, BaselineUserPrice, HeikinAshi, EquiVolume, EquiVolumeCapped, DeltaVolume, RangeBars, TickBars, VolumeBars, DeltaBars, RenkoMode, LadderL0, LadderL1, LadderL2, Forming, FormingLine, Stale, Corrected, Doji, ZeroRange, CoverageGap, LineBreakAtGap, NonTimeSeam, VolumeSubPane, Greyscale, CvdSafePalette, InvertedConvention, PartialHistoryBoundary (every story in dark / light / high contrast × compact / comfortable).
- **Tests**: unit, visual, axe (windowed mirror), performance (100k+ bars, ≥58fps budget), keyboard bar-nav interaction test.
- **Data contract**: market data through the host from `bars.{symbol}.{bar_type}.{param}` (`23-ws-protocol.md`), its required fields `generation`, `index`, `t_ms`, `o`, `h`, `l`, `c`, `v`, `confirm` and the `(generation, index)` bar key, never `t_ms`; the optional `close_t_ms` (non-time bars), `turnover`, `trades`, `amended`, `delta`, `cvd`, `min_delta` and `max_delta`; `o`, `h`, `l`, `c`, `v`, `turnover` and the delta fields are decimal strings (`23-ws-protocol.md` §14.3); staleness is the snapshot's `meta.stale` (`BarsBatch` has no `stale` field); `OhlcBar`'s `number` fields are the engine's typed arrays and prices stay exchange decimals at the boundary; spacing is by bar index on every bar mode ("Panning and bar spacing operate in _bar index space_", `26-chart-engine-design.md` §3.5); `barMode` equals the subscription's `bar_type` (E12-D09 §9).
- **Security, performance, observability**: renders market data only: never account state, position side or PnL, and no order affordance (E12-D06 R-7); the performance budget is the Tests line's; the aggregation chip and the history marker are chrome updated on range change, never per tick; no component emits analytics; screens do.
- **Design (series and DS spec)**: `docs/design/E12/E12-D06.md` (geometry, direction table, density ladder, states, gaps, mirror text, tokens) and `docs/design/E12/E12-D09.md` (the enum, the per-mode countdown, the history marker, the consistency contract).

### CMP-182 FootprintSeries

- **Tier**: Chart-primitive · **Purpose**: per-bar grid of FootprintCell (CMP-109) instances bound to the price axis — the highest-effort chassis piece per research (digest 10: "2-3 weeks — single largest line item").
- **Props**: `data: FootprintBarData[]` · `cellMode` · `displayMode` · `lodTextThresholdPx: number` (sourced from `LOD_PROFILE_M0.L1.downSwitchPx` = 8.5px — `docs/design/E06/E06-D01.md` §2/§8 — below this per-cell pixel height, hide text but keep cell + DOM-mirror value).
- **Tokens**: inherits CMP-109.
- **API sketch**:

```ts
interface FootprintBarData {
  time: number;
  cells: FootprintCellData[];
}
interface FootprintSeriesProps {
  data: FootprintBarData[];
  cellMode: "volume" | "bidask" | "delta" | "delta+total";
  displayMode: "profile" | "box";
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

- **Tier**: Chart-primitive · **Purpose**: the strip mode of CMP-131 SpeedOfTapeGauge as a pane inside the chart chassis (E11-D02), with its legend row, window label and baseline sentence (`docs/design/E25/E25-D05.md` §5.6).
- **Props**: same as CMP-131 (`windowSec` is the pane's own value) plus `paneHeightPx` (≥64); the chassis supplies the legend and the cursor.
- **Variants**: pane.
- **States**: default, warming (the sentence in the caption), delayed (the tag "Updates every 1 s, ×4 slower" in the caption, the line at the applied cadence — E17-D01 D5), idle-zero (the line at 0, caption "0 /s · quiet"), stale (the line dimmed per E11-D06 D13, instant under reduced motion — the pane's only animated property), table-alternative, hc, reduced-motion; loading / disconnected / error are chassis-level (E11-D02 D16).
- **A11y**: the sparkline is `role="img"` with the summary "tape speed, last 6 seconds, rising from 12 to 42 trades a second"; the legend row per E11-D02 D12 (8×8 swatch, label "Tape speed · 5 s", cursor value in mono, eye toggle 24×24); table alternative via `Alt+T` (time · trades/s · notional/s · z · band · window); the chassis Tab order (E11-D02 D18). Pattern (hollow, dashed, hatched) marks estimated or absent, never a side (E25-D01 §9.5, PROPOSED for `16` §6; binding today under `16` §6 rules 1 and 5): the usual-rate reference is a solid `color.text.tertiary` line.
- **Tokens**: inherits CMP-131 plus `color.surface.canvas`, `type.num.sm`.
- **API sketch**: `interface SpeedOfTapePaneProps extends SpeedOfTapeGaugeProps { paneHeightPx: number; }`
- **Data contract**: as CMP-131 — **backend-side** on `metrics.{symbol}`, windowed by `windowSec`; one line batch plus the axis text call (E11-D02 D19), never a hatch. Exact data: no `(estimated)` chip.
- **Storybook**: Default, LegendRow, TableAlternative, WarmingUp, Delayed, IdleZero, Stale, HighContrast, ReducedMotion.
- **Tests**: unit, visual, axe, table-alternative parity, performance budget.

### CMP-188 PriceAxis

- **Tier**: Chart-primitive · **Purpose**: the vertical price scale per pane in a right gutter (a left gutter when a secondary indicator scale exists — two gutters per pane, E11-D02 D7); linear / log / percent / inverted; the whole gutter is the drag zone.
- **Props**: `min / max` · `scaleType: "linear" | "log" | "percent"` · `inverted?: boolean` · `locked?: boolean` · `side: "right" | "left"` · `tickFormatter` · `showMarkPill` (default on) · `showIndexPill` (opt-in, SCR-031 Scales) · `onDragScale?`.
- **Variants**: right / left gutter · per density (`type.num.base` / `type.num.sm` / `type.num.xs` by `axisFontSizeClass`).
- **States** (E11-D02 D7): auto · locked ("Price scale locked" badge — the restore control) · mode tag `log` / `%` / `inv` · last-price pill up / down (keyed to the bar's direction, held ≤2/s, ▲ / ▼ glyph) · mark pill `M …` · index pill `I …` · focused (the CMP-039 ring 2 px inside the gutter) · dragging.
- **A11y**: tick labels are part of the DOM mirror; the surrogate is `role="group"` named "Price axis, 63,900 to 64,300, linear, auto"; keyboard: `↑/↓` compress / expand 10 %, `Shift+↑/↓` 25 %, `PageUp/PageDown` pan the range 50 %, `Home` auto-fit, `Shift+F10` the SCR-043 menu, `Esc` back to the plot cursor, `Tab` to the lock badge when locked (E11-D02 §7.1 table); announcements polite ≤2/s ("Price scale locked" once, then the range; "Price scale: auto"); direction is never colour-only (the pill's glyph).
- **Tokens**: `color.chart.axis` (= `color.text.tertiary`; 5.96 / 6.36 / 11.87 on the canvas — E11-D02 CR-2; tick labels, mode tag), `font.family.mono` via `type.num.xs` / `type.num.sm` / `type.num.base`, `type.ui.caption` (mode tag), `color.chart.rule` (= `color.border.default`; the axis rule), `color.candle.up` / `color.candle.down` + `color.chart.pill.text.inverse` (= `color.text.inverse`; the last-price pill, GL text in the axis batch), `color.chart.pill.bg` + `color.chart.pill.border` + `color.chart.pill.text.default` (= `color.surface.raised` / `color.border.strong` / `color.text.primary`; the mark / index pills, GL), `color.surface.raised` + `color.border.strong` + `color.text.primary` (the lock badge, DOM), `color.chart.boundary` (= `color.text.tertiary`; the mark line), `color.focus.ring` (the DOM ring on the surrogate) — every colour the engine draws for this entry is under an engine prefix (`docs/design/E11/E11-D05.md` §4.1b, PROPOSED aliases).
- **API sketch**: `26` §8 declares `PriceScale` (on `Pane.priceScale`) as a type name without members; PROPOSED members, contract-first to the `26` owner (E11-D05 G14): `setMode(mode)`, `setLocked(locked)`, `fit()`; the lock badge is a button whose accessible name is its text.
- **Data contract**: the pane's visible range (`viewport { priceLow, priceHigh }`); mark / index from `ticker.{symbol}`; tick size from `GET /api/v1/instruments/{symbol}`.
- **Storybook**: `ChartEngine/PriceAxis` — Linear, Log, Dragging (keyboard demo), Percent, Inverted, Locked, TwoGutters, LastPricePillUp, LastPricePillDown, MarkPill, HighContrast, Dense.
- **Tests**: unit (the ladder `{1, 2, 5} × 10^n × tickSize`, decimal-round majors D2, the pill nudge D5), visual, axe, keyboard rescale test (the table above), DOM-mirror parity (tick values), performance (gutter re-measured only on a format / font / magnitude change).

### CMP-189 TimeAxis

- **Tier**: Chart-primitive · **Purpose**: the shared horizontal time strip under the lowest pane, master clock for every pane (synced pan / zoom); calendar-ladder decimation (E11-D02 D4); the cluster `[ auto | fit | › ]` (E11-D01 Q2-c).
- **Props**: `range: {from, to}` · `timeZone` (`UTC` default) · `boundary` (US-CHART-009's one setting) · `tickFormatter` · `onPan / onZoom`.
- **Variants**: per density (density gap `G` 96 / 80 / 64 px); time bars (this ladder); non-time bars' label strategy is E12-D06's.
- **States** (E11-D02 D8): following live (`auto` pressed) · paused ("Paused at hh:mm" pill) · session / day boundary · maintenance band (`pattern.hatch.gap`) · loading band ("Loading older bars…") · go-to-date marker · remote crosshair · virtual-now (replay) · focused.
- **A11y**: the surrogate is `role="group"` named "UTC time axis, 14 Oct 07:30 to 13:47, 1 minute bars"; keyboard: `←/→` pan 10 % (`Shift` one width), `+/−` bar spacing × 1.1 (`Shift` × 1.25), `Home` = fit, `End` = latest, `Ctrl+Home` default spacing, `Shift+F10` the SCR-043 menu, `Esc` back to the plot; the cluster is one roving stop (`←/→`, `Enter` / `Space`) whose `auto` button is named by its visible text ("Following live" / "Paused at 13:47 — resume live"); **`+/−` on the focused axis; no modifier + wheel is bound** (E11-D01, ruled 2026-10-20); the zone tag's 1 Hz clock is `aria-live="off"`. Pattern (hollow, dashed, hatched) marks estimated or absent, never a side (E25-D01 §9.5, PROPOSED for `16` §6; binding today under `16` §6 rules 1 and 5): the maintenance band is `pattern.hatch.gap`, a boundary is a `dash.4-4` line.
- **Tokens**: `color.chart.axis` (tick labels, zone tag), `font.family.mono` via `type.num.*`, `color.chart.rule` (= `color.border.default`; the strip rule), `color.chart.boundary` (= `color.text.tertiary`; boundary line, band edges), `color.chart.hatch.texture` (= `color.border.strong`; `pattern.hatch.gap`'s texture), `color.surface.raised` + `color.border.default` (cluster), `color.surface.selected` + `color.border.strong` + `color.text.primary` (pressed `auto`), `color.status.warning.subtle` + `color.status.warning.strong` (Paused pill), `color.surface.hover` + `color.text.secondary` (loading band), `color.chart.marker.goto` + `color.chart.pill.text.on-marker` (= `color.action.primary.default` / `color.text.on-action`; the go-to-date marker and its GL pill), `color.chart.crosshair` at `opacity.muted` (remote crosshair), `color.chart.replay.border` + `opacity.scrim` (virtual-now line, future dim), `color.focus.ring` (the DOM ring on the surrogate) — the engine-drawn chrome binds the `docs/design/E11/E11-D05.md` §4.1b aliases (PROPOSED).
- **API sketch**: `26` §8 declares `TimeScale` (on `Chart.timeScale`) as a type name without members; PROPOSED members (E11-D05 G14): `setVisibleRange(from, to)`, `fit()`, `scrollToLatest()`, `follow(on)`.
- **Data contract**: `viewport { timeStart, timeEnd, barSpacing }`; `sync { groupId, timeRange }`; boundaries and maintenance windows from the instrument / system feed; the WS-corrected server clock (E11-S07).
- **Storybook**: `ChartEngine/TimeAxis` — Default, ZoomedIn, ZoomedOut, Decimation0_5PxPerBar, Decimation3PxPerBar, Decimation12PxPerBar, Decimation50PxPerBar, SessionBoundary, MaintenanceBand, ClusterLive, ClusterPaused, LoadingBand, GoToDateMarker, Replay, HighContrast.
- **Tests**: unit (the ladder, the drop order P3 → P0, the two 8 px exclusion zones, the worked sets of E11-D02 §5.4), visual, axe, keyboard pan / zoom test, sync-across-panes integration test, DOM-mirror parity (the retained labels), performance (≤20 time lines and labels in one SDF call).

### CMP-190 Crosshair

- **Tier**: Chart-primitive · **Purpose**: the synced cursor across the panes of a chart and the charts of a sync group, with the readout (CMP-197); the data cursor and the pointer crosshair are one position with two drivers, last input wins (E11-D01).
- **Props**: `position: {time, price} | null` · `magnetMode: "off" | "weak" | "strong"` (default `off`, E11-D01 D3) · `syncGroupId?: string`.
- **Variants**: none (pointer / keyboard / remote / magnet are states).
- **States** (E11-D02 D3, D9): pointer · keyboard (the E06-D03 D10 cursor column replaces the vertical line while the chart root has focus) · magnet snap (OHLC letter + magnet glyph in the price pill) · remote (dashed at `opacity.muted` with a neutral time pill) · coincident with a gridline (dash phase offset 4 px) · hidden during a drag / wheel burst.
- **A11y**: the crosshair position is the focused bar's DOM-mirror row (`aria-current`); keyboard-driven movement is the accessible path — `←/→` bar, `Shift` ×10 (= `PageUp/PageDown`, E06-D03 D6), `↑/↓` price level, `Home/End`, `Enter` expands the bar in the mirror — and pointer hover is a readout only (`05-accessibility-standard.md` §3.1.6); announcement cadence per E06-D03 D5 (lead 0 ms, repeat window 500 ms, trailing flush ≤250 ms). Pattern (hollow, dashed, hatched) marks estimated or absent, never a side (E25-D01 §9.5, PROPOSED for `16` §6; binding today under `16` §6 rules 1 and 5): the remote line is dashed because it is a remote cursor.
- **Tokens**: `color.chart.crosshair` (= `color.crosshair`; 9.33 / 9.65 / 9.33 on the canvas, ≥3.08 over any gridline — E11-D02 D3), `color.chart.pill.text.inverse` (= `color.text.inverse`; the pill text on the crosshair fill, GL — E11-D02 A-9), `color.chart.pill.bg` + `color.chart.pill.border` + `color.chart.pill.text.default` (the remote crosshair's neutral time pill), `opacity.muted` (remote), `color.chart.focus.ring` + `color.chart.pane.bg.default` (= `color.focus.ring` / `color.surface.canvas`; the D10 cursor column and its halo, drawn on the canvas — `docs/design/E11/E11-D05.md` §4.1b), `type.num.*`, `radius.xs`.
- **API sketch**: `ChartEvents["crosshair"] { time, price, barIndex, cell? }`, edge-triggered (`26` §8); `chart.setMagnet(mode)` is PROPOSED — `26` §8 has no magnet member (E11-D05 G14).
- **Data contract**: `pick { objectId, kind, bar, price, cell? }`, `a11y { cursorSummary }`, `sync { crosshair }` (`26` §6).
- **Storybook**: `ChartEngine/Crosshair` — Default, SyncedAcrossPanes, KeyboardDriven, MagnetOn, RemoteCrosshair, CoincidentGridline, HiddenDuringDrag, KeyboardCursorColumn.
- **Tests**: unit (snap, dash phase, hide-on-drag), visual, axe, keyboard test (the announcement cadence), cross-pane sync integration test, DOM-mirror parity (`aria-current` = the drawn column), performance (pills in the axis batch, +0 draw calls — E11-D02 A-9).

### CMP-191 DrawingToolOverlay (the drawing primitives for every `22` `DrawingTool`)

- **Tier**: Chart-primitive · **Purpose**: the drawing primitives — stroke, fill, handles, selection, lock, snap, label and chip — for every `22` `DrawingTool` (25 values; the five deferred tools by reference, no story), one handle system and one on-canvas text treatment (`docs/design/E14/E14-D08.md` §6, §7); the measure ribbon is the `tool: measure` variant (transient until Pin) and the position read-out the `long_position` / `short_position` DOM sub-contract (E14-D08 §3).
- **Props**: `drawings: Drawing[]` (`22` `Drawing` by reference: `tool: DrawingTool` — 25 values, readers tolerate unknown; `geometry`, `style`, `label`, `locked`, `visible`, `z_index`) · `activeTool: DrawingTool | null` · `magnetMode: "off"|"weak"|"strong"` · `selectedIds: string[]` · `onCreate` · `onChange` · `onDelete` · `onSelect` · `onSendToTicket` (`long_position` / `short_position`, E14-D06 A4) · `readOnly?: { reason }` (the T2 carrier) · `paneColour` (the label outline). `style.colour: DrawingColourToken | "#rrggbb"` where the token form is `color.drawing.default | color.drawing.palette.N` (E14-D08 §5; the hex form is E14-D04's client rule until the field lands, G-1). The API sketch's `DrawingObject` is `22` `Drawing` by reference: its `points` are `geometry`'s anchors and its `style` a `22` `DrawingStyle` (A-7 … A-9).
- **A11y**: DOM-mirrored as E14-D02 §5.8 / §9.4 (RULED), the mechanics verbatim. The handles set is one roving "overlay handles" stop per pane after the plot stop — `group` "Drawings on BTCUSDT 1m, 12 items", roving `tabindex`, `aria-setsize` / `aria-posinset` per surrogate, `aria-describedby` → "Page Up / Page Down move between items. Arrows nudge." (exposed on focus) — ordered by time then price. An object surrogate is a `button` "Trendline 13:40 → 14:05, item 3 of 12" (type + anchors + label; "locked", "hidden", "this pane only", "not saved" appended), `aria-pressed` for selected; locked: "locked" in the name, the edit keys refused "Locked." (the surrogate stays enabled — `Enter` opens the popover); an anchor surrogate is a `button` "Trendline, anchor 1 of 2, 13:40 64,012.5" with `aria-describedby` → the snap text while a snap candidate shows; the from → to readout is the shared polite `status` region "Moved 64,000 to 64,120. Undo available.", coalesced. Keys: `Tab` / `Shift+Tab` enter / leave the stop (focus the drawing's first surrogate); `↑` / `↓`, `←` / `→`, `Shift` ×10 move the focused handle one tick / one bar (the whole drawing on the object surrogate; "64,012.5 → 64,013.0" coalesced); `PageUp` / `PageDown`, `Home` / `End` previous / next surrogate, first / last of the set — one roving stop, never a `Tab` per surrogate; `Enter` opens the properties popover (its first field); `Space` toggles the drawing's selection; `Del` / `Backspace` delete with one undo (`Backspace` PROPOSED, E14-D02 G10) — focus the next surrogate by time, else the plot stop, and an undo that restores a drawing focuses it; `Esc` clears the selection and returns to the plot stop (the ladder's last level); `Shift+F10` / Menu opens the drawing's context menu (Clone · Lock · Hide · Properties · Delete); on a T2 session (Viewer, view-as) the surrogate stays enabled — `Enter` and `Space` are reads — with `aria-describedby` → the pane's reason node; the edit keys change nothing — no nudge, no delete, no request — with the reason announced once, `Enter` still opens the read-only popover, `Space` still toggles the selection and the menu's write items are `aria-disabled` with the reason as each item's second line. Keyboard-draw flow per anchor count: arm the tool on CMP-223 (focus → the plot stop) → one `Enter` per anchor at the data cursor, arrows move the pending anchor, `Ctrl+↑` / `Ctrl+↓` cycle the snap (PROPOSED, E14-D02 Q7) → the last anchor's `Enter` commits; a range (the polyline, 2..100) closes on `Shift+Enter`, or `Enter` on the previous point, or at its last point (E14-D02 §4.3 T27). Announcement strings are E14-D02 §12's, PROPOSED — E14-D10 finalises; an unknown stored colour is announced "Default colour (unknown stored colour)" (PROPOSED — E14-D10 finalises).
- **Tokens**: engine-prefix names only (`theme-uniforms.json` carries nothing else): `color.drawing.default` / `.selected`; the palette `color.drawing.palette.1` … `.8`, the handle `color.drawing.handle` / `.handle.ring` / `.handle.active`, `color.drawing.locked`, `color.drawing.snap` (PROPOSED aliases, E14-D08 §4.1 TP-1 … TP-13, landing in E14-S10's token PR); `color.position.entry` / `.sl` / `.tp` and `color.position.loss.subtle` / `.reward.subtle` (TP-14 / TP-15); labels and chips `color.chart.pill.bg` / `.pill.border` / `.pill.text.default` and the focused handle `color.chart.focus.ring` over a `color.chart.pane.bg.default` halo (E11-D05 §4.1b, PROPOSED — until E11-T04 lands the fallback is the drawn `color.surface.raised`, `color.border.default`, `color.text.primary`, `color.focus.ring`, `color.surface.canvas`: design-side stand-ins whose resolved hex the engine card copies, since no `color.surface.*` / `color.text.*` name reaches the GL export). Metrics, never tokens (`EngineTheme.metrics`): `style.width` 1..8 with `size.stroke.thin` / `.regular` / `.bold` = 1 / 2 / 3 (E13-D03 §4.1), default `fill_opacity` 0.05, the 8 px glyph / 24 px target / 10 · 16 px tolerance, the 12 px magnet radius, the lock glyph at `size.icon.sm` (12), the 2 px zone edges, the chip heights 20 / 24 / 20 one line and 32 / 36 / 32 two lines (compact / comfortable / dense), `type.ui.caption` / `type.num.sm`.
- **API sketch**:

```ts
interface DrawingObject {
  id: string;
  tool: DrawingTool; // 22 DrawingTool: 25 values, open-ended for readers
  points: Array<{ time: number; price: number }>;
  style: DrawingStyle; // 22 DrawingStyle; colour: DrawingColourToken | "#rrggbb", DrawingColourToken = "color.drawing.default" | "color.drawing.palette.1" … "color.drawing.palette.8" (E14-D08 §5)
  // points are 22 Drawing.geometry's anchors; width, dash, fill_colour, fill_opacity and font_size live in style (22 DrawingStyle)
}
interface DrawingToolOverlayProps {
  drawings: DrawingObject[];
  activeTool: DrawingObject["tool"] | null;
  onCreate: (d: Omit<DrawingObject, "id">) => void;
  onChange: (id: string, patch: Partial<DrawingObject>) => void;
  onDelete: (id: string) => void;
}
```

- **Storybook** (`ChartEngine/DrawingToolOverlay`, `15` §0.3 rule 8; every story in both themes and both densities): Trendline, Ray, HLine, Rectangle, Fibonacci, ExtendedLine, VerticalLine, Ellipse, Triangle, ParallelChannel, Text, Callout, Arrow, Polyline, KeyboardDrawDemo, KeyboardDrawOneAnchor, KeyboardDrawThreeAnchors, KeyboardDrawUnbounded, FibRetracement, FibRetracementInverted, FibCompressed5Cases, FibCustom0886, FibExtension, FibTimeZones, AnchoredVwap, AnchoredVwapBands, AnchoredVwapEstimated, AnchoredVwapBesideIndicator, MeasureTransient, MeasurePinned, MeasureAcrossGap, DensityComposite, HighContrast, ForcedColors, ReducedMotion, Greyscale, PositionTool, Handles, Selected, MultiSelected, Locked, Hidden, Unsaved, Conflict, ViewerReadOnly, ViewAsReadOnly, Palette, TwoHundredDrawings.
- **Tests**: unit, visual, axe, the keyboard-draw interaction test per anchor count — 1, 2, 3 — and for the unbounded class (the polyline, `2..100`: `Shift+Enter`, or `Enter` on the previous point, closes it at k ≥ 2 points — E14-D02 §4.3 T27; D02 Q5's compensating control for the brush exception) (explicit CI gate), DOM-mirror parity (the surrogate set equals the drawn set), performance (pick ≤ 1 ms at 200 drawings + 50 order lines, `26` §3.9; one drawing-label text draw call per pane, `26` §4; no per-handle text or shadow), the unknown-colour fallback (a malformed `style.colour` renders `color.drawing.default` and announces it), the T2 keys (no request, one announcement).
- **States**: default, hover (outline, no handles), `placing(n)` (one per anchor count: 1, 2, 3 or a range), selected (the handles, the popover affordance, the tree row revealed), multi-select (one group outline, no per-object handles, a count chip "7 selected"), locked (the lock glyph at the first anchor; drag and nudge refused "Locked"), hidden (not drawn; the row only), unsaved ("changes not saved" chip, text + glyph; "not saved" appended to the surrogate's name), conflict ("changed elsewhere" chip), T2 (as locked for edits; reads stay); the measure variant transient until Pin; forced-colors: the engine reads `(forced-colors: active)` and swaps to the high-contrast token set (E14-D02 §11) — no fourth palette.
- **Forbidden**: no state carried by colour alone (every state has a glyph, a word or a handle change — E14-D02 §5.1); no handle where an order, SL / TP or position line's tolerance overlaps (E14-D02 §5.7); no per-handle text or shadow (E14-D08 §6); no hex literal in a story fixture (the palette is tokens, E14-D08 §4); no animation on the drawings layer (E14-D02 §11).
- **Security**: a malformed or unknown stored colour id degrades to `color.drawing.default`, rendered and announced ("Default colour (unknown stored colour)", PROPOSED — E14-D10 finalises) — never an unstyled or invisible object; the drawing palette holds no colour reserved for status, environment or order-line semantics, so a user-coloured drawing can never be mistaken for a system state (E14-D08 §5, §8).
- **Performance**: drawings render on their own layer (`26` §3.1); drawing labels share one text draw call per pane within the ≤ 6 text draw calls budget (`26` §4); the object index picks in ≤ 1 ms for 200 drawings + 50 order lines (`26` §3.9, B8); drag at ≥ 58 fps with 200 drawings (SCR-037); handles are a one-batch glyph with no per-handle text or shadow.
- **Observability**: not an instrumented surface — `drawing.created` / `.edited` / `.deleted` / `.cloned_to_synced_charts` are the screen's analytics (SCR-037; E14-D02 §14), no sink in R1; the Storybook stories are the visual-regression baseline set.
- **Motion (E14-D08)**: none by design; the snap, selection and undo feedback pairs are E14-D09's (#353) and will append here.
- **Usage (E14-D08)**: `docs/design/E14/E14-D08.md` — §6 the handle / anchor / snap system (8 px two-tone glyph, 24 px target, 10 / 16 px tolerance, the active double ring, the lock glyph, the snap ring), §7 the Label (outlined; the ink per colour and theme) and the Chip (boxed; 20 / 24 / 20 one line, 32 / 36 / 32 two lines at compact / comfortable / dense, as metrics; ≥ 11 px CSS; a number is never truncated), §4 the palette and §5 the token-id contract, §3 the measure variant and the position read-out (a `role="region"` `<dl>` of CMP-036 rows with Send to ticket last, E14-D06 §2.2), §10 adding a tool. Fibonacci levels, band edges and the measure ribbon follow E14-D05 A3: one-hue levels (0, 0.5, 1 at `width`, the rest 1 px), one Label per level `<pct> % · <price>`, thinned by E14-D05 §3's priority walk; the anchored VWAP's always-visible anchor marker, curve, 1 px band edges over a 1 px pane-colour halo and the tail Chip; the ribbon a bounded box at default `fill_opacity` 0.05 with a two-line Chip, never persisted until Pin.

### CMP-192 OrderLineOverlay (chart-trading order/position lines)

- **Tier**: Chart-primitive (trading-critical) · **Purpose**: draggable horizontal line representing a working order or open position's entry/SL/TP, directly on the price axis — chart-click/drag trading surface.
- **Props**: `lines: OrderLineData[]` · `onDragReprice(lineId, newPrice)` · `onDelete(lineId)` · `tickSize: number` (snap).
- **A11y**: each line is DOM-mirrored and independently focusable inside the pane's one roving "overlay handles" stop (E14-D02 §9.4: `PageUp` / `PageDown` move between lines and drawing surrogates, never `Tab`), reposition via focus + arrow keys (steps by `tickSize`) as the keyboard equivalent of drag; delete via `Delete` key with a ConfirmDialog for lines representing live orders above a configurable notional threshold (E31 aligns the stop's order; E14-D08 A-21).
- **Tokens**: `color.order.line`, `color.position.entry/sl/tp`.
- **API sketch**:

```ts
interface OrderLineData {
  id: string;
  kind: "order" | "position-entry" | "sl" | "tp";
  price: number;
  side: "buy" | "sell";
  label: string;
  draggable: boolean;
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

- **Tier**: Chart-primitive · **Purpose**: generic overlay-series primitive for indicator studies (VWAP+envelopes, moving averages, ADX/Aroon for market-regime, etc.); one instance takes one palette slot and spreads its outputs over the identity ladder's tiers of that hue (E13-D03 §3.4, §4).
- **Props**: `series: {time,value}[]` · `style: { color: SlotToken; dash: DashId; width: StrokeId }` (the closed vocabulary of E13-D04 §4: `color.indicator.palette.1..8`, `dash.solid` / `dash.8-4` / `dash.8-3-2-3`, `size.stroke.thin` / `.regular` / `.bold`) · `bands?: { sigma: number; fillOpacity: "opacity.indicator.fill" }[]` (VWAP envelope mode; the fills of a pane share one coverage stencil, never compounding) · `kind: "line" | "histogram" | "band"` (per output; a histogram's `marker` is `bar.full` / `bar.narrow` / `bar.outline`).
- **Variants**: the six line tiers (`dash.solid` × three widths, `dash.8-4` × two, `dash.8-3-2-3`); three bar tiers; three band-edge tiers at the one fill alpha.
- **States**: normal · hidden (an instant redraw, E11-D06 row 38) · computing (the visible window first, D6) · insufficient history (the series starts at the first valid bar; the warm-up zone hatched by reference) · before-history · errored · provisional (the Zig Zag leg: `pattern.dashed.provisional` + the word) · stale (the data-ink dim is E11-D06 D13's) · rebuilding · re-computing (E13-D04 M6: the new draw at full alpha from frame 0, the retained old draw fading over `motion.duration.fast`; a cut under reduced motion).
- **A11y**: no DOM node of its own — named by its CMP-199 legend row, valued by the DOM mirror at the cursor bar (E06-D03 D4); identity never by colour alone (the ladder tier is the non-colour carrier, E13-D03 §4.5); the provisional leg always carries its word.
- **Tokens used**: `color.indicator.palette.1` … `color.indicator.palette.8` (the instance's slot; aliases of existing primitives, hc inherits dark), `opacity.indicator.fill`, `size.stroke.thin` / `size.stroke.regular` / `size.stroke.bold`, `color.candle.up` / `color.candle.down` (Volume's up / down with `glyph.notch.delta`), `color.text.tertiary` (guide levels, zero lines), `color.surface.canvas`; `motion.duration.fast` + `motion.easing.standard` (the re-compute fade; instant under reduced motion — E13-D04 §6 M6).
- **Storybook stories**: `ChartEngine/IndicatorOverlay` — SingleLine, WithBands, Dashed, Tiers, BandFillAlpha, Histogram, Provisional, HighContrast, RecomputeCrossFade, RecomputeReducedMotion.
- **Test requirements**: unit (the tier / id mapping, the assignment function's pairs), visual regression per tier × theme, axe over the mirror, performance (one instanced line draw per pane under the merge rule; the re-compute fade adds one draw for ≤ 6 frames and is shed first — E13-D04 §9).
- **API sketch**: `addIndicator(plugin, { slot?: SlotToken; outputs: { [id]: { kind, tier, fillTo?, marker? } } })` — the plugin's default styling as ids (E13-D03 G-7; E13-T01).
- **Data contract**: `GET /api/v1/indicators` (`IndicatorDescriptor.outputs[]`, `pane`, `compute`, `warmup_bars`, `nullable_when`); the WS `indicators.{symbol}.{bar_type}.{param}` topic (`null` before warmup, `meta.stale`); `GET /api/v1/indicator-presets` (`style` — the closed vocabulary, E13-D04 §4).

### CMP-195 AnnotationMarker (generic on-chart flag: unfinished auction, bar POC, session imbalance)

- **Tier**: Chart-primitive · **Purpose**: generic sparse-event marker primitive underlying BigTradeBubble (CMP-112), LiquidationMarker (CMP-127), ImbalanceStackIndicator (CMP-132), simple flags like Bar POC / Unfinished Auction, and the indicator markers (Supertrend flips, divergence, Zig Zag pivots — E13-D03 §4.4).
- **Props**: `time` · `price` · `shape: GlyphId` (`glyph.diamond` / `glyph.disc` / `glyph.square` for identity; `triangle.up` / `triangle.down` reserved for direction and always drawn with a label) · `icon?` (`icon/divergence`, reserved, with its words) · `color: SlotToken` (the instance's slot; never a free colour) · `provisional?: boolean` (the 1 px dashed outline `pattern.dashed.provisional` + the word "provisional") · `tooltip: ReactNode`.
- **Variants**: identity glyphs (three) · direction (▲ / ▼ with "Flip up" / "Flip down") · divergence (`icon/divergence` with "Div ▲" / "Div ▼" and the full words in the tooltip and the mirror) · provisional pivot.
- **States**: confirmed · provisional · hidden with its series; appearance on bar close is a state flip (E11-D06 D15; instant in both modes).
- **A11y**: base DOM-mirror marker contract reused by all sparse-event primitives listed above: markers are not Tab stops; the keyboard cursor reaches a marker bar like any bar and the mirror row reads the marker's word ("Supertrend flip up", "Bullish divergence", "swing high 63,980 provisional"); glyph ≤ 12 px, an interactive marker's target padded to ≥ 24 px; a marker is never hollow for an exact value.
- **Tokens used**: `color.indicator.palette.1` … `color.indicator.palette.8` (the instance's slot), `color.text.primary` (the DOM label), `color.surface.canvas` (the label's halo); the registry ids `glyph.diamond` / `glyph.disc` / `glyph.square`, `icon/divergence`, `pattern.dashed.provisional`; `motion.duration.instant` (a state flip).
- **Storybook stories**: `ChartEngine/AnnotationMarker` — IconMarker, ShapeMarker, SupertrendFlip, ZigZagPivot, Divergence, Provisional.
- **Test requirements**: unit, visual, axe (the mirror's words), performance (all markers of a pane one instanced glyph draw with DOM labels; the label-yield rule).
- **API sketch**: the marker series of an indicator plugin's `outputs[id].kind: "marker"` with `marker: GlyphId`.
- **Data contract**: Supertrend `direction` (+1 / −1) and Zig Zag `swing_high` / `swing_low` from the `indicators.*` series; the provisional leg is never published (`24` §7.4); divergence events are the detector's (E13-S03), drawn by reference.

### CMP-196 MultiChartLinker (crosshair/level sync engine hook, non-visual)

- **Tier**: Chart-primitive (utility) · **Purpose**: the sync coordinator for multi-chart layouts (`26-chart-engine-design.md` §3.5 `SyncGroup`): the time range is synced within a group, crosshair and levels optionally, **price never** (E11-D01); single-phase propagation once per frame with an `origin` token so re-entrant propagation is impossible (E11-S09).
- **Props**: `groupId` · `linkedPanes: string[]` · `syncModes: { crosshair: boolean; levels: boolean; scale: boolean }` (`scale` links indicator scales within a chart, never price across charts).
- **Variants**: none visual. **States**: joined · left · modes changed.
- **A11y**: n/a directly (non-visual); a sync-state change is announced **once** through the shared polite status region ("Panes linked: crosshair, levels" — E11-S09); the remote crosshair's treatment is CMP-190's.
- **Tokens**: n/a.
- **API sketch**: `ChartOptions.syncGroup`; `SyncGroup { add(chart), remove(chart), setModes(modes) }`.
- **Data contract**: the `sync { groupId, timeRange, crosshair }` message (`26` §6), ≤1 per frame, main → worker so instances sharing the worker propagate without a main-thread round trip.
- **Storybook**: n/a (covered via `ChartEngine/Crosshair` SyncedAcrossPanes and `ChartEngine/ChartRoot` MultiPane / SyncAnnouncement).
- **Tests**: integration test (sync propagation across 2–4 panes; the no-echo assertion), axe on the status region (one announcement per change).

### CMP-197 ChartTooltip (crosshair/hover value readout)

- **Tier**: Chart-primitive (DOM overlay) · **Purpose**: the floating readout box following the crosshair — OHLCV, delta, footprint cell detail, indicator values at the focused time / price; it flips, never clips, and never covers the last-price line (E11-D02 D10).
- **Props**: `content: TooltipField[]` (`{ label, value, unit, colorToken? }`, the E11-S07 field model) · `position: {x, y}` · `visible: boolean` · `mode: "follow" | "docked" | "off"` (SCR-031 crosshair option, E11-D03).
- **Variants**: `mode` follow / docked / off.
- **States**: follow (anchored 16 px right-below) · flipped left / above · shifted clear of the last-price band · docked (pane shorter than the box + 32 px) · overflow after 12 rows ("+3 more · Alt+T") · hidden (pointer out, drag).
- **A11y**: `aria-hidden` — a pointer / visual convenience layer; the same values are always in the DOM mirror and the live region for the keyboard cursor (E06-D03 D9 `getBarSummary`), which prevents duplicate announcement; values are never coloured by direction (▲ / ▼ glyph and `+` / `−` sign; `color.candle.down` on the overlay measures 4.09:1) — E13's coloured indicator values wait for `color.text.buy` / `color.text.sell` (E11-D02 CR-5).
- **Tokens**: `color.surface.overlay`, `color.border.default`, `radius.card`, `elevation.popover` (not `elevation.3`, a primitive — E11-D02 A-2), `color.text.secondary` (title, labels), `color.text.primary` (values), `type.ui.caption` / `type.ui.label` (title per density), `type.num.*`, `space.inset.xs` / `space.inset.sm` / `space.inset.md` per density, `motion.duration.fast` (fade; instant under reduced motion — E11-D06).
- **API sketch**: a DOM component in the main-thread overlay layer fed by `ChartEvents["crosshair"]` and each visible series' `valueAt(bar)`.
- **Data contract**: the bar store and the footprint cell under the cursor (`a11y` / `pick` messages); repositioned at most once per frame (`26` §3.11).
- **Storybook**: `ChartEngine/ChartTooltip` — OhlcvTooltip, FootprintCellTooltip, IndicatorTooltip, FlipLeft, FlipAbove, ClearOfLastPrice, Docked, OverflowTwelveRows, HighContrast.
- **Tests**: unit (flip rules 1–6, the priority stack last-price > pills > order-line labels > tooltip > legend > badge > watermark), visual, axe (hidden-from-AT verification; the mirror carries the values), performance (update cost during rapid crosshair movement, ≤1 reposition per frame).

### CMP-198 ChartWatermark / PaneBackground

- **Tier**: Chart-primitive · **Purpose**: the pane fill behind the data and the `symbol · interval` watermark (` · replay` in a replay session), centred in the price pane only (E11-D02 D13); the pane fill never changes on focus — pane focus is the D14 bar. (Also carries the mandatory Lightweight-Charts-derived-license notice location if any code is adapted, per digest 10 licensing note — engine is fully custom, so this is a placeholder slot only, not a live obligation.)
- **Props**: `text` · `opacity` (fixed at 1 — the token already encodes the lightness; an alpha would double-count under the stale dim).
- **Variants**: none (dense 40 px is a state).
- **States**: default · replay suffix · hidden below 120 px of pane height (160 px comfortable) · dense (40 px).
- **A11y**: `aria-hidden`; decorative (1.50 / 1.31 / 3.03 on the canvas); the symbol and interval are in the toolbar and the canvas `aria-label`.
- **Tokens**: `color.chart.pane.bg.default`, `color.chart.pane.bg.focused` (both = `color.surface.canvas`), `color.chart.watermark` (= `color.border.default`), `font.family.ui`, `font.weight.semibold` (48 px; 40 px dense).
- **API sketch**: `PaneOptions.watermark?: { text }` is PROPOSED — `26` §8 declares `PaneOptions` without members (E11-D05 G14); drawn as SDF text in the axis batch (0 extra draw calls).
- **Data contract**: symbol and interval from the chart config; the replay flag from the session.
- **Storybook**: `ChartEngine/Watermark` — Default, HiddenBelow120px, Replay, Dense40px, FocusDoesNotChangeFill.
- **Tests**: unit (hide threshold per density, width ≤60 % of the plot), visual (three themes).

### CMP-199 ChartLegend (per-pane series/indicator legend with visibility toggles)

- **Tier**: Chart-primitive (DOM overlay) · **Purpose**: top-left per-pane legend — row 0 is the pane-label row (2 px pane-focus bar, label, collapse chevron, pane menu), rows 1…n are series rows (8 × 8 shape swatch = CMP-037 in the slot hue and the tier's shape, label, cursor value, eye toggle); the **one home** for per-series visibility toggles and cursor values (E11-D02 D12, A-14: CMP-224 becomes the toolbar's indicator entry).
- **Props**: `items: { id, label, kind, colorToken: SlotToken, marker: "line" | "thin" | "bold" | "dash" | "dash-dot" | "bar" | "bar-narrow" | "bar-outline" | "band" | "glyph", value, visible, estimated?, error?, warmup?: { needed: number }, beforeHistory?: { startsAt }, outputs?: { name, value, marker }[], children? (ribbon), usedByRules?: boolean, provisional?: boolean, stale?: { ageS: number, lastGoodTs: string }, rebuilding?: boolean, editing?: { param: string } }[]` · `paneLabel` · `collapsed` · `onToggleVisible` · `onRemove?` (E13's remove-with-undo) · `onQuickEdit?` (the primary parameter; the commit is T2 while viewing as or for a Viewer).
- **Variants**: per density (rows 32 / 24 / 24) · `ribbon` (one expandable row: the parent shows the five lengths and a disclosure chevron, five sub-rows with value and eye when expanded, one hue in five tiers; counts as one row for the overflow) · `errored` (`icon/warning` + the word "error", value "—", the message in the row's detail, the eye operable) · `warming-up` ("34 more bars needed" with `icon/bars-missing`; the series starts at the first valid bar; the preview hatches the warm-up zone by reference) · `provisional` (the word "provisional" after the value; the swatch shows the dashed leg beside the glyph) — E13-D04 §5.1.
- **States**: default · one hidden (eye-off icon, `color.text.tertiary` label, value `—`, the word "hidden" in the name) · all hidden (`6 series · 6 hidden`) · overflow "+N more" (visible rows ≤ ⌊0.3 × pane height / row height⌋, min 3) · popover open · collapsed (`6 series · 2 hidden`) · pane-label row focused · estimated series ("(estimated)" in the label and the accessible name) · computing ("computing…", then "still computing…") · before-history (the partial-history glyph; the Owner's "Open recorder" CTA inside CMP-079 RbacGate, the sentence form for a Manager / Viewer) · used by rules (the rule glyph; "used by rules" in the name) · history unavailable ("history unavailable · Retry") · stale (the frozen value in `color.text.tertiary` + "Stale 7s") · rebuilding ("rebuilding…") · editing (the quick-edit field; its `Enter` commit **T2** while viewing as — `rbac.view_as`, the one notice per frame — and for a Viewer — `rbac.permission` — re-showing the reason under the row once) · multi-output (one row, mini swatches in one hue and three shapes) · row add (a `motion.duration.fast` opacity fade-in at the final position; instant under reduced motion — E13-D04 M7) · row remove (leaves at frame 0 with the Undo toast — M8).
- **A11y**: one roving stop placed before its pane's plot: `↑/↓` rows, `←/→` a row's controls (on a ribbon row collapse / expand), `Space` toggles ("EMA 20 hidden" / "shown", polite), `Enter` on the value opens the quick-edit, `Enter` on "+N more" opens a focus-managed popover (`Esc` closes it and returns focus), `Esc` back to the plot; the eye toggle is `aria-pressed` with the **stable name** "EMA 20 visible"; the shape swatch repeats the series kind so colour is never alone; labels ellipsise at 18 characters with the full name in the accessible name and tooltip; every state word is in the accessible name; a T2 commit keeps its native role and full label, `aria-disabled="true"`, the CMP-019 `lock` glyph and the reason linked by `aria-describedby` (E09-D09 §2.2; CMP-079 RbacGate wraps the role legs).
- **Tokens used**: inherits CMP-037 SwatchLegendItem; `color.indicator.palette.1` … `color.indicator.palette.8` (the swatch), `type.ui.label` / `type.ui.body` (comfortable), `type.num.*` (values), `color.text.primary`, `color.text.secondary` (values, status words), `color.text.tertiary` (hidden and stale rows; the T2 label and lock glyph), `color.status.danger.strong` / `color.status.warning.strong` (the error / rule glyph), `color.action.primary.default` (the pane focus bar), `color.surface.raised` + `color.border.default` (the T2 fill and hairline), `color.surface.overlay` + `elevation.popover` (the popover), `space.inset.xs` / `space.inset.sm` / `space.inset.md` (inset per density), `size.control.compact` / `size.control.comfortable` (rows 24 / 32; 24 in dense), `color.focus.ring`; `motion.duration.fast` + `motion.easing.standard` (row add; the popover), `motion.duration.instant` (state flips, row remove); CMP-079 RbacGate · CMP-019 Icon `lock` on the gated commit.
- **API sketch**: a DOM component in the overlay layer; `Pane.legend` (PROPOSED — `26` §8 declares no legend member, E11-D05 G14) reads each series' `valueAt(bar)`.
- **Data contract**: the bar under the cursor (`a11y` / `viewport` messages, ≤1 per frame); the series list from `Pane.addSeries` / `addIndicator`; `indicators.{symbol}.{bar_type}.{param}` points (`null` before warmup, `meta.stale`, the `generation_swap` / `history_repair` snaps); `IndicatorDescriptor.warmup_bars`; the referencing count (E13-D02 CG-2).
- **Storybook**: `ChartEngine/ChartLegend` — Default, ManyIndicators, AllHidden, PlusNMore, PopoverOpen, OneHidden, Collapsed, PaneLabelRowFocused, Comfortable, Compact, Dense, Errored, WarmingUp, BeforeHistory, MultiOutput, Ribbon, UsedByRules, Provisional, Stale, Rebuilding, Editing, RibbonExpanded, RowAdd, RowAddReducedMotion, QuickEditViewAs.

---

## 7A. Auth, shell-surface, chart-chrome & editor-chrome components (CMP-200..248)

This band was added during the cross-document traceability reconciliation (see `18-traceability-matrix.md` §6). `14-screens-catalogue.md` composed 39 components that had no entry in bands 1–7: authentication surfaces (SCR-001..006), shell furniture that is distinct from `CMP-070 AppShell` (status bar, right rail, panic buttons, toast host), chart _chrome_ (toolbars, pickers, chips) as opposed to chart _primitives_ (CMP-180..199, which are engine-level render objects with no DOM), and rule-editor chrome shared by the form and node editors. They are first-class entries here rather than being folded into existing IDs because each has its own a11y contract, Storybook story set and test requirements — the same reasoning §8 gives for not collapsing CMP-147..151.

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
- **A11y**: codes are an ordered list in monospace; "Copy all", "Download .txt" and "Print" are real buttons; the acknowledgement checkbox blocks the continue button and states _why_ it is required.
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
- **As built (E10-S01, #304)**: in `apps/web`, inside the `contentinfo` landmark: the WS connection and latency chips (CMP-210), the latency value, a 1 Hz UTC clock, the bar-close slot, the environment in words and the build version. Only a polite `role="status"` named "System status" holding the latency state words is live, so a value or a tick is never announced. Each value is its own subscribed leaf (zero workspace re-renders over 60 s). Not yet (no source): recorder, armed-rule count, kill-switch access, clock offset.

### CMP-209 RightRail

- **Tier**: Organism (chrome) · **Purpose**: the right-hand drawer stack hosting the notification centre (SCR-014), detector methodology (SCR-058) and detail drawers.
- **Props**: `open: boolean` · `activePanel?: string` · `panels: {id,label,content}[]` · `onClose` · `width?: number`.
- **A11y**: `role="complementary"` with an accessible name; `Esc` closes and returns focus to the trigger; it is a non-modal drawer, so focus is **not** trapped and the rest of the app stays operable.
- **Tokens**: `color.surface.raised`, `elevation.1`, `motion.drawer`.
- **Storybook**: Closed, NotificationsOpen, DetailOpen.
- **Tests**: unit, visual, axe, interaction (Esc, focus return).
- **As built (E10-S01, #304)**: in `apps/web`, mounted inside the `complementary` landmark named "Side panels" (PROPOSED): a launcher strip with one Notifications disclosure button (`aria-expanded`, `aria-controls`) and one 192 px panel holding only its heading until SCR-014 lands. The panel slides by `transform`; the reserved width opens at once and closes at the end of the slide. `Esc` closes it and returns focus to the launcher; nothing is trapped.
- **E40-D02 (#1013; [E40-D02.md](../design/E40/E40-D02.md) §7.4; owner approval pending)**: hosts the `alert-detail` drawer (CMP-046) above the docked rail at `elevation.popover`; the rail itself keeps `elevation.1` and its width. `motion.drawer` is not a token: it reads `motion.duration.normal` with `motion.easing.decelerate` (closing `accelerate`), instant under motion-reduce (X-20).

### CMP-210 HealthChips

- **Tier**: Molecule · **Purpose**: compact cluster of system-health chips (WS, ingestion lag, recorder, exchange rate-limit budget) in the top bar.
- **Props**: `chips: {id,label,state:"ok"|"warn"|"error",value?:string,tooltip:string}[]`.
- **A11y**: each chip's accessible name is "`label`: `state`, `value`" — state is always a word, never a colour alone; a chip with `warn`/`error` is focusable and opens the relevant admin screen.
- **Tokens**: `color.status.*`, `radius.pill`.
- **Storybook**: AllOk, Warning, Error, Mixed.
- **Tests**: unit, visual, axe.
- **As built (E10-S01, #304)**: two chips, in the CMP-208 status bar rather than the top bar: "Connection: <word>" and "WS latency: <state>", each glyph + word, never colour alone. They are status text: no admin link and no focus yet, and no ingestion-lag, recorder or rate-limit chip (no source). The value is outside the live region.

### CMP-211 PanicButtons

- **Tier**: Organism (trading, risk-critical) · **Purpose**: the always-reachable Flatten-all / Cancel-all / Kill-switch cluster in the app chrome (placed by the shell spec, `docs/design/E10/E10-D02.md`: RightRail top; also the system tray). Each control opens its own confirmation; none acts on a bare click. Hi-fi contract: `docs/design/E39/E39-D03.md` §5.
- **Props**: `scope: "account"|"group"|"global"` · `onFlattenAll` · `onCancelAll` · `onKillSwitch` · `enabled: {flatten,cancel,kill}` · `confirmMode: "hold"|"typed"|"single"`.
- **Variants**: `scope` account / group / global × placement shell cluster / system tray; `confirmMode` `single` (the control opens SCR-072, whose Confirm is one activation reached by Tab, Enter — the kill switch, E39-D01 D2 / architect ruling on #829), `hold` (hold 800 ms with a progress ring, or two discrete presses within 5 s (window proposed by E39-D03) — never timing-only, `05-accessibility-standard.md` §3.1 item 4(b)), `typed` (only where the catalogue requires it: Flatten-all in Live types `FLATTEN`, SCR-010).
- **States**: default, hover, focus-visible, active, holding (progress ring + percentage text), armed (after the first discrete press; the accessible name reads "Press again to …"; auto-disarms at the window end), disabled-with-reason (Viewer; a Manager on a global control; offline), engaged (the kill-switch control becomes the status "Kill switch: engaged · n accounts" plus Release… for the owner; never a second engage).
- **A11y**: each is a named `<button>` with the scope and effect in its accessible name ("Flatten all positions — all accounts", "Cancel all working orders — sub_001", "Freeze — all accounts (opens a confirmation)"); never icon-only; `single`: the control opens the dialog, inside it Tab, Enter confirms and focus starts on Cancel; `hold`: exposes progress via `aria-valuenow` with a percentage-text twin (≤2 updates/s under reduced motion) and has the keyboard equivalent hold `Enter` (keydown to keyup; key auto-repeat never counts as a press) or a second discrete press within the window; disabled states follow the disabled-with-reason rule (CMP-079: `aria-disabled` + `aria-describedby`, the control stays in the Tab order, never a bare `disabled` attribute); the cluster stays in the Tab order while disconnected (`docs/design/E17/E17-D01.md`).
- **Tokens**: `color.status.danger.default/strong/subtle`, `color.text.on-action`, `color.text.primary/secondary/tertiary`, `color.surface.raised/hover/selected/overlay`, `color.border.default/strong`, `color.focus.ring`, `border.focus`, `radius.control`, `radius.pill`, `size.control.height`, `size.target.min`, `space.2`, `space.inset.sm/md`, `type.ui.label`, `type.num.sm`, `motion.duration.fast/instant` (plus `motion.duration.hold-confirm`, proposed by E39-D03).
- **Data contract**: `POST /positions/close-all`, `POST /orders/cancel-all`, `POST /trading/kill-switch` (`SetKillSwitchRequest`; defaults `cancel_open_orders: true`, `flatten_positions: false` — decision D-2); every invocation is audited via CMP-093 AuditActionTrigger. Cancel-all cancels only orders that open or add exposure: position TP/SL and reduce-only stops are never cancelled (SR-E39-06, `docs/security/threat-models/E39-risk-killswitch.md`). The engaged state is read from the `system` WS frame `kind: "kill_switch"` (`23-ws-protocol.md` §15.9; a Manager or Viewer receives the role cut) and order entry is disabled on that frame alone.
- **Storybook**: AccountScope, GroupScope, GlobalScope, KillSwitchArmed, KillSwitchEngaged, HoldInProgress, DiscretePressArmed, TypedConfirmError, DisabledViewer, DisabledManagerGlobal, Disconnected, ReducedMotion.
- **Tests**: unit, visual, axe, interaction (the three confirm modes, keyboard hold and the discrete fallback, the Escape disarm, key-repeat never confirms), RBAC-disabled rendering (disabled-with-reason, never hidden).
- **As built (E10-S01, #304)**: not built here. The shell reserves `ShellPanicSlot` last in the TopBar (`header`), per E10-D02 ruling 1, not the RightRail top. It renders nothing (no node, no Tab stop, no stand-in button) until E39-S05 mounts the organism, and `Ctrl+Shift+K` is reserved with no handler. So the Viewer's disabled-with-reason cluster arrives with E39-S05.

### CMP-212 ToastHost

- **Tier**: Organism (chrome) · **Purpose**: the single global mount point that positions, stacks, de-duplicates and expires CMP-045 Toasts.
- **Props**: `position: "top-right"|"bottom-right"` · `max: number = 3` · `defaultDurationMs` · `pauseOnHover: boolean`.
- **A11y**: one `aria-live="polite"` region for informational toasts and a **separate** `role="alert"` region for errors/rejections, so a critical order rejection is not queued behind chatter; toasts are dismissible by keyboard and never steal focus.
- **Tokens**: `space.4`, `elevation.3`, `motion.toast`.
- **Storybook**: Single, Stacked, Overflow, ErrorAndInfoMixed.
- **Tests**: unit, visual, axe (dual live-region separation), interaction (dismiss, pause-on-hover).
- **E40-D02 (#1013; [E40-D02.md](../design/E40/E40-D02.md) §7.4; owner approval pending)**: `max` is 3, SCR-015's three slots (AM-9, X-8; it was 4): from the fourth item the slot farthest from the anchor becomes the counted toast ("4 more alerts — Open Notifications"). Placement (D-20): never over a registered order-entry panel, an armed order ticket, SCR-063, the ticket's cancel and close controls, the top-bar Safety cluster, an open dialog's footer or the element with keyboard focus; bottom-right left of the open RightRail, else top-right, else the one-line counted pill ("3 alerts — Open Notifications"); each app window keeps its own three slots. `motion.toast` is not a token: enter `translateY` 8 px and opacity over `motion.duration.fast` with `motion.easing.decelerate`, exit opacity and `translateX` 8 px with `.accelerate`, fade only under motion-reduce (X-9, X-20). AM-8's "Toasts" landmark name rides DF-19; the built `ToastRegion` `label` stands until then.

### CMP-213 FuzzyList

- **Tier**: Molecule · **Purpose**: the ranked, grouped result list inside CMP-059 CommandPalette and CMP-160 SymbolSearchInput, with matched-substring highlighting.
- **Props**: `items: {id,label,group?,icon?,hint?,matchRanges}[]` · `activeId` · `onActivate` · `emptyMessage`.
- **A11y**: implements the listbox half of the combobox pattern — `aria-activedescendant`, result count announced, group headers as `role="group"` with labels; matched substrings use `<mark>` plus weight, never colour alone.
- **Tokens**: `color.surface.raised`, `color.text.accent`.
- **Storybook**: Default, Grouped, NoResults, LongList(virtualised).
- **Tests**: unit, visual, axe, interaction (arrow navigation, Enter), performance (1 000 items).
- **E08-D05 (A-D05-3)**: Tokens: drop `color.text.accent`; the highlight is `font.weight.semibold` + `color.text.primary` over `color.text.secondary`; an item adds `tags?` (favourite, recent) and `disabled?` + `reason?`, and no interactive slot (an option's children are presentational; the host's detail bar holds the `⋯`). The slot half stays a proposal until the owner picks E13-D02 A-6 or G-2.
- **As built (E08-S09)**: the listbox half only: the host's input keeps focus and drives `activeId` (the option's id is `fuzzyOptionId(id, itemId)`); `onActivate(item)` on a press, an unavailable option too (the host says why); `onContextMenu?(item, point)`. An item is `id`, `label`, `matchRanges?` (`<mark>`), `group?` (consecutive items form a `role="group"` named by it), `icon?`, `hint?`, `tags?`, `disabled?` + `reason?`, and, with no slot, typed text: `values?` (end-aligned cells), `chip?` (a CMP-011), `delisted?` (struck, E08-D05 §6.4) and `description?`. Its name is the label, hint, values (one with no letter or digit, an absent value's "—", left out), chip and tag words, in the order they show, and the row's DOM puts a space between its cells, so the name holds the row's visible text (WCAG 2.5.3; E08-D05 §9.1's name left the values to the description); `reason` is its description, in the DOM at mount. A T2 label stays `color.text.secondary`, the CMP-019 `lock` leading it, except on a delisted row (the strike, its chip and ⊘ instead, E08-D05 §6.4): E08-D05 §9.5 rejects `text.tertiary` on `surface.selected`. Every row is `size.row.height`; above twice `visibleRows?` (default 8) it windows to the visible rows and 4 each way, with `aria-posinset` / `aria-setsize`, so no row is measured; the active option is always drawn (past the window after a scroll, which then gives up an overscan row), and a re-rank that keeps it scrolls it into view. `loading?` draws six static CMP-015 rows in a busy listbox; `emptyMessage` (CMP-026) shows in its place. Active: `color.surface.selected` and a `border.thick` `color.border.selected` bar; hover `color.surface.hover` (light: `color.surface.selected`, no bar, until the CR). Storybook adds Ranked, WithTags, DelistedItem, LongSymbolAndReason, Loading, ReRankKeepsActive, ContrastLight, ContrastHighContrast and Perf1000Items (`perf`); LongList runs through a host combobox.

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
- **Props**: `value: string` · `onChange` · `recent: string[]` · `favourites: string[]` · `showRecordingState?: boolean` · `strip?: (PaneIntervalCode | null)[]` (the favourites strip of SCR-041, a `radiogroup` "Favourites"; E12-D04 §3).
- **A11y**: combobox pattern; each option announces symbol, base/quote and recording state; the current value is readable without opening the popover.
- **Tokens**: `font.mono`, `radius.sm`.
- **Data contract**: options from the cached `GET /instruments` list; recording chip from `GET /recording/symbols`.
- **Storybook**: Default, WithRecents, NotRecorded, Delisted.
- **Tests**: unit, visual, axe, interaction (type-ahead, Esc restores previous value).

### CMP-220 IntervalPicker

- **Tier**: Molecule (trading) · **Purpose**: the interval and bar-mode selector (SCR-042): the R1 time ladder plus the bar modes in the order Time, Tick, Volume, Range, Delta, Renko; Point & Figure is not offered in R1 (E12-D03 §2).
- **Props**: `value: PaneIntervalCode` · `onChange` · `favourites: (PaneIntervalCode | null)[]` (nine slots, each any bar type or empty; E12-D04 §3) · `allowBarModes: boolean` (the E12-S12 flag, #535; E12-D03 D3-1) · `recordingStartedAt?: string | null` (`meta.recording_started_at` of `/market/bars`; `null` = no recorded prints, `undefined` = still checking; name PROPOSED) · `qtyStep?: string` (the instrument's qty step; absent = "Lot size not known yet"; name PROPOSED).
- **Variants**: trigger · menu (Favourites, Time, Recent, Bar modes) · NC-8 parameter editor (outside the menu subtree) · NC-9 favourites editor (in place, no dialog) · comfortable · placement (E12-D03 hand-off Table 1).
- **States**: the bar-mode group off (the R1 default) / on / on without Renko · mode rows T2 (CMP-079: the CMP-019 `lock`, focusable, `aria-disabled`) reading "Needs recorded prints: none yet" (C-24) or, for Volume and Delta, "Lot size not known yet" (C-25) · checking ("Checking recorded prints…", C-29) · shallow recording (enabled, with the depth line C-27) · pending (the trigger adds " …") · a favourite slot the server cannot serve (⊘ with "Not available yet", C-26) — E12-D03 §1, §5.
- **A11y**: a menu button (`aria-haspopup="menu"`, `aria-expanded`) named "Interval: 15 minutes" or "Bar mode: Volume, 50 BTC per bar" (C-39); one `role="menu"` with labelled groups, the Bar modes group's caption stating that the x-axis is not time (C-37); chips and mode rows are `menuitemradio` (`aria-checked`); a T2 row stays focusable with `aria-disabled`, its reason as the description, re-announced once on activation; the parameter editor is a `group` with a CMP-008 `spinbutton` ("Volume per bar, BTC"); the favourites editor a `listbox`; "About bar modes" is a CMP-069 inline disclosure outside the menu subtree (E12-D03 hand-off Tables 2–3); one speaker per event: the shell's polite region speaks the commit after unmount, and the per-panel region skips its switch-result line for that commit (E12-D04 §14, D04-C23).
- **Tokens**: `type.num.sm` / `type.num.base`, `color.surface.overlay`, `elevation.popover`, `radius.card`, `radius.control`, `color.action.selected`, `color.border.selected` at `border.thick`, `color.surface.hover` (light: `color.surface.selected` until E12-D03 DS-5), `color.focus.ring` at `border.focus`, `color.text.primary` / `secondary` / `tertiary` (E12-D03 DS-2; replaces `font.mono`, which is not a shipped token, and `space.1`).
- **Storybook**: TimeIntervals, BarModes, Favourites, Trigger, TriggerPending, TriggerBarMode, BarModesNoRenko, NeedsRecordedPrints, ShallowRecording, CustomInterval, ParamEditor, FavouritesEditor, Comfortable, Placement, FavouritesAnyBarType (every story in dark / light / high contrast × compact / comfortable).
- **Tests**: unit, visual, axe, interaction (`Enter`, `→`, `Esc`, the digits `1`–`9`; never a commit on blur); plus a **catalogue-level test** asserting that every bar-mode label, description key, unit and default rendered by CMP-220, SCR-031, SCR-041, SCR-042 and SCR-045 resolves to one record of the bar-mode registry, and that a mode present in one surface is present in all, or fails (`docs/design/E12/E12-D09-barmodes.json`).
- **Data contract and security**: `bar_type` and `param` of `/market/bars` with the shipped bounds (E12-D03 §2); the "Needs recorded prints" state reads `meta.recording_started_at` of `/market/bars` under `marketdata:read` and reveals only "recorded or not, since when", no storage, limit or job detail; no record action (the route shows only with `recording:write`); favourites need `settings:write`; no component emits analytics; screens do.

### CMP-221 ChartToolbar

- **Tier**: Organism (chart chrome) · **Purpose**: the chart panel's top strip — symbol, interval, chart type, indicators, drawings, templates, settings, chart-trading arm toggle.
- **Props**: `symbol` · `interval` · `chartType` · `armed: boolean` · `onAction(actionId)` · `density`.
- **A11y**: `role="toolbar"` with roving tabindex and `aria-orientation="horizontal"`; every control has a text name; overflows into CMP-041 Menu at narrow widths rather than truncating silently.
- **Tokens**: `color.surface.sunken`, `space.1`.
- **Storybook**: Comfortable, Compact, Armed, Overflowing, ViewerReadOnly.
- **Tests**: unit, visual, axe, interaction (roving focus, overflow behaviour).

### CMP-222 ChartTypeToggle

- **Tier**: Molecule (chart chrome) · **Purpose**: switch between the nine chart types of E12-D05 §3.1 (candles, bars (OHLC), hollow candles, line, area, baseline, Heikin-Ashi, equi-volume, delta-volume) and the footprint overlay toggle.
- **Props**: `value: ChartType` (= CMP-181 `chartType`) · `onChange` · `footprintOn: boolean` · `onToggleFootprint`.
- **A11y**: CMP-003 SegmentedControl semantics; each option names the chart type in text (icons alone are insufficient); footprint is a separate `aria-pressed` toggle because it composes with any base type.
- **Combination rule**: footprint is a separate `aria-pressed` toggle that composes with every base type; Heikin-Ashi with footprint, and Heikin-Ashi on a non-time bar mode, are never applied without a choice: a CMP-028 `info` decision callout (E12-D02 NC-7, a composition) keeps "Keep {current type}" as the safe default (`Esc` chooses it) or, on a non-time mode, offers "Switch to time bars"; with equi-volume or delta-volume and footprint on, the width mapping is suspended ("· width mapping off") — E12-D05 §3.4 (PROPOSED, D05-Q1, owner approval pending (#2701)).
- **Tokens**: inherits CMP-003.
- **Storybook**: Candles, Hollow, Bars, Line, Area, Baseline, HeikinAshi, EquiVolume, DeltaVolume, FootprintOn, HeikinAshiOnNonTime (the "Switch to time bars" callout, E12-D06 D06-Q1), HeikinAshiFootprintCallout, WidthMappingOff.
- **Tests**: unit, visual, axe.
- **Series visual spec**: `docs/design/E12/E12-D06.md`; the option set equals CMP-181 `chartType`. No order authority; no component emits analytics; screens do. The volume sub-pane toggle has no design home yet (E12-D05 D05-G6; E12-D09's open-questions log).

### CMP-223 DrawingToolbar

- **Tier**: Organism (chart chrome) · **Purpose**: the vertical tool rail of SCR-037 — the cursor group (cursor, crosshair, Select area), lines, shapes, Fibonacci, analysis (anchored VWAP, measure, the position tool), annotation (text note, callout, arrow, polyline), the controls (magnet mode, keep tool active, lock-all, hide-all, delete-all apart) and the overflow with its Deferred section; it arms tools and writes nothing itself (E14-D02 §3, E14-D03).
- **Props**: `activeTool`, `onSelectTool`, `magnetMode: "off" | "weak" | "strong"`, `onMagnetModeChange`, `keepActive`, `onToggleKeepActive`, `selectAreaMode`, `onToggleSelectArea`, `lockAll`, `hideAll`, `hiddenCount`, `onDeleteAll`, `disabledReason` (per control), `armedInOverflow?` (PROPOSED), `railVisible?` / `onToggleRailVisible` (RULED yes, E14-D08: "Show tool rail" `menuitemcheckbox` at the top of CMP-221's `[Draw]` menu when the rail is user-hidden, persisted under a PROPOSED settings key beside `drawing.keep_active` / `drawing.magnet_mode`; T2 per E14-D03 §8.1 — view-as first (`rbac.view_as`), then `settings:write` → `rbac.permission` "Your role can't change settings." — in rendering 2a: `aria-disabled` + `aria-describedby` → the leg's node, the CMP-019 `lock` leading the label, the reason as the second line, `Enter` changes nothing and re-shows the reason once, politely) (E14-D03 A2, §5.4, §8.1).
- **A11y**: `role="toolbar"` vertical with roving tabindex, one Tab stop after the status chips and before the first pane's legend; each tool's accessible name is the tool name, its interim chord — `Alt+L` `Alt+H` `Alt+O` `Alt+R` `Alt+D`, `Ctrl+M` (scheme (a), registered by E14-S10) — surfaced in the CMP-016 tooltip via CMP-022 Kbd and linked by `aria-describedby`; the armed tool `aria-pressed` and announced politely, since the canvas cannot convey mode to a screen reader; `Enter` / `Space` arms and moves focus to the plot stop, `Enter` again disarms; `Esc` with nothing armed is not consumed; every gated control — on the rail, in the overflow and in the tool button's context menu — is E09-D09 T2 (CMP-079 RbacGate + the CMP-019 `lock`, `decorative=false`, "Not available"; `aria-disabled`, never `disabled`) (E14-D02 §3.4 Tables 2 / 3; E14-D03 A2).
- **Tokens**: the column `color.surface.raised`, width `size.control.compact` / `size.control.comfortable`, padding `space.1`; a button `size.control.compact` / `.comfortable` square, fill none · `color.surface.hover` · `color.surface.selected`, `radius.sm`; the glyph `size.icon.md`, `color.text.primary` (enabled) · `color.text.tertiary` (T2, delete-all included) · `color.status.danger.default` (delete-all enabled); the inset bar `border.thick`, `color.border.selected`; the separator `border.hairline`, `color.border.default`; the badges 8 px, halo `color.surface.raised`, the T2 badge `color.text.tertiary`; the focus ring `border.focus` at 2 px offset, `color.focus.ring`; the chip `color.surface.raised`, `color.border.strong`, `type.ui.caption`, `color.text.primary`, glyph `size.icon.sm`; the tooltip `color.surface.overlay`, `elevation.3`, `radius.sm`, `type.ui.caption`, `color.text.primary`, the reason `color.text.secondary`; the Kbd `color.surface.raised`, `radius.xs`, `font.family.mono`; the menus `color.surface.overlay`, `elevation.3`, `radius.sm`, rules `color.border.default`, T2 items `color.text.tertiary` / `.secondary`; the `[Draw]` button (CMP-221's) on `color.surface.sunken`, glyph `color.text.primary` (E14-D03 §9.3).
- **Storybook** (`Organisms/DrawingToolbar`): Default, ToolActive, KeepActive, MagnetOff, MagnetWeak, MagnetStrong, AllLocked, AllHidden, Overflowing, CollapsedDraw, ViewerReadOnly, ViewAsReadOnly, FocusVisible, Zoom200, Comfortable, HighContrast, ForcedColors, Light (E14-D03 §11; `Light` and `Zoom200` kept as named stories beside `15` §0.3 rule 7's axes).
- **Tests**: unit, visual, axe (zero serious / critical; one tabbable item), interaction — keyboard tool selection (`Tab` → `↓` → `Enter` arms and moves focus to the plot stop; `Enter` again disarms), `Esc` on the rail with nothing armed is not consumed, the T2 press (no event, one announcement), delete-all with nothing deletable, the magnet menu's `Esc` returning focus to the magnet button, the overflow's arrow reachability including `aria-disabled` items (E14-D03 §11).
- **States**: E14-D03 §4 rows 1–20 — default, hover, focus-visible, armed (`aria-pressed` + the inset bar + the pressed fill + the chip's word), keep-active, magnet off / weak / strong, all-locked, all-hidden ("200 drawings hidden"), Viewer read-only, view-as read-only, overflowing, collapsed into `[Draw]` (under 1280 px or user-hidden; "Show tool rail" at the top of the menu), the deferred items (`aria-disabled`, no glyph), zoom 200 %, forced-colors, high-contrast.
- **Forbidden**: no single unmodified key arms a tool (E14-D02 §3.4; `05` §3.2); no `disabled` attribute on a gated control (E09-D09 §2.2); no animation on the rail (E14-D03 §4 row 19); no second toolbar stop per pane.
- **Performance**: inline SVG symbols referenced by `IconName` (E14-D03 C8); the rail re-renders on its own state only, never per tick.
- **Observability**: no component emits analytics; SCR-037's screen events do.
- **Motion (E14-D08)**: none by design; nothing on the rail animates (E14-D03 §4 row 19); the pairs are E14-D09's (#353) and will append here.
- **Usage (E14-D08)**: the rail arms tools and writes nothing itself; lock-all / hide-all / delete-all act on the drawings set through the host (E14-D03 §1.2); the icon set is CMP-019's drawing glyphs (E14-D03 §2.1); the collapsed content is CMP-221's `[Draw]` menu (E14-D03 §5.4).

### CMP-224 IndicatorChips

- **Tier**: Molecule (chart chrome) · **Purpose**: the toolbar's indicator entry — a count chip (`Ind 4`, with one state suffix: error / stale / computing / hidden, error first) that opens SCR-036 for this chart; per-indicator toggle, settings and remove live on CMP-199's rows (E11-D02 A-14; E13-D02 D29; E13-D03 §7.3).
- **Props**: `count: number` · `suffix?: { kind: "error" | "stale" | "computing" | "hidden"; n: number }` · `onOpen` (SCR-036).
- **Variants**: `Ind 0` · `Ind n` · `Ind n · 1 error` · `Ind n · 2 stale` · `Ind n · 1 computing` · `Ind n · 1 hidden` · `Ind 20` (the cap); compact (a 20 px pill in a 24 px hit box) / comfortable (a 24 px pill).
- **States**: default · focused (the ring on the canvas) · pressed while the drawer is open; every change of the count or the suffix is a state flip, instant in both modes (E11-D06 D15; E13-D04 M9).
- **A11y**: a `button` on the toolbar's roving stop; name "Indicators: 4 on this chart, 1 hidden — open the object manager" (E13-D02 §11.3); `Enter` / `Space` open SCR-036, `Esc` from the drawer returns focus to the chip; the suffix word is text, the hue rides on the glyph only, so colour is never alone; no live region of its own (the legend rows announce their events).
- **Tokens used**: `color.surface.raised` (the pill), `color.text.tertiary` (the 1 px border; the hidden glyph), `color.text.primary` (the words), `color.status.danger.strong` / `color.status.warning.strong` / `color.status.info.strong` (the suffix glyph: error / stale / computing), `radius.pill`, `type.ui.caption`, `color.focus.ring`; `motion.duration.instant` (a state flip, both modes).
- **Storybook**: `Molecules/IndicatorChips` — None, Several, WithHidden, WithError, WithComputing, WithStale, AtCap, Focused.
- **Tests**: unit (the suffix order error → stale → computing → hidden), visual, axe, interaction (keyboard open / return).

### CMP-225 DeepStatsStrip

- **Tier**: Organism (order flow) · **Purpose**: the configurable per-bar statistics strip beneath the chart (SCR-033) — volume, bid/ask volume, delta, max delta, CVD, imbalance counts, with threshold colouring and optional sparkline.
- **Props**: `rows: {id,label,unit,value,thresholdState?,sparkline?:number[]}[]` · `alignedToBars: boolean` · `onConfigure`.
- **A11y**: rendered as a real `<table>` aligned to the bar grid (not canvas), so values are readable cell by cell; threshold state is a word plus an icon; has a documented "read current bar's stats" keyboard shortcut.
- **Tokens**: `font.mono`, `color.status.*`, `space.1`.
- **Data contract**: values from the `footprint.{symbol}.{interval}` WS topic and `GET /market/footprint` bootstrap; recomputed per closed bar and on each in-progress-bar tick, coalesced to 4 Hz.
- **Storybook**: Default, AllRows, ThresholdsBreached, WithSparklines, Empty(no recording).
- **Tests**: unit, visual, axe, performance (60 visible bars × 12 rows update budget).

### CMP-226 BarCountdown

- **Tier**: Atom (chart chrome) · **Purpose**: time remaining until the current bar closes or, on non-time bars, the forming bar's progress toward its target (E12-D09 §5), in the status row beside the mark / last / spread readout — one home (E11-D02 D11).
- **Props**: `msRemaining: number` · `progress?: { done: string; target: string; unitLabel?: string }` (non-time bars, beside `msRemaining`; the host floors `done` and `target` to the field's display precision and passes strings, which the component renders as given) · `interval: Interval` · `barType: CandleSeriesProps["barMode"]` · `warnBelowMs?: number` (default 10 000, US-CHART-008).
- **Variants**: comfortable / compact (DOM chrome, two-valued).
- **States**: normal (`bar close 0:41`, `color.text.secondary`) · **warn** (≤10 s: `0:08 closing` — adds the word "closing" and `font.weight.medium` on a `color.status.warning.subtle` pill with a `color.status.warning.strong` clock glyph; the flip is instant in both motion modes, E11-D06 D15) · closed (`closed`, `color.text.tertiary`) · non-time bars: in the same slot, the activity progress text where the mode has a target ("Tick 412 / 1,000", "Vol 37 / 50 BTC", "Range 23 / 40", "Delta 12 / 25 BTC", the delta row only when the subscription sets `include_delta`, which the host sets on every delta-bar subscription, PROPOSED), numbers floored to the field's precision so the text never reads "50 / 50" before the close; else `—` with the accessible name "No countdown: bars close on activity, not time" (PROPOSED; Renko, range without a known tick size, and delta without `include_delta`); Point & Figure is not offered; a stale feed freezes the text and the status row's stale chip speaks for it (stale from ticker age > T1 5 s, E11-D02 §10); text, never a bare fill (E12-D09 §5).
- **A11y**: text, never a bare progress ring; updates at 1 Hz with `aria-live="off"` by default, and on non-time bars with each forming-bar update the host coalesces, still `aria-live="off"`; an opt-in announcement at 10 s ("Bar closing in 10 seconds") in Settings → Accessibility, never default, on time bars only, since no close time can be predicted on non-time bars (PROPOSED, E12-D09 §5); the warn state adds a word, not just a colour.
- **Tokens**: `font.family.mono` via `type.num.sm` (digits), `type.ui.caption` (label), `color.text.secondary` (normal: 8.81 / 8.98 / 14.35 on the row), `color.status.warning.subtle` + `color.text.primary` + `color.status.warning.strong` (warn: text 9.86 / 15.62 / 11.16, glyph 7.56 / 4.11 / 7.56; `warning.strong` as text measures 4.11 in light and is rejected), `color.text.tertiary` (closed / n/a: 5.62 / 5.92 / 11.21), `font.weight.medium`, `color.surface.raised` (the row).
- **Storybook**: `Atoms/BarCountdown` — Normal, Warning, Closed, NonTimeBar, Comfortable, HighContrast, ReducedMotionIdentical, NonTimeTick, NonTimeVolume, NonTimeRange, NonTimeDelta, NonTimeRenko, NonTimeRangeNoTickSize, NonTimeDeltaNoIncludeDelta, NonTimeStaleFrozen (band 7A has no `15` §0.3 rule 8 band; the title follows the tier).
- **Tests**: unit (the 10 s threshold, the server-clock source; per mode, E12-D09 §5: the source field, flooring, `—` where no target exists, the frozen text on a stale feed), visual, axe (`aria-live="off"`; the opt-in announcement fires once).
- **Security and observability**: no order authority; no component emits analytics; screens do.

### CMP-227 EstimatedBadge

- **Tier**: Atom (honesty affordance, cross-cutting) · **Purpose**: the one canonical `(estimated)` badge on every heuristic-derived value, opening CMP-069 InfoPanel / SCR-058 at the detector's section; CMP-011's `estimated` variant is a deprecated alias that renders this component (`docs/design/E25/E25-D05.md` §3–§4).
- **Props**: `detector: DetectorId` (`DetectorMethodology.detector`'s six members — `iceberg`, `stop_run`, `absorption`, `exhaustion`, `big_trade`, `regime` — plus `queue_position`, `order_count`, `liquidity_cluster`, `trade_cluster`, `liquidation_cluster`, `funding`; the union is PROPOSED, E25-D05 G2) · `variant: "inline"|"marker"|"section"` · `size: "sm"|"md"` · `confidence?: "low"|"medium"|"high"`. **No `onOpenMethodology` prop**: the drawer binding comes from the required `EstimatedMethodologyProvider` (name PROPOSED), which supplies `openMethodology(detector)` and emits `methodology.opened{detector}`; rendering outside the provider is a development-time error, never a decorative chip.
- **Variants**: `inline` (beside the value it qualifies — rows, header value cells, alert rows, option lists), `marker` (the on-chart affordance: a hollow glyph-only pill with a dashed outline and, over data ink, a 1 px pane-colour halo outside it (E06-D03 D10); the visible word is mandatory in the same pane — the pane's CMP-199 legend row carries the `section`-grade word ("Stop runs (estimated)") or a text label sits beside the mark — and is also in the DOM-mirror label and the tooltip; the hit target is the mirror surrogate), `section` (the `md` pill after a heading's text, still a button). The inline callout at decision points is a composition — CMP-028 `tone="info"` with the sentence "this is an estimate, not exchange-provided fact" and an `inline` badge — not a fourth variant. The `marker` may be hosted on a drawing's computed series (the anchored VWAP with a pre-history anchor, E14-D05 §6): the pane word is carried by the drawing's tail chip; the `DetectorId` union gains `vwap_bar_approx` with a `DetectorMethodology` entry (PROPOSED); until it lands, activation opens the tooltip (E14-D05 A4).
- **States**: default, hover (2 px outset outline — no reflow), focus-visible (`color.focus.ring` 2 px at 2 px offset; the host row keeps `overflow: visible`, so the ring is never clipped in a 24 px row), active, tooltip-open (CMP-016: hover and focus, `Esc`, dismissible — WCAG 2.2 SC 1.4.13; the first sentence is provenance), with CMP-239 (leftmost, ≥4 px gap, two accessible names), with confidence word, hc, greyscale; no disabled, loading, error or empty state by construction (E25-D05 §4.2).
- **A11y**: a native `<button>`; the literal word "estimated" is in the accessible name — "Estimated, <display name>[, <low|medium|high> confidence]" — this badge may **never** be conveyed by colour, icon or opacity alone; the visible word is "(estimated)" in both sizes (the hue rides on the outline and the glyph, never on the word; "Est." only where a sibling spec already uses it in a table cell, pending E25-D01 C15 / Q4); `aria-describedby` → the tooltip, `aria-haspopup="dialog"`; it is focusable and `Enter`/`Space` opens the methodology drawer at the section with focus on its heading, returned to the chip on close; hit target ≥24×24 CSS px by padding, never by glyph size; never on exact data; its look may be embedded only by a host — a native `<button>` whose activation calls `openMethodology(detector)` through the `EstimatedBadgeHost` context, which throws otherwise; CMP-133 is the only host today (E25-D05 §3, §7.4). Pattern (hollow, dashed, hatched) marks estimated or absent, never a side (E25-D01 §9.5, PROPOSED for `16` §6; binding today under `16` §6 rules 1 and 5).
- **E08-D04 — composition with CMP-239 FreshnessMarker (confirmed contract)**: `estimated` and data-confidence `stale`/`gapped` are different claims — one says "derived, not raw" (never changes once computed), the other says "not current" (temporal). They are never merged into one chip. When a value is both, CMP-227 renders first (leftmost) and CMP-239 renders immediately after it; each keeps its own accessible name so a screen reader announces both ("Estimated, low confidence. Stale, 4 seconds."). Visual separation: distinct shapes (pill vs dot+text) plus a minimum 4px gap — never touching or overlapping.
- **Tokens**: `color.status.info.subtle` (fill), `color.status.info.default` (outline `border.hairline`, glyph), `color.text.primary` (the word), `radius.badge`, `type.ui.caption` (sm) / `type.ui.label` (md), `size.icon.sm` (glyph; IconName `estimated`, PROPOSED — a solid ring or the "≈" alone at 12 px, the dashed ring at ≥16 px), `space.inset.xs` (the 4 px composition gap) / `space.inset.sm` (padding), `border.thick` (hover), `color.focus.ring` + `border.focus`, `size.target.min`; pattern id `pattern.dashed.estimated` for `marker` (PROPOSED). Measured: the word 10.74 / 15.44 / 12.16 (dark / light / hc); `color.status.info.strong` text on the `.subtle` fill fails light (4.34) and is never used.
- **API sketch**: `interface EstimatedBadgeProps { detector: DetectorId; variant: "inline" | "marker" | "section"; size: "sm" | "md"; confidence?: "low" | "medium" | "high"; }` · `useEstimatedMethodology(): { openMethodology(detector: DetectorId): void }` (throws outside the provider).
- **Data contract**: the chip exists when the series item carries `estimated: true` (`23` §14.7), the descriptor `confidence: "estimated"` (`24` §7.1; `22` `MetricSeries.estimated`) or a Derived value inherits `estimated=True` (`25` §1) — never from a catalogue adjective; the drawer reads `GET /detectors/methodology`; the provider emits `methodology.opened{detector}` (transport: E25-D05 G9).
- **Storybook**: Inline, Marker, Section, SizeSm, SizeMd, Hover, FocusVisible, Active, TooltipOpen, WithConfidenceWord, WithStaleFreshnessMarker, CalloutComposition, LongDetectorName, HighContrast, Greyscale, ReducedMotion, OutsideProviderThrows.
- **Tests**: unit (the provider requirement throws; no `host`-mode badge renders outside a bound native `<button>`; the name carries the word), visual, axe; plus a **catalogue-level test** asserting that every screen listed in `14-screens-catalogue.md` §12.3 under "(estimated) labelling" renders this component, a composition test asserting CMP-227 + CMP-239 never collapse into a single accessible name, and a pane-level assertion that no `marker` renders without a visible (estimated) word in the same pane.

### CMP-228 PreviewTile

- **Tier**: Molecule · **Purpose**: the live miniature preview inside settings dialogs (footprint, heatmap, theme, density) showing the effect of the current settings on sample data.
- **Props**: `kind: "footprint"|"heatmap"|"candles"|"theme"` · `settings: object` · `sampleData?: unknown`. `kind` adds `"scales"` and `"ladder"`; `source?: "live" | "sample"`, `emptyText`, `errorText`, and `value` / `caption` for `ladder` (`docs/design/E05/E05-D02-rest.md` §6 J21, RULED 6438042003; E11-D03 D03-CR-3, E32-D04 D04-A2). `kind` also adds `"chart"` (chart type and bar mode, E12-D05 §8); `caption?: string` is also the visible "Changes:" line.
- **A11y**: `role="img"` with a name describing the current configuration in words; it is decorative-adjacent, so the settings themselves always remain independently readable — the preview is never the only disclosure of a setting's effect. Five states — live, sample, empty, error and collapsed (ladder) — and never a spinner: a recomputing preview keeps its last frame; an empty or errored tile is named "Preview unavailable" (J21).
- **Tokens**: `color.surface.sunken`, `radius.card`, a 1 px `color.border.default` hairline (decorative; it does not show in light, accepted: J2); empty and error text `type.ui.caption` + `color.text.secondary`; a ladder value `type.num.base` + `color.text.primary` (J21). (Replaces `radius.md`, a primitive.)
- **Storybook**: Footprint, Heatmap, ThemeDark, ThemeLight, Sample, Empty, Error, Ladder, LadderCollapsed (J21).
- **Tests**: unit, visual, axe.
- **Design (usage spec):** [E32-D04.md](../design/E32/E32-D04.md) §8 (E32-D04; owner approval pending; the ladder builder's five glance tiles — total qty, average entry, total notional, projected risk vs cap, projected requests vs minute budget — as `role="img"` with one name, never the only disclosure: the pinned totals row repeats every figure; the `ladder` kind, `value` and `caption` props are a PROPOSED amendment routed to this catalogue's owner).

### CMP-229 ArmToggle

- **Tier**: Molecule (trading, safety-critical) · **Purpose**: the arm/lock control (US-ORD-005) gating click-to-trade on the chart and DOM, and the persistent armed indicator of `05-accessibility-standard.md` §3.1 rule 5 — the one armed treatment (E30-D04 §2.1).
- **Props**: `state: "locked"|"armed"|"unknown"` (the arm store's enum; `armed: boolean` derived) · `onChange` · `scope: "chart"|"dom"|"global"` · `autoDisarmMs?: number` · `environment: "demo"|"live"` · `account`, `size`, `coin` (the pill's content) · `pausedReason?: string`.
- **Variants**: `scope` chart / dom / global; DEMO / LIVE (the LIVE second action is CMP-044 `standard`).
- **States**: LOCKED (neutral pill, lock glyph, "LOCKED · {account} · {size} {coin}"), ARMED (the attention pill "ARMED {mm:ss} · {account} · {size} {coin}"; static once entered), PAUSED ("hotkeys paused — typing in {field}" replaces the account · size segment in compact, a second line in comfortable), UNKNOWN ("Arm state unknown — submit off", fails closed), EXPIRING (polite at 60 s and 10 s), RETURN ("LOCKED — disconnected {mm:ss}, reconnected", held until the next arm), read-only (T2: the LOCKED pill keeps its shape and full label in `color.text.tertiary`, its lock is the one CMP-019 `lock`, the reason sits under the pill — E30-D04 §16).
- **A11y**: `aria-pressed` switch whose name states the scope and state and stays stable while armed ("Chart trading: locked"; the remaining time is the CMP-035 node in `aria-describedby`, never in the name); arming in Live requires a deliberate second action and announces the change assertively; auto-disarm announces when it fires (the level per E30-D05 / E30-D02 O-L); the hotkeys-paused line is the same element's second line; the countdown is CMP-035 (`aria-live="off"`, polite at 60 s / 10 s); T2 per E09-D09 §2.2 for the role legs (CMP-079 RbacGate; CMP-019 Icon `lock`).
- **Tokens**: `color.status.warning.subtle` / `color.status.warning.strong` (ARMED), `color.surface.raised` + `color.text.secondary` (LOCKED / UNKNOWN), `color.text.primary`, `radius.pill`, `font.family.mono` + `type.num.sm` (`mm:ss`), `type.ui.label`, `space.inset.sm`.
- **API sketch**: `interface ArmToggleProps { state: "locked" | "armed" | "unknown"; onChange: (armed: boolean) => void; scope: "chart" | "dom" | "global"; autoDisarmMs?: number; environment: "demo" | "live"; account: string; size: number; coin: string; pausedReason?: string }`
- **Data contract**: the arm state from `POST /settings/arm` (the `arm_token`, TTL) and the arm store's enum (E30-S04); the six auto-disarm triggers (E30-D02 SC-2).
- **Storybook**: Locked, ArmedDemo, ArmedLive, AutoDisarmPending, Paused, Unknown, Expiring, ReturnedFromDisconnect, EntryTransition, AutoDisarmExit, LiveArmDialog, ReadOnlyT2, ScopeChart, ScopeDom, Comfortable, HighContrast, ReducedMotion.
- **Tests**: unit, visual, axe, interaction (no accidental single-key arm in Live), E2E (no order can be placed while locked), the sustained-state test (no animation after the entry), the exit persistence test, the threshold announcements, the T2 test.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §16 (E30-D04; owner approval pending).

### CMP-230 OwnOrderMarker

- **Tier**: Molecule (trading) · **Purpose**: the marker showing the user's own working orders and position on the DOM ladder rows and heatmap (US-DOM-006).
- **Props**: `side: "buy"|"sell"` · `qty: number` · `orderType` · `accountLabel?: string` · `isGroupAggregate?: boolean` · `onCancel` · `onDrag`.
- **A11y**: within the ladder's DOM-mirror table the marker is text in a dedicated "Your orders" column ("Buy 0.5 limit, account Sub-2"), so it never depends on a canvas-drawn glyph; cancel is reachable by keyboard from that cell.
- **Tokens**: `color.buy`, `color.sell`, `font.mono`.
- **Data contract**: from `orders.{accountId}` / `positions.{accountId}` WS topics, filtered to the ladder's visible price window; drag-to-modify issues an order-amend REST call.
- **Storybook**: SingleOrder, MultipleAtPrice, GroupAggregate, PositionMarker.
- **Tests**: unit, visual, axe (DOM-mirror parity), interaction (keyboard cancel).

### CMP-231 TifSelect

- **Tier**: Atom (trading) · **Purpose**: time-in-force selector (GTC, IOC, FOK, PostOnly) with per-order-type availability (E30-D02 D13: Market → IOC only; Limit → GTC default, IOC, FOK, PostOnly; Conditional follows the triggered type).
- **Props**: `value: Tif` · `onChange` · `available: Tif[]` · `orderType` · `unavailableReason?: Record<Tif, string>`.
- **Variants**: Limit, Market, Conditional.
- **States**: closed, open, option-focused, unavailable-option (the validity look of E30-D04 §2.5: the option at `opacity.disabled` with its reason as its description, `aria-disabled`, focusable, no lock), read-only (T2 on the whole select).
- **A11y**: unavailable options are disabled **with a stated reason** ("Market orders are always IOC on Bybit"), never silently absent; the expansion of each acronym is in the option's accessible description; `Enter` on an unavailable option selects nothing and announces the reason once; T2 per E09-D09 §2.2 on the whole select (CMP-079 RbacGate; CMP-019 Icon `lock`).
- **Tokens**: inherits CMP-009 Select (`color.surface.overlay`, `elevation.popover`, `radius.control`); `color.text.primary` (options), `color.text.secondary` (descriptions), `opacity.disabled` (the validity look only), `color.focus.ring`.
- **API sketch**: `interface TifSelectProps { value: Tif; onChange: (v: Tif) => void; available: Tif[]; orderType: string; unavailableReason?: Partial<Record<Tif, string>> }`
- **Data contract**: the availability matrix is a static client-side vocabulary of Bybit's order-type rules; no WS/REST dependency.
- **Storybook**: Limit, Market, PostOnlyUnavailable, Conditional, Open, OptionFocused, ReadOnlyT2, Comfortable, HighContrast.
- **Tests**: unit (the matrix per order type), visual, axe (every option named, the description present), keyboard (the unavailable option focusable; `Enter` selects nothing), the T2 test.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §17 (E30-D04; owner approval pending).

### CMP-232 LimitsChip

- **Tier**: Molecule (trading) · **Purpose**: compact display of the binding constraints on the current ticket — profile risk cap, remaining daily loss budget, max leverage, allowed-symbol status, exchange min/max qty; the binding limit is an attention pill with the word "binding", the number and the authority (E30-D02 D14); a `results` rendering for the confirm (E30-D03 A12).
- **Props**: `limits: {id,label,value,used?,max?,binding:boolean,source:"profile"|"exchange"|"global",estimated?:boolean}[]`.
- **Variants**: none binding ("Limits: none binding"), binding ("binding: {name} {value} ({authority})"), disclosure open (CMP-036 rows), `results` (the confirm).
- **States**: none-binding, binding, changed (the value-change highlight on the changed row, announced once), disclosure open / closed, stale (CMP-239 beside a wallet-fed limit).
- **A11y**: the **binding** limit is named in text and announced when it changes ("Blocked by daily loss cap: 480 of 500 USDT used") via one polite region at ≤ 1 per 2 s; each limit states which authority sets it, so the user knows whether the owner or the exchange is the constraint; the disclosure is a `<button>` with `aria-expanded` / `aria-controls`.
- **Tokens**: `color.status.warning.subtle` / `color.status.warning.strong` (the binding pill and its ⚠ glyph), `color.surface.raised` + `color.text.primary` (the neutral pill), `font.family.mono` + `type.num.sm` (every number), `radius.pill`, `color.surface.overlay` + `elevation.popover` (the rows), `space.row.height.compact` / `space.row.height.comfortable`.
- **API sketch**: `interface LimitsChipProps { limits: { id: string; label: string; value: string; used?: number; max?: number; binding: boolean; source: "profile" | "exchange" | "global"; estimated?: boolean }[] }`
- **Data contract**: from the per-account profile (`GET /exchange-accounts/{id}/profiles`), global risk policy (`GET /risk/summary`), and instrument filters (`GET /instruments/{symbol}`); the confirm's `results` from `POST /trade-groups/preview` (E30-D03 A12).
- **Storybook**: NoneBinding, RiskCapBinding, DailyLossBinding, SymbolNotAllowed, BindingChanged, DisclosureOpen, Results, StaleLimit, Comfortable, HighContrast, ReducedMotion.
- **Tests**: unit (which limit binds), visual, axe, the announcement test (once per change, ≤ 1 per 2 s), the highlight twin test.
- **Design (DS spec):** [E30-D04.md](../design/E30/E30-D04.md) §18 (E30-D04; owner approval pending); the confirm rendering: [E30-D03.md](../design/E30/E30-D03.md) A12.

### CMP-233 RuleOptions

- **Tier**: Molecule (rule engine) · **Purpose**: the non-condition settings block of a rule. **E36-D03 —** every `RuleLimits` field with its default, unit and phrase (DCR-7, memo §5.6): `once` / `once_per`, `cooldown_ms`, `max_fires_per_hour` / `max_fires_per_day` (caps 600 / 5 000; above the default owner-only, above the cap refused — SR-104; the fire-limit fields above the default wrap in CMP-079 RbacGate with the CMP-019 `lock` for a non-owner, its reason `rbac.owner_only` "Only the owner can raise a rule's fire limits.", a PROPOSED verb — E09-D09 §2.2; E36-D02 §16, §14), `max_actions_per_fire`, `max_notional_per_fire` / `max_daily_notional`, `require_confirmation`, `evaluation_timeout_ms`, `kill_switch_on_error_count`; the two always-said lines "No rule notional cap — your account's risk caps still apply." and "Turns itself off after 5 errors in a row — you re-arm it."; no rule-level "only tighten" box (memo C12) — the ratchet is a per-action read-out; `name` and `description` live in the header (E36-D02 §9).
- **Props**: **E36-D03 —** `options: RuleLimits` · `onChange` · `mode: "disabled"|"simulate"|"armed"` (`RuleMode`) · `conflictsWith?: {id, name}[]` (per CMP-159).
- **A11y**: a labelled `<fieldset>` per group; switching to `armed` is a deliberate control that surfaces SCR-085 rather than toggling silently — the dialog is E35-D02's; the switch never toggles silently and never reads armed before the `rules` frame confirms; declared conflicts are listed in text with links. **E36-D03 —** each field is labelled with its default in the help text; the always-said lines are text, not live regions.
- **Tokens**: `space.4`, `color.surface.sunken`.
- **Storybook**: **E36-D03 —** Defaults, Changed, OwnerOnlyAboveDefault, AboveCap, WithConflicts.
- **Tests**: unit, visual, axe.

### CMP-234 ValidationPanel

- **Tier**: Organism (rule engine) · **Purpose**: the shared validation surface for **both** rule editors (form mode SCR-081 and graph mode SCR-082) — errors, warnings and IR-compilation diagnostics, each anchored to the offending condition row or node. **E35-D03 —** a further host: SCR-089's validation-failure list in the import dialog; each entry moves focus to the offending pre-check row (the jump-to-offender pattern).
- **Props**: `diagnostics: {id,severity:"error"|"warning"|"info",message,anchor:{kind:"row"|"node"|"edge",id},fixHint?}[]` · `onFocusAnchor`. **E36-D03 —** `anchor` is populated with the form model's row ids by E36-T01 (memo G11: no validator diagnostic names a row today); the primary message speaks rows ("Row 2 — …"), the shipped validator text sits in a details disclosure (P10); **SCR-088's Issues segment reuses this component** (E36-D03 §5).
- **A11y**: a `role="log"` list ordered errors-first; each entry is a button that moves focus to the offending row/node (the sole mechanism by which a keyboard user navigates graph diagnostics); the error count is announced on every recompile. **E36-D03 —** the count change is a text swap, never a background flash (the 300 ms debounce would exceed 3 flashes / s). **E35-D03 —** in the import host (SCR-089) the log is `aria-live="off"`; the one count sentence comes from the dialog's polite region (E35-D04 F-10).
- **Tokens**: **E36-D03 —** `color.status.danger.default` / `color.status.danger.strong`, `color.status.warning.default` / `color.status.warning.strong`, `space.3`; `color.status.warn` and the bare `color.status.danger` do not exist in `packages/ui/tokens`.
- **Data contract**: diagnostics come from `POST /rules/validate` against the shared rule IR, so form and graph modes report **identical** diagnostics for the same rule (the round-trip invariant, OD#11).
- **Storybook**: Valid, WithErrors, WithWarnings, GraphAnchored, FormAnchored. **E35-D03 —** ImportFailures.
- **Tests**: unit, visual, axe, interaction (focus-to-anchor in both modes), contract test (same IR ⇒ same diagnostics in both editors).

### CMP-235 EditorModeToggle

- **Tier**: Molecule (rule engine, safety-relevant) · **Purpose**: switch a rule between form and node-graph editing, carrying the shared IR across without loss (OD#11).
- **Props**: `mode: "form"|"graph"` · `onChange` · `lossyWarning?: {constructs: string[]}` · `dirty: boolean`.
- **A11y**: CMP-003 SegmentedControl semantics. **E36-D03 —** the switch is **allowed** (memo C10, E36-D02 §4): a construct the target editor cannot represent renders in place as the read-only card with the lead-in "Authored in the graph editor: {sentence}. Open in the graph editor to change this.", and `lossyWarning.constructs` becomes the per-construct list; the rule is never degraded silently; the round-trip indicator lives on CMP-145 (E36-D02 §16), not here.
- **Tokens**: inherits CMP-003.
- **Storybook**: **E36-D03 —** FormActive, GraphActive, LossyWarning, DirtyUnsaved, ReadOnlyCardInPlace.
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
- **`compact` presentation for dense grids**: the cell only swaps a class; the age text lives once per row (the Status chip) or once per panel (the footer line) and reaches assistive tech through `aria-describedby`. Age format "Stale 7s", "Stale 2m", "Stale 1h".
- **A11y**: never colour-only — text label (mandatory for every non-`live` state) pairs with the reinforcing colour; `disconnected`/`reconnecting` states bubble to the parent CMP-028 banner (`role="alert"`/`role="status"`) rather than re-announcing per cell; a degraded state entering/exiting a _panel_ (not per-row) announces once via the parent's live region, collapsing flapping within 5s into one announcement — individual FreshnessMarker instances do not each own a live region.
- **Tokens**: `color.data-confidence.{state}.text`, `color.data-confidence.{state}.indicator`, `color.data-confidence.{state}.surface` (only `stale` defines a surface tint; see `packages/ui/tokens/semantic-*.tokens.json`).
- **Composition rule with CMP-227 EstimatedBadge**: see CMP-227 entry — they are always rendered as two separate, non-overlapping elements, never merged.
- **Escalation process for an undefined state**: a later epic needing a data-confidence state not in the eight above raises a design-system change request against this entry (comment on the `16-design-system-brief.md` token PR or open a new `E08-D*`-scoped ticket) — it must **not** add a local one-off variant on a consuming screen. The precedence table in `docs/design/E08/E08-D01.md` §2 is the single source for state ordering and must be updated in the same change.
- **Storybook**: Live, Stale, Reconnecting, Disconnected, Resyncing, Gapped, Backfilling, Delisted, WithEstimatedBadgeComposition.
- **Tests**: unit (precedence/never-stacked assertion, CSS-class-only render), visual (both themes), axe (redundant non-colour channel present for every non-live state), live-region collapse test (flapping within 5s → one announcement).
- **Motion spec**: [E08-D11.md](../design/E08/E08-D11.md) (E08-D11; the single flip's timing: chip at 0 ms, one `normal` settle of the dim, instant under reduce; contract lines proposed as A-rows).

### CMP-240 TreeView (E13-D02 G-1)

- **Tier**: Molecule · **Purpose**: a hierarchical list with `role="tree"` semantics; CMP-049 Table's semantics are table / grid, not `role="tree"`, so CMP-049 stays SCR-045's (E13-D02 §10 G-1, §17 C-5).
- **Props**: TBD (E36-D05 #947). E13-D02 G-1 names the parts, not their prop names: `role="tree"` / `treeitem` / `group`, `aria-multiselectable`, roving tabindex, type-ahead, disclosure, a drag handle with the `Alt+↑/↓` keyboard twin, an inline-rename slot (CMP-058), a per-item action slot (CMP-002 buttons), virtualised above 200 items (E13-D02 §10 G-1).
- **Variants**: TBD (E36-D05 #947).
- **States**: default, selected, multi-selected, hidden item, locked item, loading, empty (E13-D02 §10 G-1).
- **A11y**: `role="tree"` / `treeitem` / `group`, `aria-multiselectable`, roving tabindex, type-ahead, disclosure; the drag handle has the `Alt+↑/↓` keyboard twin (E13-D02 §10 G-1).
- **Tokens**: TBD (E36-D05 #947). Item height per consumer: SCR-036 tree row 24 / 32 px, indent step 16 / 20 px (E13-D02 §2 sizes table); SCR-088 tree item `size.row.compact` / `size.row.comfortable` (E36-D03 §13).
- **Storybook**: Default, MultiSelect, Nested, InlineRename, Empty, Loading (E13-D02 §10 G-1).
- **Tests**: TBD (E36-D05 #947); the §0.3 item 7 baseline applies.
- **Motion spec**: under `motion: reduce` a reorder repositions instantly (no slide), with the announcement carrying the position (E13-D02 §11.6); otherwise TBD (E36-D05 #947).
- **Consumers**:
  - SCR-036 Indicator manager: the object tree with multi-select (`Ctrl+Space` toggle, `Shift+↑/↓` extend, `Ctrl+A` per group; selected rows carry `aria-selected="true"`) (E13-D02 §6.3 D22; §10 G-1).
  - The rule node inspector's object list, later (E13-D02 §10 G-1).
  - SCR-088 Rule IR inspector, Tree segment (PROPOSED consumer row): "the IR tree of SCR-088: node = IR key / value, `aria-level`, type-ahead, a Copy path action per item; no drag handle, no rename" (E36-D03 §9, BQ-D03-2 RULED).
  - SCR-088, E35-D03's delta (PROPOSED, D03-A5): account leaves show the masked value "Main (…4f2a)" with a visually-hidden "account, masked"; Copy path on `Enter` (E35-D03 §7, §14 D03-A5); keys `↑` / `↓`, `←` / `→`, `Home` / `End`, type-ahead, `*` (E35-D03 §10).
- **Design (DS spec):** [E13-D02.md](../design/E13/E13-D02.md) §10 G-1 (E13-D02, status In Review; entry owner E05); consumers: [E36-D03.md](../design/E36/E36-D03.md) §9, [E35-D03.md](../design/E35/E35-D03.md) §7.

### CMP-243 BulkActionBar (E13-D02 G-4)

- **Tier**: Molecule · **Purpose**: a selection-count toolbar with actions: "N selected" + action buttons + Clear (E13-D02 §10 G-4).
- **Props**: TBD (E36-D05 #947).
- **Variants**: TBD (E36-D05 #947).
- **States**: TBD (E36-D05 #947). E13-D02 G-4 gives one rule: the bar appears with a selection (E13-D02 §10 G-4).
- **A11y**: `role="toolbar"`; appears with a selection; in the Tab order after its list (E13-D02 §10 G-4). Its appearance never moves focus (E36-D03 §2).
- **Tokens**: TBD (E36-D05 #947). Bar height per consumer: SCR-036 32 / 40 px (E13-D02 §2 sizes table); SCR-080 buttons 24 / 32 px (E36-D03 §13).
- **Storybook**: TBD (E36-D05 #947).
- **Tests**: TBD (E36-D05 #947); the §0.3 item 7 baseline applies.
- **Motion spec**: SCR-080's appear is opacity + 8 px slide, `fast` · `decelerate`, instant under reduce (E36-D03 §10 row 9); otherwise TBD (E36-D05 #947).
- **Consumers**:
  - SCR-036 Indicator manager: "**3 selected** · Hide · Show · Lock · Unlock · Delete · Clear selection", each a CMP-001 button (E13-D02 §6.3 D22).
  - CMP-114 PositionsGrid bulk cancel; the journal (E13-D02 §10 G-4).
  - SCR-080 Rules list (PROPOSED consumer row): "3 selected · Disarm · Export · Clear"; **Clear** empties the selection and returns focus to the table (E36-D03 §2, §9, BQ-D03-2 RULED).
- **Design (DS spec):** [E13-D02.md](../design/E13/E13-D02.md) §10 G-4 (E13-D02, status In Review; entry owner E05); consumer: [E36-D03.md](../design/E36/E36-D03.md) §2, §9.

### CMP-248 HistoryMarker (E12-D02 NC-2)

- **Tier**: Chart-primitive with a DOM surrogate · **Purpose**: the chart's history markers: a full-height boundary with a text tag (recording start, built-from, lookback), a labelled band (recording gap, kline coverage hole) and a seam (non-time gap, series restart); never a point flag.
- **Props**: `kind: "boundary"|"band"|"seam"` · `variant: "recording-start"|"built-from"|"lookback"|"recording-gap"|"kline-hole"|"non-time-gap"|"series-restart"` · `from: number` · `to?: number` (a band's end; both x-axis slots: a bar's `index` under the `(generation, index)` key on every bar mode, never `t_ms`; the host maps a time such as `recording_started_at` to its first slot) · `tag: string` (the visible text, verbatim from `14` SCR-030 and E12-D02 §7) · `action?: { label: string; onActivate(): void }` (`Build earlier bars` on built-from, `Load more` on lookback) (names PROPOSED).
- **Variants**: boundary (recording start; built-from with `Build earlier bars`, which wins where it meets the lookback; lookback with `Load more`) · band (recording gap; kline coverage hole) · seam (non-time gap; series restart).
- **States**: default · tag focused (its description shown) · action busy (CMP-038 text in the chart strip) · long tag (wraps inside the pane, never truncated) · the hi-fi of each is E12-D08's (#243), to confirm when merged.
- **A11y**: text-bearing, never icon-only; the tag is a `role="note"` with `tabindex="0"` in the chart's `Tab` order (E12-D02 D-11), its accessible name the tag's text and its accessible description the tag's description (`aria-describedby`); the action is a `button`, and `Enter` / `Space` activates it; both show the focus ring `color.focus.ring` at `border.focus` (`15` §0.3 rule 4); no announcement of its own: the chart strip states the boundary once (CMP-028 `chart-strip`), and the DOM mirror's gap row reads the band's text (E12-D06 §13).
- **Tokens**: `color.chart.boundary` (= `color.text.tertiary`; the boundary line and band edges), `color.chart.hatch.texture` (= `color.border.strong`; the band's texture), the band's `pattern.hatch.gap` (PROPOSED, E11-D05 §7), `color.focus.ring` at `border.focus` (the tag and the action); a boundary is never hatched (E12-D06 §8.3); the `color.chart.*` names are E11-D05's engine-chrome aliases, PROPOSED until E11-T04.
- **Storybook**: `ChartEngine/HistoryMarker` — RecordingStart, BuiltFrom, Lookback, RecordingGap, KlineHole, NonTimeGap, SeriesRestart, TagFocused, ActionBusy, LongTag, HighContrast (every story in dark / light / high contrast × compact / comfortable).
- **Tests**: unit, visual, axe (the tag in the `Tab` order; never icon-only), DOM-mirror parity (the gap row), performance (drawn on range change, zero per-frame cost).
- **Data contract and security**: recording start from `meta.recording_started_at`, holes from the coverage report (`/market/data-coverage`); recording start and gaps only, the same scope as CMP-220's recorded-prints state; no component emits analytics; screens do.
- **Why a new entry, not a variant**: CMP-195 AnnotationMarker is a point flag at one time and price, without a span, an action or a screen-reader contract of its own; the history marker spans the pane and carries both. **Design**: `docs/design/E12/E12-D09.md` §6; hi-fi E12-D08 (#243).

---

## 8. Summary tallies

| Band                                                               | Count                                                        |
| ------------------------------------------------------------------ | ------------------------------------------------------------ |
| Atoms (CMP-001..039)                                               | 39                                                           |
| Molecules (CMP-040..069)                                           | 30                                                           |
| Organisms — chrome & nav (CMP-070..099)                            | 30                                                           |
| Trading-specific (CMP-100..139)                                    | 40                                                           |
| Rule engine & node-graph (CMP-140..159)                            | 20                                                           |
| Watchlist/alerts/journal/replay/audit (CMP-160..179)               | 20                                                           |
| Chart-engine primitives (CMP-180..199)                             | 20                                                           |
| Auth / shell-surface / chart-chrome / editor-chrome (CMP-200..248) | 43                                                           |
| **Total catalogued components**                                    | **242 — see the E08-D04, E36-D05 and E12-D09 addenda below** |

**Addendum (E08-D04, 2026-09-27):** CMP-239 FreshnessMarker was added as the design-system contribution for the
data-confidence vocabulary (`docs/design/E08/E08-D01.md`) — a genuinely new cross-cutting atom (per-value
freshness marker for WatchlistRow/KeyValueRow/tape/DOM cells) with no existing entry to extend, per the ticket's
scope. This is the only count change since the lock below; future changes still require the same rationale.

**Addendum (E36-D05, #947):** CMP-240 TreeView and CMP-243 BulkActionBar are catalogued from E13-D02's G-1 and G-4
proposals (`docs/design/E13/E13-D02.md`, G-1 / G-4), whose A-2 row asks for the entries and for the last band to be
extended to CMP-243. Both are reused by E36-D03 (SCR-088's tree, SCR-080's bulk bar) with no existing entry to extend.
IDs 241 and 242 stay unassigned (E13-D02's G-2 / G-3 propose them; not catalogued here).

**Addendum (E12-D09, #244):** CMP-248 HistoryMarker is catalogued from E12-D02's NC-2 candidate (`docs/design/E12/E12-D02.md`, NC-2): a full-height boundary, band and seam with actions and a screen-reader contract of its own, which CMP-195's point flag cannot carry. CMP-180..199 is full and 241–242 and 244–247 are held by other packs' proposals (E13-D02; E10-D02's HotkeyConflictChip; E33-D04), so band 7A is extended to CMP-248. Future changes still require the same rationale.

**Decision — final count was locked at 238, not 120–180 (supersedes the brief's range for this deliverable).** The count was 199 until the cross-document traceability reconciliation (`18-traceability-matrix.md`), which found 39 components composed by `14-screens-catalogue.md` that had no catalogue entry; rather than silently dropping those references or overloading existing IDs, band 7A was opened at CMP-200..238. 238 is the number backlog tickets are generated from. Rationale for not consolidating: the trading-specific, chart-engine and band-7A entries intentionally enumerate each node-graph node type, each chart primitive, each piece of chart/editor chrome and each heuristic-detector chip as its own first-class CMP-* entry (per `05-accessibility-standard.md` §11.3's requirement that trading-specific components get the same first-class a11y/test treatment as generic atoms — collapsing them would under-specify their individual contracts, e.g. CMP-147..151's distinct keyboard-connect and a11y-label behaviours per node type, or CMP-227 EstimatedBadge's catalogue-level enforcement test).

An alternative was considered and explicitly **rejected**: merging CMP-147..151 (node-graph node types) into a single parameterised `NodeGraphNode` component with a `type` discriminator, which would reduce the nominal count to ~180. This is rejected because (a) it would require the a11y and Storybook contracts for five materially different keyboard/interaction behaviours to live inside one entry's Variants table, degrading ticket-writer clarity rather than improving it, and (b) it does not change the actual implementation surface — five distinct React components would still exist either way. _*Ticket generation must produce exactly 238 tickets, one per CMP-* ID in this document._*

---

## 9. Cross-references

- `14-screens-catalogue.md` — every screen entry names the CMP-* components it composes.
- `16-design-system-brief.md` — token names referenced throughout (`color.*`, `font.*`, `space.*`, `radius.*`, `elevation.*`, `motion.*`), density modes, Figma library structure, handoff spec.
- `05-accessibility-standard.md` §6, §11 — binding a11y contracts for canvas/WebGL components and the design-system enforcement mechanism this catalogue implements.
- `26-chart-engine-design.md` — internal architecture (render loop, texture pipeline, DOM-mirror sync API) behind the CMP-180..199 public component surface.
- `research/digests/10-frontend-tech.digest.md`, `04-deepcharts-deepchart.digest.md`, `05-deepcharts-deepdom-gamma.digest.md`, `09-execution-risk-tools.digest.md`, `23-views-and-screens.digest.md` — source feature inventories this catalogue operationalises into components.
- `backlog/*.json` — one design-system ticket per component or tight family, referencing its CMP-* ID, Storybook story list, and test requirements as Definition-of-Done.
