/* E22-D02 — SCR-053 tape and big-trade bubble panel wireframes (#507): BUILD script.
 *
 * One Penpot MCP `execute_code` call per board (the loader runs ONLY = [n]), with the bridge connected and
 * the CandleViewer file open. Same shared-plugin convention and write patterns as e22-d01-board.js r9 (the
 * lane's Penpot notes): single writer (storage.hpe1inst stamp in WRITER; "SET-ME" skips), the fail-closed
 * file guard (FILE_ID is written by the loader at load time and never kept here), the page by name (created
 * if missing; PAGE_ID pinned after the first run), re-check, then ONLY synchronous creates; idempotent:
 * removes ITS OWN top-level frames (ticket prefix, normalised name, this page only) and stamps every board
 * `hpe1ver` = VERSION; every shape is named "E22-D02 / …" and carries plugin data under TAG. No script ever
 * calls page.remove(). Never retry after a "tab suspended" answer: probe read-only first. Afterwards run
 * e22-d02-relayout.js (PASS "measure", then "restack" until moved = 0), e22-d02-dedupe.js, then export.
 *
 * Source of every word and number: docs/design/E22/E22-D02.md (the spec; §2 anatomy, §3 rows, §4 states,
 * §5 pause model, §6–§9 controls and bubbles, §10 tiers, §11–§12 keyboard and names, §13 copy deck, §14
 * contrast) and docs/design/_tools/e22_d02_tape_wires_audit.py --json; e22-d02-check-nums.py proves every
 * number and term below is in the spec before this runs. Fills are the dark theme's NEUTRAL semantic tokens
 * resolved from packages/ui/tokens at the base (token name in each shape's plugin data; nothing is bound —
 * the greyscale convention of E13-D02 §13); the only non-neutral fills are the memo §3.9 simulated swatches
 * on board 10 (hexes from the tool, labelled "simulated"). Geometry rules: row height = max wrapped height
 * over every cell incl. the label column; blocks ≥40 px apart; content margins ≥24 px (nothing within 16 px
 * of an edge); conservative estH (0.56 em Inter, 0.62 em mono, +0.4 lines, +6 px); a table row is est + 2·pad tagged gap 0
 * (est from the cell as drawn — the header is never mono) and a card its last text's bottom + pad — exactly the relayout
 * restack's sizing model, so a restack whose render matches the estimate moves and resizes nothing (gate:
 * penpot-restack-idem.js, r6); the tape rows take their height from the density (24 / 32 px), never from estH; every pill, tag, Kbd hint, state pill, divider label
 * and badge goes through pill() with the shared label-width rule (PILL_EM + pillTextW) and NBSP-joined words;
 * footer "page E22-D02 · board NN · rN" (rN = VERSION) exactly 32 px from the bottom edge (the restack's board rule — the
 * board is never taller than its footer + 32; r5: ≥24 and never shrunk). Placement: board n sits at
 * x = (n − 1) · 2000, y = 0 on every run (rowX), and placeRow() after the build re-rows every board of this
 * ticket already on the page, so a one-board-per-call draw can never stack them.
 * r1 (2026-10-23): first revision — thirteen boards planned from the spec at its PR base.
 * r2 (2026-10-23): the pre-PR design-review lens round 1 folded — every drawn tier computed from the threshold (the
 *   memo rows rescaled, D02-C9); the status-row ladder (readout first, '+N filtered' only with a filter) and its
 *   buttons (Jump to live, Load missed prints, Apply / Keep) as the sixth Tab stop; board 04 as a state diagram with
 *   its cross-edges + the P1–P14 table + seven 400 px frames incl. the full ring (S22); board 06's view-as frame
 *   with every write T2 and Size tier 2 as plain text; board 07's percentile row at eff. 220k (uncapped) and the
 *   warning strip in place; board 12's tree with one hidden status node and five stops; the type sizes snapped to
 *   the primitive scale (10 / 11 / 12 / 16); the comfortable slots, 28 px chips row, 25 / 17 and 51 / 37 rows.
 * r3 (2026-10-23): r3 = r2 + the T2-precheck-4248 fold: the Viewer permission leg (S23) as a board 06 inset with the two
 *   notice.panel_read_only notices (settings:write / workspaces:write), the panel notice drawn in its own slot right under
 *   the header (panelChrome o.notice), the view-as Apply in the T2 look (raised fill, border hairline, the middle grey),
 *   strip row A split into the plain label, two locked controls and the effective readout as a status pill, the deferred
 *   column items drawn as an absence (the structured-feed list as its own T1 inset), the CMP-056 / popover T2 excerpts and
 *   the density pair as two radio items; board 05's Disconnected pause as a 400 px frame in the 2b rendering (the ⏸ glyph
 *   kept in the middle grey with a lock badge, raised fill + hairline, the CMP-016 echo, the header outside the scrim)
 *   beside the hard-paused T1 variant and the S10 cell pill without the reason inside it; board 12's K7 clause and the
 *   Viewer line of the T2 card; board 13's S23 row and the 23-state count. The exact Inter lookup is kept; the return object carries the page name and id only.
 * r4 (2026-10-23): r4 = r3 + the 6359716505 fold: one pause model — board 04's P13 self-loop pill leaves the scroll node (P13 is
 *   the hard pause's alone), a Ctrl+Home pill under the focus node (the cursor and the viewport to the live edge, the pause holds —
 *   K4, D02-C17), the P5 guard pill [no row focused], the P5 / P9 / P13 table rows reworded; board 12's K4 (panel-scoped Jump to live; on a
 *   focused row the cursor moves and the pause holds) and K6 (hard pause only); board 13's S3 step (Ctrl+Home with no row focused);
 *   boards 01 and 05's "+N filtered" lines (the display filters' own count, never 23 §14.2 dropped — D02-C16); cOwn 17. The exact
 *   Inter lookup is kept; the return object carries the page name and id only.
 * r5 (2026-10-24): r5 = r4 + the PART split for boards 02, 03, 04, 06 (no string, number, token or geometry change): the shape budget,
 *   the dry planning pass, the pre-run guard, the pre-export self-check with the single-line wrap rule and the rollback, ported from the
 *   E14-D06 r7 script; the clear now runs after the draw. The exact Inter lookup is kept; no page-link field.
 * r6 (2026-10-29): r6 = r5 + the pre-draw restack-idempotence patch (declared patch, no spec change, no drawn word changes): the
 *   geometry now equals the relayout restack's sizing model, so the restack re-lays nothing (penpot-restack-idem.js box mode 0 / 0;
 *   r5: moved 15, resized 30, 105 shapes re-laid) — finish() sizes the board to the footer + 32 exactly (r5: ≥24 and never shrunk,
 *   so every frame regrew 8 px and boards 08 / 09 / 10, drawn taller than their content, shrank 16 / 95 / 32); card() ends at its
 *   last text's bottom + pad (r5: cy − 4, 4 px short under a foot — 17 cards); tableBlock() estimates a header cell as drawn, never
 *   mono (r5 estimated the mono columns' headers at 0.62 em, so board 12's keys header was 15 px too tall and its 78 row shapes
 *   moved up 15). Real-render mode: board 04's "▲" edge heads start at the target node's bottom edge (r5: 8 px inside it, so the
 *   15.18 px glyph line ended 7.2 px past the state:live / state:hard paused frames) and the P13 pill sits 8 px lower, clear of
 *   the lowered head; board 08's bubble marks stagger 24 px per
 *   step (r5: 18 — the 1× r 3 and 1.5× r 10.2 notes overlapped 3 px); board 06's structured-feed label is a plain string (r5
 *   NBSP-joined it, so it could break only at its hyphen and dash: 3 rendered lines over a 2-line estimate, into the menu rect).
 *   Checked and already right in r5: no toLocaleString / Intl (fmt groups with the spec's plain space — "250 000" — and fmtPrice
 *   with the spec's comma — "64,012.5"); tapeBlock's column headers draw the label; table rows est + 2·pad with gap 0. Shape
 *   counts unchanged (PART_PLAN holds).
 *
 * r7 (2026-10-29): r7 = r6 + the pre-READY audit patch (declared patch, no spec change; the orchestrator's ten-item boards checklist
 *   and the E22-D03 boards-lens classes a–g run against this script before any draw): (a) the CMP-239 feed chips carry the catalogue
 *   binding — "Stale 12s" (S8), "Offline" (S10) and "Reconstructed after gap" (gapped, S15 / S16) are surface + text + the 6 px
 *   indicator dot with no outline, and only the S9 strong chip "Stale 30s" adds the indicator as its 1 px outline too (E17-D01 D16);
 *   r6 drew every feed chip as an outlined pill with no dot; (b) every CMP-227 "(estimated)" chip draws the registry `estimated`
 *   glyph (≈, size.icon.sm 12 px) before the word (r6: the word alone); (d) every action is a CMP-001 button (square 4 px corners —
 *   Clear filter, Load missed prints, the popover's Apply / Cancel, the warning strip's Apply / Keep; r6 drew them as round chips)
 *   and a removable CMP-011 chip draws its CMP-002 remove control (×) in its own box after the label; strip() now honours a cell's
 *   pillFill / pillStroke (r6 dropped them silently, so S9's strong chip, S13's Clear filter and S15 / S16's gapped chips drew in
 *   the default look); (e) the three spec tables are drawn with the spec's own columns and cells, verbatim — board 04's P1–P14 table
 *   (§5: Id · From → to · Event · Guard · Chip text · Announcement · Emits; r6 merged Event + Guard and Chip + Announcement and
 *   paraphrased), board 12's keyboard table (§11: Id · Key · Where · Action · Focus after · Global conflict? · Registered?; r6 merged
 *   four columns) and board 12's announcement table (§12: thirteen rows × five columns; r6 merged the two resume rows and the two
 *   Stale rows and dropped the Paused, filter and column-reorder rows); (f / checklist 1) every figure is the frame's own: the
 *   tape rows of an S18 frame take their tiers from the effective threshold 34 723 USDT (r6: 250 000 on every frame), the S21 / S23
 *   strips read the user's 30 000 USDT · eff. 34.7k USDT · capped beside their capped chip and Apply 34 723 (r6: 250 000 / eff. 250k
 *   beside them) and carry the S18 sentence under the status row as board 07 does, and every "… N more rows …" count is computed
 *   from the frame's own slots (604 px log − its notice / strip / second chips row; r6 typed 15 / 19 / 20 on frames holding 17 / 15 /
 *   17); the chips row wraps on the pills' drawn widths at 11 px (r6 wrapped on 10.5 px estimates and drew at 11), so on the 400 px
 *   panels of boards 01 / 08 the three default chips take two lines at the shared label-width rule once (estimated) carries its glyph
 *   (D4's ladder) and the log holds 24 rows there (25 per the tool with one chips row — the frame says so; the E22-D03 r7 precedent).
 *   Two r6 geometry bugs found by the mock dump: tapeBlock reserved the "… N more rows …" row but drew its text only when the elision sat
 *   above the rows (every other frame ended in a blank row), and the 1280×800 / 2560×1440 panels sat 8 px under the top bar, so the 732 px
 *   panel ran 4 px into the bottom bar — the panel now fills the dock's 736 / 1 376 px (§2); board 03's band notes and board 02's bottom were
 *   computed without the chips row (the notes sat on the blank elision row); board 02's comfortable crop now draws the comfortable slot
 *   heights its label names (44 · 32 · 32 · 24, D2; r6 drew the compact slots).
 *   Checked and already right in r6: every glyph is a character (▲ ▼ ● ◆ ⧉ × ☑ ☐ ◉ ○ ▸ ⏸ ▶), never a stroke; T2 only on writes and
 *   the S10 state gate, openers / exits / Keep / Jump to live / Load missed prints T1, unavailable picker items absent; 412 / 10 000 /
 *   2 000 / 2 010 / 33 / +41 / 23.5 % / 34 723 / 30 000 consistent on every frame; no light / hc twins (greyscale, one theme).
 * r8 (2026-10-29): r8 = r7 + the r7-draw QA fold (declared patch, no spec change; boards 02 / 04 / 05 / 06 / 07 / 08 / 09 / 10 / 13 change, 01 / 03 / 11 / 12 only
 *   by the version footer): (A) every multi-line note is a plain string that wraps at spaces, and its estimated wrapped height places what follows
 *   or sits beside it (r7 NBSP-joined them, so they could break only at a hyphen and clipped at the board edge or ran under the neighbouring
 *   cards: board 04's frames label and S22 note, board 05's S10 label, echo label / note and hard-pause note, board 06's popover note,
 *   reorder note, view-as and Viewer labels, both picker captions and the popover caption, board 07's S18 note, board 09's floor label,
 *   board 10's swatch label, board 02's crop labels, board 08's cap-outline note); NB() is kept only for texts in an explicit one-line box, and the self-check now throws
 *   on ANY line holding an NBSP that is wider than its box (strict, no KNOWN_WRAPS exemption) — board 08's bubble notes (180 px boxes) and
 *   tooltip line (410 px plate) and board 02's crop labels, the last NBSP overflows, are fixed and leave KNOWN_WRAPS; (B) the T2 lock is
 *   DRAWN — lockGlyph(): a stroked rounded-rect shackle behind a filled rounded-rect body in color.text.tertiary (the ⏸ button's T2 grey), via
 *   pill() for every "🔒 …" chip / action / control, lockText() for menu items, the panel notice and the echo label, and the pause button's
 *   badge — never the 🔒 emoji (it rendered as a gold padlock on boards 05 / 06; §0 / §10 promise neutral tokens only); the self-check throws
 *   on any emoji-presentation character; (C) every elided count is computed: board 02's comfortable crop from the 572 px log at 1280×800
 *   (17 − 12 = 5; r7 typed 6, 18 drawn against the label's 17), board 06's filter frame from its slots (elide(); r7 typed 4), board 03's band
 *   from the 600 px panel's 25 rows; board 13's hand-offs foot names the drawn state and no worker; board 08's ×7 badge sits top-left of the
 *   cluster mark inside the chart pane (r7: astride the pane's right border), every bubble note carries a 1 px canvas halo and the marks stagger 48 px per step so a
 *   note never crosses the next mark (r7: 24 — the 2× aged note ran across the 1.5× square once its box was wide enough to show it). Shape counts
 *   change (the lock is two rects; PART_PLAN below is the r8 mock count).
 * r10 (2026-11-01): r10 = r9 + the pre-commit verbatim check (declared patch, no spec change; board 12 only — the §11 K4 "Global conflict?" cell
 *   hyphenated as the spec cell, listbox-of-rows; every other board changes only by the version footer and keeps its r9 / r8 draw).
 * r9 (2026-10-29): r9 = r8 + the r8-draw QA fold (declared patch, no spec change; boards 01 / 02 / 03 / 04 / 05 / 06 / 07 / 08 / 10 / 11 / 12 change
 *   — every board that draws a tape header, computed from the mock build — 09 / 13 only by the version footer): (A, QA MAJOR) board 06's
 *   T2 strip (S21 and S23) is four rows, the locked Bubbles · scale control on its own row (r8 drew it after the derived text at x 464–691
 *   inside a frame whose right border is at 671: pillTextW's upper bound on the derived text advanced the cursor past the frame); the More
 *   menu follows the strip's own height; (B, the known wrap since r4) every right-aligned tape header box is at least its label wide
 *   (pillTextW, JetBrains Mono) and ends at its column's right edge — Notional (55 px) no longer starts at the 40 / 47 px column's left edge
 *   and runs into Side; the data cells, columns and strings are unchanged, the tape still holds 5 columns + the tier mark; the 13 header
 *   entries leave KNOWN_WRAPS (the 6-ch data cells stay); (C) two self-checks: containment() — over the planning pass, no shape's right edge
 *   leaves the rect it sits in (earlier rect or board ≥ 40 × 12 px holding the shape's left edge and vertical centre; texts at their estimated
 *   advance) — and the header-gap check (≥ 4 px between neighbouring header labels' estimated extents); both throw before anything is drawn.
 *   Shape counts are unchanged (PART_PLAN below holds).
 * SHAPE BUDGET (r5): ONE plugin call creates at most SHAPE_BUDGET = 400 shapes and SEG_BUDGET = 5 000 path segments (≤ 20 000 per page;
 * this ticket draws no path shapes). Before anything is removed or drawn, a dry pass builds the wanted board against a count sink, records
 * every top-level unit (the board, each helper call made straight from the board's builder: a card, a table, a strip, a tape, the panel
 * chrome, a pill, a lone text or rect, the footer) with its shape count, and packs the units in drawing order into PARTS of at most 400
 * shapes; a unit is never cut. The pre-run guard throws ("shape budget") when the call would create more, and nothing is touched then.
 * DRIVER (one plugin call per line; set ONLY and PART before each call; PART = 0 returns the part plan + the self-check, draws nothing):
 *   ONLY = [n] with PART = 1, 2, … parts(n) in sequence; a board whose plan has one part runs with PART = null (or 1).
 *   Part 1 draws the new board root first and removes the old board only after its draw succeeded (a throw removes every shape the
 *   call created, so the page keeps the old board); part k > 1 appends to the board part 1 created (it aborts, nothing drawn, when the
 *   board is missing). A failed or repeated part k > 1 is redone from PART = 1. Shapes outside the call's part are laid out as dry
 *   records, so every x, y and block id equals the one-call build's. The relayout runs only after the last part. The mock harness
 *   (WRITER "MOCK") builds every board in one call and checks the plan instead.
 * PART_PLAN (r8, the mock count, shapes incl. the frame): 01 = 270 (1 part), 02 = 46 + 394 + 326 (3), 03 = 332 + 214 (2),
 *   04 = 391 + 378 + 74 (3), 05 = 335 + 78 (2), 06 = 389 + 140 (2), 07 = 195 (1), 08 = 348 (1), 09 = 102 (1), 10 = 128 (1), 11 = 206 (1),
 *   12 = 375 (1), 13 = 248 (1) — 20 plugin calls in all (r7: the same 20 calls; its header miscounted 21); PART = 0 prints it live.
 * PRE-EXPORT SELF-CHECK (r5; r8 NBSP + emoji; r9 containment + header gaps): selfCheck() runs on the dry pass's record before the clear and before any shape is drawn: no single-line
 *   text (an explicit one-line box — pills, Kbd hints, chips, tape cells, the readout, notices, labels) is wider than its box at the
 *   shared PILL_EM bound (Inter class sums; JetBrains Mono 0.62 em); the texts already flagged in r4 are listed in KNOWN_WRAPS and warn.
 */
"use strict";

// ---------------------------------------------------------------- constants (edit only these) -------------
const WRITER = "SET-ME"; // storage.hpe1inst stamp of the ONE instance allowed to write (probe.js); "SET-ME" skips
const VERSION = "r10"; // r10 = r9 + the pre-commit verbatim check (2026-11-01; declared patch, no spec change — header r10 line): board 12's K4 "Global conflict?" cell reads the spec cell's hyphenated form (listbox-of-rows; r9 drew "listbox of rows"); boards 01–11 and 13 change only by the version footer and are not redrawn. r9 = r8 + the r8-draw QA fold (2026-10-29; declared patch, no spec change — header r9 line): board 06 S21 / S23 — the T2 strip is four rows and the locked Bubbles control sits on its own row (r8 drew it after the derived text, 19 px past the 640 px frame); every right-aligned tape header box is at least its label wide and ends at its column's right edge, so Notional no longer runs into Side (boards 01 02 03 04 05 06 07 08 10 11 12 — every board drawing a tape header; 09 / 13 change only by the version footer); the containment and header-gap self-checks. r8 = r7 + the r7-draw QA fold (2026-10-29; declared patch, no spec change — header r8 line): multi-line notes wrap at spaces and size their neighbours (NB() only in one-line boxes; strict NBSP + emoji self-checks), the T2 lock drawn as two neutral rects (never 🔒), the elided counts computed (board 02 comfortable 5, board 06 filter frame), the hand-offs foot in the drawn state, board 08's ×7 badge inside the pane + haloed bubble notes. r7 = r6 + the pre-READY audit patch (2026-10-29; declared patch, no spec change — header r7 line): CMP-239 dot / strong-outline chips, the ≈ glyph on (estimated), CMP-001 buttons and the × remove box, strip() honouring pillFill / pillStroke, the three spec tables verbatim with their own columns, per-frame tiers / strip values / elided counts, the chips row wrapping on its drawn widths. r6 = r5 + the pre-draw restack-idempotence patch (2026-10-29; declared patch, no spec change, no drawn word changes — header r6 line): board frame footer + 32 exactly, card last text + pad, header est never mono, the ▲ edge heads at the edge, 24 px bubble stagger, the structured-feed label unjoined. r5 = r4 + the PART split for boards 02, 03, 04, 06 (no string, number, token or geometry change); hpe1ver stamp on every board; bump when the content changes
const FILE_ID = "SET-ME"; // fail-closed placeholder: the loader sets the current file's id at load time
const PAGE_NAME = "E22-D02 Tape and bubble panel wireframes"; // created by name on the first run; then pin PAGE_ID
const PAGE_ID = null; // paste the returned pageId here after the first run
const TICKET = "E22-D02";
const TAG = "cv:e22-d02"; // plugin-data key marking every shape this script creates (value "v1")
const ONLY = null; // ONE board per plugin call: [1], [2], … [13] (the shape budget refuses a call over 400 shapes outside the mock harness)
const PART = null; // null = the ONE board in ONLY in one call (its plan must have one part); 0 = return the part plan + self-check only, draw nothing; k >= 1 = part k of that board (see the DRIVER)
const SHAPE_BUDGET = 400; // the most shapes ONE plugin call may create; the dry pass + guard throw before anything is removed or drawn
const SEG_BUDGET = 5000, PAGE_SEG_BUDGET = 20000; // path segments per call / per page (this ticket draws no path shapes: every part plans 0 segments)
const HARNESS = WRITER === "MOCK"; // the offline mock harness (penpot-mockrun2 / board-shape-count / text-fit-check / board-geom-diff) builds every board in one call
const EXPORT_DIR = "docs/design/E22/img";
const BOARDS = [
  { n: 1, slug: "scr-053-panel-1280" }, { n: 2, slug: "scr-053-panel-2560" }, { n: 3, slug: "tape-rows-densities-tiers" },
  { n: 4, slug: "pause-model-states" }, { n: 5, slug: "feed-and-list-states" }, { n: 6, slug: "filter-bar-column-picker" },
  { n: 7, slug: "threshold-strip-classes" }, { n: 8, slug: "bubble-overlay-scr-030" }, { n: 9, slug: "bubble-states-scale-switch" },
  { n: 10, slug: "greyscale-cvd-proof" }, { n: 11, slug: "clustering-badge-tooltip" }, { n: 12, slug: "keyboard-a11y-announcements" },
  { n: 13, slug: "copy-deck-states-matrix" },
];
// Every number drawn on a board (spec §2–§15; the audit tool's --json). PROPOSED until the owner's approval.
const NUM = {
  rowPx: [24, 32], fontPx: [11, 13], rows600: [25, 18], rows1280: [25, 17], rows2560: [51, 37], panelPx1280: 736, panelPx2560: 1376,
  logPx1280: 604, logPx2560: 1244, logPxComfortable: [572, 1212], overscan1280: [33, 41], overscan2560: [7, 21], domRows: 60, dividers: 2,
  slotHeader: 32, slotStatus: 28, slotChips: 28, slotColHdr: 20, slotStrip: 80, slotStripCollapsed: 24, noticePx: [24, 32], rowsNotice1280: [24, 16], slotsComfortable: [44, 32, 32, 24, 32], slotStripComfortable: 108, panelW1280: 400, panelW2560: 480, panelWWide: 640,
  shellTop: 40, shellBottom: 24, minWidth: [332, 403], minWidthOneSize: 356, chTotal: 39, chCols: [12, 9, 6, 6, 4, 1, 1], monoEm: 0.6, gapPx: 8, gapPxComfortable: 12, insetPx: 12, accentPx: 2,
  rates: [50, 500, 2000], hz: 60, perFrame: [0.83, 8.33, 33.33], dwellCompact: [500, 50, 12.5], dwellComfortable: [360, 36, 9],
  hoverIntentMs: 150, parkS: 30, buffered: 412, gapMissed: 1240, readoutRate: 2010, readoutFrame: 33, filtered: 41, readoutHz: 2, readoutWindowS: 1,
  ringFillS: [200, 20, 5], ringMaxFillS: [1000, 100, 25], parkPrints: [1500, 15000, 60000], fullArrived: 12000, fullKept: 10000, fullDropped: 2000, fullAfterS: 6,
  memoSizes: [4.0, 18.75, 0.12], p99Thr: 220443, scrimRows: [3.23, 2.39, 1.89], glyphOnSellFill: [3.71, 3.43, 3.31], glyphOnBuyFill: [5.01, 3.89, 4.27], sellOnRaised: [4.42, 3.94, 3.75], sellOnCanvas: [4.68, 4.17, 3.97],
  staleT1: 10, staleT2: 30, staleShown: 12, dimPct: 15, scrim: 0.6, announcePerS: 5, summaryWindowS: 5,
  multiples: [1, 1.5, 2, 3, 4], notionals: [250000, 375000, 500000, 750000, 1000000],
  linear: [3.0, 6.5, 10.0, 17.0, 24.0], sqrt: [3.0, 10.2, 14.1, 19.7, 24.0], log: [3.0, 9.1, 13.5, 19.6, 24.0],
  rMin: 3, rMax: 24, glyphR: 10, sqSide: [5.3, 17.7, 42.5], sqSideOverR: 1.772, shapeFloorR: 5, shapeFloorSide: 8.9, shapeFloorMultiple: 1.085, rAt11x: 5.3,
  capOutlineR: 27, capOutlineOffsetPx: 3, capGapPx: 2, barPx: 12, barsCovered: 4, areaPerStep: 594, aboveCapCount: 329, aboveCapPct: 0.16,
  belowShapeFloorPct: [6.0, 14.1, 49.4], tier2Multiple: 4, floor: 250000, cap: 1000000, midcapFloor: 50000, midcapCap: 200000, newlistSeed: 2000, newlistP99: 1732,
  thresholds: [250000, 100000, 30000, 10000], flaggedPct: [0.77, 4.3, 23.5, 57.5], suggested: 34723, userValue: 30000, capPct: 20, capQuantile: 80, minSamples: 20, refreshS: 5,
  clusterMs: 250, clusterTicks: 1, clusterCount: 7, clusterNotionalM: 1.9, bigNotionalM: 1.2, maxNotionalM: 18.9, compressedN: 27, compressedSum: 1.9,
  ringDefault: 10000, ringMax: 50000, ringMiB: 32, visibleBubbles: 5000, flashMaxHz: 3, flashUsed: 0, lodKeep: 500,
  tiers: 3, radii: 5, boards: 13, states: 23, pauseRows: 14, keyRows: 15, copyRows: 26, amendRows: 10, cRows: 22, cOwn: 17, gRows: 11, gOwn: 7, qRows: 15, bqRows: 6, pairsRows: 40, pairsFail: 0, reproMatch: 19,
  fontScale: [10, 11, 12, 13, 14, 16, 20, 24], targetPx: 24, chipPx: 20, iconPx: 24,
  contrast: { canvas: [15.2, 9.33, 5.96], raised: [14.35, 8.81, 5.62], sunken: [17.42, 10.69, 6.83], hover: [12.22, 7.5, 4.79], selected: [10.17, 6.24, 3.98], overlay: [13.27, 8.14, 5.2] },
  sep: { hue: [1.59, 1.23, 1.46], fill: [1.18, 1.08, 1.13] }, glyphOnRow: 3.75, bubbleOnCanvas: 3.97, warningChip: 9.86,
  weights: [400, 500, 700], summaryPrints: 212, summaryBuyPct: 61, summaryLargestK: 134, summaryBig: 3, whaleCount: 3, whaleLargestK: 410, price: 64012.0,
};
// Every term drawn on a board that is not a number: each string must appear verbatim in the spec (check-nums).
const TERMS = [
  "Tape BTCUSDT", "Filter prints (Ctrl+F)", "Threshold…", "Pause tape (P)", "Columns…", "More (Shift+F10)",
  "2 010 /s (1 s) · 33 /frame · +41 filtered", "2 010 /s (1 s) · 33 /frame", "2 010 /s (1 s)", "Loading…", "0 /s · quiet", "Paused — 412 prints buffered", "Paused — 412 buffered", "Paused — buffer full · 10 000 kept",
  "Paused — 412 prints buffered · Jump to live", "Stale 12s", "Stale 30s", "Offline", "Reconstructed after gap", "eff. 250k USDT",
  "eff. 34.7k USDT", "eff. 220k USDT", "capped", "(estimated)", "Big only", "Reconstructed 250 ms / 1 tick", "Raw prints", "≥ 10 000 USDT", "Sell only",
  "— 412 prints while paused —", "— gap 14:02:11.331 → 14:02:19.004 —", "— 1 240 prints while disconnected —", "— 12 000 prints while paused · 2 000 not kept —",
  "— No history before 13:58:02. Recording started then. —", "— clustering off from here —", "— clustering on from here —",
  "Load missed prints", "Clear filter", "Jump to live", "Apply 34 723", "Keep 30 000", "No prints above 10 000 USDT in the last 5 min",
  "No prints yet · last print 13:58:02", "Threshold flags 23.5 % of prints — raised to 34 723 USDT (the window's p80); prints between 30 000 and 34 723 are not flagged",
  "Size tier 2 = 4× · 1M USDT", "area-linear", "reconstructed 250 ms / 1 tick", "Threshold & bubbles", "▸ Threshold 250k · area-linear · 250 ms (estimated)",
  "liq", "blk", "27 small prints · Σ 1.9", "compressed", "Side (taker): Buy", "structured feed only", "on the binary feed", "2 columns need the structured feed",
  "Prints at the same price and side within 250 ms / 1 tick are shown as one row. Enter opens Why estimated?",
  "Big sell · 1.2M USDT · 64,012.0 · 14:02:11.208", "Cluster ×7 · 1.9M USDT · Sell · 7 prints within 250 ms / 1 tick · first print 14:02:11.208 · bar 14:02 · (estimated)",
  "Big trades · area-linear · 250k → 3 px · 1M → 24 px · >1M labelled", "Big trades · log · 250k → 3 px · 1M → 24 px · >1M labelled",
  "Smaller prints hidden at this zoom", "3 whale sells in 5 s, largest 410k at 64,012.0",
  "Last 5 s: 212 prints, 61 % buy by notional, largest sell 134k at 64,012.0, 3 big", "Resumed, 412 prints inserted", "Resumed, 10 000 prints inserted, 2 000 not kept", "Reconnected — gap 14:02:11.331 to 14:02:19.004", "1 240 missed prints loaded",
  "Threshold raised to 34 723 USDT — 23.5 % of prints were flagged", "Tape stale 12 seconds.", "Tape live.", "Notional moved up, 3 of 5",
  "Nothing to pause while disconnected.", "Read-only while viewing as {user}.", "Your role can't change settings.", "Your role can't save workspaces.",
  "Read-only — your role can't change settings.", "Read-only — your role can't save workspaces.", "Move up", "Move down", "Viewer", "permission leg", "Read tape summary", "Reset columns", "Density: Compact / Comfortable", "Open settings",
  "Sell, 18.75 BTC at 64,012.0, 1.2M, whale, 14:02:11.208", "Big sell, 42,000 USDT, 65,410, 14:32:01",
  "14:02:11.331 ▲ 64,012.5 4.00 ● 256.1k Buy", "14:02:11.208 ▼ 64,012.0 18.75 ◆ 1.2M Sell", "14:02:10.994 ▲ 64,012.5 0.12 7.7k Buy",
  "size tier (of a print)", "hover intent", "innermost cancel", "Tape, newest first", "Tape controls", "Tape status", "Threshold and bubbles",
  "Active filters", "Estimated, Trade cluster", "Not available", "PROPOSED", "RULED", "synthetic", "simulated", "greyscale", "deuteranopia",
  "outlined = PROPOSED default", "keyboard focus only", "one notice, many pointers", "the view-as leg comes first",
  "Disconnected — last data 00:12", "Reduced rate ×4", "Threshold mode", "Threshold value, USDT", "Smaller prints hidden at this zoom",
];
// The tape colours under greyscale and deuteranopia (memo §3.9; the tool's cvd section): drawn as simulated swatches on board 10.
const CVD = {
  "color.buy.default": { normal: "#2EBD59", greyscale: "#878787", deuteranopia: "#9F905E" },
  "color.sell.default": { normal: "#E5484D", greyscale: "#787878", deuteranopia: "#81744B" },
  "color.buy.subtle": { normal: "#0E3D1F", greyscale: "#2C2C2C", deuteranopia: "#332E20" },
  "color.sell.subtle": { normal: "#4E1518", greyscale: "#262626", deuteranopia: "#292517" },
  "color.text.primary": { normal: "#E8EAED", greyscale: "#EAEAEA", deuteranopia: "#E9EAED" },
  "color.text.tertiary": { normal: "#8B949E", greyscale: "#929292", deuteranopia: "#8E929E" },
  "color.surface.raised": { normal: "#161B22", greyscale: "#1A1A1A", deuteranopia: "#181A22" },
  "color.surface.canvas": { normal: "#11151A", greyscale: "#141414", deuteranopia: "#12141A" },
};

// ---------------------------------------------------------------- single writer -----------------------------
if (typeof storage === "undefined" || storage.hpe1inst !== WRITER) {
  return { skip: typeof storage === "undefined" ? null : storage.hpe1inst, note: "not the writer instance — run probe.js, pick one stamp, set WRITER" };
}

// ---------------------------------------------------------------- guard + page -----------------------------
const warnings = [];
const warn = (where, e) => warnings.push(where + ": " + (e && e.message ? e.message : String(e)));
if (!penpot.currentFile || penpot.currentFile.id !== FILE_ID) {
  return { abort: "file", current: penpot.currentFile ? { id: penpot.currentFile.id, name: penpot.currentFile.name } : null };
}
const norm = (s) => String(s || "").replace(/\s*\/\s*/g, "/");
const pages = penpot.currentFile.pages || [];
function classifyPage(p) {
  const out = { id: p.id, name: p.name, ours: 0, foreign: 0, unknown: false };
  try {
    for (const s of (p.root && p.root.children) || []) { if (norm(s.name).startsWith(TICKET + "/")) out.ours++; else out.foreign++; }
  } catch (e) { out.unknown = true; warn("classify " + p.id, e); }
  return out;
}
const named = pages.filter((p) => p.name === PAGE_NAME).map(classifyPage);
let page = PAGE_ID ? pages.find((p) => p.id === PAGE_ID) || null : null;
if (!page && named.length) {
  const clean = named.filter((c) => !c.unknown && c.foreign === 0);
  if (!clean.length) return { abort: "all-candidate-pages-hold-foreign-content", pages: named, note: "decide by hand which page is ours; nothing was touched" };
  clean.sort((a, b) => (b.ours - a.ours));
  page = pages.find((p) => p.id === clean[0].id) || null;
}
const duplicatePages = named.filter((c) => !page || c.id !== page.id).map((c) => Object.assign({}, c, {
  action: c.unknown ? "keep — shapes unreadable; probe read-only, decide by hand"
    : c.foreign > 0 ? "keep — foreign content; never ours to delete"
    : c.ours > 0 ? "delete MANUALLY in the Penpot UI after this build, once a read-only probe shows it holds only E22-D02 / frames"
    : "delete MANUALLY in the Penpot UI (empty page)",
}));
let createdPage = false;
if (!page) {
  page = penpot.createPage();
  page.name = PAGE_NAME;
  createdPage = true;
}
if (!penpot.currentPage || penpot.currentPage.id !== page.id) {
  try {
    const r = penpot.openPage(page);
    if (r && typeof r.then === "function") await r;
  } catch (e) {
    warn("openPage", e);
  }
}
if (!penpot.currentPage || penpot.currentPage.id !== page.id) {
  return { retry: true, pageId: page.id, pageName: page.name, createdPage, note: "page not current yet — run again, or open it in the UI first" };
}
// ---- from here on: synchronous only (no await) ----

// ---------------------------------------------------------------- tokens (dark theme, NEUTRAL only, resolved at the base) ------------
const C = { canvas: "#11151A", raised: "#161B22", overlay: "#1C222B", hover: "#22292F", selected: "#2E363E", app: "#0B0E11", sunken: "#000000", text: "#E8EAED", text2: "#B1BAC4", text3: "#8B949E", border: "#2E363E", borderStrong: "#3D4650" };
const TOK = { canvas: "color.surface.canvas", raised: "color.surface.raised", overlay: "color.surface.overlay", hover: "color.surface.hover", selected: "color.surface.selected", app: "color.surface.app", sunken: "color.surface.sunken", text: "color.text.primary", text2: "color.text.secondary", text3: "color.text.tertiary", border: "color.border.default", borderStrong: "color.border.strong" };

// ---------------------------------------------------------------- helpers ------------------------------------
const FONT = (() => { try { const all = (penpot.fonts && penpot.fonts.all) || []; return all.find((f) => f.fontId === "gfont-inter") || all.find((f) => f.name === "Inter") || null; } catch (e) { warn("fonts", e); return null; } })(); // exact lookup: findByName("Inter") prefix-matches Inter Tight on the self-hosted file (PENPOT-FONTS 2026-10-21)
const MONO = (() => { try { return penpot.fonts && penpot.fonts.findByName ? penpot.fonts.findByName("JetBrains Mono") : null; } catch (e) { return null; } })();
function variant(font, weight) {
  try { return (font.variants || []).find((v) => String(v.fontWeight) === String(weight) && (v.fontStyle || "normal") === "normal") || null; } catch (e) { return null; }
}
function set(obj, props) { for (const k of Object.keys(props)) { try { obj[k] = props[k]; } catch (e) { warn("set " + k, e); } } }
function tag(shape, meta) {
  try { shape.setPluginData(TAG, "v1"); shape.setPluginData(TAG + ":meta", JSON.stringify(meta || {})); } catch (e) { warn("tag", e); }
}
function pad2(n) { return (n < 10 ? "0" : "") + n; }
const NB = (s) => String(s).replace(/ /g, " "); // a label whose words must never wrap (Penpot breaks at spaces and hyphens only). r8: ONLY for a text drawn in an explicit one-line box (o.h) that fits it — never for a multi-line note (an NBSP-joined note can break only at a hyphen, so it clipped at the board edge or ran under the neighbouring cards on boards 04–07 / 09 — QA A); the self-check throws on any NBSP text wider than its box
const NBSP_RE = /\u00a0/;
const EMOJI_RE = (() => { try { return new RegExp("\\p{Emoji_Presentation}|\\uFE0F", "u"); } catch (e) { return /[\uD83C-\uD83E][\uDC00-\uDFFF]|\uFE0F/; } })(); // r8 (QA B): a character that renders as a COLOUR emoji by default — 🔒 did (a gold padlock on the greyscale boards 05 / 06); ⏸ ▶ ◀ ☑ ☐ ◉ ○ are text-presentation and pass
// r8 (QA B): the T2 lock is DRAWN — two neutral rects in the middle grey (color.text.tertiary, the ⏸ button's own T2 grey): the shackle (a stroked rounded rect)
// behind the body (a filled rounded rect) — never the 🔒 emoji, so the T2 state is carried by shape, not colour (§0 / §10: neutral tokens only; board 10's swatches excepted)
const LOCK = { w: 9, h: 11 }, LOCK_RE = /^🔒[ \u00a0]?/;
function lockGlyph(parent, x, y, o) { // a padlock of width s (default 9 → 11 px tall): CMP-019 Icon lock, catalogue name "Not available"; no path shape (SEG budget stays 0)
  o = o || {}; const s = o.size || LOCK.w, ink = o.ink || "text3", shW = Math.round(s * 0.6), shH = Math.round(s * 0.8), bodyH = Math.round(s * 0.7);
  mkRect(parent, x + (s - shW) / 2, y, shW, shH, null, { stroke: ink, strokeWidth: 1.5, radius: shW / 2, role: "wire", name: (o.name || "lock") + "-shackle", blk: o.blk, stk: o.stk, binds: "CMP-019 Icon lock (Not available) — drawn, neutral" });
  mkRect(parent, x, y + shH - 2, s, bodyH, ink, { radius: 1.5, role: "wire", name: (o.name || "lock") + "-body", blk: o.blk, stk: o.stk });
  return s;
}
function lockText(parent, str, x, y, w, o) { // "🔒 label" as the drawn lock + the label in the rest of its box (menu items, the panel notice, the echo label)
  o = o || {}; const lh = o.h || Math.ceil((o.size || 11) * 1.38);
  lockGlyph(parent, x, y + Math.max(0, (lh - LOCK.h) / 2), { blk: o.blk, stk: o.stk, name: (o.name || "text") + "-lock" });
  return mkText(parent, String(str).replace(LOCK_RE, ""), x + LOCK.w + 4, y, w - LOCK.w - 4, o);
}
function estH(str, w, size, mono) { // conservative wrap estimate: 0.56 em Inter / 0.62 em mono, +0.4 lines, +6 px
  const cpl = Math.max(6, Math.floor(w / (size * (mono ? 0.62 : 0.56))));
  let lines = 0;
  for (const para of String(str).split("\n")) lines += Math.max(1, Math.ceil(para.length / cpl));
  return Math.ceil((lines + 0.4) * size * 1.38) + 6;
}
let blockSeq = 0;
// ---- the shape budget (r5; ported from the E14-D06 r7 script): ONE plugin call creates at most SHAPE_BUDGET shapes. Every shape goes through
// create(); a shape outside the call's part is a plain record (dry), never created in Penpot, so every x, y, size and block id equals the
// one-call build's. A unit is a top-level piece of a board — every helper call made straight from a board's builder (a card, a table, a strip,
// a tape, the panel chrome, a pill, a lone text or rect, the footer) — and the split never cuts inside one. Every shape here is a direct child
// of its board (no nested frames), so a part only needs the board part 1 created.
let DRY = false, CUR_BOARD = null, UNIT_DEPTH = 0;
const SPLIT = { plan: null, counts: null, segs: null, idx: 0, dryAll: false };
const BOARD_ROOTS = new WeakSet(); // the board-root marks live here, never as properties on a shape (the plugin API's shapes are not extensible)
const CREATED = []; // every live shape this call created, in order; rollback() removes them when the call throws
const FIT = []; // the planning pass's single-line texts that would wrap in their box, read by selfCheck()
const NBFIT = [], EMOJI = []; // r8: NBSP texts wider than their box (strict — no KNOWN_WRAPS exemption) and texts holding an emoji-presentation character; both throw in selfCheck()
const HDR = [], OVERRUN = [], DRYREC = []; // r9: tape header labels that touch (HDR), shapes whose right edge leaves the rect they sit in (OVERRUN) — both throw in selfCheck(); DRYREC = the planning pass's shapes of the board being planned, in z-order, read by containment()
function dryShape(type, txt) { return { type, dry: true, unitIdx: SPLIT.idx, id: null, x: 0, y: 0, width: 1, height: 1, name: "", text: txt == null ? null : String(txt), fills: [], strokes: [], pd: {}, resize(w, h) { this.width = w; this.height = h; }, appendChild() {}, setPluginData(k, v) { this.pd[k] = v; }, getPluginData(k) { return this.pd[k]; }, remove() {} }; }
function create(type, txt) {
  if (SPLIT.counts) SPLIT.counts[SPLIT.idx] = (SPLIT.counts[SPLIT.idx] || 0) + 1;
  if (DRY) { const d = dryShape(type, txt); if (SPLIT.dryAll) DRYREC.push(d); return d; }
  const s = type === "text" ? penpot.createText(String(txt)) : type === "rect" ? penpot.createRectangle() : type === "ellipse" ? penpot.createEllipse() : penpot.createBoard();
  if (s) CREATED.push(s);
  return s;
}
function rollback() { // a throw after the first live create removes this call's shapes (last first), so the page is left as it was
  let n = 0;
  for (let i = CREATED.length - 1; i >= 0; i--) { try { CREATED[i].remove(); n++; } catch (e) { warn("rollback", e); } }
  CREATED.length = 0;
  return n;
}
function rolledBack(e) { return new Error((e && e.message ? e.message : String(e)) + " — rolled back " + rollback() + " shape(s) this call created; the old board was not removed"); }
function attach(parent, child) { // a dry child is never appended; a live child under a dry parent is a split bug
  if (child.dry) return;
  if (parent.dry) throw new Error("part split: a live shape under a dry parent (" + child.name + ")");
  parent.appendChild(child);
}
function unitWrap(fn) { // a top-level unit boundary: a helper called straight from a board's builder (depth 0) opens the next unit
  return function () {
    if (UNIT_DEPTH === 0 && CUR_BOARD) { SPLIT.idx++; DRY = SPLIT.dryAll || (SPLIT.plan ? SPLIT.plan[SPLIT.idx] !== PART : false); }
    UNIT_DEPTH++;
    try { return fn.apply(null, arguments); } finally { UNIT_DEPTH--; }
  };
}
function mkText(parent, str, x, y, w, o) {
  o = o || {};
  const t = create("text", str);
  if (!t) { warn("createText", "returned null for: " + String(str).slice(0, 40)); return null; }
  t.name = TICKET + " / " + (o.name || "text");
  const size = o.size || 13;
  try { const f = o.mono ? MONO : FONT; if (f && !t.dry) f.applyToText(t, variant(f, o.weight || 400) || undefined); } catch (e) { warn("applyToText", e); }
  set(t, { fontSize: String(size), fontWeight: String(o.weight || 400), lineHeight: "1.38", growType: "auto-height", align: o.align || "left" });
  const h = o.h || estH(str, w, size, !!o.mono);
  t.resize(w, h);
  t.x = x; t.y = y;
  t.fills = [{ fillColor: o.color || C.text, fillOpacity: o.opacity == null ? 1 : o.opacity }];
  if (o.halo) t.strokes = [{ strokeColor: C.canvas, strokeOpacity: 1, strokeWidth: 1, strokeStyle: "solid", strokeAlignment: "outer" }]; // r8: a 1 px canvas halo (board 08's bubble notes over the bars)
  tag(t, { role: "text", tok: o.tok || TOK.text, blk: o.blk, stk: o.stk, idx: o.idx, after: o.after, halo: o.halo ? TOK.canvas : undefined });
  if (SPLIT.dryAll && CUR_BOARD) { // r5: a single-line text (an explicit one-line box: pills, Kbd hints, chips, tape cells, the readout, notices, labels) must fit its box at the shared PILL_EM upper bounds (JetBrains Mono 0.62 em);
    // r8: so must EVERY line holding an NBSP (it cannot break at a space — wider than its box it clips or runs under its neighbours; strict, no known-wrap exemption), and no text may hold an emoji-presentation character (it renders in colour on a greyscale board)
    const where = CUR_BOARD.name + " :: " + t.name.replace(TICKET + " / ", "") + " ";
    t.estW = Math.max(0, ...String(str).split("\n").map((ln) => fitW(ln, size, !!o.mono))); // r9: the widest line's estimated advance, read by containment()
    if (EMOJI_RE.test(String(str))) EMOJI.push(where + JSON.stringify(String(str).slice(0, 60)));
    for (const ln of String(str).split("\n")) {
      const nb = NBSP_RE.test(ln);
      if (!nb && !(o.single || o.h != null)) continue;
      const need = fitW(ln, size, !!o.mono);
      if (need > w + 0.5) (nb ? NBFIT : FIT).push(where + JSON.stringify(ln) + " needs " + Math.ceil(need) + " px in a " + Math.round(w) + " px box");
    }
  }
  attach(parent, t);
  return { shape: t, h };
}
function mkRect(parent, x, y, w, h, fillKey, o) {
  o = o || {};
  const r = create("rect");
  r.name = TICKET + " / " + (o.name || "rect");
  r.x = x; r.y = y; r.resize(Math.max(1, w), Math.max(1, h));
  r.fills = fillKey ? [{ fillColor: C[fillKey], fillOpacity: o.opacity == null ? 1 : o.opacity }] : [];
  if (o.stroke) r.strokes = [{ strokeColor: C[o.stroke], strokeOpacity: 1, strokeWidth: o.strokeWidth || 1, strokeStyle: o.dashed ? "dashed" : "solid", strokeAlignment: "inner" }];
  if (o.radius) set(r, { borderRadius: o.radius });
  tag(r, { role: o.role || "rect", tok: fillKey ? TOK[fillKey] : null, strokeTok: o.stroke ? TOK[o.stroke] : null, blk: o.blk, stk: o.stk, idx: o.idx, bg: !!o.bg, pad: o.pad, gap: o.gap, binds: o.binds });
  attach(parent, r);
  return r;
}
function mkSwatch(parent, x, y, w, h, hex, meta) { // a simulated-colour swatch: the hex comes from CVD (the tool), not from a token — board 10 only
  const r = create("rect");
  r.name = TICKET + " / swatch";
  r.x = x; r.y = y; r.resize(Math.max(1, w), Math.max(1, h));
  r.fills = [{ fillColor: hex, fillOpacity: 1 }];
  r.strokes = [{ strokeColor: C.border, strokeOpacity: 1, strokeWidth: 1, strokeStyle: "solid", strokeAlignment: "inner" }];
  set(r, { borderRadius: 4 });
  tag(r, Object.assign({ role: "wire", tok: null, simulated: hex }, meta || {}));
  attach(parent, r);
  return r;
}
function mkDisc(parent, cx, cy, r, fillKey, o) { // a buy bubble: filled disc; o.ring = a 2 px stroke-only outline (the cap outline around a filled mark)
  o = o || {};
  const e = create("ellipse");
  e.name = TICKET + " / " + (o.name || "disc");
  e.x = cx - r; e.y = cy - r; e.resize(Math.max(1, 2 * r), Math.max(1, 2 * r));
  e.fills = o.ring ? [] : [{ fillColor: C[fillKey], fillOpacity: o.opacity == null ? 1 : o.opacity }];
  if (o.ring) e.strokes = [{ strokeColor: C[fillKey], strokeOpacity: 1, strokeWidth: 2, strokeStyle: "solid", strokeAlignment: "inner" }];
  tag(e, { role: "wire", tok: TOK[fillKey], blk: o.blk, stk: o.stk });
  attach(parent, e);
  return e;
}
function mkSquare(parent, cx, cy, r, fillKey, o) { // the sell mark: a filled square of the disc's area, side = r·√π (memo F16)
  o = o || {};
  const side = r * Math.sqrt(Math.PI) + (o.grow || 0); // o.grow: the cap outline sits outside the fill
  const q = create("rect");
  q.name = TICKET + " / " + (o.name || "square");
  q.x = cx - side / 2; q.y = cy - side / 2; q.resize(Math.max(1, side), Math.max(1, side));
  q.fills = o.outline ? [] : [{ fillColor: C[fillKey], fillOpacity: o.opacity == null ? 1 : o.opacity }];
  if (o.outline) q.strokes = [{ strokeColor: C[fillKey], strokeOpacity: 1, strokeWidth: 2, strokeStyle: "solid", strokeAlignment: "inner" }];
  tag(q, { role: "wire", tok: TOK[fillKey], blk: o.blk, stk: o.stk });
  attach(parent, q);
  return q;
}
function mkBoard(n, slug, x, y, w, h) {
  const b = create("board");
  BOARD_ROOTS.add(b);
  b.name = TICKET + " / " + pad2(n) + " " + slug;
  b.x = x; b.y = y; b.resize(w, h);
  b.fills = [{ fillColor: C.canvas, fillOpacity: 1 }];
  set(b, { clipContent: false });
  tag(b, { role: "board", board: n, slug, tok: TOK.canvas, exportAs: EXPORT_DIR + "/" + TICKET + "-" + pad2(n) + "-" + slug + ".png" });
  try { b.setPluginData("hpe1ver", VERSION); } catch (e) { warn("hpe1ver", e); }
  return b;
}
function card(parent, x, y, w, o) { // background rect + texts stacked inside; the value line (16 px) leads (boards-round Minor 5)
  o = o || {};
  const pad = 14, gap = o.gap == null ? 12 : o.gap;
  const blk = TICKET + ":" + (++blockSeq);
  const stk = o.stk || blk;
  let cy = y + pad, bottom = y + pad;
  const push = (txt, opts) => { const r = mkText(parent, txt, x + pad, cy, w - 2 * pad, Object.assign({ blk, stk, idx: o.idx }, opts)); if (r) { bottom = cy + r.h; cy += r.h + (opts.after == null ? 6 : opts.after); } };
  const bg = mkRect(parent, x, y, w, 10, o.fill || "raised", { stroke: o.stroke || "border", strokeWidth: o.strokeWidth || 1, radius: 8, role: "card-bg", bg: true, pad, gap, blk, stk, idx: o.idx, name: "card" });
  if (o.kicker) push(o.kicker, { size: 11, weight: 600, color: o.kickerColor || C.text3, tok: TOK.text3, name: "kicker", after: 2 });
  if (o.value) push(o.value, { size: 16, weight: 700, name: "value", after: 6, mono: !!o.valueMono });
  if (o.title) push(o.title, { size: o.titleSize || 14, weight: 700, name: "title", after: 6 });
  if (o.body) push(o.body, { size: 12, color: C.text2, tok: TOK.text2, name: "body", after: 6 });
  if (o.lines) for (const ln of o.lines) push(ln, { size: 12, color: C.text2, tok: TOK.text2, name: "line", after: 4, mono: !!o.mono });
  if (o.foot) push(o.foot, { size: 11, weight: 500, color: C.text3, tok: TOK.text3, name: "foot", after: 0 });
  const h = bottom - y + pad; // r6: the last text's bottom + pad — the relayout restack's model (r5's "cy - y + pad - 4" was 4 px short under a foot, so the restack regrew every card)
  bg.resize(w, h);
  return { h, bg, blk, stk };
}
const PILL_EM = { upper: 0.84, wideLower: 0.95, lower: 0.56, digit: 0.68, thin: 0.34, symbol: 1.0 }; // the shared pill-label width rule (orchestrator 2026-10-21 18:21Z): per glyph class, an upper bound on Inter's advance in em
function pillTextW(label, size, mono) { // the label box a pill needs: never narrower than the flat 0.62 em estimate
  const flat = Math.ceil(String(label).length * size * 0.62);
  if (mono) return flat;
  let em = 0;
  for (const ch of String(label)) em += /[A-Z]/.test(ch) ? PILL_EM.upper : /[mw]/.test(ch) ? PILL_EM.wideLower : /[a-z]/.test(ch) ? PILL_EM.lower : /[0-9]/.test(ch) ? PILL_EM.digit : /[\s .,:;·'’|-]/.test(ch) ? PILL_EM.thin : PILL_EM.symbol;
  return Math.max(flat, Math.ceil(em * size));
}
function fitW(label, size, mono) { // r5: the self-check's width of one line: the shared PILL_EM class sum (an upper bound on Inter's advance; no flat floor), JetBrains Mono at 0.62 em
  if (mono) return String(label).length * size * 0.62;
  let em = 0;
  for (const ch of String(label)) em += /[A-Z]/.test(ch) ? PILL_EM.upper : /[mw]/.test(ch) ? PILL_EM.wideLower : /[a-z]/.test(ch) ? PILL_EM.lower : /[0-9]/.test(ch) ? PILL_EM.digit : /[\s .,:;·'’|-]/.test(ch) ? PILL_EM.thin : PILL_EM.symbol;
  return em * size;
}
// r7: the catalogue bindings of the named chips (the orchestrator's checklist item 4; E22-D03 boards-lens classes a / b / d). CMP-239 feed chips
// (`15` CMP-239; E08-D04 §4 "dot+text") = surface + text + the 6 px indicator dot, Border none; only the S9 strong chip adds the indicator as
// its 1 px outline too (E17-D01 D16). CMP-227 `inline` sm = the registry `estimated` glyph (≈ alone at size.icon.sm 12 px) + the word. A removable
// CMP-011 chip = the label + its CMP-002 remove control (×) in its own 14 px box, never a bare × in the label. Greyscale stand-ins (E13-D02 §13):
// the dot and the glyph in color.text.primary, the stale surface tint as color.surface.sunken, the offline / gapped chips on the row's raised.
const CHIP_DOT = 6, CHIP_GLYPH = 12;
const CHIP_BIND = {
  "Stale 12s": { dot: true, fill: "sunken", noStroke: true, binds: "CMP-239 stale (S8): color.data-confidence.stale.surface / .text / .indicator" },
  "Stale 30s": { dot: true, fill: "sunken", stroke: "borderStrong", strokeWidth: 1, binds: "CMP-239 stale strong (S9): the indicator as the outline too" },
  "Offline": { dot: true, fill: "raised", noStroke: true, binds: "CMP-239 disconnected (S10): color.data-confidence.disconnected.text / .indicator" },
  "Reconstructed after gap": { dot: true, fill: "raised", noStroke: true, binds: "CMP-239 gapped (S15 / S16): color.data-confidence.gapped.text / .indicator" },
  "(estimated)": { est: true, binds: "CMP-227 inline sm: the estimated glyph (size.icon.sm) + the word" },
};
function chipBind(label) { const s = String(label), b = CHIP_BIND[s]; if (b) return b; if (LOCK_RE.test(s)) return { lock: true, binds: "CMP-019 Icon lock leads a T2 label (E09-D09 §2.2) — drawn, neutral" }; if (/ ×$/.test(s)) return { removeBtn: true, binds: "CMP-011 removable: the label + the CMP-002 remove control" }; return null; } // r8: a "🔒 …" label draws the lock as its own shapes
const pillLabel = (label, b) => (b.removeBtn ? String(label).replace(/ ×$/, "") : b.lock ? String(label).replace(LOCK_RE, "") : String(label)); // r8: the text a pill draws (the × box and the drawn lock are their own shapes)
function pillW(label, size, mono, o) { // the box pill() draws for this label — every layout helper wraps on it, so the drawn widths and the wrap agree
  o = o || {}; if (o.w) return o.w;
  const b = chipBind(label) || {}, padX = o.padX == null ? 8 : o.padX, tw = pillTextW(pillLabel(label, b), size, mono);
  if (b.removeBtn) return padX + tw + 4 + 14 + 4;
  if (b.dot) return padX + CHIP_DOT + 4 + tw + padX;
  if (b.est) return padX + CHIP_GLYPH + 4 + tw + padX;
  if (b.lock) return padX + LOCK.w + 4 + tw + padX;
  return tw + 2 * padX;
}
function pill(parent, x, y, label, o) { // a chip / badge / pill / Kbd hint: the box fits the label (pillW), the words are NBSP-joined; returns its width
  o = o || {};
  const b = chipBind(label) || {};
  const h = o.h || 20, size = o.size || 11;
  const padX = o.padX == null ? 8 : o.padX, text = pillLabel(label, b);
  const tw = pillTextW(text, size, !!o.mono), w = pillW(label, size, !!o.mono, o);
  const fill = b.fill || o.fill || "raised", stroke = b.noStroke ? null : b.stroke || o.stroke || "border";
  mkRect(parent, x, y, w, h, fill, { radius: o.radius == null ? h / 2 : o.radius, stroke, strokeWidth: b.strokeWidth || o.strokeWidth || 1, dashed: o.dashed, role: "pill", blk: o.blk, stk: o.stk, idx: o.idx, name: o.name || "pill", binds: b.binds });
  let lx = x + padX;
  const ty = y + Math.max(1, (h - size * 1.38) / 2), lh = Math.ceil(size * 1.38);
  if (b.dot) { mkDisc(parent, lx + CHIP_DOT / 2, y + h / 2, CHIP_DOT / 2, "text", { name: "chip-indicator-dot", blk: o.blk, stk: o.stk }); lx += CHIP_DOT + 4; }
  if (b.est) { const gh = Math.ceil(CHIP_GLYPH * 1.38); mkText(parent, "≈", lx, y + Math.max(1, (h - gh) / 2), CHIP_GLYPH, { size: CHIP_GLYPH, weight: 700, align: "center", color: o.textColor || C.text, tok: o.textTok || TOK.text, name: "chip-estimated-glyph", blk: o.blk, stk: o.stk, idx: o.idx, h: gh }); lx += CHIP_GLYPH + 4; }
  if (b.lock) { lockGlyph(parent, lx, y + Math.max(0, (h - LOCK.h) / 2), { name: "pill-lock", blk: o.blk, stk: o.stk }); lx += LOCK.w + 4; } // r8: the drawn lock leads a T2 label
  mkText(parent, NB(text), lx, ty, b.dot || b.est || b.removeBtn || b.lock ? tw : Math.max(tw, w - 2 * padX), { size, weight: o.weight || 500, mono: !!o.mono, color: o.textColor || C.text, tok: o.textTok || TOK.text, name: "pill-label", blk: o.blk, stk: o.stk, idx: o.idx, h: lh });
  if (b.removeBtn) mkText(parent, "×", lx + tw + 4, ty, 14, { size, align: "center", color: o.textColor || C.text, tok: o.textTok || TOK.text, name: "chip-remove-button", blk: o.blk, stk: o.stk, idx: o.idx, h: lh });
  return w;
}
function kbd(parent, x, y, keys) { // a Kbd hint: a square-cornered pill in mono (every key hint on these boards is PROPOSED, spec §11)
  return pill(parent, x, y, keys, { h: 20, size: 11, mono: true, radius: 4, fill: "hover", stroke: "borderStrong", name: "kbd" });
}
function stamp(parent, x, y, word) { // the PROPOSED / RULED stamp a recommending board carries (neutral: hover fill, strong border)
  return pill(parent, x, y, word, { h: 24, size: 11, weight: 700, fill: "hover", stroke: "borderStrong", name: "stamp" });
}
function tableBlock(parent, x, y, widths, header, rows, o) { // row height = the max wrapped height over all cells, label column included
  o = o || {};
  const pad = 8, size = o.size || 11, stk = o.stk || TICKET + ":tbl" + (++blockSeq);
  let cy = y, idx = 0;
  const totalW = widths.reduce((a, b) => a + b, 0);
  const drawRow = (cells, isHeader) => {
    const blk = TICKET + ":" + (++blockSeq);
    let est = 0;
    for (let i = 0; i < cells.length; i++) est = Math.max(est, estH(cells[i], widths[i] - 2 * pad, size, !!(o.mono && o.mono[i]) && !isHeader)); // r6: the cell as drawn — a header is never mono (r5 estimated it at 0.62 em: board 12's keys header 15 px too tall, its rows re-laid)
    mkRect(parent, x, cy, totalW, est + 2 * pad, isHeader ? "hover" : idx % 2 ? "raised" : "canvas", { role: "row-bg", bg: true, pad, gap: 0, blk, stk, idx, stroke: "border", name: isHeader ? "table-header" : "table-row" });
    let cx = x;
    for (let i = 0; i < cells.length; i++) {
      mkText(parent, cells[i], cx + pad, cy + pad, widths[i] - 2 * pad, { size, weight: isHeader ? 700 : i === 0 ? 600 : 400, mono: !!(o.mono && o.mono[i]) && !isHeader, color: isHeader ? C.text : i === 0 ? C.text : C.text2, tok: isHeader || i === 0 ? TOK.text : TOK.text2, blk, stk, idx, name: isHeader ? "th" : "td" });
      cx += widths[i];
    }
    cy += est + 2 * pad;
    idx++;
  };
  drawRow(header, true);
  for (const r of rows) drawRow(r, false);
  return { h: cy - y, stk };
}
function title(parent, x, y, w, t, sub) {
  const a = mkText(parent, t, x, y, w, { size: 24, weight: 700, name: "board-title" });
  let h = a ? a.h : 30;
  if (sub) { const b = mkText(parent, sub, x, y + h + 2, w, { size: 12, color: C.text2, tok: TOK.text2, name: "board-subtitle" }); h += (b ? b.h : 16) + 2; }
  return h + 10;
}
// A state strip: labelled cells joined by arrows; each cell stacks a value line, a detail and its pills (drawn side by side, never one merged pill).
function strip(parent, x, y, w, label, cells, o) {
  o = o || {}; const blk = TICKET + ":" + (++blockSeq), stk = TICKET + ":" + (o.stk || "strip" + blockSeq);
  const hdr = mkText(parent, label, x, y, w, { size: 12, weight: 700, color: C.text3, tok: TOK.text3, name: "strip-label", blk, stk });
  const top = y + (hdr ? hdr.h : 16) + 6, gap = 26, bwEq = Math.floor((w - gap * (cells.length - 1)) / cells.length);
  const PH = 20, PGAP = 8, PROW = 6;
  const pillsOf = (c) => c.pills || (c.pill ? [{ label: c.pill, mono: c.pillMono, kbd: c.pillKbd, fill: c.pillFill, stroke: c.pillStroke, button: c.pillButton }] : []); // r7: a lone pill's fill / stroke / button reach pill() (r6 dropped them)
  const need = cells.map((c) => pillsOf(c).reduce((m, p) => Math.max(m, pillW(p.label, 11, !!p.mono) + 20), 0)), grow = need.map((n) => Math.max(0, n - bwEq));
  const extra = grow.reduce((a, b) => a + b, 0), nFree = grow.filter((g) => g === 0).length, cut = extra > 0 && nFree ? Math.ceil(extra / nFree) : 0;
  const bws = cells.map((c, i) => (grow[i] > 0 ? need[i] : bwEq - cut)), inners = bws.map((v) => v - 20);
  const pillRows = (ps, inner) => { const rows = []; let cur = [], px = 0; for (const p of ps) { const pw = pillW(p.label, 11, !!p.mono); if (cur.length && px + pw > inner) { rows.push(cur); cur = []; px = 0; } cur.push(p); px += pw + PGAP; } if (cur.length) rows.push(cur); return rows; };
  const vH = cells.map((c, i) => (c.v ? estH(c.v, inners[i], 16) : 0)), tH = cells.map((c, i) => estH(c.t, inners[i], 12)), dH = cells.map((c, i) => (c.d ? estH(c.d, inners[i], 11) : 0)), pR = cells.map((c, i) => pillRows(pillsOf(c), inners[i]));
  const pillsH = (rows) => (rows.length ? rows.length * PH + (rows.length - 1) * PROW : 0);
  let bh = 0;
  cells.forEach((c, i) => { bh = Math.max(bh, 10 + (c.v ? vH[i] + 2 : 0) + tH[i] + (c.d ? 4 + dH[i] : 0) + (pR[i].length ? 8 + pillsH(pR[i]) : 0) + 10); });
  bh = Math.max(bh, o.bh || 0);
  let bx = x;
  cells.forEach((c, i) => {
    const bw = bws[i], inner = inners[i];
    mkRect(parent, bx, top, bw, bh, c.fill || "raised", { stroke: c.decision ? "text" : "border", strokeWidth: c.decision ? 2 : 1, radius: 8, role: "wire", name: "strip-cell", blk, stk });
    let ty = top + 10;
    if (c.v) { mkText(parent, c.v, bx + 10, ty, inner, { size: 16, weight: 700, name: "strip-value", blk, stk, mono: !!c.vMono }); ty += vH[i] + 2; }
    mkText(parent, c.t, bx + 10, ty, inner, { size: 12, weight: c.v ? 500 : 700, name: "strip-title", blk, stk, mono: !!c.mono, color: c.v ? C.text2 : C.text, tok: c.v ? TOK.text2 : TOK.text });
    if (c.d) mkText(parent, c.d, bx + 10, ty + tH[i] + 4, inner, { size: 11, color: C.text2, tok: TOK.text2, name: "strip-detail", blk, stk });
    let py = top + bh - 10 - pillsH(pR[i]);
    for (const row of pR[i]) {
      let px = bx + 10;
      for (const p of row) px += (p.kbd ? kbd(parent, px, py, p.label) : pill(parent, px, py, p.label, { h: PH, size: 11, fill: p.fill || "raised", stroke: p.stroke || "border", radius: p.button ? 4 : undefined, weight: p.button ? 700 : undefined, mono: !!p.mono, textColor: p.text || C.text, textTok: p.tok || TOK.text, blk, stk, name: p.button ? "strip-button:" + p.label : "strip-pill" })) + PGAP; // r7: p.button = a CMP-001 button (4 px corners, bold), never a round chip
      py += PH + PROW;
    }
    if (i < cells.length - 1) mkText(parent, c.arrow || "→", bx + bw + 5, top + bh / 2 - 10, gap - 6, { size: 16, color: C.text3, tok: TOK.text3, align: "center", name: "strip-arrow", blk, stk });
    bx += bw + gap;
  });
  return { h: (hdr ? hdr.h : 16) + 6 + bh, stk };
}
const fmt = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " ");

// ---------------------------------------------------------------- the tape (spec §2–§3; boards-round Minor 2: a real tape) ----------
// Synthetic rows (labelled on every board): the memo's three example rows' times and prices first — their sizes rescaled so
// the tiers hold at the majors' seed (spec D02-C9: the memo's 54.4k / 134.4k cannot both hold under the 4× rule) — then a
// deterministic sequence (LCG seed 507) descending from 14:02:11.331, prices around 64,012 in 0.5 steps, BTCUSDT-plausible
// sizes. EVERY row's tier is computed from the notional at the majors' seeds (250 000 → tier 1, 1 000 000 → tier 2), never
// typed. No number here is market evidence.
const fmtNotional = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : (n / 1e3).toFixed(1) + "k");
const fmtPrice = (p) => p.toFixed(1).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
function tapeRow(time, side, size, price, tags, thr) { // r7: thr = the frame's effective threshold (default the majors' 250 000; an S18 frame passes 34 723), tier 2 at 4× (G8)
  const t1 = thr || NUM.floor, t2 = thr ? thr * NUM.tier2Multiple : NUM.cap;
  const notional = size * price, tier = notional >= t2 ? 2 : notional >= t1 ? 1 : 0;
  return { time, side, price: fmtPrice(price), size: size.toFixed(2), notional: fmtNotional(notional), tier, tags: tags || [] };
}
const MEMO_ROWS = [["14:02:11.331", "buy", NUM.memoSizes[0], 64012.5], ["14:02:11.208", "sell", NUM.memoSizes[1], 64012.0], ["14:02:10.994", "buy", NUM.memoSizes[2], 64012.5]];
const memoRows = () => MEMO_ROWS.map((r) => tapeRow(r[0], r[1], r[2], r[3]));
function tapeRows(n, seedOffset, thr) {
  let s = 507 + (seedOffset || 0);
  const rnd = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
  const rows = thr ? MEMO_ROWS.map((r) => tapeRow(r[0], r[1], r[2], r[3], [], thr)) : memoRows();
  let ms = 10994, px = 64012.5;
  for (let i = 3; i < n; i++) {
    ms -= 40 + Math.floor(rnd() * 420);
    if (ms < 0) ms += 60000;
    px += (rnd() < 0.5 ? -0.5 : 0.5) * (rnd() < 0.3 ? 1 : 0);
    const size = rnd() < 0.08 ? 1 + rnd() * 3 : rnd() < 0.3 ? 0.2 + rnd() * 1 : 0.01 + rnd() * 0.2;
    const t = "14:0" + Math.floor(ms / 60000 + 2) + ":" + pad2(Math.floor((ms % 60000) / 1000)) + "." + String(ms % 1000).padStart(3, "0");
    rows.push(tapeRow(t, rnd() < 0.5 ? "buy" : "sell", size, px, [], thr));
  }
  return rows;
}
// r7 (checklist item 1): the rows a 1280×800 panel's 604 px log holds once the frame's own extra slots take their room (a notice 24, a strip over
// the log, a second chips row 28), and the "… N more rows …" count a frame with `drawn` rows and `dividers` divider rows shows — computed, never typed.
const logRows = (minus) => Math.floor((NUM.logPx1280 - (minus || 0)) / NUM.rowPx[0]);
const elide = (drawn, dividers, minus) => ({ elideAfter: drawn, elided: Math.max(0, logRows(minus) - drawn - (dividers || 0)) });
const tapeRoom = (py, logY) => Math.min(NUM.rows1280[0], Math.floor((py + NUM.panelPx1280 - logY - NUM.slotColHdr - NUM.slotStripCollapsed) / NUM.rowPx[0])); // the rows a full 736 px panel holds under its chrome as drawn (24 under a two-line chips row; 25 under one)
// tapeBlock: a 5-cell header row, then rows at fixed column x's — Time left; Price / Size / Notional right-aligned, mono; Side left —
// the ▲/▼ glyph before Price, the ● / ◆ tier glyph right after Size, the 2 px accent at the left edge on tiers 1–2, the tier-2 band
// (surface.hover-class lightness), the dimmed HH:MM: prefix (two texts) on tiers 0–1 (undimmed on tier 2 and on the selected row),
// optional tags after the Side word, divider rows (one centred text on a hairline, `presentation`), an elided band, the live-edge divider.
function tapeBlock(parent, x, y, w, rows, o) {
  o = o || {};
  const density = o.density || "compact", rowH = density === "compact" ? NUM.rowPx[0] : NUM.rowPx[1], size = density === "compact" ? NUM.fontPx[0] : NUM.fontPx[1];
  const cw = size * NUM.monoEm, gap = density === "compact" ? NUM.gapPx : NUM.gapPxComfortable, inset = NUM.insetPx; // the step per density (16 §3)
  const colW = NUM.chCols.map((ch) => Math.ceil(ch * cw)); // Time, Price, Size, Notional, Side, glyph, tier
  const xTime = x + inset + NUM.accentPx, xGlyph = xTime + colW[0] + gap, xPrice = xGlyph + colW[5] + gap, xSize = xPrice + colW[1] + gap, xTier = xSize + colW[2] + gap, xNotional = xTier + colW[6] + gap, xSide = xNotional + colW[3] + gap;
  const hdrH = o.header === false ? 0 : density === "comfortable" ? NUM.slotsComfortable[3] : NUM.slotColHdr; // r7: 24 at comfortable (D2)
  const dividers = o.dividers || {}; // { rowIndex: "text" } drawn BEFORE that row
  const nDiv = Object.keys(dividers).length + (o.elideAfter != null ? 1 : 0);
  const total = hdrH + rows.length * rowH + nDiv * rowH;
  mkRect(parent, x, y, w, total, "raised", { stroke: "border", role: "wire", name: "tape-log" });
  if (hdrH) {
    // r9 (QA, pre-existing wrap): a right-aligned header box is never narrower than its label (JetBrains Mono, pillTextW) and ends at its column's
    // right edge, so the label ends where the data cells end and never runs into the next column (r4–r8: Notional, 55 px in the 40 / 47 px
    // column, started at the column's left edge and ran into Side); the data cells keep their columns, the left-aligned heads their boxes
    const heads = [["Time", xTime, colW[0], "left"], ["Price", xPrice, colW[1], "right"], ["Size", xSize, colW[2], "right"], ["Notional", xNotional, colW[3], "right"], ["Side", xSide, colW[4] + 40, "left"]]
      .map((h) => { if (h[3] !== "right") return h; const bw = Math.max(h[2], pillTextW(h[0], 11, true)); return [h[0], h[1] + h[2] - bw, bw, h[3]]; });
    heads.forEach((h) => mkText(parent, h[0], h[1], y + 3, h[2], { size: 11, weight: 600, mono: true, align: h[3], color: C.text3, tok: TOK.text3, name: "tape-th", h: 16 }));
    if (SPLIT.dryAll && CUR_BOARD) { // r9: the header labels' estimated extents (fitW; right-aligned labels end at their box's right edge) keep ≥ 4 px between neighbours
      const ext = heads.map((h) => { const est = fitW(h[0], 11, true), r = h[1] + h[2]; return h[3] === "right" ? [r - est, r, h[0]] : [h[1], h[1] + Math.min(h[2], est), h[0]]; }).sort((a, b2) => a[0] - b2[0]);
      for (let i = 1; i < ext.length; i++) if (ext[i][0] - ext[i - 1][1] < 4) HDR.push(CUR_BOARD.name + " :: tape-th " + ext[i - 1][2] + " / " + ext[i][2] + " gap " + Math.round(ext[i][0] - ext[i - 1][1]) + " px (" + density + ")");
    }
    mkRect(parent, x + 1, y + hdrH - 1, w - 2, 1, "border", { role: "wire", name: "tape-rule" });
  }
  let ry = y + hdrH, drawn = 0;
  const divider = (text) => { mkRect(parent, x + 1, ry + rowH / 2, w - 2, 1, "borderStrong", { role: "wire", name: "tape-divider-rule" }); mkRect(parent, x + w / 2 - 170, ry + 3, 340, rowH - 6, "raised", { role: "wire", name: "tape-divider-plate" }); mkText(parent, NB(text), x + w / 2 - 170, ry + (rowH - 15) / 2, 340, { size: 11, align: "center", color: C.text2, tok: TOK.text2, name: "tape-divider", h: 15 }); ry += rowH; };
  const elision = () => { mkText(parent, NB("… " + fmt(o.elided || 0) + " more rows …"), x, ry + (rowH - 15) / 2, w, { size: 11, align: "center", color: C.text3, tok: TOK.text3, name: "tape-elided", h: 15 }); ry += rowH; };
  rows.forEach((r, i) => {
    if (dividers[i] != null) divider(dividers[i]);
    if (o.elideAfter != null && i === o.elideAfter) elision();
    const selected = o.selectedRow === i, weight = r.tier === 2 ? 700 : r.tier === 1 ? 500 : 400;
    if (r.tier === 2) mkRect(parent, x + 1, ry, w - 2, rowH, "hover", { role: "wire", name: "row-band" });
    if (selected) mkRect(parent, x + 1, ry, w - 2, rowH, "selected", { role: "wire", name: "row-selected" });
    if (r.tier >= 1) mkRect(parent, x + 1, ry, NUM.accentPx, rowH, "text", { role: "wire", name: "row-accent" });
    if (o.focusRow === i) mkRect(parent, x + 1, ry, w - 2, rowH, null, { stroke: "text", strokeWidth: 2, role: "wire", name: "focus-ring-standin" });
    const ty = ry + (rowH - Math.ceil(size * 1.38)) / 2, cell = (s, cx, cwid, align, extra) => mkText(parent, s, cx, ty, cwid, Object.assign({ size, mono: true, weight, align, name: "tape-td", h: Math.ceil(size * 1.38) }, extra || {}));
    const dim = r.tier < 2 && !selected;
    cell(r.time.slice(0, 6), xTime, Math.ceil(6 * cw) + 1, "left", { color: dim ? C.text3 : C.text, tok: dim ? TOK.text3 : TOK.text, weight: 400 });
    cell(r.time.slice(6), xTime + Math.ceil(6 * cw), colW[0] - Math.ceil(6 * cw) + 2, "left", { weight: 400 });
    cell(r.side === "buy" ? "▲" : "▼", xGlyph, colW[5] + 4, "left", { name: "tape-side-glyph", weight: 400 });
    cell(r.price, xPrice, colW[1], "right");
    cell(r.size, xSize, colW[2], "right");
    if (r.tier >= 1) cell(r.tier === 2 ? "◆" : "●", xTier, colW[6] + 4, "left", { name: "tape-tier-glyph", weight: 400 });
    cell(r.notional, xNotional, colW[3], "right");
    cell(r.side === "buy" ? "Buy" : "Sell", xSide, colW[4] + 2, "left", { weight: 400 });
    let tx = xSide + colW[4] + 6;
    for (const tgRaw of r.tags || []) tx += pill(parent, tx, ry + (rowH - 16) / 2, tgRaw, { h: 16, size: 10, padX: 5, fill: "canvas", stroke: "border", textColor: C.text2, textTok: TOK.text2, mono: /×|⧉/.test(tgRaw), name: "row-tag" }) + 4;
    ry += rowH; drawn++;
  });
  if (o.elideAfter != null && o.elideAfter >= rows.length) elision(); // r7: the elision row after the last row is drawn in the row `total` reserved for it (r6 reserved it and drew nothing, so every frame ended in a blank row)
  if (o.liveEdge) mkRect(parent, x + 1, y + hdrH, w - 2, 1, "borderStrong", { role: "wire", name: "live-edge-divider" });
  return { h: total, rowH, xs: { xTime, xGlyph, xPrice, xSize, xTier, xNotional, xSide }, colW, cw };
}
// The panel chrome above a tape: the header row (title + five icon buttons; o.pauseT2 draws the pause button in E09-D09's 2b
// rendering — the ⏸ glyph kept in the middle grey, a lock badge at the top-right, raised fill + the border hairline), the
// optional panel notice in its own 24 px slot right under the header (o.notice — S21 / S23), the status row (chips + buttons +
// the readout; a "🔒"-prefixed action is drawn T2: raised fill, border hairline, the middle grey, the DRAWN lock — r8) and the chips row. Returns
// the y where the log starts.
function panelChrome(parent, x, y, w, o) {
  o = o || {};
  const blk = TICKET + ":" + (++blockSeq), stk = o.stk || blk;
  const S = o.density === "comfortable" ? { header: NUM.slotsComfortable[0], status: NUM.slotsComfortable[1], chips: NUM.slotsComfortable[2], notice: NUM.noticePx[1] } : { header: NUM.slotHeader, status: NUM.slotStatus, chips: NUM.slotChips, notice: NUM.noticePx[0] }; // r7: the comfortable pair's own slot heights (D2: 44 · 32 · 32; notice 32) — r6 drew the comfortable crop with the compact slots
  mkRect(parent, x, y, w, S.header, "raised", { stroke: "border", role: "wire", name: "panel-header", blk, stk });
  mkText(parent, NB(o.title || "Tape BTCUSDT"), x + 10, y + (S.header - 16) / 2, 120, { size: 12, weight: 600, name: "panel-title", blk, stk, h: 16 });
  const btns = o.buttons || ["⌕", "≡", o.paused ? "▶" : "⏸", "⊞", "⋯"], names = ["Filter prints (Ctrl+F)", "Threshold…", "Pause tape (P)", "Columns…", "More (Shift+F10)"];
  let bx = x + w - 10 - btns.length * (NUM.iconPx + 6) + 6;
  const by = y + (S.header - NUM.iconPx) / 2;
  btns.forEach((g, i) => { const t2 = i === 2 && o.pauseT2; mkRect(parent, bx, by, NUM.iconPx, NUM.iconPx, t2 ? "raised" : i === 2 && o.paused ? "selected" : "hover", { stroke: "border", radius: 4, role: "wire", name: "icon-button:" + names[i], blk, stk }); mkText(parent, g, bx, by + 3, t2 ? 14 : NUM.iconPx, { size: 12, align: "center", color: t2 ? C.text3 : C.text, tok: t2 ? TOK.text3 : TOK.text, name: "icon-glyph", blk, stk, h: 17 }); if (t2) lockGlyph(parent, bx + NUM.iconPx - 9, by - 3, { size: 8, name: "t2-lock-badge", blk, stk }); bx += NUM.iconPx + 6; });
  // the status row (plain text + buttons, never a live region — spec D29): the feed chip, the Paused chip, the gapped / capped
  // chips, the row's buttons (Jump to live · Load missed prints · Apply / Keep — one Tab stop, K1) and the readout right-aligned.
  // The row's own ladder (spec §2 D1): '+N filtered' only while a filter is on (o.filtered); when the content exceeds the
  // width the readout drops '/frame' first, then the Paused chip takes its narrow form.
  let sy = y + S.header;
  if (o.notice) { // the panel notice slot (spec §2; S21 / S23): one node right under the header, the aria-describedby target of every gated control
    mkRect(parent, x, sy, w, S.notice, "raised", { stroke: "border", role: "wire", name: "panel-notice", blk, stk });
    (LOCK_RE.test(o.notice) ? lockText : mkText)(parent, NB(o.notice), x + 10, sy + (S.notice - 15) / 2, w - 20, { size: 11, color: C.text2, tok: TOK.text2, name: "panel-notice-text", blk, stk, h: 15 }); // r8: the drawn lock leads a T2 notice
    sy += S.notice;
  }
  mkRect(parent, x, sy, w, S.status, "raised", { stroke: "border", role: "wire", name: "panel-status", blk, stk });
  let rtext = o.readout === false ? null : (o.readout || (o.filtered ? "2 010 /s (1 s) · 33 /frame · +41 filtered" : "2 010 /s (1 s) · 33 /frame"));
  const statusChips = (o.status || []).slice(), actions = (o.actions || []).slice();
  const chipsW = () => statusChips.reduce((m, c) => m + pillW(c.label, 11, !!c.mono) + 6, 0) + actions.reduce((m, a) => m + pillW(a, 11, false) + 6, 0);
  const roomFor = () => w - 20 - (rtext ? pillTextW(rtext, 11, true) + 10 : 0);
  if (chipsW() > roomFor() && rtext && / · [\d.]+ \/frame/.test(rtext)) rtext = rtext.replace(/ · [\d.]+ \/frame/, "");
  if (chipsW() > roomFor()) statusChips.forEach((c) => { if (c.label === "Paused — 412 prints buffered") c.label = "Paused — 412 buffered"; });
  const rw = rtext ? pillTextW(rtext, 11, true) : 0;
  let cx = x + 10;
  const py = sy + (S.status - NUM.chipPx) / 2;
  for (const ch of statusChips) cx += pill(parent, cx, py, ch.label, { h: NUM.chipPx, size: 11, fill: ch.fill || "hover", stroke: ch.stroke || "border", strokeWidth: ch.decision ? 2 : 1, textColor: ch.text || C.text, textTok: ch.tok || TOK.text, mono: !!ch.mono, blk, stk, name: "status-chip:" + ch.label }) + 6;
  for (const a of actions) { const t2a = a.startsWith("🔒"); cx += pill(parent, cx, py, a, { h: NUM.chipPx, size: 11, radius: 4, fill: t2a ? "raised" : "selected", stroke: t2a ? "border" : "borderStrong", textColor: t2a ? C.text3 : C.text, textTok: t2a ? TOK.text3 : TOK.text, blk, stk, name: (t2a ? "t2-action:" : "status-action:") + a }) + 6; }
  if (rtext) mkText(parent, NB(rtext), x + w - 10 - rw, py + 3, rw, { size: 11, mono: true, align: "right", color: C.text2, tok: TOK.text2, name: "readout", blk, stk, h: 15 });
  sy += S.status;
  // the chips row (CMP-055 "Active filters"): the Big only preset, the mode chip + (estimated), the removable filter chips — greedy wrap, never truncate
  const chips = (o.chips || []).slice();
  if (chips.length) {
    const rows = []; let cur = [], px = 0;
    for (const c of chips) { const pw = pillW(c.label, 11, !!c.mono); if (cur.length && px + pw > w - 20) { rows.push(cur); cur = []; px = 0; } cur.push(c); px += pw + 6; } // r7: the wrap runs on the widths pill() draws (r6 estimated at 10.5 px and drew at 11)
    if (cur.length) rows.push(cur);
    mkRect(parent, x, sy, w, rows.length * S.chips, "raised", { stroke: "border", role: "wire", name: "panel-chips", blk, stk });
    rows.forEach((row, ri) => { let qx = x + 10; for (const ch of row) qx += pill(parent, qx, sy + ri * S.chips + (S.chips - NUM.chipPx) / 2 - 2, ch.label, { h: NUM.chipPx, size: 11, fill: ch.fill || "canvas", stroke: ch.stroke || "border", textColor: ch.text || C.text, textTok: ch.tok || TOK.text, mono: !!ch.mono, blk, stk, name: "chip:" + ch.label }) + 6; });
    sy += rows.length * S.chips;
  }
  return { logY: sy, blk, stk, chipRows: chips.length ? Math.round((sy - (y + S.header + (o.notice ? S.notice : 0) + S.status)) / S.chips) : 0 };
}
// r7: the S18 warning strip in place under the status row (D20; the CMP-028-class inline strip): the F19 sentence and the exact capped readout; 64 px
function warningStripInPlace(parent, x, y, w) {
  mkRect(parent, x, y, w, 64, "hover", { stroke: "borderStrong", role: "wire", name: "warning-strip-inplace" });
  mkText(parent, "Threshold flags 23.5 % of prints — raised to 34 723 USDT (the window's p80); prints between 30 000 and 34 723 are not flagged", x + 12, y + 8, w - 24, { size: 12, weight: 600, name: "warning-text" });
  pill(parent, x + 12, y + 40, "eff. 34.7k USDT · capped", { h: 20, size: 11, mono: true, name: "eff-readout" });
  return 64;
}
function controlStrip(parent, x, y, w, o) {
  o = o || {};
  if (o.collapsed) {
    mkRect(parent, x, y, w, NUM.slotStripCollapsed, "raised", { stroke: "border", role: "wire", name: "strip-collapsed" });
    mkText(parent, NB("▸ Threshold 250k · area-linear · 250 ms (estimated)"), x + 10, y + 5, w - 20, { size: 11, color: C.text2, tok: TOK.text2, name: "strip-summary", h: 15 });
    return NUM.slotStripCollapsed;
  }
  mkRect(parent, x, y, w, NUM.slotStrip, "raised", { stroke: "border", role: "wire", name: "control-strip" });
  const rowA = [["t", "Threshold"], ["s", o.mode || "notional ▾"], ["f", o.value || "250 000 USDT"], ["m", o.eff || "eff. 250k USDT"]].concat((o.badges || []).map((bg) => ["b", bg]));
  const rowB = [["t", "Size tier 2 = 4× · 1M USDT"], ["t", "Bubbles · scale"], ["s", o.scale || "area-linear ▾"]];
  const rowC = [["t", "Rows"], ["s", o.rows || "reconstructed 250 ms / 1 tick ▾"]].concat(o.raw ? [] : [["b", "(estimated)"]]);
  const drawRow = (items, ry) => { let cx = x + 10; items.forEach((it) => { const kind = it[0], label = it[1]; if (kind === "t") { const tw = pillTextW(label, 10.5, false); mkText(parent, NB(label), cx, ry + 4, tw + 4, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "strip-text", h: 15 }); cx += tw + 12; } else cx += pill(parent, cx, ry, label, { h: NUM.chipPx, size: 11, radius: kind === "b" ? NUM.chipPx / 2 : 4, fill: kind === "s" ? "hover" : kind === "b" ? "hover" : "canvas", stroke: kind === "b" ? "borderStrong" : "border", mono: kind === "m" || kind === "f", name: "strip-control:" + label }) + 8; }); };
  drawRow(rowA, y + 4); drawRow(rowB, y + 4 + 24); drawRow(rowC, y + 4 + 48);
  return NUM.slotStrip;
}
// The 1280×800 / 2560×1440 shell: a 40 px top bar with the DEMO band, a 24 px bottom bar, labelled placeholder panels.
function shellChrome(parent, x, y, W, H) {
  mkRect(parent, x, y, W, H, "app", { stroke: "borderStrong", role: "wire", name: "shell" });
  mkRect(parent, x, y, W, NUM.shellTop, "raised", { stroke: "border", role: "wire", name: "top-bar" });
  mkText(parent, "CandleViewer", x + 16, y + 11, 120, { size: 13, weight: 700, name: "shell-title", h: 18 });
  pill(parent, x + 140, y + 10, "DEMO", { h: 20, size: 11, weight: 700, fill: "hover", stroke: "borderStrong", name: "env-band" });
  mkText(parent, NB("the DEMO band belongs to the shell chrome (14 §0.5 item 1); the tape repeats no local badge — public market data, no order affordance"), x + 210, y + 13, W - 240, { size: 11, color: C.text3, tok: TOK.text3, name: "shell-note", h: 15 });
  mkRect(parent, x, y + H - NUM.shellBottom, W, NUM.shellBottom, "raised", { stroke: "border", role: "wire", name: "bottom-bar" });
  mkText(parent, NB("workspace status bar · Live 42 ms"), x + 16, y + H - NUM.shellBottom + 5, 300, { size: 11, color: C.text3, tok: TOK.text3, name: "bottom-note", h: 15 });
  return { top: y + NUM.shellTop, bottom: y + H - NUM.shellBottom, panelH: H - NUM.shellTop - NUM.shellBottom };
}
function placeholderPanel(parent, x, y, w, h, label, sub) {
  mkRect(parent, x, y, w, h, "canvas", { stroke: "border", role: "wire", name: "placeholder:" + label });
  mkText(parent, label, x + 12, y + 10, w - 24, { size: 12, weight: 600, color: C.text2, tok: TOK.text2, name: "placeholder-label", h: 16 });
  if (sub) mkText(parent, sub, x + 12, y + 30, w - 24, { size: 11, color: C.text3, tok: TOK.text3, name: "placeholder-sub" });
}

// ---------------------------------------------------------------- content -----------------------------------
const SRC = "Source: docs/design/E22/E22-D02.md (the spec) and docs/design/_tools/e22_d02_tape_wires_audit.py --json · greyscale, neutral tokens only, unbound (E13-D02 §13) · every non-binding decision PROPOSED, owner approval pending · every tape row beyond the memo's three is synthetic (LCG seed 507), labelled · script " + VERSION;
const boards = [];
const built = [];
const GX = 0, GY = 0, GAP = 160, W_BOARD = 1840, GAPY = 40;
function rowX(n) { return GX + (n - 1) * (W_BOARD + GAP); }
function place(n, slug, w, h) { // part 1 (or a whole board) creates the board; a later part appends to the board part 1 created
  let b = null;
  if (PART > 1 && !SPLIT.dryAll) {
    const nm = norm(TICKET + "/" + pad2(n) + " " + slug);
    b = (page.root.children || []).find((s) => s.type === "board" && norm(s.name) === nm) || null;
    if (!b) throw new Error("part " + PART + ": board " + pad2(n) + " is not on the page; run PART = 1 first (nothing of this part was drawn)");
  } else b = mkBoard(n, slug, rowX(n), GY, w, h);
  boards.push(b); CUR_BOARD = b; return b;
}
function finish(b, bottom) { // footer ≥40 px below the content and the board exactly 32 px under it (the restack's board rule: lowest child + 32)
  const f = mkText(b, "page " + TICKET + " · board " + pad2(JSON.parse(b.getPluginData(TAG + ":meta")).board) + " · " + VERSION, b.x + 32, bottom + GAPY, 400, { size: 11, color: C.text3, tok: TOK.text3, name: "footer" });
  const fh = f ? f.h : 16;
  b.resize(b.width, bottom + GAPY + fh + 32 - b.y); // r6: exactly the restack's wantedH (r5: Math.max(.., + 24) — every frame regrew 8 px; boards 08 / 09 / 10 drawn taller than the content shrank 16 / 95 / 32)
  built.push({ n: JSON.parse(b.getPluginData(TAG + ":meta")).board, name: b.name, id: b.id, exportAs: JSON.parse(b.getPluginData(TAG + ":meta")).exportAs });
}
function placeRow() { // every board of this ticket on the page (built now or earlier), in board order, at rowX(n), y = GY
  const seen = new Set(), all = [];
  const take = (sh) => {
    if (!sh) return;
    const key = sh.id != null ? String(sh.id) : sh;
    if (seen.has(key)) return;
    let m = null;
    try { m = sh.getPluginData(TAG) === "v1" ? JSON.parse(sh.getPluginData(TAG + ":meta") || "{}") : null; } catch (e) { m = null; }
    if (!m || m.role !== "board" || !(m.board >= 1 && m.board <= BOARDS.length)) return;
    seen.add(key); all.push({ s: sh, n: m.board });
  };
  for (const b of boards) take(b);
  for (const sh of (page.root.children || [])) { try { if (sh.type === "board" && norm(sh.name).startsWith(TICKET + "/")) take(sh); } catch (e) { warn("row scan", e); } }
  all.sort((a, b2) => a.n - b2.n);
  const row = [];
  for (const it of all) {
    const b = it.s, tx = rowX(it.n), ty = GY, dx = tx - b.x, dy = ty - b.y;
    const entry = { board: it.n, x: tx, y: ty, w: b.width, moved: false, carried: 0 };
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
      const kids = (b.children || []).slice(), before = kids.map((c) => [c.x, c.y]);
      try { b.x = tx; b.y = ty; } catch (e) { warn("row move", e); }
      if (Math.abs(b.x - tx) > 0.5 || Math.abs(b.y - ty) > 0.5) { warn("row", "board " + it.n + " did not move; children left alone"); entry.stuck = true; row.push(entry); continue; }
      const followed = kids.length === 0 || kids.some((c, i) => Math.abs(c.x - before[i][0]) > 0.5 || Math.abs(c.y - before[i][1]) > 0.5);
      if (!followed) for (let i = 0; i < kids.length; i++) { try { kids[i].x = before[i][0] + dx; kids[i].y = before[i][1] + dy; entry.carried++; } catch (e) { warn("row child", e); } }
      entry.moved = true;
    }
    row.push(entry);
  }
  return row;
}
const want = (n) => !ONLY || ONLY.indexOf(n) >= 0;
const LEGEND = "outlined = PROPOSED default · thick outline = keyboard focus only · lighter band = tier 2 · ● tier 1 · ◆ tier 2 · ▲ buy · ▼ sell · every number: the audit tool";

// ---- idempotent: this ticket's OWN frames for the boards about to be built (normalised name, this page only) are found BEFORE the draw
// and removed only AFTER it succeeded (a whole board, or its part 1); a later part never removes anything
const planned = BOARDS.filter((bd) => want(bd.n)).map((bd) => norm(TICKET + "/" + pad2(bd.n) + " " + bd.slug));
const removed = [];
function oldPlanned() {
  const out = [];
  for (const s of (page.root.children || []).slice()) { try { if (s.type === "board" && planned.indexOf(norm(s.name)) >= 0) out.push(s); } catch (e) { warn("clear", e); } }
  return out;
}
function clearPlanned(olds) {
  for (const s of olds) {
    try {
      if (s.type !== "board") continue;
      const nm = norm(s.name);
      if (!nm.startsWith(TICKET + "/")) continue;
      if (planned.indexOf(nm) >= 0) { removed.push({ name: s.name, id: s.id, hpe1ver: s.getPluginData ? s.getPluginData("hpe1ver") : null }); s.remove(); }
    } catch (e) { warn("clear", e); }
  }
}
const BUILD = {};
// ---- the plan, the guard, the self-check, the draw (r5; the E14-D06 r7 machinery) ----
const partPlan = [], PLANS = {};
function planBoard(n) { // a dry pass of one board: shapes (and path segments) per top-level unit, then the units packed in drawing order into parts within the budgets
  const save = { blockSeq, boards: boards.length, built: built.length, warnings: warnings.length, CUR_BOARD };
  SPLIT.plan = null; SPLIT.dryAll = true; SPLIT.counts = [0]; SPLIT.segs = [0]; SPLIT.idx = 0; DRY = true;
  BUILD[n]();
  const counts = SPLIT.counts.map((c) => c || 0), segs = counts.map((_, i) => SPLIT.segs[i] || 0), plan = [], perPart = [], segPart = [];
  let part = 1, acc = 0, accS = 0;
  counts.forEach((c, i) => {
    if (c > SHAPE_BUDGET || segs[i] > SEG_BUDGET) throw new Error("shape budget: board " + pad2(n) + " unit " + i + " alone has " + c + " shapes / " + segs[i] + " segments (over " + SHAPE_BUDGET + " / " + SEG_BUDGET + "); nothing was touched");
    if (acc + c > SHAPE_BUDGET || accS + segs[i] > SEG_BUDGET) { part++; acc = 0; accS = 0; }
    plan[i] = part; acc += c; accS += segs[i]; perPart[part - 1] = acc; segPart[part - 1] = accS;
  });
  blockSeq = save.blockSeq; boards.length = save.boards; built.length = save.built; warnings.length = save.warnings;
  containment(CUR_BOARD ? CUR_BOARD.name : TICKET + " / " + pad2(n), DRYREC); DRYREC.length = 0; // r9: over the whole dry build of this board, before anything is drawn
  CUR_BOARD = save.CUR_BOARD;
  SPLIT.dryAll = false; SPLIT.counts = null; SPLIT.segs = null; SPLIT.idx = 0; DRY = false; UNIT_DEPTH = 0;
  PLANS[n] = plan; partPlan.push({ board: n, parts: part, shapes: perPart, segs: segPart });
}
// r9 (QA MAJOR, board 06): the containment self-check over the planning pass — no shape's right edge may leave the rect it sits in. A container is
// any earlier STROKED rect (a drawn outline — a panel, a frame, a card, a menu, a pill; an unstroked plate or band is a backdrop, not a
// frame) or board, at least 40 × 12 px; a shape sits in it when its left edge starts inside the container and its vertical centre lies within it. A text's right edge is estimated: a right-aligned text ends at its box's right edge, a centred one at the box centre + half its
// estimated advance (fitW), a left-aligned one at its left edge + the lesser of its box and its estimated advance; every other shape at its box.
// Tolerance 0.5 px. Generic on purpose: r8's T2 Bubbles control was drawn 19 px past the S21 / S23 frame and no gate saw it (the mock
// harness checks nested boards only; this ticket draws every frame as a rect).
function containment(boardName, recs) {
  const rightOf = (s) => { if (s.type !== "text") return s.x + s.width; const est = s.estW == null ? s.width : s.estW; if (s.align === "right") return s.x + s.width; if (s.align === "center") return Math.min(s.x + s.width, s.x + s.width / 2 + est / 2); return s.x + Math.min(s.width, est); };
  const boxes = [];
  recs.forEach((s, i) => { if ((s.type === "board" || (s.type === "rect" && s.strokes && s.strokes.length)) && s.width >= 40 && s.height >= 12) boxes.push([i, s]); });
  recs.forEach((s, j) => {
    const cy = s.y + s.height / 2, r = rightOf(s);
    for (const [i, R] of boxes) {
      if (i >= j) break;
      const rr = R.x + R.width;
      if (s.x < R.x - 0.5 || s.x > rr - 0.5 || cy < R.y || cy > R.y + R.height || r <= rr + 0.5) continue;
      OVERRUN.push(boardName + " :: " + String(s.name).replace(TICKET + " / ", "") + (s.type === "text" ? " " + JSON.stringify(String(s.text).slice(0, 40)) : "") + " right " + Math.round(r) + " leaves " + String(R.name).replace(TICKET + " / ", "") + " (right " + Math.round(rr) + ") by " + Math.round(r - rr) + " px");
    }
  });
}
function drawBoard(n) { // the whole board (PART null) or part PART of it; the shapes of the other parts stay dry
  SPLIT.plan = PART ? PLANS[n] : null; SPLIT.counts = null; SPLIT.segs = null; SPLIT.idx = 0; SPLIT.dryAll = false;
  DRY = SPLIT.plan ? SPLIT.plan[0] !== PART : false;
  BUILD[n]();
  SPLIT.plan = null; DRY = false; CUR_BOARD = null;
}
// KNOWN_WRAPS: the single-line texts the wrap rule (PILL_EM class sums, JetBrains Mono 0.62 em) flags in the content as posted (r4, PR #4248).
// They stay unchanged in r5 (the PART split makes no drawn change), so the self-check WARNS on exactly these and throws on any other wrap.
// Only the tape's mono Notional data cells (6 ch at NUM.monoEm 0.6 vs the rule's 0.62) — r9: the Notional HEADER's 13 entries are gone, its box now
// holds the label (tapeBlock, the right-aligned head rule); plus board 08's bubble notes
// (r8: board 08's bubble notes and tooltip line and board 02's crop labels — NBSP-joined overflows — are fixed, their entries gone; every NBSP text now fails strictly).
// Each entry is a FIT line without the ticket prefix: "<board> <slug> :: <shape> "<text>" needs N px in a W px box".
const KNOWN_WRAPS = [
  "01 scr-053-panel-1280 :: tape-td \"199.6k\" needs 41 px in a 40 px box",
  "01 scr-053-panel-1280 :: tape-td \"232.7k\" needs 41 px in a 40 px box",
  "01 scr-053-panel-1280 :: tape-td \"256.1k\" needs 41 px in a 40 px box",
  "02 scr-053-panel-2560 :: tape-td \"101.8k\" needs 41 px in a 40 px box",
  "02 scr-053-panel-2560 :: tape-td \"157.2k\" needs 41 px in a 40 px box",
  "02 scr-053-panel-2560 :: tape-td \"233.7k\" needs 41 px in a 40 px box",
  "02 scr-053-panel-2560 :: tape-td \"233.7k\" needs 49 px in a 47 px box",
  "02 scr-053-panel-2560 :: tape-td \"255.4k\" needs 41 px in a 40 px box",
  "02 scr-053-panel-2560 :: tape-td \"256.1k\" needs 41 px in a 40 px box",
  "02 scr-053-panel-2560 :: tape-td \"256.1k\" needs 49 px in a 47 px box",
  "03 tape-rows-densities-tiers :: tape-td \"116.6k\" needs 41 px in a 40 px box",
  "03 tape-rows-densities-tiers :: tape-td \"136.2k\" needs 41 px in a 40 px box",
  "03 tape-rows-densities-tiers :: tape-td \"197.5k\" needs 41 px in a 40 px box",
  "03 tape-rows-densities-tiers :: tape-td \"256.1k\" needs 41 px in a 40 px box",
  "03 tape-rows-densities-tiers :: tape-td \"256.1k\" needs 49 px in a 47 px box",
  "03 tape-rows-densities-tiers :: tape-td \"294.5k\" needs 41 px in a 40 px box",
  "03 tape-rows-densities-tiers :: tape-td \"294.5k\" needs 49 px in a 47 px box",
  "03 tape-rows-densities-tiers :: tape-td \"332.9k\" needs 41 px in a 40 px box",
  "03 tape-rows-densities-tiers :: tape-td \"332.9k\" needs 49 px in a 47 px box",
  "04 pause-model-states :: tape-td \"152.0k\" needs 41 px in a 40 px box",
  "04 pause-model-states :: tape-td \"256.1k\" needs 41 px in a 40 px box",
  "05 feed-and-list-states :: tape-td \"119.9k\" needs 41 px in a 40 px box",
  "05 feed-and-list-states :: tape-td \"256.1k\" needs 41 px in a 40 px box",
  "06 filter-bar-column-picker :: tape-td \"256.1k\" needs 41 px in a 40 px box",
  "07 threshold-strip-classes :: tape-td \"194.7k\" needs 41 px in a 40 px box",
  "07 threshold-strip-classes :: tape-td \"256.1k\" needs 41 px in a 40 px box",
  "08 bubble-overlay-scr-030 :: tape-td \"156.1k\" needs 41 px in a 40 px box",
  "08 bubble-overlay-scr-030 :: tape-td \"162.9k\" needs 41 px in a 40 px box",
  "08 bubble-overlay-scr-030 :: tape-td \"176.1k\" needs 41 px in a 40 px box",
  "08 bubble-overlay-scr-030 :: tape-td \"210.1k\" needs 41 px in a 40 px box",
  "08 bubble-overlay-scr-030 :: tape-td \"256.1k\" needs 41 px in a 40 px box",
  "10 greyscale-cvd-proof :: tape-td \"256.1k\" needs 41 px in a 40 px box",
  "11 clustering-badge-tooltip :: tape-td \"256.1k\" needs 41 px in a 40 px box",
  "12 keyboard-a11y-announcements :: tape-td \"135.4k\" needs 41 px in a 40 px box",
  "12 keyboard-a11y-announcements :: tape-td \"256.1k\" needs 41 px in a 40 px box",
].map((k) => TICKET + " / " + k);
function selfCheck(wanted) { // the pre-export self-check on the planning pass's record; throws before the clear and before any shape is drawn
  const fail = [], warned = [];
  // single-line texts (pills, Kbd hints, chips, tape cells, the readout, notices, labels) that would wrap in their box
  for (const f of FIT) {
    const n = parseInt(f.slice(TICKET.length + 3, TICKET.length + 5), 10);
    if (wanted.indexOf(n) < 0) continue;
    if (KNOWN_WRAPS.indexOf(f) >= 0) warned.push("known wrap: " + f); else fail.push("wraps: " + f);
  }
  for (const f of NBFIT) { const n = parseInt(f.slice(TICKET.length + 3, TICKET.length + 5), 10); if (wanted.indexOf(n) >= 0) fail.push("NBSP text wider than its box (it can break only at a hyphen — it would clip or run under its neighbours): " + f); } // r8 (QA A)
  for (const f of EMOJI) { const n = parseInt(f.slice(TICKET.length + 3, TICKET.length + 5), 10); if (wanted.indexOf(n) >= 0) fail.push("emoji-presentation character on a greyscale board (it renders in colour): " + f); } // r8 (QA B)
  for (const f of HDR) { const n = parseInt(f.slice(TICKET.length + 3, TICKET.length + 5), 10); if (wanted.indexOf(n) >= 0) fail.push("tape header labels touch (under 4 px between their estimated extents): " + f); } // r9
  for (const f of OVERRUN) { const n = parseInt(f.slice(TICKET.length + 3, TICKET.length + 5), 10); if (wanted.indexOf(n) >= 0) fail.push("a shape leaves the rect it sits in (right edge): " + f); } // r9 (QA MAJOR)
  for (const w of warned) warnings.push("SELF-CHECK " + w);
  if (fail.length) throw new Error("SELF-CHECK: " + fail.join("; ") + "; nothing was touched");
  return warned.length ? "ok (" + warned.length + " known wrap(s) warned)" : "ok";
}
function gate(wanted) { // the plan, the self-check and the guard, before the clear: returns an abort object, throws, or returns null (go)
  if (PART !== null && (!Number.isInteger(PART) || PART < 0)) throw new Error("PART must be null, 0 or a positive integer; nothing was touched");
  if (PART !== null && PART !== 0 && wanted.length !== 1) return { abort: "part", version: VERSION, note: "PART k needs exactly one board in ONLY; nothing was touched" };
  for (const n of wanted) planBoard(n);
  GATE.selfCheck = selfCheck(wanted);
  if (PART === 0) return { version: VERSION, budget: SHAPE_BUDGET, segBudget: SEG_BUDGET, partPlan, selfCheck: GATE.selfCheck, warnings };
  if (PART && PART > partPlan[0].parts) return { abort: "part", version: VERSION, partPlan, note: "board " + pad2(wanted[0]) + " has " + partPlan[0].parts + " part(s); nothing was touched" };
  const sum = (a) => a.reduce((x, y) => x + y, 0);
  const thisCall = PART ? partPlan[0].shapes[PART - 1] : partPlan.reduce((a, p) => a + sum(p.shapes), 0);
  const thisSegs = PART ? partPlan[0].segs[PART - 1] : partPlan.reduce((a, p) => a + sum(p.segs), 0);
  if (!HARNESS && thisCall > SHAPE_BUDGET) throw new Error("shape budget: this call would create " + thisCall + " shapes (over " + SHAPE_BUDGET + "); set ONLY = [n] and PART = 1 … k per the part plan " + JSON.stringify(partPlan) + "; nothing was touched");
  if (!HARNESS && thisSegs > SEG_BUDGET) throw new Error("segment budget: this call would draw " + thisSegs + " path segments (over " + SEG_BUDGET + "); nothing was touched");
  return null;
}
const GATE = { selfCheck: null };

// ---- Board 1: SCR-053 docked right of SCR-030 in the 1280×800 shell — streaming, compact (spec §2) -----------------------------
BUILD[1] = () => {
  const b = place(1, "scr-053-panel-1280", W_BOARD, 1200);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — SCR-053 at 1280×800: the tape docked right of SCR-030, streaming, compact — the header, status and column-header rows, the log at its row count (25 per the tool with one chips row; 24 drawn here — the three default chips take two lines at the shared label width rule, D4), the control strip; Tab stops numbered (§2)", SRC);
  stamp(b, X, y, "PROPOSED · BQ-1..6 RULED"); mkText(b, LEGEND, X + 260, y + 5, W - 260, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  const shell = shellChrome(b, X, y, 1280, 800);
  const chartW = 1280 - NUM.panelW1280 - 16;
  placeholderPanel(b, X + 8, shell.top + 8, chartW - 8, shell.panelH - 16, "SCR-030 chart panel · BTCUSDT 1m (E11-D02 chassis; the bubble overlay is board 08)", "toolbar row · status row [DEMO] [Live] · legend block · plot · time strip");
  const px = X + chartW + 8, py = shell.top, pw = NUM.panelW1280; // r7: the panel is the dock's full 736 px between the bars (§2); r6 inset it 8 px and ran 4 px into the bottom bar
  const chrome = panelChrome(b, px, py, pw, { chips: [{ label: "Big only" }, { label: "Reconstructed 250 ms / 1 tick" }, { label: "(estimated)", fill: "hover", stroke: "borderStrong" }] });
  const rows = tapeRows(tapeRoom(py, chrome.logY), 0); // r7: the rows the 736 px panel holds under the chips row as drawn (24; 25 with one chips row)
  const tp = tapeBlock(b, px, chrome.logY, pw, rows, { density: "compact" });
  controlStrip(b, px, chrome.logY + tp.h, pw, { collapsed: true });
  // the Tab stops, numbered (spec §11 K1), as callouts left of the panel: header controls → the status row's buttons (one stop) → chips (one stop) → list (one stop) → strip
  [["1–5", py + 6], ["6", py + NUM.slotHeader + 4], ["7", chrome.logY - chrome.chipRows * NUM.slotChips + 4], ["8", chrome.logY + NUM.slotColHdr + 2], ["9", chrome.logY + tp.h + 2]].forEach((s) => pill(b, px - 12 - pillW("Tab " + s[0], 10, false, { padX: 5 }), s[1], "Tab " + s[0], { h: 16, size: 10, padX: 5, fill: "selected", stroke: "borderStrong", name: "tab-stop" })); // r9: right-aligned 12 px left of the panel, inside the chart placeholder (r8: at px − 62, so the widest ran 3 px past the placeholder's border — the containment self-check)
  // px callouts beside the shell
  const cx = X + 1280 + 40, cw2 = W - 1280 - 40;
  const c1 = card(b, cx, y, cw2, { kicker: "SLOTS, TOP → BOTTOM (D1; every px literal is a tool input)", value: "32 · 28 · 28 · 20 · log 604 → 25 rows · 24", lines: ["header row 32 px = size.control.compact 24 + space.2: the title, five 24 × 24 icon buttons (Filter prints (Ctrl+F) · Threshold… · Pause tape (P) aria-pressed · Columns… · More (Shift+F10) — its menu: Read tape summary · Reset columns · Density: Compact / Comfortable · Open settings); surface color.surface.raised, hairline color.border.default", "status row 28 px = 20 px pills + space.2: the feed-chip slot, the Paused chip, the gapped chip with Load missed prints, capped; the readout right-aligned in type.num.sm color.text.secondary, aria-live=\"off\", ≤2 Hz — +41 filtered only while a filter is on; the chips and the readout are plain text (the one status live region is hidden and pre-rendered empty); the row's buttons are Tab stop 6; its ladder: the readout drops /frame first, then the Paused chip takes its narrow form", "chips row 28 px (CMP-055 Active filters): the Big only preset, the mode chip + CMP-227 (estimated), the removable filter chips; wraps, never truncates a chip", "column header row 20 px: plain columnheader cells in type.num.sm color.text.tertiary — a tape is newest-first by construction, nothing sorts", "the log: 604 px at 1280×800 → 25 compact rows (tool, one chips row); drawn here with the chips row on two lines — the three default chips at the shared label width rule exceed 400 px once (estimated) carries its glyph (D4: wraps, never truncates) — so the log gives up one row: 24; the ≤60-row DOM window leaves 33 overscan rows beside 2 dividers; divider rows are presentation rows inside the window (no sticky per-second headers)", "control strip collapsed by default: 24 px (one summary line); expanded 80 px = three 24 px rows + space.2 (drawn below); comfortable: header 44 · status 32 · chips 32 · column header 24 · strip 32 / 108 (tool)", "panel 736 px tall under a 40 px top bar and a 24 px status bar; drawn 400 px wide (minimum 332 px compact / 403 comfortable — tool, 0.6 em mono advance (heuristic))"], foot: "neutral tokens only: color.surface.{app,canvas,raised,hover,selected}, color.text.{primary,secondary,tertiary}, color.border.{default,strong} — unbound on the boards (E13-D02 §13)" });
  const c2 = card(b, cx, y + c1.h + 24, cw2, { kicker: "WHAT THE TAPE PROMISES (memo F5, F7, F22, F24)", value: "no density makes 500 /s row-readable", lines: ["at 2 000 prints/s a row dwells 12.5 ms (compact) — the readable artefacts are the tiers, the clusters and the paused list", "the readout 2 010 /s (1 s) · 33 /frame is the coalescing factor: prints per frame, the rate labelled with its window; +41 filtered joins it only while a display filter is on (the prints the panel's filters hid — never 23 §14.2 dropped, D02-C16)", "new prints never move focus; nothing flashes; tier emphasis is persistent; rows appear in place", "the first three rows take the memo's §3.1 times and prices with sizes rescaled so the tiers hold at 250 000 USDT (D02-C9); every row's tier is computed; every other row is synthetic (LCG seed 507) and labelled so"], foot: "the DEMO band belongs to the shell chrome; the tape repeats no local badge; no order affordance (click-to-trade is E31's)" });
  mkText(b, NB("the strip expanded (80 px: three 24 px rows); collapsed on the screen above"), cx, y + c1.h + 24 + c2.h + 24, cw2, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "strip-label", h: 15 });
  controlStrip(b, cx, y + c1.h + 24 + c2.h + 44, cw2, {});
  finish(b, Math.max(y + 800, y + c1.h + 24 + c2.h + 44 + NUM.slotStrip));
};

// ---- Board 2: the same default at 2560×1440 — two charts, the tape at 480 px, placeholders; the minimum and wide widths; the comfortable pair ----
BUILD[2] = () => {
  const b = place(2, "scr-053-panel-2560", 2800, 1700);
  const X = b.x + 32, Y = b.y + 28, W = 2800 - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — SCR-053 at 2560×1440: two chart panels, the tape at 480 px (51 compact rows), SCR-050 and SCR-055 as placeholders; below: the panel at its minimum width (332 px), at a wide width (640 px — the Side column takes the slack), and the comfortable pair (32 px rows at its own slot heights; 403 px minimum)", SRC);
  stamp(b, X, y, "PROPOSED"); mkText(b, LEGEND, X + 160, y + 5, W - 160, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  const shell = shellChrome(b, X, y, 2560, 1440);
  const tapeW = NUM.panelW2560, chartW = Math.floor((2560 - tapeW - 32) / 2);
  placeholderPanel(b, X + 8, shell.top + 8, chartW - 8, shell.panelH - 16 - 300, "SCR-030 chart panel A · BTCUSDT 1m", "overlay on (board 08)");
  placeholderPanel(b, X + 8 + chartW, shell.top + 8, chartW - 8, shell.panelH - 16 - 300, "SCR-030 chart panel B · ETHUSDT 5m", "");
  placeholderPanel(b, X + 8, shell.top + shell.panelH - 300, chartW - 8, 284, "SCR-050 DOM ladder (placeholder)", "");
  placeholderPanel(b, X + 8 + chartW, shell.top + shell.panelH - 300, chartW - 8, 284, "SCR-055 speed of tape (placeholder)", "the readout rule is shared: ≤2 Hz (E25-D01 Q14)");
  const px = X + 2560 - tapeW - 8, py = shell.top; // r7: the dock's full 1 376 px
  const chrome = panelChrome(b, px, py, tapeW, { chips: [{ label: "Big only" }, { label: "Reconstructed 250 ms / 1 tick" }, { label: "(estimated)", fill: "hover", stroke: "borderStrong" }] });
  const rows = tapeRows(NUM.rows2560[0], 1);
  const tp = tapeBlock(b, px, chrome.logY, tapeW, rows, { density: "compact" });
  controlStrip(b, px, chrome.logY + tp.h, tapeW, { collapsed: true });
  mkText(b, NB("1 244 px log → 51 compact rows (tool); overscan 7 inside the ≤60-row window"), px, chrome.logY + tp.h + NUM.slotStripCollapsed + 6, tapeW, { size: 11, color: C.text3, tok: TOK.text3, name: "callout", h: 15 });
  y += 1440 + GAPY;
  // three crops: minimum width 332, wide 640, comfortable 420 (its minimum is 403)
  const crops = [[NUM.minWidth[0], "compact", "minimum width 332 px (tool): the Side word yields to the glyph first below it"], [NUM.panelWWide, "compact", "wide 640 px: the Side column takes the slack; nothing stretches"], [420, "comfortable", "the comfortable pair: 32 px rows, type.num.base 13 px, space.3 gaps, its own slot heights; 18 rows per 600 px, 17 at 1280×800, 37 at 2560×1440; 403 px minimum (tool)"]];
  let cx = X, cropBottom = 0, cropTop = y; // r8 (QA A): the crop labels wrap at spaces inside the crop's own column (r7 NBSP-joined them in a 15 px box: 481 / 1 016 px lines ran across the neighbouring crops); the chromes start under the tallest label
  crops.forEach((cr) => { const lbl = mkText(b, cr[2], cx, y, Math.max(cr[0], 420), { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "crop-label" }); cropTop = Math.max(cropTop, y + (lbl ? lbl.h : 15) + 6); cx += Math.max(cr[0], 420) + 60; });
  cx = X;
  crops.forEach((cr) => {
    const w = cr[0], rowH = cr[1] === "compact" ? NUM.rowPx[0] : NUM.rowPx[1];
    const ch = panelChrome(b, cx, cropTop, w, { chips: [{ label: "Big only" }], readout: w < 400 ? "2 010 /s (1 s)" : undefined, density: cr[1] });
    const tcr = tapeBlock(b, cx, ch.logY, w, tapeRows(12, 2), { density: cr[1], elideAfter: 12, elided: Math.floor((cr[1] === "compact" ? NUM.logPx1280 : NUM.logPxComfortable[0]) / rowH) - 12 }); // r8 (QA C): computed from the 1280×800 log the label names — 604 / 24 = 25 → 13; 572 / 32 = 17 → 5 (r7 typed 6: 12 + 6 = 18 drawn while the label and the tool say 17)
    cropBottom = Math.max(cropBottom, ch.logY + tcr.h);
    cx += Math.max(w, 420) + 60;
  });
  finish(b, cropBottom); // r7: from the drawn crops (r6's formula missed the chips row)
};

// ---- Board 3: row anatomy at both densities, the tiers, the merged row with / without ×N, the liq tag, the compressed row, the 50 / 500 / 2 000 band ----
BUILD[3] = () => {
  const b = place(3, "tape-rows-densities-tiers", W_BOARD, 1500);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — Row anatomy at compact and comfortable with ch / px per column; size tier (of a print) 0 / 1 / 2 by weight, ● / ◆, the 2 px accent and the band; the merged row with and without ×N (C18); the liq tag; the compressed row; the 50 / 500 / 2 000 density band (§3, §10)", SRC);
  stamp(b, X, y, "PROPOSED · Q1 Q2 Q10 drawn"); mkText(b, LEGEND, X + 240, y + 5, W - 240, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  const anat = memoRows().concat([ // the memo's three rows (sizes rescaled, D02-C9), then synthetic rows (labelled); every tier computed
    tapeRow("14:02:10.771", "sell", 5.2, 64012.0, ["×7"]),
    tapeRow("14:02:10.502", "sell", 4.6, 64011.5, ["⧉"]),
    tapeRow("14:02:10.230", "buy", 0.44, 64012.0, ["liq"]),
    tapeRow("14:02:09.998", "buy", 0.06, 64012.5, ["blk"]),
  ]);
  const al = mkText(b, "compact · 24 px rows · type.num.sm 11 px · ch per column Time 12 · Price 9 · Size 6 · Notional 6 · Side 4 · glyph 1 · tier 1 = 39 ch → 332 px minimum (tool)", X, y, 540, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "anat-label" });
  const top3 = y + (al ? al.h : 30) + 6;
  const t1 = tapeBlock(b, X, top3, 520, anat, { density: "compact", selectedRow: 3, focusRow: 3 });
  mkText(b, NB("comfortable · 32 px rows · type.num.base 13 px · space.3 gaps · 403 px minimum (tool)"), X + 580, y, 600, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "anat-label", h: 15 });
  const t2 = tapeBlock(b, X + 580, top3, 620, anat, { density: "comfortable" });
  const cardX = X + 1220, cardW = W - 1220;
  const c1 = card(b, cardX, y, cardW, { kicker: "THE ROW (D7–D12; memo F1–F4, F12)", value: "Time · ▲▼ · Price · Size · ●◆ · Notional · Side · tags", lines: ["numerics right-aligned in font.family.mono tabular figures; Price · Size · Notional adjacent; the side glyph before Price; the tier glyph right after Size on the baseline (the memo's text puts the tier mark last — D02-C10); the word Buy / Sell last", "the first three rows: the memo's times and prices with sizes rescaled (4.00 → 256.1k ●, 18.75 → 1.2M ◆, 0.12 → 7.7k) — the memo's 54.4k / 134.4k cannot both hold under the 4× rule (D02-C9); every tier here is computed from 250 000 / 1 000 000 USDT", "the HH:MM: prefix in color.text.tertiary on tiers 0–1 (Q2) — undimmed on a tier-2 band and on the selected row (tertiary on selected measures 3.98 dark: rejected by design, tool)", "tier 0 regular 400 · tier 1 medium 500 + ● + 2 px accent · tier 2 bold 700 + ◆ + the band; words and numerics in color.text.primary on every tier", "×7 = the Cluster ×N cell where cluster_size is on the wire; ⧉ = the merged row on kind 3 today, flag only, no count (C18 (b)) — the panel badge says rows are reconstructed", "liq = is_liquidation as a tag, never a column (counted once via liquidations.{symbol}); blk = is_block_trade", "row 4 shows the selected row (surface.selected) with the focus-ring stand-in (2 px text.primary) — keyboard focus only"], foot: "row name: Sell, 18.75 BTC at 64,012.0, 1.2M, whale, 14:02:11.208 — side first whatever the order" });
  y = Math.max(top3 + t1.h, top3 + t2.h, y + c1.h) + GAPY;
  // the compressed row (rung 3)
  mkText(b, NB("rung 3 (Q10, D12): tier-0 prints of one frame collapse into one row; pause expands it; tier 1–2 rows are never compressed"), X, y, 1100, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "comp-label", h: 15 });
  const tc = tapeBlock(b, X, y + 20, 520, [anat[0], anat[1]], { density: "compact", dividers: { 1: "27 small prints · Σ 1.9" } });
  pill(b, X + 400, y + 20 + NUM.slotColHdr + 24 + 2, "compressed", { h: 20, size: 11, fill: "hover", stroke: "borderStrong", name: "compressed-badge" });
  y += tc.h + 20 + GAPY;
  // the 50 / 500 / 2 000 band: three 600 px crops side by side (memo F5)
  mkText(b, NB("the 50 / 500 / 2 000 prints/s band (memo F5): what stays readable in a 600 px panel of 25 compact rows — rows as a flicker · tiers only · the readout"), X, y, W, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "band-label", h: 15 });
  const bandY = y + 20, bandW = 560;
  let bandBottom = 0;
  NUM.rates.forEach((r, i) => {
    const bx = X + i * (bandW + 40);
    const ch = panelChrome(b, bx, bandY, bandW, { chips: [{ label: "Big only" }], readout: [fmt(r) + " /s (1 s) · " + NUM.perFrame[i] + " /frame", fmt(r) + " /s (1 s) · " + NUM.perFrame[i] + " /frame", "2 010 /s (1 s) · 33 /frame"][i] });
    const tband = tapeBlock(b, bx, ch.logY, bandW, tapeRows(12, 3 + i), { density: "compact", elideAfter: 12, elided: NUM.rows600[0] - 12, liveEdge: false }); // r8: computed — the 600 px panel's 25 compact rows (memo F5; the band label says so) less the 12 drawn
    bandBottom = Math.max(bandBottom, ch.logY + tband.h);
    const note = ["0.83 prints per frame · row dwell 500 ms · tier glyphs and the paused list; rows as a flicker", "8.33 prints per frame · row dwell 50 ms · tier 1–2 rows only; clusters; the readout", "33.33 prints per frame · row dwell 12.5 ms (under one frame) · tier 2 only; the readout"][i];
    mkText(b, NB(note), bx, ch.logY + tband.h + 8, bandW, { size: 11, color: C.text3, tok: TOK.text3, name: "band-note" }); // r7: under the drawn log (r6's formula missed the chips row: the note sat on the elision row)
  });
  finish(b, bandBottom + 40);
};

// ---- Board 4: the pause model — the §5 state diagram WITH its cross-edges (the soft / scroll pauses hand over to the focus pause;
// focus wins until Esc or blur), the P1–P14 transition table, and seven frames at the panel's 400 px default width ---------
BUILD[4] = () => {
  const b = place(4, "pause-model-states", W_BOARD, 2400);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — The pause model (§5): one list state with fourteen rows (P1–P14) — hover intent 150 ms → soft paused → 30 s park → re-arm; scroll-away → Jump to live (Ctrl+Home); P; click or focus pauses first and wins over the hover and park exits; Esc innermost; the full ring (S22); resume inserts under the divider; where tape.paused / tape.resumed fire", SRC);
  stamp(b, X, y, "PROPOSED · Q3 Q13 drawn · BQ-3 RULED"); mkText(b, LEGEND, X + 280, y + 5, W - 280, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  // -- the diagram: five state nodes, every edge labelled with its P-row id; the grey line is the cross-edge P8 from a soft / scroll pause
  const dy = y;
  const edge = (pts, o) => { // an orthogonal connector: 2 px segments through pts, an arrowhead at the end, a label pill
    o = o || {}; const ink = o.ink || "text3";
    for (let i = 1; i < pts.length; i++) { const x1 = pts[i - 1][0], y1 = pts[i - 1][1], x2 = pts[i][0], y2 = pts[i][1]; if (y1 === y2) mkRect(b, Math.min(x1, x2), y1 - 1, Math.abs(x2 - x1), 2, ink, { role: "wire", name: "edge" }); else mkRect(b, x1 - 1, Math.min(y1, y2), 2, Math.abs(y2 - y1), ink, { role: "wire", name: "edge" }); }
    const px = pts[pts.length - 1][0], py = pts[pts.length - 1][1], qx = pts[pts.length - 2][0], qy = pts[pts.length - 2][1];
    const head = px > qx ? "▶" : px < qx ? "◀" : py > qy ? "▼" : "▲";
    mkText(b, head, head === "▶" ? px - 14 : head === "◀" ? px : px - 7, head === "▲" ? py : head === "▼" ? py - 15 : py - 8, 14, { size: 11, align: "center", color: C[ink], tok: TOK[ink], name: "edge-head", h: 15 }); // r9: every head sits on the incoming side of its end point with its tip at the point — r6 did this for ▲ only (its box starts at the edge; r5 started 8 px inside, so the 15.18 px line rendered 7.2 px past the frame); ◀ ▶ ▼ were centred on the point, so half the head lay inside the node it enters or over the P5 label (the containment self-check)
    if (o.label) pill(b, o.lx, o.ly, o.label, { h: 20, size: 11, fill: o.decision ? "hover" : "raised", stroke: o.decision ? "text" : "border", strokeWidth: o.decision ? 2 : 1, name: "edge-label" });
  };
  const node = (x, ny, label, sub, decision) => {
    mkRect(b, x, ny, 220, 56, "raised", { stroke: decision ? "text" : "borderStrong", strokeWidth: decision ? 2 : 1, radius: 8, role: "wire", name: "state:" + label });
    mkText(b, label, x + 12, ny + 8, 196, { size: 16, weight: 700, name: "state-label", h: 22 });
    mkText(b, NB(sub), x + 12, ny + 32, 196, { size: 11, color: C.text2, tok: TOK.text2, name: "state-sub", h: 15 });
  };
  node(X + 40, dy + 170, "live", "rows enter in place");
  node(X + 720, dy + 20, "soft paused", "hover intent ≥150 ms, then move", true);
  node(X + 720, dy + 170, "scroll paused", "away from the live edge", true);
  node(X + 40, dy + 320, "focus paused", "a row holds focus", true);
  node(X + 1440, dy + 170, "hard paused", "P / button · aria-pressed", true);
  edge([[X + 200, dy + 170], [X + 200, dy + 48], [X + 720, dy + 48]], { label: "P1 pointermove after ≥150 ms at rest (hover intent)", lx: X + 300, ly: dy + 20 });
  edge([[X + 720, dy + 60], [X + 240, dy + 60], [X + 240, dy + 170]], { label: "P2 leave · P3 30 s park [no row focused]", lx: X + 300, ly: dy + 66 });
  edge([[X + 260, dy + 184], [X + 720, dy + 184]], { label: "P4 wheel away from the live edge", lx: X + 300, ly: dy + 156 });
  edge([[X + 720, dy + 200], [X + 260, dy + 200]], { label: "P5 Jump to live: Ctrl+Home · button · scroll up", lx: X + 300, ly: dy + 206 });
  pill(b, X + 300, dy + 228, "[no row focused]", { h: 20, size: 11, name: "edge-label" }); // the P5 guard: a focused row makes it P8 (K4)
  edge([[X + 150, dy + 226], [X + 150, dy + 320]], { label: "P8 click / focus: pauses first, then selects", lx: X + 250, ly: dy + 252 });
  edge([[X + 230, dy + 320], [X + 230, dy + 226]], { label: "P9 Esc (innermost) or focus leaves → live", lx: X + 250, ly: dy + 280 });
  edge([[X + 720, dy + 72], [X + 640, dy + 72], [X + 640, dy + 348], [X + 260, dy + 348]], { ink: "text2", label: "P8 cross-edge: a click or focus takes over the exit (focus wins until P9)", lx: X + 650, ly: dy + 110, decision: true });
  edge([[X + 720, dy + 218], [X + 640, dy + 218]], { ink: "text2" });
  edge([[X + 940, dy + 48], [X + 1500, dy + 48], [X + 1500, dy + 170]], { label: "P6 P or the pause button → hard paused (never auto-resumes)", lx: X + 1000, ly: dy + 20 });
  edge([[X + 940, dy + 190], [X + 1440, dy + 190]], { label: "P6 P or the button", lx: X + 1000, ly: dy + 160 });
  edge([[X + 260, dy + 360], [X + 1500, dy + 360], [X + 1500, dy + 226]], { label: "P6 from a focus pause: P makes the pause sticky (memo §5; F8 reads P as resume — D02-C13)", lx: X + 700, ly: dy + 366 });
  edge([[X + 1620, dy + 226], [X + 1620, dy + 440], [X + 10, dy + 440], [X + 10, dy + 198], [X + 40, dy + 198]], { label: "P7 P or the button — a hard pause never auto-resumes; the park never touches it; resume inserts under the divider (P12)", lx: X + 400, ly: dy + 446 });
  pill(b, X + 40, dy + 390, "Ctrl+Home on a focused row: the cursor and the viewport to the live edge; the pause holds (K4, D02-C17)", { h: 20, size: 11, name: "edge-label" });
  pill(b, X + 1400, dy + 244, "P13 Esc releases the selection; the pause continues", { h: 20, size: 11, name: "edge-label" }); // r6: 8 px lower — clear of the P6 edge's ▲ head, which now ends at dy + 241 under the hard paused node (r5: dy + 236 overlapped it 2.8 px)
  let nx = X;
  ["P10 a feed state while paused: two chips, never merged", "P11 the count ticks in a plain node — never a live region", "P12 resume inserts under the divider, never a replay"].forEach((t) => { nx += pill(b, nx, dy + 480, t, { h: 20, size: 11, name: "note-pill" }) + 12; });
  pill(b, X, dy + 510, "P14 the ring fills while paused → Paused — buffer full · 10 000 kept (S22); on resume — 12 000 prints while paused · 2 000 not kept — + Load missed prints", { h: 20, size: 11, fill: "hover", stroke: "text", strokeWidth: 2, name: "note-pill" });
  mkText(b, NB("edges carry the §5 row ids; the grey cross-edge is the focus pause that takes over a soft or scroll pause; [no row focused] = the P2 / P3 / P5 guard (memo F8 / F22; 05 §3.4 item 3)"), X, dy + 540, W, { size: 11, color: C.text3, tok: TOK.text3, name: "diagram-note", h: 15 });
  y = dy + 580;
  // -- the transition table (spec §5, P1–P14)
  const pt = tableBlock(b, X, y, [44, 190, 300, 520, 300, 190, 232], ["Id", "From → to", "Event", "Guard", "Chip text", "Announcement", "Emits"], [ // r7: the §5 table's own seven columns and cells, verbatim (r6 merged Event + Guard and Chip + Announcement and paraphrased)
    ["P1", "live → soft paused", "pointermove over the list", "the pointer has been at rest ≥150 ms over the list (hover intent, memo F9 — movement, never presence; a crossing never pauses)", "\"Paused — 412 prints buffered\"", "none", "tape.paused {cause: hover}"],
    ["P2", "soft paused → live", "the pointer leaves the list", "not hard-paused and no row holds focus (focus wins until P9)", "removed; the resume divider \"— 412 prints while paused —\"", "\"Resumed, 412 prints inserted\" polite", "tape.resumed {cause: leave, inserted: 412}"],
    ["P3", "soft paused → live (parked)", "30 s without pointermove", "the hover entry only, and no row holds focus; afterwards the soft pause re-arms only on the next pointermove or re-entry — a still pointer never re-pauses the tape (no oscillation)", "the same divider", "the same, once", "tape.resumed {cause: park, inserted: N}"],
    ["P4", "live → scroll paused", "wheel / scroll away from the live edge", "a trader reading history is never jumped to live", "\"Paused — 412 prints buffered · Jump to live\"", "none", "tape.paused {cause: scroll}"],
    ["P5", "scroll paused → live", "Jump to live: Ctrl+Home with no row focused (K4), the chip's button, or scrolling back to the top", "no park timer ever runs here; a row focused during a scroll pause makes it a focus pause (P8), which Ctrl+Home brings to the live edge without resuming (K4)", "removed; the divider", "the same, once", "tape.resumed {cause: jump, inserted: N}"],
    ["P6", "any → hard paused", "P with panel focus, or the pause button", "from a focus pause P makes the pause sticky (memo §5: \"P toggles the hard pause\"; memo F8's \"P resumes\" is the other reading — D02-C13, E22-D04 owns the key); an open menu or a text field consumes P first (K7)", "\"Paused — 412 prints buffered\"; the button aria-pressed=\"true\"", "none", "tape.paused {cause: key | button}"],
    ["P7", "hard paused → live", "P or the button", "never auto-resumes; the park never touches it", "removed; the divider", "the same, once", "tape.resumed {cause: key | button, inserted: N}"],
    ["P8", "live / soft paused / scroll paused → focus paused", "a row click or keyboard focus on a row", "pauses first, then selects (memo F8); from a soft or scroll pause the list stays frozen and the focus takes over the exit (P9)", "\"Paused — 412 prints buffered\"", "none", "tape.paused {cause: focus} (from live); tape.print_clicked {ts_ms, price, side, tier} on a click or Enter (K5) only — never on keyboard focus alone"],
    ["P9", "focus paused → live", "Esc with a row focused and nothing more inner open, or focus leaves the list", "the innermost-cancel rule (memo C16): a menu or popover closes first, the filter input clears first; these are the only exits of a focus pause whatever its entry — from a scroll pause too, and the viewport returns to the live edge (D02-C17); Ctrl+Home on a focused row moves the cursor and the viewport there and the pause holds (K4)", "removed; the divider", "the same, once", "tape.resumed {cause: esc | blur, inserted: N}"],
    ["P10", "paused + Stale / Disconnected", "the feed state changes while paused", "the pause state survives the feed state; both chips show, never merged", "\"Paused — …\" beside \"Stale 12s\"; in Disconnected the pause button is T2 (§11.4) unless hard-paused (S10)", "the feed state's own (E17-D01 §7)", "none"],
    ["P11", "paused → paused", "prints arrive", "—", "the count ticks as a text swap in a plain node — never in a live region (D29)", "none", "none"],
    ["P12", "resume insertion", "any resume", "the buffered prints are inserted under the divider; the divider is presentation, never focusable (memo F22)", "—", "one polite sentence (above)", "—"],
    ["P13", "hard paused + Esc", "Esc with a row focused and nothing more inner open", "the selection is released (the crosshair stays); the hard pause continues and ends only by P7 — a scroll pause with a focused row is a focus pause (P8), so Esc there is P9; with nothing left to cancel the key is not swallowed (05 §3.3 rule 3)", "unchanged", "none", "none"],
    ["P14", "paused (any) → paused, buffer full", "the ring fills (S22)", "the visible window and its overscan are pinned; the oldest prints outside it are evicted and counted (D02-G7, E22-S01)", "\"Paused — buffer full · 10 000 kept\"; on resume \"— 12 000 prints while paused · 2 000 not kept —\" + Load missed prints", "\"Resumed, 10 000 prints inserted, 2 000 not kept\" once", "tape.resumed {…, inserted: 10 000, dropped: 2 000} (dropped PROPOSED, D02-G1)"],
  ], { stk: TICKET + ":b4-table" });
  y += pt.h + GAPY;
  // -- the frames, each at the panel's 400 px default width (the status-row ladder runs where a Paused chip needs the room)
  const fl = mkText(b, ("frames at 400 px: soft paused (the live-edge divider; no roving cursor — a focus pause would show one) · scroll-away with the Jump to live button · hard paused (the button pressed) · resumed (the insertion divider) · P10 paused in a stale feed (two chips, never merged) · S22 the full ring · resumed after the full ring (the divider counts the prints not kept; Load missed prints in the status row)"), X, y, W, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "frames-label" });
  const fw = NUM.panelW1280, fgap = 40, fy1 = y + (fl ? fl.h : 40) + 8; // r8: under the label's wrapped height (r7: + 40 under an NBSP-joined one-line label that ran off the board)
  const frame = (fx, fy, chromeOpts, tapeOpts, seed) => { const ch = panelChrome(b, fx, fy, fw, chromeOpts); const t = tapeBlock(b, fx, ch.logY, fw, tapeRows(8, seed), Object.assign({ density: "compact" }, elide(8, Object.keys((tapeOpts || {}).dividers || {}).length, 0), tapeOpts)); return ch.logY + t.h; }; // r7: the elided count from the frame (25 − 8 − its dividers)
  let fb = 0;
  fb = Math.max(fb, frame(X, fy1, { status: [{ label: "Paused — 412 prints buffered", fill: "hover", stroke: "borderStrong" }], chips: [{ label: "Big only" }] }, { liveEdge: true }, 7));
  fb = Math.max(fb, frame(X + fw + fgap, fy1, { status: [{ label: "Paused — 412 prints buffered", fill: "hover", stroke: "borderStrong" }], actions: ["Jump to live"], chips: [{ label: "Big only" }] }, { elideAfter: 0 }, 8)); // the elision above the rows (scrolled away)
  fb = Math.max(fb, frame(X + 2 * (fw + fgap), fy1, { paused: true, status: [{ label: "Paused — 412 prints buffered", fill: "hover", stroke: "borderStrong" }], chips: [{ label: "Big only" }] }, { liveEdge: true }, 9));
  fb = Math.max(fb, frame(X + 3 * (fw + fgap), fy1, { chips: [{ label: "Big only" }] }, { dividers: { 0: "— 412 prints while paused —" } }, 10));
  const fy2 = fb + GAPY;
  fb = Math.max(fb, frame(X, fy2, { status: [{ label: "Stale 12s" }, { label: "Paused — 412 prints buffered", fill: "hover", stroke: "borderStrong" }], chips: [{ label: "Big only" }], readout: "—" }, { liveEdge: true }, 11)); // r7: the CMP-239 chip takes its binding from pill() (dot, no outline)
  fb = Math.max(fb, frame(X + fw + fgap, fy2, { paused: true, status: [{ label: "Paused — buffer full · 10 000 kept", fill: "hover", stroke: "borderStrong", decision: true }], chips: [{ label: "Big only" }] }, { liveEdge: true }, 12));
  fb = Math.max(fb, frame(X + 2 * (fw + fgap), fy2, { actions: ["Load missed prints"], chips: [{ label: "Big only" }] }, { dividers: { 0: "— 12 000 prints while paused · 2 000 not kept —" } }, 13));
  mkText(b, ("S22 (PROPOSED, E22-S01): the visible window and its overscan are pinned; the oldest prints outside it are evicted (history below the window first, then the oldest buffered prints) and counted; QA: hard-pause 6 s at 2 000 /s — the chip flips at 10 000, the window never moves, the divider counts 12 000 / 2 000"), X + 3 * (fw + fgap), fy2, fw, { size: 11, color: C.text2, tok: TOK.text2, name: "s22-note" });
  finish(b, fb);
};

// ---- Board 5: the feed and list states (§4 S7–S19) — each card's value line is its copy string ---------------------------------
BUILD[5] = () => {
  const b = place(5, "feed-and-list-states", W_BOARD, 1700);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — Feed and list states (§4): Stale T1 beside Paused (two pills) · Stale ≥ T2 · Disconnected as a 400 px frame (the header outside the scrim; the pause button T2 — the lock badge on ⏸ and the CMP-016 echo — beside the hard-paused T1 variant) · Delayed · Loading · Empty · Filtered-empty · Partial history · Reconnect backfill before / after · Mode switch · the over-threshold strip · compressed rows", SRC);
  stamp(b, X, y, "PROPOSED · Q7 Q10 drawn · T2 per §11.4"); mkText(b, LEGEND, X + 300, y + 5, W - 300, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  const s1 = strip(b, X, y, W, "FEED STATES (E17-D01 §5; E08-D11) — the tape column", [
    { v: "Stale 12s", t: "S8 · T1 trades 10 s", d: "rows kept, never re-sorted; no new rows; the panel dims 15 % (E08-D11 D26); readout —; beside a Paused chip: two pills, never merged (memo F23)", pills: [{ label: "Stale 12s" }, { label: "Paused — 412 prints buffered", fill: "hover", stroke: "borderStrong" }], decision: true }, // r7: the feed chips take their CMP-239 binding from pill()
    { v: "Stale 30s", t: "S9 · T2 = 3 × T1", d: "the strong chip (a cut, E08-D11 M34); one assertive announcement per episode — the chart's sentence; the tape adds nothing", pill: "Stale 30s" }, // the S9 strong chip: the indicator as the outline too (pill())
    { v: "Disconnected — last data 00:12", t: "S10 · transport down", d: "frozen last-good rows under the SCR-152 strip and the 0.6 scrim (the rows measure 3.23 / 2.39 / 1.89 through it — reported, D02-C15); the pause button is T2 while not hard-paused: lock glyph + the full label Pause tape (P) + the reason under the button's own node, aria-disabled, in the Tab order, one polite re-show on a press (E09-D09 §2.2, §9.3); a hard pause set before the drop keeps it T1 as resume", pills: [{ label: "Offline" }, { label: "🔒 Pause tape (P)", text: C.text3, tok: TOK.text3 }] },
    { v: "every print represented", t: "S7 · Delayed (saturated / overflowing)", d: "a raw row each, or a merged row carrying its count; no tape tag — the global chip reads Reduced rate ×4; polite once on entry / exit, by that chip", pill: "readout live", pillMono: true },
  ]);
  y += s1.h + GAPY;
  // -- S10 as a frame at 400 px (E09-D09 §2.2 rendering 2b; D28 (1)): the header outside the 0.6 scrim, the pause button T2 with the ⏸ glyph
  // kept in the middle grey and a lock badge, its reason visually hidden and echoed by CMP-016; the SCR-152 strip over the frozen rows;
  // beside it the hard-paused variant (▶ pressed before the drop) stays T1 as resume
  const sl = mkText(b, ("S10 · Disconnected at 400 px (D28 (1); E09-D09 §2.2 rendering 2b): the header row sits outside the 0.6 scrim — the pause button T2 keeps its ⏸ glyph in the middle grey with a lock badge (CMP-019, Not available), its reason visually hidden and echoed by CMP-016 on hover and focus; the SCR-152 strip over the frozen rows; beside it the hard-paused variant (▶ pressed before the drop) stays T1 as resume"), X, y, W, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "s10-label" });
  const fy10 = y + (sl ? sl.h : 40) + 8, fw10 = NUM.panelW1280, stripH10 = 28; // r8: under the label's wrapped height
  const frame10 = (fx, chromeOpts, seed) => {
    const ch = panelChrome(b, fx, fy10, fw10, chromeOpts);
    mkRect(b, fx, ch.logY, fw10, stripH10, "hover", { stroke: "borderStrong", role: "wire", name: "scr-152-strip" });
    mkText(b, NB("Disconnected — last data 00:12"), fx + 10, ch.logY + 6, fw10 - 20, { size: 12, weight: 600, name: "scr-152-text", h: 16 });
    const t = tapeBlock(b, fx, ch.logY + stripH10, fw10, tapeRows(8, seed), Object.assign({ density: "compact" }, elide(8, 0, stripH10))); // r7: the SCR-152 strip takes 28 px of the log
    mkRect(b, fx, ch.logY + stripH10, fw10, t.h, "app", { opacity: NUM.scrim, role: "wire", name: "scrim" }); // the frozen rows seen through opacity.scrim 0.6 of color.surface.app (D02-C15)
    return ch.logY + stripH10 + t.h;
  };
  let fb10 = frame10(X, { pauseT2: true, status: [{ label: "Offline" }], readout: "—" }, 43);
  // the CMP-016 echo of the hidden reason node (hover and focus) beside the frame — a copy of the hidden node, never the only one
  const ex = X + fw10 + 40, ew = 260;
  const el = mkText(b, "the pause button, T2 (2b): lock badge on ⏸ · aria-disabled · in the Tab order", ex, fy10, ew, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "echo-label" });
  const ey = fy10 + (el ? el.h : 40) + 4; // r8 (QA A): the echo sits under the label's wrapped height (r7: + 40 under an NBSP-joined label that ran under the hard-paused frame)
  mkRect(b, ex, ey, ew, 48, "overlay", { stroke: "borderStrong", radius: 6, role: "wire", name: "tooltip-echo" });
  lockText(b, NB("🔒 Pause tape (P)"), ex + 10, ey + 6, ew - 20, { size: 11, weight: 600, color: C.text3, tok: TOK.text3, name: "tooltip-echo-label", h: 15 }); // r8 (QA B): the drawn lock
  mkText(b, NB("Nothing to pause while disconnected."), ex + 10, ey + 24, ew - 20, { size: 11, color: C.text2, tok: TOK.text2, name: "tooltip-echo-reason", h: 15 });
  const en = mkText(b, "CMP-016 echoes the visually hidden reason node on hover and focus — never the only copy; P from the list changes nothing: the echo shows the reason in place for one dwell and the reason is written once into the status node (K7, K15)", ex, ey + 60, ew, { size: 11, color: C.text3, tok: TOK.text3, name: "echo-note" });
  const hx = ex + ew + 40;
  fb10 = Math.max(fb10, frame10(hx, { paused: true, pauseT2: false, status: [{ label: "Offline" }, { label: "Paused — 412 prints buffered", fill: "hover", stroke: "borderStrong" }], readout: "—" }, 47));
  const hp = mkText(b, ("hard pause set before the drop: T1, aria-pressed=\"true\" — pressing it clears the hard pause so the tape streams at reconnect (PROPOSED, S10 / P10)"), hx, fb10 + 8, fw10, { size: 11, color: C.text3, tok: TOK.text3, name: "hard-pause-note" });
  const c10 = card(b, hx + fw10 + 40, fy10, W - (hx + fw10 + 40 - X), { kicker: "S10 · THE DISCONNECTED PAUSE (D28 (1); E09-D09 §2.2 2b, §9.3; D02-C15)", value: "lock badge on ⏸ · the full label · the reason echoed · aria-disabled", lines: ["the header row sits outside the scrim, so the T2 label, glyph and echo are never dimmed; the frozen rows under the 0.6 scrim measure 3.23 / 2.39 / 1.89 dark — reported, not gated (D02-C15, E22-D03)", "the reason node is the button's own (feed.disconnected_pause, PROPOSED — E17-D01 §7 owner); the SCR-152 strip stays the feed notice, not the button's reason", "raised fill + the border hairline, the glyph and the label in the middle grey — never opacity.disabled, never color.text.disabled; text + glyph + the fill change + aria-disabled carry the state", "a hard pause set before the drop keeps the button T1 as resume (aria-pressed); pressing it clears the hard pause so the tape streams at reconnect (PROPOSED)"], foot: "a T2 press emits nothing; the feed state's own assertive announcement is SCR-152's (E17-D01 §7)" });
  y = Math.max(fb10 + 30, fb10 + 8 + (hp ? hp.h : 0), ey + 60 + (en ? en.h : 0), fy10 + c10.h) + GAPY; // r8: the wrapped notes count too
  const s2 = strip(b, X, y, W, "LIST STATES (memo §6; F23) — they reuse the divider pattern; every string verbatim", [
    { v: "Loading…", t: "S11 · before the snap (Last 200 prints)", d: "no placeholder rows — a tape promises no row count; the header and the readout read the word, never — (E25-D01 F8)", pill: "Loading…" },
    { v: "No prints yet · last print 13:58:02", t: "S12 · Empty, quiet symbol", d: "the feed chip stays Live; readout 0 /s · quiet", pill: "0 /s · quiet", pillMono: true },
    { v: "No prints above 10 000 USDT in the last 5 min", t: "S13 · Filtered-empty", d: "CMP-026 filtered-empty in the log area with the real button; the store is intact, clearing restores the rows at once; +N filtered counts the rows the display filter hides, never 23 §14.2 dropped (D02-C16); 5 min is the 14 example — N is the store's span (5 s at 2 000 /s with the 10 000-print default)", pill: "Clear filter", pillFill: "selected", pillStroke: "borderStrong", pillButton: true, decision: true }, // r7: a CMP-001 button
    { v: "— No history before 13:58:02. Recording started then. —", t: "S14 · Partial history (global AC 7)", d: "an in-list presentation divider at the seam, rows above it; REST /market/trades serves older prints when it has them; E16-D05 owns the final copy", pill: "— No history before 13:58:02 —", pillMono: true },
  ]);
  y += s2.h + GAPY;
  const s3 = strip(b, X, y, W, "the seam dividers — reconnect backfill before / after, and the mode switch", [
    { v: "— gap 14:02:11.331 → 14:02:19.004 —", t: "S15 · Reconnect backfill, before", d: "the 200-print snapshot reseeds the list (23 §9.3); the header gapped chip appears at 0 ms and outlives the overlay (E08-D11 H12 / M12) with the Load missed prints button beside it in the status row (Tab stop 6) — the divider stays presentation; polite once: Reconnected — gap 14:02:11.331 to 14:02:19.004 (the count is unknown until the REST load)", pills: [{ label: "Reconstructed after gap" }, { label: "Load missed prints", fill: "selected", stroke: "borderStrong", button: true }], decision: true }, // r7: the gapped chip from pill(); the action a CMP-001 button
    { v: "— 1 240 prints while disconnected —", t: "S16 · after Load missed prints", d: "the missed prints inserted under the divider, deduped by id on the structured path (22 PublicTrade.id) and by ts_ms + price + size + side on kind 3 (no id, G2); the gapped chip stays; polite once: 1 240 missed prints loaded", pill: "Reconstructed after gap" },
    { v: "— clustering off from here —", t: "S17 · Mode switch raw ↔ reconstructed", d: "E22-S04 re-subscribes with the new cluster_window_ms and keeps the ring buffer; the list is mixed at the seam; the panel badge flips with the option", pills: [{ label: "Raw prints", fill: "canvas" }, { label: "— clustering on from here —", mono: true }] },
  ]);
  y += s3.h + GAPY;
  // the over-threshold strip in place (S18) + the compressed rows (S19)
  mkText(b, NB("S18 · the over-threshold strip (memo F19; Q7): flagged prints carry capped=True and stay tier 1; one polite announcement per episode; silent at or below p80 in percentile mode"), X, y, W, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "strip-label", h: 15 });
  const sw = 1120, sy = y + 20;
  mkRect(b, X, sy, sw, 92, "hover", { stroke: "borderStrong", radius: 8, role: "wire", name: "warning-strip" });
  const wt = mkText(b, "Threshold flags 23.5 % of prints — raised to 34 723 USDT (the window's p80); prints between 30 000 and 34 723 are not flagged", X + 16, sy + 12, 760, { size: 13, weight: 600, name: "warning-text" });
  pill(b, X + 800, sy + 16, "Apply 34 723", { h: 24, size: 11, weight: 700, radius: 4, fill: "selected", stroke: "borderStrong", name: "apply" }); // r7: CMP-001 buttons (4 px corners)
  pill(b, X + 930, sy + 16, "Keep 30 000", { h: 24, size: 11, weight: 600, radius: 4, fill: "raised", stroke: "borderStrong", name: "keep" });
  let px2 = X + 16; const ry2 = sy + 12 + (wt ? wt.h : 40) + 6;
  px2 += pill(b, px2, ry2, "eff. 34.7k USDT", { h: 20, size: 11, mono: true, name: "eff-readout" }) + 6;
  px2 += pill(b, px2, ry2, "capped", { h: 20, size: 11, fill: "hover", stroke: "borderStrong", name: "capped" }) + 6;
  mkText(b, NB("notional mode: the capped readout is exact (no (estimated) — estimated is mode == percentile in bigtrade.py)"), px2 + 6, ry2 + 3, 860, { size: 11, color: C.text3, tok: TOK.text3, name: "capped-note", h: 15 });
  const c5 = card(b, X + sw + 40, y, W - sw - 40, { kicker: "THE NUMBERS (tool; synthetic dense tape, shape only)", value: "250 000 → 0.77 % · 100 000 → 4.3 % · 30 000 → 23.5 % · 10 000 → 57.5 %", lines: ["the engine raises the effective threshold to max(user value, window p80) and keeps flagging above it with capped=True (bigtrade.py _refresh); the strip says which prints are not flagged", "Apply makes suggested_value the user's value (a threshold write — T2 while viewing as, board 06); Keep leaves the user's value and the cap keeps following the window — the strip collapses to the capped chip; Apply / Keep sit in the status row's Tab stop", "OVERFLAG_FRACTION 0.20 · OVERFLAG_CAP_Quantile 0.80 · OVERFLAG_MIN_SAMPLES 20 (quoted from limits.py by the tool)", "announcement, polite, once per episode: Threshold raised to 34 723 USDT — 23.5 % of prints were flagged"], foot: "E22-S02 owns the control; the engine's rule is kept verbatim" });
  y += Math.max(92 + 20, c5.h) + GAPY;
  mkText(b, NB("S19 · rung 3 compressed rows (Q10): 27 small prints · Σ 1.9 with the text badge compressed — compression, not loss; the ring buffer keeps every print; pause expands"), X, y, W, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "comp-label", h: 15 });
  const pcomp = panelChrome(b, X, y + 20, 520, { chips: [{ label: "Big only" }], readout: "2 010 /s (1 s) · 33 /frame" });
  const tcomp = tapeBlock(b, X, pcomp.logY, 520, tapeRows(8, 11), Object.assign({ density: "compact", dividers: { 2: "27 small prints · Σ 1.9", 5: "27 small prints · Σ 1.9" } }, elide(8, 2, 0)));
  pill(b, X + 400, pcomp.logY + NUM.slotColHdr + 2 * 24 + 2, "compressed", { h: 20, size: 11, fill: "hover", stroke: "borderStrong", name: "compressed-badge" });
  finish(b, pcomp.logY + tcomp.h);
};

// ---- Board 6: the filter popover, the chips row, the column picker with availability by encoding, the view-as read-only frame ----
BUILD[6] = () => {
  const b = place(6, "filter-bar-column-picker", W_BOARD, 1300);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — The Ctrl+F filter popover (min notional · side · aggregated vs raw), the chips row with removable chips and the Big only preset, the mode chip + CMP-227, CMP-056 open with availability by encoding and the Alt+↑/↓ reorder path, the view-as read-only frame (T2; the notice in its slot under the header) and the Viewer inset (S23, the permission leg); where tape.filter_changed fires (§6)", SRC);
  stamp(b, X, y, "PROPOSED · BQ-3 RULED · T2 per §11.4"); mkText(b, LEGEND, X + 300, y + 5, W - 300, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  // the popover
  const popW = 420, popX = X, popY = y + 70;
  const pl = mkText(b, "the filter popover (D15) — Ctrl+F or the Filter button; initial focus the min-notional field; Enter applies; Esc clears the input first, then closes; focus returns to the button; the Reconstructed rows toggle is T2 while viewing as (the same setting as the strip's Rows switch)", X, y, popW, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "pop-label" });
  mkRect(b, popX, popY, popW, 230, "overlay", { stroke: "borderStrong", radius: 8, role: "wire", name: "filter-popover" });
  mkText(b, "Filter prints", popX + 16, popY + 12, 200, { size: 13, weight: 700, name: "pop-title", h: 18 });
  mkText(b, NB("Min notional"), popX + 16, popY + 44, 120, { size: 11, color: C.text2, tok: TOK.text2, name: "field-label", h: 15 });
  mkRect(b, popX + 140, popY + 40, 160, 24, "canvas", { stroke: "text3", role: "wire", name: "field" }); mkText(b, NB("10 000"), popX + 148, popY + 44, 100, { size: 11, mono: true, name: "field-value", h: 15 }); mkText(b, "USDT", popX + 260, popY + 44, 40, { size: 11, color: C.text3, tok: TOK.text3, name: "unit", h: 15 });
  mkText(b, "Side", popX + 16, popY + 80, 120, { size: 11, color: C.text2, tok: TOK.text2, name: "field-label", h: 15 });
  let rx = popX + 140; ["◉ Any", "○ Buy", "○ Sell"].forEach((r) => { rx += pill(b, rx, popY + 76, r, { h: 22, size: 11, radius: 4, fill: "canvas", name: "radio" }) + 8; });
  mkText(b, NB("Reconstructed rows"), popX + 16, popY + 116, 140, { size: 11, color: C.text2, tok: TOK.text2, name: "field-label", h: 15 });
  pill(b, popX + 160, popY + 112, "on · 250 ms / 1 tick", { h: 22, size: 11, radius: 11, fill: "selected", stroke: "borderStrong", name: "toggle" });
  mkText(b, ("the one filter that re-subscribes (E22-S04); the other two are display filters over the buffered store"), popX + 16, popY + 144, popW - 32, { size: 11, color: C.text3, tok: TOK.text3, name: "note" });
  pill(b, popX + popW - 170, popY + 190, "Apply", { h: 24, size: 11, weight: 700, radius: 4, fill: "selected", stroke: "borderStrong", name: "apply" }); pill(b, popX + popW - 90, popY + 190, "Cancel", { h: 24, size: 11, radius: 4, weight: 600, stroke: "borderStrong", name: "cancel" }); // r7: CMP-001 buttons
  // the chips row + list
  const px = X + popW + 40, pw = 520;
  mkText(b, "the chips row (D16): CMP-055 role=group Active filters; removable chips with a labelled remove button (Delete / Backspace removes); Big only is a pressed toggle, not removable; the mode chip + (estimated) belongs to the Rows control; +41 filtered shows while a filter is on", px, y, pw, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "chips-label" });
  const pch = panelChrome(b, px, popY + 20, pw, { chips: [{ label: "Big only", fill: "selected", stroke: "borderStrong" }, { label: "Reconstructed 250 ms / 1 tick" }, { label: "(estimated)", fill: "hover", stroke: "borderStrong" }, { label: "≥ 10 000 USDT ×" }, { label: "Sell only ×" }], readout: "2 010 /s (1 s) · 33 /frame · +41 filtered" });
  const tfl = tapeBlock(b, px, pch.logY, pw, tapeRows(8, 13).map((r) => Object.assign({}, r, { side: "sell", tier: Math.max(1, r.tier) })), Object.assign({ density: "compact" }, elide(8, 0, (pch.chipRows - 1) * NUM.slotChips))); // r8 (QA C): computed from the frame's slots — the ≤60-row window holds the filtered rows, so the 604 px log less its second chips row (r7 typed 4)
  pill(b, px + 8, pch.logY + tfl.h + 8, "tape.filter_changed {kind: size | side | aggregation, value} fires on apply and on remove", { h: 20, size: 11, mono: true, fill: "hover", stroke: "borderStrong", name: "event-callout" });
  // the column picker menu
  const mx = X + popW + 40 + pw + 40, mw = W - (popW + 40 + pw + 40);
  mkText(b, "CMP-056 open (D17): menuitemcheckbox items with an availability line; an item the encoding cannot fill is not offered — absent, never dimmed (kind 3 today: 7 items, the footer counts the two); Alt+↑/↓ reorder only while the menu is open; the Columns… opener is T1 in every session; while viewing as or without workspaces:write every item, Move up / Move down and Reset columns are T2", mx, y, mw, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "picker-label" });
  const items = [["☑ Time", "on the binary feed"], ["☑ Price", "on the binary feed"], ["☑ Size", "on the binary feed"], ["☑ Notional", "on the binary feed"], ["☑ Side", "on the binary feed"], ["☐ Block", "on the binary feed · a tag by default"], ["☐ Σ delta", "client sum"]];
  mkRect(b, mx, popY + 20, 360, 24 + items.length * 34 + 30, "overlay", { stroke: "borderStrong", radius: 8, role: "wire", name: "column-menu" });
  mkText(b, "Columns", mx + 12, popY + 28, 200, { size: 12, weight: 700, name: "menu-title", h: 16 });
  items.forEach((it, i) => { const iy = popY + 50 + i * 34; mkText(b, it[0], mx + 12, iy, 200, { size: 11, weight: 500, name: "menu-item", h: 15 }); mkText(b, NB(it[1]), mx + 12, iy + 15, 330, { size: 10, color: C.text3, tok: TOK.text3, name: "menu-item-availability", h: 14 }); });
  mkText(b, NB("2 columns need the structured feed"), mx + 12, popY + 50 + items.length * 34, 330, { size: 11, color: C.text3, tok: TOK.text3, name: "menu-footer", h: 15 });
  let kx = mx + 380; kx += kbd(b, kx, popY + 28, "Alt+↑ / Alt+↓") + 6; const rn = mkText(b, ("reorder the focused item (menu open only); Move up / Move down in each item's submenu as the non-chord path; drag is additive"), kx, popY + 28, mw - 380 - (kx - mx - 380) - 8, { size: 11, color: C.text2, tok: TOK.text2, name: "reorder-note" });
  // the two columns the binary feed cannot fill are an absence on kind 3; on the structured feed they are offered (T1) — drawn as their own small list
  const sfx = mx + 380, sfy = Math.max(popY + 96, popY + 28 + (rn ? rn.h : 0) + 8); // r8 (QA A): under the reorder note's wrapped height (r7's NBSP-joined note ran under the structured-feed list)
  mkText(b, "on the structured feed (E22-T02; D17): the two columns are offered, T1 — never drawn dimmed on kind 3", sfx, sfy, mw - 380, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "structured-label" });
  mkRect(b, sfx, sfy + 36, 300, 24 + 2 * 34 + 6, "overlay", { stroke: "borderStrong", radius: 8, role: "wire", name: "column-menu-structured" });
  mkText(b, "Columns", sfx + 12, sfy + 44, 200, { size: 12, weight: 700, name: "menu-title", h: 16 });
  [["☐ Cluster ×N", "structured feed only"], ["☐ Tick direction", "structured feed only"]].forEach((it, i) => { const iy = sfy + 66 + i * 34; mkText(b, it[0], sfx + 12, iy, 200, { size: 11, weight: 500, name: "menu-item", h: 15 }); mkText(b, NB(it[1]), sfx + 12, iy + 15, 270, { size: 10, color: C.text3, tok: TOK.text3, name: "menu-item-availability", h: 14 }); });
  y = popY + 20 + Math.max(230, 24 + items.length * 34 + 30, pch.logY - popY + tfl.h + 40) + GAPY;
  // the view-as read-only frame (S21, T2) — the notice in its own slot right under the header (spec §2); the openers T1
  const vl = mkText(b, ("S21 · view-as read-only (the view-as leg comes first, E09-D09 §2.1 step 3): one notice, many pointers — the notice in its slot directly under the header; every write is T2: the threshold mode and value, Apply, the picker's items, Move up / Move down and Reset columns, the scale and Rows switches, the Reconstructed rows toggle, the density pair; the Threshold… and Columns… openers, pause, the display filters, Big only, Clear filter, Keep, Jump to live and Load missed prints stay T1; Size tier 2 and the effective readout are status text, never converted"), X, y, W, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "viewas-label" });
  const vy = y + (vl ? vl.h : 36) + 8, vw = 640; // r8: under the label's wrapped height
  const t2pill = (tx, ty, s) => pill(b, tx, ty, s, { h: 20, size: 11, radius: 4, fill: "raised", stroke: "border", textColor: C.text3, textTok: TOK.text3, name: "t2-control" });
  const plainLbl = (tx, ty, s) => { const tw = pillTextW(s, 11, false); mkText(b, NB(s), tx, ty + 3, tw + 4, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "strip-text", h: 15 }); return tw + 12; };
  // the strip with its writes T2 — four rows (r9, QA MAJOR: r8 drew the locked Bubbles control after the derived text and it ran 19 px past the frame):
  // row A = the plain label, the mode and the value as two locked controls, the effective readout as a status pill (never T2); row B = Size tier 2
  // as derived text (never a pill, never a lock); row C = the locked scale control on its own row; row D = the locked Rows control + (estimated)
  const T2_STRIP_H = NUM.slotStrip + 24; // one row pitch more than the expanded strip
  const t2Strip = (sx, sy) => {
    mkRect(b, sx, sy, vw, T2_STRIP_H, "raised", { stroke: "border", role: "wire", name: "control-strip-t2" });
    let ax = sx + 10; ax += plainLbl(ax, sy + 4, "Threshold"); ax += t2pill(ax, sy + 4, "🔒 notional ▾") + 8; ax += t2pill(ax, sy + 4, "🔒 30 000 USDT") + 8; // r7: the frame is in S18 (its capped chip and Apply 34 723 say so), so the user's value is 30 000 and the exact readout 34.7k · capped (D20)
    ax += pill(b, ax, sy + 4, "eff. 34.7k USDT", { h: 20, size: 11, radius: 4, fill: "canvas", stroke: "border", mono: true, name: "strip-control:eff. 34.7k USDT" }) + 8;
    pill(b, ax, sy + 4, "capped", { h: 20, size: 11, fill: "hover", stroke: "borderStrong", name: "strip-control:capped" });
    [["size tier (of a print) 2 = 4× · 1M USDT — derived, read-only"], ["🔒 Bubbles · scale area-linear ▾"], ["🔒 Rows · reconstructed 250 ms / 1 tick ▾", "(estimated)"]].forEach((rowItems, ri) => { let tx = sx + 10; rowItems.forEach((s) => { if (s.startsWith("size tier")) { const tw = pillTextW(s, 11, false); mkText(b, NB(s), tx, sy + 7 + (ri + 1) * 24, tw + 4, { size: 11, color: C.text2, tok: TOK.text2, name: "derived-text", h: 15 }); tx += tw + 12; } else if (s.startsWith("🔒")) tx += t2pill(tx, sy + 4 + (ri + 1) * 24, s) + 8; else tx += pill(b, tx, sy + 4 + (ri + 1) * 24, s, { h: 20, size: 11, fill: "hover", stroke: "borderStrong", name: "strip-control:" + s }) + 8; }); });
    return T2_STRIP_H;
  };
  const moreMenu = (sx, sy, head, items) => { // the panel menu excerpt: an optional notice line first (S23), Reset columns and the density pair T2, the summary and Open settings T1
    const n = items.length + (head ? 1 : 0);
    mkRect(b, sx, sy, 320, 24 + n * 22 + 8, "overlay", { stroke: "borderStrong", radius: 8, role: "wire", name: "panel-menu-t2" }); mkText(b, "More (Shift+F10)", sx + 12, sy + 6, 200, { size: 12, weight: 700, name: "menu-title", h: 16 });
    let iy = sy + 30;
    if (head) { mkText(b, NB(head), sx + 12, iy, 296, { size: 11, color: C.text2, tok: TOK.text2, name: "menu-notice", h: 15 }); iy += 22; }
    items.forEach((it) => { const t2 = LOCK_RE.test(it); (t2 ? lockText : mkText)(b, NB(it), sx + 12, iy, 296, { size: 11, color: t2 ? C.text3 : C.text, tok: t2 ? TOK.text3 : TOK.text, name: "menu-item", h: 15 }); iy += 22; }); // r8: the drawn lock
    return 24 + n * 22 + 8;
  };
  const pickerT2 = (sx, sy, head, caption) => { // the CMP-056 excerpt with every item T2: the lock leads the label, the availability line unchanged, Move up / Move down locked too
    const its = [["🔒 ☑ Time", "on the binary feed"], ["🔒 ☑ Price", "on the binary feed"], ["🔒 ☑ Size", "on the binary feed"], ["🔒 ☑ Notional", "on the binary feed"], ["🔒 ☑ Side", "on the binary feed"]];
    const n = its.length + (head ? 1 : 0);
    mkRect(b, sx, sy, 360, 24 + n * 34 + 8, "overlay", { stroke: "borderStrong", radius: 8, role: "wire", name: "column-menu-t2" }); mkText(b, "Columns", sx + 12, sy + 8, 200, { size: 12, weight: 700, name: "menu-title", h: 16 });
    let iy = sy + 30;
    if (head) { mkText(b, NB(head), sx + 12, iy, 336, { size: 11, color: C.text2, tok: TOK.text2, name: "menu-notice", h: 15 }); iy += 34; }
    its.forEach((it) => { lockText(b, NB(it[0]), sx + 12, iy, 200, { size: 11, weight: 500, color: C.text3, tok: TOK.text3, name: "menu-item", h: 15 }); mkText(b, NB(it[1]), sx + 12, iy + 15, 330, { size: 10, color: C.text3, tok: TOK.text3, name: "menu-item-availability", h: 14 }); iy += 34; });
    const subY = sy + 24 + n * 34 + 8 + 10;
    mkRect(b, sx, subY, 160, 24 + 2 * 22 + 4, "overlay", { stroke: "borderStrong", radius: 8, role: "wire", name: "column-submenu-t2" });
    ["🔒 Move up", "🔒 Move down"].forEach((it, i) => lockText(b, NB(it), sx + 12, subY + 8 + i * 22, 136, { size: 11, color: C.text3, tok: TOK.text3, name: "menu-item", h: 15 }));
    const cap = mkText(b, caption, sx, subY + 24 + 2 * 22 + 4 + 8, 360, { size: 11, color: C.text3, tok: TOK.text3, name: "picker-caption" });
    return subY + 24 + 2 * 22 + 4 + 8 + (cap ? cap.h : 34) - sy; // r8 (QA A): the caption's wrapped height (r7: 34 typed under an NBSP-joined caption that ran under the popover excerpt)
  };
  const pva = panelChrome(b, X, vy, vw, { pauseT2: false, notice: "🔒 Read-only while viewing as {user}.", status: [{ label: "capped", fill: "hover", stroke: "borderStrong" }], actions: ["🔒 Apply 34 723", "Keep 30 000"], chips: [{ label: "Big only" }, { label: "Reconstructed 250 ms / 1 tick" }, { label: "(estimated)", fill: "hover", stroke: "borderStrong" }] });
  const ws1 = warningStripInPlace(b, X, pva.logY, vw); // r7: S18 in place (the sentence under the status row, as board 07), the rows' tiers at the effective 34 723
  const tva = tapeBlock(b, X, pva.logY + ws1, vw, tapeRows(6, 17, NUM.suggested), Object.assign({ density: "compact" }, elide(6, 0, NUM.noticePx[0] + ws1)));
  const stripY = pva.logY + ws1 + tva.h;
  const stripH = t2Strip(X, stripY);
  const menuY = stripY + stripH + 12; // r9: the four-row T2 strip
  const menuH = moreMenu(X, menuY, null, ["Read tape summary", "🔒 Reset columns", "🔒 ◉ Compact", "🔒 ○ Comfortable", "Open settings"]);
  // the CMP-056 and popover excerpts beside the frame: every item, Move up / Move down and the Reconstructed rows toggle T2 — every aria-describedby → the panel notice
  const exX = X + vw + 40;
  const pkH = pickerT2(exX, vy, null, "every item's aria-describedby → the panel notice; the density pair in the More menu is two menuitemradio items");
  const popY2 = vy + pkH + 12;
  mkRect(b, exX, popY2, 360, 56, "overlay", { stroke: "borderStrong", radius: 8, role: "wire", name: "filter-popover-t2" });
  mkText(b, NB("Reconstructed rows"), exX + 12, popY2 + 20, 140, { size: 11, color: C.text2, tok: TOK.text2, name: "field-label", h: 15 });
  t2pill(exX + 160, popY2 + 16, "🔒 on · 250 ms / 1 tick");
  const pc = mkText(b, ("the popover's toggle (the same cluster_window_ms setting as the Rows switch) — T2; min notional and side stay T1"), exX, popY2 + 64, 360, { size: 11, color: C.text3, tok: TOK.text3, name: "popover-caption" });
  const cva = card(b, exX + 400, vy, W - (exX + 400 - X), { kicker: "T2 ANATOMY (E09-D09 §2.2, §3.1, §9.1, §9.3; CMP-079 RbacGate, CMP-019 Icon lock)", value: "full label in the middle grey · lock glyph · reason · aria-disabled", lines: ["the control keeps its native role and its full label; aria-disabled=\"true\", never the disabled attribute — it stays in the Tab order, a menu item stays arrow-reachable; an arrow on a T2 radio changes nothing", "a CMP-019 lock glyph (decorative=false, name Not available) leads the label; the reason sits in the DOM at mount, linked by aria-describedby — here one panel notice in its own slot under the header, many pointers", "hi-fi (E22-D03): label color.text.tertiary, reason color.text.secondary, fill color.surface.raised with a color.border.default hairline; never color.text.disabled, never opacity.disabled — the enabled fill goes (Apply beside the T1 Keep)", "Enter / Space / a bound key on a T2 control changes nothing and re-shows the reason once, politely; a T2 press emits nothing", "the writes: the threshold mode and value, Apply 34 723, every column item with Move up / Move down and Reset columns, the scale and Rows switches, the Reconstructed rows toggle, the density pair; Size tier 2 and the effective readout are status text and are never converted; the Threshold… and Columns… openers, Keep, Jump to live and Load missed prints are reads (T1)", "the reason is a key, never data: rbac.view_as Read-only while viewing as {user}.; the key of the pause button in Disconnected, feed.disconnected_pause, is PROPOSED (E17-D01 §7 owner) — board 05", "form validity is not T2: the threshold field's own range message keeps aria-invalid and no lock glyph"], foot: "live validation and the status chips show the target user's state unchanged — reads answer as the target" });
  y = Math.max(menuY + menuH, popY2 + 64 + (pc ? pc.h : 36), vy + cva.h) + GAPY; // r8: the caption's wrapped height
  // -- S23 · the Viewer's permission leg (E09-D09 §2.1 step 3 (b); 22 x-permissions): the same writes T2 with rbac.permission, one notice per surface
  const vl2 = mkText(b, ("S23 · Viewer — the permission leg (E09-D09 §2.1 step 3 (b)): settings:write → Your role can't change settings. · workspaces:write → Your role can't save workspaces. — one notice per surface in E09-D09 §10's notice.panel_read_only form; the view-as leg comes first when both apply; the same T1 set as S21"), X, y, W, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "viewer-label" });
  const vy2 = y + (vl2 ? vl2.h : 36) + 8; // r8: under the label's wrapped height
  const pvr = panelChrome(b, X, vy2, vw, { pauseT2: false, notice: "🔒 Read-only — your role can't change settings.", status: [{ label: "capped", fill: "hover", stroke: "borderStrong" }], actions: ["🔒 Apply 34 723", "Keep 30 000"], chips: [{ label: "Big only" }, { label: "Reconstructed 250 ms / 1 tick" }, { label: "(estimated)", fill: "hover", stroke: "borderStrong" }] });
  const ws2 = warningStripInPlace(b, X, pvr.logY, vw);
  const tvr = tapeBlock(b, X, pvr.logY + ws2, vw, tapeRows(6, 19, NUM.suggested), Object.assign({ density: "compact" }, elide(6, 0, NUM.noticePx[0] + ws2)));
  const stripY2 = pvr.logY + ws2 + tvr.h;
  const stripH2 = t2Strip(X, stripY2);
  const menuY2 = stripY2 + stripH2 + 12; // r9: the four-row T2 strip
  const menuH2 = moreMenu(X, menuY2, "Read-only — your role can't save workspaces.", ["Read tape summary", "🔒 Reset columns", "🔒 ◉ Compact", "🔒 ○ Comfortable", "Open settings"]);
  const pkH2 = pickerT2(exX, vy2, "Read-only — your role can't save workspaces.", "the menu's first line is the workspaces notice; every item's aria-describedby → that line; the strip's writes, Apply and the popover toggle → the panel notice (settings)");
  const cvr = card(b, exX + 400, vy2, W - (exX + 400 - X), { kicker: "S23 · THE PERMISSION LEG (D28 (4); E09-D09 §2.1 step 3 (b), §3.1, §3.2, §10; 22 x-permissions)", value: "Your role can't change settings. · Your role can't save workspaces.", lines: ["a Viewer holds settings:read and workspaces:read only; a Manager holds settings:write and workspaces:write, so the chooser picks rbac.permission, never rbac.owner_only", "settings:write — the threshold mode and value, Apply, the scale and Rows switches and the popover's Reconstructed rows toggle persist through updateSettings (PATCH /settings) / setDetectorConfig (PUT /detectors/config)", "workspaces:write — every column item with its Move up / Move down, Reset columns and the density pair persist in the layout (updateWorkspace / updateLayout; D15 / D17)", "one notice per surface (notice.panel_read_only): Read-only — your role can't change settings. in the notice slot under the header; Read-only — your role can't save workspaces. as the first line of the CMP-056 menu and of the More menu", "CMP-079 RbacGate Denied(Permission) wraps every leg; a CMP-019 lock glyph leads every label; the openers, pause, the display filters, Big only, Clear filter, Keep, Jump to live and Load missed prints stay T1 (reads)", "QA: sign in as the Viewer fixture; assert aria-disabled, the lock glyph and the two notices; pause, the display filters and Big only still work"], foot: "no rbac.owner_only / rbac.account* / rbac.env leg arises: scope: self operations, public market data, no order affordance" });
  finish(b, Math.max(menuY2 + menuH2, vy2 + pkH2, vy2 + cvr.h));
};

// ---- Board 7: the control strip in its three modes, Size tier 2 read-only, the class seeds, the strip in place (§7) ----------------
BUILD[7] = () => {
  const b = place(7, "threshold-strip-classes", W_BOARD, 1500);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — The control strip (BQ-4 RULED: the memo's, never the ticket's) in notional · percentile (eff. 220k USDT + (estimated), uncapped) · absolute_size modes; Size tier 2 = 4× · 1M USDT read-only (G8); the class seeds (PROPOSED placeholders until T6); the over-threshold warning strip in place (S18, Q7); E22-S02 owns the control (§7)", SRC);
  stamp(b, X, y, "RULED BQ-4 · PROPOSED Q6 Q7 Q15"); mkText(b, LEGEND, X + 280, y + 5, W - 280, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  const modes = [
    ["notional (shipped default 250 000 USDT)", { value: "250 000 USDT", eff: "eff. 250k USDT" }, "the readout is exact; no badge"],
    ["percentile (p99 / 1 h; the P² estimate)", { mode: "percentile ▾", value: "99 %", eff: "eff. 220k USDT", badges: ["(estimated)"] }, "the effective readout carries CMP-227 (estimated) → SCR-058 big_trade; the dense tape's p99 / 1 h is 220 443 USDT (tool); at 1.0 % flagged the cap (eligible above p80 only) does not engage, so no capped; it refreshes at most every 5 s of print time"],
    ["absolute_size (base quantity; never a default)", { mode: "absolute_size ▾", value: "4.000 BTC", eff: "eff. 4.000 BTC" }, "the unit follows the mode"],
  ];
  modes.forEach((m, i) => {
    const sx = X, sy = y + i * 130;
    mkText(b, NB(m[0]), sx, sy, 600, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "mode-label", h: 15 });
    controlStrip(b, sx, sy + 20, 760, m[1]);
    mkText(b, m[2], sx + 780, sy + 24, W - 780, { size: 11, color: C.text3, tok: TOK.text3, name: "mode-note" });
  });
  y += 3 * 130 + 10;
  controlStrip(b, X, y, 760, { collapsed: true }); mkText(b, NB("collapsed: one 24 px summary line (the disclosure) — one line at the 332 px minimum"), X + 780, y + 4, 600, { size: 11, color: C.text3, tok: TOK.text3, name: "collapsed-note", h: 15 });
  y += NUM.slotStripCollapsed + GAPY;
  // S18 in place (Q7): notional mode at the user's 30 000 USDT — the capped chip in the status row, Apply / Keep as the row's buttons, the F19 sentence as a CMP-028-class inline strip under it
  mkText(b, NB("S18 · the over-threshold warning strip in place (memo F19; Q7): the capped chip and Apply / Keep in the status row (Tab stop 6), the sentence under it; one polite announcement per episode"), X, y, W, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "s18-label", h: 15 });
  const p18 = panelChrome(b, X, y + 20, 760, { status: [{ label: "capped", fill: "hover", stroke: "borderStrong" }], actions: ["Apply 34 723", "Keep 30 000"], chips: [{ label: "Big only" }] });
  const ws18 = warningStripInPlace(b, X, p18.logY, 760);
  const t18 = tapeBlock(b, X, p18.logY + ws18, 760, tapeRows(5, 41, NUM.suggested), Object.assign({ density: "compact" }, elide(5, 0, ws18))); // r7: the tiers from the frame's effective threshold 34 723 (r6: 250 000), the count from its slots
  mkText(b, ("the strip is advice, not an error: Apply makes 34 723 the user's value (a threshold write — T2 while viewing as), Keep leaves the user's value and the cap keeps following the window; 23.5 % is the tool's number on the synthetic dense tape"), X + 780, y + 24, W - 780, { size: 11, color: C.text3, tok: TOK.text3, name: "s18-note" });
  y += 20 + (p18.logY - (y + 20)) + 64 + t18.h + GAPY;
  const t = tableBlock(b, X, y, [320, 260, 520, 240, 420], ["Symbol class (PROPOSED)", "Mode until seeded", "Big threshold (size tier 1 — a trade-size threshold)", "Size tier 2 (client-side 4× big, G8)", "Changes the shipped BigTradeConfig?"], [
    ["Majors — BTCUSDT, ETHUSDT", "notional", "250 000 USDT (= the shipped value, quoted by the tool; US-BIG-002 sc. 1)", "1 000 000 USDT", "no"],
    ["Mid-caps — listed > 30 d, not majors", "percentile p99 / 1 h → seeded notional", "the p99 / 1 h estimate rounded to a 1-2-5 step; 50 000 USDT fallback (heuristic)", "4× big (200 000 at the fallback)", "yes: one 250 000 would flag nothing for hours on a mid-cap tape"],
    ["New listings — < 24 h of prints", "percentile p99 over the available window (≥ 20 samples), re-seeded hourly", "none until seeded (the worked newlist seed 1 732 → 2 000 USDT is synthetic, shape only)", "4× big (8 000 at the worked seed)", "yes: no absolute value is defensible before a day of prints"],
    ["Clustering (rows and bubbles)", "—", "250 ms / 1 tick on the one trades.{symbol} subscription the tape and the bubbles share; the (estimated) badge is panel-level, visible iff cluster_window_ms > 0", "—", "yes: the engine default is 0 ms / 0 ticks (C9); the engine default stays (the shipped 0 ms / 0 ticks)"],
  ], { stk: TICKET + ":b7-table" });
  y += t.h + GAPY;
  const c = card(b, X, y, W, { kicker: "WHAT THE STRIP NEVER HAS (BQ-4; memo C5, C12; D02-C1 for the 14 owner)", value: "one threshold · a derived tier 2 · area-linear with log as the switch · no min, no whale field", lines: ["the ticket's scale [log|linear] min [10k] whale [100k] strip is superseded: the bubble floor is the class's big threshold, the cap its tier-2 threshold (4×), linear is never a default — the two strips are never drawn together (rider (b))", "the mode select carries the engine's vocabulary absolute_size | notional | percentile (bigtrade_models.py Mode) — the two 22 vocabularies are C3 (XG-DETECTORCONFIG)", "a threshold change is E22-S02's bigtrade.* per-symbol setting (G4, XG-SETTINGS) and fires no tape.filter_changed", "while viewing as, the strip's writes are T2 (board 06) — Size tier 2 is derived text and never converted; the value field's own range message is form validity, not T2", "size tier (of a print) is said at first use on every board (BQ-5); Q15 — size tier or size band — stays the owner's"], foot: "E22-S02 owns the control; E22-T02 the effective-threshold echo (G1)" });
  finish(b, y + c.h);
};

// ---- Board 8: the bubble overlay on the SCR-030 chassis at 1280×800 (§8) --------------------------------------------------------
function drawChartSnippet(parent, x, y, w, h, o) { // a price pane with bars, the legend block, the status row and the overlay marks
  o = o || {};
  mkRect(parent, x, y, w, h, "canvas", { stroke: "border", role: "wire", name: "chart-pane" });
  mkRect(parent, x, y, w, 24, "raised", { stroke: "border", role: "wire", name: "chart-status-row" });
  let cx = x + 8; [["DEMO", "hover"], [o.stale ? "Stale 12s · last 14:02:11" : "Live", "canvas"]].forEach((c) => { cx += pill(parent, cx, y + 2, c[0], { h: 20, size: 11, fill: c[1], name: "chart-chip" }) + 6; });
  mkText(parent, NB("mark 64,012.5  last 64,011.0  spread 0.5"), cx + 8, y + 5, 300, { size: 11, mono: true, color: C.text2, tok: TOK.text2, name: "chart-readout", h: 15 });
  // the legend block: pane label row + the Big trades row (CMP-199)
  mkText(parent, NB("▎ Price ▾ ⋯   ● BTCUSDT 1m  64,011.0"), x + 12, y + 32, 400, { size: 11, weight: 600, name: "legend-pane-row", h: 15 });
  const legend = o.legend || "Big trades · area-linear · 250k → 3 px · 1M → 24 px · >1M labelled";
  mkText(parent, NB("◉ " + legend + (o.clustering ? "  " : "")), x + 12, y + 52, 560, { size: 11, color: C.text2, tok: TOK.text2, name: "legend-row", h: 15 });
  if (o.clustering) pill(parent, x + 12 + pillTextW("◉ " + legend, 11) + 8, y + 50, "(estimated)", { h: 18, size: 10, fill: "hover", stroke: "borderStrong", name: "legend-estimated" });
  mkText(parent, NB("[eye] Big trades visible"), x + w - 170, y + 52, 160, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-eye", h: 15 });
  // bars: 48 bars at 12 px/bar
  const barW = NUM.barPx, n = Math.floor((w - 80) / barW), base = y + h - 60;
  let p = 0.5;
  for (let i = 0; i < n; i++) { p += (((i * 7919) % 13) - 6) * 0.04; const bh = 18 + ((i * 31) % 40); const by = base - 120 - p * 60 - bh / 2; mkRect(parent, x + 40 + i * barW + 3, by, barW - 6, bh, "borderStrong", { role: "wire", name: "bar" }); }
  mkRect(parent, x, y + h - 24, w, 24, "raised", { stroke: "border", role: "wire", name: "time-strip" });
  mkText(parent, NB("13:58 · 14:00 · 14:02 · 14:04   [ auto | fit | › ]"), x + 40, y + h - 19, w - 60, { size: 11, mono: true, color: C.text3, tok: TOK.text3, name: "time-labels", h: 15 });
  if (o.badge) { pill(parent, x + 12, y + h - 52, o.badge, { h: 20, size: 11, fill: "raised", stroke: "borderStrong", name: "corner-badge" }); }
  return { base, barW, left: x + 40 };
}
BUILD[8] = () => {
  const b = place(8, "bubble-overlay-scr-030", W_BOARD, 1300);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — The bubble overlay on the SCR-030 chassis (E11-D02 §2): buy discs / sell squares of equal area at 1× / 1.5× / 2× / 3× / 4× the threshold along the bars, the ▲ / ▼ inside from r ≥ 10 px, the above-cap label and the cap-outline fallback, a cluster bubble ×7, the two age steps, the legend row, the tooltip, click → crosshair (§8)", SRC);
  stamp(b, X, y, "PROPOSED · Q5 Q11 Q14 drawn · BQ-6 RULED"); mkText(b, LEGEND, X + 320, y + 5, W - 320, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  const shell = shellChrome(b, X, y, 1280, 800);
  const chartW = 1280 - NUM.panelW1280 - 16;
  const snip = drawChartSnippet(b, X + 8, shell.top + 8, chartW - 8, shell.panelH - 16, { clustering: true });
  // marks along the bars: 1× … 4× (buy discs / sell squares alternating), the glyph inside from r ≥ 10, aged copies lighter, the above-cap pair, the cluster
  const marks = [[6, 1, "buy", "fresh"], [12, 1.5, "sell", "fresh"], [18, 2, "buy", "aged"], [26, 3, "sell", "fresh"], [34, 4, "buy", "fresh"], [42, 4, "sell", "aged"]];
  marks.forEach((m) => {
    const cx = snip.left + m[0] * snip.barW + snip.barW / 2, cy = snip.base - 150 - (m[0] % 5) * 48, r = NUM.sqrt[NUM.multiples.indexOf(m[1])], aged = m[3] === "aged"; // r8: 48 px per step — a note under mark k (r_k + 20 px) must clear the mark one step down at bar k − 6 (r_{k−1}): 14.1 + 20 + 10.2 = 44.3 for the 2× / 1.5× pair, so 48 (r6: 24 — the 2× aged note's 174 px line, drawn in a 100 px box, ran across the 1.5× square; r5: 18)
    if (m[2] === "buy") mkDisc(b, cx, cy, r, "text", { opacity: aged ? 0.5 : 1, name: "bubble-buy" }); else mkSquare(b, cx, cy, r, "text", { opacity: aged ? 0.5 : 1, name: "bubble-sell" });
    if (r >= NUM.glyphR) mkText(b, m[2] === "buy" ? "▲" : "▼", cx - 8, cy - 8, 16, { size: 10, align: "center", color: C.canvas, tok: TOK.canvas, name: "bubble-glyph", h: 14 });
    mkText(b, NB(m[1] + "× · " + fmt(NUM.notionals[NUM.multiples.indexOf(m[1])]) + " · r " + r + (aged ? " · aged" : "")), cx - 90, cy + r + 6, 180, { size: 10, align: "center", mono: true, color: C.text3, tok: TOK.text3, name: "bubble-note", h: 14, halo: true }); // r8: a 180 px box (r7: 100 — every note overflowed it, KNOWN_WRAPS) and a 1 px canvas halo over the bars (QA Minor)
  });
  // above the cap: the label plate; the cap-outline fallback; the cluster ×7
  const capX = snip.left + 50 * snip.barW, capY = snip.base - 300;
  mkDisc(b, capX, capY, NUM.rMax, "text", { name: "bubble-capped" }); mkRect(b, capX + 30, capY - 10, 44, 20, "raised", { stroke: "border", radius: 4, role: "wire", name: "cap-plate" }); mkText(b, "1.2M", capX + 30, capY - 8, 44, { size: 11, mono: true, align: "center", name: "cap-notional", h: 15 });
  const outX = snip.left + 58 * snip.barW, outY = snip.base - 230;
  mkSquare(b, outX, outY, NUM.rMax, "text", { name: "bubble-capped-sell" }); mkSquare(b, outX, outY, NUM.rMax, "text", { outline: true, grow: 2 * (NUM.capOutlineOffsetPx + 1), name: "cap-outline" }); mkText(b, "▼", outX - 8, outY - 8, 16, { size: 10, align: "center", color: C.canvas, tok: TOK.canvas, name: "bubble-glyph", h: 14 });
  mkText(b, "cap outline at r + 3 = 27 px, 2 px of canvas — where labels are hidden", outX - 90, outY + NUM.rMax + 12, 200, { size: 10, align: "center", color: C.text3, tok: TOK.text3, name: "outline-note" });
  const clX = snip.left + 66 * snip.barW, clY = snip.base - 260;
  mkSquare(b, clX, clY, 19.7, "text", { name: "bubble-cluster" }); mkText(b, "▼", clX - 8, clY - 8, 16, { size: 10, align: "center", color: C.canvas, tok: TOK.canvas, name: "bubble-glyph", h: 14 }); const bw7 = pillW("×7", 10, true, { padX: 5 }); pill(b, clX - 18 - 4 - bw7, clY - 26, "×7", { h: 16, size: 10, padX: 5, mono: true, fill: "raised", stroke: "borderStrong", name: "cluster-badge" }); // r8 (QA Minor): top-left of the cluster mark, inside the chart pane (r7: clX + 16 straddled the pane's right border)
  // the tooltip (CMP-197, DOM) near the cluster
  mkRect(b, snip.left + 300, snip.base - 58, 410, 44, "overlay", { stroke: "borderStrong", radius: 6, role: "wire", name: "tooltip" }); // r8: 410 wide (r7: 350 — the first line needed 393 px, KNOWN_WRAPS)
  mkText(b, NB("Cluster ×7 · 1.9M USDT · Sell · 7 prints within 250 ms / 1 tick"), snip.left + 308, snip.base - 54, 396, { size: 11, name: "tooltip-line", h: 15 });
  mkText(b, NB("first print 14:02:11.208 · bar 14:02 · (estimated)"), snip.left + 308, snip.base - 36, 396, { size: 11, color: C.text2, tok: TOK.text2, name: "tooltip-line", h: 15 });
  // the tape panel beside it (crop)
  const px = X + chartW + 8, pch = panelChrome(b, px, shell.top, NUM.panelW1280, { chips: [{ label: "Big only" }, { label: "Reconstructed 250 ms / 1 tick" }, { label: "(estimated)", fill: "hover", stroke: "borderStrong" }] }); // no filter on: the readout has no +N filtered
  const tp8 = tapeBlock(b, px, pch.logY, NUM.panelW1280, tapeRows(tapeRoom(shell.top, pch.logY), 21), { density: "compact", selectedRow: 1 }); // r7: 24 rows under the two-line chips row (board 01)
  controlStrip(b, px, pch.logY + tp8.h, NUM.panelW1280, { collapsed: true });
  pill(b, snip.left, snip.base + 2, "click → crosshair · tape.print_clicked {source: bubble}", { h: 18, size: 10, mono: true, fill: "hover", stroke: "borderStrong", name: "event-callout" });
  const cx2 = X + 1280 + 40, cw2 = W - 1280 - 40;
  const c1 = card(b, cx2, y, cw2, { kicker: "GEOMETRY (D21; memo F14–F16; tool §15)", value: "r = √(9 + 189(k − 1)) px: 3.0 / 10.2 / 14.1 / 19.7 / 24.0", lines: ["area-linear: between the anchors equal notional steps add equal area (594 px² per 250 000 USDT on majors); log 3.0 / 9.1 / 13.5 / 19.6 / 24.0 is the switch; linear 3.0 / 6.5 / 10.0 / 17.0 / 24.0 is never a default", "buy = a filled disc; sell = a filled square of equal area, side r·√π: 5.3 px at the floor, 17.7 at r 10, 42.5 at the cap; the ▲ / ▼ inside from r ≥ 10 px", "above the cap every print renders 24 px alike and carries its notional label (1.2M, 18.9M — engine SDF text, Q14 for E22-D03); where labels are hidden a 2 px cap outline centred 3 px outside the mark marks ≥ cap — an outline on a filled mark, never hollow (hollow is estimated's, E25-D01 §9.5)", "at 12 px/bar a 24 px radius covers 4 bars, so clustering is on for the shared subscription (C9); the cluster mark sits at the vwap and first-print time with the ×7 badge", "alpha by age: static bands (fresh / aged — two steps under reduced motion; greyscale: two lightness steps); appear is a 0 ms flip; BUBBLE_FLASH_MAX_HZ 3 is the cap, 0 is the design"], foot: "the shape floor ≈ r 5 px (side 8.9 px; 1.085×): below it the row, the tooltip and the mirror carry the side — r_min 4–5 px is E22-D03's call" });
  const c2 = card(b, cx2, y + c1.h + 24, cw2, { kicker: "THE LEGEND ROW (BQ-6 RULED: DOM, CMP-199)", value: "Big trades · area-linear · 250k → 3 px · 1M → 24 px · >1M labelled", lines: ["the four facts in words, the class's own numbers; under log the row reads Big trades · log · 250k → 3 px · 1M → 24 px · >1M labelled", "while clustering is on the row gains (estimated) as CMP-227 inline (the marker grade's visible word lives in the pane's legend row, E25-D05 §4.1)", "the eye toggle hides the layer; the tape keeps its tiers"], foot: "the tooltip is CMP-197 (DOM, flip-not-clip, E11-D02 D10); the mirror markers are DOM; the marks, glyphs, labels and badges are GL" });
  finish(b, Math.max(y + 800, y + c1.h + 24 + c2.h));
};

// ---- Board 9: the scale switch and the legend per law; the overlay states; the engine / DOM boundary card; the shape-floor pair ----
BUILD[9] = () => {
  const b = place(9, "bubble-states-scale-switch", W_BOARD, 1300);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — The scale switch (area-linear ▾ / log) and the legend text per law; fresh / aged / capped / clustered / stale (× 0.85 with the chart) / disconnected (frozen) / overlay off / LOD shedding; the engine / DOM boundary card (BQ-6); the shape-floor pair at r 3 and r 5.3 px (§8)", SRC);
  stamp(b, X, y, "PROPOSED · BQ-6 RULED · C13 noted"); mkText(b, LEGEND, X + 300, y + 5, W - 300, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  const s1 = strip(b, X, y, W, "THE SCALE SWITCH AND THE LEGEND TEXT PER LAW (memo F14, F15)", [
    { v: "area-linear ▾", t: "default (RULED BQ-6; Q5 owner / D06 T5)", d: "radii 3.0 / 10.2 / 14.1 / 19.7 / 24.0 at 1× / 1.5× / 2× / 3× / 4×", pill: "Big trades · area-linear · 250k → 3 px · 1M → 24 px · >1M labelled", decision: true },
    { v: "log", t: "the switch", d: "radii 3.0 / 9.1 / 13.5 / 19.6 / 24.0 — the two laws differ by ≤1.1 px as drawn", pill: "Big trades · log · 250k → 3 px · 1M → 24 px · >1M labelled" },
    { v: "linear", t: "in the contract, never a default", d: "radii 3.0 / 6.5 / 10.0 / 17.0 / 24.0 — everything below 2× under 10 px (crowded bottom)", pill: "not offered on the strip" },
  ]);
  y += s1.h + GAPY;
  const s2 = strip(b, X, y, W, "OVERLAY STATES — each carried by text or shape (§8)", [
    { v: "fresh / aged", t: "alpha by age as two static bands", d: "greyscale: two lightness steps; identical under reduced motion", pill: "0 ms appear" },
    { v: "capped", t: "label 1.2M, or the r + 3 px outline", d: "every above-cap print renders 24 px alike (329 of the dense tape's 200 000 prints, 0.16 % — synthetic)", pill: "1.2M", pillMono: true },
    { v: "clustered ×7", t: "the count badge; the legend's (estimated)", d: "the tooltip lists the count, the window, the tolerance and the first-print bar", pills: [{ label: "×7", mono: true }, { label: "(estimated)", fill: "hover", stroke: "borderStrong" }] },
    { v: "stale", t: "the chart's data-ink × 0.85 + its chip", d: "E11-D06 D13; no new bubbles; the tape shows Stale 12s beside it", pill: "Stale 12s", pillFill: "sunken" },
    { v: "disconnected", t: "frozen with the chart", d: "the SCR-152 strip and the scrim are the chart's", pill: "Disconnected — last data 00:12", pillFill: "sunken" },
    { v: "overlay off", t: "the legend row's eye toggle", d: "the tape keeps its tiers; the row stays in the legend with the word hidden in its name", pill: "Big trades hidden" },
    { v: "LOD shedding", t: "clusters, then decimation — a display rung only (C13)", d: "shedding never changes which prints are big; the 26 §3.6 keep ≤ 500 vs VISIBLE_BUBBLES_MAX 5 000 is 26's to reconcile (E22-K01 / S03 / T03)", pill: "Smaller prints hidden at this zoom", decision: true },
  ]);
  y += s2.h + GAPY;
  // the shape-floor pair at r 3 and r 5.3 (E22-D03's r_min call) + the boundary card
  const plateW = 560;
  mkRect(b, X, y, plateW, 170, "raised", { stroke: "border", radius: 8, role: "wire", name: "floor-plate" });
  mkText(b, ("the shape floor (memo F16; E22-D03's r_min call): at r 3 px a 5.3 px square and a 6 px disc read alike; from ≈ r 5 px (1.085×) the shape carries the side"), X + 14, y + 10, plateW - 28, { size: 11, weight: 600, name: "floor-label" });
  [[3, 90], [5.3, 260], [10, 430]].forEach((p) => { const cy = y + 110; mkDisc(b, X + p[1], cy, p[0], "text", { name: "floor-buy" }); mkSquare(b, X + p[1] + 60, cy, p[0], "text", { name: "floor-sell" }); if (p[0] >= NUM.glyphR) { mkText(b, "▲", X + p[1] - 8, cy - 8, 16, { size: 10, align: "center", color: C.canvas, tok: TOK.canvas, name: "bubble-glyph", h: 14 }); mkText(b, "▼", X + p[1] + 52, cy - 8, 16, { size: 10, align: "center", color: C.canvas, tok: TOK.canvas, name: "bubble-glyph", h: 14 }); } mkText(b, NB("r " + p[0] + " px · side " + (p[0] * NUM.sqSideOverR).toFixed(1) + " px"), X + p[1] - 40, cy + 36, 160, { size: 10, mono: true, color: C.text3, tok: TOK.text3, name: "floor-note", h: 14 }); });
  const cb = card(b, X + plateW + 40, y, W - plateW - 40, { kicker: "THE ENGINE / DOM BOUNDARY (BQ-6 RULED; C-2.16; the chart-engine lead's review item → the owner)", value: "GL: marks, glyphs, labels, badges · DOM: legend row, tooltip, mirror · never: a client threshold, a per-frame cluster", lines: ["GL — one instanced SDF-disc call (radius by notional, alpha by age, 26 render table) plus the ▲ / ▼, the cap outline, the above-cap label and the ×N badge as SDF text in the pane batch (26 §3.7)", "the named bench scenario bench/bubbles-sdf-labels — N visible bubbles (≤ 5 000) with M labelled above the cap and the cluster badges on, against 06 §4.3's overlay slice and C-14.2's p95 frame budget — is owed to E22-K01; the layer (E22-S03) does not merge without it (rider (a), D02-G3)", "DOM — the chassis's own slots (E11-D02 §2): the CMP-199 legend row, the CMP-197 tooltip (flip-not-clip), the sparse DOM-mirror markers Big sell, 42,000 USDT, 65,410, 14:32:01", "never — a threshold recompute on the client (memo F13, C4: tiers come from the engine's BigTradeEvent once E22-T02 lands G1), a per-frame cluster (backend-side, US-BIG-004 NFR), or chrome painted over the plot outside the slots"], foot: "nothing here is a new budget value; the readout and the mirror sit inside the ≤1 ms overlay slice of 06 §4.3" });
  finish(b, y + Math.max(170, cb.h));
};

// ---- Board 10: AC 3 — tiers and the bubble pair in greyscale ink beside the memo §3.9 simulated swatches (tool values) -----------
BUILD[10] = () => {
  const b = place(10, "greyscale-cvd-proof", W_BOARD, 1100);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — AC 3 in greyscale: size tier (of a print) 0 / 1 / 2 rows and the bubble pair at r 3 / 5.3 / 10 / 24 px in the boards' own ink, beside the memo §3.9 simulated swatches (normal / greyscale / deuteranopia hexes from the tool — simulated, no image exists) and their ratios; the rule words in color.text.primary as the E22-D03 hand-off (§10)", SRC);
  stamp(b, X, y, "PROPOSED · Q4 drawn · simulated"); mkText(b, LEGEND, X + 260, y + 5, W - 260, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  const mr = memoRows(), tiers = [mr[2], mr[0], mr[1]]; // tier 0 / 1 / 2 — every tier computed from the threshold (D02-C9)
  const tl = mkText(b, "the three size tiers in greyscale — weight 400 / 500 / 700 · glyph none / ● / ◆ · the 2 px edge mark · the band + the tier word in the name", X, y, 540, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "tiers-label" });
  const top10 = y + (tl ? tl.h : 30) + 6;
  const tt = tapeBlock(b, X, top10, 520, tiers, { density: "compact" });
  mkText(b, NB("the bubble pair at r 3 / 5.3 / 10 / 24 px — disc = buy, square of equal area = sell; the ▲ / ▼ from r ≥ 10 px"), X + 580, y, 700, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "pair-label", h: 15 });
  mkRect(b, X + 580, top10, 640, 120, "raised", { stroke: "border", radius: 8, role: "wire", name: "pair-plate" });
  [[3, 60], [5.3, 200], [10, 350], [24, 520]].forEach((p) => { const cy = top10 + 60; mkDisc(b, X + 580 + p[1], cy, p[0], "text", { name: "pair-buy" }); mkSquare(b, X + 580 + p[1] + 70, cy, p[0], "text", { name: "pair-sell" }); if (p[0] >= NUM.glyphR) { mkText(b, "▲", X + 580 + p[1] - 8, cy - 8, 16, { size: 10, align: "center", color: C.canvas, tok: TOK.canvas, name: "bubble-glyph", h: 14 }); mkText(b, "▼", X + 580 + p[1] + 62, cy - 8, 16, { size: 10, align: "center", color: C.canvas, tok: TOK.canvas, name: "bubble-glyph", h: 14 }); } mkText(b, NB("r " + p[0]), X + 580 + p[1] - 20, cy + 32, 120, { size: 10, mono: true, color: C.text3, tok: TOK.text3, name: "pair-note", h: 14 }); });
  y = top10 + Math.max(tt.h, 120) + GAPY;
  // the §3.9 swatches: the only non-neutral fills on these boards — simulated hexes from the tool, labelled
  const swHdr = mkText(b, ("the memo §3.9 simulated swatches — the tool's cvd section (the Rec. 601 weights and the Machado 2009 matrix cvd_sim.py uses); simulated — tool values, no image exists; the only non-neutral fills on these boards"), X, y, 1100, { size: 12, weight: 700, color: C.text3, tok: TOK.text3, name: "swatch-label" });
  let sy = y + (swHdr ? swHdr.h : 16) + 8;
  const swTokens = Object.keys(CVD), renders = ["normal", "greyscale", "deuteranopia"];
  const swW = 110, swH = 30, swGap = 14, labW = 190;
  mkRect(b, X, sy, labW + 3 * (swW + swGap) + 16, 24 + swTokens.length * (swH + 20) + 12, "raised", { stroke: "border", radius: 8, role: "wire", name: "swatch-plate" });
  renders.forEach((rn, j) => mkText(b, rn, X + labW + j * (swW + swGap), sy + 6, swW, { size: 11, weight: 700, align: "center", name: "swatch-head", h: 15 }));
  swTokens.forEach((tk, i) => {
    const ry = sy + 24 + i * (swH + 20);
    mkText(b, tk, X + 10, ry + 8, labW - 14, { size: 11, mono: true, color: C.text2, tok: TOK.text2, name: "swatch-token", h: 15 });
    renders.forEach((rn, j) => { const sx = X + labW + j * (swW + swGap); mkSwatch(b, sx, ry, swW, swH, CVD[tk][rn], { token: tk, rendering: rn }); mkText(b, CVD[tk][rn], sx, ry + swH + 2, swW, { size: 10, mono: true, align: "center", color: C.text2, tok: TOK.text2, name: "swatch-hex", h: 14 }); });
  });
  const plateH = 24 + swTokens.length * (swH + 20) + 12;
  const c3 = card(b, X + labW + 3 * (swW + swGap) + 56, sy, W - (labW + 3 * (swW + swGap) + 56), { kicker: "WHAT THE SIMULATED SWATCHES SHOW (memo §3.9; tool: every hex and ratio reproduced)", value: "the hue never carries the side alone", lines: ["the two hues separate by 1.59 / 1.23 / 1.46 (normal / greyscale / deuteranopia); the fills by 1.18 / 1.08 / 1.13 — so the ▲ / ▼ glyph, the word, the weight and, on bubbles, the disc / square carry the side", "the glyph and the accent keep ≥ 3.75:1 on the row (the sell glyph on raised 4.42 / 3.94 / 3.75) and the bubbles ≥ 3.97:1 on the canvas (4.68 / 4.17 / 3.97) in every rendering — the tool reproduces the minima; on the tier-2 fills the sell glyph measures 3.71 / 3.43 / 3.31 and the buy glyph 5.01 / 3.89 / 4.27, at or above the 3:1 non-text bar; the row text ≥ 10.21:1 on the tier-2 fills", "the hi-fi rule E22-D03 inherits (memo §3.8 line 219): the side word and every numeric in color.text.primary on every tier; the hue on the glyphs, the accent and the tier-2 fill at the non-text bar; the dimmed prefix never on a filled row", "greyscale needs no CVD run (E13-D02 §14); cvd_sim.py runs on the exports anyway to confirm nothing reads by lightness alone"], foot: "Q4: identify the tiers in greyscale within 2 s — D06 T4 tests it" });
  finish(b, sy + Math.max(plateH, c3.h));
};

// ---- Board 11: the clustering affordance — the panel-level CMP-227 chip, its tooltip, Enter → SCR-058 (G10), the switch, raw mode ----
BUILD[11] = () => {
  const b = place(11, "clustering-badge-tooltip", W_BOARD, 1000);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — The clustering affordance (§9): the panel-level CMP-227 (estimated) chip beside the mode chip Reconstructed 250 ms / 1 tick, its tooltip and Enter → SCR-058 (G10: no trade_cluster section yet), the row / bubble tooltip, the raw ↔ reconstructed switch with the seam divider, the badge absent in raw mode; E22-S04 owns", SRC);
  stamp(b, X, y, "PROPOSED · Q11 drawn · G10 noted"); mkText(b, LEGEND, X + 280, y + 5, W - 280, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  const pw = 560;
  const ml = mkText(b, "reconstructed mode: the chip sits in the chips row right after the mode chip, visible iff cluster_window_ms > 0; two accessible names, ≥4 px apart — Estimated, Trade cluster then, if stale, Stale 12s (E08-D04 §4)", X, y, pw, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "mode-label" });
  const top11 = y + (ml ? ml.h : 30) + 6;
  const pa = panelChrome(b, X, top11, pw, { chips: [{ label: "Big only" }, { label: "Reconstructed 250 ms / 1 tick" }, { label: "(estimated)", fill: "hover", stroke: "borderStrong" }] });
  const ta = tapeBlock(b, X, pa.logY, pw, tapeRows(8, 23).map((r, i) => (i === 2 ? Object.assign({}, r, { tags: ["×7"] }) : i === 5 ? Object.assign({}, r, { tags: ["⧉"] }) : r)), Object.assign({ density: "compact" }, elide(8, 0, 0)));
  // the tooltip under the chip
  const ttX = X, ttY = pa.logY + ta.h + 10;
  mkText(b, NB("the chip's tooltip (CMP-016; hover and focus; Esc dismisses):"), ttX, ttY, pw, { size: 11, color: C.text3, tok: TOK.text3, name: "chip-tooltip-label", h: 15 });
  mkRect(b, ttX, ttY + 18, pw, 46, "overlay", { stroke: "borderStrong", radius: 6, role: "wire", name: "chip-tooltip" });
  mkText(b, "Prints at the same price and side within 250 ms / 1 tick are shown as one row. Enter opens Why estimated?", ttX + 10, ttY + 24, pw - 20, { size: 11, name: "chip-tooltip-text" });
  mkText(b, NB("raw mode: neither chip shows; the seam divider marks the switch"), X + pw + 40, y, pw, { size: 11, weight: 600, color: C.text2, tok: TOK.text2, name: "raw-label", h: 15 });
  const pb = panelChrome(b, X + pw + 40, top11, pw, { chips: [{ label: "Big only" }, { label: "Raw prints" }] });
  const tb = tapeBlock(b, X + pw + 40, pb.logY, pw, tapeRows(8, 29), Object.assign({ density: "compact", dividers: { 3: "— clustering off from here —" } }, elide(8, 1, 0)));
  y = top11 + Math.max(pa.logY - top11 + ta.h + 74, pb.logY - top11 + tb.h) + GAPY;
  const c = card(b, X, y, W, { kicker: "THE AFFORDANCE (D25; memo §4 row 10; E25-D05 §4.1, line 131; US-BIG-004)", value: "one panel-level chip, never per row · Enter opens SCR-058 · the word is the full (estimated)", lines: ["CMP-227 inline in the chips row (group Active filters) right after the mode chip; the tooltip shows on hover and focus, Esc dismisses it; Enter / Space opens SCR-058 — G10: DetectorMethodology.detector has no trade_cluster member yet, so until E25-D01 G3 / the 22 owner land it the chip opens the drawer's big_trade section (PROPOSED); the display name Trade cluster is E25-D05's", "the row tooltip carries the constituent count where the encoding has it (×7 on the structured path; the flag only ⧉ on kind 3 — C18); the bubble tooltip reads Cluster ×7 · 1.9M USDT · Sell · 7 prints within 250 ms / 1 tick · first print 14:02:11.208 · bar 14:02 · (estimated)", "the raw ↔ reconstructed switch is E22-S04's Rows control; it re-subscribes with the new cluster_window_ms, keeps the ring buffer, and draws the seam divider — clustering off from here — / — clustering on from here —", "Est. appears nowhere on this panel (E11-D05 ruling 4; E25-D01 C15 / Q4 keep the prefix form the owner's)"], foot: "E22-S04 owns the controls; E22-T02 the count on kind 3 (C18)" });
  finish(b, y + c.h);
};

// ---- Board 12: the panel wireframe with the Tab stops and the roving cursor beside the a11y tree; the keyboard table; names; announcements ----
BUILD[12] = () => {
  const b = place(12, "keyboard-a11y-announcements", W_BOARD, 1700);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — The panel with its Tab stops and the roving cursor beside the a11y tree (memo §5); the keyboard table (BQ-3 RULED, every hint PROPOSED — no Tape context in keymap.json); the name / role excerpt; the announcement policy with the E06-D03 D5 check; targets ≥ 24 px; the analytics firing map; the T2 anatomy (§11–§12)", SRC);
  const stW = stamp(b, X, y, "PROPOSED · every Kbd hint · E22-D04 owns the policy"), lgX = X + Math.max(340, stW + 12); /* r9: the legend after the stamp's own width (r8: at X + 340, inside the 364 px stamp — the containment self-check) */ mkText(b, LEGEND, lgX, y + 5, W - (lgX - X), { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  const pw = 520;
  const pk = panelChrome(b, X + 70, y, pw, { paused: true, status: [{ label: "Paused — 412 prints buffered", fill: "hover", stroke: "borderStrong" }], actions: ["Jump to live"], chips: [{ label: "Big only" }] });
  const tk = tapeBlock(b, X + 70, pk.logY, pw, tapeRows(12, 31), Object.assign({ density: "compact", liveEdge: true, focusRow: 3 }, elide(12, 0, 0)));
  controlStrip(b, X + 70, pk.logY + tk.h, pw, { collapsed: true });
  [["1–5", y + 6], ["6", y + NUM.slotHeader + 4], ["7", pk.logY - NUM.slotChips + 4], ["8", pk.logY + NUM.slotColHdr + 2], ["9", pk.logY + tk.h + 2]].forEach((s) => pill(b, X + 8, s[1], "Tab " + s[0], { h: 16, size: 10, padX: 5, fill: "selected", stroke: "borderStrong", name: "tab-stop" }));
  mkText(b, NB("↑/↓ the roving cursor (row 4 focused: the 2 px stand-in = keyboard focus only)"), X + 70, pk.logY + tk.h + NUM.slotStripCollapsed + 8, pw, { size: 11, color: C.text3, tok: TOK.text3, name: "cursor-note", h: 15 });
  const tree = card(b, X + 70 + pw + 40, y, W - pw - 110, { kicker: "THE A11Y TREE (memo §5 line 272 as amended by D29, D02-C14) — one tab stop for the list, a roving cursor; no node under two parents", value: "region → toolbar · status row (plain text + buttons) · one hidden status node · group · log (grid) · strip", mono: true, lines: [
    "region \"Tape BTCUSDT\"",
    "  toolbar \"Tape controls\" — Filter prints (Ctrl+F) · Threshold… (the unit in its name) · Pause tape (P) aria-pressed · Columns… menu · More (Shift+F10) menu",
    "  the status row — plain text: the feed chip · Paused · Reconstructed after gap · capped; buttons: Jump to live · Load missed prints · Apply 34 723 USDT · Keep 30 000 USDT (Tab stop 6)",
    "  readout — plain text, aria-live=\"off\", named tape speed: 2 010 /s (1 s) · 33 /frame",
    "  status \"Tape status\" — visually hidden, pre-rendered empty, polite: the panel's only live region; the once-per-episode sentences are written into it",
    "  group \"Active filters\" — Big only aria-pressed · Reconstructed 250 ms / 1 tick + button \"Estimated, Trade cluster\" · the removable filter chips",
    "  log \"Tape, newest first\" (aria-live=\"off\")",
    "    grid (CMP-049) — row → gridcell × 5 + tags; roving tabindex; aria-rowcount / aria-rowindex; new prints never move focus",
    "      row name: \"Sell, 18.75 BTC at 64,012.0, 1.2M, whale, 14:02:11.208\"",
    "      divider rows: presentation, never focusable",
    "  group \"Threshold and bubbles\" — the strip's controls; Size tier 2 is derived text",
    "  menu (Shift+F10) — Read tape summary · Reset columns · Density: Compact / Comfortable (menuitemradio pair, CMP-063) · Open settings",
  ], foot: "the overlay: CMP-112's sparse mirror markers under the chart's role=\"application\" root (E06-D03 D4); the legend row as CMP-199; the chips and their counts are never announced (05 §6.2; E17-D01 §7)" });
  y += Math.max(pk.logY - y + tk.h + NUM.slotStripCollapsed + 30, tree.h) + GAPY;
  const keys = [ // r7: the §11 table's own seven columns and cells, verbatim (r6 merged Where · Action · Focus after · Global conflict? into one paraphrased cell)
    ["K1", "Tab / Shift+Tab", "panel", "header controls → status-row buttons (one stop) → chips (one stop) → list (one stop) → strip", "per §11", "none", "n/a"],
    ["K2", "↑ / ↓", "list (grid)", "move the roving cursor between rows; new prints never move it (memo F22)", "the row", "none in the panel context", "PROPOSED"],
    ["K3", "Home / End", "list (grid)", "first / last cell of the row (APG grid)", "the cell", "the chart's Home / End are oldest / latest bar (05 lines 52–53) — a different focus context (C22)", "PROPOSED"],
    ["K4", "Ctrl+Home / Ctrl+End", "panel focus, outside a text field or an open menu (the grid included)", "Jump to live — the viewport to the live edge: with no row focused it resumes a scroll-away pause (P5); on a focused row the roving cursor moves to the newest row and the focus pause holds (§5: the list never resumes under a focused row; Esc or blur resumes, P9; D02-C17) / Ctrl+End the oldest row", "the newest / oldest row in the grid; else stays", "none; the listbox-of-rows alternative would put Jump to live on Home (C22 — E22-D04 decides)", "PROPOSED"],
    ["K5", "Enter", "a focused row", "locate on synced charts (tape.print_clicked)", "stays", "none", "PROPOSED"],
    ["K6", "Esc", "anywhere in the panel", "innermost cancel (memo C16), innermost first as D15 says: a filter input holding text clears → the open menu / popover closes → a focused row resumes (P9; in a hard pause the selection is released, P13) → nothing swallowed", "per step", "Esc reserved (05 §3.3 rule 3) — never remapped, never swallowed", "reserved"],
    ["K7", "P", "panel focus, outside a text field or an open menu", "hard pause / resume (P6 / P7); the open CMP-056 menu's type-ahead and the filter's field consume printable keys first (the innermost rule, as for Esc); in S10 while not hard-paused P changes nothing: the pause button's CMP-016 echo shows the reason in place for one dwell without moving focus, and the reason is written once into the status node (polite; E09-D09 §9.3, E17-D01 D13)", "stays", "the chart's P = profile overlay (05 line 56) — focus-context shadowing per 05 §3.3 rule 1(3); the remap UI shows both meanings (C11)", "PROPOSED"],
    ["K8", "Ctrl+F", "panel focus", "open the filter popover (D15)", "the min-notional field", "not in reserved-keys.json; the browser's find is Electron-shadowed by the panel context (stated)", "PROPOSED"],
    ["K9", "Shift+F10 / Menu", "panel focus", "the panel menu (\"Read tape summary\", \"Reset columns\", \"Density: Compact / Comfortable\" — CMP-063 as a menuitemradio pair, \"Open settings\")", "the first item", "the lane's menu key (E11-D02 §7)", "PROPOSED"],
    ["K10", "Alt+↑ / Alt+↓", "inside the open CMP-056 menu", "reorder the focused column (D17)", "the moved item", "the chart's timeframe cycle (05 line 55) is outside the menu — never shadowed (BQ-3; D02-C5)", "PROPOSED"],
    ["K11", "Space / Enter", "a chip / the pause button", "toggle the preset, remove the filter, pause", "stays", "Space is bound in the DOM and Replay contexts (keymap.json) — different focus contexts, as K7 / K10", "n/a"],
    ["K12", "Delete / Backspace", "a filter chip", "remove it (D16)", "next chip, else the group", "the chart's Delete / Backspace = delete the selected drawing (05 §3.2 line 59) — a different focus context", "PROPOSED"],
    ["K13", "Enter / Space", "CMP-227", "open SCR-058 at the section; return to the chip on close", "the chip", "none (E25-D05 §4.3)", "n/a"],
    ["K14", "Ctrl+K", "global", "\"Read tape summary\" as a palette command (memo F21; no default key — Q9, E49)", "the palette", "reserved (05 §3.3 rule 3)", "the palette's"],
    ["K15", "Enter / Space / any bound key on a T2 control", "the gated controls (§11.4)", "nothing changes; the reason is re-shown inline at the point of action with one polite announcement (E09-D09 §9.3)", "stays", "none", "n/a"],
  ];
  const kt = tableBlock(b, X, y, [44, 200, 230, 580, 190, 370, 162], ["Id", "Key", "Where", "Action", "Focus after", "Global conflict?", "Registered?"], keys, { stk: TICKET + ":b12-keys", mono: [false, true, false, false, false, false, false] });
  y += kt.h + GAPY;
  const ann = tableBlock(b, X, y, [320, 150, 700, 390, 216], ["Event", "Region", "Text (verbatim, §13)", "Rate", "D5 check (2–3 s per ~10 words)"], [ // r7: the §12 table's thirteen rows and five columns, verbatim (r6 merged the two resume rows and the two Stale rows, merged Rate + D5, and dropped the Paused, filter and column-reorder rows)
    ["whale print (opt-in; off by default)", "status polite", "\"3 whale sells in 5 s, largest 410k at 64,012.0\"", "≤ 1 per 5 s, summarised (memo F21; the ambient budget)", "10 words ≈ 2.5 s — fits one window"],
    ["on-demand summary", "status polite", "\"Last 5 s: 212 prints, 61 % buy by notional, largest sell 134k at 64,012.0, 3 big\"", "on request only", "16 words ≈ 4 s — on request, allowed"],
    ["resume", "status polite", "\"Resumed, 412 prints inserted\"", "once per resume", "4 words"],
    ["resume with prints not kept (S22)", "status polite", "\"Resumed, 10 000 prints inserted, 2 000 not kept\"", "once per resume", "8 words"],
    ["Paused (any entry)", "none", "the chip is visible; the list stops", "never (the chip's count ticks visually only)", "—"],
    ["Stale T1 enter / exit", "status polite", "\"Tape stale 12 seconds.\" / \"Tape live.\"", "once per episode (E17-D01 §7 line 219)", "4 words"],
    ["Stale ≥ T2", "alert assertive", "the chart's sentence, once per episode (E17-D01 §7 line 218) — the tape adds nothing", "once", "—"],
    ["Disconnected / Reconnected", "alert assertive", "SCR-152's sentences (E17-D01 §7 lines 215, 226); \"Reconnected — gap 14:02:11.331 to 14:02:19.004\" polite once, then \"1 240 missed prints loaded\" after the REST load", "once", "—"],
    ["over-threshold strip", "status polite", "\"Threshold raised to 34 723 USDT — 23.5 % of prints were flagged\"", "once per episode, never per 5 s refresh", "11 words ≈ 2.8 s"],
    ["filter applied / removed, Big only", "status polite", "\"Filter applied: 2 filters active\" / \"Big only on\"", "once per action (E22-S05)", "short"],
    ["column reorder", "status polite", "\"Notional moved up, 3 of 5\"", "once per move", "short"],
    ["T2 keystroke", "status polite", "the reason sentence", "once per press", "≤ 60 characters"],
    ["the readout, the buffered count, every row arrival", "none (aria-live=\"off\")", "—", "never — counters are never announced per tick (E17-D01 D9)", "—"],
  ], { stk: TICKET + ":b12-ann" });
  y += ann.h + GAPY;
  const c = card(b, X, y, W, { kicker: "TARGETS, THE FIRING MAP AND T2 (§11, §16; E09-D09)", value: "every control ≥ 24 × 24 CSS px compact · no essential exception · no drag", lines: ["five 24 × 24 icon buttons; 20 px chips with a 24 px hit box by padding (CMP-227 and the remove buttons included); the 24 px row is the row's own target; the strip's controls 24 px tall; comfortable 32 px", "tape.filter_changed on apply / remove (board 06) · tape.paused / tape.resumed with a PROPOSED cause (and dropped for a full ring) on P1–P9, P14 (board 04) · tape.print_clicked on a click or Enter on a row — never on keyboard focus alone — and on a bubble's mirror node (boards 04, 08); a T2 press emits nothing", "T2 (§11.4): the pause button in Disconnected while not hard-paused — lock glyph + full label + Nothing to pause while disconnected. (feed.disconnected_pause, PROPOSED, E17-D01 §7 owner; its own reason node under the icon-only button, 2b); every write while viewing as — Read-only while viewing as {user}. (rbac.view_as), one notice, many pointers (the threshold, Apply, the picker and Reset columns, the scale / Rows controls, the Reconstructed rows toggle, the density pair); pause, the display filters, Big only, Clear filter, Keep, Jump to live and Load missed prints stay T1; Size tier 2 is derived text; form validity is never T2; a Viewer (no settings:write / workspaces:write): the same writes T2 — Your role can't change settings. / Your role can't save workspaces. (rbac.permission), one notice per surface; the Threshold… and Columns… openers stay T1 in every session"], foot: "E22-D04 owns the announcement policy; E22-Q04 audits it; E22-S01 / the E49 keymap owner register the Tape context" });
  finish(b, y + c.h);
};

// ---- Board 13: the state × copy matrix with the QA-testability column, the measured pairs, the counts, the amendments, the hand-offs ----
BUILD[13] = () => {
  const b = place(13, "copy-deck-states-matrix", W_BOARD, 2400);
  const X = b.x + 32, Y = b.y + 28, W = W_BOARD - 64;
  let y = Y + title(b, X, Y, W, "E22-D02 — The state × copy matrix (§4 S1–S23) with the QA-testability column, the measured greyscale pairs (tool), the C / G / Q / BQ counts, the 15 amendments summary and the hand-offs (§13–§19)", SRC);
  stamp(b, X, y, "PROPOSED · owner approval pending"); mkText(b, LEGEND, X + 280, y + 5, W - 280, { size: 11, color: C.text3, tok: TOK.text3, name: "legend-line", h: 15 }); y += 24 + GAPY;
  const states = [
    ["S1", "Streaming (Gherkin)", "none (no feed chip means Live)", "replay the dense tape at 50 / 500 / 2 000 prints/s", "01–03"],
    ["S2", "Soft paused (Gherkin)", "Paused — 412 prints buffered · narrow: Paused — 412 buffered", "rest the pointer 150 ms then move 1 px; leave → S5", "04"],
    ["S3", "Scroll-away paused", "Paused — 412 prints buffered · Jump to live", "wheel down 3 rows; wait 60 s; still paused; Ctrl+Home with no row focused → S5", "04"],
    ["S4", "Hard paused", "Paused — 412 prints buffered (the pause button aria-pressed)", "press P; park the pointer 60 s; no resume", "04"],
    ["S5", "Resumed", "— 412 prints while paused — · Resumed, 412 prints inserted (polite)", "count the inserted rows = the chip's count", "04"],
    ["S6", "Click-to-locate", "the Paused chip; the selected row", "click row 5 at 500 /s: the chip before the selection; the crosshair time = the row's", "04"],
    ["S7", "Delayed", "none on the tape (the global chip Reduced rate ×4)", "force throttle_multiplier 4; no row dropped", "05"],
    ["S8", "Stale T1", "Stale 12s beside any Paused chip (two pills) · readout —", "stop the trades fixture 12 s with the transport up", "05"],
    ["S9", "Stale ≥ T2", "Stale 30s (strong) · readout —", "stop the fixture 30 s; one assertive announcement", "05"],
    ["S10", "Disconnected (Gherkin)", "Disconnected — last data 00:12 · Offline · the pause button T2 while not hard-paused: Nothing to pause while disconnected.", "drop the socket; the strip, frozen rows, aria-disabled + the reason node", "05"],
    ["S11", "Loading", "Loading… (header and readout; never —)", "delay the snapshot 3 s", "05"],
    ["S12", "Empty", "No prints yet · last print 13:58:02 · readout 0 /s · quiet", "a symbol fixture with no prints after From", "05"],
    ["S13", "Filtered-empty (Gherkin)", "No prints above 10 000 USDT in the last 5 min · Clear filter", "min notional 10 000 on the thin ETH fixture", "05"],
    ["S14", "Partial history (Gherkin)", "— No history before 13:58:02. Recording started then. —", "start the recorder mid-fixture; scroll to the oldest row", "05"],
    ["S15", "Reconnect backfill, before", "— gap 14:02:11.331 → 14:02:19.004 — · Reconstructed after gap + Load missed prints (status row) · Reconnected — gap 14:02:11.331 to 14:02:19.004", "drop the socket 8 s on the reconnect ETH fixture", "05"],
    ["S16", "Reconnect backfill, after", "— 1 240 prints while disconnected — · 1 240 missed prints loaded", "press Load missed prints; count the inserted rows", "05"],
    ["S17", "Mode switch", "— clustering off from here — / — clustering on from here —", "flip the Rows control; the divider and the badge", "05, 11"],
    ["S18", "Over-threshold warning (Gherkin)", "Threshold flags 23.5 % of prints — raised to 34 723 USDT (the window's p80); prints between 30 000 and 34 723 are not flagged · Apply 34 723 · Keep 30 000 · eff. 34.7k USDT · capped", "30 000 USDT on the dense tape fixture (23.5 %)", "05, 07"],
    ["S19", "Compressed (rung 3)", "27 small prints · Σ 1.9 · compressed", "replay at 2 000 /s with the rung forced", "03, 05"],
    ["S20", "Big only preset on", "Big only (aria-pressed)", "press the chip at 500 /s: every visible row carries ● or ◆", "06"],
    ["S21", "View-as read-only", "Read-only while viewing as {user}. (one notice; every write T2 — threshold, Apply, picker + Reset columns, scale / Rows, Reconstructed rows, density)", "open view-as on a manager fixture: aria-disabled + the lock glyph on the writes; Size tier 2 is plain text", "06"],
    ["S22", "Paused, buffer full", "Paused — buffer full · 10 000 kept · on resume — 12 000 prints while paused · 2 000 not kept — + Load missed prints · Resumed, 10 000 prints inserted, 2 000 not kept", "hard-pause 6 s at 2 000 /s on the dense tape: the chip flips at 10 000, the window never moves, the divider counts 12 000 / 2 000", "04"],
    ["S23", "Viewer — the permission leg", "Read-only — your role can't change settings. (the strip's writes, Apply, the popover toggle) · Read-only — your role can't save workspaces. (the picker, Reset columns, the density pair) — rbac.permission, one notice per surface; the same T1 set as S21", "sign in as the Viewer fixture: aria-disabled, the lock glyph and the two notices; pause, the display filters and Big only still work", "06"],
  ];
  const st = tableBlock(b, X, y, [50, 230, 760, 560, 176], ["Id", "State", "Copy string (verbatim)", "QA testability (how to reproduce; never a claim that it was run)", "Board"], states, { stk: TICKET + ":b13-states" });
  y += st.h + GAPY;
  const pairs = tableBlock(b, X, y, [360, 120, 120, 120, 436], ["Pair (greyscale; tool over packages/ui/tokens at the base)", "dark", "light", "hc", "verdict"], [
    ["text.primary / secondary / tertiary on canvas", "15.20 / 9.33 / 5.96", "16.78 / 9.65 / 6.36", "17.21 / 15.20 / 11.87", "PASS — E13-D02 §13 reproduced"],
    ["text.primary / secondary / tertiary on raised", "14.35 / 8.81 / 5.62", "15.62 / 8.98 / 5.92", "16.25 / 14.35 / 11.21", "PASS — memo §3.8 reproduced"],
    ["text.secondary / tertiary on sunken · on hover · on selected", "10.69 / 6.83 · 7.50 / 4.79 · 6.24 / 3.98", "7.37 / 4.86 · 8.26 / 5.44 · 7.37 / 4.86", "17.42 / 13.61 · 12.22 / 9.54 · 10.17 / 7.94", "PASS; tertiary on selected 3.98 dark rejected by design (the prefix is undimmed on the selected row)"],
    ["focus stand-in text.primary on canvas / raised / hover / selected / overlay", "15.20 / 14.35 / 12.22 / 10.17 / 13.27", "16.78 / 15.62 / 14.37 / 12.82 / 14.37", "17.21 / 16.25 / 13.83 / 11.51 / 15.02", "PASS (non-text)"],
    ["decorative: border.default · border.strong · the tier-2 band edge on raised", "1.41 · 1.80 · 1.17", "1.22 · 1.46 · 1.09", "2.86 · 1.80 · 1.17", "not gated — the glyph, the weight and the word carry"],
    ["D03 inherits: Paused chip text on status.warning.subtle · row text on buy.subtle / sell.subtle", "9.86 · 10.21 / 12.06", "15.62 · 15.41 / 14.64", "11.16 · 11.56 / 13.66", "PASS (reported for E22-D03)"],
    ["S10 scrim composition: text.primary / secondary / tertiary seen through opacity.scrim 0.6 of app on raised", "3.23 / 2.39 / 1.89", "2.43 / 2.00 / 1.77", "3.52 / 3.23 / 2.76", "reported, not gated — below the text bar; D02-C15 for E22-D03 (the scrim over the strip only, or the rows kept ≥ 4.5:1)"],
  ], { stk: TICKET + ":b13-pairs" });
  y += pairs.h + GAPY;
  const cnt = strip(b, X, y, W, "COUNTS (the tool's §H; the draft repeats them)", [
    { v: "40 pairs × 3 themes · FAIL 0", t: "greyscale matrix", d: "19 of 19 reproductions match (E13-D02 §13, memo §3.8); the three scrim compositions reported", pill: "tool" },
    { v: "23 states · 14 transitions", t: "§4 state rows · §5 transition rows", d: "the six Gherkin states first; S22 the full ring; S23 the Viewer leg; P13 / P14 in the table", pill: "boards 03–06" },
    { v: "15 keys · 26 copy rows", t: "§11 keyboard rows · §13 copy rows", d: "every key hint PROPOSED", pill: "board 12" },
    { v: "C 22 + 15 · G 11 + 7", t: "inherited + own", d: "every own row names one owner", pill: "§19" },
    { v: "Q 15 · BQ 6", t: "drawn or escalated · RULED", d: "Q1–Q15 each on a board or to its owner; BQ-1..6 as recorded", pill: "§19" },
    { v: "10 amendments", t: "§17 A15-rows for E22-D03", d: "no 15 edit in this PR (BQ-1)", pill: "E22-D03", decision: true },
  ]);
  y += cnt.h + GAPY;
  const ho = card(b, X, y, W, { kicker: "HAND-OFFS (§19 HO-1..15)", value: "E22-D03 is blocked by this ticket; D04 / D05 take the tables; S01..S05 / T02 the contract rows", lines: ["E22-D03 — hue / type / icons, the CMP-112 DS entry, the A15 rows, the r_min call, the hi-fi pairs, the forced-colors rendering · E22-D04 — §11 / §12, the keys C11 / C16 / C22 / D02-C5, the announcement policy · E22-D05 — the pack by reference", "E22-S01 — the panel, the pause model, the readout, the ≤60-row window, the Tape keymap context, the pairs.mjs rows · E22-S02 — the strip and the seeds · E22-S03 — the law, the pair, the label / outline, the legend row, the bench gate · E22-S04 — the badge and the switch · E22-S05 — the filter, the columns, the Big only fallback · E22-T02 — G1 / G2 / C18 · E22-K01 — bench/bubbles-sdf-labels", "E25-D01 / D05 — the pattern rule, the marker word, the 14 §12.3 row · E24-D01 — the liq tag boundary · E40-D01 / E22-S06 — SR-9 · the 14 / 15 / 11 / 26 owners and the E49 keymap owner"], foot: "owner approval pending; the boards are drawn from the board script in this boards PR; exports in docs/design/E22/img (§0)" }); // r8: the drawn state, no worker name (QA Minor)
  finish(b, y + ho.h);
};

// ---- the gate (plan + self-check + guard) before anything is removed or drawn; the draw; the clear only after the draw succeeded
[mkText, mkRect, mkSwatch, mkDisc, mkSquare, card, pill, kbd, stamp, tableBlock, title, strip, tapeBlock, panelChrome, controlStrip, shellChrome, placeholderPanel, drawChartSnippet, finish, lockGlyph, lockText] = [mkText, mkRect, mkSwatch, mkDisc, mkSquare, card, pill, kbd, stamp, tableBlock, title, strip, tapeBlock, panelChrome, controlStrip, shellChrome, placeholderPanel, drawChartSnippet, finish, lockGlyph, lockText].map(unitWrap);
const wanted = BOARDS.filter((bd) => want(bd.n)).map((bd) => bd.n);
const stop = gate(wanted);
if (stop) return stop;
const olds = PART === null || PART === 1 ? oldPlanned() : [];
try { for (const n of wanted) drawBoard(n); } catch (e) { throw rolledBack(e); }
clearPlanned(olds);

// ---- one row at a 2 000 px pitch on every run, for every board of this ticket on the page (built now or earlier)
const row = placeRow();

// ---------------------------------------------------------------- result ------------------------------------
try { page.setPluginData(TAG, "v1"); page.setPluginData(TAG + ":built", new Date().toISOString()); } catch (e) { warn("page tag", e); }
const exportCommands = built.map((x) => "python3 docs/design/_tools/penpot_export.py " + x.id + " " + x.exportAs).join("\n");
return {
  writer: WRITER,
  version: VERSION,
  pageId: page.id,
  pageName: page.name,
  createdPage,
  removed,
  duplicatePages,
  boards: built,
  part: PART,
  partPlan,
  selfCheck: GATE.selfCheck,
  row,
  next: PART && PART < partPlan[0].parts ? "board " + pad2(wanted[0]) + ": run PART = " + (PART + 1) + " next (ONLY = [" + wanted[0] + "]); the relayout only after PART = " + partPlan[0].parts : "e22-d02-relayout.js PASS=\"measure\" → PASS=\"restack\" (until moved=0) → e22-d02-dedupe.js → probe.js until every instance agrees → export-guard (0 token-bound, 0 instances) → export → read the thirteen boards' x back (x = (n − 1) · 2000, y = 0; 0 overlapping pairs)",
  exportCommands,
  warnings,
};
