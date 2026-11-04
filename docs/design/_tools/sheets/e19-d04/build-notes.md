# E19-D04 (#439) board kit: build notes

Offline cvsheet v4 sheets for the ten §0 boards of `docs/design/E19/E19-D04.md` (file `E19-D04 boards`, page
`E19-D04`). No Penpot, no network. In a checkout the kit sits at `docs/design/_tools/sheets/e19-d04/` (raw sheets and
their `.md` to `build/`, packed sheets to `v4/`); outside one it needs `CV_REPO` naming a checkout and writes to the
sibling `E19-D04-cap/` and `E19-D04-v4/` folders. The BQ ruling (comment 6585044844) is folded in the spec; the boards
are drawn and the spec's §0 and §16 record them. After a spec edit, re-pin the spec md5 in `DOCS`, rebuild and re-run
the self-test and `check_all.py` (every cite — `§0 L…`, `§8 L…`, `§5 L…` — is looked up, never typed).

## Sources (md5-pinned in `DOCS`; the kit refuses drifted bytes)

- The spec in this checkout (md5-pinned, read from the checkout only): §0's board table, its not-drawn line, the window size and
  the drawing name; §8's state rows (one line per frame in the annotations; the self-test reconciles §8 with §0);
  §9's copy deck (W-1 … W-42, every quoted string of a cell in order); §5's matrix (sixteen rows, a cell that does not
  parse as `**Owner** · \`cursor\` — words` raises: no undecided cell). No hand-off file exists (BQ-2), so none is
  pinned.
- D03 (`E19-D03.md`, md5 `928db4e4`) at PR #5517's head `811292427` (still open 2026-11-03; its current head
  `35032f521` carries the same bytes) and D02 (`E19-D02.md`, md5 `1299df3b`), merged by `3619e95c5` (#5487; byte-identical
  to the earlier head `bed73afaa`, in the text checkout): read from the checkout when the bytes match, else with `git
show`. D03 gives the panel's redlines (§10.1, parsed) and its words (D03 W-n); D02 its title, alignment, row-size,
  stale and Histogram / Table words. Re-pin D03 to its merge commit when it merges.
- E14-D02, E14-D07 and E17-D02 at the base `95a625b09` (the popover title form, E14's context-menu items, the
  handle language, the delete toast; E17's chip); the recorded instrument fixture (tick 0.10, qty step 0.001 only).
- Tools: the checkout's `docs/design/_tools/sheets/tools/` (validator with `components.offline.json` and the default
  `token-sync.json` — §11 adds no token, so no local rows; `compact.py`; `mkcall4.py`).

## Build

```sh
python3 -X utf8 -I -B e19d04kit.py selftest                  # OK: 0 failures
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                           # OK: 0 findings
```

A rebuild is byte-identical (seed 439, one clock; every raw sheet, `.md` and packed sheet hashes equal across two
runs). `BUILD.md` gives the steps from the repository root.

## Layout

| File              | What                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------- |
| `e19d04kit.py`    | sources, §0 / §8 / decks parse, node builders, metrics, the world, sections, sheet I/O, self-test       |
| `gen/panel.py`    | the E19-D03 kit's host pieces, cut down: chart pane, CMP-183 plot, SCR-038 header / legend, docked host |
| `gen/flows.py`    | menus, dialogs, toast, chart marks, the 26 frame builders, the matrix                                   |
| `gen/registry.py` | frame id -> builder; `build_board(nn)`                                                                  |
| `gen/gen_NN.py`   | one generator per board                                                                                 |
| `check_all.py`    | the scan (validator, mkcall4 count, sha256, node rules, captions, cells, overflow, overlap, pins)       |

## The synthetic world (declared on every board; seed 439)

BTCUSDT 5-minute bars (§0's drawing "Rectangle 13:40 → 14:05" sits on 5-minute edges) from 2026-11-02 00:00 UTC to the
clock 14:30 (R-7's example date), one seeded walk whose drift is redrawn every two hours; every bar recorded (nothing
approximated). The bound chart shows 11:00 to the clock in 54 slots; row size 100 ticks unless a preset says
otherwise. Kit choices: the fixed range 12:30 → 13:30 (board 04 / 09), the drag mid-way at 13:15, the anchor at
12:30 (Keep open-ended from that range), the rectangle's price edges = the low / high of the bars it spans, the move
two bars later (13:50 → 14:15), the pan six bars back, the keyboard nudge three bars, two user presets "Scalp tight"
(50 ticks, VA 68 %, VWAP on) and "Wide value" (200 ticks, VA 80 %, nodes off), the Modified change 50 -> 80 ticks, the
view-as user "Sam", the stale age 7 s (W-39's figure, so D02's last update reads 14:29:53).

## Kit readings (each is a `readings` note on the boards that use it)

- **R-K1 (light twins).** Boards 01, 04 and 08 are dark boards nesting one `-light` frame (§0 "dark, light twin"). A
  board renders under one theme set, so each is exported under the dark set (§0's export name; its `-dark` frames) and
  again under the light set as `…-light.png` (its `-light` frame). `.md` line 3 reads `theme dark.`
- **R-K2 (range words).** A range's legend words (R-2) are its two times joined as W-26 joins them, "{start} to {end}
  UTC"; {start} / {end} / {time} fill as `YYYY-MM-DD HH:MM` and the deck's own "UTC" closes the sentence, so nothing
  reads "UTC UTC" (R-7's example carries the zone because it is quoted alone). Anchored's legend reads its one time.
- **R-K4 (toast stack).** CMP-045's stack is drawn at the window's lower right over the panel's legend controls —
  never over the plot stop, an edge handle or the Presets button (§2.6).
- Smaller ones, noted on their frames: the built-in's held values are the panel defaults (D02 L302 names it only);
  the Presets menu opens under the header band in the panel's column; W-13's {name} is the stored preset's name; the
  rename form keeps §2.3's footer; menus drawn reopened on board 03 to show the Restore item present / gone; while a
  drag is in progress the plot keeps the previous profile (recompute on release); an attached range is marked by its
  drawing alone (no band or handles of its own); E14's label follows a moved drawing's times; W-35's "· Undo" is the
  toast's action; Attach profile sits after E14's context-menu items behind a separator; the pending slider value
  is spoken as its name and aria-valuetext; board 07's two panes split 60 / 40 with the profile's pane on top.

## Live-check fold (the drawing lane's fix lines, 2026-11-03)

- **Legend keys.** Every CMP-199 legend key row is `KEY_ROW_H` 14 px (12 px rows cut the caption by 1 px top and
  bottom); the HVN / LVN marks are 12 px with their glyph at y 0. The drawn legends kept their heights (92 px, 105 px
  with the link row), so `panel.drawn_legend()` estimates a legend's height with 12 px key rows; `check_all.py` uses
  the same rule.
- **Rename selection.** `flows.LIVE_TEXT_W` holds the drawn width of "Scalp tight" (66 px), so board 02's selection
  box is 68 px (the estimate drew 82).
- **Root heights.** `LIVE_ROOT_H`: max(annotation end, footer end) + 80 as read back, 1878 (01, 02, 04, 10), 998
  (03, 05, 06, 09), 2758 (07), 1398 (08); the estimate ran 18 px over on each. A root that would end less than 80 px
  under its footer raises.
- **Focus rings (PNG review).** A focused control's 2 px outer ring was cut by its clipping parent on board 02 (the
  three name fields, the delete dialog's Cancel) and board 06 (Attach profile): the dialog footer, the CMP-040 field
  and E14's extension slot are now unclipped (`"clip": False`; no geometry change). Boards 02 and 06 were
  redrawn from the rebuilt sheets and show whole rings (spec §16).

The rebuild reproduces the drawn geometry: every node matches the drawn sheets but for the values above.

## T2 (§1.4)

Board 10 `SCR-038/preset-view-as-dark` names T2, CMP-079 RbacGate and the CMP-019 `lock` (2a): each of the four writes
leads with the lock and carries W-20 as its own second line (CMP-041 `disabledReason?`; G-T2 Major fix at text head
`cbd0c7ba9`, §1.4), no fill of its own (the items sit on the menu's `color.surface.overlay`), aria-disabled (never
disabled), arrow-reachable (the active item is a T2 item), each `aria-describedby` its own second line; label and lock
`color.text.tertiary`, reason `color.text.secondary`; apply, Reset, Restore stay T1. A Viewer's menu (W-42 per item,
same drawing rule) is `SCR-038/preset-viewer-dark`, not drawn (§0); no dialog notice exists for a Viewer. The SCR-039
footer menu is not drawn either.

## Fallbacks (stand-ins; each a `fallbacks` note)

The link glyph as two interlocked 1 px rings; CSS cursors as small shapes with their keyword (a board marker); E14's
handle glyph as an 8 px `color.text.primary` dot in a `color.border.strong` ring; the selected text as a
`color.surface.selected` box; TopBar / StatusBar placeholders without words and no environment badge anywhere;
`size.icon.sm`, `opacity.scrim` and `elevation.3` are Tier-1 primitives (validator WARN).

## Sections

`k.chunk` wraps the kids of any large non-flex board into full-size `group NN` boards (positions unchanged) so the
packer emits one section per group.
