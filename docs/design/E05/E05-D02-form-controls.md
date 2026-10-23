# E05-D02 — Design-system atoms and molecules: slice 3 of 5 (form controls)

**Ticket:** E05-D02 (#161) · **Epic:** E05 Design system v0 · **Status:** In Review — awaiting owner approval (slice 3
of 5) (design PR: the owner approves under C-10.1; the coordinator reviews). Text-first: written from `15`, the tokens
and E09-D09 without a Penpot build (the coordinator's ruling of 2026-10-23); the boards are PENDING.
**Penpot:** page `10 Components — Atoms` of the CandleViewer DS file. The boards PR builds the 11 variant sets there
(the molecules beside the atoms), exports them, adds the page id and redraws nothing in slices 1–2. Slice 5 carries
#161's closing line.
**Slices:** #161 ships as five design PRs. Slice 1 (#3914, `E05-D02.md`) covers actions and selection; slice 2 (#4290,
`E05-D02-data-display.md`) the data display and text atoms; this slice the form controls: CMP-007 TextInput, CMP-008
NumericStepperInput, CMP-009 Select, CMP-034 MaskedValue, CMP-040 FormField, CMP-047 DatePicker / DateRangePicker,
CMP-048 Combobox / AutoComplete, CMP-049 Table (the coordinator's five-slice plan puts it here, with the ticket's
Gherkin row), CMP-054 SearchBox, CMP-065 FormSection and CMP-079 RbacGate, the disabled-with-reason carrier every
gateable form control uses. Slice 4 covers feedback and overlays, slice 5 the rest.
**Companion:** `E05-D02-form-controls-a11y-audit.md` (accessibility pre-review of this slice).
**Builds on:** slice 1's conventions 1–14 (§3), token mirror (§4), exceptions (§5) and decisions A1–A12, B1–B7, C1–C15
and D1–D17 (D13 is superseded by E09-D09 §2.2 T2), and the conventions 15–20 and decisions E1–E27 of
slice 2 (#4290, merged as `c899241c8`; its spec and audit are byte-identical to the head `fd4ea21d1` this slice
cited). They apply here unchanged and are cited as "slice 1 §n", "slice 1 A3" and "slice 2 (#4290) E18".
**Order-ticket contracts.** CMP-008, CMP-009 and CMP-065 are the bases of merged order-ticket components: E30-D02
(`docs/design/E30/E30-D02.md`, SCR-060's order ticket) draws them, and E30-D04 (#4271, merged as `ca7d61fa1`,
`docs/design/E30/E30-D04.md`) is the design-system contract of CMP-100 and CMP-101 (on CMP-008), CMP-119 (on CMP-065)
and CMP-231 (on CMP-009). Where this slice meets them, §5.2 records each clash and how it is resolved.
**Key.** `05`, `14`, `15`, `16` are the `docs/plan/` documents by number; D09 is `docs/design/E09/E09-D09.md`.
`path:line` references are at `origin/main` `5a382efec`, except E30-D04's and E29-D02's, which merged after it and
are cited at this PR's base, `f128ba6c6`.

## 1. What this slice specifies

- **11 components, 28 variant properties, 85 cells.** One Penpot variant set per CMP id, named `CMP-0xx · Name` (brief
  §10; a catalogue `/` is dropped, slice 1 §1.1). The matrix rule is slice 1 conventions 2, with the form states this
  slice adds (conventions 22): every documented state at the default of the other axes, every other axis value once,
  and the universal states. Each section lists the cells it draws and the states that do not apply, with the reason.
- **One section per component** (§7): the catalogue Props and A11y text verbatim (as on `main` before this PR's edits),
  the variant properties, the Variants × States matrix, the anatomy with each part's semantic token, the keyboard table
  (the WAI-ARIA APG pattern named), the accessible name and role table, the T2 form and what is not T2, validation,
  hit target, motion, resize and forced colours, and the catalogue alignment proposed for it.
- **No build yet.** Every token below is a published semantic token or a named primitive (§4, §5); nothing is drawn
  until the boards PR. No component nests one that nests it back: CMP-007, 008, 009, 047 and 048 draw the field box
  only, and their label, help, error and reason lines are CMP-040's, drawn in CMP-040's section. Cells that nest a
  component of a later slice (CMP-015, CMP-026, CMP-027, CMP-035, CMP-041) draw it from its catalogue entry as a plain
  board until it ships, then swap in the live instance.
- **Catalogue alignment, in this PR.** The 11 entries of `15` are updated in slice 1–2's form: Variants, States and
  Tokens lines with the specified tokens, Props and A11y additions; each clause traces to its section here. Clauses
  that encode a choice awaiting your answer are listed in §6 (e); the held updates are §6 (f).

| Component                   | Penpot variant set (boards PR)  | Variant properties          | Cells  | Composes (live instances)                                              |
| --------------------------- | ------------------------------- | --------------------------- | ------ | ---------------------------------------------------------------------- |
| CMP-007 TextInput           | `CMP-007 · TextInput`           | State, Value, Affix         | 9      | `icon/{name}` (prefix glyph), CMP-019 (`lock`)                         |
| CMP-008 NumericStepperInput | `CMP-008 · NumericStepperInput` | State, Bound, Unit          | 9      | CMP-002 IconButton ×2, CMP-019 (`lock`)                                |
| CMP-009 Select              | `CMP-009 · Select`              | State, Value, Searchable    | 9      | CMP-019 Icon (`chevron-down`, `check`, `lock`)                         |
| CMP-034 MaskedValue         | `CMP-034 · MaskedValue`         | State, Copyable             | 4      | CMP-002 IconButton, CMP-033 CopyButton, CMP-035 Countdown              |
| CMP-040 FormField           | `CMP-040 · FormField`           | Layout, State, Help, Marker | 8      | CMP-007, CMP-019 (`danger`)                                            |
| CMP-047 DatePicker          | `CMP-047 · DatePicker`          | Mode, State, Time           | 11     | CMP-002, CMP-019; the calendar dialog                                  |
| CMP-048 Combobox            | `CMP-048 · Combobox`            | State                       | 10     | CMP-014 Spinner, CMP-019                                               |
| CMP-049 Table               | `CMP-049 · Table`               | Mode, State, Selection      | 10     | CMP-005, CMP-002, CMP-014, CMP-015, CMP-016, CMP-026, CMP-027, CMP-041 |
| CMP-054 SearchBox           | `CMP-054 · SearchBox`           | State, Value                | 5      | CMP-002 IconButton, CMP-019 (`search`, `close`)                        |
| CMP-065 FormSection         | `CMP-065 · FormSection`         | Collapsible, State          | 6      | CMP-040, CMP-007, CMP-019                                              |
| CMP-079 RbacGate            | `CMP-079 · RbacGate`            | Allowed, Form               | 4      | CMP-040 + CMP-007, CMP-002 + CMP-016, CMP-065                          |
| **11**                      |                                 | **28**                      | **85** |                                                                        |

Every gated cell — the T2 cells of CMP-007, 008, 009, 040, 047, 048, 049 and 065 — is a CMP-079 RbacGate
composition with the CMP-019 `lock` glyph (conventions 24); in a field atom's own T2 cell the lock leads the value
inside its well (E30-D04 §2.5 (2)), and the reason line is CMP-040's, drawn in CMP-040's T2 cell.

## 2. How to review

1. Read the conventions once (§3, items 21–29): every component section cites them instead of repeating them.
2. Read a component section top to bottom: the matrix says what the boards PR will draw, the anatomy says how, the
   tables say how it behaves. The catalogue text it quotes is `main`'s, before this PR's edits.
3. The owner decisions are in §6 (G1–G22), each PROPOSED with its options and a recommendation; §6 (e) lists the
   catalogue clauses applied in this PR that a "no" reverts, §6 (f) the held edits.
4. The catalogue edits are in `docs/plan/15-component-catalogue.md`, in the 11 entries only.
5. The boards PR then draws the 85 cells and the documentation samples and exports each section at dark/compact, with
   the six theme × density proof frames, as slice 1 §2 describes.

## 3. Conventions (21–29, numbered on from slice 2's)

21. **The field box** (CMP-007, 008, 009, 047, 048, 054; CMP-034's display box shares its geometry). The well: fill
    `color.surface.app` (§6 G4); a 1 px boundary in `color.text.tertiary`, aligned inside (the value of the primitive
    `border.hairline`, unbound: slice 1 B1; the semantic token is §6 G1); radius `radius.control`; min-height
    `size.control.height` (24 compact, 32 comfortable: the one thing density changes); padding-inline `space.inset.sm`;
    gap between parts `space.inset.xs`. Inside it: the value in `type.ui.body`, `color.text.primary` (numbers:
    conventions 27); the placeholder in `type.ui.body`, `color.text.tertiary`, an example and never the label; prefix
    and suffix text in `type.ui.body`, `color.text.tertiary`; a leading glyph at `size.icon` in `color.text.tertiary`.
    In-well buttons (the SearchBox clear, the DatePicker calendar) are CMP-002 ghost IconButtons at the trailing end,
    `size.control.height` square and flush with the well's ends; the well's 1 px boundary paints over their edge, so
    each target stays 24 × 24 (32 × 32) and the well never grows (slice 1 conventions 10). The stepper's `[−]` `[+]` sit
    outside the well (CMP-008, as `docs/design/E30/E30-D02.md` §2 draws them; their fill and Tab stops are §6 G22); a
    Select's chevron is decorative.
22. **Field states, one look each.** hover: the boundary steps to `color.text.secondary` (slice 1 D17's step), the fill
    stays. focus-visible: the CMP-039 ring (2 px `color.focus.ring` at a 2 px offset, radius `radius.control` + 2); a
    text field matches `:focus-visible` on pointer focus too (slice 1 CMP-039), so a clicked field shows the ring; the
    boundary keeps its rest or invalid look. invalid: conventions 23. read-only: no fill (the host surface shows
    through), a 1 px `color.border.default` hairline (decorative: the label and the value carry the field), the value in
    `color.text.primary`; native `readonly` (`aria-readonly` on a combobox); focusable; selection and copy work.
    disabled (plain): the whole component at `opacity.disabled`, native `disabled`, out of the Tab order, only for a
    field unavailable to everyone in the current state and never for a gate or for validity (the order ticket draws
    none: a market order shows no price field, E30-D02 §7, and a ticket field is disabled only by a gate, E30-D04 §4);
    its contrast rests on the WCAG 1.4.3 and 1.4.11 inactive exemption. disabled-with-reason: T2 (conventions 24). busy:
    conventions 25.
23. **Validation, never T2** (D09 §9.1 "form validity"). _When:_ a field validates on blur after the user changed it,
    and every field validates on submit; a field that shows an error re-validates on input and clears, silently, as
    soon as its value is valid; nothing validates on the first keystroke. _Where:_ the message line under the field
    (CMP-040's error node): a CMP-019 `danger` glyph (decorative) in `color.status.danger.strong`, then the sentence
    in `type.ui.caption`, `color.text.primary`; the boundary becomes 2 px `color.status.danger.default`
    (`border.thick`, §5.2). Three cues — the width, the glyph, the words — and never colour alone (§6 G2).
    _Semantics:_ `aria-invalid="true"` on the control; the message node is in the DOM at mount, empty while valid, and
    its id is in the control's `aria-describedby`, before the help; no `aria-errormessage` (§6 G16). _Announcement:_
    the message node is a polite live region, pre-rendered empty with its text swapped (`05` §6.2): a message that
    blur validation or an async check shows or changes is announced once, an unchanged one never again, a cleared one
    not at all. On submit the host's error summary (CMP-027 `role="alert"`, `docs/design/E30/E30-D02.md` D16, the
    GOV.UK pattern) takes focus and names the fields, and the submit stays operable; the field nodes fill in the same
    frame and the summary speaks first `(heuristic)`; E05-S03's test asserts each message is announced at most once
    (§6 G17). _Copy_ is the host's (`14:145` SCR-001: "Enter your username."). _Placement:_ fields sit on
    `color.surface.app`, `canvas`, `raised` or `overlay`; on `surface.hover` or `surface.selected` the invalid
    boundary falls to 2.43–2.92:1 in dark (2.87:1 in high contrast on `surface.selected`) (audit §4), where the glyph
    and the words carry the state.
24. **T2 in a form** (D09 §2.2, §9.1–§9.3; `14:85` rule 5; cited as "T2, conventions 24"). _Scope:_ a field, select,
    combobox, date field, stepper, row action or section that a view-as context, a permission, grant, account or
    environment leg, or a registered state blocks (D09 §2.1 steps 3–4). The view-as leg never gates a protective write:
    C-2.6's carve-out (attaching a missing native stop, tightening a stop, re-arming a protective trigger) stays enabled
    while viewing as (D09 §2.1 step 3 (a); `22` View-as "Protective writes (C-2.6)"; E42-D02 D10), so a stop-tightening
    field is never T2 on that leg, and the server classifies each write (`24` §8.10). CMP-079 RbacGate wraps the step-3
    legs; a step-4 state reason (E30-D02 §14's `frozen` and `lockout`, E17-D01 §7's feed states) goes to the control's
    own `disabledReason` (`docs/design/E42/E42-D03.md` §13 (4)). _Semantics:_ the control keeps its native role and its
    full label; `aria-disabled="true"`, never the `disabled` attribute, so it stays in the Tab order and an option or
    menu item stays arrow-reachable; a text-like field is also `readonly` (E42-D03 §13 (2)); `aria-describedby` points
    at the reason node, which is in the DOM at mount, and while T2 the description is the reason alone (D09 §9.2: help
    leaves the chain, its line stays visible). _Renderings:_ **2a inline** is the default for every slice-3 control. On
    a field the CMP-019 `lock` glyph (`decorative=false`, name "Not available"; the base set's `icon/locked`, slice 1
    §1) leads the value inside the well, ahead of any prefix, in `color.text.tertiary` like the value, and the field's
    label stays `color.text.secondary`, as E30-D04 §2.5 (2) draws the order ticket's fields (`E30-D04.md:205`, `:292`;
    §5.2); the reason sits under the field in `type.ui.caption`, `color.text.secondary`. A group (a radiogroup, a
    segmented control) is led by one lock (E30-D04 §2.5 (2)); an option or a row-menu item leads its own label with the
    lock, in `color.text.tertiary`, and carries the reason as its second line. **2b tooltip echo** only for an icon-only
    control without inline room (a CMP-049 row-action IconButton): the lock badge on the icon (slice 1 §5.2's
    `size.icon.sm` badge), the description node visually hidden, CMP-016 echoing it on hover and focus, never the only
    copy. **One notice, many pointers** for a section read-only for the session (CMP-065): one notice under its heading
    that every gated control's `aria-describedby` points at; each field still shows the lock in its well and renders no
    reason of its own. _Visual:_ the well loses its enabled look — fill `color.surface.raised` with a 1 px
    `color.border.default` hairline, as D09 §2.2 strips a filled control — and the value turns `color.text.tertiary`;
    never `color.text.disabled`, never `opacity.disabled` on the label, value, glyph or reason (D09 §11: 2.86–4.31:1).
    _Keys:_ Tab reaches it; Enter, Space, an arrow, `Alt+↓`, a bound hotkey or a printable key changes nothing and
    re-shows the reason inline with one polite announcement per focus visit (D09 §9.3); `Esc` closes a 2b echo only.
    _Reasons:_ D09 §3.1's keys (`rbac.permission` "Your role can't {verb}." with its §3.2 verb, `rbac.owner_only`,
    `rbac.account`, `rbac.account_read_only`, `rbac.env`, `rbac.view_as`) or a registered state key; a component never
    writes its own string. It emits no audit and no analytics.
25. **What is not T2** (the standing rulings; D09 §9.1). _Validity_ (conventions 23): an invalid value is a message, not
    a lock, and an option that the form's own rules make unavailable, with a stated reason, takes E30-D04 §2.5's
    validity look (ruled as LANE-55, `E30-D04.md:203`; conventions 26). _Busy:_ a control whose own request is in flight
    — a form submitting (its fields stay focusable and `readOnly`, `14:144` SCR-001 "fields locked"), a sort reading
    pages, a search — is focusable, `aria-busy` where the role allows it, with no lock and no reason (E42-D03 §7's sort
    header). _Availability:_ nothing refuses the action but what it needs is not there yet — no rows, no results, days
    outside the recorded range, a stepper at its bound — shown as an empty, loading or bound state with its own words.
    _Read-only by nature:_ a value nobody may edit here is `readOnly` (conventions 22) or plain text. _Plain disabled:_
    unavailable to everyone in this state.
26. **Popups** (CMP-009's listbox, CMP-048's results, CMP-047's calendar). The surface is `color.surface.overlay`,
    `elevation.popover`, `radius.card`, with a 1 px `color.border.default` edge (decorative: the shadow and the position
    carry it) and padding-block `space.inset.xs`; it is anchored `space.inset.xs` under the field, above it when the
    viewport has no room (an overlay anchor, slice 1 B3 (b)); at least as wide as the field; at most 10 rows tall, then
    it scrolls (§5.1). An option row: min-height `size.row.height`, padding-inline `space.inset.sm`, the label in
    `type.ui.body`, `color.text.primary`, an optional second line in `type.ui.caption`, `color.text.secondary`, and a
    leading `size.icon` slot for the selected option's `check` glyph in `color.text.primary` (the shape, not a colour,
    marks the choice). The active option (`aria-activedescendant`, keyboard or pointer) sits on `color.surface.hover`; a
    plain-disabled option is at `opacity.disabled` and the arrows skip it; an option that the form's own rules make
    unavailable, with a stated reason, takes the validity look (E30-D04 §2.5; CMP-231's unavailable TIF, its §17,
    `E30-D04.md:511`): its label at `opacity.disabled`, the reason as its second line at full opacity and as its
    description, `aria-disabled`, arrow-reachable, and Enter re-shows the reason instead of choosing it, with no lock; a
    T2 option shows the lock and its full label in `color.text.tertiary` with the reason as its second line, stays
    arrow-reachable, and Enter re-shows the reason instead of choosing it. Status rows (searching, no results, a failed
    search) are text in `color.text.secondary`, not options.
27. **Numbers and alignment.** Every number binds `type.num.*` (JetBrains Mono, tabular; `15:40` rule 6). Quantities
    end-align — in a numeric field (CMP-008) and in a numeric table column with its header — so decimals line up;
    dates, times, ids and text start-align (slice 2 (#4290) conventions 16). The decimal separator is '.' and the group
    separator ',' in every locale (slice 2 (#4290) E14); a field with focus shows no group separator (§6 G18).
28. **Resize, zoom and reflow** (`05` §5.7; slice 1 conventions 11). Heights are minimums: at 112–150 % text fields,
    rows and options grow taller and never clip; a value never wraps (a long one scrolls inside its well); labels,
    messages and reasons wrap. At 200 % zoom on the 1280 × 800 frame a popup caps its height to the room above or
    below its field and scrolls; the calendar keeps its 7 columns and scrolls inside the viewport; CMP-040's inline
    layout stacks below its fit width; CMP-049 reflows to its stacked layout (`16` §3 rule 4).
29. **Forced colours** (`05` §8.1; slice 1 conventions 12). The well's boundary is a real border, so forced colours
    keep it in a system colour, and the value takes `FieldText` on `Field`; the invalid 2 px width survives as a shape
    cue and the glyph and the message carry the state; focus is a Highlight outline; plain disabled is GrayText;
    read-only keeps its border; T2's well keeps a GrayText border, while its label and lock stay CanvasText
    (ButtonText inside a button), its value keeps `FieldText` and its reason is CanvasText — the label is never
    dimmed, and forced colours grey only `:disabled`, never `aria-disabled`, so the border is set by hand (§5.2
    records E42-D03 §15's opposite rule); an active option is Highlight with HighlightText; a selected table row or
    day sets a Highlight fill with HighlightText explicitly (`forced-color-adjust: none` on that part, system colours
    only).

## 4. Token mirror and themes

No token is added or changed, and the Penpot mirror is slice 1 §4's, re-synced with #3925 (`a0132de01`, 2026-10-20,
the last change to `packages/ui/tokens`); every figure here and in the audit is measured at that state. The slice
binds only published semantic tokens, in all three themes: `color.surface.app|canvas|raised|overlay|hover|selected`,
`color.border.default|subtle|selected`, `color.text.primary|secondary|tertiary`, `color.action.primary.default`,
`color.action.selected`, `color.status.danger.default|strong`, `color.focus.ring`; `size.control.height`,
`size.row.height`, `size.icon`; `space.inset.xs|sm|md`, `space.stack.xs|md|lg`, `space.field.gap`;
`radius.control|card`; `elevation.popover`; `type.ui.body|body-strong|label|caption|heading-sm`, `type.num.base`; and
the named primitives of §5.2. Each section's token table maps the catalogue names that do not exist (`color.border.*`,
`color.text.error`, `radius.sm`, `radius.md`, `elevation.2`, `font.mono`, `space.field.*`, `space.formsection.*`) to
shipped tokens, and the catalogue's Tokens lines are rewritten to match. A token gap is an owner decision (§6 (a)); none
is invented.

## 5. Recorded exceptions

### 5.1 Geometry constants without a token

Each value is drawn raw and logged for ticket AC2 ("zero hardcoded hex or px values"); rows that recur from slices 1
and 2 keep their resolution.

| Constant                   | Value                                                                                                                 | Components                                                                                  | Proposed resolution                                                                          |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Field boundary             | 1 px, aligned inside (the value of `border.hairline`), unbound                                                        | every well; the read-only and T2 hairlines; the popup edge; CMP-034's box; today's day ring | As slice 1 §5.1 "Control outline": name `border.hairline` a primitive exception (slice 1 B1) |
| Focus-ring offset, radius  | 2 px offset; target radius + 2                                                                                        | every focusable part                                                                        | As slice 1 B1 and B2                                                                         |
| Popup height               | at most 10 option rows (10 × `size.row.height`), then it scrolls                                                      | CMP-009, CMP-048                                                                            | A component constant counted in rows, so density keeps it; no token (§6 G5)                  |
| Calendar grid              | 7 columns × 6 rows of `size.control.height` square day cells                                                          | CMP-047                                                                                     | Data layout from bound tokens; the counts are the calendar's (§6 G5)                         |
| Mask run                   | 8 mask characters, whatever the value's length                                                                        | CMP-034                                                                                     | A security constant (§7 CMP-034 rule S4); no token                                           |
| Timing                     | auto-hide 10 s with a 2 s warning (CMP-034); the 500 ms announcement debounce (CMP-048)                               | CMP-034, CMP-048                                                                            | Behaviour constants, not style; the auto-hide cap is §6 G19                                  |
| Data and sample dimensions | column widths, the inline label column (E30-D02 §2: 56 / 72 px), skeleton row counts; the 960 px documentation column | CMP-049, CMP-040; every section                                                             | As slice 1 §5.1 "Sample dimensions": data and documentation layout, no token                 |

### 5.2 Other recorded exceptions

- **Named primitives** (slice 1 §5.2): `border.focus` for the ring width; `border.thick` for the 2 px invalid boundary
  and the 2 px outline of a selected calendar day (#3925's selected role, as slice 1's pressed IconButton);
  `opacity.disabled` for plain disabled, for days outside the allowed range and for an option's label in the validity
  look (conventions 26), all inactive; `size.icon.sm` for the 2b lock badge on an icon-only row action (as slice 1's
  badge); and `motion.duration.fast` with `motion.easing.decelerate` for the popup fade (slice 1 A8: only motion
  primitives exist).
- **A cross-spec clash, recorded (forced colours):** E42-D03 §15 renders T2 labels and glyphs in `GrayText` and their
  reasons in `CanvasText` (`docs/design/E42/E42-D03.md:642`), the opposite of slice 1 conventions 12 on `main`
  (`E05-D02.md:157`–`:158`: a gated control's shape border is GrayText, while its label, value indicators and lock
  stay CanvasText or ButtonText). E09-D09 sets no forced-colours rule, so this slice keeps slice 1's (conventions 29),
  and E42-D03 follows at its boards PR.
- **Cross-spec clashes with E30-D04, recorded for its owner** (and E30-D02's for its §13), each resolved here or put
  to you:
  - **T2 on a field (aligned).** E30-D04 §2.5 (2) and its CMP-100, 101 and 119 ARIA rows put the lock inside the well,
    leading the value, and keep the field's own label `color.text.secondary` (`E30-D04.md:205`, `:292`, `:309`, `:394`);
    this slice had led the CMP-040 label with the lock and turned it tertiary. E09-D09 §2.2 has no field case, and
    E30-D04 is the merged contract of the fields built on CMP-008 and CMP-009, so conventions 24 now follows it for
    every slice-3 field (the CMP-007, 008, 009, 040, 047, 048, 065 and 079 sections, their `15` lines and audit §1–§4).
    E30-D04's own `15` CMP-100 and CMP-101 A11y lines (on `main` since #4308) still say the lock is "leading the label";
    they follow its §2.5 (2) at its next revision.
  - **"Read-only" names T2 there.** E30-D04 and `15` CMP-100 and CMP-101 (#4308) call the fields' T2 state read-only
    (their States lines, the `ReadOnlyT2` story), where this slice keeps read-only for the non-T2 `readonly` look
    (conventions 22, 25) and calls the gated state disabled-with-reason (T2); E30-D04's owner renames at its next
    revision.
  - **The step buttons (put to you: §6 G22).** E30-D02 §2 names the nudge buttons CMP-008's `[−]` `[+]`
    (`E30-D02.md:107`); E30-D04 §4 binds them `color.surface.raised` and `radius.control` (`E30-D04.md:291`; `15`
    CMP-100 Tokens since #4308), and E30-D02 §13's Tab order stops on the price field's `[−]` and `[+]`
    (`E30-D02.md:345`); here they are CMP-002 ghost IconButtons with `tabindex="-1"`. Slice 1's CMP-002 has no raised
    variant, so aligning is not a text edit in this slice.
  - **The large step (aligned).** E30-D04 §4 keeps `PageUp`/`PageDown` ×10 for CMP-100 and CMP-101 and routes E30-D02
    §13's ×100 to D02's owner (`E30-D04.md:293`, its C14 `:1039`); G8's `largeStep` keeps ×10 as the default and names
    no ×100 for them.
  - **Unavailable options (aligned).** E30-D04 §17 keeps an unavailable TIF option present, focusable and with its
    reason, in the validity look (`E30-D04.md:511`; `15` CMP-231), which CMP-009's option looks lacked; conventions 26
    and CMP-009 now carry it, with a per-option `unavailableReason?` (§6 G9).
- **Absolute internals:** only slice 1 B3's (a) focus ring and (b) overlay anchors (the popups and the calendar
  dialog). CMP-049's sticky header is `position: sticky` in code and a flex row in Penpot, not an absolute internal.
- **Penpot variant-set chrome:** as slice 1 B7.

## 6. Decisions for the owner (collected)

Deduplicated across the 11 components and against slices 1 and 2; G1–G22 are new, each PROPOSED with its options and a
recommendation. These earlier decisions also cover this slice and are not asked again: slice 1 A2 (no selected-hover
token: a hovered selected row or day does not change), A3 (the field boundary binds a text token, G1), A6 (light
`color.status.danger.strong` equals the warning amber: the error glyph's shape and words carry it), A8 (motion
primitives), A10 (icon sizes), B1 and B2 (geometry), B3 (b) (popups are overlay anchors), C13 (strict matrix
reading) and C15 (the Storybook stories are E05-S01..S04's); slice 2 (#4290) E14 (number formatting), E24 (a
labelled divider is not a heading, which G14 answers for forms) and E27 (gated links: the host owns the gating through
CMP-079, never the atom, as conventions 24 has the host gate every slice-3 control).

### (a) Token gaps (E05-D01's token files, outside this PR's write set)

- **G1 — The field boundary token.** No `color.border.*` token reaches 3:1 on raised and overlay (slice 1 A3), so the
  1 px well boundary binds `color.text.tertiary` (5.20–6.29:1 dark, 5.44–6.81:1 light, 10.36–12.54:1 high contrast
  against the well and every host surface); E42-D03 §15 proposed `color.border.input` → `{color.text.tertiary}` (its
  DS-3) for the same reason. **Recommended:** add that alias in the E05 token follow-up (no visual change), together
  with slice 1 A3's control-outline token; keep `color.text.tertiary` until it lands. **Affects:** CMP-007, 008, 009,
  047, 048, 054.
- **G2 — The invalid look and `color.text.error`.** `15:115` names `color.text.error`, which does not exist, and the
  merged consumer specs disagree. Options: (a) `docs/design/E30/E30-D02.md` D16: a 2 px `color.status.danger.default`
  boundary, the `danger` glyph in `color.status.danger.strong` (the CMP-019 tone rule), the message in
  `color.text.primary` (red text alone measures 3.63:1); (b) `docs/design/E11/E11-D03.md` D03-CR-4: the boundary and
  glyph in `color.status.danger.strong`, the message on `color.status.danger.subtle`; (c) a new red text token
  (E30-D02's CR-2 `color.text.danger`). **Recommended:** (a) for every field: the boundary stays red in every theme
  (`.strong` is amber in dark and equal to warning in light, slice 1 A6), passes 3:1 against the well and every host
  surface (3.17:1 or more), and needs no new token; (b)'s block and (c) are not adopted. Usage rule (conventions 23):
  fields do not sit on `surface.hover` or `surface.selected`, where (a)'s boundary falls to 2.43–2.92:1 in dark
  (2.87:1 in high contrast on `surface.selected`). **Affects:** every validating field, CMP-040 (and E11-D03's
  go-to-date dialog when it is next revised).
- **G3 — Selected rows and days on #3925's selected role.** A checked CMP-005 box (`color.action.primary.default`) on
  a `color.surface.selected` row measures 2.58:1 in dark; on `color.action.selected` it measures 3.12 / 3.86 / 5.72:1,
  and row text 12.33 / 14.58 / 13.96:1. **Recommended:** a selected table row takes the `color.action.selected` tint
  (the checked box carries the state; no outline), and a selected calendar day the full selected role (the tint, a 2
  px inner `color.border.selected` outline, `color.text.primary`), as `15:487` already names `color.action.selected`;
  `docs/design/E11/E11-D04.md`'s `color.surface.selected` rows and E11-D03's primary-filled day follow when they are
  next revised. **Affects:** CMP-049, CMP-047.

### (b) Geometry constants and layout

- **G4 — The field well.** Three merged specs fill it differently: `color.surface.app` (E30-D02 D2),
  `color.surface.raised` (`docs/design/E13/E13-D03.md` SCR-035) and `color.surface.sunken` (E42-D03 §15's dialogs).
  **Recommended:** `color.surface.app` everywhere: white in light, an inset in dark, the value at 16.06 / 17.99 /
  18.18:1; `sunken` is pure black in dark (`05` §5 item 5) and equals `surface.selected` and `border.default` in light
  (#D6DAE0), and a `raised` well cannot be told from T2's `raised` well. E13-D03 and E42-D03 follow at their boards
  PRs. **Affects:** every field box.
- **G5 — Accept §5.1's new constants** (popup height in rows, the calendar grid counts, the mask run, the timings)
  under slice 1 B1's ruling. **Recommended:** yes; no new tokens. **Affects:** CMP-009, 034, 047, 048, 049.

### (c) Catalogue ambiguities (props, defaults, sizes)

- **G6 — Inline layout for CMP-040.** The order ticket lays its fields out with a label column (E30-D02 §2: 56 px
  compact, 72 px comfortable) that CMP-040 cannot express. **Recommended:** `layout?: "stacked" | "inline"` (default
  `stacked`); the column width is the host's data; inline stacks below its fit width (conventions 28). **Affects:**
  CMP-040 (SCR-060, the settings rows).
- **G7 — `size` on CMP-007 and CMP-009** has no values. **Recommended:** drop it: the height follows density through
  `size.control.height`, as slice 1 C3 recommends for CMP-004. The edit is held until you answer (§6 (f)).
- **G8 — CMP-008's large step.** `15:123` says `PageUp/PageDown` step ×10; E30-D02 §13 proposes `Shift+↑/↓` ×10 and
  `PageUp/PageDown` ×100 for price and size and leaves the contract to CMP-008; E30-D04 §4 keeps ×10 for CMP-100 and
  CMP-101 and routes the ×100 to D02's owner (`E30-D04.md:293`, its C14 `:1039`). **Recommended:** `Shift+↑/↓` ±10 ×
  `step` always; `PageUp/PageDown` ± `largeStep` (a new prop, default 10 × `step`, so the catalogue's ×10 stays the
  default, as E30-D04 §4 keeps it; should D02's owner adopt ×100, CMP-100 and CMP-101 pass 100 × tick); `Home`/`End` min
  and max. **Affects:** CMP-008 (CMP-100, CMP-101: E30-D04 §4 and its C14 stand unchanged on a "yes").
- **G9 — CMP-009's pattern.** `15:132` names the APG Listbox/Combobox pattern, `aria-activedescendant` and the Radix
  Select primitive, whose listbox takes DOM focus instead. **Recommended:** the APG select-only combobox (focus stays on
  the trigger, `aria-activedescendant` names the active option), whatever primitive meets it; `searchable` renders
  CMP-048's editable combobox, so there is one implementation of each; add `disabledReason?` (E42-D03 §20 asked for it
  for its role and level selects) and, on each option, `unavailableReason?` for the validity look (conventions 26),
  which CMP-231's unavailable TIF options need (E30-D04 §17, its `unavailableReason`). **Affects:** CMP-009 (CMP-048,
  CMP-231).
- **G10 — CMP-040's name and marker API.** (1) `labelId?`: the label carries an id, a native labelable control gets
  `<label for>`, and any other role (a radiogroup, a slider, a grid, a div combobox) gets `aria-labelledby` — this
  settles slice 1 C5's CMP-040 side. (2) Required and optional: `required` sets `aria-required="true"` and shows no
  asterisk; in a form that mixes both, the optional fields show "(optional)" after the label (E42-D02's "Display name
  (optional)"), through a new `optional?` prop. Option (b), an asterisk with a legend, is not recommended: most
  CandleViewer forms are all-required. **Recommended:** both parts. **Affects:** CMP-040 (CMP-006, CMP-010, CMP-003).
- **G11 — CMP-047's base API.** `docs/design/E11/E11-D03.md` D03-CR-2 asks for `inputTimezone`, `secondaryDisplay`,
  `formatHint` and a caption naming `min`/`max`; SCR-044's "Date+time picker" (`14:1011`) and SCR-098's "date/time
  range" (`14:2109`) need a time of day. **Recommended:** the base takes `formatHint` (default "YYYY-MM-DD"), the
  caption, and `withTime?` (an `HH:MM` field beside each date, UTC); its weeks start on Monday in every locale (ISO
  8601, the week ADR-0032's weekly bars and E11-D02's time axis already start on:
  `docs/plan/27-adrs/ADR-0032-alert-evaluation-placement.md:79`, `docs/design/E11/E11-D02.md:183`); `inputTimezone` and
  `secondaryDisplay` stay with SCR-044's dialog, their one consumer. **Affects:** CMP-047.
- **G12 — CMP-049's consumer requests.** E42-D03 Appendix A writes `grid?`, `sortPending?` and their A11y and Storybook
  clauses (`docs/design/E42/E42-D03.md:908-910`); E11-D04 §16 CR-D04-6 asks for a caption, a sticky header, a selection
  model, a stacked reflow, treegrid rows, a pinned first column and `fitChars`. **Recommended:** apply E42-D03's three
  rows here verbatim (its boards PR then finds them applied), adopt the caption, the sticky header, the checkbox
  selection (G21) and the stacked reflow, which `16` §3 rule 4 requires of every CMP-049 table, into the base; hold
  treegrid rows and the pinned column (`stickyFirstColumn`) out of the base for now: E29-D02's SCR-063 blotter asks for
  both too (treegrid rows in its D-1, `docs/design/E29/E29-D02.md:118`; sticky lead columns in its §5.1, `:146`), and
  its gap 1 (`:586`) routes the blotter's CMP-049 needs to E29-D04, so the base takes one contract for both consumers
  once E29-D04 specifies it; `fitChars` stays with E11-D04's chart table, its one consumer. **Affects:** CMP-049
  (SCR-045, SCR-121; SCR-063 through E29-D04).
- **G13 — CMP-054's name.** `15:548` has no name prop, and a placeholder is never a name. **Recommended:** a mandatory
  `label` that becomes `aria-label`; `Esc` clears a non-empty query, then bubbles. **Affects:** CMP-054.
- **G14 — CMP-065's heading.** A `legend` is not in the heading list (slice 2 (#4290) E24 left forms to carry their
  own). **Recommended:** the legend wraps a heading (`headingLevel?`, default 3); a collapsible section's disclosure
  button sits inside the heading (APG Disclosure); a collapsed section that holds an invalid field opens on submit.
  **Affects:** CMP-065 (SCR-060, SCR-114, the admin forms).
- **G15 — CMP-079's renderings.** D09 §8 DS-2 asks for a `form` prop (`"inline" | "tooltip"`) and E42-D03 §13 (4) for
  a `"notice"` form. **Recommended:** `form?: "inline" | "tooltip" | "notice"` (default `inline`; `tooltip` only for
  icon-only controls and toolbar segments) and `noticeId?` (required with `notice`); the A11y line gains the T2 rule in
  one sentence, which replaces the "decorative `locked` glyph, trailing" update slice 1 D13 promised (superseded by
  T2). **Affects:** CMP-079 and every gated control.
- **G16 — `aria-errormessage`.** `15:114` adds it "where supported". **Recommended:** drop it: the message is
  referenced once, by `aria-describedby`, so a screen reader that supports both reads it once `(heuristic)`.
  **Affects:** CMP-007 and every field through CMP-040.

### (d) Behaviour proposals

- **G17 — Validation and result announcements** (conventions 23). **Recommended:** validate on blur and on submit,
  re-validate on input once shown, announce a message politely once; CMP-027's `role="alert"` stays the host's submit
  summary; CMP-048 announces the result count or the no-results sentence politely, once per settled query, 500 ms after
  the last keystroke, never per keystroke, and a CMP-054 host announces its count the same way once its query settles
  (its debounce or Enter); an in-panel load failure (CMP-049's error state) is announced politely, which needs a polite
  error form of CMP-027 — handed to slice 4, which ships CMP-027 (E42-D03's `users.error` and E11-D04 §10's error state
  are polite already). **Affects:** CMP-040, every field, CMP-048, CMP-049, CMP-054.
- **G18 — Numeric entry.** **Recommended:** typing is never altered mid-keystroke; on blur the value is parsed,
  rounded to `precision` (the host may caption it, as CMP-100's "(rounded to nearest tick)") and range-checked; a
  typed value out of range is invalid with the bound in the message (E30-D02 §13: "Minimum 0.001"), never silently
  clamped; the arrows and the step buttons stop at the bounds; no group separator while the field has focus.
  **Affects:** CMP-008 (CMP-100, CMP-101).
- **G19 — CMP-034's security rules** (the ticket's Security note, written as design rules S1–S7 in §7 CMP-034).
  **Recommended:** approve S1–S7 and flag them to the security engineer for E05-X02, with two questions for that
  review: a cap on `autoHideMs` (proposed 30 s), and whether the Electron shell writes a copied secret with the
  clipboard formats that keep it out of Windows clipboard history and cloud sync. The cap is held until then (§6 (f)).
  S1–S7 cover client-held API keys and secrets only: recovery codes are CMP-206's one-time list (§7 CMP-034), whose
  own display rules go to the same review. **Affects:** CMP-034 (SCR-126, SCR-127).
- **G20 — CMP-034 and WCAG 2.2.1.** The catalogue's 2 s warning cannot meet 2.2.1's "extend" option (20 s); re-revealing
  is one press with focus kept on the toggle, so nothing is lost. **Recommended:** add a Settings → Accessibility option
  that lengthens the auto-hide up to 10× (2.2.1's "adjust" option), capped by G19; held until G19 is answered.
  **Affects:** CMP-034, SCR-117.
- **G21 — Table selection and row actions.** **Recommended:** selection is a leading CMP-005 column with a select-all
  header box (mixed when some rows are selected); row actions are a trailing CMP-002 `more-horizontal` IconButton
  opening a CMP-041 row menu (`Shift+F10` from the row), whose gated items are T2 with the reason as their second line;
  an inline gated IconButton takes 2b. Either column makes the table a grid (§7 CMP-049's mode rule: one Tab stop,
  `05` §3.4 item 2), where `Space` also toggles the focused row and rows carry `aria-selected`; table mode keeps no
  control in a body row. **Affects:** CMP-049 (CMP-114, SCR-121, SCR-063).
- **G22 — CMP-008's step buttons: fill and Tab stops** (§5.2). E30-D02 §2 names the order ticket's nudge buttons
  CMP-008's `[−]` `[+]` (`E30-D02.md:107`); E30-D04 §4 binds them `color.surface.raised` and `radius.control`
  (`E30-D04.md:291`; `15` CMP-100 Tokens since #4308); E30-D02 §13's Tab order stops on the price field's two (`:345`),
  while its H10 calls them optional for pointer users, since the field takes typing and arrows (`:678`), and the size
  field's pair is not listed there. Options: (a) this slice: CMP-002 ghost IconButtons with `tabindex="-1"` (§7
  CMP-008); (b) E30's: a `color.surface.raised` fill and two Tab stops, which needs a raised CMP-002 variant (slice 1's
  has primary, secondary, ghost and danger) or CMP-008's own buttons, and a bound button that is `aria-disabled` rather
  than `disabled`, since a disabled one drops the focus it holds; (c) the base as (a), with CMP-100 and CMP-101
  overriding the fill in their own entries, as `15` CMP-100 reads. **Recommended:** (a): the base composes the published
  CMP-002 unchanged; T2's raised fill and hairline (D09 §2.2) stay a visible change on the buttons, which a raised rest
  fill would already wear; the raised fill measures 1.06 / 1.07 / 1.06:1 against the ticket's canvas panel (E30-D02 D2;
  audit §4), so it marks nothing the glyph does not; and the arrows do the buttons' job (the APG Spin Button pattern),
  which keeps two Tab stops per numeric field out of a dense ticket. On a "yes", E30-D04 §4, `15` CMP-100's Tokens line
  and E30-D02 §13 follow at their next revision. **Affects:** CMP-008 (CMP-100, CMP-101).

### (e) Catalogue clauses applied, awaiting your approval

A "no" reverts the named clause; the catalogue lines carry no approval marker (slice 1 conventions 13).

- CMP-007: States line (conventions 22–24), A11y "no `aria-errormessage`" (G16) and the polite once announcement (G17),
  Tokens (G1, G2, G4), Props `disabledReason?`.
- CMP-008: Props `invalid?`, `readOnly?`, `disabledReason?`, `suffix?`, `largeStep?` (G8); States line; A11y step keys
  (G8), blur parsing (G18) and the step buttons' `tabindex="-1"` (G22); Tokens (G1, G4), with the step buttons as
  CMP-002 ghost (G22).
- CMP-009: Props `placeholder?`, `invalid?`, `disabledReason?`, per-option `disabledReason?` and `unavailableReason?`,
  `searchable` → CMP-048 (G9); States line; A11y pattern sentence and primitive clause (G9); Tokens, with the listbox's
  "at most 10 rows" (G5).
- CMP-034: Props `label`, `copyable?`, the source and mount rules (G19); States line; A11y the toggle names from
  `label`, rules S1–S7 and the recovery-code routing (G19); Tokens.
- CMP-040: Props `labelId?`, `optional?` (G10), `disabledReason?`, `layout?` (G6); Variants line (G6); States line;
  A11y (G10, conventions 23–24); Tokens.
- CMP-047: Props `withTime?`, `formatHint?`, `rangeCaption?` (G11), `invalid?`, `disabled?`, `readOnly?`,
  `disabledReason?`; Variants line; States line; A11y dialog keys and "weeks start on Monday" (G11); Tokens with the
  selected role (G3).
- CMP-048: Props `noResultsText` (§7 CMP-048), `invalid?`, `disabled?`, `disabledReason?`; States line; A11y
  announcement rule (G17); Tokens, with the listbox's "at most 10 rows" (G5).
- CMP-049: E42-D03's three rows verbatim and `caption`, `loading?`, `error?` (G12); Variants line and its mode rule
  (G12, G21); States line; A11y additions (G12, G21); Tokens with the selected role (G3); Storybook.
- CMP-054: Props `label`, `disabled?` (G13); States line; A11y `Esc` (G13) and the host's polite count, once per settled
  query (G17); Tokens.
- CMP-065: Props `headingLevel?`, `disabledReason?`, `disabled?` (G14); States line; A11y; Tokens.
- CMP-079: Props `form?`, `noticeId?`, the Variants line and the A11y T2 sentence (G15); Tokens; Storybook.

### (f) Catalogue edits held (not in this PR)

- CMP-007 and CMP-009: removing `size` (G7).
- CMP-034: the `autoHideMs` cap and the accessibility setting that lengthens it (G19, G20).
- CMP-049: the treegrid rows and the pinned column (`stickyFirstColumn`) that E11-D04 CR-D04-6 and E29-D02 both ask for,
  until E29-D04 specifies them, and E11-D04's `fitChars`, which stays with it (G12).
- CMP-047: E11-D03 D03-CR-2's `inputTimezone` and `secondaryDisplay` (G11), which stay with SCR-044.

## 7. Components

**Boards PENDING (text-first, 2026-10-23).** No section below has a Penpot build. Each names the variant set the boards
PR builds on page `10 Components — Atoms` and the export it adds, `docs/design/E05/img/CMP-0xx-name.png`.

### CMP-007 · TextInput

**Catalogue (verbatim, `15:112`, `15:114`):**

- **Props**: `value` · `onChange` · `placeholder?` · `prefix?/suffix?: ReactNode` · `size` · `invalid?: boolean` · `errorMessage?` · `disabled?` · `readOnly?` · `inputMode?` · `maxLength?`.
- **A11y**: `<input>` with `aria-invalid`, `aria-describedby` → error message id, `aria-errormessage` where supported.

| Axis  | Values                                                                            | Default |
| ----- | --------------------------------------------------------------------------------- | ------- |
| State | default, hover, focus-visible, invalid, disabled, disabled-with-reason, read-only | default |
| Value | filled, empty                                                                     | filled  |
| Affix | none, both                                                                        | none    |

_Boards PENDING: `CMP-007 · TextInput`, export `img/CMP-007-textinput.png`._

**Variants × States (9 cells):**

| Cell                      | Axes                     | What it shows                                                                                                                                |
| ------------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| default                   | Value=filled, Affix=none | the well (conventions 21) with "trader_01" in `color.text.primary`                                                                           |
| hover                     | as default               | the boundary in `color.text.secondary`                                                                                                       |
| focus-visible             | as default               | the CMP-039 ring, the caret; the boundary unchanged                                                                                          |
| invalid                   | as default               | a 2 px `color.status.danger.default` boundary; the message line is CMP-040's (its invalid cell)                                              |
| disabled                  | as default               | the whole field at `opacity.disabled`                                                                                                        |
| disabled-with-reason (T2) | as default               | `color.surface.raised` well, 1 px `color.border.default` hairline; the `lock` leads the value, both `color.text.tertiary`; reason: CMP-040's |
| read-only                 | as default               | no fill, 1 px `color.border.default` hairline, the value in `color.text.primary`                                                             |
| Value=empty               | State=default            | the placeholder in `color.text.tertiary`                                                                                                     |
| Affix=both                | State=default            | the two slots: a leading glyph (`search`) and a trailing unit ("USDT"), both `color.text.tertiary`                                           |

**Not drawn:** active — a press focuses the field, which is the focus look; loading — no catalogued async state (a
submitting form is the host's busy state, conventions 25); error — the invalid state; empty — the Value axis.

**Anatomy** (compact / comfortable; only the height changes):

| Part          | Fill and stroke                                                                | Text or glyph                                                      | Radius, size, spacing                                                                       |
| ------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| well          | `color.surface.app`; 1 px `color.text.tertiary` (states per conventions 22–24) | —                                                                  | `radius.control`; min-height `size.control.height` 24 / 32; padding-inline `space.inset.sm` |
| value         | —                                                                              | `type.ui.body`, `color.text.primary` (T2 `color.text.tertiary`)    | one line, scrolls inside the well                                                           |
| placeholder   | —                                                                              | `type.ui.body`, `color.text.tertiary`                              | —                                                                                           |
| prefix/suffix | —                                                                              | text `type.ui.body`; glyph `size.icon`; both `color.text.tertiary` | gap `space.inset.xs`                                                                        |
| lock (T2)     | —                                                                              | CMP-019 `lock` at `size.icon`, `color.text.tertiary`               | first in the well, ahead of any prefix; gap `space.inset.xs` (conventions 24)               |
| focus ring    | 2 px `color.focus.ring` (`border.focus`), 2 px offset                          | —                                                                  | `radius.control` + 2                                                                        |

**Keyboard** (no APG widget pattern: the native single-line text input):

| Keys                                         | Action                                                                                                                             |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab                              | Moves focus to or from the field; the ring shows. Plain disabled is skipped; read-only and T2 stay focusable.                      |
| Typing, Backspace, Delete, ← / →, Home / End | Native editing; read-only allows selection and copy only.                                                                          |
| Enter                                        | The enclosing form's native implicit submission, if the host has one; a trading ticket submits only with `Ctrl+Enter` (`05` §3.2). |
| Esc                                          | Not handled: it bubbles to the host (a dialog closes).                                                                             |
| Any key while T2                             | Changes nothing (`readonly`); the first refused key of a focus visit re-shows the reason with one polite announcement.             |

**Accessible name and role:**

| Element         | Role                                   | Name                                                                                               | ARIA                                                                                                                                                                                     |
| --------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| input           | textbox (native `<input type="text">`) | CMP-040's `<label for>` ("Username"); without a visible label, `aria-label`; never the placeholder | invalid: `aria-invalid="true"`, `aria-describedby` → the error node; read-only: `readonly`; T2: `aria-disabled="true"` + `readonly` + `aria-describedby` → the reason; plain: `disabled` |
| suffix (a unit) | text                                   | —                                                                                                  | its id joins `aria-describedby`, so "USDT" is read with the field                                                                                                                        |
| prefix glyph    | none                                   | —                                                                                                  | `aria-hidden="true"`                                                                                                                                                                     |
| lock (T2)       | img                                    | "Not available"                                                                                    | CMP-019 `decorative=false`, in the well before the input (conventions 24)                                                                                                                |

**T2 and not T2:** T2, conventions 24 (rendering 2a, through CMP-040). Not T2: an invalid value, a submitting form
(`readOnly`, no lock) and a value nobody may edit (read-only) — conventions 25.
**Validation:** conventions 23, with the host's copy (`14:145`: "Enter your username.", "Enter your password.").
**Hit target:** the whole well, `size.control.height` tall and as wide as its host gives it (at least 24 px); no
exception.
**Motion:** none: every state change is an instant token swap in both modes.
**Resize & overflow:** the height is a minimum (conventions 28); the value never wraps and scrolls inside the well;
prefix and suffix never shrink.
**Forced colors:** conventions 29.

**Catalogue alignment** (`15:109-117`): Props gains `disabledReason?` and notes that `placeholder?` is an example,
never the label (conventions 21); a States line replaces "default, focus, invalid (red border + icon + message, not
colour-only), disabled, readOnly" with the nine looks above (conventions 22–24); A11y drops "`aria-errormessage` where
supported" (G16) and adds the polite once announcement and the T2 semantics; Tokens names the shipped tokens (G1, G2,
G4): `color.surface.app`, `color.text.tertiary`, `color.text.secondary`, `color.text.primary`,
`color.status.danger.default`, `color.border.default`, `color.surface.raised`, `color.focus.ring`, `radius.control`,
`size.control.height`, `size.icon`, `space.inset.sm`, `space.inset.xs`, `type.ui.body`, `type.num.base` (numeric
inputs), `border.thick`, `border.focus`, `opacity.disabled`; Storybook adds ReadOnly and DisabledWithReason. Held:
dropping `size` (G7).

### CMP-008 · NumericStepperInput

**Catalogue (verbatim, `15:122-123`):**

- **Props**: `value: number` · `min?/max?` · `step: number` · `precision: number` · `onChange` · `onStep(direction)` · `disabled?`.
- **A11y**: `role="spinbutton"` semantics (`aria-valuenow/min/max/text`), `↑/↓` arrow keys step by `step`, `PageUp/PageDown` step ×10, `Home/End` jump to min/max.

| Axis  | Values                                                                            | Default |
| ----- | --------------------------------------------------------------------------------- | ------- |
| State | default, hover, focus-visible, invalid, disabled, disabled-with-reason, read-only | default |
| Bound | none, at-max                                                                      | none    |
| Unit  | false, true                                                                       | false   |

_Boards PENDING: `CMP-008 · NumericStepperInput`, export `img/CMP-008-numericstepperinput.png`._

**Variants × States (9 cells):** the seven states of CMP-007 at Bound=none, Unit=false (the same well looks, the T2
cell's lock leading the value; the `[−]` `[+]` glyphs turn `color.text.tertiary` there), plus **Bound=at-max** (the
value at its maximum, `[+]` plain disabled at `opacity.disabled`: availability, not T2) and **Unit=true** ("5" with a
"%" suffix; a host may put the unit in the label instead, as `docs/design/E11/E11-D03.md` §6.2 does). **Not drawn:**
active (the step buttons' pressed look is CMP-002's), loading (none catalogued), error (the invalid state), empty (an
empty number field is invalid on blur when the host requires a value; otherwise it shows its placeholder as CMP-007
does).

**Anatomy:** the CMP-007 well, with the value in `type.num.base`, end-aligned (conventions 27); the unit suffix in
`type.ui.body`, `color.text.tertiary`; then, outside the well after a `space.inset.xs` gap, two CMP-002 ghost
IconButtons `[−]` (`minus`) and `[+]` (`plus`), `size.control.height` square, `space.inset.xs` apart (E30-D02 §2),
glyphs `color.text.secondary`, hover `color.surface.hover` with `color.text.primary` (slice 1 conventions 3); E30-D04 §4
fills the order ticket's pair `color.surface.raised` (§5.2, §6 G22).

**Keyboard** (WAI-ARIA APG Spin Button pattern):

| Keys                  | Action                                                                                                                      |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab       | Moves focus to or from the input. The `[−]` `[+]` buttons are not tab stops (`tabindex="-1"`): the keys below do their job. |
| ↑ / ↓                 | Value ± `step`, rounded to `precision`; stops at `max` / `min`, never wraps.                                                |
| Shift+↑ / Shift+↓     | Value ± 10 × `step` (G8).                                                                                                   |
| Page Up / Page Down   | Value ± `largeStep` (default 10 × `step`, the catalogue's ×10, which E30-D04 §4 keeps for CMP-100 and CMP-101) (G8).        |
| Home / End            | `min` / `max`, when set.                                                                                                    |
| Typing                | Edits the text; parsed, rounded and range-checked on blur, never mid-keystroke (G18).                                       |
| Enter                 | Commits the typed value (the blur rules); implicit form submission is the host's, as CMP-007.                               |
| Any of these while T2 | Changes nothing; the first refused key of a focus visit re-shows the reason with one polite announcement.                   |

A pointer press on `[−]` or `[+]` steps once; a held press does not repeat (no timing-dependent input). Their
`tabindex="-1"` is §6 G22 (E30-D02 §13 stops on the price field's pair).

**Accessible name and role:**

| Element     | Role                                                                     | Name                                    | ARIA                                                                                                                                              |
| ----------- | ------------------------------------------------------------------------ | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| input       | spinbutton (`<input type="text" inputmode="decimal" role="spinbutton">`) | CMP-040's label ("Auto-scale margin")   | `aria-valuenow` (the number), `aria-valuemin`/`max` when set, `aria-valuetext` with the unit ("5 %"); invalid, read-only, T2 and plain as CMP-007 |
| `[−]` `[+]` | button, `tabindex="-1"`                                                  | "Decrease {label}" / "Increase {label}" | plain `disabled` at a bound; T2: `aria-disabled="true"` + `aria-describedby` → the field's reason                                                 |
| unit suffix | text                                                                     | —                                       | `aria-hidden="true"`: `aria-valuetext` already carries it                                                                                         |

**T2 and not T2:** T2, conventions 24; the step buttons share the field's reason, and a press re-shows it. Not T2: a
bound (availability), an out-of-range value (validity).
**Validation:** conventions 23 and G18; the bound is in the message (E30-D02 §13: "Minimum 0.001").
**Hit target:** the well; each step button 24 × 24 (32 × 32), meeting WCAG 2.5.8 by size.
**Motion:** none. **Resize & overflow:** as CMP-007; the step buttons never grow. **Forced colors:** conventions 29;
the step buttons follow CMP-002 (in T2 a GrayText border and a ButtonText glyph, slice 1 conventions 12).

**Catalogue alignment** (`15:119-126`): Props gains `invalid?`, `readOnly?`, `disabledReason?`, `suffix?` (the unit) and
`largeStep?` (default 10 × `step`); a new States line (default, hover, focus-visible, invalid, disabled,
disabled-with-reason (T2), read-only; at a bound the matching step button is plain disabled); A11y gains the unit in
`aria-valuetext`, `Shift+↑/↓`, `largeStep`, the step buttons' names and `tabindex="-1"`, and the blur rules (G8, G18,
G22); Tokens: the CMP-007 well, the end-aligned `type.num.base` value and the step buttons' CMP-002 ghost tokens (G22);
Storybook adds Invalid and DisabledWithReason.

### CMP-009 · Select

**Catalogue (verbatim, `15:131-132`):**

- **Props**: `options[]` · `value` · `onChange` · `size` · `disabled?` · `searchable?: boolean`.
- **A11y**: WAI-ARIA APG "Listbox"/"Combobox" pattern (uses Radix Select primitive), `aria-expanded`, `aria-activedescendant`, type-ahead.

| Axis       | Values                                                                       | Default  |
| ---------- | ---------------------------------------------------------------------------- | -------- |
| State      | default, hover, focus-visible, open, invalid, disabled, disabled-with-reason | default  |
| Value      | selected, placeholder                                                        | selected |
| Searchable | false, true                                                                  | false    |

_Boards PENDING: `CMP-009 · Select`, export `img/CMP-009-select.png`._

**Variants × States (9 cells):** the trigger in default, hover, focus-visible, invalid, disabled and
disabled-with-reason (the CMP-007 looks, "sub_001" in the well and a trailing `chevron-down` in `color.text.secondary`);
**open**: the chevron turns `chevron-up` and the listbox (conventions 26) shows five option looks — rest, active on
`color.surface.hover`, selected with the `check` glyph, plain disabled, and a T2 option ("sub_002", reason
`rbac.account_read_only` "You can view this account, not trade it.") with its second line — and, as a documentation
sample beside it, the sixth: CMP-231's list under a market order, its "FOK" option in the validity look with E30-D02
§14's `tif.unavailable.market` "Market orders are always IOC on Bybit" (E30-D04 §17); **Value=placeholder** ("Choose…"
in `color.text.tertiary`); **Searchable=true** at open: CMP-048's editable input in the trigger (G9). **Not drawn:**
active (opening is the open cell), read-only (a value nobody may change is plain text, CMP-020), loading (a Select's
list is closed and local; an async list is CMP-048), empty (a Select always has options).

**Anatomy:** the trigger is the CMP-007 well with the value or placeholder in `type.ui.body` and a trailing
`chevron-down` at `size.icon`, `color.text.secondary`, decorative; the listbox is conventions 26; type-ahead has no
visual.

**Keyboard** (WAI-ARIA APG select-only Combobox pattern; G9):

| Keys                               | Action                                                                                                                              |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab                    | Moves focus to or from the trigger.                                                                                                 |
| Enter, Space, ↓, ↑, Alt+↓ (closed) | Opens the listbox; the active option is the selected one, else the first.                                                           |
| Home / End (closed or open)        | Opens on, or moves to, the first / last option.                                                                                     |
| A printable character              | Opens if closed and moves to the next option that starts with the typed string (type-ahead).                                        |
| ↓ / ↑ (open)                       | Next / previous option; plain-disabled options are skipped, validity-look and T2 options are not; no wrap.                          |
| Page Up / Page Down (open)         | Moves ten options.                                                                                                                  |
| Enter or Alt+↑ (open)              | Chooses the active option and closes; focus stays on the trigger. An unavailable or T2 option is never chosen; its reason re-shows. |
| Esc (open)                         | Closes without changing the value; focus stays on the trigger. A second Esc bubbles.                                                |
| Tab (open)                         | Chooses the active option (never a validity-look or T2 one), closes and moves focus on (APG).                                       |
| Any of these while T2              | The listbox never opens; the first refused key of a focus visit re-shows the reason with one polite announcement (E42-D03 §13 (6)). |

**Accessible name and role:**

| Element | Role     | Name                                                  | ARIA                                                                                                                                       |
| ------- | -------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| trigger | combobox | CMP-040's label through `aria-labelledby` ("Account") | `aria-haspopup="listbox"`, `aria-expanded`, `aria-controls`, `aria-activedescendant` while open; invalid and T2 as CMP-007 (no `readonly`) |
| listbox | listbox  | the same label                                        | —                                                                                                                                          |
| option  | option   | its label (and second line)                           | `aria-selected="true"` on the chosen one; plain: `aria-disabled="true"`; unavailable, T2: also `aria-describedby` → its reason line        |
| chevron | none     | —                                                     | `aria-hidden="true"`                                                                                                                       |

**T2 and not T2:** a gated select is T2 through CMP-040 (conventions 24); a gated option is a T2 option (conventions
26). Not T2: an unchosen required value (validity); an option the form's own rules make unavailable takes the validity
look with its reason (conventions 26), and one with no reason to give is plain disabled.
**Validation:** conventions 23; a required select with no choice is invalid on submit, with the host's sentence.
**Hit target:** the trigger well; each option row the popup's full width × `size.row.height`. **Motion:** the listbox
fades in over `motion.duration.fast` with `motion.easing.decelerate`, no movement; motion-reduce: instant (slice 1 A8).
**Resize & overflow:** the trigger's value truncates with an ellipsis only when its host is narrower than the value (the
full value stays its accessible value); options wrap to two lines, then truncate with the full text in the name.
**Forced colors:** conventions 29; the chevron and the check are `currentColor`; a T2 option keeps its lock, label and
reason in CanvasText (HighlightText while active); a validity-look option's label is GrayText, set by hand (forced
colours grey only `:disabled`), and its reason CanvasText (HighlightText while active).

**Catalogue alignment** (`15:128-135`): Props gains `placeholder?`, `invalid?`, `disabledReason?` and, on each option,
`disabled?`, `unavailableReason?` (the validity look) and `disabledReason?` (T2) (conventions 26), and `searchable`
renders CMP-048's editable combobox (G9); a new States line with the open state and the six option looks; A11y replaces
"(uses Radix Select primitive)" with "(any primitive that meets the select-only combobox,
`docs/design/E05/E05-D02-form-controls.md` §6 G9)", since Radix Select's listbox takes DOM focus, and appends "the
trigger keeps focus and `aria-activedescendant` names the active option (the APG select-only combobox)", the `Esc` rule
and the validity-look and T2 options' `aria-describedby`, with neither `Enter` nor `Tab` choosing them; Tokens:
`elevation.2` → `elevation.popover`, `radius.md` → `radius.card`, plus the field tokens and `opacity.disabled` for an
unavailable option's label; Storybook adds Open, UnavailableOption and DisabledWithReason. Held: dropping `size` (G7).

### CMP-034 · MaskedValue

**Catalogue (verbatim, `15:362-363`):**

- **Props**: `value: string` · `revealed?: boolean` · `onToggleReveal` · `autoHideMs?: number` (default 10000, re-masks automatically).
- **A11y**: toggle is CMP-002 IconButton with label "Show secret"/"Hide secret"; auto-hide timer announced via polite live region ~2s before hiding ("Secret will hide in 2 seconds") satisfying WCAG 2.2.1 (no silent unannounced timing change).

| Axis     | Values                             | Default |
| -------- | ---------------------------------- | ------- |
| State    | masked, revealed, expiring, copied | masked  |
| Copyable | false, true                        | false   |

_Boards PENDING: `CMP-034 · MaskedValue`, export `img/CMP-034-maskedvalue.png`._

**Variants × States (4 cells):** **masked** (Copyable=false: the box with the 8-character mask and the "Show" toggle);
**revealed** (the value in mono, "Hide" toggle, the countdown "Hides in 8 s"); **expiring** (the last 2 s: "Hides in 2
s", annotated with the one announcement); **copied** (Copyable=true, masked, CMP-033 in its copied state). **Not
drawn:** hover, focus-visible and active are the nested CMP-002's and CMP-033's own (slice 2 (#4290) conventions 20);
disabled-with-reason does not apply (the component lives only on owner-only admin screens, SCR-126 and SCR-127 under
`/admin`, which every other session never reaches: D09 §2.1 step 1, T3); disabled, read-only, loading, error and
empty do not apply (the component renders only when it holds a value, and it is read-only by nature).

**Security design rules** (the ticket's Security note; flagged to the security engineer for E05-X02, §6 G19):

- **S1 Never the default.** Every mount starts masked: `revealed` is never `true` at mount (a lint or test fails a
  consumer that opens it revealed). A route change, the window losing focus or the tab going hidden, the idle lock
  (`docs/design/E09/E09-D06.md`) and sign-out re-mask it; revealing one value masks any other on the page.
- **S2 Opt-in.** Only an explicit press of the reveal toggle (pointer, Enter or Space) reveals; never hover, focus, a
  hotkey, a "reveal all" or a URL parameter.
- **S3 Time-limited.** The value re-masks `autoHideMs` after the press (default 10 s; the cap is §6 G19); "Hide"
  re-masks at once; a new press restarts the clock.
- **S4 Nothing leaks while masked.** The DOM holds the 8-character mask only — not the value, not in an attribute, a
  `title`, a data attribute, the accessible name or a CSS-hidden node; the mask's length never tells the value's;
  print renders the mask.
- **S5 Copy never logs.** With `copyable`, CMP-033 copies the value from memory on an explicit press; its live region
  says "Copied" only (slice 2 (#4290) E21); no log, analytics event, audit record, error report or telemetry carries
  the value, its length or anything derived from it (C-12.2, C-12.6). The clipboard-history question is §6 G19's.
- **S6 Only a value the client holds.** `value` is a key or secret the user has just entered in the current flow
  (SCR-126, SCR-127), before it is sent. No API returns a stored secret (C-2.7), so after a save the screen shows the
  server's masked metadata (the label, `key_id_masked`, the fingerprint) as plain text, with no reveal.
- **S7 Short-lived.** The value leaves component state on unmount and after a successful submit; it never enters
  browser storage (C-12.2), a URL, an autofill store or the undo history.

**Recovery codes are not CMP-034's.** The ticket's Security note names them beside API keys, but `14` never puts
CMP-034 on a recovery-code screen: the server generates the codes and shows them once, in full, through CMP-206
RecoveryCodeList (SCR-003, SCR-016, SCR-112: `14:191`, `14:432`, `14:2241`; drawn in `docs/design/E09/E09-D04.md`
§6), a display that S1 and S6 would forbid. Their display rules are CMP-206's own, routed to E05-X02 beside S1–S7
(§6 G19); S1–S7 cover the API keys and secrets a user enters on SCR-126 and SCR-127 only.

**Anatomy:**

| Part      | Tokens                                                                                                                                                              |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| box       | fill `color.surface.raised`, 1 px `color.border.default` hairline (decorative), `radius.control`, min-height `size.control.height`, padding-inline `space.inset.sm` |
| mask      | 8 × "•" in `type.num.base`, `color.text.secondary`                                                                                                                  |
| value     | `type.num.base`, `color.text.primary`, start-aligned (an identifier, conventions 27); wraps at any character, never truncated                                       |
| toggle    | CMP-002 ghost IconButton, `eye` / `eye-off` (registry names with #271), `space.inset.xs` after the box                                                              |
| copy      | CMP-033 CopyButton (Copyable=true), `space.inset.xs` after the toggle                                                                                               |
| countdown | a CMP-035 Countdown (`format: "words"`, `aria-live="off"`): "Hides in {s} s", `type.ui.caption`, `color.text.tertiary`, `space.stack.xs` under the box              |

**Keyboard** (WAI-ARIA APG Button pattern for the toggle and Copy; the box is not focusable):

| Keys                        | Action                                                                                                                                                         |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab             | The toggle, then Copy.                                                                                                                                         |
| Enter / Space on the toggle | Reveals (its name becomes "Hide {label}"; focus stays) or masks.                                                                                               |
| Enter / Space on Copy       | Copies; CMP-033's copied state for 2 s.                                                                                                                        |
| (no key) at `autoHideMs`    | Re-masks; focus stays on the toggle, whose name returns to "Show {label}"; announced once, 2 s before ("Secret will hide in 2 seconds"), silent at the moment. |

**Accessible name and role:**

| Element     | Role   | Name                                | ARIA                                                                                                       |
| ----------- | ------ | ----------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| container   | group  | `label` ("API secret")              | —                                                                                                          |
| mask        | text   | a visually hidden "{label}, hidden" | the mask characters `aria-hidden="true"`                                                                   |
| value       | text   | —                                   | read in browse mode; never in a live region                                                                |
| toggle      | button | "Show {label}" / "Hide {label}"     | `aria-controls` → the box; the swapped name carries the state, so no `aria-pressed` (the catalogue's form) |
| copy        | button | "Copy {label}"                      | CMP-033's                                                                                                  |
| live region | status | —                                   | CMP-035's one threshold announcement, "Secret will hide in 2 seconds"; never the value                     |

**Timing (WCAG 2.2.1):** the auto-hide is announced and loses nothing — one press re-reveals with focus kept — but a
2 s warning cannot meet 2.2.1's 20 s "extend" option; the "adjust" option is §6 G20.
**Hit target:** the toggle and Copy, 24 × 24 (32 × 32). **Motion:** none; the countdown's text changes once a second
and is never announced per tick. **Resize & overflow:** the value wraps at any character; the mask never wraps; the
buttons never grow. **Forced colors:** the box border and the text CanvasText; the buttons follow CMP-002.

**Catalogue alignment** (`15:359-366`): Props: `value` gains "a value the client holds in the current flow, never a
stored secret: C-2.7", plus `label: string` (names the group and the buttons) and `copyable?: boolean` (default
`false`, CMP-033), and `revealed?` "never `true` at mount"; a new States line (masked, revealed, expiring, copied); A11y
names the toggle "Show {label}"/"Hide {label}" in place of "Show secret"/"Hide secret" (their reading when `label` is
"secret") and appends S1–S7 in one sentence, routing recovery codes to CMP-206; Tokens: `font.mono` → `type.num.base`,
plus the box, mask and countdown tokens; Storybook adds Copyable. Held: the `autoHideMs` cap and the adjust setting
(G19, G20).

### CMP-040 · FormField

**Catalogue (verbatim, `15:422-423`):**

- **Props**: `label` · `htmlFor` · `required?` · `help?` · `error?` · `children`.
- **A11y**: `<label for>` association, `aria-describedby` chains help+error ids, `aria-required`.

| Axis   | Values                                                      | Default |
| ------ | ----------------------------------------------------------- | ------- |
| Layout | stacked, inline                                             | stacked |
| State  | default, invalid, disabled, disabled-with-reason, read-only | default |
| Help   | false, true                                                 | false   |
| Marker | none, optional                                              | none    |

_Boards PENDING: `CMP-040 · FormField`, export `img/CMP-040-formfield.png`._

**Variants × States (8 cells):** each with a CMP-007 instance as the child. **default** ("Username" over the field);
**invalid** (the error line: the `danger` glyph and "Enter your username.", `14:145`; the child's 2 px boundary);
**disabled** (label, field and lines at `opacity.disabled`); **disabled-with-reason** (T2: the label unchanged, the
child's T2 well with the `lock` leading its value, the reason line `rbac.permission` "Your role can't change
settings."); **read-only** (the child's read-only well); **Help=true** (a help line, CMP-100's "(rounded to nearest
tick)", `15:984`); **Marker=optional** ("Display name (optional)", `docs/design/E42/E42-D02.md`); **Layout=inline** (the
order ticket's label column, E30-D02 §2). **Not drawn:** hover, focus-visible and active belong to the child; loading (a
field has none; the form's busy state is its host's); empty (the child's placeholder).

**Anatomy** (lines in the order shown; each in the DOM at mount when its prop can be set):

| Part          | Tokens                                                                                                                                          | Spacing                                                                                                  |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| label         | `type.ui.label`, `color.text.secondary`, T2 included (its lock sits in the child's well, conventions 24); "(optional)" in `color.text.tertiary` | label to control `space.stack.xs`                                                                        |
| control       | the child                                                                                                                                       | —                                                                                                        |
| reason (T2)   | `type.ui.caption`, `color.text.secondary`                                                                                                       | control to first line `space.stack.xs`; between lines `space.stack.xs`                                   |
| error         | `danger` glyph `size.icon`, `color.status.danger.strong`; sentence `type.ui.caption`, `color.text.primary`                                      | glyph to text `space.inset.xs`                                                                           |
| help          | `type.ui.caption`, `color.text.secondary`                                                                                                       | —                                                                                                        |
| inline layout | the label column (the host's width), then the control                                                                                           | column gap `space.field.gap`; the label centred on the control's first line; the lines under the control |

**Keyboard:** none of its own (no APG pattern: a labelled-field wrapper). A click on the label focuses the control:
natively through `<label for>`, and through a click handler for an `aria-labelledby` child. The Tab order is the
child's.

**Accessible name and role:**

| Element      | Role                                                                        | Name                         | ARIA                                                                                                                                                  |
| ------------ | --------------------------------------------------------------------------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| label        | `<label for>` for a native labelable child; else text with `id` = `labelId` | —                            | an other-role child (radiogroup, slider, grid, a div combobox) takes `aria-labelledby` = `labelId` (§6 G10, slice 1 C5)                               |
| control      | its own                                                                     | the label, with "(optional)" | `aria-describedby`: the error id, then the help id (the reason id alone while T2); `aria-required="true"` when required; `aria-invalid` with an error |
| error node   | none                                                                        | —                            | `aria-live="polite"`, `aria-atomic="true"`, pre-rendered empty (conventions 23)                                                                       |
| help, reason | text                                                                        | —                            | referenced, not live                                                                                                                                  |
| lock glyph   | img                                                                         | "Not available"              | CMP-019 `decorative=false`, the child's, in its well (conventions 24)                                                                                 |
| error glyph  | none                                                                        | —                            | `aria-hidden="true"`                                                                                                                                  |

**T2 and not T2:** CMP-040 renders 2a for its child (conventions 24): the label unchanged, the lock in the child's well
leading its value, the reason under the control, and `aria-disabled`, `readonly` (text-like children) and
`aria-describedby` → the reason passed down; inside a one-notice section (CMP-065) the child points at the section's
notice and no reason line renders. A T2 field never validates, so it never shows an error. Not T2: an error, a busy
form, read-only, plain disabled (conventions 25).
**Required and optional:** `required` sets `aria-required="true"` and shows no asterisk; in a form that mixes both, the
optional fields carry "(optional)" (§6 G10).
**Hit target:** none of its own; the label adds to the control's pointer target. **Motion:** none: lines appear and go
at once, with no height animation. **Resize & overflow:** the label and the lines wrap; the inline layout stacks when
its column and the control's minimum width no longer fit (conventions 28). **Forced colors:** label and lines
CanvasText, a T2 field's label included, and the child's lock CanvasText (conventions 29); the error glyph
`currentColor`.

**Catalogue alignment** (`15:419-426`): Props: `labelId?`, `optional?` (G10), `disabledReason?` (T2), `layout?:
"stacked" | "inline"` (default `stacked`, G6), and `required?` gains "(sets `aria-required`; no asterisk)"; a Variants
line (stacked, inline) and a new States line (default, invalid, disabled, disabled-with-reason (T2), read-only); A11y
adds the `labelId` route, the chain order and the reason-alone rule, and the polite once error node; Tokens:
`space.field.*` → `space.stack.xs` and the shipped `space.field.gap` (the inline column gap), plus the label, help,
error and reason tokens; Storybook adds Optional, Inline, ReadOnly and DisabledWithReason.

### CMP-047 · DatePicker / DateRangePicker

**Catalogue (verbatim, `15:485-486`):**

- **Props**: `value` · `onChange` · `mode: "single"|"range"` · `min?/max?` · `timezone: "UTC"` (locked, 24/7 market — no user-timezone ambiguity per research digest).
- **A11y**: WAI-ARIA "Date Picker Dialog" pattern, full keyboard grid navigation (arrows move by day, `PageUp/Down` by month), live region announces selected range.

| Axis  | Values                                                                                  | Default |
| ----- | --------------------------------------------------------------------------------------- | ------- |
| Mode  | single, range                                                                           | single  |
| State | default, hover, focus-visible, open, invalid, disabled, disabled-with-reason, read-only | default |
| Time  | false, true                                                                             | false   |

_Boards PENDING: `CMP-047 · DatePicker`, export `img/CMP-047-datepicker.png`._

**Variants × States (11 cells):** at Mode=single, Time=false: the field's default, hover, focus-visible, invalid
("Nothing is recorded for that window.", `14:2096`), disabled, disabled-with-reason (SCR-098's range for a viewer:
`rbac.permission` "Your role can't control replay.") and read-only looks (CMP-007's), and **open** (October 2026:
today, the selected day, the focused day, days before `min` and the caption); **Mode=range** (Start and End fields);
**Mode=range, open** (the start picked, the end pending, the in-range band under the pointer's day); **Time=true**
("14:05" beside the date). **Not drawn:** active (a press focuses or opens), loading (dates are computed, not
fetched; recorded coverage is the host's caption), empty (the field's placeholder, "YYYY-MM-DD").

**Anatomy:**

| Part                     | Tokens                                                                                                                                                                                           |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| date field               | the CMP-007 well; the value "2026-10-23" in `type.num.base`, start-aligned; a "UTC" suffix; the calendar button flush in the well's end (conventions 21)                                         |
| time field (Time=true)   | a second well, "14:05" and "UTC", `space.inset.xs` after the date; typed only                                                                                                                    |
| range                    | Start and End fields (CMP-040 labels) `space.inset.sm` apart; one calendar button, on the End field                                                                                              |
| format hint              | CMP-040's help line, `formatHint` (default "YYYY-MM-DD")                                                                                                                                         |
| dialog                   | conventions 26's surface, padding `space.inset.md`; a header with the month (`type.ui.heading-sm`, `color.text.primary`) between two CMP-002 ghost IconButtons (`chevron-left`, `chevron-right`) |
| weekday row              | `type.ui.caption`, `color.text.tertiary`, Monday first (ISO 8601); each an `abbr` with the full name                                                                                             |
| day cell                 | `size.control.height` square, `radius.control`; the number in `type.num.base`, `color.text.primary`, centred; days of other months are blank                                                     |
| today                    | a 1 px `color.text.tertiary` ring inside the cell                                                                                                                                                |
| selected day, range ends | the selected role: `color.action.selected`, a 2 px inner `color.border.selected` outline (`border.thick`), `color.text.primary` (§6 G3)                                                          |
| in range                 | `color.surface.selected` behind the days between the ends (decorative: the ends, the fields and the announcement carry the range)                                                                |
| out of range             | the number at `opacity.disabled` (inactive; availability)                                                                                                                                        |
| caption                  | `type.ui.caption`, `color.text.secondary`, under the grid: the host's sentence naming the range (E11-D03: "Recorded history: 2026-09-01 – today")                                                |

**Keyboard** (WAI-ARIA APG Date Picker Dialog pattern; the dialog is modal):

| Keys                                          | Action                                                                                                                                        |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab (fields)                      | The date field, the time field, then the calendar button.                                                                                     |
| Typing                                        | "YYYY-MM-DD" and "HH:MM", parsed on blur (conventions 23).                                                                                    |
| Alt+↓ in a field; Enter / Space on the button | Opens the dialog; focus moves to the selected day, else today, else the first allowed day.                                                    |
| ← / →                                         | Previous / next day.                                                                                                                          |
| ↑ / ↓                                         | The same weekday, previous / next week.                                                                                                       |
| Home / End                                    | First / last day of the week.                                                                                                                 |
| Page Up / Page Down                           | Previous / next month (the same day number, clamped to the month's last).                                                                     |
| Shift+Page Up / Shift+Page Down               | Previous / next year.                                                                                                                         |
| Enter / Space on a day                        | Single: picks it and closes. Range: the first pick sets the start, the second the end and closes; a second pick before the start replaces it. |
| Enter / Space on an out-of-range day          | Nothing changes; the caption is announced once.                                                                                               |
| Tab / Shift+Tab (dialog)                      | Cycles the two month buttons and the grid; focus stays in the dialog.                                                                         |
| Esc                                           | Closes without a change. Every close returns focus to the calendar button.                                                                    |
| Any key while T2                              | The fields are T2 (`readonly`) and the button `aria-disabled`: the dialog never opens; the reason is re-shown once per focus visit.           |

**Accessible name and role:**

| Element         | Role                        | Name                                  | ARIA                                                                                                                                  |
| --------------- | --------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| date field      | textbox                     | CMP-040's label ("Start")             | `aria-describedby` → the error, then the format hint and the "UTC" suffix; invalid, read-only, T2 and plain as CMP-007                |
| calendar button | button                      | "Choose date" (range: "Choose dates") | `aria-haspopup="dialog"`; T2: `aria-disabled="true"` + `aria-describedby` → the field's reason                                        |
| dialog          | dialog, `aria-modal="true"` | the month heading ("October 2026")    | —                                                                                                                                     |
| grid            | grid                        | the month heading                     | —                                                                                                                                     |
| day             | gridcell holding a button   | "23 October 2026", with ", today"     | `aria-selected="true"` on the selected day and every day of a range; `aria-disabled="true"` out of range; `aria-current="date"` today |
| month buttons   | button                      | "Previous month" / "Next month"       | —                                                                                                                                     |
| live region     | status                      | —                                     | the range, twice at most: "Start 2026-10-01. Choose the end date." then "2026-10-01 to 2026-10-07, 7 days." (proposed strings)        |

**T2 and not T2:** T2, conventions 24 (the fields and the button share one reason). Not T2: days outside `min`–`max`
(availability, with the caption), an empty or reversed range (validity), read-only.
**Validation:** conventions 23; `14:2096`'s "range end after start" and "Nothing is recorded for that window." are
the host's checks and copy. **Hit target:** the fields; the calendar and month buttons 24 × 24 (32 × 32); each day
cell `size.control.height` square. **Motion:** the dialog fades as conventions 26's popups; a month change is instant.
**Resize & overflow:** the dialog keeps 7 columns and scrolls inside the viewport at 200 % zoom (conventions 28); a
range stacks End under Start when its host is narrower than both fields. **Forced colors:** conventions 29; today's
ring a CanvasText border; selected days Highlight with HighlightText; in-range days a 1 px Highlight border
(`forced-color-adjust: none` on the cell, system colours only); out-of-range numbers GrayText; in T2 the calendar
button follows CMP-002 (a GrayText border, a ButtonText glyph).

**Catalogue alignment** (`15:482-489`): Props gains `withTime?`, `formatHint?` and `rangeCaption?` (G11), `invalid?`,
`disabled?`, `readOnly?` and `disabledReason?`; a Variants line (single, range, with or without time) and a new States
line (its days include the out-of-range look); A11y appends the modal dialog, the focus placement (the selected day,
else today, else the first allowed day) and its return, `Home`/`End` by week, `Shift+PageUp/Down` by year, and "weeks
start on Monday; every value is UTC" (the week start is G11's), while the two range announcements stay in the table
above; Tokens: `color.action.selected` with `color.border.selected` and `color.text.primary` (G3),
`color.surface.selected`, `color.text.tertiary`, `elevation.popover`, `radius.card`, `size.control.height`,
`type.num.base`, `type.ui.heading-sm`, `type.ui.caption`, `border.thick`, plus the field tokens; Storybook adds
WithTime, Invalid and DisabledWithReason. Held: `inputTimezone`, `secondaryDisplay` (G11).

### CMP-048 · Combobox / AutoComplete

**Catalogue (verbatim, `15:494-495`):**

- **Props**: `value` · `onChange` · `options[]|asyncSearch(query)` · `loading?` · `placeholder?`.
- **A11y**: WAI-ARIA Combobox pattern, `aria-activedescendant`, `aria-expanded`, results count announced via polite live region on each query update (debounced to avoid flooding).

| Axis  | Values                                                                                                           | Default |
| ----- | ---------------------------------------------------------------------------------------------------------------- | ------- |
| State | default, hover, focus-visible, open, loading, no-results, search-failed, invalid, disabled, disabled-with-reason | default |

_Boards PENDING: `CMP-048 · Combobox`, export `img/CMP-048-combobox.png`._

**Variants × States (10 cells):** default, hover, focus-visible, invalid and disabled (CMP-007's looks with "BTC"
typed); **open** (three results, the second active, its matched "BTC" in `type.ui.body-strong`); **loading** (a status
row: CMP-014 sm and "Searching…"); **no-results** (`14:979`'s "No USDT perpetual matches 'xyz'."); **search-failed**
(the `danger` glyph and the host's sentence, SCR-102's "catalogue load failed", `14:2175`); and
**disabled-with-reason** (a rule's metric picker while viewing as another user: `rbac.view_as` "Read-only while
viewing as alex."). **Not drawn:** active (typing is the interaction), read-only (a value nobody may change is plain
text), empty (the no-results cell).

**Anatomy:** the input is the CMP-007 well (an optional leading glyph through `prefix`); the listbox and its options
are conventions 26, with the matched part of each label in `type.ui.body-strong` (weight, not colour); the status rows
are `type.ui.body`, `color.text.secondary` — loading pairs CMP-014 sm with its words (CMP-038), a failed search leads
with the `danger` glyph in `color.status.danger.strong`.

**Keyboard** (WAI-ARIA APG Combobox pattern, editable, list autocomplete):

| Keys              | Action                                                                                                                                   |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab   | Moves focus to or from the input; leaving never chooses the active option.                                                               |
| Typing            | Edits the query; after the debounce the listbox opens with results or a status row.                                                      |
| ↓ / ↑             | Opens if closed; next / previous option (from the input, ↓ reaches the first); ↑ on the first returns to the text.                       |
| Alt+↓ / Alt+↑     | Opens without moving / closes.                                                                                                           |
| Enter             | Chooses the active option (the input shows its label; the listbox closes); with none active, the host's Enter (SCR-121 applies a query). |
| Esc               | Closes the listbox and keeps the text; a second Esc bubbles.                                                                             |
| ← / →, Home / End | Move the caret in the input.                                                                                                             |
| Any key while T2  | Changes nothing; the first refused key of a focus visit re-shows the reason with one polite announcement.                                |

**Accessible name and role:**

| Element     | Role                                 | Name                       | ARIA                                                                                                                                                                      |
| ----------- | ------------------------------------ | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| input       | combobox                             | CMP-040's label ("Metric") | `aria-autocomplete="list"`, `aria-expanded`, `aria-controls`, `aria-activedescendant`; invalid and T2 as CMP-007                                                          |
| listbox     | listbox                              | the same label             | `aria-busy="true"` while searching                                                                                                                                        |
| option      | option                               | its label and second line  | `aria-selected="true"` on the active option (APG list autocomplete)                                                                                                       |
| status row  | none (presentational, not an option) | —                          | its words reach the live region                                                                                                                                           |
| live region | status                               | —                          | the count ("8 results") or the no-results sentence once per settled query, 500 ms after the last keystroke; a failure once; "Searching…" is shown, not announced (§6 G17) |

**T2 and not T2:** T2, conventions 24, through CMP-040. Not T2: loading (busy), no results (availability), a failed
search (the source failed, not the input), an unlisted value (validity).
**Validation:** a host that needs a listed value validates on blur: free text that matches no option is invalid, with
the host's sentence. **Hit target:** the input; each option row. **Motion:** the listbox as conventions 26; the
spinner CMP-014's pair. **Resize & overflow:** options wrap to two lines, then truncate, with the full text in the
name. **Forced colors:** conventions 29; the matched part keeps its weight.

**Catalogue alignment** (`15:491-498`): Props gains `noResultsText: string` (the host's sentence; required with
`asyncSearch`), `invalid?`, `disabled?` and `disabledReason?`; a new States line (loading is busy with `aria-busy` on
the listbox, no results availability); A11y appends the 500 ms debounce once per settled query, the status rows that
are not options and `Esc` (G17); Tokens: `elevation.2` → `elevation.popover`, plus `radius.card`,
`type.ui.body-strong` and the field tokens; Storybook adds SearchFailed and DisabledWithReason.

### CMP-049 · Table

**Catalogue (verbatim, `15:503-504`):**

- **Props**: `columns: ColumnDef[]` · `rows: T[]` · `sort?/onSortChange` · `rowKey` · `onRowSelect?` · `virtualized?: boolean` (default true above 50 rows) · `emptyState?: ReactNode`.
- **A11y**: semantic `<table>` with `scope` on headers even when virtualized (windowed rendering keeps ARIA table role structure via `role="rowgroup"/"row"/"cell"` with `aria-rowindex`/`aria-colindex` when native table elements aren't feasible in the virtualization window); sortable headers are buttons with `aria-sort`.

| Axis      | Values                                                            | Default   |
| --------- | ----------------------------------------------------------------- | --------- |
| Mode      | table, grid                                                       | table     |
| State     | populated, loading, empty, filtered-empty, error, sorting, reflow | populated |
| Selection | none, multiple                                                    | none      |

**Mode rule:** `grid` is implied whenever a body column is interactive — `onRowSelect`'s select column, an actions
column, an inline control; the `grid` prop only forces it for a static table. Table mode's interactive content is the
sortable header buttons and the focusable scroll region, and its body rows carry no controls: a roving tabindex keeps a
long table to one Tab stop (`05` §3.4 item 2, "200+ Tab presses"; E42-D03 §13 puts SCR-121's table, which has row
actions, in grid mode).

_Boards PENDING: `CMP-049 · Table`, export `img/CMP-049-table.png`._

**Variants × States (10 cells; the ticket's Gherkin "loading, empty and error are explicitly drawn"):**

| Cell                    | Axes                       | What it shows                                                                                                                                                                                      |
| ----------------------- | -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| populated               | Mode=table, Selection=none | the sticky header with one sorted column (`arrow-down`, `aria-sort="descending"`) and one sortable unsorted; a numeric column end-aligned in mono; zebra rows; one hovered row; no in-row controls |
| loading                 | as populated               | the header row kept; CMP-015 skeleton rows filling the body; the caption's loading words (E11-D04 §10: "Loading 5,000 bars…")                                                                      |
| empty                   | as populated               | the header row kept; CMP-026 `no-data` across every column (E42-D03 `users.empty`: "You're the only user. Invite a manager or viewer to delegate.")                                                |
| filtered-empty          | as populated               | CMP-026 `filtered-empty` with Clear filters (E11-D04 §10: "No rows match: Bid-stacked, Delta negative")                                                                                            |
| error                   | as populated               | the header row kept; CMP-027 with Retry (E42-D03 U-6: "Couldn't load users — store unavailable."), announced politely (§6 G17)                                                                     |
| sorting                 | as populated               | the `sortPending` header: its label and `aria-sort` kept, CMP-014 sm in place of its glyph, `aria-busy` (E42-D03 §7)                                                                               |
| reflow                  | as populated               | the stacked layout at 200 % zoom (conventions 28): one block per row                                                                                                                               |
| Mode=grid               | State=populated            | the actions column (an interactive body column, so a grid); the CMP-039 ring on a focused cell, the header row in the arrows' path                                                                 |
| Selection=multiple      | State=populated, Mode=grid | two rows on `color.action.selected` with checked boxes; the select-all box mixed (the select column makes it a grid)                                                                               |
| row menu with a T2 item | Mode=grid                  | the row menu open; "Edit risk caps" T2 with `rbac.owner_only` "Only the owner can change account settings." as its second line (D09 §2.4, SCR-063)                                                 |

**Not drawn:** invalid (a table holds no input of its own), disabled and disabled-with-reason for the whole table (it
is read data, and reads in a visible surface are never gated; row actions are T2 one by one), read-only (rows are
read-only by nature), active (opening a row is the host's action).

**Anatomy** (compact / comfortable: only the row height changes):

| Part           | Tokens                                                                                                                                                                                                                |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| shell          | the host's surface; a scroll region; `caption` in `type.ui.label`, `color.text.secondary` (visually hidden when a heading already names the table)                                                                    |
| header row     | sticky; fill `color.surface.hover`; a 1 px `color.border.subtle` rule under it (decorative); min-height `size.row.height` 24 / 32; labels `type.ui.label`, `color.text.primary`; numeric headers end-aligned          |
| sort glyph     | `size.icon`, `color.text.tertiary`, after the label at `space.inset.xs`: `arrow-up` ascending, `arrow-down` descending, a neutral sort glyph when sortable and unsorted (registry names with #271)                    |
| body row       | min-height `size.row.height`; odd `color.surface.canvas`, even `color.surface.raised` (E11-D04 §2); hover `color.surface.hover`; selected `color.action.selected` (§6 G3)                                             |
| cell           | padding-inline `space.inset.sm`; text `type.ui.body`, `color.text.primary`; secondary text `color.text.secondary`, never `color.text.tertiary` (4.79–4.83:1 in dark; see below); numbers `type.num.base`, end-aligned |
| select column  | grid mode only (the mode rule): a CMP-005 per row and a select-all CMP-005 in the header, the cell `size.control.height` wide                                                                                         |
| actions column | grid mode only (the mode rule): trailing, a CMP-002 ghost `more-horizontal` IconButton opening the CMP-041 row menu (§6 G21)                                                                                          |
| reflow         | one block per row: the first cell as its heading line (with the row's actions in grid mode), the other cells as header–value pairs in a 2-column grid; still one row element per record (E11-D04 §5.2)                |

Two measured choices behind the anatomy (audit §4): `color.text.tertiary` measures 4.79:1 on a hovered row and 4.83:1
on a selected row in dark, too thin a margin for body text, so cells never use it; and the header's
`color.border.subtle` rule equals its `color.surface.hover` fill in every theme (1.00:1), so it reads only against the
first body row (1.24:1 in dark) and carries nothing; it stays as the real border that forced colours paint CanvasText.

**Keyboard** — table mode (WAI-ARIA APG Table pattern: static cells, no control in a body row):

| Keys                                             | Action                                                                                                                                            |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab                                  | The scroll region when it scrolls (`tabindex="0"`, named by the caption), then the sortable header buttons in order; body rows hold no Tab stops. |
| Arrows, Page Up / Down, Home / End on the region | Scroll it (native).                                                                                                                               |
| Enter / Space on a header button                 | Sorts ascending, then descending; while that column is `sortPending` the press changes nothing.                                                   |

**Keyboard** — grid mode (`grid`, or implied by an interactive body column; WAI-ARIA APG Grid pattern):

| Keys                    | Action                                                                                                   |
| ----------------------- | -------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab         | One stop: into the grid on the last focused cell, else the first data cell; the next Tab leaves.         |
| ↑ / ↓                   | Previous / next row, the header row included.                                                            |
| ← / →                   | Previous / next cell.                                                                                    |
| Home / End              | First / last cell of the row.                                                                            |
| Ctrl+Home / Ctrl+End    | First / last row.                                                                                        |
| Page Up / Page Down     | One visible page of rows.                                                                                |
| Enter                   | Sorts on a header; opens the row menu on the actions cell, the row (the host's action) elsewhere.        |
| Space                   | Toggles the focused row's selection (Selection=multiple).                                                |
| Shift+F10, the Menu key | Opens the row menu; T2 items stay arrow-reachable, and Enter on one re-shows its reason once (D09 §9.3). |
| Esc                     | Closes the row menu; focus returns to the cell it was opened from.                                       |

In grid mode a focused cell scrolls below the sticky header (`scroll-margin-top`), so focus is never hidden (WCAG
2.4.11); table mode puts no Tab stop in the body.

**Accessible name and role:**

| Element      | Role                                        | Name                                            | ARIA                                                                             |
| ------------ | ------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------------------- |
| table        | table (native `<table>`); grid in grid mode | the caption                                     | `aria-rowcount` (every row; -1 while unknown); `aria-busy="true"` while loading  |
| header cell  | columnheader (`th scope="col"`)             | its label                                       | `aria-sort` on the sorted column, `none` on the other sortable ones              |
| sort button  | button                                      | the header label                                | `aria-busy="true"` while `sortPending`                                           |
| row          | row                                         | —                                               | `aria-rowindex` (absolute); `aria-selected` in grid mode with selection          |
| select boxes | checkbox                                    | "Select all rows"; "Select {first cell}"        | the select-all `aria-checked="mixed"` when some rows are selected                |
| actions      | button                                      | "Actions for {first cell}" ("Actions for alex") | `aria-haspopup="menu"`; a gated inline IconButton takes 2b (conventions 24)      |
| live region  | status, one per table                       | —                                               | sort, filter, selection ("2 selected") and load results, once each (E11-D04 D16) |

**T2 and not T2:** row actions are T2 one by one — a row-menu item 2a with its second line, an inline IconButton 2b
with the CMP-016 echo (conventions 24). Not T2: sorting and loading (busy), empty and filtered-empty (availability), an
error (the source failed).
**Hit target:** rows `size.row.height` (24 / 32); header buttons fill their cells; select boxes take their 24 px cell;
action buttons 24 × 24. **Motion:** none; skeletons follow CMP-015's pair (static under reduce, E11-D04 §10), the
sort spinner CMP-014's. **Resize & overflow:** rows grow taller with text; numbers never wrap or truncate; text cells
truncate with a CSS ellipsis (the full text stays in the DOM and is read whole); below the fit width, and at 200 %
zoom, the table reflows to the stacked layout (`16` §3 rule 4). **Forced colors:** the header keeps a 1 px CanvasText
bottom border and each row a 1 px CanvasText separator (the fills are lost); selected rows set a Highlight fill with
HighlightText; the sort glyph `currentColor`; the focus ring Highlight.

**Catalogue alignment** (`15:500-507`): Props applies E42-D03 Appendix A's row verbatim (`grid?`, `sortPending?`) and
adds `caption: string`, `loading?: boolean` and `error?: {message, onRetry}` (G12); `onRowSelect?` renders the select
column and makes the table a grid (G21); a Variants line (table, grid, with the mode rule) and a new States line (the
seven states, the selected row on `color.action.selected`); A11y applies E42-D03's row verbatim, then adds the sticky
header and `scroll-margin-top`, table mode's two kinds of Tab stop (the focusable scroll region and the header buttons)
with no control in a body row, the grid that an interactive body column implies, the select boxes, the `Shift+F10` row
menu with T2 items, the one live region and the stacked reflow; Tokens: `color.surface.raised`, `color.border.subtle`
and `font.mono` become the anatomy's tokens (G3); Storybook applies E42-D03's row verbatim and adds Loading, Error,
FilteredEmpty and Reflow. Held: the treegrid rows and `stickyFirstColumn` that E11-D04 and E29-D02 both ask for, until
E29-D04 specifies them, and E11-D04's `fitChars` (G12).

### CMP-054 · SearchBox

**Catalogue (verbatim, `15:548-549`):**

- **Props**: `value` · `onChange` · `placeholder?` · `onClear`.
- **A11y**: clear button labelled "Clear search"; `role="searchbox"`.

| Axis  | Values                                  | Default |
| ----- | --------------------------------------- | ------- |
| State | default, hover, focus-visible, disabled | default |
| Value | empty, filled                           | empty   |

_Boards PENDING: `CMP-054 · SearchBox`, export `img/CMP-054-searchbox.png`._

**Variants × States (5 cells):** default, hover, focus-visible and disabled at Value=empty (the leading `search`
glyph and the host's placeholder); **Value=filled** ("alex", with the clear button). **Not drawn:** active, invalid
(every query is valid; no matches is the host's availability state), disabled-with-reason (searching is a read, and a
visible surface's search is never gated: D09 §2.1), read-only, loading and empty (the host's results own them).

**Anatomy:** the CMP-007 well; a leading `search` glyph (`size.icon`, `color.text.tertiary`, decorative); the value;
a trailing CMP-002 ghost IconButton (`close`, "Clear search"), shown only with a value, flush in the well
(conventions 21).

**Keyboard** (no APG widget pattern: a native search field; its results are the host's region):

| Keys                   | Action                                                                                             |
| ---------------------- | -------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab        | The field, then the clear button when it shows.                                                    |
| Typing                 | Changes the query; the host filters after its debounce or waits for Enter.                         |
| Enter                  | Applies the query when the host searches on Enter (SCR-121, E42-D03 §7).                           |
| Esc                    | Clears a non-empty query and keeps focus; on an empty query it bubbles (a dialog closes) (§6 G13). |
| Enter / Space on Clear | Clears; focus returns to the field.                                                                |

**Accessible name and role:**

| Element      | Role                                       | Name                                                  | ARIA                                                                                       |
| ------------ | ------------------------------------------ | ----------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| field        | searchbox (native `<input type="search">`) | `label` through `aria-label` ("Search users"; §6 G13) | the placeholder is never the name; `disabled` when plain disabled                          |
| search glyph | none                                       | —                                                     | `aria-hidden="true"`                                                                       |
| clear button | button                                     | "Clear search"                                        | rendered only with a value; the host announces its count, politely, once per settled query |

**Hit target:** the well; the clear button 24 × 24 (32 × 32). **Motion:** none. **Resize & overflow:** as CMP-007.
**Forced colors:** conventions 29; the glyphs `currentColor`.

**Catalogue alignment** (`15:545-552`): Props gains `label: string` (mandatory, the `aria-label`) and `disabled?`; a new
States line (default, hover, focus-visible, filled, disabled); A11y appends `Esc`, the focus return after Clear and the
host's polite count, once per settled query (G17); Tokens: "inherits CMP-007" plus the `search` glyph's `size.icon` and
`color.text.tertiary`; Storybook adds Disabled.

### CMP-065 · FormSection

**Catalogue (verbatim, `15:647-648`):**

- **Props**: `title` · `description?` · `collapsible?` · `children`.
- **A11y**: `fieldset`/`legend` semantics.

| Axis        | Values                                                            | Default |
| ----------- | ----------------------------------------------------------------- | ------- |
| Collapsible | false, true                                                       | false   |
| State       | default, collapsed, errors-within, disabled, disabled-with-reason | default |

_Boards PENDING: `CMP-065 · FormSection`, export `img/CMP-065-formsection.png`._

**Variants × States (6 cells):** **default** ("Default SL/TP offsets", one of SCR-114's fieldsets, `14:2271`, with a
description and two CMP-040 fields); **Collapsible=true** (expanded); **collapsed**; **errors-within** (collapsed, the
heading line adding the `danger` glyph and "2 problems", proposed copy); **disabled** (plain, for everyone in the
state); **disabled-with-reason** (T2, one notice: `rbac.permission` "Your role can't change settings." under the
heading, each field's well led by the lock). **Not drawn:** hover, focus-visible and active belong to the disclosure
button (the CMP-039 ring on focus) and the fields; loading, error and empty are the host's.

**Anatomy:** a `fieldset` with no border or padding of its own (the panel pads); a `legend` that holds the heading
(`type.ui.heading-sm`, `color.text.primary`) — and, when collapsible, the disclosure button around the heading's text
with a `chevron-right` / `chevron-down` (`size.icon`, `color.text.secondary`); the description (`type.ui.caption`,
`color.text.secondary`, `space.stack.xs` under the heading); fields `space.stack.md` apart; sections `space.stack.lg`
apart; the errors-within line (`danger` glyph in `color.status.danger.strong`, `type.ui.caption`,
`color.text.primary`); the T2 notice (`type.ui.caption`, `color.text.secondary`, under the description).

**Keyboard:** none for a plain section (a group). Collapsible: the WAI-ARIA APG Disclosure pattern — Tab reaches the
heading's button; Enter or Space toggles it and focus stays; a collapsed section's fields leave the Tab order.

**Accessible name and role:**

| Element           | Role                           | Name                      | ARIA                                                                                          |
| ----------------- | ------------------------------ | ------------------------- | --------------------------------------------------------------------------------------------- |
| section           | group (`<fieldset>`)           | the legend's heading text | `aria-describedby` → the description                                                          |
| heading           | heading, `h{headingLevel}` (3) | `title`                   | — (§6 G14)                                                                                    |
| disclosure button | button                         | `title`                   | `aria-expanded`, `aria-controls` → the body; `aria-describedby` → the errors-within line      |
| T2 notice         | text                           | —                         | the `aria-describedby` target of every gated field in the section (one notice, many pointers) |

**T2 and not T2:** one notice, many pointers (conventions 24). Not T2: collapsed (a view state), errors within
(validity), plain disabled (`<fieldset disabled>`, for everyone in the state).
**Validation:** on submit, a collapsed section that holds an invalid field opens, so focus can reach the field (G14).
**Hit target:** the disclosure button spans the heading line, at least 24 px tall. **Motion:** expand and collapse
are instant in both modes. **Resize & overflow:** the heading, description and notice wrap. **Forced colors:** the
heading and the T2 notice CanvasText; the chevron and the glyphs `currentColor`; the gated fields' labels and locks
CanvasText (conventions 29).

**Catalogue alignment** (`15:644-651`): Props gains `headingLevel?: 2 | 3 | 4` (default 3), `disabled?` and
`disabledReason?` (the one notice); a new States line; A11y appends the heading inside the legend, the disclosure
button, the errors opening on submit and the one notice; Tokens: `space.formsection.*` → `space.stack.xs`,
`space.stack.md`, `space.stack.lg`, plus `type.ui.heading-sm`, `type.ui.caption`, `color.text.primary`,
`color.text.secondary`; Storybook adds WithErrors and DisabledWithReason.

### CMP-079 · RbacGate

**Catalogue (verbatim, `15:786-787`):**

- **Props**: `allowed: boolean` · `reason: string` (required when `allowed` is false; a key of the vocabulary in `docs/design/E09/E09-D09.md` §3) · `children` (any interactive component).
- **A11y**: propagates `disabledReason` to the wrapped atom's native prop (CMP-001/002/004 etc. all accept it) rather than overlaying a separate non-semantic layer.

| Axis    | Values                  | Default |
| ------- | ----------------------- | ------- |
| Allowed | true, false             | true    |
| Form    | inline, tooltip, notice | inline  |

_Boards PENDING: `CMP-079 · RbacGate`, export `img/CMP-079-rbacgate.png`._

**Variants × States (4 cells):** **Allowed=true** (a CMP-040 field, unchanged: T1); **inline** (the same field in T2 2a:
the T2 well with the lock leading the value, the label unchanged, the reason `rbac.view_as` "Read-only while viewing as
alex."); **tooltip** (a CMP-049 row-action IconButton with the lock badge and a CMP-016 echo of `rbac.owner_only` "Only
the owner can change account settings." on hover and focus); **notice** (a CMP-065 section with one notice and two
fields pointing at it). The sentence form is CMP-026 with `cta` omitted (D09 §8), not this component. **Not drawn:**
every other state belongs to the wrapped control.

**Anatomy:** none of its own (a behavioural wrapper): the T2 look is the wrapped control's (conventions 24).
**Keyboard:** none of its own; the wrapped control's T2 keys (conventions 24).
**Accessible name and role:**

| Element             | Role            | Name               | ARIA                                                                                                                                                        |
| ------------------- | --------------- | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| wrapper             | none of its own | —                  | never overlays a non-semantic layer (`15:787`)                                                                                                              |
| wrapped control     | its own         | its own full label | `aria-disabled="true"` (never `disabled`); `aria-describedby` → the reason node (inline, tooltip) or `noticeId` (notice); a text-like field also `readonly` |
| reason node         | text            | —                  | rendered at mount; visually hidden and echoed by CMP-016 in the tooltip form                                                                                |
| lock glyph or badge | img             | "Not available"    | CMP-019 `decorative=false`                                                                                                                                  |

**Not wrapped** (not T2): validity, busy, availability, a step-4 state reason (the control's own `disabledReason`),
T3 admin navigation (never rendered) and T4 refusals (the host's).

**Catalogue alignment** (`15:783-790`): Props gains `form?: "inline" | "tooltip" | "notice"` (default `inline`;
`tooltip` only for icon-only controls and toolbar segments) and `noticeId?` (required with `notice`) (G15), with a
Variants line for the three forms; A11y appends the T2 rule in one sentence — the wrapped control keeps its role and
full label, takes `aria-disabled` and `aria-describedby` → the reason rendered at mount (a text-like field also
`readonly`), the CMP-019 `lock` glyph ("Not available") leads the label in 2a (on a field, the value inside the well:
E30-D04 §2.5 (2), conventions 24) or badges the icon in 2b, and a key re-shows the reason with one polite announcement
(E09-D09 §2.2, §9) — which replaces slice 1 D13's promised "decorative `locked` glyph, trailing" line; Tokens: "n/a
(behavioural wrapper; the wrapped control's T2 look binds `color.text.tertiary`, `color.text.secondary`,
`color.surface.raised` and `color.border.default`)"; Storybook adds FormInline, FormTooltip and FormNotice.

## 8. Design QA checklist (brief §12)

Completed for the 11 components of this slice. Open items say why and who closes them.

**Tokens & visual**

- [ ] Uses only published Tier-2/Tier-3 tokens — zero hardcoded hex/px values. **Open:** every colour, spacing, size,
      radius, type and opacity value named here is a published semantic token or a named primitive (§4, §5.2), and
      no component holds a hex value; the raw values left are §5.1's constants, recorded rather than hidden. Ticked
      when the owner accepts them (slice 1 B1, §6 G5) or tokens replace them, and the boards PR has drawn them.
- [ ] Verified in all three themes at both density modes. **Open:** structurally guaranteed (every paint is a
      semantic token that all three themes resolve; density re-points only the two heights), and the figures cover
      all three themes (audit §4), but the boards are PENDING.
- [ ] Passes the automated contrast-matrix check for every colour pair it introduces or touches. **Open:** every pair
      passes on the surfaces it is specified for (audit §4); two fall below 3:1 off them and are handled by a rule:
      the invalid boundary on `surface.hover` and `surface.selected` in dark (§6 G2: fields are not placed there) and a
      checked box on `surface.selected` (§6 G3: selected rows take `color.action.selected`).
- [ ] CVD simulation reviewed for any new colour-carrying state. **Open:** the audit §5 records ΔE76 spot checks made
      with `docs/research/_tools/cvd_simulate.py`; the formal review is E05-D04's. Structurally no slice-3 state
      depends on hue alone.

**Behaviour & states**

- [ ] Every documented State has a corresponding Penpot variant (and Storybook story). **Open:** the 85 cells are
      specified (§1, §7); the boards PR draws them, and the stories are E05-S01..S04's (slice 1 C15).
- [ ] Disabled states use the disabled-with-reason pattern (CMP-079), never a bare disabled control. **Specified:**
      every gateable control is T2 from the start (conventions 24), plain disabled is kept for unavailability only, and
      validity, busy and availability are not T2 (conventions 25). **Open** until the boards PR draws it.
- [ ] Loading/empty/error states are explicitly designed. **Specified:** CMP-049's loading, empty, filtered-empty and
      error states with the header row kept (the ticket's Gherkin), and CMP-048's loading, no-results and
      failed-search rows. **Open** until the boards PR draws them.

**Accessibility**

- [ ] Keyboard-interaction table completed and matches an implemented, tested keyboard path. **Tables complete** for
      all 11 (the APG pattern named, or "none of its own" with the reason). **Open** for "implemented, tested", which
      is E05-S01..S04's Definition of Done.
- [x] Accessible-name/role table completed: all 11 (§7; summary in the audit §2).
- [x] Canvas/WebGL-adjacent strategy specified: not applicable — no slice-3 component draws on a canvas; CMP-049 is
      the base of the DOM table alternative (`docs/design/E11/E11-D04.md`).
- [x] Motion-safe/motion-reduce pair specified for any animated property: popups fade over `motion.duration.fast`
      and appear at once under reduce; CMP-014's and CMP-015's pairs cover the spinners and skeletons; every other
      change is instant in both modes.
- [x] Hit targets meet the minimum or log an essential exception: every control is at least 24 × 24 px compact and
      32 px comfortable, in-well buttons included (conventions 21); no essential exception. 32 px is E05-D07's
      comfortable value, which supersedes this item's older "40-44px" (slice 1 C13).
- [ ] Accessibility role has signed off (§13). **Open:** this PR carries the pre-review
      (`E05-D02-form-controls-a11y-audit.md`); the formal sign-off is E05-D04's.

**Trading-specific safety**

- [x] Any component touching order placement, position modification or rule arming states its confirm-gate variant:
      not applicable; no slice-3 component places, changes or arms anything, and CMP-008's keys and blur rules keep a
      typed trading value from changing silently (§6 G8, G18).
- [x] Any heuristic/estimated value is chip-tagged: not applicable; no slice-3 component shows an estimated value.
- [x] Demo/Live context is unambiguous wherever a trading action can fire: not applicable at component level.

**Consistency**

- [x] Reuses an existing CMP-* rather than a near-duplicate: no new ID; CMP-009's searchable mode is CMP-048 (§6 G9),
      and CMP-054 and every field share CMP-007's well.
- [ ] Storybook stories match the full Variants × States matrix. **Not applicable to this design PR** (slice 1 C15).
- [ ] Composes only published-library components. **Open:** the boards PR nests the published CMP-002, 005, 014, 016,
      019 and 033, and CMP-015, 026, 027, 035 and 041 once their slices ship (§1).

## 9. Approval

The owner approves by merging this spec PR and/or commenting `approved` on #161 (C-10.1; the coordinator reviews
under the owner's delegation): owner approval pending. This text merges first with the boards PENDING; the boards PR
builds slice 3's sections on page `10 Components — Atoms`. Engineering stories E05-S01..S04 move to Ready only after
every slice is approved. The accessibility pre-review is `E05-D02-form-controls-a11y-audit.md`; the formal
accessibility and CVD sign-off is E05-D04's. CMP-034's security rules S1–S7 go to the security engineer in E05-X02
(§6 G19).
