# E12-D07 / 04 row-states

File `E12-D07 boards`, page `E12-D07 SCR-045 data table`; export `docs/design/E12/img/E12-D07-04-row-states.png`; sheet `04-row-states.json` (validated); theme dark.

Board 04 of ten (§0 L78: every `state` word of §6 on one board, the closed row unmarked, the stale caption clause). Grid (18000, 0); 3280 x 2414 px; footer "page E12-D07 SCR-045 data table · board 04 · r1".

## Frames

- `SCR-045∕states∕all-words · dark`
- `SCR-045∕states∕stale-caption · dark`
- SCR-045∕states∕all-words · dark: 1280 x 800 window, one chart panel, table open in place (time 1m, 13:24-13:42, 19 rows)
- SCR-045∕states∕stale-caption · dark: 1280 x 800 window, one chart panel, table open in place (time 1m, 13:24-13:42, 19 rows)

## Validator and size

- `04-row-states.json: 0 errors, 88 warnings, 47 sections, 147663 bytes` (exit 0)
- 47 sections, 147663 bytes

## Live checks (11)

- root 'E12-D07 / 04 row-states' at (18000, 0): read back the name exactly after the first section call (a mismatch makes a duplicate root); size 3280 x 2414
- after touchTexts + relayout: the annotation column (estimated 2539 px) ends inside the root (h 2414); raise the root's h if not
- frame 'SCR-045∕states∕all-words · dark': read back 1280 x 800 at (80, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕states∕stale-caption · dark': read back 1280 x 800 at (1440, 80) after relayout; no child overflows it (clip on)
- export docs/design/E12/img/E12-D07-04-row-states.png: the PNG's frames are each 1280 x 800 device px; record the board id and the PNG size
- read back the focused row's ring on SCR-045∕states∕all-words · dark: row 06 (13:29, Est.·POC) stroke 2 px color.focus.ring, inner
- read back the `state` cell texts on SCR-045∕states∕all-words · dark top to bottom: —, POC, —, Est., —, Est.·POC, —, width capped, —, no range, —, —, —, stale, —, —, —, corrected, forming (19 rows)
- measure the `state` column on SCR-045∕states∕all-words · dark: 95 px (12 characters, Equi-volume, §5)
- read back the caption's last clause on SCR-045∕states∕stale-caption · dark: "values as of 13:42:05"
- read back the status-row chip on SCR-045∕states∕stale-caption · dark: "Stale 7s · last 13:42:05" with the warning glyph
- on SCR-045∕states∕stale-caption · dark: every closed row's `state` reads stale and its values bind color.text.secondary; the last row reads forming

## Spec gaps (4)

- §6 L231: POC is "the visible range's POC bar" (one bar), yet the board shows both `POC` (13:25) and `Est.·POC` (13:29) so each form appears (build notes §4); in a live table only one row of a visible range carries POC
- §6 L228: `width capped` is drawn on 13:31 as a tagged specimen; its computed N is 1.0 (the name shows it, ruling P-3), below the cap (14 r rounds above 48), which is the chart's equi-volume rule (D06:311), not recomputed by the table
- §6 L227 / §6.2: the specimen `stale` on all-words (13:37) is one row of a stale snapshot; stale-caption shows the real case, every row of that snapshot `stale`
- §6 accessible-name join: the spec gives each word's addition, not the separator; the annotation joins the row name and the additions with ", " (E11-D04's row name form)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (2)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the expander, check and sort glyphs
- fallback: color.text.buy / color.text.sell (E11-D04 CR-D04-2 = E11-D02 CR-5, unregistered) drawn as color.buy.default / color.sell.default; the sign (+ / −) is the carrier (D04E11 §5.4)

## Sources (2)

- E12-D07 §6 L219-232 (the words and name additions), §6.2 L240-242, §5 (equi-volume state width), §0 L78; E11-D04 :183 (Est.·POC), :254 (forming describedby), :264 (values as of), :59 (stale chip)
- spec E12-D07.md md5 d8bbf958 (§0 L78); hand-off §H; E11-D04 §2, §5, §6, §10 (md5 02f3ff69); E12-D04 board kit (chrome geometry)

## Tokens (33)

- color.text.secondary
- size.icon.sm
- type.num.sm
- color.text.primary
- space.inset.sm
- color.buy.default
- color.surface.canvas
- color.sell.default
- color.surface.raised
- color.focus.ring
- border.focus
- type.ui.caption
- color.text.tertiary
- type.ui.label
- color.border.default
- border.hairline
- radius.control
- space.inset.xs
- space.stack.xs
- color.surface.selected
- size.icon
- color.env.demo
- radius.badge
- radius.card
- type.ui.heading-sm
- space.inset.lg
- space.inset.md
- color.surface.hover
- color.surface.app
- color.surface.sunken
- color.status.warning.strong
- type.ui.body
- space.stack.sm
