# E08-D09 / 01 healthy

File `E08-D09 boards`, page `E08-D09 SCR-147 Connectivity`; export `docs/design/E08/img/E08-D09-01-healthy.png`; sheet `01-healthy.json` (validated); theme dark.

Board 01 of ten (§0 L83: the whole page: band, summary strip, per-class table with per-account rows, reserve band, simulator (form), inspector (collapsed), clock ok, actions, history (closed); sub-frames: S-13 loading, S-15 stale, S-16 degraded, S-17 error, S-18 unavailable, S-19 not connected yet). Grid (0, 0); 4640 x 2758 px; footer W-01; "page E08-D09 SCR-147 Connectivity · board 01 · r1".

## Frames

- `SCR-147 · S-01 healthy · top · dark` (S-01)
- `SCR-147 · S-01 healthy · middle · dark` (S-01)
- `SCR-147 · S-01 healthy · bottom · dark` (S-01)
- `SCR-147 · S-13 loading · dark` (S-13)
- `SCR-147 · S-15 stale · dark` (S-15)
- `SCR-147 · S-16 degraded · dark` (S-16)
- `SCR-147 · S-17 error: our counters not reporting · dark` (S-17)
- `SCR-147 · S-18 unavailable: the read itself failed · dark` (S-18)
- `SCR-147 · S-19 not connected yet · dark` (S-19)

## Validator and size

- `01-healthy.json: 0 errors, 26 warnings, 137 sections, 486868 bytes` (exit 0)
- 137 sections, 486868 bytes

## Live checks (21)

- S-01 healthy · top: the page is about 1860 px for a 672 px view: the export shows its top only (as drawn); read back that the main column clips it
- S-13 loading: the page is about 708 px for a 672 px view: the export shows its top only (as drawn); read back that the main column clips it
- S-15 stale: the page is about 789 px for a 672 px view: the export shows its top only (as drawn); read back that the main column clips it
- S-16 degraded: the page is about 737 px for a 672 px view: the export shows its top only (as drawn); read back that the main column clips it
- S-17 error: our counters not reporting: the page is about 789 px for a 672 px view: the export shows its top only (as drawn); read back that the main column clips it
- S-18 unavailable: the read itself failed: the page is about 737 px for a 672 px view: the export shows its top only (as drawn); read back that the main column clips it
- S-19 not connected yet: the page is about 801 px for a 672 px view: the export shows its top only (as drawn); read back that the main column clips it
- S-01 top / middle / bottom: the page ends inside the bottom frame's view (est. page 1860 px); re-set the bottom scroll to page h − 672 if the drawn height differs
- every budgets row: read back each cell's text; no two adjacent texts closer than 16 px
- root 'E08-D09 / 01 healthy' at (0, 0): read back the name exactly after the first section call; size 4640 x 2758
- after touchTexts + relayout: the annotation column (estimated 2806 px) ends inside the root (h 2758); raise the root's h to its end + 80 if not
- frame 'SCR-147 · S-01 healthy · top · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-147 · S-01 healthy · middle · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-147 · S-01 healthy · bottom · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'SCR-147 · S-13 loading · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-147 · S-15 stale · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- frame 'SCR-147 · S-16 degraded · dark': read back 1280 x 800 at (2800, 960); clip on, no child spills
- frame 'SCR-147 · S-17 error: our counters not reporting · dark': read back 1280 x 800 at (80, 1840); clip on, no child spills
- frame 'SCR-147 · S-18 unavailable: the read itself failed · dark': read back 1280 x 800 at (1440, 1840); clip on, no child spills
- frame 'SCR-147 · S-19 not connected yet · dark': read back 1280 x 800 at (2800, 1840); clip on, no child spills
- export docs/design/E08/img/E08-D09-01-healthy.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (9)

- D09-G1 (§21.2 L699): a read of per-account, per-class usage, limit, window and headroom at 1 Hz, with the IP ho
- D09-G14 (§21.2 L712): the reserve figure per account
- D09-G10 (§21.2 L708): a fan-out cost read for the simulator
- D09-G3 (§21.2 L701): a read of the inspector: per-topic age, gap count, the per-request and per-socket figures
- D09-G5 (§21.2 L703): a clock read with last measured, next due and the state
- D09-G6 (§21.2 L704): a re-measure route and its cooldown
- D09-G7 (§21.2 L705): a force-reconnect route; the audit code connectivity.reconnect_forced registered
- D09-G9 (§21.2 L707): a usage-history read
- D09-G2 (§21.2 L700): the rate-budget provider behind /admin/capacity is not wired

## Spec gaps (0)

## Deviations (2)

- G-row marker line 'Waits on D09-Gn' on each waiting section: §0 asks for the mark, gives no string
- accounts Swing, Scalp, Hedge, Desk: kit aliases (only "Main" is a spec slot)

## Copy keys (29)

- W-09 (§15 L424; meter value text)
- W-13 (§15 L428; S-01)
- W-60 (§15 L475; budget row action)
- W-07 (§15 L422; per-class table caption)
- W-08 (§15 L423; column headers)
- W-06a (§15 L420; reserve band, not served (S-19))
- W-06b (§15 L421; reserve band, served)
- W-14 (§15 L429; S-02 (CMP-178 prefix verbatim))
- W-52 (§15 L467; blast radius)
- W-29 (§15 L444; clock ok)
- W-41 (§15 L457; simulator labels)
- W-44 (§15 L460; inspector disclosure)
- W-38 (§15 L454; clock offset)
- W-39 (§15 L455; next measurement)
- W-35 (§15 L450; re-measure)
- W-50 (§15 L465; force reconnect trigger, title, confirm)
- W-53 (§15 L468; private stream placeholder)
- W-05 (§15 L419; not wired (S-19))
- W-70 (§15 L480; history disclosure)
- W-02 (§15 L416; page `h1`; route name)
- W-03 (§15 L417; header meta)
- W-04 (§15 L418; old values)
- W-12 (§15 L427; origin action line)
- W-25 (§15 L440; S-17)
- W-11 (§15 L426; origin label)
- W-24 (§15 L439; S-16)
- W-26 (§15 L441; S-18)
- W-10 (§15 L425; per-minute fallback row)
- W-01 (§15 L415; board footer (verbatim))

## Copy gaps (3)

- "Admin area": the band region name, from §2.1 L171 (CMP-087 own string; not in §15)
- clock dl labels Offset, Last measured, Next due, State: §10 L348 prose
- Public WS / Private WS row-group words and second lines: §3.1 L211

## Fallbacks (7)

- fallback: CMP-178's ring glyph (§5.2) drawn as a 12 px ellipse outline, border.thick (no ring icon)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders; only CMP-087's band and rule and the SCR-147 page are drawn (§2.1, §2.2)
- fallback: CMP-015 Skeleton drawn as color.surface.hover bars (no library component in the file)
- fallback: CMP-178's clock glyph (§5.2) drawn with the local icon 'pending'
- fallback: CMP-178's octagon glyph drawn with the local icon 'danger'
- fallback: CMP-178's triangle glyph drawn with the local icon 'warning'

## Sources (1)

- spec E08-D09.md md5 9146d4d4 (§0 L83, §2, §3, §5.2, §15, §16, §17); hand-off E08-D09-handoff.md md5 3dc8240e

## Tokens (44)

- radius.badge
- color.surface.hover
- color.action.primary.default
- color.status.success.strong
- size.icon
- type.ui.body-strong
- color.text.primary
- space.inset.xs
- color.text.secondary
- radius.control
- type.ui.body
- type.ui.caption
- space.stack.xs
- space.inset.sm
- type.num.base
- color.surface.canvas
- color.surface.raised
- color.border.default
- color.neutral.default
- border.thick
- border.hairline
- radius.card
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
- color.text.link
- space.inset.lg
- space.stack.md
- type.ui.label
- color.text.on-action
- size.icon.sm
- space.stack.lg
- space.inset.md
- color.surface.selected
- color.surface.sunken
- space.button.paddingX
- color.action.secondary.default
- type.ui.heading-md
- color.surface.app
- color.border.subtle
- color.data-confidence.stale.indicator
- color.data-confidence.stale.text
- color.status.danger.strong
- color.status.warning.strong
