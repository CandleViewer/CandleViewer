# E08-D09 / 07 inspector-history

File `E08-D09 boards`, page `E08-D09 SCR-147 Connectivity`; export `docs/design/E08/img/E08-D09-07-inspector-history.png`; sheet `07-inspector-history.json` (validated); theme dark.

Board 07 of ten (§0 L89: the inspector with 3 connections at 36, 120 and 480 topic rows (the last past the threshold); S-14 inspector empty; the history sparkline and its table; history empty). Grid (6000, 3200); 4640 x 2758 px; footer W-01; "page E08-D09 SCR-147 Connectivity · board 07 · r1".

## Frames

- `SCR-147 · inspector · 36 topic rows · dark` (no S-id)
- `SCR-147 · inspector · 120 topic rows · dark` (no S-id)
- `SCR-147 · inspector · 480 topic rows · dark` (no S-id)
- `SCR-147 · S-14 empty · dark` (S-14)
- `SCR-147 · history sparkline and table · dark` (no S-id)
- `SCR-147 · history empty · dark` (no S-id)
- `SCR-147 · S-19 not connected yet · inspector and history · dark` (S-19)

## Validator and size

- `07-inspector-history.json: 0 errors, 1 warnings, 93 sections, 217788 bytes` (exit 0)
- 93 sections, 217788 bytes

## Live checks (14)

- inspector frames: read back the disclosure labels 'Subscriptions (3 connections, 36 topics)', '(… 120 topics)', '(… 480 topics)' and each socket header's 'Binding: topics per request'
- each frame: the drawn section's top sits at about y 16 in the main column (scroll offset in its note); if not, set the page's y so it does
- history frame: 60 sparkline marks, the tallest 8 of 10 (scaled to the limit); the table's first row is 14:01 with 8
- 120 and 480 frames: the grid viewport is 512 px high and clips; the scroll thumb sits inside it
- root 'E08-D09 / 07 inspector-history' at (6000, 3200): read back the name exactly after the first section call; size 4640 x 2758
- after touchTexts + relayout: the annotation column (estimated 2658 px) ends inside the root (h 2758); raise the root's h to its end + 80 if not
- frame 'SCR-147 · inspector · 36 topic rows · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-147 · inspector · 120 topic rows · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-147 · inspector · 480 topic rows · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'SCR-147 · S-14 empty · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-147 · history sparkline and table · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- frame 'SCR-147 · history empty · dark': read back 1280 x 800 at (2800, 960); clip on, no child spills
- frame 'SCR-147 · S-19 not connected yet · inspector and history · dark': read back 1280 x 800 at (80, 1840); clip on, no child spills
- export docs/design/E08/img/E08-D09-07-inspector-history.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (3)

- D09-G3 (§21.2 L701): a read of the inspector: per-topic age, gap count, the per-request and per-socket figures
- D09-G4 (§21.2 L702): resubscribe and snapshot re-seed counters; dropped-update and queue figures in a read
- D09-G9 (§21.2 L707): a usage-history read

## Spec gaps (0)

## Deviations (3)

- G-row marker line 'Waits on D09-Gn' on each waiting section: §0 asks for the mark, gives no string
- 'sections 2 to 4 (summary strip, Rate budgets, Fan-out simulator), scrolled out of view': the sections above are scrolled out of the view and stand in as one unfilled 1500 px block (drawn on board 01); the scroll offset in the main column's note is therefore nominal
- 'sections 2 to 7 (summary strip to Actions), scrolled out of view': the sections above are scrolled out of the view and stand in as one unfilled 2100 px block (drawn on board 01); the scroll offset in the main column's note is therefore nominal

## Copy keys (21)

- W-44 (§15 L460; inspector disclosure)
- W-47 (§15 L463; binding limit)
- W-45 (§15 L461; socket label)
- W-13 (§15 L428; S-01)
- W-46 (§15 L462; per-request figures)
- W-52 (§15 L467; blast radius)
- W-48 (§15 L464; topic row)
- W-39 (§15 L455; next measurement)
- W-29 (§15 L444; clock ok)
- W-35 (§15 L450; re-measure)
- W-50 (§15 L465; force reconnect trigger, title, confirm)
- W-70 (§15 L480; history disclosure)
- W-02 (§15 L416; page `h1`; route name)
- W-03 (§15 L417; header meta)
- W-30 (§15 L445; S-14)
- W-72 (§15 L482; trend label)
- W-71 (§15 L481; window)
- W-08 (§15 L423; column headers)
- W-73 (§15 L483; history empty)
- W-05 (§15 L419; not wired (S-19))
- W-01 (§15 L415; board footer (verbatim))

## Copy gaps (4)

- connection header "connected since {t}", "{n} reconnects in the last hour", "ping {n} ms": §9 L335 names the fields, the deck has no strings
- inspector column headings "Topic", "Last message", "Gaps", "Last resubscribe", "Last re-seed": §9 L335 (topic row fields)
- "Admin area": the band region name, from §2.1 L171 (CMP-087 own string; not in §15)
- history table headings "Time", "Used (requests per second)", "Limit (requests per second)": §14 L403 ("Time, Used, Limit, unit in the header")

## Fallbacks (3)

- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders; only CMP-087's band and rule and the SCR-147 page are drawn (§2.1, §2.2)
- fallback: CMP-178's ring glyph (§5.2) drawn as a 12 px ellipse outline, border.thick (no ring icon)
- fallback: CMP-024's line drawn as stepped 2 px column marks (no path primitive in cvsheet)

## Sources (1)

- spec E08-D09.md md5 30646600 (§0 L89, §2, §3, §5.2, §15, §16, §17); hand-off E08-D09-handoff.md md5 e6bb50a9

## Tokens (36)

- color.text.secondary
- size.icon
- type.ui.body-strong
- color.text.primary
- space.inset.xs
- space.inset.sm
- radius.control
- type.ui.caption
- color.surface.canvas
- color.border.default
- color.status.success.strong
- type.ui.body
- type.num.base
- space.inset.lg
- space.inset.md
- space.stack.xs
- color.surface.sunken
- color.surface.hover
- color.surface.raised
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
- space.button.paddingX
- color.action.secondary.default
- type.ui.heading-md
- space.stack.lg
- color.surface.app
- color.surface.selected
- color.border.subtle
- radius.badge
- color.border.strong
- color.neutral.default
- border.thick
- color.action.primary.default
- border.hairline
- type.ui.label
