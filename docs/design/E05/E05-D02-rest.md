# E05-D02 — Design-system atoms and molecules: slice 5 of 5 (the rest of the v0 subset and the custom trading glyphs)

**Ticket:** E05-D02 (#161) · **Epic:** E05 Design system v0 · **Status:** In Review — awaiting owner approval (slice 5
of 5) (design PR: the owner approves under C-10.1; the coordinator reviews). Text-first: written from `15`, the tokens,
E09-D09 and the owning screen specs without a Penpot build; the boards are PENDING. This slice closes #161 once the
boards PR has merged; until then this PR, like slices 1–4, refers to #161 without closing it.
**Penpot:** the per-set file `E05-D02 boards` (the coordinator's ruling of 2026-10-27: the shared DS file no longer
loads, so the boards are the ten specimen boards of the boards PR, `E05-D02 / 01 actions` … `E05-D02 / 10
light-composite`, on the four slice pages). Slice 5 adds no board (the ten-board cap per design ticket). A slice-5
component folds into a specimen board where its text lands first, as a part of a slice 1–4 component: CMP-022 Kbd in
board 09's menu shortcut slot and tooltip, and CMP-035 Countdown in board 09's order-confirm footer (slice 4 §1 draws
both "from its catalogue entry as a plain board until it ships"). Every other section here, the glyph set included, is
**not drawn — the text is binding**.
**Slices:** #161 ships as five design PRs. Slice 1 (#3914, `E05-D02.md`) covers actions and selection; slice 2 (#4290,
`E05-D02-data-display.md`) the data display and text atoms; slice 3 (#4322, `E05-D02-form-controls.md`) the form
controls; slice 4 (#4414, `E05-D02-feedback-overlays.md`) the feedback and overlays; this slice the rest of the
coordinator's five-slice plan on #161: CMP-022 Kbd, CMP-035 Countdown, CMP-036 KeyValueRow, CMP-042 Tabs, CMP-050 Card,
CMP-059 CommandPalette, CMP-062 ThemeSwitcher, CMP-063 DensityToggle, CMP-069 InfoPanel, CMP-085 SkipLink and CMP-228
PreviewTile, plus the custom trading glyphs of `16` §5 (E05-T06, #271, takes them from here).
**Companion:** `E05-D02-rest-a11y-audit.md` (accessibility pre-review of this slice).
**Builds on:** slice 1's conventions 1–14, token mirror, exceptions and decisions A1–A12, B1–B7, C1–C15 and D1–D17 (D13
is superseded by E09-D09 §2.2 T2); the conventions 15–20 and decisions E1–E27 of slice 2 (#4290, merged); the
conventions 21–29 and decisions G1–G23 of slice 3 (#4322, merged as `3a2fc5c29`); and the conventions 30–39 and
decisions H1–H37 of slice 4 (#4414, merged as `04a8caa95`). They apply unchanged and are cited as "slice 1 A10", "slice
2 (#4290) E20", "slice 3 (#4322) conventions 24" and "slice 4 (#4414) conventions 32".
**Key.** `05`, `14`, `15`, `16`, `21`, `22` are the `docs/plan/` documents by number; D09 is
`docs/design/E09/E09-D09.md`. This branch's base is `origin/main` `966f9edcd`, and every `path:line` reference is at
that commit; slices 1–4 are cited by section. "The tokens" are `packages/ui/tokens` as #3925 left them (`a0132de01`,
their last change).

## 1. What this slice specifies

- **11 components, 27 variant properties, 66 cells,** plus **13 custom trading glyphs** specified as glyph specs
  (§7.12). One Penpot variant set per CMP id would be named `CMP-0xx · Name` (brief §10; slice 1 §1.1), but under the
  board cap the cells are a specification, not a build: the matrix rule is slice 1 conventions 2 (every documented state
  at the default of the other axes, every other axis value once, the universal states where the component is
  interactive), and each section lists its cells and the states that do not apply, with the reason.
- **One section per component** (§7): the catalogue Props and A11y verbatim, the variant properties, the matrix, the
  anatomy and its tokens, the keyboard and role tables, focus, motion, live regions, T2 and what is not T2, the
  analytics it annotates (CMP-062, CMP-063: #161's Observability), alignment.
- **No build.** Every token below is a published semantic token or a named primitive (§4, §5); the cells nest the
  components of slices 1–4 (CMP-001, 002, 003, 004, 006, 007, 014, 015, 016, 019, 021, 026, 027, 039, 041, 043, 046,
  049, 079) by reference.
- **The ruling on gating** (slice 4 §1, the orchestrator's ruling on slice 2, record 6368751311, M1): an atom never owns
  policy gating; the host does. A container here — a card, a tab panel, the palette, the info panel — has no gated state
  of its own; a nested control takes T2 in its own form through CMP-079 RbacGate with the host's reason (conventions
  46). The gated cells are CMP-042's gated tab, CMP-059's gated command and the appearance controls' T2 option (§6 J15).
- **Catalogue alignment is held.** This PR's write set is the two spec files; the `15` clauses each section proposes are
  collected in §6 (f) for the catalogue's owner, as slice 4's were applied in its own PR.

| Component              | Variant set (specified; not drawn) | Variant properties                 | Cells  | Composes (by reference)                                                             |
| ---------------------- | ---------------------------------- | ---------------------------------- | ------ | ----------------------------------------------------------------------------------- |
| CMP-022 Kbd            | `CMP-022 · Kbd`                    | Keys, Surface                      | 5      | —                                                                                   |
| CMP-035 Countdown      | `CMP-035 · Countdown`              | Format, Phase                      | 7      | CMP-019 (`clock`)                                                                   |
| CMP-036 KeyValueRow    | `CMP-036 · KeyValueRow`            | Emphasis, Value, Freshness, Layout | 7      | CMP-239 FreshnessMarker (by reference), CMP-020                                     |
| CMP-042 Tabs           | `CMP-042 · Tabs`                   | Orientation, Icons, State          | 8      | CMP-019, CMP-079 + CMP-019 `lock` (the gated tab)                                   |
| CMP-050 Card           | `CMP-050 · Card`                   | Surface, Header, Padding           | 5      | CMP-001 / CMP-002 (actions), CMP-015, CMP-027                                       |
| CMP-059 CommandPalette | `CMP-059 · CommandPalette`         | Query, Row                         | 7      | CMP-043, CMP-213 FuzzyList, CMP-022, CMP-019 (`warning`, `lock`), CMP-079           |
| CMP-062 ThemeSwitcher  | `CMP-062 · ThemeSwitcher`          | Value, State                       | 5      | CMP-003, CMP-004 ("match system"), CMP-079 + CMP-019 `lock` (§6 J15 (b) only)       |
| CMP-063 DensityToggle  | `CMP-063 · DensityToggle`          | Scope, Value, Form                 | 6      | CMP-003, CMP-041 (`menuitemradio` form), CMP-079 + CMP-019 `lock` (§6 J15 (b) only) |
| CMP-069 InfoPanel      | `CMP-069 · InfoPanel`              | Variant, State                     | 5      | CMP-046 (`modal=false`), CMP-002 (close), CMP-015, CMP-027, CMP-021                 |
| CMP-085 SkipLink       | `CMP-085 · SkipLink`               | State, Targets                     | 3      | CMP-039                                                                             |
| CMP-228 PreviewTile    | `CMP-228 · PreviewTile`            | Kind, State                        | 8      | — (the host's renderer draws inside it; CMP-015 is never used, E11-D03 D12)         |
| **11**                 |                                    | **27**                             | **66** |                                                                                     |
| Custom trading glyphs  | `icon/{name}` (glyph specs, §7.12) | Size                               | 13     | registered through CMP-019 (E05-T06)                                                |

Every gated cell — CMP-042's gated tab, CMP-059's gated command and, only under §6 J15 (b), the appearance controls'
locked option — is a CMP-079 RbacGate composition with the CMP-019 `lock` glyph (conventions 46).

**Deviations.** (1) The coordinator's brief for this slice names the new decisions "H1…"; slice 4 already holds H1–H37
(§6), so this slice numbers its decisions **J1–J25** (I is skipped: it reads as a numeral). (2) The brief's Penpot line
names the per-set file; this slice therefore draws nothing of its own and says so per section. (3) No `15` entry is
edited (the write set above).

## 2. How to review

1. Read the conventions once (§3, items 40–49): every component section cites them instead of repeating them.
2. Read a section top to bottom: the matrix says what a build would draw, the anatomy how, the tables how it behaves;
   the catalogue text it quotes is `main`'s at `966f9edcd`.
3. The owner decisions are §6 (J1–J25); §6 (e) says what a "no" reverts, §6 (f) lists the held `15` clauses and the
   hand-offs.
4. The glyph set (§7.12) is a specification for E05-T06: names, meanings, motifs, the grid, the stroke, the optical
   sizes, the states it never has and the accessible-name rule. E05-T06 draws them and registers them.

## 3. Conventions (40–49, numbered on from slice 4's)

40. **Shortcut hints are the keymap's, never the component's** (CMP-022, and every Kbd inside CMP-016, CMP-041,
    CMP-059). A Kbd renders the **active profile's** binding, never the shipped default, and renders nothing when the
    command is unbound; the command stays reachable without it (E12-D04 §3.1 and §9.2, `E12-D04.md:119`, `:232`; SCR-013
    shows the user's current bindings, `E10-D03.md:285`). A hint sits in a tooltip, a menu row's trailing slot, a
    palette row and the cheatsheet, never inline on a toolbar (E15-D03 D-9, `E15-D03.md:142`, §4.8 `:406`). It is never
    interactive and never the only disclosure of a command's name. Keys `Esc` and `Ctrl+K` are not remappable (`05:85`,
    cited by `E12-D04.md:230`), so their hints are constant.
41. **Time text** (CMP-035, and every time a component here shows). A deadline is the server's instant, rendered, never
    computed from a local duration (E39-D02, `E39-D02.md:84`: "the server's `until`, rendered, never computed"); where
    an absolute time exists it is the primary text and the relative count the secondary one (E27-D03 BQ-10,
    `E27-D03.md:184`). Digits bind `type.num.*` (JetBrains Mono, tabular; `15:40` rule 6 as slice 3 (#4322) conventions
    27 applies it), so a ticking count never reflows its line. A count changes its digits only — no fade, no colour step
    per tick (E39-D02, `E39-D02.md:191`).
42. **Label and value pairs** (CMP-036, and the rows inside CMP-050, CMP-069, CMP-228's captions). The label is
    `type.ui.label` in `color.text.secondary`; the value is `color.text.primary`, a number in `type.num.*` and any other
    value in `type.ui.body`; the pair keeps one baseline. An unavailable value is "—" in `color.text.secondary`, never
    an empty cell and never a zero (E37-D02 row 13's agreement: "'—' is Stale, 'Loading…' is Loading", `E37-D02.md:91`).
    A unit is part of the value text ("1.000 BTC"), never a second colour.
43. **Which switcher** (CMP-042, CMP-003, CMP-063, CMP-062). Tabs switch **panel-local sections** whose content is not a
    value (`15:456`); a value the user sets is a CMP-003 SegmentedControl or a CMP-006 RadioGroup (the appearance
    controls, conventions 45); a top-level route set is navigation (CMP-071, CMP-086), never tabs; a workspace's tab
    strip is its own component (E15-D02, `E15-D02.md:774`: "CMP-042 Tabs is panel-local"). A tab carries no count that
    changes per tick (E29-D02 D-17, `E29-D02.md:158`).
44. **Content surfaces** (CMP-050, CMP-228, CMP-069's inline form). A card is `color.surface.raised` on
    `color.surface.canvas` or `color.surface.app`, `radius.card`, either lifted by `elevation.card` or edged by a 1 px
    `color.border.default` hairline (E25-D05 `static` and `flat`, `E25-D05.md:247`). The fill steps are 1.06–1.15:1
    (audit §4): the step and the edge are decorative, so the card's heading or its first line names the group and
    nothing depends on seeing the box. A preview inset is `color.surface.sunken` (`15:2674`), one step below the surface
    it sits on.
45. **Appearance preferences** (CMP-062, CMP-063; `16` §4 runtime contract, `16:138`; `14` SCR-116, `14:2359`–`:2366`).
    The control writes one preference through the E05-T02 runtime, which swaps CSS custom properties at the document
    root within one frame and never remounts a panel or drops a GL context (`14:2365`). A **committed change** — a
    press, a key, the `Ctrl+Shift+H` high-contrast toggle (`05:79`) — speaks once in the control's polite region and
    emits its analytics event once (`appearance.theme_changed`, `appearance.density_changed`; `14:2366`, #161
    Observability). An applied preference that is not the user's act — the initial load, the server's settings fed with
    `store.apply(patch, { persist: false, track: false })` (`16:138`), a "match system" flip — speaks nothing and emits
    nothing (§6 J16). The event names are #161's and `14`'s; their payload is the analytics owner's, and this spec names
    only the trigger.
46. **Containers never gate; their nested controls do** — slice 4 (#4414) conventions 36, unchanged and cited from every
    section with a gated control: the control keeps its native role and its full label; `aria-disabled="true"`, never
    the `disabled` attribute, so it stays in the Tab order (a tab stays arrow-reachable, a palette option stays in the
    listbox); the CMP-019 `lock` glyph (`decorative=false`, name "Not available") leads the label in rendering 2a; the
    reason is in the DOM at mount and linked by `aria-describedby`; CMP-079 RbacGate wraps the role legs (D09 §2.1 step
    3, §8); the label and lock `color.text.tertiary`, the reason `color.text.secondary`, a filled control's fill
    `color.surface.raised` with a 1 px `color.border.default` hairline; never `color.text.disabled`, never
    `opacity.disabled`; `Enter`, `Space`, a bound hotkey or an arrow that would select it changes nothing and re-shows
    the reason inline with one polite announcement (D09 §2.2, §3.1, §9.1, §9.3, `E09-D09.md:49`). The reason is the
    host's key (`rbac.view_as` first, then `rbac.permission` with the D09 §3.2 verb, e.g. "Your role can't change
    settings.", `E09-D09.md:115`); a component never writes it. Several gated controls in one surface point at one
    reason line. A command or link whose only destination is an admin route is hidden (T3, D09 §2.1 step 1; no `admin.*`
    command exists in the palette for a session without it, `E09-D09.md:175`).
47. **What is not T2 here** (D09 §9.1; the standing rulings, slice 4 (#4414) conventions 37). _Availability:_ an
    emulated order type before E33 takes the validity look with its sentence, no lock (E30-D04 §7, BQ-7 RULED,
    `E30-D04.md:338`); a palette query with no match is "No command or symbol matches 'xyz'" (`14:357`); a preview with
    no bars is its empty text (E11-D03 D12). _Busy:_ a preview being recomputed keeps its last frame, never a spinner
    (`E11-D03.md:83`); an info panel loading its methodology is CMP-015 rows. _Outcome:_ a countdown that reached zero
    is replaced by its host's outcome line (SCR-076 cancels and closes, E30-D03 D3; an expired grace's own line), never
    a locked control. _Read-only data:_ a KeyValueRow, a card and a preview tile are not controls and have no gated
    state; their host's notice speaks for the panel (D09 §2.2 "one notice, many pointers").
48. **Forced colours** (`05` §8.1; slice 1 conventions 12; slice 4 (#4414) conventions 38). A Kbd cap, a card, a tab
    strip, a preview tile and the palette keep a real 1 px border, which forced colours paint CanvasText (ButtonText on
    a control), so the shape survives when fills are lost; the selected tab's 2 px rule becomes Highlight; a selected or
    active option sets a Highlight fill with HighlightText (`forced-color-adjust: none` on that part only); the skip
    link renders as LinkText on Canvas with its CanvasText border; text is CanvasText, glyphs `currentColor`; a preview
    tile's image keeps its own colours (`forced-color-adjust: none` on the canvas only), because its name and the
    settings carry the meaning (`15:2673`).
49. **Resize, zoom and reflow** (`05` §5 item 7; slice 3 (#4322) conventions 28; slice 4 (#4414) conventions 39).
    Heights are minimums: at 112–150 % text, a Kbd cap, a tab, a row and a tile grow and never clip. A KeyValueRow
    stacks its value under its label when the pair cannot share one line; a tab strip scrolls horizontally inside its
    tablist and never wraps to a second row or hides a tab (`(heuristic)`, PROPOSED); the palette at 200 % on the 1280 ×
    800 frame fills the viewport as slice 4's dialogs do, its input row and footer hint sticky and its results
    scrolling; a card's header wraps its title before its actions move under it; a preview tile keeps its aspect and
    scales its image, never its name.

## 4. Token mirror and themes

No token is added or changed; the mirror is slice 1 §4's, re-synced with #3925 (`a0132de01`, the last change to
`packages/ui/tokens`), and every figure here and in the audit is measured at that state in all three themes. The slice
binds only published semantic tokens — the surface, border, text, action, status (`subtle`, `default`, `strong`) and
focus colours, `size.control.height`, `size.row.height`, `size.icon`, the `space.inset.*`, `space.stack.*`,
`space.panel.padding` and `space.dialog.padding` aliases, `radius.control|card|dialog|badge`,
`elevation.card|popover|dialog`, the `type.ui.*` and `type.num.*` styles and the motion primitives (slice 1 A8) — plus
the named primitives of §5.2. Each section maps the catalogue names that do not exist to shipped tokens (slice 1
conventions 9): `font.mono` (CMP-022, CMP-035) → the `type.num.*` styles over `font.family.mono` (E17-D02 CR-5,
`E17-D02.md:386`; E30-D03 A15, `E30-D03.md:677`); `color.text.warning` (CMP-035) → none, the number carries the
threshold (§6 J1); `space.row.*` and `font.size.body/label` (CMP-036) → `space.inset.*` and `type.ui.label` /
`type.ui.body`; `space.tabs.*` (CMP-042) → `space.inset.*` (E12-D05 D05-C10, `E12-D05.md:548`); `radius.lg` and
`elevation.1` (CMP-050) → `radius.card` and `elevation.card` (E25-D05 CR-4, `E25-D05.md:388`, `:247`); `elevation.4`
(CMP-059) → `elevation.dialog` (E10-D03 §6.1, `E10-D03.md:281`); `color.action.primary` (CMP-085) →
`color.action.primary.default` (E10-D03 A5, `E10-D03.md:753`); `radius.md` (CMP-228) → `radius.card`, the semantic alias
of the same primitive (E12-D05, `E12-D05.md:384`). The catalogue's `radius.xs` (CMP-022) is a primitive with no
semantic alias and stays a named primitive (§5.2). Two tokens other specs need and the tokens lack are named with their
stand-ins: a node-category hue is `color.node.*` (shipped; the glyphs never take it, §6 J25), and the 12 px glyph size
is slice 1 A10's open question (§6 J24). A token gap is an owner decision (§6 (a)); none is invented.

## 5. Recorded exceptions

### 5.1 Geometry and timing constants without a token

Each value is drawn or specified raw and logged for ticket AC2 ("zero hardcoded hex or px values"); rows that recur from
slices 1–4 keep their resolution.

| Constant         | Value                                                                                                                                                                                                                                             | Components        | Proposed resolution                                                        |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- | -------------------------------------------------------------------------- |
| Kbd cap          | at least as wide as it is tall (one character is square), padding `space.inset.xs` inline; the cap height follows its `type.num.xs` line and never exceeds the host row                                                                           | CMP-022           | A component constant (slice 1 B1); no token (§6 J3)                        |
| Surface widths   | the palette 640 px (E10-D03 §6.1, `E10-D03.md:281`); an inline info panel at its host's width; a drawer info panel at slice 4's 480 px (E08-D06 D-14); the skip link at its label's width                                                         | CMP-059, 069, 085 | Host data and slice 4 (#4414) §5.1's widths; no size token (§6 J3)         |
| Row heights      | the palette's rows 32 px compact, 40 px comfortable (E10-D03 §6.1), against `size.row.height` 24 / 32                                                                                                                                             | CMP-059           | E10-D03's values as host data (§5.2; §6 J12)                               |
| Rules            | the selected tab's 2 px rule (`border.thick`); a card's 1 px hairline (`border.hairline`)                                                                                                                                                         | CMP-042, CMP-050  | Named primitives (§5.2)                                                    |
| Preview geometry | the tile's aspect and size are its host's (E11-D03 §6.4; E12-D05's preview; E32-D04's 24 px glance tiles, `E32-D04.md:366`)                                                                                                                       | CMP-228           | Host data, like slice 1 §5.1 "Sample dimensions"                           |
| Glyph grid       | the 24-unit grid of the base set, a 1.5 px stroke that never scales, round caps and joins (`16:149`–`:150`; slice 1 §7 and CMP-019's build record)                                                                                                | §7.12             | As slice 1 CMP-019's "geometry constants with no token": the 1.5 px stroke |
| Timing           | a countdown ticks once per second (1 Hz) and announces at the thresholds of §6 J7 (60 s, 10 s, 0 s by default, `15:385`); the palette's result count speaks once per settled query; a skip-link target keeps its focus ring until focus leaves it | CMP-035, 059, 085 | Behaviour constants (slice 3 (#4322) §5.1 "Timing")                        |

### 5.2 Other recorded exceptions

- **Named primitives** (slice 1 §5.2): `radius.xs` for the Kbd cap (the catalogue's, `15:258`); `border.thick` for the
  selected tab's rule; `border.hairline` for every 1 px edge (slice 1 B1); `border.focus` for the ring width;
  `size.icon.sm|md|lg` for the glyph optical sizes (slice 1 A10).
- **Absolute internals:** only slice 1 B3's (a) focus ring and (b) overlay anchors; here also the skip link, which is
  positioned over the TopBar's empty left of its second row while focused (E10-D02, `E10-D02.md:254`; E10-D03,
  `E10-D03.md:149`).
- **Penpot:** nothing is built (§1); the specimen boards' chrome is the boards PR's.
- **Cross-spec clashes, recorded for their owners**, each aligned here, kept with its owner following, or put to you.
  The sweep took every spec under `docs/design` that names one of these 11 ids or a `16` §5 trading glyph (the counts at
  `966f9edcd`: CMP-022 40 files, CMP-035 39, CMP-036 46, CMP-042 26, CMP-050 17, CMP-059 13, CMP-062 none, CMP-063 8,
  CMP-069 22, CMP-085 11, CMP-228 19, tools and data files included) and read every line naming an id for an anatomy, a
  token, a role, a key, a state or a timing; a spec merged after `966f9edcd` is not covered. The clashes:
  - **Kbd look.** E10-D03 draws the cap on `color.surface.raised` with `color.text.primary` and a `color.border.strong`
    edge (`E10-D03.md:385`, `:405`, `:505`) at `type.num.xs` (`:285`); E15-D03 §4.8 draws it in `color.text.secondary`
    at `type.num.sm` with `radius.xs` (`E15-D03.md:406`); E12-D04 draws its digits in `color.text.secondary`
    (`E12-D04.md:337`). Put to you (§6 J4).
  - **Countdown colour.** `15` names `color.text.warning` (`15:386`), which does not exist; E17-D02 CR-5 maps it to
    `color.status.warning.strong` (`E17-D02.md:386`), which measures 4.41 / 4.11 / 3.78:1 in light on canvas, raised and
    overlay (below 4.5:1 for text, audit §4), and E30-D03 A15 drops it, "the number carries the threshold"
    (`E30-D03.md:677`). Aligned with E30-D03 (§6 J1); E17-D02 CR-5's colour row goes back to its owner.
  - **Countdown formats.** E24-D02 needs `hh:mm:ss` (NG-5, `E24-D02.md:560`); E17-D02 needs an approximate "~4 s" (G10,
    `E17-D02.md:469`); E26-D02 makes its replay clock a `role="timer"` (D-19, `E26-D02.md:61`). Put to you (§6 J6).
  - **Tab selection look and activation.** E29-D02 and E40-D02 mark the selected tab with a 2 px `color.border.selected`
    rule and `color.text.primary` (`E29-D02.md:166`; `E40-D02.md:1515`) and activate automatically (`E29-D02.md:158`);
    E30-D04 §7's OrderTypeTabs use a `color.surface.selected` fill with a 2 px `color.text.primary` rule and manual
    activation (`E30-D04.md:338`, `:344`). Aligned with E29-D02 for CMP-042; CMP-103 keeps E30-D04's look as its own
    component (§6 J9).
  - **Card heading.** `15` gives a titled card heading semantics (`15:539`); E15-D05 A-4 needs no heading inside a
    listbox option (`E15-D05.md:514`); E42-D03's tiles are regions labelled by their heading (`E42-D03.md:253`). Aligned
    with both through a `headingLevel` prop (§6 J11).
  - **A live KeyValueRow dimmed.** E08-D11 M25 dims a CMP-036 live block to `color.text.disabled` while disconnected
    (`E08-D11.md:143`), the token D09 §11 measures at 2.86–4.31:1 (`E09-D09.md:220`, DS-1). It is a data state, not T2,
    so it is kept with its owner (E08-D11) and flagged: the value text is meaning, and 2.86:1 fails `05` §5 for text. A
    recommendation rides §6 J8 (c).
  - **The palette.** E10-D03 §6.1 owns SCR-012's look (`E10-D03.md:281`), with rows taller than `size.row.height`
    (§5.1) and a destructive command's warning glyph at 3.78:1 in light (its matrix row 43 PASS, glyph bar). Followed.
  - **Appearance values.** `15` CMP-062 offers `dark | light | high-contrast` (`15:647`); `22` `Settings.appearance`
    stores `theme: dark | light | system` and a separate `high_contrast` boolean, and `density: compact | comfortable |
spacious` (`22-api-openapi.yaml:21003`–`:21007`); the runtime maps `spacious` to `comfortable` and `system` to
    "match system" (`apps/web/src/shell/bootstrap/themeFromSettings.ts:9`–`:20`); `14` SCR-116 lists CVD-safe themes and
    a cosy density (`14:2361`), and its checklist "compact / comfortable / spacious" (`14:2367`). Put to you (§6 J13,
    J14).
  - **Info panel trigger.** `15` opens CMP-069 "from the chip's tooltip via `Enter`" (`15:712`); a tooltip has no
    interactive content (slice 4 (#4414) CMP-016), and E25-D05 makes the chip itself a button with
    `aria-haspopup="dialog"` (`E25-D05.md:111`). Aligned with E25-D05 (§6 J18).
  - **One-click arm glyph.** E30-D04 §3.3 gives CMP-229 ArmToggle `icon/unlock` for ARMED and `icon/lock` for LOCKED
    (`E30-D04.md:269`–`:270`); `16` §5 lists a custom "one-click-arm" glyph (`16:150`). Put to you (§6 J23).

## 6. Decisions for the owner (collected)

Deduplicated across the 11 components and against slices 1–4; J1–J25 are new, each PROPOSED with options and a
recommendation unless a merged source rules it (then marked RULED with the source). Not asked again: slice 1 A8 (motion
primitives), A10 (icon optical sizes; J24 only adds the glyph forms), B1–B3 (geometry, rings, overlay anchors), C13
(strict matrix) and C15 (stories); slice 3 (#4322) G15 (CMP-079's forms); slice 4 (#4414) H7 (surface widths), H21
(the dialog recipe, which the palette follows) and H32 (initial focus).

### (a) Token gaps (E05-D01's token files, outside this PR's write set)

- **J1 — The countdown under its threshold.** `15` CMP-035 binds `color.text.warning`, which is not shipped (`15:386`).
  Options: (a) `color.status.warning.strong` on the digits (E17-D02 CR-5) — 11.65 / 4.41 / 11.65:1 on canvas, 4.11 on
  raised and 3.78 on overlay in light, below the 4.5:1 text bar there; (b) no colour change: the digits keep their
  colour, the number itself carries the threshold, and the host's words carry urgency (E30-D03 A15, `E30-D03.md:677`);
  (c) (b) plus a CMP-019 `clock` glyph in `color.status.warning.strong` leading the digits under the threshold (a
  non-text mark: 4.41 / 4.11 / 3.78:1 in light, above 3:1). **Recommended:** (c) — never colour alone, never a text pair
  below 4.5:1, and the glyph is the one E30-D04 §3.3 already gives the countdown contexts (`icon/clock`,
  `E30-D04.md:275`). **Affects:** CMP-035; E17-D02 CR-5 (its colour row).
- **J2 — The preview tile's edge in light.** `color.border.default` on `color.surface.sunken` measures 1.71 / 1.00 /
  3.47:1 (dark / light / hc) and `color.border.strong` 2.19 / 1.20 / 2.19:1: in light the tile has no visible edge.
  Options: (a) accept it: the tile is decorative-adjacent, `role="img"` with a name, and never the only disclosure
  (`15:2673`), so its boundary is not an SC 1.4.11 component boundary; (b) a light-only edge token, an E05-D01 change.
  **Recommended:** (a); the boards' light composite shows it. **Affects:** CMP-228.

### (b) Geometry constants and layout

- **J3 — Accept §5.1's constants** (the Kbd cap, the palette's 640 px and its 32 / 40 px rows as E10-D03's host data,
  the tab rule, the glyph grid, the timing values) under slice 1 B1's ruling. Options: (a) recorded constants; (b) size
  tokens for them. **Recommended:** (a), like slice 4 (#4414) H7. **Affects:** CMP-022, 035, 042, 059, 085, §7.12.

### (c) Catalogue ambiguities (props, defaults, sizes)

- **J4 — One Kbd look.** Two merged specs draw it differently (§5.2). Options: (a) E10-D03's: `color.surface.raised`
  cap, `color.text.primary`, `type.num.xs`, a 1 px `color.border.strong` edge; (b) E15-D03's: `color.text.secondary`,
  `type.num.sm`, `radius.xs`; (c) one look that takes E10-D03's cap and edge, `radius.xs` and `type.num.xs` from both,
  and `color.text.secondary` from E15-D03 and E12-D04, because a hint is secondary to the label it follows in every
  host (a menu row's label is `color.text.primary`). **Recommended:** (c): 8.81 / 8.98 / 14.35:1 on raised and 8.14 /
  8.26 / 13.27:1 on overlay, with the cap edge decorative (1.80 / 1.46 / 1.80:1 on raised; the text, not the box, is the
  hint). **Affects:** CMP-022; E10-D03 and E15-D03 follow at their next revision.
- **J5 — Kbd keys, separators and the spoken form.** `15` gives `keys: string[]` and the expansion "Control plus Shift
  plus H" (`15:256`–`:257`); the keymap's bindings also use a digit range ("Alt+1..9") and pointer chords ("Ctrl+click",
  "Shift+wheel") (`apps/web/src/keymap/keymap.json`, the source of truth for default hotkeys, E49-T04). Options: (a) one
  `<kbd>` per key nested in an outer `<kbd>` (the HTML pattern for a key combination), no visible "+", the caps
  `space.inset.xs` apart; a range renders its two ends as caps with an en dash between them; a pointer chord renders its
  key caps and the pointer word as text; the outer `<kbd>` carries a visually hidden expansion whose key words come
  from one name table owned with the keymap (the catalogue gives "Control" and "Shift"; every other word is the
  keymap owner's, E10/E49, never written per screen); (b) a visible "+" between caps. **Recommended:** (a) — E15-D03
  draws "`Ctrl` `S`" without a "+" (`E15-D03.md:386`) and E39-D03 speaks "Control plus Shift plus K"
  (`E39-D03.md:155`). **Affects:** CMP-022; the keymap's name table (hand-off).
- **J6 — Countdown formats and the clock role.** `15` offers `mm:ss | words` (`15:384`). Options: (a) add `hh:mm:ss`
  (E24-D02 NG-5) and `approx` ("~4 s", E17-D02 G10), keep `words` for E39-D02's "in 9 h 58 m"; a count is plain text
  with `aria-live="off"`; a running **clock** that is not a deadline (E26-D02's replay clock) is the host's
  `role="timer"` region, outside CMP-035; (b) keep two formats and let hosts format. **Recommended:** (a). **Affects:**
  CMP-035; E24-D02, E17-D02 (their gaps answered when approved).
- **J7 — Countdown thresholds.** `15` says "defined thresholds (e.g. 60s, 10s, 0s)" (`15:385`); E30-D03 announces at
  0:10 and 0:00 only, with its own copy (`E30-D03.md:472`). Options: (a) a `thresholds?: number[]` prop (seconds,
  default `[60, 10, 0]`) and an `announce?: (s) => string` key from the host; each threshold speaks once, politely;
  crossing several at once (a tab returning from the background) speaks the latest only; (b) fixed thresholds.
  **Recommended:** (a). **Affects:** CMP-035.
- **J8 — KeyValueRow semantics and states.** `15` asks for `dt`/`dd` (`15:394`), which need a `dl` parent. Options:
  (a) rows render `<div>` + `<dt>` + `<dd>` and always sit in the host's `<dl>` (one `dl` per group; a single row is a
  `dl` of one); (b) rows render `role="group"` without `dl`. Plus (c) for a live row in `disconnected` /
  `reconnecting`, the value keeps `color.text.primary` and CMP-239's marker carries the state, rather than E08-D11 M25's
  `color.text.disabled` (2.86–4.31:1). **Recommended:** (a) and (c); (c) goes to E08-D11's owner as a request.
  **Affects:** CMP-036; E08-D11 M25.
- **J9 — Tabs: the selected look and activation.** Options: (a) CMP-042's selected tab is a 2 px `color.border.selected`
  bottom rule (`border.thick`) with the label `color.text.primary`, no fill (E29-D02, E40-D02; 4.89 / 4.13 / 6.66:1 on
  raised, 5.18 / 4.44 / 7.05:1 on canvas); unselected labels `color.text.secondary`; activation automatic by default
  (APG; E29-D02 D-17) with `activation: "manual"` for a host whose switch re-shapes a form or costs a fetch (E30-D04
  §7; E15-D02's WorkspaceTabStrip); CMP-103 keeps E30-D04's fill and `color.text.primary` rule as its own anatomy; (b)
  E30-D04's look for every tab strip. **Recommended:** (a): the rule is the non-colour carrier in both, and
  `aria-selected` carries it to assistive technology. **Affects:** CMP-042, CMP-103 (unchanged).
- **J10 — Tabs without a tab panel per tab.** `15` says "lazy-mount tabpanels retain focus correctly on switch"
  (`15:458`). Options: (a) one `tabpanel` per tab, each `aria-labelledby` its tab, the inactive panels `hidden` (or not
  mounted); a panel with no focusable content takes `tabindex="0"` so Tab reaches its content (APG); a switch never
  moves focus off the tab; (b) one shared panel re-labelled per tab. **Recommended:** (a). **Affects:** CMP-042.
- **J11 — Card surface and heading.** Options: (a) `surface: "elevated" | "flat"` (E25-D05's `static` and `flat`,
  `E25-D05.md:247`), `headingLevel?: 2 | 3 | 4 | 0` where 0 renders the title as plain text for a card inside a listbox
  option (E15-D05 A-4), and `region?: boolean` for a dashboard tile that is a landmark labelled by its heading (E42-D03,
  `E42-D03.md:253`); actions in the header's trailing slot; (b) the catalogue as is. **Recommended:** (a). **Affects:**
  CMP-050; E15-D05 A-4 (answered).
- **J12 — The palette's per-command reason and rows.** E10-D03 A12 asks for `commands[].disabledReason?` (E09-D09's key
  sentence) so a gated command renders T2 with the reason as its second line (`E10-D03.md:760`; E15-D02 §12), and draws
  rows 32 / 40 px. Options: (a) adopt A12 and E10-D03's row heights as palette data, and leave the dialog's title, the
  input's label, the listbox's name and the count sentence to E15, which implements SCR-012 (`E10-D03.md:281`) — no
  merged text writes them; (b) gated commands hidden. (b)
  contradicts `14` SCR-012's "RBAC-disabled entries greyed with a reason" (`14:357`) and D09's T2. **Recommended:** (a).
  **Affects:** CMP-059, CMP-213.
- **J13 — ThemeSwitcher's values.** Options: (a) three segments **Dark · Light · High contrast** (`15:647`; `16` §4's
  three presets, `16:137`), plus a separate CMP-004 Toggle for `16` §4's "match system" mode, off by default (`16:143`;
  its label is SCR-116's copy); the CVD-safe options of SCR-116 are a chart-palette choice, not a theme (E22-D03 D03-G2,
  `E22-D03.md:428`: no CVD theme ships); mapping to `22`'s `theme` + `high_contrast` is `themeFromSettings.ts`'s; (b)
  four segments with "System" as one. **Recommended:** (a): "match system" composes with a chosen theme, so it is a
  switch, not a fourth value; the accent and the chart palette stay SCR-116's other controls. **Affects:** CMP-062; `14`
  SCR-116's Type line (hand-off).
- **J14 — DensityToggle's values.** Options: (a) **Compact · Comfortable** globally (`16` §3's two modes, `16:109`; the
  runtime's two), with `dense` only for `scope: "panel"` on a chart panel (E11-D02 CR-8, `E11-D02.md:648`; E11-D05,
  `E11-D05.md:301`); `22`'s `spacious` is not offered and maps to Comfortable (`themeFromSettings.ts:15`); (b) three
  global values. **Recommended:** (a). **Affects:** CMP-063; `14` SCR-116's "cosy" and "spacious" (hand-off).

### (d) Behaviour proposals

- **J15 — Who may change the appearance.** `updateSettings` needs `settings:write` (`22-api-openapi.yaml:9803`), which a
  viewer never holds (`21-database-schema.md:4895`). Options: (a) the change always applies on this device through the
  runtime and its local store (`16:138`) for every role and in view-as (the actor's own presentation, `scope: self`); a
  session without `settings:write` simply skips the server save — no T2, no message; (b) T2 for a viewer: each option
  keeps its role, `aria-disabled`, the `lock`, the reason `rbac.permission` "Your role can't change settings." through
  CMP-079 (conventions 46). **Recommended:** (a): high contrast and density are accessibility needs (`05:79` gives
  high contrast a global hotkey), and the server still authorises its own record (C-12.4); (b) is drawn as an inset
  only if you choose it. Routed to D09's owner as a PROPOSED clarification of §2.1. **Affects:** CMP-062, CMP-063.
- **J16 — When an appearance change speaks and is counted.** Options: (a) conventions 45: a committed user change speaks
  once ("Theme changed to High Contrast", `15:648`; a density change with its scope, "Chart panel density: dense",
  `E11-D05.md:301`; the global density sentence is the host's key, none being written yet) and emits its event once; an
  arrow that moves selection in CMP-003 is a committed change (selection follows focus, slice 1 CMP-003), and the
  region's text is replaced, so a quick run speaks its last value; initial load, server-fed applies and a match-system
  flip speak and count nothing; (b) count only on leaving the control. **Recommended:** (a). **Affects:** CMP-062,
  CMP-063.
- **J17 — InfoPanel's two forms.** Options: (a) `variant: "drawer" | "inline"`: the drawer is CMP-046 `modal=false`
  (`15:712`; E25-D05 §3, `E25-D05.md:111`); the inline form is a disclosure inside its host that stays open while read
  (E12-D03 D3-8, DS-3, `E12-D03.md:53`, `:472`); (b) drawer only. **Recommended:** (a). **Affects:** CMP-069.
- **J18 — How the InfoPanel opens.** Options: (a) `Enter` or `Space` on the trigger (the CMP-227 chip, a `button` with
  `aria-haspopup="dialog"`) opens it; nothing inside a tooltip is operable; `Esc` from the drawer returns focus to the
  chip (`E25-D05.md:104`); (b) the catalogue's "from the chip's tooltip via `Enter`". **Recommended:** (a). **Affects:**
  CMP-069.
- **J19 — SkipLink targets.** `05` asks for a set ("Skip to order ticket" / "Skip to chart", `05:98`); `15` has one
  `targetId` (`15:869`) and `14` SCR-010 "skip link to main content" (`14:297`). Options: (a) `targets: { id, label
}[]`, "Skip to main content" always first, further links only for regions the route mounts (the order ticket, the
  chart), each its own link in DOM order before the TopBar; (b) one link. **Recommended:** (a). **Affects:** CMP-085.
- **J20 — The skip target.** Options: (a) activation moves focus to the target, which takes `tabindex="-1"` (removed on
  blur) and shows the CMP-039 ring while focused, and the next Tab continues from it; (b) scroll only. **Recommended:**
  (a): WCAG 2.4.1 needs the sequential focus to move, not only the viewport. **Affects:** CMP-085.
- **J21 — PreviewTile's kinds, source and states.** Options: (a) adopt E11-D03 D03-CR-3 (`source: "live" | "sample"`,
  `emptyText`, `errorText`, `kind` gains `"scales"`, `E11-D03.md:443`), E12-D05's chart-type and bar-mode previews
  (`E12-D05.md:546`) and E32-D04 D04-A2 (`kind: "ladder"`, `value`, `caption`, `E32-D04.md:37`), with five states —
  live, sample, empty, error, collapsed (E32-D04) — and never a spinner (E11-D03 D12); (b) the catalogue's four kinds.
  **Recommended:** (a). **Affects:** CMP-228.

### (e) The glyph set (§7.12)

- **J22 — Glyph names.** Options: (a) `icon/flatten-all`, `icon/chase-limit`, `icon/iceberg-order`, `icon/twap`,
  `icon/one-click-arm`, `icon/native-sl-shield` (E36-D02's name, `E36-D02.md:342`), `icon/estimated` (E25-D05 CR-3,
  `E25-D05.md:387`), `icon/node-trigger`, `icon/node-condition`, `icon/node-action`, `icon/node-logic-gate`,
  `icon/node-comment` and `icon/heatmap-convention-swap`: `16` §5's list in its own words, kebab-case; (b) shorter
  names. **Recommended:** (a). **Affects:** §7.12; E05-T06's registry.
- **J23 — The one-click-arm glyph and CMP-229.** Options: (a) `icon/one-click-arm` marks the 1-click trading toggle
  (`05:65`, "Toggle 1-click trading", "Shows persistent armed indicator"); CMP-229 ArmToggle keeps E30-D04's
  `icon/unlock` / `icon/lock` (`E30-D04.md:269`–`:270`); never two arm glyphs on one control; (b) alias
  `one-click-arm` to `unlock`. **Recommended:** (a). **Affects:** §7.12; E30-D04 (unchanged).
- **J24 — Small forms.** Slice 1 A10 is open (shipped 12 / 16 / 20 px; proposed 16 / 20 / 24). Options: (a) each
  custom glyph has its 24-unit master and, where its detail closes up at 12 px, a reduced 12 px form drawn to the same
  stroke (E25-D05 CR-3's precedent for `estimated`: a solid ring or "≈" alone at 12 px); the glyphs marked "16 px
  minimum" in §7.12 are never used at 12 px; (b) one drawing at every size. **Recommended:** (a). **Affects:** §7.12.
- **J25 — Node glyph colour.** Options: (a) the node-type glyphs are `currentColor` (the header's text token); the
  category hue rides the node's stripe in `color.node.*` (E37-D02, `E37-D02.md:169`), so the glyph never repeats a hue
  that measures 3.03:1 (`color.node.comment` on canvas, dark); (b) glyphs in `color.node.*`. **Recommended:** (a).
  **Affects:** §7.12; CMP-147..151 (unchanged).

### (f) Catalogue clauses held, and hand-offs

- **Held for `15`'s owner (this PR edits no `15` entry):** the "Catalogue alignment" paragraph of each §7 section —
  CMP-022 (J4, J5), CMP-035 (J1, J6, J7), CMP-036 (J8), CMP-042 (J9, J10), CMP-050 (J11), CMP-059 (J12), CMP-062 (J13,
  J15, J16), CMP-063 (J14, J15, J16), CMP-069 (J17, J18), CMP-085 (J19, J20), CMP-228 (J21) — and CMP-019's registry
  line for the 13 glyphs (J22–J25). A "no" on a J-row drops the clauses that cite it.
- **Hand-offs (outside this PR's write set):** the 13 glyphs to E05-T06 (#271), which draws, registers and tests them;
  `14` SCR-116's Type line and checklist ("cosy", "spacious", the CVD-safe themes; J13, J14) and `14` SCR-010's skip
  link line (J19) to their owner; E08-D11 M25 (J8 (c)), E17-D02 CR-5 (J1), E10-D03 §6.1's Kbd and E15-D03 §4.8 (J4),
  E24-D02 NG-5 and E17-D02 G10 (J6), D09 §2.1 (J15) and `16` §5's icon list, which E05-T06's DoD updates (J22).

## 7. Components

**Not drawn — the text is binding** (the board cap, §1). No section below has a Penpot build. CMP-022 and CMP-035 appear
on specimen board 09 as parts of CMP-041, CMP-016 and CMP-044 (slice 4 §1); every other cell is specified here only.

### CMP-022 · Kbd

**Catalogue (verbatim, `15:256-257`):**

- **Props**: `keys: string[]` (e.g. `["Ctrl","Shift","H"]`).
- **A11y**: `<kbd>` semantic element, visually-hidden expansion text for screen readers ("Control plus Shift plus H").

| Axis    | Values                              | Default |
| ------- | ----------------------------------- | ------- |
| Keys    | single, combo, range, pointer       | combo   |
| Surface | raised, overlay (tooltip, menu row) | raised  |

**Variants × States (5 cells; not drawn — board 09 shows it inside the menu row and the tooltip):**

| Cell          | Axes                       | What it shows                                                                                                     |
| ------------- | -------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| combo         | Keys=combo, Surface=raised | `Ctrl` `Shift` `K`, three caps `space.inset.xs` apart (E39-D03, `E39-D03.md:155`)                                 |
| single        | Keys=single                | `F` — one square cap (the keymap's "F" binding)                                                                   |
| range         | Keys=range                 | `Alt` `1`–`9`: the keymap's "Alt+1..9" form, the range ends as caps with an en dash (§6 J5)                       |
| in a menu row | Surface=overlay            | "Save as new layout… `Ctrl` `Shift` `S`", the caps right-aligned in the trailing slot (E15-D03, `E15-D03.md:386`) |
| remapped      | Keys=combo                 | a user binding with the word "remapped" beside it in `color.text.secondary` (SCR-013, `E10-D03.md:285`)           |

**Not drawn:** hover, focus, active, disabled (a Kbd is not interactive); unbound (nothing renders, conventions 40); a
conflict chip (CMP-244, proposed by E10-D03 §6.2, outside #161).

**Anatomy** (no density change: the cap follows its text line):

| Part      | Tokens                                                                                                                                                        |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| cap       | fill `color.surface.raised`, a 1 px `color.border.strong` edge (`border.hairline`, decorative), `radius.xs`; padding `space.inset.xs` inline; square at least |
| key text  | `type.num.xs` (JetBrains Mono, tabular), `color.text.secondary` (§6 J4): 8.81 / 8.98 / 14.35:1 on raised, 8.14 / 8.26 / 13.27:1 on overlay                    |
| gap       | `space.inset.xs` between caps; a range's en dash and a pointer word ("click") in `type.ui.caption`, `color.text.secondary`                                    |
| expansion | visually hidden text inside the outer `<kbd>` ("Control plus Shift plus K")                                                                                   |

**Keyboard:** none of its own (not an APG widget; never focusable). Its host's keys apply.

**Accessible name and role:**

| Element     | Role            | Name                                                                                           | ARIA                                                                                                               |
| ----------- | --------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| outer `kbd` | none (semantic) | the visually hidden expansion, read as text                                                    | the visible caps are `aria-hidden="true"` so the expansion is read once, never "Ctrl K"                            |
| inner `kbd` | none            | —                                                                                              | one per key (the HTML pattern for a combination, §6 J5)                                                            |
| in a menu   | —               | the item's name stays its label; the hint is its `aria-keyshortcuts` value ("Control+Shift+S") | the whole Kbd is `aria-hidden="true"` there, so the expansion never joins the item's name (CMP-041's row, slice 4) |

**Focus:** never. **Motion:** none. **Live region:** none. **T2 and not T2:** not a control; it has no gated state, and
a gated command's hint stays as drawn (its row carries T2, conventions 46). **Hit target:** none. **Resize & overflow:**
the cap grows with the text scale; caps never wrap apart from each other. **Forced colors:** the caps keep a CanvasText
1 px border, the text CanvasText (conventions 48).

**Catalogue alignment (held, §6 (f)):** Props say `keys` holds the keymap's display form, ranges and pointer chords
included (J5); A11y adds the visible caps hidden, the keymap's name table and `aria-keyshortcuts` on a host item (J5);
Tokens become the anatomy's (`type.num.xs` for `font.mono`, `color.text.secondary`, `color.border.strong`, J4);
Storybook adds Range, InMenuRow, Remapped.

### CMP-035 · Countdown

**Catalogue (verbatim, `15:384-385`):**

- **Props**: `expiresAt: number` (epoch ms) · `format: "mm:ss"|"words"` · `onExpire?`.
- **A11y**: `aria-live="off"` visually (updates every second would flood SR) with a discrete polite announcement only at defined thresholds (e.g. 60s, 10s, 0s) — documented pattern reused wherever a countdown appears, except countdowns in a grid column, which announce nothing (SCR-100 "Funding in", E08-D07 D22, §4.5).

| Axis   | Values                            | Default |
| ------ | --------------------------------- | ------- |
| Format | mm:ss, hh:mm:ss, words, approx    | mm:ss   |
| Phase  | running, under threshold, expired | running |

**Variants × States (7 cells; not drawn — board 09 shows "Cancels in 0:20" in the order confirm):**

| Cell            | Axes                        | What it shows                                                                                                    |
| --------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| default         | Format=mm:ss, Phase=running | "Cancels in 0:20" (`confirm.countdown`, E30-D03, `E30-D03.md:472`), the digits `type.num.sm`                     |
| under threshold | Phase=under threshold       | "Cancels in 0:09" with the CMP-019 `clock` glyph leading the digits in `color.status.warning.strong` (§6 J1 (c)) |
| expired         | Phase=expired               | the host's outcome replaces it (SCR-076 cancels and closes), the countdown unmounted (conventions 47)            |
| hh:mm:ss        | Format=hh:mm:ss             | "Funding in 07:58:12" (E24-D02 NG-5, §6 J6)                                                                      |
| words           | Format=words                | "until 00:00 UTC, in 9 h 58 m" — the absolute time first (E39-D02, `E39-D02.md:179`; conventions 41)             |
| approx          | Format=approx               | "Next try in ~4 s" (E17-D02, `E17-D02.md:279`)                                                                   |
| in a grid       | Format=mm:ss                | a SCR-100 "Funding in" cell: same digits, no announcement at any threshold (`15:385`)                            |

**Not drawn:** hover, focus, disabled (not interactive); paused (a countdown never pauses; a host that stops the clock
— SCR-076 restarting on any key or pointer event, slice 4 (#4414) conventions 34 — re-mounts it with a new `expiresAt`).

**Anatomy:** the host's sentence in its own `type.ui.*` style and colour, the digits `type.num.sm` (or the host's
`type.num.*` size) in the same colour, tabular so the width never changes (conventions 41); under the threshold the
`clock` glyph at `size.icon`, `color.status.warning.strong`, `space.inset.xs` before the digits. No density change.

**Keyboard:** none of its own (not focusable; a focusable host such as SCR-076's footer owns the keys).

**Accessible name and role:**

| Element         | Role            | Name / text                                                                                                              | ARIA                                                                                                     |
| --------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| the count       | none (text)     | its words, read on demand: "Cancels in 20 seconds unless you act" (the spoken form, `E30-D03.md:472`)                    | `aria-live="off"`; the visible "0:20" is `aria-hidden="true"` and a visually hidden twin holds the words |
| the announcer   | status (polite) | at each threshold once: the host's key, e.g. `confirm.countdown.announce10` "10 seconds until this confirmation cancels" | pre-rendered empty with its host (slice 4 (#4414) conventions 33); latest only (§6 J7)                   |
| the clock glyph | none            | —                                                                                                                        | `aria-hidden="true"` (the words carry it)                                                                |

**Focus:** never moves focus, at a threshold or at expiry (`05:96`). **Motion:** none: digits swap once a second in both
modes (`E39-D02.md:191`). **Live region:** thresholds only, polite, once each; never per tick; in a grid column none.
**T2 and not T2:** no gated state; expiry is an outcome (conventions 47). **Hit target:** none. **Resize & overflow:**
tabular digits keep the width; the sentence wraps before the digits split. **Forced colors:** CanvasText; the glyph
`currentColor` (conventions 48).

**Catalogue alignment (held, §6 (f)):** Props `format: "mm:ss" | "hh:mm:ss" | "words" | "approx"` (J6), `thresholds?:
number[]` and `announce?` (J7); A11y adds the spoken twin, latest-only on a multi-threshold crossing, and a running
clock as the host's `role="timer"` (J6); Tokens become `type.num.*` and the `clock` glyph in
`color.status.warning.strong` (J1); Storybook adds HhMmSs, Approx, InGrid.

### CMP-036 · KeyValueRow

**Catalogue (verbatim, `15:393-394`):**

- **Props**: `label` · `value: ReactNode` · `emphasis?: boolean` · `freshness?: DataConfidenceState` (renders CMP-239 FreshnessMarker beside `value` for live fields — see E08-D04).
- **A11y**: renders as definition-list pair (`dt`/`dd`) semantics for screen-reader table-like traversal.

| Axis      | Values                | Default |
| --------- | --------------------- | ------- |
| Emphasis  | off, on               | off     |
| Value     | number, text, missing | number  |
| Freshness | none, live, stale     | none    |
| Layout    | inline, stacked       | inline  |

**Variants × States (7 cells; not drawn):**

| Cell     | Axes                                      | What it shows                                                                                                            |
| -------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| default  | Emphasis=off, Value=number, Layout=inline | a preview row "Liquidation" with its price (E30-D04 §11's rows, `E30-D04.md:406`), value end-aligned, one baseline       |
| emphasis | Emphasis=on                               | the same pair with the value one step up: a number `type.num.md`, a text `type.ui.body-strong` (`(heuristic)`, PROPOSED) |
| text     | Value=text                                | a text value, as in E27-D03's key block (`E27-D03.md:890`)                                                               |
| missing  | Value=missing                             | "Funding · —", the "—" in `color.text.secondary` (conventions 42)                                                        |
| live     | Freshness=live                            | the value with CMP-239's marker beside it (E08-D04; motion E08-D11 M17, `E08-D11.md:135`)                                |
| stale    | Freshness=stale                           | the value kept in `color.text.primary`, CMP-239's stale marker and word beside it; no value-change emphasis (`15:398`)   |
| stacked  | Layout=stacked                            | the value under its label, for a narrow host or 150 % text (conventions 49)                                              |

**Not drawn:** hover, focus, disabled (not interactive; a value that is a link nests CMP-021, which owns them); every
CMP-239 state beyond live and stale (E08-D11's M25–M27 are its own frames: `disconnected` / `reconnecting`,
`backfilling`, `delisted`).

**Anatomy:**

| Part   | Tokens                                                                                                                                                            |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| row    | min-height `size.row.height` (24 / 32 px); gap `space.inset.sm`; rows `space.stack.xs` apart                                                                      |
| label  | `type.ui.label`, `color.text.secondary` (9.33 / 9.65 / 15.20:1 on canvas, 8.81 / 8.98 / 14.35:1 on raised)                                                        |
| value  | a number `type.num.base` (or the host's `type.num.*` size), any other value `type.ui.body`; `color.text.primary` (15.20 / 16.78 / 17.21:1 on canvas); end-aligned |
| marker | CMP-239 beside the value, `space.inset.xs` before it                                                                                                              |

**Keyboard:** none of its own (not focusable); a nested link or button owns its keys.

**Accessible name and role:**

| Element | Role              | Name                        | ARIA                                                                                                        |
| ------- | ----------------- | --------------------------- | ----------------------------------------------------------------------------------------------------------- |
| list    | (the host's `dl`) | the host's heading          | one `dl` per group (§6 J8 (a))                                                                              |
| row     | none (`div`)      | —                           | wraps one `dt` and one `dd`                                                                                 |
| label   | term (`dt`)       | its text                    | —                                                                                                           |
| value   | definition (`dd`) | its text, the unit included | an unavailable "—" is never read as a dash: the host's state word (CMP-239's, on a live row) is in the `dd` |

**Focus:** never. **Motion:** E08-D11's (`15:398`): a live field settles once through CMP-239; nothing else moves.
**Live region:** none of its own: a host that must announce a computed value uses one polite region at most one update
per 2 s, latest only (CMP-121's line, `15:1381`). **T2 and not T2:** not a control; no gated state (conventions 47).
**Hit target:** none. **Resize & overflow:** the stacked layout at 150 % text or a narrow host; a value never truncates
— a long text value wraps, a number never wraps. **Forced colors:** CanvasText for both; CMP-239's word carries its
state (conventions 48).

**Catalogue alignment (held, §6 (f)):** A11y adds the host's `dl` and the "—" read as a state word (J8 (a)); Tokens
become the anatomy's (`space.inset.*` and `type.ui.label` / `type.ui.body` / `type.num.*` for `space.row.*` and
`font.size.body/label`); Props add `layout?: "inline" | "stacked"`; Storybook adds Missing, Stale, Stacked.

### CMP-042 · Tabs

**Catalogue (verbatim, `15:457-458`):**

- **Props**: `tabs: {id,label,icon?}[]` · `value` · `onChange` · `orientation`.
- **A11y**: WAI-ARIA Tabs pattern (`role=tablist/tab/tabpanel`), arrow-key nav, `aria-selected`, lazy-mount tabpanels retain focus correctly on switch.

| Axis        | Values                                                        | Default    |
| ----------- | ------------------------------------------------------------- | ---------- |
| Orientation | horizontal, vertical                                          | horizontal |
| Icons       | none, leading                                                 | none       |
| State       | default, hover, focus-visible, selected, disabled-with-reason | default    |

**Variants × States (8 cells; not drawn):**

| Cell              | Axes                               | What it shows                                                                                                                                                                                   |
| ----------------- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| default           | Orientation=horizontal, Icons=none | "Positions · Working orders · Fills · Trade groups · Algos" (E29-D02, `E29-D02.md:166`), Positions selected                                                                                     |
| hover             | State=hover                        | an unselected tab on `color.surface.hover`, its label `color.text.primary`                                                                                                                      |
| focus-visible     | State=focus-visible                | the CMP-039 ring on the focused tab                                                                                                                                                             |
| selected          | State=selected                     | the 2 px `color.border.selected` bottom rule and the label `color.text.primary` (§6 J9)                                                                                                         |
| vertical          | Orientation=vertical               | settings sections in a column, the rule on the trailing edge                                                                                                                                    |
| with icons        | Icons=leading                      | a CMP-019 glyph before each label, decorative                                                                                                                                                   |
| gated (T2)        | State=disabled-with-reason         | a tab whose section the session may not open: the `lock` leads the full label in `color.text.tertiary`, the reason line under the strip (conventions 46; E30-D04 §7's T2 row, `E30-D04.md:341`) |
| manual activation | State=focus-visible                | focus on "Limit" while "Market" stays selected, for a host that sets `activation: "manual"` (§6 J9)                                                                                             |

**Not drawn:** active (a press selects at once); plain disabled (a tab is either gated, T2, or available — an emulated
order type is CMP-103's validity look, conventions 47); a count badge (conventions 43); loading (the tab panel's own
state, CMP-015 or CMP-026 inside it).

**Anatomy:**

| Part          | Tokens                                                                                                                                                                                       |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| tablist       | min-height `size.control.height` (24 / 32 px), on its host surface; a 1 px `color.border.default` line under the strip (decorative)                                                          |
| tab           | padding `space.inset.sm` inline (compact) / `space.inset.md` (comfortable) (E30-D04, `E30-D04.md:345`); `type.ui.label`; unselected `color.text.secondary` (8.81 / 8.98 / 14.35:1 on raised) |
| selected rule | 2 px `color.border.selected` (`border.thick`), flush with the strip's bottom edge: 4.89 / 4.13 / 6.66:1 on raised, 5.18 / 4.44 / 7.05:1 on canvas                                            |
| icon          | CMP-019 at `size.icon`, `space.inset.xs` before the label, `currentColor`                                                                                                                    |
| reason        | (gated) `type.ui.caption`, `color.text.secondary`, under the strip, the gated tab's `aria-describedby`                                                                                       |

**Keyboard** (WAI-ARIA APG Tabs pattern; automatic activation unless the host sets manual):

| Keys                            | Action                                                                                                                        |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Tab                             | Into the tablist onto the selected tab (roving `tabindex`); the next Tab goes into the tab panel (§6 J10)                     |
| → / ← (↓ / ↑ when vertical)     | Next / previous tab, wrapping; automatic: selects it; manual: moves focus only                                                |
| Home / End                      | First / last tab, as the arrows                                                                                               |
| Enter / Space                   | Manual: selects the focused tab; automatic: nothing more                                                                      |
| any of the above on a gated tab | Focus lands on it; nothing is selected; the reason is re-shown inline with one polite announcement (D09 §9.3; conventions 46) |

**Accessible name and role:**

| Element | Role     | Name                                       | ARIA                                                                                                      |
| ------- | -------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| tablist | tablist  | the host's label ("Order type", "Blotter") | `aria-orientation` when vertical                                                                          |
| tab     | tab      | its visible label                          | `aria-selected`, `aria-controls` its panel; gated: `aria-disabled="true"` + `aria-describedby` the reason |
| panel   | tabpanel | from its tab (`aria-labelledby`)           | `tabindex="0"` when it holds nothing focusable (§6 J10)                                                   |
| lock    | img      | "Not available"                            | CMP-019 `decorative=false` (gated tab only)                                                               |

**Focus:** a switch never moves focus off the tab; a lazy-mounted panel mounts without stealing it (`15:458`).
**Motion:** none: selection and the panel swap are cuts in both modes (E30-D04 §7's motion row, `E30-D04.md:346`).
**Live region:** none. **T2 and not T2:** a tab gated by role, grant or state is T2 (conventions 46); an unavailable
type (CMP-103's emulated tab) is availability, not T2 (conventions 47). **Hit target:** each tab at least
`size.control.height` tall and 24 px wide. **Resize & overflow:** the strip scrolls horizontally, never wraps or hides a
tab (conventions 49); vertical tabs wrap their labels. **Forced colors:** the selected rule Highlight, labels
ButtonText, the focus ring Highlight (conventions 48).

**Catalogue alignment (held, §6 (f)):** Props add `activation?: "automatic" | "manual"` and a per-tab `disabledReason?`
through CMP-079 (J9, conventions 46); A11y adds the panel `tabindex`, focus kept on switch and the T2 tab (J10); Tokens
become the anatomy's (`color.border.selected` for `color.action.selected`, `space.inset.*` for `space.tabs.*`);
Storybook adds ManualActivation and GatedTab.

### CMP-050 · Card

**Catalogue (verbatim, `15:538-539`):**

- **Props**: `title?` · `actions?: ReactNode` · `padding` · `children`.
- **A11y**: heading semantics if `title` present.

| Axis    | Values                       | Default  |
| ------- | ---------------------------- | -------- |
| Surface | elevated, flat               | elevated |
| Header  | none, title, title + actions | title    |
| Padding | panel, none                  | panel    |

**Variants × States (5 cells; not drawn):**

| Cell         | Axes                           | What it shows                                                                                                     |
| ------------ | ------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| default      | Surface=elevated, Header=title | a titled card on `color.surface.canvas`, `elevation.card` (E25-D05 `static`, `E25-D05.md:247`)                    |
| flat         | Surface=flat                   | the same card with a 1 px `color.border.default` hairline and no shadow (E25-D05 `flat`)                          |
| with actions | Header=title + actions         | the title left and a CMP-002 `more-horizontal` and a CMP-001 secondary right, in the header row                   |
| no padding   | Padding=none                   | a card whose child is a CMP-049 table edge to edge                                                                |
| region tile  | Header=title                   | an admin home tile: the heading is a CMP-021 link and the card a `region` named by it (E42-D03, `E42-D03.md:253`) |

**Not drawn:** hover, focus, selected (a card is not interactive; a card that is a listbox option takes its option's
states from its host, E15-D05 §6.2, and a card that opens a detail puts one link or button in its header, never makes
the whole box clickable `(heuristic)`); loading, empty and error (the content's: CMP-015, CMP-026 and CMP-027 inside the
body, as E42-D03's tiles compose them).

**Anatomy:**

| Part    | Tokens                                                                                                                                                                                         |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| surface | `color.surface.raised` (1.06 / 1.07 / 1.06:1 on canvas; decorative, conventions 44), `radius.card`; elevated `elevation.card`; flat a 1 px `color.border.default` hairline (`border.hairline`) |
| header  | min-height `size.control.height`; title `type.ui.heading-sm`, `color.text.primary` (14.35 / 15.62 / 16.25:1); actions trailing, `space.inset.xs` apart                                         |
| body    | padding `space.panel.padding` (Padding=panel) or 0; header-to-body `space.stack.sm`                                                                                                            |

**Keyboard:** none of its own; its actions and content own their keys and keep DOM order (header, then body).

**Accessible name and role:**

| Element | Role                                   | Name                            | ARIA                                                                                         |
| ------- | -------------------------------------- | ------------------------------- | -------------------------------------------------------------------------------------------- |
| card    | none, or `region` when `region` is set | the heading (`aria-labelledby`) | a region only for a landmark-worthy tile (§6 J11)                                            |
| title   | heading at `headingLevel` (2–4)        | its text                        | `headingLevel: 0` renders plain text inside a listbox option (E15-D05 A-4, `E15-D05.md:514`) |
| actions | their own                              | their own                       | an icon-only action's `aria-label` includes the card's title (CMP-002's rule)                |

**Focus:** none of its own. **Motion:** none. **Live region:** none of its own. **T2 and not T2:** a container: its
gated actions take T2 themselves (conventions 46). **Hit target:** its actions'. **Resize & overflow:** the title wraps
before the actions move under it (conventions 49); the body scrolls only if its host fixes the height. **Forced
colors:** a CanvasText 1 px border in both surfaces, because the shadow and the fill step are lost (conventions 48).

**Catalogue alignment (held, §6 (f)):** Props add `surface?: "elevated" | "flat"`, `headingLevel?: 2 | 3 | 4 | 0` and
`region?: boolean` (J11); A11y adds the option and region readings; Tokens become `radius.card`, `elevation.card` and
`border.hairline` + `color.border.default` (for `radius.lg`, `elevation.1`); Storybook adds Flat, RegionTile, InOption.

### CMP-059 · CommandPalette

**Catalogue (verbatim, `15:620-621`):**

- **Props**: `open` · `onOpenChange` · `commands: {id,label,group,shortcut?,onRun}[]`.
- **A11y**: Combobox+Listbox pattern inside a modal Dialog; results grouped with `role="group"` + group labels; live region announces result count.

| Axis  | Values                              | Default |
| ----- | ----------------------------------- | ------- |
| Query | empty, typed, no match              | empty   |
| Row   | default, active, destructive, gated | default |

**Variants × States (7 cells; not drawn — E10-D03 §6.1 owns SCR-012's look, `E10-D03.md:281`):**

| Cell        | Axes            | What it shows                                                                                                                                                              |
| ----------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| empty query | Query=empty     | Recent (the last five, newest first) and Suggested (role-aware, most used first)                                                                                           |
| results     | Query=typed     | the groups Navigate · Panel · Symbol · Action · Setting; an empty group has no header; each row's CMP-022 hint trailing                                                    |
| active row  | Row=active      | the active option on `color.surface.selected` with the CMP-039 ring (`aria-activedescendant`)                                                                              |
| destructive | Row=destructive | the `warning` glyph in `color.status.warning.strong` and the tag "confirms"; running it opens its confirmation, never fires (`14:356`)                                     |
| gated (T2)  | Row=gated       | a Viewer's write command in its group: `lock`, the full label in `color.text.tertiary`, the reason line "Your role can't change positions." in `color.text.secondary` (2a) |
| no results  | Query=no match  | "No command or symbol matches 'xyz'" (`14:357`) and a suggestion; no headers                                                                                               |
| group run   | Query=typed     | the footer hint "`Ctrl+Enter` runs for every account in the group" with CMP-022 caps (`E10-D03.md:281`)                                                                    |

**Not drawn:** closed; the opening and closing motion (slice 4 (#4414) conventions 35: the scrim fades, the card is a
cut); a loading row for the symbol search (no source names one; E10-D03 is silent, recorded for E15).

**Anatomy** (E10-D03 §6.1, followed; slice 4's dialog for the frame):

| Part         | Tokens                                                                                                                                                             |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| surface      | CMP-043 frame: `color.surface.overlay`, `elevation.dialog`, `radius.dialog`, 640 px wide, centred under the TopBar, over slice 4's scrim                           |
| input        | `type.ui.body`, `color.text.primary`; placeholder `color.text.tertiary` (5.20 / 5.44 / 10.36:1 on overlay)                                                         |
| group header | `type.ui.caption`, `color.text.tertiary` (5.20 / 5.44 / 10.36:1)                                                                                                   |
| row          | 32 px compact, 40 px comfortable (§5.1); `type.ui.body`, `color.text.primary` (13.27 / 14.37 / 15.02:1); active `color.surface.selected` (10.17 / 12.82 / 11.51:1) |
| tag, footer  | `type.ui.caption`; the footer hint `color.text.secondary` (8.14 / 8.26 / 13.27:1)                                                                                  |
| gated row    | `lock` + label `color.text.tertiary`, reason `color.text.secondary` (conventions 46)                                                                               |

**Keyboard** (WAI-ARIA APG Combobox with a listbox popup, inside the APG Dialog (Modal) pattern):

| Keys       | Action                                                                                                                                             |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ctrl+K     | Opens it, focus in the input (`05:85`: reserved, not remappable); pressed again while open, closes it (`(heuristic)`, PROPOSED)                    |
| typing     | Filters; the first result becomes active; the count speaks once the results settle                                                                 |
| ↓ / ↑      | Moves the active option, skipping group headers, wrapping; focus stays in the input (`aria-activedescendant`)                                      |
| Enter      | Runs the active command (a destructive one opens its confirmation); on a gated command, nothing runs and the reason is re-shown and announced once |
| Ctrl+Enter | Runs against every account in the active group (`14:356`); gated as Enter                                                                          |
| Esc        | Closes it and returns focus to the element that had it (slice 4 (#4414) conventions 32; `05:85`: `Esc` is the universal cancel)                    |
| Tab        | Stays in the dialog (a trap); the input is the only stop                                                                                           |

**Accessible name and role:**

| Element | Role            | Name                                                        | ARIA                                                                                                                       |
| ------- | --------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| dialog  | dialog          | E15's title key (§6 J12)                                    | `aria-modal="true"`                                                                                                        |
| input   | combobox        | E15's label key (§6 J12)                                    | `aria-expanded="true"`, `aria-controls` the listbox, `aria-activedescendant` the active option, `aria-autocomplete="list"` |
| listbox | listbox         | E15's key (§6 J12)                                          | —                                                                                                                          |
| group   | group           | its header ("Action")                                       | `aria-labelledby` the header                                                                                               |
| option  | option          | the label, then the tag ("Flatten all positions, confirms") | gated: `aria-disabled="true"` + `aria-describedby` the reason; the Kbd hidden, its keys in `aria-keyshortcuts`             |
| count   | status (polite) | E15's count sentence                                        | pre-rendered; once per settled query (`14:358`)                                                                            |

**Focus:** stays in the input throughout; return on close per slice 4 (#4414) conventions 32. **Motion:** slice 4's
dialog recipe. **Live region:** the count, polite, once per settled query; nothing per keystroke. **T2 and not T2:** a
gated command is T2 (2a, through CMP-079 and the per-command reason, §6 J12); view-as first, never on a C-2.6 protective
command ("Cancel all orders on this account…" stays enabled while viewing as, `E10-D03.md:281`); an `admin.*` command is
absent for a session without it (T3, `E09-D09.md:175`); no match is availability (conventions 47). **Hit target:** rows
32 / 40 px. **Resize & overflow:** at 200 % it fills the viewport, the input and footer sticky, the results scrolling
(conventions 49). **Forced colors:** the active row Highlight with HighlightText; the gated label CanvasText with its
lock and reason (conventions 48).

**Catalogue alignment (held, §6 (f)):** Props add `commands[].disabledReason?`, `destructive?` and `kbd` from the
keymap (J12, conventions 40); A11y adds the keys above, the option name with its tag and the count's once-per-query
rule; Tokens become `elevation.dialog`, `radius.dialog` and the rows' (for `elevation.4`); Storybook adds EmptyQuery,
RbacDisabled, Destructive (E10-D03's list, `E10-D03.md:563`).

### CMP-062 · ThemeSwitcher

**Catalogue (verbatim, `15:647-648`):**

- **Props**: `value: "dark"|"light"|"high-contrast"` · `onChange`.
- **A11y**: CMP-003 SegmentedControl composition; changes announced via polite live region ("Theme changed to High Contrast").

| Axis  | Values                                  | Default |
| ----- | --------------------------------------- | ------- |
| Value | dark, light, high-contrast              | dark    |
| State | default, focus-visible, match system on | default |

**Variants × States (5 cells; not drawn):** each cell shows the control in the theme it selects, because the switch
re-themes the page within one frame (conventions 45).

| Cell            | Axes                  | What it shows                                                                                                                                                               |
| --------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| dark            | Value=dark            | CMP-003 with three segments, Dark checked (`16` §4: dark is the default, `16:137`)                                                                                          |
| light           | Value=light           | Light checked, the control in the light theme                                                                                                                               |
| high contrast   | Value=high-contrast   | High contrast checked, the control in the high-contrast theme                                                                                                               |
| focus-visible   | State=focus-visible   | the CMP-039 ring on the checked segment (slice 1 CMP-003)                                                                                                                   |
| match system on | State=match system on | the CMP-004 toggle on and the segment the system resolves to checked; the segments stay operable, and choosing one turns match system off (`(heuristic)`, PROPOSED, §6 J13) |

**Not drawn:** hover, disabled and the gated form (slice 1 CMP-003 owns them; the gated form exists only under §6 J15
(b), as CMP-003's disabled-with-reason with the `lock` and "Your role can't change settings."); the CVD-safe and accent
choices of SCR-116 (other controls, §6 J13).

**Anatomy:** slice 1 CMP-003's, unchanged (`size.control.height`, the `color.action.selected` fill with its
`color.border.selected` outline, labels `type.ui.label`); the "match system" toggle is slice 1 CMP-004 beside it,
`space.inset.sm` apart. No token of its own (`15:649` "n/a").

**Keyboard** (WAI-ARIA APG Radio Group, through CMP-003; slice 1's table applies): Tab to the checked segment; arrows,
`Home` and `End` move and check (selection follows focus), and each check is a committed change (§6 J16); `Space`
checks; Tab on to the toggle. `Ctrl+Shift+H` toggles high contrast from anywhere (`05:79`) and takes the same path.

**Accessible name and role:**

| Element   | Role            | Name                                                     | ARIA                                                                      |
| --------- | --------------- | -------------------------------------------------------- | ------------------------------------------------------------------------- |
| group     | radiogroup      | the SCR-116 field label (its copy)                       | as CMP-003                                                                |
| segment   | radio           | "Dark" · "Light" · "High contrast" (the values in words) | `aria-checked`                                                            |
| toggle    | switch          | SCR-116's label for "match system"                       | CMP-004's                                                                 |
| announcer | status (polite) | "Theme changed to High Contrast" (`15:648`)              | pre-rendered; once per committed change; nothing on load or a system flip |

**Analytics (#161 Observability; `14:2366`):** `appearance.theme_changed`, once per committed user change (a segment,
the toggle, `Ctrl+Shift+H`); never on the initial load, a server-fed apply (`track: false`, `16:138`) or a match-system
flip (§6 J16). The payload is the analytics owner's.

**Focus:** stays on the segment; the re-theme never moves it. **Motion:** none: the swap is instant in both modes
(`16:138`; `14:2365`). **Live region:** one polite sentence per committed change. **T2 and not T2:** none under §6 J15
(a), recommended; under (b) the T2 form of conventions 46. **Hit target:** CMP-003's. **Resize & overflow:** CMP-003's.
**Forced colors:** CMP-003's; in forced colours the theme choice still applies to the non-forced parts (the chart
canvas), so the control keeps working (conventions 48).

**Catalogue alignment (held, §6 (f)):** Props keep the three values and add the "match system" toggle beside them (J13);
A11y adds the committed-change rule and `Ctrl+Shift+H` (J16); a new **Analytics** line names `appearance.theme_changed`
and its trigger; Storybook adds MatchSystem, Light, HighContrast.

### CMP-063 · DensityToggle

**Catalogue (verbatim, `15:656-657`):**

- **Props**: `value: "comfortable"|"compact"` · `scope: "global"|"panel"` · `onChange`.
- **A11y**: CMP-003 composition; per-panel override announced with scope context.

| Axis  | Values                                    | Default   |
| ----- | ----------------------------------------- | --------- |
| Scope | global, panel                             | global    |
| Value | compact, comfortable, dense (chart panel) | compact   |
| Form  | segmented, menu                           | segmented |

**Variants × States (6 cells; not drawn):**

| Cell              | Axes                        | What it shows                                                                                             |
| ----------------- | --------------------------- | --------------------------------------------------------------------------------------------------------- |
| global            | Scope=global, Value=compact | CMP-003 Compact · Comfortable on SCR-116 (`16:109`)                                                       |
| comfortable       | Value=comfortable           | Comfortable checked, the control at comfortable density                                                   |
| panel             | Scope=panel                 | a per-panel override in a panel's settings, with the scope in the group label                             |
| chart panel dense | Scope=panel, Value=dense    | three segments on a chart panel, Dense checked (E11-D02 CR-8; E11-D05, `E11-D05.md:301`)                  |
| menu form         | Form=menu                   | "Density: Compact / Comfortable" as a `menuitemradio` pair in a panel menu (E22-D02 K9, `E22-D02.md:295`) |
| focus-visible     | Form=segmented              | the CMP-039 ring on the checked segment                                                                   |

**Not drawn:** hover, disabled, gated (CMP-003's and CMP-041's; the gated form only under §6 J15 (b)); spacious and
cosy (§6 J14).

**Anatomy:** CMP-003's (segmented) or CMP-041's checkable items (menu), unchanged; no token of its own (`15:658`).

**Keyboard:** segmented — the APG Radio Group through CMP-003 (selection follows focus; each check commits, §6 J16);
menu — the APG Menu through CMP-041: arrows move, `Enter` / `Space` check the `menuitemradio` and close the menu (slice
4 (#4414) CMP-041).

**Accessible name and role:**

| Element   | Role                       | Name                                                                                | ARIA                      |
| --------- | -------------------------- | ----------------------------------------------------------------------------------- | ------------------------- |
| group     | radiogroup (or menu group) | the field label; with scope, it names the scope (the panel's name)                  | as CMP-003 / CMP-041      |
| option    | radio / menuitemradio      | "Compact" · "Comfortable" · "Dense"                                                 | `aria-checked`            |
| announcer | status (polite)            | with scope: "Chart panel density: dense" (`E11-D05.md:301`); global: the host's key | once per committed change |

**Analytics (#161 Observability; `14:2366`):** `appearance.density_changed`, once per committed user change, global or
per panel; never on load or a server-fed apply (§6 J16). The payload — scope included — is the analytics owner's.

**Focus:** stays on the option (segmented) or returns to the menu's trigger (menu). **Motion:** none; the density swap
is a custom-property change in one frame and never remounts a panel (`14:2365`; `16` §3 rule 1, `16:125`). **Live
region:** one polite sentence per committed change. **T2 and not T2:** as CMP-062 (§6 J15). **Hit target:** CMP-003's or
CMP-041's. **Resize & overflow:** theirs. **Forced colors:** theirs (conventions 48).

**Catalogue alignment (held, §6 (f)):** Props `value: "compact" | "comfortable" | "dense"`, `dense` only with
`scope: "panel"` on a chart panel (J14, E11-D02 CR-8) and `form?: "segmented" | "menu"`; A11y adds the scope in the name
and the committed-change rule (J16); a new **Analytics** line names `appearance.density_changed`; Storybook adds
ChartPanelDense, MenuForm.

### CMP-069 · InfoPanel

**Catalogue (verbatim, `15:711-712`):**

- **Props**: `title` · `content: ReactNode` · `relatedDetector?: string`.
- **A11y**: opens as CMP-046 Drawer (non-modal), triggerable from the chip's tooltip via `Enter`.

| Axis    | Values                          | Default |
| ------- | ------------------------------- | ------- |
| Variant | drawer, inline                  | drawer  |
| State   | open, loading, error, collapsed | open    |

**Variants × States (5 cells; not drawn):**

| Cell             | Axes                       | What it shows                                                                                                                            |
| ---------------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| drawer · open    | Variant=drawer, State=open | SCR-058 at a detector's section: the plain-language summary first, the technical detail second (`14:1350`), the detector's name as title |
| drawer · loading | State=loading              | the title and CMP-015 text rows while `GET /api/v1/detectors/config` answers (`14:1354`); the static text shows at once                  |
| drawer · error   | State=error                | the static methodology kept; the current parameter values replaced by a CMP-027 inline error with Retry                                  |
| inline · open    | Variant=inline, State=open | E12-D03's About bar modes: the panel under its trigger row, outside the menu, focus on its heading (E12-D03 §6.4, `E12-D03.md:293`)      |
| inline · closed  | State=collapsed            | the trigger with `aria-expanded="false"`; nothing else renders                                                                           |

**Not drawn:** the drawer's open and close motion and its non-modal frame (slice 4 (#4414) CMP-046, unchanged); a gated
state (a container; a link inside it that the session may not follow is the host's — E12-D03's route is CMP-079's
sentence form without `recording:write`, `E12-D03.md:472`).

**Anatomy:** the drawer form is slice 4 CMP-046 `modal=false` (480 px, `elevation.popover` per slice 4 H31, a CMP-002
close), with the title `type.ui.heading-sm` and the body `type.ui.body` in `color.text.primary`, links CMP-021; the
inline form sits on its host's surface with `space.inset.sm` padding and a 1 px `color.border.default` hairline above
it (decorative). Tokens are CMP-046's (`15:714`).

**Keyboard** (drawer: a non-modal dialog, slice 4 CMP-046; inline: the APG Disclosure pattern):

| Keys                                               | Action                                                                                                                                                    |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Enter / Space on the trigger                       | Opens it (the CMP-227 chip is a `button` with `aria-haspopup="dialog"`, `E25-D05.md:111`; §6 J18); focus moves to the drawer's heading at `tabindex="-1"` |
| Esc (drawer)                                       | Closes it; focus returns to the chip (`E25-D05.md:104`)                                                                                                   |
| Tab (drawer)                                       | Moves through its links and close; Tab past the last leaves the drawer, which stays open (non-modal, slice 4 CMP-046)                                     |
| Enter / Space on the inline trigger, or Esc inside | Toggles it; on close focus returns to the trigger (`E12-D03.md:293`–`:296`)                                                                               |

**Accessible name and role:**

| Element      | Role             | Name                | ARIA                                                          |
| ------------ | ---------------- | ------------------- | ------------------------------------------------------------- |
| drawer       | dialog           | its title           | `aria-modal="false"` (slice 4 CMP-046)                        |
| inline panel | region (or none) | its heading         | the trigger's `aria-controls`; `aria-expanded` on the trigger |
| heading      | heading          | the detector's name | `tabindex="-1"` while it receives focus on open               |
| loading      | —                | —                   | the body `aria-busy="true"` until the values arrive           |

**Analytics:** none of its own; the CMP-227 provider emits `methodology.opened` with `{detector}` when it opens the
drawer (`14:1355`; E25-D05, `E25-D05.md:56`). **Focus:** to the heading on open, back to the trigger on close.
**Motion:** slice 4 CMP-046's (the drawer slides in opaque, motion-reduce a cut); the inline panel is a cut. **Live
region:** none: focus on the heading reads it; a load failure is CMP-027's polite region (slice 4 conventions 33). **T2
and not T2:** a container (conventions 46); loading is busy (conventions 47). **Hit target:** the close button's.
**Resize & overflow:** the drawer's body scrolls; at 720 CSS px or less it takes the full width (slice 4 conventions
39); the inline panel wraps in its host. **Forced colors:** slice 4 CMP-046's; the inline hairline CanvasText.

**Catalogue alignment (held, §6 (f)):** Props add `variant?: "drawer" | "inline"` (J17); A11y replaces "triggerable from
the chip's tooltip via `Enter`" with `Enter` / `Space` on the trigger and `Esc` back to it (J18), and adds the heading
focus and `aria-busy`; Storybook adds Inline, Loading, Error.

### CMP-085 · SkipLink

**Catalogue (verbatim, `15:869-870`):**

- **Props**: `targetId`.
- **A11y**: visually hidden until focused, then visible at top-left.

| Axis    | Values                    | Default   |
| ------- | ------------------------- | --------- |
| State   | unfocused, focused, hover | unfocused |
| Targets | one, several              | one       |

**Variants × States (3 cells; not drawn — E10-D03 draws the shell's, `E10-D03.md:149`):**

| Cell    | Axes            | What it shows                                                                                                                                 |
| ------- | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| focused | State=focused   | "Skip to main content" (`E10-D03.md:352`) as a pill at the TopBar's empty left of its second row, over nothing it hides (`E10-D02.md:254`)    |
| several | Targets=several | the first link focused, then "Skip to order ticket" and "Skip to chart" (`05:98`), each its own link, shown one at a time as focused (§6 J19) |
| hover   | State=hover     | the focused pill under a pointer: `color.action.primary.hover` (6.75 / 6.75 / 5.47:1 for the label)                                           |

**Not drawn:** unfocused (visually hidden, nothing to see); disabled and gated (a skip link is always available); the
floating window's own link, which is the same component in its own document (`14:650`).

**Anatomy** (E10-D03, followed):

| Part  | Tokens                                                                                                                                                                   |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| pill  | `color.action.primary.default` (the catalogue's `color.action.primary`, E10-D03 A5), `radius.control`, min-height `size.control.height`, padding `space.button.paddingX` |
| label | `type.ui.label`, `color.text.on-action`: 4.76 / 4.76 / 7.45:1                                                                                                            |
| ring  | the CMP-039 ring, 2 px outside the pill on `color.surface.app`: 7.45 / 6.75 / 19.35:1; the pill itself 4.07 / 4.76 / 7.45:1 against the app chrome                       |

**Keyboard:**

| Keys        | Action                                                                                                                             |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Tab (first) | The first Tab on a page focuses the first skip link and shows it (`15:873` "keyboard-first-tab test")                              |
| Tab         | To the next skip link, then into the TopBar (E10-D02's focus order, `E10-D02.md:254`); each link hides again when it loses focus   |
| Enter       | Moves focus to the target, which takes `tabindex="-1"` and shows the CMP-039 ring; the next Tab continues from the target (§6 J20) |

**Accessible name and role:**

| Element | Role                       | Name                                      | ARIA                                                              |
| ------- | -------------------------- | ----------------------------------------- | ----------------------------------------------------------------- |
| link    | link                       | "Skip to main content" (`E10-D03.md:352`) | `href="#<targetId>"`; the first focusable element in the document |
| target  | its own (`main`, a region) | its own                                   | `tabindex="-1"` while focused, removed on blur (§6 J20)           |

**Focus:** moves only on the user's `Enter`. **Motion:** none: it appears and hides as a cut in both modes. **Live
region:** none. **T2 and not T2:** never gated. **Hit target:** `size.control.height` tall. **Resize & overflow:** the
pill grows with the text; it never covers the ENV badge or a NavRail label (`E10-D02.md:254`). **Forced colors:**
LinkText on Canvas with a CanvasText border; the ring Highlight (conventions 48).

**Catalogue alignment (held, §6 (f)):** Props `targets: { id, label }[]` with main content first (J19); A11y adds the
target's `tabindex="-1"` and the Tab order (J20); Tokens become `color.action.primary.default`, `color.text.on-action`
and `color.focus.ring` (E10-D03 A5); Storybook adds Several.

### CMP-228 · PreviewTile

**Catalogue (verbatim, `15:2672-2673`):**

- **Props**: `kind: "footprint"|"heatmap"|"candles"|"theme"` · `settings: object` · `sampleData?: unknown`.
- **A11y**: `role="img"` with a name describing the current configuration in words; it is decorative-adjacent, so the settings themselves always remain independently readable — the preview is never the only disclosure of a setting's effect.

| Axis  | Values                                               | Default |
| ----- | ---------------------------------------------------- | ------- |
| Kind  | candles, footprint, heatmap, theme, ladder (E32-D04) | candles |
| State | live, sample, empty, error, collapsed (ladder only)  | live    |

**Variants × States (8 cells; not drawn):**

| Cell               | Axes                     | What it shows                                                                                                                                             |
| ------------------ | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| candles · live     | Kind=candles, State=live | this chart's bars through the pending Scales values, axis labels `color.text.tertiary` (6.83 / 4.86 / 13.61:1 on sunken) (E11-D03 §6.4, `E11-D03.md:277`) |
| sample             | State=sample             | bundled recorded, redacted bars with the label "Sample bars: not this chart" (E12-D05 W-19, `E12-D05.md:334`, PROPOSED there)                             |
| empty              | State=empty              | "Preview unavailable — no bars loaded" in `color.text.secondary` (10.69 / 7.37 / 17.42:1) over the CMP-029 silhouette (`E11-D03.md:279`)                  |
| error              | State=error              | "Preview unavailable — chart error; settings still apply" with a `color.status.danger.strong` glyph (11.31 / 3.37 / 11.31:1, non-text) (`E11-D03.md:280`) |
| theme              | Kind=theme               | SCR-116's tile: a chart cell, a ladder row and a positions row under the current theme and density (`14:2361`)                                            |
| footprint          | Kind=footprint           | a footprint cell sample under the current colours (`15:2675` Storybook "Footprint"); heatmap the same with the heatmap ramp                               |
| ladder             | Kind=ladder              | E32-D04's glance tile: the value `type.num.base` `color.text.primary`, its caption under it, 24 px tall compact (`E32-D04.md:366`, D04-A2 PROPOSED)       |
| ladder · collapsed | State=collapsed          | the five figures on one line separated by " · " (E32-D04, `E32-D04.md:376`)                                                                               |

**Not drawn:** hover, focus, disabled, gated (not interactive; the settings beside it are the controls); loading — never
a spinner, the last frame stays until the next (E11-D03 D12, `E11-D03.md:83`; conventions 47).

**Anatomy:**

| Part    | Tokens                                                                                                                                                    |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| tile    | `color.surface.sunken`, `radius.card` (the catalogue's `radius.md`, the same primitive), a 1 px `color.border.default` hairline (decorative; §6 J2)       |
| image   | the host's renderer at its own colours (a second engine view, `E11-D03.md:277`); the theme kind renders the tokens of the theme it previews               |
| text    | empty and error text `type.ui.caption` in `color.text.secondary`; a ladder value `type.num.base` `color.text.primary` (17.42 / 12.82 / 19.73:1 on sunken) |
| caption | the visible caption under the tile in `type.ui.caption`, `color.text.secondary` (E12-D05 W-20, `E12-D05.md:335`)                                          |

**Keyboard:** none (not focusable; E32-D04's tiles never take focus, the pinned row repeats each figure,
`E32-D04.md:366`).

**Accessible name and role:**

| Element | Role | Name                                                                                                                                                                                   | ARIA                                                |
| ------- | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| tile    | img  | the configuration in words, e.g. "Preview: BTCUSDT 1 minute, logarithmic scale, 1 decimal, inverted, 12 pixels per bar, UTC" (`E11-D03.md:278`); empty or error: "Preview unavailable" | `aria-live="off"`: the fields announce themselves   |
| caption | none | its text                                                                                                                                                                               | not referenced by the tile; it is read in DOM order |

**Focus:** never. **Motion:** none of its own; the image re-projects within one frame per change (`E11-D03.md:277`), and
under motion-reduce it is a cut as well. **Live region:** none. **T2 and not T2:** not a control; empty and error are
availability and failure (conventions 47). **Hit target:** none. **Resize & overflow:** the tile keeps its aspect and
scales its image; the name never truncates (conventions 49). **Forced colors:** the image keeps its colours
(`forced-color-adjust: none` on the canvas only); the edge CanvasText; the text CanvasText (conventions 48).

**Catalogue alignment (held, §6 (f)):** Props add `source?: "live" | "sample"`, `emptyText`, `errorText`, the kinds
`scales` and `ladder`, and `value` / `caption` for `ladder` (J21; E11-D03 D03-CR-3, E32-D04 D04-A2); A11y adds the
empty and error names and "never a spinner"; Tokens become `radius.card` and the hairline; Storybook adds Sample,
Empty, Error, Ladder, LadderCollapsed.

### 7.12 Custom trading glyphs (`16` §5; for E05-T06, #271)

`16` §5 lists the trading-domain icons no generic set provides: "flatten-all, chase-limit, iceberg-order, TWAP,
one-click-arm, native-SL-shield, estimated/heuristic-badge glyph, node-graph node-type glyphs
(trigger/condition/action/logic-gate/comment), heatmap-convention swap", "drawn to the same 1.5px-stroke grid as the
base set and contributed to the same icon registry" (`16:150`). This section specifies them as glyph specs, not
drawings: slice 1 conventions 7 assigns them to this slice, and E05-T06 draws, registers and tests them (its DoD).

**Rules for all 13 (binding, from their sources):**

- **Grid and stroke.** Outline style on the base set's 24-unit grid; a 1.5 px stroke that never scales; round caps and
  joins; square-ish bounding boxes for toolbar and menu alignment (`16:149`); no filled area except dots, which follow
  slice 1 CMP-019's build record (a 2-unit dot under the stroke); every glyph stays inside the grid and never touches
  its edge, like the base set's `icon/{name}` components (slice 1 §7).
- **Optical sizes.** Each glyph has one 24-unit master, rendered at the `size.icon.sm|md|lg` scale — 12 / 16 / 20 px as
  shipped, 16 / 20 / 24 px if slice 1 A10 is approved; the semantic `size.icon` (16 px, both densities) is the default.
  Where a glyph's detail closes up at 12 px it has a reduced 12 px form or is marked "16 px minimum" below (§6 J24;
  E25-D05 CR-3's precedent).
- **Colour.** `currentColor`: the context's text token (`color.text.primary`, `secondary`, `tertiary` on a T2 label), a
  filled action's label token, or a tone token where the host names one (slice 1 CMP-019's mapping; E25-D05's
  `color.status.info.default` for `icon/estimated`). A
  glyph never carries a category or side hue by itself (§6 J25; `05` §4).
- **No states of its own.** A glyph has no hover, focus, disabled or selected look; its host's state recolours it
  through `currentColor`. It is never animated (E05-T06's Out of scope: "Animated icons").
- **Accessible name.** Beside visible text the glyph is decorative, `aria-hidden="true"`; on an icon-only control the
  control carries the name and the glyph stays hidden; a meaningful standalone glyph is CMP-019 `decorative=false` with
  a label (`16:152`; slice 1 CMP-019). The **Name when meaningful** column below is the label a host uses only when it
  shows the glyph with no adjacent word, which no merged spec does today; every listed use is decorative.
- **Registry.** Each is registered as `icon/{name}` with the description in the table, which feeds CMP-019's
  completeness test and the design file's icon page (`16:151`).

| Name (§6 J22)                  | Registry description                                    | Motif (PROPOSED, `(heuristic)`)                                                                                                                                   | Where used (source)                                                                                                                   | Smallest size        | Name when meaningful      |
| ------------------------------ | ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------------------------- |
| `icon/flatten-all`             | Close every position at market                          | three short horizontal strokes of unequal length collapsing onto one baseline under a down-pointing chevron                                                       | CMP-123 FlattenAllButton (`15:1403`), the CMP-211 panic cluster (E39-D03)                                                             | 16 px minimum        | "Flatten all"             |
| `icon/chase-limit`             | Limit order that follows the price                      | a horizontal price line with a short tick (the limit) and a curved arrow tracking it from behind                                                                  | SCR-068 chase-limit builder (E33-D02 §5)                                                                                              | 16 px minimum        | "Chase limit"             |
| `icon/iceberg-order`           | Order shown in visible slices with a hidden remainder   | a waterline; a small peak above it and a larger body below in a plain outline — never dashed, because dashed means estimated or absent (E25-D05, `E25-D05.md:60`) | SCR-067 Iceberg builder (E33-D02 §4, `E33-D02.md:219`); never the iceberg **detector**, which is `icon/estimated` territory (CMP-227) | 16 px minimum        | "Iceberg order"           |
| `icon/twap`                    | Order split evenly over a time window                   | a horizontal time axis with four equal steps rising under it                                                                                                      | SCR-066 TWAP builder (E33-D02 §3, `E33-D02.md:161`)                                                                                   | 16 px minimum        | "TWAP"                    |
| `icon/one-click-arm`           | One-click trading is armed                              | a pointer arrow with a short lightning stroke beside its tip                                                                                                      | the 1-click trading toggle and its persistent armed indicator (`05:65`); never on CMP-229 (§6 J23)                                    | 12 px                | "One-click trading armed" |
| `icon/native-sl-shield`        | A native exchange stop-loss protects the position       | a shield with one horizontal stop line across its lower third; distinct from `icon/shield-off`'s diagonal slash (E30-D04 §3.3, `E30-D04.md:271`)                  | CMP-158 SafetyInvariantNotice (E36-D02, `E36-D02.md:96`)                                                                              | 16 px minimum        | "Native stop-loss"        |
| `icon/estimated`               | The value is inferred, not reported by the exchange     | at ≥16 px a dashed ring with a centred "≈"; at 12 px a solid ring or the "≈" alone (E25-D05 CR-3, `E25-D05.md:387`)                                               | CMP-227 EstimatedBadge, every variant (E25-D05, `E25-D05.md:70`)                                                                      | 12 px (reduced form) | "Estimated"               |
| `icon/node-trigger`            | Rule node: what starts an evaluation                    | a pointed pennant, echoing the trigger node's pointed left cap (E37-D02, `E37-D02.md:169`)                                                                        | CMP-147 TriggerNode header and the palette's Trigger group (E37-D02)                                                                  | 12 px                | "Trigger"                 |
| `icon/node-condition`          | Rule node: a comparison that is true or false           | a square with a short "=" inside, echoing the square cap                                                                                                          | CMP-148 ConditionNode                                                                                                                 | 12 px                | "Condition"               |
| `icon/node-action`             | Rule node: what the rule does                           | a rounded square with a right-pointing triangle inside, echoing the rounded cap                                                                                   | CMP-149 ActionNode                                                                                                                    | 12 px                | "Action"                  |
| `icon/node-logic-gate`         | Rule node: combines inputs (all, any, none, at least n) | a diamond, echoing the gate's diamond notch                                                                                                                       | CMP-150 LogicGateNode                                                                                                                 | 12 px                | "Gate"                    |
| `icon/node-comment`            | Rule node: a note outside the rule                      | a page with a folded top-right corner, echoing the comment's dog-ear                                                                                              | CMP-151 CommentNode                                                                                                                   | 12 px                | "Comment"                 |
| `icon/heatmap-convention-swap` | Swap which side the heatmap colours show as bid and ask | two small squares side by side with a two-headed arrow beneath them                                                                                               | the convention swap (owner decision #10, `EngineTheme.convention`; E11-D05, `E11-D05.md:277`)                                         | 16 px minimum        | "Swap heatmap colours"    |

**Words and names.** The node names are E37-D02's type words ("Trigger" · "Condition" · "Action" · "Gate" ·
"Comment", `E37-D02.md:169`); "Estimated" is CMP-227's word; "Flatten all", "Chase limit", "Iceberg order", "TWAP" and
"Native stop-loss" are `16` §5's and their hosts' terms; "One-click trading armed" and "Swap heatmap colours" are
PROPOSED, for the keymap's and E11's owners, because no merged text names those two glyphs. The registry descriptions
are PROPOSED for E05-T06's `registry.ts` (`(heuristic)`).

**Contrast** (audit §4): as non-text marks every glyph needs 3:1 on its host surface. `color.text.primary` and
`secondary` clear it everywhere (8.14:1 or more); a T2 glyph in `color.text.tertiary` measures 5.20–5.96:1 dark, 5.44–
6.36:1 light, 10.36–11.87:1 hc on canvas, raised and overlay; `icon/estimated` in `color.status.info.default` measures
6.20 / 3.48 / 6.20:1 on raised and 6.57 / 3.74 / 6.57:1 on canvas (E25-D05's binding).

**Not drawn:** all 13 (the board cap); E05-T06 draws them, at the three optical sizes, and its DoD updates `16` §5 with
the final list.

## 8. Design QA checklist (brief §12)

Completed for the 11 components and the glyph set. Open items say why and who closes them.

- [ ] **Tokens:** only published Tier-2/Tier-3 tokens, no hardcoded hex/px. **Open:** every value is a semantic token
      or a named primitive (§4, §5.2); §5.1's constants are recorded, ticked when §6 J3 is answered.
- [ ] **Themes and densities:** structurally guaranteed and measured in all three themes (audit §4). **Open:** not
      drawn (the board cap); the light composite board shows the slice 1–4 parts only.
- [ ] **Contrast matrix:** every text pair passes; the thin pairs are decorative or carried by words — the Kbd edge
      (1.80 / 1.46 / 1.80:1), the card's fill step and hairline (1.06–1.58:1), the preview tile's edge in light (1.00:1,
      §6 J2), the palette's destructive glyph in light (3.78:1, a glyph, E10-D03's PASS). **Open** for the owner (J1,
      J2).
- [ ] **CVD:** ΔE76 spot checks in the audit §5; selection carries a rule, a check or a word; tones carry a glyph and a
      word. **Open:** E05-D04's review.
- [ ] **Every State has a variant (and a story):** the 66 cells are specified (§1, §7). **Open:** not drawn; the stories
      are E05-S01..S04's (slice 1 C15).
- [ ] **Disabled with a reason (CMP-079):** containers never gate; the gated tab, the gated palette command and, under
      §6 J15 (b), the appearance options take T2 through CMP-079 with the CMP-019 `lock` (conventions 46); availability,
      busy, outcomes and read-only data stay apart (conventions 47). **Open** for J15.
- [x] **Loading, empty and error designed:** CMP-069's loading and error cells, CMP-228's empty, error and sample
      cells, CMP-059's no-results cell; CMP-050's are its content's (CMP-015, 026, 027).
- [ ] **Keyboard tables** complete for all 11 (the APG pattern named, or none of its own with the reason). **Open** for
      "implemented, tested" (E05-S01..S04).
- [x] **Accessible-name/role tables:** all 11 and the glyph name rule (§7, §7.12; summary in the audit §2).
- [x] **Canvas-adjacent:** CMP-228 is `role="img"` with a name in words and never the only disclosure.
- [x] **Motion pairs:** nothing here animates except slice 4's dialog and drawer frames, which carry theirs; a theme or
      density switch is instant in both modes (conventions 45).
- [x] **Hit targets:** tabs, palette rows, the skip link and the appearance controls are at least 24 × 24 px compact
      and 32 px comfortable; Kbd, Countdown, KeyValueRow, Card and PreviewTile are not targets.
- [ ] **Accessibility sign-off (§13).** **Open:** the pre-review is the companion audit; the sign-off is E05-D04's.
- [x] **Analytics annotated:** `appearance.theme_changed` (CMP-062) and `appearance.density_changed` (CMP-063), each
      once per committed user change (conventions 45, §6 J16; #161 Observability).
- [x] **Estimated values:** `icon/estimated` specified from E25-D05 CR-3 (§7.12); CMP-069 is the methodology drawer.
- [x] **Demo/Live:** nothing here restates the environment; the palette's commands route into their own confirmations.
- [x] **No near-duplicate:** no new CMP id; the workspace tab strip stays E15-D02's own component (conventions 43);
      CMP-103 keeps its look over CMP-042 (§6 J9); `icon/one-click-arm` and CMP-229's lock pair stay apart (§6 J23).
- [ ] **Storybook matches the matrix.** Not applicable to this design PR (slice 1 C15).
- [ ] **Composes only published components.** **Open:** CMP-213, CMP-227 and CMP-239 are referenced from their own
      specs, outside #161.

## 9. Approval

The owner approves by merging this spec PR and/or commenting `approved` on #161 (C-10.1; the coordinator reviews under
the owner's delegation): owner approval pending. This text merges first with the boards PENDING; slice 5 adds no board
and is specified only, its two folded parts (CMP-022, CMP-035) appearing on specimen board 09. **#161 closes when the
boards PR has merged**, which carries the closing line; this PR refers to #161 without closing it. Engineering stories
E05-S01..S04 move to Ready only after every slice is approved, and E05-T06 (#271) takes §7.12. The accessibility
pre-review is `E05-D02-rest-a11y-audit.md`; the formal accessibility and CVD sign-off is E05-D04's. The `15` clauses and
hand-offs of §6 (f) go to their owners when the coordinator files them.
