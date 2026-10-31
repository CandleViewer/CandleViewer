# E08-D09 / 05 clock

File `E08-D09 boards`, page `E08-D09 SCR-147 Connectivity`; export `docs/design/E08/img/E08-D09-05-clock.png`; sheet `05-clock.json` (validated); theme dark.

Board 05 of ten (§0 L87: S-09 warning, S-10 alarm with order entry halted, S-11 `10002` seen, S-12 not measured yet; the re-measure button busy and in cooldown). Grid (24000, 0); 4640 x 2270 px; footer W-01; "page E08-D09 SCR-147 Connectivity · board 05 · r1".

## Frames

- `SCR-147 · S-09 clock warning · dark` (S-09)
- `SCR-147 · S-10 clock alarm: order entry halted · dark` (S-10)
- `SCR-147 · S-11 10002 seen · dark` (S-11)
- `SCR-147 · S-12 clock not measured yet · dark` (S-12)
- `SCR-147 · re-measure busy · dark` (no S-id)
- `SCR-147 · re-measure cooldown · dark` (no S-id)

## Validator and size

- `05-clock.json: 0 errors, 1 warnings, 43 sections, 131492 bytes` (exit 0)
- 43 sections, 131492 bytes

## Live checks (18)

- frame 1 'SCR-147 · S-09 clock warning · dark': read back the Clock section's h2 'Clock' and the Re-measure control inside the main column's 672 px view (not clipped)
- frame 2 'SCR-147 · S-10 clock alarm: order entry halted · dark': read back the Clock section's h2 'Clock' and the Re-measure control inside the main column's 672 px view (not clipped)
- frame 3 'SCR-147 · S-11 10002 seen · dark': read back the Clock section's h2 'Clock' and the Re-measure control inside the main column's 672 px view (not clipped)
- frame 4 'SCR-147 · S-12 clock not measured yet · dark': read back the Clock section's h2 'Clock' and the Re-measure control inside the main column's 672 px view (not clipped)
- frame 5 'SCR-147 · re-measure busy · dark': read back the Clock section's h2 'Clock' and the Re-measure control inside the main column's 672 px view (not clipped)
- frame 6 'SCR-147 · re-measure cooldown · dark': read back the Clock section's h2 'Clock' and the Re-measure control inside the main column's 672 px view (not clipped)
- frames 1-3: the Clock tile's number and the dl's Offset row read the same W-38 sentence
- frame 4 (S-12): no figure in the Offset row; the text reads W-23's sentence, never '0' or 'In sync'
- frame 6: the T2 button shows the 'locked' icon first, then 'Re-measure now'; the reason sits under it
- root 'E08-D09 / 05 clock' at (24000, 0): read back the name exactly after the first section call; size 4640 x 2270
- after touchTexts + relayout: the annotation column (estimated 2411 px) ends inside the root (h 2270); raise the root's h to its end + 80 if not
- frame 'SCR-147 · S-09 clock warning · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-147 · S-10 clock alarm: order entry halted · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-147 · S-11 10002 seen · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'SCR-147 · S-12 clock not measured yet · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-147 · re-measure busy · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- frame 'SCR-147 · re-measure cooldown · dark': read back 1280 x 800 at (2800, 960); clip on, no child spills
- export docs/design/E08/img/E08-D09-05-clock.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (3)

- D09-G1 (§21.2 L699): a read of per-account, per-class usage, limit, window and headroom at 1 Hz, with the IP ho
- D09-G5 (§21.2 L703): a clock read with last measured, next due and the state
- D09-G6 (§21.2 L704): a re-measure route and its cooldown

## Spec gaps (0)

## Deviations (4)

- board 05 / 09 windows draw the page's band, header, summary strip and the Clock section only (§2.2 L180): Rate budgets, the simulator and the inspector, which sit between them, are left out so the clock is in the 672 px view (a focus crop; board 01 draws the whole page)
- G-row marker line 'Waits on D09-Gn' on each waiting section: §0 asks for the mark, gives no string
- re-measure cooldown: 30 s implied (ran 10 s before as of, W-36b's 20 s left); the server's cooldown is unspecified (D09-G6)
- summary strip on board 05: REST budget and Private streams in S-19 (D09-G1), Public market data 'Within budget' with W-52's '3 connections', IP hold 'Within budget' (D09-G13 assumed served): fixed across the six frames; only the Clock tile varies

## Copy keys (18)

- W-37 (§15 L453; clock consequences)
- W-22 (§15 L437; S-10, S-11)
- W-27 (§15 L442; S-11)
- W-39 (§15 L455; next measurement)
- W-38 (§15 L454; clock offset)
- W-05 (§15 L419; not wired (S-19))
- W-52 (§15 L467; blast radius)
- W-13 (§15 L428; S-01)
- W-21 (§15 L436; S-09)
- W-11 (§15 L426; origin label)
- W-35 (§15 L450; re-measure)
- W-02 (§15 L416; page `h1`; route name)
- W-03 (§15 L417; header meta)
- W-12 (§15 L427; origin action line)
- W-23 (§15 L438; S-12)
- W-29 (§15 L444; clock ok)
- W-36b (§15 L452; T2 reason, cooldown)
- W-01 (§15 L415; board footer (verbatim))

## Copy gaps (2)

- clock dl labels 'State', 'Offset', 'Measurement', 'Next due': §10 Fields L355 names the fields (offset, last measured, next due, the alarm state) but §15 gives no dt string
- "Admin area": the band region name, from §2.1 L171 (CMP-087 own string; not in §15)

## Fallbacks (4)

- fallback: CMP-178's ring glyph (§5.2) drawn as a 12 px ellipse outline, border.thick (no ring icon)
- fallback: CMP-178's triangle glyph drawn with the local icon 'warning'
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders; only CMP-087's band and rule and the SCR-147 page are drawn (§2.1, §2.2)
- fallback: CMP-178's octagon glyph drawn with the local icon 'danger'

## Sources (1)

- spec E08-D09.md md5 30646600 (§0 L87, §2, §3, §5.2, §15, §16, §17); hand-off E08-D09-handoff.md md5 e6bb50a9

## Tokens (39)

- type.ui.heading-sm
- color.text.link
- color.neutral.default
- border.thick
- type.ui.body-strong
- color.text.primary
- type.ui.caption
- color.text.tertiary
- space.inset.xs
- color.surface.raised
- radius.card
- space.inset.lg
- space.stack.sm
- color.status.success.strong
- size.icon
- type.num.base
- color.status.warning.strong
- space.stack.md
- color.text.secondary
- type.ui.body
- space.inset.sm
- space.stack.xs
- space.button.paddingX
- radius.control
- color.action.secondary.default
- type.ui.heading-md
- space.stack.lg
- color.surface.app
- color.surface.hover
- color.surface.selected
- color.border.subtle
- space.inset.md
- color.status.danger.strong
- color.focus.ring
- border.focus
- color.border.default
- border.hairline
- type.ui.label
- color.surface.canvas
