# E05-D02 — Design-system atoms and molecules: slice 2 of 5 (data display and text atoms)

**Ticket:** E05-D02 (#161) · **Epic:** E05 Design system v0 · **Status:** In Review — awaiting owner approval (slice 2 of 5)
(design PR: the owner approves under C-10.1; the coordinator reviews); text-first: the boards are PENDING and the
boards PR completes slice 2 (§6)
**Penpot:** page `10 Components — Atoms` (page id `a4fbc4c3-2c4d-80f4-8008-b1248b9e760f`) of the CandleViewer DS file.
**Slices:** #161 ships as five design PRs. Slice 1 (#3914, `E05-D02.md`) covers actions and selection. This slice
covers the data display and text atoms: CMP-011 Tag, CMP-012 Badge, CMP-013 Avatar, CMP-018 Divider, CMP-020
Typography primitives, CMP-021 Link, CMP-024 Sparkline, CMP-025 Avatar Group, CMP-030 Divider-Label, CMP-032
Confidence Dots, CMP-033 CopyButton and CMP-037 SwatchLegendItem. Later slices cover the remaining atoms and the
molecules; only the last one completes the ticket.
**Companion:** `E05-D02-data-display-a11y-audit.md` (accessibility pre-review of this slice).
**Builds on slice 1:** its conventions (§3), token mirror (§4), recorded exceptions (§5), owner decisions A1–A12,
B1–B7, C1–C15 and D1–D17 (§6; D13 is superseded by E09-D09 §2.2 T2) and icon optical sizes (§7) apply here
unchanged, except the hover cells that §5 E18 puts to you. This document cites them as "slice 1 §n" or
"slice 1 A3" and adds only what is new.

## 1. What was built

- **12 components, 82 variants**, on the same page as slice 1. Each is one Penpot variant component per CMP id, named
  `CMP-0xx · Name` (brief §10), with the catalogue's variant properties and values, and every documented Variant ×
  State is drawn by slice 1's matrix rule (conventions §2). Nine of the twelve are static: they draw no focus or
  disabled state (§3 item 19).
- **One documentation section per component**, structured as in slice 1 §1.1: the title, the verbatim catalogue
  Props/A11y text, the variant set, a labelled matrix with one instance per drawn combination, the keyboard table
  (the WAI-ARIA APG pattern named, or "not focusable" with the reason) and the accessible-name/role table, the
  disabled-with-reason row where the build drew one (CMP-021 only, held for §5 E27), then notes and samples.
- **Composition by live instances:** CMP-011 and CMP-033 nest CMP-002 IconButton, CMP-025 nests CMP-013 Avatar, CMP-030
  nests CMP-018 Divider and CMP-020 Text, CMP-037 nests CMP-020 Text and NumericText, and CMP-021's reason row uses a
  CMP-016 Tooltip. Superseded by E09-D09 §2.2 T2 (#3953); the boards PR folds §1, §5 E10, the CMP-011 and CMP-021 sections of §6 (CMP-021's gated state as §5 E27 rules: a T2 link or none), §7, the audit's gated rows and the catalogue's gated clause into T2, and T2 governs until then. Overrides only; nothing is detached.
- **No token change.** This slice adds or edits no token, and the Penpot token mirror is slice 1 §4's.
  `packages/ui/tokens` changed once since `73441f53`, the state these sections were specified against: #3925
  (`a0132de01`, 2026-10-20) retuned `color.status.danger.default` in light and high contrast, made the
  high-contrast focus ring white, moved several hover and active fills and added the selected role (slice 1 §4,
  A1, A6, A7). Every figure in this document was re-measured at that state.
- **Catalogue alignment, in this PR.** The twelve entries' updates are applied to
  `docs/plan/15-component-catalogue.md` on top of slice 1's edits (#3914): Tokens lines with the shipped tokens, a
  Variants line (CMP-011), States lines (CMP-011, CMP-021, CMP-033), Props and A11y additions and the CMP-024 and
  CMP-037 Storybook lines; no other entry changes. CMP-011's gated clause carries the E09-D09 §2.2 T2 marker (and
  `14` §0.5 rule 5 for its omission) and its estimated clauses the CMP-227 marker (§5 E19); CMP-021's Tokens line
  keeps `radius.control` for the ring until §5 E8 is answered, and CMP-020's says its `colorBySign` tokens are below
  4.5:1 as text on some tiers until §5 E1. Seven updates are held: five wait for an owner answer (§5 E11, CMP-012's
  connection-dot A11y sentence; E15, CMP-020's Storybook rename to AbbreviatedWithExpandedReading; E19, CMP-011's
  `onOpenMethodology?` prop; E25, `noreferrer` on CMP-021's Props line; E27, CMP-021's gating: the
  `disabled?/disabledReason?` Props clause, the disabled-with-reason parts of its States and A11y lines and the
  `locked` icon on its Tokens line, so its Props line stays `main`'s and its States and A11y lines keep plain
  disabled only) and two are Penpot follow-ups, not catalogue lines (CMP-021 re-copies its Props and A11y lines and
  CMP-033 its A11y line into their Penpot descriptions, §4.3).

| Component                          | Penpot component                  | Variants | Live instances inside                            |
| ---------------------------------- | --------------------------------- | -------- | ------------------------------------------------ |
| CMP-011 Tag / Chip                 | `CMP-011 · Tag`                   | 11       | CMP-002 IconButton (remove), `icon/{name}`       |
| CMP-012 Badge (status dot/count)   | `CMP-012 · Badge`                 | 10       | `icon/{name}` in the usage samples               |
| CMP-013 Avatar / ProfileBadge base | `CMP-013 · Avatar`                | 2        | —                                                |
| CMP-018 Divider                    | `CMP-018 · Divider`               | 4        | —                                                |
| CMP-020 Typography primitives      | `CMP-020 · Typography primitives` | 29       | —                                                |
| CMP-021 Link                       | `CMP-021 · Link`                  | 7        | `icon/{name}`; CMP-016 Tooltip in the reason row |
| CMP-024 Sparkline                  | `CMP-024 · Sparkline`             | 6        | —                                                |
| CMP-025 Avatar Group / Stack       | `CMP-025 · Avatar Group`          | 2        | CMP-013 Avatar                                   |
| CMP-030 Divider-Label              | `CMP-030 · Divider-Label`         | 1        | CMP-018 Divider, CMP-020 Text                    |
| CMP-032 Rating/Confidence Dots     | `CMP-032 · Confidence Dots`       | 3        | —                                                |
| CMP-033 CopyButton                 | `CMP-033 · CopyButton`            | 4        | CMP-002 IconButton, `icon/{name}`                |
| CMP-037 SwatchLegendItem           | `CMP-037 · SwatchLegendItem`      | 3        | CMP-020 Text and NumericText                     |

Every fill, stroke, radius, padding, gap, height, typography and opacity is bound to a **semantic** token. The
recorded exceptions are the geometry constants in §4.1 and the items in §4.2: the named primitives of slice 1 §5.2,
the Penpot-only layout workarounds and Penpot's own variant-set chrome.

### 1.1 Penpot structure

- Each section is a board at the page root named `CMP-0xx · Name — doc`; the variant set `CMP-0xx · Name` sits inside
  it (its id is on the component's "Drawn" line in §6).
- Names drop a catalogue `/`, as in slice 1 §1.1: `CMP-011 · Tag`, `CMP-013 · Avatar`, `CMP-025 · Avatar Group`,
  `CMP-032 · Confidence Dots`. The plugin API cannot set a component description, so the full catalogue names are in
  the table above, and the CMP-011 and CMP-032 sections also spell them out in their notes.
- An axis with a single value is not a variant property: State=default is dropped in CMP-012, 013, 025 and 032.
  CMP-030, whose only axis has one value, is a one-variant set, because Penpot cannot hold a set without properties
  (§5 E5).
- Samples beyond the matrix: the dot and count pairings in CMP-012, the right-aligned numeric column in CMP-020, the
  reason row in CMP-021, the 256 × 64 size demo in CMP-024, the 120 and 400 px fill demo in CMP-030 and the keyed
  colour overrides in CMP-037.

## 2. How to review

1. Open page `10 Components — Atoms` (its page id is in the header) and switch the colour theme (`theme/dark` → `light` → `high-contrast`) and the density
   theme (`density/compact` → `comfortable`) in the token panel. Only colours change with the theme. Density re-points
   only `size.control.height` and `size.row.height` (slice 1 §4), so the chips, the md avatar, the avatar stack, the
   vertical divider, the CopyButton and the legend row grow from 24 to 32 px, and nothing else moves; the 8 px dots
   of CMP-012 and CMP-032 keep their size.
2. The boards are PENDING (text-first merge, 2026-10-23): this PR carries no exports. The boards PR, which completes
   slice 2, redraws the 12 sections on page `10 Components — Atoms` (the page id in the header), with CMP-021's gated
   state held until §5 E27 is answered and then drawn per that ruling, the E09-D09 §2.2 T2 form on CMP-011's remove
   button through CMP-002 if §5 E10 is approved, CMP-011's estimated chip restated as CMP-227 (§5 E19) and the hover
   cells of §5 E18, and exports each at dark/compact (§6).
3. The owner decisions this slice needs are collected in §5; each component's own questions are listed with it in §6.
   What the boards show that is clipped, overlapping or off is in §4.3.
4. The catalogue text quoted in §6 is each entry as it stands on `main`, before this PR's alignment edits (§1).

## 3. Conventions

The component sections in §6 cite slice 1's conventions as "conventions §n" (slice 1 §3, items 1–14); they apply
unchanged, except the hover cells of items 2 and 3, which §5 E18 puts to you. This slice needed six more, numbered
on from them:

15. **Data ink** (CMP-024, CMP-032, CMP-037): a mark that carries data binds the semantic token of what it stands for
    (`color.buy.default`, `color.sell.default`, `color.neutral.default`, `color.heatmap.*`, and
    `color.status.info.default` for estimated confidence); uncoloured data ink binds `color.text.tertiary` (E06-D02
    §2.3). Data marks reach 3:1 on app and canvas; where another tier falls short (the audit's §4 lists each one), a
    shape, slope, count, sign, glyph or label already carries the meaning (brief §6 rule 1). Data-sized marks have no
    size token: their sample sizes are data (§4.1).
16. **Typography roles** (CMP-020, used by CMP-030 and CMP-037; extends conventions §6): Text binds
    `type.ui.caption|body|body-strong|label`, Heading `type.ui.heading-sm|heading-md|heading-lg|display` with a
    semantic `level` independent of its style, and NumericText and MonoText `type.num.*` (JetBrains Mono, fixed-width
    digits). Numbers right-align in columns; ids left-align. A colour-by-sign value always carries its + or − sign,
    and zero is unsigned and neutral. An abbreviated value carries its expanded reading as visually hidden text, never
    as `aria-label` on a span (§5 E15).
17. **Avatars** (CMP-013, CMP-025; extends conventions §8): a circle is `radius.badge` on a square box; md is
    `size.control.height`, sm is `size.icon`. The fill is the interim `color.neutral.subtle` with `color.text.primary`
    initials until an avatar palette exists (§5 E2). An avatar beside its visible name is decorative; alone, it is
    `role="img"` named by the full label, never the initials. Stacks overlap through fixed `size.icon` slots, never a
    negative gap.
18. **Padding-sized marks** (CMP-012, CMP-032): an 8 px dot is an empty board padded by `space.inset.xs` on every
    side, so no size token is invented. Penpot needs a 0.01 px spacer inside it (§4.1, §5 E5). Density never changes
    these marks, because `space.inset.*` has a single value (slice 1 §4).
19. **Static atoms** (CMP-012, 013, 018, 020, 024, 025, 030, 032, 037): conventions §2 makes focus-visible and
    disabled universal only for interactive components, so these draw neither. Their keyboard table says why they are
    not focusable, and their role/name table says how the host names them. Conventions §11 and §12 hold for them
    as for the three interactive ones, and each §6 section states its "Resize & overflow" and "Forced colors" rule:
    text takes CanvasText, strokes and glyphs currentColor, and a mark that forced colours would repaint as Canvas
    keeps its shape (a border or a CanvasText fill; the legend swatch, whose colour is its value, keeps its colour).
20. **Nested controls own their states** (CMP-011, CMP-033): a component that nests CMP-002 takes its focus ring and
    its disabled dimming from the nested IconButton and never adds a second ring or a second `opacity.disabled`. The
    chip's own ring appears only on the estimated chip, which is itself the focus target.

## 4. Recorded exceptions (new in this slice)

### 4.1 Geometry constants without a token

Each value below is drawn raw and logged for ticket AC2 ("zero hardcoded hex or px values"). Rows that recur from
slice 1 keep its resolution; the "CMP-018 group question" the specs cite is this table together with slice 1 §5.1
and slice 1 B1. Zero values (padding or gap 0, CMP-037's square swatch corner) need no token and are not listed.

| Constant             | Value                                                                                                                                                                                                                                                                                                                                                                              | Components                                                                                                                                  | Proposed resolution                                                                                                         |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Hairline stroke      | 1 px, aligned inside (the value of the primitive `border.hairline`), unbound                                                                                                                                                                                                                                                                                                       | CMP-011 neutral and estimated outlines, CMP-012 count outline, CMP-018 rule (CMP-030 through it), CMP-032 empty dot, CMP-037 swatch outline | As slice 1 §5.1 "Control outline": name `border.hairline` a primitive exception (slice 1 B1)                                |
| Dash pattern         | Penpot's default dash on the 1 px estimated outline, unbound                                                                                                                                                                                                                                                                                                                       | CMP-011 estimated chip                                                                                                                      | A CMP-011 constant: code draws `border-style: dashed` with the browser's own dash; no token (§5 E9)                         |
| Cut-out ring         | 2 px outside stroke in `color.surface.canvas` (the value of the primitive `border.thick`), width unbound                                                                                                                                                                                                                                                                           | CMP-025 avatars and +N chip                                                                                                                 | Name `border.thick` a primitive exception, like `border.focus` (§5 E4)                                                      |
| Data-ink stroke      | 1.5 px, centred, round caps (the icon-grid weight)                                                                                                                                                                                                                                                                                                                                 | CMP-024 line; the nested glyphs of CMP-011, CMP-012, CMP-021 and CMP-033                                                                    | As slice 1 §5.1 "Glyph stroke": a glyph-grid constant, no token (slice 1 B1); the sparkline uses the same weight            |
| Focus-ring geometry  | 2 px offset: the ring rect is the target + 4 px at −2,−2; radius + 2 on rounded targets                                                                                                                                                                                                                                                                                            | CMP-011 estimated chip, CMP-021; CMP-011's remove button and CMP-033 through CMP-002                                                        | As slice 1 §5.1 "Focus-ring offset" and "radius" (slice 1 B2); CMP-021's ring radius is §5 E8                               |
| Dot spacer           | A paint-less 0.01 × 0.01 px rectangle in each 8 px dot, which then renders 8.01 px                                                                                                                                                                                                                                                                                                 | CMP-012 dots, CMP-032 dots                                                                                                                  | Penpot-only: code sizes the empty dot by its padding (§5 E5)                                                                |
| Live-region stand-in | A hidden single-space text at (0, 28)                                                                                                                                                                                                                                                                                                                                              | CMP-033                                                                                                                                     | Penpot-only: code renders an empty `role="status"` element (§5 E5)                                                          |
| Sample dimensions    | CMP-018's 240 px horizontal sample; CMP-024's 64 × 16 px master, 256 × 64 px size demo, 20 normalised points and two bounds anchors (M0 0, M64 16); CMP-030's 240 px root and 120 / 400 px demos; CMP-037's 200 px rows; CMP-020's 160 px numeric column; CMP-021's 640 px variant set; 234 and 314 px matrix cells; 288, 480 and 620 px captions; the 960 px documentation column | every section                                                                                                                               | As slice 1 §5.1 "Sample dimensions": data and documentation layout, not style values; instances fill their parent; no token |

### 4.2 Other recorded exceptions

- **Named primitives** (as slice 1 §5.2): `border.focus` for the ring width (CMP-011, CMP-021; CMP-033 through
  CMP-002) and `opacity.disabled` for the disabled states (CMP-011, CMP-021; CMP-033 through its nested CMP-002). No
  other primitive is bound.
- **Penpot layout workarounds** (§5 E5): the dot spacer (CMP-012, CMP-032); `min-width`, which Penpot ignores on hug
  children, so a single-digit count draws 14 × 16 px and the +N chip 22 × 24 px (code's `min-width` gives 16 and
  24); CMP-037's row, fixed at `size.row.height` with `layoutItemMinH` also bound (code uses `min-height`, so a
  two-line label grows the row); the single-space live region (CMP-033); and CMP-030's one-variant set.
- **Nested dimming** (§3 item 20, §5 E21): CMP-033's own root binds no opacity; the dimming comes from the nested
  CMP-002 at State=disabled, so the button is not dimmed twice (conventions §3 puts `opacity.disabled` on the root).
- **Penpot variant-set chrome:** all twelve sets keep Penpot's 2 px `#BB97D8` inner stroke and 20 px radius (slice 1
  §5.2 and B7).
- **Icon instance boards:** the nested `icon/{name}` instances are boards without flex (slice 1 §5.2 and B6).

### 4.3 Known gaps in the Penpot build (no owner decision needed)

Every drawn combination of the twelve draw lists is present, in the variant set and in the matrix. The boards as drawn
on 2026-10-20 show:

- **CMP-011:** in the removable focus-visible variant, the nested CMP-002 ring touches the last glyph of the label and
  covers the chip's 1 px outline on the right (0 px clearance; §5 E7). The estimated chip's dashed outline breaks up
  at the pill's ends, so the end arcs read as a second pair of brackets around "(estimated)" (§5 E9).
- **CMP-012:** single-digit counts draw as 14 × 16 px ovals, not 16 px circles (§4.2). The danger count outline and
  the "Blocked" glyph in the usage row are amber, because `color.status.danger.strong` is amber in dark (slice 1 A6).
- **CMP-018 and CMP-030:** the 1 px `color.border.subtle` rules are barely visible at 1x (1.24:1 on canvas, 1.31:1 on
  app, dark), and CMP-030's rule sits on a half pixel, so Penpot's export anti-aliases it across two rows (browsers snap
  it). Judge the rules in the matrix cells.
- **CMP-024:** the matrix wraps 5 + 1 (cosmetic).
- **CMP-025:** the 8 px overlap hides most of each covered avatar's second initial ("AD" and "BS" read as "A" and "B"
  plus a sliver), and with Overflow=true the +N chip covers most of "CF" (§5 E6). On the `color.surface.app` matrix
  cells the canvas-coloured cut-out ring shows as an outline (§5 E23). The +N chip is 22 × 24 px (§4.2).
- **Description markers:** CMP-020 strips the catalogue text's Markdown markers; the other eleven sections quote them
  literally, the same inconsistency slice 1 §5.3 records.
- **Penpot descriptions:** after the catalogue edits are approved, CMP-021 re-copies its Props and A11y lines and
  CMP-033 its A11y line into their sections (the last catalogue item of each spec).

## 5. Decisions for the owner (collected)

Deduplicated across the 12 components and against slice 1 §6; each component's own wording stays in its section
(§6). The new decisions are E1–E27; where an answer changes a drawing, the change lands in one Penpot pass over this
slice's sections with new exports ("the follow-up" below). These slice 1 decisions also cover this slice, and
are not asked again:

- **A1** (the label-on-fill retune, resolved by #3925): no label in this slice sits on a status `.default` fill; the
  solid count badge stays rejected because labels on those fills still fail in some themes (E3).
- **A3** (control-outline token): CMP-032's empty dot binds `color.text.tertiary` for a non-text outline, as the
  slice 1 controls do.
- **A4** (light `color.border.subtle` on overlays): CMP-018 and CMP-030 bind it. In dark it also equals
  `color.surface.hover` (1.00:1), so a divider on a hovered surface disappears in both themes.
- **A6** (status glyph colours): CMP-011's warning and danger chips and CMP-012's outlines and glyphs (the `.strong`
  outlines and glyphs are identical in light and near-identical amber in dark, dE76 14.7); since #3925 the light
  `.default` dots differ (dE76 56.6).
- **A10** (icon optical sizes): CMP-021's 16 px external-link glyph beside 13 px text, and CMP-037's swatch (12 px in
  the shipped code, 16 px drawn; under A10 the 12 px primitive goes away).
- **A11** (size model): CMP-013 has no lg, because no semantic size exists above 32 px.
- **B1** (geometry constants): every 1 px and 1.5 px row of §4.1.
- **B2** (ring radius + 2): CMP-011's estimated chip (a pill, so `radius.badge` either way) and CMP-033 through
  CMP-002. CMP-021 is E8.
- **B6** and **B7** (icon masters, variant-set chrome): the nested icons of CMP-011, 012, 021 and 033, and all twelve
  sets.
- **C13** (strict matrix reading): combinations the rules make derivable are not drawn (CMP-011 draws Icon=true only
  at State=default; CMP-020 draws text, heading and mono-text once per style). CMP-012 draws the full Variant × Tone
  cross rather than each tone once, because both shapes are used in every tone.
- **Slice 1 §1.1** (names without `/`): CMP-011, 013, 025 and 032.

Slice 1's **C2** (gating props) is not one of them: it adds `disabled?/disabledReason?` to CMP-003, 005, 006, 010 and
031 only (`E05-D02.md` §6) and never names CMP-021, so a gated link is put to you as E27.

### (a) Token gaps (E05-D01's token files, outside this PR's write set)

- **E1 — Text-grade buy, sell and neutral tokens for signed numbers?** `colorBySign` text binds
  `color.buy|sell|neutral.default`, which fail 4.5:1 in 14 tier pairs: dark sell from 4.42 (raised) to 3.13
  (selected), dark and high-contrast zero 3.98 on selected, light buy 4.30 to 3.84 and light sell 4.15 to 3.70 on
  overlay, hover, selected and sunken. Hovered and selected table rows are the common context. **Recommended:** add the
  catalogue's `color.text.buy|sell|neutral`, tuned to at least 4.5:1 on all seven tiers in all three themes and checked
  by `verify_tokens.py`, in the next E05 token pass (the E05-D01 follow-up of slice 1 A4 and A6; #3925 added none);
  `colorBySign` then binds them, and CMP-024's strokes keep the `.default` tokens, which pass 3:1 everywhere.
  **Affects:** CMP-020 (CMP-116 PnLBadge, every signed-number cell).
- **E2 — An avatar palette?** No token can express the catalogue's `color.avatar.palette[]` or the per-account `color`
  hash, so avatars draw the interim `color.neutral.subtle` with `color.text.primary` initials (at least 12.22:1) and
  the ColorPalette story waits. **Recommended:** define it in slice 1 A5's palette token PR: a short named set, each
  colour with a paired initials token at 4.5:1 or more, clear of the env colours and the buy/sell hues, CVD-reviewed by
  E05-D04; the hash picks an index, never a raw colour. **Affects:** CMP-013, CMP-025 (CMP-106 AccountBadge).
- **E3 — Component-tier chip and badge tokens?** No `color.chip.*` group is shipped, so chips map to
  `color.neutral.*`, `color.status.{tone}.*` and `color.text.*`. A solid status count would need a label token at
  4.5:1 on every `.default` fill, and the existing pairs fail (`color.text.inverse` is 3.83:1 on dark
  `color.status.danger.default` and 3.45:1 on light `color.status.warning.default`; #3925 lifted light danger to
  10.31:1 and left these). **Recommended:** keep the mappings and the tinted
  status look (subtle fill, `color.text.primary` label or numeral at 9.86:1 or more, `.strong` glyph or outline) for
  v0; no `color.chip.*` and no `color.text.on-status.*`. **Affects:** CMP-011, CMP-012.

### (b) Geometry constants and layout exceptions

- **E4 — Name `border.thick` for the 2 px cut-out ring?** **Recommended:** yes, a named primitive exception like
  `border.focus` and slice 1 B1's `border.hairline`, so the ring width binds. **Affects:** CMP-025.
- **E5 — Accept the Penpot layout workarounds?** (1) A 0.01 px spacer inside each 8 px dot, because Penpot does not
  size an empty hug board from its padding; (2) Penpot ignores `min-width` on hug children (14 × 16 px count, 22 × 24
  px +N chip); (3) CMP-037's row is fixed at `size.row.height` instead of hug plus a minimum height; (4) a hidden
  single-space text stands for CMP-033's empty live region; (5) a component with a single draw is a one-variant set.
  **Recommended:** accept all five as Penpot-only. Code renders what the specs describe (an empty element sized by its
  padding, `min-width`, `min-height`, an empty `role="status"` element, one component); no strut layers, no new
  tokens. **Affects:** CMP-012, 025, 030, 032, 033, 037 (CMP-036 and CMP-038 in a later slice).
- **E6 — An avatar overlap without a token?** `space.avatar.overlap` does not exist; the overlap comes from
  `size.icon` slots holding `size.control.height` avatars: 8 px compact, 16 px (half an avatar) comfortable.
  **Recommended:** accept for v0 (token-bound, no negative gap), and add a semantic overlap token only if the
  comfortable stack reviews as too dense. **Affects:** CMP-025.
- **E7 — Removable chip geometry?** The nested CMP-002 ring (2 px offset + 2 px) exactly fills the 4 px
  `space.inset.xs` gap, so on focus it touches the label; and the chip binds `size.control.height` so its 24 px remove
  target fits, which fills a 24 px table row edge to edge. **Recommended:** widen the label-to-remove gap to
  `space.inset.sm` (8 px) on removable chips, as slice 1 B5 does for the swatch picker, so the ring sits on clear
  fill; keep the height, since a shorter chip would need a new size token. **Affects:** CMP-011 (CMP-055, CMP-169).
- **E8 — Link focus ring: square or rounded?** The spec binds `radius.control` (4 px) to the ring of an unrounded
  link; slice 1 B2's rule (the ring follows the element's radius) gives a square ring. **Recommended:** square, per B2
  and the CMP-039 contract, so code adds no radius to links; the follow-up redraws the ring at radius 0 and drops
  `radius.control` from the CMP-021 Tokens line. **Affects:** CMP-021.
- **E9 — The estimated chip's dashed outline?** Penpot's default dash leaves the pill's end arcs as separate short
  dashes that read as a second pair of brackets. **Recommended:** accept: code draws `border-style: dashed` with the
  browser's own dash, so the Penpot dash is illustrative; keep the literal parentheses for parity with CMP-227.
  **Affects:** CMP-011 (CMP-227).

### (c) Catalogue ambiguities (props, defaults, sizes)

- **E10 — Chip variant rules?** Only neutral chips are removable; info, warning and danger always show their registry
  glyph (`icon?` applies to neutral only); estimated shows the literal "(estimated)" with a dashed outline; gated
  removal belongs to the consumer (CMP-079 on the nested IconButton, or no remove control); after a removal the owning
  group moves focus (CMP-169, CMP-055). **Recommended:** approve; this PR's catalogue edits carry these as the
  Variants, States and A11y lines. **Affects:** CMP-011. Its gated-removal clause is superseded by E09-D09 §2.2 T2 (#3953); the boards PR folds §1, §5 E10, the CMP-011 and CMP-021 sections of §6 (CMP-021's gated state as §5 E27 rules: a T2 link or none), §7, the audit's gated rows and the catalogue's gated clause into T2, and T2 governs until then. Its "or no remove control" option is ruled by `14` §0.5 rule 5 / E09-D09 §2.1: never hidden for RBAC or environment gating (read-only tags, a data property, may still omit it).
- **E11 — Badge details?** Cap the displayed count at "99+" (the name keeps the full number); keep dot + glyph + word,
  per conventions §4, while light warning and danger glyphs are identical (`.strong`, A6); connection state belongs
  to CMP-239 and E08-D04 §3, not to CMP-012. **Recommended:** approve all three; the held connection-dot A11y edit is
  then dropped. **Affects:** CMP-012.
- **E12 — Avatar sizes?** CMP-013 sm (16 px) shows one initial and md (24 px compact, 32 px comfortable) two; CMP-025
  draws md only, which fills a 24 px compact row. **Recommended:** approve the CMP-013 sizes (in the catalogue Props
  edit); keep CMP-025 at md for v0 and add `size` when a screen needs sm, since a 16 px stack first needs its own
  token-bound overlap. **Affects:** CMP-013, CMP-025.
- **E13 — Divider props?** `inset?` has no type: read as a boolean that insets both ends (`space.inset.md` horizontal,
  `space.inset.xs` vertical). Meaningful versus decorative has no prop: adopt Radix Separator's `decorative?: boolean`
  (default false, which gives `role="separator"`; layout dividers pass true). **Recommended:** approve both (in the
  catalogue Props edit). **Affects:** CMP-018 (CMP-030).
- **E14 — Typography props and number formatting?** Heading takes `level` 1–6, independent of its style; a Text tone is
  an instance colour override; zero is never signed; `format="pnl"` and `colorBySign` need `signDisplay="always"`;
  the decimal is '.' and grouping ',' in every locale; the n/a axes of text, heading and mono-text are stated once in
  the section notes. **Recommended:** approve (in the catalogue Props edit), and set the K/M/B abbreviation threshold
  in the NumericText stories, since it changes no drawn variant. **Affects:** CMP-020.
- **E15 — The abbreviated value's reading?** The catalogue puts "1,200,000" in `aria-label` on a span, which ARIA 1.2
  prohibits (axe `aria-prohibited-attr`); the design renders the visible "1.2M" `aria-hidden` plus a visually hidden
  "1,200,000". **Recommended:** approve (the catalogue A11y edit); the Storybook rename to
  AbbreviatedWithExpandedReading waits for this answer. **Affects:** CMP-020, CMP-037's values.
- **E16 — Legend item props and draws?** The shipped `SwatchLegendItem` has a `glyph?` prop the catalogue lacks; its
  swatch is a raw 12 px square where the design binds `size.icon` (16 px); the shipped ColorConventionLegend uses a
  glyph without a value, which is not drawn; and the 1 px `color.border.strong` outline is 1.57–1.91:1 on canvas.
  **Recommended:** add `glyph?` (required when the swatch encodes direction), keep the 16 px swatch, draw HasValue=false
  with HasGlyph=true and its story in the follow-up, and accept the outline, which only keeps the zero stop (1.00:1)
  visible while the label carries the meaning. **Affects:** CMP-037 (CMP-113 HeatmapLegend, ColorConventionLegend).
- **E17 — Confidence dots: one tone and a named level?** **Recommended:** keep the single `color.status.info.default`
  tone (colour carries no meaning, and a warning-to-success ramp would read as an alarm), and require a `label`
  override to name the level (lint or test). **Affects:** CMP-032 (CMP-227).
- **E18 — Hover and link states?** No hover, active or visited state is drawn. Conventions §2 and §3 (slice 1's
  revision 2, which postdates these sections) give every pointer control a hover cell and a link
  `color.text.primary` on hover, and slice 1 D17 draws them for the selection controls; here CMP-033 and CMP-011's
  remove button hover as their nested CMP-002 does, and the estimated chip as CMP-227 does (§5 E19).
  **Recommended:** the boards PR draws the CMP-002 hover cells of CMP-011 and CMP-033, as conventions §2 asks; for
  links, none for v0, an exception to those two conventions: a link keeps the underline and the pointer, which
  carry the affordance, and visited means nothing for in-app routes. A "no" on links adds CMP-021's hover cells
  (`color.text.primary`). **Affects:** CMP-021, CMP-011, CMP-033.

### (d) Behaviour proposals

- **E19 — Who makes the estimated chip interactive?** Brief §12 wants every estimated value to link to its methodology,
  but CMP-011 has no handler. **Recommended:** CMP-227 EstimatedBadge, a native `<button>` bound to the drawer by its
  `EstimatedMethodologyProvider` (name PROPOSED; `15` CMP-227: no `onOpenMethodology` prop). CMP-011's estimated
  variant is a deprecated alias that renders CMP-227 (the E25-D05 line of `15` CMP-011), so CMP-011 gains no prop
  (that catalogue edit stays held); an honesty marker is never dimmed, and CMP-227 has no disabled state by
  construction (E25-D05 §4.2), so the drawn disabled variant becomes a note. Superseded by CMP-227 (E25-D05
  §3–§4): the estimated look and states this slice drew and specifies (§4.1's dash pattern, §4.3's estimated gap,
  §5 E9, E10's estimated clause, the CMP-011 section's estimated rows, the audit's estimated rows and the
  catalogue's estimated clauses) give way to CMP-227's; the boards PR restates them, and CMP-227 governs until then.
  **Affects:** CMP-011, CMP-227.
- **E20 — CopyButton feedback?** The copied state reverts silently after 2 s; the check glyph is the only visible
  feedback; the announcement reads "Copied" in the catalogue and "Copied to clipboard" in E09-D04; a failed copy has
  no state. **Recommended:** 2 s and silent; the glyph swap is enough (a shape change, and a visible word would reflow
  dense rows); one wording, the catalogue's "Copied", with E09-D04 aligned to it; and a failed state (the `error`
  glyph and a "Copy failed" announcement) in the follow-up, since the browser dev target can deny clipboard access.
  **Affects:** CMP-033 (E09-D04).
- **E21 — CopyButton gating and dimming?** No disabled-with-reason state is drawn, because copying a value the user
  can already see is never RBAC- or env-gated; the disabled state dims through the nested IconButton only; the live
  region never contains the copied value (flagged for E05-X02). **Recommended:** approve all three; a gated use would
  add one draw. **Affects:** CMP-033.
- **E22 — A floor on the sparkline's y-range?** Auto-ranging makes a flat series look as volatile as a trend.
  **Recommended:** approve a minimum span (±0.5 % of the first value for price series, set per data kind for Deep
  Stats), recorded in the engineering story. **Affects:** CMP-024 (CMP-161 WatchlistRow, Deep Stats).
- **E23 — The avatar group on other surfaces, and its hidden names?** The cut-out ring is `color.surface.canvas`, so on
  raised, hovered or selected rows it shows as an outline; the names folded into +N reach assistive technology only.
  **Recommended:** the ring takes the host's surface token (an instance override, a CSS custom property in code,
  canvas by default); CMP-025 stays a static image, and a host that needs every name shows it (the trade-group detail,
  for example) rather than adding a focus stop to every row. **Affects:** CMP-025.
- **E24 — Section semantics for labelled dividers?** A separator named by its label is not a heading, so screen-reader
  users cannot jump between form sections. **Recommended:** keep CMP-030 as specified (a labelled separator, leading
  caption and trailing rule); a form that needs section navigation (CMP-107's order ticket, the rule groups) carries a
  heading or a fieldset and legend itself and passes the rule as decorative. **Affects:** CMP-030 (CMP-107, the rule
  editor).
- **E25 — `rel="noopener noreferrer"` on external links?** **Recommended:** yes, so the private host never leaks in a
  Referer header on the browser dev target. It changes the catalogue's `rel="noopener"`, so that edit waits for your
  answer. **Affects:** CMP-021.
- **E26 — Heatmap swatches under colour-vision deficiency?** `color.heatmap.bid.3` and `.ask.3` are only 4.8–5.0 apart
  (dE76) under deuteranopia, so a deuteranope reads the side from the label alone; the spec keeps the ▲/▼ glyph
  optional for heatmap stops (05 §4.1's heatmap rule). **Recommended:** keep it optional for v0, and let E05-D04's CVD
  review decide whether heatmap legends also carry the glyph. **Affects:** CMP-037 (CMP-113).
- **E27 — Can a link be gated?** The 2026-10-20 build gives CMP-021 a gated state (State=disabled-with-reason: the
  dimmed link, a `locked` glyph and a reason tooltip) that no decision covers, since slice 1's C2 stops at CMP-003,
  005, 006, 010 and 031 (`E05-D02.md:384`–`:387`; lines on `main`). `14` §0.5 rule 5 (`14-screens-catalogue.md:85`)
  and its anatomy, E09-D09 §2.1, already settle two cases, which are not asked: a bare link whose only job is to reach
  an `/admin/*` destination is hidden for a session without `admin:read` (T3, step 1, `E09-D09.md:38` and `:44`;
  E08-D06's owner-only "Recorder settings" link is absent for others, `E08-D06-handoff.md:203`), and a control that
  stands for a capability inside a visible surface drops its admin link and is decided by steps 2–5 with no link (the
  host's sentence form or a T2 control, E09-D09 §2.2). Asked: does a link to a non-admin destination that fails a
  step 3 or 4 leg (a permission, grant or environment, or a blocking state, `E09-D09.md:40`–`:41`) need a T2 link at
  all, and if so, does CMP-021 join E09-D09 §8's T2 atoms "as CMP-001" (`E09-D09.md:205` lists CMP-001, 002, 004 and
  005)? One merged spec already has one: E40-D02's "create a rule" link to `/rules/new`, disabled for a session
  without `rules:write` (`E40-D02.md:83`–`:87`). **Recommended:** the host owns the gating, never the atom: CMP-021
  states no gating policy of its own, and a link to an admin destination is hidden, not locked. For the asked case,
  yes, as CMP-001: the host decides through CMP-079 RbacGate, the link takes E09-D09 §2.2's T2 form (a CMP-019 `lock`
  glyph leading the full label, the reason inline), and CMP-021 joins E09-D09 §8's T2 atoms (an E09-D09 edit, outside
  this PR). A "no" keeps links out of T2, and E40-D02's "create a rule" then needs another T2 control. Until you
  answer, CMP-021's gating clauses in `15` stay at `main`'s text (§1), and the boards PR draws CMP-021 per your
  ruling. **Affects:** CMP-021 (E09-D09 §8, E40-D02).

## 6. Components

### CMP-011 · Tag

**Catalogue (verbatim):**

- **Props**: `label` · `variant: "neutral"|"info"|"warning"|"danger"|"estimated"` · `icon?` · `removable?` · `onRemove?`.
- **A11y**: if removable, remove control is a labelled `IconButton` (CMP-002) child, not a bare `×`.

| Axis      | Values                                    | Default |
| --------- | ----------------------------------------- | ------- |
| Variant   | neutral, info, warning, danger, estimated | neutral |
| State     | default, focus-visible, disabled          | default |
| Removable | false, true                               | false   |
| Icon      | false, true                               | false   |

**Drawn:** 11 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d189d102ec48`.

_Board `CMP-011 · Tag — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it (the estimated chip restated as CMP-227, §5 E19; the remove button takes the T2 form through CMP-002 if §5 E10 is approved) and exports `img/CMP-011-tag-chip.png` here._

**Keyboard** (Button (the remove IconButton and the estimated chip) plus Tooltip (the estimated chip's methodology summary through CMP-016). Static chips follow no pattern: they are non-interactive text.):

| Keys                           | Action                                                                                                                                                                                                                                                                                       |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab                | Moves focus to the remove button (Removable=true) or to the estimated chip. Static neutral/info/warning/danger chips are not in the tab order.                                                                                                                                               |
| Enter / Space (remove button)  | Fires onRemove. The chip does not move focus itself. The owning group (CMP-169 TagEditor, CMP-055 FilterBar) must move focus to the next chip's remove button, otherwise the previous one, otherwise its own input or container. Focus never falls to `<body>`. This is a consumer contract. |
| Tab onto the estimated chip    | Shows the CMP-016 tooltip with the methodology summary (triggerOnFocus).                                                                                                                                                                                                                     |
| Esc (estimated chip)           | Hides the tooltip; focus stays on the chip.                                                                                                                                                                                                                                                  |
| Enter / Space (estimated chip) | Opens the CMP-069 InfoPanel methodology drawer through the handler that CMP-227 (or the consumer) wires; see open question.                                                                                                                                                                  |

**Accessible name and role:**

| Element                                        | Role                | Name                                                                            | ARIA                                                                                                                                        |
| ---------------------------------------------- | ------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| container (static neutral/info/warning/danger) | none (generic span) | the visible label text                                                          | none                                                                                                                                        |
| icon-left                                      | none                | none                                                                            | aria-hidden="true" (the status word is in the label)                                                                                        |
| remove (CMP-002 IconButton)                    | button              | "Remove {label}", e.g. "Remove Breakout" (aria-label, lint-enforced by CMP-002) | disabled when State=disabled; for gated removal, disabledReason through CMP-079 (the reason is the accessible description); no aria-pressed |
| container (Variant=estimated)                  | button              | the visible text "(estimated)"; the literal word estimated is in the name       | aria-describedby points at the CMP-016 tooltip; aria-haspopup="dialog", no aria-expanded (CMP-227, §5 E19)                                  |
| focus-ring                                     | none                | none                                                                            | visual only (:focus-visible)                                                                                                                |

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue                                    | Shipped                                                                                                                                                   | Note                                                                                                                                                                                                                                |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `color.chip.*` (neutral)                     | color.neutral.subtle (fill), color.border.default (1 px stroke), color.text.secondary (label, icon)                                                       | no `color.chip.*` group is shipped                                                                                                                                                                                                  |
| `color.chip.*` (info / warning / danger)     | color.status.{info\|warning\|danger}.subtle (fill), color.text.primary (label), color.status.{info\|warning\|danger}.strong (glyph)                       | Labels use text.primary because .strong on .subtle is 4.34 / 4.11 / 3.85:1 in light (below 4.5:1). text.primary on .subtle is ≥9.86:1 in every theme. Glyphs (.strong on .subtle) are ≥3.85:1 in every theme (lowest: light danger) |
| `color.chip.*` (estimated)                   | color.status.info.strong (dashed 1 px stroke), color.text.secondary (label), no fill                                                                      | keeps CMP-227's color.status.info family                                                                                                                                                                                            |
| radius.pill                                  | radius.badge                                                                                                                                              | radius.pill is a primitive; radius.badge resolves to {radius.pill} = 9999                                                                                                                                                           |
| focus-ring (§0.3 rule 4)                     | color.focus.ring + border.focus                                                                                                                           | border.focus is the primitive conventions.md allows for the ring width                                                                                                                                                              |
| (sizing, spacing and type: not in the entry) | size.control.height, space.inset.sm (paddingX; paddingLeft when removable), space.inset.xs (gap; paddingRight when removable), size.icon, type.ui.caption | conventions §5 to §7                                                                                                                                                                                                                |

**Hit target:** Removable=true (neutral only): the remove control is a CMP-002 IconButton whose box is size.control.height square (24×24 compact, 32×32 comfortable). It meets WCAG 2.5.8 with no essential exception and fills the chip's full height. Variant=estimated: the whole chip is the target (size.control.height tall, wider than 24 px). Static neutral/info/warning/danger chips are not targets.  
**Motion:** None. Chips render, change and are removed instantly, and the focus ring appears instantly. The estimated chip's tooltip delay and fade belong to CMP-016.

**Resize & overflow:** The chip height is a minimum and grows with 112–150 % text. Labels never wrap; a chip list wraps whole chips onto the next line. Only a user-authored neutral tag may truncate, at the consumer's maximum width, keeping its full text in the DOM and in the remove button's name; status and estimated chips never truncate. The remove IconButton never grows (CMP-002).

**Forced colors:** Fills are repainted as Canvas, so every chip keeps its shape with a 1 px border that forced colours paint CanvasText (neutral already has one; a status chip carries a transparent one at rest); label CanvasText; status glyphs currentColor, so the glyph shape and the word carry the tone (conventions §4); the remove button follows CMP-002; the estimated chip follows CMP-227 (§5 E19).

**Deviations recorded by the build:**

- Geometry constants with no token (allowed, listed here): the 1 px outlines, inner alignment (neutral solid color.border.default; estimated dashed color.status.info.strong with Penpot's default dash pattern); the focus-ring rect sized chip+4 at (-2,-2) with a 2 px OUTER stroke per the state rules of conventions §3, which renders the same as the spec anatomy's chip+8 with an inner stroke. The ring's radius is bound to radius.badge; the chip is a pill, so the +2 radius rule makes no difference.
- Icon size: binding size.icon on the icon/{name} instances left them at the 24 px main size, so they were resized to 16x16 and size.icon was re-bound (same fix as CMP-003); the tokens and the 16 px size were verified on all 11 variants and on the close glyphs.
- Removable chips (paddingLeft space.inset.sm, paddingRight space.inset.xs): Penpot laid them out with the two values swapped (4 left, 8 right) while the layout was in its default 'simple' padding mode. Fixed by setting flex.leftPadding/rightPadding directly, which switches to per-side padding. That dropped the token bindings, so both tokens were re-bound in a later call. Bindings and geometry verified on the variants and on the matrix copies: label at x=8, close box 4 px from the right edge.
- remove = a CMP-002 · IconButton instance (Variant=ghost, Size=md, State=default; State=focus-visible on the focus-visible chip, default on the disabled chip). Its nested icon/more-horizontal was swapped to icon/close with swapComponent (an override on the instance), with the stroke re-bound to color.text.secondary and the size to size.icon. The remove layer exists only in the Removable=true variants, not as a hidden layer in the others.
- icon-left is present in all 11 variants. It is hidden when Icon=false, uses icon/pin as the hidden placeholder in the neutral and estimated variants, and is parked at its layout slot (8,4).
- No reason row: CMP-011 has no disabled-with-reason state. Gated removal is a consumer composition (CMP-079 on the nested CMP-002, or omitting the control; see §5 E10: superseded by E09-D09 §2.2 T2, and the omission by `14` §0.5 rule 5 / E09-D09 §2.1 except for read-only tags), and the notes text says so. CMP-016 Tooltip exists in the library but was not needed.
- The full catalogue name 'Tag / Chip' is in the doc notes text, not in a component description: the plugin API has no component description field (see spec open question 7).
- Extra doc texts after keyboard and a11y, following the CMP-003 and CMP-018 sections: notes (hit target, motion, anatomy, variant and state rules, contrast, colour-blindness review, focus-after-removal contract), tokens (the spec tokenMap plus the geometry constants) and open-questions (the spec list). Backticks are stripped in the rendered tables; the description is verbatim, markdown markers included.
- The variant container's children were re-ordered to the spec draw order, because createVariantContainer had scrambled them.

**Open questions for the owner:**

- `color.chip.*` is not shipped. It is mapped to `color.neutral.*`, color.status.{tone}.* and `color.text.*` (see tokenMap). Confirm this mapping, or add a tier-3 `color.chip.*` group in a separate token PR.
- Palette (affects CMP-011, CMP-012 and CMP-023). In light, color.status.{info|warning|danger}.strong on .subtle is 4.34 / 4.11 / 3.85:1, below 4.5:1 for 11 px text, so status chip labels use color.text.primary and only the glyph uses .strong. In light, status.danger.strong resolves to the same primitive as status.warning.strong (palette.light.amber.300), so the glyphs are dE 0 apart for every vision type; since #3925 status.danger.default is palette.light.red.800, dE 56.6 from warning's (33.9 tritan). In dark, danger.strong (amber.400) and warning.strong (amber.300) are dE 14.7 apart (11.2 tritan). Warning and danger therefore differ by their subtle fill, glyph shape and word, not by hue; under tritanopia in light the subtle fills are only dE 4.7 apart (below the 5.0 JND), so the glyph shape and the word carry it there. Should the owner open a palette follow-up?
- Estimated interactivity: brief §12 requires every estimated chip to link to its CMP-069 InfoPanel, but CMP-011 has no handler prop. Either add onOpenMethodology? (required when variant="estimated"), or confirm the chip is only interactive inside CMP-227 EstimatedBadge. In the second case the CMP-011 estimated chip is static and its focus-visible and disabled variants are dropped.
- Should the estimated chip be exempt from opacity.disabled? It is an honesty marker (brief §1 principle 2, 'never lie by omission'; CMP-227), and dimmed its label drops to 2.84 / 2.31 / 3.96:1. If it is exempt, a disabled estimated chip keeps full opacity and only leaves the tab order, and the drawn State=disabled variant becomes a note.
- Chip height binds size.control.height so the 24×24 remove target fits. In a 24 px table row the chip therefore touches the row edges. A shorter inline chip would need a new semantic size token; none is invented here.
- RAW-VALUES REGISTER (group Indicators; one ruling for all groups). The E05-D02 AC and brief §12 ask for zero hardcoded px. Unbound numbers left in this group: (1) 1 px strokes: CMP-011 neutral outline, CMP-011 dashed estimated outline (and its dash pattern), CMP-012 count outline, CMP-032 empty-dot ring; the primitive border.hairline (1) exists but conventions only allow border.focus. (2) 2 px strokes: CMP-025 cut-out ring and CMP-014 arc; the primitive border.thick (2) exists. (3) Focus-ring geometry: CMP-011's ring rect is the chip expanded by 4 px (conventions §3's 2 px offset + the 2 px border.focus width), the same in every group. (4) Data-driven or intrinsic geometry: the CMP-023 root width (200 px in the drawn variants; instances fill their parent), the CMP-023 indicator widths (value % of the track: 124 / 170 / 200 px), and the CMP-014 arc (270° sweep, radius 9/24 of the box, round caps). Proposed ruling: record border.hairline and border.thick as named conventions exceptions, like border.focus, so strokes can bind; whitelist (3) and (4) as intrinsic geometry. CMP-025 no longer uses a raw negative gap (token-bound slots, see CMP-025). Stale since the build: slice 1 B1 and §5 E4 now put this ruling to you (`border.hairline` and `border.thick` as named exceptions), and CMP-014 is slice 1's and CMP-023 a later slice's.
- Penpot treats '/' in a component name as an asset-group path, so 'Tag / Chip' is named 'CMP-011 · Tag', with the full catalogue name in the component description. Confirm this rule so all groups name slashed components the same way.
- Matrix scope: Removable=true is drawn only for Variant=neutral (FilterBar and TagEditor chips). Status chips report system state and the estimated chip is an honesty marker, so neither is removable; this is now a spec rule, mirrored in catalogue_updates. Confirm. Estimated State=disabled is drawn because conventions §2 makes disabled universal for interactive components. It is the chip's own state and is never stacked on a disabled parent.
- Gated removal (RBAC, env, CMP-169 rule-sourced readOnlyTags) is expressed by the consumer. Either omit the remove control (read-only tags), or show the nested CMP-002 in its disabled-with-reason look through CMP-079 (locked icon + CMP-016 tooltip). Superseded by E09-D09 §2.2 T2 (#3953); the boards PR folds §1, §5 E10, the CMP-011 and CMP-021 sections of §6 (CMP-021's gated state as §5 E27 rules: a T2 link or none), §7, the audit's gated rows and the catalogue's gated clause into T2, and T2 governs until then. Per conventions §2, no new chip State value is drawn unless the owner asks for one. Confirm.
- A single chip cannot see its siblings, so the focus-after-removal rule (next remove button, else previous, else the group's input) is a consumer contract. The CMP-169 TagEditor and CMP-055 FilterBar entries should state it in their own tickets.
- Removable + focus-visible (build review): the nested CMP-002 ring (2 px offset + 2 px border.focus) exactly fills the 4 px space.inset.xs gap, so its outer edge touches the last glyph of the label. Accept, or widen the label-to-remove gap?
- Estimated chip (build review): on a radius.badge pill, Penpot's default dash pattern leaves the two end arcs as separate short dashes. They read like a second pair of brackets around the literal '(estimated)'. Accept, tune the (unbound) dash pattern, or drop the literal parentheses (affects CMP-227 parity)?

### CMP-012 · Badge

**Catalogue (verbatim):**

- **Props**: `variant: "count"|"dot"` · `value?: number` · `tone: "neutral"|"info"|"success"|"warning"|"danger"`.
- **A11y**: `aria-label` describing meaning (e.g. "3 unread alerts"), never colour-only — dot variant always paired with adjacent text/icon at point of use.

| Axis    | Values                                  | Default |
| ------- | --------------------------------------- | ------- |
| Variant | count, dot                              | count   |
| State   | default                                 | default |
| Tone    | neutral, info, success, warning, danger | neutral |

**Drawn:** 10 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d153fe4eec00`.

_Board `CMP-012 · Badge — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it and exports `img/CMP-012-badge-status-dot-count.png` here._

**Keyboard** (None (static indicator). A standalone count badge uses the WAI-ARIA 1.2 img role.):

| Keys | Action                                                                                                                                        |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| none | Not focusable; no keyboard interaction. A badge on a control (e.g. the notifications IconButton) leaves focus and activation to that control. |

**Accessible name and role:**

| Element                                         | Role | Name                                                                                                                       | ARIA                                                                                                                                                                                                                                                               |
| ----------------------------------------------- | ---- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| container (Variant=count, standalone)           | img  | aria-label naming the count, what is counted and any condition the tone implies, e.g. "3 unread alerts", "2 failed orders" | role=img is required because ARIA 1.2 prohibits aria-label on a generic span. Not a live region: the host decides what is announced. The count always sits on or beside visible text or an icon naming what is counted; the tone never carries the condition alone |
| container (Variant=count on a labelled control) | none | none; the count joins the host's name, e.g. "Notifications, 3 unread"                                                      | aria-hidden="true"                                                                                                                                                                                                                                                 |
| container (Variant=dot)                         | none | none; the adjacent visible word names the state (with the tone's registry glyph for info/success/warning/danger)           | aria-hidden="true" always. A dot is never rendered alone, so there is no standalone role=img dot                                                                                                                                                                   |
| value / dot                                     | none | none                                                                                                                       | presentational (inside the img or the hidden container)                                                                                                                                                                                                            |

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue                                                | Shipped                                                                                                      | Note                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `color.status.*` (dot)                                   | color.status.{info\|success\|warning\|danger}.default                                                        | ≥3:1 on color.surface.app and color.surface.canvas in every theme (lowest 3.22:1: light warning on canvas). Below 3:1 elsewhere: in light, warning is 2.999 on raised, 2.76 on overlay and hover, 2.46 on selected and sunken, and info is 2.86 on selected and sunken; in dark, danger is 2.92 on hover and 2.43 on selected, and in high contrast 2.87 on selected. On those surfaces the dot is a redundant cue only; the glyph and word carry the meaning |
| `color.status.*` (count fill)                            | color.status.{info\|success\|warning\|danger}.subtle                                                         |                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `color.status.*` (count outline)                         | color.status.{info\|success\|warning\|danger}.strong                                                         | ≥3.64:1 vs canvas and ≥3.39:1 vs raised in every theme (lowest: light success.strong)                                                                                                                                                                                                                                                                                                                                                                         |
| tone="neutral" (`color.status.neutral.*` does not exist) | color.neutral.default (dot, count outline), color.neutral.subtle (count fill)                                |                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| (count numeral: not in the entry)                        | color.text.primary + type.num.xs                                                                             | Solid fills were rejected: no text token reaches 4.5:1 on every status .default in every theme (e.g. text.inverse is 3.83:1 on dark danger.default and 3.45:1 on light warning.default)                                                                                                                                                                                                                                                                       |
| (shape: not in the entry)                                | size.icon (count height and min-width; dot slot), space.inset.xs (count paddingX; dot padding), radius.badge |                                                                                                                                                                                                                                                                                                                                                                                                                                                               |

**Hit target:** Not applicable: the badge is not interactive. When it decorates a control, the host's own target (at least 24×24) applies, and the badge must not shrink or cover it.  
**Motion:** None. Count and tone changes are instant, with no pulse, bounce or count-up (E08-D01 §4: a state change is a single flip, with no pulsing).

**Resize & overflow:** Count: the size.icon height is a minimum, and the pill grows with the numeral at 112–150 % text and with more digits (hug, min-width size.icon); the "99+" cap waits for §5 E11, and the aria-label always keeps the full number. Dot: a fixed 8 px dot in a size.icon slot that never scales with text, aligned to the first line of its paired word. Neither ever truncates.

**Forced colors:** Count: its 1 px outline becomes a CanvasText border on Canvas with a CanvasText numeral; the tone colours are lost, and the host text and the aria-label carry the condition. Dot: `forced-color-adjust: none` with a CanvasText fill, because a background-filled dot would be repainted as Canvas and vanish; the paired glyph and word carry the tone (conventions §4).

**Deviations recorded by the build:**

- Dot sizing: the spec's stop condition was hit, and 8 px was not hardcoded. An empty flex board set to hug keeps its own size in Penpot, so padding does not size it. Each `dot` board (hug, padding space.inset.xs on all sides, fill color.status.{tone}.default or color.neutral.default, radius radius.badge) holds a transparent 0.01x0.01 rect named `spacer`. The dot's size still comes from the inset token: it renders 8.01x8.01, centred in the 16 px size.icon slot. This needs owner acceptance (the dot-sizing question below).
- Count width: the count root is now hug width with fixed height. On all 5 mains flex.horizontalSizing is auto (layoutChild.horizontalSizing auto) and verticalSizing is fix, with height bound to size.icon. layoutItemMinW is bound to size.icon (layoutChild.minWidth 16) on all 5. Penpot applies a layout child's min width only to children set to fill, so a single digit still renders 14x16 (4 + 6 + 4) instead of a 16 px circle. In code, the CSS min-width gives 16. More digits now grow the pill. Checked with two temporary instances, since deleted: '12' gives 20x16 and '99+' gives 26x16, with the numeral at the 4 px inset and nothing clipped.
- Sizing tokens: in this Penpot build, binding a sizing token to width or height records the binding but does not resize the shape. So each size-bound shape was resized to the token's value, read at runtime (size.icon = 16), and then bound: count height, dot slot width and height, and the 4 glyph instances (scaled from 24 to 16; their vectors use scale constraints). On the count roots that resize had switched them from hug to fixed; they are set back to hug.
- Relayout: every text in the section is measured. The section's 36 flex boards outside component copies, and the section itself, were relaid; shapes inside component copies were skipped, because relaying a copy records a sizing override on it. Such an override is why the 6 count instances had not followed the main.
- Values with no token: the 1 px inside count outline (strokeWidth left unbound, as the spec's raw-values register says), the 0.01 px dot spacer, the 960 px width of the description, keyboard and a11y texts and of the matrix board, and the 1.5 px glyph strokes that come with the icon/{name} components.
- The variant container keeps the 2 px inner stroke (#bb97d8) that Penpot adds to every variant container. It is not token-bound, and it is the only unbound fill, stroke or text in the section. CMP-004, CMP-014, CMP-018 and CMP-020 have the same stroke.
- Usage samples: a `usage` board between the variant set and the matrix, filled with color.surface.app. It holds 5 dot pairings with gap space.inset.xs: Idle (word only), Syncing, Healthy, Degraded and Blocked. Each is a dot plus a glyph bound to color.status.{tone}.strong at size.icon, plus a word in type.ui.caption / color.text.primary. It also holds 'Alerts' + a count instance (Tone=danger, 3) + the annotation 'a11y: role="img", aria-label="3 unread alerts"'. The spec gives no style for the 'Alerts' label, so it uses type.ui.caption / color.text.primary.
- Matrix captions list only the axes that vary ('Variant=count, Tone=neutral'). State has only the value default, so it is not a variant property.
- The rules' 'visible: hidden' is done by leaving the part out: count variants contain only `value` and dot variants only `dot`. There are no hidden layers.
- No focus, disabled, loading or error states, and no reason row: the spec draws only State=default and the badge is not interactive. CMP-014, CMP-016 and CMP-039 instances are not needed.

**Open questions for the owner:**

- Count style: a solid status fill fails 4.5:1 for the numeral in at least one theme for info, warning and danger, so the count badge is drawn tinted (subtle fill, text.primary numeral, .strong outline). Confirm, or add `color.text.on-status.*` tokens if solid count badges are wanted.
- Pairing strength: conventions §4 makes the status glyph mandatory, so a status dot is specified with its glyph and a word, which makes the dot itself a third, redundant cue. The catalogue only asks for 'text/icon'. If the owner finds dot + word enough, the rule can be relaxed to word-only for dots; the dot stays aria-hidden either way. (The identical light warning and danger glyph colours, `.strong`, are covered by this pairing rule; the palette follow-up is asked in CMP-011.)
- Large counts: should the display cap at "99+" (the aria-label keeps the full number)? The catalogue does not say.
- Connection dots: in the E08 vocabulary, a Badge dot showing connection state would use tone warning for reconnecting and tone danger for disconnected (the same primitives as color.data-confidence.{reconnecting|disconnected}.indicator). But CMP-239 says reconnecting and disconnected bubble to the parent CMP-028 banner, and E08-D04 §3 draws its own indicator dot per state. So it is unsettled whether CMP-012 renders connection dots at all, even though its catalogue purpose names a 'connection dot'. Confirm ownership. The matching catalogue update is held as pending.
- Matrix scope: the full 2×5 Variant × Tone cross (10 variants) is drawn, rather than the minimal reading 'each Tone once', because both count and dot are used in every tone.
- Dot sizing: accept the 0.01 px spacer, which keeps the dot sized by space.inset.xs padding (8.01 px)? Or hardcode 8 px, or add a density-independent sizing token for dots? It needs your explicit acceptance (§5 E5); the spacer is recorded in §4.2.
- Count min-width in Penpot: is a 14x16 single digit acceptable? The count now hugs and grows for '12' and '99+', and the size.icon min-width binding is kept for handoff, where CSS gives 16. Alternatively, a Penpot-only min-width strut can force 16 px: a column 'value-slot' holding the value plus a strut sized by padding. That adds layers that are not in the anatomy.
- Token check: in the shipped semantic-dark set, color.status.danger.strong resolves to palette.amber.400 (#F0B441). So the danger count outline and the danger glyph render amber, close to warning.strong (amber.300 #F5C86B). Is that intended? This is for the token owner, not this build.

### CMP-013 · Avatar

**Catalogue (verbatim):**

- **Props**: `label: string` (initials derived) · `color?: string` (deterministic per-account hash) · `size`.
- **A11y**: decorative unless only content — pairs with visible text label at point of use.

| Axis  | Values  | Default |
| ----- | ------- | ------- |
| Size  | sm, md  | md      |
| State | default | default |

**Drawn:** 2 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d15c412ce2b9`.

_Board `CMP-013 · Avatar — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it and exports `img/CMP-013-avatar-profilebadge-base.png` here._

**Keyboard** (None (static image; the WAI-ARIA img role when the avatar is the only content).):

| Keys | Action                                                 |
| ---- | ------------------------------------------------------ |
| none | Not focusable; no keyboard interaction (static image). |

**Accessible name and role:**

| Element                                 | Role | Name                                                   | ARIA               |
| --------------------------------------- | ---- | ------------------------------------------------------ | ------------------ |
| container (default: decorative)         | none | none; the adjacent visible label names the account     | aria-hidden="true" |
| container (when it is the only content) | img  | the full label, e.g. "Alpha Desk" (never the initials) | aria-label         |
| initials                                | none | none                                                   | presentational     |

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue                         | Shipped                                                                                         | Note                                                                                                              |
| --------------------------------- | ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| color.avatar.palette[]            | none yet (open question); interim fill color.neutral.subtle with initials in color.text.primary | No semantic token can express a per-account palette. Conventions §9 says to raise this rather than invent a token |
| radius.circle                     | radius.badge                                                                                    | radius.circle is a primitive (9999); radius.badge also resolves to 9999, which gives a circle on a square box     |
| size (no values in the catalogue) | sm = size.icon (16); md = size.control.height (24 compact / 32 comfortable)                     |                                                                                                                   |
| (initials type: not in the entry) | type.ui.label (md), type.ui.caption (sm)                                                        |                                                                                                                   |

**Hit target:** Not applicable: the avatar is not interactive.  
**Motion:** None (static).

**Resize & overflow:** A fixed circle (size.control.height for md, size.icon for sm) that never grows with text. The initials are part of the graphic: sized with the circle, they do not follow the text scale (two letters do not fit a 24 px circle at 150 %), and the circle clips them. The full name is in the adjacent visible label or, when the avatar is the only content, in its aria-label; nothing inside the circle truncates.

**Forced colors:** The circle carries a transparent 1 px border at rest, which forced colours paint CanvasText (its fill is repainted as Canvas), and the initials render in CanvasText.

**Deviations recorded by the build:**

- The variant set has one property, Size (md, sm). State has only the value 'default' and does not vary in draw, so it is not a variant property. Matrix captions still read 'Size=md, State=default' and 'Size=sm, State=default'.
- Each variant root IS the anatomy 'container': a flex row board, centred, fixed square, clip content on, the same root-as-container pattern as CMP-012 and CMP-014. A wrapper board would make the instance-level 2 px cut-out stroke that CMP-025 puts on avatar instances square instead of circular.
- The sm main's size.icon width/height binding was lost when the plugin tab was suspended mid-call (shape stayed 100x100). Fixed by resizing it to the token's resolved value (16x16) and re-binding size.icon. Final state: width/height bound to size.icon, 16x16.
- The description text is the spec description_verbatim exactly as written, markdown ** and backticks included (CMP-012 does the same; CMP-014 stripped the markdown).
- Added a 'tokens' caption after the a11y text, the way CMP-014 does. It records the tokenMap, the interim color.neutral.subtle fill, and that Size lg and the ColorPalette story are deliberately not drawn. The a11y text also ends with the spec's hit-target and motion lines, as in CMP-012.
- Hard-coded geometry: none in the component, where every fill, radius, width, height, padding, gap and typography is token-bound. The doc frame's 960 px text width is a documentation layout constant (§4.1). The purple outline on the variant container is Penpot's own variant-container frame, also seen on CMP-014; the build did not set it.
- No reason demo row and no focus, disabled, loading or error states. The avatar is static and not interactive, and the spec defines none of these.

**Open questions for the owner:**

- The avatar palette needs semantic tokens (for example a color.avatar.N set with paired initials text). They must be contrast-validated, CVD-reviewed (brief §12) and kept clear of the reserved env colours (demo blue, live red) and the buy/sell green/red (brief §2.1). Until then the ColorPalette story cannot be drawn, and the runtime `color` hash is outside the token system.
- Size lg is not drawn: no semantic sizing token exists above size.control.height (32 px comfortable). Add one, or confirm that sm and md are enough.
- Confirm that sm (16 px) shows one initial and md shows two (first letters of the first two words).
- Penpot name: 'Avatar / ProfileBadge base' contains '/', which Penpot reads as an asset path, so the component is named 'CMP-013 · Avatar'.

### CMP-018 · Divider

**Catalogue (verbatim):**

- **Props**: `orientation: "horizontal"|"vertical"` · `inset?`.
- **A11y**: `role="separator"` when semantically meaningful (e.g. inside menu), decorative otherwise.

| Axis        | Values               | Default    |
| ----------- | -------------------- | ---------- |
| Orientation | horizontal, vertical | horizontal |
| Inset       | false, true          | false      |

**Drawn:** 4 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d14b336c413c`.

_Board `CMP-018 · Divider — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it and exports `img/CMP-018-divider.png` here._

**Keyboard** (A non-focusable ARIA `separator`, as used inside the APG Menu/Menubar and Toolbar patterns; otherwise decorative.):

| Keys                        | Action                                                                                             |
| --------------------------- | -------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab, Arrow keys | Never focusable. In an APG Menu, Menubar or Toolbar, arrow-key focus movement skips the separator. |

**Accessible name and role:**

| Element                                             | Role          | Name        | ARIA                                                                                                                                                                                  |
| --------------------------------------------------- | ------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Divider, decorative (layout)                        | none (hidden) | not exposed | Radix Separator decorative: no role, removed from the accessibility tree.                                                                                                             |
| Divider, meaningful (inside Menu, Menubar, Toolbar) | separator     | unnamed     | role="separator"; aria-orientation="vertical" when vertical (horizontal is the implicit default); not focusable. Never inside a listbox: ARIA 1.2 allows only option and group there. |

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue           | Shipped             | Note                                                          |
| ------------------- | ------------------- | ------------------------------------------------------------- |
| color.border.subtle | color.border.subtle | Exists and is unchanged. See the light-overlay open question. |

**Hit target:** n/a. The divider is non-interactive.  
**Motion:** None. The divider is static.

**Resize & overflow:** A horizontal divider fills its container's width; a vertical one defaults to size.control.height and stretches to its toolbar's height. The 1 px rule and the inset spacing do not follow the text scale.

**Forced colors:** The rule is drawn as a 1 px border, not a background (which forced colours repaint as Canvas), so it renders in CanvasText on every surface; the separator semantics are unchanged.

**Deviations recorded by the build:**

- The rule is 1 px thick: rect height on horizontal variants, width on vertical ones. No token exists for this; it equals the primitive border.hairline (spec open question 4).
- The horizontal container is drawn 240 px wide as a sample width; real instances fill their parent. Not token-bound.
- Padding 0 and gap 0 on the non-inset containers are left unbound because they are zero values with no token (spec: 'Padding 0 unless inset; gap 0; no fill'). So the Orientation=horizontal, Inset=false main has no token bindings on the board itself; its rule binds color.border.subtle.
- The variant set's 2 px outline is Penpot's built-in variant-container stroke. It is the only unbound stroke in the section, the same as the other atom sections.
- The description is the spec's description_verbatim, markdown markers included ('- **Props**: ...'), as CMP-030 does; an earlier stripped version was replaced.
- Beyond the required texts, the section has three extra caption texts, as CMP-030 and CMP-020 do: notes (states not drawn, anatomy, semantics annotation, density), tokens (token map plus the two catalogue-update lines) and open-questions.

**Open questions for the owner:**

- `inset?` has no type or meaning in the catalogue. This spec reads it as a boolean that insets both ends: horizontal by space.inset.md (12 px, the space.panel.padding content edge), vertical by space.inset.xs (4 px). Confirm, or define it as leading-only (Material's list inset).
- Light theme: color.border.subtle resolves to the same value as color.surface.overlay (light.neutral.150, #E3E6EA, 1.00:1), so a Divider inside a light-theme Menu or Popover (CMP-041, CMP-017) is invisible. Dark overlay is 1.09:1. Options: dividers on color.surface.overlay bind color.border.default (dark 1.30, light 1.12, hc 2.64), or E05-D01 re-tunes light color.border.subtle. Owner decision.
- Semantic versus decorative has no prop. Proposal: adopt Radix Separator's `decorative?: boolean` (Radix default false, giving role="separator"); layout dividers pass decorative.
- Geometry constants for the whole group: 1 px rules and outlines (CMP-018, CMP-030, CMP-037 swatch outline; equal to the primitive border.hairline), 1.5 px strokes (CMP-019 glyphs, CMP-024 line; the brief §5 grid weight), and the 2 px focus offset with its +2 px concentric radius and the 2 px proposal/halo strokes (CMP-039) have no semantic token. #161's 'zero hardcoded px' criterion cannot be met for them as things stand. Options: allow border.hairline as a recorded primitive exception (like border.focus) and treat 1.5 px stroke and 2 px offset as glyph-grid constants, or add semantic tokens (e.g. a divider width and a focus-ring offset). Illustrative content geometry (sample widths, sparkline points, candle positions) is data, not tokens.

### CMP-020 · Typography primitives

**Catalogue (verbatim):**

- **Props** (NumericText): `value: number` · `format: "price"|"qty"|"pct"|"pnl"|"notional"` · `precision?` · `signDisplay?: "auto"|"always"|"never"` · `colorBySign?: boolean`.
- **A11y**: `NumericText` renders a visually-hidden expanded reading (`aria-label`) for screen readers when abbreviated (e.g. "1.2M" → aria-label "1,200,000") per §4.

| Axis        | Values                                                                                                                           | Default  |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------- | -------- |
| Variant     | text, heading, numeric-text, mono-text                                                                                           | text     |
| Style       | caption, body, body-strong, label, heading-sm, heading-md, heading-lg, display, num-xs, num-sm, num-base, num-md, num-lg, num-xl | body     |
| Format      | price, qty, pct, pnl, notional                                                                                                   | price    |
| SignDisplay | auto, always, never                                                                                                              | auto     |
| ColorBySign | false, true                                                                                                                      | false    |
| Sign        | positive, negative, zero                                                                                                         | positive |

**Drawn:** 29 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d157afaecfe3`.

_Board `CMP-020 · Typography primitives — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it and exports `img/CMP-020-typography-primitives-text-heading-numerictext-monotext.png` here._

**Keyboard** (None. These are static text. Heading uses the ARIA `heading` role; there is no APG widget pattern.):

| Keys            | Action                                                                                                               |
| --------------- | -------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab | Skipped. Static text is never focusable. Headings are reached through screen-reader heading navigation (H), not Tab. |

**Accessible name and role:**

| Element                           | Role                                      | Name                                                                                    | ARIA                                                                                                                                                                                                                                                                                                   |
| --------------------------------- | ----------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Text                              | none (generic span, or paragraph p)       | its text content                                                                        | none                                                                                                                                                                                                                                                                                                   |
| Heading                           | heading                                   | its text content                                                                        | Rendered as h1 to h6. aria-level is the semantic `level`, independent of the visual Style.                                                                                                                                                                                                             |
| NumericText                       | none (generic span)                       | the value as displayed; '-420.00' is read as 'minus 420.00', '+420.00' as 'plus 420.00' | No aria-label on the span: ARIA 1.2 prohibits naming generic elements.                                                                                                                                                                                                                                 |
| NumericText, abbreviated ('1.2M') | none (generic span)                       | the expanded reading '1,200,000'                                                        | The visible '1.2M' is aria-hidden="true", followed by a visually hidden '1,200,000' text node. Deviation from catalogue: the catalogue A11y line puts this reading in aria-label, which ARIA 1.2 prohibits on a generic span (axe aria-prohibited-attr). Pending owner confirmation (open question 1). |
| NumericText with colorBySign      | none (generic span)                       | the value with its sign glyph: '+420.00', '-420.00', or an unsigned '0.00'              | colorBySign requires signDisplay="always", so every non-zero value carries a +/- glyph: that glyph is the non-colour channel, and zero is unsigned and neutral. Colour adds nothing for assistive tech. Spoken 'profit'/'loss' wording is the job of CMP-116 PnLBadge.                                 |
| MonoText                          | none (generic span; code when it is code) | its text content                                                                        | none                                                                                                                                                                                                                                                                                                   |

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue                                         | Shipped                                                                                                                                                                                                                        | Note                                                                                                                                             |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| font.family.ui/mono                               | `type.ui.*` / `type.num.*`                                                                                                                                                                                                     | The family is part of the composite typography tokens (`type.ui.*` = Inter, `type.num.*` = JetBrains Mono). There is no separate family binding. |
| font.size.scale[]                                 | type.ui.caption, type.ui.body, type.ui.body-strong, type.ui.label, type.ui.heading-sm, type.ui.heading-md, type.ui.heading-lg, type.ui.display, type.num.xs, type.num.sm, type.num.base, type.num.md, type.num.lg, type.num.xl | Size, weight and line-height come from the composite token (10/11/12/13/14/16/20/24 px scale).                                                   |
| color.text.buy                                    | color.buy.default                                                                                                                                                                                                              | HC re-points it to color.buy.hc. Text contrast is below 4.5:1 on some surface tiers (see open question 2).                                       |
| color.text.sell                                   | color.sell.default                                                                                                                                                                                                             | HC re-points it to color.sell.hc.                                                                                                                |
| color.text.neutral                                | color.neutral.default                                                                                                                                                                                                          | Zero or unchanged values.                                                                                                                        |
| text-buy / text-sell / text-neutral (§0.3 rule 6) | color.buy.default / color.sell.default / color.neutral.default                                                                                                                                                                 | Same mapping.                                                                                                                                    |
| font.feature.tabularNums (brief §2.2)             | none (no token)                                                                                                                                                                                                                | JetBrains Mono digits are fixed-width. Code sets font-variant-numeric: tabular-nums.                                                             |

**Hit target:** n/a. Static text has no target.  
**Motion:** None. Values change instantly. The price-tick flash recipe (brief §7: motion-safe instant-to-fast background flash, motion-reduce a brief text tint with no flash) belongs to the consuming trading cell, not to CMP-020.

**Resize & overflow:** All four primitives follow the text scale. Text and Heading wrap within their container and never truncate unless the consumer sets a line clamp and keeps the full text available. NumericText never wraps or truncates: a tabular column grows, or the consumer switches the value to format notional (abbreviated, with its expanded reading). MonoText (ids, hashes) may truncate in the middle with an ellipsis only where its consumer offers the full value (a CopyButton, a tooltip).

**Forced colors:** All text renders in CanvasText (LinkText inside links); the colorBySign colours are lost, so the + or − sign carries profit and loss, which is why colorBySign requires signDisplay="always" (§5 E14, conventions §4); headings keep their size and weight.

**Deviations recorded by the build:**

- The description is description_verbatim with the markdown markers removed (the leading '- ', '**' and backticks); the words are unchanged. This matches the CMP-014 section. Backticks were also removed from the keyboard, a11y, notes, tokens and open-questions texts.
- The variant container and the matrix are fixed at 960 px wide so the 29 variants and 29 cells wrap inside the 992 px section. No token exists for this width; it is a layout constant.
- The 'numeric column' alignment demo is fixed at 160 px wide and its caption at 480 px. These are illustrative sizes with no token.
- The variant container keeps Penpot's own purple variant-set stroke, which is not token-bound. The CMP-014 and CMP-012 sets have the same stroke. It has no fill.
- The anatomy says the variant root has padding 0, gap 0 and no fill, so the 29 variant boards have no spacing or fill tokens because there is nothing to bind. Each board has a flex row that hugs its content; numeric-text boards use justify end, and their text is right-aligned.
- Extra doc content beyond the standard section items: (a) an 'align-demo' row with seven numeric-text instances set to horizontal fill in a fixed-width column. It shows the anatomy's justify-end right alignment, and the horizontal fill is a layout override on those instances only. (b) Caption texts for notes (n/a axes, invalid combinations not drawn, tone and level), motion, tokens with the tokenMap, and open questions. (c) An extra 'note' caption in the notional cell (expanded reading 1,200,000, with the visible 1.2M aria-hidden) and in the qty/never/negative cell (comes from -0.250; the side is a separate 'Short' label).
- Numeric-text matrix captions wrap over 3 lines, 2 axes per line, so 4 cells fit in a row. Captions for text, heading and mono-text list only Variant and Style, the axes in their draw entries. The n/a values of the other four axes (Format=price, SignDisplay=auto, ColorBySign=false, Sign=positive) are stated once in the 'notes' text.

**Open questions for the owner:**

- Deviation from the catalogue A11y line (owner decision): the catalogue puts the abbreviated value's expanded reading in `aria-label`, but ARIA 1.2 prohibits naming a generic span (axe aria-prohibited-attr). This spec renders the visible '1.2M' aria-hidden plus a visually hidden '1,200,000' text node. The catalogue_updates rewrite the A11y line and rename the AbbreviatedWithAriaLabel story to match. The Penpot description still quotes the catalogue verbatim, so the a11y annotation carries a 'Deviation from catalogue' line. Confirm, or name the value through an element whose role allows naming.
- colorBySign text contrast (13 px text needs 4.5:1), recomputed from the token files. Failing pairs: dark color.sell.default 4.42 raised, 4.09 overlay, 3.76 hover, 3.13 selected (it passes app 4.94, canvas 4.68, sunken 5.37); dark and hc color.neutral.default (the zero colour) 3.98 on selected; light color.buy.default 4.30 on overlay and hover, 3.84 on sunken and selected; light color.sell.default 4.15 on overlay and hover, 3.70 on sunken and selected. Dark buy, hc buy and sell, and light neutral pass on every tier. Hovered and selected table rows are the most common failing context, so a negative value in a selected or hovered row fails WCAG 1.4.3, and verify_tokens.py does not test buy/sell/neutral text pairs. Options: (a) ship the catalogue's text-grade names color.text.buy / color.text.sell / color.text.neutral, tuned to at least 4.5:1 on every tier including hover and selected, with a proof check (E05-D01 follow-up); (b) restrict colorBySign to app and canvas surfaces, which would also have to exclude hovered and selected rows, so it does not fit interactive tables. Until decided, the draw uses the shipped color.buy/sell/neutral.default.
- Only NumericText has catalogued props. This spec assumes Heading takes `level` (1 to 6) independent of its visual Style, and that Text tone is an instance colour override (primary by default). Confirm, or catalogue these props.
- Formatting decisions to confirm: zero renders unsigned in every signDisplay mode (`always` maps to Intl exceptZero). `format="pnl"` and `colorBySign` both require signDisplay `always`, so `auto` and `never` are invalid with either: 05 §4.1 asks for an explicit +/- sign on P&L and never colour alone, and CMP-116 PnLBadge always shows the sign. Grouping is ',' and the decimal is '.' regardless of locale. The threshold for K/M/B abbreviation is unspecified (the drawn example is 1,200,000 → 1.2M).
- Build question: is one 'notes' line stating the n/a axes for text, heading and mono-text enough to meet 'the doc marks them n/a', or should every matrix caption repeat it?

### CMP-021 · Link

**Catalogue (verbatim):**

- **Props**: `href?` · `to?` (internal route) · `external?: boolean` (renders icon + `rel="noopener"` + opens Electron shell external browser).
- **A11y**: native `<a>`, focus-visible ring, external-link icon has `aria-hidden` with adjacent visually-hidden "(opens externally)" text.

| Axis     | Values                                                 | Default |
| -------- | ------------------------------------------------------ | ------- |
| State    | default, focus-visible, disabled, disabled-with-reason | default |
| External | false, true                                            | false   |

**Drawn:** 7 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d18bbf9079fb`.

_Board `CMP-021 · Link — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it, its gated state held until §5 E27 is answered and then drawn per that ruling, and exports `img/CMP-021-link.png` here._

**Keyboard** (Link (WAI-ARIA APG Link pattern, native `<a href>`; explicit role="link" for the disabled states, which have no href)):

| Keys                               | Action                                                                                                                                                                     |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab                    | Moves focus to / from the link; keyboard focus shows the ring. A plain disabled link (no href, no tabindex) is skipped; disabled-with-reason stays focusable (tabindex=0). |
| Enter                              | Follows the link: an internal route navigates in-app; External=true opens the system browser through the Electron shell.                                                   |
| Enter (State=disabled-with-reason) | No navigation; the reason tooltip (CMP-016) is shown because the link has focus.                                                                                           |
| Esc (reason tooltip open)          | Dismisses the reason tooltip; focus stays on the link.                                                                                                                     |
| Space                              | Not handled (native link behaviour; Space does not activate links).                                                                                                        |

**Accessible name and role:**

| Element                             | Role                                                                                    | Name                                                                                                                              | ARIA                                                                                            |
| ----------------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| link (State=default, focus-visible) | link (native `<a href>`)                                                                | Visible link text; External=true appends the visually-hidden " (opens externally)" ("Bybit API documentation (opens externally)") | External: rel="noopener" (catalogue)                                                            |
| link (State=disabled)               | link (explicit role="link": an `<a>` without href has no link role, it maps to generic) | Visible link text                                                                                                                 | aria-disabled="true"; no href and no tabindex, so it is not focusable and is skipped by Tab     |
| link (State=disabled-with-reason)   | link (explicit role="link", no href)                                                    | Visible link text (e.g. "Shortcut settings")                                                                                      | aria-disabled="true" + tabindex="0" + aria-describedby="`<reason id>`"; activation does nothing |
| external-icon                       | none (decorative)                                                                       | —                                                                                                                                 | aria-hidden="true"                                                                              |
| locked                              | none (decorative)                                                                       | —                                                                                                                                 | aria-hidden="true"; the reason text is the accessible description                               |
| sr-text                             | text (visually hidden span)                                                             | " (opens externally)"                                                                                                             | part of the link's accessible name                                                              |
| reason                              | tooltip                                                                                 | Reason text from E09-D09 §3.1's vocabulary, e.g. "Your role can't {verb}."                                                        | referenced by the link's aria-describedby; shown on hover and focus; Esc dismisses              |

The State=disabled-with-reason, `locked` and `reason` rows, and the keyboard table's disabled-with-reason and Esc rows, are as built and held for §5 E27, as the audit's §2 row says.

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue                                     | Shipped                                                                                                   | Note                                                                                                                                   |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| color.text.link                               | color.text.link                                                                                           | Exists; label text, underline, external-link icon and locked glyph. 7.05:1 on canvas (dark), 6.30:1 (light), 6.15:1 on overlay (dark). |
| (not listed) type, icon, gap, focus, disabled | type.ui.body, size.icon, space.inset.xs, color.focus.ring, radius.control, border.focus, opacity.disabled | type.ui.body is what the Penpot component shows; code inherits the surrounding font.                                                   |

**Hit target:** Inline in a sentence: WCAG 2.5.8 inline exception (the target is bounded by the line box, 18.2 px for type.ui.body). Standalone (e.g. "Forgot password?"): keep at least 24 px clearance to the next target (2.5.8 spacing exception) or place it in a size.control.height row. Logged as this component's target note.  
**Motion:** None (state changes are instant in both motion-safe and motion-reduce).

**Resize & overflow:** No fixed height: an inline link wraps with its sentence (the underline follows each line) and follows the text scale; a standalone link does not wrap and grows (in a size.control.height row it keeps the row's minimum height). The external icon stays attached to the last word (no line break before it).

**Forced colors:** Label, underline and external icon render in LinkText (forced colours own link colours), and the underline stays; focus: a Highlight outline; plain disabled: GrayText; a gated link, if §5 E27 keeps one, follows E09-D09 §2.2 T2, and the boards PR draws it per that ruling.

**Deviations recorded by the build:**

- Focus-ring corner radius is bound to radius.control (4 px), as the spec's anatomy and State=focus-visible rule name it. The generic state rule (target radius + 2, 0 if square) would give 0 here, because the link root has no radius. The spec's token is kept and flagged in the notes and in the open questions (§5 E8).
- Geometry constants with no token: the focus-ring rect is the link bounds plus 4 px, placed at -2,-2 (the CMP-039 2 px offset; its 2 px outer stroke is bound to border.focus). Doc-frame widths are illustrative: description, keyboard, a11y and notes texts 960 px, matrix 960 px, reason caption 620 px, variant container 640 px.
- The variant container is 640 px wide, not the 960 px earlier builds used, so it wraps into one row per External value (false row 512 px, true row 572 px). Its children are re-appended in the spec's draw order.
- sr-text (External=true only) stays an in-flow child that is hidden, not an absolutely positioned layer. Penpot leaves hidden layers out of flex layout, so it sits outside the flow as the spec asks, and conventions section 5 allows only the focus ring and overlay anchors to be absolute. It was created visible, measured, then hidden.
- Hidden locked and external-icon instances kept stale creation coordinates, because hidden flex children are not laid out. They are parked at their in-flow position inside the root (locked at 0,1.5; external-icon after the label). Cosmetic only.
- Icon mains are 24x24. Each locked / external-link instance was resized to 16 and bound to size.icon (width and height), with strokes bound to color.text.link.
- The label underline is a text property (textDecoration=underline), not a token, as the spec says.
- The variant container keeps Penpot's own variant-container border stroke, unbound. It is the only unbound paint in the section; earlier builds had it too.
- Reason row: the CMP-016 Tooltip instance sits above the disabled-with-reason link (spec: side=top, anchored above the link) in an 'anchor' column. The anchor gap is space.inset.xs, per CMP-016's 4 px placement rule, rather than space.stack.xs (both 4 px). The explanatory caption sits beside the anchor.
- A 'notes' text (hit target, motion, layers, states, focus ring, token map, the spec's 5 open questions) follows the reason row. It goes beyond the standard section items, as earlier builds did.

**Open questions for the owner:**

- CMP-021 has no States line: drawn default, focus-visible and disabled (the matrix rule makes disabled universal) plus disabled-with-reason (next item). Hover, active and visited are not drawn. Add any?
- OWNER APPROVAL (list in the PR body), gated links, now §5 E27: slice 1's C2 does not cover links, and `14` §0.5 rule 5 step 1 hides a link to an admin destination (T3) rather than gating it, so E27 asks only about non-admin destinations. As built: RBAC/env-gated links use State=disabled-with-reason (focusable role="link" + aria-disabled + reason tooltip), because 14-screens-catalogue.md §0.5 rule 5 renders a control the session may not use 'disabled with a visible reason' and 'never hidden' (only whole admin areas are hidden from navigation), the settings screen's sign-off checklist there requires 'sections the role cannot use are disabled with a reason, not hidden', and brief §12 forbids a bare disabled control for any RBAC/env-gated action. Superseded by E09-D09 §2.2 T2 (#3953); the boards PR folds §1, §5 E10, the CMP-011 and CMP-021 sections of §6 (CMP-021's gated state as §5 E27 rules: a T2 link or none), §7, the audit's gated rows and the catalogue's gated clause into T2, and T2 governs until then. Plain disabled (not focusable) stays for unavailability that is not gating. This adds `disabled?/disabledReason?` to Link's Props (CMP-079 propagates disabledReason to the wrapped atom), a catalogue edit held until E27 is answered; a "no" still adds plain `disabled?`, which `15`'s States and A11y lines already use. Drawn for External=false only: external documentation links are not RBAC/env-gated. Confirm.
- The link is always underlined: color.text.link against body text is 2.16:1 (dark), below the 3:1 that would let colour alone mark a link (WCAG 1.4.1).
- Add `noreferrer` to the catalogue's rel="noopener" so the private host never leaks in a Referer header on the browser dev target?
- The external-link icon renders at size.icon (16 px) beside 13 px text; revisit with the icon optical-size decision on #161.
- Focus ring radius: the spec binds radius.control (4 px rounded ring) on an unrounded inline link, while the CMP-039 / conventions concentric rule (element radius + 2, 0 if square) would give a square ring. Which should code ship? The build follows the spec.

### CMP-024 · Sparkline

**Catalogue (verbatim):**

- **Props**: `data: number[]` · `width/height` · `colorBySign?: boolean`.
- **A11y**: `role="img"` + `aria-label` summarising trend ("up 3.2% over 20 bars"); underlying data reachable via the parent row's DOM-mirror table (not a standalone interactive control).

| Axis        | Values         | Default |
| ----------- | -------------- | ------- |
| Trend       | up, down, flat | up      |
| ColorBySign | false, true    | false   |

**Drawn:** 6 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d17f976e0a2b`.

_Board `CMP-024 · Sparkline — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it and exports `img/CMP-024-sparkline.png` here._

**Keyboard** (None. A static graphic (ARIA `img`), not an APG widget.):

| Keys            | Action                                                                                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Tab / Shift+Tab | Skipped. The sparkline is not a standalone interactive control; the parent row (e.g. CMP-161 WatchlistRow) owns focus and the table alternative. |

**Accessible name and role:**

| Element         | Role                                    | Name                                                                                          | ARIA                                                                       |
| --------------- | --------------------------------------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Sparkline (svg) | img                                     | a trend summary: 'up 3.2% over 20 bars', 'down 3.2% over 20 bars' or 'unchanged over 20 bars' | role="img" aria-label="…"; path children are aria-hidden; not focusable    |
| Underlying data | the parent row's DOM-mirror table cells | per the parent (CMP-161, Deep Stats)                                                          | Values are reachable in the parent's mirror table, not from the sparkline. |

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue                                | Shipped                                     | Note                                                     |
| ---------------------------------------- | ------------------------------------------- | -------------------------------------------------------- |
| color.text.buy                           | color.buy.default                           | net up with colorBySign                                  |
| color.text.sell                          | color.sell.default                          | net down with colorBySign                                |
| (implied) neutral and uncoloured strokes | color.neutral.default / color.text.tertiary | flat with colorBySign / colorBySign=false (E06-D02 §2.3) |

**Hit target:** n/a. The sparkline is not interactive; the parent row is the target.  
**Motion:** None. It redraws instantly on new data (no draw-in, no tween). If a draw-in is ever added it must ship the brief §7 pair: motion-safe 'fast' line-draw, motion-reduce instant full render.

**Resize & overflow:** Data-sized: width and height come from the host (64 × 16 drawn); the polyline scales with its box, and the 1.5 px stroke never scales. It does not follow the text scale: a row that grows with text keeps the sparkline's height or lets it fill the row. The trend is in its role="img" name, so nothing is truncated.

**Forced colors:** The line uses stroke: currentColor, so it renders in CanvasText; the sign colours are lost, and the slope and the accessible name carry the direction (conventions §4).

**Deviations recorded by the build:**

- Geometry constants with no token: the sparkline container is fixed at 64 x 16 px. These are the width/height props as a sample size; the spec says the sparkline is data-sized and has no size token.
- The 1.5 px line stroke is a raw value. The spec's open question 2 says it has no token.
- The size-demo instances are resized to 256 x 64 px, an illustrative sample size. The 20 polyline point coordinates come from the spec's normalised y sets times 64 x 16.
- Each line path also starts with two move-to anchors, M0 0 and M64 16, before the polyline. They make the path's bounds equal the container, so sizing it fill x fill scales the polyline with the box and keeps its 0.15 to 0.85 height margins. Without them, fill sizing would stretch the line to the box edges. A probe showed they draw nothing and survive resizing (tested 160 x 40). This is recorded in the section notes.
- The spec asks for round caps and joins. The Penpot plugin API has no stroke-join property, so caps are set to round and joins use Penpot's default rendering. Stroke alignment is center, which is the only meaningful option for an open path.
- Extra content beyond the standard section items, following the CMP-030 section pattern: a size-demo row and notes, tokens and open-questions captions. The size-demo row holds 6 instances at 256 x 64 showing the width/height props, with the stroke staying 1.5 px.
- No focus-visible, disabled, disabled-with-reason, loading or error states are drawn, so the reason row does not apply. The spec defines no such states because the sparkline is a non-interactive role=img graphic.
- The matrix wraps 5 + 1 at its fixed 960 px width, because cells size to their captions. The variant container has no fill; Penpot draws its standard purple variant-container outline on export, as in the peer sections.

**Open questions for the owner:**

- Y-scaling: auto-ranging min..max makes a near-flat series look as volatile as a trending one, so the Flat story would read as noise. Proposal: floor the y-domain at a minimum span, e.g. ±0.5 % of the first value for price series, and per data kind for Deep Stats. This is an engineering constant documented in the story. The Penpot Flat variant is drawn within the middle 10 % of the height.
- The 1.5 px stroke has no token (see the CMP-018 geometry-constants question).

### CMP-025 · Avatar Group

**Catalogue (verbatim):**

- **Props**: `items: {label,color}[]` · `max: number` (overflow shows `+N` chip).
- **A11y**: `aria-label` listing all item labels even when visually truncated.

| Axis     | Values      | Default |
| -------- | ----------- | ------- |
| State    | default     | default |
| Overflow | false, true | false   |

**Drawn:** 2 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d167bfdeca91`.

_Board `CMP-025 · Avatar Group — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it and exports `img/CMP-025-avatar-group-stack.png` here._

**Keyboard** (None (static image summary using the WAI-ARIA img role).):

| Keys | Action                                                         |
| ---- | -------------------------------------------------------------- |
| none | Not focusable; no keyboard interaction (static image summary). |

**Accessible name and role:**

| Element                            | Role | Name                                                                                                                      | ARIA                                                                                                           |
| ---------------------------------- | ---- | ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| container                          | img  | "5 accounts: Alpha Desk, Bravo Sub, Carry Fund, Delta Main, Echo Hedge": every item label, including those folded into +N | aria-label (role=img is needed because aria-label is prohibited on a generic div); children are presentational |
| avatar instances (and their slots) | none | none                                                                                                                      | aria-hidden="true"                                                                                             |
| overflow (+N)                      | none | none                                                                                                                      | aria-hidden="true" (the hidden names are already in the container's name)                                      |

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue                               | Shipped                                                                                                                                   | Note                                   |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| space.avatar.overlap                    | none; the overlap comes from slots of width size.icon holding avatars of size.control.height (8 px in compact), pending the open question | no raw gap and no absolute positioning |
| (avatar cut-out ring: not in the entry) | color.surface.canvas (2 px outside stroke, width unbound)                                                                                 |                                        |
| (+N chip: not in the entry)             | color.neutral.subtle, color.text.secondary, type.num.sm, radius.badge, size.control.height (height and min-width), space.inset.xs         |                                        |
| (avatars)                               | CMP-013 · Avatar instances, Size=md, each in a size.icon-wide slot                                                                        |                                        |

**Hit target:** Not applicable: the group is not interactive.  
**Motion:** None (static).

**Resize & overflow:** One row that never wraps: items beyond `max` fold into the +N chip. Avatar and chip sizes are fixed and do not follow the text scale; the +N numeral sits in a chip whose min-width is size.control.height and which grows with digits. Every name stays in the group's aria-label.

**Forced colors:** Each avatar keeps its 1 px CanvasText border (CMP-013), and the cut-out ring (a border or outline in code, never a box-shadow, which forced colours remove) becomes a CanvasText ring that keeps overlapping circles apart; the +N chip: a 1 px CanvasText border and a CanvasText numeral.

**Deviations recorded by the build:**

- The +N chip still renders 22x24, not 24x24. layoutItemMinW is bound to size.control.height (minWidth reads 24), but Penpot ignores min-width on hug children. The chip is 14 px of '+2' text plus 2 x 4 px of space.inset.xs. In code, CSS min-width gives 24. CMP-012 hits the same Penpot limit. Kept as a documented gap (§4.2).
- The only variant property is Overflow (false, true). State has the single value 'default' and does not vary in the draw list. The matrix captions read 'State=default, Overflow=...' to match the draw entries.
- Raw value: the 2 px OUTSIDE cut-out ring on every avatar instance and on the +N chip. The width is unbound; the colour is bound to color.surface.canvas. The spec records it in the CMP-011 raw-values register (the primitive border.thick = 2). The slot widths (16) and the chip height (24) were resized to the token value read at runtime and then bound to size.icon and size.control.height, because in this Penpot build binding alone does not resize.
- clipContent is off on the variant roots as well as on the slots. The spec names only the slots; the roots need it so the 2 px outside rings are not cut at their top and bottom edges.
- The variant container keeps Penpot's built-in variant-set outline (#bb97d8, 2 px inner). It is the same on all 12 variant sets on the page and is the only unbound fill or stroke among the section's 56 shapes (57 counting the section).
- Extra documentation after the keyboard and a11y texts: a 'tokens' caption (anatomy bindings, the overlap arithmetic, the raw value) and a 'notes' caption (sample data, states not drawn, open questions), following the CMP-013 section. The a11y text also includes the spec's hit-target and motion lines.
- The variant container and the matrix hug their content instead of being fixed at 960 px, because there are only two variants. The section is 992x572.
- In the original build, a relayout toggled sizing on boards inside component copies; the two matrix instances were reset to their main at the time. The CMP-013 avatar copies inside the mains keep their intended overrides (initials, ring) and may also hold a same-value sizing override from that toggle. A later relayout skipped every board inside a component copy, so it added no overrides.

**Open questions for the owner:**

- space.avatar.overlap is not shipped. The overlap is now token-bound (slot width size.icon vs avatar size.control.height): 8 px in compact, but 16 px (half the avatar) in comfortable, because size.icon does not scale with density. Accept, or add a semantic overlap token. Note that at 8 px the next avatar and its ring also cover part of each covered avatar's second initial; the full names stay in the accessible name. The earlier raw −8 px negative gap remains an alternative only if the coordinator accepts raw values (raw-values register in CMP-011) and Penpot accepts a negative gap.
- The cut-out ring assumes the group sits on color.surface.canvas. On raised or hovered rows the ring colour will not match. Should the ring bind to the parent surface token per usage, or is canvas acceptable?
- Overflowed names reach assistive technology (through aria-label) but not pointer users. Should +N become a focusable CMP-016 tooltip trigger listing the hidden names? That would make it interactive and add focus-visible and disabled variants.
- Avatars are drawn at md only (24 px compact). Dense 24 px trade-group rows may need sm: add a `size` prop?
- Raw values: the only raw value left here is the 2 px cut-out ring stroke (raw-values register in CMP-011; the primitive border.thick = 2 exists).
- Penpot name: 'Avatar Group / Stack' is named 'CMP-025 · Avatar Group' because Penpot reads '/' as an asset path.
- Build: in Penpot the +N chip is 22x24 because min-width is ignored on hug children. Accept the documented gap (code applies min-width: 24px), or fix the chip width to size.control.height in the design file, which stops it growing for two-digit counts?

### CMP-030 · Divider-Label

**Catalogue (verbatim):**

- **Props**: `label: string`.
- **A11y**: renders as a non-interactive `role="separator"` with `aria-orientation="horizontal"`; label is visible text, not just aria.

| Axis  | Values  | Default |
| ----- | ------- | ------- |
| State | default | default |

**Drawn:** 1 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d1747940818b`.

_Board `CMP-030 · Divider-Label — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it and exports `img/CMP-030-divider-label.png` here._

**Keyboard** (None. A non-focusable ARIA `separator` named by its visible label; no APG widget pattern.):

| Keys            | Action                                                                                         |
| --------------- | ---------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab | Skipped. The separator is non-interactive; screen readers reach the label text in browse mode. |

**Accessible name and role:**

| Element | Role                                | Name                                                    | ARIA                                                                                                                                                 |
| ------- | ----------------------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| wrapper | none (div)                          | not named                                               | Holds the label span and the separator as siblings.                                                                                                  |
| label   | none (visible text span with an id) | its text, e.g. 'Take profit'                            | Read as normal text in browse mode.                                                                                                                  |
| rule    | separator                           | the label, via aria-labelledby pointing at the label id | aria-orientation="horizontal"; not focusable. The label must be a sibling, never a child, because in ARIA a separator's children are presentational. |

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue           | Shipped             | Note                                                                             |
| ------------------- | ------------------- | -------------------------------------------------------------------------------- |
| color.border.subtle | color.border.subtle | via the composed CMP-018 Divider instance (see CMP-018's light-overlay question) |
| font.size.caption   | type.ui.caption     | Inter 11 / 400 / 1.2, coloured color.text.secondary                              |
| (not listed) gap    | space.inset.sm      | between the label and the rule                                                   |

**Hit target:** n/a. Divider-Label is non-interactive.  
**Motion:** None. Divider-Label is static.

**Resize & overflow:** The caption follows the text scale and never truncates; the rule fills the remaining width and shrinks first, down to zero; in a very narrow container the caption wraps and the rule stays centred on its first line.

**Forced colors:** The caption renders in CanvasText and the rule as a 1 px CanvasText border (CMP-018).

**Deviations recorded by the build:**

- No spec axis varies in draw: State has the single value 'default'. A Penpot variant set cannot have zero properties, so the set keeps the spec's only axis as its single property, State=default. The matrix caption reads 'State=default'.
- How the single-variant set was made: Penpot's createVariantFromComponents rejects a single main, so the component was turned into a variant with LibraryComponent.transformInVariant(). That always adds a duplicate variant (Property 1 = Value 1 / Value 2), so the duplicate's main (component 17279edf-22b9-80e9-8008-d174794db2b8) was deleted, the property renamed to State and the value set to default. The library lists one CMP-030 entry with one variant and no variant error. Penpot may still keep the deleted duplicate in its restorable deleted-components list.
- The variant container keeps Penpot's built-in variant-set chrome: a 2 px inner stroke #bb97d8 and a 20 px corner radius, with no token. CMP-018, CMP-014, CMP-012 and CMP-020 have the same chrome. It has no fill.
- Geometry constants with no token: the component root is drawn 240 px wide, as the spec says (instances fill). The description, variant container, matrix row, fill-demo row and the caption texts are fixed at 960 px wide, a layout constant. The fill-demo instances are 120 px and 400 px wide (illustrative sample sizes). The rule's 1 px height comes from the composed CMP-018 main and is not set here.
- Instance overrides, as the anatomy requires: the CMP-020 text/caption label's fill is overridden from CMP-020's color.text.primary to color.text.secondary, and its text to 'Take profit' ('Stop loss' in the 400 px demo). type.ui.caption is bound explicitly on the main's label text. That binding was first lost when it raced with the fill binding in the same call. A separate call re-applied it, and an audit confirmed the main and all three instances carry type.ui.caption plus color.text.secondary.
- Extras beyond the standard section items, in this order after the matrix: a 'fill-demo' row (two instances at 120 px and 400 px showing that the rule shrinks or fills while the label never truncates), then keyboard, a11y, and three more caption texts: 'notes' (states not drawn, anatomy, density, contrast), 'tokens' (tokenMap plus both catalogue_updates lines) and 'open-questions'.
- The description is description_verbatim exactly, markdown markers included. CMP-012, CMP-004, CMP-036 and CMP-037 do the same; CMP-014 and CMP-020 stripped the markers.
- No focus-visible, disabled, disabled-with-reason, loading or error state is drawn, so there is no reason row or CMP-016 Tooltip. Divider-Label is static and non-interactive, and the spec lists only State=default. There are no icons and no focus ring.

**Open questions for the owner:**

- Section semantics: in ARIA a separator's children are presentational, so a label inside it disappears from browse mode. This spec keeps the label as a visible sibling that names the separator via aria-labelledby. Screen-reader users still cannot jump between sections by heading. For order-ticket and rule-group sections, consider a heading (h3) or fieldset/legend as the semantic carrier, with the rule decorative. Owner/accessibility decision.
- Layout: leading caption plus trailing rule, not a centred caption. Confirm.
- Build: Penpot needs at least one variant property, so CMP-030 ships as a one-variant set with State=default. The alternative is a plain, non-variant component. Confirm which the atom library wants for single-draw components; CMP-038 is the other one.
- Carried from CMP-018: the rule's color.border.subtle measures 1.24:1 on color.surface.canvas and 1.31:1 on color.surface.app in dark, so it is barely visible at 1x. The label carries the meaning (9.33:1 and 9.85:1). This rides on CMP-018's light-overlay question.

### CMP-032 · Confidence Dots

**Catalogue (verbatim):**

- **Props**: `level: "low"|"medium"|"high"` · `label?`.
- **A11y**: never colour-only — filled-dot-count + text label always paired. The dots are a supplement to a numeric confidence value the consumer renders adjacent (or passes as `label`), never its replacement; the word low / medium / high is always present in the text (E25-D05 §9).

| Axis  | Values            | Default |
| ----- | ----------------- | ------- |
| State | default           | default |
| Level | low, medium, high | low     |

**Drawn:** 3 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d199080bddec`.

_Board `CMP-032 · Confidence Dots — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it and exports `img/CMP-032-rating-confidence-dots.png` here._

**Keyboard** (None. This is static text plus a decorative graphic, not the APG radio or slider 'rating' input.):

| Keys | Action                                                     |
| ---- | ---------------------------------------------------------- |
| none | Not focusable; no keyboard interaction (static indicator). |

**Accessible name and role:**

| Element   | Role                   | Name                                                                                                              | ARIA                          |
| --------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| container | none (generic)         | none                                                                                                              | none                          |
| dots      | none                   | none                                                                                                              | aria-hidden="true"            |
| label     | none (plain text node) | the visible text, e.g. "Low confidence". Inside CMP-227 this composes as "Estimated, low confidence" (E08-D04 §4) | plain text, not a live region |

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue                        | Shipped                                                                                                                                  | Note                                                                                                                |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `color.status.*`                 | color.status.info.default (filled dots)                                                                                                  | One tone (the estimated/heuristic family, as in CMP-227). The level is carried by the filled-dot count and the text |
| (empty dot: not in the entry)    | color.text.tertiary (1 px inside stroke)                                                                                                 |                                                                                                                     |
| (label: not in the entry)        | type.ui.caption + color.text.secondary                                                                                                   |                                                                                                                     |
| (dot geometry: not in the entry) | space.inset.xs padding on an empty board (8 px dot), radius.badge, gaps space.inset.xs (between dots) and space.inset.sm (dots to label) |                                                                                                                     |

**Hit target:** Not applicable: the indicator is not interactive.  
**Motion:** None. A level change is a single instant flip.

**Resize & overflow:** The label follows the text scale and never truncates (it names the level); in a narrow container it wraps and the dots stay aligned to its first line. The dots are fixed (8 px from space.inset.xs padding) and do not scale with text.

**Forced colors:** A filled dot sets `forced-color-adjust: none` with a CanvasText fill, because a background fill would be repainted as Canvas; an empty dot keeps its 1 px ring, which forced colours paint CanvasText, so filled versus empty survives; the label renders in CanvasText and names the level anyway.

**Deviations recorded by the build:**

- The spec's stop condition was hit for dot sizing. The spec says: if Penpot does not size an empty hug board from its padding, stop and report rather than hardcode. A probe confirmed it: an empty flex board, hug on both axes, with padding space.inset.xs on all sides and radius.badge, stayed 100x100 after a relayout (the probe was then deleted). 8 px is not hardcoded. Each dot board (hug, padding space.inset.xs on all four sides, radius.badge) holds one paint-less 0.01x0.01 rectangle named 'spacer', the same technique as CMP-012's dot and CMP-023's bar. So each dot hugs to 8.01x8.01 and its size still comes from the token, and the dots row is 32.03x8.01 instead of the spec's 32x8. This needs owner acceptance (open question 6).
- State is not a variant property. Its only value is 'default' and it does not vary in the draw list, so the variant set's only property is Level (low / medium / high). Matrix captions read 'Level=low', 'Level=medium' and 'Level=high'. CMP-012, CMP-013, CMP-014 and CMP-025 do the same.
- Values with no token: the empty dot's 1 px inside stroke width (left unbound, per the spec's raw-values register in CMP-011), the 0.01 px spacer, the 960 px width of the description, keyboard, a11y, notes and open-questions texts, of the matrix and of the variant container, and the 314 px matrix cell width.
- The variant container keeps the chrome Penpot adds to every variant container: radius 20 and a 2 px inner #bb97d8 stroke. Neither is token-bound. CMP-033, CMP-012 and the other sets on the page have the same chrome. Its gaps (space.inset.lg) and padding (space.inset.md) are bound.
- Extra documentation beyond the standard section items. Each matrix cell has a second 'note' text (type.ui.caption, color.text.secondary), e.g. '1 of 3 dots filled; "Low confidence"'. After a11y, the section adds a 'notes' text and an 'open-questions' text (type.ui.caption, color.text.secondary, 960 px auto-height). These cover anatomy, level rules, the dot-size finding, the token map, hit target, motion, the states drawn and raw values. CMP-033 and CMP-023 do the same.
- The description keeps the literal markdown markers (** and backticks) from description_verbatim, as CMP-033 and CMP-037 do.
- No focus-visible, disabled, disabled-with-reason, loading or error state is drawn. The indicator is static and not interactive, and the spec lists only State=default. So there is no reason row and no CMP-016 Tooltip instance, although CMP-016 does exist in the library.

**Open questions for the owner:**

- Tone: should the level also map to a tone (low = warning, medium = info, high = success)? This spec uses a single info tone so that colour carries no meaning and the count plus the text do. Confirm.
- Dot geometry uses the empty-board padding technique (2 × space.inset.xs = 8 px) because there is no 8 px sizing token. Confirm, or add a semantic dot-size token. The density themes re-point only the two heights (slice 1 §4), so the dots stay 8 px in both modes.
- Raw values: the empty dot's 1 px ring is unbound (raw-values register in CMP-011).
- The default label is "{Level} confidence" ("Low confidence", "Medium confidence", "High confidence"); a `label` override must still name the level (to be enforced by lint or a test). Confirm.
- Penpot name: 'Rating/Confidence Dots' is named 'CMP-032 · Confidence Dots' because Penpot reads '/' as an asset path.
- Build finding: accept the paint-less 0.01 x 0.01 spacer in each dot? It renders 8.01 px, still sized by space.inset.xs, with nothing hardcoded, matching CMP-012's dot and CMP-023's bar. The alternatives are a raw 8 px fixed size or a new semantic dot-size token. The spec's 'stop and report' condition is recorded under deviations.

### CMP-033 · CopyButton

**Catalogue (verbatim):**

- **Props**: `value: string` · `label` (a11y name) · `onCopied?`.
- **A11y**: `aria-label`, announces "Copied" via a transient polite live region on success.

| Axis  | Values                                   | Default |
| ----- | ---------------------------------------- | ------- |
| State | default, copied, focus-visible, disabled | default |

**Drawn:** 4 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d1946e70bab8`.

_Board `CMP-033 · CopyButton — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it and exports `img/CMP-033-copybutton.png` here._

**Keyboard** (Button (WAI-ARIA APG Button pattern) + status message (polite live region, WCAG 4.1.3)):

| Keys                | Action                                                                                                                                                                                                                                                                  |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab     | Moves focus to / from the button; keyboard focus shows the CMP-002 ring. Disabled: skipped.                                                                                                                                                                             |
| Enter / Space       | Copies `value` to the clipboard, switches to State=copied and announces "Copied" (polite); focus stays on the button. Pressing again while copied copies again and re-announces. Key repeat (`event.repeat`, a held Enter) is ignored: one announcement per activation. |
| (no key; after 2 s) | Reverts to State=default silently (no announcement).                                                                                                                                                                                                                    |

**Accessible name and role:**

| Element     | Role                                     | Name                                                                          | ARIA                                                                                                                                                                                                     |
| ----------- | ---------------------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| button      | button (native `<button type="button">`) | aria-label from `label` (e.g. "Copy order ID"); unchanged in the copied state | disabled attribute when disabled                                                                                                                                                                         |
| icon        | none (decorative)                        | —                                                                             | aria-hidden="true"                                                                                                                                                                                       |
| live-region | status                                   | —                                                                             | role="status" (implicit aria-live="polite"), visually hidden, present before the first copy; receives "Copied" on success and is cleared on revert; never contains the copied value (it may be a secret) |

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue                 | Shipped                                                                                                              | Note                                                                                                                                                                                                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| color.action.ghost        | CMP-002 IconButton Variant=ghost: no fill, color.text.secondary icon; hover color.surface.hover + color.text.primary | No color.action.ghost token exists; the nested IconButton carries the ghost tokens.                                                                                                                                                          |
| (not listed) copied state | color.status.success.default                                                                                         | check glyph; at least 3:1 non-text on all seven surface tokens in all three themes (lowest: 3.84:1 on light color.surface.sunken and color.surface.selected). color.status.success.strong was rejected (2.78:1 on those two light surfaces). |

**Hit target:** 24 x 24 px compact, 32 x 32 px comfortable (CMP-002 md square, size.control.height). No exception.  
**Motion:** None. motion-safe: default → copied → default are instant glyph swaps (the 2 s revert is a timed state change, not motion); motion-reduce: identical.

**Resize & overflow:** Never grows: the nested CMP-002 md box stays size.control.height square at every text scale; the copied state swaps the glyph in place, so nothing reflows; "Copied" exists only in the live region.

**Forced colors:** As CMP-002 ghost: a ButtonFace box with a 1 px ButtonText border and a ButtonText glyph; copied: the check glyph in ButtonText (the success colour is lost; the glyph shape and the "Copied" announcement carry it); hover: border Highlight; focus: a Highlight outline; disabled: GrayText.

**Deviations recorded by the build:**

- Empty live region: in State=default, focus-visible and disabled the live-region text holds a single space, not an empty string. Penpot text cannot be empty: createText("") returns null and setting characters to "" throws. A U+200B zero-width space was tried first, but it stayed unmeasured at 1x1, so it was replaced with a space, which measures 4x19. In all four variants the layer is hidden, set absolute at parent (0, 28) and bound to type.ui.body and color.text.primary. State=copied holds "Copied" (44x19).
- Disabled: the dimming comes from the nested CMP-002 instance at State=disabled, as the spec rule says ('IconButton State=disabled (opacity.disabled)'). That nested root has opacity.disabled bound and resolves to 0.45. The CopyButton root itself binds no opacity, which differs from the generic state rule of conventions §3 (the whole component at opacity.disabled). A second binding would dim the button twice (0.45 x 0.45).
- Focus-visible: the ring is the nested CMP-002 focus-visible ring layer, not a direct child of the CopyButton root. It is an absolute rect at -2,-2, 28x28, with no fill and an outer stroke bound to color.focus.ring and border.focus. Its radius is a raw 6 px (radius.control 4 + 2), inherited from CMP-002. The CopyButton roots and the variant container have clipContent = false.
- Icon: the nested IconButton's icon layer (icon/more-horizontal) was swapped with swapComponent to icon/copy, or to icon/check for State=copied. These are instance overrides; nothing was detached. The swapped layer is renamed 'icon', resized to 16 and re-bound to size.icon for width and height. Its strokes are re-bound to color.text.secondary, or to color.status.success.default when copied. The icon/{name} boards have no flex layout and keep the icon set's 1.5 px glyph strokes, as in CMP-002. CMP-002's hidden 'locked' layer stays hidden in every variant.
- Geometry constants with no token: the 960 px widths of the variant container, matrix, description, keyboard, a11y, notes and open-questions texts; the 234 px matrix cells (4 x 234 + 3 x 8 = 960); the live-region offset (0, 28); the inherited ring geometry above; the 1.5 px glyph strokes. The root has no padding and no gap per the spec, so there is nothing to bind there.
- The variant container keeps Penpot's default variant-set outline: a 2 px #bb97d8 stroke and radius 20, neither token-bound, the same as every other set on the page. Its fill is empty: the pixel check shows the canvas #11151A through it.
- The description is description_verbatim character for character, including the ** and backtick markdown, as in CMP-016, CMP-031 and CMP-039. In the a11y text, a name cell of '—' is shown as '(no name)', as CMP-002 does.
- Doc content beyond the standard section items, all token-bound: each matrix cell has a 'note' text (type.ui.caption, color.text.secondary) under its 'State=…' caption, giving the glyph, its colour token and the live-region content or the inherited state. 'notes' and 'open-questions' texts follow the a11y text. The notes cover anatomy, tokens, the token map, hit target, motion, and why there is no reason row. Inter renders '->' in the token-map line as an arrow ligature.
- No reason row and no CMP-016 Tooltip: the spec draws no disabled-with-reason state (open question 6). There is no loading or error state either, so no CMP-014 Spinner is used.

**Open questions for the owner:**

- The copied revert interval is not catalogued; proposed 2 s, no announcement on revert.
- Copy failure (clipboard permission denied) is not catalogued and not drawn; add a later state (error glyph + "Copy failed" announcement)?
- The copied state shows only the check glyph in the success colour; there is no visible "Copied" text for sighted users. E09-D04 asks not to rely on a tooltip alone. Is the glyph change enough?
- Wording: the catalogue announces "Copied"; E09-D04 announces "Copied to clipboard". Which one?
- Security: the live-region text and any analytics never contain the copied value (it may be an API secret or a recovery code); flag for E05-X02.
- State=disabled-with-reason is deliberately not drawn: no catalogued CopyButton use is RBAC- or env-gated, because copying is a read-only, client-side action on a value the user can already see, so the 14-screens §0.5 rule 5 / brief §12 'disabled with a reason' requirement (controls the user may not use) does not arise; the conventions §2 matrix rule draws no state the catalogue does not list. Plain disabled covers 'no value to copy yet'. If a gated use appears, it is one draw: nested CMP-002 in its T2 form (E09-D09 §2.2) plus `disabled?/disabledReason?` on the Props line. Confirm.
- Build: is it acceptable that the CopyButton root binds no opacity in State=disabled, so the dimming comes only from the nested CMP-002 opacity.disabled? The generic conventions §3 rule puts it on the root; doing both would dim twice.
- Build: is a hidden single-space text an acceptable stand-in for the empty live region, given that Penpot cannot hold an empty text?

### CMP-037 · SwatchLegendItem

**Catalogue (verbatim):**

- **Props**: `color` · `label` · `value?`.
- **A11y**: grouped under parent legend's `role="group"` with `aria-label`.

| Axis     | Values      | Default |
| -------- | ----------- | ------- |
| HasValue | true, false | true    |
| HasGlyph | false, true | false   |

**Drawn:** 3 variant(s) per the matrix rule; Penpot variant set `17279edf-22b9-80e9-8008-d1677c770364`.

_Board `CMP-037 · SwatchLegendItem — doc` PENDING (text-first merge, 2026-10-23): the boards PR redraws it and exports `img/CMP-037-swatchlegenditem.png` here._

**Keyboard** (None. A static list (ul/li) inside an ARIA `group` named by the parent legend; no APG widget pattern.):

| Keys            | Action                                                                                                                                                                                                                               |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Tab / Shift+Tab | Skipped. The item is informational and not focusable. If click-to-filter-by-stop is ever added it becomes a control, which needs a catalogue change first (brief §3, the E05-D07 amendment: 24 px compact / 32 px comfortable rows). |

**Accessible name and role:**

| Element                                                      | Role          | Name                                                                | ARIA                                                                    |
| ------------------------------------------------------------ | ------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Parent legend (CMP-113 HeatmapLegend, ColorConventionLegend) | group         | its aria-label, e.g. 'Footprint colour legend'                      | wraps a ul (shipped ColorConventionLegend)                              |
| SwatchLegendItem                                             | listitem (li) | its visible text, e.g. 'Bid liquidity 1.2M' (the glyph is excluded) | none                                                                    |
| swatch                                                       | none (hidden) | not exposed                                                         | aria-hidden="true". The label states the meaning; colour reinforces it. |
| glyph                                                        | none (hidden) | not exposed                                                         | aria-hidden="true". The label text already states the side.             |
| value                                                        | none (text)   | the value; an abbreviated value exposes its expanded reading        | per CMP-020 NumericText                                                 |

**Token mapping** (catalogue name → shipped semantic token):

| Catalogue                                         | Shipped                                                                                                                                                                                                           | Note                                                                                                                       |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `color.*` (context-dependent)                     | swatch fill = the keyed data token (`color.heatmap.*`, `color.cvd.*`, color.buy.default, color.sell.default, `color.candle.*`); outline color.border.strong; label color.text.secondary; value color.text.primary | The Penpot master uses color.heatmap.bid.3, and instances override the fill.                                               |
| shipped code: 12x12 px swatch, gap var(--space-2) | size.icon / space.inset.sm                                                                                                                                                                                        | The code uses a raw 12 px swatch and the primitive space.2. The design binds the semantic equivalents (see open question). |
| (label and value type: not in the entry)          | type.ui.caption (label), type.num.sm (value, a CMP-020 NumericText instance)                                                                                                                                      |                                                                                                                            |

**Hit target:** n/a. This is an informational legend row. If click-to-filter is ever added, the row is the target at size.row.height (brief §3, the E05-D07 amendment: 24 px compact / 32 px comfortable rows).\
**Motion:** None. The item is static.

**Resize & overflow:** The row height (size.row.height) is a minimum; the label fills the width and wraps, with the swatch, glyph and value aligned to its first line; the value never wraps (CMP-020 NumericText, right-aligned); the size.icon swatch does not scale with text.

**Forced colors:** The swatch keeps its real colour (`forced-color-adjust: none` on the swatch only: the key must match the WebGL chart, which forced colours do not repaint), and its 1 px outline is set to CanvasText, as CMP-031's border; glyph, label and value render in CanvasText.

**Deviations recorded by the build:**

- Row height: the anatomy asks for hug height with a size.row.height min-height. Penpot applies min-height only to children set to fill, so each variant root has a fixed height bound to size.row.height (resized to the resolved 24 px first) and also binds layoutItemMinH to size.row.height. CMP-036 does the same. In Penpot a label that wraps to two lines would be clipped; in code the min-height lets the row grow.
- Binding a sizing token does not resize the shape in this Penpot build. So the swatches were resized to size.icon's resolved 16 px and the roots to size.row.height's resolved 24 px before binding, as CMP-012 did.
- Values with no token: the 200 px variant width (from the spec); the 1 px inner swatch stroke (strokeWidth left unbound, since there is no border-width semantic token) and the swatch's radius 0; the 960 px width of the description, variant container, matrix, overrides row and doc texts; and the 288 px override captions.
- The variant container keeps Penpot's own 2 px inner variant-set stroke (#bb97d8). It is not token-bound and is the only unbound fill or stroke in the section. CMP-004, CMP-012, CMP-014, CMP-018 and CMP-020 have the same stroke.
- 'Hidden' parts are left out rather than set invisible, as in CMP-012: the HasValue=false variant has no value layer and the HasGlyph=false variants have no glyph layer.
- The description is description_verbatim exactly, markdown markers included, as in CMP-036. In the keyboard and a11y texts the backticks are removed (the APG line reads 'ARIA group').
- Extra content beyond the standard section items. (a) An 'overrides' row, which the spec's swatch-colour rule asks the doc frame to show. It has three instances with token-bound swatch fill overrides: color.heatmap.ask.3 'Ask liquidity' 0.8M; color.heatmap.zero 'Zero intensity' with no value, where the outline keeps the box visible; and color.sell.default with glyph '▼' 'Sell volume' 0.9M. (b) 'notes' and 'open-questions' caption texts. The sample labels and the 0.8M and 0.9M values are illustrative; the spec names only 'Bid liquidity' and '1.2M'. Override captions use color.text.tertiary, like the matrix captions.
- The relayout skipped shapes inside component copies, so no sizing overrides are recorded on instances (the issue CMP-012 hit).

**Open questions for the owner:**

- Shipped SwatchLegendItem (packages/ui/src/components/SwatchLegendItem.tsx) has a `glyph?: string` prop (the non-colour channel used by ColorConventionLegend) that the catalogue lacks. This spec draws it (HasGlyph), makes it required whenever the swatch encodes direction (buy/sell, up/down), and the catalogue Props line adds both. Confirm.
- Swatch size: the shipped code draws a raw 12x12 px swatch; the design binds size.icon (16 px, the row's icon slot). Confirm 16 px. Keeping 12 px would bind the primitive size.icon.sm, which needs a recorded exception.
- Swatch outline contrast: color.border.strong against canvas is 1.91:1 (dark/hc) and 1.57:1 (light). That is enough to make the zero-intensity box visible but below 3:1. The label text carries the meaning, so this is recorded for the accessibility pre-review rather than treated as a defect.
- Build: the shipped ColorConventionLegend uses glyph WITHOUT value ('Red = sell / ask / down' + '▼'). That is HasValue=false + HasGlyph=true, which is not in the spec's draw list. Should the spec add that draw entry (and Storybook story)? Until then the sell example in the overrides row uses the HasValue=true + HasGlyph=true variant with a sample value.
- Build: is it acceptable to fix the row height at size.row.height in Penpot (with layoutItemMinH also bound) instead of hug plus min-height? The same question applies to CMP-036.

## 7. Design QA checklist (brief §12)

Completed for the 12 components of this slice. Open items say why and who closes them.

**Tokens & visual**

- [ ] Uses only published Tier-2/Tier-3 tokens — zero hardcoded hex/px values. **Open:** every colour, spacing,
      size, radius, type and opacity value is bound to a published semantic token, and no component holds a hex
      value; the raw values left are the geometry constants in §4.1 and the items in §4.2, recorded rather than
      hidden. Ticked when the owner accepts them (slice 1 B1, §5 E4 and E5) or tokens replace them.
- [ ] Verified in all three themes at both density modes. **Open:** structurally guaranteed (every paint is a
      semantic token that all three themes resolve, heights bind the two density-owned tokens, auto-layout
      everywhere), and the contrast figures cover all three themes, but the boards are PENDING (the boards PR, §6)
      and the mode-switch walk-through (§2 step 1) is not recorded yet.
- [ ] Passes the automated contrast-matrix check for every colour pair it introduces or touches. **Open:** 14
      `colorBySign` text pairs fail 4.5:1 (§5 E1). The non-text pairs below 3:1 that
      `E05-D02-data-display-a11y-audit.md` §4 lists are not relied on for meaning (dividers, the legend swatch
      outline, dots off their specified surfaces). No pair in this slice is one of the label-on-fill pairs #3925
      retuned (slice 1 A1).
- [ ] CVD simulation reviewed for any new colour-carrying state. **Open:** the audit §5 records dE76 spot checks made
      with `docs/research/_tools/cvd_simulate.py` (heatmap bid and ask swatches 4.8–5.0 apart under deuteranopia,
      §5 E26); the formal CVD review is E05-D04's. Structurally no slice-2 state depends on hue alone.

**Behaviour & states**

- [x] Every documented State has a corresponding Penpot variant (and Storybook story). All 82 variants of the matrix
      rule are drawn, including the universal focus-visible and disabled states of the three interactive components
      (the conventions §2 hover cells of CMP-011's remove button and CMP-033 come with the boards PR, §5 E18);
      the Storybook stories are E05-S01/S02's.
- [ ] Disabled states use the disabled-with-reason pattern (CMP-079), never a bare disabled control. **Open:** the boards PR, T2. CMP-021's as-built
      gated link (dimmed, with a CMP-016 Tooltip) is held for §5 E27; gated chip removal goes through CMP-079 on the nested
      IconButton (§5 E10); copying is never gated (§5 E21); the nine other components are not interactive.
- [x] Loading/empty/error states are explicitly designed. No entry in this slice lists a loading, empty or error
      state; the missing copy-failure state is proposed in §5 E20.

**Accessibility**

- [ ] Keyboard-interaction table completed and matches an implemented, tested keyboard path. **Tables complete** for
      all 12 (APG pattern named, or "not focusable" with the reason). **Open** for "implemented, tested", which is
      E05-S01/S02's Definition of Done.
- [x] Accessible-name/role table completed: all 12 (§6; summary in the audit §2).
- [x] Canvas/WebGL-adjacent strategy specified: CMP-024 is `role="img"` with a trend summary, and its data is in the
      parent row's DOM-mirror table (05 §6.1); CMP-037's items are a list in a named group, and the label states what
      each swatch keys.
- [x] Motion-safe/motion-reduce pair specified for any animated property: no component in this slice animates; every
      change is instant in both modes (CMP-024 states the pair a future draw-in must ship, and CMP-020's price flash
      belongs to the consuming cell).
- [x] Hit targets meet the minimum or log an essential exception: the remove button, the estimated chip and the
      CopyButton are at least 24 × 24 px compact and 32 px comfortable; CMP-021 uses the WCAG 2.5.8 inline exception
      in a sentence and 24 px spacing or a 24 px row when standalone (its logged target note). 32 px is the
      comfortable value E05-D07 validated (brief §3), which supersedes this item's older "40-44px".
- [ ] Accessibility role has signed off (§13). **Open:** this PR carries the pre-review
      (`E05-D02-data-display-a11y-audit.md`); the formal sign-off is E05-D04's.

**Trading-specific safety**

- [x] Any component touching order placement, position modification or rule arming states its confirm-gate variant:
      not applicable, no component in this slice places, changes or arms anything.
- [ ] Any heuristic/estimated value is chip-tagged and links to its methodology InfoPanel. **Open:** the estimated
      chip is drawn (CMP-011) and CMP-032 shows the confidence beside it, but the link to CMP-069 waits for §5 E19
      (CMP-227 owns it).
- [x] Demo/Live context is unambiguous wherever a trading action can fire: not applicable at atom level; these atoms
      carry no environment state.

**Consistency**

- [x] Reuses an existing CMP-* rather than a near-duplicate: no new ID. CMP-030 composes CMP-018 and CMP-020, CMP-037
      composes CMP-020, CMP-011 and CMP-033 compose CMP-002, and CMP-025 composes CMP-013.
- [ ] Storybook stories match the full Variants × States matrix. **Not applicable to this design PR:** the stories are
      E05-S01/S02's, and the Penpot matrices are the enumeration they copy.
- [ ] Composes only published-library components. **Open:** as built on 2026-10-20, the nested CMP-002, CMP-013,
      CMP-016, CMP-018, CMP-020 and `icon/{name}` copies are instances with overrides and nothing is detached; the
      page is not re-verified at this head, so the boards PR verifies it on the redrawn page (audit scope).

## 8. Approval

The owner approves by merging this spec PR and/or commenting `approved` on #161 (C-10.1; the coordinator reviews
under the owner's delegation). This text merges first with the boards PENDING; the boards PR completes slice 2 (§6)
and delivers the brief §11.4 hand-off checklist, `docs/design/E05/E05-D02-handoff.md` (brief §13.3 item 8).
Engineering stories E05-S01..S04 move to Ready only after every slice is approved. The
accessibility pre-review is `E05-D02-data-display-a11y-audit.md`; the formal accessibility and CVD sign-off is
E05-D04's.
