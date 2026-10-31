# E05-D05 — Design QA of the built component library against spec

**Ticket:** E05-D05 (#260) · blocked by E05-S04 · checklist: `docs/plan/16-design-system-brief.md` §12 (design QA
checklist, four groups) · specs: `E05-D02*.md` (component specs, slices 1–5), `E05-D03.md` (motion) and the catalogue
`docs/plan/15-component-catalogue.md`. Companion: the formal accessibility and CVD sign-off is E05-D04's; this review
overlaps it only where §12 asks the same question, and records the overlap informally.
**Status:** agent-run review of the built library. Drift findings are open items for the coordinator; the
CDO acknowledgement is **owner approval pending** (§9).

**Honest scope.**

- **Agent-run, not a human pass.** The rater is an agent. Nothing here is a designer's side-by-side judgement of the
  build against a board; "looks right" at a glance in light and high contrast is not claimed.
- **Audited tree:** `main` at `16d70feed92578bd0d5583688f5d71975d4b976d` (64 component sources, 69 story
  files, 62 component stylesheets, 4,614 VR baselines). CMP-062 ThemeSwitcher, CMP-063 DensityToggle and CMP-228
  PreviewTile are on `main` since #5221; the parts that live only in E05-S04 slice H (#5237: the RbacGate forms, the
  density menu, the matrix) were read from that slice and are not on `main`. Line references below are to this tree;
  re-check them at READY.
- **Penpot not compared.** §12 asks that every state has a Figma variant and that the component composes published
  library components only. No board was drawn for this review, so those two items are a **read of the spec documents**
  (`E05-D02*.md`, `E05-D02-boards.md`) against the build, not a canvas compare. They are marked `spec read` below.
- **Render evidence is the VR baselines.** The baselines were read as files and a few were opened as images; no
  computed-style probe or Storybook run was done for this review. Hit targets and spacing are therefore **read from the
  CSS and the token build**, not measured in a browser. Every measured claim is labelled `CSS read`.
- **Imported, not redone:** contrast ratios (`contrast:gate`, E05-T05), axe per story (E05-T03) and the keyboard,
  name and role tables (the `E05-D02*-a11y-audit.md` set). They are cited, not recomputed.
- **Not done here:** fixes, screen-reader passes (E05-Q02), a live motion review, forced-colours rendering on Windows,
  zoom at 200 %, and any change to the catalogue (§7 proposes rows; it edits nothing).

## 0. Method

1. **The v0 set** was pinned from the ticket lists, not from the story files: `docs/plan/backlog/E05.json`
   (`E05-S01`..`E05-S04`, checked against `gh issue view 264 265 266 267`) names CMP-001..010 (S01), CMP-011..039 (S02),
   CMP-040..050 with CMP-054, 059, 065 and 069 (S03), and CMP-062, 063, 079, 085, 089..091 and 228 (S04, which also
   touches 031, 037, 065 and 069). S02 and S03 list what they defer (CMP-227; CMP-051..053, 055..058, 060, 061, 064,
   066..068); those ids are not in the set. Result: **62 ids** (§2). Three more shipped components sit outside it as
   dependencies and are reviewed only for duplication: CMP-160 SymbolSearchInput, CMP-213 FuzzyList, CMP-219
   SymbolPicker (and `DateRangePicker`, which CMP-047 covers).
2. **Tokens named versus used.** For each catalogue entry the `Tokens` line was parsed, each dotted token mapped to its
   CSS custom property (`color.action.primary.default` to `--color-action-primary-default`), and compared with every
   `var(--…)` in that component's stylesheet. Every `var()` in `packages/ui/src/components/*.css` (196 distinct names)
   was also checked against the generated token build (`packages/ui/build/css/tokens.*.css`) and the local `--cv-*`
   properties. The catalogue `Tokens` lines are condensed (the specs carry the full list), so "used, not in the
   catalogue line" is **not** counted as drift; "named in the catalogue, absent from the build" is.
3. **Hard-coded values.** `grep` for hex, `rgb()`, `hsl()` and every `px` literal in the stylesheets, excluding comment
   lines and the documented `calc(var(--border-hairline) * 1px)` pattern.
4. **Variants and states versus stories.** The catalogue `Storybook` list of each entry was compared with the
   `export const` names in the component's `*.stories.tsx`. A renamed story with the same purpose counts as covered
   (listed in §4); a missing name with no equivalent is a gap.
5. **Render evidence.** `packages/ui/vr/baselines/<group>-<component>--<story>--<theme>--<density>.png`: 769 per cell in
   each of six cells (dark, light, high-contrast × compact, comfortable). The cross-component sheets are
   `atoms-all-atoms-matrix--<theme>-<density>--dark--compact.png` (36 files) and
   `molecules-all-molecules-matrix--*` (180 files).
6. **Cells.** The ticket asks for a result per theme × density cell. The stylesheets branch on theme or density in five
   places only (`controls.css`, `fuzzylist.css`, `symbolpicker.css`, `tabs.css`, `toast.css`), so for every other
   component the CSS is cell-independent and the six cells share one result; the cells that differ are named in §2.
   That is a CSS-structure argument, not a pixel comparison.

Result words: **Pass** (checked, nothing found); **Pass, note** (a finding below, not a failure of the item); **Gap**
(catalogue lists a variant or story the build lacks); **Fail** (an expected token or behaviour is not what the code
does); **Spec read** (Penpot leg, no canvas); **Imported** (cited from another review).

## 1. Summary

| §12 group          | Item                                                   | Result                                                                                                                    |
| ------------------ | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| Tokens & visual    | Only published Tier-2/3 tokens, zero hard-coded values | **Pass, note**: no hex; one token-tier finding (D-01), one literal offset (D-04)                                          |
| Tokens & visual    | All three themes at both densities                     | **Fail** on 3 components (D-02), **Pass, note** on 1 (D-03); other cells share one CSS result                             |
| Tokens & visual    | Contrast-matrix pairs                                  | **Imported** (E05-T05 gate, not re-run here)                                                                              |
| Tokens & visual    | CVD for colour-carrying states                         | **Imported** (E05-D04 owns it; no number here)                                                                            |
| Behaviour & states | Each state has a Figma variant and a story             | Figma **Spec read**; stories **Gap** on 15 components (§4)                                                                |
| Behaviour & states | Disabled-with-reason for gated actions                 | **Pass**: 16 gated controls carry the pattern and a story, 5 more under other story names; 2 shell controls exempt (§2.3) |
| Behaviour & states | Loading, empty, error designed, not greyed-out         | **Pass, note**: designed wherever they exist; listed stories missing on a few (§4)                                        |
| Accessibility      | Keyboard and name/role tables                          | **Imported**; no keyboard-named story on 5 interactive components (D-07)                                                  |
| Accessibility      | Canvas/WebGL-adjacent strategy                         | **n/a**: only Sparkline and SkeletonChart are chart-adjacent, both static                                                 |
| Accessibility      | Motion-safe / motion-reduce pair                       | **Pass**: all 12 animated stylesheets carry a reduce rule (§2.4)                                                          |
| Accessibility      | Hit targets 24 px compact / 40-44 px comfortable       | **Fail on the rule, not the build**: brief §12 says 40-44, build and spec say 32 (D-05)                                   |
| Accessibility      | Accessibility sign-off                                 | E05-D04's; not claimed                                                                                                    |
| Trading safety     | Confirm-gate variant, estimated chip, env context      | **Pass, note**: gate ladder stories missing (D-08); estimated chip is CMP-227, deferred                                   |
| Consistency        | Reuse, no near-duplicate                               | **Pass, note**: 6 pairs or sets reviewed, 2 consolidations proposed (§5)                                                  |
| Consistency        | Stories match the Variants × States list               | **Gap** on 15 components (§4)                                                                                             |
| Consistency        | Published-library Penpot components only               | **Spec read**                                                                                                             |

Findings: **8 drift findings** (0 serious, 3 moderate, 5 minor; §3), **15 components with story gaps** (§4), **6
near-duplicate pairs or sets** (§5), **11 proposed catalogue rows** (§7). No finding blocks a Definition of Done on its
own; D-02 and D-08 should be filed as Bugs (§8).

## 2. Component matrix

### 2.1 How to read it

Columns are the four §12 groups: **T** tokens & visual, **B** behaviour & states, **A** accessibility, **C**
consistency. `P` pass, `P*` pass with a finding, `G` gap, `F` fail. "6/6" would mean the six cells share one result
(§0 item 6); every row is 6/6 and has a baseline in each cell. Finding ids are §3 (`D-nn`); story gaps are §4. The A
column covers what the CSS shows (forced-colours block, reduce rule, target size) and what the story set shows
(keyboard-named story); the keyboard, name and role tables themselves are the D02 audits'.

### 2.2 Per-component results

Evidence for the whole table: `packages/ui/src/components/*.css` (token resolution, §3), `*.stories.tsx` (§4), and
`packages/ui/vr/baselines/*all-atoms-matrix*` / `*all-molecules-matrix*` for the six cells. A `P` in column A means the
stylesheet has a forced-colours block (60 of 62 stylesheets; the two without are `densitytoggle.css` and
`themeswitcher.css`, wrappers whose children carry theirs) and, where the component animates, a reduce rule.

| CMP | Component                   | T   | B   | A   | C   | Notes                                                                     |
| --- | --------------------------- | --- | --- | --- | --- | ------------------------------------------------------------------------- |
| 001 | Button                      | P   | P   | P   | P   | 16 stories vs 6 listed; height comes from `.cv-control` (`controls.css`)  |
| 002 | IconButton                  | P   | P   | P   | P   | CopyButton composes it (§5)                                               |
| 003 | SegmentedControl            | P   | P   | P   | P   | ThemeSwitcher composes it                                                 |
| 004 | Toggle                      | P   | P   | P   | P   | `WithLabel` is `LabelLeft`/`LabelHidden`                                  |
| 005 | Checkbox                    | P   | P   | P   | P   |                                                                           |
| 006 | RadioGroup                  | P   | P   | P   | P   |                                                                           |
| 007 | TextInput                   | P   | P   | P   | P   | `fields.css` is shared by 007, 008, 048, 054, 160                         |
| 008 | NumericStepperInput         | P   | G   | P   | P   | `Mixed` story missing                                                     |
| 009 | Select                      | F   | G   | P   | P*  | D-02 (light); `Searchable`, `WithSpecimen`, `Mixed` missing               |
| 010 | Slider                      | P   | G   | P   | P   | `Mixed` story missing                                                     |
| 011 | Tag / Chip                  | P   | G   | P   | P   | `EstimatedChip` missing (CMP-227 is deferred, so by design)               |
| 012 | Badge                       | P   | P   | P   | P   |                                                                           |
| 013 | Avatar                      | P   | G   | P   | P   | `ColorPalette` story missing                                              |
| 014 | Spinner                     | P   | G   | P   | P   | `Nested`, `SlowPath` missing                                              |
| 015 | Skeleton                    | P   | P   | P   | P   | `Count` is `LongCount`                                                    |
| 016 | Tooltip                     | P   | P   | P   | P   | `Echo` is `EchoName`, `EchoReason`                                        |
| 017 | Popover                     | P   | P   | P   | P   |                                                                           |
| 018 | Divider                     | P   | P   | P   | P   |                                                                           |
| 019 | Icon                        | P   | P   | P   | P   | `src/icons/`, `Icons.stories.tsx`; 156 baselines                          |
| 020 | Typography                  | P   | P   | P   | P   | `AbbreviatedWithAriaLabel` is `AbbreviatedWithExpandedReading`            |
| 021 | Link                        | P   | P   | P   | P   |                                                                           |
| 022 | Kbd                         | P   | P   | P   | P   | uses `--radius-xs`, present in the build                                  |
| 023 | ProgressBar                 | P   | G   | P   | P   | `Running`, `Failed`, `Unknown`, `InWizard` missing                        |
| 024 | Sparkline                   | P   | P   | P   | P   |                                                                           |
| 025 | AvatarGroup                 | P   | P   | P   | P   | overlap is derived from `size.icon`, no token (§7 row 5)                  |
| 026 | EmptyState                  | P   | P   | P   | P*  | Callout/ErrorState/InfoPanel overlap (§5)                                 |
| 027 | ErrorState                  | P   | P   | P   | P*  | `Error` in the catalogue line is `ErrorSeverityStory`                     |
| 028 | Callout                     | P   | G   | P   | P*  | `ChartStrip`, `BarRebuildProgress` missing (later epics compose them)     |
| 029 | SkeletonChart               | P   | P   | P   | P   | `SinglePane`/`MultiPane` are `Default`/`ThreePanes`                       |
| 030 | Divider-Label               | P   | P   | P   | P   | in `divider.css`; `Labelled` story                                        |
| 031 | ColorSwatch                 | P   | G   | P   | P   | `Mixed`, `Custom` missing                                                 |
| 032 | ConfidenceDots              | P   | P   | P   | P   |                                                                           |
| 033 | CopyButton                  | P   | P   | P   | P*  | §5                                                                        |
| 034 | MaskedValue                 | P   | P   | P   | P   |                                                                           |
| 035 | Countdown                   | P   | P   | P   | P   | digits inherit colour; catalogue `Tokens` line is stale (§7 row 3)        |
| 036 | KeyValueRow                 | P   | G   | P   | P   | `LiveFreshness` missing (`Stale` present)                                 |
| 037 | SwatchLegendItem            | P   | P   | P   | P   |                                                                           |
| 038 | InlineSpinnerText           | P   | P   | P   | P   |                                                                           |
| 039 | FocusRing                   | P*  | P   | P   | P   | D-04; `RingOnButton`/`RingOnCustomSurrogate` are `Normal`/`Inset`         |
| 040 | FormField                   | P   | P   | P   | P   |                                                                           |
| 041 | Menu                        | F   | G   | P   | P   | D-02 (light); 5 listed stories missing                                    |
| 042 | Tabs                        | P   | P   | P   | P   | density branch (`tabs.css:60-66`) is intended                             |
| 043 | Dialog                      | P*  | P   | P*  | P*  | D-01; no keyboard-named story; §5                                         |
| 044 | ConfirmDialog               | P   | G   | P   | P*  | D-08; `TypedConfirm`/`HoldToConfirm` are `Typed`/`Hold`                   |
| 045 | Toast                       | P   | P   | P   | P   | density branch (`toast.css:121`) is intended                              |
| 046 | Drawer                      | P*  | P   | P*  | P*  | D-01; no keyboard-named story; §5                                         |
| 047 | DatePicker                  | P   | P   | P   | P   | `Range` is the `DateRangePicker` story file                               |
| 048 | Combobox                    | F   | P   | P   | P*  | D-02 (its rows are `select.css`'s); §5                                    |
| 049 | Table                       | P   | G   | P*  | P   | `Virtualized`, `MergedCell`, `SortUnavailable` missing; no keyboard story |
| 050 | Card                        | P   | P   | P   | P   |                                                                           |
| 054 | SearchBox                   | P   | P   | P   | P*  | §5                                                                        |
| 059 | CommandPalette              | P   | G   | P*  | P   | `Grouped`, `EmptyQuery` missing; no keyboard story                        |
| 062 | ThemeSwitcher               | P   | P   | P   | P   | no forced-colours block (wrapper; children carry theirs)                  |
| 063 | DensityToggle               | P   | P   | P   | P   | same as 062; `ChartPanelDense` is `ChartPanel`                            |
| 065 | FormSection                 | P   | P   | P   | P   |                                                                           |
| 069 | InfoPanel                   | P   | P   | P*  | P*  | no keyboard story; §5                                                     |
| 079 | RbacGate                    | P   | G   | P*  | P   | `EnvMismatch` story missing; no keyboard story                            |
| 085 | SkipLink                    | P   | P   | P   | P   |                                                                           |
| 089 | ForbiddenState              | P   | P   | P   | P   | one stylesheet (`appstate.css`) with 090                                  |
| 090 | NotFoundState               | P   | P   | P   | P   |                                                                           |
| 091 | GlobalErrorBoundaryFallback | P   | P   | P   | P   | `crash.css`                                                               |
| 228 | PreviewTile                 | P   | P   | P   | P   | `Error` is `ErrorState`                                                   |

### 2.3 Disabled-with-reason (§12, behaviour group)

Sixteen gated controls carry a `DisabledWithReason` story: Button, IconButton, Checkbox, Toggle, TextInput, Select,
NumericStepperInput, Slider, Tag, Menu, DatePicker, DateRangePicker, Combobox, SymbolSearchInput, FormField,
FormSection. Five more express it under other names: SegmentedControl and RadioGroup (`GatedGroup`), ColorSwatch
(`SwatchLocked`, `PickerLocked`), ConfirmDialog (`ConfirmGated`) and CommandPalette (`Gated`). ThemeSwitcher and
DensityToggle expose no reason prop; both are local preferences, never RBAC or environment gated, so the pattern does
not apply (CMP-062 and 063 entries).

### 2.4 Motion

Twelve stylesheets declare a `transition` or `animation` property outside comments: `combobox`, `dialog`, `drawer`,
`menu`, `popover`, `progress`, `select`, `skeleton`, `spinner`, `toast`, `toggle`, `tooltip`. All twelve also carry a
`prefers-reduced-motion` or `data-motion="reduce"` rule. `button.css`, `radio.css` and `formsection.css` mention
"transition" only in comments (hover and expand are instant by spec). CSS read; no live motion check.

## 3. Token drift findings

Form: **token expected / value observed**, file:line, severity (serious = a user cannot do or see the thing; moderate =
a documented state is degraded or a rule is broken in one theme; minor = hygiene).

| Id   | Token expected / value observed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Where                                                                                                                                                                                         | Severity |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| D-01 | Tier-2/3 token expected for the modal scrim / `--palette-black` (Tier-1 primitive) observed. Documented: the scrim is the PROPOSED `color.surface.scrim`, bound meanwhile to `palette.black` + `opacity.scrim` (`E05-D02-feedback-overlays.md` convention 31, §6 H1). The token does not exist in the build.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | `dialog.css:25`, `drawer.css:23` (opacity `--opacity-scrim` on the next line)                                                                                                                 | minor    |
| D-02 | `color.surface.hover` expected to differ from the surface the row sits on / `--color-surface-hover` = `#E3E6EA` equals `--color-surface-overlay` = `#E3E6EA` in light (`packages/ui/tokens/semantic-light.tokens.json`: `surface.hover` and `surface.overlay` are both `{palette.light.neutral.150}`; the untracked build output reads `build/css/tokens.light.css:111-112`). Menu rows and the Select active/hover row (which Combobox reuses) paint `surface.hover` on an `overlay` panel, so the fill is invisible in light; the focus ring is the only cue. `fuzzylist.css:55-58` already works around the same collision (E08-D05 §13) with a light-only `surface.selected`; Menu and Select do not. `molecules-menu--hover--light--compact.png` shows the hovered row with no distinct fill. | `menu.css:26` (panel), `menu.css:87-91` (row); `select.css:91` (panel), `select.css:184-186` (active row); `combobox.css:4,17` takes its rows from `select.css`, so it inherits the collision | moderate |
| D-03 | Theme-agnostic component CSS expected / a `:root[data-theme="light"]` selector observed in a component stylesheet (the only one). It is the right local fix for D-02's collision, but the cause is the token pair (§7 row 7).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | `fuzzylist.css:55-58`                                                                                                                                                                         | minor    |
| D-04 | A focus-offset token expected / the literal `outline-offset: 2px` observed in 8 stylesheets (`fields`, `appstate`, `focusring`, `checkbox`, `slider`, `segmented`, `skiplink`, `toggle`); ColorSwatch uses `0` (`colorswatch.css:59`) and the 11 inset rings bind to `border.focus` (for example `menu.css:96`). Documented as "a CMP-039 constant, no token" (`E05-D02.md:209`, `:680`, `:825`). Three `calc()` lines also mix a bare literal with a token: `confidencedots.css:43`, `select.css:70`, `skeleton.css:136`.                                                                                                                                                                                                                                                                         | `focusring.css:13`, `fields.css:33`, `appstate.css:97`, `checkbox.css:38`, `slider.css:63`, `segmented.css:142`, `skiplink.css:39`, `toggle.css:24`                                           | minor    |
| D-05 | Brief §12 expects 40-44 px comfortable targets / `size.control.comfortable` = `32px` (`build/css/tokens.dark.css:292`); compact `24px` (`:293`); `size.target.min` = `24px` (`:303`). The build matches the spec and the brief's own §3 amendment (`16:130`, `:143`), not §12 (`16:674`). `E05-D02.md:426-428` already recommends correcting §12; the correction has not landed.                                                                                                                                                                                                                                                                                                                                                                                                                   | `docs/plan/16-design-system-brief.md:674`; build correct                                                                                                                                      | moderate |
| D-06 | Focus-ring radius: the spec says `radius.control + 2` in one place (`E05-D02.md:680`), `radius.badge` in another (`:882`, `:1021`) and `radius.control` in a third (`:952`) / the build draws the ring as the element's own outline, which follows each element's radius (`focusring.css:4`). Three spec statements, one behaviour, none equal.                                                                                                                                                                                                                                                                                                                                                                                                                                                    | `E05-D02.md` lines above; `focusring.css:4,13`                                                                                                                                                | minor    |
| D-07 | A keyboard story per interactive component expected (§12: a keyboard path that is implemented, tested) / no story whose name carries `Keyboard`, `Key`, `Esc`, `Focus` or `Tab` on Drawer, Table, CommandPalette, InfoPanel, RbacGate. Unit tests may cover the path (`packages/ui/test/*.test.tsx`, not re-run); the story set does not show it. Name-based, so a covering story under another name is possible.                                                                                                                                                                                                                                                                                                                                                                                  | `Drawer.stories.tsx`, `Table.stories.tsx`, `CommandPalette.stories.tsx`, `InfoPanel.stories.tsx`, `RbacGate.stories.tsx`                                                                      | minor    |
| D-08 | Confirm-gate ladder stories expected (catalogue CMP-044: `Rung1`..`Rung4`, `TwoChoice`, `TwoChoiceUnknown`) / `ConfirmDialog.stories.tsx` has `Standard`, `Guard`, `Typed`, `Hold*`, `CountingDown`, `TimedOut`, `OrderConfirm` and no rung or two-choice story. The §12 trading-safety item (standard / typed / hold variant stated, keyboard path tested) holds for those three gates; the four-rung ladder of E09-D09 is not rendered.                                                                                                                                                                                                                                                                                                                                                          | `packages/ui/src/components/ConfirmDialog.stories.tsx`                                                                                                                                        | moderate |

**Hard-coded values.** `grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(' packages/ui/src/components/*.css` returns two
hits, both inside comments (`skeleton.css:192`, `select.css:181`). The 84 `px` literal lines outside comments and the
hairline pattern fall into five classes; none is a colour and none is a bare spacing value:

| Class                                                          | Lines | Example                                                 | Verdict                                              |
| -------------------------------------------------------------- | ----- | ------------------------------------------------------- | ---------------------------------------------------- |
| `outline-offset: 2px`                                          | 8     | `focusring.css:13`                                      | D-04                                                 |
| Forced-colours borders (`CanvasText`, `Highlight`, …)          | 15    | `callout.css:93`, `table.css:287`, `iconbutton.css:155` | allowed: system colours, no token can express them   |
| `calc(var(--border-*) * 1px)` and similar token-times-px forms | 47    | `focusring.css:19`, `dialog.css:114`                    | allowed: the hairline pattern, widened to `border.*` |
| Rest `1px` transparent borders and `-1px` overlap margins      | 8     | `button.css:11`, `tag.css:11,75`                        | allowed by the hairline rule                         |
| Visually-hidden `1px` boxes                                    | 6     | `controls.css:18-20`, `skiplink.css:6-8`                | allowed: not a layout dimension                      |

Three `calc()` lines mix a bare literal with a token and are the only near-misses (`confidencedots.css:43`,
`select.css:70`, `skeleton.css:136`); minor, folded into D-04.

Responsive and sizing literals in `rem` (`dialog.css:127` 40 rem / 25 rem, `drawer.css:111` 45 rem,
`commandpalette.css:12` 40 rem / 25 rem, `emptystate.css:14` 30 rem) have no token; they are breakpoints and a measure.
Proposed as a follow-up (§7 row 8), not a finding: a spec for them does not exist in `16`.

**Token resolution.** All 196 distinct `var(--…)` names resolve: 18 to `--cv-*` properties set at runtime by the component or its
host (`--cv-anchor-width`, `--cv-progress`, `--cv-slider-pos` and so on), the rest to the token build or to a
property a stylesheet defines itself. The catalogue `Tokens` lines of 17 entries that name tokens absent from the build are catalogue drift, not code drift (§7 rows 1–4):
`color.text.error` (CMP-007), `color.text.warning` (CMP-035), `color.surface.skeleton` (CMP-015, 029), `color.track`
(CMP-023), `space.avatar.overlap` (CMP-025), `motion.shimmer` / `motion.spin` / `motion.slide` (CMP-014, 015, 046),
`color.surface.scrim` (CMP-043, D-01) and `font.mono` (CMP-007, 008, 022, 034, 035, 049; the build name is
`font.family.mono`).

## 4. Variants × states versus stories

The catalogue `Storybook` line is the matrix §12 names. Result of the comparison (§0 item 4): **47 of 62 entries are
complete or complete by renamed equivalents; 15 have at least one listed story with no equivalent.** The gaps, with the
equivalents counted as covered:

| CMP | Variant expected / story missing                                        | Counted as covered                                                 |
| --- | ----------------------------------------------------------------------- | ------------------------------------------------------------------ |
| 008 | `Mixed`                                                                 | —                                                                  |
| 009 | `Searchable`, `WithSpecimen`, `Mixed`                                   | —                                                                  |
| 010 | `Mixed`                                                                 | —                                                                  |
| 011 | `EstimatedChip` (CMP-227, deferred by S02)                              | —                                                                  |
| 013 | `ColorPalette`                                                          | —                                                                  |
| 014 | `Nested`, `SlowPath`                                                    | `Standalone` is `Labelled`; `Nested` may be `Decorative`           |
| 023 | `Running`, `Failed`, `Unknown`, `InWizard`                              | `AllTones`, `Success`, `Warning`, `Danger` cover the tones         |
| 028 | `ChartStrip`, `BarRebuildProgress`                                      | —                                                                  |
| 031 | `Mixed`, `Custom`                                                       | —                                                                  |
| 036 | `LiveFreshness`                                                         | `Stale`                                                            |
| 041 | `ChipItems`, `WithDescription`, `TrailingZone`, `ContentSlot`, `Groups` | `Nested` is `NestedSubmenu`                                        |
| 044 | `Rung1`..`Rung4`, `TwoChoice`, `TwoChoiceUnknown`                       | `TypedConfirm` is `Typed`; `HoldToConfirm` is `Hold`               |
| 049 | `Virtualized`, `MergedCell`, `SortUnavailable`                          | `Perf200Rows` partly covers `Virtualized`; `Error` is `ErrorStory` |
| 059 | `Grouped`, `EmptyQuery`                                                 | `RbacDisabled` is `Gated`; `Destructive` is `WithConfirms`         |
| 079 | `Denied(EnvMismatch)` (the catalogue lists 12 stories, the file has 11) | the other eight `Denied*` are present                              |

Two reading notes. Several gaps are stories for states the component cannot yet reach (`Mixed` needs a multi-edit
host; `Rung1..4` needs E09-D09's ladder host; `ChartStrip` is a later epic's composition); for those the correct fix may
be to amend the catalogue line (§7 row 6) rather than add a story. The name check was not used to
flag absent `Hover`, `Active` or `FocusVisible` stories: many are inapplicable (overlays, static atoms) and a state
matrix story such as `AllStates` often covers them.

## 5. Near-duplicates

Evidence is composition (imports in the `*.tsx`) and shared selectors (`grep` of the stylesheets); "looks identical" is
not claimed from pixels.

| Pair or set                                      | Evidence                                                                                                                                                                                                                                                                                      | Recommendation                                                                                                                                                               |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SearchBox · SymbolSearchInput · FuzzyList input  | All three draw `.cv-field` (`fields.css`); SearchBox adds a clear IconButton (`searchbox.css`, 28 lines); SymbolSearchInput and Combobox share `fieldParts`/`fieldContext`; FuzzyList is the result list, not an input.                                                                       | **Why both**: three roles (generic filter, symbol preview with recents, type-ahead base) over one well. Keep; add to the CMP-054 entry "composes CMP-007's well" (§7 row 9). |
| Select · Combobox · Menu · FuzzyList rows        | Combobox takes its option rows from `select.css` (`combobox.css:4`); Menu draws `.cv-menu__row` (`menu.css:87`), FuzzyList `.cv-fuzzylist__row` (`fuzzylist.css:51`), Select `.cv-select__row` (`select.css:168`): three row implementations with the same hover, active and disabled states. | **Consolidate the row** into one shared selector and fix D-02 once. Keep all four components: they differ in typing, nesting and ranking.                                    |
| Callout · InfoPanel · EmptyState · ErrorState    | InfoPanel composes Drawer, ErrorState and Skeleton; Callout is the inline band; EmptyState and ErrorState are block placeholders with their own icon and action layouts (`emptystate.css` 96, `errorstate.css` 149, `callout.css` 105).                                                       | **Why all four**: banner, expandable methodology note, empty block, error block. Document the choice rule in the catalogue (§7 row 10). No code consolidation.               |
| Dialog · ConfirmDialog · Drawer                  | ConfirmDialog is built on Dialog (`ConfirmDialog.tsx:14`); Dialog and Drawer carry an identical scrim rule (`dialog.css:22-26`, `drawer.css:20-24`) and repeated layer plumbing.                                                                                                              | **Consolidate the scrim** into one `.cv-scrim` selector (and one token when `color.surface.scrim` lands, D-01). Keep the three components.                                   |
| IconButton · CopyButton                          | CopyButton wraps IconButton (`CopyButton.tsx:2`); `copybutton.css` is 26 lines.                                                                                                                                                                                                               | **Why both**: CopyButton is a one-purpose composition over IconButton (26-line stylesheet). Keep; the catalogue entry should say "composes CMP-002".                         |
| ThemeSwitcher · DensityToggle · SegmentedControl | ThemeSwitcher wraps SegmentedControl and Toggle (`ThemeSwitcher.tsx:4-5`, 9-line stylesheet). DensityToggle is built on Button and Menu, not SegmentedControl, because it carries a per-panel override and a menu form.                                                                       | **Why all three**: different controls with different output. Note in the catalogue that DensityToggle is not a SegmentedControl skin (§7 row 9).                             |

One CSS-level duplicate is not a component pair: **12 stylesheets repeat the same reduced-motion block** (`transition-duration: 0.01ms !important`,
for example `dialog.css:163-177`, `popover.css:97-105`). It is the strongest recurring-drift class (§8).

## 6. Accepted deviations, with where each is written

"No silent waivers" (the ticket's fourth scenario): each accepted deviation must be written where a reader of the
component sees it, not only in a review. Result: **spec docs carry all five; Storybook notes carry none in full (one partly).** The notes are written in #5237 (E05-S04 slice H, commit "write the accepted deviations into the Storybook notes"), so this scenario passes once #5237 merges.

| Deviation                                                         | Written in                                                                                | In the component's Storybook notes?             |
| ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------- |
| Scrim bound to `palette.black` + `opacity.scrim` (D-01)           | `E05-D02-feedback-overlays.md` convention 31, §6 H1; comment at `dialog.css`/`drawer.css` | No (`Dialog.stories.tsx`, `Drawer.stories.tsx`) |
| Focus-ring offset has no token (D-04)                             | `E05-D02.md:209`, `:680`, `:825`; `focusring.css:4`                                       | Partly (`FocusRing.stories.tsx` Normal/Inset)   |
| Comfortable target is 32 px, not 40–44 (D-05)                     | `E05-D02.md:426-428`; `16` §3 amendment (`:130`, `:143`)                                  | No                                              |
| Light-theme FuzzyList hover uses `surface.selected` (D-03)        | comment at `fuzzylist.css:55`, E08-D05 §13                                                | No                                              |
| ThemeSwitcher / DensityToggle have no disabled-with-reason (§2.3) | `15` entries CMP-062, 063                                                                 | No                                              |

The code-side change (one `parameters.docs.description` line per component naming its deviation) is #5237; it is
outside this docs-only review. #5232 also removes D-03's FuzzyList override, which moots the FuzzyList row above.

## 7. Catalogue amendments the review implies

Proposed rows for `docs/plan/15-component-catalogue.md`; none is applied here. "Implementation is the better answer"
(the ticket's wording) holds for rows 1–5.

| #   | Entry                                      | Proposed change                                                                                                                                                                                                                                  | Why                                                                  |
| --- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| 1   | CMP-007, 008, 022, 034, 035, 049           | `Tokens`: `font.mono` becomes `font.family.mono` (the build and `fields.css`/`kbd.css` use the latter).                                                                                                                                          | Name absent from the build.                                          |
| 2   | CMP-007                                    | `Tokens`: drop `color.text.error`; the invalid state uses `color.status.danger.default` (boundary, `fields.css:49`) and `color.status.danger.strong` (message, `:143`).                                                                          | Token does not exist; code follows the spec text.                    |
| 3   | CMP-035                                    | `Tokens`: remove `color.status.warning.strong`, `color.text.warning`; digits inherit the host sentence's colour (`countdown.css`, conventions 41).                                                                                               | Spec says no colour step; line is stale.                             |
| 4   | CMP-014, 015, 023, 025, 029, 046           | `Tokens`: replace `motion.spin/shimmer/slide`, `color.surface.skeleton`, `color.track`, `space.avatar.overlap` with what the stylesheets bind (`motion.recipes`, `surface.hover` + `surface.raised`, `action.primary.default`, derived overlap). | Names are not tokens in the build.                                   |
| 5   | CMP-025                                    | Add a Notes line: the overlap is `size.icon` arithmetic (8 px compact), no token.                                                                                                                                                                | Recorded as drift class "unbound geometry constant".                 |
| 6   | CMP-008, 009, 010, 031, 044, 028, 059, 079 | Where a listed story needs a host that does not exist yet (`Mixed`, `Rung1..4`, `ChartStrip`), mark it `(with <ticket>)` instead of leaving a silent gap.                                                                                        | Keeps §12's "full matrix" checkable; stories follow their host.      |
| 7   | Tokens (`16` §3 / `E05-D02` surface notes) | Add a light-theme `color.surface.hover-on-overlay` (or move light `surface.hover` off `#E3E6EA`) so Menu, Select, Combobox and FuzzyList need no per-component override.                                                                         | Root cause of D-02, D-03. A token change, so E05-D01/T05 own it.     |
| 8   | `16` §3 (sizing)                           | Add breakpoint / measure tokens (`size.measure.prose` 30 rem; overlay breakpoints 40 / 45 rem and 25 rem height).                                                                                                                                | Seven rem literals with no home (§3).                                |
| 9   | CMP-054, 063                               | CMP-054: "composes the CMP-007 well and a CMP-002 ghost clear". CMP-063: "built on Button and Menu; not a CMP-003 skin."                                                                                                                         | Records the composition checked in §5.                               |
| 10  | CMP-026, 027, 028, 069                     | Add one choice-rule line to each: banner (028), expandable note (069), empty block (026), error block (027).                                                                                                                                     | Four near-identical-role components, no rule for choosing (§5).      |
| 11  | `16` §12                                   | Correct the hit-target line to "24 px compact / 32 px comfortable" (D-05).                                                                                                                                                                       | The review changed a rule's reading; `E05-D02.md:428` recommends it. |

Rows 7, 8 and 11 touch `16` or the token files; they need the owner of `16` (the design-system brief, owner `basiltt`) and CODEOWNER review.

## 8. Recurring drift classes and follow-ups

Per the Definition of Done ("recurring drift classes become a lint rule or a VR story"). Each is a follow-up Task to
file, not inline work.

| Class                                                    | Evidence                                  | Proposed guard                                                                                                                        |
| -------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Tier-1 primitive used in a component stylesheet          | `dialog.css:25`, `drawer.css:23` (2 hits) | stylelint `declaration-property-value-disallowed-list` for `var(--palette-*)` in `src/components/**`, with the two documented waivers |
| Hover fill equals the surface it sits on                 | D-02 (Menu, Select)                       | extend `tools/contrast/pairs.mjs`: a pair per overlay surface × `surface.hover`, with a floor ΔE                                      |
| Same reduced-motion block pasted 12 times                | §5 last paragraph                         | one shared rule in `theme.css` keyed on `[data-motion="reduce"]`, plus a stylelint check that every animated file is covered          |
| Literal `outline-offset: 2px`                            | D-04 (8 files)                            | one `.cv-focus-ring` rule or a `--cv-focus-offset` property in `focusring.css`; stylelint to ban the literal elsewhere                |
| Story-gap drift (catalogue lists a story, file lacks it) | §4, 15 entries                            | a CI script that compares each catalogue `Storybook` line with the `export const` names, name-matched, warning on gaps                |
| Light-theme component override                           | D-03 (1 hit)                              | stylelint: no `[data-theme=…]` selector in `src/components/**`                                                                        |

## 9. Sign-off (drafted for the coordinator)

Shape follows the E05-Q01 sign-off comments: sources, honest scope, a result table, the line, open items, limits,
human legs owed.

**Sources:** `E05-D05-design-qa.md` (this document); `docs/plan/16-design-system-brief.md` §12; `15-component-catalogue.md`;
`E05-D02*.md`; `E05-D03.md`; `packages/ui/vr/baselines`; `main` at `16d70feed`.

**Agent-run, honest scope: not a human pass.** Rater: an agent. No Penpot compare, no browser measurement, no
screen reader; every number marked `CSS read` was read from the stylesheet and the token build.

| Scenario (ticket)                       | Result                                                                                                                                         |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Every component inspected in every mode | **Pass partial**: 62 of 62 ids, all six cells have a baseline; cells share one CSS result except where §2.2 says; no per-cell pixel comparison |
| Drift quantified, not impressionistic   | **Pass**: 8 findings in "token expected / value observed" form with file:line (§3)                                                             |
| Near-duplicate detection                | **Pass**: 6 pairs or sets, 2 consolidations (row, scrim), 4 keep-both with a reason (§5)                                                       |
| No silent waivers                       | **Fail**: 5 deviations are in the specs, 0 in Storybook notes (§6); a small `packages/ui` follow-up closes it                                  |

**Design QA sign-off: conditional; withheld pending the Storybook-notes follow-up ("No silent waivers" reads Fail above), otherwise yes, with open items.** Proposed line for the ticket: "E05-D05: design QA of the 62-id v0
set against `16` §12 completed at `main` `16d70feed`, agent-run, not a human pass; 8 drift findings (0
serious), 15 components with story gaps; open items below; CDO acknowledgement pending (owner)"; post it only once the Storybook deviation notes (§6) land.

**Open items** (none serious; all prioritised for filing):

1. **D-02** (moderate, p1 Bug): Menu, Select and Combobox hover/active fill invisible in light. Fix by the token (§7 row 7) or
   one shared row (§5). The fix is open as PR #5232.
2. **D-08** (moderate, p1): ConfirmDialog ladder (`Rung1..4`, `TwoChoice`) has no story; blocked on the E09-D09 host (E09-D09 is the
   design ticket that specifies the ladder; no E09 ticket in the backlog builds the host), so the owner is routed to the
   coordinator: file a Task with that dependency, or amend the catalogue (§7 row 6).
3. **D-05** (moderate, p2): correct `16` §12's 40–44 px to 24 / 32 px (§7 row 11); owed by the owner of `16`
   (`docs/plan/16-design-system-brief.md`, owner `basiltt`).
4. **D-01, D-03, D-04, D-06, D-07** (minor): token proposals and a keyboard story per component (§8).
5. **Story gaps** (§4): file one Task per component group, or amend per §7 row 6.
6. **Storybook notes** (§6): written in #5237; the scenario passes once it merges.
7. **Rebase gate:** CMP-062, 063 and 228 are on `main` (#5221). Re-run the §3 greps and the §4 comparison on the final
   base before READY; the slice-H-only parts are #5237.

**Limits.** Not run: Storybook or `vr` (no render), `contrast:gate`, `storybook:test`, a computed-style probe, 100 % /
200 % zoom, forced colours, live motion; the 84 `px` literal lines were classified by pattern, not each opened.

**Needs a human** (owner or designer): the side-by-side visual judgement of the build against the boards in light and
high contrast; the Penpot legs (a Figma/Penpot variant per documented state, published-library composition only),
which can only be a spec read unless boards are drawn; real pointer and keyboard feel; the CDO acknowledgement.

**Human legs still owed:** the CDO acknowledgement (**owner approval pending**, recorded here per the agent-delivery
adaptation), the Penpot compare, and E05-Q02's screen-reader pass.
