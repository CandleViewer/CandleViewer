/* E12-D05 — SCR-031 chart settings, General tab: hi-fi boards (#241; the text is PR #4669, docs/design/E12/E12-D05.md +
 * E12-D05-handoff.md at cec8310a6d, merged on main as #4669): BUILD script, r2.
 *
 * RUN ORDER (each step is ONE Penpot MCP execute_code call; long bodies go through docs/design/_tools/penpot_exec.py):
 *   1. probe.js (read-only): stamp the connected plugin instances, run it until every instance agrees, pick ONE stamp and
 *      set WRITER in this script, e12-d05-relayout.js and e12-d05-dedupe.js.
 *   2. this script with ONLY = [n] and PART as the result of PART = 0 says: one call for a board of at most 400 shapes
 *      (PART = null), else PART = 1, 2, … K, one call each, in order (ONLY left at "SET-ME", null, [] or [n, m] aborts
 *      before any write; PART = null on a board in parts, a PART the plan does not have or a call over the budget throws
 *      before any write). PART = 0 prints the plan of every built board and touches nothing.
 *   3. once board n holds every part: e12-d05-relayout.js ONLY = [n], PASS = "measure" until `unmeasured` is 0, then
 *      PASS = "restack" until `moved` is 0 (again after any part re-run).
 *   4. export board n: the result's exportCommands line (python3 docs/design/_tools/penpot_export.py <id> <exportAs>), 1x.
 *   5. inspect the PNG: the scrim translucent (the workspace visible under it), no clipped or re-wrapped label, Inter (not Inter
 *      Tight) and JetBrains Mono, the candles of the preview crisp.
 *   6. after the last board: e12-d05-dedupe.js (DRY_RUN = true first), then probe.js until every instance agrees.
 *   Never retry a call after a "tab suspended" answer: probe read-only first.
 *
 * MACHINERY (E15-D07 r3's, itself E15-D03 / E29-D03's; generic parts byte-for-byte: page safety, PARTS, the recorder, stamps, token
 * binding, the scrim re-assert, the relayout and dedupe passes, exportCommands, the self-check): single writer (storage.hpe1inst =
 * WRITER); FILE_ID set by the runner at load time, never committed, posted or logged ("SET-ME" fails closed); the page is pinned by
 * PAGE_ID once known, else found by name (created when missing) and used only when it holds nothing but `E12-D05 /` frames; one call
 * creates at most SHAPE_BUDGET = 400 shapes and SEG_BUDGET = 5,000 path segments (this script draws no path: 0 segments); a larger
 * board is cut into K = ceil(shapes / 250) parts replayed from one recorded build.
 *
 * CONVENTIONS: board n is "E12-D05 / NN <slug>" (spec §0), exported to EXPORT_DIR/E12-D05-NN-<slug>.png; board x = Σ widths of the
 * boards before it + (n − 1) × 160 (GAP), y = 0: one row. Each frame is a 1280 × 800 window (§0, the BUDGET:viewport anchors) named
 * exactly as its §15.1 Frame cell, laid out in a row in §15.1's order and walked left to right; its caption prints the row's cells.
 * Board 01 (and its twins) adds one frame beside its row, the same window with the dialog's body scrolled to the end (CMP-043
 * "scrolls": the four sections are taller than the body of a card at 80 % of 800 px); it is not a register row and is not in the
 * result's frames. Every board has the source band (eyebrow "E12-D05 · <SCR> · board NN · <VERSION> · <theme> · <density>", the title
 * naming the spec sections), the notes, the a11y strip and the footer "page <PAGE_NAME> · board NN · <VERSION> · <theme>".
 * CHROME: the workspace behind the SCR-031 dialog is E15-D03's merged chrome (41-chrome.js, 42-d03.js and 40-copy.js, as pp/361 r3
 * carries them), under the modal scrim: palette.black at opacity.scrim BY VALUE, read back after the bindings and re-asserted (r3 F-1
 * of #4640, 20-prims / 80-parts); the TopBar, the StatusBar and the view-as banner stay unscrimmed.
 * TOKENS: every fill, stroke and text colour and every type style is a token NAME of packages/ui/tokens (read at cec8310a6d by
 * tools/gen_tokens.py; dark = primitives → semantic-dark, light = + semantic-light, high contrast = + semantic-hc; no hex typed by
 * hand), recorded in the shape's meta and bound at run time by name under the template's value guard; radius, stroke width, icon size,
 * opacities and positions by value. The high-contrast twin (board 10) is built on TV's dark column holding its hc values (59-twins).
 * NUMBERS: every bound, default, count and the viewport are the spec's audit tool's --json (e12_d05_settings_audit.py, 05-audit.js);
 * the chrome's rows are E15-D03's tool's (pp/361 work/audit-d03.json). The preview draws E12-D06's recorded BTCUSDT 1m klines
 * (07-data.js, pp/202's, packages/fixtures/bybit/2026-10-05).
 * WORDS: §12's W-rows and D03's C-rows the spec quotes (verbatim), §3.1's lines, E11-D03's chrome copy (tabs, helper lines, preview
 * states), E15-D02's prompt; every PROPOSED item carries a PROPOSED stamp beside the card, never on it.
 * r1 (2026-10-26): the ten boards, offline (the mock harness: 0 failures on every board).
 * r2 (2026-10-27): the orchestrator's four rulings: 01/08/10's scroll frame labelled a specimen of CMP-043's 640 px cap; the Reset
 *   confirm bodies stamped as PROPOSED copy rows of the E12-D05 copy deck (boards PR); 04/09 specimen 7 (Renko atr:14) redrawn in
 *   D03 board 05's "Renko, atr: typed" form (C-12 in the message line, nothing sent).
 */
"use strict";

// ---------------------------------------------------------------- runner constants (a runner sets each with a regex on its line)
const WRITER = "SET-ME"; // storage.hpe1inst stamp of the ONE instance allowed to write (probe.js); "SET-ME" skips
const VERSION = "r2"; // hpe1ver stamp on every board, printed in each board's eyebrow and footer; bump when the content changes
const FILE_ID = "SET-ME"; // the self-hosted CandleViewer file's id: set by the runner at load time, never committed, posted or logged; "SET-ME" fails closed
const PAGE_NAME = "E12-D05 SCR-031 General"; // spec §0: page `E12-D05 SCR-031 General` (file `E12-D05 boards`), created by name at the boards step; then pin PAGE_ID and record the id in spec §0
const PAGE_ID = null; // after the first run paste the returned pageId here so later runs pin the page by id
const TICKET = "E12-D05";
const TAG = "cv:e12-d05"; // plugin-data key marking every shape this script creates (value "v1")
const ONLY = "SET-ME"; // the runner sets [n]: one board per call; anything else aborts before any write
const PART = null; // null = board n in ONE call (a board of at most SHAPE_BUDGET shapes); 0 = the parts plan only, nothing touched; k = part k of board n, k = 1..K one call each, in order
const EXPORT_DIR = "docs/design/E12/img"; // spec §0: docs/design/E12/img/E12-D05-NN-<slug>.png

// ------------------------------------------- the ten boards (spec §0's table; widths are the board script's) -----------------------
// twin: a light or high-contrast twin reuses its dark board's builder in its own theme (59-twins), drawing its own §15.1 row
// w: 2 × 40 + frames × 1280 + (frames − 1) × 80 (one row of 1280 × 800 windows, §0)
const BOARDS = [
  { n: 1, slug: "general-populated", w: 2720, theme: "dark", density: "comfortable", scr: "SCR-031 · CMP-043", plan: "2720 × 1300" },
  { n: 2, slug: "chart-types", w: 5440, theme: "dark", density: "comfortable", scr: "SCR-031 · CMP-006 · CMP-028", plan: "5440 × 1300" },
  { n: 3, slug: "bar-modes", w: 6800, theme: "dark", density: "comfortable", scr: "SCR-031 · CMP-006 · CMP-008", plan: "6800 × 1300" },
  { n: 4, slug: "validation", w: 1360, theme: "dark", density: "comfortable", scr: "SCR-031 · CMP-008", plan: "1360 × 1400" },
  { n: 5, slug: "all-panels", w: 4080, theme: "dark", density: "comfortable", scr: "SCR-031 · CMP-003 · SCR-030", plan: "4080 × 1300" },
  { n: 6, slug: "preview", w: 6800, theme: "dark", density: "comfortable", scr: "SCR-031 · CMP-228", plan: "6800 × 1300" },
  { n: 7, slug: "chrome-and-roles", w: 10880, theme: "dark", density: "comfortable", scr: "SCR-031 · CMP-044 · CMP-079", plan: "10880 × 1300" },
  { n: 8, slug: "general-populated-light", w: 2720, theme: "light", density: "comfortable", scr: "SCR-031 · CMP-043", plan: "2720 × 1300", twin: 1 },
  { n: 9, slug: "validation-light", w: 1360, theme: "light", density: "comfortable", scr: "SCR-031 · CMP-008", plan: "1360 × 1400", twin: 4 },
  { n: 10, slug: "general-populated-hc", w: 2720, theme: "high-contrast", density: "comfortable", scr: "SCR-031 · CMP-043", plan: "2720 × 1300", twin: 1 },
];
const NOT_DRAWN = []; // every §0 board is drawn (lever 4 already applied by the spec: 10 boards, 3 light twins)
const GAP = 160; // one row, 160 px apart; board n sits at x = Σ widths of boards 1..n−1 + (n − 1) × GAP, y = 0
const TOKEN_PROPS = { fill: "fill", stroke: "strokeColor", type: "typography" }; // the plugin API's TokenProperty names (check with penpot_api_info "TokenProperty" before the first bound run)

// ---------------------------------------------------------------- per-call budget (never edited by the runner) ----
// the orchestrator's ruling (2026-10-23 18:46Z, every board script): one plugin call creates at most SHAPE_BUDGET shapes and
// SEG_BUDGET path segments, the page holds at most PAGE_SEG_BUDGET path segments; texture or noise is an image fill
const SHAPE_BUDGET = 400; // shapes one plugin call may create, the board frame counted
const SEG_BUDGET = 5000; // path segments one plugin call may create (this script draws no path: 0 on every call)
const PAGE_SEG_BUDGET = 20000; // path segments the page may hold
const PART_SHAPES = 250; // r2: a board over SHAPE_BUDGET is cut into K = ceil(shapes / PART_SHAPES) near-equal runs of its creation sequence (at most 250 shapes per call: the 120 s bridge timeout on a big page)

// ---------------------------------------------------------------- single writer -----------------------------
if (typeof storage === "undefined" || storage.hpe1inst !== WRITER) {
  return { skip: typeof storage === "undefined" ? null : storage.hpe1inst, note: "not the writer instance — run probe.js, pick one stamp, set WRITER" };
}

// ---------------------------------------------------------------- guard (the page comes after the parts plan) --
const warnings = [];
const warn = (where, e) => warnings.push(where + ": " + (e && e.message ? e.message : String(e)));
if (FILE_ID === "SET-ME" || !penpot.currentFile || penpot.currentFile.id !== FILE_ID) {
  return { abort: "file", note: FILE_ID === "SET-ME" ? "FILE_ID is not set (the runner sets it at load time)" : "the open file is not FILE_ID", current: penpot.currentFile ? { name: penpot.currentFile.name } : null };
}
if (!Array.isArray(ONLY) || ONLY.length !== 1 || !Number.isInteger(ONLY[0]) || !BOARDS.some((bd) => bd.n === ONLY[0])) {
  return { abort: "only", note: "ONLY must be [n] with one board number of the BOARDS table (one board per call); nothing was touched" };
}
if (NOT_DRAWN.includes(ONLY[0])) { // refused before anything is touched (no page found or made, nothing removed)
  return { abort: "not-drawn", board: ONLY[0], note: "board " + String(ONLY[0]).padStart(2, "0") + " " + BOARDS.find((bd) => bd.n === ONLY[0]).slug + " is not drawn (NOT_DRAWN); nothing was touched" };
}
if (!(PART === null || (Number.isInteger(PART) && PART >= 0))) { // refused before anything is touched
  throw new Error("PART " + JSON.stringify(PART) + ": null (one call), 0 (the parts plan) or a part number 1..K; nothing was touched");
}
const norm = (s) => String(s || "").replace(/\s*\/\s*/g, "/");
// the page (found by name, or created on PART null / 1) and the clear come after the record, the parts plan and the budget
// guard (the PARTS sections near the end), so a refused call touches nothing
// ---------------------------------------------------------------- the audit tools' numbers (generated by tools/gen_audit.py; never typed by hand) ----
// E12-D05: `python3 -I docs/design/_tools/e12_d05_settings_audit.py --json` at the PR head cec8310a6d (the spec's audit tool): values{BUDGET:*}
// by key without the "BUDGET:" prefix; COUNT:*, LIM:*, D03:*, FIX:*, HEX:*, CONTRAST:* as they are; extra{} flattened (parity.<mode>,
// d03_order, chart_types, contrast.<theme>.<pair>, themes_json): the bounds, defaults, counts, the viewport and the §13 values.
// E15-D03 (merged c4989493, #4478): its audit tool's --json on that tree (work/audit-d03.json), only the values its merged chrome builders
// read (41-chrome.js, 42-d03.js: the shell rows v.*, h.*, focus.*, the header widths hdr.*, the parent splits parent.*, dense / scalping).
// A board reads A("menu.w") and so on; an unknown key warns and draws "?" (never a guessed number).
const AV = {
  "v.topbar": "80", "v.statusbar": "48", "v.banner.compact": "32", "v.tabstrip.compact": "32", "v.restore.compact": "32", "v.tabgroup.compact": "24",
  "v.header.compact": "24", "v.status.compact": "24", "v.timestrip.compact": "24", "v.tray.compact": "24", "v.allowance.compact": "232",
  "v.conditional.compact": "112", "v.ceiling.compact": "344", "v.share.compact": "56", "v.banner.comfortable": "40", "v.tabstrip.comfortable": "40",
  "v.restore.comfortable": "40", "v.tabgroup.comfortable": "32", "v.header.comfortable": "32", "v.status.comfortable": "32", "v.timestrip.comfortable": "32",
  "v.tray.comfortable": "32", "v.allowance.comfortable": "264", "v.conditional.comfortable": "144", "v.ceiling.comfortable": "408",
  "v.share.comfortable": "72", "h.navrail": "64", "h.rightrail-strip": "48", "h.gutter": "4", "h.hitband": "24", "h.header-inset": "12",
  "focus.frame-px": "2 px", "focus.frame-axis-px": "4 px", "focus.bar-px": "3 px", "h.hitband-reach": "10 px", "h.hitband-into-content": "8 px",
  "h.hitband-control-yield": "8 px", "hit.handle.compact": "24×24", "hit.badge-visual.compact": "20", "hit.badge.compact": "24",
  "hit.handle.comfortable": "32×32", "hit.badge-visual.comfortable": "28", "hit.badge.comfortable": "32", "hdr.chart.full": "713", "hdr.chart.s1": "555",
  "hdr.chart.s3": "393", "hdr.chart.s4": "362", "hdr.chart.s5": "334", "hdr.chart.s6": "308", "hdr.chart.min": "308", "hdr.chart.min.comfortable": "340",
  "hdr.dom.full": "688", "hdr.dom.s1": "688", "hdr.dom.s2": "540", "hdr.dom.s3": "507", "hdr.dom.s4": "476", "hdr.dom.s5": "448", "hdr.dom.s6": "378",
  "hdr.dom.min": "378", "hdr.dom.min.comfortable": "414", "hdr.tape.full": "436", "hdr.tape.s1": "320", "hdr.tape.s3": "287", "hdr.tape.s5": "259",
  "hdr.tape.s6": "233", "hdr.tape.min": "233", "hdr.tape.min.comfortable": "261", "hdr.positions.full": "318", "hdr.positions.s1": "318",
  "hdr.positions.s5": "290", "hdr.positions.min": "290", "hdr.positions.min.comfortable": "318", "hdr.dom.min.parent": 380, "hdr.dom.min.framed": "382",
  "hdr.dom.min.comfortable.framed": 418, "hdr.tape.min.comfortable.framed": 265, "canvas.1280": "1168×672", "dock.1280.compact": "1168×640",
  "scalping.split.1280.compact": "698 / 466", "dense.split.1280.compact": "522 / 383 / 255", "dock.1280.comfortable": "1168×632",
  "scalping.split.1280.comfortable": "698 / 466", "dense.split.1280.comfortable": "477 / 418 / 265", "canvas.1920": "1808×952",
  "dock.1920.compact": "1808×920", "scalping.split.1920.compact": "1082 / 722", "dense.split.1920.compact": "810 / 594 / 396",
  "dock.1920.comfortable": "1808×912", "scalping.split.1920.comfortable": "1082 / 722", "dense.split.1920.comfortable": "810 / 594 / 396",
  "hdr.chart.full.comfortable": 769, "hdr.chart.s1.comfortable": 595, "hdr.chart.s3.comfortable": 433, "hdr.chart.s4.comfortable": 402,
  "hdr.chart.s5.comfortable": 366, "hdr.chart.s6.comfortable": 340, "hdr.dom.full.comfortable": 736, "hdr.dom.s1.comfortable": 736,
  "hdr.dom.s2.comfortable": 588, "hdr.dom.s3.comfortable": 555, "hdr.dom.s4.comfortable": 524, "hdr.dom.s5.comfortable": 488, "hdr.dom.s6.comfortable": 414,
  "hdr.tape.full.comfortable": 508, "hdr.tape.s1.comfortable": 356, "hdr.tape.s3.comfortable": 323, "hdr.tape.s5.comfortable": 287,
  "hdr.tape.s6.comfortable": 261, "hdr.positions.full.comfortable": 354, "hdr.positions.s1.comfortable": 354, "hdr.positions.s5.comfortable": 318,
  "hdr.chart.full.parent": 741, "hdr.chart.full.delta": -28, "hdr.chart.min.parent": 328, "hdr.chart.min.delta": -20, "hdr.dom.full.parent": 655,
  "hdr.dom.full.delta": 33, "hdr.dom.min.delta": -2, "hdr.tape.s1.parent": 299, "hdr.tape.s1.delta": 21, "hdr.tape.min.parent": 232, "hdr.tape.min.delta": 1,
  "hdr.positions.min.parent": 274, "hdr.positions.min.delta": 16, "hdr.chart.min.framed": 312, "hdr.chart.min.comfortable.framed": 344,
  "hdr.positions.min.comfortable.framed": 322, "dense.split.1280.compact.parent": "522 / 383 / 255", "dense.split.1280.comfortable.parent": "522 / 383 / 255",
  "dense.split.1280.comfortable.moved": 45, "dense.split.1920.compact.parent": "810 / 594 / 396", "dense.split.1920.comfortable.parent": "810 / 594 / 396",
  "parent.topbar": 80.0, "parent.statusbar": 48.0, "parent.navrail": 64.0, "parent.rightrail": 48.0, "parent.allowance.compact": 232.0,
  "parent.allowance.comfortable": 264.0, "parent.conditional.compact": 112.0, "parent.conditional.comfortable": 144.0, "parent.ceiling.compact": 344.0,
  "parent.share.compact": 56.0, "parent.share.comfortable": 72.0, "parent.price_gutter.compact": 48.0, "parent.price_gutter.comfortable": 56.0,
  "parent.inset": 12.0, "parent.handle": 16.0, "parent.gap": 8.0, "parent.icon": 24.0, "parent.icon_gap": 4.0, "parent.kind": 28.0, "parent.symbol": 80.0,
  "parent.interval": 40.0, "parent.badge.count": 36.0, "parent.badge.one": 75.0, "parent.badge.three": 205.0, "parent.env": 56.0, "parent.arm.short": 76.0,
  "parent.arm.full": 100.0, "parent.prov.full": 176.0, "parent.prov.short": 34.0, "parent.chart.actions": 184.0, "parent.positions.min": 274.0,
  "parent.cluster.1280": 390.0, "parent.tabs.1280": 776.0, "parent.reason.viewer": 220.0, "parent.reason.limit": 290.0, "parent.p95.now": 11.8,
  "parent.p95.est": 17.9, "parent.budget.ms": 16.0, "parent.refresh": 60.0, "parent.scalping.row": 0.6, "parent.scalping.col": 0.6, "parent.dense.0": 0.45,
  "parent.dense.1": 0.33, "parent.dense.2": 0.22, "parent.canvas.1920.w": 1808.0, "parent.canvas.1920.h": 952.0, "parent.canvas.1280.w": 1168.0,
  "parent.canvas.1280.h": 672.0, "parent.chart.full": 741.0, "parent.chart.min": 328.0, "parent.dom.full": 655.0, "parent.dom.min": 380.0,
  "parent.tape.full": 299.0, "parent.tape.min": 232.0, "build-per-m": "10", "param.max-len": "24", "row.comfortable": "32", "target.min": "24",
  "type-switch": "100", "viewport.h": "800", "viewport.w": "1280", "CONTRAST:action-overlay.dark": "3.36:1", "CONTRAST:action-overlay.hc": "6.15:1",
  "CONTRAST:action-overlay.light": "3.80:1", "CONTRAST:danger-overlay.dark": "8.61:1", "CONTRAST:danger-overlay.hc": "8.61:1",
  "CONTRAST:danger-overlay.light": "3.77:1", "CONTRAST:danger-sunken.dark": "11.30:1", "CONTRAST:danger-sunken.hc": "11.30:1",
  "CONTRAST:danger-sunken.light": "3.37:1", "CONTRAST:infostrong-info.dark": "7.30:1", "CONTRAST:infostrong-info.hc": "7.30:1",
  "CONTRAST:infostrong-info.light": "4.33:1", "CONTRAST:mark.min": "3:1", "CONTRAST:onaction-action.dark": "4.75:1", "CONTRAST:onaction-action.hc": "7.44:1",
  "CONTRAST:onaction-action.light": "4.75:1", "CONTRAST:primary-app.dark": "16.05:1", "CONTRAST:primary-app.hc": "18.17:1",
  "CONTRAST:primary-app.light": "17.99:1", "CONTRAST:primary-info.dark": "10.73:1", "CONTRAST:primary-info.hc": "12.15:1",
  "CONTRAST:primary-info.light": "15.44:1", "CONTRAST:primary-overlay.dark": "13.26:1", "CONTRAST:primary-overlay.hc": "15.02:1",
  "CONTRAST:primary-overlay.light": "14.37:1", "CONTRAST:primary-selected.dark": "10.16:1", "CONTRAST:primary-selected.hc": "11.51:1",
  "CONTRAST:primary-selected.light": "12.82:1", "CONTRAST:ring-app.dark": "7.44:1", "CONTRAST:ring-app.hc": "19.35:1", "CONTRAST:ring-app.light": "6.75:1",
  "CONTRAST:ring-overlay.dark": "6.15:1", "CONTRAST:ring-overlay.hc": "15.99:1", "CONTRAST:ring-overlay.light": "5.39:1",
  "CONTRAST:ring-raised.dark": "6.65:1", "CONTRAST:ring-raised.hc": "17.29:1", "CONTRAST:ring-raised.light": "5.86:1", "CONTRAST:ring-selected.dark": "4.71:1",
  "CONTRAST:ring-selected.hc": "12.25:1", "CONTRAST:ring-selected.light": "4.81:1", "CONTRAST:secondary-overlay.dark": "8.14:1",
  "CONTRAST:secondary-overlay.hc": "13.26:1", "CONTRAST:secondary-overlay.light": "8.26:1", "CONTRAST:secondary-raised.dark": "8.80:1",
  "CONTRAST:secondary-raised.hc": "14.35:1", "CONTRAST:secondary-raised.light": "8.98:1", "CONTRAST:secondary-sunken.dark": "10.69:1",
  "CONTRAST:secondary-sunken.hc": "17.42:1", "CONTRAST:secondary-sunken.light": "7.37:1", "CONTRAST:tertiary-app.dark": "6.29:1",
  "CONTRAST:tertiary-app.hc": "12.53:1", "CONTRAST:tertiary-app.light": "6.81:1", "CONTRAST:tertiary-overlay.dark": "5.19:1",
  "CONTRAST:tertiary-overlay.hc": "10.36:1", "CONTRAST:tertiary-overlay.light": "5.44:1", "CONTRAST:tertiary-raised.dark": "5.62:1",
  "CONTRAST:tertiary-raised.hc": "11.20:1", "CONTRAST:tertiary-raised.light": "5.91:1", "CONTRAST:tertiary-sunken.dark": "6.82:1",
  "CONTRAST:tertiary-sunken.hc": "13.60:1", "CONTRAST:tertiary-sunken.light": "4.85:1", "CONTRAST:text.min": "4.5:1", "COUNT:boards": "10",
  "COUNT:boards.dark": "7", "COUNT:boards.max": "10", "COUNT:boards.twins": "3", "COUNT:frames.drawn": "30", "COUNT:lines.budget": "600",
  "COUNT:lines.budget-handoff": "150", "COUNT:modes": "6", "COUNT:pairs": "20", "COUNT:twins.max-share": "one third", "COUNT:types": "9",
  "D03:default.delta": "25", "D03:default.range": "40", "D03:default.renko": "30", "D03:default.tick": "1,000", "D03:default.volume": "50",
  "D03:estimate-delay": "300", "FIX:btc.floor": "1", "FIX:btc.qty-step": "0.001", "FIX:btc.tick": "0.1", "HEX:action.primary.default.dark": "#2B6CE8",
  "HEX:action.primary.default.hc": "#6EA1F5", "HEX:action.primary.default.light": "#2B6CE8", "HEX:focus.ring.dark": "#6EA1F5", "HEX:focus.ring.hc": "#FFFFFF",
  "HEX:focus.ring.light": "#1F55BF", "HEX:status.danger.strong.dark": "#F0B441", "HEX:status.danger.strong.hc": "#F0B441",
  "HEX:status.danger.strong.light": "#9A6A05", "HEX:surface.app.dark": "#0B0E11", "HEX:surface.app.hc": "#0B0E11", "HEX:surface.app.light": "#FFFFFF",
  "HEX:surface.overlay.dark": "#1C222B", "HEX:surface.overlay.hc": "#1C222B", "HEX:surface.overlay.light": "#E3E6EA", "HEX:surface.sunken.dark": "#000000",
  "HEX:surface.sunken.hc": "#000000", "HEX:surface.sunken.light": "#D6DAE0", "HEX:text.primary.dark": "#E8EAED", "HEX:text.primary.hc": "#F6F8FA",
  "HEX:text.primary.light": "#14171A", "HEX:text.secondary.dark": "#B1BAC4", "HEX:text.secondary.hc": "#E8EAED", "HEX:text.secondary.light": "#3A4148",
  "HEX:text.tertiary.dark": "#8B949E", "HEX:text.tertiary.hc": "#C9D1D9", "HEX:text.tertiary.light": "#525C66", "LIM:qty.max": "1,000,000,000,000",
  "LIM:qty.min-steps": "10", "LIM:range.max": "100,000", "LIM:range.min": "2", "LIM:renko.max": "100,000", "LIM:renko.min": "2", "LIM:tick.max": "1,000,000",
  "LIM:tick.min": "100", "parity.tick": "\"Trades per bar\", trades, whole number, 1,000, 100 to 1,000,000 (`bars/limits.py:62`), C-7",
  "parity.volume": "\"Volume per bar\", the base asset, whole, 50 (D3-11), whole; at least max(10 × qty step, 1), BTCUSDT 1; at most 1,000,000,000,000 (`bars/limits.py:70-74`; `bars/spec.py:161-196`), C-8, C-10",
  "parity.range": "\"Range per bar\", ticks, whole, 40, 2 to 100,000 (`bars/limits.py:63`), C-11",
  "parity.delta": "\"Delta per bar (±)\", the base asset, whole, 25 (D3-11), as Volume (`bars/spec.py:161-168`), C-9, C-10",
  "parity.renko": "\"Brick size\", ticks, whole, 30, 2 to 100,000; `atr:` held (`bars/limits.py:65`; `bars/models.py:53-59`; `bars/spec.py:58-60`), C-11, C-12",
  "d03_order": "time, tick, volume, range, delta, renko", "chart_types": "candle, hollow, bar, line, area, baseline, heikin-ashi, equi-volume, delta-volume",
  "contrast.dark.primary-overlay": 13.269, "contrast.dark.secondary-overlay": 8.141, "contrast.dark.tertiary-overlay": 5.2,
  "contrast.dark.primary-app": 16.056, "contrast.dark.tertiary-app": 6.292, "contrast.dark.ring-overlay": 6.153, "contrast.dark.ring-app": 7.446,
  "contrast.dark.action-overlay": 3.361, "contrast.dark.onaction-action": 4.759, "contrast.dark.danger-overlay": 8.613, "contrast.dark.primary-info": 10.737,
  "contrast.dark.infostrong-info": 7.303, "contrast.dark.primary-selected": 10.169, "contrast.dark.secondary-raised": 8.806,
  "contrast.dark.tertiary-raised": 5.624, "contrast.dark.secondary-sunken": 10.69, "contrast.dark.tertiary-sunken": 6.827, "contrast.dark.ring-raised": 6.655,
  "contrast.dark.ring-selected": 4.715, "contrast.dark.danger-sunken": 11.31, "contrast.light.primary-overlay": 14.37,
  "contrast.light.secondary-overlay": 8.264, "contrast.light.tertiary-overlay": 5.443, "contrast.light.primary-app": 17.991,
  "contrast.light.tertiary-app": 6.815, "contrast.light.ring-overlay": 5.393, "contrast.light.ring-app": 6.752, "contrast.light.action-overlay": 3.801,
  "contrast.light.onaction-action": 4.759, "contrast.light.danger-overlay": 3.78, "contrast.light.primary-info": 15.443,
  "contrast.light.infostrong-info": 4.336, "contrast.light.primary-selected": 12.82, "contrast.light.secondary-raised": 8.982,
  "contrast.light.tertiary-raised": 5.916, "contrast.light.secondary-sunken": 7.373, "contrast.light.tertiary-sunken": 4.856,
  "contrast.light.ring-raised": 5.862, "contrast.light.ring-selected": 4.812, "contrast.light.danger-sunken": 3.372, "contrast.hc.primary-overlay": 15.023,
  "contrast.hc.secondary-overlay": 13.269, "contrast.hc.tertiary-overlay": 10.362, "contrast.hc.primary-app": 18.178, "contrast.hc.tertiary-app": 12.538,
  "contrast.hc.ring-overlay": 15.993, "contrast.hc.ring-app": 19.352, "contrast.hc.action-overlay": 6.153, "contrast.hc.onaction-action": 7.446,
  "contrast.hc.danger-overlay": 8.613, "contrast.hc.primary-info": 12.156, "contrast.hc.infostrong-info": 7.303, "contrast.hc.primary-selected": 11.513,
  "contrast.hc.secondary-raised": 14.352, "contrast.hc.tertiary-raised": 11.207, "contrast.hc.secondary-sunken": 17.423, "contrast.hc.tertiary-sunken": 13.606,
  "contrast.hc.ring-raised": 17.298, "contrast.hc.ring-selected": 12.256, "contrast.hc.danger-sunken": 11.31, "themes_json": "dark, light, high-contrast",
};
function A(key) { if (!Object.prototype.hasOwnProperty.call(AV, key)) { warn("audit", "no audit value " + key); return "?"; } return AV[key]; }
const AN = (key) => parseFloat(String(A(key))); // the number of an audit value ("2 px" → 2, "29.0 %" → 29)
const AWH = (key) => String(A(key)).split("×").map(Number); // "1168×672" → [1168, 672]
const ARECT = (key) => { const v = String(A(key)).split(",").map((s) => Number(s.trim())); if (v.length !== 4 || v.some((x) => !Number.isFinite(x))) warn("audit", key + " is not a rectangle: " + A(key)); return { x: v[0], y: v[1], w: v[2], h: v[3] }; }; // "32, 32, 319, 343" → { x, y, w, h } (§5.6)
// ---------------------------------------------------------------- the §15.1 frame register (generated by tools/gen_register.py) ----
// Spec §15.1 at the PR head (cec8310a6d): 30 rows (§15.1 counts them as its drawn frames); each board draws exactly its rows, each
// frame is named exactly as the row's Frame cell, and its caption prints the row's cells (State, Components, Copy, Tokens, Status;
// anchors reduced to their value, backticks dropped). The twins (08, 09, 10) have rows of their own ("as 01", "as 04").
const REG = [
  {"frame": "general/populated · dark", "board": "01", "theme": "dark", "state": "Candles, Time 1m, defaults", "components": "CMP-043, CMP-042, CMP-065, CMP-006, CMP-009, CMP-228, CMP-003, CMP-001", "copy": "W-1, W-2, W-8, W-9", "tokens": "color.surface.overlay, color.text.primary, color.text.secondary, color.action.primary.default", "status": "PENDING"},
  {"frame": "types/radio-list · dark", "board": "02", "theme": "dark", "state": "the nine options with their lines", "components": "CMP-006", "copy": "W-2, W-3", "tokens": "color.text.primary, color.text.secondary, color.action.primary.default", "status": "PENDING"},
  {"frame": "types/baseline-base · dark", "board": "02", "theme": "dark", "state": "Baseline, Price chosen, snapped", "components": "CMP-006, CMP-100", "copy": "W-4", "tokens": "color.surface.app, color.text.tertiary", "status": "PENDING"},
  {"frame": "types/ha-footprint · dark", "board": "02", "theme": "dark", "state": "the AC4 callout, then each outcome: Heikin-Ashi on with footprint off, or the type kept", "components": "CMP-028, CMP-001", "copy": "W-5", "tokens": "color.status.info.subtle, color.status.info.strong, color.text.primary", "status": "PENDING"},
  {"frame": "types/ha-non-time · dark", "board": "02", "theme": "dark", "state": "HA on Volume bars", "components": "CMP-028, CMP-001", "copy": "W-6", "tokens": "color.status.info.subtle, color.status.info.strong, color.text.primary", "status": "PENDING"},
  {"frame": "modes/volume-field · dark", "board": "03", "theme": "dark", "state": "Volume 50, valid", "components": "CMP-006, CMP-008, CMP-069", "copy": "C-3, C-40, W-7", "tokens": "color.surface.app, color.text.primary, color.text.tertiary", "status": "PENDING"},
  {"frame": "modes/estimate-states · dark", "board": "03", "theme": "dark", "state": "estimating, built, failed, too many, may pass", "components": "CMP-008", "copy": "C-15, C-16, C-17, C-18, C-19, C-20", "tokens": "color.text.secondary, color.status.danger.strong", "status": "PENDING"},
  {"frame": "modes/needs-build · dark", "board": "03", "theme": "dark", "state": "the tag on options", "components": "CMP-006", "copy": "C-30", "tokens": "color.text.secondary", "status": "PENDING"},
  {"frame": "modes/no-prints · dark", "board": "03", "theme": "dark", "state": "every non-time option T2", "components": "CMP-006, CMP-079", "copy": "C-24", "tokens": "color.text.tertiary, color.text.secondary", "status": "PENDING"},
  {"frame": "modes/lot-unknown · dark", "board": "03", "theme": "dark", "state": "Volume and Delta T2", "components": "CMP-006, CMP-079", "copy": "C-25", "tokens": "color.text.tertiary, color.text.secondary", "status": "PENDING"},
  {"frame": "validation/specimens · dark", "board": "04", "theme": "dark", "state": "§4.2's rows", "components": "CMP-008, CMP-040", "copy": "C-7, C-8, C-9, C-10, C-11, C-12", "tokens": "color.status.danger.strong, color.text.primary, color.surface.app", "status": "PENDING"},
  {"frame": "scope/partial-apply · dark", "board": "05", "theme": "dark", "state": "All panels, 3 of 4", "components": "CMP-003, CMP-065", "copy": "W-11, C-24, C-25", "tokens": "color.text.secondary, color.text.tertiary", "status": "PENDING"},
  {"frame": "scope/outcome · dark", "board": "05", "theme": "dark", "state": "after Save: the changed panels' builds, the unchanged panel's strip notice", "components": "D02 NC-1, CMP-001", "copy": "W-12, W-24", "tokens": "color.text.primary", "status": "PENDING"},
  {"frame": "scope/default-notice · dark", "board": "05", "theme": "dark", "state": "As new default saved, posted after the build", "components": "D02 NC-1, CMP-001", "copy": "W-13, W-14", "tokens": "color.text.primary, color.status.info.subtle", "status": "PENDING"},
  {"frame": "preview/live · dark", "board": "06", "theme": "dark", "state": "a chart type, live", "components": "CMP-228", "copy": "W-20", "tokens": "color.surface.sunken, color.text.tertiary", "status": "PENDING"},
  {"frame": "preview/cached · dark", "board": "06", "theme": "dark", "state": "a held bar mode", "components": "CMP-228", "copy": "W-20", "tokens": "color.surface.sunken, color.text.tertiary", "status": "PENDING"},
  {"frame": "preview/renko-sample · dark", "board": "06", "theme": "dark", "state": "Renko 30, not built (AC2)", "components": "CMP-228", "copy": "W-19, W-20, C-6", "tokens": "color.surface.sunken, color.text.tertiary, color.text.secondary", "status": "PENDING"},
  {"frame": "preview/empty · dark", "board": "06", "theme": "dark", "state": "no bars loaded", "components": "CMP-228", "copy": "—", "tokens": "color.surface.sunken, color.text.secondary", "status": "PENDING"},
  {"frame": "preview/error · dark", "board": "06", "theme": "dark", "state": "chart error", "components": "CMP-228", "copy": "—", "tokens": "color.surface.sunken, color.status.danger.strong", "status": "PENDING"},
  {"frame": "reset/general · dark", "board": "07", "theme": "dark", "state": "the General confirm, bar mode changing", "components": "CMP-044", "copy": "W-15, W-25", "tokens": "color.surface.overlay, color.text.primary", "status": "PENDING"},
  {"frame": "reset/all · dark", "board": "07", "theme": "dark", "state": "the global confirm", "components": "CMP-044", "copy": "W-16, W-25", "tokens": "color.surface.overlay, color.text.primary", "status": "PENDING"},
  {"frame": "chrome/dirty-guard · dark", "board": "07", "theme": "dark", "state": "Esc with changes", "components": "CMP-044", "copy": "W-17, W-22", "tokens": "color.surface.overlay, color.focus.ring", "status": "PENDING"},
  {"frame": "chrome/saving · dark", "board": "07", "theme": "dark", "state": "Save busy", "components": "CMP-001", "copy": "—", "tokens": "color.action.primary.default, color.text.on-action", "status": "PENDING"},
  {"frame": "chrome/save-failed · dark", "board": "07", "theme": "dark", "state": "Save failed", "components": "CMP-028, CMP-001", "copy": "W-18", "tokens": "color.status.danger.strong, color.text.primary", "status": "PENDING"},
  {"frame": "roles/viewer · dark", "board": "07", "theme": "dark", "state": "Viewer: Save and As new default T2", "components": "CMP-079, CMP-065", "copy": "W-23", "tokens": "color.text.tertiary, color.surface.raised", "status": "PENDING"},
  {"frame": "roles/view-as · dark", "board": "07", "theme": "dark", "state": "viewing as", "components": "CMP-079", "copy": "W-26", "tokens": "color.text.tertiary, color.surface.raised", "status": "PENDING"},
  {"frame": "keyboard/storyboard · dark", "board": "07", "theme": "dark", "state": "§11's two walks, step by step", "components": "CMP-043, CMP-042, CMP-044", "copy": "C-8, W-15, W-25", "tokens": "color.focus.ring", "status": "PENDING"},
  {"frame": "general/populated · light", "board": "08", "theme": "light", "state": "as 01", "components": "CMP-043, CMP-042, CMP-065, CMP-006, CMP-009, CMP-228, CMP-003, CMP-001", "copy": "W-1, W-2, W-8, W-9", "tokens": "color.surface.overlay, color.text.primary, color.text.secondary, color.action.primary.default", "status": "PENDING"},
  {"frame": "validation/specimens · light", "board": "09", "theme": "light", "state": "as 04", "components": "CMP-008, CMP-040", "copy": "C-7, C-8, C-9, C-10, C-11, C-12", "tokens": "color.status.danger.strong, color.text.primary, color.surface.app", "status": "PENDING"},
  {"frame": "general/populated · hc", "board": "10", "theme": "hc", "state": "as 01", "components": "CMP-043, CMP-042, CMP-065, CMP-006, CMP-009, CMP-228, CMP-003, CMP-001", "copy": "W-1, W-2, W-8, W-9", "tokens": "color.surface.overlay, color.text.primary, color.text.secondary, color.action.primary.default", "status": "PENDING"},
];
const TWIN_OF = { 8: 1, 9: 4, 10: 1 }; // spec §0: 08 = light twin of 01, 09 = light twin of 04, 10 = high-contrast twin of 01
function regRows(n) { return REG.filter((r) => Number(r.board) === n); }
const regState = (r) => { const m = /^([a-z-]+)\/([A-Za-z0-9-]+) · /.exec(r.frame); return m ? m[1] + "/" + m[2] : null; }; // "types/ha-footprint · dark" → "types/ha-footprint"
// ---------------------------------------------------------------- the recorded fixtures (generated by tools/gen_data.py; never typed by hand) ----
// packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page0.json sha256 f0057b3966600d4976dc3cd45a02fd69ec9a9e1e2d51e0f57c270c8187c66cb0
// packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page1.json sha256 060d171157b7f83c2d2176b7725a0751d9a524221562e2d4bb6e0ca2898b9663
// packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page2.json sha256 9bc92ee015be46ae7082824437f1308d5a38db92874878d9d0ea0818b72e3db4
// packages/fixtures/bybit/2026-10-05/ws/clean_publicTrade_BTCUSDT.jsonl sha256 e7ba4ff2c4cc374d50f5a542441ae62a7b68ba4d8dc561c165d0ddd15281d816
// packages/fixtures/bybit/2026-10-05/rest/instruments_before.json sha256 57417cbb2b59b93b41a2bd41f32112559d6e0606a147d6b3d1eb9b13521b0a75
// (manifest.json: source "documented-shape (exception #1778 A)", capture_date 2026-10-05; the paths spec §0 names, present at the base)
// KL: the 450 BTCUSDT 1m klines, chronological: [open time ms, open, high, low, close, volume BTC] (1699999980000 … 1700026920000)
// TR: the 542 publicTrade prints in file order: [T ms, taker side +1 Buy / -1 Sell, size BTC, price]
const KL = [
  [1699999980000,63000.0,63001.5,62994.5,62996.0,13.33],[1700000040000,62996.0,62999.0,62994.5,62997.5,36.18],
  [1700000100000,62997.5,63000.0,62996.0,62998.5,80.88],[1700000160000,62998.5,63004.0,62997.0,63002.5,19.43],
  [1700000220000,63002.5,63009.0,63001.0,63007.5,44.68],[1700000280000,63007.5,63009.0,62997.5,62999.0,47.16],
  [1700000340000,62999.0,63000.5,62993.0,62994.5,16.61],[1700000400000,62994.5,62996.0,62989.5,62991.0,40.1],
  [1700000460000,62991.0,62992.5,62984.5,62986.0,1.46],[1700000520000,62986.0,62987.5,62978.5,62980.0,88.54],
  [1700000580000,62980.0,62981.5,62969.0,62970.5,53.65],[1700000640000,62970.5,62975.0,62969.0,62973.5,17.57],
  [1700000700000,62973.5,62977.5,62972.0,62976.0,58.54],[1700000760000,62976.0,62985.5,62974.5,62984.0,39.75],
  [1700000820000,62984.0,62985.5,62975.0,62976.5,9.51],[1700000880000,62976.5,62978.0,62974.5,62976.0,87.05],
  [1700000940000,62976.0,62977.5,62972.5,62974.0,68.12],[1700001000000,62974.0,62975.5,62970.0,62971.5,65.65],
  [1700001060000,62971.5,62973.0,62963.5,62965.0,67.78],[1700001120000,62965.0,62970.0,62963.5,62968.5,88.43],
  [1700001180000,62968.5,62970.0,62958.0,62959.5,37.17],[1700001240000,62959.5,62961.0,62952.5,62954.0,66.64],
  [1700001300000,62954.0,62964.0,62952.5,62962.5,42.1],[1700001360000,62962.5,62966.0,62961.0,62964.5,39.36],
  [1700001420000,62964.5,62971.5,62963.0,62970.0,21.66],[1700001480000,62970.0,62971.5,62967.0,62968.5,52.53],
  [1700001540000,62968.5,62974.5,62967.0,62973.0,78.8],[1700001600000,62973.0,62978.0,62971.5,62976.5,85.57],
  [1700001660000,62976.5,62981.0,62975.0,62979.5,5.23],[1700001720000,62979.5,62985.5,62978.0,62984.0,0.29],
  [1700001780000,62984.0,62985.5,62974.0,62975.5,21.98],[1700001840000,62975.5,62982.5,62974.0,62981.0,86.61],
  [1700001900000,62981.0,62986.0,62979.5,62984.5,78.46],[1700001960000,62984.5,62986.0,62975.5,62977.0,53.87],
  [1700002020000,62977.0,62978.5,62974.5,62976.0,81.55],[1700002080000,62976.0,62985.0,62974.5,62983.5,6.43],
  [1700002140000,62983.5,62990.0,62982.0,62988.5,69.11],[1700002200000,62988.5,62990.0,62979.5,62981.0,26.36],
  [1700002260000,62981.0,62982.5,62977.0,62978.5,75.99],[1700002320000,62978.5,62980.0,62969.5,62971.0,68.87],
  [1700002380000,62971.0,62972.5,62960.5,62962.0,53.46],[1700002440000,62962.0,62971.0,62960.5,62969.5,53.83],
  [1700002500000,62969.5,62974.5,62968.0,62973.0,80.53],[1700002560000,62973.0,62974.5,62970.5,62972.0,68.68],
  [1700002620000,62972.0,62973.5,62966.0,62967.5,47.13],[1700002680000,62967.5,62969.0,62966.0,62967.5,35.81],
  [1700002740000,62967.5,62969.0,62961.0,62962.5,41.98],[1700002800000,62962.5,62964.0,62956.0,62957.5,51.31],
  [1700002860000,62957.5,62969.0,62956.0,62967.5,34.88],[1700002920000,62967.5,62972.0,62966.0,62970.5,64.73],
  [1700002980000,62970.5,62972.0,62967.0,62968.5,85.9],[1700003040000,62968.5,62976.5,62967.0,62975.0,41.43],
  [1700003100000,62975.0,62982.0,62973.5,62980.5,15.89],[1700003160000,62980.5,62982.0,62972.5,62974.0,39.77],
  [1700003220000,62974.0,62980.0,62972.5,62978.5,70.84],[1700003280000,62978.5,62980.5,62977.0,62979.0,37.38],
  [1700003340000,62979.0,62980.5,62975.5,62977.0,56.63],[1700003400000,62977.0,62978.5,62968.0,62969.5,2.1],
  [1700003460000,62969.5,62974.0,62968.0,62972.5,76.7],[1700003520000,62972.5,62977.0,62971.0,62975.5,26.27],
  [1700003580000,62975.5,62977.0,62966.0,62967.5,9.97],[1700003640000,62967.5,62978.5,62966.0,62977.0,72.78],
  [1700003700000,62977.0,62979.0,62975.5,62977.5,58.61],[1700003760000,62977.5,62980.5,62976.0,62979.0,34.95],
  [1700003820000,62979.0,62983.0,62977.5,62981.5,33.76],[1700003880000,62981.5,62985.0,62980.0,62983.5,6.97],
  [1700003940000,62983.5,62993.0,62982.0,62991.5,58.73],[1700004000000,62991.5,62993.0,62982.5,62984.0,70.34],
  [1700004060000,62984.0,62989.0,62982.5,62987.5,47.51],[1700004120000,62987.5,62994.0,62986.0,62992.5,32.56],
  [1700004180000,62992.5,62994.0,62982.5,62984.0,66.66],[1700004240000,62984.0,62985.5,62977.5,62979.0,85.71],
  [1700004300000,62979.0,62980.5,62970.5,62972.0,46.34],[1700004360000,62972.0,62977.5,62970.5,62976.0,83.6],
  [1700004420000,62976.0,62978.0,62974.5,62976.5,74.53],[1700004480000,62976.5,62978.5,62975.0,62977.0,47.26],
  [1700004540000,62977.0,62978.5,62969.0,62970.5,1.54],[1700004600000,62970.5,62972.0,62968.5,62970.0,31.77],
  [1700004660000,62970.0,62977.0,62968.5,62975.5,17.36],[1700004720000,62975.5,62977.0,62970.0,62971.5,51.92],
  [1700004780000,62971.5,62976.5,62970.0,62975.0,57.46],[1700004840000,62975.0,62982.0,62973.5,62980.5,61.14],
  [1700004900000,62980.5,62982.0,62974.0,62975.5,38.32],[1700004960000,62975.5,62977.0,62973.0,62974.5,18.92],
  [1700005020000,62974.5,62976.0,62965.5,62967.0,37.78],[1700005080000,62967.0,62968.5,62960.5,62962.0,0.37],
  [1700005140000,62962.0,62963.5,62956.0,62957.5,20.75],[1700005200000,62957.5,62969.0,62956.0,62967.5,9.61],
  [1700005260000,62967.5,62971.0,62966.0,62969.5,28.23],[1700005320000,62969.5,62971.0,62967.0,62968.5,66.54],
  [1700005380000,62968.5,62971.5,62967.0,62970.0,35.31],[1700005440000,62970.0,62971.5,62961.5,62963.0,33.19],
  [1700005500000,62963.0,62964.5,62953.0,62954.5,49.71],[1700005560000,62954.5,62958.0,62953.0,62956.5,79.66],
  [1700005620000,62956.5,62958.0,62955.0,62956.5,71.59],[1700005680000,62956.5,62958.0,62952.0,62953.5,6.85],
  [1700005740000,62953.5,62955.0,62945.5,62947.0,60.39],[1700005800000,62947.0,62958.0,62945.5,62956.5,5.34],
  [1700005860000,62956.5,62966.0,62955.0,62964.5,15.78],[1700005920000,62964.5,62966.0,62957.5,62959.0,81.01],
  [1700005980000,62959.0,62960.5,62956.0,62957.5,18.89],[1700006040000,62957.5,62966.5,62956.0,62965.0,20.59],
  [1700006100000,62965.0,62966.5,62958.0,62959.5,18.98],[1700006160000,62959.5,62961.0,62952.5,62954.0,29.84],
  [1700006220000,62954.0,62955.5,62948.0,62949.5,53.49],[1700006280000,62949.5,62951.0,62940.5,62942.0,62.24],
  [1700006340000,62942.0,62943.5,62937.0,62938.5,78.25],[1700006400000,62938.5,62943.5,62937.0,62942.0,25.26],
  [1700006460000,62942.0,62944.0,62940.5,62942.5,54.58],[1700006520000,62942.5,62946.0,62941.0,62944.5,10.17],
  [1700006580000,62944.5,62946.0,62942.0,62943.5,75.85],[1700006640000,62943.5,62953.0,62942.0,62951.5,2.63],
  [1700006700000,62951.5,62958.0,62950.0,62956.5,47.31],[1700006760000,62956.5,62958.0,62946.0,62947.5,8.21],
  [1700006820000,62947.5,62958.5,62946.0,62957.0,29.94],[1700006880000,62957.0,62958.5,62955.5,62957.0,83.07],
  [1700006940000,62957.0,62961.0,62955.5,62959.5,41.94],[1700007000000,62959.5,62964.5,62958.0,62963.0,64.83],
  [1700007060000,62963.0,62964.5,62961.0,62962.5,34.6],[1700007120000,62962.5,62964.0,62957.0,62958.5,5.89],
  [1700007180000,62958.5,62968.0,62957.0,62966.5,57.13],[1700007240000,62966.5,62968.5,62965.0,62967.0,54.86],
  [1700007300000,62967.0,62971.5,62965.5,62970.0,18.4],[1700007360000,62970.0,62971.5,62960.5,62962.0,33.75],
  [1700007420000,62962.0,62970.0,62960.5,62968.5,57.95],[1700007480000,62968.5,62973.5,62967.0,62972.0,17.82],
  [1700007540000,62972.0,62973.5,62960.5,62962.0,71.14],[1700007600000,62962.0,62970.0,62960.5,62968.5,4.95],
  [1700007660000,62968.5,62980.0,62967.0,62978.5,27],[1700007720000,62978.5,62980.0,62967.5,62969.0,25.65],
  [1700007780000,62969.0,62970.5,62958.5,62960.0,39.17],[1700007840000,62960.0,62961.5,62949.5,62951.0,6.89],
  [1700007900000,62951.0,62955.5,62949.5,62954.0,54],[1700007960000,62954.0,62964.5,62952.5,62963.0,59.86],
  [1700008020000,62963.0,62964.5,62961.0,62962.5,84.98],[1700008080000,62962.5,62970.0,62961.0,62968.5,22.26],
  [1700008140000,62968.5,62979.5,62967.0,62978.0,42.54],[1700008200000,62978.0,62988.5,62976.5,62987.0,32.34],
  [1700008260000,62987.0,62998.5,62985.5,62997.0,14.39],[1700008320000,62997.0,62998.5,62988.0,62989.5,3.07],
  [1700008380000,62989.5,62991.0,62987.5,62989.0,31.28],[1700008440000,62989.0,62990.5,62980.5,62982.0,40.88],
  [1700008500000,62982.0,62991.5,62980.5,62990.0,41.69],[1700008560000,62990.0,62991.5,62980.0,62981.5,22.98],
  [1700008620000,62981.5,62983.0,62972.0,62973.5,27.14],[1700008680000,62973.5,62984.5,62972.0,62983.0,71.1],
  [1700008740000,62983.0,62993.5,62981.5,62992.0,20.21],[1700008800000,62992.0,62998.5,62990.5,62997.0,26.71],
  [1700008860000,62997.0,62998.5,62988.5,62990.0,30.51],[1700008920000,62990.0,62991.5,62987.5,62989.0,40.74],
  [1700008980000,62989.0,62994.0,62987.5,62992.5,58.19],[1700009040000,62992.5,63001.0,62991.0,62999.5,35.81],
  [1700009100000,62999.5,63001.0,62989.0,62990.5,23.78],[1700009160000,62990.5,62992.0,62986.5,62988.0,47.18],
  [1700009220000,62988.0,62997.0,62986.5,62995.5,63.2],[1700009280000,62995.5,62997.0,62988.0,62989.5,23.71],
  [1700009340000,62989.5,62991.0,62981.5,62983.0,21.19],[1700009400000,62983.0,62984.5,62972.0,62973.5,67.63],
  [1700009460000,62973.5,62975.0,62964.5,62966.0,34.11],[1700009520000,62966.0,62974.0,62964.5,62972.5,37.01],
  [1700009580000,62972.5,62974.0,62968.5,62970.0,89.85],[1700009640000,62970.0,62971.5,62965.0,62966.5,40.16],
  [1700009700000,62966.5,62968.0,62964.0,62965.5,30.12],[1700009760000,62965.5,62974.5,62964.0,62973.0,50.43],
  [1700009820000,62973.0,62979.0,62971.5,62977.5,82.18],[1700009880000,62977.5,62979.0,62970.5,62972.0,84.69],
  [1700009940000,62972.0,62973.5,62961.5,62963.0,19.13],[1700010000000,62963.0,62964.5,62961.0,62962.5,62.93],
  [1700010060000,62962.5,62966.0,62961.0,62964.5,49.43],[1700010120000,62964.5,62966.0,62957.5,62959.0,37.24],
  [1700010180000,62959.0,62968.0,62957.5,62966.5,25],[1700010240000,62966.5,62972.5,62965.0,62971.0,7.43],
  [1700010300000,62971.0,62972.5,62961.0,62962.5,70.41],[1700010360000,62962.5,62964.0,62957.5,62959.0,77.34],
  [1700010420000,62959.0,62960.5,62952.5,62954.0,84.25],[1700010480000,62954.0,62956.0,62952.5,62954.5,64.04],
  [1700010540000,62954.5,62956.0,62944.0,62945.5,13.17],[1700010600000,62945.5,62950.0,62944.0,62948.5,4.55],
  [1700010660000,62948.5,62952.5,62947.0,62951.0,18.96],[1700010720000,62951.0,62952.5,62942.5,62944.0,83.97],
  [1700010780000,62944.0,62950.0,62942.5,62948.5,57.68],[1700010840000,62948.5,62950.0,62937.0,62938.5,10.77],
  [1700010900000,62938.5,62942.5,62937.0,62941.0,16.24],[1700010960000,62941.0,62942.5,62937.0,62938.5,61.79],
  [1700011020000,62938.5,62940.0,62929.0,62930.5,46.75],[1700011080000,62930.5,62932.0,62925.0,62926.5,58.73],
  [1700011140000,62926.5,62928.0,62918.0,62919.5,54.03],[1700011200000,62919.5,62921.0,62912.0,62913.5,0.42],
  [1700011260000,62913.5,62915.0,62904.5,62906.0,3.81],[1700011320000,62906.0,62907.5,62897.0,62898.5,13.59],
  [1700011380000,62898.5,62900.0,62889.5,62891.0,26.82],[1700011440000,62891.0,62892.5,62889.0,62890.5,3.12],
  [1700011500000,62890.5,62896.0,62889.0,62894.5,74.15],[1700011560000,62894.5,62896.0,62891.5,62893.0,11.1],
  [1700011620000,62893.0,62894.5,62881.5,62883.0,62.75],[1700011680000,62883.0,62884.5,62874.0,62875.5,76.72],
  [1700011740000,62875.5,62881.5,62874.0,62880.0,51.56],[1700011800000,62880.0,62881.5,62868.5,62870.0,41.46],
  [1700011860000,62870.0,62871.5,62859.5,62861.0,63.16],[1700011920000,62861.0,62862.5,62851.5,62853.0,7.01],
  [1700011980000,62853.0,62854.5,62847.5,62849.0,62.24],[1700012040000,62849.0,62850.5,62838.0,62839.5,64.52],
  [1700012100000,62839.5,62848.0,62838.0,62846.5,43.32],[1700012160000,62846.5,62848.0,62838.5,62840.0,35.71],
  [1700012220000,62840.0,62851.5,62838.5,62850.0,41.76],[1700012280000,62850.0,62854.5,62848.5,62853.0,67.12],
  [1700012340000,62853.0,62860.0,62851.5,62858.5,8.65],[1700012400000,62858.5,62864.0,62857.0,62862.5,59.65],
  [1700012460000,62862.5,62867.0,62861.0,62865.5,39.51],[1700012520000,62865.5,62867.0,62856.5,62858.0,71.79],
  [1700012580000,62858.0,62859.5,62856.0,62857.5,7.04],[1700012640000,62857.5,62864.5,62856.0,62863.0,48.41],
  [1700012700000,62863.0,62865.0,62861.5,62863.5,72.08],[1700012760000,62863.5,62865.5,62862.0,62864.0,65.75],
  [1700012820000,62864.0,62865.5,62853.0,62854.5,66.11],[1700012880000,62854.5,62856.0,62845.5,62847.0,2.95],
  [1700012940000,62847.0,62848.5,62843.5,62845.0,87.97],[1700013000000,62845.0,62846.5,62838.0,62839.5,72.25],
  [1700013060000,62839.5,62841.0,62830.5,62832.0,48.75],[1700013120000,62832.0,62833.5,62828.0,62829.5,14.29],
  [1700013180000,62829.5,62836.0,62828.0,62834.5,9.02],[1700013240000,62834.5,62842.5,62833.0,62841.0,26.39],
  [1700013300000,62841.0,62850.5,62839.5,62849.0,83.61],[1700013360000,62849.0,62850.5,62841.0,62842.5,58.32],
  [1700013420000,62842.5,62854.0,62841.0,62852.5,75.68],[1700013480000,62852.5,62854.0,62849.5,62851.0,89.63],
  [1700013540000,62851.0,62852.5,62841.5,62843.0,2.94],[1700013600000,62843.0,62844.5,62837.5,62839.0,74.21],
  [1700013660000,62839.0,62847.5,62837.5,62846.0,21.93],[1700013720000,62846.0,62847.5,62835.0,62836.5,84.52],
  [1700013780000,62836.5,62838.0,62828.0,62829.5,88.73],[1700013840000,62829.5,62840.0,62828.0,62838.5,48.73],
  [1700013900000,62838.5,62840.0,62829.5,62831.0,75.12],[1700013960000,62831.0,62832.5,62822.5,62824.0,70.2],
  [1700014020000,62824.0,62829.0,62822.5,62827.5,27.26],[1700014080000,62827.5,62829.0,62822.5,62824.0,77.75],
  [1700014140000,62824.0,62825.5,62820.5,62822.0,15.19],[1700014200000,62822.0,62823.5,62819.5,62821.0,43.12],
  [1700014260000,62821.0,62830.0,62819.5,62828.5,30.98],[1700014320000,62828.5,62830.0,62820.5,62822.0,21.31],
  [1700014380000,62822.0,62833.5,62820.5,62832.0,83.8],[1700014440000,62832.0,62833.5,62825.5,62827.0,78.19],
  [1700014500000,62827.0,62834.0,62825.5,62832.5,29.26],[1700014560000,62832.5,62838.0,62831.0,62836.5,22.91],
  [1700014620000,62836.5,62844.0,62835.0,62842.5,53.37],[1700014680000,62842.5,62844.0,62839.5,62841.0,3.59],
  [1700014740000,62841.0,62849.0,62839.5,62847.5,62.06],[1700014800000,62847.5,62849.0,62843.0,62844.5,64.82],
  [1700014860000,62844.5,62853.5,62843.0,62852.0,25.88],[1700014920000,62852.0,62853.5,62845.5,62847.0,21.67],
  [1700014980000,62847.0,62848.5,62837.0,62838.5,27.16],[1700015040000,62838.5,62846.5,62837.0,62845.0,7.07],
  [1700015100000,62845.0,62846.5,62838.5,62840.0,21.31],[1700015160000,62840.0,62846.5,62838.5,62845.0,51.84],
  [1700015220000,62845.0,62854.0,62843.5,62852.5,47.78],[1700015280000,62852.5,62854.0,62841.0,62842.5,42.62],
  [1700015340000,62842.5,62844.0,62832.0,62833.5,11.56],[1700015400000,62833.5,62835.0,62831.0,62832.5,56.04],
  [1700015460000,62832.5,62835.0,62831.0,62833.5,13.21],[1700015520000,62833.5,62835.0,62823.5,62825.0,62.8],
  [1700015580000,62825.0,62826.5,62817.5,62819.0,41],[1700015640000,62819.0,62827.5,62817.5,62826.0,82.21],
  [1700015700000,62826.0,62835.0,62824.5,62833.5,53.53],[1700015760000,62833.5,62835.0,62828.5,62830.0,58.87],
  [1700015820000,62830.0,62832.0,62828.5,62830.5,69.03],[1700015880000,62830.5,62838.0,62829.0,62836.5,88.11],
  [1700015940000,62836.5,62838.0,62827.5,62829.0,34.45],[1700016000000,62829.0,62833.5,62827.5,62832.0,68.93],
  [1700016060000,62832.0,62837.5,62830.5,62836.0,37.67],[1700016120000,62836.0,62846.5,62834.5,62845.0,54.02],
  [1700016180000,62845.0,62846.5,62842.5,62844.0,84.6],[1700016240000,62844.0,62850.0,62842.5,62848.5,71],
  [1700016300000,62848.5,62853.0,62847.0,62851.5,33.28],[1700016360000,62851.5,62853.0,62842.0,62843.5,84.49],
  [1700016420000,62843.5,62853.0,62842.0,62851.5,70.24],[1700016480000,62851.5,62855.0,62850.0,62853.5,78.38],
  [1700016540000,62853.5,62855.0,62846.5,62848.0,72.15],[1700016600000,62848.0,62849.5,62838.5,62840.0,16.52],
  [1700016660000,62840.0,62841.5,62830.0,62831.5,48.63],[1700016720000,62831.5,62835.0,62830.0,62833.5,62.05],
  [1700016780000,62833.5,62835.0,62824.5,62826.0,32.19],[1700016840000,62826.0,62836.0,62824.5,62834.5,18.51],
  [1700016900000,62834.5,62836.0,62833.0,62834.5,83.62],[1700016960000,62834.5,62836.0,62824.0,62825.5,62.01],
  [1700017020000,62825.5,62827.0,62823.0,62824.5,58.72],[1700017080000,62824.5,62826.0,62814.5,62816.0,67.64],
  [1700017140000,62816.0,62817.5,62811.5,62813.0,39.56],[1700017200000,62813.0,62814.5,62806.5,62808.0,51.11],
  [1700017260000,62808.0,62809.5,62806.5,62808.0,61.09],[1700017320000,62808.0,62809.5,62798.0,62799.5,9.84],
  [1700017380000,62799.5,62803.0,62798.0,62801.5,5.56],[1700017440000,62801.5,62803.0,62799.5,62801.0,30.12],
  [1700017500000,62801.0,62803.0,62799.5,62801.5,14.78],[1700017560000,62801.5,62803.0,62791.0,62792.5,11.8],
  [1700017620000,62792.5,62802.0,62791.0,62800.5,12.13],[1700017680000,62800.5,62805.5,62799.0,62804.0,54.78],
  [1700017740000,62804.0,62805.5,62793.5,62795.0,80.59],[1700017800000,62795.0,62796.5,62788.5,62790.0,69.09],
  [1700017860000,62790.0,62791.5,62788.5,62790.0,75.61],[1700017920000,62790.0,62791.5,62784.0,62785.5,72.45],
  [1700017980000,62785.5,62789.5,62784.0,62788.0,34.99],[1700018040000,62788.0,62789.5,62784.5,62786.0,1.65],
  [1700018100000,62786.0,62790.5,62784.5,62789.0,66.06],[1700018160000,62789.0,62796.5,62787.5,62795.0,66.22],
  [1700018220000,62795.0,62797.5,62793.5,62796.0,33.73],[1700018280000,62796.0,62802.0,62794.5,62800.5,21.68],
  [1700018340000,62800.5,62802.0,62795.5,62797.0,51.7],[1700018400000,62797.0,62806.0,62795.5,62804.5,20.16],
  [1700018460000,62804.5,62806.0,62797.5,62799.0,77.94],[1700018520000,62799.0,62808.5,62797.5,62807.0,86.54],
  [1700018580000,62807.0,62817.0,62805.5,62815.5,78.69],[1700018640000,62815.5,62823.5,62814.0,62822.0,13.46],
  [1700018700000,62822.0,62823.5,62819.5,62821.0,8.42],[1700018760000,62821.0,62826.5,62819.5,62825.0,36.16],
  [1700018820000,62825.0,62826.5,62818.5,62820.0,44.43],[1700018880000,62820.0,62823.5,62818.5,62822.0,54.51],
  [1700018940000,62822.0,62830.5,62820.5,62829.0,35.43],[1700019000000,62829.0,62830.5,62821.0,62822.5,30.43],
  [1700019060000,62822.5,62824.0,62820.5,62822.0,79.12],[1700019120000,62822.0,62833.0,62820.5,62831.5,19.5],
  [1700019180000,62831.5,62837.5,62830.0,62836.0,21.85],[1700019240000,62836.0,62843.0,62834.5,62841.5,23.51],
  [1700019300000,62841.5,62843.0,62836.5,62838.0,79.19],[1700019360000,62838.0,62842.5,62836.5,62841.0,78.14],
  [1700019420000,62841.0,62852.5,62839.5,62851.0,26.1],[1700019480000,62851.0,62862.5,62849.5,62861.0,36.65],
  [1700019540000,62861.0,62865.5,62859.5,62864.0,50.96],[1700019600000,62864.0,62866.0,62862.5,62864.5,26.3],
  [1700019660000,62864.5,62866.0,62859.0,62860.5,36.86],[1700019720000,62860.5,62862.0,62856.5,62858.0,3.61],
  [1700019780000,62858.0,62859.5,62852.0,62853.5,49.37],[1700019840000,62853.5,62860.5,62852.0,62859.0,68.68],
  [1700019900000,62859.0,62860.5,62851.5,62853.0,77.05],[1700019960000,62853.0,62861.5,62851.5,62860.0,67.32],
  [1700020020000,62860.0,62861.5,62853.5,62855.0,74.21],[1700020080000,62855.0,62856.5,62853.0,62854.5,40.31],
  [1700020140000,62854.5,62864.5,62853.0,62863.0,10.1],[1700020200000,62863.0,62871.0,62861.5,62869.5,21.97],
  [1700020260000,62869.5,62871.0,62862.0,62863.5,69.22],[1700020320000,62863.5,62866.5,62862.0,62865.0,49.46],
  [1700020380000,62865.0,62870.0,62863.5,62868.5,45.53],[1700020440000,62868.5,62870.0,62863.5,62865.0,84.23],
  [1700020500000,62865.0,62867.0,62863.5,62865.5,42.39],[1700020560000,62865.5,62870.5,62864.0,62869.0,22.7],
  [1700020620000,62869.0,62874.0,62867.5,62872.5,9.03],[1700020680000,62872.5,62875.0,62871.0,62873.5,81.27],
  [1700020740000,62873.5,62875.0,62865.5,62867.0,25.2],[1700020800000,62867.0,62868.5,62857.5,62859.0,49.12],
  [1700020860000,62859.0,62870.5,62857.5,62869.0,8.21],[1700020920000,62869.0,62870.5,62864.0,62865.5,83.88],
  [1700020980000,62865.5,62867.0,62863.0,62864.5,79.85],[1700021040000,62864.5,62866.0,62855.0,62856.5,13.24],
  [1700021100000,62856.5,62858.5,62855.0,62857.0,69.94],[1700021160000,62857.0,62858.5,62853.0,62854.5,49],
  [1700021220000,62854.5,62856.5,62853.0,62855.0,10.3],[1700021280000,62855.0,62866.0,62853.5,62864.5,16.12],
  [1700021340000,62864.5,62873.0,62863.0,62871.5,49.63],[1700021400000,62871.5,62873.0,62863.5,62865.0,13.1],
  [1700021460000,62865.0,62874.5,62863.5,62873.0,27.17],[1700021520000,62873.0,62876.0,62871.5,62874.5,43.74],
  [1700021580000,62874.5,62876.5,62873.0,62875.0,12.43],[1700021640000,62875.0,62878.0,62873.5,62876.5,25.23],
  [1700021700000,62876.5,62888.0,62875.0,62886.5,68.43],[1700021760000,62886.5,62888.0,62884.0,62885.5,36.11],
  [1700021820000,62885.5,62887.0,62884.0,62885.5,14.29],[1700021880000,62885.5,62890.5,62884.0,62889.0,69.82],
  [1700021940000,62889.0,62899.5,62887.5,62898.0,67.07],[1700022000000,62898.0,62908.5,62896.5,62907.0,4.72],
  [1700022060000,62907.0,62908.5,62899.5,62901.0,48.02],[1700022120000,62901.0,62902.5,62890.0,62891.5,46.8],
  [1700022180000,62891.5,62893.0,62884.0,62885.5,9.63],[1700022240000,62885.5,62887.0,62877.0,62878.5,32.66],
  [1700022300000,62878.5,62880.0,62873.5,62875.0,66.78],[1700022360000,62875.0,62876.5,62872.0,62873.5,28.23],
  [1700022420000,62873.5,62879.5,62872.0,62878.0,65.34],[1700022480000,62878.0,62886.5,62876.5,62885.0,47.23],
  [1700022540000,62885.0,62886.5,62875.5,62877.0,28.77],[1700022600000,62877.0,62886.5,62875.5,62885.0,2.8],
  [1700022660000,62885.0,62896.5,62883.5,62895.0,68.16],[1700022720000,62895.0,62896.5,62885.0,62886.5,40.84],
  [1700022780000,62886.5,62889.5,62885.0,62888.0,34.5],[1700022840000,62888.0,62889.5,62878.0,62879.5,53],
  [1700022900000,62879.5,62881.0,62877.5,62879.0,61.57],[1700022960000,62879.0,62886.0,62877.5,62884.5,69.34],
  [1700023020000,62884.5,62886.0,62882.5,62884.0,17.07],[1700023080000,62884.0,62891.5,62882.5,62890.0,86.67],
  [1700023140000,62890.0,62891.5,62882.5,62884.0,17.56],[1700023200000,62884.0,62892.0,62882.5,62890.5,60.28],
  [1700023260000,62890.5,62895.0,62889.0,62893.5,21.26],[1700023320000,62893.5,62900.0,62892.0,62898.5,60.71],
  [1700023380000,62898.5,62906.0,62897.0,62904.5,75.78],[1700023440000,62904.5,62906.0,62894.0,62895.5,70.81],
  [1700023500000,62895.5,62907.0,62894.0,62905.5,6.02],[1700023560000,62905.5,62909.0,62904.0,62907.5,81.78],
  [1700023620000,62907.5,62909.0,62903.5,62905.0,89.18],[1700023680000,62905.0,62906.5,62893.5,62895.0,20.55],
  [1700023740000,62895.0,62896.5,62886.0,62887.5,23.67],[1700023800000,62887.5,62893.5,62886.0,62892.0,50.08],
  [1700023860000,62892.0,62895.5,62890.5,62894.0,17.84],[1700023920000,62894.0,62900.5,62892.5,62899.0,65.43],
  [1700023980000,62899.0,62907.0,62897.5,62905.5,56.11],[1700024040000,62905.5,62914.5,62904.0,62913.0,8.07],
  [1700024100000,62913.0,62915.5,62911.5,62914.0,74.29],[1700024160000,62914.0,62915.5,62911.0,62912.5,41.99],
  [1700024220000,62912.5,62915.0,62911.0,62913.5,15.86],[1700024280000,62913.5,62917.5,62912.0,62916.0,74.35],
  [1700024340000,62916.0,62926.0,62914.5,62924.5,5.69],[1700024400000,62924.5,62935.0,62923.0,62933.5,33.43],
  [1700024460000,62933.5,62935.0,62922.5,62924.0,26.42],[1700024520000,62924.0,62928.0,62922.5,62926.5,72.14],
  [1700024580000,62926.5,62928.0,62920.0,62921.5,81.28],[1700024640000,62921.5,62925.5,62920.0,62924.0,59.51],
  [1700024700000,62924.0,62926.0,62922.5,62924.5,17.99],[1700024760000,62924.5,62926.0,62916.0,62917.5,12.35],
  [1700024820000,62917.5,62919.0,62912.5,62914.0,46.82],[1700024880000,62914.0,62915.5,62904.5,62906.0,16.33],
  [1700024940000,62906.0,62907.5,62900.0,62901.5,0.16],[1700025000000,62901.5,62909.5,62900.0,62908.0,83.86],
  [1700025060000,62908.0,62909.5,62898.5,62900.0,72.2],[1700025120000,62900.0,62908.0,62898.5,62906.5,89.85],
  [1700025180000,62906.5,62916.5,62905.0,62915.0,76.83],[1700025240000,62915.0,62916.5,62905.5,62907.0,80.46],
  [1700025300000,62907.0,62915.0,62905.5,62913.5,11.43],[1700025360000,62913.5,62915.0,62906.0,62907.5,85.61],
  [1700025420000,62907.5,62909.0,62902.5,62904.0,66.73],[1700025480000,62904.0,62915.0,62902.5,62913.5,5.72],
  [1700025540000,62913.5,62921.0,62912.0,62919.5,7.16],[1700025600000,62919.5,62925.0,62918.0,62923.5,74.34],
  [1700025660000,62923.5,62929.0,62922.0,62927.5,89.12],[1700025720000,62927.5,62929.0,62921.0,62922.5,81.18],
  [1700025780000,62922.5,62924.5,62921.0,62923.0,19.06],[1700025840000,62923.0,62930.5,62921.5,62929.0,76.36],
  [1700025900000,62929.0,62930.5,62923.0,62924.5,15.48],[1700025960000,62924.5,62926.0,62913.0,62914.5,77.96],
  [1700026020000,62914.5,62920.0,62913.0,62918.5,80.2],[1700026080000,62918.5,62920.0,62915.0,62916.5,79.73],
  [1700026140000,62916.5,62922.5,62915.0,62921.0,89.83],[1700026200000,62921.0,62922.5,62914.5,62916.0,82],
  [1700026260000,62916.0,62917.5,62910.5,62912.0,81.07],[1700026320000,62912.0,62919.0,62910.5,62917.5,48.47],
  [1700026380000,62917.5,62924.5,62916.0,62923.0,43.66],[1700026440000,62923.0,62924.5,62919.0,62920.5,74.83],
  [1700026500000,62920.5,62922.0,62909.5,62911.0,40.78],[1700026560000,62911.0,62912.5,62909.5,62911.0,7.14],
  [1700026620000,62911.0,62912.5,62908.0,62909.5,32.89],[1700026680000,62909.5,62913.0,62908.0,62911.5,62.91],
  [1700026740000,62911.5,62913.0,62900.5,62902.0,42.42],[1700026800000,62902.0,62903.5,62898.5,62900.0,73.68],
  [1700026860000,62900.0,62901.5,62895.0,62896.5,46.45],[1700026920000,62896.5,62898.0,62890.0,62891.5,86.22]
].map((r) => ({ t: r[0], o: r[1], h: r[2], l: r[3], c: r[4], v: r[5] }));
const TR = [
  [1699999999995,1,0.131,63120.60],[1700000029995,-1,0.242,63120.60],[1700000059995,1,0.049,63120.90],[1700000059995,1,0.458,63120.90],
  [1700000089995,1,0.357,63120.90],[1700000089995,-1,0.370,63120.90],[1700000119995,1,0.462,63121.00],[1700000149995,1,0.014,63120.70],
  [1700000149995,1,0.481,63120.90],[1700000179995,1,0.497,63121.10],[1700000179995,1,0.271,63121.10],[1700000209995,-1,0.481,63121.40],
  [1700000239995,1,0.177,63121.50],[1700000239995,1,0.390,63121.30],[1700000269995,1,0.214,63121.20],[1700000269995,1,0.096,63121.50],
  [1700000299995,-1,0.459,63121.20],[1700000299995,-1,0.260,63121.40],[1700000329995,-1,0.301,63121.30],[1700000359995,-1,0.302,63121.60],
  [1700000359995,1,0.246,63121.90],[1700000389995,-1,0.213,63122.10],[1700000419995,-1,0.045,63122.00],[1700000449995,1,0.399,63122.20],
  [1700000449995,-1,0.190,63122.00],[1700000479995,1,0.241,63122.20],[1700000479995,-1,0.361,63121.90],[1700000509995,1,0.087,63122.10],
  [1700000509995,1,0.007,63122.20],[1700000539995,1,0.208,63122.30],[1700000569995,-1,0.236,63122.60],[1700000569995,1,0.197,63122.50],
  [1700000599995,1,0.219,63122.60],[1700000629995,-1,0.292,63122.60],[1700000659995,-1,0.249,63122.70],[1700000689995,-1,0.001,63122.70],
  [1700000689995,-1,0.235,63122.80],[1700000719995,1,0.326,63123.10],[1700000749995,1,0.441,63123.20],[1700000779995,-1,0.017,63123.50],
  [1700000809995,1,0.232,63123.20],[1700000839995,-1,0.128,63123.50],[1700000869995,1,0.177,63123.20],[1700000869995,1,0.086,63123.10],
  [1700000899995,1,0.337,63123.00],[1700000929995,-1,0.233,63123.20],[1700000929995,-1,0.255,63123.40],[1700000959995,1,0.160,63123.10],
  [1700000959995,-1,0.216,63123.10],[1700000989995,1,0.130,63123.00],[1700001019995,-1,0.419,63123.10],[1700001049995,1,0.204,63122.90],
  [1700001079995,1,0.229,63122.60],[1700001109995,1,0.500,63122.70],[1700001109995,-1,0.115,63122.90],[1700001139995,-1,0.338,63122.90],
  [1700001169995,-1,0.065,63122.60],[1700001169995,1,0.157,63122.40],[1700001199995,1,0.159,63122.70],[1700001229995,1,0.214,63122.90],
  [1700001229995,-1,0.067,63123.00],[1700001259995,1,0.303,63123.10],[1700001289995,-1,0.088,63123.20],[1700001319995,1,0.178,63123.20],
  [1700001349995,-1,0.303,63123.00],[1700001379995,1,0.481,63123.00],[1700001409995,-1,0.009,63122.90],[1700001409995,-1,0.461,63122.80],
  [1700001439995,1,0.103,63122.50],[1700001439995,-1,0.416,63122.80],[1700001469995,-1,0.110,63122.70],[1700001499995,1,0.429,63122.90],
  [1700001499995,-1,0.469,63122.90],[1700001529995,1,0.034,63123.20],[1700001529995,1,0.044,63123.40],[1700001559995,1,0.467,63123.20],
  [1700001589995,-1,0.308,63123.10],[1700001619995,-1,0.175,63123.00],[1700001619995,-1,0.121,63122.70],[1700001649995,1,0.165,63122.50],
  [1700001649995,-1,0.038,63122.20],[1700001679995,1,0.425,63122.50],[1700001679995,-1,0.059,63122.30],[1700001709995,1,0.290,63122.00],
  [1700001709995,-1,0.187,63121.70],[1700001739995,1,0.235,63121.80],[1700001739995,1,0.403,63121.70],[1700001769995,-1,0.007,63122.00],
  [1700001799995,-1,0.059,63121.70],[1700001829995,1,0.403,63121.50],[1700001859995,1,0.231,63121.30],[1700001859995,1,0.082,63121.10],
  [1700001889995,-1,0.413,63121.10],[1700001919995,-1,0.365,63121.20],[1700001919995,-1,0.052,63121.20],[1700001949995,-1,0.021,63121.40],
  [1700001979995,-1,0.372,63121.10],[1700002009995,-1,0.161,63121.10],[1700002009995,1,0.033,63121.10],[1700002039995,-1,0.058,63121.20],
  [1700002039995,1,0.402,63121.10],[1700002069995,-1,0.133,63121.30],[1700002069995,1,0.158,63121.10],[1700002099995,-1,0.042,63120.90],
  [1700002129995,-1,0.047,63120.60],[1700002129995,-1,0.482,63120.80],[1700002159995,-1,0.022,63120.80],[1700002189995,-1,0.406,63120.60],
  [1700002189995,-1,0.126,63120.90],[1700002219995,1,0.126,63120.60],[1700002219995,1,0.414,63120.40],[1700002249995,1,0.138,63120.40],
  [1700002279995,1,0.012,63120.60],[1700002309995,-1,0.253,63120.50],[1700002339995,1,0.052,63120.80],[1700002339995,-1,0.040,63120.90],
  [1700002369995,1,0.073,63120.70],[1700002399995,1,0.364,63120.60],[1700002399995,-1,0.065,63120.70],[1700002429995,1,0.400,63120.50],
  [1700002459995,1,0.092,63120.80],[1700002459995,-1,0.276,63120.70],[1700002489995,1,0.130,63120.40],[1700002519995,-1,0.414,63120.60],
  [1700002549995,-1,0.278,63120.70],[1700002549995,-1,0.006,63120.70],[1700002579995,-1,0.088,63121.00],[1700002579995,-1,0.013,63120.90],
  [1700002609995,1,0.032,63121.00],[1700002609995,-1,0.297,63121.20],[1700002639995,1,0.071,63121.30],[1700002669995,-1,0.204,63121.60],
  [1700002669995,-1,0.089,63121.70],[1700002699995,-1,0.004,63121.50],[1700002729995,-1,0.257,63121.60],[1700002759995,1,0.123,63121.80],
  [1700002759995,-1,0.352,63121.70],[1700002789995,-1,0.173,63121.50],[1700002789995,-1,0.498,63121.60],[1700002819995,1,0.391,63121.30],
  [1700002849995,1,0.160,63121.10],[1700002849995,-1,0.435,63121.00],[1700002879995,-1,0.305,63120.80],[1700002879995,1,0.460,63120.50],
  [1700002909995,1,0.129,63120.30],[1700002909995,1,0.483,63120.30],[1700002939995,-1,0.368,63120.30],[1700002969995,1,0.279,63120.30],
  [1700002969995,1,0.269,63120.50],[1700002999995,-1,0.322,63120.80],[1700003029995,1,0.492,63120.70],[1700003059995,1,0.228,63121.00],
  [1700003089995,-1,0.482,63121.30],[1700003119995,1,0.466,63121.30],[1700003119995,-1,0.065,63121.20],[1700003149995,1,0.221,63121.00],
  [1700003149995,-1,0.466,63121.10],[1700003179995,-1,0.143,63121.30],[1700003209995,1,0.492,63121.30],[1700003239995,-1,0.297,63121.40],
  [1700003269995,1,0.428,63121.10],[1700003299995,1,0.146,63120.90],[1700003299995,1,0.140,63120.70],[1700003329995,-1,0.427,63120.80],
  [1700003329995,-1,0.406,63121.00],[1700003359995,-1,0.252,63121.10],[1700003389995,1,0.394,63121.40],[1700003389995,-1,0.105,63121.20],
  [1700003419995,1,0.463,63121.50],[1700003419995,1,0.061,63121.80],[1700003449995,-1,0.495,63121.90],[1700003479995,-1,0.294,63121.60],
  [1700003509995,-1,0.389,63121.60],[1700003509995,-1,0.001,63121.70],[1700003539995,-1,0.180,63121.70],[1700003569995,-1,0.174,63121.80],
  [1700003569995,-1,0.058,63122.10],[1700003599995,1,0.286,63122.10],[1700003599995,-1,0.326,63121.80],[1700003629995,-1,0.480,63121.80],
  [1700003659995,1,0.231,63122.00],[1700003659995,1,0.185,63122.10],[1700003689995,-1,0.297,63122.30],[1700003719995,-1,0.441,63122.30],
  [1700003719995,1,0.253,63122.40],[1700003749995,-1,0.323,63122.60],[1700003779995,1,0.325,63122.60],[1700003809995,-1,0.434,63122.90],
  [1700003809995,1,0.418,63122.70],[1700003839995,-1,0.409,63122.60],[1700003869995,-1,0.078,63122.90],[1700003869995,-1,0.249,63122.90],
  [1700003899995,1,0.139,63122.90],[1700003929995,-1,0.036,63123.10],[1700003959995,-1,0.011,63122.80],[1700003959995,1,0.354,63122.60],
  [1700003989995,-1,0.310,63122.60],[1700004019995,1,0.122,63122.40],[1700004019995,-1,0.036,63122.30],[1700004049995,-1,0.240,63122.50],
  [1700004079995,-1,0.335,63122.30],[1700004109995,1,0.201,63122.20],[1700004109995,-1,0.089,63122.30],[1700004139995,-1,0.444,63122.60],
  [1700004139995,-1,0.367,63122.70],[1700004169995,1,0.433,63122.60],[1700004199995,-1,0.163,63122.90],[1700004229995,1,0.403,63123.20],
  [1700004229995,1,0.038,63123.10],[1700004259995,-1,0.298,63123.40],[1700004289995,-1,0.236,63123.50],[1700004319995,1,0.458,63123.30],
  [1700004349995,-1,0.385,63123.20],[1700004349995,1,0.060,63123.20],[1700004379995,-1,0.035,63123.40],[1700004409995,-1,0.165,63123.20],
  [1700004439995,1,0.024,63122.90],[1700004439995,1,0.456,63122.60],[1700004469995,1,0.254,63122.80],[1700004499995,-1,0.061,63122.70],
  [1700004499995,1,0.049,63122.80],[1700004529995,1,0.254,63122.80],[1700004559995,1,0.499,63122.80],[1700004559995,1,0.420,63122.60],
  [1700004589995,-1,0.109,63122.60],[1700004589995,-1,0.170,63122.60],[1700004619995,1,0.466,63122.70],[1700004619995,1,0.024,63122.50],
  [1700004649995,1,0.440,63122.80],[1700004679995,-1,0.435,63122.70],[1700004679995,-1,0.471,63122.80],[1700004709995,1,0.451,63122.80],
  [1700004739995,1,0.008,63123.10],[1700004769995,1,0.290,63122.90],[1700004769995,-1,0.067,63122.90],[1700004799995,-1,0.464,63122.90],
  [1700004829995,1,0.269,63122.60],[1700004859995,-1,0.400,63122.30],[1700004889995,1,0.098,63122.30],[1700004919995,1,0.382,63122.30],
  [1700004949995,1,0.340,63122.50],[1700004949995,-1,0.169,63122.50],[1700004979995,1,0.126,63122.40],[1700004979995,1,0.180,63122.10],
  [1700005009995,1,0.464,63122.20],[1700005009995,-1,0.276,63122.10],[1700005039995,-1,0.471,63122.30],[1700005069995,-1,0.381,63122.50],
  [1700005099995,1,0.500,63122.40],[1700005129995,1,0.471,63122.20],[1700005159995,-1,0.437,63122.50],[1700005189995,1,0.468,63122.20],
  [1700005219995,-1,0.051,63122.30],[1700005219995,1,0.065,63122.20],[1700005249995,1,0.459,63122.20],[1700005279995,-1,0.013,63122.50],
  [1700005279995,-1,0.047,63122.70],[1700005309995,-1,0.044,63123.00],[1700005309995,1,0.441,63122.90],[1700005339995,-1,0.161,63122.60],
  [1700005339995,1,0.134,63122.80],[1700005369995,1,0.439,63123.10],[1700005369995,-1,0.049,63123.30],[1700005399995,1,0.258,63123.60],
  [1700005399995,1,0.170,63123.70],[1700005429995,-1,0.490,63123.80],[1700005429995,-1,0.054,63123.90],[1700005459995,-1,0.269,63124.10],
  [1700005489995,-1,0.381,63124.40],[1700005519995,-1,0.200,63124.20],[1700005549995,-1,0.177,63123.90],[1700005549995,1,0.023,63123.70],
  [1700005579995,-1,0.214,63124.00],[1700005579995,-1,0.181,63123.90],[1700005609995,1,0.270,63123.80],[1700005609995,1,0.163,63123.50],
  [1700005639995,-1,0.294,63123.80],[1700005639995,-1,0.144,63123.50],[1700005669995,-1,0.475,63123.50],[1700005669995,-1,0.418,63123.70],
  [1700005699995,1,0.069,63123.80],[1700005729995,-1,0.295,63123.90],[1700005759995,1,0.360,63124.20],[1700005759995,-1,0.186,63124.30],
  [1700005789995,-1,0.238,63124.30],[1700005789995,-1,0.273,63124.40],[1700005819995,1,0.129,63124.10],[1700005849995,1,0.465,63124.20],
  [1700005879995,-1,0.481,63124.00],[1700005909995,1,0.280,63124.30],[1700005939995,1,0.105,63124.50],[1700005939995,1,0.324,63124.40],
  [1700005969995,1,0.407,63124.70],[1700005999995,1,0.262,63124.90],[1700006029995,-1,0.461,63124.60],[1700006029995,-1,0.364,63124.90],
  [1700006059995,1,0.307,63124.70],[1700006059995,1,0.218,63124.70],[1700006089995,-1,0.279,63124.90],[1700006089995,-1,0.372,63124.70],
  [1700006119995,-1,0.209,63125.00],[1700006149995,-1,0.264,63124.70],[1700006179995,-1,0.316,63124.40],[1700006179995,-1,0.021,63124.50],
  [1700006209995,-1,0.004,63124.80],[1700006209995,-1,0.357,63124.60],[1700006239995,1,0.421,63124.70],[1700006269995,-1,0.498,63124.80],
  [1700006269995,-1,0.270,63125.10],[1700006299995,-1,0.309,63125.20],[1700006299995,-1,0.232,63125.40],[1700006329995,-1,0.301,63125.20],
  [1700006329995,1,0.130,63125.00],[1700006359995,1,0.189,63125.00],[1700006389995,-1,0.480,63125.00],[1700006389995,1,0.461,63125.20],
  [1700006419995,1,0.197,63124.90],[1700006449995,-1,0.408,63124.90],[1700006449995,-1,0.326,63125.20],[1700006479995,-1,0.199,63125.50],
  [1700006479995,1,0.248,63125.50],[1700006509995,-1,0.076,63125.30],[1700006509995,1,0.417,63125.00],[1700006539995,1,0.302,63124.90],
  [1700006539995,-1,0.487,63125.20],[1700006569995,-1,0.379,63125.10],[1700006569995,-1,0.222,63125.10],[1700006599995,-1,0.111,63125.40],
  [1700006599995,-1,0.487,63125.60],[1700006629995,-1,0.047,63125.80],[1700006629995,1,0.106,63125.50],[1700006659995,1,0.053,63125.30],
  [1700006689995,-1,0.397,63125.10],[1700006689995,-1,0.333,63124.80],[1700006719995,1,0.046,63125.10],[1700006749995,1,0.282,63125.20],
  [1700006749995,-1,0.178,63125.00],[1700006779995,1,0.377,63125.20],[1700006809995,1,0.136,63125.50],[1700006809995,-1,0.092,63125.70],
  [1700006839995,1,0.403,63126.00],[1700006839995,1,0.444,63125.80],[1700006869995,-1,0.151,63125.50],[1700006869995,-1,0.464,63125.70],
  [1700006899995,-1,0.055,63125.40],[1700006899995,-1,0.315,63125.20],[1700006929995,-1,0.214,63125.00],[1700006959995,-1,0.325,63125.30],
  [1700006959995,1,0.404,63125.60],[1700006989995,-1,0.053,63125.90],[1700006989995,-1,0.475,63125.60],[1700007019995,-1,0.154,63125.30],
  [1700007019995,1,0.118,63125.60],[1700007049995,1,0.211,63125.50],[1700007049995,1,0.132,63125.30],[1700007079995,1,0.273,63125.30],
  [1700007109995,-1,0.144,63125.30],[1700007139995,-1,0.137,63125.50],[1700007139995,1,0.256,63125.50],[1700007169995,-1,0.124,63125.60],
  [1700007169995,1,0.311,63125.50],[1700007199995,-1,0.274,63125.70],[1700007229995,-1,0.271,63125.40],[1700007259995,1,0.162,63125.60],
  [1700007289995,-1,0.061,63125.60],[1700007289995,1,0.358,63125.40],[1700007319995,1,0.326,63125.20],[1700007319995,1,0.289,63125.30],
  [1700007349995,1,0.116,63125.50],[1700007379995,-1,0.217,63125.60],[1700007409995,1,0.421,63125.30],[1700007409995,1,0.044,63125.20],
  [1700007439995,-1,0.138,63125.10],[1700007469995,1,0.169,63124.80],[1700007469995,1,0.059,63124.70],[1700007499995,1,0.349,63125.00],
  [1700007499995,1,0.178,63125.10],[1700007529995,1,0.154,63124.80],[1700007559995,-1,0.272,63124.60],[1700007559995,-1,0.016,63124.30],
  [1700007589995,-1,0.191,63124.10],[1700007619995,-1,0.141,63123.80],[1700007649995,-1,0.491,63123.90],[1700007679995,1,0.311,63123.80],
  [1700007709995,1,0.348,63123.80],[1700007709995,-1,0.289,63123.90],[1700007739995,-1,0.155,63124.00],[1700007739995,-1,0.282,63123.80],
  [1700007769995,1,0.090,63123.50],[1700007799995,-1,0.141,63123.30],[1700007829995,-1,0.484,63123.20],[1700007859995,1,0.207,63123.20],
  [1700007859995,1,0.382,63123.40],[1700007889995,-1,0.279,63123.10],[1700007889995,1,0.317,63123.20],[1700007919995,1,0.080,63123.20],
  [1700007919995,1,0.347,63122.90],[1700007949995,-1,0.187,63122.90],[1700007979995,1,0.435,63122.70],[1700007979995,-1,0.427,63123.00],
  [1700008009995,1,0.308,63123.00],[1700008009995,-1,0.152,63122.80],[1700008039995,1,0.471,63122.90],[1700008069995,1,0.236,63122.90],
  [1700008099995,-1,0.307,63123.20],[1700008129995,-1,0.210,63123.10],[1700008129995,-1,0.028,63123.10],[1700008159995,1,0.331,63123.10],
  [1700008189995,1,0.426,63123.40],[1700008219995,1,0.272,63123.50],[1700008249995,-1,0.401,63123.60],[1700008249995,-1,0.411,63123.70],
  [1700008279995,1,0.475,63124.00],[1700008279995,1,0.055,63124.30],[1700008309995,1,0.060,63124.60],[1700008309995,1,0.470,63124.90],
  [1700008339995,-1,0.130,63124.90],[1700008339995,1,0.316,63125.10],[1700008369995,-1,0.184,63125.10],[1700008369995,-1,0.226,63125.00],
  [1700008399995,1,0.029,63125.20],[1700008429995,1,0.457,63125.40],[1700008429995,1,0.279,63125.50],[1700008459995,1,0.500,63125.40],
  [1700008459995,1,0.246,63125.50],[1700008489995,1,0.204,63125.50],[1700008519995,1,0.172,63125.20],[1700008549995,1,0.402,63125.40],
  [1700008549995,-1,0.381,63125.60],[1700008579995,-1,0.334,63125.50],[1700008579995,1,0.222,63125.80],[1700008609995,1,0.293,63125.80],
  [1700008609995,-1,0.430,63125.80],[1700008639995,1,0.193,63125.60],[1700008669995,1,0.335,63125.30],[1700008669995,1,0.235,63125.00],
  [1700008699995,-1,0.470,63125.20],[1700008699995,1,0.498,63125.00],[1700008729995,1,0.238,63124.90],[1700008759995,1,0.276,63125.20],
  [1700008759995,-1,0.003,63125.40],[1700008789995,1,0.340,63125.40],[1700008819995,1,0.039,63125.30],[1700008849995,-1,0.300,63125.10],
  [1700008879995,1,0.219,63125.20],[1700008909995,1,0.480,63125.50],[1700008939995,1,0.127,63125.70],[1700008969995,-1,0.061,63126.00],
  [1700008969995,1,0.199,63126.10],[1700008999995,1,0.329,63126.20],[1700009029995,1,0.399,63125.90],[1700009029995,1,0.490,63125.60],
  [1700009059995,-1,0.371,63125.60],[1700009059995,1,0.305,63125.60],[1700009089995,-1,0.395,63125.70],[1700009119995,-1,0.284,63125.80],
  [1700009119995,-1,0.358,63125.60],[1700009149995,1,0.254,63125.90],[1700009149995,-1,0.185,63126.20],[1700009179995,-1,0.433,63126.10],
  [1700009209995,1,0.375,63126.40],[1700009239995,1,0.133,63126.30],[1700009239995,-1,0.179,63126.20],[1700009269995,-1,0.007,63126.10],
  [1700009269995,1,0.491,63125.90],[1700009299995,1,0.037,63125.70],[1700009299995,1,0.279,63126.00],[1700009329995,1,0.296,63126.20],
  [1700009329995,-1,0.201,63126.00],[1700009359995,1,0.079,63125.70],[1700009389995,-1,0.196,63125.40],[1700009419995,1,0.303,63125.60],
  [1700009419995,1,0.345,63125.70],[1700009449995,-1,0.072,63125.50],[1700009479995,-1,0.183,63125.30],[1700009479995,1,0.116,63125.50],
  [1700009509995,1,0.179,63125.70],[1700009509995,-1,0.046,63125.70],[1700009539995,-1,0.012,63125.50],[1700009539995,1,0.315,63125.40],
  [1700009569995,-1,0.131,63125.70],[1700009569995,1,0.027,63125.80],[1700009599995,1,0.490,63125.60],[1700009599995,1,0.058,63125.80],
  [1700009629995,1,0.382,63126.00],[1700009629995,-1,0.063,63125.80],[1700009659995,-1,0.339,63126.10],[1700009689995,-1,0.372,63126.40],
  [1700009719995,1,0.415,63126.60],[1700009749995,-1,0.340,63126.90],[1700009779995,1,0.138,63127.00],[1700009779995,1,0.344,63126.70],
  [1700009809995,-1,0.496,63127.00],[1700009839995,-1,0.205,63127.30],[1700009839995,-1,0.051,63127.20],[1700009869995,1,0.233,63127.00],
  [1700009899995,1,0.202,63127.00],[1700009929995,1,0.040,63126.80],[1700009929995,1,0.434,63127.00],[1700009959995,-1,0.097,63127.30],
  [1700009959995,1,0.434,63127.10],[1700009989995,-1,0.101,63127.20],[1700009989995,-1,0.338,63127.00],[1700010019995,1,0.235,63126.90],
  [1700010049995,1,0.457,63127.20],[1700010079995,-1,0.241,63127.50],[1700010109995,1,0.444,63127.60],[1700010139995,-1,0.408,63127.30],
  [1700010139995,-1,0.202,63127.40],[1700010169995,-1,0.493,63127.30],[1700010169995,-1,0.009,63127.00],[1700010199995,-1,0.408,63126.90],
  [1700010199995,-1,0.034,63126.70],[1700010229995,-1,0.267,63126.70],[1700010229995,1,0.295,63127.00],[1700010259995,1,0.052,63126.70],
  [1700010289995,-1,0.385,63126.60],[1700010289995,1,0.327,63126.70],[1700010319995,1,0.249,63126.80],[1700010319995,1,0.434,63127.00],
  [1700010349995,1,0.473,63126.90],[1700010349995,-1,0.185,63126.70],[1700010379995,1,0.302,63126.50],[1700010409995,-1,0.444,63126.50],
  [1700010439995,-1,0.175,63126.80],[1700010439995,-1,0.312,63127.10],[1700010469995,1,0.393,63126.80],[1700010469995,1,0.420,63127.00],
  [1700010499995,-1,0.282,63127.30],[1700010499995,1,0.039,63127.20],[1700010529995,-1,0.043,63127.10],[1700010559995,-1,0.121,63127.00],
  [1700010589995,-1,0.370,63126.70],[1700010619995,-1,0.404,63126.40],[1700010619995,1,0.421,63126.70],[1700010649995,-1,0.174,63126.80],
  [1700010679995,1,0.019,63127.10],[1700010679995,-1,0.410,63127.10],[1700010709995,-1,0.214,63126.80],[1700010739995,1,0.362,63126.90],
  [1700010769995,1,0.120,63126.70],[1700010769995,1,0.499,63126.40]
].map((r) => ({ T: r[0], side: r[1], v: r[2], p: r[3] }));
// INSTR: BTCUSDT's priceFilter.tickSize and lotSizeFilter.qtyStep from packages/fixtures/bybit/2026-10-05/rest/instruments_before.json (the non-time bars' tick and lot units)
const INSTR = { tick: 0.1, qtyStep: 0.001 };
const FIXTURE = { klines: "packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page{0,1,2}.json", trades: "packages/fixtures/bybit/2026-10-05/ws/clean_publicTrade_BTCUSDT.jsonl", bars: KL.length, prints: TR.length };
// ---------------------------------------------------------------- tokens (packages/ui/tokens, read at cec8310a6d) ------
const TV = { // colour token → [dark, light, high-contrast], resolved from packages/ui/tokens at cec8310a6d (themes.json: primitives → semantic-dark,
  // + semantic-light, + semantic-hc) by tools/gen_tokens.py (pp/202's, its list pp/361's chrome names + E12-D06 §14.1's candle slots); no hex is typed by hand
  "color.surface.app": ["#0B0E11", "#FFFFFF", "#0B0E11"], "color.surface.canvas": ["#11151A", "#F6F7F9", "#11151A"],
  "color.surface.raised": ["#161B22", "#EDEFF2", "#161B22"], "color.surface.overlay": ["#1C222B", "#E3E6EA", "#1C222B"],
  "color.surface.hover": ["#22292F", "#E3E6EA", "#22292F"], "color.surface.selected": ["#2E363E", "#D6DAE0", "#2E363E"],
  "color.border.subtle": ["#22292F", "#E3E6EA", "#22292F"], "color.border.default": ["#2E363E", "#D6DAE0", "#586470"],
  "color.border.strong": ["#3D4650", "#C2C8D0", "#3D4650"], "color.border.selected": ["#4A86EE", "#2B6CE8", "#6EA1F5"],
  "color.text.primary": ["#E8EAED", "#14171A", "#F6F8FA"], "color.text.secondary": ["#B1BAC4", "#3A4148", "#E8EAED"],
  "color.text.tertiary": ["#8B949E", "#525C66", "#C9D1D9"], "color.text.on-action": ["#FFFFFF", "#FFFFFF", "#0B0E11"],
  "color.text.link": ["#6EA1F5", "#1F55BF", "#6EA1F5"], "color.action.primary.default": ["#2B6CE8", "#2B6CE8", "#6EA1F5"],
  "color.action.secondary.default": ["#2E363E", "#D6DAE0", "#2E363E"], "color.action.selected": ["#0F2650", "#DDE8FC", "#0F2650"],
  "color.buy.default": ["#2EBD59", "#1C7A3C", "#6BD48A"], "color.sell.default": ["#E5484D", "#C7373C", "#F08A8A"],
  "color.status.info.subtle": ["#093644", "#DAF2F7", "#093644"], "color.status.info.strong": ["#6ED0E8", "#12798F", "#6ED0E8"],
  "color.status.warning.subtle": ["#4A3306", "#FCEECB", "#4A3306"], "color.status.warning.strong": ["#F5C86B", "#9A6A05", "#F5C86B"],
  "color.status.danger.subtle": ["#4E1518", "#FBE2E3", "#4E1518"], "color.status.danger.strong": ["#F0B441", "#9A6A05", "#F0B441"],
  "color.status.success.subtle": ["#0E3D1F", "#DCF3E4", "#0E3D1F"], "color.status.success.strong": ["#6BD48A", "#1E9448", "#6BD48A"],
  "color.env.live": ["#E5484D", "#C7373C", "#E5484D"], "color.env.demo": ["#2B6CE8", "#2B6CE8", "#2B6CE8"],
  "color.focus.ring": ["#6EA1F5", "#1F55BF", "#FFFFFF"], "color.data-confidence.stale.surface": ["#000000", "#D6DAE0", "#000000"],
  "color.data-confidence.stale.text": ["#B1BAC4", "#3A4148", "#E8EAED"], "color.data-confidence.stale.indicator": ["#F5C86B", "#9A6A05", "#F5C86B"],
  "color.surface.sunken": ["#000000", "#D6DAE0", "#000000"], "palette.black": ["#000000", "#000000", "#000000"],
  "color.text.disabled": ["#586470", "#707B87", "#586470"], "color.status.danger.default": ["#C93A3F", "#7A1E22", "#D8474B"],
  "color.status.info.default": ["#1EA8CC", "#178AA8", "#1EA8CC"], "color.status.warning.default": ["#E8A317", "#B87F0A", "#E8A317"],
  "color.status.success.default": ["#2EBD59", "#1C7A3C", "#2EBD59"], "color.action.secondary.hover": ["#3D4650", "#C2C8D0", "#3D4650"],
  "color.candle.up": ["#2EBD59", "#1C7A3C", "#2EBD59"], "color.candle.down": ["#E5484D", "#C7373C", "#E5484D"],
  "color.candle.wick": ["#8B949E", "#525C66", "#8B949E"], "color.axis.text": ["#8B949E", "#525C66", "#8B949E"]
};
const THI = (th) => (th === "light" ? 1 : th === "high-contrast" ? 2 : 0); // a theme's column in TV (pp/202's: 59-twins builds the hc twin on TV's dark column holding its hc values)
const TT = { // typography token → [family, size, weight, line height]
  "type.ui.label": ["Inter", 12, 500, 1.2],
  "type.ui.body": ["Inter", 13, 400, 1.4],
  "type.ui.body-strong": ["Inter", 13, 500, 1.4],
  "type.ui.caption": ["Inter", 11, 400, 1.2],
  "type.num.base": ["JetBrains Mono", 13, 400, 1.2],
  "type.num.md": ["JetBrains Mono", 14, 500, 1.2],
  "type.ui.heading-sm": ["Inter", 14, 600, 1.2],
  "type.ui.heading-md": ["Inter", 16, 600, 1.2],
  "type.num.xs": ["JetBrains Mono", 10, 400, 1.2], // E10-D03 §2.1: the HealthChips' and the StatusBar's mono values
  "type.num.sm": ["JetBrains Mono", 11, 400, 1.2], // r1 (#361): E15-D07 §5.8 / §10: the CMP-022 Kbd hint in menu rows (font.size.xs, font.lineheight.tight)
};
const NV = { // spacing, size, radius, border-width and font-weight tokens (px or weight)
  "space.inset.xs": 4, "space.inset.sm": 8, "space.inset.md": 12, "space.panel.padding": 12, "space.stack.xs": 4, "space.stack.sm": 8,
  "space.stack.md": 12, "space.stack.lg": 16, "space.dialog.padding": 24, "space.field.gap": 8, "space.button.paddingX": 12, "size.row.compact": 24,
  "size.row.comfortable": 32, "size.control.compact": 24, "size.control.comfortable": 32, "size.icon.sm": 12, "size.icon.md": 16, "size.target.min": 24,
  "radius.badge": 9999, "radius.control": 4, "radius.card": 6, "radius.dialog": 10, "radius.xs": 2, "border.hairline": 1,
  "border.thick": 2, "border.focus": 2, "font.weight.bold": 700,
  // r1 (#319): the primitives E15-D03 §3, §4 and §10 name
  "space.1": 4, "space.2": 8, "space.3": 12, "space.4": 16, "space.6": 24, "size.icon.lg": 20, "radius.pill": 9999,
  "font.weight.regular": 400, "font.weight.medium": 500, "font.weight.semibold": 600,
  // r1 (#361): the primitives E15-D07 §4.3, §5.6 and §10 name (radius.sm: the thumbnail; space.8: the corner pointer inset; space.16: the mini-map height)
  "radius.sm": 4, "space.8": 32, "space.16": 64,
  // r3 (#361): the 15 Dialog scrim's opacity, packages/ui/tokens/primitives.tokens.json opacity.scrim (type opacity, one value for every theme)
  "opacity.scrim": 0.6,
};
const S4 = NV["space.inset.xs"], S8 = NV["space.inset.sm"], S12 = NV["space.inset.md"], PANEL_IN = NV["space.panel.padding"];
const DENS = { // E15-D03 §3.1 and §10: the workspace rows follow size.control.compact / .comfortable; the shell rows (TopBar 80, StatusBar 48) are density-fixed
  compact: { row: NV["size.row.compact"], rowTok: "size.row.compact", tb: 32, ctl: NV["size.control.compact"], ctlTok: "size.control.compact", ins: S8, insTok: "space.inset.sm", icon: NV["size.icon.sm"], iconTok: "size.icon.sm", pill: 20, bnr: 32, split: [72, 24], hgap: NV["space.2"], env: 20, i: 0 },
  comfortable: { row: NV["size.row.comfortable"], rowTok: "size.row.comfortable", tb: 40, ctl: NV["size.control.comfortable"], ctlTok: "size.control.comfortable", ins: S12, insTok: "space.inset.md", icon: NV["size.icon.md"], iconTok: "size.icon.md", pill: 28, bnr: 40, split: [72, 32], hgap: NV["space.3"], env: 24, i: 1 },
}; // tb: the tab strip (§3.1, 32 / 40); pill: a badge `size.control.*` less `space.1` (§10, 20 / 28); hgap: the header's element gap (§4.2.1: space.2 / space.3); env: CMP-075's pill (E10-D03 §1.2: 20 / 24)
const NBSP = "\u00A0", MINUS = "\u2212", M = 40; // no-break space (pill labels never wrap), the minus sign U+2212 (§3.4), the board margin

// ---------------------------------------------------------------- token catalog (bind by name, theme-checked) -----
const CAT = (() => {
  const out = { ok: false, theme: null, index: new Map(), note: "", sets: [] };
  let cat = null;
  try { cat = penpot.library && penpot.library.local ? penpot.library.local.tokens : null; } catch (e) { out.note = "catalog unreadable: " + (e && e.message ? e.message : e); return out; }
  if (!cat) { out.note = "no token catalog (penpot.library.local.tokens)"; return out; }
  let sets = [], themes = [];
  try { sets = Array.from(cat.sets || []); } catch (e) { warn("catalog sets", e); }
  try { themes = Array.from(cat.themes || []); } catch (e) { warn("catalog themes", e); }
  const isOn = (x) => { try { return x.active === true; } catch (e) { return false; } };
  const activeSets = sets.filter(isOn);
  out.sets = activeSets.map((s) => s.name);
  const activeThemes = themes.filter((t) => isOn(t) && (!t.group || t.group === "theme")).map((t) => t.name);
  const inferred = out.sets.indexOf("semantic-light") >= 0 ? "light" : out.sets.indexOf("semantic-hc") >= 0 ? "high-contrast" : out.sets.indexOf("semantic-dark") >= 0 ? "dark" : null;
  let th = activeThemes.length === 1 ? activeThemes[0] : null;
  if (th && inferred && th !== inferred) { out.note = "the active theme " + th + " disagrees with the active sets (" + inferred + ")"; th = null; }
  out.theme = th || (activeThemes.length ? null : inferred);
  for (const s of activeSets) { try { for (const t of s.tokens || []) out.index.set(t.name, t); } catch (e) { warn("catalog tokens " + s.name, e); } }
  out.ok = true;
  if (!out.theme && !out.note) out.note = sets.length ? "no single active theme in the catalog" : "empty token catalog";
  return out;
})();
// Binding happens on REAL shapes, after the replay (PARTS): during the build every candidate is a record. BQ collects the
// board's candidates (name|prop|theme → records); finish() hands them to the record; after the replay, flushBindings() binds
// the real shapes THIS call created, so a board in parts binds each shape once, in the call that makes it.
const BQ = new Map();
const BVQ = []; // by-value token uses [record, reason or null]: radius, stroke width, icon size, a bold weight over a type token
const TOKREP = []; // per call: { n, bound, unbound, byValue, byValueReasons, reasons }
let TH = "dark"; // the theme the next shapes are drawn in: the board's, or the half of a mixed board being drawn
function bindLater(shape, name, prop) {
  if (!shape || !name) return;
  const k = name + "|" + prop + "|" + TH;
  let q = BQ.get(k);
  if (!q) { q = { name, prop, theme: TH, shapes: [] }; BQ.set(k, q); }
  q.shapes.push(shape);
}
function byValue(shape, reason) { if (shape) BVQ.push([shape, reason || null]); }
const hex8 = (v) => { const m = /^#?([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(String(v || "").trim()); return m ? "#" + (m[1] + (m[2] || "FF")).toUpperCase() : null; }; // all eight digits: an opaque #RRGGBB reads #RRGGBBFF, so a translucent catalog value never equals the opaque one (fails closed)
function typoOf(tok) { // a typography token's value as { fam, size, weight, lh }, or null when it cannot be read (the guard then fails closed)
  let v = null;
  try { v = tok.resolvedValue; } catch (e) { v = null; }
  if (!v || typeof v !== "object") { try { v = JSON.parse(tok.resolvedValueString); } catch (e) { v = null; } }
  if (!v || typeof v !== "object") return null;
  const famRaw = v.fontFamily != null ? v.fontFamily : v.fontFamilies, fam = Array.isArray(famRaw) ? famRaw[0] : famRaw;
  const size = parseFloat(v.fontSize), weight = parseFloat(v.fontWeight), lh = parseFloat(v.lineHeight);
  if (typeof fam !== "string" || !(size > 0) || !(weight > 0) || !(lh > 0)) return null; // a weight word ("regular") or a missing field: unreadable
  return { fam, size, weight, lh };
}
function valueGuard(q, tok) { // null when the catalog token's value equals the repository's for the shape's theme, else the reason (fails closed)
  if (q.prop === TOKEN_PROPS.type) {
    const want = TT[q.name], got = typoOf(tok);
    if (!want) return "no repository value for " + q.name;
    if (!got) return "catalog typography value unreadable";
    if (got.fam !== want[0] || Math.abs(got.size - want[1]) > 0.01 || got.weight !== want[2] || Math.abs(got.lh - want[3]) > 0.001) return "catalog typography differs from packages/ui/tokens";
    return null;
  }
  const repo = TV[q.name] ? TV[q.name][THI(q.theme)] : null; // #202 / #241: dark, light or high-contrast column
  if (!repo) return "no repository value for " + q.name;
  let cv = null; try { cv = tok.resolvedValueString; } catch (e) { cv = null; }
  if (!hex8(cv)) return "catalog colour value unreadable (not a hex)";
  if (hex8(cv) !== hex8(repo)) return "catalog value differs from packages/ui/tokens (all eight hex digits compared)";
  return null;
}
// one applyToShapes per (token, property, theme) over the real shapes this call made: each is bound once or counted unbound
function flushBindings(n, binds, bvq, real) {
  const rep = { n, bound: 0, unbound: 0, byValue: 0, byValueReasons: {}, reasons: {} };
  for (const [rec, why] of bvq) { if (!real(rec)) continue; rep.byValue++; if (why) rep.byValueReasons[why] = (rep.byValueReasons[why] || 0) + 1; }
  const miss = (q, why) => { rep.unbound += q.shapes.length; rep.reasons[why] = (rep.reasons[why] || 0) + q.shapes.length; };
  for (const q0 of binds.values()) {
    const shapes = q0.shapes.map(real).filter(Boolean);
    if (!shapes.length) continue; // another part's shapes: bound in their own call
    const q = { name: q0.name, prop: q0.prop, theme: q0.theme, shapes };
    if (!CAT.ok || !CAT.theme) { miss(q, CAT.note || "no active theme"); continue; }
    if (CAT.theme !== q.theme) { miss(q, q.theme + " shape while the " + CAT.theme + " theme is active (binding is by name)"); continue; }
    const tok = CAT.index.get(q.name);
    if (!tok) { miss(q, "token not in an active set"); continue; }
    const why = valueGuard(q, tok);
    if (why) { miss(q, why); continue; }
    try { tok.applyToShapes(q.shapes, [q.prop]); rep.bound += q.shapes.length; } catch (e) { miss(q, "applyToShapes threw: " + (e && e.message ? e.message : e)); }
  }
  TOKREP.push(rep);
  return rep;
}
const FONTS = (() => { try { return (penpot.fonts && penpot.fonts.all) || []; } catch (e) { warn("fonts", e); return []; } })();
const FONT = FONTS.find((f) => f.fontId === "gfont-inter") || null; // exact: findByName("Inter") prefix-matches Inter Tight (PENPOT-FONTS)
const MONO = FONTS.find((f) => f.fontId === "gfont-jetbrains-mono") || null; // exact as well
if (!FONT) warn("fonts", "gfont-inter not found: texts keep the file default font");
if (!MONO) warn("fonts", "gfont-jetbrains-mono not found: numerals keep the file default font");
function variant(font, weight) { try { return (font.variants || []).find((v) => String(v.fontWeight) === String(weight) && (v.fontStyle || "normal") === "normal") || null; } catch (e) { return null; } }
function set(obj, props) { for (const k of Object.keys(props)) { try { obj[k] = props[k]; } catch (e) { warn("set " + k, e); } } }
// r2 (#361): FOLLOW, when set, is merged into every meta tagged meanwhile: a follow row (fr row id, fo group, fg gap before the group;
// flab = the group's auto-width label, fbg = a rect resized to the label's right + fp), laid out by the relayout restack at measured widths
let FOLLOW = null;
function withF(f, fn) { const p = FOLLOW; FOLLOW = f ? Object.assign({}, p || {}, f) : null; try { return fn(); } finally { FOLLOW = p; } }
function tag(shape, meta) { try { shape.setPluginData(TAG, "v1"); shape.setPluginData(TAG + ":meta", JSON.stringify(FOLLOW ? Object.assign({}, meta || {}, FOLLOW) : meta || {})); } catch (e) { warn("tag", e); } }
function pad2(n) { return (n < 10 ? "0" : "") + n; }
let SC = 1; // the scale of the panel being drawn (board 19's 125 %, board 20's 60 %): geometry and type multiply by it
const col = (tok) => { const v = TV[tok] || (warn("token", "unknown colour token " + tok), TV["color.text.primary"]); return v[TH === "light" ? 1 : 0]; };

// Width estimates (layout only; the relayout pass reads the measured heights). TIGHT: per character class for Inter, sized to
// stay at or above Inter's advances (caps 0.72–1.0 em, lowercase 0.27–0.88 em, digits 0.64 em; +2 % at weight 500, +5 % at 600,
// +4 % headroom), used to lay out cells, so the §5.1 / §6.1 minimum widths hold where the real text fits. SAFE: never below
// 0.57 em per character (the offline mock estimates 0.56 em), used for stacked texts (dialog lines, menus, tooltips, notes,
// buttons) so a mock-estimated wrap can never push one line onto the next. JetBrains Mono: 0.63 em (its advance is 0.60).
const EM_FLAT = 0.57, EM_MONO = 0.63;
// The MEASURED pass (r3; D-8: the column widens to fit on the first snapshot, which the build measures): where the estimates above
// cannot fit a panel's headers on one line and its values (boards 03, 04 and 07 in comfortable), fit() lays the panel out again at
// the measured widths and the panel draws its header and rows at them: Inter's character classes with 2 % headroom instead of 4 %,
// JetBrains Mono at 0.61 em (its advance is 0.60), and each header in HEAD_INK as Penpot drew it on the r2 exports.
let WMEAS = false;
const MEAS_HR = 1.02, MEAS_MONO = 0.61;
const HEAD_INK = { // type.ui.label (Inter 12, weight 500) headers on the r2 exports (boards 01, 02 and 06): ink extent in px; + 2 px of side bearings is the advance
  "Entry (USDT)": 73, "Mark (USDT)": 72, "uPnL (USDT)": 72, "rPnL today (USDT)": 105, "Liq price (USDT)": 93, "Liq dist. %": 58, "Avg fill (USDT)": 82, "Price (USDT)": 73,
};
const monoEm = () => (WMEAS ? MEAS_MONO : EM_MONO);
const CAPS = { A: 0.7, B: 0.66, C: 0.71, D: 0.74, E: 0.59, F: 0.57, G: 0.75, H: 0.75, I: 0.28, J: 0.52, K: 0.67, L: 0.55, M: 0.88, N: 0.75, O: 0.78, P: 0.64, Q: 0.78, R: 0.66, S: 0.64, T: 0.63, U: 0.74, V: 0.7, W: 0.98, X: 0.68, Y: 0.67, Z: 0.63 }; // Inter caps, at or above the rendered advances (BTCUSDT 4.75 em vs ~4.7 measured)
function charEm(ch) {
  if (ch === " " || ch === NBSP) return 0.28;
  if (/[il.,:;'’!|]/.test(ch)) return 0.27;
  if (/[fjrt]/.test(ch)) return 0.37;
  if (ch === "m") return 0.88;
  if (ch === "w") return 0.8;
  if (/[bdghnopqu]/.test(ch)) return 0.6;
  if (/[a-z]/.test(ch)) return 0.56;
  if (CAPS[ch]) return CAPS[ch];
  if (/[0-9]/.test(ch)) return 0.64;
  if (ch === "·") return 0.4;
  if (/[()[\]{}"“”‘]/.test(ch)) return 0.38;
  if (ch === "/") return 0.45;
  if (/[-–]/.test(ch)) return 0.45;
  return 1.0; // arrows, bullets, ×, ≥, —, …, %, +, −, §, ▸ and other symbols
}
function wordW(word, size, mono, weight, safe) {
  const n = Array.from(word).length, short = WMEAS && (mono ? n <= 4 : n <= 3); // r4: in the measured pass a word of 3 characters or fewer and a numeral of 4 or fewer keep the 4 % headroom ("SL", "1.2", "0.5": a wrap would split them; the saving there is under 1 px)
  if (mono) return n * size * (short ? EM_MONO : monoEm());
  let em = 0;
  for (const ch of word) em += charEm(ch);
  const tight = em * size * (Number(weight) >= 600 ? 1.05 : Number(weight) >= 500 ? 1.02 : 1) * (WMEAS && !short ? MEAS_HR : 1.04);
  return safe ? Math.max(tight, n * size * EM_FLAT) : tight;
}
function lineW(str, size, mono, weight, safe) { // one line, no wrap: the words plus the spaces between them
  const ws = String(str).split(" ");
  const sp = mono ? size * monoEm() : safe ? size * EM_FLAT : size * 0.28 * (WMEAS ? MEAS_HR : 1.04);
  return ws.reduce((a, w) => a + wordW(w, size, mono, weight, safe), 0) + (ws.length - 1) * sp;
}
function estLines(str, w, size, mono, weight) { // SAFE widths: the line count a box of width w needs
  const sp = size * (mono ? EM_MONO : EM_FLAT);
  let lines = 0;
  for (const para of String(str).split("\n")) {
    let cur = 0, n = 1;
    for (const word of para.split(" ")) {
      const ww = wordW(word, size, mono, weight, true);
      if (ww > w + 0.01) { if (cur > 0) n++; const k = Math.ceil(ww / w); n += k - 1; cur = ww - (k - 1) * w; continue; }
      const need = cur === 0 ? ww : cur + sp + ww;
      if (need > w + 0.01) { n++; cur = ww; } else cur = need;
    }
    lines += n;
  }
  return lines;
}
const kfmt = (v) => String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ","); // 1680 → "1,680" (the spec's style)
const r2 = (v) => Math.round(v * 100) / 100; // scaled sizes to 2 decimals (12 × 0.6 is 7.2, never 7.199999999999999)
const TYP = (type) => { const t = TT[type]; return { fam: t[0], size: r2(t[1] * SC), weight: t[2], lh: t[3], mono: t[0] === "JetBrains Mono" }; };
function tw(str, type) { const t = TYP(type || "type.ui.body"); return Math.ceil(Math.max.apply(null, String(str).split("\n").map((l) => lineW(l, t.size, t.mono, t.weight, false)))); } // TIGHT, widest line
function twm(str, type) { const t = TYP(type || "type.ui.body"); return Math.ceil(Math.max.apply(null, String(str).split("\n").map((l) => lineW(l, t.size, t.mono, t.weight, true)))); } // SAFE, widest line
function th1(type) { const t = TYP(type || "type.ui.body"); return t.size * t.lh; } // one line's height
function ellipsize(label, fits, o) { // the longest word-boundary prefix that fits, then "…" (§7: an sl.* line longer than its State cell ends in an ellipsis); o.sentence (a banner line, r3): a cut at a sentence's end keeps the spec's own full stop and adds no "…"
  if (fits(label)) return label;
  const words = String(label).split(" ");
  for (let n = words.length - 1; n > 0; n--) { const pre = words.slice(0, n).join(" "), t = o && o.sentence && /\.$/.test(pre) ? pre : pre.replace(/[\s—–·,:;-]+$/, "") + "…"; if (fits(t)) return t; }
  return "…";
}



// ---------------------------------------------------------------- the shape recorder (PARTS; E15-D02 r4's, unchanged but for textDecoration) --
// During the build no Penpot shape is made. mkShape() returns a RECORD that keeps every value the code sets, so each read
// (a frame's x / y / width / height, the board's width, a name, a plugin-data value) sees exactly what the one-call build
// read back, and logs each write in program order (REC.ops: [seq, op, a, b]; seq = the shape's place in the board's
// creation sequence, the board frame 0). The PARTS sections near the end cut that sequence into parts and replay the
// writes of ONE part onto real shapes, in the same order, so every part computes the layout of the one-call build and
// creates only its own shapes. A record is sealed: a write the recorder does not know throws (strict mode) instead of
// being dropped from the replay.
const REC_PROPS = ["name", "x", "y", "fills", "strokes", "fontSize", "fontWeight", "lineHeight", "growType", "align", "borderRadius", "clipContent", "textDecoration"]; // textDecoration: the struck-through old value (§4.5)
let REC = null; // the board being recorded: { n, ops (null when only counted), shapes (records by seq) }
function recLog(seq, op, a, b2) { if (REC && REC.ops) REC.ops.push([seq, op, a, b2]); }
class Rec {
  constructor(kind, seq, text) {
    this.kind = kind; // "text" | "rect" | "board" (no path kind: this script draws no path, so every call has 0 segments)
    this.seq = seq;
    this.text = text == null ? null : String(text);
    this.v = {}; // the values the build set (reads come from here)
    this.pd = {}; // plugin data
    this.parent = null;
    this.children = [];
    Object.seal(this);
  }
  get type() { return this.kind === "rect" ? "rectangle" : this.kind; }
  get id() { return "rec:" + this.seq; } // a placeholder: the result gets the real id into its boards and frames
  get characters() { return this.text; }
  rd(k) { // a value the build set; a read before the build set it is reported (the one-call build read Penpot's default there)
    if (Object.prototype.hasOwnProperty.call(this.v, k)) return this.v[k];
    warn("record", "read of " + k + " before it was set on the " + this.kind + " #" + this.seq);
    return k === "width" || k === "height" ? (this.kind === "text" && k === "height" ? 1 : 100) : k === "name" ? "" : k === "fills" || k === "strokes" ? [] : k === "x" || k === "y" ? 0 : undefined;
  }
  get width() { return this.rd("width"); }
  get height() { return this.rd("height"); }
  resize(w, h) { this.v.width = w; this.v.height = h; recLog(this.seq, "rsz", w, h); }
  appendChild(c) {
    if (!(c instanceof Rec)) throw new Error("record: appendChild of a shape that is not a record");
    if (c.parent) throw new Error("record: the " + c.kind + " #" + c.seq + " is appended a second time"); // r3 never re-parents
    const last = this.children[this.children.length - 1];
    if (last && last.seq > c.seq) warn("record", "#" + c.seq + " appended under #" + this.seq + " after #" + last.seq + ": out of creation order"); // the parts' z-order rests on creation order
    c.parent = this;
    this.children.push(c);
    recLog(this.seq, "add", c.seq);
  }
  setPluginData(k, v) { this.pd[k] = String(v); recLog(this.seq, "pd", k, String(v)); }
  getPluginData(k) { return Object.prototype.hasOwnProperty.call(this.pd, k) ? this.pd[k] : ""; }
  applyFont(font, v) { recLog(this.seq, "font", font, v); } // replayed as font.applyToText(real text, variant)
}
for (const k of REC_PROPS) {
  Object.defineProperty(Rec.prototype, k, { get() { return this.rd(k); }, set(val) { this.v[k] = val; recLog(this.seq, "set", k, val); } });
}
// the one creation site: kind "text" (with its characters), "rect" or "board"; the record's seq is its place in the sequence
function mkShape(kind, text) {
  if (!REC) throw new Error("record: a " + kind + " was made outside a board's record");
  const s = new Rec(kind, REC.shapes.length, text);
  REC.shapes.push(s);
  recLog(s.seq, "new", kind, s.text);
  return s;
}
let blockSeq = 0;
const newBlk = () => TICKET + ":" + (++blockSeq);
function K(o) { o = o || {}; const blk = o.blk || newBlk(); return { blk, stk: o.stk || blk, idx: o.idx || 0 }; } // a block key: own stack unless given
function txt(par, str, x, y, w, o) { // a text in a typography token; colour by token name; single line unless o.ml
  o = o || {};
  const type = o.type || "type.ui.body";
  const T = TYP(type);
  const t = mkShape("text", String(str)); // a record; the replay (PARTS) makes the real text (penpot.createText) in its part
  if (!t) { warn("createText", "returned null for: " + String(str).slice(0, 40)); return null; }
  t.name = TICKET + " / " + (o.name || "text");
  const f = T.mono ? MONO : FONT;
  const wt = o.weightTok ? NV[o.weightTok] : T.weight; // o.weightTok: a weight token over the type token (the ENV pill's LIVE in font.weight.bold, §6)
  try { if (f) t.applyFont(f, variant(f, wt) || undefined); } catch (e) { warn("applyToText", e); } // replayed as f.applyToText(text, variant)
  set(t, { fontSize: String(T.size), fontWeight: String(wt), lineHeight: String(T.lh), growType: "auto-height", align: o.align || "left" });
  if (o.deco) set(t, { textDecoration: o.deco });
  const h = Math.ceil(estLines(str, w, T.size, T.mono, T.weight) * T.size * T.lh);
  t.resize(Math.max(1, w), Math.max(1, h));
  if (o.grow === "auto-width") set(t, { growType: "auto-width" }); // a squeezed single line (the 360-px dock): it may grow, it never wraps
  t.x = x; t.y = y;
  const c = o.col || "color.text.primary";
  t.fills = [{ fillColor: col(c), fillOpacity: 1 }];
  const k = o.k || K();
  tag(t, { role: "text", tok: c, type, weightTok: o.weightTok, theme: TH, scale: SC !== 1 ? SC : undefined, sl: o.ml || String(str).indexOf("\n") >= 0 ? undefined : true, font: T.fam, blk: k.blk, stk: k.stk, idx: k.idx, after: o.after });
  par.appendChild(t);
  bindLater(t, c, TOKEN_PROPS.fill);
  if (SC !== 1) byValue(t, "scaled frame: the token size would reset it"); // a typography token owns size, weight and line height: bound, it would re-style a scaled text back to its size
  else if (o.weightTok) byValue(t, o.weightTok + " over " + type + ": the type token would reset the weight"); // bound, type.ui.caption would set 400 back
  else bindLater(t, type, TOKEN_PROPS.type);
  return { shape: t, h, w };
}
function gw(ch, big) { const s = (big ? NV["size.icon.md"] : NV["size.icon.sm"]) * SC; return Math.max(s, Math.ceil(Array.from(ch).length * EM_FLAT * s)); } // a glyph slot: the icon size, wider only for a two-character placeholder
function gly(par, ch, x, y, o) { // a CMP-019 icon placeholder glyph in its size.icon.* slot, centred
  o = o || {};
  const tokSize = o.big ? "size.icon.md" : "size.icon.sm", size = r2(NV[tokSize] * SC), w = gw(ch, o.big);
  const t = mkShape("text", String(ch)); // a record (penpot.createText in its part)
  if (!t) { warn("createText", "returned null for glyph " + ch); return null; }
  t.name = TICKET + " / " + (o.name || "glyph");
  try { if (FONT) t.applyFont(FONT, variant(FONT, 400) || undefined); } catch (e) { warn("applyToText", e); }
  set(t, { fontSize: String(size), fontWeight: "400", lineHeight: "1.2", growType: "auto-height", align: "center" });
  t.resize(w, Math.ceil(size * 1.2));
  t.x = x; t.y = y;
  const c = o.col || "color.text.secondary";
  t.fills = [{ fillColor: col(c), fillOpacity: 1 }];
  const k = o.k || K();
  tag(t, { role: "text", tok: c, glyph: tokSize, theme: TH, scale: SC !== 1 ? SC : undefined, sl: true, font: "Inter", blk: k.blk, stk: k.stk, idx: k.idx });
  par.appendChild(t);
  bindLater(t, c, TOKEN_PROPS.fill);
  byValue(t, null); // its size is a size.icon.* token, set by value
  return { shape: t, w, h: size * 1.2 };
}
function box(par, x, y, w, h, o) { // a rectangle: fill and stroke by token name; radius and stroke width by token value
  o = o || {};
  const r = mkShape("rect"); // a record (penpot.createRectangle in its part)
  r.name = TICKET + " / " + (o.name || "rect");
  r.x = x; r.y = y; r.resize(Math.max(1, w), Math.max(1, h));
  r.fills = o.fill ? [{ fillColor: col(o.fill), fillOpacity: o.op != null ? o.op : 1 }] : []; // o.op: an opacity token's value (#319 board 06: the scrim at opacity.scrim)
  if (o.stroke) { r.strokes = [{ strokeColor: col(o.stroke), strokeOpacity: 1, strokeWidth: NV[o.bw || "border.hairline"] * SC, strokeStyle: o.dashed ? "dashed" : "solid", strokeAlignment: "inner" }]; byValue(r, null); }
  if (o.r) { set(r, { borderRadius: NV[o.r] === 9999 ? Math.ceil(Math.min(w, h) / 2) : NV[o.r] * SC }); byValue(r, null); }
  const k = o.k || K();
  tag(r, { role: o.role || "rect", tok: o.fill || null, strokeTok: o.stroke || null, theme: TH, rad: o.r, bw: o.stroke ? (o.bw || "border.hairline") : undefined, size: o.sz, blk: k.blk, stk: k.stk, idx: k.idx, bg: o.bg ? true : undefined, pad: o.bg ? 0 : undefined, gap: o.gap, opTok: o.opTok });
  par.appendChild(r);
  if (o.fill && o.op == null) bindLater(r, o.fill, TOKEN_PROPS.fill);
  else if (o.fill) byValue(r, o.fill + " at " + (o.opTok || "an opacity") + " " + o.op + ": by value (r3, #361 F-1: a colour-token bind writes the token's opaque value over the fill opacity)");
  if (o.stroke) bindLater(r, o.stroke, TOKEN_PROPS.stroke);
  return r;
}
function lockIcon(par, x, y, big, c, k) { // the CMP-019 `lock` icon drawn as two shapes (no colour emoji, D01 HW-21) in a size.icon.* slot
  const s = (big ? NV["size.icon.md"] : NV["size.icon.sm"]) * SC, u = s / 12;
  box(par, x + 3 * u, y + 1 * u, 6 * u, 7 * u, { stroke: c, r: "radius.badge", name: "lock-shackle", k });
  const body = box(par, x + 2 * u, y + 5 * u, 8 * u, 6 * u, { fill: c, r: "radius.xs", name: "lock-body", k });
  byValue(body, null); // the icon size (size.icon.*), set by value
  return s;
}

// ---------------------------------------------------------------- parts: what a cell, a band or a line holds ----------
// A part is one of: { t, type, col, box, al } text · { g, col } glyph · { bar } P&L accent · { pnl } signed P&L numeral with its
// accent bar · { lock } lock icon · { chip } pill or tag · { btn } button · { split } SplitButton · { cb } checkbox · { sp } spacer;
// gb overrides the gap before it (default space.inset.xs, the glyph-to-word gap of §12).
const NUM = "type.num.base", CAP = "type.ui.caption", LBL = "type.ui.label", BODY = "type.ui.body", STRONG = "type.ui.body-strong", H_SM = "type.ui.heading-sm", H_MD = "type.ui.heading-md";
const PRI = "color.text.primary", SEC = "color.text.secondary", TER = "color.text.tertiary", LINK = "color.text.link";
const BUY = "color.buy.default", SELL = "color.sell.default", WARN_S = "color.status.warning.strong", DANGER_S = "color.status.danger.strong", INFO_S = "color.status.info.strong";
const TONE = { info: ["color.status.info.subtle", INFO_S], warning: ["color.status.warning.subtle", WARN_S], danger: ["color.status.danger.subtle", DANGER_S], success: ["color.status.success.subtle", "color.status.success.strong"] }; // §6 L393-L396
function DZ(name) { // a density's values at the current scale
  const d = DENS[name], z = { i: d.i, name, rowTok: d.rowTok, ctlTok: d.ctlTok, insTok: d.insTok, iconTok: d.iconTok };
  for (const key of ["row", "tb", "ctl", "ins", "icon", "pill", "bnr", "hgap", "env"]) z[key] = d[key] * SC; // r1 (#319): + hgap, env (the workspace header gap and CMP-075's pill)
  z.split = [d.split[0] * SC, d.split[1] * SC]; z.gap = S4 * SC; z.pin = PANEL_IN * SC; z.strip = 32 * SC;
  return z;
}
function pillTextW(label, size) { return Math.max(Math.ceil(size * 2), Math.ceil(Array.from(String(label)).length * size * 0.7), Math.ceil(lineW(String(label), size, false, 400, false))); } // 0.70 em per character; floor: 2 em and the TIGHT width (wide caps such as "DEMO")
function chipH(c, D) { return c.ctl ? D.ctl : D.pill; }
function chipPad(c) { return (c.padX == null ? S4 : c.padX) * SC; } // pills and tags: inset space.inset.xs (§12)
function chipW(c, D) {
  const size = TYP(CAP).size;
  let w = chipPad(c) * 2;
  c.parts.forEach((p, i) => { w += (i ? S4 * SC : 0) + (p.g != null ? gw(p.g, D.i === 1) : p.lock ? D.icon : p.dot ? DOT * SC : pillTextW(p.t, size) + (p.bold ? Math.ceil(size * 0.4) : 0)); }); // a bold label: 0.4 em of headroom over the 0.70-em box
  return Math.ceil(w);
}
function btnW(b, D) { return b.w ? b.w * SC : Math.ceil(NV["space.button.paddingX"] * SC * 2 + twm(b.t, LBL) + (b.kind === "t2" || b.kind === "busy" ? D.icon + D.gap : 0) + (b.caret ? D.gap + gw("▾", D.i === 1) : 0)); }
function pnlW(v) { return Math.ceil(Array.from(v).length * monoEm() * TYP(NUM).size) + (v[0] === "+" || v[0] === MINUS ? (S4 + NV["border.thick"]) * SC : 0); }
function pw(p, D) {
  if (p.sp != null) return p.sp * SC;
  if (p.g != null) return gw(p.g, D.i === 1);
  if (p.bar) return NV["border.thick"] * SC;
  if (p.lock) return D.icon;
  if (p.chip) return chipW(p.chip, D);
  if (p.btn) return btnW(p.btn, D);
  if (p.split) return splitW1(p.split, D) + D.split[1];
  if (p.sw) return toggleW(p.sw, D);
  if (p.cb != null) return D.icon;
  if (p.pnl != null) return p.slot != null ? Math.max(Math.ceil(p.slot * SC), pnlW(p.pnl)) : pnlW(p.pnl); // slot: a fixed right-aligned slot shared by a column's numerals (§12 numeric alignment)
  if (p.box) return p.box * SC;
  return p.safe || WSAFE ? twm(p.t, p.type || BODY) : tw(p.t, p.type || BODY);
}
let WSAFE = false; // fit()'s second pass measures the SAFE widths, to spend the slack where the offline estimate is wider than the tight one
const gapOf = (p, i, D) => (i === 0 ? 0 : (p.gb != null ? p.gb * SC : D.gap));
function partsW(list, D) { return (list || []).reduce((a, p, i) => a + pw(p, D) + gapOf(p, i, D), 0); }
let STALE = false; // a shaded (stale, offline, feed-down) row: its words take color.data-confidence.stale.text (§12)
const tcol = (c) => (STALE && (c === PRI || c === SEC || !c) ? "color.data-confidence.stale.text" : (c || PRI));
function drawPart(par, p, x, y0, h0, D, k, al, bx, bw) { // bx, bw: a text part's box when drawParts gives it the free room of its cell
  const cy = (h) => y0 + (h0 - h) / 2;
  if (p.sp != null) return;
  if (p.g != null) { const big = D.i === 1; gly(par, p.g, x, cy(NV[big ? "size.icon.md" : "size.icon.sm"] * SC * 1.2), { col: tcol(p.col || SEC), big, k, name: p.name || "glyph" }); return; }
  if (p.bar) { box(par, x, cy(D.icon), NV["border.thick"] * SC, D.icon, { fill: p.bar, name: "pnl-accent", k }); return; }
  if (p.lock) { lockIcon(par, x, cy(D.icon), D.i === 1, tcol(p.lock), k); return; }
  if (p.chip) { chip(par, x, cy(chipH(p.chip, D)), p.chip, D, k); return; }
  if (p.btn) { button(par, x, cy(p.btn.h ? p.btn.h * SC : D.ctl), p.btn, D, k); return; }
  if (p.split) { split(par, x, cy(D.ctl), p.split, D, k); return; }
  if (p.sw) { toggle(par, x, cy(D.ctl), p.sw, D, k); return; }
  if (p.cb != null) { checkbox(par, x, cy(D.icon), p.cb, D, k); return; }
  if (p.pnl != null) { // the numeral right-aligned in its box; the accent bar immediately left of the sign (JetBrains Mono: 0.60 em advance)
    const v = p.pnl, w = pw(p, D), nw = Math.ceil(Array.from(v).length * EM_MONO * TYP(NUM).size), right = x + w; // the box keeps the 0.63 em estimate in a measured panel too: it only reaches into the cell's free room on the left
    txt(par, v, right - nw, cy(th1(NUM)), nw, { type: NUM, col: tcol(PRI), align: "right", k, name: "pnl" });
    const hue = v[0] === "+" ? BUY : v[0] === MINUS ? SELL : null; // none at zero (D-6)
    if (hue) box(par, right - Array.from(v).length * 0.6 * TYP(NUM).size - (S4 + NV["border.thick"]) * SC, cy(D.icon), NV["border.thick"] * SC, D.icon, { fill: hue, name: "pnl-accent", k });
    return;
  }
  const type = p.type || BODY, T = TYP(type), w = bw != null ? bw : p.box ? p.box * SC : (p.safe || WSAFE ? twm : tw)(p.t, type);
  const h = (p.ml ? estLines(p.t, w, T.size, T.mono, T.weight) : String(p.t).split("\n").length) * T.size * T.lh;
  txt(par, p.t, bx != null ? bx : x, cy(h), w, { type, col: tcol(p.col), align: p.al || (al === "r" ? "right" : al === "c" ? "center" : "left"), k, name: p.name || "cell", deco: p.deco, ml: p.ml, grow: p.grow });
}
const plainText = (p) => p.t != null && p.pnl == null && !p.box && p.g == null && !p.chip && !p.btn && !p.split && !p.sw && p.cb == null && !p.lock && !p.bar && p.sp == null;
function drawParts(par, list, x0, x1, y0, h0, D, k, al, mode) { // left from x0, right ending at x1, or centred between them
  if (!list || !list.length) return 0;
  const prev = WSAFE;
  WSAFE = mode === "safe"; // one row (cells, headers, bands): TIGHT, so glyphs and tags sit close to their words; stacked lines (dialogs, menus, tooltips): SAFE when they fit
  if (WSAFE && partsW(list, D) > x1 - x0 + 0.5) WSAFE = false;
  let total = partsW(list, D), squeeze = 1;
  const soft = (p) => plainText(p) && !TYP(p.type || BODY).mono; // Inter words may give way; JetBrains Mono numerals never do
  if (total > x1 - x0 + 0.5) { // even TIGHT does not fit (the 360-px dock): the Inter words share what is left (auto-width, so they never wrap)
    const textW = list.reduce((a, p) => a + (soft(p) ? pw(p, D) : 0), 0);
    if (textW > 0) squeeze = Math.max(0.5, (textW - (total - (x1 - x0))) / textW);
    total = x1 - x0;
  }
  let x = al === "r" ? x1 - total : al === "c" ? x0 + (x1 - x0 - total) / 2 : x0;
  list.forEach((p, i) => {
    x += gapOf(p, i, D);
    const w = soft(p) ? pw(p, D) * squeeze : pw(p, D), last = i === list.length - 1;
    if (plainText(p) && list.length === 1 && al === "c") drawPart(par, p, x, y0, h0, D, k, al, x0, x1 - x0); // one label: centred on the whole room
    else if (plainText(p) && al === "l" && last && x1 - x > w) drawPart(par, p, x, y0, h0, D, k, al, x, x1 - x); // the last word run takes the free room to x1
    else if (plainText(p) && al === "r" && i === 0 && x > x0) drawPart(par, p, x, y0, h0, D, k, al, x0, x + w - x0); // the first takes the room back to x0
    else if (squeeze < 1 && soft(p)) drawPart(par, Object.assign({}, p, { grow: al === "r" ? undefined : "auto-width" }), x, y0, h0, D, k, al, x, w);
    else drawPart(par, p, x, y0, h0, D, k, al);
    x += w;
  });
  WSAFE = prev;
  return total;
}
function chip(par, x, y, c, D, k) { // a pill, tag or chip: fill and border by token, radius.badge, label(s) in type.ui.caption, NBSP-joined
  const h = chipH(c, D), w = chipW(c, D), size = TYP(CAP).size, multi = c.parts.length > 1;
  box(par, x, y, w, h, { fill: c.fill || "color.surface.raised", stroke: c.stroke, bw: c.bw, r: c.r || "radius.badge", name: c.name || "pill", k, role: "pill", sz: c.ctl ? D.ctlTok : "no height token (CR-7)" });
  let cx = x + chipPad(c);
  c.parts.forEach((p, i) => {
    if (i) cx += S4 * SC;
    if (p.g != null) { gly(par, p.g, cx, y + (h - NV[D.i ? "size.icon.md" : "size.icon.sm"] * SC * 1.2) / 2, { col: p.col || SEC, big: D.i === 1, k, name: "pill-glyph" }); cx += gw(p.g, D.i === 1); }
    else if (p.lock) { lockIcon(par, cx, y + (h - D.icon) / 2, D.i === 1, p.lock, k); cx += D.icon; }
    else if (p.dot) { box(par, cx, y + (h - DOT * SC) / 2, DOT * SC, DOT * SC, { fill: p.hollow ? null : p.dot, stroke: p.hollow ? p.dot : null, r: "radius.badge", name: "env-dot", k }); cx += DOT * SC; } // CMP-075's dot: filled for LIVE, an outline for DEMO (§6, E30-D02:267)
    else { const lw = pillTextW(p.t, size) + (p.bold ? Math.ceil(size * 0.4) : 0); txt(par, String(p.t).replace(/ /g, NBSP), cx, y + (h - th1(CAP)) / 2, lw, { type: CAP, col: p.col || PRI, align: multi ? "left" : "center", k, name: "pill-label", weightTok: p.bold ? "font.weight.bold" : undefined }); cx += lw; }
  });
  return w;
}
function button(par, x, y, b, D, k) { // CMP-001: primary, secondary, ghost, or T2 (disabled with a visible reason: raised fill, hairline, lock + tertiary label)
  const st = STALE; STALE = false; // a control on a shaded row keeps its own tokens (§12: an enabled control's text is color.text.primary); only cell words and numerals take the stale text
  try { return button0(par, x, y, b, D, k); } finally { STALE = st; }
}
function button0(par, x, y, b, D, k) {
  const w = btnW(b, D), h = b.h ? b.h * SC : D.ctl, kind = b.kind || "secondary";
  const fill = kind === "primary" ? "color.action.primary.default" : kind === "t2" ? "color.surface.raised" : kind === "ghost" ? null : "color.action.secondary.default"; // busy: CMP-038's busy form keeps the secondary fill
  const tc = kind === "primary" ? "color.text.on-action" : kind === "t2" ? (b.onSel ? SEC : TER) : (b.col || PRI);
  box(par, x, y, w, h, { fill, stroke: kind === "t2" ? "color.border.default" : (kind === "ghost" ? b.stroke : null), r: "radius.control", name: b.name || (kind === "t2" ? "button-t2" : "button"), k, sz: D.ctlTok });
  const parts = [];
  if (kind === "t2") parts.push({ lock: tc });
  if (kind === "busy") parts.push({ g: "⟳", col: tc }); // CMP-038's busy form: the spinner leads the unchanged label, no lock (busy is never T2, §3.8)
  parts.push({ t: b.t, type: LBL, col: tc, al: "center", safe: true });
  if (b.caret) parts.push({ g: "▾", col: tc });
  drawParts(par, parts, x, x + w, y, h, D, k, "c");
  if (b.arm) box(par, x + 2 * SC, y + h - 3 * SC, (w - 4 * SC) * b.arm, NV["border.thick"] * SC, { fill: "color.text.on-action", name: "arming-bar", k });
  return w;
}
function splitW1(s, D) { return s.fit ? Math.max(D.split[0], btnW({ t: s.t, kind: s.t2 ? "t2" : s.busy ? "busy" : "secondary" }, D)) : D.split[0]; } // the primary: 72 px for the row's verb (Close, Cancel); a label of its own ("Closing…", r3) is sized as a CMP-001 button: space.button.paddingX each side of the lock, its gap and the label
function split(par, x, y, s, D, k) { // CMP-057 SplitButton: primary + ▾, always visible (D-12); T2 per E09-D09 rendering 2b
  const st = STALE; STALE = false; // as button(): an enabled SplitButton on a shaded row keeps color.text.primary (§12)
  try { split0(par, x, y, s, D, k); } finally { STALE = st; }
}
function split0(par, x, y, s, D, k) {
  const w1 = splitW1(s, D), w2 = D.split[1], h = D.ctl, t2 = !!s.t2, busy = !t2 && !!s.busy, tc = t2 ? (s.onSel ? SEC : TER) : PRI;
  const fill = t2 ? "color.surface.raised" : "color.action.secondary.default", stroke = t2 ? "color.border.default" : null;
  box(par, x, y, w1 - SC, h, { fill, stroke, r: "radius.control", name: t2 ? "split-primary-t2" : busy ? "split-primary-busy" : "split-primary", k, sz: D.ctlTok });
  box(par, x + w1, y, w2, h, { fill, stroke, r: "radius.control", name: t2 ? "split-menu-t2" : "split-menu", k, sz: D.ctlTok });
  drawParts(par, t2 ? [{ lock: tc }, { t: s.t, type: LBL, col: tc }] : busy ? [{ g: "⟳", col: PRI }, { t: s.t, type: LBL, col: PRI }] : [{ t: s.t, type: LBL, col: tc }], x, x + w1 - SC, y, h, D, k, "c"); // busy (r4): CMP-001's loading state, the ⟳ spinner leading "Closing…", no lock (spec §8.1)
  drawParts(par, [{ g: "▾", col: tc }], x + w1, x + w1 + w2, y, h, D, k, "c");
  if (s.focus) ring(par, x, y, w1 - SC, h, k);
}
function checkbox(par, x, y, on, D, k) { // CMP-005: size.icon box, radius.xs; checked = color.action.selected + ✓; "off" = T2 (a DEMO row in a LIVE session, D-4): the lock marker inside the box (E09-D09 §2.2)
  const checked = on === true;
  box(par, x, y, D.icon, D.icon, { fill: checked ? "color.action.selected" : null, stroke: on === "off" ? TER : tcol(SEC), r: "radius.xs", name: checked ? "checkbox-checked" : on === "off" ? "checkbox-t2" : "checkbox", k });
  if (checked) gly(par, "✓", x, y + (D.icon - D.icon * 1.2) / 2, { col: PRI, big: D.i === 1, k, name: "checkbox-mark" });
  if (on === "off") lockIcon(par, x, y, D.i === 1, TER, k); // E09-D09 §2.2 T2: the lock glyph is the visible marker, so the border colour is not the only signal
}
function toggleW(s, D) { return 2 * D.icon + 4 * SC + D.gap + twm(s.t, LBL); } // CMP-004: the track (2 × size.icon + 4) and its label
function toggle(par, x, y, s, D, k) { // CMP-004 Toggle (Switch), off (role=switch, aria-checked=false): a color.surface.raised track with 1 px color.border.strong, the knob color.text.secondary at the left; the label after it in type.ui.label (CMP-004's color.action.on / off are not tokens: FINDING (d))
  const tw0 = 2 * D.icon + 4 * SC, th0 = D.icon + 4 * SC, ty = y + (D.ctl - th0) / 2;
  box(par, x, ty, tw0, th0, { fill: "color.surface.raised", stroke: "color.border.strong", r: "radius.badge", name: "switch-track", k });
  box(par, x + 2 * SC, ty + 2 * SC, D.icon, D.icon, { fill: SEC, r: "radius.badge", name: "switch-knob", k });
  drawParts(par, [{ t: s.t, type: LBL, col: PRI, safe: true }], x + tw0 + D.gap, x + toggleW(s, D), y, D.ctl, D, k, "l");
}
function ring(par, x, y, w, h, k) { return box(par, x, y, w, h, { stroke: "color.focus.ring", bw: "border.focus", name: "focus-ring", k }); } // 2 px inset (§11.3)
function iconBtn(par, x, y, ch, D, k, o) { o = o || {}; box(par, x, y, D.ctl, D.ctl, { stroke: o.stroke, r: "radius.control", name: "icon-button", k }); drawParts(par, [{ g: ch, col: o.col || SEC }], x, x + D.ctl, y, D.ctl, D, k, "c"); return D.ctl; }
const DOT = 6; // the ENV pill's dot (px, by value: no size token; E30-D02:267 gives the dot, not its size)
const envPill = (env) => ({ fill: "color.surface.raised", stroke: env === "DEMO" ? "color.env.demo" : "color.env.live", parts: [{ dot: env === "DEMO" ? "color.env.demo" : "color.env.live", hollow: env === "DEMO" }, { t: env, bold: env === "LIVE" }], name: "env-pill" }); // CMP-075 (§6; E30-D02:267): the word on color.surface.raised, the 1 px border and the dot in the env hue, LIVE in font.weight.bold with a filled dot
const tagC = (tone, glyph, label, o) => Object.assign({ fill: TONE[tone][0], parts: (glyph ? [glyph === "lock" ? { lock: TONE[tone][1] } : { g: glyph, col: TONE[tone][1] }] : []).concat([{ t: label }]), name: "tag-" + tone }, o || {});
const fchip = (label) => ({ ctl: true, padX: S8, fill: "color.surface.raised", stroke: "color.border.strong", parts: [{ t: label }, { g: "✕", col: SEC }], name: "filter-chip" }); // CMP-055 chip with its remove target
const tchip = (label) => ({ ctl: true, padX: S8, fill: "color.action.selected", stroke: "color.border.selected", parts: [{ g: "✓", col: PRI }, { t: label }], name: "type-chip-pressed" }); // aria-pressed toggle chip
function tipSize(lines, o) { // the tooltip's width and height for these lines (SAFE widths: its lines stack)
  o = o || {};
  const D = DZ(o.d || "compact"), pad = S8 * SC, lh = th1(CAP) + 2 * SC;
  const lw = (l) => { if (typeof l === "string") return twm(l, CAP); const prev = WSAFE; WSAFE = true; const w = partsW(l, D); WSAFE = prev; return w; };
  return { w: o.w ? o.w * SC : Math.ceil(Math.max.apply(null, lines.map(lw)) + 2 * pad), h: Math.ceil(lines.length * lh + 2 * S4 * SC + 2 * SC), lh, pad, D };
}
function tip(par, x, y, lines, o) { // CMP-016 tooltip: surface.overlay, border.default, radius.control, caption lines (a line may be parts)
  o = o || {};
  const k = K(), { w, h, lh, pad, D } = tipSize(lines, o);
  box(par, x, y, w, h, { fill: "color.surface.overlay", stroke: "color.border.default", r: "radius.control", name: "tooltip", k, bg: true });
  lines.forEach((l, i) => {
    const ly = y + S4 * SC + SC + i * lh;
    if (typeof l === "string") txt(par, l, x + pad, ly, w - 2 * pad, { type: CAP, col: o.col || PRI, k, name: "tooltip-line" });
    else drawParts(par, l, x + pad, x + w - pad, ly, lh, D, k, "l", "safe");
  });
  return { w, h, k };
}
function echo(par, x, y, lines, o) { return tip(par, x, y, lines, Object.assign({ col: SEC }, o || {})); } // r4: CMP-016's echo of a T2 reason, color.text.secondary on color.surface.overlay (E09-D09 §11.1; spec §12)
function menu(par, x, y, items, o) { // CMP-041 row menu: surface.overlay, border.default, radius.card; a T2 item shows its reason as a second line (E09-D09 2a); a pointer item (ptr, r4) keeps the lock and the full label with no second line: its reason is the scope's notice (spec §10.4)
  o = o || {};
  const D = DZ(o.d || "compact"), k = K(), w = (o.w || 220) * SC, pad = S8 * SC, inner = w - 2 * pad - D.icon - D.gap;
  const heights = items.map((it) => (it.t2 ? Math.ceil(th1(BODY) + estLines(it.t2, inner, TYP(CAP).size, false, 400) * th1(CAP) + (S4 + S8) * SC) : D.ctl + S4 * SC)); // items at control height (size.control.*) plus space.inset.xs
  const h = heights.reduce((a, b) => a + b, 0) + 2 * S4 * SC;
  if (o.up) y -= h; // o.up: y is the menu's bottom edge (it opens upward, flipping as a menu does when it would hide what it opens over)
  box(par, x, y, w, h, { fill: "color.surface.overlay", stroke: "color.border.default", r: "radius.card", name: "menu", k, bg: true });
  let cy = y + S4 * SC;
  items.forEach((it, i) => {
    if (it.focus) ring(par, x + 2 * SC, cy, w - 4 * SC, heights[i], k); // keyboard focus: 2 px inset color.focus.ring (§6; light's color.surface.hover equals color.surface.overlay, so a fill would not show)
    if (it.head) { txt(par, it.t, x + pad, cy + (heights[i] - th1(LBL)) / 2, w - 2 * pad, { type: LBL, col: SEC, k, name: "menu-heading" }); cy += heights[i]; return; }
    if (it.t2) {
      lockIcon(par, x + pad, cy + 4 * SC + (th1(BODY) - D.icon) / 2, false, TER, k);
      txt(par, it.t, x + pad + D.icon + D.gap, cy + 4 * SC, inner, { type: BODY, col: TER, k, name: "menu-item-t2" });
      txt(par, it.t2, x + pad + D.icon + D.gap, cy + 4 * SC + th1(BODY), inner, { type: CAP, col: SEC, k, name: "menu-item-reason", ml: true });
    } else if (it.ptr) {
      drawParts(par, [{ lock: TER }, { t: it.t, col: TER, name: "menu-item-t2-pointer" }], x + pad, x + w - pad, cy, heights[i], D, k, "l", "safe");
    } else {
      drawParts(par, (it.g ? [{ g: it.g, col: it.gcol || SEC }] : [{ sp: D.icon / SC }]).concat([{ t: it.t, col: it.col || PRI }]), x + pad, x + w - pad, cy, heights[i], D, k, "l", "safe");
    }
    cy += heights[i];
  });
  return { w, h, k };
}
function dlg(par, x, y, w, h, o) { // CMP-043 / CMP-044: surface.overlay, border.default, radius.dialog, padding space.dialog.padding (a popover: radius.card, space.stack.lg)
  o = o || {};
  const k = K(), P = NV[o.pad || "space.dialog.padding"] * SC;
  box(par, x, y, w * SC, h * SC, { fill: "color.surface.overlay", stroke: "color.border.default", r: o.r || "radius.dialog", name: o.name || "dialog", k, bg: true });
  return { k, x: x + P, y: y + P, w: w * SC - 2 * P, bottom: y + h * SC - P, right: x + w * SC - P };
}
function lines(par, dd, list, y0) { // stacked lines inside a dialog or card; returns the next y
  let y = y0;
  for (const l of list) {
    if (l.parts) { const D = DZ("compact"); drawParts(par, l.parts, dd.x, dd.x + dd.w, y, l.h || D.ctl, D, dd.k, "l", "safe"); y += (l.h || D.ctl) + (l.after == null ? 8 : l.after) * SC; continue; }
    const type = l.type || BODY, T = TYP(type);
    const r = txt(par, l.t, dd.x + (l.dx || 0), y, dd.w - (l.dx || 0), { type, col: l.col || PRI, k: dd.k, name: l.name || "dialog-line", ml: true });
    y += (r ? r.h : T.size * T.lh) + (l.after == null ? 8 : l.after) * SC;
  }
  return y;
}
function btnRow(par, dd, btns, D) { // the dialog's buttons, right-aligned on its bottom padding line
  const parts = btns.map((b, i) => ({ btn: b, gb: i ? 8 : 0 }));
  drawParts(par, parts, dd.x, dd.right, dd.bottom - D.ctl, D.ctl, D, dd.k, "r");
}
function field(par, x, y, w, D, value, o) { // a text field (CMP-100 / CMP-101 / typed confirm): canvas fill, border.strong (focused: 2 px color.focus.ring), radius.control
  o = o || {};
  const k = o.k || K(), h = o.h || D.ctl, rw = o.R ? partsW(o.R, D) + 8 * SC : 0;
  box(par, x, y, w, h, { fill: "color.surface.canvas", stroke: o.focus ? "color.focus.ring" : "color.border.strong", bw: o.focus ? "border.focus" : "border.hairline", r: "radius.control", name: o.name || "field", k });
  drawParts(par, [{ t: value, type: o.type || BODY, col: o.col }], x + S8 * SC, x + w - S8 * SC - rw, y, h, D, k, "l");
  if (o.R) drawParts(par, o.R, x + S8 * SC, x + w - S8 * SC, y, h, D, k, "r");
}
function note(par, x, y, w, str, o) { // an annotation outside the panel: type.ui.caption, color.text.secondary, on color.surface.app
  o = o || {};
  const r = txt(par, str, x, y, w, { type: CAP, col: o.col || SEC, k: o.k || K({ stk: o.stk, idx: o.idx }), name: o.name || "annotation", ml: true });
  return r ? r.h : 14;
}


// ---------------------------------------------------------------- board scaffolding -------------------------------------------
const built = [];
const FRAMES = []; // the SCR child frames of the board being built: { board, name, id, w, h }
const LAYOUT = []; // per panel (kept from the template: the dock rectangles a board reports; empty unless a builder pushes)
const BUILD = {}; // BUILD[n] = () => the board, recorded (place → frames → finish)
function boardX(n) { let x = 0; for (const bd of BOARDS) { if (bd.n < n) x += bd.w; } return x + (n - 1) * GAP; } // from the BOARDS table, never a per-call counter
let NOTES = null;
const THEMES = (bd) => (bd.theme === "dark+light" ? "dark and light" : bd.theme);
const DENSITIES = (bd) => (bd.density === "both" ? "compact and comfortable" : bd.density);
// the board frame (color.surface.app of its theme) and the 64 px source band: the eyebrow (type.ui.label, color.text.tertiary) and
// the title (type.ui.heading-md, color.text.primary) naming the spec section (board plan, "Bands on every board")
function place(n, title) {
  const bd = BOARDS.find((z) => z.n === n);
  TH = bd.theme === "light" ? "light" : "dark"; SC = 1; STALE = false;
  const b = mkShape("board"); // a record (penpot.createBoard in part 1, or the one call)
  b.name = TICKET + " / " + pad2(n) + " " + bd.slug;
  b.x = boardX(n); b.y = 0; b.resize(bd.w, 400);
  b.fills = [{ fillColor: col("color.surface.app"), fillOpacity: 1 }];
  set(b, { clipContent: false });
  const file = TICKET + "-" + pad2(n) + "-" + bd.slug + ".png";
  tag(b, { role: "board", board: n, slug: bd.slug, file, tok: "color.surface.app", theme: TH, themes: bd.theme, density: bd.density, plan: bd.plan, exportAs: EXPORT_DIR + "/" + file });
  try { b.setPluginData("hpe1ver", VERSION); } catch (e) { warn("hpe1ver", e); }
  bindLater(b, "color.surface.app", TOKEN_PROPS.fill);
  const X = b.x + M, W = bd.w - 2 * M, k = K();
  txt(b, TICKET + " · " + bd.scr + " · board " + pad2(n) + " · " + VERSION + " · " + THEMES(bd) + " · " + DENSITIES(bd), X, b.y + 12, W, { type: LBL, col: TER, k, name: "eyebrow" });
  const tr = txt(b, title, X, b.y + 32, W, { type: H_MD, k, name: "board-title", ml: true });
  NOTES = { stk: TICKET + ":notes:" + n, idx: 0 };
  return { b, n, X, W, y: Math.max(b.y + 88, b.y + 32 + (tr ? tr.h : 20) + 24), bd };
}
// a child frame: a board inside the board (it clips and exports alone), named "<board> / SCR-nnn/<state>": the spec's own frame
// name (§0: SCR-078/<state>, SCR-063/<state>, SCR-152/<state>; SCR-060/<state> for board 08's Submit strip) after the board's
// path, so a search for "SCR-078/anatomy-compact" finds it (r2); one block of its own (pad 0), so the relayout never moves it
function frame(B, suffix0, x, y, w, h, o) {
  o = o || {};
  const suffix = String(suffix0).replace(/\s*\/\s*/g, "/"); // "SCR-078 / loading" → "SCR-078/loading"
  const f = mkShape("board");
  f.name = B.b.name + " / " + suffix;
  f.x = x; f.y = y; f.resize(w, h);
  const fill = o.fill === undefined ? "color.surface.app" : o.fill;
  f.fills = fill ? [{ fillColor: col(fill), fillOpacity: 1 }] : [];
  set(f, { clipContent: true });
  const k = K();
  tag(f, { role: "frame", board: B.n, frame: suffix, tok: fill, theme: TH, blk: k.blk, stk: k.stk, idx: 0, pad: 0 });
  B.b.appendChild(f);
  if (fill) bindLater(f, fill, TOKEN_PROPS.fill);
  FRAMES.push({ board: B.n, name: f.name, id: f.id, w, h });
  return f;
}
// a frame sized to what it holds: made at the plan's height, then grown to its content's bottom plus a margin (never shorter);
// draw(f, x, y) returns the content's bottom (absolute y) or nothing
function framed(B, suffix, x, y, w, h, draw, o) {
  o = o || {};
  const f = frame(B, suffix, x, y, w, h, o), entry = FRAMES[FRAMES.length - 1];
  const bottom = draw(f, x, y), pad = o.pad != null ? o.pad : 12;
  let fh = h;
  if (typeof bottom === "number" && bottom - y + pad > h + 0.5) { fh = Math.ceil(bottom - y + pad); f.resize(w, fh); entry.h = fh; }
  return { f, h: fh };
}
// a frame caption under its frame (type.ui.caption, color.text.secondary): the section and the tokens; SAFE widths, so the measured
// text is never taller than the estimate that placed what follows; returns its height
function caption(B, x, y, w, str) { return note(B.b, x, y, w, str, { name: "frame-caption" }); }
// the a11y strip (every board: Focus order · Names · Keys · Live regions, each from spec §8), then the notes column, the footer
// "page <PAGE_NAME> · board NN · <VERSION> · <theme>" (r3: page, board, version and theme only; E13-D03's form), the board height, and the board's bindings handed to the record (flushed on the
// real shapes after the replay)
function finish(B, y, notes, a11y) {
  TH = B.bd.theme === "light" ? "light" : "dark"; SC = 1; STALE = false;
  let ny = y + 32;
  for (const s of notes || []) ny += note(B.b, B.X, ny, B.W, s, { stk: NOTES.stk, idx: NOTES.idx++ }) + 12;
  for (const [label, s] of a11y || []) ny += note(B.b, B.X, ny, B.W, label + ": " + s, { stk: NOTES.stk, idx: NOTES.idx++, name: "a11y-strip" }) + 6;
  const fh = note(B.b, B.X, ny + 28, B.W, "page " + PAGE_NAME + " · board " + pad2(B.n) + " · " + VERSION + " · " + THEMES(B.bd), { stk: NOTES.stk, idx: NOTES.idx++, col: TER, name: "footer" });
  B.b.resize(B.b.width, ny + 28 + fh + 32 - B.b.y);
  if (REC) { REC.binds = new Map(BQ); REC.bvq = BVQ.slice(); }
  const meta = JSON.parse(B.b.getPluginData(TAG + ":meta"));
  built.push({ n: B.n, name: B.b.name, id: B.b.id, exportAs: meta.exportAs, w: B.b.width, h: Math.round(B.b.height), theme: B.bd.theme, density: B.bd.density });
}
const annotate = (B, x, y, w, str, o) => note(B.b, x, y, w, str, o); // a free annotation (its own block)
// a redline: a 1 px dimension line with end ticks and its number (color.text.secondary, as E29-D02 board 21's)
function dimH(par, x, y, w, n, k) {
  box(par, x, y, w, 1, { fill: SEC, name: "redline", k });
  box(par, x, y - 3, 1, 7, { fill: SEC, name: "redline-tick", k }); box(par, x + w - 1, y - 3, 1, 7, { fill: SEC, name: "redline-tick", k });
  const nw = Math.max(16, twm(String(n), CAP) + 4);
  txt(par, String(n), x + w / 2 - nw / 2, y - 4 - th1(CAP), nw, { type: CAP, col: SEC, align: "center", k, name: "redline-number" });
}
function dimV(par, x, y, h, n, k, o) {
  o = o || {};
  box(par, x, y, 1, h, { fill: SEC, name: "redline", k });
  box(par, x - 3, y, 7, 1, { fill: SEC, name: "redline-tick", k }); box(par, x - 3, y + h - 1, 7, 1, { fill: SEC, name: "redline-tick", k });
  if (n != null) { const nw = Math.max(16, twm(String(n), CAP) + 4); txt(par, String(n), o.right ? x + 6 : x - 6 - nw, y + h / 2 - th1(CAP) / 2, nw, { type: CAP, col: SEC, align: o.right ? "left" : "right", k, name: "redline-number" }); }
}
// ---------------------------------------------------------------- copy: every string a board draws, with its source ----------
// C[key] = [string, source]. Sources: E15-D03 §5 / §9 (the copy deck; `D02` = E15-D02 verbatim), §3 / §4 / §10 table labels,
// E10-D03 §2.1's chrome map (the TopBar, NavRail, RightRail and StatusBar strings it fixes: robin · Owner, All (3), the
// HealthChips, the StatusBar's items), §1.6's fixtures (E15-D02's three workspace names and the 40-character name).
const C = {
  // §9 copy deck
  restoredChip: ["Restored", "§9 ws.tab.restored.chip (D02:130)"],
  saveClean: ["No unsaved changes", "§9 ws.save.clean (D02:280)"],
  saveRestored: ["Save restored layout", "§9 ws.save.restored (D02:130)"],
  splitterMin: ["Minimum size.", "§9 splitter.min (D02:383)"],
  compactNotice: ["Panel too small — showing compact view", "§9 panel.compact.notice (D02:389)"],
  // §1.6 fixtures and §5's populated-owner tabs
  wsScalping: ["Scalping", "§1.6 / §5 populated-owner"], wsSwing: ["Swing 4H", "§1.6 / §5 populated-owner"], wsFanout: ["Fanout review", "§1.6 / §5 populated-owner"],
  wsLong: ["Fanout review — EU session: BTCUSDT, ETH", "§1.6 the 40-character name"],
  // §4.5 / D-9 the toolbar
  tbLayout: ["Layout 1", "§4.5 [Layout 1 ▾] (CMP-217)"], tbSync: ["Sync: A", "§4.5 [Sync: A ▾] (CMP-218)"], tbAdd: ["Add panel", "§4.5 [Add panel]"], tbSave: ["Save", "§4.5 [Save]"],
  // §4.2.4 the chart's CMP-221 row and the kinds
  hdrCandle: ["Candle", "§4.2.4 chart row"], hdrFP: ["FP", "§4.2.4 chart row"], hdrInd: ["Ind", "§4.2.4 chart row"], hdrDraw: ["Draw", "§4.2.4 chart row"],
  syncAxes3: ["symbol, crosshair, drawings", "§4.2.1 #7, §4.2.4 (D-6)"], armed: ["ARMED 4:32", "§4.2.1 #9 (CMP-229)"],
  // E10-D03 §2.1 (the shell chrome, composed; its strings verbatim)
  wordmark: ["CandleViewer", "E10-D03 §2.1 / §0 (the wordmark is text)"], scope: ["All (3)", "E10-D03 §2.1 account scope"],
  search: ["Search commands", "E10-D03 §2.1 search trigger"], kbd: ["Ctrl+K", "E10-D03 §2.1 the Kbd hint"], user: ["robin · Owner", "E10-D03 §2.1 user menu"],
  flatten: ["FLATTEN ALL…", "E10-D03 §2.1 Safety cluster"], cancelAll: ["CANCEL ALL…", "E10-D03 §2.1 Safety cluster"], freeze: ["FREEZE…", "E10-D03 §2.1 Safety cluster"],
  killSwitch: ["Kill switch…", "E10-D03 §2.1 StatusBar"], version: ["v1.4.2", "E10-D03 §2.1 StatusBar"],
  clockLine: ["Clock offset +12 ms · 14:02:05 UTC · Bar close 00:42", "E10-D03 §2.1 StatusBar"],
};
const c = (key) => { const v = C[key]; if (!v) { warn("copy", "no copy key " + key); return "?"; } return v[0]; };
// E10-D03 §2.1's HealthChips row and StatusBar chips: [words, value] (the value in type.num.xs)
const HEALTH = [["Exchange WS: ok", "38 ms"], ["Ingest lag: ok", "0.4 s"], ["Recorder: ok", "3 symbols"], ["Rate budget: ok", "41 %"]];
const STATUS_CHIPS = [["Live", "42 ms", true], ["Recorder:", "3 symbols"], ["Rules:", "3 armed"]];
// E10-D03 §2.1 / §5.1 the collapsed NavRail (Terminal current; counts 3 and 2 as CMP-012 badges) and the RightRail strip's launchers;
// the glyphs are CMP-019 placeholders by name (terminal, rules, journal, replay, alerts, settings, admin), never a colour emoji
const RAIL = [["terminal", "▣"], ["rules", "⚑", "3"], ["journal", "▤"], ["replay", "▶"], ["alerts", "◎", "2"], ["settings", "⚙"]];
const RAIL_ADMIN = ["admin", "◈"];
const LAUNCHERS = [["alerts", "◎"], ["notifications", "▤"], ["recorder", "●"]];
// ---------------------------------------------------------------- shared hi-fi workspace chrome ---------------------------------
// The SCR-020 shell in colour: E10-D03 §2.1's TopBar / NavRail / RightRail strip / StatusBar (composed, its tokens), E15-D03's tab
// strip and toolbar (§4.4, §4.5, §10), the CMP-080 panel frame with its inset focus reservation and header bar slot (§4.1, D-1),
// the CMP-082 header with its slots (§4.2.1), CMP-081's gutter and splitter (§4.3). Geometry from the audit values (A) and the
// tokens (NV); no number is typed where the spec or the tool gives it.
const HEADER_OVER = {}; // the template's result slot: a header whose items overrun its room ({ panel, need, room })
const SP1 = NV["space.1"], SP2 = NV["space.2"], SP3 = NV["space.3"], SP4 = NV["space.4"];
const TOPBAR_H = AN("v.topbar"), STATUSBAR_H = AN("v.statusbar"), NAVRAIL_W = AN("h.navrail"), STRIP_W = AN("h.rightrail-strip");
const GUTTER = AN("h.gutter"), HITBAND = AN("h.hitband"), FOCUS_PX = AN("focus.frame-px"), BAR_PX = AN("focus.bar-px");
const PRICE_GUTTER = { compact: AN("parent.price_gutter.compact"), comfortable: AN("parent.price_gutter.comfortable") }; // the parent's price gutter (E15-D02 §3, the tool's parent figures)
const ROWS = (d) => ({ tab: AN("v.tabstrip." + d), header: AN("v.header." + d), status: AN("v.status." + d), time: AN("v.timestrip." + d), banner: AN("v.banner." + d), restore: AN("v.restore." + d), tray: AN("v.tray." + d), group: AN("v.tabgroup." + d) });
function hair(par, x, y, w, h, tok, name, k) { return box(par, x, y, w, h, { fill: tok || "color.border.default", name: name || "hairline", k }); } // a border.hairline (1 px) or border.thick rule as a filled rect
const lw500 = (s) => Math.ceil(lineW(String(s), TYP(LBL).size, false, 500, false));
const lw600 = (s) => Math.ceil(lineW(String(s), TYP(LBL).size, false, 600, false)); // D-7: a tab is laid out at its semibold width
const cy0 = (y, h, type) => y + (h - th1(type)) / 2;

// CMP-075 / CMP-074 env badge (E10-D03 §1.2, four channels): the word in color.text.primary on the color.surface.raised pill, DEMO
// font.weight.medium / LIVE font.weight.bold, the glyph (outline dot DEMO, filled dot LIVE, a 16 px slot) and the border.thick rule
// in color.env.*; LIVE adds a border.thick underline in color.env.live; radius.pill; space.2 padding; 20 / 24 tall (D.env)
function envW(env) { return Math.ceil(2 * SP2 + lw600(env) + (env === "LIVE" ? 2 : 0) + SP1 + NV["size.icon.md"]); }
function envBadge(par, x, y, env, D, o) {
  o = o || {};
  const k = o.k || K(), h = o.h || D.env, live = env === "LIVE", hue = live ? "color.env.live" : "color.env.demo", w = envW(env);
  box(par, x, y, w, h, { fill: "color.surface.raised", stroke: hue, bw: "border.thick", r: "radius.pill", name: "env-badge", k, role: "pill" });
  const ww = lw600(env) + (live ? 2 : 0), ty = cy0(y, h, LBL);
  txt(par, env, x + SP2, ty, ww, { type: LBL, col: PRI, weightTok: live ? "font.weight.bold" : undefined, k, name: "env-word" });
  if (live) hair(par, x + SP2, ty + th1(LBL) - 2, ww, NV["border.thick"], hue, "env-live-underline", k);
  const ds = 8, dx = x + w - SP2 - NV["size.icon.md"] + (NV["size.icon.md"] - ds) / 2, dy = y + (h - ds) / 2;
  box(par, dx, dy, ds, ds, { fill: live ? hue : null, stroke: live ? null : hue, bw: "border.thick", r: "radius.pill", name: live ? "env-dot-filled" : "env-dot-outline", k });
  return w;
}
// a 24 / 32 px chrome control (E10-D03 §2.1: account scope, workspace switcher, symbol, interval, user menu): color.surface.raised,
// a color.border.strong hairline, radius.control, space.2 padding, the label in type.ui.label color.text.primary, the chevron secondary
function ctlW(label, caret) { return Math.ceil(2 * SP2 + lw500(label) + (caret ? SP1 + NV["size.icon.sm"] : 0)); }
function ctl(par, x, y, label, D, o) {
  o = o || {};
  const k = o.k || K(), w = o.w || ctlW(label, o.caret !== false);
  box(par, x, y, w, D.ctl, { fill: o.fill || "color.surface.raised", stroke: o.stroke === undefined ? "color.border.strong" : o.stroke, bw: o.bw, r: "radius.control", name: o.name || "control", k, sz: D.ctlTok });
  const parts = [{ t: String(label).replace(/ /g, NBSP), type: LBL, col: o.col || PRI, safe: true }].concat(o.caret === false ? [] : [{ g: "▾", col: SEC }]);
  drawParts(par, parts, x, x + w, y, D.ctl, Object.assign({}, D, { i: 0 }), k, "c");
  return w;
}

// ---------------------------------------------------------------- TopBar (CMP-072; E10-D03 §2.1): 80 = a 48 row + the 32 HealthChips row
function topBar(par, x, y, w, D, o) {
  o = o || {};
  const k = K(), h1 = 48, cy = y + (h1 - D.ctl) / 2, ins = D.ins;
  box(par, x, y, w, TOPBAR_H, { fill: "color.surface.raised", name: "topbar", k });
  hair(par, x, y + TOPBAR_H - 1, w, 1, "color.border.default", "topbar-rule", k);
  let cx = x + ins + SP2;
  const wm = c("wordmark"), wmw = twm(wm, H_SM) + 4; // SAFE width: the wordmark never runs into the badge
  txt(par, wm, cx, cy0(y, h1, H_SM), wmw, { type: H_SM, col: PRI, k, name: "wordmark" });
  cx += wmw + SP2;
  for (const env of o.envs || ["LIVE"]) cx += envBadge(par, cx, y + (h1 - D.env) / 2, env, D, { k }) + SP2;
  for (const label of [c("scope"), c("wsScalping"), "BTCUSDT", "1m"]) cx += ctl(par, cx, cy, label, D, { k, name: "topbar-control" }) + SP2;
  if (w >= 1900) { // E10-D03 §2.2: the search trigger widens to 240 px at 1920
    const sw = 240;
    box(par, cx, cy, sw, D.ctl, { fill: "color.surface.raised", stroke: "color.border.strong", r: "radius.control", name: "search-trigger", k });
    searchGlyph(par, cx + SP2, cy + (D.ctl - 16) / 2, k);
    drawParts(par, [{ t: c("search"), type: LBL, col: SEC }], cx + SP2 + 16 + SP1, cx + sw - 2 * SP2 - kbdW(c("kbd")), cy, D.ctl, D, k, "l");
    kbd(par, cx + sw - SP2 - kbdW(c("kbd")), cy + (D.ctl - 16) / 2, c("kbd"), k);
    cx += sw + SP2;
  } else { // E10-D03 §2.2 at 1280: the 24 px icon button with its Ctrl+K Kbd hint beside it
    box(par, cx, cy, D.ctl, D.ctl, { fill: "color.surface.raised", stroke: "color.border.strong", r: "radius.control", name: "search-trigger", k });
    searchGlyph(par, cx + (D.ctl - 16) / 2, cy + (D.ctl - 16) / 2, k);
    cx += D.ctl + SP1;
    kbd(par, cx, cy + (D.ctl - 16) / 2, c("kbd"), k);
    cx += kbdW(c("kbd")) + SP2;
  }
  // right: the user menu, then the Safety cluster (CMP-211; E39-D03 §5 as E10-D03 §2.1 composes it): FLATTEN ALL… / CANCEL ALL…
  // outline (color.surface.raised, a color.status.danger.default hairline, color.text.primary); FREEZE… color.text.on-action on
  // color.status.danger.default; space.2 apart
  const sl = [c("flatten"), c("cancelAll"), c("freeze")], sws = sl.map((l) => ctlW(l, false) + 2 * SP2);
  let rx = x + w - ins - sws.reduce((a, b) => a + b, 0) - SP2 * (sl.length - 1);
  const uw = ctlW(c("user"), true), ux = rx - SP3 - uw;
  if (ux < cx) warn("topbar", "the right group overlaps the left group by " + Math.ceil(cx - ux) + " px at " + w);
  ctl(par, ux, cy, c("user"), D, { k, name: "user-menu" });
  sl.forEach((l, i) => {
    const fz = i === 2;
    ctl(par, rx, cy, l, D, { k, w: sws[i], caret: false, fill: fz ? "color.status.danger.default" : "color.surface.raised", stroke: fz ? null : "color.status.danger.default", col: fz ? "color.text.on-action" : PRI, name: ["flatten-all", "cancel-all", "freeze"][i] });
    rx += sws[i] + SP2;
  });
  // row 2: the HealthChips (CMP-210): 20 / 24 chips, radius.pill, space.2 padding, 8 px gaps, a 16 px tone glyph leading; the
  // words type.ui.caption color.text.primary, the value type.num.xs color.text.secondary (E10-D03 §2.1)
  let hx = x + ins + SP2;
  const ch = D.env, hy = y + h1 + (TOPBAR_H - h1 - ch) / 2;
  for (const [words, val] of o.health || HEALTH) hx += healthChip(par, hx, hy, words, val, ch, k, "color.status.success.strong") + SP2;
  return { h: TOPBAR_H };
}
function chipTextW(s, type) { return Math.ceil(lineW(String(s), TYP(type).size, TYP(type).mono, TYP(type).weight, true)) + 2; }
function healthChip(par, x, y, words, val, h, k, glyphTok) {
  const gwid = NV["size.icon.md"], w = SP2 + (glyphTok ? gwid + SP1 : 0) + chipTextW(words, CAP) + (val ? SP1 + chipTextW(val, "type.num.xs") : 0) + SP2;
  box(par, x, y, w, h, { fill: "color.surface.raised", stroke: "color.border.default", r: "radius.pill", name: "health-chip", k, role: "pill" });
  let cx = x + SP2;
  if (glyphTok) { box(par, cx + (gwid - 8) / 2, y + (h - 8) / 2, 8, 8, { fill: glyphTok, r: "radius.pill", name: "tone-glyph", k }); cx += gwid + SP1; }
  txt(par, words.replace(/ /g, NBSP), cx, cy0(y, h, CAP), chipTextW(words, CAP), { type: CAP, col: PRI, k, name: "chip-words" });
  cx += chipTextW(words, CAP) + SP1;
  if (val) txt(par, val.replace(/ /g, NBSP), cx, cy0(y, h, "type.num.xs"), chipTextW(val, "type.num.xs"), { type: "type.num.xs", col: SEC, k, name: "chip-value" });
  return w;
}
// CMP-022 Kbd (§4.8; E10-D03 §2.1): color.surface.raised, a color.border.strong hairline, radius.xs, the mono key in type.num.xs
function searchGlyph(par, x, y, k) { // the CMP-019 search glyph in a size.icon.md slot: a ring and a handle (two shapes, no path)
  box(par, x + 2, y + 2, 9, 9, { stroke: SEC, bw: "border.thick", r: "radius.pill", name: "search-ring", k });
  box(par, x + 10, y + 10, 4, 4, { fill: SEC, r: "radius.xs", name: "search-handle", k });
}
function kbdW(key) { return chipTextW(key, "type.num.xs") + 2 * SP1; }
function kbd(par, x, y, key, k) {
  const w = kbdW(key);
  box(par, x, y, w, 16, { fill: "color.surface.raised", stroke: "color.border.strong", r: "radius.xs", name: "kbd", k });
  txt(par, key, x + SP1, cy0(y, 16, "type.num.xs"), w - 2 * SP1, { type: "type.num.xs", col: SEC, k, name: "kbd-key", align: "center" });
  return w;
}

// ---------------------------------------------------------------- NavRail collapsed (CMP-071; E10-D03 §2.1, §5): 64 = a 32 px item + space.4 each side
function navRail(par, x, y, h, D, o) {
  o = o || {};
  const k = K(), it = 32, ix = x + SP4;
  box(par, x, y, NAVRAIL_W, h, { fill: "color.surface.raised", name: "navrail", k });
  hair(par, x + NAVRAIL_W - 1, y, 1, h, "color.border.default", "navrail-rule", k);
  const item = (g, yy, current, count) => {
    if (current) { // current: color.surface.selected + a 3 px leading bar in color.border.selected + the weight (never colour alone)
      box(par, ix, yy, it, it, { fill: "color.surface.selected", r: "radius.control", name: "rail-item-current", k });
      box(par, x + SP1, yy, BAR_PX, it, { fill: "color.border.selected", name: "rail-current-bar", k });
    }
    gly(par, g, ix + (it - NV["size.icon.md"]) / 2, yy + (it - NV["size.icon.md"] * 1.2) / 2, { big: true, col: PRI, k, name: "rail-glyph" });
    if (count) { // the CMP-012 count badge: color.status.info.subtle, the word color.text.primary
      const bw = 16, bx = ix + it - 6, by = yy - 6; // top-right of the item, clear of its glyph
      box(par, bx, by, bw, bw, { fill: "color.status.info.subtle", r: "radius.pill", name: "rail-count", k, role: "pill" });
      txt(par, count, bx, cy0(by, bw, CAP), bw, { type: CAP, col: PRI, align: "center", k, name: "rail-count-word" });
    }
  };
  RAIL.forEach(([, g, count], i) => item(g, y + SP4 + i * (it + SP2), i === 0, count));
  if (o.admin !== false && h > 360) item(RAIL_ADMIN[1], y + h - SP4 - it, false);
}
// RightRail (CMP-209) collapsed to its 48 px strip (a 40 px launcher with space.1 each side): color.surface.raised, a hairline on the inner edge
function rightStrip(par, x, y, h) {
  const k = K(), lw = STRIP_W - 2 * SP1;
  box(par, x, y, STRIP_W, h, { fill: "color.surface.raised", name: "rightrail-strip", k });
  hair(par, x, y, 1, h, "color.border.default", "rightrail-rule", k);
  LAUNCHERS.forEach(([, g], i) => {
    const ly = y + SP1 + i * (lw + SP1);
    box(par, x + SP1, ly, lw, lw, { stroke: "color.border.default", r: "radius.control", name: "drawer-launcher", k });
    gly(par, g, x + SP1 + (lw - NV["size.icon.md"]) / 2, ly + (lw - NV["size.icon.md"] * 1.2) / 2, { big: true, col: PRI, k, name: "launcher-glyph" });
  });
}
// StatusBar (CMP-208; E10-D03 §2.1): 48, color.surface.sunken, a hairline above; space.inset.sm; chips as the HealthChips; the clock
// line; Kill switch… a 24 px outline button; the ENV repeat (CMP-075); the version color.text.tertiary
function statusBar(par, x, y, w, D, o) {
  o = o || {};
  const k = K(), ins = D.ins, ch = D.env, chy = y + (STATUSBAR_H - ch) / 2;
  box(par, x, y, w, STATUSBAR_H, { fill: "color.surface.sunken", name: "statusbar", k });
  hair(par, x, y, w, 1, "color.border.default", "statusbar-rule", k);
  let cx = x + ins;
  for (const [words, val, live] of STATUS_CHIPS) cx += healthChip(par, cx, chy, words, val, ch, k, live ? "color.status.success.strong" : null) + SP2;
  const cl = c("clockLine"), clw = chipTextW(cl, CAP);
  txt(par, cl, cx + SP2, cy0(y, STATUSBAR_H, CAP), clw, { type: CAP, col: SEC, k, name: "status-clock" });
  const vw = chipTextW(c("version"), "type.num.xs"), env = o.env || "LIVE", ew = envW(env), kw = ctlW(c("killSwitch"), false) + 2 * SP2;
  let rx = x + w - ins - vw;
  txt(par, c("version"), rx, cy0(y, STATUSBAR_H, "type.num.xs"), vw, { type: "type.num.xs", col: TER, k, name: "version" });
  rx -= SP3 + ew; envBadge(par, rx, y + (STATUSBAR_H - D.env) / 2, env, D, { k });
  rx -= SP3 + kw; ctl(par, rx, y + (STATUSBAR_H - NV["size.control.compact"]) / 2, c("killSwitch"), Object.assign({}, D, { ctl: NV["size.control.compact"] }), { k, w: kw, caret: false, fill: null, stroke: "color.border.strong", name: "kill-switch" });
  if (rx < cx + SP2 + clw + SP3) warn("statusbar", "the right group overlaps the clock line at " + w);
}

// ---------------------------------------------------------------- the workspace tab strip and toolbar (§4.4, §4.5, §10) ----------
// Row: color.surface.raised, a bottom border.hairline color.border.default, 32 / 40 tall; a tab = its label (type.ui.label, laid out at
// the semibold width, D-7) + its markers + space.3 each side; active: font.weight.semibold, color.text.primary, a border.thick underline
// color.text.primary, its ×; inactive color.text.secondary; "+" CMP-002. The toolbar: CMP-001 secondary buttons (color.surface.raised,
// border.hairline color.border.default, color.text.primary; never the action blue) at size.control.*, space.2 apart, space.3 from the edge
const TABS_OWNER = () => [{ t: c("wsScalping"), active: true }, { t: c("wsSwing") }, { t: c("wsFanout") }];
function tbW(label, caret) { return Math.ceil(2 * NV["space.button.paddingX"] + lw500(label) + (caret ? SP1 + NV["size.icon.sm"] : 0)); }
function tbBtn(par, x, y, label, D, o) {
  o = o || {};
  const k = o.k || K(), w = o.w || tbW(label, o.caret);
  box(par, x, y, w, D.ctl, { fill: "color.surface.raised", stroke: "color.border.default", r: "radius.control", name: o.name || "toolbar-button", k, sz: D.ctlTok });
  drawParts(par, [{ t: String(label).replace(/ /g, NBSP), type: LBL, col: o.col || PRI, safe: true }].concat(o.caret ? [{ g: "▾", col: SEC }] : []), x, x + w, y, D.ctl, Object.assign({}, D, { i: 0 }), k, "c");
  return w;
}
function tabStrip(par, x, y, w, D, o) {
  o = o || {};
  const k = K(), h = D.tb, ty = y + (h - D.ctl) / 2, pos = {};
  box(par, x, y, w, h, { fill: "color.surface.raised", name: "tab-strip", k });
  hair(par, x, y + h - 1, w, 1, "color.border.default", "tab-strip-rule", k);
  let tx = x + SP2;
  for (const t of o.tabs || TABS_OWNER()) {
    const lw = lw600(t.t), xw = t.active ? SP1 + NV["size.icon.sm"] : 0, tw0 = SP3 + lw + xw + SP3;
    txt(par, t.t, tx + SP3, cy0(ty, D.ctl, LBL), lw, { type: LBL, col: t.active ? PRI : SEC, weightTok: t.active ? "font.weight.semibold" : undefined, k, name: t.active ? "tab-active" : "tab" });
    if (t.active) {
      gly(par, "✕", tx + SP3 + lw + SP1, cy0(ty, D.ctl, LBL) + (th1(LBL) - NV["size.icon.sm"] * 1.2) / 2, { col: SEC, k, name: "tab-close" });
      hair(par, tx + SP3, y + h - 1 - NV["border.thick"], lw + xw, NV["border.thick"], PRI, "tab-underline", k);
    }
    pos[t.t] = { x: tx, w: tw0 };
    tx += tw0;
  }
  box(par, tx + SP1, ty, D.ctl, D.ctl, { r: "radius.control", name: "tab-new", k });
  gly(par, "+", tx + SP1 + (D.ctl - NV["size.icon.md"]) / 2, ty + (D.ctl - NV["size.icon.md"] * 1.2) / 2, { big: true, col: SEC, k, name: "tab-new-glyph" });
  tx += SP1 + D.ctl;
  // the right cluster (§3.5): [Layout 1 ▾] [Sync: A ▾] [Add panel] [Save] [⋯]
  const items = [[c("tbLayout"), true], [c("tbSync"), true], [c("tbAdd")], [o.saveLabel || c("tbSave"), false, o.saveClean !== false && !o.saveLabel]];
  const ws = items.map(([l, caret]) => tbW(l, caret));
  let rx = x + w - SP3 - D.ctl - ws.reduce((a, b) => a + b, 0) - SP2 * items.length;
  pos.cluster = { x: rx, w: x + w - rx };
  if (rx < tx + SP3) warn("tab strip", "the toolbar overlaps the tabs at " + w);
  items.forEach(([l, caret, clean], i) => { tbBtn(par, rx, ty, l, D, { k, caret, col: clean ? "color.text.disabled" : PRI, name: clean ? "toolbar-save-clean" : "toolbar-button" }); rx += ws[i] + SP2; }); // Save, clean: availability "No unsaved changes" (D02:280; no lock: not T2)
  box(par, rx, ty, D.ctl, D.ctl, { fill: "color.surface.raised", stroke: "color.border.default", r: "radius.control", name: "toolbar-more", k });
  gly(par, "⋯", rx + (D.ctl - NV["size.icon.md"]) / 2, ty + (D.ctl - NV["size.icon.md"] * 1.2) / 2, { big: true, col: SEC, k, name: "toolbar-more-glyph" });
  return { h, pos };
}

// ---------------------------------------------------------------- CMP-080 DockPanel and CMP-082 PanelHeader (§4.1, §4.2) ---------
// The frame: radius.card, body color.surface.canvas; 2 px reserved per side (D-1): unfocused an outer border.hairline color.border.default
// and an inner hairline color.surface.canvas; focused the full reservation color.focus.ring (border.focus), painted INSIDE the box, so the
// content box never moves (§3.4). elevation.card in every state (a shadow: not drawn by this script, recorded in the meta). The header
// (24 / 32): color.surface.raised, a bottom border.hairline color.border.default, side insets space.3; the 3 px bar slot at its left
// edge inside space.3 (empty color.surface.raised, focused color.focus.ring; CR-5).
function grip(par, x, y, D, k, tok) { // the CMP-019 grip in its size.icon.* slot: 2 × 3 dots (no path, no text stand-in)
  const s = D.icon, d = 2, gx = [x + s / 2 - 3, x + s / 2 + 1], gyy = [0, 1, 2].map((i) => y + (s - 10) / 2 + i * 4);
  for (const yy of gyy) for (const xx of gx) box(par, xx, yy, d, d, { fill: tok || TER, name: "grip-dot", k });
}
function kebab(par, x, y, k) { // the CMP-019 more-vertical glyph in a size.icon.md slot: three dots, color.text.secondary
  for (let i = 0; i < 3; i++) box(par, x + 7, y + 3 + i * 4.5, 2, 2, { fill: SEC, name: "kebab-dot", k });
}
function iconBtnX(par, x, y, D, kind, k, hover) { // CMP-002 IconButton, size.control.* square; glyph size.icon.md color.text.secondary; hovered: color.surface.hover
  box(par, x, y, D.ctl, D.ctl, { fill: hover ? "color.surface.hover" : undefined, r: "radius.control", name: (kind === "menu" ? "panel-options" : "panel-close") + (hover ? "-hover" : ""), k });
  const gx = x + (D.ctl - 16) / 2, gy = y + (D.ctl - 16) / 2;
  if (kind === "menu") kebab(par, gx, gy, k); else gly(par, "✕", gx, y + (D.ctl - 16 * 1.2) / 2, { big: true, col: SEC, k, name: "panel-close-glyph" });
  return D.ctl;
}
const SYNC_A = (words) => ({ letter: "A", words: words == null ? c("syncAxes3") : words });
function syncWords(s) { return s === "none" ? null : s.words ? "· " + s.words : null; }
function syncW(s) { const lead = s === "none" ? "No sync" : s.letter, wd = syncWords(s); return Math.ceil(2 * SP2 + chipTextW(lead, CAP) + 2 + (wd ? SP1 + chipTextW(wd, CAP) : 0)); }
function syncBadge(par, x, y, s, D, k) { // D-6: a CMP-011-style chip, color.surface.raised, border.hairline color.border.strong, the letter font.weight.bold color.text.primary, the axes words color.text.secondary; "No sync" on an unsynced market panel
  const w = syncW(s), h = D.pill, ty = cy0(y, h, CAP), none = s === "none", lead = none ? "No sync" : s.letter, lw = chipTextW(lead, CAP) + 2, wd = syncWords(s);
  box(par, x, y, w, h, { fill: "color.surface.raised", stroke: "color.border.strong", r: "radius.badge", name: "sync-badge", k, role: "pill" });
  txt(par, lead.replace(/ /g, NBSP), x + SP2, ty, lw, { type: CAP, col: none ? SEC : PRI, weightTok: none ? undefined : "font.weight.bold", k, name: "sync-letter" });
  if (wd) txt(par, wd.replace(/ /g, NBSP), x + SP2 + lw + SP1, ty, chipTextW(wd, CAP), { type: CAP, col: SEC, k, name: "sync-words" });
  return w;
}
// one header row: P = { kind, symbol, interval, chartTools, prov, sync, env, arm, actions, focused, close (default true) }
function panelHeader(par, hx, hy, hw, D, P, k) {
  const hh = D.ctl;
  box(par, hx, hy, hw, hh, { fill: "color.surface.raised", r: "radius.control", name: "panel-header", k });
  hair(par, hx, hy + hh - 1, hw, 1, "color.border.default", "panel-header-rule", k);
  box(par, hx, hy, BAR_PX, hh, { fill: P.focused ? "color.focus.ring" : "color.surface.raised", name: P.focused ? "focus-bar" : "focus-bar-slot", k });
  let x = hx + SP3;
  grip(par, x, hy + (hh - D.icon) / 2, D, k, P.gripTok);
  if (P.pos) P.pos.push({ n: 2, x, w: D.icon + SP1 });
  x += D.icon + SP1 + D.hgap;
  const Dc = Object.assign({}, D, { i: 0 }), item = (w, draw, n) => { if (P.pos && n) P.pos.push({ n, x, w }); draw(x); x += w + D.hgap; };
  if (P.kind) { const w = lw600(P.kind); item(w, (ix) => txt(par, P.kind, ix, cy0(hy, hh, LBL), Math.max(w, twm(P.kind, LBL) + 1), { type: LBL, col: PRI, weightTok: "font.weight.semibold", k, name: "kind-word" }), 3); }
  const picker = (label, n) => { const w = lw500(label) + SP1 + NV["size.icon.sm"]; item(w, (ix) => drawParts(par, [{ t: label, type: LBL, col: PRI }, { g: "▾", col: SEC }], ix, ix + w, hy, hh, Dc, k, "l"), n); };
  if (P.symbol) picker(P.symbol, 4);
  if (P.symText) { const w = lw500(P.symText); item(w, (ix) => txt(par, P.symText, ix, cy0(hy, hh, LBL), Math.max(w, twm(P.symText, LBL) + 1), { type: LBL, col: PRI, k, name: "symbol-text" }), 4); } // the compact view: the symbol as text (§4.2.3)
  if (P.scope) { const w = lw500(P.scope); item(w, (ix) => txt(par, P.scope, ix, cy0(hy, hh, LBL), Math.max(w, twm(P.scope, LBL) + 1), { type: LBL, col: PRI, k, name: "scope-text" })); } // §4.2.1 #4: an account kind's "all symbols" as text (no picker)
  if (P.interval) picker(P.interval, 5);
  if (P.status) { const w = chipTextW(P.status, CAP); item(w, (ix) => txt(par, P.status, ix, cy0(hy, hh, CAP), w, { type: CAP, col: SEC, k, name: "status-slot" }), 0); } // §4.2.2 stale / disconnected: E17-D02's words in a fixed-width slot right of the symbol
  if (P.chartTools) { picker(c("hdrCandle"), 10); for (const t of [c("hdrFP"), c("hdrInd"), c("hdrDraw")]) { const w = lw500(t); item(w, (ix) => txt(par, t, ix, cy0(hy, hh, LBL), w, { type: LBL, col: PRI, k, name: "chart-tool" })); } }
  if (P.prov) { const w = chipTextW(P.prov, CAP); item(w, (ix) => txt(par, P.prov, ix, cy0(hy, hh, CAP), w, { type: CAP, col: SEC, k, name: "provenance" }), 6); }
  if (P.sync) { const w = syncW(P.sync); item(w, (ix) => syncBadge(par, ix, hy + (hh - D.pill) / 2, P.sync, D, k), 7); }
  if (P.reduced) { const w = 2 * SP2 + chipTextW(P.reduced, CAP); item(w, (ix) => { box(par, ix, hy + (hh - D.pill) / 2, w, D.pill, { fill: "color.surface.overlay", stroke: "color.border.strong", r: "radius.badge", name: "reduced-chip", k, role: "pill" }); txt(par, P.reduced, ix + SP2, cy0(hy, hh, CAP), w - 2 * SP2, { type: CAP, col: PRI, k, name: "reduced-label" }); }, 0); } // §4.2.2 reduced: CMP-011 neutral, right of the sync badge
  if (P.env) { const w = envW(P.env); item(w, (ix) => envBadge(par, ix, hy + (hh - D.env) / 2, P.env, D, { k }), 8); }
  if (P.arm) { // CMP-229 (E30's): armed = the attention pill (color.status.warning.subtle); LOCKED = neutral (color.surface.raised, a color.border.strong hairline); T2 (R-7) = the lock leading, the label color.text.tertiary (§1.4)
    const t2 = P.armForm === "t2", neutral = P.armForm === "neutral" || t2, lk = t2 ? NV["size.icon.sm"] + S4 : 0, w = 2 * S8 + lk + lw500(P.arm);
    item(w, (ix) => {
      box(par, ix, hy, w, hh, { fill: neutral ? "color.surface.raised" : "color.status.warning.subtle", stroke: neutral ? (t2 ? "color.border.default" : "color.border.strong") : undefined, r: "radius.pill", name: t2 ? "arm-state-t2" : neutral ? "arm-state-locked" : "arm-state", k, role: "pill" });
      if (t2) lockIcon(par, ix + S8, hy + (hh - NV["size.icon.sm"]) / 2, false, TER, k);
      txt(par, P.arm, ix + S8 + lk, cy0(hy, hh, LBL), w - 2 * S8 - lk, { type: LBL, col: t2 ? TER : PRI, k, name: "arm-word" });
    }, 9);
  }
  if (P.icons) { const n = P.icons.length, w = n * D.ctl + (n - 1) * SP1; item(w, (ix) => P.icons.forEach((g, i) => iconBtn(par, ix + i * (D.ctl + SP1), hy, g, D, k, { col: SEC })), 10); } // §4.2.1 #10: own actions as CMP-002 IconButtons (size.control.* square, space.1 apart; the tool's TAPE_ACTIONS)
  if (P.actions) for (const a of P.actions) { const w = tbW(a); item(w, (ix) => tbBtn(par, ix, hy, a, D, { k, name: "own-action" })); }
  // right: ⋮ "Panel options", space.1, × "Close {Kind}"
  let rx = hx + hw - SP3;
  if (P.close !== false) { rx -= D.ctl; iconBtnX(par, rx, hy, D, "close", k); if (P.pos) P.pos.push({ n: 12, x: rx, w: D.ctl }); rx -= SP1; }
  rx -= D.ctl; iconBtnX(par, rx, hy, D, "menu", k, P.hoverMenu); if (P.pos) P.pos.push({ n: 11, x: rx, w: D.ctl }, { n: 1, x: hx, w: BAR_PX });
  const need = x - D.hgap - hx + (hx + hw - rx) + D.hgap;
  if (x - D.hgap > rx - D.hgap) HEADER_OVER[(P.kind || "Chart") + "@" + hw] = { panel: P.kind || "Chart", need: Math.ceil(need), room: hw };
  return { right: rx, leftEnd: x - D.hgap };
}
// the panel: frame, header, and for a chart its status row (env badge), plot with the price gutter, and time strip; returns the content rect
function dockPanel(par, r, P, D) {
  const k = K(), f = FOCUS_PX;
  box(par, r.x, r.y, r.w, r.h, { fill: "color.surface.canvas", stroke: P.focused ? "color.focus.ring" : "color.border.default", bw: P.focused ? "border.focus" : "border.hairline", r: "radius.card", name: P.focused ? "panel-frame-focused" : "panel-frame", k, role: "panel" });
  const hx = r.x + f, hy = r.y + f, hw = r.w - 2 * f;
  panelHeader(par, hx, hy, hw, D, P, k);
  let y = hy + D.ctl;
  const bottom = r.y + r.h - f;
  if (P.kind || P.bare) return { x: hx, y, w: hw, h: bottom - y }; // P.bare: the compact view (§4.2.3), no status row
  // a chart (CMP-221 row in the header): the status row (env badge, E11), the plot, the price gutter and the time strip
  envBadge(par, hx + SP3, y + (D.ctl - D.env) / 2, P.statusEnv || "LIVE", D, { k });
  y += D.ctl;
  const ty = bottom - D.ctl;
  hair(par, hx, ty, hw, 1, "color.border.default", "time-strip-rule", k);
  const pg = PRICE_GUTTER[D.name];
  hair(par, hx + hw - pg, y, 1, ty - y, "color.border.default", "price-gutter-rule", k);
  return { x: hx, y, w: hw, h: ty - y, plotW: hw - pg, timeY: ty };
}

// ---------------------------------------------------------------- the shell: TopBar, NavRail, canvas (tab strip + dock), RightRail strip, StatusBar
function wsShell(par, x, y, W, H, o) {
  o = o || {};
  const D = DZ(o.d || "compact");
  topBar(par, x, y, W, D, o);
  const top = y + TOPBAR_H, bottom = y + H - STATUSBAR_H;
  navRail(par, x, top, bottom - top, D);
  rightStrip(par, x + W - STRIP_W, top, bottom - top);
  const cx = x + NAVRAIL_W, cw = W - NAVRAIL_W - STRIP_W;
  tabStrip(par, cx, top, cw, D, o);
  statusBar(par, x, bottom, W, D, o);
  return { D, canvas: { x: cx, y: top, w: cw, h: bottom - top }, dock: { x: cx, y: top + D.tb, w: cw, h: bottom - top - D.tb } };
}
// CMP-081's gutter (space.1, color.surface.app) and its splitter line in a state (§4.3): rest border.hairline color.border.default; hover,
// focus and at minimum border.thick color.text.tertiary; dragging border.thick color.text.secondary; the grip size.target.min × space.1;
// focus adds CMP-039's ring around the hit band; at minimum a border.thick stop mark across the line
function splitterV(par, gx, y, h, state, k) {
  box(par, gx, y, GUTTER, h, { fill: "color.surface.app", name: "gutter", k });
  const thick = state !== "rest", lt = thick ? NV["border.thick"] : NV["border.hairline"], ltok = state === "rest" ? "color.border.default" : state === "dragging" ? SEC : TER;
  const mid = y + h / 2;
  if (thick) box(par, gx, mid - HITBAND / 2, GUTTER, HITBAND, { fill: TER, name: "splitter-grip", k });
  box(par, gx + (GUTTER - lt) / 2, y, lt, h, { fill: ltok, name: "splitter-line", k });
  if (state === "minimum") box(par, gx - 4, mid - 1, GUTTER + 8, NV["border.thick"], { fill: TER, name: "splitter-stop-mark", k });
  if (state === "focus" || state === "minimum" || state === "dragging-focused") box(par, gx + GUTTER / 2 - HITBAND / 2, y, HITBAND, h, { stroke: "color.focus.ring", bw: "border.focus", name: "splitter-focus-ring", k });
}
// a redline (1 px color.text.secondary with end ticks, as the template's dimH / dimV) whose label reads "<label> <n>" beside it
function redV(par, x, y, h, label, k, o) {
  o = o || {};
  box(par, x, y, 1, h, { fill: SEC, name: "redline", k });
  box(par, x - 3, y, 7, 1, { fill: SEC, name: "redline-tick", k }); box(par, x - 3, y + h - 1, 7, 1, { fill: SEC, name: "redline-tick", k });
  const lw = twm(label, CAP) + 4;
  txt(par, label, x + 8, y + h / 2 - th1(CAP) / 2, Math.max(o.w || 0, lw), { type: CAP, col: o.col || SEC, k, name: "redline-label" });
}
// a table of spec values: cols [{ h, w, al, mono }]; rows arrays of strings ({ strong: true } as the last element bolds the row); a
// header row (type.ui.label color.text.secondary), body rows type.ui.body (numerals type.num.base), hairlines color.border.default
function table(par, x, y, cols, rows, o) {
  o = o || {};
  const k = K(), pad = 8, W = cols.reduce((a, cc) => a + cc.w, 0);
  let cy = y, cx = x;
  const hh = Math.max(24, Math.max.apply(null, cols.map((cc) => estLines(cc.h, cc.w - 2 * pad, TYP(LBL).size, false, 500))) * th1(LBL) + 8);
  for (const cc of cols) { txt(par, cc.h, cx + pad, cy + 4, cc.w - 2 * pad, { type: LBL, col: SEC, k, name: "table-head", ml: true, align: cc.al === "r" ? "right" : "left" }); cx += cc.w; }
  cy += hh; hair(par, x, cy - 1, W, 1, "color.border.strong", "table-rule", k);
  for (const row0 of rows) {
    const strong = row0[row0.length - 1] && row0[row0.length - 1].strong, row = strong ? row0.slice(0, -1) : row0;
    const types = cols.map((cc, i) => (cc.mono && /^[−+]?[\d.,×/ %px]+$/.test(String(row[i])) ? NUM : strong ? STRONG : BODY));
    const rh = Math.max(24, Math.max.apply(null, cols.map((cc, i) => estLines(String(row[i] == null ? "" : row[i]), cc.w - 2 * pad, TYP(types[i]).size, TYP(types[i]).mono, TYP(types[i]).weight) * th1(types[i]))) + 8);
    cx = x;
    cols.forEach((cc, i) => { const s = String(row[i] == null ? "" : row[i]); if (s) txt(par, s, cx + pad, cy + 4, cc.w - 2 * pad, { type: types[i], col: PRI, k, name: "table-cell", ml: true, align: cc.al === "r" ? "right" : "left" }); cx += cc.w; });
    cy += rh; hair(par, x, cy - 1, W, 1, "color.border.default", "table-rule", k);
  }
  return cy;
}
// ---------------------------------------------------------------- E15-D03's merged chrome friends (c4989493, #4478), byte-for-byte ----------
// From E15-D03's board script r1 (pp/319): 43-b02.js lines 7–94 (the kinds' copy, the §3.6 header steps hdrP / toolStep / drawStep /
// probeHeader, splitterH, wsPanel) and 46-b05.js lines 10–245 (the role shells: b5TopBar, b5StatusBar, SCR-124's banner b5Banner, the tab
// row with Save T2 b5TabRow, b5Shell, b5Panel and the region names b5Name). E15-D07's menus open from these headers' ⋮ (§5.7).
Object.assign(C, {
  armShort: ["ARMED", "§4.2.3 step 4 (the countdown dropped; kept in the name and tooltip)"],
  provFull: ["· symbol set by sync group A", "§4.2.1 #6 / §4.2.3 step 0"], provShort: ["via A", "§4.2.1 #6 / §4.2.3 step 2"],
  allSymbols: ["all symbols", "§4.2.1 #4 / §4.2.4 positions row"],
  kindDOM: ["DOM", "§4.2.1 #3"], kindTape: ["Tape", "§4.2.1 #3"], kindPositions: ["Positions", "§4.2.1 #3"],
  nameChart: ["Chart, BTCUSDT 1 minute, Live", "§4.2.4 / §6.2 Names"], nameDOM: ["DOM, BTCUSDT, Live", "§4.2.4 / §6.2 Names"],
  nameTape: ["Tape, BTCUSDT", "§4.2.4 / §6.2 Names"], namePositions: ["Positions, all symbols, Live", "§4.2.4 / §6.2 Names"],
});
const TAPE_ICONS = ["▽", "≥", "‖", "▥"]; // §4.2.4 tape: [Filter] [Threshold…] [Pause] [Columns…] as CMP-002 IconButtons (CMP-019 placeholders by name; the tool's TAPE_ACTIONS = 4)
const B02_OVER = [];
const DENSE_COL = 0.7; // `D02`:278 dense: `column` 0.7 / 0.3 [`row` 0.45 / 0.33 / 0.22 [chart, DOM, tape], positions]
const HDR_STEPS = { chart: ["full", "s1", "s3", "s4", "s5", "s6"], dom: ["full", "s1", "s2", "s3", "s4", "s5", "s6"], tape: ["full", "s1", "s3", "s5", "s6"], positions: ["full", "s1", "s5"] }; // §3.6 (the tool's STEPS)
const hdrKey = (kind, s, d) => "hdr." + kind + "." + s + (d === "comfortable" ? ".comfortable" : "");
function hdrStep(kind, panelW, d, extra) { const inner = panelW - 2 * FOCUS_PX - (extra || 0); for (const s of HDR_STEPS[kind]) if (AN(hdrKey(kind, s, d)) <= inner) return s; // §3.6: measured inside the frame (the panel less focus.frame-px each side)
  warn("header", kind + " at " + panelW + " is below its minimum"); return HDR_STEPS[kind][HDR_STEPS[kind].length - 1]; }
const stepOf = (n) => (n === 0 ? "full" : "s" + n);
const STEPS_DRAWN = []; // the anchored frames: [key, step] (the self-check lists them)
function toolStep(kind, panelW, d, key, extra) { // §6.2 "Steps drawn": the tool's anchored step (BUDGET step.<layout>.<vp>.<density>.<kind>) where it anchors one, else §3.6's rule (the tool's own rule)
  const s = hdrStep(kind, panelW, d, extra);
  if (!key || !Object.prototype.hasOwnProperty.call(AV, key)) return s;
  const t = stepOf(AN(key));
  if (HDR_STEPS[kind].indexOf(t) < 0) warn("step", key + ": the tool's " + t + " is not a " + kind + " step");
  if (t !== s) warn("step", key + ": the tool anchors " + t + ", the widths give " + s + " at " + panelW);
  STEPS_DRAWN.push([key, t]);
  return t;
}
function drawStep(f, r, P, D, who) { // the header at exactly the chosen step; an overrun is reported, never re-stepped
  const key = (P.kind || "Chart") + "@" + (r.w - 2 * FOCUS_PX);
  delete HEADER_OVER[key];
  const q = dockPanel(f, r, P, D);
  if (HEADER_OVER[key]) { warn("header", who + ": drawn needs " + HEADER_OVER[key].need + " in " + HEADER_OVER[key].room); delete HEADER_OVER[key]; }
  return q;
}
const stepN = (s) => (s === "full" ? 0 : parseInt(s.slice(1), 10));
const stepWord = (s) => (s === "full" ? "full row" : s === "s6" ? "step 6 = minimum" : "step " + stepN(s));
function hdrP(kind, s, focused) { // the header row of a kind at a §4.2.3 step (§4.2.4's rows)
  const n = stepN(s), close = n < 5;
  if (kind === "chart") return { symbol: "BTCUSDT", interval: "1m", chartTools: n === 0, sync: SYNC_A(n >= 6 ? "" : n >= 3 ? "3" : undefined), arm: n >= 4 ? c("armShort") : c("armed"), close, focused };
  if (kind === "dom") return { kind: c("kindDOM"), symbol: "BTCUSDT", prov: n >= 6 ? null : n >= 2 ? c("provShort") : c("provFull"), sync: SYNC_A(n >= 6 ? "" : n >= 3 ? "1" : "symbol"), env: "LIVE", arm: n >= 4 ? c("armShort") : c("armed"), close, focused };
  if (kind === "tape") return { kind: c("kindTape"), symbol: "BTCUSDT", sync: SYNC_A(n >= 6 ? "" : n >= 3 ? "1" : "symbol"), icons: n >= 1 ? null : TAPE_ICONS, close, focused };
  return { kind: c("kindPositions"), scope: c("allSymbols"), env: "LIVE", close, focused };
}
function probeHeader(P, hw, D) { // panelHeader's own width arithmetic, no shape made: true when the row's left items end a gap before ⋮
  const ws = [];
  if (P.kind) ws.push(lw600(P.kind));
  const pick = (label) => lw500(label) + SP1 + NV["size.icon.sm"];
  if (P.symbol) ws.push(pick(P.symbol));
  if (P.symText) ws.push(lw500(P.symText));
  if (P.scope) ws.push(lw500(P.scope));
  if (P.interval) ws.push(pick(P.interval));
  if (P.status) ws.push(chipTextW(P.status, CAP));
  if (P.chartTools) { ws.push(pick(c("hdrCandle"))); for (const t of [c("hdrFP"), c("hdrInd"), c("hdrDraw")]) ws.push(lw500(t)); }
  if (P.prov) ws.push(chipTextW(P.prov, CAP));
  if (P.sync) ws.push(syncW(P.sync));
  if (P.reduced) ws.push(2 * SP2 + chipTextW(P.reduced, CAP));
  if (P.env) ws.push(envW(P.env));
  if (P.arm) ws.push(2 * S8 + (P.armForm === "t2" ? NV["size.icon.sm"] + S4 : 0) + lw500(P.arm));
  if (P.icons) ws.push(P.icons.length * D.ctl + (P.icons.length - 1) * SP1);
  if (P.actions) for (const a of P.actions) ws.push(tbW(a));
  const x = SP3 + D.icon + SP1 + D.hgap + ws.reduce((a, b) => a + b + D.hgap, 0);
  const rx = hw - SP3 - (P.close !== false ? D.ctl + SP1 : 0) - D.ctl;
  return x <= rx;
}
const REGION = { chart: "nameChart", dom: "nameDOM", tape: "nameTape", positions: "namePositions" };
function splitterH(par, x, gy, w, k) { // CMP-081 at rest, horizontal: the space.1 gutter on color.surface.app, a border.hairline color.border.default line centred
  box(par, x, gy, w, GUTTER, { fill: "color.surface.app", name: "gutter", k });
  box(par, x, gy + (GUTTER - NV["border.hairline"]) / 2, w, NV["border.hairline"], { fill: "color.border.default", name: "splitter-line", k });
}
// one panel in a cell: the frame and header (dockPanel), its region name in the body (D-5), and optionally its content rect outlined (§3.4)
function wsPanel(f, r, kind, d, D, focused, o) {
  o = o || {};
  // the tool's step (§3.6 width ≤ the panel's width); if the drawn row (SAFE offline widths, comfortable control sizes) still overruns,
  // the next step that fits is drawn and the caption says so (never an overlapping row)
  const s0 = toolStep(kind, r.w, d, o.layout ? "step." + o.layout + "." + o.vp + "." + d + "." + kind : null), s = s0;
  const q = drawStep(f, r, hdrP(kind, s, focused), D, kind + " " + d + " " + r.w + " at " + s);
  const k = K();
  const nm = "role=\"region\" · \"" + c(REGION[kind]) + "\"" + (focused ? " · focused" : "") + (o.extra || "");
  const lx = q.x + SP3, ly = q.y + SP3;
  txt(f, nm, lx, ly, Math.min(twm(nm, CAP) + 4, q.w - 2 * SP3), { type: CAP, col: SEC, k, name: "region-name" });
  if (o.rect) {
    const want = A(o.rect), got = q.w + "×" + q.h;
    if (want !== got) warn("rect", o.rect + ": drawn " + got + ", the tool's " + want);
    box(f, q.x, q.y, q.w, q.h, { stroke: "color.border.strong", dashed: true, name: "content-rect", k });
    const lab = "content rect · " + (focused ? "focused " : "unfocused ") + want + " = " + (focused ? "unfocused " : "focused ") + A(o.rect.replace(focused ? ".focused" : ".unfocused", focused ? ".unfocused" : ".focused")) + " (§3.4)";
    txt(f, lab, lx, q.y + q.h - SP2 - th1(CAP), Math.min(twm(lab, CAP) + 4, q.w - 2 * SP3), { type: CAP, col: PRI, k, name: "content-rect-label" });
  }
  return { s, s0, q, kind, w: r.w };
}
Object.assign(C, {
  b5Swing: ["Swing", "§7.1 manager: Swing (E15-D02 manager-swing, D02:278)"],
  b5Analyst: ["Analyst (not saved)", "§9 ws.tab.viewer.unsaved (D02:278)"],
  b5Scope1: ["sub_001", "E10-D03 §0 specimen: the manager's one LIVE account (cell 7)"],
  b5UserMgr: ["alex · Manager", "E10-D03 §0 specimen user"], b5UserViewer: ["lee · Viewer", "E10-D03 §0 specimen user"],
  b5FreezeMine: ["Freeze my account…", "E10-D03 cell 7 (E39-D01 D-1)"],
  b5ViewAs: ["Read-only while viewing as alex.", "§9 rbac.view_as with §1.6's alex (R-1)"],
  b5PermSave: ["Your role can't save workspaces.", "§9 rbac.permission (R-2, R-3–R-6)"],
  b5PermOrders: ["Your role can't place orders.", "§9 rbac.permission (R-7)"],
  b5Account: ["This account isn't assigned to you.", "§9 rbac.account (R-9)"],
  b5Unstored: ["This workspace isn't saved.", "§9 ws.export.unstored (V-4)"],
  b5UndoNone: ["Nothing to undo.", "§9 layout.undo.none (V-5)"], b5RevertClean: ["No unsaved changes.", "§9 layout.revert.clean (V-2)"],
  b5Unconf: ["unconfirmed", "§9 env.unconfirmed (E10-D03:214)"],
  b5ExitViewAs: ["Exit view-as", "E42-D02 SCR-124's banner action"],
  b5Locked: ["LOCKED", "§4.2.1 #9 (CMP-229)"],
  b5Journal: ["Journal", "§4.2.4 journal row"],
  b5NewWs: ["New workspace…", "§4.4 \"+\" menu"], b5OpenWs: ["Open workspace…", "§4.4 \"+\" menu (CMP-073)"], b5Import: ["Import…", "§4.4 \"+\" menu"],
  b5SaveAsNew: ["Save as new layout…", "§4.5 [⋯]"], b5Undo: ["Undo layout change", "§4.5 [⋯]"], b5Revert: ["Revert to saved…", "§4.5 [⋯]"],
  b5Settings: ["Workspace settings…", "§4.5 [⋯]"], b5Export: ["Export…", "§4.5 [⋯]"], b5Rename: ["Rename", "§8.1 R-6 (context menu)"], b5CloseTab: ["Close tab", "§4.4 close"],
});
const B5_SPELL = { "1m": "1 minute", "15m": "15 minutes", "1h": "1 hour", "4h": "4 hours" }; // §9 panel.region.name: the interval spelled
const B5_ENVW = { LIVE: "Live", DEMO: "Demo" };
function b5Name(kind, env, iv) { // §9 panel.region.name (§4.2.4's names; the environment word per D-4)
  if (kind === "chart") return "Chart, BTCUSDT " + B5_SPELL[iv || "1m"] + ", " + B5_ENVW[env];
  if (kind === "dom") return "DOM, BTCUSDT, " + B5_ENVW[env];
  if (kind === "tape") return "Tape, BTCUSDT";
  if (kind === "positions") return "Positions, all symbols, " + B5_ENVW[env];
  return c("b5Journal");
}

// ---------------------------------------------------------------- the unconfirmed badge (§7.2; E10-D03:214): adds, never removes
// While on (env/unconfirmed only, reset in a finally), every CMP-074 / CMP-075 instance takes the state: the border.thick rule becomes
// dashed in the same color.env.*, and the caption "unconfirmed" (type.ui.caption, color.text.secondary) sits beside the word; the word,
// weight, glyph and hue never change. envW grows by the caption, so the header steps (§3.6) see the real width.
const ENV_U = { on: false };
const envW0 = envW, envBadge0 = envBadge;
envW = function (env) { return envW0(env) + (ENV_U.on ? SP1 + chipTextW(c("b5Unconf"), CAP) : 0); };
envBadge = function (par, x, y, env, D, o) {
  if (!ENV_U.on) return envBadge0(par, x, y, env, D, o);
  o = o || {};
  const k = o.k || K(), h = o.h || D.env, live = env === "LIVE", hue = live ? "color.env.live" : "color.env.demo", w = envW(env);
  box(par, x, y, w, h, { fill: "color.surface.raised", stroke: hue, bw: "border.thick", dashed: true, r: "radius.pill", name: "env-badge-unconfirmed", k, role: "pill" });
  const ww = lw600(env) + (live ? 2 : 0), ty = cy0(y, h, LBL);
  txt(par, env, x + SP2, ty, ww, { type: LBL, col: PRI, weightTok: live ? "font.weight.bold" : undefined, k, name: "env-word" });
  if (live) hair(par, x + SP2, ty + th1(LBL) - 2, ww, NV["border.thick"], hue, "env-live-underline", k);
  const uw = chipTextW(c("b5Unconf"), CAP);
  txt(par, c("b5Unconf"), x + SP2 + ww + SP1, cy0(y, h, CAP), uw, { type: CAP, col: SEC, k, name: "env-unconfirmed-caption" });
  const ds = 8, dx = x + w - SP2 - NV["size.icon.md"] + (NV["size.icon.md"] - ds) / 2, dy = y + (h - ds) / 2;
  box(par, dx, dy, ds, ds, { fill: live ? hue : null, stroke: live ? null : hue, bw: "border.thick", r: "radius.pill", name: live ? "env-dot-filled" : "env-dot-outline", k });
  return w;
};

// ---------------------------------------------------------------- the shell per role (E10-D03 §2.1 and its cells 1, 6, 7, 18)
// o = { envs, scope, ws, user, freeze, t2Cluster (the Viewer: lock + label, 2b), health ("states" = words only), admin, banner,
//       killT2, env, tabs, save ("clean" | "perm" | "viewas"), reason (2a beside Save) }
function b5T2Ctl(par, x, y, label, D, k, name) { // a T2 chrome control (§1.4, E10-D03 cell 18 2b): the lock leads, the label color.text.tertiary
  const w = ctlW(label, false) + 2 * SP2 + NV["size.icon.sm"] + S4;
  box(par, x, y, w, D.ctl, { fill: "color.surface.raised", stroke: "color.border.default", r: "radius.control", name: name || "control-t2", k, sz: D.ctlTok });
  lockIcon(par, x + 2 * SP2, y + (D.ctl - NV["size.icon.sm"]) / 2, false, TER, k);
  txt(par, label, x + 2 * SP2 + NV["size.icon.sm"] + S4, cy0(y, D.ctl, LBL), lw500(label) + 2, { type: LBL, col: TER, k, name: (name || "control-t2") + "-label" });
  return w;
}
function b5TopBar(par, x, y, w, D, o) {
  const k = K(), h1 = 48, cy = y + (h1 - D.ctl) / 2, ins = D.ins;
  box(par, x, y, w, TOPBAR_H, { fill: "color.surface.raised", name: "topbar", k });
  hair(par, x, y + TOPBAR_H - 1, w, 1, "color.border.default", "topbar-rule", k);
  let cx = x + ins + SP2;
  const wm = c("wordmark"), wmw = twm(wm, H_SM) + 4;
  txt(par, wm, cx, cy0(y, h1, H_SM), wmw, { type: H_SM, col: PRI, k, name: "wordmark" });
  cx += wmw + SP2;
  for (const env of o.envs || ["LIVE"]) cx += envBadge(par, cx, y + (h1 - D.env) / 2, env, D, { k }) + SP2;
  for (const label of [o.scope || c("scope"), o.ws || c("wsScalping"), "BTCUSDT", "1m"]) cx += ctl(par, cx, cy, label, D, { k, name: "topbar-control" }) + SP2;
  if (w >= 1900) {
    const sw = 240;
    box(par, cx, cy, sw, D.ctl, { fill: "color.surface.raised", stroke: "color.border.strong", r: "radius.control", name: "search-trigger", k });
    searchGlyph(par, cx + SP2, cy + (D.ctl - 16) / 2, k);
    drawParts(par, [{ t: c("search"), type: LBL, col: SEC }], cx + SP2 + 16 + SP1, cx + sw - 2 * SP2 - kbdW(c("kbd")), cy, D.ctl, D, k, "l");
    kbd(par, cx + sw - SP2 - kbdW(c("kbd")), cy + (D.ctl - 16) / 2, c("kbd"), k);
    cx += sw + SP2;
  } else {
    box(par, cx, cy, D.ctl, D.ctl, { fill: "color.surface.raised", stroke: "color.border.strong", r: "radius.control", name: "search-trigger", k });
    searchGlyph(par, cx + (D.ctl - 16) / 2, cy + (D.ctl - 16) / 2, k);
    cx += D.ctl + SP1;
    kbd(par, cx, cy + (D.ctl - 16) / 2, c("kbd"), k);
    cx += kbdW(c("kbd")) + SP2;
  }
  const sl = [c("flatten"), c("cancelAll"), o.freeze || c("freeze")], t2 = !!o.t2Cluster;
  const sws = sl.map((l) => ctlW(l, false) + 2 * SP2 + (t2 ? NV["size.icon.sm"] + S4 : 0));
  let rx = x + w - ins - sws.reduce((a, b) => a + b, 0) - SP2 * (sl.length - 1);
  const user = o.user || c("user"), uw = ctlW(user, true), ux = rx - SP3 - uw;
  if (ux < cx) warn("topbar", "board 05: the right group overlaps the left group by " + Math.ceil(cx - ux) + " px at " + w);
  ctl(par, ux, cy, user, D, { k, name: "user-menu" });
  sl.forEach((l, i) => {
    const nm = ["flatten-all", "cancel-all", "freeze"][i];
    if (t2) b5T2Ctl(par, rx, cy, l, D, k, nm + "-t2");
    else { const fz = i === 2; ctl(par, rx, cy, l, D, { k, w: sws[i], caret: false, fill: fz ? "color.status.danger.default" : "color.surface.raised", stroke: fz ? null : "color.status.danger.default", col: fz ? "color.text.on-action" : PRI, name: nm }); }
    rx += sws[i] + SP2;
  });
  let hx = x + ins + SP2;
  const ch = D.env, hy = y + h1 + (TOPBAR_H - h1 - ch) / 2;
  for (const [words, val] of HEALTH) hx += healthChip(par, hx, hy, words, o.health === "states" ? null : val, ch, k, "color.status.success.strong") + SP2;
}
function b5StatusBar(par, x, y, w, D, o) {
  const k = K(), ins = D.ins, ch = D.env, chy = y + (STATUSBAR_H - ch) / 2;
  box(par, x, y, w, STATUSBAR_H, { fill: "color.surface.sunken", name: "statusbar", k });
  hair(par, x, y, w, 1, "color.border.default", "statusbar-rule", k);
  let cx = x + ins;
  for (const [words, val, live] of STATUS_CHIPS) cx += healthChip(par, cx, chy, words, val, ch, k, live ? "color.status.success.strong" : null) + SP2;
  const cl = c("clockLine"), clw = chipTextW(cl, CAP);
  txt(par, cl, cx + SP2, cy0(y, STATUSBAR_H, CAP), clw, { type: CAP, col: SEC, k, name: "status-clock" });
  const vw = chipTextW(c("version"), "type.num.xs"), env = o.env || "LIVE", ew = envW(env);
  const Dk = Object.assign({}, D, { ctl: NV["size.control.compact"] }), kl = c("killSwitch");
  const kw = o.killT2 ? ctlW(kl, false) + 2 * SP2 + NV["size.icon.sm"] + S4 : ctlW(kl, false) + 2 * SP2;
  let rx = x + w - ins - vw;
  txt(par, c("version"), rx, cy0(y, STATUSBAR_H, "type.num.xs"), vw, { type: "type.num.xs", col: TER, k, name: "version" });
  rx -= SP3 + ew; envBadge(par, rx, y + (STATUSBAR_H - D.env) / 2, env, D, { k });
  rx -= SP3 + kw;
  if (o.killT2) b5T2Ctl(par, rx, y + (STATUSBAR_H - Dk.ctl) / 2, kl, Dk, k, "kill-switch-t2");
  else ctl(par, rx, y + (STATUSBAR_H - Dk.ctl) / 2, kl, Dk, { k, w: kw, caret: false, fill: null, stroke: "color.border.strong", name: "kill-switch" });
  if (rx < cx + SP2 + clw + SP3) warn("statusbar", "board 05: the right group overlaps the clock line at " + w);
}
// SCR-124's view-as banner (E42-D02; a stand-in in E10-D03's banner slot, v.banner.compact tall, first in the DOM): the rbac.view_as
// line is the one notice every gated control points at (§1.4); its Exit view-as action at the right
function b5Banner(par, x, y, w, D) {
  const k = K(), h = AN("v.banner.compact");
  box(par, x, y, w, h, { fill: "color.status.info.subtle", name: "viewas-banner", k, sz: "v.banner.compact" });
  txt(par, c("b5ViewAs"), x + D.ins + SP2, cy0(y, h, LBL), twm(c("b5ViewAs"), LBL) + 4, { type: LBL, col: PRI, weightTok: "font.weight.semibold", k, name: "viewas-banner-line" });
  const bw = tbW(c("b5ExitViewAs"));
  tbBtn(par, x + w - D.ins - SP2 - bw, y + (h - D.ctl) / 2, c("b5ExitViewAs"), D, { k, name: "viewas-exit" });
  return h;
}
// the tab strip with its right cluster (§4.4, §4.5, §3.5): Save clean (availability, V-1), T2 permission with its 2a reason beside it
// (R-2: the lock + space.2 + the reason, the tool's tab.reason.viewer), or T2 view-as in the pointer form (R-1: no reason, the banner)
function b5TabRow(par, x, y, w, D, tabs, o) {
  const k = K(), h = D.tb, ty = y + (h - D.ctl) / 2, pos = { tabs: [] };
  box(par, x, y, w, h, { fill: "color.surface.raised", name: "tab-strip", k });
  hair(par, x, y + h - 1, w, 1, "color.border.default", "tab-strip-rule", k);
  let tx = x + SP2;
  for (const t of tabs) {
    const lw = Math.max(lw600(t.t), Math.ceil(lineW(String(t.t), TYP(LBL).size, false, 600, true)));
    const tw0 = SP3 + lw + (t.dirty ? SP1 + lw600("*") : 0) + (t.active || t.focus ? SP1 + NV["size.icon.sm"] : 0) + SP3;
    let cx = tx + SP3;
    txt(par, String(t.t).replace(/ /g, NBSP), cx, cy0(ty, D.ctl, LBL), lw + 2, { type: LBL, col: t.active ? PRI : SEC, weightTok: t.active ? "font.weight.semibold" : undefined, k, name: t.active ? "tab-active" : "tab" });
    cx += lw;
    if (t.dirty) { cx += SP1; txt(par, "*", cx, cy0(ty, D.ctl, LBL), lw600("*") + 2, { type: LBL, col: PRI, k, name: "tab-dirty" }); cx += lw600("*"); }
    if (t.active || t.focus) { cx += SP1; gly(par, "✕", cx, cy0(ty, D.ctl, LBL) + (th1(LBL) - NV["size.icon.sm"] * 1.2) / 2, { col: SEC, k, name: "tab-close" }); }
    if (t.active) hair(par, tx + SP3, y + h - 1 - NV["border.thick"], tw0 - 2 * SP3, NV["border.thick"], PRI, "tab-underline", k);
    if (t.focus) box(par, tx, ty, tw0, D.ctl, { stroke: "color.focus.ring", bw: "border.focus", r: "radius.control", name: "tab-focus-ring", k });
    pos.tabs.push({ t, x: tx, w: tw0 });
    tx += tw0;
  }
  if (o.noCluster) return { h, pos }; // a crop of the strip: the tabs only (R-6's inset)
  box(par, tx + SP1, ty, D.ctl, D.ctl, { r: "radius.control", name: "tab-new", k });
  gly(par, "+", tx + SP1 + (D.ctl - NV["size.icon.md"]) / 2, ty + (D.ctl - NV["size.icon.md"] * 1.2) / 2, { big: true, col: SEC, k, name: "tab-new-glyph" });
  pos.plus = { x: tx + SP1, w: D.ctl }; tx += SP1 + D.ctl;
  const sv = o.save || "clean", t2 = sv === "perm" || sv === "viewas", saveL = c("tbSave");
  const items = [[c("tbLayout"), true], [c("tbSync"), true], [c("tbAdd")]], ws = items.map(([l, caret]) => tbW(l, caret));
  const saveW = tbW(saveL) + (t2 ? NV["size.icon.sm"] + S4 : 0), rw = o.reason ? chipTextW(o.reason, CAP) : 0;
  let rx = x + w - SP3 - D.ctl - ws.reduce((a, b) => a + b, 0) - saveW - SP2 * 4 - (o.reason ? rw + SP2 : 0);
  pos.cluster = { x: rx, w: x + w - rx };
  if (rx < tx + SP3) warn("tab strip", "board 05: the toolbar overlaps the tabs at " + w);
  items.forEach(([l, caret], i) => { tbBtn(par, rx, ty, l, D, { k, caret }); rx += ws[i] + SP2; });
  pos.save = { x: rx, w: saveW };
  if (t2) {
    box(par, rx, ty, saveW, D.ctl, { fill: "color.surface.raised", stroke: "color.border.default", r: "radius.control", name: "toolbar-save-t2", k, sz: D.ctlTok });
    lockIcon(par, rx + NV["space.button.paddingX"], ty + (D.ctl - NV["size.icon.sm"]) / 2, false, TER, k);
    txt(par, saveL, rx + NV["space.button.paddingX"] + NV["size.icon.sm"] + S4, cy0(ty, D.ctl, LBL), lw500(saveL) + 2, { type: LBL, col: TER, k, name: "toolbar-save-t2-label" });
  } else tbBtn(par, rx, ty, saveL, D, { k, col: TER, name: "toolbar-save-clean" }); // clean: availability "No unsaved changes" (V-1, no lock)
  rx += saveW + SP2;
  if (o.reason) { txt(par, o.reason, rx, cy0(ty, D.ctl, CAP), rw, { type: CAP, col: SEC, k, name: "toolbar-save-reason" }); pos.reason = { x: rx, w: rw }; rx += rw + SP2; }
  box(par, rx, ty, D.ctl, D.ctl, { fill: "color.surface.raised", stroke: "color.border.default", r: "radius.control", name: "toolbar-more", k });
  gly(par, "⋯", rx + (D.ctl - NV["size.icon.md"]) / 2, ty + (D.ctl - NV["size.icon.md"] * 1.2) / 2, { big: true, col: SEC, k, name: "toolbar-more-glyph" });
  pos.more = { x: rx, w: D.ctl };
  return { h, pos };
}
function b5Shell(f, x, y, W, H, o) {
  const D = DZ("compact");
  b5TopBar(f, x, y, W, D, o);
  let top = y + TOPBAR_H;
  if (o.banner) top += b5Banner(f, x, top, W, D);
  const bottom = y + H - STATUSBAR_H;
  navRail(f, x, top, bottom - top, D, { admin: o.admin });
  rightStrip(f, x + W - STRIP_W, top, bottom - top);
  const cx = x + NAVRAIL_W, cw = W - NAVRAIL_W - STRIP_W;
  const ts = b5TabRow(f, cx, top, cw, D, o.tabs || TABS_OWNER(), o);
  b5StatusBar(f, x, bottom, W, D, o);
  return { D, ts, dock: { x: cx, y: top + D.tb, w: cw, h: bottom - top - D.tb } };
}
// the header row's left end (probeHeader's arithmetic, relative to the header's x): where a 2a reason beside the arm toggle starts
function b5LeftEnd(P, D) {
  const ws = [];
  if (P.kind) ws.push(lw600(P.kind));
  const pick = (label) => lw500(label) + SP1 + NV["size.icon.sm"];
  if (P.symbol) ws.push(pick(P.symbol));
  if (P.interval) ws.push(pick(P.interval));
  if (P.prov) ws.push(chipTextW(P.prov, CAP));
  if (P.sync) ws.push(syncW(P.sync));
  if (P.env) ws.push(envW(P.env));
  if (P.arm) ws.push(2 * S8 + (P.armForm === "t2" ? NV["size.icon.sm"] + S4 : 0) + lw500(P.arm));
  return SP3 + D.icon + SP1 + D.hgap + ws.reduce((a, b) => a + b + D.hgap, 0) - D.hgap;
}
// one panel: the §3.6 step that fits inside the frame (probed as board 02 does), the env per D-4, the region name in its body;
// o = { iv, arm, armForm, notice (CMP-028 info row under the header, R-7), reason (2a beside the arm toggle, R-9) }
function b5Panel(f, r, kind, D, focused, env, o) {
  o = o || {};
  const mk = (st) => {
    const P = kind === "journal" ? { kind: c("b5Journal") } : hdrP(kind, st, focused);
    P.focused = focused;
    if (P.env) P.env = env;
    if (kind === "chart") { P.statusEnv = env; if (o.iv) P.interval = o.iv; }
    if (o.arm !== undefined) { P.arm = o.arm; P.armForm = o.armForm; }
    return P;
  };
  let q = null, s = "full", P = null;
  if (kind === "journal") { P = mk("full"); q = dockPanel(f, r, P, D); }
  else {
    const extra = ENV_U.on && hdrP(kind, "full", false).env ? envW(env) - envW0(env) : 0; // the unconfirmed caption widens the header's env badge (§7.2): §3.6's rule on the widened row
    s = toolStep(kind, r.w, "compact", null, extra); P = mk(s);
    q = drawStep(f, r, P, D, "board 05: " + kind + " " + r.w + " at " + s);
  }
  const k = K();
  if (o.reason) { // R-9 2a: the reason beside the toggle, color.text.secondary, inside the header row
    const hx = r.x + FOCUS_PX, rx = hx + b5LeftEnd(P, D) + D.hgap, rw = chipTextW(o.reason, CAP), lim = hx + r.w - 2 * FOCUS_PX - SP3 - 2 * D.ctl - SP1 - D.hgap;
    if (rx + rw > lim) warn("header", "board 05: the R-9 reason overruns the header by " + Math.ceil(rx + rw - lim) + " px");
    txt(f, o.reason, rx, cy0(r.y + FOCUS_PX, D.ctl, CAP), rw, { type: CAP, col: SEC, k, name: "arm-reason-2a" });
  }
  if (o.notice) { // CMP-028 tone="info", size.control.*, under the header; every gated control's aria-describedby points at it
    box(f, q.x, q.y, q.w, D.ctl, { fill: "color.status.info.subtle", name: "panel-notice", k, sz: D.ctlTok });
    txt(f, o.notice, q.x + SP3, cy0(q.y, D.ctl, CAP), twm(o.notice, CAP) + 4, { type: CAP, col: PRI, k, name: "panel-notice-text" });
    q = Object.assign({}, q, { y: q.y + D.ctl, h: q.h - D.ctl });
  }
  const nm = "role=\"region\" · \"" + b5Name(kind, env, o.iv) + "\"" + (focused ? " · focused" : "") + (ENV_U.on && (kind === "chart" || kind === "dom" || kind === "positions") ? " · description gains \"environment unconfirmed\"" : "");
  const room = (q.plotW || q.w) - 2 * SP3, w = twm(nm, CAP) + 4;
  txt(f, nm, q.x + SP3, q.y + SP3, Math.min(w, room), { type: CAP, col: SEC, k, name: "region-name", ml: w > room });
  return { q, s, kind, w: r.w };
}
// =============================================================================================================
// E12-D05 shared builders: the copy deck (§12 W-rows, D03's C-rows quoted by the spec), the General tab (§2, §3, §4, §2.2, §2.3), the
// dialog chrome E11-D03 designed once (CMP-043 `lg`, the CMP-042 tabs, the CMP-003 scope control and its helper lines, the footer;
// E11-D03 §6.1, §6.3) with this ticket's additions (§7.3 partial apply, §9 resets, dirty and saving states), the frames' workspaces
// (E15-D03's merged chrome, 41-chrome / 42-d03) and the register captions (§15.1). Every number is A(…) (the spec's audit tool) or a
// token (NV); every word is a W-row, a C-row (D03:184–227, verbatim), E11-D03's chrome copy (E11-D03:272–281) or E15-D02's prompt.
// =============================================================================================================
const PROP = "PROPOSED";
const OWNER = "PROPOSED, owner approval pending (#2701)";
// ---- §12 copy deck (W-n) and D03's C-n, the strings a board draws (verbatim; {placeholders} filled from §0's fixture data) ----
const WD = {
  "W-1": ["Chart type", "Bar mode", "Crosshair", "Session"],
  "W-2": ["Candles", "Bars (OHLC)", "Hollow candles", "Line", "Area", "Baseline", "Heikin-Ashi", "Equi-volume", "Delta-volume"],
  "W-4": ["Base price", "First visible close", "Price", "rounded to the " + A("FIX:btc.tick") + " tick"],
  "W-5": ["Footprint needs a real-price bar type. Heikin-Ashi recomputes each bar's open and close, so footprint cells would not line up with traded prices.", "Keep Candles", "Use Heikin-Ashi, turn footprint off"],
  "W-6": ["Heikin-Ashi is drawn on time bars only.", "Switch to time bars", "Keep Volume"],
  "W-7": ["Rebuilds the chart on Save"],
  "W-8": ["Precision and the bar-close countdown are on the Scales tab.", "Precision: Auto (tick " + A("FIX:btc.tick") + ")", "Go to Scales"],
  "W-9": ["Trades 24/7. Day boundary: UTC 00:00.", "Maintenance windows: Scales tab"],
  "W-10": ["The drawing magnet is set in the drawing rail."],
  "W-13": ["Saved as your default for new chart panels.", "Undo", "Dismiss"],
  "W-14": ["Saves as your default: bar mode and its size."],
  "W-15": ["Reset General to defaults?", "Rebuilds the chart on Save.", "Reset", "Keep settings"],
  "W-16": ["Reset all chart settings to defaults?", "Rebuilds the chart on Save.", "Reset", "Keep settings"],
  "W-17": ["Discard your changes to these settings?", "Discard changes", "Keep editing"],
  "W-18": ["Couldn't save these settings. Your changes are still here.", "Retry"],
  "W-19": ["Sample bars: not this chart"],
  "W-22": ["General, changed"],
  "W-23": ["Your role can't save workspaces. Change the bar mode for this view from the interval menu."],
  "W-25": ["General reset to defaults for this panel", "All chart settings reset to defaults for this panel"],
  "W-26": ["Read-only while viewing as alex."], // {user}: E15-D03's view-as chrome names alex (42-d03 b5ViewAs); D05 names no viewed user (ambiguity A-6)
};
// §3.1's Description column (W-3), in D02's order (the spec's rows)
const TYPES = [
  ["candle", "Candles", "Body from open to close, wick from high to low"],
  ["bar", "Bars (OHLC)", "A high-low stem with the open tick left and the close tick right"],
  ["hollow", "Hollow candles", "Hollow when the close is at or above the open; coloured by the previous close"],
  ["line", "Line", "Closes joined by a line"],
  ["area", "Area", "A line of closes with the area under it filled"],
  ["baseline", "Baseline", "Line split above and below a base price"],
  ["heikin-ashi", "Heikin-Ashi", "Smoothed candles computed on your device; prices on the axis stay real"],
  ["equi-volume", "Equi-volume", "Candle width follows each bar's volume"],
  ["delta-volume", "Delta-volume", "Candle width follows each bar's delta, with a signed delta pane"],
];
WD["W-3"] = TYPES.map((t) => t[2]);
if (TYPES.length !== AN("COUNT:types")) warn("types", TYPES.length + " types, the tool counts " + A("COUNT:types"));
if (TYPES.map((t) => t[1]).join("|") !== WD["W-2"].join("|")) warn("types", "§3.1's names differ from W-2");
// D03's C-rows the spec quotes (D03:184–227, verbatim; {BTC} and {1} filled for BTCUSDT: base asset BTC, floor A("FIX:btc.floor"))
const CD = {
  "C-1": "One bar per clock interval.", "C-2": "Bars close on trade count, so busy periods make more bars.",
  "C-3": "Bars close on traded volume; one big trade can close several.", "C-4": "Bars close on a fixed high-low range; quiet markets add few.",
  "C-5": "Bars close once net buying or selling reaches the size.", "C-6": "Equal bricks; reversals need two bricks, hiding small swings.",
  "C-7": "Enter " + A("LIM:tick.min") + " to " + A("LIM:tick.max") + " trades.",
  "C-8": "Whole BTC only in this release; at least " + A("FIX:btc.floor") + " BTC per bar.",
  "C-9": "Whole BTC only in this release; at least " + A("FIX:btc.floor") + " BTC of delta per bar.",
  "C-10": "Enter at most " + A("LIM:qty.max") + " BTC.",
  "C-11": "Enter " + A("LIM:range.min") + " to " + A("LIM:range.max") + " ticks.",
  "C-12": "ATR bricks are not available yet. Enter a brick size in ticks.",
  "C-15": "Estimating…", "C-16": "Builds the last 3 days: about 3.1 M prints, about 30 s.",
  "C-17": "Ready for the loaded window; no build needed.", "C-18": "Size not known yet",
  "C-19": "Too many bars for this setting; choose a larger size or a shorter window", "C-20": "May pass the 250,000-bar build limit",
  "C-24": "Needs recorded prints: none yet", "C-25": "Lot size not known yet", "C-26": "Not available yet", "C-30": "Needs a build",
};
{ // the spec quotes C-7, C-10 and C-11 with their numbers (§4.1); the build re-derives them from the tool's LIM values and checks
  const VERB = { "C-7": "Enter 100 to 1,000,000 trades.", "C-10": "Enter at most 1,000,000,000,000 BTC.", "C-11": "Enter 2 to 100,000 ticks." };
  for (const k of Object.keys(VERB)) if (CD[k] !== VERB[k]) warn("parity", k + " from the tool's LIM reads \"" + CD[k] + "\", §4.1 quotes \"" + VERB[k] + "\"");
}
// §4.1 parity: mode, label (the tool's parity cell, its first quoted string), unit, D03 description, default, message ids
const PLAB = (m) => { const v = /^"([^"]+)"/.exec(String(A("parity." + m))); return v ? v[1] : "?"; };
const MODES = [
  { id: "time", name: "Time", label: "Interval", unit: null, desc: "C-1", def: "1m" },
  { id: "tick", name: "Tick", label: PLAB("tick"), unit: "trades", desc: "C-2", def: A("D03:default.tick"), msg: "C-7" },
  { id: "volume", name: "Volume", label: PLAB("volume"), unit: "BTC", desc: "C-3", def: A("D03:default.volume"), msg: "C-8" },
  { id: "range", name: "Range", label: PLAB("range"), unit: "ticks", desc: "C-4", def: A("D03:default.range"), msg: "C-11" },
  { id: "delta", name: "Delta", label: PLAB("delta"), unit: "BTC", desc: "C-5", def: A("D03:default.delta"), msg: "C-9" },
  { id: "renko", name: "Renko", label: PLAB("renko"), unit: "ticks", desc: "C-6", def: A("D03:default.renko"), msg: "C-11" },
];
if (MODES.map((m) => m.id).join(",") !== String(A("d03_order")).replace(/\s/g, "")) warn("parity", "the modes' order differs from D03's (" + A("d03_order") + ")");
if (MODES.length !== AN("COUNT:modes")) warn("parity", MODES.length + " modes, the tool counts " + A("COUNT:modes"));
WD["C-40"] = [PLAB("volume"), "BTC"]; // C-40: the editor label and unit drawn for Volume (BTCUSDT's base asset)
const MODE = (id) => MODES.find((m) => m.id === id);
// E11-D03's chrome copy, verbatim (§6.1 tabs, §6.3 helper lines, §6.4 preview states); E15-D02:507's prompt (W-17)
const TABS = ["General", "Scales", "Appearance", "Trading", "Performance"];
const HELP = {
  this: "This chart panel only. Other panels and future panels are unchanged.",
  all: "Every chart panel in this workspace, now. Defaults for future panels are unchanged.",
  default: "This panel now, and every chart panel you create later. Other existing panels are unchanged.",
};
const INTERIM = "Defaults for the other fields are stored per panel until the settings contract carries them"; // E11-D03:858 verbatim (§7.2)
const SEGS = [["this", "This panel"], ["all", "All panels"], ["default", "As new default"]];
const PV_EMPTY = "Preview unavailable — no bars loaded", PV_ERROR = "Preview unavailable — chart error; settings still apply"; // E11-D03:279, :280
const REASON_SAVE = "Your role can't save workspaces.", REASON_SET = "Your role can't change settings."; // E09-D09:114, :115 (§10.1)
const DLG_TITLE = "Chart settings"; // E11-D03 §6.1
// §7.3's example panels (illustrative: §0), the 4 chart panels of the workspace; Volume applies each panel's own per-symbol value
// R1 F-3: the register's State "All panels, 3 of 4" and §7.3's examples (3 of 4; 1 unchanged, ETHFIUSDT with C-24), drawn as written; the
// second reason C-25 (the Copy cell) is shown on the frame as a margin note giving the line such a panel reads, not as a fifth panel
const PANELS = [
  { sym: "BTCUSDT", iv: "1m", to: "Volume 50 BTC" },
  { sym: "BTCUSDT", iv: "15m", to: "Volume 50 BTC" },
  { sym: "BTCUSDT", iv: "1h", to: "Volume 50 BTC" },
  { sym: "ETHFIUSDT", iv: "1m", reason: "C-24" },
];
const C25_LINE = "… · stays Time 1m · " + "Lot size not known yet"; // §7.3's unchanged-panel line form with C-25's reason (the panel unnamed)
const nChanged = PANELS.filter((p) => !p.reason).length;
WD["W-11"] = ["Applies to " + nChanged + " of " + PANELS.length + " chart panels"].concat(PANELS.map((p) => p.sym + " · " + (p.reason ? "stays Time " + p.iv + " · " + CD[p.reason] : "Time " + p.iv + " → " + p.to)));
WD["W-12"] = ["Bar mode saved for " + nChanged + " of " + PANELS.length + " chart panels; " + (PANELS.length - nChanged) + " unchanged"];
WD["W-24"] = PANELS.filter((p) => p.reason).map((p) => "Bar mode unchanged · " + CD[p.reason]).concat(["Dismiss"]);
WD["W-20"] = ["Changes:"]; // each preview frame fills the template (its caption is checked per frame)
const WALT = { // a Copy id whose string depends on the frame (W-25: General or All, as pressed)
  "W-25": (row) => (/reset\/all/.test(row.frame) ? WD["W-25"][1] : WD["W-25"][0]),
};
const wordsOf = (id) => WD[id] || (CD[id] ? [CD[id]] : null);

// ---- geometry (§0: each frame a 1280 × 800 window, comfortable density; CMP-043 `lg` at most 960 px wide, the card at most 80 % of the
// viewport with its body scrolling between a fixed header and footer, `15`:465–466) ----
const VW = AN("viewport.w"), VH = AN("viewport.h"), DLG_W = 960, DLG_H = Math.floor(0.8 * VH), FGAPX = 80;
const COLW = 588, PVW = 300, COLGAP = 24; // the two columns (§2.1, E11-D03 §6.1): the sections, then the preview tile
const RAD = NV["size.icon.md"]; // a CMP-006 radio's circle (size.icon.md)
NV["opacity.muted"] = 0.7; // packages/ui/tokens primitives opacity.muted (E11-D03:279's silhouette; read at cec8310a6d), by value as the scrim
const SCRIM_OP = NV["opacity.scrim"];
function scrim(f, x, y, w, h) { box(f, x, y, w, h, { fill: "palette.black", op: SCRIM_OP, opTok: "opacity.scrim", name: "modal-scrim", k: K() }); }

// ---- the controls (CMP-006 radio, CMP-003 segment, CMP-008 / CMP-009 / CMP-100 fields, CMP-001 buttons, CMP-028 callout) ----
const T2S = []; // the T2 controls of the board being built: { frame, x, y, w, h, lockX, labelX, reason }
let CUR_F = null; // the frame being drawn (its name), for T2S and the stamps
function radio(par, x, y, sel, k, o) { // the CMP-006 circle: selected = color.action.primary.default with the color.text.on-action dot; else a color.text.tertiary ring
  o = o || {};
  if (sel) { box(par, x, y, RAD, RAD, { fill: "color.action.primary.default", r: "radius.badge", name: "radio-selected", k }); box(par, x + 5, y + 5, RAD - 10, RAD - 10, { fill: "color.text.on-action", r: "radius.badge", name: "radio-dot", k }); }
  else box(par, x, y, RAD, RAD, { stroke: TER, r: "radius.badge", name: o.t2 ? "radio-t2" : "radio", k });
}
// one horizontal option (circle, label; a T2 option: the lock leads the label in color.text.tertiary and its reason follows as text)
function hOptW(o) { return RAD + 8 + (o.t2 ? NV["size.icon.sm"] + 4 : 0) + twm(o.t, BODY) + (o.tag ? 8 + chipW(tagChip(o.tag), DZ("compact")) : 0) + (o.reason ? 8 + twm(o.reason, CAP) : 0); }
const tagChip = (label) => ({ fill: "color.surface.raised", stroke: "color.border.default", parts: [{ t: label, col: SEC }], name: "tag" }); // R1 F-9: the C-30 label color.text.secondary (the register's Tokens cell)
function hOpt(par, x, y, h, o, k) { // returns its width
  const cy = y + (h - RAD) / 2;
  radio(par, x, cy, o.sel, k, { t2: o.t2 });
  let cx = x + RAD + 8;
  if (o.t2) { lockIcon(par, cx, y + (h - NV["size.icon.sm"]) / 2, false, TER, k); cx += NV["size.icon.sm"] + 4; }
  const lw = twm(o.t, BODY);
  txt(par, o.t, cx, y + (h - th1(BODY)) / 2, lw, { type: BODY, col: o.t2 ? TER : PRI, k, name: o.t2 ? "option-t2-label" : "option-label" });
  if (o.t2) T2S.push({ frame: CUR_F, x, y, w: hOptW(o), h, lockX: cx - NV["size.icon.sm"] - 4, labelX: cx, reason: o.reason, what: o.t });
  cx += lw;
  if (o.tag) { cx += 8; const D = DZ("compact"); cx += chip(par, cx, y + (h - D.pill) / 2, tagChip(o.tag), D, k); }
  if (o.reason) { cx += 8; const rw = twm(o.reason, CAP); txt(par, o.reason, cx, y + (h - th1(CAP)) / 2, rw, { type: CAP, col: SEC, k, name: "t2-reason" }); cx += rw; }
  if (o.focus) ring(par, x - 4, y + 2, cx - x + 8, h - 4, k);
  return cx - x;
}
// a horizontal radio group that wraps at w; rows of the comfortable height; returns the rows' total height
function hGroupH(opts, w) { const D = DZ("comfortable"); let x = 0, rows = 1; for (const o of opts) { const ow = hOptW(o); if (x > 0 && (o.br || x + ow > w)) { rows++; x = 0; } x += ow + 20; } return rows * D.row; }
function hGroup(par, x0, y0, w, opts, k) {
  const D = DZ("comfortable");
  let x = x0, y = y0;
  for (const o of opts) { const ow = hOptW(o); if (x > x0 && (o.br || x + ow > x0 + w)) { x = x0; y += D.row; } hOpt(par, x, y, D.row, o, k); x += ow + 20; }
  return y + D.row - y0;
}
function segW(label, o) { return Math.ceil(2 * NV["space.button.paddingX"] + twm(label, LBL) + (o.pressed ? NV["size.icon.sm"] + 4 : 0) + (o.t2 ? NV["size.icon.sm"] + 4 : 0)); }
function segment(par, x, y, label, o, k) { // CMP-003: pressed = color.surface.selected + 1 px color.border.strong + ✓; unpressed color.text.secondary on color.surface.raised; T2 the lock + color.text.tertiary
  const D = DZ("comfortable"), w = segW(label, o);
  box(par, x, y, w, D.ctl, { fill: o.pressed ? "color.surface.selected" : "color.surface.raised", stroke: o.pressed ? "color.border.strong" : "color.border.default", r: "radius.control", name: o.t2 ? "write-segment-t2" : o.pressed ? "segment-pressed" : "segment", k });
  const parts = [];
  if (o.t2) parts.push({ lock: TER });
  if (o.pressed) parts.push({ g: "✓", col: PRI });
  parts.push({ t: label, type: LBL, col: o.t2 ? TER : o.pressed ? PRI : SEC, safe: true });
  drawParts(par, parts, x, x + w, y, D.ctl, Object.assign({}, D, { i: 0 }), k, "c");
  if (o.t2) T2S.push({ frame: CUR_F, x, y, w, h: D.ctl, lockX: x + (w - partsW(parts, Object.assign({}, D, { i: 0 }))) / 2, labelX: x + w / 2, reason: o.reason, what: label });
  if (o.focus) ring(par, x - 3, y - 3, w + 6, D.ctl + 6, k);
  return w;
}
function fieldW(value, unit) { return Math.max(200, Math.ceil(16 + Array.from(String(value)).length * TYP(NUM).size * EM_MONO + 6 + (unit ? twm(unit, LBL) + 6 : 0) + 44)); }
function t2Field(par, x, y, w, value, unit, reason, k) { // a T2 field (§10.1: the bar-mode group T2 for a Viewer or while viewing as): the lock leads the value in color.text.tertiary
  const D = DZ("comfortable");
  box(par, x, y, w, D.ctl, { fill: "color.surface.raised", stroke: "color.border.default", r: "radius.control", name: "write-field-t2", k });
  lockIcon(par, x + 8, y + (D.ctl - NV["size.icon.sm"]) / 2, false, TER, k);
  txt(par, value + (unit ? " " + unit : ""), x + 8 + NV["size.icon.sm"] + 6, y + (D.ctl - th1(NUM)) / 2, w - 30, { type: NUM, col: TER, k, name: "field-value-t2" });
  T2S.push({ frame: CUR_F, x, y, w, h: D.ctl, lockX: x + 8, labelX: x + 8 + NV["size.icon.sm"] + 6, reason, what: "the " + (unit ? unit : "interval") + " field" });
}
function stepperField(par, x, y, w, value, unit, o, k) { // CMP-008: the value in JetBrains Mono on color.surface.app, the unit suffix color.text.tertiary, the steppers; the boundary color.text.tertiary, invalid 2 px color.status.danger.strong
  o = o || {};
  const D = DZ("comfortable"), bad = !!o.invalid;
  box(par, x, y, w, D.ctl, { fill: "color.surface.app", stroke: bad ? DANGER_S : o.focus ? "color.focus.ring" : TER, bw: bad || o.focus ? "border.thick" : "border.hairline", r: "radius.control", name: "field", k });
  const sw = 20, sx = x + w - 2 * sw - 4;
  txt(par, value, x + 8, y + (D.ctl - th1(NUM)) / 2, Math.max(20, sx - x - 16 - (unit ? twm(unit, LBL) + 6 : 0)), { type: NUM, col: PRI, k, name: "field-value" });
  if (unit) txt(par, unit, sx - 6 - twm(unit, LBL), y + (D.ctl - th1(LBL)) / 2, twm(unit, LBL), { type: LBL, col: TER, k, name: "field-unit" });
  for (const [i, g] of [[0, "−"], [1, "+"]]) { box(par, sx + i * sw, y + 4, sw - 2, D.ctl - 8, { fill: "color.surface.raised", r: "radius.xs", name: "stepper", k }); drawParts(par, [{ g, col: SEC }], sx + i * sw, sx + i * sw + sw - 2, y + 4, D.ctl - 8, D, k, "c"); }
  if (o.caret) box(par, Math.round(x + 8 + twm(value, NUM) + 1), Math.round(y + (D.ctl - th1(NUM)) / 2), 1, Math.ceil(th1(NUM)), { fill: PRI, name: "field-caret", k }); // r2: the text caret after the typed value (D03 board 05, "atr:14|")
  if (o.focus && bad) ring(par, x - 4, y - 4, w + 8, D.ctl + 8, k); // focus outside the invalid boundary, on the surface around it (§13)
}
function selectField(par, x, y, w, value, k) { // CMP-009 Select: the interval
  const D = DZ("comfortable");
  box(par, x, y, w, D.ctl, { fill: "color.surface.app", stroke: TER, r: "radius.control", name: "select", k });
  drawParts(par, [{ t: value, type: NUM, col: PRI }], x + 8, x + w - 12 - NV["size.icon.md"], y, D.ctl, D, k, "l");
  gly(par, "▾", x + w - 8 - NV["size.icon.md"], y + (D.ctl - NV["size.icon.md"] * 1.2) / 2, { col: SEC, big: true, k, name: "select-caret" });
}
function btn(par, x, y, b, k) { // CMP-001 at the comfortable height; T2 records its lock and reason (checked by d5Checks)
  const D = DZ("comfortable");
  if (b.kind === "saving") { // CMP-001's loading state on the primary: the ⟳ leads the unchanged label, aria-busy, still focusable (§9.3)
    const w = btnW({ t: b.t, kind: "busy" }, D);
    box(par, x, y, w, D.ctl, { fill: "color.action.primary.default", r: "radius.control", name: "write-save-busy", k, sz: D.ctlTok });
    drawParts(par, [{ g: "⟳", col: "color.text.on-action" }, { t: b.t, type: LBL, col: "color.text.on-action", al: "center", safe: true }], x, x + w, y, D.ctl, D, k, "c");
    return w;
  }
  const w = button(par, x, y, Object.assign({}, b, { name: b.name || (b.kind === "t2" ? "button-t2" : "button") }), D, k);
  if (b.kind === "t2") T2S.push({ frame: CUR_F, x, y, w, h: D.ctl, lockX: x + NV["space.button.paddingX"], labelX: x + NV["space.button.paddingX"] + D.icon + D.gap, reason: b.reason, what: b.t });
  if (b.focus) ring(par, x - 3, y - 3, w + 6, D.ctl + 6, k);
  return w;
}
const bW = (b) => (b.kind === "saving" ? btnW({ t: b.t, kind: "busy" }, DZ("comfortable")) : btnW(b, DZ("comfortable")));
function btnRowR(par, xr, y, list, k) { let x = xr - list.reduce((a, b) => a + bW(b), 0) - 8 * (list.length - 1); const out = []; for (const b of list) { out.push({ b, x }); btn(par, x, y, b, k); x += bW(b) + 8; } return out; }
function infoGlyph(par, x, y, tok, k) { box(par, x, y, 16, 16, { stroke: tok, r: "radius.badge", name: "info-glyph-ring", k }); txt(par, "i", x, y + (16 - th1(CAP)) / 2, 16, { type: CAP, col: tok, align: "center", k, name: "info-glyph" }); }
// CMP-028 inline callout, tone info (§3.4): color.status.info.subtle, the glyph and edge color.status.info.strong, text color.text.primary, the two choices
function calloutH(w, text) { const D = DZ("comfortable"); return Math.ceil(12 + estLines(text, w - 48, TYP(BODY).size, false, 400) * th1(BODY) + 8 + D.ctl + 12); }
function callout(par, x, y, w, text, btns, k, o) {
  o = o || {};
  const h = calloutH(w, text), tone = o.tone || "info", edge = tone === "danger" ? DANGER_S : INFO_S;
  box(par, x, y, w, h, { fill: tone === "danger" ? "color.surface.raised" : "color.status.info.subtle", stroke: edge, r: "radius.control", name: "callout", k });
  box(par, x, y, NV["border.thick"], h, { fill: edge, name: "callout-edge", k });
  if (tone === "danger") gly(par, "✕", x + 12, y + 12, { col: DANGER_S, big: true, k, name: "error-glyph" }); else infoGlyph(par, x + 12, y + 13, edge, k);
  const r = txt(par, text, x + 36, y + 12, w - 48, { type: BODY, col: PRI, k, name: "callout-text", ml: true });
  const by = y + 12 + r.h + 8;
  let bx = x + 36;
  for (const b of btns) { btn(par, bx, by, b, k); bx += bW(b) + 8; }
  return h;
}
// a PROPOSED stamp in the frame's margin right of the dialog (never on the dialog): "PROPOSED" + its source, color.text.primary over the scrim
let STAMPS = null; // { cols: [{ x, w }], top, maxY, list } for the frame being drawn
function stamp(y, label, o) { if (STAMPS) STAMPS.list.push({ y, t: (o && o.plain ? "" : (o && o.owner ? OWNER : PROP) + " · ") + label, name: o && o.plain ? "annotation" : "proposed-stamp" }); }
function flushStamps() { // placed in y order down the right margin (right of the card, left of the RightRail strip), then the left margin (right of the NavRail)
  let ci = 0, bottom = STAMPS.top - 6;
  for (const st of STAMPS.list.sort((p, q) => p.y - q.y)) {
    for (;;) {
      const col = STAMPS.cols[ci], h = Math.ceil(estLines(st.t, Math.floor(col.w * 0.85), TYP(CAP).size, false, 400) * th1(CAP)) /* pessimistic: the chip holds a wider wrap */, yy = Math.max(st.y, bottom + 6);
      if (yy + h + 2 <= STAMPS.maxY) { // R1 F-6: a color.surface.raised chip under the stamp, so its ink passes on every theme's scrimmed workspace (light: #626364 alone gives 3.0:1)
        const kk = K(); box(STAMPS.par, col.x - 4, yy - 2, col.w + 8, h + 4, { fill: "color.surface.raised", r: "radius.xs", name: "stamp-chip", k: kk });
        txt(STAMPS.par, st.t, col.x, yy, col.w, { type: CAP, col: PRI, k: kk, name: st.name, ml: true }); bottom = yy + h + 2 + NV["space.2"]; break; } // R1 F-10: space.2 between stacked stamps
      if (++ci >= STAMPS.cols.length) { warn("stamp", CUR_F + ": no room for the stamp \"" + st.t + "\""); return; }
      bottom = STAMPS.top - 6;
    }
  }
}
function withStamps(par, cols, top, maxY, fn) { const p = STAMPS; STAMPS = { par, cols, top, maxY, list: [] }; try { const r = fn(); flushStamps(); return r; } finally { STAMPS = p; } }
// an annotation inside a frame (a callout label in free space; d5Checks keeps it off every dialog and control rect)
function fnote(par, x, y, w, str, o) { return txt(par, str, x, y, w, { type: CAP, col: (o && o.col) || PRI, k: K(), name: "annotation", ml: true }).h; }
// ---------------------------------------------------------------- the CMP-228 preview tile (§8; E11-D03 D12, E11-D03:277–281) ----
// The bars are E12-D06's recorded fixture (07-data.js, pp/202's: 450 BTCUSDT 1m klines, packages/fixtures/bybit/2026-10-05), drawn as
// E12-D06's L0 marks in miniature: a 1 px wick in color.candle.wick on the slot's centre column, the body clamp(round(0.7 × s), 1, 35)
// wide (forced odd), color.candle.up / color.candle.down; OHLC ticks the same inks; Renko bricks no wick. No price is typed by hand.
const KB = KL; // 07-data.js: [{ t, o, h, l, c, v }] chronological
function agg(bars, n) { const out = []; for (let i = 0; i + n <= bars.length; i += n) { const g = bars.slice(i, i + n); out.push({ t: g[0].t, o: g[0].o, h: Math.max.apply(null, g.map((b) => b.h)), l: Math.min.apply(null, g.map((b) => b.l)), c: g[g.length - 1].c }); } return out; }
function renkoCloses(bars, ticks) { // §8 sample: Renko bricks of `ticks` ticks over the recorded closes (D03 C-6: a reversal needs two bricks), integer ticks
  // the box [lo, hi] is the last brick: a brick up needs a close at hi + ticks (a continuation, or a reversal two bricks above a down brick's low),
  // a brick down a close at lo − ticks; the first brick leaves the rounded first close by one brick
  const tk = (p) => Math.round(p / INSTR.tick), px = (n) => Math.round(n * INSTR.tick * 10) / 10, out = [];
  let lo = null, hi = null;
  for (const b of bars) {
    const q = tk(b.c);
    if (lo === null) { lo = hi = Math.round(q / ticks) * ticks; continue; }
    for (;;) {
      if (q >= hi + ticks) { out.push({ t: b.t, o: px(hi), c: px(hi + ticks), h: px(hi + ticks), l: px(hi) }); lo = hi; hi += ticks; continue; }
      if (q <= lo - ticks) { out.push({ t: b.t, o: px(lo), c: px(lo - ticks), h: px(lo), l: px(lo - ticks) }); hi = lo; lo -= ticks; continue; }
      break;
    }
  }
  return out;
}
function volBars(bars, size) { // Volume bars of `size` BTC built from the recorded klines (each kline whole: an illustration of a held Volume series, §8)
  const out = []; let cur = null;
  for (const b of bars) {
    if (!cur) cur = { t: b.t, o: b.o, h: b.h, l: b.l, c: b.c, v: 0 };
    cur.h = Math.max(cur.h, b.h); cur.l = Math.min(cur.l, b.l); cur.c = b.c; cur.v += b.v;
    if (cur.v >= size) { out.push(cur); cur = null; }
  }
  return out;
}
const PV_N = 40; // bars in the miniature
const PV_VOL = volBars(KB, AN("D03:default.volume")).slice(-PV_N), PV_VOL_HOLLOW = PV_VOL.slice(-24), PV_LIVE = KB.slice(-PV_N), PV_5M = agg(KB, 5).slice(-36), PV_RENKO = renkoCloses(KB, AN("D03:default.renko")).slice(-PV_N);
const fmtPx = (p) => kfmt(Number(p).toFixed(1)); // BTCUSDT's tick 0.1 (Auto precision, §6)
const hhmmU = (ms) => { const d = new Date(ms); return pad2(d.getUTCHours()) + ":" + pad2(d.getUTCMinutes()); };
function pvScale(bars, top, h) { let lo = Infinity, hi = -Infinity; for (const b of bars) { lo = Math.min(lo, b.l); hi = Math.max(hi, b.h); } const m = (hi - lo) * 0.08 || 1; lo -= m; hi += m; return { lo, hi, y: (p) => top + Math.round(((hi - p) / (hi - lo)) * h) }; }
const oddW = (s) => { let b = Math.max(1, Math.min(35, Math.round(0.7 * s))); if (b >= 4 && b % 2 === 0) b -= 1; return b; };
// the tile: { kind: "candles" | "ohlc" | "sample" | "empty" | "error", bars, label (W-19 for the sample) }; returns its height
const PV_H = 188;
function previewTile(par, x, y, w, o, k) {
  const h = PV_H;
  box(par, x, y, w, h, { fill: "color.surface.sunken", stroke: "color.border.default", r: "radius.card", name: "preview-tile", k });
  if (o.kind === "empty" || o.kind === "error") {
    if (o.kind === "empty") for (let i = 0; i < 7; i++) { const bh = 28 + ((i * 37) % 40); box(par, x + 60 + i * 26, y + 76 - bh / 2, 12, bh, { fill: TER, op: NV["opacity.muted"], opTok: "opacity.muted", r: "radius.xs", name: "preview-silhouette", k }); } // the CMP-029 silhouette at opacity.muted (E11-D03:279)
    else gly(par, "✕", x + w / 2 - 8, y + 70, { col: DANGER_S, big: true, k, name: "preview-error-glyph" });
    const t = o.kind === "empty" ? PV_EMPTY : PV_ERROR;
    txt(par, t, x + 12, y + 128, w - 24, { type: CAP, col: SEC, align: "center", k, name: "preview-state", ml: true });
    return h;
  }
  const gut = 60, top = y + (o.label ? 26 : 10), bot = y + h - 22, pw = w - 12 - gut, bars = o.bars, s = pw / bars.length, S = pvScale(bars, top, bot - top);
  if (o.label) txt(par, o.label, x + 10, y + 7, w - 20, { type: CAP, col: TER, k, name: "preview-sample-label" });
  bars.forEach((b, i) => {
    const xl = x + 6 + i * s, bw = oddW(s), cx = Math.round(xl + (s - bw) / 2 + (bw - 1) / 2), up = b.c >= b.o, ink = up ? "color.candle.up" : "color.candle.down";
    const yo = S.y(b.o), yc = S.y(b.c), bt = Math.min(yo, yc), bh = Math.max(1, Math.abs(yo - yc));
    if (o.kind === "candles") {
      box(par, cx, S.y(b.h), 1, Math.max(1, S.y(b.l) - S.y(b.h)), { fill: "color.candle.wick", name: "preview-wick", k });
      box(par, Math.round(xl + (s - bw) / 2), bt, bw, bh, { fill: ink, name: "preview-body", k });
    } else if (o.kind === "hollow") { // D06 §4.2: hollow when the close is at or above the open (a 1 px outline), solid below; the ink by the previous close
      const prev = i ? bars[i - 1].c : b.o, hk = b.c >= prev ? "color.candle.up" : "color.candle.down";
      if (b.c >= b.o) { // R1 F-5: the wick stops at the outline, so the hollow body stays open (a wick through it reads solid at this size)
        const bh2 = Math.max(3, bh);
        if (bt > S.y(b.h)) box(par, cx, S.y(b.h), 1, bt - S.y(b.h), { fill: hk, name: "preview-wick", k });
        if (S.y(b.l) > bt + bh2) box(par, cx, bt + bh2, 1, S.y(b.l) - bt - bh2, { fill: hk, name: "preview-wick", k });
        box(par, Math.round(xl + (s - bw) / 2), bt, bw, bh2, { stroke: hk, name: "preview-body-hollow", k });
      } else { box(par, cx, S.y(b.h), 1, Math.max(1, S.y(b.l) - S.y(b.h)), { fill: hk, name: "preview-wick", k }); box(par, Math.round(xl + (s - bw) / 2), bt, bw, bh, { fill: hk, name: "preview-body", k }); }
    } else if (o.kind === "ohlc") {
      box(par, cx, S.y(b.h), 1, Math.max(1, S.y(b.l) - S.y(b.h)), { fill: ink, name: "preview-stem", k });
      const tk = Math.max(1, Math.floor(bw / 2));
      box(par, cx - tk, yo, tk, 1, { fill: ink, name: "preview-open-tick", k }); box(par, cx + 1, yc, tk, 1, { fill: ink, name: "preview-close-tick", k });
    } else if (o.kind === "baseline") { // the line of closes as 1 px runs (no rotated shape in this script), up ink above the base, down ink below
      const nb = bars[i + 1];
      if (nb) {
        const y0 = S.y(b.c), y1 = S.y(nb.c), x0 = Math.round(xl + s / 2), x1 = Math.round(xl + s + s / 2), above = (b.c + nb.c) / 2 >= o.base;
        box(par, x0, y0, Math.max(1, x1 - x0), 1, { fill: above ? "color.candle.up" : "color.candle.down", name: "preview-line", k });
        if (y1 !== y0) box(par, x1, Math.min(y0, y1), 1, Math.abs(y1 - y0) + 1, { fill: above ? "color.candle.up" : "color.candle.down", name: "preview-line", k });
      }
    } else box(par, Math.round(xl + 0.5), bt, Math.max(1, Math.floor(s) - 1), bh, { fill: ink, name: "preview-brick", k }); // sample: Renko bricks
  });
  if (o.kind === "baseline") box(par, x + 6, S.y(o.base), pw, 1, { fill: "color.candle.wick", name: "preview-base-line", k }); // base B (D06 §3.2's base line ink)
  const lx = x + w - gut + 4;
  for (const f of [0.15, 0.5, 0.85]) { const p = S.hi - (S.hi - S.lo) * f; txt(par, fmtPx(p), lx, S.y(p) - th1(CAP) / 2, gut - 8, { type: CAP, col: TER, k, name: "preview-axis-price" }); }
  if (o.times) { const n = bars.length; for (const i of [Math.floor(n * 0.2), Math.floor(n * 0.75)]) txt(par, hhmmU(bars[i].t), x + 6 + i * s - 14, bot + 4, 36, { type: CAP, col: TER, align: "center", k, name: "preview-axis-time" }); }
  return h;
}
// ---------------------------------------------------------------- the SCR-031 dialog with the General tab (§2–§9; E11-D03 §6.1–§6.4) ----
// st (every key optional): type, typeFocus, base ("first" | "price"), callout ("ha-fp" | "ha-nt"), mode, value, invalid (a C-id), fieldFocus,
// est (a C-id), modeState ("needs" | "noprints" | "lot"), modeFocus, magnet, readout, scope, partial, footer { saving, failed, focus },
// role ("owner" | "viewer" | "viewas"), preview { kind, bars, label, caption, times }, scroll (0 | "end" | "bar" | px), tabChanged
function sectionRows(st) {
  const D = DZ("comfortable"), rows = [], role = st.role || "owner", t2Role = role !== "owner";
  const reasonBar = role === "viewer" ? WD["W-23"][0] : role === "viewas" ? WD["W-26"][0] : null;
  const legend = (t, extra) => rows.push({ h: Math.ceil(th1(H_SM)), after: 8, sec: t, draw: (p, x, y, k) => { txt(p, t, x, y, twm(t, H_SM) + 4, { type: H_SM, col: PRI, k, name: "section-legend" }); if (extra) extra(p, x, y, k); } });
  // ---- Chart type (§3.1): CMP-006 vertical, two columns at lg, column-major (five down the left, four down the right) ----
  legend(WD["W-1"][0]);
  rows[rows.length - 1].stamp = ["§3.1 the nine lines; §2.1 column-major order"];
  const cw = Math.floor((COLW - 16) / 2), dw = cw - RAD - 8, optH = (t) => Math.ceil(th1(BODY) + estLines(t[2], dw, TYP(CAP).size, false, 400) * th1(CAP));
  const sel = st.type || "candle";
  for (let i = 0; i < 5; i++) {
    const pair = [TYPES[i], TYPES[i + 5]].filter(Boolean), h = Math.max.apply(null, pair.map(optH));
    rows.push({ h, after: 10, id: "type", draw: (p, x, y, k) => pair.forEach((t, j) => {
      const ox = x + j * (cw + 16), on = t[0] === sel;
      radio(p, ox, y + (th1(BODY) - RAD) / 2, on, k);
      txt(p, t[1], ox + RAD + 8, y, dw, { type: BODY, col: PRI, k, name: "option-label" });
      txt(p, t[2], ox + RAD + 8, y + th1(BODY), dw, { type: CAP, col: SEC, k, name: "option-description", ml: true });
      if (on && st.typeFocus) ring(p, ox - 6, y - 4, cw + 12, optH(t) + 8, k); // R1 F-12: the ring spans the option's full column (6 px each side)
    }) });
  }
  if (sel === "baseline") { // §3.2: shown only while Baseline is chosen
    const bm = st.base || "first", lw = twm(WD["W-4"][0], LBL) + 4;
    rows.push({ h: D.row, after: 4, id: "base", draw: (p, x, y, k) => { txt(p, WD["W-4"][0], x, y + (D.row - th1(LBL)) / 2, lw, { type: LBL, col: PRI, k, name: "field-label" }); hGroup(p, x + lw + 12, y, COLW - lw - 12, [{ t: WD["W-4"][1], sel: bm === "first" }, { t: WD["W-4"][2], sel: bm === "price" }], k); } });
    if (bm === "price") rows.push({ h: D.ctl, after: 8, id: "base", draw: (p, x, y, k) => { // CMP-100: the Decimal string, snapped to the tick on blur
      const fw = 140; box(p, x + lw + 12, y, fw, D.ctl, { fill: "color.surface.app", stroke: TER, r: "radius.control", name: "price-field", k });
      txt(p, st.baseValue, x + lw + 20, y + (D.ctl - th1(NUM)) / 2, fw - 16, { type: NUM, col: PRI, k, name: "field-value" });
      txt(p, WD["W-4"][3], x + lw + 12 + fw + 8, y + (D.ctl - th1(CAP)) / 2, twm(WD["W-4"][3], CAP) + 4, { type: CAP, col: TER, k, name: "field-caption" });
    } });
  }
  if (st.callout) { // §3.4: the inline CMP-028 callout under the group, settled before Save
    const ha = st.callout === "ha-fp", text = ha ? WD["W-5"][0] : WD["W-6"][0];
    const btns = ha ? [{ t: WD["W-5"][1], focus: st.calloutFocus }, { t: WD["W-5"][2] }] : [{ t: WD["W-6"][1] }, { t: WD["W-6"][2], focus: st.calloutFocus }];
    rows.push({ h: calloutH(COLW, text), after: 8, id: "callout", stamp: ["§3.4 (BQ-8)", true], draw: (p, x, y, k) => callout(p, x, y, COLW, text, btns, k) });
  }
  // ---- Bar mode (§4.1, §5): CMP-006 horizontal, the one field, the static caption W-7, the estimate ----
  const md = MODE(st.mode || "time");
  rows.push({ gap: 20 });
  legend(WD["W-1"][1], (p, x, y, k) => txt(p, WD["W-7"][0], x + twm(WD["W-1"][1], H_SM) + 16, y + (th1(H_SM) - th1(CAP)) / 2, twm(WD["W-7"][0], CAP) + 4, { type: CAP, col: TER, k, name: "group-caption" }));
  if (reasonBar) { // §10.1: one CMP-065 notice (W-23 for a Viewer; W-26 first while viewing as); the radios point at it
    const nh = Math.ceil(estLines(reasonBar, COLW - 36, TYP(BODY).size, false, 400) * th1(BODY)) + 12;
    rows.push({ h: nh, after: 8, id: "notice", stamp: role === "viewer" ? null : ["§10.1 W-26 first"], draw: (p, x, y, k) => { box(p, x, y, COLW, nh, { fill: "color.surface.raised", stroke: "color.border.default", r: "radius.control", name: "group-notice", k }); lockIcon(p, x + 10, y + 6 + (th1(BODY) - NV["size.icon.sm"]) / 2, false, TER, k); txt(p, reasonBar, x + 28, y + 6, COLW - 36, { type: BODY, col: SEC, k, name: "t2-reason", ml: true }); } });
  }
  const opts = MODES.map((m, i) => {
    const o = { t: m.name, sel: m.id === md.id, focus: st.modeFocus && m.id === md.id, br: st.modeState === "noprints" && i > 0 }; // R1 F-11: no prints, one option per row (each T2 with its reason)
    if (t2Role) { o.t2 = true; o.reasonRef = reasonBar; }
    else if (st.modeState === "needs" && m.id !== "time" && m.id !== md.id) o.tag = CD["C-30"];
    else if (st.modeState === "noprints" && m.id !== "time") { o.t2 = true; o.reason = CD["C-24"]; o.sel = false; }
    else if (st.modeState === "lot" && (m.id === "volume" || m.id === "delta")) { o.t2 = true; o.reason = CD["C-25"]; o.sel = false; }
    return o;
  });
  const gh = hGroupH(opts, COLW);
  rows.push({ h: gh, after: 4, id: "radios", draw: (p, x, y, k) => { const n0 = T2S.length; hGroup(p, x, y, COLW, opts, k); for (let i = n0; i < T2S.length; i++) if (!T2S[i].reason) T2S[i].reason = reasonBar; } });
  const dsc = CD[md.desc];
  rows.push({ h: Math.ceil(th1(CAP)), after: 8, id: "desc", draw: (p, x, y, k) => txt(p, dsc, x, y, COLW, { type: CAP, col: SEC, k, name: "mode-description" }) });
  if (!(st.modeState === "noprints" && md.id !== "time")) {
    const lw = twm(md.label, LBL) + 4;
    rows.push({ h: D.ctl, after: 6, id: "field", draw: (p, x, y, k) => {
      txt(p, md.label, x, y + (D.ctl - th1(LBL)) / 2, lw, { type: LBL, col: PRI, k, name: "field-label" });
      const v = md.id === "time" ? st.value || md.def : st.value != null ? st.value : String(md.def);
      if (t2Role) t2Field(p, x + lw + 12, y, md.id === "time" ? 96 : fieldW(v, null), v, md.id === "time" ? null : md.unit, reasonBar, k);
      else if (md.id === "time") selectField(p, x + lw + 12, y, 96, v, k);
      else stepperField(p, x + lw + 12, y, fieldW(v, md.unit), v, md.unit, { invalid: !!st.invalid || !!st.held || st.est === "C-19", focus: st.fieldFocus, caret: !!st.held }, k); // C-19 refuses: the invalid boundary (D03:168); r2 ruling 3: a typed atr: is D03 board 05's "Renko, atr: typed" form (invalid boundary, caret kept)
    } });
    if (st.invalid) rows.push({ h: Math.ceil(th1(CAP)) + 2, after: 6, id: "msg", draw: (p, x, y, k) => { gly(p, "✕", x + lw + 12, y, { col: DANGER_S, k, name: "invalid-glyph" }); txt(p, CD[st.invalid], x + lw + 12 + 16, y, COLW - lw - 28, { type: CAP, col: PRI, k, name: "field-message" }); } });
    if (st.held) rows.push({ h: Math.ceil(th1(CAP)) + 2, after: 6, id: "msg", draw: (p, x, y, k) => { gly(p, "✕", x + lw + 12, y, { col: DANGER_S, k, name: "invalid-glyph" }); txt(p, CD["C-12"], x + lw + 12 + 16, y, COLW - lw - 28, { type: CAP, col: PRI, k, name: "field-message" }); } }); // r2 ruling 3: C-12 in the message line with the ✕, as D03 board 05 draws it; nothing is sent
    if (st.est) rows.push({ h: Math.ceil(th1(CAP)), after: 4, id: "est", draw: (p, x, y, k) => { // D03:141, :168: C-19 with ✕ color.status.danger.strong, C-20 with ⚠ color.status.warning.strong (glyph 12 + 4 gap)
      const g = st.est === "C-19" ? ["✕", DANGER_S, "estimate-glyph-refused"] : st.est === "C-20" ? ["⚠", WARN_S, "estimate-glyph-warning"] : null;
      if (g) gly(p, g[0], x + lw + 12, y, { col: g[1], k, name: g[2] });
      txt(p, CD[st.est], x + lw + 12 + (g ? 16 : 0), y, COLW - lw - 12 - (g ? 16 : 0), { type: CAP, col: SEC, k, name: "estimate-line" });
    } });
  }
  // ---- Crosshair (§2.2, X-7) ----
  rows.push({ gap: 20 });
  legend(WD["W-1"][2]);
  const lab = 72;
  const xrow = (label, values, on, stampIt) => rows.push({ h: D.row, after: 2, stamp: stampIt, draw: (p, x, y, k) => { txt(p, label, x, y + (D.row - th1(LBL)) / 2, lab - 8, { type: LBL, col: PRI, k, name: "field-label" }); hGroup(p, x + lab, y, COLW - lab, values.map((v) => ({ t: v, sel: v === on })), k); } });
  xrow("Magnet", ["Off", "Weak", "Strong"], st.magnet || "Off");
  xrow("Readout", ["Follow", "Docked", "Off"], st.readout || "Follow", ["§2.2 the Readout default"]);
  rows.push({ h: Math.ceil(th1(CAP)), after: 8, draw: (p, x, y, k) => txt(p, WD["W-10"][0], x, y, COLW, { type: CAP, col: TER, k, name: "helper" }) });
  // ---- Session and the pointer to Scales (§2.3) ----
  rows.push({ gap: 20 });
  legend(WD["W-1"][3]);
  rows[rows.length - 1].stamp = ["§2.3 the Session row (BQ-16)", true];
  for (const t of WD["W-9"]) rows.push({ h: Math.ceil(th1(BODY)), after: 2, draw: (p, x, y, k) => txt(p, t, x, y, COLW, { type: BODY, col: SEC, k, name: "session-line" }) });
  rows.push({ h: Math.ceil(th1(BODY)), after: 2, sep: 8, stamp: ["§2.3 the pointer copy"], draw: (p, x, y, k) => txt(p, WD["W-8"][0], x, y, COLW, { type: BODY, col: SEC, k, name: "pointer-line" }) });
  rows.push({ h: Math.ceil(th1(BODY)), after: 6, draw: (p, x, y, k) => txt(p, WD["W-8"][1], x, y, COLW, { type: BODY, col: SEC, k, name: "pointer-value" }) });
  rows.push({ h: D.ctl, after: 0, draw: (p, x, y, k) => btn(p, x, y, { t: WD["W-8"][2], kind: "ghost", stroke: "color.border.default", focus: st.scalesFocus }, k) });
  return rows;
}
// R1 F-4: the preview's legend names the bar mode the preview draws, in C-38's trigger form (D03:223: 15m · Tick 1,000 · Vol 50 BTC ·
// Range 40 · Delta 25 BTC · Renko 30)
function pvHead(st) {
  const m = st.mode || "time", v = st.value != null ? String(st.value) : null, d = MODE(m);
  const n = kfmt(v != null ? v : String(d.def));
  const form = m === "time" ? (v || "1m") : m === "volume" ? "Vol " + n + " BTC" : m === "delta" ? "Delta " + n + " BTC" : d.name + " " + n;
  return "Preview (BTCUSDT · " + form + ")";
}
// lay the rows out in content coordinates (y from the body's top)
function layoutRows(rows) { let y = 0; for (const r of rows) { if (r.gap) { y += r.gap; continue; } y += r.sep || 0; r.y = y; y += r.h + (r.after || 0); } return y; }
function settingsDialog(f, fx, fy, st) {
  st = st || {};
  const D = DZ("comfortable"), P = NV["space.dialog.padding"], role = st.role || "owner";
  const top = fy + TOPBAR_H + (role === "viewas" ? AN("v.banner.compact") : 0), dx = fx + (VW - DLG_W) / 2, dy = Math.round(top + (fy + VH - STATUSBAR_H - top - DLG_H) / 2); // centred between the TopBar (and SCR-124's banner) and the StatusBar
  const dd = dlg(f, dx, dy, DLG_W, DLG_H, { name: "dialog" }), k = dd.k;
  const out = { dx, dy, w: DLG_W, h: DLG_H, ctl: {} };
  const cols = [{ x: dx + DLG_W + 8, w: VW - STRIP_W - 16 - DLG_W - (dx - fx) }, { x: fx + NAVRAIL_W + 8, w: dx - fx - NAVRAIL_W - 16 }]; // the stamps' margins: right of the card, then left of it
  return withStamps(f, cols, dy, fy + VH - STATUSBAR_H - 8, () => {
    // header: the title (CMP-043 type.ui.heading-sm) and the CMP-002 close; the CMP-042 tabs (E11-D03 §6.1)
    txt(f, DLG_TITLE, dd.x, dd.y, 300, { type: H_SM, col: PRI, k, name: "dialog-title" });
    box(f, dd.right - D.ctl, dd.y - 6, D.ctl, D.ctl, { r: "radius.control", name: "icon-button", k });
    drawParts(f, [{ g: "✕", col: SEC }], dd.right - D.ctl, dd.right, dd.y - 6, D.ctl, D, k, "c");
    const ty = dd.y + Math.ceil(th1(H_SM)) + 12;
    let tx = dd.x;
    TABS.forEach((t, i) => {
      const w = Math.ceil(2 * NV["space.inset.md"] + twm(t, LBL)), on = i === 0;
      if (on) box(f, tx, ty, w, D.ctl, { fill: "color.action.selected", r: "radius.control", name: "tab-selected", k });
      txt(f, t, tx + NV["space.inset.md"], ty + (D.ctl - th1(LBL)) / 2, w - 2 * NV["space.inset.md"], { type: LBL, col: on ? PRI : SEC, weightTok: on ? "font.weight.semibold" : undefined, k, name: on ? "tab-active" : "tab" });
      if (on) box(f, tx, ty + D.ctl - NV["border.thick"], w, NV["border.thick"], { fill: "color.border.selected", name: "tab-underline", k });
      if (on && st.tabChanged) stamp(ty, "W-22: the tab's name reads \"" + WD["W-22"][0] + "\" (§9.2)");
      tx += w + 4;
    });
    box(f, dd.x, ty + D.ctl, dd.w, 1, { fill: "color.border.default", name: "tabs-rule", k });
    // footer, bottom up: the buttons, the error row (§9.3), the role reasons (§10.1), the scope helper lines and the §7.3 list, the scope control
    const by = dd.bottom - D.ctl;
    const t2 = role === "viewer" ? REASON_SAVE : role === "viewas" ? WD["W-26"][0] : null;
    const ft = st.footer || {};
    const btns = [
      { t: "Reset General…", kind: t2 ? "t2" : "secondary", reason: t2, focus: ft.focus === "resetG", name: t2 ? "write-reset-general-t2" : "write-reset-general" },
      { t: "Reset all…", kind: t2 ? "t2" : "secondary", reason: t2, name: t2 ? "write-reset-all-t2" : "write-reset-all" },
      { t: "Cancel", kind: "secondary", name: "cancel" },
      ft.saving ? { t: "Save", kind: "saving" } : { t: "Save", kind: t2 ? "t2" : "primary", reason: t2, focus: ft.focus === "save", name: t2 ? "write-save-t2" : "write-save" },
    ];
    const pos = btnRowR(f, dd.right, by, btns, k);
    out.ctl.buttons = pos;
    let fy0 = by;
    if (ft.failed) { // §9.3 failed: W-18 with Retry (C-41's form); the dialog stays
      const eh = D.ctl + 8;
      fy0 -= eh + 8;
      box(f, dd.x, fy0, dd.w, eh, { fill: "color.surface.raised", stroke: DANGER_S, r: "radius.control", name: "callout", k });
      box(f, dd.x, fy0, NV["border.thick"], eh, { fill: DANGER_S, name: "callout-edge", k });
      gly(f, "✕", dd.x + 12, fy0 + (eh - NV["size.icon.md"] * 1.2) / 2, { col: DANGER_S, big: true, k, name: "error-glyph" });
      txt(f, WD["W-18"][0], dd.x + 36, fy0 + (eh - th1(BODY)) / 2, twm(WD["W-18"][0], BODY) + 4, { type: BODY, col: PRI, k, name: "error-text" });
      btn(f, dd.right - 8 - bW({ t: WD["W-18"][1] }), fy0 + 4, { t: WD["W-18"][1], focus: ft.retryFocus, name: "retry" }, k);
    }
    if (t2) { // one reason line for Save and both Resets (E09-D09 2a: the host's reason under the footer, color.text.secondary)
      fy0 -= Math.ceil(th1(CAP)) + 6;
      const rw = twm(t2, CAP) + 4;
      txt(f, t2, dd.right - rw, fy0, rw, { type: CAP, col: SEC, k, name: "t2-reason" });
      if (role === "viewer") stamp(fy0, "§10.1 Reset General… and Reset all… T2");
    }
    const scope = st.scope || "this", segT2 = role === "viewer" ? REASON_SET : role === "viewas" ? WD["W-26"][0] : null;
    const lines = [{ t: HELP[scope], col: TER }];
    if (scope === "default") lines.push({ t: WD["W-14"][0], col: TER, stamp: ["§7.2 W-14 helper"] }, { t: INTERIM, col: TER });
    if (segT2) lines.push({ t: "As new default: " + segT2, col: SEC, name: "t2-reason" });
    if (st.partial) { lines.push({ t: WD["W-11"][0], col: PRI, type: BODY, gap: 6, stamp: ["§7.3 the partial-apply list (BQ-11)"] }); for (const l of WD["W-11"].slice(1)) lines.push({ t: l, col: SEC }); }
    const lh = (l) => Math.ceil((l.type === BODY ? th1(BODY) : th1(CAP))) + 2 + (l.gap || 0);
    fy0 -= 10 + lines.reduce((a, l) => a + lh(l), 0);
    const sy = fy0 - 4 - D.ctl;
    // the scope control (CMP-003, E11-D03 D10): "Apply to:" and the three segments
    const al = "Apply to:", aw = twm(al, LBL) + 4;
    txt(f, al, dd.x, sy + (D.ctl - th1(LBL)) / 2, aw, { type: LBL, col: PRI, k, name: "field-label" });
    let sx = dd.x + aw + 12;
    for (const [id, label] of SEGS) {
      const o = { pressed: id === scope, t2: id === "default" && !!segT2, reason: segT2, focus: st.scopeFocus === id };
      sx += segment(f, sx, sy, label, o, k) + 4;
    }
    let ly = fy0;
    for (const l of lines) { ly += l.gap || 0; txt(f, l.t, dd.x, ly, dd.w, { type: l.type || CAP, col: l.col, k, name: l.name || "scope-helper" }); if (l.stamp) stamp(ly, l.stamp[0]); ly += lh(l) - (l.gap || 0); }
    // the body: the four sections (left) and the preview (right), scrolling between the header and the footer (CMP-043 "scrolls")
    const bodyTop = ty + D.ctl + 16, bodyBot = sy - 16, bodyH = bodyBot - bodyTop;
    const rows = sectionRows(st), contentH = layoutRows(rows);
    const pvH = Math.ceil(th1(H_SM)) + 8 + PV_H + 8 + (st.preview ? Math.ceil(estLines(st.preview.caption || "", PVW, TYP(CAP).size, false, 400) * th1(CAP)) : 0);
    const maxScroll = Math.max(0, Math.max(contentH, pvH) - bodyH);
    let scroll = st.scroll === "end" ? maxScroll : st.scroll === "bar" ? Math.min(maxScroll, rows.find((r) => r.sec === WD["W-1"][1]).y) : Number(st.scroll || 0);
    scroll = Math.max(0, Math.min(maxScroll, scroll));
    out.scroll = scroll; out.maxScroll = maxScroll; out.bodyTop = bodyTop; out.bodyH = bodyH; out.hidden = [];
    const vis = (y, h) => y >= scroll - 0.5 && y + h <= scroll + bodyH + 0.5;
    rows.forEach((r, i) => { if (r.sec) { const nx = rows.slice(i + 1).find((q) => !q.gap); r.withNext = nx; } });
    for (const r of rows) {
      if (r.gap) continue;
      if (!vis(r.y, r.h) || (r.withNext && !vis(r.withNext.y, r.withNext.h))) { out.hidden.push(r.sec || r.y); continue; } // a legend shows only with its first row
      const yy = bodyTop + r.y - scroll;
      r.draw(f, dd.x, yy, K());
      if (r.stamp) stamp(yy, r.stamp[0], { owner: r.stamp[1] });
    }
    const px = dd.x + COLW + COLGAP;
    if (st.preview && vis(0, pvH)) {
      const yy = bodyTop - scroll, kp = K();
      txt(f, st.preview.head || pvHead(st), px, yy, PVW, { type: H_SM, col: PRI, k: kp, name: "section-legend" }); // E11-D03 §6.1's CMP-065 legend (the pane's symbol and setting)
      previewTile(f, px, yy + Math.ceil(th1(H_SM)) + 8, PVW, st.preview, kp);
      if (st.preview.caption) txt(f, st.preview.caption, px, yy + Math.ceil(th1(H_SM)) + 8 + PV_H + 8, PVW, { type: CAP, col: SEC, k: kp, name: "preview-caption", ml: true });
      if (st.preview.stamp) stamp(yy + Math.ceil(th1(H_SM)) + 8, st.preview.stamp);
    }
    if (maxScroll > 0) { // the body's scroll position (CMP-043 "scrolls"): a 4 px thumb in the card's right padding
      const th = Math.max(24, Math.round((bodyH * bodyH) / (bodyH + maxScroll))), tyy = bodyTop + Math.round(((bodyH - th) * scroll) / maxScroll);
      box(f, dd.right + 10, tyy, 4, th, { fill: "color.border.strong", r: "radius.badge", name: "scroll-thumb", k });
    }
    for (const [ny, t] of st.marginNotes || []) stamp(fy + ny, t, { plain: true });
    out.contentH = contentH; out.rows = rows;
    return out;
  });
}
// ---- CMP-044 over the dialog (§9.1 the two Reset confirms, §9.2 the dirty guard): a second scrim, the card centred, focus on the safe choice ----
function confirmCard(f, fx, fy, title, body, btns, o) {
  o = o || {};
  const D = DZ("comfortable"), P = NV["space.dialog.padding"], w = o.w || 520, iw = w - 2 * P;
  const bodyH = body.reduce((a, l) => a + Math.ceil(estLines(l.t, iw - (l.dx || 0), TYP(l.type || BODY).size, false, 400) * th1(l.type || BODY)) + (l.after == null ? 6 : l.after), 0);
  const h = Math.ceil(2 * P + th1(H_SM) + 12 + bodyH + 12 + D.ctl);
  const x = Math.round(fx + (VW - w) / 2), y = Math.round(fy + (VH - h) / 2);
  const dd = dlg(f, x, y, w, h, { name: "confirm-dialog" }), k = dd.k;
  txt(f, title, dd.x, dd.y, iw, { type: H_SM, col: PRI, k, name: "confirm-title", ml: true });
  let yy = dd.y + Math.ceil(th1(H_SM)) + 12;
  for (const l of body) { const r = txt(f, l.t, dd.x + (l.dx || 0), yy, iw - (l.dx || 0), { type: l.type || BODY, col: l.col || PRI, k, name: "confirm-body", ml: true }); yy += r.h + (l.after == null ? 6 : l.after); }
  btnRowR(f, dd.right, dd.bottom - D.ctl, btns, k);
  return { x, y, w, h };
}
// ---------------------------------------------------------------- the frames: windows (the workspace behind the dialog) and specimen sheets ----
// A window is the 1280 × 800 frame (§0) holding E15-D03's merged chrome (b5Shell: TopBar, NavRail, RightRail strip, tab strip, StatusBar;
// the role shells of 42-d03), its chart panel(s) (42-d03's §3.6 header steps on the D03 tool's widths), the modal scrim (palette.black at
// opacity.scrim, by value, re-asserted after the bindings: pp/361 r3 F-1; the TopBar, the StatusBar and the view-as banner stay unscrimmed)
// and the SCR-031 dialog. A specimen sheet (estimate-states, ha-footprint, validation/specimens, keyboard/storyboard) is the same 1280 × 800
// frame holding 1:1 crops of the dialog's parts, each labelled: one window cannot show several states of one field at once.
const SPELL = { "1m": "1 minute", "15m": "15 minutes", "1h": "1 hour", "Vol 50 BTC": "Volume 50 BTC" };
// R1 F-7: a frame whose chart shows another bar mode sets TB_IV, and the TopBar's interval control reads it (E15-D03's b5TopBar draws "1m"
// by value; 42-d03 stays byte-identical to the template, so the override wraps the control it calls)
let TB_IV = null;
{ const ctl0 = ctl; ctl = function (par, x, y, label, D, o) { return ctl0(par, x, y, TB_IV && label === "1m" && o && o.name === "topbar-control" ? TB_IV : label, D, o); }; }
function wsChart(f, r, sym, iv, focused, D) { // a chart panel at its §3.6 step with its symbol and interval; returns the plot rect
  const s = toolStep("chart", r.w, "compact"), P = hdrP("chart", s, !!focused);
  P.symbol = sym; P.interval = iv; P.statusEnv = "LIVE";
  const q = drawStep(f, r, P, D, "E12-D05 chart " + sym + " " + r.w + " at " + s), k = K();
  const nm = "role=\"region\" · \"Chart, " + sym + " " + SPELL[iv] + ", Live\"" + (focused ? " · focused" : "");
  txt(f, nm, q.x + SP3, q.y + D.ctl + SP3, Math.min(twm(nm, CAP) + 4, (q.plotW || q.w) - 2 * SP3), { type: CAP, col: SEC, k, name: "region-name" });
  return q;
}
// the NC-1 status strip (D02 D-7): a third chrome row at the plot's top, one message, its action and Dismiss (an outcome notice); a build strip
function strip(f, q, D, text, btns, o) {
  o = o || {};
  const k = K(), h = D.ctl + 4, w = (q.plotW || q.w);
  box(f, q.x, q.y, w, h, { fill: o.notice ? "color.status.info.subtle" : "color.surface.raised", name: o.notice ? "strip-notice" : "strip", k });
  hair(f, q.x, q.y + h - 1, w, 1, "color.border.default", "strip-rule", k);
  let x = q.x + SP3;
  if (o.busy) { gly(f, "⟳", x, q.y + (h - NV["size.icon.sm"] * 1.2) / 2, { col: PRI, k, name: "strip-busy" }); x += NV["size.icon.sm"] + SP1; }
  const bws = (btns || []).map((b) => btnW({ t: b }, D)), room = q.x + w - SP3 - bws.reduce((a, b) => a + b + SP2, 0) - x;
  txt(f, text, x, q.y + (h - th1(CAP)) / 2, Math.min(twm(text, CAP) + 4, room), { type: CAP, col: PRI, k, name: o.notice ? "strip-notice-text" : "strip-text" });
  let bx = q.x + w - SP3 - bws.reduce((a, b) => a + b + SP2, 0) + SP2;
  (btns || []).forEach((b, i) => { button(f, bx, q.y + 2, { t: b, name: "strip-button" }, D, k); bx += bws[i] + SP2; });
  return h;
}
// a window frame: { role, panels: "one" | "four", scrim, dialog: st } → { f, D, dock, dlg, panels }
function winFrame(B, row, x, y, o) {
  o = o || {};
  const f = frame(B, o.name || row.frame, x, y, VW, VH);
  CUR_F = o.name || row.frame;
  const role = o.role || "owner";
  TB_IV = o.iv || null;
  const sh = role === "viewer" ? b5Shell(f, x, y, VW, VH, { user: c("b5UserViewer"), t2Cluster: true, killT2: true, health: "states", admin: false, save: "perm", reason: c("b5PermSave") })
    : role === "viewas" ? b5Shell(f, x, y, VW, VH, { banner: true, save: "viewas", t2Cluster: true }) : b5Shell(f, x, y, VW, VH, {});
  TB_IV = null;
  const D = sh.D, dk = sh.dock, out = { f, D, dock: dk, panels: [] };
  if (o.panels === "four") {
    const w2 = Math.floor((dk.w - GUTTER) / 2), h2 = Math.floor((dk.h - GUTTER) / 2), k = K();
    PANELS.forEach((p, i) => { const r = { x: dk.x + (i % 2) * (w2 + GUTTER), y: dk.y + Math.floor(i / 2) * (h2 + GUTTER), w: i % 2 ? dk.w - w2 - GUTTER : w2, h: i < 2 ? h2 : dk.h - h2 - GUTTER }; out.panels.push({ p, r, q: wsChart(f, r, p.sym, p.iv, i === 0, D) }); });
    splitterV(f, dk.x + w2, dk.y, dk.h, "rest", k);
    splitterH(f, dk.x, dk.y + h2, dk.w, k);
  } else out.panels.push({ p: PANELS[0], r: dk, q: wsChart(f, dk, "BTCUSDT", o.iv || "1m", true, D) });
  if (o.dialog) {
    const top = y + TOPBAR_H + (role === "viewas" ? AN("v.banner.compact") : 0);
    scrim(f, x, top, VW, y + VH - STATUSBAR_H - top);
    out.dlg = settingsDialog(f, x, y, o.dialog);
  }
  return out;
}
function sheetFrame(B, row, x, y) { const f = frame(B, row.frame, x, y, VW, VH); CUR_F = row.frame; return f; }
// a crop: a dialog-surface card (color.surface.overlay, radius.dialog) with its label above it (an annotation); returns the inner box
function crop(f, x, y, w, h, label, k) {
  k = k || K();
  const lh = label ? txt(f, label, x, y, w, { type: CAP, col: SEC, k: K(), name: "crop-label", ml: true }).h + 6 : 0;
  box(f, x, y + lh, w, h, { fill: "color.surface.overlay", stroke: "color.border.default", r: "radius.dialog", name: "dialog-crop", k });
  return { x: x + 16, y: y + lh + 14, w: w - 32, bottom: y + lh + h, k, top: y + lh };
}
// draw a run of sectionRows (by their sec / index range) into a crop: rows from the first whose sec is `from` until the next legend
function drawRowsInto(f, rows, x, y, pick) { let yy = y; for (const r of rows) { if (r.gap || !pick(r)) continue; yy += r.sep || 0; r.draw(f, x, yy, K()); yy += r.h + (r.after || 0); } return yy; }
function sectionOf(rows, name) { let on = false; return rows.filter((r) => { if (r.sec) on = r.sec === name; return on && !r.gap; }); }
function rowsH(rows) { return rows.reduce((a, r) => a + (r.sep || 0) + r.h + (r.after || 0), 0); }
// ---------------------------------------------------------------- the board's own checks (d5Checks; each hit is a warn(), so the mock fails) ----
// 1. annot-clear: no annotation text (frame captions, notes, stamps, crop labels, in-frame annotations, the footer and the a11y strip) meets a
//    drawn dialog rect or control rect (the card, a confirm, a crop, a button, a radio, a segment, a field, a callout, a tab, the preview tile,
//    a strip, the chrome's controls);
// 2. view-as: in a frame named view-as no write control is drawn enabled: every write-* rect ends -t2, and the TopBar's FLATTEN ALL… /
//    CANCEL ALL… / FREEZE… are their -t2 forms (E15-D03's view-as shell);
// 3. no-path: no footer (and no other text) holds a path ("work/", or "/" + a name with a file extension);
// 4. t2: every T2 control of the dialog has its lock leading (a lock-body rect inside it, left of its label) and its reason drawn in its frame;
// 5. words: every frame draws its §15.1 Copy cell: each id's strings (§12 W-rows, D03's C-rows, filled) appear on the frame (board 01's
//    row on the register frame plus the scrolled frame beside it).
const D5_ANNOT = /\/ (annotation|frame-caption|proposed-stamp|crop-label|callout-label|footer|a11y-strip|board-title|eyebrow)$/;
const D5_CTRL = /\/ (dialog|confirm-dialog|dialog-crop|button|button-t2|write-[a-z-]+|cancel|retry|confirm-[a-z]+|guard-[a-z]+|segment|segment-pressed|radio|radio-t2|radio-selected|field|select|price-field|stepper|callout|icon-button|tab-selected|preview-tile|strip|strip-notice|strip-button|group-notice|scroll-thumb|topbar-control|toolbar-button|search-trigger|user-menu|control-t2|flatten-all(-t2)?|cancel-all(-t2)?|freeze(-t2)?|kill-switch(-t2)?|drawer-launcher|tab-new|toolbar-more|toolbar-save-[a-z0-9-]+|viewas-exit|env-badge)$/;
const D5_TB = /\/ (flatten-all|cancel-all|freeze)$/;
const D5_PATH = /work\/|\/[\w.-]*\.[A-Za-z][A-Za-z0-9]{0,4}\b/;
const D5_STATS = [];
const nbsp = (s) => String(s || "").replace(/ /g, " ");
function d5Checks(B) {
  if (!REC || !REC.shapes) return;
  const rect = (s) => ({ x: s.v.x, y: s.v.y, w: s.v.width, h: s.v.height }), meets = (a, b) => Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 0.5 && Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > 0.5;
  const desc = (s, out) => { for (const ch of s.children) { out.push(ch); desc(ch, out); } return out; };
  const pre = TICKET.length + 3, nm = (s) => String(s.v.name || "").slice(pre);
  // 1. annot-clear
  const ctrls = REC.shapes.filter((s) => s.kind === "rect" && D5_CTRL.test(s.v.name || "")).map((s) => ({ r: rect(s), n: nm(s) }));
  let hits = 0;
  for (const s of REC.shapes) {
    if (s.kind !== "text" || !D5_ANNOT.test(s.v.name || "")) continue;
    const r = rect(s), m = ctrls.find((c0) => meets(r, c0.r));
    if (m && hits++ < 8) warn("annot-clear", "board " + pad2(B.n) + ": the " + nm(s) + " \"" + nbsp(s.text).slice(0, 50) + "\" (" + [r.x, r.y, r.w, r.h].map(Math.round).join(", ") + ") meets the " + m.n + " at " + [m.r.x, m.r.y, m.r.w, m.r.h].map(Math.round).join(", "));
  }
  if (hits > 8) warn("annot-clear", "board " + pad2(B.n) + ": " + (hits - 8) + " more annotation texts meet a dialog or control rect");
  // the board's child frames by name
  const frames = new Map();
  for (const fr of REC.shapes) if (fr.kind === "board" && fr.parent && fr.parent.seq === 0) frames.set(String(fr.v.name), fr);
  const textsOf = (names) => { const out = []; for (const n0 of names) { const fr = frames.get(n0); if (fr) for (const s of desc(fr, [])) if (s.kind === "text") out.push(nbsp(s.text)); } return out; };
  // 2. view-as
  let va = 0;
  for (const [n0, fr] of frames) {
    if (!/view-?as/i.test(n0)) continue;
    va++;
    const all = desc(fr, []), live = all.filter((s) => s.kind === "rect" && (/\/ write-[a-z-]+$/.test(s.v.name || "") && !/-t2$/.test(s.v.name) || D5_TB.test(s.v.name || "")));
    if (live.length) warn("view-as", "board " + pad2(B.n) + " frame " + n0.slice(String(B.b.name).length + 3) + ": " + live.length + " write control(s) drawn enabled while viewing as (" + live.map(nm).join(", ") + ")");
    if (!all.some((s) => s.kind === "text" && nbsp(s.text) === c("b5ViewAs"))) warn("view-as", "board " + pad2(B.n) + " frame " + n0 + ": no SCR-124 banner line");
  }
  // 3. no-path (footers first, then every text)
  for (const s of REC.shapes) if (s.kind === "text" && D5_PATH.test(s.text || "")) warn("no-path", "board " + pad2(B.n) + ": the " + nm(s) + " \"" + String(s.text).slice(Math.max(0, String(s.text).search(D5_PATH) - 30), String(s.text).search(D5_PATH) + 30) + "\" holds a path (a board names page, board, version and theme only)");
  // 4. t2: the lock leads and the reason is drawn
  const locks = REC.shapes.filter((s) => s.kind === "rect" && /\/ lock-body$/.test(s.v.name || "")).map(rect);
  let t2n = 0;
  for (const t of T2S) {
    t2n++;
    const fn = B.b.name + " / " + norm(t.frame);
    const lk = locks.find((l) => l.x >= t.x - 0.5 && l.x + l.w <= t.labelX + 0.5 && l.y >= t.y - 0.5 && l.y + l.h <= t.y + t.h + 0.5);
    if (!lk) warn("t2", "board " + pad2(B.n) + ": the T2 \"" + t.what + "\" in " + t.frame + " has no lock leading its label");
    if (!t.reason) warn("t2", "board " + pad2(B.n) + ": the T2 \"" + t.what + "\" in " + t.frame + " has no reason");
    else if (!textsOf([fn]).some((x) => x.indexOf(t.reason) >= 0)) warn("t2", "board " + pad2(B.n) + ": the T2 \"" + t.what + "\"'s reason \"" + t.reason + "\" is not drawn in " + t.frame);
  }
  // 5. words: the row's Copy cell on its frame
  let wn = 0;
  for (const row of regRows(B.n)) {
    const names = [B.b.name + " / " + norm(row.frame)].concat(FRAME_EXTRA.filter((e) => e.board === B.n && e.row === row.frame).map((e) => e.name));
    if (!frames.has(names[0])) { warn("words", "board " + pad2(B.n) + ": no frame " + row.frame); continue; }
    const all = textsOf(names).join("\n");
    for (const id of String(row.copy).split(",").map((s) => s.trim()).filter((s) => s && s !== "—")) {
      const ws = WALT[id] ? [WALT[id](row)] : wordsOf(id);
      if (!ws) { warn("words", "board " + pad2(B.n) + " " + row.frame + ": no copy for " + id); continue; }
      for (const w of ws) { wn++; if (all.indexOf(w) < 0) warn("words", "board " + pad2(B.n) + " " + row.frame + ": " + id + "'s \"" + w.slice(0, 60) + "\" is not on the frame"); }
    }
  }
  D5_STATS.push({ board: B.n, controls: ctrls.length, viewAsFrames: va, t2: t2n, words: wn });
}
const finish0 = finish;
finish = function (B, y, notes, a11y) { finish0(B, y, notes, a11y); d5Checks(B); T2S.length = 0; };
// ---------------------------------------------------------------- the boards (spec §0's table; §15.1's rows) ----------------------------------
// Every board lays its §15.1 rows out in one row, left to right (§0: the owner walks them left to right), 80 px apart; each frame's caption
// prints the row's cells (State, Components, Copy, Tokens, Status) and what the frame shows; the board's notes and its a11y strip follow.
const FRAME_EXTRA = []; // { board, row, name }: a frame drawn beside a register row that is not a row of its own (board 01's scroll position)
function regCap(row, extra) { return row.frame + " · board " + row.board + " · " + row.theme + " · State: " + row.state + " · Components: " + row.components + " · Copy: " + row.copy + " · Tokens: " + row.tokens + " · Status: " + row.status + (extra ? " · " + extra : ""); }
function lay(B, items) { // items: [{ row, draw(x, y) → caption extra (string), name? }]; returns the captions' bottom
  let x = B.X, bottom = B.y;
  for (const it of items) {
    const ex = it.draw(x, B.y) || "";
    const ch = caption(B, x, B.y + VH + 12, VW, it.cap ? it.cap : regCap(it.row, ex));
    bottom = Math.max(bottom, B.y + VH + 12 + ch);
    x += VW + FGAPX;
  }
  return bottom;
}
const THEME_NOTE = (B, sheetOnly) => "Theme: " + B.bd.theme + "; every ink is the theme's resolved token value (packages/ui/tokens at the spec head; §13), the comfortable density (16:114)" + (sheetOnly ? "." : ", the workspace behind the dialog E15-D03's merged compact chrome.");
const GEN_A11Y = [
  ["Focus order", "tabs → × → Chart type → the callout's two buttons, while shown → Baseline base fields → Bar mode → the field → Magnet → Readout → Go to Scales → Apply to → Reset General… → Reset all… → Cancel → Save → Retry, while shown (§11); each radio group one stop, arrows inside"],
  ["Names", "the dialog role=\"dialog\" aria-modal, labelled \"Chart settings\"; each tabpanel by its tab; a T2 control keeps its place with its reason bound by aria-describedby; the preview role=\"img\" with §8's name, not focusable"],
  ["Keys", "Esc innermost first: a callout's Keep, then the dirty guard (§9.2), then close; Enter in the field validates and never saves (R-2)"],
  ["Live regions", "one polite region in the dialog; after Save W-21 (or W-12), then W-13, then each build's start speak in the panel's own region (§11)"],
];
const ST_POP = () => ({ type: "candle", mode: "time", magnet: "Off", readout: "Follow", scope: "this", preview: { kind: "candles", bars: PV_LIVE, times: true } });

// ---- Board 01 general-populated (and twins 08 light, 10 high contrast) ------------------------------------------------------------------
BUILD[1] = (n) => {
  const B = place(n || 1, "SCR-031 General tab, populated: Candles, Time 1m, Crosshair, Session and the pointer to Scales, the preview, Apply to (§2, §3.1, §4.1, §2.2, §2.3, §7.2, §8)");
  const row = regRows(B.n)[0];
  const bottom = lay(B, [
    { row, draw: (x, y) => { const w = winFrame(B, row, x, y, { dialog: ST_POP() }); return "the card at CMP-043 lg (960 px) and 80 % of the window (640 px), its body scrolled to the top (" + Math.round(w.dlg.scroll) + " of " + Math.round(w.dlg.maxScroll) + " px): the four sections need " + Math.round(w.dlg.contentH) + " px and the body has " + Math.round(w.dlg.bodyH) + " (15:466 \"scrolls\"); the next frame is the same window scrolled to the end"; } },
    { row, cap: "Scroll specimen, not a §15.1 register row · CMP-043's 640 px cap (15:465–466): " + row.frame + " · scrolled to the end · the same window and state, the body scrolled to its end (CMP-043 \"scrolls\", 15:466): Bar mode's field, Crosshair (Magnet Off, Readout Follow, W-10), Session (W-9) and the pointer (W-8) with Go to Scales; a specimen of the cap beside the register frame, not a register row (the register's frame continued)",
      draw: (x, y) => { const nm = row.frame + " · scrolled to the end"; winFrame(B, row, x, y, { name: nm, dialog: Object.assign(ST_POP(), { scroll: "end", marginNotes: [[120, "Scroll specimen, not a register row: CMP-043's 640 px cap (15:465–466)"]] }) }); FRAMES.pop(); FRAME_EXTRA.push({ board: B.n, row: row.frame, name: B.b.name + " / " + norm(nm) }); return ""; } },
  ]);
  finish(B, bottom, [
    "Read left to right: the dialog over the workspace (E15-D03's chrome under the modal scrim, palette.black at opacity.scrim " + SCRIM_OP + " by value; the TopBar and StatusBar unscrimmed), then a scroll specimen, not a register row: the same dialog scrolled to the end, since CMP-043's 640 px cap makes the body scroll (15:465–466). The General tab holds four sections, Chart type · Bar mode · Crosshair · Session (W-1), the preview tile on the right (§2.1, E11-D03 §6.1).",
    "Precision and the bar-close countdown are pointed to, not hosted (R-1, §2.3); the drawing magnet is named in W-10, not hosted (§2.2). Data: BTCUSDT, tick " + A("FIX:btc.tick") + " (§0); the preview draws the recorded BTCUSDT 1m klines live (E12-D06's fixture), no caption while nothing changes.",
    "PROPOSED stamps sit right of the card, never on it: the copy deck is PROPOSED unless cited verbatim (§12); the Session row is the owner's (BQ-16, #2701).",
    THEME_NOTE(B),
  ], GEN_A11Y);
};

// ---- Board 02 chart-types ------------------------------------------------------------------------------------------------------------------
BUILD[2] = (n) => {
  const B = place(n || 2, "Chart type: the nine options with their lines, the Baseline base field, the two §3.4 callouts (AC4) (§3.1–§3.4)");
  const rows = regRows(B.n), R = (s) => rows.find((r) => regState(r) === s);
  const baseV = fmtPx(Math.round(((Math.min.apply(null, PV_LIVE.map((b) => b.l)) + Math.max.apply(null, PV_LIVE.map((b) => b.h))) / 2) / INSTR.tick) * INSTR.tick);
  const items = [
    { row: R("types/radio-list"), draw: (x, y) => { winFrame(B, R("types/radio-list"), x, y, { dialog: Object.assign(ST_POP(), { typeFocus: true }) }); return "focus on the group (one stop, arrows inside); the list fills its two columns column-major, five down the left and four down the right, so the DOM, arrow and reading orders match (§2.1, PROPOSED)"; } },
    { row: R("types/baseline-base"), draw: (x, y) => { winFrame(B, R("types/baseline-base"), x, y, { dialog: Object.assign(ST_POP(), { type: "baseline", base: "price", baseValue: baseV, preview: { kind: "baseline", bars: PV_LIVE, base: Number(baseV.replace(/,/g, "")), times: true, caption: "Changes: Chart type Candles → Baseline." } }) }); return "Baseline chosen, the base shown only while it is (§3.2): Price opens the CMP-100 field, its Decimal string snapped on blur to the tick (" + baseV + "); applied live with no refetch (§5); the preview's line is drawn as 1 px runs over the recorded closes, the base line color.candle.wick"; } },
    { row: R("types/ha-footprint"), draw: (x, y) => haSheet(B, R("types/ha-footprint"), x, y) },
    { row: R("types/ha-non-time"), draw: (x, y) => { winFrame(B, R("types/ha-non-time"), x, y, { iv: "Vol 50 BTC", dialog: Object.assign(ST_POP(), { type: "heikin-ashi", callout: "ha-nt", calloutFocus: false, mode: "volume", value: String(A("D03:default.volume")), preview: { kind: "candles", bars: PV_VOL } }) }); return "Heikin-Ashi chosen while the chart shows Volume 50 BTC bars (the TopBar's interval and the panel header read C-38's \"Vol 50 BTC\"): pending, the same callout form (W-6, §3.4; D06:567); the chart and the preview keep Candles on Volume bars (the preview's bars: the recorded 1m klines grouped into 50 BTC bars, an illustration of the held series)"; } },
  ];
  const bottom = lay(B, items);
  finish(B, bottom, [
    "Every type applies live (§5), except a Heikin-Ashi choice §3.4 holds pending: Heikin-Ashi chosen with footprint on, or on a non-time mode, waits for a callout button; arrowing to another option withdraws it and removes the callout. Footprint composes with every other type (BQ-8, PROPOSED, owner approval pending (#2701)).",
    "Heikin-Ashi is a client transform over time bars; the dialog never sends heikin_ashi in a bar_type or an interval_code (R-3, §3.3).",
    THEME_NOTE(B),
  ], GEN_A11Y);
};
function haSheet(B, row, x, y) { // the AC4 callout, then each outcome (§3.4): crops of the Chart type section
  const f = sheetFrame(B, row, x, y), cw = COLW + 32;
  const part = (st, cx, cy, label) => {
    const rows = sectionRows(Object.assign(ST_POP(), st)), pick = sectionOf(rows, WD["W-1"][0]), h = rowsH(pick) + 28;
    const c0 = crop(f, cx, cy, cw, h, label);
    drawRowsInto(f, pick, c0.x, c0.y, () => true);
    return c0.bottom;
  };
  const b1 = part({ type: "heikin-ashi", callout: "ha-fp", calloutFocus: true }, x + 12, y + 16, "1 · Heikin-Ashi chosen with footprint on: pending; the callout appears under the group without moving focus and is announced once; Tab reaches its two buttons; Esc chooses " + WD["W-5"][1] + " (§3.4, D02:34). Here focus is on " + WD["W-5"][1] + ", the safe default.");
  part({ type: "heikin-ashi" }, x + 12 + cw + 16, y + 16, "2 · Outcome: \"" + WD["W-5"][2] + "\" pressed: Heikin-Ashi applies, footprint is turned off on CMP-222 (the chart toolbar, not this section); the callout goes");
  const b3 = part({ type: "candle" }, x + 12 + cw + 16, y + 16 + 400, "3 · Outcome: \"" + WD["W-5"][1] + "\" pressed (or Esc): the type kept, footprint stays on (CMP-222); the callout goes");
  if (b1 > y + VH || b3 > y + VH) warn("sheet", "ha-footprint overruns its frame");
  const sk = K(); // §3.4's PROPOSED stamp, in the sheet's free space under crop 1, outside every crop (R1 F-1)
  const st4 = OWNER + " · §3.4 (BQ-8): the pending Heikin-Ashi choice, its callout and both outcomes", sh4 = Math.ceil(estLines(st4, Math.floor(cw * 0.85), TYP(CAP).size, false, 400) * th1(CAP));
  box(f, x + 12 - 4, b1 + 24 - 2, cw + 8, sh4 + 4, { fill: "color.surface.raised", r: "radius.xs", name: "stamp-chip", k: sk });
  txt(f, st4, x + 12, b1 + 24, cw, { type: CAP, col: PRI, k: sk, name: "proposed-stamp", ml: true });
  return "a specimen sheet (the State names three states): the callout, then each outcome, 1:1 crops of the Chart type section; either choice leaves a valid state (AC4); the words are D02:279's, verbatim";
}

// ---- Board 03 bar-modes ------------------------------------------------------------------------------------------------------------------
BUILD[3] = (n) => {
  const B = place(n || 3, "Bar mode: the Volume field, the estimate states, \"Needs a build\", the two T2 options (§4.1, §5, §10.2)");
  const rows = regRows(B.n), R = (s) => rows.find((r) => regState(r) === s);
  const vol = String(A("D03:default.volume")), pv = { kind: "sample", bars: PV_RENKO, label: WD["W-19"][0] };
  const bottom = lay(B, [
    { row: R("modes/volume-field"), draw: (x, y) => { winFrame(B, R("modes/volume-field"), x, y, { dialog: Object.assign(ST_POP(), { mode: "volume", value: vol, est: "C-16", scroll: "bar", preview: pv }) }); return "Volume 50 (D3-11's first-use default), valid: the label \"" + MODE("volume").label + "\", the unit the visible suffix BTC and part of the accessible name \"Volume per bar, BTC\" (D03:336); C-3 the mode's line; W-7 the static caption on the group; the estimate line C-16 (requested " + A("D03:estimate-delay") + " ms after the last key); the body scrolled to Bar mode"; } },
    { row: R("modes/estimate-states"), draw: (x, y) => estSheet(B, R("modes/estimate-states"), x, y) },
    { row: R("modes/needs-build"), draw: (x, y) => { winFrame(B, R("modes/needs-build"), x, y, { dialog: Object.assign(ST_POP(), { modeState: "needs", scroll: "bar", preview: pv }) }); return "C-30's tag on each option not built for the loaded window (D03:215); the tag is a word, never colour alone"; } },
    { row: R("modes/no-prints"), draw: (x, y) => { winFrame(B, R("modes/no-prints"), x, y, { dialog: Object.assign(ST_POP(), { modeState: "noprints", scroll: "bar", preview: pv }) }); return "no recorded prints: every non-time option T2, focusable, aria-disabled, its reason C-24 as text bound by aria-describedby; an arrow moves focus onto one without checking it (§10.2)"; } },
    { row: R("modes/lot-unknown"), draw: (x, y) => { winFrame(B, R("modes/lot-unknown"), x, y, { dialog: Object.assign(ST_POP(), { modeState: "lot", scroll: "bar", preview: pv }) }); return "lot size not known: Volume and Delta T2 with C-25 (§10.2); with the flag or the Renko switch off an option is absent, never refused (D03:157)"; } },
  ]);
  finish(B, bottom, [
    "Only Save starts a build (R-2): a bar mode or parameter change is marked by W-7 on the group, C-30 per option and the estimate line; Enter in the field validates and never saves. Labels, units, defaults, bounds and messages are D03's, verbatim (R-4, §4.1); the one intended difference: no Recent row in the dialog (D03:237).",
    "Order Time, Tick, Volume, Range, Delta, Renko (D03:62); " + A("COUNT:modes") + " modes; one field, for the selected mode only (D02:247).",
    THEME_NOTE(B),
  ], GEN_A11Y);
};
function estSheet(B, row, x, y) { // C-15 … C-20 under the field (§5; D03:245)
  const f = sheetFrame(B, row, x, y), cw = COLW + 32;
  const specs = [
    ["volume", "C-15", "1 · Estimating: requested " + A("D03:estimate-delay") + " ms after the last key"],
    ["volume", "C-16", "2 · Estimated: the build window and its size"],
    ["volume", "C-17", "3 · Built: no build needed"],
    ["volume", "C-18", "4 · The estimate failed: the commit proceeds (D-2)"],
    ["tick", "C-19", "5 · Tick or Volume over 250,000 bars: Save refused"],
    ["delta", "C-20", "6 · Delta: a bound, a warning"],
  ];
  specs.forEach(([m, est, label], i) => {
    const rows = sectionRows(Object.assign(ST_POP(), { mode: m, value: String(MODE(m).def), est })), pick = rows.filter((r) => r.id === "field" || r.id === "est");
    const cx = x + 12 + (i % 2) * (cw + 16), cy = y + 24 + Math.floor(i / 2) * 200;
    const c0 = crop(f, cx, cy, cw, rowsH(pick) + 28, label);
    drawRowsInto(f, pick, c0.x, c0.y, () => true);
  });
  return "a specimen sheet: six 1:1 crops of the field with its estimate line; the estimate is never announced while typing (D03:250); the estimate text color.text.secondary; C-19 with the ✕ in color.status.danger.strong and the field's invalid boundary (sends nothing, Enter refused), C-20 with the ⚠ in color.status.warning.strong (commits) (D03:141, :168)";
}

// ---- Board 04 validation (and twin 09 light) ---------------------------------------------------------------------------------------------
const SPECIMENS = [ // §4.2's rows, in order: mode, typed value, the message id, label, field state
  ["tick", "50", "C-7", "Tick 50: ✕ + the message; aria-invalid"],
  ["volume", "0", "C-8", "Volume 0: ✕ + the message"],
  ["volume", "0.5", "C-8", "Volume 0.5: ✕ + the message (whole numbers only)"],
  ["delta", "0", "C-9", "Delta 0: ✕ + the message"],
  ["range", "1", "C-11", "Range 1: ✕ + the message"],
  ["renko", "1", "C-11", "Renko 1: ✕ + the message"],
  ["renko", "atr:14", "held", "Renko atr:14: the held sentence; nothing is sent (D03 board 05's \"Renko, atr: typed\" form)", true],
  ["tick", "123456789012345678901234", "C-7", "a pasted value of more than " + A("param.max-len") + " characters: the field keeps the first " + A("param.max-len") + " (maxlength), then the mode's bound message"],
  ["volume", "1000000000001", "C-10", "Volume over the ceiling: ✕ + the message; the raw typed value, ungrouped"],
  ["tick", "50", "C-7", "Save pressed with Tick 50: nothing saves; focus moves to the field and C-7 is announced once (§9.3)", true],
];
BUILD[4] = (n) => {
  const B = place(n || 4, "Validation specimens: §4.2's rows, C-7 … C-12 verbatim (§4.1, §4.2, §9.3)");
  const row = regRows(B.n)[0];
  const bottom = lay(B, [{ row, draw: (x, y) => {
    const f = sheetFrame(B, row, x, y), cw = COLW + 32;
    SPECIMENS.forEach(([m, v, msg, label, foc], i) => {
      const st = Object.assign(ST_POP(), { mode: m, value: v, fieldFocus: !!foc });
      if (msg === "held") st.held = true; else st.invalid = msg;
      const rows = sectionRows(st), pick = rows.filter((r) => r.id === "field" || r.id === "msg");
      const cx = x + 12 + (i % 2) * (cw + 16), cy = y + 16 + Math.floor(i / 2) * 154;
      const c0 = crop(f, cx, cy, cw, rowsH(pick) + 28, (i + 1) + " · " + label);
      drawRowsInto(f, pick, c0.x, c0.y, () => true);
    });
    return "a specimen sheet: ten 1:1 crops of the one field; glyph + text, aria-invalid, aria-describedby, announced politely once (15:439); color.status.danger.strong marks only the ✕ and the invalid boundary, the message color.text.primary (§13); each mode keeps the value typed for it while the dialog is open (PROPOSED); specimen 7 is D03 board 05's \"Renko, atr: typed\" frame (D3-6, D03:171): atr:14 typed in the one field with the caret, the invalid boundary, ✕ and C-12 in the message line, aria-invalid, Enter keeps focus and sends nothing; never a read-only value; D03's \"Held for R2\" anatomy stays on D03 board 05 only";
  } }]);
  finish(B, bottom, [
    "Messages are D03's deck, verbatim (C-7 … C-12; {BTC} and {1} filled for BTCUSDT, whose floor is " + A("FIX:btc.floor") + " BTC while only whole numbers parse, qty step " + A("FIX:btc.qty-step") + "). Every field takes at most " + A("param.max-len") + " characters (22:3999). The backend re-validates; a server refusal shows as the field's message, never its developer text (D03:81–83).",
    "Lot size unknown (C-25) and no recorded prints (C-24) are option states, not field messages (board 03); precision has no free entry and P&F is not offered, so neither has a message (D05-C13).",
    THEME_NOTE(B, true),
  ], GEN_A11Y);
};

// ---- Board 05 all-panels -----------------------------------------------------------------------------------------------------------------
BUILD[5] = (n) => {
  const B = place(n || 5, "All panels: the partial-apply list, its outcome in each panel's strip, the as-new-default notice (§7.2–§7.4, AC3)");
  const rows = regRows(B.n), R = (s) => rows.find((r) => regState(r) === s);
  const vol = String(A("D03:default.volume"));
  const bottom = lay(B, [
    { row: R("scope/partial-apply"), draw: (x, y) => { winFrame(B, R("scope/partial-apply"), x, y, { dialog: Object.assign(ST_POP(), { mode: "volume", value: vol, est: "C-16", scope: "all", partial: true, scroll: "bar", preview: { kind: "sample", bars: PV_RENKO, label: WD["W-19"][0] },
      marginNotes: [[150, "A panel whose lot size is not known is listed unchanged the same way, with C-25: \"" + C25_LINE + "\" (§7.3; none in this workspace)"]] }) }); return "All panels with a bar-mode change, before Save: 3 of 4 as §7.3's examples, every chart panel named, changed first, the unchanged one with its reason (C-24; C-25's line form in the margin note: D03's words reused for a panel); Volume applies each panel's own per-symbol value (D03:56); nothing blocks the whole apply (R-6); the panel names are illustrative (§0)"; } },
    { row: R("scope/outcome"), draw: (x, y) => {
      const w = winFrame(B, R("scope/outcome"), x, y, { panels: "four" });
      for (const pp of w.panels) {
        if (pp.p.reason) strip(w.f, pp.q, w.D, "Bar mode unchanged · " + CD[pp.p.reason], ["Dismiss"], { notice: true });
        else strip(w.f, pp.q, w.D, "Building " + pp.p.to + "...", ["Cancel"], { busy: true });
      }
      const q0 = w.panels[0].q;
      fnote(w.f, q0.x + SP3, q0.y + w.D.ctl + 40, Math.min(420, (q0.plotW || q0.w) - 2 * SP3), "Announced once, politely, in the invoking panel's region: \"" + WD["W-12"][0] + "\" (W-12, §11). PROPOSED · §7.3 the partial-apply rule (BQ-11).");
      return "after Save: each changed panel runs its build strip (D02 §7: \"Building Volume 50 BTC...\" with Cancel, D02:269's form) and each unchanged panel shows the outcome notice W-24 with Dismiss, no timer, Esc never dismisses (D02 D-7); the dialog is closed";
    } },
    { row: R("scope/default-notice"), draw: (x, y) => {
      const w = winFrame(B, R("scope/default-notice"), x, y, { iv: "Vol 50 BTC" });
      const q = w.panels[0].q;
      strip(w.f, q, w.D, WD["W-13"][0], [WD["W-13"][1], WD["W-13"][2]], { notice: true });
      fnote(w.f, q.x + SP3, q.y + w.D.ctl + 40, Math.min(560, (q.plotW || q.w) - 2 * SP3), OWNER + " · §7.4 (BQ-12): no modal. W-13 is posted once the Save's build on this panel ended (built, cancelled or failed), never while it runs; with no build it is posted at once. Undo sends one PATCH /me/preferences restoring each leaf it wrote (null where the leaf was not overridden).");
      fnote(w.f, q.x + SP3, q.y + w.D.ctl + 120, Math.min(560, (q.plotW || q.w) - 2 * SP3), "Before Save, As new default's helper named the keys: \"" + WD["W-14"][0] + "\" (W-14) and E11-D03:858's interim sentence, so a misclick cannot silently reconfigure every future chart (T Sec).");
      return "As new default saved: the panel's status strip shows the outcome notice W-13 with Undo and Dismiss (D02 D-7's form: no timer, Esc never dismisses); the build has ended, so the TopBar and the panel header read Vol 50 BTC (C-38); W-14 is the scope helper shown before Save, so here it is quoted in the annotation, not drawn as UI";
    } },
  ]);
  finish(B, bottom, [
    "§7.3 (PROPOSED; RULED BQ-11): Tick, Range and Renko apply the same number everywhere; Volume and Delta apply the mode with each panel's own per-symbol value. Sync groups never carry chart type or bar mode (22:20195): All panels is an explicit fan-out.",
    "The panels: BTCUSDT 1m, 15m and 1h (changed) and ETHFIUSDT 1m (no recorded prints), illustrative (§0), 3 of 4 as §7.3's examples and the register's State; the lot-size reason C-25 is shown as the line such a panel reads; no account data (R-7).",
    THEME_NOTE(B),
  ], GEN_A11Y);
};

// ---- Board 06 preview --------------------------------------------------------------------------------------------------------------------
BUILD[6] = (n) => {
  const B = place(n || 6, "The preview tile: live, cached, the Renko sample with its text (AC2), empty, errored (§8; E11-D03 D12)");
  const rows = regRows(B.n), R = (s) => rows.find((r) => regState(r) === s);
  const W20 = "Changes: Bar mode Time 1m → Renko 30 ticks per brick (rebuilds on Save). Chart type unchanged.";
  const pv = (s, st, ex) => ({ row: R(s), draw: (x, y) => { winFrame(B, R(s), x, y, { dialog: Object.assign(ST_POP(), st) }); return ex; } });
  const bottom = lay(B, [
    pv("preview/live", { type: "bar", preview: { kind: "ohlc", bars: PV_LIVE, times: true, caption: "Changes: Chart type Candles → Bars (OHLC)." } }, "a chart type, live: drawn from this chart's store in the same frame as the change, no fetch, no label; name \"Preview: BTCUSDT, Time 1 minute, bars (OHLC)\""),
    pv("preview/cached", { value: "5m", preview: { kind: "candles", bars: PV_5M, times: true, caption: "Changes: Bar mode Time 1m → Time 5m. Chart type unchanged." } }, "a bar mode the client holds (D02:88): Time 5m from the loaded 1m bars, live, no label; name \"Preview: BTCUSDT, Time 5 minutes, candles\""),
    pv("preview/renko-sample", { mode: "renko", value: String(A("D03:default.renko")), est: "C-16", preview: { kind: "sample", bars: PV_RENKO, label: WD["W-19"][0], caption: W20, stamp: "§8 W-19 and the name (D03-CR-3)" } }, "Renko 30, not built: CMP-228's sampleData, bundled recorded, redacted bars (here the recorded BTCUSDT 1m closes in 30-tick bricks), labelled W-19; the visible caption W-20 reuses C-6 as the mode's description (\"" + CD["C-6"] + "\", D03:191), so the preview is never the only disclosure (AC2); name \"Preview: BTCUSDT, Renko 30 ticks per brick, candles; sample bars\" (D03-CR-3, PROPOSED)"),
    pv("preview/empty", { preview: { kind: "empty" } }, "no bars loaded: E11-D03's empty state verbatim (E11-D03:279), the CMP-029 silhouette at opacity.muted; the fields stay enabled"),
    pv("preview/error", { preview: { kind: "error" } }, "chart error: E11-D03's errored state verbatim (E11-D03:280), the color.status.danger.strong glyph; the fields stay enabled"),
  ]);
  finish(B, bottom, [
    "One tile for the dialog (E11-D03:214), never a spinner and never a fetch (T Perf). The bars are the recorded BTCUSDT 1m klines E12-D06 renders (packages/fixtures, 2026-10-05), at tick " + A("FIX:btc.tick") + " (Auto precision, §6).",
    "C-6 for the caption: \"" + CD["C-6"] + "\" (D03:191).",
    THEME_NOTE(B),
  ], GEN_A11Y);
};

// ---- Board 07 chrome-and-roles -----------------------------------------------------------------------------------------------------------
const CHG = () => Object.assign(ST_POP(), { type: "hollow", mode: "volume", value: String(A("D03:default.volume")), magnet: "Strong", est: "C-16",
  preview: { kind: "hollow", bars: PV_VOL_HOLLOW, label: WD["W-19"][0], caption: "Changes: Bar mode Time 1m → Volume 50 BTC (rebuilds on Save). Chart type Candles → Hollow candles." } }); // the pending changes the resets and the guard name (the type live, the mode on Save: sample bars)
const RESET_GEN = [
  { t: "General settings for this panel return to their defaults:" },
  { t: "Chart type: Hollow candles → Candles", dx: 12, after: 2 }, { t: "Bar mode: Volume 50 BTC → Time 1m", dx: 12, after: 2 }, { t: "Magnet: Strong → Off", dx: 12 },
  { t: WD["W-15"][1] },
];
const RESET_ALL = [
  { t: "All chart settings for this panel return to their defaults:" },
  { t: "General", type: LBL, after: 2 }, { t: "Chart type: Hollow candles → Candles", dx: 12, after: 2 }, { t: "Bar mode: Volume 50 BTC → Time 1m", dx: 12, after: 2 }, { t: "Magnet: Strong → Off", dx: 12 },
  { t: "Scales", type: LBL, after: 2 }, { t: "Scale mode: Logarithmic → Linear", dx: 12 },
  { t: WD["W-16"][1] },
];
BUILD[7] = (n) => {
  const B = place(n || 7, "Chrome and roles: the two Reset confirms (AC5), the dirty guard, saving and failed, Viewer and view-as, the keyboard storyboard (§9, §10, §11)");
  const rows = regRows(B.n), R = (s) => rows.find((r) => regState(r) === s);
  const over = (s, st, card, post) => ({ row: R(s), draw: (x, y) => { const w = winFrame(B, R(s), x, y, { dialog: st }); scrim(w.f, x, y + TOPBAR_H, VW, VH - TOPBAR_H - STATUSBAR_H); const cc = card(w.f, x, y);
    if (post) withStamps(w.f, [{ x: w.dlg.dx + DLG_W + 8, w: VW - STRIP_W - 16 - DLG_W - (w.dlg.dx - x) }], y + post[0], y + VH - STATUSBAR_H - 8, () => stamp(y + post[0], post[1])); // r2 ruling 3: the stamp drawn over the second scrim, in the right margin
    return cc; } });
  const RESET_STAMP = "§9.1 the confirm body: PROPOSED copy row, E12-D05 copy deck (boards PR); modelled on E11-D03:273";
  const bottom = lay(B, [
    over("reset/general", Object.assign(CHG(), { marginNotes: [[560, "After Reset: focus back on Reset General…; announced \"" + WD["W-25"][0] + "\" (W-25)"]] }), (f, x, y) => {
      confirmCard(f, x, y, WD["W-15"][0], RESET_GEN, [{ t: WD["W-15"][2], name: "confirm-reset" }, { t: WD["W-15"][3], focus: true, name: "confirm-keep" }]);
      return "CMP-044 standard in D11's form over the dialog (a second scrim): the title names General, the body lists every field of General that changes, old → new, then \"Rebuilds the chart on Save.\" (the bar mode changes) and the scope clause \"for this panel\"; the body is modelled on E11-D03:273 and is a PROPOSED copy row of the E12-D05 copy deck (boards PR), stamped; focus starts on Keep settings (15:478); Keep settings leaves every field untouched (AC5)";
    }, [300, RESET_STAMP]),
    over("reset/all", Object.assign(CHG(), { marginNotes: [[560, "After Reset: focus back on Reset all…; announced \"" + WD["W-25"][1] + "\" (W-25)"]] }), (f, x, y) => {
      confirmCard(f, x, y, WD["W-16"][0], RESET_ALL, [{ t: WD["W-16"][2], name: "confirm-reset" }, { t: WD["W-16"][3], focus: true, name: "confirm-keep" }]);
      return "the global confirm: every changed field of every tab, old → new, grouped by tab (Scales' scale mode from E11-D03 §6.2), \"Rebuilds the chart on Save.\" and the scope clause; under As new default the defaults are the built-in ones (PROPOSED); the body is modelled on E11-D03:273 and is a PROPOSED copy row of the E12-D05 copy deck (boards PR), stamped";
    }, [300, RESET_STAMP]),
    over("chrome/dirty-guard", Object.assign(CHG(), { tabChanged: true }), (f, x, y) => {
      confirmCard(f, x, y, WD["W-17"][0], [], [{ t: WD["W-17"][1], name: "guard-discard" }, { t: WD["W-17"][2], focus: true, name: "guard-keep" }], { w: 460 });
      return "Esc with unsaved changes (or Cancel, ×, the scrim): E15-D02's prompt verbatim (E15-D02:507), Keep editing focused (E05-FO option (a)); the changed tab's accessible name adds \"changed\" (W-22, PROPOSED)";
    }),
    { row: R("chrome/saving"), draw: (x, y) => { winFrame(B, R("chrome/saving"), x, y, { dialog: Object.assign(CHG(), { footer: { saving: true } }) }); return "Save busy: CMP-001's loading state on Save, aria-busy, still focusable (D03:281–284); Save only updates the layout's working copy (§7.1)"; } },
    { row: R("chrome/save-failed"), draw: (x, y) => { winFrame(B, R("chrome/save-failed"), x, y, { dialog: Object.assign(CHG(), { scope: "default", footer: { failed: true } }) }); return "As new default's PATCH /me/preferences failed: the dialog stays with W-18 (C-41's form) and Retry, the last stop of the tab order; every change stays here (§9.3, D05-G4)"; } },
    { row: R("roles/viewer"), draw: (x, y) => { winFrame(B, R("roles/viewer"), x, y, { role: "viewer", dialog: Object.assign(ST_POP(), { role: "viewer", scroll: "bar" }) }); return "Viewer (E11-D09 C-14, PROPOSED): chart type and crosshair apply live as view state; Save T2 \"" + REASON_SAVE + "\", As new default T2 \"" + REASON_SET + "\"; the bar-mode group one notice W-23 with its radios T2 pointing at it; Reset General… and Reset all… T2 (PROPOSED); each T2 keeps its place, the lock leading, the label color.text.tertiary"; } },
    { row: R("roles/view-as"), draw: (x, y) => { winFrame(B, R("roles/view-as"), x, y, { role: "viewas", dialog: Object.assign(ST_POP(), { role: "viewas", scroll: "bar" }) }); return "viewing as: W-26 checked first on Save, the As new default segment, the bar-mode radios and both Resets; chart type and crosshair stay live as view state (PROPOSED); SCR-124's banner unscrimmed, the TopBar's FLATTEN ALL… / CANCEL ALL… / FREEZE… T2 (E15-D03's view-as shell)"; } },
    { row: R("keyboard/storyboard"), draw: (x, y) => kbSheet(B, R("keyboard/storyboard"), x, y) },
  ]);
  finish(B, bottom, [
    "A confirmed Reset sets the fields in the dialog only, live like any other change, so it never commits on its own; Save commits it (R-2). Defaults are the user's effective settings (22:9667–9669), else the built-in ones (22:11939–11941).",
    "Roles (§10.1): Owner and Manager full; Demo and Live identical (D03:453); no account, key or order data anywhere (R-7). The workspace behind is E15-D03's role shells (42-d03): the Viewer's T2 cluster and Kill switch, view-as's SCR-124 banner.",
    THEME_NOTE(B),
  ], GEN_A11Y);
};
function kbSheet(B, row, x, y) { // §11's two walks, step by step: 1:1 crops of the part each step lands on, the focus ring where focus is
  const f = sheetFrame(B, row, x, y), cw = COLW + 32, D = DZ("comfortable");
  const pick = (st, ids) => sectionRows(Object.assign(ST_POP(), st)).filter((r) => ids.indexOf(r.id) >= 0);
  const footer = (focus) => (c0) => { btnRowR(f, c0.x + c0.w, c0.y, [{ t: "Reset General…", focus: focus === "resetG" }, { t: "Reset all…" }, { t: "Cancel" }, { t: "Save", kind: "primary", focus: focus === "save" }], c0.k); return c0.y + D.ctl; };
  const conf = (focus) => (c0) => { txt(f, WD["W-15"][0], c0.x, c0.y, c0.w, { type: H_SM, col: PRI, k: c0.k, name: "confirm-title" }); txt(f, WD["W-15"][1], c0.x, c0.y + 24, 240, { type: BODY, col: PRI, k: c0.k, name: "confirm-body" }); btnRowR(f, c0.x + c0.w, c0.y + 24, [{ t: WD["W-15"][2], focus: focus === "reset" }, { t: WD["W-15"][3], focus: focus === "keep" }], c0.k); return c0.y + 24 + D.ctl; };
  const rowsOf = (rs) => (c0) => drawRowsInto(f, rs, c0.x, c0.y, () => true);
  const steps = [
    ["Walk 1 · 1 — from the tabs, Tab: Chart type (one stop; arrows inside)", rowsOf(pick({ typeFocus: true }, ["type"]).slice(0, 1))],
    ["2 — Tab to Bar mode, → → to Volume: its field appears; nothing is committed", rowsOf(pick({ mode: "volume", value: "50", modeFocus: true }, ["radios", "field"]))],
    ["3 — Tab to the field, type 0, Enter: C-8 is spoken once", rowsOf(pick({ mode: "volume", value: "0", invalid: "C-8", fieldFocus: true }, ["field", "msg"]))],
    ["4 — replace it with 75", rowsOf(pick({ mode: "volume", value: "75", fieldFocus: true }, ["field"]))],
    ["5 — Tab … to Save, Enter", footer("save")],
    ["6 — the dialog closes, focus on the invoker; the chart says \"Building the chart as Volume 75 BTC bars. Escape cancels.\" (D02:284)", (c0) => { box(f, c0.x, c0.y, c0.w, D.ctl, { fill: "color.surface.raised", name: "strip", k: c0.k }); txt(f, "Building Volume 75 BTC...", c0.x + 12, c0.y + (D.ctl - th1(CAP)) / 2, 300, { type: CAP, col: PRI, k: c0.k, name: "strip-text" }); return c0.y + D.ctl; }],
    ["Walk 2 · 1 — Tab to Reset General…, Enter", footer("resetG")],
    ["2 — the confirm opens on Keep settings", conf("keep")],
    ["3 — Tab to Reset, Enter", conf("reset")],
    ["4 — focus returns to Reset General…; \"" + WD["W-25"][0] + "\" is spoken (W-25)", footer("resetG")],
    ["Esc in the confirm instead closes it and resets nothing; focus returns to Reset General…", footer("resetG")],
  ];
  const H = [80, 104, 84, 64, 64, 64, 64, 84, 84, 64, 64];
  steps.forEach(([label, draw], i) => {
    const cx = x + 12 + (i % 2) * (cw + 16), cy = y + 10 + Math.floor(i / 2) * 130;
    const c0 = crop(f, cx, cy, cw, H[i], label);
    const b = draw(c0);
    if (b > c0.bottom - 8) warn("sheet", "keyboard crop " + (i + 1) + " overruns by " + Math.ceil(b - c0.bottom + 8));
  });
  return "a specimen sheet: §11's two walks, each step a 1:1 crop of the part focus lands on, the color.focus.ring outside the control with an offset (never on the Save fill, §13)";
}
// ---------------------------------------------------------------- twins (spec §0: 08 = 01 in light, 09 = 04 in light, 10 = 01 in high contrast) ----
// A twin reuses its dark board's builder: the builder takes its board number, and place() sets TH from the twin's BOARDS row ("light").
// High contrast (#202, carried for #241): place() knows dark and light only, and col() reads TV's dark column for every theme but light, so board 10 is
// built with each TV row's dark column holding its high-contrast value (restored afterwards, also on a throw), then every record and
// queued binding of the board is re-stamped theme "high-contrast" (a run binds it only while the catalog's high-contrast theme is active).
function withHC(fn) {
  const saved = Object.keys(TV).map((k) => [k, TV[k][0]]);
  for (const k of Object.keys(TV)) TV[k][0] = TV[k][2];
  try { return fn(); } finally { for (const [k, v] of saved) TV[k][0] = v; }
}
for (const bd of BOARDS) {
  if (!bd.twin || typeof BUILD[bd.n] === "function" || typeof BUILD[bd.twin] !== "function") continue;
  const dark = BUILD[bd.twin];
  if (bd.theme !== "high-contrast") { BUILD[bd.n] = () => dark(bd.n); continue; }
  BUILD[bd.n] = () => {
    withHC(() => dark(bd.n));
    if (!REC) return;
    for (const s of REC.shapes) { // the meta's theme (and the board's) → high-contrast; a later pd op, so the replay writes it last
      let m = null; try { m = JSON.parse(s.getPluginData(TAG + ":meta") || "{}"); } catch (e) { m = null; }
      if (m && m.theme === "dark") { m.theme = "high-contrast"; s.setPluginData(TAG + ":meta", JSON.stringify(m)); }
    }
    if (REC.binds) for (const q of REC.binds.values()) if (q.theme === "dark") q.theme = "high-contrast";
  };
}


// ---------------------------------------------------------------- record, parts plan, budget guard (E15-D02 r4's) ------------
// Nothing is touched until the guard has passed. Board n is recorded FIRST, on the script's fresh data (place → BUILD[n] →
// finish, records in place of shapes); then each other drawn board is recorded for counting only (the page totals and the PART = 0
// plan; their warnings are dropped here, each board reports its own; r4: a NOT_DRAWN board is neither recorded nor counted).
const SEQ0 = blockSeq; // the block-id counter here (0): every record starts from it, as one call would
function recordBoard(n, withOps) {
  blockSeq = SEQ0; BQ.clear(); BVQ.length = 0; TH = "dark"; SC = 1; STALE = false; WSAFE = false; WMEAS = false;
  for (const key of Object.keys(HEADER_OVER)) delete HEADER_OVER[key]; // r2: each record starts with no header overflow, so the result reports board n's alone
  REC = { n, ops: withOps ? [] : null, shapes: [], binds: null, bvq: null };
  try {
    BUILD[n]();
    return REC;
  } finally { REC = null; }
}
const segsOf = (r) => 0; // a record is a text, a rect or a board: no path, so no path segment (a path kind would count its commands here)
function planOf(r) { // the creation sequence cut into nk near-equal contiguous runs; one call when it fits SHAPE_BUDGET
  const shapes = r.shapes.length, segments = r.shapes.reduce((a, s) => a + segsOf(s), 0);
  const nk = shapes > SHAPE_BUDGET ? Math.ceil(shapes / PART_SHAPES) : 1, parts = [];
  for (let i = 0, from = 0; i < nk; i++) {
    const size = Math.floor(shapes / nk) + (i < shapes % nk ? 1 : 0), to = from + size - 1;
    parts.push({ part: i + 1, from, to, shapes: size, segments: r.shapes.slice(from, to + 1).reduce((a, s) => a + segsOf(s), 0) });
    from = to + 1;
  }
  return { board: r.n, shapes, segments, parts };
}
const N0 = ONLY[0], BD0 = BOARDS.find((bd) => bd.n === N0);
// r1 (#319): boards whose builder is not written yet (UNBUILT) are refused before anything is touched and left out of the plan
const UNBUILT = BOARDS.filter((bd) => !NOT_DRAWN.includes(bd.n) && typeof BUILD[bd.n] !== "function").map((bd) => bd.n);
if (UNBUILT.includes(N0)) return { abort: "not-built", version: VERSION, board: N0, note: "board " + pad2(N0) + " " + BD0.slug + " has no builder in " + VERSION + " yet; nothing was touched" };
let RECN = null;
try { RECN = recordBoard(N0, true); } catch (e) {
  return { abort: "build", version: VERSION, board: N0, error: String(e && e.message || e), stack: e && e.stack ? String(e.stack).split("\n").slice(0, 4).join(" / ") : null, warnings, note: "board " + pad2(N0) + " did not lay out; nothing was touched" };
}
const builtN = built.splice(0), framesN = FRAMES.splice(0), layoutN = LAYOUT.splice(0), warnN = warnings.length, headerN = Object.assign({}, HEADER_OVER); // board n's own, before the counting records
const PLANS = [];
for (const bd of BOARDS) {
  if (bd.n === N0) { PLANS.push(planOf(RECN)); continue; }
  if (NOT_DRAWN.includes(bd.n) || UNBUILT.includes(bd.n)) continue; // not drawn (NOT_DRAWN) or no builder yet (UNBUILT): not in the plan or the page totals
  let r = null;
  try { r = recordBoard(bd.n, false); } catch (e) { throw new Error("parts plan: board " + pad2(bd.n) + " did not lay out (" + String(e && e.message || e) + "), so the page totals are unknown; nothing was touched"); }
  PLANS.push(planOf(r));
}
built.length = 0; FRAMES.length = 0; LAYOUT.length = 0; warnings.length = warnN;
built.push(...builtN); FRAMES.push(...framesN); LAYOUT.push(...layoutN);
for (const key of Object.keys(HEADER_OVER)) delete HEADER_OVER[key];
Object.assign(HEADER_OVER, headerN); // the result's headerOverflow: board n's headers only (r2; the other records counted shapes only)
const PLAN = PLANS.find((p) => p.board === N0), KP = PLAN.parts.length, PARTED = KP > 1;
const BUDGET = { shapes: SHAPE_BUDGET, segments: SEG_BUDGET, pageSegments: PAGE_SEG_BUDGET, partShapes: PART_SHAPES };
const PAGE_PLAN = { boards: PLANS.length, shapes: PLANS.reduce((a, p) => a + p.shapes, 0), segments: PLANS.reduce((a, p) => a + p.segments, 0), calls: PLANS.reduce((a, p) => a + p.parts.length, 0) };
const planRow = (p) => ({ board: p.board, shapes: p.shapes, segments: p.segments, parts: p.parts.length, calls: p.parts.map((q) => q.shapes + " [" + q.segments + "]").join(" + ") });
if (PART === 0) {
  const over = [];
  for (const p of PLANS) for (const q of p.parts) if (q.shapes > SHAPE_BUDGET || q.segments > SEG_BUDGET) over.push(pad2(p.board) + (p.parts.length > 1 ? " part " + q.part : "") + ": " + q.shapes + " shapes [" + q.segments + "]");
  return { version: VERSION, part: 0, board: N0, budget: BUDGET, thisBoard: Object.assign(planRow(PLAN), { driver: KP > 1 ? "ONLY = [" + N0 + "], PART = 1.." + KP + ", one call each, in order; the relayout after PART = " + KP : "ONLY = [" + N0 + "], PART = null: one call" }), plan: PLANS.map(planRow), page: PAGE_PLAN, notDrawn: NOT_DRAWN.map((n) => pad2(n) + " " + BOARDS.find((bd) => bd.n === n).slug + ": not drawn"), unbuilt: UNBUILT.map((n) => pad2(n) + " " + BOARDS.find((bd) => bd.n === n).slug), overBudget: over, warnings, note: "the parts plan only (shapes per call, the board frame counted in part 1; path segments in brackets): nothing was touched" };
}
// the pre-run guard: it throws, and nothing is touched, when this call or the page would pass the budget
if (PARTED && PART === null) throw new Error("board " + pad2(N0) + " creates " + PLAN.shapes + " shapes, over the " + SHAPE_BUDGET + "-shape budget of one plugin call: draw it in parts, ONLY = [" + N0 + "] with PART = 1.." + KP + " (one call each, in order); nothing was touched");
if (PART !== null && PART > KP) throw new Error("board " + pad2(N0) + " has " + KP + " part(s) (" + planRow(PLAN).calls + " shapes): there is no PART " + PART + "; nothing was touched");
const PK = PARTED ? PART : null; // the part this call draws; null = the whole board in one call (PART 1 of a one-part board is that call)
const CALL = PK ? PLAN.parts[PK - 1] : { part: null, from: 0, to: PLAN.shapes - 1, shapes: PLAN.shapes, segments: PLAN.segments };
if (CALL.shapes > SHAPE_BUDGET || CALL.segments > SEG_BUDGET || PAGE_PLAN.segments > PAGE_SEG_BUDGET) {
  throw new Error("budget: board " + pad2(N0) + (PK ? " part " + PK : "") + " would create " + CALL.shapes + " shapes and " + CALL.segments + " path segments in one call (at most " + SHAPE_BUDGET + " and " + SEG_BUDGET + "), the page would hold " + PAGE_PLAN.segments + " path segments (at most " + PAGE_SEG_BUDGET + "); nothing was touched");
}

// ---------------------------------------------------------------- page (found by name then PAGE_ID, as E29-D02's guard) ------------
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
if (page) {
  const c = classifyPage(page);
  if (c.unknown || c.foreign > 0) return { abort: "pinned-page-holds-foreign-content", page: c, note: "PAGE_ID points at a page with foreign content; nothing was touched" };
}
if (!page && named.length) {
  const clean = named.filter((c) => !c.unknown && c.foreign === 0);
  if (!clean.length) return { abort: "all-candidate-pages-hold-foreign-content", pages: named, note: "decide by hand which page is ours; nothing was touched" };
  clean.sort((a, b) => (b.ours - a.ours));
  page = pages.find((p) => p.id === clean[0].id) || null;
}
const duplicatePages = named.filter((c) => !page || c.id !== page.id).map((c) => Object.assign({}, c, {
  action: c.unknown ? "keep — shapes unreadable; probe read-only, decide by hand"
    : c.foreign > 0 ? "keep — foreign content; never ours to delete"
    : c.ours > 0 ? "delete MANUALLY in the Penpot UI after this build, once a read-only probe shows it holds only " + TICKET + " / frames"
    : "delete MANUALLY in the Penpot UI (empty page)",
}));
let createdPage = false;
if (!page && PK > 1) return { abort: "part", version: VERSION, board: N0, part: PK, parts: KP, note: "PART " + PK + " appends to the board PART = 1 makes, but there is no page " + PAGE_NAME + ": run PART = 1 first; nothing was touched" };
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

// ---------------------------------------------------------------- the board: clear (one call, PART 1) or find (PART > 1) --
// A parted board's shapes carry one more plugin-data key, PSTAMP = "<part>:<seq>" (seq = the place in the creation
// sequence; the board frame "1:0"); a one-call board's carry none. A later part finds the board PART = 1 made and every
// frame it appends into by these stamps, never by order.
const PSTAMP = TAG + ":part";
const partOf = (s) => { for (const q of PLAN.parts) if (s >= q.from && s <= q.to) return q.part; return 0; };
const EXIST = new Map(); // seq -> the real shape an earlier part (or an earlier run of this part) made
const KEEP = new Set(); // seqs of this part's frames kept because a later part's shapes sit inside them (a re-run after later parts)
const FOUND = [], gone = new Set(), retry = { removed: 0, kept: 0, later: 0, restacked: 0 };
const mine = (s) => s >= CALL.from && s <= CALL.to && !KEEP.has(s); // the shapes this call creates
const removed = [];
if (!PK || PK === 1) {
  // r3's clear, unchanged: remove this ticket's OWN top-level board for the board about to be built (normalised name + own TAG)
  const planned = [norm(TICKET + "/" + pad2(N0) + " " + BD0.slug)];
  for (const s of (page.root.children || []).slice()) {
    try {
      if (s.type !== "board") continue; // top-level frames only
      const nm = norm(s.name);
      if (!nm.startsWith(TICKET + "/")) continue; // never another ticket's frame
      if (planned.indexOf(nm) < 0) continue; // only the board this call rebuilds
      let ours = false;
      try { ours = s.getPluginData(TAG) === "v1"; } catch (e) { ours = false; }
      if (!ours) { warn("clear", "kept an untagged frame named " + s.name + " (not built by this script)"); continue; }
      removed.push({ name: s.name, id: s.id, hpe1ver: s.getPluginData ? s.getPluginData("hpe1ver") : null });
      s.remove();
    } catch (e) { warn("clear", e); }
  }
} else {
  // PART k > 1: the ONE board PART = 1 made (name, TAG, this VERSION, stamp "1:0"); read-only until every check has passed
  const nm0 = norm(TICKET + "/" + pad2(N0) + " " + BD0.slug), tops = [];
  for (const s of page.root.children || []) { try { if (s.type === "board" && norm(s.name) === nm0 && s.getPluginData(TAG) === "v1") tops.push(s); } catch (e) { warn("find", e); } }
  const refuse = (why) => ({ abort: "part", version: VERSION, board: N0, part: PK, parts: KP, note: why + "; nothing was touched" });
  if (tops.length !== 1) return refuse(tops.length ? tops.length + " copies of board " + pad2(N0) + " on the page: run e12-d05-dedupe.js, or PART = 1 (it replaces them all)" : "no board " + pad2(N0) + " on the page to append to: run PART = 1 first");
  const PB = tops[0];
  let ver = null, st0 = null;
  try { ver = PB.getPluginData("hpe1ver"); st0 = PB.getPluginData(PSTAMP); } catch (e) { warn("find", e); }
  if (ver !== VERSION || st0 !== "1:0") return refuse("board " + pad2(N0) + " on the page is " + (ver !== VERSION ? "revision " + JSON.stringify(ver) : "not a parts build") + ", not this script's: run PART = 1 first");
  let bad = 0, unstamped = 0;
  const walk = (node, pseq) => {
    for (const c of node.children || []) {
      let m = null;
      try { m = /^(\d+):(\d+)$/.exec(c.getPluginData(PSTAMP) || ""); } catch (e) { m = null; }
      if (!m) { unstamped++; continue; }
      const f = { s: c, part: +m[1], seq: +m[2], parent: pseq };
      if (f.seq < 1 || f.seq >= PLAN.shapes || partOf(f.seq) !== f.part) bad++;
      FOUND.push(f);
      if (c.type === "board") walk(c, f.seq);
    }
  };
  walk(PB, 0);
  if (bad) return refuse(bad + " shape(s) inside board " + pad2(N0) + " carry a part stamp this plan does not make: run PART = 1 first");
  if (unstamped) warn("part", unstamped + " shape(s) inside board " + pad2(N0) + " carry no part stamp (not made by this script's parts): left as they are");
  EXIST.set(0, PB);
  for (const f of FOUND) EXIST.set(f.seq, f.s);
  const bySeq = new Map(FOUND.map((f) => [f.seq, f]));
  for (const f of FOUND) {
    if (f.part <= PK) continue;
    retry.later++;
    for (let a = bySeq.get(f.parent); a; a = bySeq.get(a.parent)) if (a.part === PK) KEEP.add(a.seq); // the frame stays: a later part's shape sits in it
  }
  // every parent this part appends into is made in this call or already on the board (an earlier part, a kept frame)
  const missing = new Set();
  for (const op of RECN.ops) if (op[1] === "add" && mine(op[2]) && !mine(op[0]) && !EXIST.has(op[0])) missing.add(partOf(op[0]));
  if (missing.size) return refuse("the frames part(s) " + Array.from(missing).sort((a, b) => a - b).join(", ") + " make(s) are not inside board " + pad2(N0) + ": run PART = " + Math.min.apply(null, Array.from(missing)) + " first");
  // a retry: remove this part's own shapes (a removed frame takes its children, all of this part), keep the frames above
  for (const f of FOUND) {
    if (f.part !== PK || KEEP.has(f.seq)) continue;
    const pf = bySeq.get(f.parent);
    if (pf && pf.part === PK && !KEEP.has(pf.seq)) { gone.add(f.seq); continue; } // goes with its frame
    try { f.s.remove(); gone.add(f.seq); } catch (e) { warn("part remove", e); }
  }
  for (const s of gone) EXIST.delete(s);
  retry.removed = gone.size; retry.kept = KEEP.size;
}

// ---------------------------------------------------------------- replay this call's writes onto real shapes ------
// In program order: each recorded write of a shape this call creates goes to its real shape (made where the record was);
// each append of such a shape goes to its parent, made in this call or found by its stamp. Writes of other parts' shapes
// are skipped, so the parts together make exactly the one-call build's shapes, values, order and z-order.
const REAL = new Map(), NEWKIDS = new Map();
let created = 0, buildError = null;
try {
  for (const op of RECN.ops) {
    const s = op[0], what = op[1];
    if (what === "add") {
      if (!mine(op[2])) continue;
      const P = REAL.get(s) || EXIST.get(s), ch = REAL.get(op[2]);
      if (!P || !ch) { warn("replay", "#" + op[2] + " has no " + (!P ? "parent #" + s : "shape")); continue; }
      try { P.appendChild(ch); if (!NEWKIDS.has(s)) NEWKIDS.set(s, []); NEWKIDS.get(s).push(op[2]); } catch (e) { warn("append", e); }
      continue;
    }
    if (!mine(s)) continue;
    if (what === "new") {
      let sh = null;
      try { sh = op[2] === "text" ? penpot.createText(op[3]) : op[2] === "rect" ? penpot.createRectangle() : penpot.createBoard(); } catch (e) { warn("create " + op[2], e); }
      if (!sh) { warn("create " + op[2], "no shape for #" + s + (op[2] === "text" ? ": " + String(op[3]).slice(0, 40) : "")); continue; }
      REAL.set(s, sh);
      created++;
      if (PK) { try { sh.setPluginData(PSTAMP, PK + ":" + s); } catch (e) { warn("part stamp", e); } } // first, so a retry finds it
      continue;
    }
    const sh = REAL.get(s);
    if (!sh) continue;
    try {
      if (what === "set") sh[op[2]] = op[3];
      else if (what === "rsz") sh.resize(op[2], op[3]);
      else if (what === "pd") sh.setPluginData(op[2], op[3]);
      else if (what === "font") op[2].applyToText(sh, op[3] || undefined);
    } catch (e) { warn(what === "font" ? "applyToText" : what === "set" ? "set " + op[2] : what === "pd" ? "tag" : "resize", e); }
  }
} catch (e) {
  buildError = { board: N0, part: PK, error: String(e && e.message || e), stack: e && e.stack ? String(e.stack).split("\n").slice(0, 4).join(" / ") : null, note: "rerun this call: it replaces its own shapes" };
  warn("replay " + N0, buildError.error);
}
// a re-run after later parts: in each parent that got new shapes, the shapes of this part and later parts are put back in
// creation order (appendChild brings a shape to the top), keeping the longest run already in that order; never otherwise
if (PK > 1 && retry.later) {
  const kidsOf = new Map();
  for (const f of FOUND) if (f.part >= PK && !gone.has(f.seq)) { if (!kidsOf.has(f.parent)) kidsOf.set(f.parent, []); kidsOf.get(f.parent).push(f.seq); }
  for (const [p, kids] of NEWKIDS) {
    const E = (kidsOf.get(p) || []).slice().sort((a, b) => a - b);
    if (!E.length) continue;
    const cur = E.concat(kids), at = new Map(cur.map((q, i) => [q, i])), T = cur.slice().sort((a, b) => a - b);
    let k = 0, last = -1;
    while (k < T.length && at.get(T[k]) > last) { last = at.get(T[k]); k++; }
    const P = REAL.get(p) || EXIST.get(p);
    for (const q of T.slice(k)) { try { P.appendChild(REAL.get(q) || EXIST.get(q)); retry.restacked++; } catch (e) { warn("restack", e); } }
  }
}

// ---------------------------------------------------------------- token bindings on the real shapes this call made -------
const TOKN = flushBindings(N0, RECN.binds || new Map(), RECN.bvq || [], (r) => (r && REAL.get(r.seq)) || null);
// r3 (#4640 F-1): every translucent fill this call made (a meta opTok: the modal scrim, palette.black at opacity.scrim) is read back
// after the bindings and re-asserted at its token's value; one still off after the re-assert is a warning (the r2 boards drew it opaque)
const SCRIMS = { shapes: 0, ok: 0, reasserted: 0, off: 0, opacity: [] };
for (const rec of RECN.shapes) {
  let m = null; try { m = JSON.parse(rec.pd[TAG + ":meta"] || "{}"); } catch (e) { m = {}; }
  if (!m.opTok) continue;
  const sh = REAL.get(rec.seq); if (!sh) continue; // another part's shape
  const want = NV[m.opTok], read = () => { try { const f = (sh.fills || [])[0]; return f ? f.fillOpacity : null; } catch (e) { return null; } };
  SCRIMS.shapes++;
  let got = read();
  if (got == null || Math.abs(got - want) > 0.001) {
    try { sh.fills = [{ fillColor: col(m.tok), fillOpacity: want }]; } catch (e) { warn("scrim", e); }
    SCRIMS.reasserted++; got = read();
  }
  if (got != null && Math.abs(got - want) <= 0.001) SCRIMS.ok++; else { SCRIMS.off++; warn("scrim", "board " + pad2(N0) + ": the " + String(sh.name).slice(TICKET.length + 3) + " reads fill opacity " + got + ", " + m.opTok + " is " + want); }
  if (SCRIMS.opacity.indexOf(got) < 0) SCRIMS.opacity.push(got);
}

// ---------------------------------------------------------------- result ------------------------------------
try { page.setPluginData(TAG, "v1"); page.setPluginData(TAG + ":built", new Date().toISOString()); } catch (e) { warn("page tag", e); }
// the result carries the real shapes' ids (a record's id is "rec:<seq>"); a frame a later part draws reads null
const realId = (id) => { const m = /^rec:(\d+)$/.exec(String(id)); if (!m) return id; const r = REAL.get(+m[1]) || EXIST.get(+m[1]) || null; return r ? r.id : null; };
for (const x of built) x.id = realId(x.id);
for (const x of FRAMES) x.id = realId(x.id);
const counts = { shapes: 0, texts: 0 }, fonts = {}, onBoard = {};
const walkCount = (s) => { for (const c of s.children || []) { counts.shapes++; if (c.type === "text") { counts.texts++; let id = null; try { id = c.fontId || null; } catch (e) { id = null; } fonts[id || "(no fontId)"] = (fonts[id || "(no fontId)"] || 0) + 1; } if (PK) { let m = null; try { m = /^(\d+):/.exec(c.getPluginData(PSTAMP) || ""); } catch (e) { m = null; } const k2 = m ? m[1] : "unstamped"; onBoard[k2] = (onBoard[k2] || 0) + 1; } walkCount(c); } };
for (const x of built) { const s = (page.root.children || []).find((c) => c.id === x.id); if (s) walkCount(s); }
if (PK) onBoard["1"] = (onBoard["1"] || 0) + 1; // the board frame (part 1)
const missing = PK ? PLAN.parts.filter((q) => (onBoard[String(q.part)] || 0) !== q.shapes).map((q) => q.part) : []; // parts not (fully) on the board
const DONE = !PK || !missing.length; // the board holds every part: relayout and export now
if (PK === KP && missing.length) for (const q of missing) warn("parts", "board " + pad2(N0) + " holds " + (onBoard[String(q)] || 0) + " shapes of part " + q + ", the plan makes " + PLAN.parts[q - 1].shapes + ": run PART = " + q + " again (then the relayout)");
const EXPORT = "python3 docs/design/_tools/penpot_export.py ";
return {
  writer: WRITER,
  version: VERSION,
  pageId: page.id, // record it in spec §0 (page name and id only, never a host, team or file id)
  pageName: page.name,
  createdPage,
  removed,
  duplicatePages, // same-name pages NOT built on: each carries a manual `action`; nothing here was deleted
  part: PK ? { board: N0, part: PK, of: KP, sections: ["creation sequence " + CALL.from + "–" + CALL.to], created, declared: CALL.shapes, segs: CALL.segments, budget: BUDGET, last: PK === KP } : null, parts: KP, // part k of K (null: the board in one call); created = the shapes this call made
  call: { shapes: created, segments: CALL.segments, planned: CALL.shapes, budget: BUDGET }, // shapes this call created (the frame counted in part 1)
  plan: PLAN.parts.map((q) => ({ part: q.part, shapes: q.shapes, segments: q.segments })), // this board's parts
  onBoard: PK ? onBoard : undefined, // shapes per part on the board after this call (the frame counted in part 1)
  missing: PK ? missing : undefined, // the parts still to draw (or to draw again) before the relayout
  partRetry: PK > 1 ? retry : undefined, // a re-run of this part: its own shapes removed, frames kept, shapes re-stacked
  boards: built, // { n, name, id, exportAs, w, h, theme, density }
  headerOverflow: Object.keys(HEADER_OVER).map((k) => HEADER_OVER[k]), // headers wider than their column's inside at the spec's widths (open-points OP-4)
  frames: FRAMES, // the SCR child frames of this board: { board, name, id, w, h } (id null: a later part draws it)
  scrims: SCRIMS, // r3: the translucent fills this call made, read back after the bindings: { shapes, ok, reasserted, off, opacity: [values read] } (expect off 0, opacity [0.6])
  tokens: { catalog: { ok: CAT.ok, theme: CAT.theme, activeSets: CAT.sets, names: CAT.index.size, note: CAT.note }, boards: TOKREP }, // this call's shapes: bound, unbound (with reasons), byValue
  layout: LAYOUT, // the dock rectangles a builder reports (the template's slot, kept)
  shapes: counts.shapes, texts: counts.texts, fonts, // the whole board so far; fonts: the fontId histogram (expect gfont-inter and gfont-jetbrains-mono only)
  error: buildError,
  next: DONE ? "e12-d05-relayout.js PASS=\"measure\" (until unmeasured=0) → PASS=\"restack\" (until moved=0) → export (exportCommands) → inspect the PNG → next board; after the last board e12-d05-dedupe.js, then probe.js until every instance agrees"
    : "board " + pad2(N0) + ": PART = " + (missing.indexOf(PK) >= 0 ? PK : missing[0]) + " next (ONLY = [" + N0 + "]); still to draw: part " + missing.join(", ") + " of " + KP + "; the relayout and the export once every part is on the board",
  exportCommands: DONE ? built.map((x) => EXPORT + x.id + " " + x.exportAs).join("\n") : "",
  warnings,
};
