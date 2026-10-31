# E08-D06 / 23 SCR-103∕states-matrix

File `E08-D06 boards`, page `E08-D06 SCR-103 Symbol info`; export `docs/design/E08/img/scr-103-states-matrix-dark.png`; sheet `23-states-matrix-dark.json` (validated); theme dark.

Board 23D (§15 L636: §6). Grid (6000, 9600); 1920 x 1259 px; footer "page E08-D06 SCR-103 Symbol info · board 23 · r3".

## Frames

- `SCR-103 · States matrix · §6 · dark · compact` (1280 x 980; Populated, recorded, Not recorded, Not recorded, Manager or Viewer, Not recorded, Owner viewing as, Stale, T1, Stale, T2, Exchange feed down, Reconnecting, disconnected, Awaiting the first tick, Live unavailable, Not trading, Catalogue loading, Catalogue overdue, Rules changed while open, Contract load failed, Not in the instrument list, Forbidden, Coverage failed, Tiers unavailable, Recording restricted, Clock alarm, Opened from a replay surface, Demo / live)
- one table: a header row and the 23 §6 rows (r2 `matrix`)

## Validator and size

- `23-states-matrix-dark.json: 0 errors, 1 warnings, 23 sections, 63499 bytes` (exit 0)
- 23 sections, 63499 bytes

## Live checks (7)

- table: read back its height (estimated 863 px) and that the last row (Demo / live) ends at or above y 964 inside the frame; no cell text is clipped (each row's h >= its tallest cell's text + 8)
- the two T2 rows read back fill color.surface.sunken; every other body row has no fill
- CVD: run the colour-vision simulation (protanopia, deuteranopia) on the exported PNG; every state stays readable by its words and glyphs (§10.3 'Colour'); tritanopia deferred (no simulator output; a C-row to the tool's owner, ruling 2026-10-31)
- root 'E08-D06 / 23 SCR-103∕states-matrix' at (6000, 9600): read back the name exactly after the first section call; size 1920 x 1259
- after touchTexts + relayout: the annotation column (estimated 1148 px) ends inside the root (h 1259); raise the root's h to its end + 80 if not
- frame 'SCR-103 · States matrix · §6 · dark · compact': read back 1280 x 980 at (80, 80); clip on, no child spills; its caption sits 28 px above it
- export docs/design/E08/img/scr-103-states-matrix-dark.png: record the board id and the PNG size (1920 x 1259 at 1x)

## Derivations (0)

## Spec gaps (0)

## Deviations (1)

- §6's first column header "State (trigger)" (L281) is drawn "State"; the triggers are not drawn (they stay binding in the spec)

## Copy gaps (21)

- L285 column 3 (Recording in CandleViewer): a verbatim excerpt of 79 of the cell's 144 characters (r2's cell); the full cell binds
- L286 column 3 (Recording in CandleViewer): a verbatim excerpt of 57 of the cell's 121 characters (r2's cell); the full cell binds
- L287 column 2 (Live market): a verbatim excerpt of 60 of the cell's 162 characters (r2's cell); the full cell binds
- L288 column 2 (Live market): a verbatim excerpt of 72 of the cell's 149 characters (r2's cell); the full cell binds
- L290 column 2 (Live market): a verbatim excerpt of 74 of the cell's 178 characters (r2's cell); the full cell binds
- L291 column 2 (Live market): a verbatim excerpt of 62 of the cell's 84 characters (r2's cell); the full cell binds
- L292 column 2 (Live market): a verbatim excerpt of 73 of the cell's 142 characters (r2's cell); the full cell binds
- L293 column 2 (Live market): a verbatim excerpt of 60 of the cell's 87 characters (r2's cell); the full cell binds
- L293 column 3 (Recording in CandleViewer): a verbatim excerpt of 68 of the cell's 151 characters (r2's cell); the full cell binds
- L293 column 4 (Header, actions, announcement): a verbatim excerpt of 58 of the cell's 387 characters (r2's cell); the full cell binds
- L294 column 1 (Contract rules): a verbatim excerpt of 43 of the cell's 184 characters (r2's cell); the full cell binds
- L294 column 3 (Recording in CandleViewer): a verbatim excerpt of 64 of the cell's 116 characters (r2's cell); the full cell binds
- L296 column 1 (Contract rules): a verbatim excerpt of 40 of the cell's 98 characters (r2's cell); the full cell binds
- L297 column 1 (Contract rules): a verbatim excerpt of 75 of the cell's 358 characters (r2's cell); the full cell binds
- L298 column 1 (Contract rules): a verbatim excerpt of 72 of the cell's 165 characters (r2's cell); the full cell binds
- L300 column 3 (Recording in CandleViewer): a verbatim excerpt of 68 of the cell's 95 characters (r2's cell); the full cell binds
- L303 column 2 (Live market): a verbatim excerpt of 59 of the cell's 108 characters (r2's cell); the full cell binds
- L305 column 1 (Contract rules): a verbatim excerpt of 55 of the cell's 284 characters (r2's cell); the full cell binds
- L305 column 2 (Live market): a verbatim excerpt of 53 of the cell's 76 characters (r2's cell); the full cell binds
- L305 column 3 (Recording in CandleViewer): a verbatim excerpt of 23 of the cell's 71 characters (r2's cell); the full cell binds
- L305 column 4 (Header, actions, announcement): a verbatim excerpt of 53 of the cell's 177 characters (r2's cell); the full cell binds

## Fallbacks (1)

- kit choice: r2's numbered markers are not drawn on the frames; each marker is an annotation block naming its part ('at: ...') so no marker shifts the drawer's layout

## Spec cites (1)

- L307: Retry keeps focus on the button, sets aria-busy on its band and never

## Sources (2)

- r2 board data: the DATA block of the posted board script (posted 2026-10-23, 4 parts), sha256 298c156f…e1a7; read as data only, every value re-derived by the kit
- spec E08-D06.md md5 af8763f0 (§15 L636); hand-off E08-D06-handoff.md md5 50667e8f; r2 data block sha256 298c156f

## Tokens (17)

- type.ui.label
- color.text.secondary
- space.inset.sm
- space.inset.xs
- color.surface.raised
- color.text.primary
- type.ui.caption
- color.border.subtle
- color.surface.sunken
- type.ui.heading-sm
- color.surface.app
- space.stack.md
- space.inset.lg
- space.stack.xs
- color.text.tertiary
- space.stack.sm
- color.surface.canvas
