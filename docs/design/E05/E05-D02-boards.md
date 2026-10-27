# E05-D02 — specimen boards (as built)

**Ticket:** E05-D02 (#161) · **Epic:** E05 Design system v0 · **Status:** In Review — the boards PR (design PR: the
owner approves under C-10.1; the coordinator reviews). It completes the five text slices: slice 1
[`E05-D02.md`](E05-D02.md), slice 2 [`E05-D02-data-display.md`](E05-D02-data-display.md), slice 3
[`E05-D02-form-controls.md`](E05-D02-form-controls.md), slice 4
[`E05-D02-feedback-overlays.md`](E05-D02-feedback-overlays.md) and slice 5 (`E05-D02-rest.md`, #4719).

## 1. The ruling

The coordinator's ruling of 2026-10-27 on #161: the shared DS file no longer loads, so #161 is drawn as **ten
specimen boards** (the cap of ten drawn boards per design ticket, light twins at most a third) in the **per-set file
`E05-D02 boards`**, **one page per slice** (slices 1–4; slice 5 adds no board and folds into board 09, §4). Each board
is a specimen sheet: per component one titled block of the variants, sizes and states its slice names, each block
captioned with its CMP id, spec lines and tokens, and one annotation column (sources, PROPOSED / RULED stamps, what is
not drawn). Every variant, size or state a board does not show is **not drawn — the text is binding**: the slice
docs stay the specification, and the boards are specimens of it.

No library component and no `inst` node is used: every component is composed from board, rect, text and ellipse
shapes with token binds. The only icons are the file's local `icon / locked`, `arrow-up`, `arrow-down`, `close` and
`drag-handle`; every other glyph is a text glyph. Boards 01–09 are drawn and exported in the dark theme. Board 10 is
the only light board: drawn dark, then exported after the file-wide switch to light and the wait for its token binds to
resolve.

## 2. Pages

| Page                                    | Page id                                | Boards     |
| --------------------------------------- | -------------------------------------- | ---------- |
| `E05-D02 slice 1 actions and selection` | `2a1599b6-22f9-808a-8008-da8a85fa16d8` | 01, 02     |
| `E05-D02 slice 2 data display and text` | `2a1599b6-22f9-808a-8008-da8d726f1db4` | 03, 04     |
| `E05-D02 slice 3 form controls`         | `7761b3e4-893d-806e-8008-da8ece40d3a5` | 05, 06, 07 |
| `E05-D02 slice 4 feedback and overlays` | `006e12a1-d0c6-803c-8008-da92b1e868e0` | 08, 09, 10 |

## 3. The boards

Each export is the board at 1x. "States drawn" is the sheet's content check; "Not drawn" sums its annotation column
(the full list, per CMP and with its spec line, is the sheet's `.md` under `docs/design/_tools/sheets/e05-d02/`).

### 01 actions

`E05-D02 / 01 actions` · slice 1 page · board id `2a1599b6-22f9-808a-8008-da8a86035933` · 4780 × 1481 · dark ·
[`img/E05-D02-01-actions.png`](img/E05-D02-01-actions.png)

- **Components:** CMP-001 Button, CMP-002 IconButton, CMP-003 SegmentedControl, CMP-004 Toggle.
- **States drawn:** every CMP-001 variant × the seven states at md, sm / lg at default, buy / sell arrows in every
  cell; CMP-002 four variants × five states, sizes, Pressed=true (gated pressed keeps its outline); CMP-003 text and
  icon-only × five states, size sm, two options; CMP-004 Checked=false × five states, Checked=true default / hover /
  focus / T2, Critical off / on, label left and hidden. T2 cells: the lock leads, label and lock
  `color.text.tertiary`, the reason in caption secondary.
- **Not drawn (17):** comfortable density; sm / lg × every non-default state; CMP-002 Pressed=true on primary / danger
  and its proposed name tooltip; CMP-003 six options (copy gap) and fullWidth; CMP-004 Checked=true × disabled and
  Critical × every non-default state; the CMP-044 confirm wrappers (board 09 draws CMP-044).
- **Live check:** met; lint 0 findings.

### 02 selection-and-primitives

`E05-D02 / 02 selection-and-primitives` · slice 1 page · board id `2a1599b6-22f9-808a-8008-da8c6ac3c60e` ·
4172 × 1196 · dark · [`img/E05-D02-02-selection-and-primitives.png`](img/E05-D02-02-selection-and-primitives.png)

- **Components:** CMP-005 Checkbox, CMP-006 RadioGroup, CMP-010 Slider, CMP-014 Spinner, CMP-019 Icon, CMP-031
  ColorSwatch, CMP-039 FocusRing (spec only).
- **States drawn:** CMP-005 Checked false / true / indeterminate × five states; CMP-006 vertical × five states and
  horizontal; CMP-010 Marks=false × five states and Marks=true; CMP-014 sm / md, standalone, cancellable load, order
  submit; CMP-019 sizes, the five local glyphs, decorative / meaningful; CMP-031 Selected × five states and the picker;
  CMP-039 its two reference frames.
- **Not drawn (20):** comfortable density; derivable state products; the CMP-006 option-level lock sample; the
  CMP-014 motion and surfaces row; **the CMP-019 47-glyph base set** (the per-set file holds five icons) and the
  proposed 16 / 20 / 24 optical scale; CMP-031 user palette, ThemeChip and StaticSwatch; the CMP-039 halo proposal
  (D11) and thick ring (A9).
- **Live check:** met; lint 0 findings.

### 03 tags-badges-avatars

`E05-D02 / 03 tags-badges-avatars` · slice 2 page · board id `2a1599b6-22f9-808a-8008-da8d72fe5b05` · 3153 × 1360 ·
dark · [`img/E05-D02-03-tags-badges-avatars.png`](img/E05-D02-03-tags-badges-avatars.png)

- **Components:** CMP-011 Tag, CMP-012 Badge, CMP-013 Avatar, CMP-025 Avatar Group, CMP-032 Confidence Dots, CMP-037
  SwatchLegendItem.
- **States drawn:** the slice's named cells; CMP-011's gated remove button in T2 2b (lock badge and CMP-016 echo, no
  disabled token); status chips and dots carry a glyph and a word; Badge numerals in `color.text.primary`.
- **Not drawn (16):** comfortable density; Removable on the non-neutral tones (E10); the estimated chip disabled
  (E19); multi-digit counts and the `99+` cap (E11, held); a lone dot; Avatar size lg and its palette story (E2); the
  Avatar Group ring on raised / hover (E23); a Confidence Dots label override; the third legend sample and a two-line
  legend label.
- **Live check:** met. **Open defect:** the lint reports 5 overlaps in the CMP-025 stack (28 px avatars in 16 px slots,
  as slice 2 specifies). They are intended and were left as lint noise (§5).

### 04 text-and-dividers

`E05-D02 / 04 text-and-dividers` · slice 2 page · board id `2a1599b6-22f9-808a-8008-da8df3e70ef7` · 3189 × 1210 ·
dark · [`img/E05-D02-04-text-and-dividers.png`](img/E05-D02-04-text-and-dividers.png)

- **Components:** CMP-018 Divider, CMP-020 Typography primitives, CMP-021 Link, CMP-024 Sparkline, CMP-030
  Divider-Label, CMP-033 CopyButton.
- **States drawn:** the slice's named cells; CMP-021 default / focus-visible / disabled × External; signed values
  carry their sign and the zero cell is unsigned in `color.neutral.default`.
- **Not drawn (15):** CMP-021 disabled-with-reason (**held until slice 2 §5 E27 is answered**), hover / active /
  visited (E18) and a wrapping inline link; the light Menu / Popover divider case; CMP-020 qty / pct / pnl formats,
  SignDisplay=never, the 160 px column demo and mono-text in every numeric style; the Sparkline size demo and y-range
  floor (E22); a narrow wrapped Divider-Label; CMP-033 disabled-with-reason (E21: never gated) and copy failure (E20).
- **Live check:** met; lint 0 findings.

### 05 text-inputs

`E05-D02 / 05 text-inputs` · slice 3 page · board id `7761b3e4-893d-806e-8008-da8ece47e3d7` · 3576 × 1510 · dark ·
[`img/E05-D02-05-text-inputs.png`](img/E05-D02-05-text-inputs.png)

- **Components:** CMP-007 TextInput, CMP-008 NumericStepperInput, CMP-034 MaskedValue, CMP-040 FormField, CMP-054
  SearchBox, CMP-065 FormSection.
- **States drawn:** every named cell once (CMP-007 9, CMP-008 9, CMP-034 4, CMP-040 8, CMP-054 5, CMP-065 6). T2:
  the lock first in the well, value `color.text.tertiary`, label `color.text.secondary`, the reason in caption
  secondary. Invalid: the 2 px `color.status.danger.default` boundary, the danger glyph and words.
- **Not drawn (17):** comfortable density (only the height changes, 32); every combination beyond the named cells;
  the states each section assigns to its child or host (active, loading, empty).
- **Live check:** met; lint 0 findings.

### 06 pickers-and-gates

`E05-D02 / 06 pickers-and-gates` · slice 3 page · board id `7761b3e4-893d-806e-8008-da8f7704637d` · 3396 × 1269 ·
dark · [`img/E05-D02-06-pickers-and-gates.png`](img/E05-D02-06-pickers-and-gates.png)

- **Components:** CMP-009 Select, CMP-047 DatePicker, CMP-048 Combobox, CMP-079 RbacGate.
- **States drawn:** every named cell once (CMP-009 9 and the CMP-231 validity sample, CMP-047 11, CMP-048 10,
  CMP-079 4); T2 lock first; status rows carry a glyph and words; loading is a spinner and words.
- **Not drawn (14):** comfortable density; every combination beyond the named cells; the states assigned to the
  wrapped control or host; CMP-047 range-open weeks 3–5; the RbacGate sentence form (that is CMP-026).
- **Live fixes:** 19 unmeasured texts after the first pass, fixed by re-running from the touch step (root height
  1239 → 1269), which also cleared the one outside-root finding; the CMP-047 T2 well widened 156 → 170 (content
  120 → 134) so the `UTC` affix no longer overflows. T2 lock first and its reason on one line: met. Lint 0 findings.

### 07 table

`E05-D02 / 07 table` · slice 3 page · board id `7761b3e4-893d-806e-8008-da913ca0c0aa` · 2200 × 932 · dark ·
[`img/E05-D02-07-table.png`](img/E05-D02-07-table.png)

- **Components:** CMP-049 Table.
- **States drawn:** the ten named cells (populated, loading, empty, filtered-empty, error, sorting, reflow, Mode=grid,
  Selection=multiple, the row menu with a T2 item) and the inline 2b IconButton; loading, empty and error are drawn
  as the ticket's Gherkin asks.
- **Not drawn (8):** invalid, disabled and read-only of the whole table; active; combinations beyond the ten cells;
  comfortable density; the live region (announced, never drawn); the hidden caption and forced colours.
- **Live check:** met; lint 0 findings.

### 08 feedback-states

`E05-D02 / 08 feedback-states` · slice 4 page · board id `006e12a1-d0c6-803c-8008-da92b1fbcc0a` · 4101 × 3450 ·
dark · [`img/E05-D02-08-feedback-states.png`](img/E05-D02-08-feedback-states.png)

- **Components:** CMP-015 Skeleton, CMP-023 ProgressBar, CMP-026 EmptyState, CMP-027 ErrorState, CMP-028 Callout,
  CMP-029 Skeleton-Chart placeholder, CMP-038 InlineSpinnerText, CMP-045 Toast, CMP-089 ForbiddenState, CMP-090
  NotFoundState, CMP-091 GlobalErrorBoundaryFallback.
- **States drawn:** each block's named cells; tone is a glyph and a word in every status cell; the CMP-045 T2 action
  is lock-led with one reason line (2a notice).
- **Not drawn (35):** per block, the interactive states it does not have, the states owned by another component,
  every combination beyond the named cells and comfortable density; the CMP-026 recording CTA (wording under review);
  the CMP-091 route h1, error id and repeated-crash sentences (E10-D03's strings).
- **Live check:** met; lint 0 findings.

### 09 overlays

`E05-D02 / 09 overlays` · slice 4 page · board id `006e12a1-d0c6-803c-8008-da93e7177891` · 5400 × 2764 · dark ·
[`img/E05-D02-09-overlays.png`](img/E05-D02-09-overlays.png)

- **Components:** CMP-016 Tooltip, CMP-017 Popover, CMP-041 Menu, CMP-043 Dialog, CMP-044 ConfirmDialog, CMP-046
  Drawer; slice 5's CMP-022 and CMP-035 as plain text (§4).
- **States drawn:** each block's named cells; modal cells over the scrim stand-in; floating surfaces on conventions
  30's tokens; menu items are flex rows, the T2 item lock-led with its reason line; the CMP-044 gated Confirm in T2 2a.
- **Not drawn (23):** closed states; the states owned by the trigger or the content; every combination beyond the
  named cells and comfortable density; the CMP-041 scale-mode radio group; the host-owned titles and rows of CMP-043,
  CMP-044 and CMP-046.
- **Live check:** met; lint 0 findings.

### 10 light-composite

`E05-D02 / 10 light-composite` · slice 4 page · board id `a3e246e9-1c1d-806b-8008-da96192f91e3` · 3833 × 1309 ·
**light** · [`img/E05-D02-10-light-composite.png`](img/E05-D02-10-light-composite.png)

- **Components:** the contrast-critical cells of every slice in light: CMP-001 Button (slice 1), CMP-012 Badge
  (slice 2), CMP-007 TextInput (slice 3), CMP-028 Callout, CMP-045 Toast and CMP-044 ConfirmDialog (slice 4).
- **States drawn:** status carried by a glyph and words; T2 cells lock-led in `color.text.tertiary` with the reason
  in `color.text.secondary`; focus-visible cells carry CMP-039's 2 px `color.focus.ring`.
- **Not drawn (10):** the non-critical variants and states in light (CMP-001 secondary / ghost, hover, active,
  disabled, loading, sizes; the CMP-012 dot on raised and other hosts, below 3:1 in light; CMP-007 hover, disabled,
  read-only, empty, both affixes; the other CMP-028, CMP-045 and CMP-044 cells, which board 08 or 09 draws in dark).
- **Live fix:** both scrim rects rebound to fill `palette.black` at `opacity.scrim` (0.6). Lint 0 findings.

## 4. Slice 5 folds

Slice 5 adds no board. Its two folds are drawn on board 09 as plain text, not as components: CMP-022 Kbd is the
`Del` key text in the CMP-041 menu's shortcut slot, and CMP-035 Countdown is the `Cancels in 0:20` text in the CMP-044
order confirm's footer. The board's tooltip cells hold no shortcut. Every other slice-5 section, the glyph set
included, is not drawn — the text is binding.

## 5. Open defects and sheet drift

- **03:** the lint's 5 overlaps in the CMP-025 stack are intended (§3). A later lint could skip a stack group. Open.
- **Sheet drift (06, 10):** the two live fixes above were made on the boards, not in the sheets. The committed sheets
  are the ones rendered, so a re-render from them needs the same two fixes: the CMP-047 T2 well at 170 (content 134)
  and the scrim fill `palette.black`. The optional widening of the 06 T2 reason text to 170 was not made.
- **Driver:** the first pass on 06 left texts unmeasured; a second pass from the touch step fixed it (timing, not
  the sheet).

## 6. Provenance

- Specs: the four slice docs as of `966f9edcd` (the kit pins each md5). Kit, generators, build notes and sheets:
  [`docs/design/_tools/sheets/e05-d02/`](../_tools/sheets/e05-d02/). Renderer cvsheet v4.3.
- Packed sheets as rendered (sha256, first 12 hex): 01 `8b415ae802c5`, 02 `c8b5de03e663`, 03 `842f96671eaf`, 04
  `3ca1e3b03056`, 05 `f8ceed15a3a9`, 06 `4ed927be4a4f`, 07 `f5e10aff4bdf`, 08 `8991e42723d5`, 09 `74a412d952cb`, 10
  `a2fa70ca99cc`. The committed copies differ only in `compactOf.file`, cut to the sheet's file name.
- The committed kit is the rendered kit after `black -l 100` and `ruff --fix`. Regenerating every sheet with it gives
  the same sheets and `.md` files, except for the kit md5 stamped in each sheet's sources note.

## 7. Review checklist

- [ ] Ten boards, no more; board 10 is the only light board (cap: light twins at most a third).
- [ ] Each PNG opens and matches its row: name, page, board id and size.
- [ ] Every CMP of slices 1–4 is on exactly one of boards 01–09; each slice section names its board or says
      "not drawn".
- [ ] T2 cells: lock first, `color.text.tertiary`, one reason line; no disabled token on a T2 path.
- [ ] Status never by colour alone: a glyph and a word in every status cell.
- [ ] Specimen strings come from the slice docs; nothing in a board contradicts its section.
- [ ] Board 10 in light: the focus ring, T2 and status cells are legible; the scrim is black at 0.6.
- [ ] The open items in §5 are accepted or ticketed.
