# E05-D02 — Accessibility pre-review, slice 5: the rest of the v0 subset and the custom trading glyphs

**Ticket:** E05-D02 (#161) · companion to `E05-D02-rest.md` (slice 5) · required by
`docs/plan/16-design-system-brief.md` §12 (accessibility items) and `docs/plan/05-accessibility-standard.md` §3
(keyboard, focus, target size, skip links), §4 (colour independence), §5 (contrast), §6.2 (live regions), §7 (reduced
motion) and §11 (design-system requirements).
**Status:** pre-review. The ticket's Definition of Done asks for an Accessibility role pre-review here; **the formal
accessibility and CVD sign-off is E05-D04's**, and this document does not replace it.

Covers the 11 components of slice 5 (CMP-022, 035, 036, 042, 050, 059, 062, 063, 069, 085 and 228) and the 13 custom
trading glyphs as specified in `E05-D02-rest.md` §7 and §7.12. The slice is text-first and adds no board (the ten-board
cap): CMP-022 and CMP-035 appear on specimen board 09 as parts of slice 4's menu, tooltip and order confirm; everything
else is specified only. The CMP-003, CMP-004 and CMP-019 these components nest are reviewed in slice 1's audit
(`E05-D02-a11y-audit.md`), CMP-079 in slice 3's (`E05-D02-form-controls-a11y-audit.md`), and CMP-041, CMP-043 and
CMP-046 in slice 4's (`E05-D02-feedback-overlays-a11y-audit.md`).

**Method.** Every ratio below was computed for this review from `packages/ui/tokens` as #3925 left them (`a0132de01`,
their last change), each theme layered as `packages/ui/tokens/tests/verify_tokens.py` layers it (its loader, imported),
with `contrast_ratio()` from `docs/design/_tools/contrast_check.py` (WCAG 2.x relative luminance) and ΔE76 from
`docs/research/_tools/cvd_simulate.py`; values are rounded half up to two places. "The host surfaces" are
`color.surface.app`, `canvas`, `raised` and `overlay`. The keyboard and name/role rows summarise the full tables in
`E05-D02-rest.md` §7. "§6 Jn" points at that document's owner decisions; "conventions n" at its §3. In §4–§6 a colour
token drops its `color.` prefix (`text.primary` is `color.text.primary`) except `color.border.*`, which keeps it because
`border.*` names the border-width primitives.

## 1. Summary

| Check                  | Requirement                            | Result                                                                                                                                                                                                                                                                                                            |
| ---------------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Keyboard operation     | `05` §3.1, §3.4                        | **Pass at design stage.** Every focusable component names its APG pattern (Tabs, Combobox with a listbox inside a modal Dialog, Radio Group through CMP-003, Menu through CMP-041, a non-modal dialog and a Disclosure for CMP-069) or says it has none of its own; tests are E05-S01..S04's.                     |
| Bypass blocks          | `05` §3.4 item 5; WCAG 2.4.1           | **Open on §6 J19 and J20**: one "Skip to main content" link is specified as the first Tab stop (E10-D03); `05` asks for a set ("Skip to order ticket" / "Skip to chart"), and the target must take focus, not only scroll.                                                                                        |
| Dialogs and focus      | `05` §3.4 items 3–4; WCAG 2.1.2, 2.4.3 | **Pass at design stage**: the palette traps Tab with focus in its input and returns focus on close (slice 4 conventions 32); the info drawer is non-modal, focus to its heading and back to the chip on `Esc` (§6 J18).                                                                                           |
| Visible focus          | `05` §3.4.6; WCAG 2.4.7, 2.4.11        | **Pass**: the CMP-039 ring is 7.45 / 6.75 / 19.35:1 on app, 6.66 / 5.86 / 17.30:1 on raised, 6.15 / 5.39 / 15.99:1 on overlay and 4.72 / 4.81 / 12.26:1 on the palette's selected row; a skip target shows it too (§6 J20).                                                                                       |
| Target size            | `05` §3.4.7; WCAG 2.5.8                | **Pass**, no essential exception: tabs, palette rows (32 / 40 px), the skip link and the appearance controls are at least 24 × 24 px compact; Kbd, Countdown, KeyValueRow, Card and PreviewTile are not targets.                                                                                                  |
| Colour never alone     | `05` §4                                | **Pass**: the selected tab carries a 2 px rule and `aria-selected`; the countdown's threshold a `clock` glyph and the number (§6 J1); a destructive command its glyph and "confirms"; T2 a lock, a tertiary label and a reason; the glyphs are `currentColor` and never carry a hue alone (§6 J25).               |
| Text contrast          | `05` §5; WCAG 1.4.3                    | **Pass with one decision**: every text pair specified passes 4.5:1; the countdown's catalogue colour `color.text.warning` does not exist, and its stand-in `status.warning.strong` would fail for text in light (3.78–4.41:1), so §6 J1 keeps the digits' colour.                                                 |
| Live regions           | `05` §6.2; WCAG 4.1.3                  | **Pass at design stage** (conventions 45): a countdown speaks only at its thresholds, latest only, never per tick and never in a grid; the palette's count once per settled query; an appearance change once per committed change and never on load.                                                              |
| Timing                 | WCAG 2.2.1                             | **Pass**: no component here times anything out; CMP-035 shows its host's deadline, and SCR-076's cancelling countdown is slice 4's (conventions 34).                                                                                                                                                              |
| Disabled with a reason | `14` §0.5 rule 5; E09-D09 §2.2         | **Specified**: containers never gate; the gated tab and the gated palette command take T2 through CMP-079 with the CMP-019 `lock`, the label in `text.tertiary` and the reason in `text.secondary`, never `text.disabled` or `opacity.disabled` (conventions 46). **Open on §6 J15** for the appearance controls. |
| Accessibility settings | `05` §5 item 6; `05:79`                | **Open on §6 J15**: a viewer lacks `settings:write`; the recommendation applies theme and density on the device for every role, so high contrast is never locked away.                                                                                                                                            |
| Motion                 | `05` §7; brief §7                      | **Pass**: nothing here animates but slice 4's dialog and drawer frames; theme and density swaps, tab switches and the countdown's digits are cuts in both modes.                                                                                                                                                  |
| Non-text images        | WCAG 1.1.1                             | **Pass at design stage**: CMP-228 is `role="img"` with its configuration in words and never the only disclosure; every custom glyph is decorative beside its word, with a name rule for any standalone use (§7.12).                                                                                               |

## 2. Keyboard path, role and name

| Component              | Keyboard path (APG pattern)                                                                                                                                                 | Role and accessible name                                                                                                                                                                         |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| CMP-022 Kbd            | None: never focusable; its host's keys apply.                                                                                                                               | Nested `<kbd>`; the visible caps hidden and one visually hidden expansion read ("Control plus Shift plus K"); in a menu item the Kbd is hidden and `aria-keyshortcuts` carries it.               |
| CMP-035 Countdown      | None: not focusable.                                                                                                                                                        | Text, `aria-live="off"`; a hidden twin holds the words; a polite announcer at each threshold, the host's key; a running clock is the host's `role="timer"` (§6 J6).                              |
| CMP-036 KeyValueRow    | None: a nested link or button owns its keys.                                                                                                                                | `dt` / `dd` inside the host's `dl` (§6 J8); "—" read as the state word, never "dash".                                                                                                            |
| CMP-042 Tabs           | Tabs: Tab to the selected tab, arrows and `Home` / `End` move (automatic select, or manual with `Enter` / `Space`), Tab into the panel; a gated tab re-shows its reason.    | `tablist` named by the host; `tab` with `aria-selected` and `aria-controls`; `tabpanel` labelled by its tab, `tabindex="0"` when empty of controls; gated: `aria-disabled` + `aria-describedby`. |
| CMP-050 Card           | None of its own; its actions keep DOM order.                                                                                                                                | A heading at `headingLevel` (none inside a listbox option); a `region` only for a landmark tile, named by its heading (§6 J11).                                                                  |
| CMP-059 CommandPalette | Combobox + listbox inside Dialog (Modal): `Ctrl+K` opens with focus in the input, ↑ / ↓ move the active option, `Enter` / `Ctrl+Enter` run, `Esc` closes and returns focus. | `dialog`; `combobox` with `aria-activedescendant`; `listbox` with `group`s named by their headers; `option` named by label and tag; the count a polite status. Names are E15's keys (§6 J12).    |
| CMP-062 ThemeSwitcher  | Radio Group through CMP-003; `Ctrl+Shift+H` from anywhere (`05:79`).                                                                                                        | `radiogroup` named by SCR-116's label; `radio` "Dark" · "Light" · "High contrast"; the CMP-004 switch for "match system"; one polite sentence per committed change.                              |
| CMP-063 DensityToggle  | Radio Group through CMP-003, or Menu through CMP-041 (`menuitemradio`).                                                                                                     | `radiogroup` or the menu's group, the scope in its name; "Compact" · "Comfortable" · "Dense" (chart panel); one polite sentence per committed change.                                            |
| CMP-069 InfoPanel      | Drawer: a non-modal dialog opened by `Enter` / `Space` on the chip, focus to its heading, `Esc` back to the chip; inline: Disclosure.                                       | `dialog` (`aria-modal="false"`) named by its title, or an inline region with `aria-expanded` on the trigger; the body `aria-busy` while loading.                                                 |
| CMP-085 SkipLink       | The first Tab shows it; `Enter` moves focus to the target (`tabindex="-1"`, the ring shown); Tab continues from there.                                                      | `link` "Skip to main content" (E10-D03); further links per §6 J19.                                                                                                                               |
| CMP-228 PreviewTile    | None: not focusable.                                                                                                                                                        | `img` named by the configuration in words; "Preview unavailable" when empty or errored; `aria-live="off"`.                                                                                       |
| Custom glyphs (§7.12)  | None: never focusable.                                                                                                                                                      | Decorative beside a word (`aria-hidden`); an icon-only control carries the name; a standalone glyph is CMP-019 `decorative=false` with the §7.12 name.                                           |

## 3. Focus, target size, timing, live region and motion

| Component | Focus                                                   | Target size                 | Timing                            | Live region                                                              | Motion pair (safe / reduce)                       |
| --------- | ------------------------------------------------------- | --------------------------- | --------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------- |
| CMP-022   | None.                                                   | None.                       | None.                             | None.                                                                    | None / none.                                      |
| CMP-035   | Never moves focus, at a threshold or at expiry.         | None.                       | 1 Hz digits; the host's deadline. | Polite at 60 / 10 / 0 s by default (§6 J7), latest only; none in a grid. | Digit swap / the same.                            |
| CMP-036   | None.                                                   | None.                       | None.                             | None; a host's computed row at most once per 2 s.                        | E08-D11's settle through CMP-239 / a cut.         |
| CMP-042   | Stays on the tab on switch; lazy panels never steal it. | 24 × 24 px or more.         | None.                             | Only a gated tab's reason, once.                                         | None (cuts) / none.                               |
| CMP-050   | None of its own.                                        | Its actions'.               | None.                             | None.                                                                    | None / none.                                      |
| CMP-059   | In the input; a trap; back to the opener on close.      | Rows 32 / 40 px.            | None.                             | The count, once per settled query; a gated command's reason once.        | Slice 4's dialog: the scrim fades, the card cuts. |
| CMP-062   | Stays on the segment.                                   | CMP-003's.                  | None.                             | Once per committed change; nothing on load or a system flip.             | Instant swap / the same.                          |
| CMP-063   | Stays on the option, or back to the menu trigger.       | CMP-003's or CMP-041's.     | None.                             | Once per committed change, with the scope.                               | Instant swap / the same.                          |
| CMP-069   | To the heading on open; back to the trigger on close.   | The close button's.         | None.                             | None; a load failure is CMP-027's polite region.                         | Slice 4 CMP-046's slide / a cut; inline a cut.    |
| CMP-085   | To the target on `Enter`; never on its own.             | `size.control.height` tall. | None.                             | None.                                                                    | Appears as a cut / the same.                      |
| CMP-228   | None.                                                   | None.                       | None.                             | None.                                                                    | One-frame re-projection / a cut.                  |
| Glyphs    | None.                                                   | None (their control's).     | None.                             | None.                                                                    | Never animated.                                   |

## 4. Contrast pairs each component introduces

Text needs 4.5:1 (WCAG 1.4.3); glyphs, boundaries, fills that carry a value and focus indicators 3:1 (WCAG 1.4.11).
**Bold** marks a pair below its bar. Dark / light / high contrast.

| Component           | Pair                                                                                                 | Dark                         | Light                        | High contrast                | Needs  | Note                                                                        |
| ------------------- | ---------------------------------------------------------------------------------------------------- | ---------------------------- | ---------------------------- | ---------------------------- | ------ | --------------------------------------------------------------------------- |
| CMP-022             | key text `text.secondary` on `surface.raised` / `surface.overlay`                                    | 8.81 / 8.14                  | 8.98 / 8.26                  | 14.35 / 13.27                | 4.5    | §6 J4 (c)                                                                   |
| CMP-022             | key text `text.primary` on `surface.raised` (E10-D03's option)                                       | 14.35                        | 15.62                        | 16.25                        | 4.5    | §6 J4 (a)                                                                   |
| CMP-022             | cap edge `color.border.strong` on `surface.raised`; the cap fill on `surface.overlay`                | **1.80**; **1.08**           | **1.46**; **1.09**           | **1.80**; **1.08**           | —      | decorative: the text is the hint (E10-D03 row 21, "structure")              |
| CMP-035             | the digits in their host's `text.tertiary` on canvas / raised / overlay                              | 5.96 / 5.62 / 5.20           | 6.36 / 5.92 / 5.44           | 11.87 / 11.21 / 10.36        | 4.5    | the host's colour, kept under the threshold (§6 J1)                         |
| CMP-035             | `status.warning.strong` as text on canvas / raised / overlay (§6 J1 (a))                             | 11.65 / 11.00 / 10.17        | **4.41 / 4.11 / 3.78**       | 11.65 / 11.00 / 10.17        | 4.5    | why (a) is not recommended                                                  |
| CMP-035             | the `clock` glyph in `status.warning.strong` on the same surfaces (§6 J1 (c))                        | 11.65 / 11.00 / 10.17        | 4.41 / 4.11 / 3.78           | 11.65 / 11.00 / 10.17        | 3      | passes as a glyph                                                           |
| CMP-036             | label `text.secondary` and value `text.primary` on canvas                                            | 9.33; 15.20                  | 9.65; 16.78                  | 15.20; 17.21                 | 4.5    | on raised 8.81; 14.35 (light 8.98; 15.62)                                   |
| CMP-036             | E08-D11 M25's `text.disabled` on raised (kept with its owner)                                        | **2.86**                     | **3.74**                     | **2.86**                     | 4.5    | §6 J8 (c)                                                                   |
| CMP-042             | selected rule `color.border.selected` on raised / canvas                                             | 4.89 / 5.18                  | 4.13 / 4.44                  | 6.66 / 7.05                  | 3      | the non-colour carrier of selection                                         |
| CMP-042             | unselected `text.secondary` on raised; hover `text.primary` on `surface.hover`                       | 8.81; 12.22                  | 8.98; 14.37                  | 14.35; 13.83                 | 4.5    | —                                                                           |
| CMP-042             | `action.selected` fill on raised (E30-D04's CMP-103 look)                                            | **1.16**                     | **1.07**                     | **1.16**                     | —      | decorative there too; its 2 px `text.primary` rule carries it               |
| CMP-050             | `surface.raised` on canvas / app; the hairline on canvas / app                                       | **1.06 / 1.12; 1.50 / 1.58** | **1.07 / 1.15; 1.31 / 1.40** | **1.06 / 1.12**; 3.03 / 3.20 | —      | decorative (conventions 44); the heading names the group                    |
| CMP-050             | title `text.primary` on raised                                                                       | 14.35                        | 15.62                        | 16.25                        | 4.5    | —                                                                           |
| CMP-059             | rows `text.primary` on overlay; on the active `surface.selected`                                     | 13.27; 10.17                 | 14.37; 12.82                 | 15.02; 11.51                 | 4.5    | E10-D03 §6.1                                                                |
| CMP-059             | group headers and placeholder `text.tertiary` on overlay                                             | 5.20                         | 5.44                         | 10.36                        | 4.5    | never on `surface.selected`, where it would be **3.98** dark                |
| CMP-059             | destructive glyph `status.warning.strong` on overlay / on `surface.selected`                         | 10.17 / 7.80                 | 3.78 / 3.37                  | 10.17 / 7.80                 | 3      | a glyph; "confirms" carries it (E10-D03 row 43)                             |
| CMP-059             | gated label `text.tertiary`, reason `text.secondary` on overlay                                      | 5.20; 8.14                   | 5.44; 8.26                   | 10.36; 13.27                 | 4.5    | conventions 46                                                              |
| CMP-085             | label `text.on-action` on `action.primary.default`; hover                                            | 4.76; 6.75                   | 4.76; 6.75                   | 7.45; 5.47                   | 4.5    | E10-D03 rows 38–39                                                          |
| CMP-085             | the pill against `surface.app`; the ring on `surface.app`                                            | 4.07; 7.45                   | 4.76; 6.75                   | 7.45; 19.35                  | 3      | the ring sits outside the pill (on the pill it would be 1.83 / 1.42 / 2.60) |
| CMP-228             | empty / error text `text.secondary`; axis labels `text.tertiary` on `surface.sunken`                 | 10.69; 6.83                  | 7.37; 4.86                   | 17.42; 13.61                 | 4.5    | E11-D03 §6.4                                                                |
| CMP-228             | error glyph `status.danger.strong`; a ladder value `text.primary` on `surface.sunken`                | 11.31; 17.42                 | 3.37; 12.82                  | 11.31; 19.73                 | 3; 4.5 | —                                                                           |
| CMP-228             | tile edge `color.border.default` / `color.border.strong` on `surface.sunken`                         | **1.71 / 2.19**              | **1.00 / 1.20**              | 3.47 / **2.19**              | —      | decorative-adjacent image (§6 J2)                                           |
| Glyphs (§7.12)      | `text.primary` / `text.secondary` / `text.tertiary` on canvas, raised, overlay                       | ≥ 13.27 / ≥ 8.14 / ≥ 5.20    | ≥ 14.37 / ≥ 8.26 / ≥ 5.44    | ≥ 15.02 / ≥ 13.27 / ≥ 10.36  | 3      | every context colour clears the glyph bar                                   |
| Glyphs              | `icon/estimated` in `status.info.default` on raised / canvas                                         | 6.20 / 6.57                  | 3.48 / 3.74                  | 6.20 / 6.57                  | 3      | E25-D05's binding                                                           |
| T2 (conventions 46) | label `text.tertiary`, reason `text.secondary` on raised; never `text.disabled` (2.86 / 3.74 / 2.86) | 5.62; 8.81                   | 5.92; 8.98                   | 11.21; 14.35                 | 4.5    | E09-D09 §11                                                                 |

## 5. CVD (colour-vision deficiency)

Not reviewed in this pre-review: nothing is drawn, and the formal CVD review is E05-D04's (`05` §4.2, brief §13.3 item
3). ΔE76 spot checks (base, then protanopia / deuteranopia / tritanopia); every state named here also has a non-colour
carrier:

- **The selected tab's rule against the strip's line** (`color.border.selected` vs `color.border.default`): 64.34
  (66.36 / 69.34 / 46.34) dark, 79.55 (80.80 / 86.57 / 44.28) light, 46.61 (48.37 / 51.07 / 37.98) high contrast — the
  rule also differs in width (2 px against 1 px) and `aria-selected` carries it.
- **The countdown's warning glyph against its digits** (`status.warning.strong` vs `text.primary`): 54.75 (53.57 /
  58.32 / 31.31) dark, 71.31 (66.06 / 73.12 / 54.62) light, 55.37 (54.35 / 58.74 / 33.01) high contrast; the number
  carries the threshold regardless (§6 J1).
- **The estimated glyph against secondary text** (`status.info.default` vs `text.secondary`): 32.38 (20.80 / 30.16 /
  34.10) dark, 36.93 (32.79 / 34.20 / 39.13) light, 44.80 (34.84 / 44.40 / 45.46) high contrast; the word "(estimated)"
  is always in the badge (E25-D05).
- **The skip link's pill against the app chrome** (`action.primary.default` vs `surface.app`): 83.88 (86.45 / 89.77 /
  57.00) dark, 89.18 (89.99 / 96.31 / 56.31) light, 77.31 (79.34 / 80.63 / 72.06) high contrast.
- **Node categories** are carried by the stripe's cap shape and the type word as well as `color.node.*` (E37-D02); the
  glyphs take `currentColor` (§6 J25), so no glyph pair depends on a category hue.

## 6. Findings for the owner and E05-D04

1. The countdown's catalogue colour `color.text.warning` does not exist; E17-D02 CR-5's stand-in,
   `status.warning.strong`, fails 4.5:1 as text in light on every host surface (4.41 / 4.11 / 3.78:1). Keep the digits'
   colour and add the `clock` glyph under the threshold (§6 J1 (c)).
2. E08-D11 M25 dims a live KeyValueRow to `text.disabled` while disconnected, 2.86:1 on raised in dark and high
   contrast — a text failure for meaningful values; the CMP-239 marker can carry the state instead (§6 J8 (c)).
3. A viewer holds no `settings:write`, so a T2 appearance control would lock high contrast and density away from a role
   that may need them (`05:79` gives high contrast a global hotkey); §6 J15 (a) applies them on the device for every
   role.
4. `05` §3.4 item 5 asks for a set of skip links and WCAG 2.4.1 needs the sequential focus to move to the target; the
   catalogue has one `targetId` and no focus rule (§6 J19, J20).
5. `15` opens CMP-069 "from the chip's tooltip via `Enter`"; a tooltip holds no operable content, so the trigger is the
   chip itself (§6 J18; E25-D05).
6. The Kbd cap's edge and fill are decorative (1.08–1.80:1); the hint is its text, 8.14:1 or more (§6 J4).
7. The preview tile's edge is invisible in light (1.00:1); the tile is a decorative-adjacent image whose settings carry
   the meaning (§6 J2).
8. `text.tertiary` measures 3.98:1 on `surface.selected` in dark: nothing in the palette's active row may use it (the
   gated reason uses `text.secondary`, 6.24:1 there).
9. The `icon/iceberg-order` glyph must not use a dashed outline for its hidden part: dashed means estimated or absent
   (E25-D05's pattern rule), and the iceberg order is the user's own, not an inference (§7.12).

## 7. References

`docs/plan/05-accessibility-standard.md` §3 (incl. §3.4 item 5 skip links, `05:79` and `05:85`), §4, §5, §6.2, §7, §8.1,
§11 · `docs/plan/16-design-system-brief.md` §3, §4, §5, §12, §13 · `docs/plan/14-screens-catalogue.md` §0.5 rule 5,
SCR-010, SCR-012, SCR-058, SCR-116 · `docs/plan/15-component-catalogue.md` §0.3 and the 11 entries ·
`docs/plan/22-api-openapi.yaml` `Settings.appearance`, `updateSettings` · `docs/plan/21-database-schema.md` the RBAC
seed · `docs/design/E05/E05-D02-rest.md` (§3 conventions, §5 exceptions, §6 decisions, §7 components, §7.12 glyphs, §8
QA checklist) · `docs/design/E05/E05-D02-a11y-audit.md`, `E05-D02-form-controls-a11y-audit.md` and
`E05-D02-feedback-overlays-a11y-audit.md` (slices 1, 3 and 4) · `docs/design/E09/E09-D09.md` §2.2, §3.1, §9, §11 ·
`docs/design/E10/E10-D02.md` · `docs/design/E10/E10-D03.md` §2.1, §6.1, §6.2, §10.2, §11.1 ·
`docs/design/E11/E11-D03.md` §6.4 · `docs/design/E11/E11-D05.md` §6 · `docs/design/E12/E12-D03.md` §6.4 ·
`docs/design/E12/E12-D05.md` · `docs/design/E15/E15-D03.md` §4.8 · `docs/design/E15/E15-D05.md` A-4 ·
`docs/design/E17/E17-D02.md` CR-5 · `docs/design/E25/E25-D05.md` §3, §4, CR-3 · `docs/design/E29/E29-D02.md` ·
`docs/design/E30/E30-D03.md` · `docs/design/E30/E30-D04.md` §3.3, §7 · `docs/design/E32/E32-D04.md` §8 ·
`docs/design/E36/E36-D02.md` · `docs/design/E37/E37-D02.md` · `docs/design/E08/E08-D11.md` ·
`docs/design/E40/E40-D02.md` · `packages/ui/tokens/` and `packages/ui/tokens/tests/verify_tokens.py` ·
`docs/design/_tools/contrast_check.py` · `docs/research/_tools/cvd_simulate.py` · #3925 (the token state measured here).
