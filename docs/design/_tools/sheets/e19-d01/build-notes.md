# E19-D01 board kit — build notes

Ticket #382 (E19-D01): the nine research boards of the profiles UX memo (memo §0, BQ-15: nine greyscale boards, no
light twins) for the Penpot file `E19-D01 boards`, page `E19-D01`, exported to
`docs/design/research/img/E19-D01-NN-<slug>.png` (the path memo §0 names). Offline: no Penpot, no network. RESEARCH
BOARDS: greyscale — node() refuses every colour token outside `GREY`; check_all re-scans every sheet for it.

## BUILD

`BUILD.md` beside this file: the kit sits at `docs/design/_tools/sheets/e19-d01/` (outputs in `build/`, not committed,
and `v4/`, with each `.md` sidecar beside the kit), or runs from anywhere with `CV_CHECKOUT=<checkout>` (outputs in the
sibling `E19-D01-cap/` and `E19-D01-v4/` folders).

Sources (md5-pinned in `DOCS`, read by repo-relative path; the kit refuses drifted bytes; the memo is pinned as the
boards PR leaves it, with §0's rows drawn and §13 As built, every line a board cites in place; `05` is read with
`git show` at the memo's base `ca49e693ae45`, because it moved on main after it): the memo `docs/design/research/e19-profiles.md` (§0 boards, §2 RQs / method / deviations, §3 F, §4.3 ladder,
§5 levels, §6 modes and honesty states, §7 PD, §8 competitive, §9 C / G / A / OQ, §10 protocol, §11 traceability —
parsed, never typed), `05` §6's profile table (the columns A-6 extends) and the recorded instrument fixture (BTCUSDT
tick 0.10, qty step 0.001). The BQ list and the ruling of record are not repo files: the memo carries their rulings
(BQ-0..BQ-15, "ruled as proposed"), so the memo pin covers them.

Layout: `e19d01kit.py` (registries, greyscale tokens, node primitives, the world, frame / board / sections / lint /
validate / write / md / pack, self-test); `gen/rb.py` (cards, chips, menu, radio group, the lo-fi profile pane,
legend); `gen/gen_01..09.py`.

## The world (seed 382; every number derived)

BTCUSDT 30-minute periods over the UTC days 28, 29 and 30 Oct 2026 (30 Oct developing, as of 14:30 UTC: 29 periods),
a seeded walk from 62 900.0 with a per-day drift, ranges and volumes on the tick and qty step. Recorded trades from
28 Oct 09:00 UTC; before it, kline bars only (approximated with the memo's uniform rule, §4.1); nothing kept for
25–27 Oct. Recorded periods spread their volume over seeded tick weights (so no POC tie needs C-1's open
tie-break); delta and TPO count over the recorded portion only. Profiles: rows of 50 ticks (5.00 USDT), POC = the
heaviest row, value area 70 % by `22`'s single-step expansion (tie: up). Derived: 30 Oct POC 63,085.0, VA
63,060.0–63,185.0, HVN 63,205.0, LVN 63,150.0, single prints 63,150.0 / 63,225.0 / 63,230.0, IB 63,072.6–63,108.6;
29 Oct (final) POC 63,035.0; 28 Oct POC 62,840.0; both untested through 14:30 (naked). The composite 25–29 Oct: 2 of 5
requested days recorded, 28 Oct morning approximated.

## Readings taken (ambiguities settled)

1. Board plan: memo §0's nine boards (names, content cells, PENDING or drawn); the kit places 21 frames (2–3 per board; ids
   `<topic>/<view>`), none named by the memo.
2. Theme: dark only, greyscale (memo §0, BQ-15, README :54–:57 "research board"); no light twins.
3. URLs: memo §8's three fetched rows are written "public documentation page, fetched 2026-11-01 (URL in memo §8)" —
   a board carries no URL; the memo keeps the links. Only the fetched (Sierra Chart) rows get schematics.
4. The role word "orchestrator" in memo text is drawn verbatim; the banned list blocks agent part names (with the
   hyphen), local paths, hosts and URLs.
5. Glyphs are stand-ins (memo §5: E19-D03 chooses): HVN chevron-right, LVN solid circle, single print 2 px bar, IB
   vertical bar, nPOC 1 px ray. The hatch is a hollow bar with a dashed inner outline (pattern ids are not tokens).
6. HVN / LVN by a kit illustration rule (3-row smoothed local extremes), not a definition; IB = the first two TPO
   periods; the nearest N = 1 naked POC drawn, "1 hidden".
7. A row is hatched when any of its volume is bar-approximated (G-3: no per-row flag); a day with any recorded trades
   counts in the partial chip's n.
8. Density: compact = the docked panel, dense = the chart overlay (dense is chart-only, `16` :146), same one-tick rows
   merged per `26` :238 on a 320 px plot (a memo example height); the memo §4.3 ladder is re-derived from its Rows
   column and must agree.
9. Labels the memo does not write ("Profile · BTCUSDT", "Row size …", the covered-range words, "Period mode", the
   CMP-227 accessible name) are drawn and listed per sheet as copy gaps (PROPOSED; E19-D02 / D03 write the copy).
10. Packed sheets keep compact.py's absolute pack-source path in `compactOf.file` outside a checkout; in a checkout the
    committed `v4/` copy carries the bare raw-sheet name (the sha256 beside it unchanged; BUILD.md).

## Live-check fold (render 2026-11-03, nine boards, dark)

The nine boards were drawn from these sheets on page `E19-D01` of the per-set file `E19-D01 boards`, with the local icon
seed `local-icons.js` (the shared five plus check, chevron-down, chevron-right and info, each from its `packages/ui`
Lucide SVG). Every frame read back at its sheet size and position with clip on, no child spilling and no text cut; the
drawing lint's only findings are the overlaps of the profile panes' stacked `layer · NN` children (boards 04, 05, 06
and 07), which share one rectangle by design. One SHEET-FIX line came back, made on the board and folded here, so a
rebuild reproduces the drawn boards:

11. Every root's height is the live read-back, max(annotation end, footer end) + 80: `LIVE_ROOT_H` in the kit, which
    checks it under the kit's own estimate and over the frames' end. Boards 05, 06, 07 and 09 came down from 1056,
    1312, 992 and 2960 px to 932, 1095, 847 and 2956 px; the other five were already exact.

Drawn deviations, recorded in memo §13 and not redrawn: the dashed board-marker outlines are barely taller than their
text, so the dashes graze the letters; board 04's in-situ POC rail runs along the POC row's bar with the price at
regular weight (a lo-fi stand-in; E19-D03 chooses the cue). The `.md` "N shapes" lines count the sheet's nodes; the
board's node count (memo §13) adds the icon instances' children.
