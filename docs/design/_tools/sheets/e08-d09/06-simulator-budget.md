# E08-D09 / 06 simulator-budget

File `E08-D09 boards`, page `E08-D09 SCR-147 Connectivity`; export `docs/design/E08/img/E08-D09-06-simulator-budget.png`; sheet `06-simulator-budget.json` (validated); theme dark.

Board 06 of ten (§0 L88: the simulator's result (served and deferred accounts); the Change budget dialog and its refusal). Grid (0, 3200); 4640 x 1878 px; footer W-01; "page E08-D09 SCR-147 Connectivity · board 06 · r1".

## Frames

- `SCR-147 · S-19 not connected yet · simulator · dark` (S-19)
- `SCR-147 · simulator result · dark` (no S-id)
- `SCR-147 · Change budget dialog · dark` (no S-id)
- `SCR-147 · Change budget refusal · dark` (no S-id)
- `SCR-147 · T2 view-as forms · dark` (no S-id)

## Validator and size

- `06-simulator-budget.json: 0 errors, 13 warnings, 64 sections, 238235 bytes` (exit 0)
- 64 sections, 238235 bytes

## Live checks (15)

- modal: re-centre 'CMP-044 dialog · Change budget' after relayout (estimated 560 x 490 px)
- Change budget dialog: the page is about 691 px for a 672 px view: the export shows its top only (as drawn); read back that the main column clips it
- modal: re-centre 'CMP-044 dialog · Change budget' after relayout (estimated 560 x 521 px)
- Change budget refusal: the page is about 691 px for a 672 px view: the export shows its top only (as drawn); read back that the main column clips it
- T2 frame: the row menu sits under Main's row action (estimated x 760, y 266); re-anchor it to the row's bottom-right after relayout
- simulator result: read back 5 rows, 3 'Served now' and 2 'Deferred', and the W-40 line with 15 requests and 3 %
- Change budget dialog: read back the focus ring on Cancel; refusal frame: the ring on the field, the field's value 600 and the danger stroke
- root 'E08-D09 / 06 simulator-budget' at (0, 3200): read back the name exactly after the first section call; size 4640 x 1878
- after touchTexts + relayout: the annotation column (estimated 1785 px) ends inside the root (h 1878); raise the root's h to its end + 80 if not
- frame 'SCR-147 · S-19 not connected yet · simulator · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-147 · simulator result · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-147 · Change budget dialog · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'SCR-147 · Change budget refusal · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-147 · T2 view-as forms · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E08/img/E08-D09-06-simulator-budget.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (7)

- D09-G1 (§21.2 L699): a read of per-account, per-class usage, limit, window and headroom at 1 Hz, with the IP ho
- D09-G14 (§21.2 L712): the reserve figure per account
- D09-G10 (§21.2 L708): a fan-out cost read for the simulator
- D09-G8 (§21.2 L706): the budget-change setting, route and audit code connectivity.budget_changed
- D09-G12 (§21.2 L710): a step-up class for the two connectivity actions
- D09-G17 (§21.2 L715): the server permission each of the two writes needs (force reconnect, budget change)
- D09-G7 (§21.2 L705): a force-reconnect route; the audit code connectivity.reconnect_forced registered

## Spec gaps (2)

- §12's refusal: the server's mapped reason has no §15 string; drawn as W-59's slot {mapped reason}
- §8's output columns and the IP bucket line have no §15 strings: headings from §8's Output prose

## Deviations (5)

- G-row marker line 'Waits on D09-Gn' on each waiting section: §0 asks for the mark, gives no string
- dialog width 560 px: a kit choice (no source gives CMP-044's width)
- W-74's {user} slot filled with the kit alias 'Sam' (no sample in §15)
- board 06: the dialogs open over Rate budgets; the T2 frame draws Rate budgets then Actions (the simulator, inspector and clock between them are off the frame)
- the T2 row menu is drawn as an overlay anchored under Main's row action (position estimated)

## Copy keys (22)

- W-07 (§15 L422; per-class table caption)
- W-08 (§15 L423; column headers)
- W-09 (§15 L424; meter value text)
- W-13 (§15 L428; S-01)
- W-60 (§15 L475; budget row action)
- W-06a (§15 L420; reserve band, not served (S-19))
- W-06b (§15 L421; reserve band, served)
- W-41 (§15 L457; simulator labels)
- W-05 (§15 L419; not wired (S-19))
- W-02 (§15 L416; page `h1`; route name)
- W-03 (§15 L417; header meta)
- W-40 (§15 L456; simulator result line)
- W-42 (§15 L458; simulator outcomes; announcement)
- W-43 (§15 L459; simulator stale)
- W-61 (§15 L476; allowed range)
- W-62 (§15 L477; effect and way back)
- W-64 (§15 L479; invariants)
- W-54 (§15 L469; step-up slot)
- W-63 (§15 L478; audit marker)
- W-74 (§15 L484; T2 view-as (verbatim))
- W-50 (§15 L465; force reconnect trigger, title, confirm)
- W-01 (§15 L415; board footer (verbatim))

## Copy gaps (16)

- budget table headings "Meter" and "State": §3.2 L226 and L227 (W-08 lists six)
- "Rate budgets": section h2, §2.2 anatomy, from the spec prose at L177 (not in §15)
- "Fan-out simulator": section h2, §2.2 anatomy, from the spec prose at L178 (not in §15)
- "Admin area": the band region name, from §2.1 L171 (CMP-087 own string; not in §15)
- "Requests": simulator output column, from the spec prose at L326 (not in §15)
- "Share of spendable budget": simulator output column, from the spec prose at L326 (not in §15)
- "Outcome": simulator output column, from the spec prose at L326 (not in §15)
- "Shared IP bucket": the IP bucket line's label, from the spec prose at L326 (not in §15)
- "requests per minute": the field's unit (W-61's unit), from the spec prose at L379 (not in §15)
- "Current value": label of the current value, from the spec prose at L379 (not in §15)
- "New value": label of the new-value field, from the spec prose at L379 (not in §15)
- "Change budget": dialog title: W-60 without its ellipsis, from the spec prose at L379 (not in §15)
- "Save budget": dialog confirm, from the spec prose at L379 (not in §15)
- "Cancel": dialog button, from the spec prose at L369 (not in §15)
- "{mapped reason}": the server's mapped reason (§12) has no string; drawn as W-59's own slot, from the spec prose at L474 (not in §15)
- "Actions": section h2, §2.2 anatomy, from the spec prose at L181 (not in §15)

## Fallbacks (4)

- fallback: CMP-178's ring glyph (§5.2) drawn as a 12 px ellipse outline, border.thick (no ring icon)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders; only CMP-087's band and rule and the SCR-147 page are drawn (§2.1, §2.2)
- fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim

## Sources (1)

- spec E08-D09.md md5 bb6e2dd1 (§0 L88, §2, §3, §5.2, §15, §16, §17); hand-off E08-D09-handoff.md md5 3dc8240e

## Tokens (47)

- type.ui.caption
- color.text.secondary
- space.inset.sm
- space.inset.xs
- color.surface.canvas
- radius.badge
- color.surface.hover
- color.action.primary.default
- color.status.success.strong
- size.icon
- type.ui.body-strong
- color.text.primary
- radius.control
- type.ui.body
- space.stack.xs
- type.num.base
- color.surface.raised
- color.border.default
- color.neutral.default
- border.thick
- border.hairline
- radius.card
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
- type.ui.label
- color.text.on-action
- size.icon.sm
- space.inset.lg
- space.inset.md
- color.surface.selected
- color.surface.sunken
- space.button.paddingX
- type.ui.heading-md
- space.stack.lg
- color.surface.app
- color.border.subtle
- color.focus.ring
- border.focus
- color.status.warning.strong
- color.action.secondary.default
- color.surface.overlay
- radius.dialog
- space.dialog.padding
- space.stack.md
- opacity.scrim
- color.status.danger.strong
