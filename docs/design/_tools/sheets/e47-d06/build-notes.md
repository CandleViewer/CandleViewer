# E47-D06 (#1305) board kit: build notes

Offline cvsheet v4 sheets for the eight §0 boards of `docs/design/E47/E47-D06.md` (file `E47-D06 boards`, page
`E47-D06 — Canvas accessibility`), frames from the hand-off's §I (23 frames, each a 1280 x 800 window at compact
density). No Penpot, no network. Synthetic data only (seed 1305, BTCUSDT, 600 1m bars 04:00 to 13:59 UTC), declared
on every board's face; only the tick size (0.1) is the recorded fixture's (hand-off §I).

## Build

In a checkout the kit sits at `docs/design/_tools/sheets/e47-d06/` (raw sheets to `build/`, packed to `v4/`);
anywhere else set `CV_CHECKOUT` to a checkout (raw sheets + `.md` to `../E47-D06-cap/`, packed to `../E47-D06-v4/`).

```sh
python3 -X utf8 -I -B e47d06kit.py selftest                 # OK: 0 failures
for n in 01 02 03 04 05 06 07 08; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                       # every sheet "ok", "OK: 0 findings"
```

A rebuild is byte-identical (raw sheets, packed sheets and `.md`). Each packed sheet's `compactOf` is the bare raw
name and the raw sheet's sha256.

## Sources (md5-pinned in `DOCS`; the kit refuses drifted bytes)

- Spec and hand-off as this checkout commits them (md5-pinned): §0 (boards, file, page, exports, the twins sentence, frame size),
  hand-off §I (frames), §2 (inventory), §4 (caps), §5 (name grammar, joiners), §6.2 (column sets, caption form),
  §6.3–§6.6 (the bold control words, the count and no-match forms), §8 (labels), §9 (oracle), §10 (T2 items, keys,
  reasons' verbs, Export's string and key), §13 (copy deck) are parsed; the COUNT anchors are checked.
- `docs/design/E09/E09-D09.md`: the rbac.permission / rbac.view_as templates and the permission verbs.
- `docs/plan/14-screens-catalogue.md` at the spec's base (`git show`, the "Inputs pinned" line): the panel titles
  (screen headings). `docs/design/E11/E11-D04.md`: SCR-047's
  never-recorded copy row and the stale chip's form.
- `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`: BTCUSDT's tick size only.
- E47-D04 at the Start line's pin, read with `git show`: §7.1's ring geometry.

## Boards

| Board                   | Frames | Kind                                                                                             |
| ----------------------- | ------ | ------------------------------------------------------------------------------------------------ |
| 01 four-layer-inventory | 1      | §2 as a sheet (15 surfaces x 4 layers)                                                           |
| 02 surrogate-grammar    | 3      | chart windows: cursor window + mirror callouts; the bubble sparse set; 24 px targets and overlap |
| 03 profile-table        | 2      | SCR-038 with the table in place: sorted by volume; the In VA filter                              |
| 04 ladder-table         | 2      | SCR-050: native grid + ladder table, AC3; the patch tick (order held)                            |
| 05 table-states         | 6      | stale (W-5), feed Stale, empty, no data (SCR-047 1a), filtered to zero, load more                |
| 06 equal-status-headers | 6      | eight panel headers with the switch; five T2 frames                                              |
| 07 parity-oracle        | 1      | sheet: canvas → mirror label → table row → P-1 … P-5                                             |
| 08 profile-table-light  | 2      | board 03's builders, light set at export                                                         |

## Kit choices and fallbacks (also in each sheet's notes)

- Chrome as placeholders (the E47-D03 kit's SCR-116 chrome); CMP-039 ring bands from the E47-D04 kit's way.
- The world: BASE is derived so AC3's 64,100.0 is an own-order level; the 13:42 bar (W-1's) carries a seeded refill
  burst (the estimated, Ask-stacked level of QA-1, and a 21-print cluster bubble).
- Profile rows of 10 ticks, 70 % value area, 30-minute TPO periods (SCR-038's settings, kit values).
- Hidden layers (mirror, surrogates, aria-describedby) are annotation callouts and outlines in
  color.status.info.default.
- T2: lock (`locked` icon) + full label in color.text.tertiary, reason in color.text.secondary, raised fill with a
  color.border.default hairline, aria-disabled; the one-notice form for the trade keys and view-as; never dimmed.

## Change log: independent check fixes (2026-11-02)

- 05 states/stale now draws W-1 verbatim (D04E11:272) as the banner on the profile table (the bar-table surface);
  the ladder's W-5 is named as not drawn. Sorted-by live-region strings in 03/04 (and 08, which inherits 03) follow
  the verbatim pattern with the column lowercased ("Sorted by volume, descending", "Sorted by cumulative depth,
  ascending"). Copy keys: 03/04/05/08 list table.export_deferred; 06 also lists rbac.permission and rbac.view_as.
- Regenerated all eight boards; selftest 0 failures, check_all 0 findings, validator exit 0 on all eight cap sheets,
  mkcall4 count exit 0, packed compactOf sha256 = raw sha256.

## Live-check fold (after the render, 2026-11-03)

The drawing lane drew the eight boards from this kit and returned 13 fix lines. Folded here, so a rebuild reproduces
the drawn geometry:

- Root heights are the checked `want` (footer end + 80): 998 on 01–04, 07 and 08, 1878 on 05 and 06 (`MEASURED_H`).
- Board 02's surrogate bounds are named `dashed · surrogate HH:MM:SS`, so the post-step dashes all 36 (they were dashed
  by hand on the first render).
- Board 05's W-1 callout (380 px wide) sits at x 898 (`PX0 + 826`), the first free x right of the table; at x 932 it
  ran 32 px past the frame. `check_all.py` now fails a callout past its frame.
- Board 05's `Learn more` underline takes the label's measured 71 px (`MEASURED_W`; the estimate was 73).
- Drawn text carries no backtick: `text()` strips them (the first render kept `` `05` ``, `` `14` `` cite marks on 01–08).
  `check_all.py` fails a backtick in drawn text. The PNGs are not redrawn for this (spec §18, drawn deviations).

Recorded, not folded (a drawing step, nothing in the kit changes): board 02's `grammar∕cursor-window` texts re-set
after the first JetBrains Mono text drew in a fallback serif; board 05's stale frame and annotation column re-set and
four top-level texts re-drawn after a tab reload; touch and relayout run once per top-level child on 05 and 06 (about
2,100 and 2,700 shapes; a single relayout call ran past the bridge's 120 s).
