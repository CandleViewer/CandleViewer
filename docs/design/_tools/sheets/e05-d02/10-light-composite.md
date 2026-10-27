# E05-D02 / 10 light-composite

File `E05-D02 boards`, page `E05-D02 slice 4 feedback and overlays` (render with `--page`); export `docs/design/E05/img/E05-D02-10-light-composite.png`; sheet `10-light-composite.json` (validated); theme light.

Validator: 10-light-composite.json: 0 errors, 9 warnings, 11 sections, 76321 bytes

## Blocks

- `CMP-001 · Button` — slice 1 L621-694; spec export `img/CMP-001-button.png`
- `CMP-012 · Badge` — slice 2 L467-540; spec export `img/CMP-012-badge-status-dot-count.png`
- `CMP-007 · TextInput` — slice 3 L522-603; spec export `img/CMP-007-textinput.png`
- `CMP-028 · Callout` — slice 4 L1365-1435; spec export `img/CMP-028-callout-banner.png`
- `CMP-045 · Toast` — slice 4 L1779-1860; spec export `img/CMP-045-toast-notification.png`
- `CMP-044 · ConfirmDialog` — slice 4 L1683-1778; spec export `img/CMP-044-confirmdialog.png`

## Content checks

- one light block per slice at least (s1 CMP-001; s2 CMP-012; s3 CMP-007; s4 CMP-028, CMP-045, CMP-044)
- status carried by glyph + words (callouts, toasts), never colour alone
- T2 cells: lock leads the full label / value, color.text.tertiary; reason color.text.secondary
- focus-visible cells carry CMP-039's 2 px color.focus.ring
- every specimen string issued by say() (copy gaps logged)

## Live checks for the drawer

- the file's light theme (semantic-light over semantic-dark) is active when board 10 renders and exports; the dark boards keep the dark theme
- board 10: rebind both 'scrim · …' rects' fill to palette.black (opacity.scrim kept) before export; the light export must show a black 60 % scrim, not light sunken
- render on page 'E05-D02 slice 4 feedback and overlays' (mkcall4.py … --page 'E05-D02 slice 4 feedback and overlays'; its default would be 'E05-D02')
- root 'E05-D02 / 10 light-composite': hugs its content (about 3833 x 1278 px estimated)

## Not drawn — the text is binding

- CMP-001: secondary and ghost (not contrast-critical: text on a neutral fill) — not drawn, the text is binding (slice 1 L621-694)
- CMP-001: hover, active, disabled and loading in light — not drawn, the text is binding (slice 1 L621-694)
- CMP-001: sizes sm / lg — not drawn, the text is binding (slice 1 L621-694)
- CMP-012: the dot on raised, overlay, hover, selected and sunken hosts (below 3:1 in light, slice 2 L503) — not drawn, the text is binding (slice 2 L467-540)
- CMP-012: 99+ and the count's long values — not drawn, the text is binding (slice 2 L467-540)
- CMP-007: hover, disabled, read-only, Value=empty and Affix=both in light (not contrast-critical beyond the drawn boundary and T2 cells) — not drawn, the text is binding (slice 3 L522-603)
- CMP-028: the default cell's CMP-023 progress, reconnecting, disconnected, band, dismissible and the hatched unprotected banner in light — not drawn, the text is binding (slice 4 L1365-1435)
- CMP-045: danger (no copy in the cell) — not drawn, the text is binding (slice 4 L1779-1860)
- CMP-045: focused, T2 action and undo in light — not drawn, the text is binding (slice 4 L1779-1860)
- CMP-044: typed, typed · match, hold, holding, armed, busy, partial failure and the order confirm in light (board 09 draws them dark) — not drawn, the text is binding (slice 4 L1683-1778)

## Strings used

- "Owner only: your role can't use this action." — CMP-001 slice 1 L621-694
- 'Save' — CMP-001 slice 1 L621-694
- 'Buy / Long' — CMP-001 slice 1 L621-694
- 'Sell / Short' — CMP-001 slice 1 L621-694
- 'Freeze sub_001 — cancel 3 working orders' — slice 4 (outside the CMP section)
- 'Enter your username.' — CMP-040 slice 3 L842-912
- 'trader_01' — CMP-007 slice 3 L522-603
- "Your role can't change settings." — CMP-040 slice 3 L842-912
- 'Reconnected — backfilling history' — CMP-028 slice 4 L1365-1435
- 'Recorded coverage catching up: 00:41 remaining.' — CMP-028 slice 4 L1365-1435
- 'Degraded — some data feeds are stale' — CMP-028 slice 4 L1365-1435
- 'Book and tape are live; 1 of 4 topics stale 6s. Recent trades may lag.' — CMP-028 slice 4 L1365-1435
- 'Trading locked: daily loss limit −2 % reached at 13:41 UTC.' — CMP-028 slice 4 L1365-1435
- 'Accepted — stop 63,900.0 held by the exchange · exchange id ends …5f60' — CMP-028 slice 4 L1365-1435
- 'Session extended. Idle timer reset. Next warning in 14:00.' — CMP-045 slice 4 L1779-1860
- 'Accepted — stop 63,900.0 held by the exchange' — CMP-045 slice 4 L1779-1860
- 'Open chart' — CMP-045 slice 4 L1779-1860
- 'Snooze ▾' — CMP-045 slice 4 L1779-1860
- 'Disable' — CMP-045 slice 4 L1779-1860
- 'Details' — CMP-045 slice 4 L1779-1860
- 'Warning · Alert' — CMP-045 slice 4 L1779-1860
- 'BTC above 65k' — CMP-045 slice 4 L1779-1860
- 'Last price 65,012.5 crossed above 65,000' — CMP-045 slice 4 L1779-1860
- 'BTCUSDT · 5m' — CMP-045 slice 4 L1779-1860
- 'What this does' — CMP-044 slice 4 L1683-1778
- 'Freeze sub_001 — cancel 3 working orders' — CMP-044 slice 4 L1683-1778
- 'Cancel' — CMP-044 slice 4 L1683-1778
- 'Freeze sub_001?' — CMP-044 slice 4 L1683-1778
- "Your role can't use the kill switch." — CMP-044 slice 4 L1683-1778

## Stamps

- PROPOSED · slice 1 A12 (slice 1 L333)
- PROPOSED · slice 1 D16 (slice 1 L529)
- PROPOSED · slice 1 D13 (slice 1 L481)
- PROPOSED · slice 3 G23 (slice 3 L418)
- PROPOSED · slice 4 H5 (slice 4 L562)
- PROPOSED · slice 1 A6 (slice 1 L294)
- PROPOSED · slice 4 H6 (slice 4 L577)
- PROPOSED · slice 4 H26 (slice 4 L786)
- PROPOSED · slice 4 H1 (slice 4 L520)
- PROPOSED · slice 4 H24 (slice 4 L756)
- PROPOSED · slice 4 H30 (slice 4 L830)

## Kit choices and deviations

- kit choice (specimen): Each state is a cell: the specimen on a color.surface.app plate (the matrix cells of slice 1 §1.1), its state caption under it in type.ui.caption color.text.secondary; cells sit in state rows led by a 120 px row label; a block is a color.surface.canvas card with a 1 px color.border.subtle edge
- kit choice (focus): A focus ring is CMP-039's 2 px color.focus.ring (border.focus) rect, positioned 2 px outside the control on a flex wrapper 4 px larger than it (radius.md = radius.control + 2, FALLBACKS RING)
- kit choice (t2): T2 (E09-D09 §2.2, slices 3-4 conventions 24 / 36-37; it supersedes slice 1 §3's trailing lock): the shape loses its enabled look (color.surface.raised fill, 1 px color.border.default hairline), the CMP-019 lock LEADS the full label, label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary (2a inline); icon-only controls carry a size.icon.sm lock badge bottom-right and a CMP-016 echo of the reason (2b); never color.text.disabled, never opacity.disabled on label, glyph or reason
- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS ICONS)
- kit choice (light): Board 10 is the only light board: the same construction as the dark blocks, drawn once; the light theme (semantic-light over semantic-dark) is applied through the file's theme at export
- kit choice (page): mkcall4.py derives a page from the board name ('E05-D02 / NN …' -> 'E05-D02'); the sheet carries its page in sheet['page'] and the renderer passes --page '<page>' (live check)

## Tokens and fallbacks

- token: the CMP-039 ring's radius (radius.control + 2 = 6 px, slice 1 §5.1, no token) binds the Tier-1 primitive radius.md (6 px; validator WARN)
- fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file's local 'icon / locked'
- fallback: the scrim is palette.black at opacity.scrim (s4 conventions 31, H1), a primitive colour the validator refuses: the sheet binds color.surface.sunken at opacity.scrim (E15-D06's SCRIM precedent); sunken is black only in dark, so the live step MUST rebind the two scrim rects to palette.black before the light export (s4 conventions 31: never color.surface.sunken)

## Copy gaps

- CMP-045 danger: the cell names 'an order rejection with Details' but gives no title or body: the danger toast is not drawn on board 10 (board 08 owns CMP-045)
- CMP-044 default: the 'What this does' group's sentences and the subtitle are SCR-072's (E39-D03 §4.1), not quoted in the cell: the group draws its label only

## Sources

- spec docs/design/E05/E05-D02.md at 966f9edcd md5 72dc9ede4f3ce6a4620ffd50816cb935 (frozen copy E05-D02@966f9edcd.md)
- spec docs/design/E05/E05-D02-data-display.md at 966f9edcd md5 fa72d69bce5362a9430f20a0feaf39a3 (frozen copy E05-D02-data-display@966f9edcd.md)
- spec docs/design/E05/E05-D02-form-controls.md at 966f9edcd md5 c768259c5a59fbf6161a52f0cb498b79 (frozen copy E05-D02-form-controls@966f9edcd.md)
- spec docs/design/E05/E05-D02-feedback-overlays.md at 966f9edcd md5 fb6e8b12d79fc6c057f0b695d495867d (frozen copy E05-D02-feedback-overlays@966f9edcd.md)
- Penpot file 'E05-D02 boards', page 'E05-D02 slice 4 feedback and overlays'; kit e05d02kit.py md5 1af7cacf448b9098924bf67629612f6b

## Shape count

- {"sheet": "10-light-composite.json", "shapes": 389, "texts": 174, "by_type": {"board": 180, "ellipse": 5, "icon": 15, "rect": 15, "text": 174}, "sections": 11, "bytes": 76321, "largest_section": 9292, "largest_compacted": 6146}
