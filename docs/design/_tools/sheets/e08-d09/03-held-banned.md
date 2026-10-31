# E08-D09 / 03 held-banned

File `E08-D09 boards`, page `E08-D09 SCR-147 Connectivity`; export `docs/design/E08/img/E08-D09-03-held-banned.png`; sheet `03-held-banned.json` (validated); theme dark.

Board 03 of ten (§0 L85: S-04 held by IP (all accounts, time left, its condition sentence W-33); S-05 banned (placeholder, contract-first) side by side). Grid (12000, 0); 3280 x 1455 px; footer W-01; "page E08-D09 SCR-147 Connectivity · board 03 · r1".

## Frames

- `SCR-147 · S-04 held by IP · dark` (S-04)
- `SCR-147 · S-05 banned · dark` (S-05)

## Validator and size

- `03-held-banned.json: 0 errors, 1 warnings, 26 sections, 106676 bytes` (exit 0)
- 26 sections, 106676 bytes

## Live checks (9)

- S-04 frame: read back the hold panel's state line 'On hold — all accounts' and 'Our hold ends at 14:10:31 (in 8m 20s)'; the IP hold tile shows the same time
- S-05 frame: read back 'Time left: not received' in both the panel and the IP hold tile; no W-31 text on either frame (search the frames for 'reserved budget')
- each frame: scrolled 180 px (S-05 210 px), the summary strip's top sits at about y 16 in the main column; three account rows show under the hold panel
- each frame: the hold panel's stroke is the state's tone token (color.status.danger.strong)
- root 'E08-D09 / 03 held-banned' at (12000, 0): read back the name exactly after the first section call; size 3280 x 1455
- after touchTexts + relayout: the annotation column (estimated 1430 px) ends inside the root (h 1455); raise the root's h to its end + 80 if not
- frame 'SCR-147 · S-04 held by IP · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-147 · S-05 banned · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E08/img/E08-D09-03-held-banned.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (3)

- D09-G14 (§21.2 L712): the reserve figure per account
- D09-G1 (§21.2 L699): a read of per-account, per-class usage, limit, window and headroom at 1 Hz, with the IP ho
- D09-G13 (§21.2 L711): the IP lockout state and its time left in a read

## Spec gaps (0)

## Deviations (1)

- G-row marker line 'Waits on D09-Gn' on each waiting section: §0 asks for the mark, gives no string

## Copy keys (22)

- W-16 (§15 L431; S-04)
- W-11 (§15 L426; origin label)
- W-34 (§15 L449; what not to do)
- W-33 (§15 L448; the condition, exchange IP hold (S-04, S-05))
- W-32 (§15 L447; reads under a hold (S-04, S-05))
- W-12 (§15 L427; origin action line)
- W-07 (§15 L422; per-class table caption)
- W-08 (§15 L423; column headers)
- W-09 (§15 L424; meter value text)
- W-60 (§15 L475; budget row action)
- W-06a (§15 L420; reserve band, not served (S-19))
- W-05 (§15 L419; not wired (S-19))
- W-52 (§15 L467; blast radius)
- W-13 (§15 L428; S-01)
- W-29 (§15 L444; clock ok)
- W-02 (§15 L416; page `h1`; route name)
- W-03 (§15 L417; header meta)
- W-17 (§15 L432; S-05)
- W-50 (§15 L465; force reconnect trigger, title, confirm)
- W-36 (§15 L451; T2 reason, hold)
- W-35 (§15 L450; re-measure)
- W-01 (§15 L415; board footer (verbatim))

## Copy gaps (2)

- budget table headings "Meter" and "State": §3.2 L226 and L227 (W-08 lists six)
- "Admin area": the band region name, from §2.1 L171 (CMP-087 own string; not in §15)

## Fallbacks (4)

- fallback: CMP-178's clock glyph (§5.2) drawn with the local icon 'pending'
- fallback: CMP-178's ring glyph (§5.2) drawn as a 12 px ellipse outline, border.thick (no ring icon)
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders; only CMP-087's band and rule and the SCR-147 page are drawn (§2.1, §2.2)
- fallback: CMP-178's octagon glyph drawn with the local icon 'danger'

## Sources (1)

- spec E08-D09.md md5 30646600 (§0 L85, §2, §3, §5.2, §15, §16, §17); hand-off E08-D09-handoff.md md5 e6bb50a9

## Tokens (35)

- type.ui.caption
- color.text.secondary
- color.status.danger.strong
- size.icon
- type.ui.body-strong
- color.text.primary
- type.ui.body
- space.inset.xs
- color.surface.raised
- radius.card
- space.inset.lg
- space.stack.sm
- border.hairline
- space.inset.sm
- color.surface.canvas
- radius.badge
- color.surface.hover
- radius.control
- space.stack.xs
- type.num.base
- color.border.default
- color.neutral.default
- border.thick
- color.text.tertiary
- type.ui.heading-sm
- color.text.link
- color.status.success.strong
- space.stack.md
- type.ui.heading-md
- space.stack.lg
- color.surface.app
- color.surface.selected
- color.border.subtle
- space.inset.md
- type.ui.label
