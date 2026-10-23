# E05-D02 — Design-system atoms and molecules: slice 4 of 5 (feedback and overlays)

**Ticket:** E05-D02 (#161) · **Epic:** E05 Design system v0 · **Status:** In Review — awaiting owner approval (slice 4
of 5) (design PR: the owner approves under C-10.1; the coordinator reviews). Text-first: written from `15`, the tokens
and E09-D09 without a Penpot build (the coordinator's ruling of 2026-10-23); the boards are PENDING.
**Penpot:** page `10 Components — Atoms` of the CandleViewer DS file. The boards PR builds the 17 variant sets there
(the molecules and the three route states beside the atoms), exports them, adds the page id and redraws nothing in
slices 1–3. Slice 5 carries #161's closing line.
**Slices:** #161 ships as five design PRs. Slice 1 (#3914, `E05-D02.md`) covers actions and selection; slice 2 (#4290,
`E05-D02-data-display.md`) the data display and text atoms; slice 3 (#4322, `E05-D02-form-controls.md`)
the form controls; this slice the feedback and overlays of the coordinator's five-slice plan on #161: CMP-015 Skeleton,
CMP-016 Tooltip, CMP-017 Popover, CMP-023 ProgressBar, CMP-026 EmptyState, CMP-027 ErrorState / InlineError, CMP-028
Callout / Banner, CMP-029 Skeleton-Chart placeholder, CMP-038 InlineSpinnerText, CMP-041 Menu, CMP-043 Dialog, CMP-044
ConfirmDialog, CMP-045 Toast, CMP-046 Drawer, CMP-089 ForbiddenState, CMP-090 NotFoundState and CMP-091
GlobalErrorBoundaryFallback. Slice 5 covers the rest.
**Companion:** `E05-D02-feedback-overlays-a11y-audit.md` (accessibility pre-review of this slice).
**Builds on:** slice 1's conventions 1–14, token mirror, exceptions and decisions A1–A12, B1–B7, C1–C15 and D1–D17 (D13
is superseded by E09-D09 §2.2 T2); the conventions 15–20 and decisions E1–E27 of slice 2 (#4290, head `fd4ea21d1`);
and the conventions 21–29 and decisions G1–G21 of slice 3 (#4322, head `838bbb768`), the base of this branch. Slices 2
and 3 are read at those heads and cited as they stand, if their PRs merge as is. They apply unchanged and are cited as
"slice 1 A8", "slice 2 (#4290) E20" and "slice 3 (#4322) conventions 24".
**Key.** `05`, `14`, `15`, `16` are the `docs/plan/` documents by number; D09 is `docs/design/E09/E09-D09.md`, D08
`docs/design/E09/E09-D08.md`. `path:line` references are at `origin/main` `5a382efec`; slices 2 and 3 are cited by
section.

## 1. What this slice specifies

- **17 components, 50 variant properties, 99 cells.** One Penpot variant set per CMP id, named `CMP-0xx · Name` (brief
  §10; a catalogue `/` is dropped, slice 1 §1.1). The matrix rule is slice 1 conventions 2: every documented state at
  the default of the other axes, every other axis value once, and the universal states where the component is
  interactive. Each section lists its cells and the states that do not apply, with the reason; "closing" is a motion
  state, specified in the Motion line and never drawn as a cell.
- **One section per component** (§7): the catalogue Props and A11y verbatim, the variant properties, the matrix, the
  anatomy and its tokens, the keyboard and role tables, focus, motion, live regions, T2 and what is not T2, alignment.
- **No build yet.** Every token below is a published semantic token or a named primitive (§4, §5); nothing is drawn
  until the boards PR. Cells nest the components of slices 1–3 (CMP-001, 002, 005, 006, 007, 014, 019, 021, 031, 033,
  040, 047, 079) as live instances once their boards exist; a component of slice 5 (CMP-022 Kbd) or outside #161
  (CMP-212 ToastHost) is drawn from its catalogue entry as a plain board until it ships.
- **The ruling on gating.** An atom never owns policy gating; the host does (the orchestrator's ruling on slice 2,
  record 6368751311, M1; slice 2 (#4290) E27 recommends the same: "the host owns the gating, never the atom", and "a
  link to an admin destination is hidden, not locked"). A container here — tooltip, popover, menu, dialog, drawer,
  toast, callout, empty state — has no gated state of its own; only a nested control takes T2, in its own T2 form
  through CMP-079 RbacGate, with the host's reason (conventions 36).
- **Catalogue alignment, in this PR.** The 17 entries of `15` are updated in slices 1–3's form; each clause traces to
  its section here. Clauses that encode a choice awaiting your answer are listed in §6 (e); the held updates are §6 (f).

| Component                   | Penpot variant set (boards PR)          | Variant properties                   | Cells  | Composes (live instances)                                                                                     |
| --------------------------- | --------------------------------------- | ------------------------------------ | ------ | ------------------------------------------------------------------------------------------------------------- |
| CMP-015 Skeleton            | `CMP-015 · Skeleton`                    | Shape, Motion, Surface               | 6      | —                                                                                                             |
| CMP-016 Tooltip             | `CMP-016 · Tooltip`                     | Side, Mode, Content, Trigger         | 7      | CMP-001, CMP-002 (triggers; CMP-079 on the gated one), CMP-019 (`lock` badge)                                 |
| CMP-017 Popover             | `CMP-017 · Popover`                     | Modal, Placement, Overflow           | 4      | CMP-040 + CMP-007, CMP-031, CMP-001; CMP-047's calendar                                                       |
| CMP-023 ProgressBar         | `CMP-023 · ProgressBar`                 | Kind, Tone, Value, Label             | 8      | CMP-019 (`warning`, `danger`)                                                                                 |
| CMP-026 EmptyState          | `CMP-026 · EmptyState`                  | Variant, Action                      | 7      | CMP-019, CMP-001, CMP-021, CMP-023, CMP-027                                                                   |
| CMP-027 ErrorState          | `CMP-027 · ErrorState`                  | Form, Severity, Retry, Details       | 4      | CMP-019 (`danger`, `warning`), CMP-001, CMP-033                                                               |
| CMP-028 Callout / Banner    | `CMP-028 · Callout`                     | Tone, Placement, Dismissible, Action | 8      | CMP-019, CMP-001, CMP-002, CMP-021, CMP-023                                                                   |
| CMP-029 Skeleton-Chart      | `CMP-029 · Skeleton-Chart placeholder`  | Panes, Motion                        | 3      | — (the host's CMP-038 sits over it)                                                                           |
| CMP-038 InlineSpinnerText   | `CMP-038 · InlineSpinnerText`           | Phase, Cancel                        | 3      | CMP-014 Spinner, CMP-001                                                                                      |
| CMP-041 Menu                | `CMP-041 · Menu`                        | Trigger, ItemState                   | 10     | CMP-019 (`check`, `chevron-right`, `lock`), CMP-079 (gated items), CMP-022 (plain board)                      |
| CMP-043 Dialog              | `CMP-043 · Dialog`                      | Size, Role, Overflow, State          | 7      | CMP-001, CMP-002 (close), CMP-040 + CMP-007                                                                   |
| CMP-044 ConfirmDialog       | `CMP-044 · ConfirmDialog`               | Variant, State                       | 9      | CMP-043, CMP-001, CMP-040 + CMP-007, CMP-005, CMP-006, CMP-027, CMP-019 (`lock`), CMP-079 (the gated Confirm) |
| CMP-045 Toast               | `CMP-045 · Toast`                       | Tone, Action, Lifetime, State        | 7      | CMP-019 (tone glyphs, `lock`), CMP-001, CMP-002 (dismiss), CMP-041 (Snooze), CMP-079 (gated actions)          |
| CMP-046 Drawer              | `CMP-046 · Drawer`                      | Side, Modal, State                   | 5      | CMP-002 (close), CMP-001, CMP-015                                                                             |
| CMP-089 ForbiddenState      | `CMP-089 · ForbiddenState`              | Variant, Ref, Scope                  | 4      | CMP-019 (`lock`), CMP-021, CMP-001                                                                            |
| CMP-090 NotFoundState       | `CMP-090 · NotFoundState`               | Variant                              | 3      | CMP-019 (`search`), CMP-021                                                                                   |
| CMP-091 GlobalErrorBoundary | `CMP-091 · GlobalErrorBoundaryFallback` | Scope, Details, Repeated             | 4      | CMP-019 (`danger`), CMP-001, CMP-033                                                                          |
| **17**                      |                                         | **50**                               | **99** |                                                                                                               |

Every gated cell — CMP-016's echo · reason, CMP-041's disabled-with-reason, CMP-044's gated and CMP-045's T2 action —
is a CMP-079 RbacGate composition with the CMP-019 `lock` glyph (conventions 36); CMP-026's two sentence cells carry
neither, because the sentence form has no `lock` and no button (D09 §2.2, §8).

**Deviations.** None of the 17 belongs elsewhere: CMP-089, 090 and 091 sit in the organism band of `15` §0.2, but the
ticket lists them as cross-band v0 additions. The brief's "slice 2 E-row on CMP-014's cap" is slice 1's D15
(`E05-D02.md:508`–`:528`); slice 2 (#4290) has no row on it.

## 2. How to review

1. Read the conventions once (§3, items 30–39): every component section cites them instead of repeating them.
2. Read a section top to bottom: the matrix says what the boards PR draws, the anatomy how, the tables how it behaves;
   the catalogue text it quotes is `main`'s, before this PR's edits.
3. The owner decisions are §6 (H1–H30); §6 (e) says what a "no" reverts, §6 (f) lists the held edits and hand-offs.
4. The catalogue edits are in `docs/plan/15-component-catalogue.md`, in the 17 entries only; the boards PR then draws
   the 99 cells and exports each section at dark/compact with the six proof frames (slice 1 §2).

## 3. Conventions (30–39, numbered on from slice 3's)

30. **Floating surfaces** (CMP-016, 017, 041, 045, the non-modal CMP-046). Fill `color.surface.overlay`, elevation
    `elevation.popover`, radius `radius.card`, a 1 px `color.border.default` edge (decorative: the elevation and the
    position carry the layer; `color.border.subtle` vanishes on light overlay, slice 1 A4). Text on them is
    `color.text.primary` (13.27:1 or more), `color.text.secondary` (8.14:1 or more) or `color.text.tertiary` (5.20:1 or
    more); never `color.surface.raised`, which is T2's well and fill (slice 3 conventions 24). **Modal surfaces**
    (CMP-043, 044, the modal CMP-046) take `elevation.dialog` and `radius.dialog` (the drawer is square: it meets the
    viewport edges) over the scrim of conventions 31. An anchored surface sits `space.inset.xs` from its anchor and
    flips side when the viewport has no room (an overlay anchor, slice 1 B3 (b)).
31. **The scrim and the inert page** (CMP-043, 044, the modal CMP-046). The scrim is black at `opacity.scrim` (0.6) in
    every theme — the PROPOSED `color.surface.scrim` (D08 A-2, `E09-D08.md:453`), bound meanwhile to the named
    primitives `palette.black` and `opacity.scrim` (§6 H1); never `color.surface.sunken`, which is black in dark only;
    no blur (D08 D16). It covers the workspace below the TopBar and the SCR-152 slot: the env band, the CMP-211 panic
    cluster and the shell's live regions stay above it and outside the inert subtree (§6 H23; `14:1673` "never covered
    by a modal"). The page under it is `inert`. CMP-212's toasts render above the scrim but outside the dialog's trap
    and never over its footer, and they stay in the inert subtree: a toast is seen, its sentence speaks through
    CMP-212's pre-rendered regions, which stay outside the subtree with the shell's, and its actions are reached after
    the dialog closes (E40-D02 §4.3 "Modals", `E40-D02.md:671`, D-20); while the stack is inert, every timer in it is
    paused, and they resume when the dialog closes (conventions 34). A press on the scrim is Cancel for `role="dialog"`
    and does nothing for `role="alertdialog"`, which asks for an explicit choice.
32. **Focus contract for overlays** (`05` §3.4 items 3–4, `05:96`–`:97`). Nothing here takes focus on its own: a toast,
    a callout, a tooltip and a route-level replacement never move it (D09 §9.4 restorations excepted, CMP-089, 091). A
    surface opened by the user takes it: a popover to its first control (or `initialFocusRef`; without one, its heading
    at `tabindex="-1"`), a drawer to `initialFocusRef`, else its heading at `tabindex="-1"` (its body is content to
    read: E08-D06 §10.1, `E08-D06.md:397`; E40-D02 §4.4, `E40-D02.md:683`), a menu to its first item (`↑` from the
    trigger: its last), a dialog to `initialFocusRef`, else its first field, else its heading; a destructive or alert
    dialog to Cancel (`14:1619` SCR-072, `14:2521` SCR-129; E42-D02 D18). A modal traps Tab; a non-modal surface lets
    Tab leave and closes or stays open as its section says. **Return:** on close, focus goes back to the control that
    opened it; when that control is gone, to the host's named fallback (E40-D02's bell), never to `body`. **Esc** closes
    the topmost layer only and stops there: a tooltip first, then a menu or popover, then the dialog (`05` §3.3 rule 3:
    `Esc` is reserved).
33. **Where feedback speaks** (`05` §6.2, `05:148`–`:150`; D09 §4.4). Polite by default; assertive (`role="alert"`) only
    for `05` §6.2's discrete, important class: an order rejected, the connection lost, a risk lockout, a refused action
    at its point of action, the error summary on submit. Each message speaks **once**; a counter, an age or a countdown
    is `aria-live="off"` and never announced per tick. A component that is its own region (CMP-027, CMP-028, CMP-038)
    mounts it empty with its host and inserts the text when its state begins — the CMP-014 rule, the region hygiene of
    `05` §6.2. A component that arrives with new content (a toast, a dialog, a route page) does not rely on its own live
    role: a toast writes its sentence into CMP-212's pre-rendered polite or assertive region (§6 H28); a dialog is read
    when focus enters it.
34. **Timing** (WCAG 2.2.1, 2.2.2, 2.2.4). Nothing a user must read or act on disappears on a timer unless it pauses on
    hover and focus, its duration follows the user's setting with an "until dismissed" choice, and a persistent record
    keeps it (SCR-014). A toast with an action or a `danger` tone never times out (§6 H26). Looping motion stops at 5 s
    (the skeleton shimmer) or is an essential request-bound indicator with slow-path words at 5 s (CMP-014, CMP-038,
    slice 1 D15). An interruption never takes focus, so the user postpones it by ignoring it; only an explicit
    `alertdialog` the user's own action opened moves focus (`05` §3.4 item 3).
35. **Motion pairs** (brief §7, `16:171`–`:183`; D08 D2; E40-D02 §8). Only `opacity` and `transform` animate, with the
    shipped primitives `motion.duration.*` and `motion.easing.*` (slice 1 A8). **A focused control is never inside a
    fading element** (D08 D2): a dialog's scrim fades and its card is a cut (§6 H21); a popover and a menu appear at
    once; only what never holds focus fades in (a tooltip) or slides in (a toast, a drawer, which is opaque from its
    first frame). Exits fade over `motion.duration.fast` with `pointer-events: none` from their first frame.
    `motion-reduce` removes every movement: a cut, or the fade-only toast of brief §7, which needs the E05-D03 (#162)
    recipe to survive the global reduce rule in `packages/ui/src/theme/theme.css` and is otherwise a cut too. A mode
    change mid-flight lets a running fade finish on its clock (D08 D15).
36. **Containers never gate; their nested controls do** (the ruling, §1). A gated action inside any component of this
    slice is the nested control's T2 form: CMP-001's and CMP-002's (D09 §2.2, which supersedes slice 1 D13), a CMP-041
    item's (§7 CMP-041), CMP-006's option (slice 1). _Wrapper:_ CMP-079 RbacGate wraps the step-3 leg (D09 §2.1 step 3;
    §8, `E09-D09.md:204`) in slice 3 (#4322) G15's `form` — `inline` by default, `tooltip` for an
    icon-only control or a toolbar segment without room, `notice` for one reason line that several controls point at; a
    step-4 state reason goes to the control's own `disabledReason` (slice 3 (#4322) conventions 24).
    _Semantics:_ the control keeps its role and its full label; `aria-disabled="true"`, never `disabled`, so it stays in
    the Tab order and a menu item stays arrow-reachable; the CMP-019 `lock` glyph (`decorative=false`, name "Not
    available") leads the label in rendering 2a, and is the badge on an icon-only control in 2b; the reason is in the
    DOM at mount, linked by `aria-describedby`. _Visual:_ the label and the lock in `color.text.tertiary`, the reason in
    `color.text.secondary`, a filled control's fill to `color.surface.raised` with a 1 px `color.border.default`
    hairline (`border.hairline`); never `color.text.disabled`, never `opacity.disabled` on the label, glyph or reason
    (D09 §2.2, `E09-D09.md:49`, measured 2.86–4.31:1 in D09 §11; slice 3 conventions 24). _Keys:_ Tab reaches it;
    `Enter`, `Space` or a bound hotkey changes nothing and re-shows the reason inline with one polite announcement; an
    arrow lands on a T2 menu item without activating it (D09 §9.3). _Reason:_ the host's key (D09 §3.1 or a registered
    state vocabulary); a component never writes it, and it emits no audit and no analytics. Several gated controls in
    one surface point at one reason line ("one notice, many pointers"). The sentence form is CMP-026 with `cta` omitted:
    no `lock` and no button; CMP-026's own decorative glyph stays (D09 §2.2, `E09-D09.md:49`; §8, `E09-D09.md:210`). A
    link whose only destination is an admin route is hidden (T3, D09 §2.1 step 1), never locked.
37. **What is not T2 here** (D09 §9.1; the standing rulings). _Busy:_ a confirm whose request is in flight, a toast
    action being sent, a load — CMP-001 `loading`, `aria-busy`, focusable, no lock, no reason. _Outcome:_ an action done
    or no longer applicable is replaced by its outcome line (an expired Undo by "EMA 21 removed."; #960 Q13).
    _Availability:_ no rows, no results, history not recorded yet — CMP-026's words. _Validity:_ a typed confirmation
    that does not match keeps Confirm natively disabled (D09 §9.1 "form validity"; §6 H24). _Route outcomes:_ CMP-089
    renders D09's T4 landing and the step-3 never-had landing, CMP-090 D09's T3 hard-404 — states, not locks.
    _Failures:_ CMP-027 and CMP-091 are outcomes.
38. **Forced colours** (`05` §8.1; slice 1 conventions 12). Every floating and modal surface keeps a real 1 px border,
    which forced colours paint CanvasText, so the layer keeps its edge when its fill and shadow are lost; the scrim
    keeps `forced-color-adjust: none` with its black at 0.6 so it neither vanishes nor turns opaque; text takes
    CanvasText, glyphs `currentColor`; a tone edge or fill (toast, callout, progress fill) becomes CanvasText or
    Highlight and the glyph and the word carry the tone; a focused menu item sets a Highlight fill with HighlightText
    explicitly (`forced-color-adjust: none` on that part); the focus ring is a Highlight outline; skeleton fills drop
    out, and the host's busy words carry the wait.
39. **Resize, zoom and reflow** (`05` §5 item 7; slice 3 conventions 28). Heights are minimums: at 112–150 % text, rows,
    items and buttons grow taller and never clip. At 200 % zoom on the 1280 × 800 frame a dialog fills the viewport (its
    width `min(size, 100vw − 2 × space.inset.lg)`), its header and footer stay as one sticky row each and its body
    scrolls; a drawer takes the full width at a viewport of 720 CSS px or less (E08-D06 D-14, `E08-D06.md:51`); a
    popover or menu caps its height to the room above or below its anchor and scrolls; a tooltip wraps inside its
    maximum width and flips side; a toast keeps its width or the viewport width less `space.inset.lg` each side.

## 4. Token mirror and themes

No token is added or changed; the Penpot mirror is slice 1 §4's, re-synced with #3925 (`a0132de01`, the last change to
`packages/ui/tokens`), and every figure here and in the audit is measured at that state. The slice binds only published
semantic tokens, in all three themes — the surface, border, text, action, status (`subtle`, `default`, `strong`) and
focus colours, `size.control.height`, `size.row.height`, `size.icon`, the `space.inset.*`, `space.stack.*`,
`space.dialog.padding` and `space.panel.padding` aliases, `radius.control|card|dialog|badge`,
`elevation.popover|dialog|scrim`, the `type.ui.*` and `type.num.*` styles and the motion primitives (slice 1 A8) — plus
the named primitives of §5.2. Each section maps the catalogue names that do not exist (`color.surface.skeleton`,
`motion.shimmer`, `motion.slide`, `color.track`, `color.callout.*`, `space.emptystate.*`, the bare
`color.status.warning/danger` and `color.action.primary`, the primitives `elevation.3`, `elevation.4`, `radius.md`,
`radius.lg`) to shipped tokens, and the Tokens lines are rewritten to match. Two tokens other specs propose are named
with their stand-ins (slice 1 conventions 9): `color.surface.scrim` (D08 A-2; `palette.black` at `opacity.scrim`, §6 H1)
and `motion.duration.hold-confirm` (E39-D03 G12; the 800 ms constant, §6 H2). A token gap is an owner decision (§6 (a));
none is invented.

## 5. Recorded exceptions

### 5.1 Geometry and timing constants without a token

Each value is drawn or specified raw and logged for ticket AC2 ("zero hardcoded hex or px values"); rows that recur from
slices 1–3 keep their resolution.

| Constant          | Value                                                                                                                                                                                                                                                                                | Components                                | Proposed resolution                                                                             |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Surface widths    | tooltip at most 320 px; toast 360 px (E40-D02 §4.2); dialog sm 420 / md 560 / lg 960 px (§6 H17); drawer 480 px for detail (E08-D06 D-14), 320 / 360 px for docked inspectors (E14-D02, E18-D02); the empty-state and route-state text column at most 480 px                         | CMP-016, 026, 043, 044, 045, 046, 089–091 | Component constants and host data, like slice 1 §5.1 "Sample dimensions"; no size token (§6 H7) |
| Surface heights   | a dialog at most 80 % of the viewport, then its body scrolls (E39-D03 §4); a popover or menu at most the room to the viewport edge                                                                                                                                                   | CMP-017, 041, 043, 044, 046               | Layout rules, not values (§6 H7)                                                                |
| Progress track    | 8 px thick, built from `space.inset.xs` padding (slice 1 B4)                                                                                                                                                                                                                         | CMP-023                                   | As slice 1 B4; no token                                                                         |
| Rings             | the inset focus ring at a −2 px offset (§6 H8); the hold ring's 3 px stroke (E39-D03 §5)                                                                                                                                                                                             | CMP-041; CMP-044                          | CMP-039 constants, as slice 1 B2                                                                |
| Skeleton geometry | the last text line at 60 % width; CMP-029's candle silhouette (illustrative data)                                                                                                                                                                                                    | CMP-015, CMP-029                          | Data and illustration, like slice 1's surrogate chart                                           |
| Timing            | tooltip delay 300 ms (`15:196`), leave grace 100 ms, skip window 300 ms; slow path at 5 s; shimmer period 1,200 ms, stopped at 5 s; toast duration 5 / 10 / 20 s / until dismissed; hold 800 ms (300–2,000 ms setting), discrete window 5 s, key gap 250 ms; activation guard 400 ms | CMP-016, 015, 029, 038, 044, 045          | Behaviour constants (slice 3 §5.1 "Timing"); the hold value is the token of §6 H2               |

### 5.2 Other recorded exceptions

- **Named primitives** (slice 1 §5.2): `palette.black` with `opacity.scrim` for the scrim until §6 H1; `border.thick`
  for the toast's and the callout's 2 px tone edge (slice 2 (#4290) E4's naming); `border.focus` for the ring width;
  `border.hairline` for every 1 px edge (slice 1 B1); `opacity.disabled` for a plain-disabled menu item; CMP-019's
  `size.icon.lg` for the empty-state and route-state glyph (slice 1 §5.2's size scale).
- **Absolute internals:** only slice 1 B3's (a) focus ring (the inset ring of §6 H8 included) and (b) overlay anchors —
  every floating surface of this slice, the scrim, and the toast stack, whose position is CMP-212's.
- **Penpot variant-set chrome:** as slice 1 B7.

## 6. Decisions for the owner (collected)

Deduplicated across the 17 components and against slices 1–3; H1–H30 are new, each PROPOSED with options and a
recommendation. Not asked again: slice 1 A4 (overlay rules bind `color.border.default`), A6 (light danger and warning
glyphs share one amber), A8 (motion primitives), A10 (icon sizes), B1–B3 (geometry, rings, overlay anchors), C9 (spinner
modes), C13 (strict matrix), C15 (stories) and D15 (the slow path); slice 2 (#4290) E20 ("Copied" once); slice 3
(#4322) G2 (the error glyph), G17 (answered by H14) and G21 (row menus).

### (a) Token gaps (E05-D01's token files, outside this PR's write set)

- **H1 — The scrim colour.** No scrim colour is shipped: `elevation.scrim` is a shadow, `color.surface.overlay` a fill,
  and `color.surface.sunken` is black in dark only (`#D6DAE0` in light). Options: (a) D08 A-2's
  `color.surface.scrim = {palette.black}` in `semantic-dark` and `semantic-light`, used at `opacity.scrim`; (b) bind
  `color.surface.sunken`, which fogs the light page; (c) keep the primitives for good. **Recommended:** (a), in the E05
  token follow-up; until it lands the scrim binds the named primitives `palette.black` and `opacity.scrim` (§5.2), as
  E39-D03 §4 and D08 D2 draw it. **Affects:** CMP-043, 044, 046 (and CMP-077, the auth chassis).
- **H2 — The hold-confirm duration.** E39-D03 G12 (`E39-D03.md:407`) routes the missing hold token to this lane:
  `14:294` SCR-010 says 800 ms, E30-D02 600 ms (E39-D03 C7); E39-D03 Q4, ruled on 2026-10-22, sets 800 ms, a 300–2,000
  ms user range (US-SET-003) and a 5 s discrete window. Options: (a) add `motion.duration.hold-confirm` = 800 ms with
  #162's recipes; (b) a CMP-044 constant. **Recommended:** (a); until it lands `holdDurationMs` defaults to the 800 ms
  constant (§5.1), and E30-D02's 600 ms follows at its next revision. **Affects:** CMP-044, CMP-211.
- **H3 — The skeleton tokens and the shimmer.** `color.surface.skeleton` and `motion.shimmer` do not exist. Three merged
  specs already agree on a recipe: blocks in `color.surface.hover`, a sweep to `color.surface.raised` with a 1,200 ms
  period (3 × `motion.duration.slow`), stopped at 5 s, then the static two-tone (E11-D06 D16, `E11-D06.md:92`; E42-D04
  M12, `E42-D04.md:563`; E36-D03). In light `color.surface.hover` equals the overlay (1.00:1), so on an overlay host the
  blocks take `color.surface.selected` and sweep to `color.surface.hover`. Options: (a) accept the mapping and the
  recipe, no token; (b) add `color.surface.skeleton` and a shimmer recipe in #162. **Recommended:** (a); the sweep's
  luminance step is 0.011–0.090, under the 0.10 flash bar (audit §4). Brief §7's "slow looping shimmer" gains the 5 s
  stop (a hand-off, §6 (f)). **Affects:** CMP-015, CMP-029.
- **H4 — The progress track and the tone fills.** `color.track` does not exist (CMP-138 uses `color.surface.sunken`,
  which is black in dark). The track binds `color.surface.hover`; the fills measure against it 3.09 / 3.80 / 5.66:1
  (`color.action.primary.default`), 5.99 / 4.30 / 5.99 (`color.status.success.default`), 9.36 / 3.78 / 9.36
  (`color.status.warning.strong`: `.default` is 2.76:1 in light) and 2.92 / 8.24 / 3.45 (`color.status.danger.default`,
  thin in dark). Options: (a) these four and the value text that always carries the figure; (b) a `color.track` token
  tuned for every fill. **Recommended:** (a) now, and (b) in the E05 token follow-up so the dark danger fill reaches
  3:1. **Affects:** CMP-023 (CMP-138, CMP-177 inherit it).
- **H5 — The callout tokens and the connection tones.** `color.callout.*` does not exist. A callout binds
  `color.status.{tone}.subtle` with a 2 px `border.thick` start edge and its glyph in `.strong`, words in
  `color.text.primary` and `.secondary` (E08-D03 §2, `E08-D03.md:49`; it drew a 4 px edge without a token). The two
  connection tones keep `color.status.danger.subtle` and `.strong`: the catalogue's
  `color.data-confidence.disconnected.indicator` measures 2.88:1 (dark) and `reconnecting.indicator` 2.81:1 (light) on
  that fill (E17-D02 C21, `E17-D02.md:443`). Options: (a) the status subtle and strong pair, the connection tones on
  danger; (b) the catalogue's accents on the fill. **Recommended:** accept; the data-confidence indicators stay on
  `color.surface.*` (CMP-239's). **Affects:** CMP-028 (CMP-077, CMP-092).
- **H6 — Light status edges on the overlay.** Light `color.status.warning.default` measures 2.76:1 on
  `color.surface.overlay`; E40-D02 §4.2 (`E40-D02.md:626`) binds `.strong` in light only until its DS-CR-2, a per-theme
  binding a token swap cannot express (`16` §4). Options: (a) `.default` in every theme; (b) E40-D02's light-only
  `.strong`. **Recommended:** bind `.default` in every theme, rely on the `.strong` glyph and the tone's word, and ask
  the token follow-up (with slice 1 A6) to lift light warning to 3:1 on the overlay. **Affects:** CMP-045, CMP-023
  (warning uses `.strong`), CMP-165.

### (b) Geometry constants and layout

- **H7 — Accept §5.1's constants** (surface widths and heights, the 8 px track, the timing values) under slice 1 B1's
  ruling. Options: (a) recorded constants; (b) a size-token family for overlay widths. **Recommended:** yes; no size
  tokens, and a host that needs another width (E36-D02's 1,120 px template gallery) passes it as data. **Affects:**
  CMP-015, 016, 023, 029, 038, 043, 044, 045, 046.
- **H8 — An inset ring inside scrolling containers.** CMP-039's ring sits 2 px outside its target; a menu item that
  spans its popup is clipped by the popup's scroll box. Options: (a) an inset variant of CMP-039 — the same 2 px
  `color.focus.ring`, drawn 2 px inside the item's bounds, radius `radius.control` (5.66 / 5.39 / 14.72:1 on the focused
  item's `color.surface.hover`); (b) pad every popup by the ring's reach. **Recommended:** (a), recorded as a CMP-039
  constant (§5.1). **Affects:** CMP-041 (and any item in a scrolling container).

### (c) Catalogue ambiguities (props, defaults, sizes)

- **H9 — CMP-015 `shape="chart"` beside CMP-029.** Options: (a) keep both: `chart` is a plain block for a chart-sized
  slot in a card, a row or a tile (CMP-024, CMP-228), and CMP-029 is the chart pane's placeholder; (b) drop `chart`.
  **Recommended:** (a), with that rule in the Props line. **Affects:** CMP-015, CMP-029.
- **H10 — CMP-016's two modes and its content.** A tooltip either **describes** its trigger (the text is the trigger's
  description: its node is in the DOM at mount, `hidden` until shown, and the trigger's `aria-describedby` points at it)
  or **echoes** a name or reason that lives elsewhere (an icon-only control's `aria-label`; a T2 reason node, D09 §9.2):
  then it is `aria-hidden="true"`, so nothing is read twice. Content is text only — a tooltip never holds a link or a
  control (a popover does). Hover shows it after `delay` (300 ms); keyboard focus (`:focus-visible`) at once; it stays
  while the pointer is on the trigger or the tooltip (WCAG 1.4.13), hides on leave after a 100 ms grace, on blur and on
  `Esc`, and never on a timer. Options: (a) the two modes, text-only content and this timing; (b) the catalogue's
  `ReactNode` and one mode. **Recommended:** approve; `content: string` replaces `ReactNode`, with `mode`. **Affects:**
  CMP-016 and every echo: slice 1 D10 and D14, the T2 2b form of CMP-002 and CMP-049.
- **H11 — CMP-017's semantics.** Options: (a) a dialog: `role="dialog"`, named by its heading or `aria-label`; non-modal
  without `aria-modal`, focus into it on open, Tab past its last control closes it and moves on from the trigger,
  `Shift+Tab` before its first returns to the trigger; modal with `aria-modal` and a trap; (b) a disclosure (focus stays
  on the trigger), which a portal-rendered panel cannot keep in reading order. **Recommended:** (a), with a required
  name (`aria-label?`/`aria-labelledby?`, one of them) and a pointer guard: an outside press closes it only when it both
  starts and ends outside. **Affects:** CMP-017 (CMP-041, CMP-047, SCR-018's coach marks, SCR-037's property popovers).
- **H12 — CMP-023's role, label and range.** The catalogue is a task-progress role, but its own purpose lists recorder
  disk usage, a gauge, and CMP-138 asks for `role="meter"` (E39-D02 C5, `15:1603`). Options: (a) the four rules below;
  (b) the progressbar role only, as written. **Recommended:** `kind: "progress" | "meter"` (default `progress`);
  determinate only — an unknown total uses CMP-038, never an indeterminate loop (E08-D11 D8, `E08-D11.md:65`); `label`
  or `aria-labelledby` required (axe `aria-progressbar-name`); `valueText?` for `aria-valuetext` ("page 3 of ~9"); the
  value text always rendered. **Affects:** CMP-023 (CMP-138, CMP-177, CMP-026).
- **H13 — CMP-026's error variant, link and heading.** `variant="error"` duplicates CMP-027. Options: (a) it renders
  CMP-027's panel form with `live="polite"` (slice 3 G17), one error surface; (b) its own look. **Recommended:** (a);
  plus `link?: {label, href}` (SCR-151's "one secondary learn-more link", `14:2859`) and `headingLevel?` (default 3, so
  the heading fits its panel's outline). **Affects:** CMP-026, CMP-027 (SCR-151 and every empty panel).
- **H14 — CMP-027's forms and politeness.** Options: (a) the three props below; (b) severity-only roles and a second
  component for a polite failure. **Recommended:** `form: "panel" | "inline"` (default `panel`);
  `live?: "assertive" | "polite" | "off"`, defaulting by severity (error assertive, warning polite) — polite for an
  in-panel load failure (slice 3 G17), `off` when another node already announced it; `action?: {label, onClick}` beside
  `retry?` (E11-D03 D03-CR-1, `E11-D03.md:429`); `details` behind a "Technical details" disclosure, selectable, with
  CMP-033's copy. **Affects:** CMP-027 (CMP-049, CMP-026, E30-D02 D16's summary).
- **H15 — CMP-028 in the shell band.** D09 DS-6 (`E09-D09.md:220`) asks for a band slot, a disclosure and a live switch;
  `15:302`–`:304` say "inline, non-global". Options: (a) the four parts below; (b) CMP-028 inline only, with the band as
  its own component. **Recommended:** (1) `placement: "inline" | "band"` (band: full width, no radius, under the TopBar;
  the slot's stacking order is the shell's, CMP-070 / CMP-072, outside #161); (2)
  `live?: "assertive" | "polite" | "off"`, defaulting by tone as `15:307` maps them, `off` rendering no live role (D09
  §4.1's access-changed banner); (3) the "What changed" disclosure is held: D09 DS-6 lists three shapes (a `details` on
  every tone, a children slot, CMP-051) — choose one; (4) correct "EnvBanner CMP-078" to CMP-074 (E17-D02 C15).
  **Affects:** CMP-028 (D09 §3.3 and §4.1, CMP-077).
- **H16 — CMP-041's items.** E11-D03 D03-CR-1 (`E11-D03.md:441`), which D09 §8 adopts, asks for
  `kind: "action" | "radio" | "checkbox"`, `checked?`, `group?`, `disabledReason?` (a second line, `aria-describedby`,
  focusable `aria-disabled`), `description?` and a context target opened by `Shift+F10` or the Menu key. Options: (a)
  apply it with the danger rule below; (b) the catalogue's `disabled?` alone, which D09 §8 rules out. **Recommended:**
  apply it, plus `elevation.popover` for `elevation.3` and one danger rule: a danger item is in the last group after a
  separator, its verb names the loss, its label ends with "…" when it opens CMP-044, its glyph takes
  `color.status.danger.strong` (7.93 / 3.78 / 7.93:1 on a focused item) and its label stays `color.text.primary` (red
  text is 3.17:1 on the dark overlay); the hidden "destructive action" description stays (`15:432`). E14-D03's
  `danger.default` glyph (2.92:1 on a focused dark item) follows at its boards PR. **Affects:** CMP-041.
- **H17 — CMP-043's sizes and role.** `size` has no values. Options: (a) three maximum widths and a role prop; (b)
  widths left to each consumer. **Recommended:** `size: "sm" | "md" | "lg"` (default `md`) as maximum widths 420 / 560 /
  960 px — E11-D03's go-to-date (420), E39-D03's SCR-072 card (560), E36-D03's export dialog (960) — and
  `role?: "dialog" | "alertdialog"` (default `dialog`; `alertdialog` for SCR-072, SCR-129, SCR-148 and the auth
  chassis). **Affects:** CMP-043, CMP-044.
- **H18 — CMP-089's props and words.** Options: (a) D09 DS-3; (b) the catalogue's `reason?` and "Access denied".
  **Recommended:** apply D09 DS-3 (`E09-D09.md:215`):
  `{code, requiredPermissions?, instance?, variant: "never-had" | "withdrawn", backHref, copyDetails}`, the `h1` from
  D09 §10 ("You don't have access to this" / "Your access changed"), never "Access denied"; "Ref {instance}" only when a
  403 body was received; the account variant echoes only the id the client asked for. **Affects:** CMP-089 (SCR-154).
- **H19 — CMP-090's props.** Options: (a) the three props below; (b) `path?` alone. **Recommended:** `path` (echoed as
  text), `tryRoutes` (derived from the session's permitted routes, D09 §6) and `variant?: "unknown" | "deleted"`
  (`14:2920`'s distinct copy for a deleted object); a typed `/admin/**` without `admin:read` always renders `unknown`,
  with the same copy, title and analytics as any unknown route. **Affects:** CMP-090 (SCR-155).
- **H20 — CMP-091's scope and focus.** The catalogue moves focus to the fallback heading on mount; `05` §3.4 item 3
  forbids stealing it. Options: (a) the scope and the restoration rule below; (b) the catalogue's focus move on mount.
  **Recommended:** `scope: "panel" | "app"`; focus moves only when the crash unmounted the focused element — a
  restoration, not a move (D09 §9.4); one assertive announcement — through the shell's pre-rendered region for a panel
  (conventions 33), the fallback's own `role="alert"` for the app, whose shell is gone; a repeated crash stops the
  automatic remount (`14:2930`). **Affects:** CMP-091 (SCR-156).

### (d) Behaviour proposals

- **H21 — Dialog and drawer motion.** Brief §7 (`16:178`) scales and fades a dialog; D08 D2 (`E09-D08.md:76`, merged,
  measured) fades only the scrim and cuts the card, so no frame shows a half-visible, focused Confirm; E30-D04 M6,
  merged after this branch's base (`E30-D04.md:547` at `4cc2f502f`), fades CMP-044's card in with an 8 px rise, Cancel
  focused at frame 0. Options: (a) D08 D2 for every CMP-043 and CMP-044 dialog; (b) brief §7 as written; (c) E30-D04 M6.
  **Recommended:** (a): the scrim 0 → 0.6 over `motion.duration.normal` / `standard`, the card at frame 0, the exit over
  `fast` / `accelerate`; drawers slide `translateX` over `normal` / `decelerate` (E40-D02 §8, E08-D06 A-3), opaque from
  frame 0; reduce: instant. The brief §7 line and E30-D04 M6 are hand-offs (§6 (f)). **Affects:** CMP-043, 044, 046.
- **H22 — `Esc`, the NoEscClose story and the scrim.** `15:450` lets a destructive confirm disable `Esc`; `05` §3.4 item
  4 keeps `Esc` = Cancel even on irreversible confirms ("cancel is always safe"). Options: (a) drop NoEscClose; (b) keep
  it, documented per instance. **Recommended:** drop NoEscClose: `Esc` always cancels before the confirmed send; once
  the request is sent, `Esc` closes the view and cancels nothing, and the outcome continues in the host's toast or
  surface (E39-D03's S20 toast); a press on the scrim is Cancel for a `dialog` and nothing for an `alertdialog`.
  **Affects:** CMP-043, 044, 046.
- **H23 — What the scrim makes inert.** Options: (a) E08-D05 D-11 (`E08-D05.md:52`): the scrim covers the workspace
  below the TopBar and the SCR-152 slot; the env band, the CMP-211 panic cluster and the shell's live regions stay above
  it and outside the inert subtree, and a panic press closes the dialog without commit; (b) the whole page inert (APG).
  **Recommended:** (a) for every workspace dialog and modal drawer — the safety controls stay one press away; the auth
  chassis keeps D08's own scope. **Affects:** CMP-043, 044, 046.
- **H24 — The confirm: its look, the typed rule and the guard.** E39-D03 §4 draws Confirm as CMP-001 `danger`; E42-D02
  D3 (`E42-D02.md:129`) draws text on `danger.subtle` with a `danger.strong` border. Options: (a) the three rules below;
  (b) E42-D02 D3's subtle confirm and an `aria-disabled` Confirm described by the instruction. **Recommended:** (1)
  CMP-001 `danger` (`color.text.on-action` on `color.status.danger.default`, 5.05 / 10.31 / 4.54:1), one danger button
  in the system; E42-D02 follows at its boards PR; (2) typed: the token is the object's own name, or a fixed word where
  the scope has none (`FLATTEN`, `LIVE`; E39-D03 C13); Confirm stays natively disabled until the summary has loaded and
  the field matches exactly (validity, not T2; D09 §9.1); `Enter` in the field never confirms (E42-D02 D18); paste is
  allowed (the token guards against a slip, not a client); (3) Confirm ignores an activation in the first 400 ms after
  the dialog opens (`14` SCR-076; E30-D02 `:355`) and ignores key repeats. **Affects:** CMP-044 (CMP-001).
- **H25 — The hold variant.** Options: (a) E39-D03's contract as the base; (b) the catalogue's sentence, each screen
  writing its own paths. **Recommended:** E39-D03 §5's contract (CMP-211's `hold` mode, `E39-D03.md:123`) as CMP-044's
  base: pointer — press and hold for `holdDurationMs` (H2) with a ring (`role="progressbar"`) and its percentage text;
  keyboard — hold `Enter` for the same time, or two non-repeat presses of `Enter` or `Space` at least 250 ms apart
  within 5 s (the first arms and renames the button "Press again to …", announced politely once); key repeats never
  confirm; `Esc` or blur disarms; reduce — no sweep, the percentage text alone at ≤ 2 updates a second. **Affects:**
  CMP-044 (CMP-211).
- **H26 — Toast timing.** The rule for CMP-045: a toast with an action, a `danger` tone or an error never times out; any
  other toast follows the user's toast-duration setting (5 / 10 / 20 s / until dismissed; E40 a11y T-1, OQ-12), pauses
  the whole stack on hover and focus, shows no countdown bar, and is copied to SCR-014. E40-D02 D-18 (Q2, ruled by the
  coordinator on 2026-10-22) closes Info and Warning fired-alert toasts, which carry actions, after 20 s, because each
  action is also on their SCR-014 row (E40 a11y KM-3, `e40-alerts-a11y-review.md:69`). Options: (a) the rule as
  CMP-045's default, with D-18 as CMP-165's documented exception; (b) the rule without exception, which reopens Q2.
  **Recommended:** (a): both meet WCAG 2.2.1 through the duration setting and the persistent record. **Affects:**
  CMP-045 (CMP-165, CMP-212).
- **H27 — Undo never delays a safety action.** `14:400` SCR-015 offers "Undo within 5 s for cancellations"; an order
  cancel held for 5 s would delay a risk-reducing action ("cancel is always safe", `05:97`). Options: (a) the rule
  below; (b) SCR-015's 5 s Undo on cancels, which holds the cancel back. **Recommended:** an order cancel is sent at
  once and its toast offers no Undo (re-placing is a new order through the ticket); Undo stays for local, reversible
  actions (an indicator or a drawing removed, E13-D02 §6.2, `E13-D02.md:223`), whose toast persists and whose Undo
  window follows the duration setting, then gives way to its outcome line; E13-D02's fixed 10 s window (pausing on hover
  and focus) is one of the setting's values and follows it too. The `14` wording and E13-D02's window are hand-offs to
  their owners (§6 (f)). **Affects:** CMP-045 (SCR-015, E31's undo window).
- **H28 — Where a toast speaks.** `15:468` puts the live role on the toast; CMP-212 (`15:2530`) owns a polite and an
  assertive region, and E40-D02 §4.3 lets only the announcer write. Options: (a) CMP-212's regions and a `politeness`
  prop; (b) a live role on each toast, as written. **Recommended:** a toast is never its own live region: it writes its
  sentence once into CMP-212's pre-rendered region (`05` §6.2 hygiene), polite for info, success and warning, assertive
  for `danger`; `role` becomes `politeness?: "polite" | "assertive"`, independent of `tone` (E40 AM-11,
  `e40-alerts-a11y-review.md:200`). **Affects:** CMP-045, CMP-212.
- **H29 — CMP-038's slow path.** Options: (a) the props below; (b) a slow path written by each host. **Recommended:**
  `slowLabel?` replaces the label at 5 s, announced once; `onCancel?` and `cancelLabel?` only for a load, an export or a
  replay, never an order submit, which says "Checking with the exchange…" and stays busy (slice 1 D15; C-2.10); no time
  cap and no elapsed counter; SCR-150's reload at 15 s is the host's. **Affects:** CMP-038 (CMP-014, CMP-001, SCR-150).
- **H30 — A gated Confirm inside an open dialog.** A `permission_change` can remove the confirm's leg while the dialog
  is open. Options: (a) degrade in place (D09 §4.1): Confirm takes CMP-001's T2 form with the host's reason under the
  footer, focus stays, one assertive announcement if it held focus (D09 §4.4 row 2); (b) close the dialog with "Not
  sent". **Recommended:** (a): nothing was sent, and the user reads why before cancelling; (b) stays D09 §4.2's rule for
  a request already held behind SCR-006. **Affects:** CMP-044, CMP-043.

### (e) Catalogue clauses applied, awaiting your approval

Each §7 **Catalogue alignment** paragraph lists the clauses applied to its entry and the H-row each encodes; a "no"
reverts every clause that cites it (no approval marker in `15`, slice 1 conventions 13). Clauses that map a token or
quote a merged spec (E11-D03 D03-CR-1, D09 DS-3, E40-D02 §7.4) follow their sources.

### (f) Catalogue edits held, and hand-offs

- **Held in `15`:** CMP-028's "What changed" disclosure (H15 (3)), until you choose one of D09 DS-6's three shapes.
- **Hand-offs (outside this PR's write set):** `16` §7 — the dialog recipe (H21) and the shimmer's 5 s stop (H3) — and
  `16` §2.6 with the token set — `color.surface.scrim` (H1) and `motion.duration.hold-confirm` (H2) — to the E05 token
  follow-up and E05-D03 (#162); the `14` SCR-015 Type line's Undo (H27) to its owner (E10); E13-D02 §6.2's fixed 10 s
  Undo window (H27), E42-D02 D3's confirm look (H24), E14-D03's danger glyph (H16) and E30-D04 M6's card motion (H21) to
  their owners; E40-D02 §4.2's light edge (H6) to its DS-CR-2.

## 7. Components

**Boards PENDING (text-first, 2026-10-23).** No section below has a Penpot build. Each names the variant set the boards
PR builds on page `10 Components — Atoms` and the export it adds, `docs/design/E05/img/CMP-0xx-name.png`.

### CMP-015 · Skeleton

**Catalogue (verbatim, `15:187-188`):**

- **Props**: `shape: "text"|"row"|"card"|"chart"` · `count?: number`.
- **A11y**: `aria-hidden="true"` (the loading state is announced once by the parent container's `aria-busy`, not per-skeleton).

| Axis    | Values                 | Default |
| ------- | ---------------------- | ------- |
| Shape   | text, row, card, chart | text    |
| Motion  | shimmer, static        | shimmer |
| Surface | base, overlay          | base    |

**Variants × States (6 cells; boards PENDING: `CMP-015 · Skeleton`, export `img/CMP-015-skeleton.png`):**

| Cell            | Axes                                     | What it shows                                                                                          |
| --------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| default         | Shape=text, Motion=shimmer, Surface=base | three lines (`count` 3) at `type.ui.body`'s line box, the last at 60 % width; the sweep's middle frame |
| row             | Shape=row                                | a `size.row.height` row with three cell blocks: a CMP-049 body while it loads (`E11-D04.md:321`)       |
| card            | Shape=card                               | a `radius.card` block holding a heading line and two text lines                                        |
| chart           | Shape=chart                              | one plain block filling a chart-sized slot in a card, a row or a tile (§6 H9)                          |
| Motion=static   | Shape=row                                | the static two-tone: the reduce look, and the look after the 5 s stop                                  |
| Surface=overlay | Shape=row                                | blocks in `color.surface.selected` on `color.surface.overlay`: a drawer or a popover loading (§6 H3)   |

**Not drawn:** interactive states (it is hidden and inert); loading is itself; empty and error are the host's.

**Anatomy** (compact / comfortable: only a row's height changes):

| Part        | Tokens                                                                                                                                 |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| text line   | the line box of the text style it stands for (`type.ui.body`); `radius.control`; gap `space.stack.xs`                                  |
| row         | min-height `size.row.height` 24 / 32; cell blocks `size.icon` tall, `radius.control`, padding-inline `space.inset.sm`; rows abut       |
| card, chart | card: `radius.card`, padding `space.inset.md`, inner lines as text; chart: one `radius.card` block, the slot's size (host data)        |
| fill        | `color.surface.hover` on app, canvas and raised hosts; `color.surface.selected` on an overlay host (§6 H3)                             |
| shimmer     | a band sweeping the fill to `color.surface.raised` (on an overlay: to `color.surface.hover`) and back; 1,200 ms period, stopped at 5 s |

**Keyboard:** none: not focusable.

**Accessible name and role:**

| Element     | Role                             | Name    | ARIA                                                                                                 |
| ----------- | -------------------------------- | ------- | ---------------------------------------------------------------------------------------------------- |
| skeleton    | none                             | —       | `aria-hidden="true"`                                                                                 |
| host region | its own (a table, panel, drawer) | its own | `aria-busy="true"` while loading; its words carry the wait ("Loading 5,000 bars…", `E11-D04.md:321`) |

**Motion:** motion-safe — one sweep per 1,200 ms, a `transform` on the band only, stopped at 5 s; the static two-tone
then holds and the host's slow-path words take over (CMP-038, conventions 34). Motion-reduce — the static two-tone from
frame 0 (brief §7). The sweep's luminance step is 0.011 (dark) and 0.073 (light), under the 0.10 flash bar. **Live
region:** none of its own: the host announces the wait once. **T2 and not T2:** no T2 (a placeholder); loading is busy
(conventions 37). **Hit target:** none. **Resize & overflow:** lines follow their text style (they stand for text); rows
keep their minimum height; card and chart fill their slot. **Forced colors:** the fills drop out and the host's words
carry the wait (conventions 38).

**Catalogue alignment** (`15:184-191`): Props notes the `chart` rule (H9); a States line (shimmer, stopped at 5 s;
static under reduce and after the stop); A11y appends that the host's words carry the wait; Tokens become the anatomy's,
replacing `color.surface.skeleton` and `motion.shimmer` (H3); Storybook adds Static and OnOverlay.

### CMP-016 · Tooltip

**Catalogue (verbatim, `15:196-197`):**

- **Props**: `content: ReactNode` · `side` · `delay?: number` (default 300ms) · `triggerOnFocus?: boolean` (true always, for keyboard parity).
- **A11y**: Radix Tooltip primitive — appears on hover AND focus, dismissible via `Esc`, does not trap focus, `role="tooltip"` + `aria-describedby` linking trigger.

| Axis    | Values                   | Default   |
| ------- | ------------------------ | --------- |
| Side    | top, right, bottom, left | top       |
| Mode    | describes, echo          | describes |
| Content | short, long              | short     |
| Trigger | hover, focus             | hover     |

**Variants × States (7 cells; boards PENDING: `CMP-016 · Tooltip`, export `img/CMP-016-tooltip.png`):**

| Cell          | Axes                                                   | What it shows                                                                                                                                                |
| ------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| default       | Side=top, Mode=describes, Content=short, Trigger=hover | one line over a CMP-001 trigger, `space.inset.xs` above it                                                                                                   |
| long          | Content=long                                           | E39-D03 S20's "Closes 4 positions at market — all accounts, LIVE + DEMO · hold 800 ms or press twice", wrapped at the 320 px maximum (`E39-D03.md:211`)      |
| echo · name   | Mode=echo                                              | a collapsed NavRail item's name over its icon (`14:332` SCR-011 "tooltips on collapsed icons reachable by keyboard focus"); the name is the `aria-label`     |
| echo · reason | Mode=echo                                              | the T2 2b echo over a CMP-002 in CMP-079 (`form="tooltip"`) with its `lock` badge: "Only the owner can change account settings." (D09 §2.4, `E09-D09.md:76`) |
| focus         | Trigger=focus                                          | the trigger's CMP-039 ring and the tooltip, shown at once                                                                                                    |
| right         | Side=right                                             | beside an option in a vertical list (slice 1 §3)                                                                                                             |
| bottom        | Side=bottom                                            | flipped below when the viewport has no room above                                                                                                            |

**Not drawn:** closed (nothing renders); Side=left (derivable, slice 1 C13); every state of its own (the trigger's).

**Anatomy** (no density change: the tooltip has no row height):

| Part    | Tokens                                                                                                                                                                        |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| surface | `color.surface.overlay`, `elevation.popover`, `radius.card`, a 1 px `color.border.default` edge; padding `space.inset.xs` block, `space.inset.sm` inline; at most 320 px wide |
| text    | `type.ui.caption`, `color.text.primary` (13.27:1 or more); wraps; no arrow                                                                                                    |
| offset  | `space.inset.xs` from the trigger, centred on it; flips side when there is no room                                                                                            |

**Keyboard** (WAI-ARIA APG Tooltip pattern):

| Keys                       | Action                                                                                       |
| -------------------------- | -------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab to trigger | Keyboard focus (`:focus-visible`) shows the tooltip at once; a pointer focus does not.       |
| Tab / Shift+Tab away, blur | Hides it.                                                                                    |
| Esc                        | Hides it; focus stays; the key stops here (a second `Esc` reaches the host, conventions 32). |

**Accessible name and role:**

| Element             | Role    | Name    | ARIA                                                                                                                                            |
| ------------------- | ------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| tooltip (describes) | tooltip | —       | in the DOM at mount, `hidden` until shown; the trigger's `aria-describedby` points at it, so the description is there when focus lands (§6 H10) |
| tooltip (echo)      | tooltip | —       | `aria-hidden="true"`: a visual duplicate of the trigger's `aria-label` or of the always-rendered reason node (D09 §9.2); never read twice       |
| trigger             | its own | its own | never the HTML `title` attribute (D09 §9.2)                                                                                                     |

**Focus:** never takes focus; persists while the pointer is on the trigger or the tooltip (WCAG 1.4.13), hides on leave
after a 100 ms grace, on blur and on `Esc`, never on a timer. **Motion:** motion-safe — opacity 0 → 1 over
`motion.duration.fast` / `decelerate` after the delay, out over `fast` / `accelerate`; motion-reduce — instant. **Live
region:** none: a tooltip is read as a description, never announced. **T2 and not T2:** the tooltip is T2's reason echo
(2b: the trigger in CMP-079 `form="tooltip"`, its CMP-019 `lock` badge the visible marker) and never the only copy (D09
§2.2, §9.2); it has no gated state of its own (conventions 36). **Hit target:** the trigger's; the tooltip is hoverable,
not a target. **Resize & overflow:** wraps inside 320 px; grows with text scale; flips side at the viewport edge.
**Forced colors:** a CanvasText 1 px border on Canvas, CanvasText text (conventions 38).

**Catalogue alignment** (`15:193-200`): Props `content: string` and `mode?: "describes" | "echo"` (H10); A11y appends
the two modes, the delay, keyboard focus at once, hoverable and persistent, `Esc` stopping at the tooltip, and the T2 2b
echo of a trigger in CMP-079 with its `lock` badge (conventions 36); Tokens become the anatomy's (`elevation.popover`
for `elevation.3`, `radius.card` for `radius.sm`); Storybook adds Echo.

### CMP-017 · Popover

**Catalogue (verbatim, `15:205-206`):**

- **Props**: `open` · `onOpenChange` · `anchor` · `placement` · `modal?: boolean`.
- **A11y**: focus-trap when `modal`, returns focus to trigger on close, `Esc` closes, click-outside closes (with `pointerdown` guard to avoid mis-fire on drag).

| Axis      | Values        | Default |
| --------- | ------------- | ------- |
| Modal     | false, true   | false   |
| Placement | below, above  | below   |
| Overflow  | fits, scrolls | fits    |

**Variants × States (4 cells; boards PENDING: `CMP-017 · Popover`, export `img/CMP-017-popover.png`):**

| Cell    | Axes                                        | What it shows                                                                                                                                               |
| ------- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| default | Modal=false, Placement=below, Overflow=fits | SCR-037's property popover, "a standard form" (`14:914`): a CMP-040 field, CMP-031 swatches and `Save as default` · `Delete`; the ring on its first control |
| modal   | Modal=true                                  | CMP-047's calendar dialog (slice 3): its heading, the trapped grid, the return to the calendar button annotated                                             |
| above   | Placement=above                             | flipped above its trigger when there is no room below                                                                                                       |
| scrolls | Overflow=scrolls                            | capped at the room to the viewport edge: the body scrolls under a fixed header and footer                                                                   |

**Not drawn:** closed (nothing renders); hover, active, disabled (the trigger's); loading, empty, error (its content's).

**Anatomy** (no density change of its own; its content follows density):

| Part    | Tokens                                                                                                                                                                                                                                       |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| surface | conventions 30: `color.surface.overlay`, `elevation.popover`, `radius.card`, a 1 px `color.border.default` edge; padding `space.inset.sm`; at least as wide as its trigger; `space.inset.xs` from the anchor, flipping when there is no room |
| heading | optional: `type.ui.body-strong`, `color.text.primary`                                                                                                                                                                                        |
| body    | the host's content, gap `space.stack.sm`                                                                                                                                                                                                     |
| footer  | optional: a CMP-001 row, end-aligned, `space.inset.sm` apart                                                                                                                                                                                 |

**Keyboard** (non-modal: a non-modal dialog, §6 H11; modal: WAI-ARIA APG Dialog (Modal)):

| Keys                         | Action                                                                                                                                                                             |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Enter / Space on the trigger | Opens it; focus moves to its first control (or `initialFocusRef`, or its heading at `tabindex="-1"`).                                                                              |
| Tab / Shift+Tab              | Modal: cycles inside. Non-modal: through its controls; Tab past the last closes it and moves on from the trigger; Shift+Tab before the first returns to the trigger and closes it. |
| Esc                          | Closes it; focus returns to the trigger.                                                                                                                                           |
| a press outside              | Closes it when the press starts and ends outside (a drag that leaves it does not); focus goes to the pressed control, else to the trigger.                                         |

**Accessible name and role:**

| Element | Role                    | Name                                                                | ARIA                                                       |
| ------- | ----------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------- |
| trigger | button (CMP-001 or 002) | its label                                                           | `aria-haspopup="dialog"`, `aria-expanded`, `aria-controls` |
| popover | dialog                  | its heading (`aria-labelledby`) or `aria-label`, one required (H11) | `aria-modal="true"` only when modal                        |

**Focus:** conventions 32. **Motion:** it takes focus, so it appears at once (conventions 35); the exit fades over
`motion.duration.fast` / `accelerate` with `pointer-events: none`; motion-reduce — instant. **Live region:** none of its
own. **T2 and not T2:** none of its own (a container); a gated control inside takes its own T2 form, and a link whose
only destination is an admin route is hidden (conventions 36). **Hit target:** its controls'. **Resize & overflow:**
caps its height and scrolls; flips at the viewport edge; content wraps (conventions 39). **Forced colors:** a CanvasText
1 px border on Canvas (conventions 38).

**Catalogue alignment** (`15:202-209`): Props gains `aria-label?/aria-labelledby?` (one required) and `initialFocusRef?`
(H11); A11y appends the dialog role, focus into it, Tab leaving a non-modal popover closing it, and the outside press
that starts and ends outside; Tokens become the anatomy's (`elevation.popover` for `elevation.3`, `radius.card` for
`radius.md`); Storybook adds Flipped and Scrolling.

### CMP-023 · ProgressBar

**Catalogue (verbatim, `15:259-260`):**

- **Props**: `value: number` (0-100) · `label?` · `tone`.
- **A11y**: `role="progressbar"` `aria-valuenow/min/max`.

| Axis  | Values                            | Default  |
| ----- | --------------------------------- | -------- |
| Kind  | progress, meter                   | progress |
| Tone  | default, success, warning, danger | default  |
| Value | partial, empty, complete          | partial  |
| Label | shown, hidden                     | shown    |

**Variants × States (8 cells; boards PENDING: `CMP-023 · ProgressBar`, export `img/CMP-023-progress-bar.png`):**

| Cell       | Axes                                                    | What it shows                                                                                              |
| ---------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| default    | Kind=progress, Tone=default, Value=partial, Label=shown | "Loading history" with the value text "page 3 of ~9" (E08-D04, `15:287`): the fill at a third of the track |
| empty      | Value=empty                                             | the track alone and "0 %"                                                                                  |
| complete   | Value=complete                                          | the full fill and "100 %"                                                                                  |
| unlabelled | Label=hidden                                            | the bar and its value text, named by the host's heading through `aria-labelledby`                          |
| meter      | Kind=meter                                              | a share of the recording budget (CMP-177, `15:2075`), "31 %"                                               |
| success    | Tone=success                                            | a finished export at 100 %                                                                                 |
| warning    | Tone=warning, Kind=meter                                | the recorder disk near its budget (CMP-177 NearDiskBudget): the `warning` glyph before "85 %"              |
| danger     | Tone=danger, Kind=meter                                 | over the budget: the `danger` glyph before "97 %"                                                          |

**Not drawn:** interactive states (not interactive); indeterminate (never, §6 H12); error (the host's CMP-027).

**Anatomy** (no density change; a host row keeps its own height):

| Part       | Tokens                                                                                                                                                                              |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| label row  | label `type.ui.label`, `color.text.secondary`, start-aligned; value text `type.num.sm`, `color.text.secondary`, end-aligned; `space.stack.xs` above the track                       |
| tone glyph | warning and danger only: CMP-019 `warning` / `danger` at `size.icon` in `.strong`, before the value text, `space.inset.xs` apart                                                    |
| track      | `color.surface.hover`, 8 px (`space.inset.xs` padding, slice 1 B4), `radius.badge`, the host's width                                                                                |
| fill       | default `color.action.primary.default`; success `color.status.success.default`; warning `color.status.warning.strong`; danger `color.status.danger.default` (§6 H4); `radius.badge` |

**Keyboard:** none: not focusable; the bar is read in reading order. **Accessible name and role:**

| Element              | Role                                        | Name                                         | ARIA                                                                                                  |
| -------------------- | ------------------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| bar                  | progressbar (`progress`) or meter (`meter`) | `label`, or `aria-labelledby` (one required) | `aria-valuenow`, `aria-valuemin`, `aria-valuemax`; `aria-valuetext` from `valueText` ("page 3 of ~9") |
| value text and glyph | none                                        | —                                            | `aria-hidden="true"`: the bar's value carries them                                                    |

**Motion:** motion-safe — a new value moves the fill by `transform: scaleX` over `motion.duration.normal` / `standard`,
samples at most once a second (E08-D11 M7, `E08-D11.md:125`); motion-reduce — a step. No loop. **Live region:** none:
the value changes silently and the host announces the start, the completion or a failure once (conventions 33). **T2 and
not T2:** none (a status display). **Hit target:** none. **Resize & overflow:** the track keeps 8 px; the label row
wraps, the value text never truncates. **Forced colors:** the fill `forced-color-adjust: none` in Highlight on a track
with a 1 px CanvasText border; the value text carries the figure (conventions 38).

**Catalogue alignment** (`15:256-263`): Props gains `kind?`, `valueText?`, the four `tone` values and a required name
(H12, H4); a States line (determinate only, the value text always shown, a glyph on warning and danger); A11y appends
`role="meter"`, `aria-valuetext` and no live region; Tokens become the anatomy's (the track for `color.track`;
`color.action.primary` read as `.default`); Storybook adds Meter and Unlabelled.

### CMP-026 · EmptyState

**Catalogue (verbatim, `15:286`, `15:288`):**

- **Props**: `icon` · `title` · `description` · `cta?: {label,onClick}` · `variant: "no-data"|"recording-not-started"|"backfill-in-progress"|"filtered-empty"|"error"`.
- **A11y**: heading semantics preserved (`h3` inside panel context), CTA is a real focusable button.

| Axis    | Values                                                                      | Default |
| ------- | --------------------------------------------------------------------------- | ------- |
| Variant | no-data, recording-not-started, backfill-in-progress, filtered-empty, error | no-data |
| Action  | cta, sentence                                                               | cta     |

**Variants × States (7 cells; boards PENDING: `CMP-026 · EmptyState`, export `img/CMP-026-emptystate.png`):**

| Cell                 | Axes                                           | What it shows                                                                                                                                                                                                   |
| -------------------- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| default              | Variant=no-data, Action=cta                    | "No rules yet — start from a template" with `Browse templates` (E36-D03, `E36-D03.md:112`)                                                                                                                      |
| recording            | Variant=recording-not-started                  | "History starts {ts} — recording began then", the owner's CTA to the recorder (`14:83`; wording under review, E16-D01 §4) and the `link?` drawn once: `Show coverage` (E11-D04 §11.2, `E11-D04.md:343`; §6 H13) |
| backfill             | Variant=backfill-in-progress                   | "Loading history — page 3 of ~9" with a determinate CMP-023 (`15:287`); informational, never `danger`                                                                                                           |
| filtered-empty       | Variant=filtered-empty                         | "No rows match: Bid-stacked, Delta negative" with `Clear filters` (E11-D04 §10)                                                                                                                                 |
| error                | Variant=error                                  | CMP-027's panel form, polite: "Couldn't load users — store unavailable." with `Retry` (E42-D03 U-6, `E42-D03.md:339`; §6 H13)                                                                                   |
| sentence             | Action=sentence                                | T2's sentence form for a viewer: "No rules yet. Your role can't change rules." — the reason alone, no button (`E36-D03.md:112`; D09 §8)                                                                         |
| sentence · recording | Variant=recording-not-started, Action=sentence | "Only the owner can start recording." for a manager or viewer (D09 §2.4, `E09-D09.md:73`)                                                                                                                       |

**Not drawn:** interactive states (static; the CTA and link are CMP-001's, CMP-021's); loading (CMP-015 or backfill).

**Anatomy** (compact / comfortable: spacing only):

| Part        | Tokens                                                                                                                                                              |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| block       | centred in its region on the host surface; a column at most 480 px (§5.1); padding `space.inset.xl`; gap `space.stack.sm`, then `space.stack.md` before the actions |
| glyph       | CMP-019 `size="lg"` (`size.icon.lg`, slice 1 §5.2) in `color.text.tertiary`, decorative                                                                             |
| heading     | `type.ui.heading-sm`, `color.text.primary`; `h3` unless `headingLevel` says otherwise                                                                               |
| description | `type.ui.body`, `color.text.secondary`; the sentence form uses the same style                                                                                       |
| actions     | the CTA a CMP-001 `secondary`; the link a CMP-021; `space.inset.sm` apart                                                                                           |
| progress    | backfill only: CMP-023 `progress`, or CMP-038 when the total is unknown (§6 H12)                                                                                    |

**Keyboard:** none of its own: the CTA (APG Button) and the link (APG Link) are in the Tab order. **Accessible name and
role:**

| Element | Role                              | Name      | ARIA                                                  |
| ------- | --------------------------------- | --------- | ----------------------------------------------------- |
| heading | heading, level `headingLevel` (3) | the fact  | —                                                     |
| CTA     | button (CMP-001)                  | its label | a gated CTA is never drawn: the sentence form instead |
| link    | link (CMP-021)                    | its label | —                                                     |
| glyph   | none                              | —         | `aria-hidden="true"`                                  |

**Motion:** none: the block swaps in at once. **Live region:** none: the block is static; when a filter empties a table,
the host's region says so once (slice 3 CMP-049). **T2 and not T2:** the sentence form only (D09 §8, `E09-D09.md:210`):
`cta` omitted, `description` the host's reason (conventions 36). Emptiness is availability, not T2 (conventions 37).
**Hit target:** CMP-001's and CMP-021's. **Resize & overflow:** wraps; never truncates. **Forced colors:** CanvasText
text, the glyph `currentColor`.

**Catalogue alignment** (`15:283-291`): Props gains `headingLevel?`, `link?` and the `error` rule (H13); a States line
(the five variants and the sentence form, D09 §8); Tokens become the anatomy's (for `space.emptystate.*`); Storybook
adds SentenceForm.

### CMP-027 · ErrorState / InlineError

**Catalogue (verbatim, `15:296-297`):**

- **Props**: `message` · `severity: "warning"|"error"` · `retry?: {label,onClick}` · `details?: string` (collapsible technical detail).
- **A11y**: `role="alert"` for severity `error` (assertive live region), `role="status"` for `warning` (polite).

| Axis     | Values         | Default |
| -------- | -------------- | ------- |
| Form     | panel, inline  | panel   |
| Severity | error, warning | error   |
| Retry    | shown, none    | shown   |
| Details  | closed, open   | closed  |

**Variants × States (4 cells, and one sample; boards PENDING: `CMP-027 · ErrorState`, export
`img/CMP-027-errorstate-inlineerror.png`):**

| Cell    | Axes                                                    | What it shows                                                                                                                                                                                  |
| ------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| default | Form=panel, Severity=error, Retry=shown, Details=closed | "Couldn't load users — store unavailable." with `Retry` (E42-D03 U-6, `E42-D03.md:339`); an in-panel load failure, so `live="polite"` is set over the error default (§6 H14; the Polite story) |
| warning | Severity=warning                                        | the `warning` glyph and the host's sentence, `role="status"`                                                                                                                                   |
| inline  | Form=inline, Retry=none                                 | the refusal at the point of action: "Not sent — your access changed. {reason}" (D09 `inflight.not_sent`, `E09-D09.md:270`), assertive once                                                     |
| details | Details=open                                            | "Technical details" open: the code and the correlation id, selectable, with a CMP-033 copy button                                                                                              |
| summary | (sample)                                                | E30-D02 D16's error summary (`E30-D02.md:141`): the inline form with a heading and links to the fields, focused after a failed submit                                                          |

**Not drawn:** interactive states (its buttons are CMP-001's); loading and empty (other components).

**Anatomy** (compact / comfortable: spacing and button heights only):

| Part    | Tokens                                                                                                                                     |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| panel   | CMP-026's block: a column at most 480 px, centred, padding `space.inset.xl`, gaps `space.stack.sm` and `space.stack.md`                    |
| glyph   | CMP-019 `danger` (error) or `warning` (warning) in `color.status.danger.strong` / `.warning.strong`; panel `size="lg"`, inline `size.icon` |
| message | `type.ui.body`, `color.text.primary`; never a raw exchange or server payload                                                               |
| actions | `Retry` and `action` CMP-001 `secondary`; "Technical details" a CMP-001 `ghost` with `chevron-down`; `space.inset.sm` apart                |
| details | `type.num.sm`, `color.text.secondary` on `color.surface.raised`, `radius.control`, padding `space.inset.sm`; selectable; CMP-033 copies it |
| inline  | one row: glyph, message, then an inline `Retry`; gap `space.inset.xs`; no fill                                                             |

**Keyboard:** none of its own; `Retry` and the action are buttons (APG Button); "Technical details" is an APG Disclosure
(`Enter` / `Space` toggle, `aria-expanded`). The submit summary takes focus because the host moves it there
(`tabindex="-1"`, E30-D02 D16). **Accessible name and role:**

| Element           | Role                                                                           | Name                | ARIA                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------ | ------------------- | ------------------------------------------------------------------------------------------------------- |
| surface           | alert (error) or status (warning) by default; `live` overrides; none for `off` | —                   | mounted with its host, its text inserted when the failure begins (conventions 33); `aria-atomic="true"` |
| glyph             | none                                                                           | —                   | `aria-hidden="true"`                                                                                    |
| Technical details | button                                                                         | "Technical details" | `aria-expanded`, `aria-controls`; the details are never in the live region                              |

**Motion:** none: it appears at once. **Live region:** once per failure: an error assertive, a warning polite; an
in-panel load failure polite (slice 3 G17); `off` when another node already announced it (§6 H14). **T2 and not T2:** an
error is an outcome, never T2 (conventions 37); a gated `action` takes CMP-001's T2 form through CMP-079 (conventions
36). **Hit target:** the buttons', at least 24 px. **Resize & overflow:** wraps; the details scroll inside their box and
never truncate. **Forced colors:** CanvasText text, the glyph `currentColor`, the details box a 1 px CanvasText border.

**Catalogue alignment** (`15:293-300`): Props gains `form?`, `live?` and `action?` (H14); a States line (panel and
inline, error and warning, details closed and open); A11y appends the `live` default and overrides, the mount rule,
"the message never carries raw exchange or server text" and the disclosure; Tokens become the anatomy's (the `.strong`
glyphs for the bare `color.status.warning/danger`); Storybook adds Inline and Polite.

### CMP-028 · Callout / Banner

**Catalogue (verbatim, `15:305`, `15:307`):**

- **Props**: `tone: "info"|"warning"|"danger"|"success"|"connection-reconnecting"|"connection-disconnected"` · `icon?` · `dismissible?` · `retry?: {label,onClick}`.
- **A11y**: `role="status"` (info/success/connection-reconnecting) or `role="alert"` (warning/danger/connection-disconnected).

| Axis        | Values                                                                           | Default |
| ----------- | -------------------------------------------------------------------------------- | ------- |
| Tone        | info, warning, danger, success, connection-reconnecting, connection-disconnected | info    |
| Placement   | inline, band                                                                     | inline  |
| Dismissible | false, true                                                                      | false   |
| Action      | none, retry                                                                      | none    |

**Variants × States (8 cells; boards PENDING: `CMP-028 · Callout`, export `img/CMP-028-callout-banner.png`):**

| Cell         | Axes                                       | What it shows                                                                                                                                                                                               |
| ------------ | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| default      | Tone=info, Placement=inline                | "Reconnected — backfilling history" · "Recorded coverage catching up: 00:41 remaining." with a CMP-023 (E08-D03 §3, `E08-D03.md:77`)                                                                        |
| warning      | Tone=warning                               | "Degraded — some data feeds are stale" · "Book and tape are live; 1 of 4 topics stale 6s. Recent trades may lag.", with `live="polite"` (E08-D03 §3; §6 H15)                                                |
| danger       | Tone=danger                                | "Trading locked: daily loss limit −2 % reached at 13:41 UTC." (`14:1629` SCR-073); `role="alert"` once; not dismissible while it holds                                                                      |
| success      | Tone=success                               | "Accepted — stop 63,900.0 held by the exchange · exchange id ends …5f60" (E30-D02, `E30-D02.md:280`)                                                                                                        |
| reconnecting | Tone=connection-reconnecting               | "Connection unstable — last data Ns ago", one polite "Connection unstable" (E08-D11 D4, `E08-D11.md:61`)                                                                                                    |
| disconnected | Tone=connection-disconnected, Action=retry | "Disconnected — reconnecting (attempt 3, next in 4 s)" · "Last data 00:12 ago. Trading is disabled while offline." · "Your exchange-side stop-losses are unaffected." · `Retry now` · `Details` (`14:2875`) |
| band         | Placement=band                             | D09's "Your access changed just now." (`E09-D09.md:265`) in the band slot, `live="off"`, dismissible once read                                                                                              |
| dismissible  | Dismissible=true                           | "Reconnected" · "While you were offline: 1 order filled, 1 stop moved by a rule." with its close button (E08-D03 §3, `E08-D03.md:79`)                                                                       |

**Not drawn:** interactive states (its buttons are CMP-001's, CMP-002's); empty and error (CMP-026, CMP-027).

**Anatomy** (compact / comfortable: spacing and button heights only):

| Part    | Tokens                                                                                                                                                   |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| fill    | `color.status.{tone}.subtle`; both connection tones on `color.status.danger.subtle` (§6 H5)                                                              |
| edge    | a 2 px `border.thick` start edge in `color.status.{tone}.strong`                                                                                         |
| glyph   | CMP-019 at `size.icon` in `.strong`: `info`, `check` (success), `warning`, `danger`, `disconnected` (both connection tones, until E17-D02 CR-8's glyphs) |
| title   | `type.ui.body-strong`, `color.text.primary`                                                                                                              |
| body    | `type.ui.body`, `color.text.secondary`; a connection tone's `details` sentence under it                                                                  |
| actions | CMP-001 `secondary` (`Retry now`), CMP-021 links, `space.inset.sm` apart; the dismiss a trailing CMP-002 `ghost` `close`, "Dismiss {title}"              |
| box     | inline: `radius.card`, padding `space.inset.sm` block and `space.inset.md` inline, glyph-to-text `space.inset.sm`; band: full width, square              |

**Keyboard:** none of its own: its buttons are in the Tab order (APG Button); `Details` is an APG Disclosure that moves
focus to its first control and returns it on `Esc` (E17-D02, `E17-D02.md:193`). `Esc` never dismisses a lockout, freeze,
disconnect or protection banner (E40 a11y KM-6, `e40-alerts-a11y-review.md:72`). **Accessible name and role:**

| Element | Role                                                                                                                                  | Name              | ARIA                                                                                 |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------ |
| callout | status (info, success, connection-reconnecting) or alert (warning, danger, connection-disconnected); `live` overrides; none for `off` | —                 | mounted with its host, the text inserted when the state begins; `aria-atomic="true"` |
| glyph   | none                                                                                                                                  | —                 | `aria-hidden="true"`                                                                 |
| dismiss | button                                                                                                                                | "Dismiss {title}" | —                                                                                    |

**Motion:** content at 0 ms in both modes; a dismissal fades over `motion.duration.fast` (E08-D11, `15:311`);
motion-reduce — instant. **Live region:** once per state entry; a connection callout once per Disconnected episode, a
flap collapsing into one polite "Connection unstable" (E08-D11 D4); ages and countdowns `aria-live="off"`; never raw
exchange error text (`15:306`). **T2 and not T2:** none of its own (a container; conventions 36); the banner reports a
state that may be another control's reason. **Hit target:** its buttons, at least 24 px. **Resize & overflow:** wraps;
the actions wrap under the body. **Forced colors:** the fill drops; a 1 px CanvasText border keeps the box, the edge
turns CanvasText, and the glyph and the title carry the tone (conventions 38).

**Catalogue alignment** (`15:302-311`): Purpose reads CMP-074 for "CMP-078"; Props gains `placement?` and `live?` (H15);
a States line (six tones, inline and band, dismissible); A11y appends the `live` override and "each state entry is
announced once"; Tokens become the anatomy's (for `color.callout.*` and the `color.data-confidence.*.indicator` accents,
H5), and the E08-D04 paragraph's two accents are qualified to match: they stay on `color.surface.*`, and on the
callout's fill the edge and the glyph bind `color.status.danger.strong` (H5; E17-D02 C21, `E17-D02.md:443`); Storybook
adds Band and LivePolite. Held: the disclosure (H15 (3)).

### CMP-029 · Skeleton-Chart placeholder

**Catalogue (verbatim, `15:316-317`):**

- **Props**: `paneCount?: number`.
- **A11y**: `aria-hidden`, parent panel carries `aria-busy="true"`.

| Axis   | Values          | Default |
| ------ | --------------- | ------- |
| Panes  | 1, 3            | 1       |
| Motion | shimmer, static | shimmer |

**Variants × States (3 cells; boards PENDING: `CMP-029 · Skeleton-Chart placeholder`, export
`img/CMP-029-skeleton-chart.png`):** **default** (Panes=1, Motion=shimmer: the candle silhouette and the axis blocks,
with the host's CMP-038 "Loading 5,000 bars…" centred over it, outside the hidden node — `E11-D02.md:407`,
`E11-D04.md:321`); **Panes=3** (a price pane over two sub-panes, divided by the host's pane rules); **Motion=static**
(the reduce look and the look after the 5 s stop). **Not drawn:** every interactive state (it is hidden and inert);
empty and error (CMP-026, CMP-027 in the pane).

**Anatomy:** the pane is the host's size on `color.surface.canvas`; candle bodies, wicks and the price and time axis
label blocks are `color.surface.hover` (1.24:1 on canvas, decorative), in illustrative geometry (§5.1); the shimmer is
CMP-015's (§6 H3). Density changes nothing in it. **Keyboard:** none.

**Accessible name and role:**

| Element      | Role   | Name             | ARIA                                                                              |
| ------------ | ------ | ---------------- | --------------------------------------------------------------------------------- |
| placeholder  | none   | —                | `aria-hidden="true"`                                                              |
| chart region | region | the chart's name | `aria-busy="true"`; the host's CMP-038 words sit over it, outside the hidden node |

**Motion:** as CMP-015 — the 1,200 ms sweep stopped at 5 s; static under reduce (`14:710` "static under reduced
motion"). **Live region:** none of its own. **T2:** none. **Hit target:** none. **Resize & overflow:** fills its pane;
the number of candles follows the width. **Forced colors:** the blocks drop out; the host's words carry the wait.

**Catalogue alignment** (`15:313-320`): a States line (shimmer, stopped at 5 s; static under reduce and after the stop);
A11y appends that the host's CMP-038 words sit over it, outside the hidden node; Tokens: `color.surface.hover` (for
`color.surface.skeleton`), `color.surface.canvas`, CMP-015's sweep; Storybook adds Static.

### CMP-038 · InlineSpinnerText

**Catalogue (verbatim, `15:399-400`):**

- **Props**: `label: string`.
- **A11y**: single `role="status"` wrapping both icon and text (avoids double-announcement bug class).

| Axis   | Values        | Default |
| ------ | ------------- | ------- |
| Phase  | waiting, slow | waiting |
| Cancel | none, offered | none    |

**Variants × States (3 cells; boards PENDING: `CMP-038 · InlineSpinnerText`, export
`img/CMP-038-inlinespinnertext.png`):** **default** (Phase=waiting: "Loading positions", slice 1 CMP-014's example);
**slow** (Phase=slow, Cancel=none: an order submit at 5 s, "Checking with the exchange…", still busy, no Cancel — slice
1 D15); **cancellable** (Cancel=offered: a load at 5 s, "Still loading positions…" with `Cancel`). **Not drawn:** hover,
focus-visible, active and disabled (not interactive; `Cancel` is CMP-001's); empty and error (the host's outcome
replaces it).

**Anatomy:** a row with gap `space.inset.xs`: CMP-014 `sm` (`size.icon`, nested, its arc `color.action.primary.default`,
3.09:1 or more on every host surface, slice 1 CMP-014), then the text in `type.ui.body`, `color.text.secondary`;
`Cancel` a CMP-001 `ghost` `sm` after it, `space.inset.sm` apart (loads, exports and replays only). Density changes only
`Cancel`'s height. **Keyboard:** none of its own; `Cancel` is a button in the Tab order after the busy control (slice 1
CMP-014). **Accessible name and role:**

| Element   | Role   | Name                     | ARIA                                                                                         |
| --------- | ------ | ------------------------ | -------------------------------------------------------------------------------------------- |
| container | status | —                        | mounted empty with its host, the text inserted when the wait begins (conventions 33); atomic |
| spinner   | none   | —                        | `aria-hidden="true"` (slice 1 C9)                                                            |
| Cancel    | button | `cancelLabel` ("Cancel") | follows the text in the Tab order; never steals focus                                        |

**Motion:** CMP-014's pair: rotation for as long as the request keeps its host busy, no cap; under reduce, slice 1 D15's
colour cross-fade. **Live region:** the label once at the start, the slow text once at 5 s; nothing per second, no
elapsed counter; completion is the host's (§6 H29). **T2 and not T2:** busy, never T2 (conventions 37); `Cancel` is
never offered on an order submit: its retries reuse the `orderLinkId` (C-2.10). **Hit target:** `Cancel` at least 24 px.
**Resize & overflow:** the text wraps after the spinner. **Forced colors:** CanvasText text, the arc `currentColor`.

**Catalogue alignment** (`15:396-403`): Props gains `slowLabel?`, `onCancel?` and `cancelLabel?` (H29); a States line
(waiting, slow, with Cancel); A11y appends the mount rule and "the label is announced once and the slow text once, with
no time cap and no elapsed counter"; Tokens become the anatomy's (for "inherits CMP-014/CMP-020"); Storybook adds
SlowPath and SlowPathWithCancel.

### CMP-041 · Menu

**Catalogue (verbatim, `15:431-432`):**

- **Props**: `trigger: ReactNode` · `items: {label,icon?,shortcut?,onSelect,danger?,disabled?}[]` · `onOpenChange`.
- **A11y**: WAI-ARIA "Menu Button" pattern, arrow-key nav, type-ahead, `Esc` closes + returns focus, danger items get `aria-describedby` "destructive action" hint.

| Axis      | Values                                                                                          | Default |
| --------- | ----------------------------------------------------------------------------------------------- | ------- |
| Trigger   | button, context                                                                                 | button  |
| ItemState | default, hover, focus-visible, active, checked, disabled, disabled-with-reason, danger, submenu | default |

**Variants × States (10 cells; each draws the open menu with the named item; boards PENDING: `CMP-041 · Menu`, export
`img/CMP-041-menu.png`):**

| Cell                 | Axes                              | What it shows                                                                                                                                                                                      |
| -------------------- | --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| default              | Trigger=button, ItemState=default | E14-D02's tree-row menu (`E14-D02.md:75`): Duplicate · Reveal on chart · Move up · Move down, a separator, Remove with its `Del` shortcut                                                          |
| hover                | ItemState=hover                   | the pointer on "Reveal on chart": `color.surface.hover`, no ring (slice 1 conventions 2, D17)                                                                                                      |
| focus-visible        | ItemState=focus-visible           | "Reveal on chart" on `color.surface.hover` with the inset ring (§6 H8)                                                                                                                             |
| active               | ItemState=active                  | a pointer press: `color.surface.selected`                                                                                                                                                          |
| checked              | ItemState=checked                 | E11-D03's price-scale menu (`E11-D03.md:125`): the "Scale mode" radios and the Lock, Invert, Merge and Scale price only checkboxes, grouped, the `check` marking the chosen                        |
| disabled             | ItemState=disabled                | a plain-disabled item at `opacity.disabled` (unavailable to everyone in this state)                                                                                                                |
| disabled-with-reason | ItemState=disabled-with-reason    | SCR-063's "Edit risk caps" for a manager, through CMP-079: the `lock`, the full label in `color.text.tertiary`, "Only the owner can change account settings." as its second line (`E09-D09.md:76`) |
| danger               | ItemState=danger                  | Remove in the last group: its glyph in `color.status.danger.strong`, its label `color.text.primary` (§6 H16)                                                                                       |
| submenu              | ItemState=submenu                 | a row menu's Snooze open on its presets, 15 m / 1 h / until tomorrow (E40 a11y KM-5, `e40-alerts-a11y-review.md:71`)                                                                               |
| context              | Trigger=context                   | opened at the pointer on a grid row, or by `Shift+F10` on it (slice 3 CMP-049; D09 §9.3)                                                                                                           |

**Not drawn:** closed (the trigger alone); loading, empty and error (its items are known; a command list is CMP-059).

**Anatomy** (compact / comfortable: only the item height changes):

| Part         | Tokens                                                                                                                                                            |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| surface      | CMP-017's (conventions 30); padding-block `space.inset.xs`; at least as wide as its trigger; capped at the viewport edge, then it scrolls                         |
| item         | min-height `size.row.height` 24 / 32; padding-inline `space.inset.sm`; gap `space.inset.xs`; label `type.ui.body`, `color.text.primary`                           |
| leading slot | `size.icon`: the item's glyph in `color.text.secondary`, the `check` in `color.text.primary` on a checked item, the `lock` in `color.text.tertiary` on a T2 item  |
| trailing     | a shortcut in `type.num.sm`, `color.text.tertiary` (CMP-022 Kbd once slice 5 ships); a submenu's `chevron-right` in `color.text.secondary`                        |
| second line  | a T2 reason or a `description`: `type.ui.caption`, `color.text.secondary`                                                                                         |
| item states  | hover and focus `color.surface.hover`; focus-visible adds the inset ring (§6 H8); active `color.surface.selected`; disabled `opacity.disabled`; T2 conventions 36 |
| group        | label `type.ui.caption`, `color.text.tertiary`, not focusable; separator a 1 px `color.border.default` rule with `space.inset.xs` above and below                 |
| danger       | the last group; its glyph `color.status.danger.strong`, its label `color.text.primary`                                                                            |

**Keyboard** (WAI-ARIA APG Menu Button and Menu):

| Keys                                   | Action                                                                                                                    |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Enter / Space / ↓ on the trigger       | Opens the menu on its first item; `↑` opens it on its last.                                                               |
| ↓ / ↑, Home / End                      | Next / previous item, wrapping; first / last. Separators and group labels are skipped; disabled and T2 items are reached. |
| a printable character                  | Type-ahead: the next item whose label starts with the typed text.                                                         |
| Enter                                  | Activates the item and closes the menu; focus returns to the trigger, or moves into the dialog the item opens.            |
| Space                                  | Activates an action item; toggles a checkbox or radio item and keeps the menu open.                                       |
| → (or Enter) on a submenu item; ←, Esc | Opens the submenu on its first item; closes it, focus back on its parent item.                                            |
| Esc                                    | Closes the menu; focus returns to the trigger, or to the element a context menu opened from.                              |
| Tab / Shift+Tab                        | Closes every open menu and moves focus on from the trigger.                                                               |
| Enter / Space on a disabled or T2 item | Nothing happens; a T2 item re-shows its reason with one polite announcement (D09 §9.3).                                   |
| Shift+F10, the Menu key, a right-click | Opens a context menu on the focused element or at the pointer.                                                            |

**Accessible name and role:**

| Element       | Role                                        | Name                                                         | ARIA                                                                                                                                                                  |
| ------------- | ------------------------------------------- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| trigger       | button                                      | its label                                                    | `aria-haspopup="menu"`, `aria-expanded`, `aria-controls`                                                                                                              |
| menu          | menu                                        | the trigger (`aria-labelledby`); a context menu `aria-label` | —                                                                                                                                                                     |
| item          | menuitem, menuitemcheckbox or menuitemradio | its label                                                    | `aria-checked` on checkable items; `aria-keyshortcuts` for a shortcut; a submenu item `aria-haspopup="menu"` + `aria-expanded`; its glyphs and key text `aria-hidden` |
| T2 item       | its kind                                    | its full label                                               | `aria-disabled="true"`, `aria-describedby` → its second line, in the DOM at mount                                                                                     |
| disabled item | its kind                                    | its label                                                    | `aria-disabled="true"`: focusable, never activated (APG)                                                                                                              |
| danger item   | menuitem                                    | its label                                                    | `aria-describedby` → a visually hidden "Destructive action" (`15:432`)                                                                                                |
| group         | group, with a `separator` between groups    | its label                                                    | —                                                                                                                                                                     |

**Focus:** conventions 32 (the first item; back to the trigger). **Motion:** it opens at once (it takes focus,
conventions 35); it closes with a `motion.duration.fast` fade; submenus switch at once; motion-reduce — instant. **Live
region:** none of its own; a T2 item's refused key speaks once through the shell's polite region. **T2 and not T2:** per
item, rendering 2a with the reason as the second line, the step-3 leg through CMP-079 (conventions 36; D09 §8,
`E09-D09.md:208`; slice 3 G21); a plain disabled item is unavailability, not a gate (conventions 37). **Hit target:**
every item is `size.row.height` tall and the menu's full width. **Resize & overflow:** items grow taller with text;
labels and second lines wrap and never truncate; the menu caps its height and scrolls. **Forced colors:** the focused
item a Highlight fill with HighlightText (`forced-color-adjust: none`); separators CanvasText; a T2 item keeps its lock,
label and reason in CanvasText (HighlightText while focused), never GrayText (slice 3 conventions 29).

**Catalogue alignment** (`15:428-435`): Props applies E11-D03 D03-CR-1 (H16); a States line (the item states, T2 per D09
§2.2 through CMP-079, danger last); A11y appends Enter and Space, Tab closing all, disabled and T2 items reached and
never activated, and the danger rule; Tokens become the anatomy's (`elevation.popover` for `elevation.3`, the inset ring
of H8); Storybook adds Checkable, DisabledWithReason and Danger.

### CMP-043 · Dialog

**Catalogue (verbatim, `15:449-450`):**

- **Props**: `open` · `onOpenChange` · `title` · `description?` · `size` · `children` · `initialFocusRef?`.
- **A11y**: `role="dialog"` `aria-modal="true"` `aria-labelledby`/`aria-describedby`, focus-trap, `Esc` closes (unless a destructive-confirm variant disables Esc-as-cancel-shortcut deliberately, documented per instance), focus returns to trigger on close.

| Axis     | Values                | Default |
| -------- | --------------------- | ------- |
| Size     | sm, md, lg            | md      |
| Role     | dialog, alertdialog   | dialog  |
| Overflow | fits, scrolls         | fits    |
| State    | default, busy, reflow | default |

**Variants × States (7 cells, each over the scrim; boards PENDING: `CMP-043 · Dialog`, export
`img/CMP-043-dialog-modal.png`):**

| Cell        | Axes                                               | What it shows                                                                                                                                              |
| ----------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| default     | Size=md, Role=dialog, Overflow=fits, State=default | a title, a description, two CMP-040 fields, `Cancel` and the primary action; focus on the first field                                                      |
| sm          | Size=sm                                            | E11-D03's "Go to date" (420 px, `E11-D03.md:288`)                                                                                                          |
| lg          | Size=lg                                            | E42-D03's "Invite a user" (`size` Large, `E42-D03.md:420`)                                                                                                 |
| alertdialog | Role=alertdialog                                   | E14-D02's "Delete 497 drawings on BTCUSDT? 3 locked drawings stay. One undo." with `Cancel` (focused) and `Delete 497` (`E14-D02.md:363`); no close button |
| scrolls     | Overflow=scrolls                                   | the card at 80 % of the viewport: the body scrolls between a fixed header and footer (E39-D03 §4)                                                          |
| busy        | State=busy                                         | after the primary press: CMP-001 `loading`, the fields `readOnly`; `Esc` closes the view and cancels nothing (§6 H22)                                      |
| reflow      | State=reflow                                       | 200 % zoom on the 1280 × 800 frame: the dialog fills the viewport, header and footer sticky, the body scrolling (conventions 39)                           |

**Not drawn:** closed; hover, active, disabled (not a control; never gated); error (CMP-027 inline in the body).

**Anatomy** (compact / comfortable: the nested controls' heights only):

| Part   | Tokens                                                                                                                                                                                                                               |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| scrim  | conventions 31: `palette.black` at `opacity.scrim` (§6 H1), at brief §2.5's step 5 (`elevation.scrim`'s layer)                                                                                                                       |
| card   | `color.surface.overlay`, `elevation.dialog`, `radius.dialog`, a 1 px `color.border.default` edge; padding `space.dialog.padding`; block gap `space.stack.md`; at most 420 / 560 / 960 px wide (§6 H17) and 80 % of the viewport tall |
| header | title `type.ui.heading-sm`, `color.text.primary` (`h2`); description `type.ui.body`, `color.text.secondary`; a `dialog` adds CMP-002 `ghost` `close` ("Close {title}")                                                               |
| body   | the host's content; it scrolls when the card is capped                                                                                                                                                                               |
| footer | a CMP-001 row, end-aligned, `space.inset.sm` apart: `Cancel` (`secondary`) first, the primary or danger action last                                                                                                                  |

**Keyboard** (WAI-ARIA APG Dialog (Modal); Alert Dialog for `role="alertdialog"`):

| Keys                         | Action                                                                                                           |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| on open                      | Focus to `initialFocusRef`, else the first field, else the heading; an alertdialog to `Cancel` (conventions 32). |
| Tab / Shift+Tab              | Cycles inside the card (the trap).                                                                               |
| Enter in a single-line field | The form's primary action (implicit submission); never a destructive confirm (CMP-044).                          |
| Esc                          | Cancel: closes, focus back to the trigger; while busy, closes the view and cancels nothing (§6 H22).             |
| a press on the scrim         | Cancel for a `dialog`; nothing for an `alertdialog` (conventions 31).                                            |

**Accessible name and role:**

| Element | Role                           | Name                          | ARIA                                                                                                                                                           |
| ------- | ------------------------------ | ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| card    | dialog or alertdialog (`role`) | the title (`aria-labelledby`) | `aria-modal="true"`; `aria-describedby` → the description                                                                                                      |
| scrim   | none                           | —                             | `aria-hidden="true"`; the page under it `inert`, the TopBar and the shell regions excepted (§6 H23); CMP-212's toasts painted above it, inert (conventions 31) |
| close   | button                         | "Close {title}"               | `role="dialog"` only; the drawer's name form (CMP-046)                                                                                                         |

**Focus:** conventions 32: initial focus, the trap, the return to the trigger or the host's fallback. **Motion:** §6
H21: the scrim fades 0 → 0.6 over `motion.duration.normal` / `standard` and the card is a cut at frame 0 (D08 D2); the
exit fades over `fast` / `accelerate` with `pointer-events: none`; motion-reduce — instant. **Live region:** none on
open: the dialog is read as focus enters it (an alertdialog's message with it); results go to the host's toast or an
inline CMP-027. **T2 and not T2:** none of its own (a container); a gated control inside takes its own T2 (conventions
36; §6 H30); a busy primary action is busy, not T2. **Hit target:** its controls'. **Resize & overflow:**
conventions 39. **Forced colors:** conventions 38.

**Catalogue alignment** (`15:446-453`): Props gains the `size` values and `role?` (H17); a States line (default,
scrolls, busy, reflow); A11y rewrites the `Esc` clause (H22) and gains the scrim, the inert page (H23) with CMP-212's
toasts above the scrim, inert and their timers paused (conventions 31), the initial focus, the close button's name
"Close {title}" and the fallback return; Tokens become the anatomy's (`elevation.dialog` for `elevation.4`,
`radius.dialog` for `radius.lg`, the scrim's stand-in of H1); Storybook drops NoEscClose and adds AlertDialog, Scrolling
and Busy.

### CMP-044 · ConfirmDialog

**Catalogue (verbatim, `15:458-459`):**

- **Props**: `title` · `message` · `confirmLabel` · `cancelLabel` · `variant: "standard"|"typed"|"hold"` · `typedConfirmValue?: string` (must match, e.g. symbol name) · `holdDurationMs?` (with discrete keyboard fallback per `05-accessibility-standard.md` §3.1.4) · `onConfirm` · `onCancel`.
- **A11y**: `variant="hold"` always ships a keyboard-operable discrete alternative (press-and-hold OR two sequential `Enter` presses within a visible countdown) — never a mouse-only/timing-only gate.

| Axis    | Values                                                       | Default  |
| ------- | ------------------------------------------------------------ | -------- |
| Variant | standard, typed, hold                                        | standard |
| State   | default, match, holding, armed, busy, partial-failure, gated | default  |

**Variants × States (9 cells, each over the scrim; boards PENDING: `CMP-044 · ConfirmDialog`, export
`img/CMP-044-confirmdialog.png`):**

| Cell            | Axes                            | What it shows                                                                                                                                                                                                                                                                               |
| --------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| default         | Variant=standard, State=default | SCR-072's "Freeze sub_001?" (E39-D03 §4.1, `E39-D03.md:106`): the subtitle, the "What this does" group, `Cancel` (focused) and `Freeze sub_001 — cancel 3 working orders`                                                                                                                   |
| typed           | Variant=typed                   | E42-D02's rung 3, deleting user alex (`E42-D02.md:249`): the field for the username empty, the confirm natively disabled                                                                                                                                                                    |
| typed · match   | Variant=typed, State=match      | the field matching exactly; the confirm enabled                                                                                                                                                                                                                                             |
| hold            | Variant=hold                    | the confirm naming the effect, its ring at 0 % and "0 %"                                                                                                                                                                                                                                    |
| holding         | Variant=hold, State=holding     | a pointer hold: the ring at 50 % and "50 %" (`E39-D03.md:118`)                                                                                                                                                                                                                              |
| armed           | Variant=hold, State=armed       | the keyboard path after the first press: "Press again to flatten 4 positions — all accounts, LIVE + DEMO", the 5 s window (`E39-D03.md:119`)                                                                                                                                                |
| busy            | State=busy                      | after Confirm: CMP-001 `loading`, the inputs `readOnly`; SCR-072's per-account progress is the host's (`14:1617`)                                                                                                                                                                           |
| partial failure | State=partial-failure           | SCR-072's "partial failure with retry" (`14:1617`): a CMP-027 inline error with `Retry` above the footer                                                                                                                                                                                    |
| gated           | State=gated                     | the leg left mid-dialog: Confirm in CMP-001's T2 form through CMP-079 — the `lock` leading its full label in `color.text.tertiary`, the fill `color.surface.raised` with a `color.border.default` hairline — and "Your role can't use the kill switch." under the footer (D09 §3.2; §6 H30) |

**Not drawn:** a typed mismatch (the empty cell's look); hover and active (CMP-001's); a disabled dialog (never gated).

**Anatomy** (on CMP-043, `role="alertdialog"`, `size` md — SCR-072's 560 px card):

| Part         | Tokens                                                                                                                                                                                                                                            |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| title        | the verb and the object, as a question ("Freeze sub_001?"); CMP-043's header                                                                                                                                                                      |
| consequences | `role="group"` "What this does": `color.surface.raised`, `radius.card`, padding `space.inset.md`; sentences `type.ui.body`, `color.text.primary`; the irreversible line `type.ui.body-strong` (E39-D03 §4)                                        |
| typed field  | CMP-040 + CMP-007; its label names the token; `type.num.base` when the token is an id                                                                                                                                                             |
| confirm      | CMP-001 `danger` (`color.text.on-action` on `color.status.danger.default`, §6 H24), labelled with the effect, never "Confirm"; a gate that only switches context (SCR-074's Demo → Live) uses `primary`; gated (§6 H30), conventions 36's T2 look |
| hold ring    | E39-D03 §5 (`E39-D03.md:118`): a 3 px ring, `color.status.danger.default` over a `color.border.strong` track, beside its percentage in `type.num.sm`, `color.text.secondary`                                                                      |
| cancel       | CMP-001 `secondary`, first in the footer, the initial focus                                                                                                                                                                                       |

**Keyboard** (WAI-ARIA APG Alert Dialog):

| Keys                                | Action                                                                                                                                                                                                                                                                                                 |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| on open                             | Focus on `Cancel`; nothing is sent until Confirm (E39-D03 `:216`).                                                                                                                                                                                                                                     |
| Tab / Shift+Tab                     | The body's controls, `Cancel`, Confirm, cycling (the trap).                                                                                                                                                                                                                                            |
| Enter / Space on Confirm (standard) | Confirms, except in the first 400 ms after the dialog opened; key repeats are ignored (§6 H24).                                                                                                                                                                                                        |
| typing in the typed field           | Confirm enables when the text matches exactly; `Enter` in the field never confirms.                                                                                                                                                                                                                    |
| hold, pointer                       | Press and hold Confirm for `holdDurationMs`; releasing early resets the ring.                                                                                                                                                                                                                          |
| hold, keyboard                      | Hold `Enter` for `holdDurationMs`, or two non-repeat presses of `Enter` or `Space` at least 250 ms apart within 5 s (the first arms); `Space` has no hold path (it activates on `keyup`), so a held `Space` is one press; `Esc` or blur disarms (§6 H25; E39-D03 §5, `E39-D03.md:123`, `:129`–`:130`). |
| Esc                                 | Cancel before the send; focus returns to the trigger (§6 H22).                                                                                                                                                                                                                                         |
| Enter / Space on a T2 Confirm       | Nothing; the reason is re-shown with one polite announcement (D09 §9.3).                                                                                                                                                                                                                               |

**Accessible name and role:**

| Element      | Role        | Name                                                                               | ARIA                                                                                                        |
| ------------ | ----------- | ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| dialog       | alertdialog | the title                                                                          | `aria-modal="true"`; `aria-describedby` → the consequences                                                  |
| consequences | group       | "What this does"                                                                   | —                                                                                                           |
| confirm      | button      | the effect ("Freeze sub_001 — cancel 3 working orders"); armed, "Press again to …" | native `disabled` until a typed match (validity); `aria-disabled` + `aria-describedby` → the reason when T2 |
| hold ring    | progressbar | the Confirm's label (`aria-labelledby`)                                            | `aria-valuenow` 0–100, drawn at up to 10 updates a second, its text twin at up to 2                         |
| typed field  | textbox     | its label                                                                          | —                                                                                                           |

**Focus:** `Cancel` first; after a confirmed send the dialog stays open and busy until the outcome, then closes with the
result in the host's toast (E39-D03 S20) and focus back on the trigger. **Motion:** CMP-043's (§6 H21); the hold ring
fills over `holdDurationMs`; motion-reduce — no sweep, the percentage text alone (`E39-D03.md:239`). **Live region:** a
Confirm label change and the armed name are polite, once (E39-D03 D13); the result is the host's polite toast, a failed
leg an assertive CMP-027 once; a Confirm gated mid-dialog speaks once, assertively, when it held focus (D09 §4.4). **T2
and not T2:** the nested Confirm takes CMP-001's T2 form in place through CMP-079 (§6 H30; conventions 36; 2a, the
host's reason under the footer); a scope option gated inside the body is CMP-006's T2 (E39-D03 `confirm-manager`). Not
T2: a typed mismatch (validity: native `disabled`), the summary still loading (availability), a sent confirm (busy).
**Hit target:** `Cancel` and Confirm at least 24 px; E39-D03's Confirm at least 240 px wide (host data). **Resize &
overflow:** conventions 39; a consequence phrase never wraps mid-phrase ("Open positions are NOT closed", E39-D03).
**Forced colors:** Confirm as CMP-001 (the danger meaning in its words); the ring Highlight on a CanvasText track, its
text twin carrying the progress.

**Catalogue alignment** (`15:455-462`): Props gains `consequences?` and `busy?` and states the label, typed-token and
hold rules (H24, H25, H2); a States line (the nine cells; the gated Confirm through CMP-079 with the `lock`, the
tertiary label and the `color.surface.raised` fill, D09 §2.2); A11y appends `role="alertdialog"`, focus on `Cancel`, the
400 ms guard, ignored repeats, the typed field's `Enter` rule, the hold paths (`Space` arms, never holds) and their
reduce twin, and H30's T2 Confirm; Tokens become the anatomy's (for `color.status.danger` and `elevation.4`); Storybook
adds Busy, PartialFailure and ConfirmGated.

### CMP-045 · Toast

**Catalogue (verbatim, `15:467-468`):**

- **Props**: `title` · `description?` · `tone` · `action?: {label,onClick}` · `durationMs?` · `dismissible?`.
- **A11y**: `role="status"` (polite) default, `role="alert"` (assertive) for `tone="danger"`; never auto-dismisses content the user hasn't had a chance to perceive — pauses on hover/focus, and provides a persistent-log fallback (Notification Center) so nothing is lost if missed (WCAG 2.2.1 no timing loss of info).

| Axis     | Values                         | Default |
| -------- | ------------------------------ | ------- |
| Tone     | info, success, warning, danger | info    |
| Action   | none, actions                  | none    |
| Lifetime | timed, persistent              | timed   |
| State    | default, focused               | default |

**Variants × States (7 cells; boards PENDING: `CMP-045 · Toast`, export `img/CMP-045-toast-notification.png`):**

| Cell      | Axes                                                  | What it shows                                                                                                                                                                                                                                                     |
| --------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| default   | Tone=info, Action=none, Lifetime=timed, State=default | "Session extended. Idle timer reset. Next warning in 14:00." (D08 row 15, `E09-D08.md:114`)                                                                                                                                                                       |
| success   | Tone=success                                          | "Order accepted · id 42f" (`14:400` SCR-015)                                                                                                                                                                                                                      |
| warning   | Tone=warning, Action=actions, Lifetime=persistent     | E40-D02's fired alert (`E40-D02.md:626`): "Warning · Alert", "BTC above 65k", "Last price 65,012.5 crossed above 65,000", "BTCUSDT · 5m", `Open chart` `Snooze ▾` `Disable` `Details`                                                                             |
| danger    | Tone=danger, Lifetime=persistent                      | an order rejection with `Details`, which opens SCR-077 (`14:1691`)                                                                                                                                                                                                |
| focused   | State=focused                                         | an action holding keyboard focus: its ring, and every timer in the stack paused (annotated)                                                                                                                                                                       |
| T2 action | Action=actions                                        | a viewer's fired alert: `Snooze` and `Disable` in T2 through CMP-079 (`form="notice"`), each led by the `lock` with its full label in `color.text.tertiary`, and one reason line both point at, "Your role can't change alerts." (E40-D02 §2.9, `E40-D02.md:312`) |
| undo      | Action=actions                                        | a local undo, "EMA 21 removed. Undo" (E13-D02, `E13-D02.md:223`), and the outcome line once its window closes (§6 H27)                                                                                                                                            |

**Not drawn:** hover (behaviour); disabled (never gated whole); the stack, count and storm summary (CMP-212, CMP-165).

**Anatomy** (E40-D02 §4.2; compact / comfortable: the buttons' heights and the body's line clamp):

| Part    | Tokens                                                                                                                |
| ------- | --------------------------------------------------------------------------------------------------------------------- |
| surface | conventions 30; 360 px (§5.1); padding `space.inset.md`; rows `space.stack.sm`                                        |
| edge    | a 2 px `border.thick` start edge in `color.status.{tone}.default` (§6 H6)                                             |
| glyph   | CMP-019 at `size.icon` in `.strong`: `info`, `check`, `warning`, `danger`                                             |
| kicker  | optional: `type.ui.caption`, `color.text.secondary` — the tone's word and the kind ("Warning · Alert")                |
| title   | `type.ui.body-strong`, `color.text.primary`, one line                                                                 |
| body    | `type.ui.body`, `color.text.secondary`, at most two lines (three comfortable); the full text is in SCR-014            |
| meta    | `type.num.sm`, `color.text.tertiary`                                                                                  |
| actions | CMP-001 `secondary` and `ghost`, compact, text labels; gated, conventions 36's T2 look and one reason line under them |
| dismiss | CMP-002 `ghost` `close`, "Dismiss {title}"                                                                            |

**Keyboard** (no APG widget; its messages follow the APG Alert pattern through CMP-212's regions):

| Keys                                          | Action                                                                                                                                                                                                                                                                                                            |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tab / Shift+Tab                               | A toast never takes focus on arrival; Tab reaches the stack (CMP-212's place in the Tab order, or the palette's "Focus toasts", E40 a11y KM-5) and moves through each toast's actions and dismiss button; while a modal is open the stack is inert and its actions wait for the dialog to close (conventions 31). |
| Enter / Space                                 | Activate the focused action.                                                                                                                                                                                                                                                                                      |
| Enter / Space on a T2 action                  | Nothing changes; the reason line is re-shown and announced once, politely (D09 §9.3).                                                                                                                                                                                                                             |
| Esc on a focused toast                        | Dismisses it; focus moves to the next toast, else back to where it was before the stack (E40 a11y KM-6).                                                                                                                                                                                                          |
| hover or focus in the stack, or an open modal | Pauses every timer in it; leaving the stack, or the dialog closing, resumes them (conventions 31).                                                                                                                                                                                                                |

**Accessible name and role:**

| Element      | Role   | Name                          | ARIA                                                                                                                                    |
| ------------ | ------ | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| toast        | group  | its title (`aria-labelledby`) | an item of CMP-212's list; never a live region itself (§6 H28)                                                                          |
| announcement | —      | —                             | its sentence, written once into CMP-212's polite region (info, success, warning) or assertive region (`danger`); `politeness` overrides |
| glyph        | none   | —                             | `aria-hidden="true"`                                                                                                                    |
| dismiss      | button | "Dismiss {title}"             | never gated                                                                                                                             |
| T2 action    | button | its full label                | `aria-disabled="true"`, `aria-describedby` → the one reason line                                                                        |

**Timing** (§6 H26): by default persistent with an action, an error or a `danger` tone; otherwise the user's duration (5
/ 10 / 20 s / until dismissed); paused on hover and focus; no countdown bar; copied to SCR-014; an Undo window follows
the same setting and ends in its outcome line, never on an order cancel (§6 H27). **Motion** (E40-D02 §8,
`E40-D02.md:1232`): enter `translateY` 8 px → 0 with opacity over `motion.duration.fast` / `decelerate`; exit opacity
with `translateX` 8 px over `fast` / `accelerate`; motion-reduce — opacity only over `fast` (it needs E05-D03's
exemption; until then a cut). **T2 and not T2:** a gated action is CMP-001's T2 through CMP-079 (`form="notice"`,
conventions 36): the `lock` leads its full label, and one reason line under the actions is what every gated action's
`aria-describedby` points at (one notice, many pointers); `Enter` or `Space` on it re-shows that line with one polite
announcement; the dismiss button is never gated. Not T2: an action whose request is sending is busy; an Undo past its
window is an outcome. **Hit target:** actions at least 24 px; dismiss 24 × 24. **Resize & overflow:** 360 px or the
viewport less `space.inset.lg` each side; the body wraps to its clamp. **Forced colors:** conventions 38: the edge turns
CanvasText; the glyph and the kicker carry the tone.

**Catalogue alignment** (`15:464-471`): Props gains `kicker?`, `persistent?` and `politeness?` (E40-D02 §7.4; H28) and
the persistence rule (H26); a States line (the seven cells; a gated action through CMP-079 with the `lock`, the tertiary
label and one reason line every gated action points at, D09 §2.2); A11y rewrites the role clause (H28) and gains "A
toast never takes focus; `Esc` on a focused toast dismisses it; an order cancel offers no Undo" (H27); Tokens become the
anatomy's (`elevation.popover` for `elevation.3`; for the bare `color.status.*`); Storybook adds Persistent, Focused,
ActionGated and Undo.

### CMP-046 · Drawer

**Catalogue (verbatim, `15:476-477`):**

- **Props**: `open` · `onOpenChange` · `side: "left"|"right"` · `title` · `children`.
- **A11y**: same contract as Dialog (focus-trap, `Esc`, return focus) but non-modal option available (`modal?: boolean`) for drawers meant to coexist with chart interaction.

| Axis  | Values                   | Default |
| ----- | ------------------------ | ------- |
| Side  | right, left              | right   |
| Modal | true, false              | true    |
| State | default, loading, narrow | default |

**Variants × States (5 cells; boards PENDING: `CMP-046 · Drawer`, export `img/CMP-046-drawer-side-panel.png`):**

| Cell      | Axes                                  | What it shows                                                                                                                                                                 |
| --------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| default   | Side=right, Modal=true, State=default | SCR-103's instrument rules (E08-D06 D-14, `E08-D06.md:51`): 480 px, full height below the TopBar and the SCR-152 slot, the scrim over the workspace, sticky header and footer |
| non-modal | Modal=false                           | the alert detail drawer (E40-D02 §4.6, `E40-D02.md:724`): 480 px at `elevation.popover`, no scrim, the workspace live beside it                                               |
| left      | Side=left                             | the same anatomy mirrored                                                                                                                                                     |
| loading   | State=loading                         | `aria-busy`, CMP-015 rows in `color.surface.selected` on the overlay (§6 H3)                                                                                                  |
| narrow    | State=narrow                          | a viewport of 720 CSS px or less: the full width                                                                                                                              |

**Not drawn:** closed; interactive states (a container); error (CMP-027 in the body, E40-D02 §4.6); empty (CMP-026).

**Anatomy** (compact / comfortable: the nested controls' heights only):

| Part   | Tokens                                                                                                                                                                                   |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| panel  | `color.surface.overlay`; modal `elevation.dialog` over the scrim (E08-D06 A-3), non-modal `elevation.popover`; square; a 1 px `color.border.default` inner edge; the host's width (§5.1) |
| header | sticky; title `type.ui.heading-sm`, `color.text.primary` (`h2`); CMP-002 `ghost` `close` ("Close {title}"); padding `space.panel.padding`; a 1 px `color.border.default` rule under it   |
| body   | scrolls; padding `space.panel.padding`; gap `space.stack.md`                                                                                                                             |
| footer | optional, sticky: a CMP-001 row                                                                                                                                                          |

**Keyboard** (modal: WAI-ARIA APG Dialog (Modal); non-modal: a non-modal dialog):

| Keys                 | Action                                                                                                                           |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| on open              | Focus to `initialFocusRef`, else the heading at `tabindex="-1"`.                                                                 |
| Tab / Shift+Tab      | Modal: cycles inside. Non-modal: through it and on to the page after its opener (it follows its opener's region in focus order). |
| Esc, Close           | Closes; focus back to the opener, or the host's fallback when the opener has gone (E40-D02's bell).                              |
| a press on the scrim | Modal only: closes, as Cancel.                                                                                                   |

**Accessible name and role:**

| Element | Role   | Name                          | ARIA                             |
| ------- | ------ | ----------------------------- | -------------------------------- |
| drawer  | dialog | its title (`aria-labelledby`) | `aria-modal="true"` when modal   |
| opener  | button | its label                     | `aria-expanded`, `aria-controls` |
| close   | button | "Close {title}"               | —                                |
| scrim   | none   | —                             | modal only, as CMP-043's         |

**Focus:** conventions 32. **Motion** (§6 H21): it slides `translateX` 100 % → 0 over `motion.duration.normal` /
`decelerate`, opaque and interactive from frame 0, and closes over `fast` / `accelerate`; a modal drawer's scrim fades
with it; motion-reduce — instant (E40-D02 §8, `E40-D02.md:1237`; E08-D06 A-3). **Live region:** none on open; a host may
announce an error drawer once (SCR-077 `role="alert"` on open, `14:1691`). **T2 and not T2:** none of its own
(conventions 36); loading is busy. **Hit target:** the close button 24 × 24. **Resize & overflow:** conventions 39.
**Forced colors:** the inner edge and the header rule CanvasText; the scrim as CMP-043.

**Catalogue alignment** (`15:473-480`): Props names `modal?`, `initialFocusRef?` and the width as host data (H7); a
States line (default, loading, narrow); A11y appends the initial focus (`initialFocusRef`, else the heading), the
non-modal Tab path, the fallback return and the TopBar above a modal drawer's scrim, with CMP-212's toasts as under
CMP-043 (H23; conventions 31); Tokens become the anatomy's (for `elevation.3` and `motion.slide`, H21); Storybook adds
Loading and Narrow.

### CMP-089 · ForbiddenState

**Catalogue (verbatim, `15:876-877`):**

- **Props**: `reason?`.
- **A11y**: `h1` "Access denied", explanatory text, link home.

| Axis    | Values               | Default    |
| ------- | -------------------- | ---------- |
| Variant | never-had, withdrawn | never-had  |
| Ref     | shown, none          | shown      |
| Scope   | permission, account  | permission |

**Variants × States (4 cells; boards PENDING: `CMP-089 · ForbiddenState`, export `img/CMP-089-forbiddenstate.png`):**

| Cell      | Axes                                           | What it shows                                                                                                                                                                                                          |
| --------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| default   | Variant=never-had, Ref=shown, Scope=permission | "You don't have access to this" · "Your role can't see the journal. Ask the owner if you need it." · `Back to your workspace` · `Copy details` · "Ref {instance}" (D09 §10, `E09-D09.md:275`, `:277`)                  |
| no Ref    | Ref=none                                       | the step-3 pre-check landing: no request was sent, so no Ref line and no audit entry (D09 §5.1)                                                                                                                        |
| withdrawn | Variant=withdrawn, Ref=none                    | "Your access changed" · "Your role can't see the journal any more — this changed just now. Anything you already sent was decided by the server: check Orders. Ask the owner if this is unexpected." (`E09-D09.md:276`) |
| account   | Scope=account                                  | "This account isn't assigned to you." with the account id the client itself asked for, in mono (`scr154.echo`, `E09-D09.md:278`)                                                                                       |

**Which tier it renders:** D09's T4 route landing (§2.1 step 2: the server refused the route, `E09-D09.md:51`) and the
step-3 never-had landing a route reaches with no request sent (`14:85`). It is a route outcome: never T2, never T3 (an
admin route without `admin:read` renders CMP-090). **Not drawn:** hover, focus and disabled of the page (its link and
button are CMP-021's and CMP-001's); loading (the landing renders from the 403 or the session, with no fetch beyond D09
§5.1's one re-read).

**Anatomy:** CMP-026's block on the route's `color.surface.app`: the CMP-019 `lock` at `size="lg"` in
`color.text.tertiary` (decorative); the `h1` in `type.ui.heading-lg`, `color.text.primary`; the sentence in
`type.ui.body`, `color.text.secondary`; the account echo in `type.num.base`, `color.text.primary`;
`Back to your workspace` a CMP-021 and `Copy details` a CMP-001 `secondary`, `space.inset.sm` apart; "Ref {instance}" in
`type.num.sm`, `color.text.secondary`, selectable. **Keyboard:** none of its own: the link (APG Link) and the button
(APG Button); the Ref is selectable text.

**Accessible name and role:**

| Element         | Role                             | Name                                     | ARIA                                           |
| --------------- | -------------------------------- | ---------------------------------------- | ---------------------------------------------- |
| heading         | heading, level 1                 | D09 §10's `h1`                           | `tabindex="-1"`; it is also the document title |
| sentence, Ref   | text                             | —                                        | the Ref selectable                             |
| link and button | link (CMP-021), button (CMP-001) | "Back to your workspace", "Copy details" | "Copied" as slice 2 (#4290) E20                |
| glyph           | none                             | —                                        | `aria-hidden="true"`                           |

**Focus:** on navigation, to the `h1`, as on any route (D09 §9.4); on an in-place replacement focus never moves, except
to restore it to the `h1` when the replacement unmounted the focused element, after the announcement (D09 §4.1,
`E09-D09.md:128`). **Live region:** the in-place replacement is announced once, assertively (D09 §4.4,
`E09-D09.md:145`). **Data and security:** it names a capability, never data — no label and no existence hint; the
account variant echoes only the id the client's own route carried (D09 §14.1; SR-056); the page emits `error.403_shown`,
and the server audits `rbac.denied` (D09 §5.2). **Motion:** none. **Hit target:** the link and the button, at least 24
px. **Resize & overflow:** wraps; the Ref breaks anywhere rather than overflow. **Forced colors:** CanvasText, LinkText,
the glyph `currentColor`.

**Catalogue alignment** (`15:873-880`): Purpose names the tiers; Props takes D09 DS-3 for `reason?` (H18); A11y takes
D09 §10's `h1`, never "Access denied", the vocabulary sentence, the Ref only with a 403 body, the focus rule and one
announcement (D09 §4.4); Tokens: inherits CMP-026, plus `type.ui.heading-lg`, `type.num.base`, `type.num.sm`; Storybook
adds Withdrawn, AccountVariant and NoRef.

### CMP-090 · NotFoundState

**Catalogue (verbatim, `15:885`; the entry has no A11y line):**

- **Props**: `path?`.

| Axis    | Values           | Default |
| ------- | ---------------- | ------- |
| Variant | unknown, deleted | unknown |

**Variants × States (3 cells; boards PENDING: `CMP-090 · NotFoundState`, export `img/CMP-090-notfoundstate.png`):**
**default** (Variant=unknown at `/nowhere`: "Page not found" · "There's nothing at /nowhere." · "Try: Workspace ·
Journal · Settings", `E09-D09.md:279`); **admin** (`/admin/users` for a session without `admin:read`: the same copy,
title and analytics — D09's T3 hard-404, §6, `E09-D09.md:168`); **deleted** (Variant=deleted: the distinct copy for a
deleted object, "this workspace was deleted", `14:2920`). **Which tier it renders:** T3 for an admin destination (D09
§2.1 step 1, `E09-D09.md:50`) and a plain unknown route, which is no RBAC case at all; never T2. **Not drawn:**
interactive states (its links are CMP-021's); loading (it resolves client-side with no network call, `14:2918`).

**Anatomy:** CMP-026's block on `color.surface.app`: the CMP-019 `search` at `size="lg"` in `color.text.tertiary`
(decorative); the `h1` in `type.ui.heading-lg`; the sentence in `type.ui.body`, `color.text.secondary`, with the
attempted route in `type.num.sm` as text; "Try:" and the session's permitted top-level routes as CMP-021 links, `·`
between them. **Keyboard:** none of its own: the links (APG Link).

**Accessible name and role:**

| Element   | Role                      | Name             | ARIA                                                                   |
| --------- | ------------------------- | ---------------- | ---------------------------------------------------------------------- |
| heading   | heading, level 1          | "Page not found" | `tabindex="-1"`; the document title, identical for every unknown route |
| route     | text                      | —                | plain text, never a link                                               |
| try links | a list of links (CMP-021) | the route names  | the `·` separators `aria-hidden="true"`                                |

**Focus:** on navigation, to the `h1` (D09 §9.4). **Live region:** none. **Data and security:** the try list is derived
from the session's permitted routes, so a viewer is never sent from a 404 to a 403, and it is identical for an admin
route and an unknown one; `error.404_shown {route}` is the same event for both; nothing is fetched (D09 §6). **Motion:**
none. **Hit target:** each link at least 24 px tall. **Resize & overflow:** wraps; the route breaks anywhere. **Forced
colors:** CanvasText, LinkText.

**Catalogue alignment** (`15:882-888`): Props `path` (echoed as text), `tryRoutes` (the session's permitted routes) and
`variant?: "unknown" | "deleted"` (H19); a new A11y line: the `h1` "Page not found", the route echoed as text, the try
links a list, identical copy, title and analytics for an admin route without `admin:read` (D09 §6), focus to the `h1` on
navigation; Tokens: inherits CMP-026, plus `type.ui.heading-lg` and `type.num.sm`; Storybook adds Deleted.

### CMP-091 · GlobalErrorBoundaryFallback

**Catalogue (verbatim, `15:893-894`):**

- **Props**: `error` · `onReload` · `onReport`.
- **A11y**: `role="alert"`, focus moves to the fallback heading on mount.

| Axis     | Values       | Default |
| -------- | ------------ | ------- |
| Scope    | panel, app   | panel   |
| Details  | closed, open | closed  |
| Repeated | false, true  | false   |

**Variants × States (4 cells; boards PENDING: `CMP-091 · GlobalErrorBoundaryFallback`, export
`img/CMP-091-globalerrorboundaryfallback.png`):** **default** (Scope=panel: "This panel crashed" with `Reload panel` and
`Remove panel` inside the panel, the workspace alive around it (`14:2924`); the Ref line; the host's protection sentence
where true); **app** (Scope=app: reload, safe mode and the diagnostics export with its correlation id, `14:2924`);
**details** (Details=open: the stack behind "Technical details", as CMP-027's); **repeated** (Repeated=true: the
automatic remount stopped, with the host's sentence saying why, `14:2930`). **Not drawn:** interactive states of the
surface (its buttons are CMP-001's); loading and empty (other components). It is an outcome, never T2 (conventions 37).

**Anatomy:** panel scope inside the panel's own region on its surface: the CMP-019 `danger` at `size="lg"` in
`color.status.danger.strong`, the heading in `type.ui.heading-sm`, the statement in `type.ui.body`,
`color.text.secondary`, `Reload panel` a CMP-001 `secondary` and `Remove panel` a `ghost`; app scope a page on
`color.surface.app` with the `h1` in `type.ui.heading-lg`; both carry the Ref in `type.num.sm` (selectable, with a
CMP-033 copy button) and CMP-027's details box. **Keyboard:** none of its own: the buttons (APG Button) and the
"Technical details" disclosure (APG Disclosure).

**Accessible name and role:**

| Element           | Role   | Name                | ARIA                                                         |
| ----------------- | ------ | ------------------- | ------------------------------------------------------------ |
| panel fallback    | region | its heading         | its one sentence spoken through the shell's assertive region |
| app fallback      | alert  | —                   | its own `role="alert"` (the shell is gone), with the `h1`    |
| Technical details | button | "Technical details" | `aria-expanded`, `aria-controls`                             |
| glyph             | none   | —                   | `aria-hidden="true"`                                         |

**Focus:** it moves only when the crash unmounted the focused element: then it is restored to the fallback's heading
(`tabindex="-1"`) after the announcement (D09 §9.4); focus elsewhere in the workspace stays (`05` §3.4 item 3). **Live
region:** once per crash, assertive; a repeated crash re-announces only when the remount stops. **Motion:** none; no
automatic remount loop (`14:2930`). **Hit target:** the buttons, at least 24 px. **Resize & overflow:** wraps; the
details scroll inside their box. **Forced colors:** CanvasText, the glyph `currentColor`, the details box a 1 px
CanvasText border.

**Catalogue alignment** (`15:890-897`): Props gains `scope`, `correlationId`, `onRemovePanel?`, `onSafeMode?`,
`repeated?` and `protectionNote?` (H20); A11y takes the focus restoration, the two announcement paths, the details
disclosure and the selectable Ref; Tokens: inherits CMP-027, plus `type.ui.heading-sm`, `type.ui.heading-lg`,
`type.num.sm`, `color.surface.raised`; Storybook adds App, Details and Repeated.

## 8. Design QA checklist (brief §12)

Completed for the 17 components. Open items say why and who closes them.

- [ ] **Tokens:** only published Tier-2/Tier-3 tokens, no hardcoded hex/px. **Open:** every value is a semantic token or
      a named primitive (§4, §5.2); §5.1's constants and the scrim's primitives are recorded, ticked when §6 H1 and H7
      are answered and the boards PR has drawn them.
- [ ] **Themes and densities:** structurally guaranteed and measured in all three themes (audit §4). **Open:** the
      boards are PENDING.
- [ ] **Contrast matrix:** every text pair passes; three non-text pairs are thin and carried by words — the dark danger
      progress fill (2.92:1, §6 H4), light warning's toast edge (2.76:1, §6 H6), E39-D03's hold ring on its track
      (1.90:1 dark). **Open** for the owner.
- [ ] **CVD:** ΔE76 spot checks in the audit §5; every tone carries a glyph and a word. **Open:** E05-D04's review.
- [ ] **Every State has a variant (and a story):** the 99 cells are specified (§1, §7). **Open:** the boards PR draws
      them; the stories are E05-S01..S04's (slice 1 C15).
- [ ] **Disabled with a reason (CMP-079):** containers never gate; a nested control takes its own T2 form through
      CMP-079, with the CMP-019 `lock` and the host's reason (conventions 36; the four gated cells, §1); validity and
      unavailability stay apart (conventions 37). **Open** until drawn.
- [ ] **Loading, empty and error designed:** CMP-015, 026, 027, 029, 038 and 091, and the drawer's and dialogs' loading
      and failure cells. **Open** until drawn.
- [ ] **Keyboard tables** complete for all 17 (the APG pattern named, or none of its own with the reason). **Open** for
      "implemented, tested" (E05-S01..S04).
- [x] **Accessible-name/role tables:** all 17 (§7; summary in the audit §2).
- [x] **Canvas-adjacent:** CMP-029 is hidden and its chart region `aria-busy` with words.
- [x] **Motion pairs** for every animated property (conventions 35).
- [x] **Hit targets:** 24 × 24 px compact and 32 px comfortable, no essential exception (E05-D07's 32 px supersedes
      brief §12's older "40-44px", slice 1 C13).
- [ ] **Accessibility sign-off (§13).** **Open:** the pre-review is the companion audit; the sign-off is E05-D04's.
- [x] **Confirm gates:** CMP-044's standard, typed and hold variants with their keyboard paths, the 400 ms guard and
      ignored repeats (§6 H24, H25); the variant per action is its screen's.
- [x] **Estimated values:** not applicable in this slice.
- [x] **Demo/Live:** the env band stays above every scrim (conventions 31, §6 H23); a confirm restates the environment
      through its host's content (`14` SCR-075).
- [x] **No near-duplicate:** no new ID; CMP-026's error is CMP-027 (§6 H13); CMP-044 composes CMP-043.
- [ ] **Storybook matches the matrix.** Not applicable to this design PR (slice 1 C15).
- [ ] **Composes only published components.** **Open:** the boards PR nests the slice 1–3 components and CMP-022 once
      slice 5 ships (§1).

## 9. Approval

The owner approves by merging this spec PR and/or commenting `approved` on #161 (C-10.1; the coordinator reviews under
the owner's delegation): owner approval pending. This text merges first with the boards PENDING; the boards PR builds
slice 4's sections on page `10 Components — Atoms`. Engineering stories E05-S01..S04 move to Ready only after every
slice is approved. The accessibility pre-review is `E05-D02-feedback-overlays-a11y-audit.md`; the formal accessibility
and CVD sign-off is E05-D04's. The hand-offs of §6 (f) go to their owners when the coordinator files them.
