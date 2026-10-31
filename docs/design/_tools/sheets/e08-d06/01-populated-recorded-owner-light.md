# E08-D06 / 01 SCR-103∕populated-recorded-owner · light

File `E08-D06 boards`, page `E08-D06 SCR-103 Symbol info`; export `docs/design/E08/img/scr-103-populated-recorded-owner-light.png`; sheet `01-populated-recorded-owner-light.json` (validated); theme light.

Board 1L (§15 L614: §3). Grid (0, 12000); 1120 x 1786 px; footer "page E08-D06 SCR-103 Symbol info · board 01 · r3".

## Frames

- `SCR-103 · Populated, recorded · Owner · light · compact` (480 x 1360; Populated, recorded)

## Validator and size

- `01-populated-recorded-owner-light.json: 0 errors, 0 warnings, 23 sections, 54960 bytes` (exit 0)
- 23 sections, 54960 bytes

## Live checks (6)

- root 'E08-D06 / 01 SCR-103∕populated-recorded-owner · light' at (0, 12000): read back the name exactly after the first section call; size 1120 x 1786
- after touchTexts + relayout: the annotation column (estimated 1722 px) ends inside the root (h 1786); raise the root's h to its end + 80 if not
- frame 'SCR-103 · Populated, recorded · Owner · light · compact': read back 480 x 1360 at (80, 80); clip on, no child spills; its caption sits 28 px above it
- theme: activate the light token set before exporting board 1L (twin of 1D); read back one bound fill (color.surface.overlay) as the light value; nothing on the board is painted
- export docs/design/E08/img/scr-103-populated-recorded-owner-light.png: record the board id and the PNG size (1120 x 1786 at 1x)
- board 1L: same nodes as 1D; every fill and text colour is a token binding (nothing painted), so the light set re-binds them at export

## Derivations (5)

- SCR-103 · Populated, recorded · Owner · light · compact: sticky header 103 = the measured header 102 + the 1 px header rule (live-check fold)
- rules from instruments_after.json as delivered (tick 0.10, max qty 100.000, leverage 100.00) -> F3 0.1, 100, 100× (§5 L220)
- live from the recorded snapshot: last 82,751.2, index 82,782.37 (F4), volume 41,760.372 (F5), turnover 3.41 B (F7), change ▲ +1.23 %, funding +0.00771 % (F6), Updated 06:35:46 UTC
- countdown next in 01:24:13 · 08:00 UTC: next_funding_time_ms - ts_ms = 5053229 ms to go, floored to seconds (§7 L320)
- recording: 1 · 4 Sep 02:11–02:15 UTC, connection lost (F10: 02:11:00-02:14:20 rounded out), disk 812 GB (F7 of 812,340,221,100 bytes)

## Spec gaps (0)

## Deviations (0)

## Copy gaps (0)

## Fallbacks (3)

- kit choice (Q7): the drawer is 480 px wide; no size.drawer token exists (§2 D-14)
- the state glyphs (● ○ ◐ ▲ ▼ ✕) are text characters of the value string (§10.3 'Colour'), not icons
- kit choice: r2's numbered markers are not drawn on the frames; each marker is an annotation block naming its part ('at: ...') so no marker shifts the drawer's layout

## Spec cites (24)

- L419: "Symbol info: BTCUSDT" ("Symbol info:" visually hidden)
- L51: CMP-046 modal, right side, 480 CSS px
- L419: dialog, aria-modal="true", aria-labelledby the title, aria-describedby
- L397: the title (tabindex="-1")
- L487: symbol.info_viewed
- L420: section, aria-labelledby its h3
- L421: dd "0.1 USDT. Price must be a multiple of 0.1. Example: 50,000.04 beco
- L421: dl with one dt / dd pair per value (F8), units inside the text
- L39: Provenance in honest words:
- L39: updated_at is when the server fetched the catalogue
- L41: One freshness marker for the live band, in its header.
- L283: values, no marker (absence is live)
- L320: Next funding in 1 hour 24 minutes, at 08:00 UTC
- L330: The digits update at most once a second
- L424: text in aria-live="off"
- L47: The CandleViewer band reads and never subscribes:
- L474: GET /market/data-coverage?symbol= once per open (06 row 13: reads unde
- L99: Recorder settings
- L48: the SCR-140 link hidden (T3) for Manager and Viewer
- L428: CMP-021 a for Recorder settings
- L398: each control, ring color.focus.ring at border.focus
- L52: Both open a new panel, never the focused one, so no armed pane is reta
- L428: "Open BTCUSDT in a new chart", "Open BTCUSDT DOM ladder", "Recorder se
- L398: Close → band actions (Retry, Try again) → "Show all N tiers" → the tie

## Sources (2)

- Seed data: the r2 board script's DATA block, sha256 298c156f…e1a7, posted 2026-10-23 on #174 (values re-derived by the §5 formatters)
- spec E08-D06.md md5 af8763f0 (§15 L614); hand-off E08-D06-handoff.md md5 50667e8f; r2 data block sha256 298c156f

## Tokens (26)

- type.ui.heading-md
- color.text.primary
- space.inset.sm
- color.text.secondary
- size.icon
- radius.control
- type.ui.caption
- space.dialog.padding
- space.stack.sm
- color.border.default
- type.ui.body
- space.inset.xs
- type.num.base
- color.text.tertiary
- space.inset.lg
- type.ui.heading-sm
- space.stack.xs
- color.text.link
- type.ui.body-strong
- space.button.paddingX
- color.action.secondary.default
- space.stack.lg
- color.surface.overlay
- elevation.dialog
- type.ui.label
- color.surface.canvas
