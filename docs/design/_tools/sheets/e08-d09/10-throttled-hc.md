# E08-D09 / 10 throttled-hc

File `E08-D09 boards`, page `E08-D09 SCR-147 Connectivity`; export `docs/design/E08/img/E08-D09-10-throttled-hc.png`; sheet `10-throttled-hc.json` (validated); theme hc.

Board 10 of ten (§0 L92: high-contrast twin of 02). Grid (24000, 3200); 3280 x 1989 px; footer W-01; "page E08-D09 SCR-147 Connectivity · board 10 · r1".

## Frames

- `SCR-147 · S-02 approaching limit · hc` (S-02)
- `SCR-147 · S-03 throttled · hc` (S-03)

## Validator and size

- `10-throttled-hc.json: 0 errors, 1 warnings, 21 sections, 74497 bytes` (exit 0)
- 21 sections, 74497 bytes

## Live checks (11)

- root 'E08-D09 / 10 throttled-hc' at (24000, 3200): read back the name exactly after the first section call; size 3280 x 1989
- after touchTexts + relayout: the annotation column (estimated 1953 px) ends inside the root (h 1989); raise the root's h to its end + 80 if not
- frame 'SCR-147 · S-02 approaching limit · hc': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-147 · S-03 throttled · hc': read back 1280 x 800 at (1440, 80); clip on, no child spills
- theme: activate the hc token set before exporting board 10 (twin of 02); read back one bound fill (color.surface.canvas) as the hc value
- export docs/design/E08/img/E08-D09-10-throttled-hc.png: every frame is 1280 x 800; record the board id and the PNG size
- frame S-02: row 01's state cell reads "Exchange", the warning glyph, "Attention: near limit", "88 % of the spendable budget used"; Headroom "1 · 12 %"
- frame S-03: row 01's state cell reads "Throttled" and "Retry at 14:02:53 (in 42 s)"; Headroom "0 · 0 %"; the S-03 detail shows "Main, order", "Limit 10 requests per second", "code 10006"
- both frames: the reserve band has 2 rows "Reserved for stops and cancels · <alias>" with "2 requests"; no text overlaps a neighbour in any budgets row (cells 8 px padded a side)
- both frames: the REST budget tile's state word equals row 01's state word
- after relayout: each frame's main column clips the page (scroll recorded in the frame block); the S-03 detail and the reserve band end inside the 704 px body

## G rows (2)

- D09-G1 (§21.2 L699): a read of per-account, per-class usage, limit, window and headroom at 1 Hz, with the IP ho
- D09-G14 (§21.2 L712): the reserve figure per account

## Spec gaps (0)

## Deviations (4)

- G-row marker line 'Waits on D09-Gn' on each waiting section: §0 asks for the mark, gives no string
- account Swing: a kit alias (only "Main" is a spec slot)
- reserve 2 requests per account per 1 s order window: an illustrative W-06b slot; D09-G14 serves the real figure
- meter fill for S-02 and S-03 uses the warning tone (the register's color.status.warning.strong for both states, §5.2); §16 lists CMP-023's three fills

## Copy keys (18)

- W-09 (§15 L424; meter value text)
- W-14 (§15 L429; S-02 (CMP-178 prefix verbatim))
- W-11 (§15 L426; origin label)
- W-60 (§15 L475; budget row action)
- W-13 (§15 L428; S-01)
- W-07 (§15 L422; per-class table caption)
- W-08 (§15 L423; column headers)
- W-06a (§15 L420; reserve band, not served (S-19))
- W-06b (§15 L421; reserve band, served)
- W-52 (§15 L467; blast radius)
- W-29 (§15 L444; clock ok)
- W-02 (§15 L416; page `h1`; route name)
- W-03 (§15 L417; header meta)
- W-12 (§15 L427; origin action line)
- W-15 (§15 L430; S-03)
- W-31 (§15 L446; the condition, per-account throttle (S-03))
- W-34 (§15 L449; what not to do)
- W-01 (§15 L415; board footer (verbatim))

## Copy gaps (4)

- budget table headings "Meter" and "State": §3.2 L226 and L227 (W-08 lists six)
- "Admin area": the band region name, from §2.1 L171 (CMP-087 own string; not in §15)
- Used now and Window cells print the figure; the unit "requests" is in the meter's aria-valuetext (W-09), per R-3's "in the cell, the header or the accessible name"
- IP hold tile at S-01 has no number string in §15 (no W-n for the IP figure when healthy)

## Fallbacks (3)

- fallback: CMP-178's triangle glyph drawn with the local icon 'warning'
- fallback: CMP-178's ring glyph (§5.2) drawn as a 12 px ellipse outline, border.thick (no ring icon)
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders; only CMP-087's band and rule and the SCR-147 page are drawn (§2.1, §2.2)

## Sources (1)

- spec E08-D09.md md5 9146d4d4 (§0 L92, §2, §3, §5.2, §15, §16, §17); hand-off E08-D09-handoff.md md5 3dc8240e

## Tokens (36)

- type.ui.caption
- color.text.secondary
- color.status.warning.strong
- size.icon
- type.ui.body-strong
- color.text.primary
- type.ui.body
- space.inset.xs
- radius.badge
- color.surface.hover
- radius.control
- space.stack.xs
- space.inset.sm
- type.num.base
- color.surface.canvas
- color.status.success.strong
- color.action.primary.default
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
- type.ui.heading-md
- space.stack.lg
- color.surface.app
- color.surface.selected
- color.border.subtle
- space.inset.md
- type.ui.label
