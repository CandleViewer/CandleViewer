# E08-D06 / 25 SCR-103∕not-recorded-non-owner-view-as

File `E08-D06 boards`, page `E08-D06 SCR-103 Symbol info`; export `docs/design/E08/img/scr-103-not-recorded-non-owner-view-as-dark.png`; sheet `25-not-recorded-non-owner-view-as-dark.json` (validated); theme dark.

Board 25D (§15 L638: SOLUSDT; Manager or Viewer `rbac.owner_only`; viewing as `rbac.view_as`). Grid (12000, 9600); 1680 x 1549 px; footer "page E08-D06 SCR-103 Symbol info · board 25 · r3".

## Frames

- `SCR-103 · Not recorded, Manager or Viewer · SOLUSDT · dark · compact` (480 x 1220; Not recorded, Manager or Viewer)
- `SCR-103 · Not recorded, Owner viewing as · SOLUSDT · dark · compact` (480 x 1220; Not recorded, Owner viewing as)
- A: r2 drawer d25 (Manager or Viewer); B: d25B (Owner viewing as alex)

## Validator and size

- `25-not-recorded-non-owner-view-as-dark.json: 0 errors, 1 warnings, 29 sections, 79348 bytes` (exit 0)
- 29 sections, 79348 bytes

## Live checks (8)

- frame A: the recording band reads, in order, '○ Not recorded', 'Recorded data from' not available yet, 'Streams, last 90 days', "Only the owner can start recording.", "Recording is set up by the owner."; neither sentence is a button, link or aria-disabled control
- frame B: the same band reads "Read-only while viewing as alex." where frame A reads "Only the owner can start recording."; every other text equals frame A's
- CVD: run the colour-vision simulation (protanopia, deuteranopia) on the exported PNG; every state stays readable by its words and glyphs (§10.3 'Colour'); tritanopia deferred (no simulator output; a C-row to the tool's owner, ruling 2026-10-31)
- root 'E08-D06 / 25 SCR-103∕not-recorded-non-owner-view-as' at (12000, 9600): read back the name exactly after the first section call; size 1680 x 1549
- after touchTexts + relayout: the annotation column (estimated 1525 px) ends inside the root (h 1549); raise the root's h to its end + 80 if not
- frame 'SCR-103 · Not recorded, Manager or Viewer · SOLUSDT · dark · compact': read back 480 x 1220 at (80, 80); clip on, no child spills; its caption sits 28 px above it
- frame 'SCR-103 · Not recorded, Owner viewing as · SOLUSDT · dark · compact': read back 480 x 1220 at (640, 80); clip on, no child spills; its caption sits 28 px above it
- export docs/design/E08/img/scr-103-not-recorded-non-owner-view-as-dark.png: record the board id and the PNG size (1680 x 1549 at 1x)

## Derivations (12)

- SCR-103 · Not recorded, Manager or Viewer · SOLUSDT · dark · compact: sticky header 103 = the measured header 102 + the 1 px header rule (live-check fold)
- SCR-103 · Not recorded, Owner viewing as · SOLUSDT · dark · compact: sticky header 103 = the measured header 102 + the 1 px header rule (live-check fold)
- examples re-derived with Decimal: 148.1234 to tick 0.005 nearest = 148.125 (§5 L271); 0.0019 to step 0.001 down = 0.001; min notional 5; leverage step 0.01
- identity 'SOL / USDT · USDT perpetual · settled in USDT · listed 2020-04-01': base / quote, contract LinearPerpetual -> 'USDT perpetual' (§4.1), settle, launchTime 1585699200000 -> listed date (UTC)
- '0.005': SOLUSDT tick '0.005' in instruments_after.json -> 0.005 (§5 L220)
- 'USDT': SOLUSDT quote coin 'USDT' (the unit column, §3)
- '0.001': SOLUSDT step '0.001' in instruments_after.json -> 0.001 (§5 L220)
- 'SOL': SOLUSDT base coin 'SOL' (the unit column, §3)
- '100': SOLUSDT maxQty '100.000' in instruments_after.json -> 100 (§5 L220)
- '5': SOLUSDT minNotional '5' in instruments_after.json -> 5 (§5 L220)
- '100×': SOLUSDT maxLev '100.00' in instruments_after.json -> 100× (§5 L220)
- '8 h': SOLUSDT funding 480 in instruments_after.json -> 8 h (§5 L220)

## Spec gaps (0)

## Deviations (0)

## Copy gaps (3)

- 'SOL / USDT · USDT perpetual · settled in USDT · listed 2020-04-01': r2 substitution idSOL: L59 'BTC / USDT · USDT perpetual · settled in USDT · listed 2020-04-01' with 'BTC' -> 'SOL' per the fixture
- 'Rules revision 8 · checked 2 h ago': r2 substitution provSOL: L39 'Rules revision 7 · checked 2 h ago' with 'revision 7' -> 'revision 8' per L296
- 'Price must be a multiple of 0.005 · 148.1234 → 148.125 (nearest)': r2 substitution exSOL: L65 'Price must be a multiple of 0.1 · 50,000.04 → 50,000.0 (nearest)' with '0.1 ·' -> '0.005 ·' per SOLUSDT (fixture, after the tick change); '50,000.04 → 50,000.0' -> '148.1234 → 148.125' per SOLUSDT (fixture, after the tick change)

## Fallbacks (4)

- kit choice (Q7): the drawer is 480 px wide; no size.drawer token exists (§2 D-14)
- kit choice: SOLUSDT has no recorded ticker, so its live rows are drawn as labelled placeholder bars (r2's 'placeholder'), never invented values
- the state glyphs (● ○ ◐ ▲ ▼ ✕) are text characters of the value string (§10.3 'Colour'), not icons
- kit choice: r2's numbered markers are not drawn on the frames; each marker is an annotation block naming its part ('at: ...') so no marker shifts the drawer's layout

## Spec cites (6)

- L285: "○ Not recorded" (or its refusal); T2 in the sentence form (§8): "Only
- L429: text: CMP-026 description in CMP-079's sentence form; no control, glyp
- L48: the SCR-140 link hidden (T3) for Manager and Viewer, replaced by E09-D
- L363: a T2 reason never borrows the T3 sentence
- L286: as for a Manager or Viewer, with rbac.view_as "Read-only while viewing
- L52: Both open a new panel, never the focused one, so no armed pane is reta

## Sources (2)

- r2 board data: the DATA block of the posted board script (posted 2026-10-23, 4 parts), sha256 298c156f…e1a7; read as data only, every value re-derived by the kit
- spec E08-D06.md md5 af8763f0 (§15 L638); hand-off E08-D06-handoff.md md5 50667e8f; r2 data block sha256 298c156f

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
- color.surface.hover
- type.ui.body-strong
- space.button.paddingX
- color.action.secondary.default
- space.stack.lg
- color.surface.overlay
- elevation.dialog
- type.ui.label
- color.surface.canvas
