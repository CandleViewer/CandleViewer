# E12-D07 / 02 tick-volume-delta

File `E12-D07 boards`, page `E12-D07 SCR-045 data table`; export `docs/design/E12/img/E12-D07-02-tick-volume-delta.png`; sheet `02-tick-volume-delta.json` (validated); theme dark.

Board 02 of ten (§0 L75: the non-time row header (§2.2); tick's `trades`; the volume and delta variants as frames of one board, delta's `buy` and `sell` among them; `close time` and `duration` as auto columns). Grid (6000, 0); 3280 x 2644 px; footer "page E12-D07 SCR-045 data table · board 02 · r1".

## Frames

- `SCR-045∕tick∕default · dark`
- `SCR-045∕tick∕wide-auto · dark`
- `SCR-045∕volume∕default · dark`
- `SCR-045∕delta∕default · dark`
- tick/default: tick set, RightRail open, P columns only; bar 3 of 5 focused (spec §2.2 L134–137, §3.1 L156)
- tick/wide-auto: + close time, duration (§3.1 L162–163, §5 L207, §7.4 L278); bar 3 of 5 focused
- volume/default: volume set + auto columns; bar k of 8 at the sweep (§3.2 L174, §5 L208)
- delta/default: delta set + buy, sell, close time, duration (§3.1 L157–158, §3.2 L176, §5 L210)
- Walkthrough (hand-off §E L59): a tick row says when it opened and its position (row header), when it closed and how long it took (row name close clause, §2.2 L137; the wide frame's cells), and its `trades`
- Copy: W-10 (spec L353), W-11 (L354), W-12 (L355), W-14 (L357); theme dark; export docs/design/E12/img/E12-D07-02-tick-volume-delta.png

## Validator and size

- `02-tick-volume-delta.json: 0 errors, 181 warnings, 100 sections, 353801 bytes` (exit 0)
- 100 sections, 353801 bytes

## Live checks (15)

- frame 'SCR-045∕tick∕default · dark': read back row 06's stroke = 2 px color.focus.ring (inner) and its row header text '10:22:11.412 bar 3 of 5'
- frame 'SCR-045∕tick∕default · dark': read back the header words time · open · high · low · close · volume · delta · trades · state and 20 body rows; the caption contains 'Bar order · not time' and 'each bar closes at 1,000 trades'
- frame 'SCR-045∕tick∕wide-auto · dark': read back row 06's stroke = 2 px color.focus.ring (inner) and its row header text '10:22:11.412 bar 3 of 5'
- frame 'SCR-045∕tick∕wide-auto · dark': read back the header words time · open · high · low · close · volume · delta · trades · state · close time · duration and 20 body rows; the caption contains 'Bar order · not time' and 'each bar closes at 1,000 trades'
- frame 'SCR-045∕volume∕default · dark': read back the header words time · open · high · low · close · volume · delta · state · close time · duration and 20 body rows; the caption contains 'Bar order · not time' and 'each bar closes at 50 BTC of volume'
- frame 'SCR-045∕delta∕default · dark': read back the header words time · open · high · low · close · volume · delta · buy · sell · state · close time · duration and 20 body rows; the caption contains 'Bar order · not time' and 'each bar closes at 25 BTC of delta either way'
- root 'E12-D07 / 02 tick-volume-delta' at (6000, 0): read back the name exactly after the first section call (a mismatch makes a duplicate root); size 3280 x 2644
- after touchTexts + relayout: the annotation column (estimated 2832 px) ends inside the root (h 2644); raise the root's h if not
- frame 'SCR-045∕tick∕default · dark': read back 1280 x 800 at (80, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕tick∕wide-auto · dark': read back 1280 x 800 at (1440, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕volume∕default · dark': read back 1280 x 800 at (80, 960) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕delta∕default · dark': read back 1280 x 800 at (1440, 960) after relayout; no child overflows it (clip on)
- export docs/design/E12/img/E12-D07-02-tick-volume-delta.png: the PNG's frames are each 1280 x 800 device px; record the board id and the PNG size
- frame tick∕default: the RightRail is 240 px wide (open) and the dock 976; the header has no `close time` or `duration`
- frames tick∕wide-auto, volume∕default, delta∕default: the RightRail is the 48 px strip and the header ends `state · close time · duration`

## Spec gaps (5)

- A-1: at 1280 the one panel is 1,168 CSS px and tick's auto set (1,004.4, §5 L207) fits, so tick/default and tick/wide-auto would be one picture; tick/default opens the RightRail (dock 976) so the auto columns stay hidden there
- A-2: §2.2 L137's example “closed 10:22:14.020 after 0:02.6” cannot hold under its own rule (L135): bars sharing one open time are consecutive, so bars 1–4 of 5 close at 10:22:11.412 after 0:00.0; the data keeps the rule and the example string is not drawn
- A-8: hand-off §H L95's recorded fixtures cannot build tick / volume / delta bars; seeded synthetic stream, the instrument's tick size and qty step from the fixture
- A-11: the caption's date sits inside the visible-range clause
- A-12: color.text.buy / color.text.sell unregistered: signed cells use color.buy.default / color.sell.default, the sign carries the meaning

## Deviations (0)

## Copy keys (6)

- W-10 (§13 L353, verbatim)
- W-11 (§13 L354, PROPOSED, the registry's unit)
- W-19 (§13 L362, PROPOSED)
- W-21 (§13 L364, PROPOSED)
- W-12 (§13 L355, PROPOSED, the registry's unit)
- W-14 (§13 L357, PROPOSED, the registry's unit)

## Copy gaps (0)

## Fallbacks (2)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the expander, check and sort glyphs
- fallback: color.text.buy / color.text.sell (E11-D04 CR-D04-2 = E11-D02 CR-5, unregistered) drawn as color.buy.default / color.sell.default; the sign (+ / −) is the carrier (D04E11 §5.4)

## Sources (1)

- spec E12-D07.md md5 561a7fee (§0 L75); hand-off §H; E11-D04 §2, §5, §6, §10 (md5 02f3ff69); E12-D04 board kit (chrome geometry)

## Tokens (32)

- color.text.secondary
- size.icon.sm
- type.num.sm
- color.text.primary
- space.inset.sm
- color.sell.default
- color.surface.canvas
- color.surface.raised
- color.buy.default
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
- type.ui.body
- space.stack.sm
