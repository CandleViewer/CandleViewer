/* E36-D02 — SCR-081 rule editor (form mode) and SCR-083 templates gallery hi-fi boards (#873): BUILD script.
 *
 * Paste this whole file as the body of ONE Penpot MCP `execute_code` call (or run it through the loader one board
 * at a time with ONLY = [n]), with the bridge connected and the CandleViewer file open. Same shared-plugin convention
 * and write patterns as e36-d01-board.js r5 (penpot-gotchas.md): single writer (storage.hpe1inst stamp in WRITER;
 * "SET-ME" skips), file-id guard (FILE_ID is set by the loader at load time and never committed or posted), page by
 * name (created if missing; pin PAGE_ID after the first run), re-check, then ONLY synchronous creates; idempotent:
 * removes ITS OWN top-level frames (ticket prefix, normalised name, this page only) and stamps every board `hpe1ver`
 * = VERSION; every shape is named "E36-D02 / …" and carries plugin data under TAG. No script ever calls
 * page.remove(). Never retry after a "tab suspended" answer: probe read-only first. Afterwards run
 * e36-d02-relayout.js (PASS "measure", then "restack" until moved = 0), e36-d02-dedupe.js, then export.
 *
 * Source of every word and number: docs/design/E36/E36-D02.md (the spec: §2 anatomy, §3 states, §4 indicator,
 * §5–§9 the component contracts, §10 the gallery, §11 200 %, §12–§13 keyboard / names / announcements, §14 copy
 * deck, §15 the measured matrix, §16 the `15` amendments, §17 observability, §20 C / G / Q) and
 * docs/design/E36/E36-D02-handoff.md; the sentences are the E36-D01 memo's (docs/design/research/e36-rules-in-words.md
 * §2 rows 3–14, §5.4 S1–S3, §5.6); e36-d02-check-nums.py proves every number and word below is in the spec before
 * this runs. Fills are the dark theme's semantic tokens of packages/ui/tokens resolved at the base
 * 290d29f0ac6c57daf304ad43b372240b98c4959d (token name in each shape's plugin data; the hexes are the audit tool's).
 * Geometry rules: row height = max wrapped height over every cell; every block ≥40 px below the content above;
 * content margins ≥24 px; conservative estH (0.56 em Inter, 0.62 em mono, +0.4 lines, +6 px); every pill through
 * pillTextW (the shared label-width rule) with NBSP-joined words; non-breaking hyphens in rule ids and in
 * hard‑locked / read‑only / round‑trip; the footer "page E36-D02 · board NN · rN" 24 px under the content.
 *
 * BUDGET (r7; the E14-D06 r7 PART mechanism): ONE plugin call creates at most SHAPE_BUDGET = 400 shapes and SEG_BUDGET = 5,000
 * path segments; the page holds at most PAGE_SEG_BUDGET = 20,000 path segments. Before anything is removed or drawn, a dry pass
 * builds every board against a count sink, records every top-level unit (the board with its title, each card, each table row,
 * each pill, each field row, each section, the header, the band, the action bar, the footer) with its shapes and segments, and
 * packs the units in drawing order into PARTS within both per-call budgets; a unit is never cut. The pre-run guard throws
 * ("budget") when the call would create more than the budget, and nothing is touched then.
 * DRIVER (one plugin call per line; set ONLY and PART before each call; PART = 0 returns the part plan and the self-check and
 *   draws nothing): ONLY = [n] with PART = null when its plan has one part (the whole board), else PART = 1, 2, … parts(n) in
 *   sequence. Part 1 draws the new board root (and its part) first and removes the old board only after its draw succeeds; a
 *   later part attaches to the board part 1 built (it aborts, nothing drawn, when that board is missing); a throw removes every
 *   shape the call created, so a failed call leaves the page as it was. A failed or repeated part k > 1 is redone from PART = 1.
 *   Shapes outside the call's part are laid out as dry records, so every x, y and block id equals the one-call build's. The
 *   mock harness (WRITER "MOCK") builds every board in one call.
 * PART_PLAN (r7, the mock count, shapes incl. the board root): 02 = 2 parts, 03 = 2 parts, 12 = 2 parts, every other board 1
 *   part; PART = 0 prints the live plan (shapes and segments per part).
 * PRE-EXPORT SELF-CHECK (r7): selfCheck() runs on the dry pass's record before the clear and before any shape is drawn, and
 *   throws when a single-line text (a pill / chip / button label, a field label, the band text, the saved caption, an inline
 *   T2 or validity reason) is wider than its box at the shared PILL_EM bound (Inter class sums; JetBrains Mono 0.62 em);
 *   the pre-existing items in KNOWN_WRAPS warn instead (returned under knownWraps).
 */
"use strict";

// ---------------------------------------------------------------- constants (edit only these) -------------
const WRITER = "SET-ME"; // storage.hpe1inst stamp of the ONE instance allowed to write (probe.js); "SET-ME" skips
const VERSION = "r7"; // hpe1ver stamp on every board; bump when the content changes — r7 = r6 + the PART split for boards 02, 03, 12 (no string, number, token or geometry change): the shape / segment budget, the dry planning pass, ONLY + PART, the pre-run guard, the pre-export self-check with the single-line wrap rule (KNOWN_WRAPS warn), the draw-then-clear and the rollback; the exact Inter lookup kept; no pageLink. Before: r6 = r5 + the issuecomment-6355339796 fold (the orchestrator's T2-delta closure: APPROVE pending boards at f9d8459a, three nits for the boards commit; the validity look agreed lane-wide at 02:13Z): (V) the four validity-disabled buttons — 02-4's Arm… "Fix the errors first." and Save draft "Fix the errors to save." (board 02) and board 07's two Arm… specimen rows ("Fix the errors first.", "Tick ‘I understand’ on Flatten all positions first.") — no longer take the T2 fill: each keeps its own variant fill and full label (Save draft primary; Arm… primary on demo) at opacity.disabled (0.45 — fill, hairline and label), the reason full-opacity color.text.secondary beside it in a layer named validity-reason, never t2-reason (E30-D02 D3; spec §1); the look is named on boards 01, 02, 07 and 08; (N2) 02-5 while viewing as — the view-as line is the frame's one notice, the armed notice yields and the ARMED-DEMO pill keeps the state visible (board 02: the 02-5 label and the view-as inset); (N1) is a spec-only fix; the exact Inter lookup kept; no pageLink. Before: r5 = r4 + the issuecomment-6354615174 fold (the orchestrator's T2 gate delta, REQUEST_CHANGES at 7b7db68c): M1 the view-as leg — rbac.view_as "Read-only while viewing as {user}." as the first leg on Save draft, Validate, Simulate, Arm… / Disarm, Start recording and SCR-083's Create draft, one notice per frame, drawn as a named inset (boards 02, 10), first in the Arm reasons list (board 07), the §13 row and the counts (board 13), state 4's view-as tooltip (board 03); M2 form validity out of the T2 grammar — Fix the errors first. / Fix the errors to save. / Add an action to save. / Tick ‘I understand’ on Flatten all positions first. drawn aria-disabled with the reason and no lock, no CMP-079 (boards 02, 07, 08); m1 the six composed frames named; m3 a full stop on every rule.* and validity string and the simulate-first string rendered from the defaults (boards 01, 02, 03, 07, 11, 12); the exact Inter lookup kept; no pageLink. Before: r4 = r3 + the T2-precheck-4148 fold (the lane's standing E09-D09 T2 gate pre-check, read-only, 2026-10-22 22:20Z): (1) every gated row reaches the T2 rule — Start recording T2 for a session without recording:write (boards 04, 05), the ten non-placing orders:write actions and Resume new orders T2 while the six simulate-only ones stay pickable with the tag "simulate only" (board 06), the fire limits above the default T2 for a non-owner and the flatten-all gate reason (board 07); (2) the T2 form — the raised fill with the border hairline, the lock, the tertiary label, the secondary reason — on the pickers, the add buttons, the row menus, Validate and Simulate (board 02), a picker specimen (board 06), the two rejected / decorative matrix rows (board 12), the glyph stand-in note (boards 02, 06, 07); (3) the stage-nothing press and the arrow onto a T2 option (board 13); (4) keyed reasons — "Simulate first — 5 fires or 24 h", "Fix the errors first", "Fix the errors to save", "Your role can't place orders." + "This account isn't assigned to you." (boards 01, 02, 03, 07, 12); (5) one notice per read-only frame — 02-5 and 02-6 point every gated control at the notice / banner, no per-control reason (boards 02, 08); (6) CMP-079 RbacGate + the CMP-019 lock named (boards 01, 07, 13); the Minors: the six composed indicator frames and 02-5's two notice buttons (boards 02, 03), SCR-083 at 200 % and the T2 reason at 200 % (board 11), the forced-colours card (board 12), the arm path and retries (board 07); the exact Inter lookup kept; no pageLink. Before: r3 = r2 + the orchestrator's text round 2 (issuecomment-6342714018) fold (M1 no loosening control for any role — #4137, M2, M3, m3, m7); r2 = r1 + the pre-PR design-review lens round 1 (F-1…F-11); r1 = the desk spec, boards pending
const FILE_ID = "SET-ME"; // the self-hosted CandleViewer file id, set by the loader at load time; never committed or posted
const PAGE_NAME = "E36-D02 Rule form editor and templates"; // created by name on the first run; then pin PAGE_ID
const PAGE_ID = null; // paste the returned pageId here after the first run
const TICKET = "E36-D02";
const TAG = "cv:e36-d02"; // plugin-data key marking every shape this script creates (value "v1")
const ONLY = null; // e.g. [1, 2] builds (and clears) a subset of boards; null = all thirteen (outside the mock harness the guard refuses a call over the budget: one board per call)
const PART = null; // null = the board(s) in ONLY in one call (each plan must have one part); 0 = return the part plan + the self-check only, nothing drawn; k >= 1 = part k of the ONE board in ONLY (see the DRIVER)
const SHAPE_BUDGET = 400; // the most shapes ONE plugin call may create
const SEG_BUDGET = 5000; // the most path segments ONE plugin call may create
const PAGE_SEG_BUDGET = 20000; // the most path segments on the page (every board)
const HARNESS = WRITER === "MOCK"; // the offline mock harness builds every board in one call
// KNOWN_WRAPS: [board, layer, line] — single-line texts drawn before r7 that the r7 wrap rule flags; kept unchanged (no drawn change in
// r7), so they warn (knownWraps in the result) instead of throwing; any other wrap throws.
const KNOWN_WRAPS = [];
const EXPORT_DIR = "docs/design/E36/img";
const BOARDS = [
  { n: 1, slug: "scr-081-anatomy" },
  { n: 2, slug: "scr-081-states" },
  { n: 3, slug: "round-trip-indicator" },
  { n: 4, slug: "condition-rows-grouping" },
  { n: 5, slug: "metric-picker" },
  { n: 6, slug: "action-rows" },
  { n: 7, slug: "options-limits-summary" },
  { n: 8, slug: "validation-copy" },
  { n: 9, slug: "scr-083-gallery" },
  { n: 10, slug: "scr-083-preview-states" },
  { n: 11, slug: "long-content-200pct" },
  { n: 12, slug: "themes-densities-greyscale" },
  { n: 13, slug: "keyboard-a11y-copy" },
];
// Every number drawn on a board (spec §0–§22; the audit tool's --json). Keep equal to the spec; e36-d02-check-nums.py enforces it.
const NUM = {
  states: 6,
  indicatorStates: 4,
  boards: 13,
  templates: 12,
  categoryCount: 7,
  signals: 105,
  estimated: 13,
  operators: 15,
  actions: 25,
  triggers: 13,
  limits: 11,
  destructive: 8,
  longestTitle: 31,
  pairsGated: 32,
  pairsProposed: 18,
  pairsRegistered: 14,
  pairsFail: 0,
  cRows: 21,
  gRows: 15,
  qRows: 12,
  handoffBlocks: 8,
  amendmentRows: 11,
  categories: [13, 41, 16, 11, 13, 8, 3],
  estimatedByCategory: [2, 7, 2, 0, 2, 0, 0],
  summaryWords: [44, 48, 55],
  maxWords: 55,
  column: 1120,
  cropW: 1280,
  cropH: 800,
  screenW: 1920,
  screenH: 1080,
  rowCompact: 24,
  rowComfortable: 32,
  actionBar: 48,
  headerRow: 32,
  labelColumn: 160,
  bracketPx: 2,
  debounceMs: 300,
  compileMs: 500,
  instantiateMs: 300,
  firesPerHour: 60,
  firesPerDay: 500,
  capPerHour: 600,
  capPerDay: 5000,
  maxActions: 10,
  timeoutMs: 250,
  killSwitch: 5,
  maxChildren: 32,
  simFires: 5,
  simHours: 24,
  ttlS: 60,
  offsetTicks: 2,
  longRows: 12,
  longActions: 6,
  zoom: 200,
  zoomMid: 125,
  versionN: 3,
  ruleMaxChars: 120,
  contrast: {
    textCanvas: 15.2,
    text2Canvas: 9.33,
    text3Canvas: 5.96,
    textRaised: 14.35,
    text2Raised: 8.81,
    text3Raised: 5.62,
    textSuccess: 10.21,
    glyphSuccess: 6.69,
    textWarning: 9.86,
    text2Warning: 6.05,
    glyphWarning: 7.56,
    textDanger: 12.06,
    glyphDanger: 7.83,
    textHover: 12.22,
    text2Hover: 7.5,
    dangerCanvas: 3.63,
    dangerRaised: 3.43,
    textInfo: 10.74,
    glyphInfo: 4.64,
    focusCanvas: 7.05,
    focusRaised: 6.66,
    focusWarning: 4.57,
    onAction: 4.76,
    onDanger: 5.05,
    text3WarningRejected: 3.86,
    borderStrongRejected: 1.91,
  },
};
// Every term drawn on a board that is not a number: each string must appear verbatim in the spec or the handoff (check-nums).
const TERMS = [
  "BLOCKED-PENPOT",
  "PROPOSED",
  "RULED",
  "DECIDED",
  "heuristic",
  "(estimated)",
  "C-2.6",
  "C-4.14",
  "C-2.21",
  "C-2.20",
  "C-1.2",
  "C-6.1",
  "Round-trips ✓",
  "Graph-only construct — read-only here",
  "Round-trip mismatch",
  "Not verified",
  "Checking…",
  "since your last save",
  "The stop only ever tightens.",
  "Rules never loosen a stop.",
  "Turns itself off after 5 errors in a row — you re-arm it.",
  "No rule notional cap — your account's risk caps still apply.",
  "Asks before acting (skipped if unanswered in 60 s).",
  "Row 2 is missing a value.",
  "Position side compares to long / short, not a number.",
  "This rule depends on an estimated detector — behaviour is heuristic.",
  "Every position keeps a native stop — you can move it, not delete it.",
  "Kept at 63,900.0 — every position keeps a native stop. Move it instead.",
  "Rules can tighten it, never remove it — the stop is held by the exchange, not by this app.",
  "The rule engine is not running — armed rules are not evaluating. Your native stops are held by the exchange and are unaffected.",
  "Authored in the graph editor:",
  "Open in the graph editor to change this.",
  "Saving is blocked until the mismatch is resolved.",
  "View diff",
  "Keep the form version — the graph's {diverging node} is replaced by this form's Row {n}.",
  "Keep the graph version — your form edits since the last save are discarded.",
  "Simulate first — 5 fires or 24 h.",
  "Only the owner can arm rules against live.",
  "Not verified — arming is blocked.",
  "The rule engine is not running",
  "Fix the errors first.",
  "Add an action to save.",
  "Fix the errors to save.",
  "Your role can't place orders.",
  "This account isn't assigned to you.",
  "You can view this account, not trade it.",
  "Only the owner can start recording.",
  "Only the owner can raise a rule's fire limits.",
  "Tick ‘I understand’ on Flatten all positions first.",
  "I understand this flattens every open position on the accounts in scope.",
  "simulate only",
  "Requires orders:write.",
  "Requires orders:write on at least one account; available in simulate mode only.",
  "rbac.permission",
  "rbac.owner_only",
  "rbac.account",
  "rule.arm.simulate_first",
  "rule.arm.unverified",
  "rule.save.mismatch",
  "rbac.view_as",
  "Read-only while viewing as {user}.",
  "Validation — not run while viewing as",
  "Not verified — round-trip checks don't run while viewing as another user.",
  "form validity",
  "view-as",
  "CMP-079",
  "CMP-019",
  "CMP-002",
  "CMP-016",
  "RbacGate",
  "Not available",
  "aria-disabled",
  "aria-readonly",
  "color.border.default",
  "color.text.disabled",
  "opacity.disabled",
  "forced-colors",
  "CanvasText",
  "one notice, many pointers",
  "Arm path and retries",
  "E09-D09 §2.2",
  "E09-D09 §9.3",
  "E09-D09 §2.4",
  "A-rows",
  "D02-A1",
  "D02-A2",
  "A rule needs at least one action — add one to save.",
  "Creates 3 rules",
  "Opens in the form editor",
  "Uses an estimated detector",
  "Needs recorded data",
  "Create draft",
  "Create 3 drafts",
  "No templates match — clear the search or the filters.",
  "Templates are not available — the rule engine is not running.",
  "Start recording",
  "Condition 1 of 2",
  "Shift+F10",
  "Ctrl+S",
  "Ctrl+Enter",
  "Alt+G",
  "Alt+Shift+↑",
  "Alt+↑/↓",
  "Ctrl+D",
  "aria-describedby",
  "aria-busy",
  'role="status"',
  'role="log"',
  'role="note"',
  'role="alert"',
  "DRAFT",
  "ARMED-DEMO",
  "ARMED-LIVE",
  "PAUSED",
  "ERROR",
  "DEMO",
  "LIVE",
  "Last saved 13:42:10 UTC",
  "2 accounts · BTCUSDT · new positions",
  "Disarm to edit",
  "Edit as a new draft version",
  "Validate",
  "Simulate",
  "Save draft",
  "Arm…",
  "Move up",
  "Move down",
  "Duplicate",
  "Remove",
  "all of",
  "any of",
  "+ any-of group",
  "+ condition",
  "+ action",
  "Scope",
  "Trigger",
  "Conditions",
  "Actions",
  "Options",
  "is above",
  "is at least",
  "is below",
  "is at most",
  "is between",
  "is outside",
  "crosses above",
  "crosses below",
  "changes",
  "is one of",
  "is none of",
  "for at least",
  "price",
  "orderflow",
  "book",
  "derivatives",
  "position",
  "account",
  "replay",
  "Unrealised R",
  "Position side",
  "Position open",
  "Position age",
  "Spread (bps)",
  "Tape speed z-score",
  "Distance to liquidity cluster",
  "Nearest imbalance zone distance",
  "VWAP band sigma",
  "Place order",
  "Modify stop loss",
  "Move stop to breakeven",
  "Scale out",
  "Flatten all positions",
  "Halt new orders",
  "places orders",
  "native_stop_violation",
  "absolute",
  "offset_from_entry",
  "offset_from_price",
  "atr",
  "structure",
  "next_utc_day",
  "duration_ms",
  "manual",
  "semantics undocumented (G6)",
  "once_per",
  "cooldown_ms",
  "max_fires_per_hour",
  "max_fires_per_day",
  "max_actions_per_fire",
  "max_notional_per_fire",
  "max_daily_notional",
  "require_confirmation",
  "evaluation_timeout_ms",
  "kill_switch_on_error_count",
  "Once per position.",
  "At most every 60 s.",
  "Up to 500 times a day.",
  "If an action fails, the rest are skipped.",
  "rule.roundtrip_verified",
  "rule.roundtrip_mismatch_resolved",
  "rule.saved",
  "rule.validated",
  "rule.template_previewed",
  "rule.template_instantiated",
  "rule.created",
  "CMP-140",
  "CMP-141",
  "CMP-142",
  "CMP-143",
  "CMP-144",
  "CMP-145",
  "CMP-157",
  "CMP-158",
  "CMP-227",
  "CMP-233",
  "CMP-234",
  "CMP-235",
  "CMP-003",
  "CMP-011",
  "CMP-026",
  "CMP-028",
  "CMP-040",
  "CMP-043",
  "CMP-044",
  "CMP-048",
  "CMP-050",
  "CMP-054",
  "CMP-065",
  "CMP-105",
  "SCR-058",
  "SCR-080",
  "SCR-081",
  "SCR-082",
  "SCR-083",
  "SCR-085",
  "SCR-088",
  "E36-D03",
  "E36-D04",
  "E36-D05",
  "E36-T01",
  "E36-S01",
  "E36-S03",
  "E36-S04",
  "E36-Q05",
  "E35-D02",
  "E37-D01",
  "E40-D02",
  "E49",
  "E32-D01",
  "E25-D01",
  "E09-D09",
  "E17-D01",
  "Arm A",
  "T2",
  "sl.note",
  "sl.kept",
  "DCR-11",
  "US-RULE-004",
  "US-RULE-006",
  "US-RULE-007",
  "MAX_BOOLEAN_CHILDREN",
  "color.text.primary",
  "color.text.secondary",
  "color.text.tertiary",
  "color.surface.canvas",
  "color.surface.raised",
  "color.surface.hover",
  "color.status.success.subtle",
  "color.status.warning.subtle",
  "color.status.danger.subtle",
  "color.status.info.subtle",
  "color.status.danger.default",
  "color.focus.ring",
  "color.border.selected",
  "size.control.height",
  "space.inset.sm",
  "space.inset.md",
  "space.inset.lg",
  "border.thick",
  "font.family.mono",
  "font.mono",
  "color.border.invalid",
  "space.rulegroup.indent",
  "color.status.warn",
  "icon/round-trip-ok",
  "icon/round-trip-partial",
  "icon/round-trip-mismatch",
  "icon/round-trip-unverified",
  "icon/lock",
  "icon/native-sl-shield",
  "pairs.mjs",
  "encodings.json",
  "Main",
  "Alt",
  "sub_001",
  "BTCUSDT",
  "break-even (your average entry) plus 2 ticks",
  "notify me (push, high)",
  "scale out 33 % at market",
  "tighten the stop to 2.0 × ATR(14) from the close",
  "buy 0.25 at market with a native stop at 63,900",
  "flatten every position",
  "halt new orders on this account until the next UTC day",
  "owner approval pending",
  "not designed here",
  "state variant",
  "worked example",
  "illustrative",
  "Checking",
  "destructive class",
  "Rule editor — BE after 1R",
  "Rule templates — 12",
  "Rule actions",
  "Estimated,",
  "Round-trip:",
  "Validation — 2 errors, 0 warnings",
  "No problems — 0 errors · 0 warnings.",
  "Metric",
  "Editor",
  "Form",
  "Graph",
];

// ---------------------------------------------------------------- single writer -----------------------------
if (typeof storage === "undefined" || storage.hpe1inst !== WRITER) {
  return {
    skip: typeof storage === "undefined" ? null : storage.hpe1inst,
    note: "not the writer instance — run probe.js, pick one stamp, set WRITER",
  };
}

// ---------------------------------------------------------------- guard + page -----------------------------
const warnings = [];
const warn = (where, e) => warnings.push(where + ": " + (e && e.message ? e.message : String(e)));
if (!penpot.currentFile || penpot.currentFile.id !== FILE_ID) {
  return {
    abort: "file",
    current: penpot.currentFile
      ? { id: penpot.currentFile.id, name: penpot.currentFile.name }
      : null,
  };
}
const norm = (s) => String(s || "").replace(/\s*\/\s*/g, "/");
const pages = penpot.currentFile.pages || [];
function classifyPage(p) {
  const out = { id: p.id, name: p.name, ours: 0, foreign: 0, unknown: false };
  try {
    for (const s of (p.root && p.root.children) || []) {
      if (norm(s.name).startsWith(TICKET + "/")) out.ours++;
      else out.foreign++;
    }
  } catch (e) {
    out.unknown = true;
    warn("classify " + p.id, e);
  }
  return out;
}
const named = pages.filter((p) => p.name === PAGE_NAME).map(classifyPage);
let page = PAGE_ID ? pages.find((p) => p.id === PAGE_ID) || null : null;
if (!page && named.length) {
  const clean = named.filter((c) => !c.unknown && c.foreign === 0);
  if (!clean.length)
    return {
      abort: "all-candidate-pages-hold-foreign-content",
      pages: named,
      note: "decide by hand which page is ours; nothing was touched",
    };
  clean.sort((a, b) => b.ours - a.ours);
  page = pages.find((p) => p.id === clean[0].id) || null;
}
const duplicatePages = named
  .filter((c) => !page || c.id !== page.id)
  .map((c) =>
    Object.assign({}, c, {
      action: c.unknown
        ? "keep — shapes unreadable; probe read-only, decide by hand"
        : c.foreign > 0
          ? "keep — foreign content; never ours to delete"
          : c.ours > 0
            ? "delete MANUALLY in the Penpot UI after this build, once a read-only probe shows it holds only E36-D02 / frames"
            : "delete MANUALLY in the Penpot UI (empty page)",
    }),
  );
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
  return {
    retry: true,
    pageId: page.id,
    pageName: page.name,
    createdPage,
    note: "page not current yet — run again, or open it in the UI first",
  };
}
// ---- from here on: synchronous only (no await) ----

// ---------------------------------------------------------------- tokens (dark theme, resolved at the base) ----
const C = {
  canvas: "#11151A",
  raised: "#161B22",
  hover: "#22292F",
  selected: "#2E363E",
  app: "#0B0E11",
  overlay: "#1C222B",
  text: "#E8EAED",
  text2: "#B1BAC4",
  text3: "#8B949E",
  onAction: "#FFFFFF",
  border: "#2E363E",
  borderStrong: "#3D4650",
  borderSelected: "#4A86EE",
  focus: "#6EA1F5",
  primary: "#2B6CE8",
  dangerSubtle: "#4E1518",
  dangerStrong: "#F0B441",
  danger: "#C93A3F",
  successSubtle: "#0E3D1F",
  successStrong: "#6BD48A",
  warning: "#E8A317",
  warningSubtle: "#4A3306",
  warningStrong: "#F5C86B",
  info: "#1EA8CC",
  infoSubtle: "#093644",
  infoStrong: "#6ED0E8",
  buy: "#2EBD59",
  sell: "#E5484D",
};
const TOK = {
  canvas: "color.surface.canvas",
  raised: "color.surface.raised",
  hover: "color.surface.hover",
  selected: "color.surface.selected",
  app: "color.surface.app",
  overlay: "color.surface.overlay",
  text: "color.text.primary",
  text2: "color.text.secondary",
  text3: "color.text.tertiary",
  onAction: "color.text.on-action",
  border: "color.border.default",
  borderStrong: "color.border.strong",
  borderSelected: "color.border.selected",
  focus: "color.focus.ring",
  primary: "color.action.primary.default",
  dangerSubtle: "color.status.danger.subtle",
  dangerStrong: "color.status.danger.strong",
  danger: "color.status.danger.default",
  successSubtle: "color.status.success.subtle",
  successStrong: "color.status.success.strong",
  warning: "color.status.warning.default",
  warningSubtle: "color.status.warning.subtle",
  warningStrong: "color.status.warning.strong",
  info: "color.status.info.default",
  infoSubtle: "color.status.info.subtle",
  infoStrong: "color.status.info.strong",
  buy: "color.buy.default",
  sell: "color.sell.default",
};

// ---------------------------------------------------------------- helpers -----------------------------------
// semantic-light layered over dark (themes.json), resolved at the base — the audit tool's light column; board 12's two compositions only
const LIGHT = {
  canvas: "#F6F7F9",
  raised: "#EDEFF2",
  hover: "#E3E6EA",
  selected: "#D6DAE0",
  app: "#FFFFFF",
  overlay: "#E3E6EA",
  text: "#14171A",
  text2: "#3A4148",
  text3: "#525C66",
  onAction: "#FFFFFF",
  border: "#D6DAE0",
  borderStrong: "#C2C8D0",
  borderSelected: "#2B6CE8",
  focus: "#1F55BF",
  primary: "#2B6CE8",
  dangerSubtle: "#FBE2E3",
  dangerStrong: "#9A6A05",
  danger: "#7A1E22",
  successSubtle: "#DCF3E4",
  successStrong: "#1E9448",
  warning: "#B87F0A",
  warningSubtle: "#FCEECB",
  warningStrong: "#9A6A05",
  info: "#178AA8",
  infoSubtle: "#DAF2F7",
  infoStrong: "#12798F",
  buy: "#1C7A3C",
  sell: "#C7373C",
};
function withLightComfortable(fn) {
  // board 12: the light theme (a token swap, 15 §0.3 rule 1) at the comfortable density (32 px rows, 56 px action bar) in a 1024 px column at 1280 wide; restored afterwards
  const saveC = Object.assign({}, C),
    saveN = { rowCompact: NUM.rowCompact, actionBar: NUM.actionBar, column: NUM.column };
  Object.assign(C, LIGHT);
  NUM.rowCompact = NUM.rowComfortable;
  NUM.actionBar = 56;
  NUM.column = 1024;
  try {
    return fn();
  } finally {
    Object.assign(C, saveC);
    NUM.rowCompact = saveN.rowCompact;
    NUM.actionBar = saveN.actionBar;
    NUM.column = saveN.column;
  }
}
const FONT = (() => {
  try {
    const all = (penpot.fonts && penpot.fonts.all) || [];
    return (
      all.find((f) => f.fontId === "gfont-inter") || all.find((f) => f.name === "Inter") || null
    );
  } catch (e) {
    warn("fonts", e);
    return null;
  }
})(); // exact lookup: findByName("Inter") prefix-matches Inter Tight on the self-hosted file (PENPOT-FONTS 2026-10-21)
const MONO = (() => {
  try {
    return penpot.fonts && penpot.fonts.findByName
      ? penpot.fonts.findByName("JetBrains Mono")
      : null;
  } catch (e) {
    return null;
  }
})();
function variant(font, weight) {
  try {
    return (
      (font.variants || []).find(
        (v) => String(v.fontWeight) === String(weight) && (v.fontStyle || "normal") === "normal",
      ) || null
    );
  } catch (e) {
    return null;
  }
}
function set(obj, props) {
  for (const k of Object.keys(props)) {
    try {
      obj[k] = props[k];
    } catch (e) {
      warn("set " + k, e);
    }
  }
}
function tag(shape, meta) {
  try {
    shape.setPluginData(TAG, "v1");
    shape.setPluginData(TAG + ":meta", JSON.stringify(meta || {}));
  } catch (e) {
    warn("tag", e);
  }
}
function pad2(n) {
  return (n < 10 ? "0" : "") + n;
}
const NB = " "; // no-break space: joins the words of a chip / pill / button label so no word wraps under its outline
const NBH = "‑"; // non-breaking hyphen: rule ids and compounds never break at the hyphen on a board (n7)
const nb = (s) => String(s).replace(/ /g, NB);
const idh = (s) => String(s).replace(/-/g, NBH);
function estLines(str, w, size, mono) {
  const cpl = Math.max(6, Math.floor(w / (size * (mono ? 0.62 : 0.56))));
  let lines = 0;
  for (const para of String(str).split("\n")) lines += Math.max(1, Math.ceil(para.length / cpl));
  return lines;
}
function estH(str, w, size, mono) {
  // conservative wrap estimate: the wrapped lines plus a 0.4-line margin at line height 1.38, plus 6 px; the relayout pass measures
  return Math.ceil((estLines(str, w, size, mono) + 0.4) * size * 1.38) + 6;
}
let blockSeq = 0;
// ---- the budget (r7): every shape goes through create(); a shape outside the call's part is a plain record (dry), never created in
// Penpot, so every x, y and block id equals the one-call build's. Every shape here sits on its board root, so a unit is any
// contiguous run of the drawing order; unit() opens one at each top-level helper (card, table row, pill, field row, section, …).
let DRY = false,
  CUR_BOARD = null,
  CUR_N = null;
const SPLIT = { plan: null, counts: null, segs: null, idx: 0, dryAll: false };
const BOARD_ROOTS = new WeakSet(); // the marks live here, never as properties on a shape (the plugin API's shapes are not extensible)
const CREATED = []; // every live shape this call created, in order; rollback() removes them when the call throws
const FIT = []; // the planning pass's single-line texts that would wrap in their box, read by selfCheck()
function dryShape(type, txt) {
  return {
    type,
    dry: true,
    unitIdx: SPLIT.idx,
    id: null,
    x: 0,
    y: 0,
    width: 1,
    height: 1,
    name: "",
    text: txt == null ? null : String(txt),
    fills: [],
    strokes: [],
    pd: {},
    resize(w, h) {
      this.width = w;
      this.height = h;
    },
    appendChild() {},
    setPluginData(k, v) {
      this.pd[k] = v;
    },
    getPluginData(k) {
      return this.pd[k];
    },
    remove() {},
  };
}
function create(type, txt) {
  if (SPLIT.counts) SPLIT.counts[SPLIT.idx] = (SPLIT.counts[SPLIT.idx] || 0) + 1;
  if (DRY) return dryShape(type, txt);
  const s =
    type === "text"
      ? penpot.createText(String(txt))
      : type === "rect"
        ? penpot.createRectangle()
        : type === "path"
          ? penpot.createPath()
          : penpot.createBoard();
  if (s) CREATED.push(s);
  return s;
}
function uncreate(s) {
  const i = CREATED.lastIndexOf(s);
  if (i >= 0) CREATED.splice(i, 1);
}
function rollback() {
  // a throw after the first live create removes this call's shapes (last first), so the page is left as it was
  let n = 0;
  for (let i = CREATED.length - 1; i >= 0; i--) {
    try {
      CREATED[i].remove();
      n++;
    } catch (e) {
      warn("rollback", e);
    }
  }
  CREATED.length = 0;
  return n;
}
function rolledBack(e) {
  return new Error(
    (e && e.message ? e.message : String(e)) +
      " — rolled back " +
      rollback() +
      " shape(s) this call created; the old board was not removed",
  );
}
function attach(parent, child) {
  // a dry child is never appended; a live child under a dry parent is a split bug
  if (child.dry) return;
  if (parent.dry)
    throw new Error("part split: a live shape under a dry parent (" + child.name + ")");
  parent.appendChild(child);
}
function unit(parent) {
  // a top-level unit boundary: only a helper drawing straight onto the board opens one
  if (parent !== CUR_BOARD) return;
  SPLIT.idx++;
  DRY = SPLIT.dryAll || (SPLIT.plan ? SPLIT.plan[SPLIT.idx] !== PART : false);
}
function fitW(label, size, mono) {
  // the self-check's width of one line: the shared PILL_EM class sum (an upper bound on Inter's advance; no flat floor), JetBrains Mono at 0.62 em
  if (mono) return String(label).length * size * 0.62;
  let em = 0;
  for (const ch of String(label))
    em += /[A-Z]/.test(ch)
      ? PILL_EM.upper
      : /[mw]/.test(ch)
        ? PILL_EM.wideLower
        : /[a-z]/.test(ch)
          ? PILL_EM.lower
          : /[0-9]/.test(ch)
            ? PILL_EM.digit
            : /[\s.,:;·'’|-]/.test(ch)
              ? PILL_EM.thin
              : PILL_EM.symbol;
  return em * size;
}
function mkText(parent, str, x, y, w, o) {
  o = o || {};
  const t = create("text", str);
  if (!t) {
    warn("createText", "returned null for: " + String(str).slice(0, 40));
    return null;
  }
  t.name = TICKET + " / " + (o.name || "text");
  const size = o.size || 13;
  try {
    const f = o.mono ? MONO : FONT;
    if (f && !t.dry) f.applyToText(t, variant(f, o.weight || 400) || undefined);
  } catch (e) {
    warn("applyToText", e);
  }
  set(t, {
    fontSize: String(size),
    fontWeight: String(o.weight || 400),
    lineHeight: "1.38",
    growType: "auto-height",
    align: o.align || "left",
  });
  const h = estH(str, w, size, !!o.mono);
  t.resize(w, h);
  t.x = x;
  t.y = y;
  t.fills = [{ fillColor: o.color || C.text, fillOpacity: o.dim != null ? o.dim : 1 }]; // o.dim: a dimmed control's label (the validity look) — never a reason text, which stays full-opacity (E30-D02 D3)
  tag(t, {
    role: "text",
    tok: o.tok || TOK.text,
    blk: o.blk,
    stk: o.stk,
    idx: o.idx,
    after: o.after,
    dim: o.dim,
    dimTok: o.dim != null ? o.dimTok || "opacity.disabled" : undefined,
  });
  if (o.single && SPLIT.dryAll && CUR_BOARD) {
    // r7: a single-line text must fit its box at the shared PILL_EM upper bounds (JetBrains Mono 0.62 em)
    const layer = t.name.replace(TICKET + " / ", "");
    for (const ln of String(str).split("\n")) {
      const need = fitW(ln, size, !!o.mono);
      if (need > w + 0.5)
        FIT.push({
          board: CUR_N,
          layer,
          line: ln,
          need: Math.ceil(need),
          box: Math.round(w),
          msg:
            "board " +
            pad2(CUR_N) +
            " " +
            layer +
            " " +
            JSON.stringify(ln) +
            " needs " +
            Math.ceil(need) +
            " px in a " +
            Math.round(w) +
            " px box",
        });
    }
  }
  attach(parent, t);
  return { shape: t, h };
}
function mkRect(parent, x, y, w, h, fillKey, o) {
  o = o || {};
  const r = create("rect");
  r.name = TICKET + " / " + (o.name || "rect");
  r.x = x;
  r.y = y;
  r.resize(w, h);
  r.fills = fillKey
    ? [
        {
          fillColor: C[fillKey],
          fillOpacity: o.dim != null ? o.dim : o.opacity == null ? 1 : o.opacity,
        },
      ]
    : []; // o.dim: the whole control at opacity.disabled (the validity look; VALIDITY)
  if (o.stroke)
    r.strokes = [
      {
        strokeColor: C[o.stroke],
        strokeOpacity: o.dim != null ? o.dim : 1,
        strokeWidth: o.strokeWidth || 1,
        strokeStyle: o.dashed ? "dashed" : "solid",
        strokeAlignment: "inner",
      },
    ];
  if (o.radius) set(r, { borderRadius: o.radius });
  tag(r, {
    role: o.role || "rect",
    tok: fillKey ? TOK[fillKey] : null,
    strokeTok: o.stroke ? TOK[o.stroke] : null,
    blk: o.blk,
    stk: o.stk,
    idx: o.idx,
    bg: !!o.bg,
    pad: o.pad,
    gap: o.gap,
    dim: o.dim,
    dimTok: o.dim != null ? o.dimTok || "opacity.disabled" : undefined,
  });
  attach(parent, r);
  return r;
}
let pathFallback = false; // set once createPath/content fails, so every later connector draws a thin rect without retrying
function mkPolyline(parent, pts, strokeKey, o) {
  // one stroked path through absolute page points; null => the caller draws the rect fallback
  if (pathFallback || typeof penpot.createPath !== "function") {
    pathFallback = true;
    return null;
  }
  if (SPLIT.segs) SPLIT.segs[SPLIT.idx] = (SPLIT.segs[SPLIT.idx] || 0) + pts.length; // one M + one L per further point
  let p = null;
  try {
    p = create("path");
    p.name = TICKET + " / " + (o.name || "connector");
    p.content = pts
      .map((q, i) => (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1))
      .join(" ");
    p.fills = [];
    p.strokes = [
      {
        strokeColor: C[strokeKey],
        strokeOpacity: 1,
        strokeWidth: o.width || 2,
        strokeStyle: "solid",
        strokeAlignment: "center",
      },
    ];
    if (!p.dry && !(p.width > 0 || p.height > 0)) throw new Error("path content not applied");
    tag(p, { role: "wire", tok: TOK[strokeKey], blk: o.blk, stk: o.stk });
    attach(parent, p);
    return p;
  } catch (e) {
    warn("path-fallback (drawing rects instead)", e);
    pathFallback = true;
    try {
      if (p && !p.dry) {
        p.remove();
        uncreate(p);
      }
    } catch (e2) {
      /* nothing to undo */
    }
    return null;
  }
}
function bracket(parent, x, y1, y2, strokeKey, o) {
  // the any-of group's bracket: a 2 px vertical ink flush with the group's first and last row (n5)
  o = o || {};
  if (
    mkPolyline(
      parent,
      [
        [x + 6, y1],
        [x, y1],
        [x, y2],
        [x + 6, y2],
      ],
      strokeKey,
      o,
    )
  )
    return;
  mkRect(parent, x - 1, y1, 2, y2 - y1, strokeKey, { role: "wire", name: o.name || "bracket" });
}
function mkBoard(n, slug, x, y, w, h) {
  const b = create("board");
  BOARD_ROOTS.add(b);
  b.name = TICKET + " / " + pad2(n) + " " + slug;
  b.x = x;
  b.y = y;
  b.resize(w, h);
  b.fills = [{ fillColor: C.canvas, fillOpacity: 1 }];
  set(b, { clipContent: false });
  tag(b, {
    role: "board",
    board: n,
    slug,
    tok: TOK.canvas,
    exportAs: EXPORT_DIR + "/" + TICKET + "-" + pad2(n) + "-" + slug + ".png",
  });
  try {
    b.setPluginData("hpe1ver", VERSION);
  } catch (e) {
    warn("hpe1ver", e);
  }
  return b;
}
// A block = background rect + texts stacked inside; blocks in the same `stk` are re-stacked by the relayout pass.
function card(parent, x, y, w, o) {
  o = o || {};
  unit(parent);
  const pad = 14;
  const blk = TICKET + ":" + ++blockSeq;
  const stk = o.stk || blk;
  let cy = y + pad;
  const push = (txt, opts) => {
    const r = mkText(
      parent,
      txt,
      x + pad,
      cy,
      w - 2 * pad,
      Object.assign({ blk, stk, idx: o.idx }, opts),
    );
    if (r) cy += r.h + (opts.after == null ? 6 : opts.after);
  };
  const bg = mkRect(parent, x, y, w, 10, o.fill || "raised", {
    stroke: o.stroke || "border",
    radius: 8,
    role: "card-bg",
    bg: true,
    pad,
    gap: o.gap == null ? 12 : o.gap,
    blk,
    stk,
    idx: o.idx,
    name: "card",
  });
  if (o.kicker)
    push(o.kicker, {
      size: 11,
      weight: 600,
      color:
        o.kickerColor ||
        (o.fill && o.fill !== "raised" && o.fill !== "canvas" && o.fill !== "hover"
          ? C.text2
          : C.text3),
      tok:
        o.kickerTok ||
        (o.fill && o.fill !== "raised" && o.fill !== "canvas" && o.fill !== "hover"
          ? TOK.text2
          : TOK.text3),
      name: "kicker",
      after: 2,
    }); // m5: never text.tertiary on a status fill
  if (o.title) push(o.title, { size: o.titleSize || 15, weight: 700, name: "title", after: 6 });
  if (o.body) push(o.body, { size: 12.5, color: C.text2, tok: TOK.text2, name: "body", after: 6 });
  if (o.lines)
    for (const ln of o.lines)
      push(ln, { size: 12.5, color: C.text2, tok: TOK.text2, name: "line", after: 4 });
  if (o.foot)
    push(o.foot, {
      size: 11,
      weight: 500,
      color:
        o.fill && o.fill !== "raised" && o.fill !== "canvas" && o.fill !== "hover"
          ? C.text2
          : C.text3,
      tok:
        o.fill && o.fill !== "raised" && o.fill !== "canvas" && o.fill !== "hover"
          ? TOK.text2
          : TOK.text3,
      name: "foot",
      after: 0,
    });
  const h = cy - y + pad - 4;
  bg.resize(w, h);
  return { h, bg, blk, stk };
}
const PILL_EM = { upper: 0.84, wideLower: 0.95, lower: 0.56, digit: 0.68, thin: 0.34, symbol: 1.0 }; // the shared pill-label width rule (orchestrator 2026-10-21 18:21Z; the E13-D02 r7 table): per glyph class, an upper bound on Inter's advance in em
function pillTextW(label, size, mono) {
  // the label box a pill needs: never narrower than the old flat estimate
  const flat = Math.ceil(String(label).length * size * 0.62);
  if (mono) return flat;
  let em = 0;
  for (const ch of String(label))
    em += /[A-Z]/.test(ch)
      ? PILL_EM.upper
      : /[mw]/.test(ch)
        ? PILL_EM.wideLower
        : /[a-z]/.test(ch)
          ? PILL_EM.lower
          : /[0-9]/.test(ch)
            ? PILL_EM.digit
            : /[\s.,:;·'’|-]/.test(ch)
              ? PILL_EM.thin
              : PILL_EM.symbol;
  return Math.max(flat, Math.ceil(em * size));
}
function pill(parent, x, y, label, o) {
  // a chip / badge / pill / button / T2 reason: returns its width; the box fits the label, the words never wrap; o.dim (VALIDITY) draws fill, hairline and label at opacity.disabled — the form-validity look
  o = o || {};
  unit(parent);
  const h = o.h || 22,
    size = o.size || 11;
  const padX = o.padX == null ? 8 : o.padX,
    tw = pillTextW(label, size, !!o.mono),
    w = o.w || tw + 2 * padX; // the shared rule: the box fits the label
  mkRect(parent, x, y, w, h, o.fill || "raised", {
    radius: o.radius == null ? h / 2 : o.radius,
    stroke: o.stroke || "border",
    strokeWidth: o.strokeWidth || 1,
    dashed: o.dashed,
    role: o.role || "pill",
    blk: o.blk,
    stk: o.stk,
    idx: o.idx,
    name: o.name || "pill",
    dim: o.dim,
    dimTok: o.dimTok,
  });
  mkText(
    parent,
    nb(label),
    x + padX,
    y + Math.max(1, (h - size * 1.38) / 2),
    Math.max(tw, w - 2 * padX),
    {
      size,
      weight: o.weight || 500,
      mono: !!o.mono,
      color: o.textColor || C.text,
      tok: o.textTok || TOK.text,
      name: "pill-label",
      blk: o.blk,
      stk: o.stk,
      idx: o.idx,
      dim: o.dim,
      dimTok: o.dimTok,
      single: true,
    },
  );
  return w;
}
function stamp(parent, x, y, word, fillKey) {
  // the PROPOSED / RULED / DECIDED pill at the top of a board
  return pill(parent, x, y, word, {
    h: 24,
    size: 11,
    weight: 700,
    fill: fillKey || "warningSubtle",
    stroke:
      fillKey === "successSubtle"
        ? "successStrong"
        : fillKey === "infoSubtle"
          ? "info"
          : "warningStrong",
    name: "stamp",
  });
}
function tableBlock(parent, x, y, widths, header, rows, o) {
  // row height = the max wrapped height over all cells, label column included
  o = o || {};
  const pad = 8,
    size = o.size || 11.5,
    stk = o.stk || TICKET + ":tbl" + ++blockSeq;
  let cy = y,
    idx = 0;
  const totalW = widths.reduce((a, b) => a + b, 0);
  const drawRow = (cells, isHeader) => {
    unit(parent);
    const blk = TICKET + ":" + ++blockSeq;
    let est = 0;
    for (let i = 0; i < cells.length; i++)
      est = Math.max(est, estH(cells[i], widths[i] - 2 * pad, size));
    mkRect(
      parent,
      x,
      cy,
      totalW,
      est + 2 * pad,
      isHeader ? "hover" : idx % 2 ? "raised" : "canvas",
      {
        role: "row-bg",
        bg: true,
        pad,
        gap: 0,
        blk,
        stk,
        idx,
        stroke: "border",
        name: isHeader ? "table-header" : "table-row",
      },
    );
    let cx = x;
    for (let i = 0; i < cells.length; i++) {
      mkText(parent, cells[i], cx + pad, cy + pad, widths[i] - 2 * pad, {
        size,
        weight: isHeader ? 700 : i === 0 ? 600 : 400,
        color: isHeader ? C.text : i === 0 ? C.text : C.text2,
        tok: isHeader || i === 0 ? TOK.text : TOK.text2,
        blk,
        stk,
        idx,
        name: isHeader ? "th" : "td",
      });
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
  unit(parent);
  const a = mkText(parent, t, x, y, w, { size: 24, weight: 700, name: "board-title" });
  let h = a ? a.h : 30;
  if (sub) {
    const b = mkText(parent, sub, x, y + h + 2, w, {
      size: 12.5,
      color: C.text2,
      tok: TOK.text2,
      name: "board-subtitle",
    });
    h += (b ? b.h : 16) + 2;
  }
  return h + 10;
}
function column(parent, x, y, w, items, stkName, fill) {
  // items: card options; returns the bottom y
  let cy = y,
    idx = 0;
  const stk = TICKET + ":" + stkName;
  for (const it of items) {
    const c = card(parent, x, cy, w, Object.assign({ stk, idx: idx++, fill }, it));
    cy += c.h + 12;
  }
  return cy;
}
function grid(parent, x, y, w, items, cols, stkName) {
  // cards column-major in `cols` aligned columns (n14): item i goes to column floor(i / rows)
  const gap = 24,
    cw = (w - (cols - 1) * gap) / cols,
    per = Math.ceil(items.length / cols);
  const ys = [];
  for (let c = 0; c < cols; c++) ys.push(y);
  for (let i = 0; i < items.length; i++) {
    const col = Math.floor(i / per);
    const c = card(
      parent,
      x + col * (cw + gap),
      ys[col],
      cw,
      Object.assign({ stk: TICKET + ":" + stkName + col, idx: i % per }, items[i]),
    );
    ys[col] += c.h + 12;
  }
  return Math.max.apply(null, ys) - 12;
}

// ---------------------------------------------------------------- screen chrome (boards 01–03, 09–11) --------
// A composed SCR-081 frame: the DEMO band, the header (name, status word, Form | Graph, the indicator chip, "v3 · Last saved"),
// the sentence block with the scope chip, then the five sections as the caller draws them, CMP-158 and the sticky action bar.
function band(parent, x, y, w, live) {
  // the chrome's environment band: never colour-only — the word is the signal (14 §0.5 item 1)
  unit(parent);
  mkRect(parent, x, y, w, 24, live ? "dangerSubtle" : "infoSubtle", {
    role: "band",
    name: "env-band",
  });
  pill(parent, x + 12, y + 2, live ? "LIVE" : "DEMO", {
    h: 20,
    size: 10.5,
    weight: 700,
    fill: live ? "dangerSubtle" : "infoSubtle",
    stroke: live ? "dangerStrong" : "info",
    name: "env-badge",
  });
  mkText(
    parent,
    live ? "Live trading — real orders" : "Demo trading — no real orders",
    x + 84,
    y + 4,
    300,
    { size: 11, color: C.text2, tok: TOK.text2, name: "env-text", single: true },
  );
}
function indicatorChip(parent, x, y, state, o) {
  // the round-trip indicator: fill + glyph + word, never colour alone (spec §4)
  o = o || {};
  const S = {
    identical: {
      fill: "successSubtle",
      stroke: "successStrong",
      glyph: "✓",
      word: "Round-trips ✓",
    },
    graph_only_construct: {
      fill: "warningSubtle",
      stroke: "warningStrong",
      glyph: "⚠",
      word: "Graph-only construct — read-only here",
    },
    mismatch: {
      fill: "dangerSubtle",
      stroke: "dangerStrong",
      glyph: "✕",
      word: "Round-trip mismatch",
    },
    unverified: { fill: "hover", stroke: "border", glyph: "?", word: "Not verified" },
    checking: { fill: "hover", stroke: "border", glyph: "", word: "Checking…" },
  }[state];
  const label =
    (S.glyph ? S.glyph + " " : "") +
    S.word.replace("Round-trips ✓", "Round-trips") +
    (o.stale ? " · since your last save" : "");
  return pill(parent, x, y, label, {
    h: 24,
    size: 11.5,
    weight: 600,
    fill: S.fill,
    stroke: S.stroke,
    name: "indicator-" + state,
    textColor: C.text,
    textTok: TOK.text,
  });
}
function header(parent, x, y, w, o) {
  // returns the bottom y; o: {name, status, indicator, stale, sentence, chip, live}
  o = o || {};
  unit(parent);
  const t = mkText(parent, o.name || "BE after 1R", x, y, 420, {
    size: 18,
    weight: 700,
    name: "rule-name",
  });
  let cx = x + 440;
  cx +=
    pill(parent, cx, y + 2, o.status || "DRAFT", {
      h: 24,
      size: 11,
      weight: 700,
      fill: "hover",
      name: "status-word",
    }) + 12;
  cx +=
    pill(parent, cx, y + 2, "Form", {
      h: 24,
      size: 11.5,
      weight: 600,
      fill: "selected",
      stroke: "borderSelected",
      radius: 6,
      name: "mode-form",
    }) + 2;
  cx +=
    pill(parent, cx, y + 2, "Graph", {
      h: 24,
      size: 11.5,
      weight: 500,
      fill: "raised",
      radius: 6,
      name: "mode-graph",
      textColor: C.text2,
      textTok: TOK.text2,
    }) + 12;
  cx += indicatorChip(parent, cx, y + 2, o.indicator || "identical", { stale: o.stale }) + 12;
  mkText(parent, "v3 · Last saved 13:42:10 UTC", cx, y + 6, 220, {
    size: 11,
    color: C.text3,
    tok: TOK.text3,
    name: "saved-caption",
    single: true,
  });
  const sy = y + (t ? t.h : 26) + 10;
  const s = mkText(parent, o.sentence || S1, x, sy, w - 300, {
    size: 13,
    name: "sentence",
    color: C.text,
    tok: TOK.text,
  });
  pill(parent, x + w - 280, sy, o.chip || "2 accounts · BTCUSDT · new positions", {
    h: 22,
    size: 11,
    fill: "hover",
    name: "scope-chip",
  });
  return sy + (s ? s.h : 40) + 8;
}
function section(parent, x, y, w, legend, rowsDraw) {
  // a fieldset: legend + the caller's rows; returns the bottom y
  unit(parent);
  const lg = mkText(parent, legend, x, y, w, {
    size: 12,
    weight: 700,
    color: C.text2,
    tok: TOK.text2,
    name: "legend",
  });
  mkRect(parent, x, y + (lg ? lg.h : 18) + 2, w, 1, "border", {
    role: "rule",
    name: "legend-rule",
  });
  let cy = y + (lg ? lg.h : 18) + 10;
  cy = rowsDraw(cy) || cy;
  return cy + 12;
}
function fieldRow(parent, x, y, w, label, controls, o) {
  // one 24 px compact row: a 160 px label column then controls as pills; returns the bottom y
  o = o || {};
  unit(parent);
  mkText(parent, label, x, y + 4, NUM.labelColumn - 8, {
    size: 12,
    color: C.text2,
    tok: TOK.text2,
    name: "field-label",
    single: true,
  });
  let cx = x + NUM.labelColumn;
  for (const c of controls) {
    const opts = Object.assign(
      { h: NUM.rowCompact, size: 11.5, fill: "raised", name: "control" },
      typeof c === "string" ? {} : c,
    );
    cx += pill(parent, cx, y, typeof c === "string" ? c : c.label, opts) + 8;
  }
  if (o.fragment) {
    const f = mkText(
      parent,
      o.fragment,
      x + NUM.labelColumn,
      y + NUM.rowCompact + 2,
      w - NUM.labelColumn,
      { size: 11.5, color: C.text2, tok: TOK.text2, name: "fragment" },
    );
    return y + NUM.rowCompact + 2 + (f ? f.h : 16) + 4;
  }
  return y + NUM.rowCompact + 8;
}
const T2 = { fill: "raised", stroke: "border", textColor: C.text3, textTok: TOK.text3 }; // E09-D09 §2.2: the enabled fill goes — color.surface.raised with a color.border.default hairline; the full label in color.text.tertiary, led by the lock
const LOCK = "🔒 "; // the colour emoji U+1F512 stands in for CMP-019 lock on every T2 control (glyphNote)
const DIM = 0.45; // opacity.disabled (packages/ui/tokens/primitives.tokens.json at the base) — the form-validity look, E30-D02 D3: "disabled = opacity.disabled on the control with the reason as full-opacity text under it, never inside it" (spec §1). The control keeps its own variant fill and full label; fill, hairline and label are drawn at this opacity (the board's rendering of CSS opacity on the control); the reason text stays full-opacity color.text.secondary in its own validity-reason layer; no lock, no CMP-079, no key (E09-D09 §9.1); never the T2 fill
const VALIDITY = { dim: DIM, dimTok: "opacity.disabled" }; // spread into a pill's options for a control disabled by form validity (Save draft / Arm… on 02-4; board 07's two validity rows)
function glyphNote(parent, x, y, w) {
  // the stand-in named on the board (the E09-D09 boards' DS-4 note); returns its height
  const g = mkText(
    parent,
    "Glyph note: the 🔒 on every T2 control of these boards is the colour emoji U+1F512, a stand-in for the CMP-019 lock glyph, which the built control draws in color.text.tertiary — the label's colour (E09-D09 §2.2)",
    x,
    y,
    w,
    { size: 10.5, color: C.text3, tok: TOK.text3, name: "glyph-note" },
  );
  return g ? g.h : 16;
}
function actionBar(parent, x, y, w, o) {
  // CMP-158 pinned above the sticky action bar (spec §2); returns the bottom y. o: a *Reason draws the T2 pill with its inline reason (2a); a *Locked draws the T2 pill alone — its aria-describedby → the frame's one notice (02-5 / 02-6 / view-as, E09-D09 §2.2 one notice, many pointers); a *Validity draws the control disabled by form validity in E30-D02 D3's look — its own variant fill and full label at opacity.disabled (VALIDITY), aria-disabled, the inline reason full-opacity in a validity-reason layer; NO lock, no CMP-079, no key and never the T2 fill (E09-D09 §9.1; spec §1, §3)
  o = o || {};
  const n = card(parent, x, y, w, {
    fill: "infoSubtle",
    stroke: "info",
    kicker: 'CMP-158 · role="note" · non-dismissible',
    title:
      "Every position keeps a native stop — you can move it, not delete it. Rules can tighten it, never remove it — the stop is held by the exchange, not by this app.",
    titleSize: 12.5,
  });
  const by = y + n.h + 8;
  mkRect(parent, x, by, w, NUM.actionBar, "raised", {
    stroke: "border",
    role: "action-bar",
    name: "action-bar",
  });
  let cx = x + 12;
  const py = by + (NUM.actionBar - NUM.rowCompact) / 2;
  const vT2 = !!(o.validateReason || o.validateLocked);
  cx +=
    pill(
      parent,
      cx,
      py,
      (vT2 ? LOCK : "") + "Validate",
      vT2
        ? Object.assign(
            { h: NUM.rowCompact, size: 12, weight: 600, radius: 6, name: "btn-validate-t2" },
            T2,
          )
        : {
            h: NUM.rowCompact,
            size: 12,
            fill: "raised",
            stroke: "borderStrong",
            radius: 6,
            name: "btn-validate",
          },
    ) + 8;
  const sT2 = !!o.simulateLocked;
  cx +=
    pill(
      parent,
      cx,
      py,
      (sT2 ? LOCK : "") + "Simulate",
      sT2
        ? Object.assign(
            { h: NUM.rowCompact, size: 12, weight: 600, radius: 6, name: "btn-simulate-t2" },
            T2,
          )
        : {
            h: NUM.rowCompact,
            size: 12,
            fill: "raised",
            stroke: "borderStrong",
            radius: 6,
            name: "btn-simulate",
          },
    ) + 8;
  const saveT2 = !!(o.saveReason || o.saveLocked),
    saveV = !saveT2 && !!o.saveValidity; // a T2 leg outranks form validity (E09-D09 §2.1: the first missing leg decides)
  cx +=
    pill(
      parent,
      cx,
      py,
      (saveT2 ? LOCK : "") + "Save draft",
      saveT2
        ? Object.assign(
            { h: NUM.rowCompact, size: 12, weight: 600, radius: 6, name: "btn-save-t2" },
            T2,
          )
        : Object.assign(
            {
              h: NUM.rowCompact,
              size: 12,
              weight: 600,
              fill: "primary",
              stroke: "primary",
              radius: 6,
              textColor: C.onAction,
              textTok: TOK.onAction,
              name: saveV ? "btn-save-validity" : "btn-save",
            },
            saveV ? VALIDITY : {},
          ),
    ) + 8; // the primary variant kept, dimmed to opacity.disabled while the form is invalid (E30-D02 D3)
  const armT2 = !!(o.armReason || o.armLocked),
    armV = !armT2 && !!o.armValidity;
  const armOpts = armT2
    ? Object.assign({ h: NUM.rowCompact, size: 12, weight: 600, radius: 6, name: "btn-arm-t2" }, T2)
    : Object.assign(
        o.live
          ? {
              h: NUM.rowCompact,
              size: 12,
              weight: 600,
              fill: "danger",
              stroke: "danger",
              radius: 6,
              textColor: C.onAction,
              textTok: TOK.onAction,
              name: armV ? "btn-arm-validity" : "btn-arm-live",
            }
          : {
              h: NUM.rowCompact,
              size: 12,
              weight: 600,
              fill: "primary",
              stroke: "primary",
              radius: 6,
              textColor: C.onAction,
              textTok: TOK.onAction,
              name: armV ? "btn-arm-validity" : "btn-arm",
            },
        armV ? VALIDITY : {},
      ); // CMP-001 primary on demo; the destructive class (danger + the typed confirm) only when the scope includes live (CMP-145 A11y; BQ-7); the same variant dimmed to opacity.disabled while form validity holds (E30-D02 D3)
  cx += pill(parent, cx, py, (armT2 ? LOCK : "") + (o.armLabel || "Arm…"), armOpts) + 12;
  const distinct = (r, i, a) => r && a.indexOf(r) === i;
  const t2Reasons = [o.armReason, o.saveReason, o.validateReason].filter(distinct),
    vReasons = [o.armValidity, o.saveValidity].filter(distinct); // every distinct inline reason — the T2 ones and the form-validity ones in their own layers (02-4 carries two validity reasons)
  let rx = cx;
  const avail = w - (cx - x) - 12;
  if (t2Reasons.length) {
    const t2s = t2Reasons.join(" · ");
    const t2W = vReasons.length ? Math.min(avail, Math.ceil(t2s.length * 11.5 * 0.56) + 8) : avail; // no frame mixes the two today; a mixed bar would place the validity layer after the T2 one
    mkText(parent, t2s, rx, py + 4, t2W, {
      size: 11.5,
      color: C.text2,
      tok: TOK.text2,
      name: "t2-reason",
      single: true,
    });
    rx += t2W + 12;
  }
  if (vReasons.length)
    mkText(parent, vReasons.join(" · "), rx, py + 4, Math.max(40, w - (rx - x) - 12), {
      size: 11.5,
      color: C.text2,
      tok: TOK.text2,
      name: "validity-reason",
      single: true,
    }); // full-opacity color.text.secondary beside the dimmed control, never inside its label (E30-D02 D3)
  return by + NUM.actionBar;
}
const S1 =
  "When a 1m bar closes on BTCUSDT (Main), if unrealised R is at least 1.0 and the position is long: move the stop to break-even (your average entry) plus 2 ticks and tag the journal be-moved. Once per position. The stop only ever tightens.";
const S2 =
  "When a 1m bar closes on BTCUSDT (Main), if the position is long and either the spread is above 8 bps or tape speed is above 3 sigma: tighten the stop to 2.0 × ATR(14) from the close. At most every 60 s. The stop only ever tightens.";
const S3 =
  "When a trade prints on BTCUSDT (Main), if the price is in a stop-hunt zone (estimated) and unrealised R is at least 0.5: move the stop to break-even (your average entry) plus 2 ticks and notify me (push, high). Once per position. Uses an estimated detector — behaviour is heuristic. The stop only ever tightens.";

// ---------------------------------------------------------------- content -----------------------------------
const SRC =
  "Source: docs/design/E36/E36-D02.md · every statement (heuristic); no participant, no session, no screen-reader run · every default PROPOSED; BQ-1..7 RULED (main-orchestrator, [LANE-46] 2026-10-22); the grouping model DECIDED by the shipped form subset · boards BLOCKED-PENPOT until drawn · revision " +
  VERSION;
const boards = [];
const built = [];
const GX = 0,
  GY = 0,
  GAP = 160,
  W_BOARD = 1840,
  GAPY = 40;
let nextX = GX;
function place(n, slug, w, h) {
  // part 1 (or a whole board) creates the board root; a later part attaches to the board part 1 built
  let b = null;
  if (PART > 1 && !SPLIT.dryAll) {
    const nm = norm(TICKET + "/" + pad2(n) + " " + slug);
    b = (page.root.children || []).find((s) => s.type === "board" && norm(s.name) === nm) || null;
    if (!b)
      throw new Error(
        "part " +
          PART +
          ": board " +
          pad2(n) +
          " is not on the page; run PART = 1 first (nothing of this part was drawn)",
      );
  } else b = mkBoard(n, slug, nextX, GY, w, h);
  nextX += w + GAP;
  boards.push(b);
  CUR_BOARD = b;
  CUR_N = n;
  return b;
}
function finish(b, bottom) {
  // every board ends with a footer line 24 px under its content; the board is sized to the footer, never to the pre-set height
  unit(b);
  const meta = JSON.parse(b.getPluginData(TAG + ":meta"));
  const fy = bottom + 24;
  const f = mkText(
    b,
    "page " + PAGE_NAME.split(" ")[0] + " · board " + pad2(meta.board) + " · " + VERSION,
    b.x + 32,
    fy,
    600,
    { size: 10.5, color: C.text3, tok: TOK.text3, name: "footer" },
  );
  b.resize(b.width, fy + (f ? f.h : 18) + 24 - b.y);
  built.push({ n: meta.board, name: b.name, id: b.id, exportAs: meta.exportAs });
}
const want = (n) => !ONLY || ONLY.indexOf(n) >= 0;

// ---- idempotent: remove this ticket's OWN frames for the boards about to be built (normalised name, this page only) — r7: only after the new board is drawn
const planned = BOARDS.filter((bd) => want(bd.n)).map((bd) =>
  norm(TICKET + "/" + pad2(bd.n) + " " + bd.slug),
);
const removed = [];
function oldPlanned() {
  // this ticket's planned boards on the page before the draw (a whole board, or its part 1)
  const out = [];
  for (const s of (page.root.children || []).slice()) {
    try {
      if (s.type === "board" && planned.indexOf(norm(s.name)) >= 0) out.push(s);
    } catch (e) {
      warn("clear", e);
    }
  }
  return out;
}
function clearPlanned(olds) {
  // runs only after the new board is drawn, on the boards found before the draw
  for (const s of olds) {
    try {
      if (s.type !== "board") continue;
      const nm = norm(s.name);
      if (!nm.startsWith(TICKET + "/")) continue;
      if (planned.indexOf(nm) >= 0) {
        removed.push({
          name: s.name,
          id: s.id,
          hpe1ver: s.getPluginData ? s.getPluginData("hpe1ver") : null,
        });
        s.remove();
      }
    } catch (e) {
      warn("clear", e);
    }
  }
}

// ---- the plan, the guard, the self-check, the draw (r7) ----
const BUILD = {};
const partPlan = [],
  PLANS = {};
function planBoard(n) {
  // a dry pass of one board: shapes and segments per unit, then the units packed in drawing order into parts within both budgets
  const save = {
    nextX,
    blockSeq,
    boards: boards.length,
    built: built.length,
    warnings: warnings.length,
    CUR_BOARD,
    CUR_N,
  };
  SPLIT.plan = null;
  SPLIT.dryAll = true;
  SPLIT.counts = [0];
  SPLIT.segs = [0];
  SPLIT.idx = 0;
  DRY = true;
  try {
    BUILD[n]();
  } finally {
    nextX = save.nextX;
    blockSeq = save.blockSeq;
    boards.length = save.boards;
    built.length = save.built;
    warnings.length = save.warnings;
    CUR_BOARD = save.CUR_BOARD;
    CUR_N = save.CUR_N;
  }
  const counts = SPLIT.counts.map((c) => c || 0),
    segs = counts.map((_, i) => SPLIT.segs[i] || 0),
    plan = [],
    perPart = [],
    segPart = [];
  let part = 1,
    acc = 0,
    accS = 0;
  counts.forEach((c, i) => {
    if (c > SHAPE_BUDGET || segs[i] > SEG_BUDGET)
      throw new Error(
        "budget: board " +
          pad2(n) +
          " unit " +
          i +
          " alone has " +
          c +
          " shapes / " +
          segs[i] +
          " segments; nothing was touched",
      );
    if (acc + c > SHAPE_BUDGET || accS + segs[i] > SEG_BUDGET) {
      part++;
      acc = 0;
      accS = 0;
    }
    plan[i] = part;
    acc += c;
    accS += segs[i];
    perPart[part - 1] = acc;
    segPart[part - 1] = accS;
  });
  SPLIT.dryAll = false;
  SPLIT.counts = null;
  SPLIT.segs = null;
  SPLIT.idx = 0;
  DRY = false;
  PLANS[n] = plan;
  partPlan.push({ board: n, parts: part, shapes: perPart, segs: segPart });
}
function drawBoard(n) {
  // the whole board (PART null) or part PART of it; the shapes of the other parts stay dry
  SPLIT.plan = PART ? PLANS[n] : null;
  SPLIT.counts = null;
  SPLIT.segs = null;
  SPLIT.idx = 0;
  SPLIT.dryAll = false;
  DRY = SPLIT.plan ? SPLIT.plan[0] !== PART : false;
  BUILD[n]();
  SPLIT.plan = null;
  DRY = false;
  CUR_BOARD = null;
  CUR_N = null;
}
const GATE = { selfCheck: null, knownWraps: [], pageSegs: 0 };
function selfCheck(wanted) {
  // the pre-export self-check on the planning pass's record; throws before the clear and before any shape is drawn
  const fail = [],
    known = [];
  for (const f of FIT) {
    if (wanted.indexOf(f.board) < 0) continue;
    const isKnown = KNOWN_WRAPS.some(
      (k) => k[0] === f.board && k[1] === f.layer && k[2] === f.line,
    );
    (isKnown ? known : fail).push("wraps: " + f.msg);
  }
  GATE.knownWraps = known;
  if (fail.length) throw new Error("SELF-CHECK: " + fail.join("; ") + "; nothing was touched");
  return known.length ? "ok · " + known.length + " known wrap(s) warned (KNOWN_WRAPS)" : "ok";
}
function gate(wanted) {
  // the plan, the self-check and the guard, before the clear: returns an abort object, throws, or returns null (go)
  if (PART !== null && (!Number.isInteger(PART) || PART < 0))
    throw new Error("PART must be null, 0 or a positive integer; nothing was touched");
  if (PART !== null && PART !== 0 && wanted.length !== 1)
    return {
      abort: "part",
      version: VERSION,
      note: "PART k needs exactly one board in ONLY; nothing was touched",
    };
  for (const bd of BOARDS) planBoard(bd.n); // every board: the page's segment total; the guard reads the wanted ones
  GATE.pageSegs = partPlan.reduce((a, p) => a + p.segs.reduce((x, y) => x + y, 0), 0);
  const wp = partPlan.filter((p) => wanted.indexOf(p.board) >= 0);
  GATE.selfCheck = selfCheck(wanted);
  if (PART === 0)
    return {
      version: VERSION,
      budget: { shapes: SHAPE_BUDGET, segs: SEG_BUDGET, pageSegs: PAGE_SEG_BUDGET },
      partPlan: wp,
      pageSegs: GATE.pageSegs,
      selfCheck: GATE.selfCheck,
      knownWraps: GATE.knownWraps,
      warnings,
    };
  if (GATE.pageSegs > PAGE_SEG_BUDGET)
    throw new Error(
      "budget: the page would hold " +
        GATE.pageSegs +
        " path segments (over " +
        PAGE_SEG_BUDGET +
        "); nothing was touched",
    );
  if (PART && PART > wp[0].parts)
    return {
      abort: "part",
      version: VERSION,
      partPlan: wp,
      note: "board " + pad2(wanted[0]) + " has " + wp[0].parts + " part(s); nothing was touched",
    };
  const sum = (k) => wp.reduce((a, p) => a + p[k].reduce((x, y) => x + y, 0), 0);
  const callShapes = PART ? wp[0].shapes[PART - 1] : sum("shapes"),
    callSegs = PART ? wp[0].segs[PART - 1] : sum("segs");
  if (!HARNESS && (callShapes > SHAPE_BUDGET || callSegs > SEG_BUDGET))
    throw new Error(
      "budget: this call would create " +
        callShapes +
        " shapes / " +
        callSegs +
        " segments (over " +
        SHAPE_BUDGET +
        " / " +
        SEG_BUDGET +
        "); set ONLY = [n] and PART = 1 … k per the part plan " +
        JSON.stringify(wp) +
        "; nothing was touched",
    );
  return null;
}
function nextStep(wanted) {
  return PART && PART < partPlan.filter((p) => p.board === wanted[0])[0].parts
    ? "board " +
        pad2(wanted[0]) +
        ": run PART = " +
        (PART + 1) +
        " next (ONLY = [" +
        wanted[0] +
        "]); the relayout only after the last part"
    : 'e36-d02-relayout.js PASS="measure" → PASS="restack" (until moved=0) → e36-d02-dedupe.js → probe.js until every instance agrees → export';
}

// A composed SCR-081 screen (1920 wide): returns the bottom y. o: header options + {rows, actions, options, banner, armReason, saveReason, validateReason, armLabel, readOnlyCard, bannerFill,
// pickersDisabled (02-6: the vocabulary pickers and the add buttons T2 → the banner), readOnly (02-5: values as read-only text, every editing affordance T2 → the notice), saveLocked / armLocked / validateLocked / simulateLocked,
// armValidity / saveValidity (02-4: disabled by form validity — the control's own fill and full label at opacity.disabled, aria-disabled, the reason full-opacity beside it; no lock, no CMP-079; E09-D09 §9.1, E30-D02 D3)}
function scr081(b, X, Y, W, o) {
  o = o || {};
  unit(b);
  band(b, X, Y, W, !!o.live);
  const colX = X + (W - NUM.column) / 2,
    colW = NUM.column;
  let y = Y + 24 + 16;
  if (o.banner) {
    const bn = card(b, colX, y, colW, {
      fill: o.bannerFill || "dangerSubtle",
      stroke: o.bannerFill === "warningSubtle" ? "warningStrong" : "dangerStrong",
      kicker:
        o.bannerKicker ||
        'CMP-028 · role="alert" · announced once · the one notice — every gated control\'s aria-describedby points here',
      title: o.banner,
      titleSize: 12.5,
    });
    y += bn.h + 12;
  }
  y = header(b, colX, y, colW, o);
  if (o.armedLine) {
    const al = card(b, colX, y, colW, {
      fill: "infoSubtle",
      stroke: "info",
      kicker:
        'CMP-028 · role="status" · the one notice — every gated control\'s aria-describedby points here',
      title: o.armedLine,
      titleSize: 12.5,
    });
    y += al.h + 8;
    let bx = colX + 14;
    bx +=
      pill(b, bx, y, "Disarm to edit", {
        h: NUM.rowCompact,
        size: 12,
        weight: 600,
        fill: "raised",
        stroke: "borderStrong",
        radius: 6,
        name: "btn-disarm-to-edit",
      }) + 8;
    pill(b, bx, y, "Edit as a new draft version", {
      h: NUM.rowCompact,
      size: 12,
      weight: 600,
      fill: "primary",
      stroke: "primary",
      radius: 6,
      textColor: C.onAction,
      textTok: TOK.onAction,
      name: "btn-new-draft",
    });
    y += NUM.rowCompact + 12;
  }
  const gated = !!(o.pickersDisabled || o.readOnly);
  const pick = (label) =>
    Object.assign({ label: (o.pickersDisabled ? LOCK : "") + label }, o.pickersDisabled ? T2 : {}); // a vocabulary picker's trigger button (the metric / trigger / action)
  const roRow = (cy, labelText, text, fragment, menu) => {
    // 02-5: the values as read-only text in color.text.primary (aria-readonly); the row menu T2 → the notice (icon-only: the tooltip echo)
    mkText(b, labelText, colX, cy + 4, NUM.labelColumn - 8, {
      size: 12,
      color: C.text2,
      tok: TOK.text2,
      name: "field-label",
    });
    mkText(b, text, colX + NUM.labelColumn, cy + 4, colW - NUM.labelColumn - 80, {
      size: 12,
      color: C.text,
      tok: TOK.text,
      name: "readonly-value",
    });
    if (menu)
      pill(
        b,
        colX + colW - 60,
        cy,
        LOCK + "⋯",
        Object.assign({ h: NUM.rowCompact, size: 11.5, padX: 6, name: "row-menu-t2" }, T2),
      );
    if (fragment) {
      const f = mkText(
        b,
        fragment,
        colX + NUM.labelColumn,
        cy + NUM.rowCompact + 2,
        colW - NUM.labelColumn,
        { size: 11.5, color: C.text2, tok: TOK.text2, name: "fragment" },
      );
      return cy + NUM.rowCompact + 2 + (f ? f.h : 16) + 4;
    }
    return cy + NUM.rowCompact + 8;
  };
  y = section(b, colX, y, colW, "Scope", (cy) => {
    if (o.readOnly) {
      cy = roRow(cy, "Symbol", "BTCUSDT", null, false);
      cy = roRow(cy, "Accounts", "Main · Alt", null, false);
      return roRow(cy, "Applies to", "any", null, false);
    }
    cy = fieldRow(b, colX, cy, colW, "Symbol", [{ label: "BTCUSDT" }]);
    cy = fieldRow(b, colX, cy, colW, "Accounts", [{ label: "Main" }, { label: "Alt" }]);
    return fieldRow(b, colX, cy, colW, "Applies to", [
      { label: "◉ any", fill: "selected", stroke: "borderSelected" },
      "○ open positions",
      "○ pending orders",
      "○ the account",
    ]);
  });
  y = section(b, colX, y, colW, "Trigger", (cy) =>
    o.readOnly
      ? roRow(
          cy,
          "When",
          (o.trigger || "a bar closes") + " · " + (o.timeframe || "1m"),
          null,
          false,
        )
      : fieldRow(
          b,
          colX,
          cy,
          colW,
          "When",
          [pick(o.trigger || "a bar closes"), pick(o.timeframe || "1m")],
          { fragment: o.triggerDesc || "When a bar closes · timeframe 1m" },
        ),
  );
  y = section(b, colX, y, colW, "Conditions — all of", (cy) => {
    if (o.estimatedBanner) {
      const eb = card(b, colX, cy, colW, {
        fill: "warningSubtle",
        stroke: "warningStrong",
        kicker: 'CMP-028 · role="status" · callout',
        title: "This rule depends on an estimated detector — behaviour is heuristic.",
        titleSize: 12.5,
      });
      cy += eb.h + 10;
    }
    for (const r of o.rows || []) {
      const labelText = "Condition " + r.n + " of " + (o.rows || []).length;
      if (o.readOnly) {
        cy = roRow(
          cy,
          labelText,
          r.metric + (r.chip ? " (estimated)" : "") + " · " + r.op + " · " + r.value,
          r.fragment,
          true,
        );
        continue;
      }
      const controls = [pick(r.metric)];
      if (r.chip)
        controls.push({ label: "(estimated)", fill: "infoSubtle", stroke: "info", size: 10.5 });
      controls.push(
        { label: r.op },
        { label: r.value, mono: true },
        { label: "⋯", w: NUM.rowCompact, padX: 6 },
      );
      if (r.invalid)
        mkRect(
          b,
          colX + NUM.labelColumn - 6,
          cy - 3,
          colW - NUM.labelColumn + 6,
          NUM.rowCompact + 6,
          null,
          {
            stroke: "danger",
            strokeWidth: NUM.bracketPx,
            radius: 6,
            role: "invalid-outline",
            name: "invalid-outline",
          },
        );
      cy = fieldRow(b, colX, cy, colW, labelText, controls, { fragment: r.fragment });
    }
    if (o.readOnlyCard) {
      const rc = card(b, colX + NUM.labelColumn, cy, colW - NUM.labelColumn, {
        fill: "warningSubtle",
        stroke: "warningStrong",
        kicker: "⚠ read‑only · Authored in the graph editor",
        title:
          "Authored in the graph editor: none of: the spread is above 8 bps, tape speed is above 3 sigma. Open in the graph editor to change this.",
        titleSize: 12.5,
        foot: "Open in the graph editor →",
      });
      cy += rc.h + 8;
    }
    let cx = colX + NUM.labelColumn;
    cx +=
      pill(
        b,
        cx,
        cy,
        (gated ? LOCK : "") + "+ condition",
        gated
          ? Object.assign(
              { h: NUM.rowCompact, size: 11.5, radius: 6, name: "add-condition-t2" },
              T2,
            )
          : {
              h: NUM.rowCompact,
              size: 11.5,
              fill: "raised",
              stroke: "borderStrong",
              radius: 6,
              name: "add-condition",
            },
      ) + 8;
    pill(
      b,
      cx,
      cy,
      (gated ? LOCK : "") + "+ any-of group",
      gated
        ? Object.assign({ h: NUM.rowCompact, size: 11.5, radius: 6, name: "add-group-t2" }, T2)
        : {
            h: NUM.rowCompact,
            size: 11.5,
            fill: "raised",
            stroke: "borderStrong",
            radius: 6,
            name: "add-group",
          },
    );
    return cy + NUM.rowCompact + 8;
  });
  y = section(b, colX, y, colW, "Actions", (cy) => {
    for (const a of o.actions || []) {
      const labelText = "Action " + a.n + " of " + (o.actions || []).length;
      if (o.readOnly) {
        cy = roRow(cy, labelText, [a.name].concat(a.params || []).join(" · "), a.fragment, true);
        continue;
      }
      cy = fieldRow(
        b,
        colX,
        cy,
        colW,
        labelText,
        [pick(a.name)].concat((a.params || []).map((p) => ({ label: p, mono: true }))),
        { fragment: a.fragment },
      );
    }
    pill(
      b,
      colX + NUM.labelColumn,
      cy,
      (gated ? LOCK : "") + "+ action",
      gated
        ? Object.assign({ h: NUM.rowCompact, size: 11.5, radius: 6, name: "add-action-t2" }, T2)
        : {
            h: NUM.rowCompact,
            size: 11.5,
            fill: "raised",
            stroke: "borderStrong",
            radius: 6,
            name: "add-action",
          },
    );
    return cy + NUM.rowCompact + 8;
  });
  y = section(b, colX, y, colW, "Options", (cy) => {
    cy = o.readOnly
      ? roRow(cy, "Once per", "position · cooldown 1 s · 60 / h · 500 / day", null, false)
      : fieldRow(b, colX, cy, colW, "Once per", [
          { label: "position" },
          { label: "cooldown 1 s", mono: true },
          { label: "60 / h · 500 / day", mono: true },
        ]);
    const l1 = mkText(
      b,
      "No rule notional cap — your account's risk caps still apply. · Turns itself off after 5 errors in a row — you re-arm it.",
      colX + NUM.labelColumn,
      cy,
      colW - NUM.labelColumn,
      { size: 11.5, color: C.text2, tok: TOK.text2, name: "always-said" },
    );
    return cy + (l1 ? l1.h : 16) + 4;
  });
  if (o.validation) {
    const v = card(b, colX, y, colW, {
      fill: "dangerSubtle",
      stroke: "dangerStrong",
      kicker: 'CMP-234 · role="log" · errors first · ' + o.validation.heading,
      lines: o.validation.lines,
      titleSize: 12.5,
    });
    y += v.h + 12;
  }
  return actionBar(b, colX, y, colW, {
    armReason: o.armReason,
    saveReason: o.saveReason,
    validateReason: o.validateReason,
    armValidity: o.armValidity,
    saveValidity: o.saveValidity,
    armLabel: o.armLabel,
    live: !!o.live,
    saveLocked: o.saveLocked,
    armLocked: o.armLocked,
    validateLocked: o.validateLocked,
    simulateLocked: o.simulateLocked,
  });
}
const S1_ROWS = [
  {
    n: 1,
    metric: "Unrealised R",
    op: "is at least",
    value: "1.0 R",
    fragment: "unrealised R is at least 1.0",
  },
  { n: 2, metric: "Position side", op: "is", value: "long", fragment: "the position is long" },
];
const S1_ACTIONS = [
  {
    n: 1,
    name: "Move stop to breakeven",
    params: ["offset 2 ticks"],
    fragment:
      "move the stop to break-even (your average entry) plus 2 ticks · Every position keeps a native stop — you can move it, not delete it.",
  },
  { n: 2, name: "Log journal tag", params: ["be-moved"], fragment: "tag the journal be-moved" },
];

// ---- Board 1: SCR-081 anatomy ---------------------------------------------------------------------------------
BUILD[1] = () => {
  const b = place(1, "scr-081-anatomy", NUM.screenW + 64, 1900);
  const X = b.x + 32,
    Y = b.y + 28,
    W = NUM.screenW;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — SCR-081 anatomy (§2): one 1120 px column — header with the round‑trip indicator, the sentence as the accessible description and the scope chip; five fieldset sections; CMP-158 pinned above the sticky action bar; draft state, S1 as the rule",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "PROPOSED · 1920×1080 dark compact · a 1280×800 crop strip below · tokens of packages/ui/tokens at the base",
  );
  y += 24 + GAPY;
  const sy = y;
  y = scr081(b, X, y, W, {
    rows: S1_ROWS,
    actions: S1_ACTIONS,
    armReason: "Simulate first — 5 fires or 24 h.",
  });
  y += GAPY;
  const notes = grid(
    b,
    X,
    y,
    W,
    [
      {
        kicker: "HEADER · 32 PX ROW",
        title:
          "name · status word DRAFT / ARMED-DEMO / ARMED-LIVE / PAUSED / ERROR · Form | Graph (CMP-235 as CMP-003) · the indicator chip · v3 · Last saved 13:42:10 UTC",
        body: "the sentence block is the editor region's aria-describedby (≤55 words); the scope chip beside it: 2 accounts · BTCUSDT · new positions (US-RULE-007; DCR-12 both, PROPOSED)",
      },
      {
        kicker: "FIVE FIELDSET SECTIONS (CMP-065)",
        title:
          "Scope (CMP-144) · Trigger (CMP-143) · Conditions (CMP-141 + CMP-140) · Actions (CMP-142) · Options (CMP-233) · gated controls: CMP-079 RbacGate + the CMP-019 lock (E09-D09 §2.2)",
        body: "fields 24 px compact / 32 px comfortable (size.control.height); label column 160 px; insets space.inset.sm / space.inset.md; applies_to has four radios, any the default (C7)",
      },
      {
        kicker: "CMP-158 + THE STICKY ACTION BAR · 48 PX",
        title:
          "Every position keeps a native stop — you can move it, not delete it. Rules can tighten it, never remove it — the stop is held by the exchange, not by this app. — then Validate · Simulate · Save draft · Arm…",
        body: "Arm… is CMP-001 primary while the scope is demo-only and the destructive class (danger + the typed confirm) when its environments include live; a T2 reason while view-as or the new-rule gate holds: Simulate first — 5 fires or 24 h. (rbac.view_as first); disabled by form validity: the button keeps its own fill and label at opacity.disabled with the reason full-opacity beside it, no lock (E09-D09 §9.1; E30-D02 D3); Arm… in T2 = CMP-079 RbacGate + the CMP-019 lock (E09-D09 §2.2)",
      },
    ],
    3,
    "b1-notes",
  );
  y = notes + GAPY;
  const cap = mkText(
    b,
    "1280×800 crop (16 §8): the column is 1024 px, the action bar stays sticky, nothing clips",
    X,
    y,
    W,
    { size: 12.5, color: C.text2, tok: TOK.text2, name: "crop-caption" },
  );
  y += (cap ? cap.h : 18) + 8;
  mkRect(b, X, y, NUM.cropW, 120, "raised", {
    stroke: "borderStrong",
    radius: 6,
    role: "crop",
    name: "crop-1280x800",
  });
  const cx0 = X + (NUM.cropW - 1024) / 2;
  mkRect(b, cx0, y + 16, 1024, 88, "canvas", {
    stroke: "border",
    radius: 4,
    role: "crop-column",
    name: "crop-column",
  });
  mkText(
    b,
    "1024 px column · header · sections · CMP-158 · sticky action bar",
    cx0 + 16,
    y + 48,
    980,
    { size: 12, color: C.text2, tok: TOK.text2, name: "crop-text" },
  );
  finish(b, y + 120);
  void sy;
};

// ---- Board 2: the six SCR-081 states ---------------------------------------------------------------------------
BUILD[2] = () => {
  const b = place(2, "scr-081-states", NUM.screenW + 64, 9000);
  const X = b.x + 32,
    Y = b.y + 28,
    W = NUM.screenW;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — The six SCR-081 states (§3), each its own frame with realistic content: draft · validating · valid · invalid · armed · vocabulary-unavailable",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "PROPOSED · every gated control in E09-D09's T2 form — aria-disabled, the lock glyph, the full label in color.text.tertiary on color.surface.raised with a color.border.default hairline, the reason in color.text.secondary; one notice per read-only frame · nothing moves focus",
  );
  y += 24 + GAPY;
  const frames = [
    {
      label: "02-1 draft (S1)",
      o: { rows: S1_ROWS, actions: S1_ACTIONS, armReason: "Simulate first — 5 fires or 24 h." },
    },
    {
      label:
        "02-2 validating — the region aria-busy; Validate in its loading state; the indicator Checking…",
      o: {
        rows: S1_ROWS,
        actions: S1_ACTIONS,
        indicator: "checking",
        armReason: "Simulate first — 5 fires or 24 h.",
      },
    },
    {
      label:
        "02-3 valid (S2) — No problems — 0 errors · 0 warnings.; Arm… enabled (the gate satisfied; primary against DEMO — danger + the typed confirm only against LIVE)",
      o: {
        sentence: S2,
        rows: [
          {
            n: 1,
            metric: "Position side",
            op: "is",
            value: "long",
            fragment: "the position is long",
          },
          {
            n: 2,
            metric: "Spread (bps)",
            op: "is above",
            value: "8 bps",
            fragment: "either the spread is above 8 bps",
          },
          {
            n: 3,
            metric: "Tape speed z-score",
            op: "is above",
            value: "3 sigma",
            fragment: "or tape speed is above 3 sigma",
          },
        ],
        actions: [
          {
            n: 1,
            name: "Modify stop loss",
            params: ["atr", "2.0 × ATR(14)"],
            fragment:
              "tighten the stop to 2.0 × ATR(14) from the close · Every position keeps a native stop — you can move it, not delete it.",
          },
        ],
      },
    },
    {
      label:
        "02-4 invalid (S1, row 2 emptied) — the CMP-234 log at the top, the offending row outlined and focusable; Save draft disabled by form validity — Fix the errors to save. · Arm… — Fix the errors first. (each keeps its primary fill and full label at opacity.disabled, the reason full-opacity beside it — E30-D02 D3; aria-disabled, no lock, no CMP-079 — E09-D09 §9.1; an invalid draft is never stored — 422; the count stays in the CMP-234 heading)",
      o: {
        rows: [
          S1_ROWS[0],
          {
            n: 2,
            metric: "Position side",
            op: "is",
            value: "—",
            invalid: true,
            fragment:
              "Row 2 is missing a value. · details: Operator 'eq' needs 2 operand(s) in node c3.",
          },
        ],
        actions: S1_ACTIONS,
        validation: {
          heading: "Validation — 2 errors, 0 warnings",
          lines: [
            "Row 2 — Row 2 is missing a value.",
            "Row 2 — Position side compares to long / short, not a number.",
          ],
        },
        armValidity: "Fix the errors first.",
        saveValidity: "Fix the errors to save.",
      },
    },
    {
      label:
        "02-5 armed (ARMED-DEMO) — the values read‑only (aria-readonly); every editing affordance and Save draft T2 → the armed notice (one node, no per-control reason); Disarm to edit · Edit as a new draft version (the new draft opens as 02-1 with the gate T2); while viewing as, the view-as line is the frame's one notice and the armed notice yields — the ARMED-DEMO pill and the read-only values keep the armed state visible, never a second notice",
      o: {
        rows: S1_ROWS,
        actions: S1_ACTIONS,
        status: "ARMED-DEMO",
        armedLine:
          "This version is armed and cannot change under the engine. Disarm to edit, or edit as a new draft version.",
        armLabel: "Disarm",
        readOnly: true,
        saveLocked: true,
      },
    },
    {
      label:
        '02-6 vocabulary-unavailable — the engine-down banner role="alert" (SCR-080\'s words, never paused) is the one node; the pickers, the add buttons, Validate, Simulate, Save draft and Arm… T2 → the banner (no per-control reason)',
      o: {
        rows: S1_ROWS,
        actions: S1_ACTIONS,
        indicator: "unverified",
        banner:
          "The rule engine is not running — armed rules are not evaluating. Your native stops are held by the exchange and are unaffected.",
        pickersDisabled: true,
        armLocked: true,
        saveLocked: true,
        validateLocked: true,
        simulateLocked: true,
      },
    },
  ];
  for (const f of frames) {
    const lb = mkText(b, f.label, X, y, W, { size: 14, weight: 700, name: "frame-label" });
    y += (lb ? lb.h : 20) + 8;
    y = scr081(b, X, y, W, f.o) + GAPY;
  }
  let vy = y - GAPY + 16;
  const va = card(b, X, vy, W, {
    fill: "infoSubtle",
    stroke: "info",
    kicker:
      'VIEW-AS (E09-D09 §2.1 STEP 3A) · A TREATMENT OF EVERY FRAME, NOT A SEVENTH STATE · CMP-028 role="status" · the one notice — every write\'s aria-describedby points here',
    title: "Read-only while viewing as {user}.",
    body: "rbac.view_as, the first leg: Save draft, Validate, Simulate, Arm… (or 02-5's Disarm, Disarm to edit and Edit as a new draft version), + condition / + any-of group / + action, each row menu and Start recording are T2 with no per-control string; the fields read-only as in 02-5 (aria-readonly); no validateRule or compileRule is sent (22 refuses both 403 view_as_read_only) — CMP-234 collapsed: Validation — not run while viewing as; the indicator Not verified with the view-as tooltip; the editor switch stays allowed and runs no compile; a T2 press re-shows this sentence, polite, once. On 02-5 this line is the frame's only notice — the armed notice yields (the view-as leg is checked first, E09-D09 §2.1 step 3; one notice, many pointers, §2.2) and the ARMED-DEMO status pill with the read-only values keeps the armed state visible",
  });
  vy += va.h + 16;
  const gn2 = glyphNote(b, X, vy, W);
  finish(b, vy + gn2);
};

// ---- Board 3: the round-trip indicator ---------------------------------------------------------------------------
BUILD[3] = () => {
  const b = place(3, "round-trip-indicator", W_BOARD, 2600);
  const X = b.x + 32,
    Y = b.y + 28,
    W = W_BOARD - 64;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — The round‑trip indicator (§4): four designed states + Checking… + since your last save; none distinguished by colour alone — fill + glyph + word; state 3 blocks saving with two recovery choices that say what is lost",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "PROPOSED · on POST /api/v1/rules/{ruleId}/compile, on save and on mode switch only · rule.roundtrip_verified {result} · rule.roundtrip_mismatch_resolved {choice} audited",
  );
  y += 24 + GAPY;
  const states = ["identical", "graph_only_construct", "mismatch", "unverified", "checking"];
  let cx = X;
  for (const st of states) cx += indicatorChip(b, cx, y, st) + 16;
  indicatorChip(b, cx, y, "identical", { stale: true });
  y += 24 + GAPY;
  const t = tableBlock(
    b,
    X,
    y,
    [230, 330, 620, 596],
    ["State", "Fill · glyph · word (dark)", "Tooltip / card lead-in", "What it shows and disables"],
    [
      [
        "1 identical — Round-trips ✓",
        "color.status.success.subtle · ✓ icon/round-trip-ok (6.69:1) · color.text.primary (10.21:1, PROPOSED pairs.mjs row)",
        "This rule is fully editable in both the form and the graph editor.",
        "nothing disabled; the form and graph ir_hash agree",
      ],
      [
        "2 graph_only_construct — Graph-only construct — read-only here",
        "color.status.warning.subtle · ⚠ icon/round-trip-partial (7.56:1) · color.text.primary (9.86:1, registered)",
        "Authored in the graph editor: {sentence}. Open in the graph editor to change this. — the read‑only card in place, one per graph-only subtree; solid fill + glyph + text, never dashed",
        "the card's subtree read‑only; the rest editable; saving must not drop or rewrite the read‑only part (E36-S03's test). Shipped fallback (D02-G2): the whole rule as one banner with the same lead-in (memo C10); CMP-235's switch stays allowed",
      ],
      [
        "3 mismatch — Round-trip mismatch",
        "color.status.danger.subtle · ✕ icon/round-trip-mismatch (7.83:1; dark danger.strong = palette.amber.400) · color.text.primary (12.06:1, registered)",
        "The form and the graph compile to different rules. Saving is blocked until you choose which version to keep.",
        "Save draft T2 Saving is blocked until the mismatch is resolved. — Arm… the same; View diff → SCR-088 (a labelled placeholder); the two recovery choices in a CMP-044 standard dialog; never auto-resolved",
      ],
      [
        "4 unverified — Not verified",
        "color.surface.hover · ? icon/round-trip-unverified (not a dash: — is Stale; not hollow: hollow is estimated / absent) · color.text.primary (12.22:1)",
        "Not verified — the compile service is unreachable. You can save a draft; arming is blocked until the rule is verified.",
        "Save draft enabled (draft only); Arm… T2 Not verified — arming is blocked.; while viewing as another user the same chip with the tooltip Not verified — round-trip checks don't run while viewing as another user. (no compile is sent; rbac.view_as first)",
      ],
      [
        "Checking… (checking: true)",
        "color.surface.hover · no glyph (no spinner, motion none) · Checking… · the chip aria-busy",
        "—",
        "only while the compile runs on save / mode switch (≤500 ms p95); never on a keystroke",
      ],
      [
        "since your last save (staleSince set)",
        "the last result's fill and word + the qualifier in color.text.secondary (7.50:1)",
        "the last tooltip + Last verified 13:42:10 UTC.",
        "the last result is kept, never blanked; the next save runs the compile again",
      ],
    ],
    { stk: TICKET + ":b3-table" },
  );
  y += t.h + GAPY;
  const cw = (W - 24) / 2;
  const left = column(
    b,
    X,
    y,
    cw,
    [
      {
        kicker: "STATE 2 · THE READ‑ONLY CARD (R3) AND THE WHOLE-RULE FALLBACK (D02-G2)",
        title:
          "Authored in the graph editor: none of: the spread is above 8 bps, tape speed is above 3 sigma. Open in the graph editor to change this.",
        body: "one card per graph-only subtree, in place inside the condition list, with the memo's sentence per construct: none of · at least n of · either (A and B) or C · A minus B is above x · happened within the last w · happened at least n times in w · has not changed for w · shared condition A, used by n actions. Solid amber (color.status.warning.subtle, text.primary 9.86:1), glyph + text, never dashed or hollow (D02-C14).",
        fill: "warningSubtle",
        stroke: "warningStrong",
      },
      {
        kicker: "STATE 4 · DRAFT ONLY",
        title:
          "Not verified — the compile service is unreachable. You can save a draft; arming is blocked until the rule is verified.",
        body: "Save draft enabled; Arm… T2 per E09-D09 §2.2 — Not verified — arming is blocked. (rule.arm.unverified; 14 state 4: the indicator says so in text); while viewing as another user: the same chip, the view-as tooltip, no compile sent (rbac.view_as first — the one notice)",
      },
    ],
    "b3-left",
  );
  const right = column(
    b,
    X + cw + 24,
    y,
    cw,
    [
      {
        kicker: "STATE 3 · BLOCKING (AC 4)",
        title:
          "Save draft 🔒 Saving is blocked until the mismatch is resolved. · View diff → SCR-088 diff view — E36-D03, not designed here",
        body: "The two recovery choices, each saying what is lost (AC 4): Keep the form version — the graph's {diverging node} is replaced by this form's Row {n}. (S2: the graph's 'the spread is above 12 bps' is replaced by this form's Row 2 'the spread is above 8 bps' — a mismatch is a logic divergence, not a layout one: graph_layout is a Rule field outside the hash, carried through untouched, so no layout is lost; the node is named from round_trip.diff[].path) · Keep the graph version — your form edits since the last save are discarded. The choice emits rule.roundtrip_mismatch_resolved {choice} (audited); never auto-resolved.",
        fill: "dangerSubtle",
        stroke: "dangerStrong",
      },
      {
        kicker: "OBSERVABILITY (§17) · ANNOUNCEMENT",
        title:
          "rule.roundtrip_verified {result} fires when the compile returns — on save and on mode switch, never per keystroke",
        body: "one polite announcement when the result changes (Round-trip: {word}); never for Checking…; inside the ≤1 per 5 s ambient budget; focus trapped in the mismatch dialog, Esc = cancel, focus returned to the chip.",
      },
    ],
    "b3-right",
  );
  y = Math.max(left, right) + GAPY;
  const fl = mkText(
    b,
    "The six indicator states as composed SCR-081 frames (S1; the DEMO band, CMP-158 and the action bar on each — AC sc. 2: a frame, not a note)",
    X,
    y,
    W,
    { size: 14, weight: 700, name: "frames-title" },
  );
  y += (fl ? fl.h : 20) + 8;
  const iframes = [
    {
      label:
        "03-1 identical — Round-trips ✓; nothing disabled by the indicator (the new-rule gate assumed satisfied, as 02-3; Arm… primary against DEMO)",
      o: { rows: S1_ROWS, actions: S1_ACTIONS, indicator: "identical" },
    },
    {
      label:
        "03-2 graph_only_construct — the read‑only card in place inside the condition list; the rest editable",
      o: {
        rows: S1_ROWS,
        actions: S1_ACTIONS,
        indicator: "graph_only_construct",
        readOnlyCard: true,
      },
    },
    {
      label:
        "03-3 mismatch — Save draft 🔒 and Arm… 🔒 Saving is blocked until the mismatch is resolved. (rule.save.mismatch, one state key, inline); View diff → SCR-088",
      o: {
        rows: S1_ROWS,
        actions: S1_ACTIONS,
        indicator: "mismatch",
        saveReason: "Saving is blocked until the mismatch is resolved.",
        armReason: "Saving is blocked until the mismatch is resolved.",
      },
    },
    {
      label:
        "03-4 unverified — Save draft enabled (draft only); Arm… 🔒 Not verified — arming is blocked. (rule.arm.unverified)",
      o: {
        rows: S1_ROWS,
        actions: S1_ACTIONS,
        indicator: "unverified",
        armReason: "Not verified — arming is blocked.",
      },
    },
    {
      label:
        "03-5 Checking… — the chip aria-busy while the compile runs on save / mode switch; nothing disabled, nothing moves",
      o: { rows: S1_ROWS, actions: S1_ACTIONS, indicator: "checking" },
    },
    {
      label:
        "03-6 since your last save — the last result kept with the qualifier; nothing disabled",
      o: { rows: S1_ROWS, actions: S1_ACTIONS, indicator: "identical", stale: true },
    },
  ];
  for (const f of iframes) {
    const lb = mkText(b, f.label, X, y, W, { size: 14, weight: 700, name: "frame-label" });
    y += (lb ? lb.h : 20) + 8;
    y = scr081(b, X, y, W, f.o) + GAPY;
  }
  finish(b, y - GAPY);
};

// ---- Board 4: CMP-140 rows and CMP-141 grouping ---------------------------------------------------------------
BUILD[4] = () => {
  const b = place(4, "condition-rows-grouping", W_BOARD, 2400);
  const X = b.x + 32,
    Y = b.y + 28,
    W = W_BOARD - 64;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — CMP-140 RuleConditionRow and CMP-141 RuleConditionGroup (§5, §6): Condition N of M, the metric as its display_name, the operator as G4's verb, the value form, the row menu, the fragment beneath; two levels, no advanced",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "PROPOSED · the grouping model DECIDED by the shipped form subset · the bracket ink color.text.tertiary 5.96:1 (n5) · never amber on a form construct",
  );
  y += 24 + GAPY;
  const colW = NUM.column;
  const rows = [
    { n: 1, metric: "Position side", op: "is", value: "long", fragment: "the position is long" },
    {
      n: 2,
      metric: "Spread (bps)",
      op: "is above",
      value: "8 bps",
      fragment: "either the spread is above 8 bps",
    },
    {
      n: 3,
      metric: "Tape speed z-score",
      op: "is above",
      value: "3 sigma",
      fragment: "or tape speed is above 3 sigma",
    },
    {
      n: 4,
      metric: "In stop-hunt zone",
      chip: true,
      op: "is true",
      value: "—",
      fragment: "the price is in a stop-hunt zone (estimated)",
    },
    {
      n: 5,
      metric: "Spread (bps)",
      op: "is above",
      value: "8 bps",
      fragment: "(not available — BTCUSDT is not recorded · Start recording)",
      unavailable: true,
    },
    {
      n: 6,
      metric: "Position side",
      op: "is",
      value: "—",
      invalid: true,
      fragment: "Row 6 is missing a value.",
    },
  ];
  const lg = mkText(
    b,
    "Conditions — all of  (S2 with the any-of group, then the estimated row of S3, the unavailable row and the invalid row)",
    X,
    y,
    colW,
    { size: 12, weight: 700, color: C.text2, tok: TOK.text2, name: "legend" },
  );
  y += (lg ? lg.h : 18) + 10;
  let cy = y,
    groupTop = 0,
    groupBottom = 0;
  for (const r of rows) {
    const inGroup = r.n === 2 || r.n === 3;
    const rx = X + (inGroup ? 24 : 0);
    if (r.n === 2) {
      groupTop = cy;
      const gl = mkText(
        b,
        "any of  (Condition group — either … or …)",
        rx + NUM.labelColumn,
        cy,
        600,
        { size: 11.5, weight: 700, color: C.text2, tok: TOK.text2, name: "group-legend" },
      );
      cy += (gl ? gl.h : 16) + 4;
    }
    const controls = [
      {
        label: r.metric,
        textColor: r.unavailable ? C.text3 : C.text,
        textTok: r.unavailable ? TOK.text3 : TOK.text,
      },
    ];
    if (r.chip)
      controls.push({ label: "(estimated)", fill: "infoSubtle", stroke: "info", size: 10.5 });
    controls.push(
      { label: r.op },
      { label: r.value, mono: true },
      { label: "⋯", w: NUM.rowCompact, padX: 6 },
    );
    if (r.invalid)
      mkRect(
        b,
        rx + NUM.labelColumn - 6,
        cy - 3,
        colW - NUM.labelColumn + 6 - (inGroup ? 24 : 0),
        NUM.rowCompact + 6,
        null,
        {
          stroke: "danger",
          strokeWidth: NUM.bracketPx,
          radius: 6,
          role: "invalid-outline",
          name: "invalid-outline",
        },
      );
    cy = fieldRow(b, rx, cy, colW - (inGroup ? 24 : 0), "Condition " + r.n + " of 6", controls, {
      fragment: r.fragment,
    });
    if (r.unavailable) {
      // the Start recording action: T1 for the Owner; T2 for a session without recording:write (every Manager, by the ruling)
      let ux = rx + NUM.labelColumn;
      ux +=
        pill(
          b,
          ux,
          cy,
          LOCK + "Start recording",
          Object.assign({ h: 20, size: 10.5, radius: 6, name: "start-recording-t2" }, T2),
        ) + 8;
      const ut = mkText(
        b,
        "Only the owner can start recording. — rbac.owner_only for a session without recording:write (every Manager, by the ruling); for the Owner the one-click action is T1",
        ux,
        cy + 2,
        colW - NUM.labelColumn - 150,
        { size: 11, color: C.text2, tok: TOK.text2, name: "t2-reason" },
      );
      cy += Math.max(20, ut ? ut.h : 16) + 6;
    }
    if (r.n === 3) groupBottom = cy - 4;
  }
  bracket(b, X + 12, groupTop, groupBottom, "text3", { name: "any-of-bracket" });
  let ax = X + NUM.labelColumn;
  ax +=
    pill(b, ax, cy, "+ condition", {
      h: NUM.rowCompact,
      size: 11.5,
      fill: "raised",
      stroke: "borderStrong",
      radius: 6,
      name: "add-condition",
    }) + 8;
  pill(b, ax, cy, "+ any-of group", {
    h: NUM.rowCompact,
    size: 11.5,
    fill: "raised",
    stroke: "borderStrong",
    radius: 6,
    name: "add-group",
  });
  cy += NUM.rowCompact + 8;
  // the row menu, to the right of the list
  const mx = X + colW + 40,
    mw = W - colW - 40;
  const menu = card(b, mx, y, mw, {
    kicker: "ROW MENU · SHIFT+F10 OR THE ⋯ BUTTON",
    title: "Move up · Move down · Duplicate · Remove",
    body: "one roving stop per row (Tab to enter, ↑ / ↓ move, ← / → between the row's controls); no drag anywhere; Esc: cancel the innermost thing; every target ≥24 px (P11)",
  });
  const inv = card(b, mx, y + menu.h + 12, mw, {
    kicker: "INVALID ROW",
    title: "Row 6 is missing a value.",
    body: "outline color.status.danger.default at border.thick (3.63:1 on canvas) + a color.status.danger.strong glyph + the text Row 6; the shipped validator text in the details disclosure, the id only there (P10)",
    fill: "dangerSubtle",
    stroke: "dangerStrong",
  });
  y = Math.max(cy, y + menu.h + 12 + inv.h) + GAPY;
  const t = tableBlock(
    b,
    X,
    y,
    [250, 460, 1066],
    ["Operator id (15)", "Verb (G4)", "Value form"],
    [
      [
        "gt · gte · lt · lte",
        "is above · is at least · is below · is at most",
        "one number with the unit shown (1.0 R, 8 bps) or a metric ref (type.num.sm, font.family.mono, tabular)",
      ],
      [
        "eq · neq",
        "is · is not",
        "number, enum value (long / short / flat) or boolean; tolerance as a (within {t}) disclosure on numbers",
      ],
      [
        "between · outside",
        "is between {a} and {b} · is outside {a} to {b}",
        "two numbers (right2), the lower first",
      ],
      [
        "crosses_above · crosses_below",
        "crosses above · crosses below",
        "one number or metric ref; false on the first evaluation after warmup",
      ],
      ["changed", "changes", "no value (arity 1)"],
      [
        "is_true · is_false",
        "the predicate as a clause (a position is open) · its negation (no position is open)",
        "no value (arity 1); the fragment is the whole clause",
      ],
      [
        "in_set · not_in_set",
        "is one of {a}, {b} · is none of {a}, {b}",
        "the enum's values as removable CMP-011 chips (set_values)",
      ],
      [
        "sustained_for (a TemporalOp)",
        "{comparison} for at least {w}",
        "one duration in s / min as a disclosure on the row — the one temporal form the subset allows",
      ],
    ],
    { stk: TICKET + ":b4-table" },
  );
  y += t.h + GAPY;
  const g = grid(
    b,
    X,
    y,
    W,
    [
      {
        kicker: "CMP-141 · TWO LEVELS (DECIDED)",
        title:
          "all of rows + one any-of group (rows only), or the root switch to any of (a flat list); 32 children at most (MAX_BOOLEAN_CHILDREN)",
        body: "the group is its own fieldset, name Condition group — either … or …, legend any of, indented by space.inset.lg with the 2 px bracket in color.text.tertiary (5.96 / 6.36 / 11.87), flush with its first and last row; reads back either {A} or {B} / any of: {A}, {B}, {C} (G2)",
      },
      {
        kicker: "WHAT IS NOT HERE",
        title:
          "no advanced mode (memo C4 / DCR-4) · no nesting deeper than one group · no NOT (is_false negates a boolean metric)",
        body: "a graph-only subtree renders in the list as the read‑only card, in place, never as an empty box (P6); a form construct is never amber — amber is the read‑only card's and the warning banner's (n5)",
      },
      {
        kicker: "PROPS DELTA (DCR-5 → §16)",
        title:
          "operator = the 15 ids as verbs; value gains right2, setValues, tolerance, sustainedForMs; joinToNext dropped; diagnostics[] anchored by row id (G5)",
        body: "tokens: font.family.mono via type.num.* and color.status.danger.default at border.thick replace the missing font.mono / color.border.invalid",
      },
    ],
    3,
    "b4-notes",
  );
  finish(b, g);
};

// ---- Board 5: CMP-157 metric picker ---------------------------------------------------------------------------
BUILD[5] = () => {
  const b = place(5, "metric-picker", W_BOARD, 2200);
  const X = b.x + 32,
    Y = b.y + 28,
    W = W_BOARD - 64;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — CMP-157 MetricPickerCombobox open (§7): the seven categories with counts, the option anatomy — display_name · unit · (estimated) chip · description — the unavailable option with Start recording — T1 for the Owner, T2 for a session without recording:write — search, replay last",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "PROPOSED · R2 · (estimated) is a tag on the option (CMP-227), never a category · 105 ids · 13 estimated · categories derived client-side until the signal carries scope (G8)",
  );
  y += 24 + GAPY;
  const px = X,
    pw = 760;
  mkRect(b, px, y, pw, 1300, "overlay", {
    stroke: "borderStrong",
    radius: 8,
    role: "popover",
    name: "picker-popover",
  });
  let cy = y + 12;
  mkRect(b, px + 12, cy, pw - 24, NUM.rowCompact, "raised", {
    stroke: "borderSelected",
    radius: 6,
    role: "search",
    name: "search-box",
  });
  mkText(b, "Metric — type to filter (41 metrics)", px + 22, cy + 4, pw - 48, {
    size: 12,
    color: C.text2,
    tok: TOK.text2,
    name: "search-placeholder",
  });
  cy += NUM.rowCompact + 10;
  const cats = [
    "price · 13",
    "orderflow · 41",
    "book · 16",
    "derivatives · 11",
    "position · 13",
    "account · 8",
    "replay · 3",
  ];
  const opts = {
    "price · 13": [
      ["Price", "price", "Last / mark / index price"],
      ["ATR", "price", "Wilder average true range"],
      ["Market regime", "enum", "Regime from ADX, Hurst and ATR%", true],
    ],
    "orderflow · 41": [
      ["Tape speed z-score", "zscore", "Fast-window tape speed vs baseline"],
      ["In stop-hunt zone", "bool", "Price within k ticks of a detected stop cluster", true],
      ["CVD divergence", "bool", "Pivot-based swing comparison of price vs CVD", true],
    ],
    "book · 16": [
      [
        "Spread (bps)",
        "bps",
        "(not available — BTCUSDT is not recorded · Start recording)",
        false,
        true,
      ],
      [
        "Spread (bps)",
        "bps",
        "Only the owner can start recording. (rbac.owner_only — a session without recording:write)",
        false,
        true,
        true,
      ],
      [
        "Distance to liquidity cluster",
        "count",
        "Ticks to the nearest heatmap cluster at or above z",
      ],
      ["Iceberg present", "bool", "Repeated resting-size refills at a level", true],
    ],
    "derivatives · 11": [
      ["Funding rate", "pct", "Current funding rate"],
      ["Time to funding", "ms", "Milliseconds until the next funding"],
    ],
    "position · 13": [
      ["Unrealised R", "ratio", "Unrealised PnL in multiples of initial risk"],
      ["Position side", "enum", "Side of the position"],
      ["Position age", "ms", "Time since the position opened"],
    ],
    "account · 8": [["Daily loss", "pct", "Loss today as percent of start-of-day equity"]],
    "replay · 3": [["Replay speed", "ratio", "Replay speed multiplier"]],
  };
  for (const c of cats) {
    mkText(b, c, px + 20, cy, pw - 40, {
      size: 11,
      weight: 700,
      color: C.text2,
      tok: TOK.text2,
      name: "category",
    });
    cy += 20;
    for (const o of opts[c]) {
      const sel = o[0] === "Unrealised R";
      if (sel)
        mkRect(b, px + 12, cy - 2, pw - 24, 50, "selected", {
          radius: 6,
          role: "option-bg",
          name: "option-active",
        });
      let ox = px + 20;
      mkText(b, o[0] + " · " + o[1], ox, cy, 320, {
        size: 12.5,
        weight: 600,
        color: o[4] ? C.text3 : C.text,
        tok: o[4] ? TOK.text3 : TOK.text,
        name: "option-title",
      });
      if (o[3])
        pill(b, ox + 340, cy - 1, "(estimated)", {
          h: 20,
          size: 10.5,
          fill: "infoSubtle",
          stroke: "info",
          name: "option-chip",
        });
      if (o[4] && !o[5])
        pill(b, ox + 340, cy - 1, "Start recording", {
          h: 20,
          size: 10.5,
          fill: "raised",
          stroke: "borderStrong",
          radius: 6,
          name: "start-recording",
        });
      if (o[5])
        pill(
          b,
          ox + 340,
          cy - 1,
          LOCK + "Start recording",
          Object.assign({ h: 20, size: 10.5, radius: 6, name: "start-recording-t2" }, T2),
        ); // T2 per E09-D09 §2.2: the reason is the option's second line
      mkText(b, o[2], ox, cy + 26, pw - 56, {
        size: 11,
        color: C.text2,
        tok: TOK.text2,
        name: "option-description",
      });
      cy += 52;
    }
    cy += 6;
  }
  const rx = X + pw + 40,
    rw = W - pw - 40;
  const col = column(
    b,
    rx,
    y,
    rw,
    [
      {
        kicker: "OPTION ANATOMY",
        title:
          "line 1 — display_name · unit · the CMP-227 chip (estimated) when estimated · the unavailable clause with Start recording as the one-click action; line 2 — the description in color.text.secondary",
        body: "the chip: the literal word estimated in the accessible name, focusable, Enter opens SCR-058 (14 §0.5 item 2); the unavailable option stays saveable with the sentence saying so (P9, E3)",
      },
      {
        kicker: "SEVEN CATEGORIES (R2)",
        title:
          "price 13 · orderflow 41 · book 16 · derivatives 11 · position 13 · account 8 · replay 3 = 105; the 13 estimated fall 2 / 7 / 2 / 0 / 2 / 0 / 0",
        body: "derived from scope and input (the tool recounts the 93 rows and the 12 kernel-bound); replay last and filtered out when the rule's environments exclude replay (memo Q5); never a detector or estimated group (P5)",
      },
      {
        kicker: "KEYBOARD (CMP-048)",
        title:
          "type to filter · ↑ / ↓ move · Enter selects · Esc closes (innermost cancel) · Home / End jump · → reaches the chip inside an option (PROPOSED)",
        body: "the results count announced politely per query (41 metrics), debounced; 24 px option rows in compact, 32 comfortable; the popover color.surface.overlay with elevation.popover",
      },
      {
        kicker: "CONTRACT",
        title:
          "GET /api/v1/rules/vocabulary signals[]: display_name, description, unit, confidence, estimated, dependencies, available, unavailable_reason, recorder_action; cached per session under its ETag",
        body: "props delta (DCR-10 → §16): category = the seven; per option estimated, available, unavailableReason, recorderAction",
      },
    ],
    "b5-right",
  );
  finish(b, Math.max(y + 1300, col));
};

// ---- Board 6: CMP-142 action rows -----------------------------------------------------------------------------
BUILD[6] = () => {
  const b = place(6, "action-rows", W_BOARD, 2600);
  const X = b.x + 32,
    Y = b.y + 28,
    W = W_BOARD - 64;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — CMP-142 RuleActionRow (§8): the six parameter forms with their sentence fragments; the non-emptiable native stop (E32-D01 §5.2 Arm A); the tighten-only stop rows — no loosening control for any role (#4137); the destructive class; a manager's action picker",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "RULED · #4137 Rules never loosen a stop. — widen_stop omitted from the picker for every role, no loosening toggle · memo C23 break-even (your average entry) plus 2 ticks · the rider: every stop row carries the first sentence of sl.note verbatim · C-2.6, C-4.14",
  );
  y += 24 + GAPY;
  const forms = [
    {
      kicker: "PLACE ORDER · DESTRUCTIVE CLASS · places orders",
      title:
        "▲ Buy | ▼ Sell · market | limit · qty 0.25 · price — · native stop 63,900 (non-emptiable) · take-profits · algo",
      lines: [
        'Every position keeps a native stop — you can move it, not delete it. (the first sentence of sl.note, role="note")',
        'on a clear attempt: Kept at 63,900.0 — every position keeps a native stop. Move it instead. (sl.kept, role="status", polite, once per attempt)',
        "fragment: buy 0.25 at market with a native stop at 63,900 — never without it (native_stop_violation)",
      ],
      fill: "dangerSubtle",
      stroke: "dangerStrong",
    },
    {
      kicker: "MODIFY STOP LOSS · TIGHTEN-ONLY FOR EVERY ROLE",
      title:
        "mode absolute | offset_from_entry | offset_from_price | atr | structure · value 2.0 × ATR(14) · The stop only ever tightens.",
      lines: [
        "no loosening control for any role — a rule action never loosens a stop (#4137 RULED); only_tighten=false and widen_stop are refused at save whatever the role; memo R1's owner line and memo C12's hard-lock are superseded (D02-C20)",
        "Every position keeps a native stop — you can move it, not delete it. · fragment: tighten the stop to 2.0 × ATR(14) from the close · The stop only ever tightens.",
      ],
    },
    {
      kicker: "MOVE STOP TO BREAKEVEN",
      title: "offset_ticks 2 (default)",
      lines: [
        "Every position keeps a native stop — you can move it, not delete it.",
        "fragment: move the stop to break-even (your average entry) plus 2 ticks (memo C23 RULED; the fee basis waits for memo G14)",
      ],
    },
    {
      kicker: "SCALE OUT",
      title: "qty_pct 33 % | qty · order_type market · Reduce-only.",
      lines: ["fragment: scale out 33 % at market"],
    },
    {
      kicker: "FLATTEN ALL POSITIONS · DESTRUCTIVE CLASS · flattens",
      title:
        "symbols (optional chips) · ☐ I understand this flattens every open position on the accounts in scope.",
      lines: [
        "the acknowledgement travels with the arm request (acknowledge_flatten_all) — the box gates Arm…, not Save draft; fragment: flatten every position",
      ],
      fill: "dangerSubtle",
      stroke: "dangerStrong",
    },
    {
      kicker: "HALT NEW ORDERS",
      title:
        "scope account · until next_utc_day | duration_ms | manual · for 5 min — duration not yet in the contract (G6)",
      lines: [
        "fragment: halt new orders on this account until the next UTC day · … until you resume them · … for 5 min (illustrative, G6)",
      ],
    },
  ];
  const g = grid(b, X, y, W, forms, 2, "b6-forms");
  y = g + GAPY;
  const t = tableBlock(
    b,
    X,
    y,
    [320, 760, 696],
    [
      "Action picker (the vocabulary's 25 display_names; widen_stop omitted — #4137) — a session without orders:write",
      "Second line",
      "Treatment (never hidden; 14 §0.5 item 5; every gated row T2 per E09-D09 §2.2)",
    ],
    [
      [
        "Place order · Scale in · Reverse position · Arm chase limit · Start iceberg slice · Start TWAP (every places_orders action: available false, simulate_only true)",
        "the catalogue's notes, then the tag simulate only (the simulate_only flag as a word, PROPOSED); the shipped _SIM_TEXT Requires orders:write on at least one account; available in simulate mode only. only in the details (P10; D02-G14)",
        "pickable (T1) — US-RULE-003 sc. 3: available only in simulate mode, with the restriction explained; the T2 sits on Arm…: 🔒 Your role can't place orders. (rbac.permission; orders_write_required 403)",
      ],
      [
        "Modify stop loss · Modify take profit · Move stop to breakeven · Scale out · Flatten position · Flatten all positions · Cancel order · Cancel all orders · Reduce leverage · Tighten stop (orders:write, no order placed: available false, simulate_only false)",
        "the reason as the second line; Requires orders:write. only in the details",
        "🔒 T2 Your role can't place orders. (rbac.permission, E09-D09 §2.2 / §3.2 orders:write → place orders)",
      ],
      [
        "Resume new orders (rules:arm_live)",
        "the reason as the second line",
        "🔒 T2 Only the owner can arm rules against live. (rbac.owner_only; D02-G14)",
      ],
      [
        "Halt new orders and every action that needs no permission",
        "the catalogue's notes",
        "available; the destructive class (places orders / flattens — 8 actions) carries a color.status.danger.strong glyph + the word",
      ],
    ],
    { stk: TICKET + ":b6-table" },
  );
  y += t.h + GAPY;
  // the picker specimen: the T2 form on options (E09-D09 §2.2) — the lock + the full display_name in color.text.tertiary on color.surface.raised with the hairline, the reason as the second line
  const spT = mkText(
    b,
    "Action picker specimen — a Manager without orders:write (the CMP-048 listbox): every T2 option stays arrow-reachable, its second line is the reason; Enter on it stages nothing",
    X,
    y,
    W,
    { size: 12.5, weight: 700, name: "specimen-title" },
  );
  y += (spT ? spT.h : 18) + 8;
  const sw = 640;
  const spec = [
    [
      "Place order",
      "simulate only",
      "the catalogue's notes as the second line · the tag simulate only · the shipped _SIM_TEXT in the details",
      false,
    ],
    ["Modify stop loss", null, "Your role can't place orders.", true],
    ["Resume new orders", null, "Only the owner can arm rules against live.", true],
    ["Halt new orders", null, "the catalogue's notes as the second line", false],
  ];
  mkRect(b, X, y, sw, spec.length * 60 + 16, "overlay", {
    stroke: "borderStrong",
    radius: 8,
    role: "popover",
    name: "action-picker-popover",
  });
  let sy = y + 10;
  for (const [nm, tagWord, line2, isT2] of spec) {
    let ox = X + 12;
    ox +=
      pill(
        b,
        ox,
        sy,
        (isT2 ? LOCK : "") + nm,
        isT2
          ? Object.assign({ h: 22, size: 12, weight: 600, radius: 6, name: "option-t2" }, T2)
          : {
              h: 22,
              size: 12,
              weight: 600,
              fill: "raised",
              stroke: "border",
              radius: 6,
              name: "option",
            },
      ) + 8;
    if (tagWord)
      pill(b, ox, sy + 1, tagWord, {
        h: 20,
        size: 10.5,
        fill: "hover",
        stroke: "border",
        name: "option-tag",
      });
    mkText(b, line2, X + 12, sy + 28, sw - 24, {
      size: 11,
      color: C.text2,
      tok: TOK.text2,
      name: "option-second-line",
    });
    sy += 60;
  }
  const gn6 = glyphNote(b, X + sw + 40, y, W - sw - 40);
  y = Math.max(y + spec.length * 60 + 16, y + gn6) + GAPY;
  const c = card(b, X, y, W, {
    kicker: "ADVANCED DISCLOSURE PER ROW · THE EMPTY LIST",
    title:
      "on_error · targets · dry_run_only with their §5.6 phrases: If an action fails, the rest are skipped. · TARGET_SEMANTICS verbatim · — simulated, never sent",
    body: "the empty list reads A rule needs at least one action — add one to save.; every stop-management row (modify_stop_loss, tighten_stop, move_to_breakeven) and the place_order stop field carry the sl.note sentence; rows that do not touch a stop do not (the rider) — modify_take_profit reuses the stop form but moves the take-profit, not the stop: no stop note",
  });
  finish(b, y + c.h);
};

// ---- Board 7: CMP-233 options, the summary block, the Arm button's reasons ------------------------------------
BUILD[7] = () => {
  const b = place(7, "options-limits-summary", W_BOARD, 2200);
  const X = b.x + 32,
    Y = b.y + 28,
    W = W_BOARD - 64;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      'E36-D02 — CMP-233 RuleOptions and the summary block (§9): every RuleLimits field with its default and its phrase (DCR-7), the two always-said lines, no rule-level "only tighten" box (memo C12); the Arm button\'s T2 reasons',
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "RULED · BQ-6 No rule notional cap — your account's risk caps still apply. · Asks before acting (skipped if unanswered in 60 s). · #4118 Turns itself off after 5 errors in a row — you re-arm it.",
  );
  y += 24 + GAPY;
  const t = tableBlock(
    b,
    X,
    y,
    [330, 420, 1026],
    ["Field (RuleLimits, 11)", "Control (default)", "Phrase when it differs · always-said lines"],
    [
      [
        "once · once_per",
        "checkbox Once · per position / day / group / this rule's lifetime (none)",
        "Once. · Once per position. / Once per day. / Once per group. / Once in this rule's lifetime.",
      ],
      [
        "cooldown_ms",
        "duration in s (1 s; the IR stores ms)",
        "At most every 60 s. (default read as at most once a second)",
      ],
      [
        "max_fires_per_hour · max_fires_per_day",
        "numbers (60 · 500); caps 600 · 5 000",
        "Up to 10 times an hour. · Up to 500 times a day.; above the default: T2 for a non-owner — 🔒 Only the owner can raise a rule's fire limits. (rbac.owner_only, PROPOSED verb; E09-D09 §2.2) inline under the field, the stepper's increment at the default aria-disabled with the same reason; above the cap refused at save and again at arming for every role (SR-104)",
      ],
      [
        "max_actions_per_fire",
        "number (10, ≤ MAX_ACTIONS)",
        "Only the first {n} actions run per firing. when below the rule's action count (G6)",
      ],
      [
        "max_notional_per_fire · max_daily_notional",
        "USDT amounts (null · null)",
        "At most {x} USDT per firing. / At most {x} USDT a day. — both null: always No rule notional cap — your account's risk caps still apply.",
      ],
      [
        "require_confirmation",
        "checkbox (off)",
        "Asks before acting (skipped if unanswered in 60 s).",
      ],
      [
        "evaluation_timeout_ms",
        "number in ms (250; 10–5000)",
        "Each check may take up to {n} ms. (a timeout counts as an error, E8)",
      ],
      [
        "kill_switch_on_error_count",
        "number (5)",
        "always said: Turns itself off after 5 errors in a row — you re-arm it.; {n} errors when changed",
      ],
    ],
    { stk: TICKET + ":b7-table" },
  );
  y += t.h + GAPY;
  const cw = (W - 24) / 2;
  const left = column(
    b,
    X,
    y,
    cw,
    [
      {
        kicker: "THE SUMMARY BLOCK · aria-describedby OF THE EDITOR REGION",
        title: S1,
        body: "the scope chip 2 accounts · BTCUSDT · new positions beside it (DCR-12 both); the safety line last and fixed (G7); the (estimated) word after the metric title and Uses an estimated detector — behaviour is heuristic. when any metric is estimated (G8); re-reads politely on blur of a row or on save, never per keystroke (P12)",
      },
      {
        kicker: "SCR-085 — E35-D02, NOT DESIGNED HERE",
        title:
          'one hand-off frame: the arming dialog restates the same sentence (F20) and the always-said facts; Live arming is a destructive-class typed step (CMP-044 variant="typed") that needs rules:arm_live and a fresh authenticator step-up — Re-enter your authenticator code to arm a live rule. — and carries the flatten-all acknowledgement (acknowledge_flatten_all)',
        body: "BQ-7 RULED: D02 draws the Arm button's states and this hand-off frame only; the (estimated) callout on SCR-085 is E35-D02's (memo R5 row 7)",
      },
    ],
    "b7-left",
  );
  let ry = y;
  const rl = mkText(
    b,
    "The Arm button's reasons — T2 (E09-D09 §2.2: CMP-079 RbacGate; aria-disabled; the CMP-019 lock + the full label in color.text.tertiary; color.surface.raised with a color.border.default hairline; the reason in color.text.secondary; keyed in §14; the first missing leg first) and form validity (E09-D09 §9.1; E30-D02 D3: the button keeps its own variant fill and full label at opacity.disabled, the reason full-opacity in color.text.secondary beside it — aria-disabled, focusable, a press re-shows the CMP-234 summary; no lock, no CMP-079, no key)",
    X + cw + 24,
    ry,
    cw,
    { size: 12, weight: 700, name: "arm-reasons-title" },
  );
  ry += (rl ? rl.h : 18) + 8;
  for (const [r, k, validity] of [
    [
      "Read-only while viewing as {user}.",
      "rbac.view_as — the first leg (E09-D09 §2.1 step 3a): every write while GET /auth/session/view-as reports a context; the frame's one notice",
    ],
    [
      "Simulate first — 5 fires or 24 h.",
      "rule.arm.simulate_first ({fires} / {hours} from RuleEngineConfig.min_simulation_fires / min_simulation_hours, 24 §11.7 — 5 / 24 the defaults; no progress count)",
    ],
    [
      "Only the owner can arm rules against live.",
      "rbac.owner_only (Manager, LIVE — E09-D09 §2.4 row 70)",
    ],
    ["Not verified — arming is blocked.", "rule.arm.unverified (§4 state 4)"],
    [
      "Saving is blocked until the mismatch is resolved.",
      "rule.save.mismatch (§4 state 3; the same node as Save draft's)",
    ],
    [
      "aria-describedby → the engine-down banner",
      "02-6: one notice, many pointers (no per-control reason)",
    ],
    [
      "Your role can't place orders.",
      "rbac.permission (a places_orders action, no orders:write — orders_write_required 403)",
    ],
    [
      "This account isn't assigned to you.",
      "rbac.account (an account in scope outside the grant — shown at the account in Scope's CMP-105)",
    ],
    [
      "Only the owner can raise a rule's fire limits.",
      "rbac.owner_only (a non-owner, a limit above the default; PROPOSED verb)",
    ],
    [
      "Fix the errors first.",
      "form validity, not T2 (E09-D09 §9.1): validation — the count stays in the CMP-234 heading; the primary fill and the full label at opacity.disabled, the reason full-opacity (E30-D02 D3); no lock, no CMP-079, no key",
      true,
    ],
    [
      "Tick ‘I understand’ on Flatten all positions first.",
      "form validity, not T2 (E09-D09 §9.1): the flatten-all box unticked — acknowledgement_required 422; the primary fill and the full label at opacity.disabled, the reason full-opacity (E30-D02 D3); no lock, no CMP-079, no key",
      true,
    ],
  ]) {
    let cx = X + cw + 24;
    cx +=
      pill(
        b,
        cx,
        ry,
        (validity ? "" : LOCK) + "Arm…",
        validity
          ? Object.assign(
              {
                h: NUM.rowCompact,
                size: 12,
                weight: 600,
                fill: "primary",
                stroke: "primary",
                radius: 6,
                textColor: C.onAction,
                textTok: TOK.onAction,
                name: "btn-arm-validity",
              },
              VALIDITY,
            )
          : Object.assign(
              { h: NUM.rowCompact, size: 12, weight: 600, radius: 6, name: "btn-arm-t2" },
              T2,
            ),
      ) + 12; // a validity row: the primary variant (02-4 arms against DEMO) at opacity.disabled, no lock (E30-D02 D3); a T2 row: the raised fill, the hairline, the lock
    const rt = mkText(
      b,
      r + " — " + k,
      cx,
      ry + 4,
      cw - (cx - X - cw - 24),
      Object.assign(
        { size: 12, color: C.text2, tok: TOK.text2 },
        validity ? { name: "validity-reason" } : { name: "t2-reason" },
      ),
    ); // the reason layer: validity-reason for a form-validity row, never t2-reason
    ry += Math.max(NUM.rowCompact, (rt ? rt.h : 16) - 4) + 10;
  }
  ry += glyphNote(b, X + cw + 24, ry, cw) + 8;
  const en = card(b, X + cw + 24, ry, cw, {
    kicker: "ENABLED (02-3 valid, the gate satisfied)",
    title:
      "Arm… — CMP-001 primary while the scope is demo-only (color.text.on-action on color.action.primary.default 4.76:1); CMP-001 danger — the destructive class (5.05:1) with the typed confirm — only when the scope's environments include live; opens SCR-085",
    body: "RuleValidationResult.blocks_arming: any error or any open safety-class warning refuses mode=armed; the new-rule gate: simulate for 5 fires or 24 h first (24 §11.7); on demo the SCR-085 dialog's variant is E35-D02's (standard, PROPOSED). Arm path and retries: a missing live step-up keeps Arm… enabled — SCR-006 opens, the request is held and re-sent once on success (E09-D09 §2.1 step 5); a 403 / 422 at arming shows at the point of action (T4), then Arm… re-derives from the fresh session; the Owner's override of the new-rule gate is SCR-085's (E35-D02) — 02-1 depicts a Manager",
  });
  finish(b, Math.max(left, ry + en.h));
};

// ---- Board 8: validation copy -----------------------------------------------------------------------------------
BUILD[8] = () => {
  const b = place(8, "validation-copy", W_BOARD, 1800);
  const X = b.x + 32,
    Y = b.y + 28,
    W = W_BOARD - 64;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — Validation copy (§3, §14): the five designed messages with their shipped validator counterparts in the details disclosure; the CMP-234 error summary with in-page links; the estimated-detector banner; the DCR-11 banner",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "RULED · BQ-4 Row 2 is missing a value. verbatim · Position side compares to long / short, not a number. (display-name form, P1 / P10) · the shipped safety messages keep their wording",
  );
  y += 24 + GAPY;
  const t = tableBlock(
    b,
    X,
    y,
    [560, 640, 576],
    [
      "Designed message (primary line)",
      "Shipped validator text (the details disclosure; the id only there)",
      "Where",
    ],
    [
      [
        "Row 2 is missing a value.",
        "Operator 'gte' needs 2 operand(s) in node c3. (schema_error) · Node c3 needs at least one value to test against. (missing_action_param)",
        "the invalid row + the CMP-234 entry Row 2 — Row 2 is missing a value.",
      ],
      [
        "Position side compares to long / short, not a number.",
        "Node c3 compares enum with ratio without an explicit conversion. (type_mismatch) — 14's id-bearing string is C3 for the 14 owner",
        "the invalid row + the CMP-234 entry",
      ],
      [
        "This rule depends on an estimated detector — behaviour is heuristic.",
        "— (the banner follows the shipped confidence, never the catalogue's italics; memo C3)",
        'the CMP-028 callout above the rows, role="status", announced once',
      ],
      [
        "I understand this flattens every open position on the accounts in scope.",
        "— (acknowledged in the arm request, acknowledge_flatten_all; 14 Validation names the box)",
        "the flatten_all_positions row's checkbox; unticked, Arm… is disabled by form validity — Tick ‘I understand’ on Flatten all positions first. (aria-disabled + the reason, no lock — E09-D09 §9.1; the button at opacity.disabled, the reason full-opacity — E30-D02 D3)",
      ],
      [
        "A rule needs at least one action — add one to save.",
        "— (14: a rule with no action cannot be saved)",
        "the empty Actions list; Save draft disabled by form validity — Add an action to save. (aria-disabled + the reason, no lock, no CMP-079 — E09-D09 §9.1; the button at opacity.disabled, the reason full-opacity — E30-D02 D3)",
      ],
      [
        "Action 1 would leave a position without its native exchange stop-loss, which is never allowed.",
        "native_stop_violation (safety) — kept verbatim",
        "CMP-234; unreachable by design in the form: the native stop field is non-emptiable",
      ],
      [
        "No cooldown set; rule may fire on every update. · This rule would evaluate about {n} times a minute.",
        "guard_missing (warning, safety) · high_frequency (warning, performance)",
        "CMP-234 warnings; a safety-class warning blocks arming",
      ],
    ],
    { stk: TICKET + ":b8-table" },
  );
  y += t.h + GAPY;
  const cw = (W - 2 * 24) / 3;
  const c1 = card(b, X, y, cw, {
    kicker: 'CMP-234 · role="log" · errors first',
    title: "Validation — 2 errors, 0 warnings",
    lines: [
      "Row 2 — Row 2 is missing a value.",
      "Row 2 — Position side compares to long / short, not a number.",
    ],
    foot: "each entry a button that moves focus to the offending row (the sole diagnostic navigation); the count announced on every recompile",
    fill: "dangerSubtle",
    stroke: "dangerStrong",
  });
  const c2 = card(b, X + cw + 24, y, cw, {
    kicker: 'ESTIMATED-DETECTOR BANNER · CMP-028 tone="warning" · callout',
    title: "This rule depends on an estimated detector — behaviour is heuristic.",
    body: 'solid fill color.status.warning.subtle, glyph ⚠ color.status.warning.strong (7.56:1), text color.text.primary (9.86:1); role="status", announced once on entry; above the rows when any referenced metric is estimated (S3)',
    fill: "warningSubtle",
    stroke: "warningStrong",
  });
  const c3 = card(b, X + 2 * (cw + 24), y, cw, {
    kicker:
      'ENGINE-DOWN BANNER (SCR-080\'s words + DCR-11\'s tail) · CMP-028 tone="danger" · role="alert"',
    title:
      "The rule engine is not running — armed rules are not evaluating. Your native stops are held by the exchange and are unaffected.",
    body: "SCR-080's engine-down words, then DCR-11's reassurance tail (E17-D01 D8); never paused — that is B9's paused_degraded, the feed-degraded state (D02-C21); announced once, assertively (a discrete event); the one node: the pickers, the add buttons, Validate, Simulate, Save draft and Arm… are T2 with aria-describedby → this banner, no per-control reason; text color.text.primary 12.06:1, second line color.text.secondary 7.40:1",
    fill: "dangerSubtle",
    stroke: "dangerStrong",
  });
  finish(b, y + Math.max(c1.h, c2.h, c3.h));
};

// ---- Board 9: SCR-083 gallery -------------------------------------------------------------------------------------
const TEMPLATES = [
  {
    t: "T1",
    title: "Move SL to break-even after 1R",
    s: "When the position changes on BTCUSDT (Main), if unrealised R is at least 1.0: move the stop to break-even (your average entry) plus 2 ticks. Once per position. The stop only ever tightens.",
    needs: "Needs: Unrealised R · recorded history: none needed",
    stop: true,
    ex: "illustrative: at 64,000 entry and 63,900 stop, 1R is reached at 64,100 — the stop moves to 64,000.20",
  },
  {
    t: "T2",
    title: "ATR trailing stop (ratchet)",
    s: "When a 1m bar closes on BTCUSDT (Main), if a position is open: tighten the stop to 2.0 × ATR(14) from the close. The stop only ever tightens.",
    needs: "Needs: Position open, ATR · recorded history: none needed",
    stop: true,
    ex: "illustrative: close 64,200, ATR(14) 45 → the stop moves to 64,110 if that is tighter",
  },
  {
    t: "T3",
    title: "Structure (swing) trailing stop",
    s: "When a 5m bar closes on BTCUSDT (Main), if the position is long: tighten the stop to 10 ticks below the last swing low. The stop only ever tightens.",
    needs: "Needs: Position side, Swing low · recorded history: none needed",
    stop: true,
    ex: "illustrative: swing low 63,950 → the stop moves to 63,949",
  },
  {
    t: "T4",
    title: "Partial TP ladder at 1R/2R/3R",
    s: "Three rules, one per rung: When the position changes on BTCUSDT (Main), if unrealised R is at least 1.0: scale out 33 % at market. Once per position.",
    needs: "Needs: Unrealised R · recorded history: none needed · Creates 3 rules",
    ex: "illustrative: 0.30 BTC → 0.10 out at 1R, 0.10 at 2R, 0.10 at 3R",
  },
  {
    t: "T5",
    title: "Time stop (close after N minutes)",
    s: "Every 60 s on BTCUSDT (Main), if the position is older than 30 min and unrealised R is below 0.2: flatten the position and tag the journal time-stop. Once per position.",
    needs: "Needs: Position age, Unrealised R · recorded history: none needed",
    ex: "illustrative: opened 13:10 UTC, at 13:41 UTC with unrealised R 0.1 the position is flattened",
  },
  {
    t: "T6",
    title: "Cancel working orders when spread > N bps",
    s: "When the book updates on BTCUSDT (Main), if the spread is above 8 bps: cancel every working entry order. At most every 60 s.",
    needs: "Needs: Spread (bps) · needs BTCUSDT on the recorded-symbol list (book)",
    ex: "illustrative: spread 9 bps → every working entry order is cancelled",
  },
  {
    t: "T7",
    title: "Daily loss lockout",
    s: "When a position closes on Main, if today's loss is at least 2 % of equity: halt new orders on this account until the next UTC day and notify me (push, high).",
    needs: "Needs: Daily loss · recorded history: none needed",
    ex: "illustrative: equity 10,000 USDT, today's loss 210 USDT → new orders halted until 00:00 UTC",
  },
  {
    t: "T8",
    title: "Halt on tape-speed spike",
    s: "When a trade prints on BTCUSDT (Main), if tape speed is above 3 sigma: halt new orders on this account for 5 min — illustrative: the duration has no field yet (G6). At most every 5 min.",
    needs: "Needs: Tape speed z-score · needs BTCUSDT on the recorded-symbol list (trades)",
    ex: "illustrative: tape speed 3.4 sigma at 13:42:10 UTC → halted until 13:47:10 UTC",
  },
  {
    t: "T9",
    title: "Avoid stops inside a detected liquidity cluster",
    s: "When a 1m bar closes on BTCUSDT (Main), if the nearest liquidity cluster is at most 5 ticks from the price and the position is long: tighten the stop to 10 ticks from the price. The stop only ever tightens.",
    needs:
      "Needs: Distance to liquidity cluster, Position side · needs BTCUSDT on the recorded-symbol list (book)",
    stop: true,
    badge: true,
    ex: "illustrative: price 64,000, cluster 4 ticks below → the stop moves to 63,999 if that is tighter; never move the stop away (memo C11 RULED)",
  },
  {
    t: "T10",
    title: "Reduce leverage when funding exceeds a threshold",
    s: "When the funding rate changes on BTCUSDT (Main), if funding is above 0.05 %: reduce leverage to 5×. Once per day.",
    needs: "Needs: Funding rate · recorded history: none needed",
    ex: "illustrative: funding 0.06 % → leverage set to 5×",
  },
  {
    t: "T11",
    title: "Flatten before funding settlement",
    s: "Every 60 s on BTCUSDT (Main), if funding settles within 5 min and a position is open: flatten the position. Once per day.",
    needs: "Needs: Time to funding, Position open · recorded history: none needed",
    ex: "illustrative: funding at 16:00 UTC → the position is flattened from 15:55 UTC",
  },
  {
    t: "T12",
    title: "Re-arm chase when the book thins",
    s: "When the book updates on BTCUSDT (Main), if either book pressure is below −0.5 or liquidity was pulled: arm the chase limit. At most every 30 s.",
    needs:
      "Needs: Book pressure, Liquidity pulled · needs BTCUSDT on the recorded-symbol list (book)",
    ex: "illustrative: book pressure −0.6 → the chase limit is armed",
  },
];
function templateCard(parent, x, y, w, tp, o) {
  o = o || {};
  const lines = [tp.s, tp.needs];
  if (tp.stop) lines.push("Every position keeps a native stop — you can move it, not delete it.");
  lines.push(tp.ex);
  const c = card(parent, x, y, w, {
    kicker:
      tp.t +
      (tp.badge
        ? " · state variant — no shipped template needs it; T9's metric is exact (memo C3)"
        : ""),
    title: tp.title,
    lines,
    foot:
      "Opens in the form editor" +
      (tp.badge ? " · Uses an estimated detector" : "") +
      (tp.t === "T4" ? " · Creates 3 rules" : ""),
    stk: o.stk,
    idx: o.idx,
  });
  return c;
}
function scr083(b, X, Y, W, o) {
  // the SCR-083 dialog composed (boards 09 and 12): the band, the CMP-043 dialog with search + filters, the twelve cards column-major (n14); returns the bottom y
  o = o || {};
  band(b, X, Y, W, false);
  let y = Y + 24 + 16;
  const dx = X + (W - NUM.column) / 2,
    dw = NUM.column;
  const dialogTop = y;
  const dialogBg = mkRect(b, dx - 16, y - 12, dw + 32, 10, "overlay", {
    stroke: "borderStrong",
    radius: 10,
    role: "dialog",
    name: "dialog-bg",
  });
  mkText(
    b,
    'Start from a template  (CMP-043 · role="list" Rule templates — 12 · roving focus · Enter previews · Esc closes)',
    dx,
    y,
    dw,
    { size: 16, weight: 700, name: "dialog-title" },
  );
  y += 30;
  let fx = dx;
  fx +=
    pill(b, fx, y, "Search templates…", {
      h: NUM.rowCompact,
      size: 11.5,
      fill: "raised",
      stroke: "borderSelected",
      radius: 6,
      w: 320,
      name: "search",
    }) + 12;
  for (const f of [
    "stops",
    "exits",
    "risk",
    "execution",
    "Uses an estimated detector",
    "Needs recorded data",
  ])
    fx +=
      pill(b, fx, y, f, {
        h: NUM.rowCompact,
        size: 11.5,
        fill: "raised",
        stroke: "borderStrong",
        name: "filter-chip",
      }) + 8;
  y += NUM.rowCompact + 16;
  const gap = 24,
    cw = (dw - 2 * gap) / 3,
    per = 4;
  const ys = [y, y, y];
  for (let i = 0; i < TEMPLATES.length; i++) {
    const col = Math.floor(i / per);
    const c = templateCard(b, dx + col * (cw + gap), ys[col], cw, TEMPLATES[i], {
      stk: TICKET + ":" + (o.stk || "b9-col") + col,
      idx: i % per,
    });
    ys[col] += c.h + 12;
  }
  y = Math.max(ys[0], ys[1], ys[2]) + 4;
  dialogBg.resize(dw + 32, y - dialogTop + 24);
  return y + 12;
}
BUILD[9] = () => {
  const b = place(9, "scr-083-gallery", NUM.screenW + 64, 2800);
  const X = b.x + 32,
    Y = b.y + 28,
    W = NUM.screenW;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — SCR-083 templates gallery (§10): the twelve catalogue cards with the memo's sentences, Needs:, the recorded-history line, Opens in the form editor, T4 Creates 3 rules, T9 tightening-only with the badge as a state variant; search and filters",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "RULED · BQ-3 the badge is a T9 state variant + the filter chip; no 13th template (C-1.2) · memo C11 tightening only for every role · every stop-management card carries the first sentence of sl.note (the rider)",
  );
  y += 24 + GAPY;
  y = scr083(b, X, y, W) - 12 + GAPY; // the twelve cards through templateCard, column-major in 3 aligned columns (n14)
  const notes = grid(
    b,
    X,
    y,
    W,
    [
      {
        kicker: "CARD ANATOMY (CMP-050)",
        title:
          "title (14's name) · the behaviour sentence (memo §2 rows 3–14, verbatim — P2) · Needs: the display_names · the recorded-history line (dependencies ∩ RECORDED_INPUTS: trades, book, liquidations) · Opens in the form editor · a one-line worked example labelled illustrative · Preview",
        body: "all twelve are form-compatible (at most one any-of group); T4 Creates 3 rules (a sequence is three rules or a graph, R3); T9 reads row 11 — tightening only — with a note on the memo's G13 gap; the badge Uses an estimated detector is drawn once on T9's card as a state variant so the filter has a target",
      },
      {
        kicker: "FILTERS · KEYBOARD",
        title:
          "stops · exits · risk · execution · Uses an estimated detector · Needs recorded data; the search over title and sentence",
        body: 'a role="list" named Rule templates — 12 with roving focus: ↑ / ↓ / ← / → move, Enter previews, Esc closes; cards column-major in aligned rows (n14); color.surface.raised, radius.card, elevation.card',
      },
    ],
    2,
    "b9-notes",
  );
  finish(b, notes);
};

// ---- Board 10: SCR-083 preview, empty and no-results -----------------------------------------------------------
BUILD[10] = () => {
  const b = place(10, "scr-083-preview-states", NUM.screenW + 64, 1900);
  const X = b.x + 32,
    Y = b.y + 28,
    W = NUM.screenW;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — SCR-083 preview-before-instantiate, the empty state and the no-results state (§10); where rule.template_previewed, rule.template_instantiated {templateId} and rule.created fire (§17)",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "PROPOSED · a template instantiates a draft in ≤300 ms with no evaluation until armed · the templateId has no contract on main (D02-G10)",
  );
  y += 24 + GAPY;
  const cw = (W - 2 * 24) / 3;
  const p = card(b, X, y, cw, {
    kicker: "PREVIEW — T1 · rule.template_previewed on open",
    title: "Move SL to break-even after 1R",
    lines: [
      TEMPLATES[0].s,
      "Limits: Once per position. · cooldown 1 s · 60 / h · 500 / day · 10 actions a firing · 250 ms an evaluation",
      "No rule notional cap — your account's risk caps still apply. · Turns itself off after 5 errors in a row — you re-arm it.",
      "Every position keeps a native stop — you can move it, not delete it.",
      TEMPLATES[0].ex,
      "Needs: Unrealised R · recorded history: none needed",
    ],
    foot: "Create draft → rule.template_instantiated {templateId}, then the audited rule.created; the draft opens in SCR-081 in ≤300 ms (Create 3 drafts on T4)",
  });
  const e = card(b, X + cw + 24, y, cw, {
    kicker: 'EMPTY STATE · CMP-026 variant="error"',
    title: "Templates are not available — the rule engine is not running.",
    body: "The rule engine is not running — armed rules are not evaluating. Your native stops are held by the exchange and are unaffected.",
    fill: "dangerSubtle",
    stroke: "dangerStrong",
  });
  const n = card(b, X + 2 * (cw + 24), y, cw, {
    kicker: 'NO-RESULTS STATE · CMP-026 variant="filtered-empty"',
    title: "No templates match — clear the search or the filters.",
    body: "a Clear filters button; the list keeps its accessible name Rule templates — 12 (0 shown)",
  });
  y += Math.max(p.h, e.h, n.h) + GAPY;
  const va10 = card(b, X, y, W, {
    fill: "infoSubtle",
    stroke: "info",
    kicker:
      'VIEW-AS (E09-D09 §2.1 STEP 3A) · THE ONE NOTICE OF THE DIALOG · CMP-028 role="status" · Create draft\'s aria-describedby points here',
    title: "Read-only while viewing as {user}.",
    body: "rbac.view_as, the first leg: Create draft / Create 3 drafts is T2 (createRule is refused 403 view_as_read_only); search, the filters and Preview are reads and stay T1 (E09-D09 §2.2 one notice, many pointers)",
  });
  y += va10.h + GAPY;
  const t = tableBlock(
    b,
    X,
    y,
    [360, 700, 760],
    ["Event", "Fires when", "Board"],
    [
      ["rule.template_previewed", "a card's preview opens (Enter or Preview)", "10"],
      [
        "rule.template_instantiated {templateId}",
        "Create draft (three events for T4's three drafts)",
        "10",
      ],
      ["rule.created (audited)", "per draft, after Create draft", "10"],
      [
        "rule.roundtrip_verified {result}",
        "the compile returns — on save and on mode switch only, never per keystroke",
        "03",
      ],
      [
        "rule.roundtrip_mismatch_resolved {choice}",
        "the mismatch dialog's confirm (audited)",
        "03",
      ],
      [
        "rule.saved · rule.validated",
        "Save draft · each validation result (debounced 300 ms)",
        "02",
      ],
    ],
    { stk: TICKET + ":b10-table" },
  );
  finish(b, y + t.h);
};

// ---- Board 11: long content at 200 % --------------------------------------------------------------------------------
BUILD[11] = () => {
  const b = place(11, "long-content-200pct", NUM.screenW + 64, 4200);
  const X = b.x + 32,
    Y = b.y + 28,
    W = NUM.screenW;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — Long content at 200 % (§11, AC sc. 3): 12 conditions, 6 actions, one nested any-of group, the longest shipped metric name (Nearest imbalance zone distance, 31 characters) — the wrapping, the overflow, the sticky action bar, the stacked reflow",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "PROPOSED · rows wrap the metric title, never the verb or the value · sections reflow to stacked cards (16 §3 rule 4) · the action bar stays sticky · the 125 % strip below: single-line rows, nothing clips",
  );
  y += 24 + GAPY;
  band(b, X, y, W, false);
  y += 24 + 16;
  const colX = X + (W - 1400) / 2,
    colW = 1400,
    Z = 2; // 200 %: every px doubles; the 1120 px column becomes 1400 CSS px inside 1920
  const stackedRow = (cy, label, metric, op, value, frag) => {
    // label above control (the stacked reflow); the title may take two lines
    mkText(b, label, colX, cy, colW, {
      size: 11 * Z,
      color: C.text2,
      tok: TOK.text2,
      name: "stacked-label",
    });
    cy += 30;
    let cx = colX;
    cx +=
      pill(b, cx, cy, metric, {
        h: NUM.rowCompact * Z,
        size: 11.5 * Z,
        fill: "raised",
        name: "control",
      }) + 16;
    cx +=
      pill(b, cx, cy, op, {
        h: NUM.rowCompact * Z,
        size: 11.5 * Z,
        fill: "raised",
        name: "control",
      }) + 16;
    cx +=
      pill(b, cx, cy, value, {
        h: NUM.rowCompact * Z,
        size: 11.5 * Z,
        fill: "raised",
        mono: true,
        name: "control",
      }) + 16;
    pill(b, cx, cy, "⋯", {
      h: NUM.rowCompact * Z,
      size: 11.5 * Z,
      w: NUM.rowCompact * Z,
      padX: 12,
      fill: "raised",
      name: "menu",
    });
    cy += NUM.rowCompact * Z + 6;
    const f = mkText(b, frag, colX, cy, colW, {
      size: 11.5 * Z,
      color: C.text2,
      tok: TOK.text2,
      name: "fragment",
    });
    return cy + (f ? f.h : 30) + 10;
  };
  const hd = mkText(
    b,
    "Rule editor — Twelve conditions  ·  DRAFT  ·  Round-trips ✓  ·  v3 · Last saved 13:42:10 UTC",
    colX,
    y,
    colW,
    { size: 18 * Z, weight: 700, name: "rule-name-200" },
  );
  y += (hd ? hd.h : 50) + 12;
  const sent = mkText(
    b,
    "When a 1m bar closes on BTCUSDT (Main), if nearest imbalance zone distance is at most 12 and the position is long and unrealised R is at least 1.0 and … (12 conditions): tighten the stop to 2.0 × ATR(14) from the close and tag the journal wide. At most every 60 s. The stop only ever tightens.",
    colX,
    y,
    colW,
    { size: 13 * Z, name: "sentence-200" },
  );
  y += (sent ? sent.h : 80) + 16;
  const lg = mkText(b, "Conditions — all of  (12 of 32)", colX, y, colW, {
    size: 12 * Z,
    weight: 700,
    color: C.text2,
    tok: TOK.text2,
    name: "legend-200",
  });
  y += (lg ? lg.h : 34) + 8;
  y = stackedRow(
    y,
    "Condition 1 of 12",
    "Nearest imbalance zone distance",
    "is at most",
    "12 ticks",
    "nearest imbalance zone distance is at most 12 — the title wraps at word boundaries; the verb and the value stay on one line",
  );
  y = stackedRow(y, "Condition 2 of 12", "Position side", "is", "long", "the position is long");
  const g0 = y;
  mkText(b, "any of  (Condition group — either … or …)", colX + 48, y, colW, {
    size: 11.5 * Z,
    weight: 700,
    color: C.text2,
    tok: TOK.text2,
    name: "group-legend-200",
  });
  y += 36;
  y = stackedRow(
    y,
    "Condition 3 of 12",
    "Spread (bps)",
    "is above",
    "8 bps",
    "either the spread is above 8 bps",
  );
  y = stackedRow(
    y,
    "Condition 4 of 12",
    "Tape speed z-score",
    "is above",
    "3 sigma",
    "or tape speed is above 3 sigma",
  );
  bracket(b, colX + 24, g0, y - 10, "text3", { name: "any-of-bracket-200", width: 4 });
  const more = mkText(
    b,
    "Conditions 5 … 12 follow below the viewport (the list scrolls; the sticky action bar stays in view) — then the 6 actions",
    colX,
    y,
    colW,
    { size: 12 * Z, color: C.text2, tok: TOK.text2, name: "more-200" },
  );
  y += (more ? more.h : 34) + 24;
  const reasonLine = Math.ceil(11.5 * Z * 1.38) + 14; // the T2 reason on its own line under the controls: the bar grows by that line (spec §11)
  mkRect(b, colX, y, colW, NUM.actionBar * Z + reasonLine, "raised", {
    stroke: "border",
    role: "action-bar",
    name: "action-bar-200",
  });
  let cx = colX + 24;
  const py = y + (NUM.actionBar * Z - NUM.rowCompact * Z) / 2;
  for (const lb of ["Validate", "Simulate"])
    cx +=
      pill(b, cx, py, lb, {
        h: NUM.rowCompact * Z,
        size: 12 * Z,
        fill: "raised",
        stroke: "borderStrong",
        radius: 12,
        name: "btn-200",
      }) + 16;
  cx +=
    pill(b, cx, py, "Save draft", {
      h: NUM.rowCompact * Z,
      size: 12 * Z,
      weight: 600,
      fill: "primary",
      stroke: "primary",
      radius: 12,
      textColor: C.onAction,
      textTok: TOK.onAction,
      name: "btn-save-200",
    }) + 16;
  pill(
    b,
    cx,
    py,
    LOCK + "Arm…",
    Object.assign(
      { h: NUM.rowCompact * Z, size: 12 * Z, weight: 600, radius: 12, name: "btn-arm-200" },
      T2,
    ),
  );
  mkText(b, "Simulate first — 5 fires or 24 h.", colX + 24, y + NUM.actionBar * Z - 2, colW - 48, {
    size: 11.5 * Z,
    color: C.text2,
    tok: TOK.text2,
    name: "t2-reason-200",
  });
  y += NUM.actionBar * Z + reasonLine + 8;
  const rc200 = mkText(
    b,
    "the T2 reason at 200 %: it no longer fits beside Arm… in the 96 CSS px bar, so it moves onto its own line under the bar's controls and the bar grows by that line — never truncated, never a tooltip-only copy",
    colX,
    y,
    colW,
    { size: 12.5, color: C.text2, tok: TOK.text2, name: "t2-reason-caption" },
  );
  y += (rc200 ? rc200.h : 18) + GAPY;
  // the 125 % strip (AC sc. 3's other zoom, drawn as a frame): the 1120 px column becomes 1400 CSS px inside 1920; rows stay single-line with the label column beside the control; nothing clips
  const Z1 = 1.25;
  const sl = mkText(
    b,
    "125 % — the 1120 px column becomes 1400 CSS px inside 1920: rows stay single-line with the 160 px label column (200 CSS px) beside the control; the sentence wraps at word boundaries; the action bar stays sticky; nothing clips — the stacked reflow is the 200 % rule only",
    X,
    y,
    W,
    { size: 14, weight: 700, name: "strip-125-title" },
  );
  y += (sl ? sl.h : 20) + 8;
  band(b, X, y, W, false);
  y += 24 + 16;
  const row125 = (cy, label, metric, op, value, frag) => {
    // one single-line row at 125 %: the label column beside the controls
    mkText(b, label, colX, cy + 4 * Z1, NUM.labelColumn * Z1 - 8, {
      size: 12 * Z1,
      color: C.text2,
      tok: TOK.text2,
      name: "field-label-125",
    });
    let cx = colX + NUM.labelColumn * Z1;
    cx +=
      pill(b, cx, cy, metric, {
        h: NUM.rowCompact * Z1,
        size: 11.5 * Z1,
        fill: "raised",
        name: "control-125",
      }) + 10;
    cx +=
      pill(b, cx, cy, op, {
        h: NUM.rowCompact * Z1,
        size: 11.5 * Z1,
        fill: "raised",
        name: "control-125",
      }) + 10;
    cx +=
      pill(b, cx, cy, value, {
        h: NUM.rowCompact * Z1,
        size: 11.5 * Z1,
        fill: "raised",
        mono: true,
        name: "control-125",
      }) + 10;
    pill(b, cx, cy, "⋯", {
      h: NUM.rowCompact * Z1,
      size: 11.5 * Z1,
      w: NUM.rowCompact * Z1,
      padX: 8,
      fill: "raised",
      name: "menu-125",
    });
    const f = mkText(
      b,
      frag,
      colX + NUM.labelColumn * Z1,
      cy + NUM.rowCompact * Z1 + 2,
      colW - NUM.labelColumn * Z1,
      { size: 11.5 * Z1, color: C.text2, tok: TOK.text2, name: "fragment-125" },
    );
    return cy + NUM.rowCompact * Z1 + 2 + (f ? f.h : 20) + 6;
  };
  const h125 = mkText(
    b,
    "Rule editor — Twelve conditions  ·  DRAFT  ·  Round-trips ✓  ·  v3 · Last saved 13:42:10 UTC",
    colX,
    y,
    colW,
    { size: 18 * Z1, weight: 700, name: "rule-name-125" },
  );
  y += (h125 ? h125.h : 32) + 8;
  const lg125 = mkText(b, "Conditions — all of  (12 of 32)", colX, y, colW, {
    size: 12 * Z1,
    weight: 700,
    color: C.text2,
    tok: TOK.text2,
    name: "legend-125",
  });
  y += (lg125 ? lg125.h : 22) + 6;
  y = row125(
    y,
    "Condition 1 of 12",
    "Nearest imbalance zone distance",
    "is at most",
    "12 ticks",
    "nearest imbalance zone distance is at most 12 — at 125 % the title, the verb and the value stay on one row",
  );
  y = row125(y, "Condition 2 of 12", "Position side", "is", "long", "the position is long");
  mkRect(b, colX, y, colW, NUM.actionBar * Z1, "raised", {
    stroke: "border",
    role: "action-bar",
    name: "action-bar-125",
  });
  let cx1 = colX + 16;
  const py1 = y + (NUM.actionBar * Z1 - NUM.rowCompact * Z1) / 2;
  for (const lb of ["Validate", "Simulate"])
    cx1 +=
      pill(b, cx1, py1, lb, {
        h: NUM.rowCompact * Z1,
        size: 12 * Z1,
        fill: "raised",
        stroke: "borderStrong",
        radius: 8,
        name: "btn-125",
      }) + 10;
  cx1 +=
    pill(b, cx1, py1, "Save draft", {
      h: NUM.rowCompact * Z1,
      size: 12 * Z1,
      weight: 600,
      fill: "primary",
      stroke: "primary",
      radius: 8,
      textColor: C.onAction,
      textTok: TOK.onAction,
      name: "btn-save-125",
    }) + 10;
  pill(b, cx1, py1, "🔒 Arm…", {
    h: NUM.rowCompact * Z1,
    size: 12 * Z1,
    weight: 600,
    fill: "raised",
    stroke: "border",
    radius: 8,
    textColor: C.text3,
    textTok: TOK.text3,
    name: "btn-arm-125",
  });
  y += NUM.actionBar * Z1 + GAPY;
  // SCR-083 at 200 % (spec §11): the dialog fills the viewport, the filter chips wrap onto a second row, the twelve cards reflow to one column and the preview pane stacks below the list; nothing clips
  const s83 = mkText(
    b,
    "SCR-083 at 200 % — the dialog fills the viewport; the filter chips wrap onto a second row; the twelve cards reflow to one column; the preview pane stacks below the list instead of beside it; nothing clips",
    X,
    y,
    W,
    { size: 14, weight: 700, name: "strip-083-200-title" },
  );
  y += (s83 ? s83.h : 20) + 8;
  band(b, X, y, W, false);
  y += 24 + 16;
  const dTop = y;
  const dbg = mkRect(b, colX - 16, y - 12, colW + 32, 10, "overlay", {
    stroke: "borderStrong",
    radius: 10,
    role: "dialog",
    name: "dialog-bg-200",
  });
  const dt = mkText(b, "Start from a template", colX, y, colW, {
    size: 16 * Z,
    weight: 700,
    name: "dialog-title-200",
  });
  y += (dt ? dt.h : 44) + 8;
  let fx = colX,
    fy = y;
  fx +=
    pill(b, fx, fy, "Search templates…", {
      h: NUM.rowCompact * Z,
      size: 11.5 * Z,
      fill: "raised",
      stroke: "borderSelected",
      radius: 12,
      w: 640,
      name: "search-200",
    }) + 24;
  for (const f of [
    "stops",
    "exits",
    "risk",
    "execution",
    "Uses an estimated detector",
    "Needs recorded data",
  ]) {
    const pw = pillTextW(f, 11.5 * Z) + 32;
    if (fx + pw > colX + colW) {
      fx = colX;
      fy += NUM.rowCompact * Z + 12;
    } // the chips wrap onto a second row
    fx +=
      pill(b, fx, fy, f, {
        h: NUM.rowCompact * Z,
        size: 11.5 * Z,
        fill: "raised",
        stroke: "borderStrong",
        name: "filter-chip-200",
      }) + 16;
  }
  y = fy + NUM.rowCompact * Z + 24;
  const card200 = (cy, kicker, ttl, lines) => {
    // one card of the single column at 200 %: every size doubled; a block for the relayout pass
    const pad = 28,
      blk = TICKET + ":" + ++blockSeq;
    const bg = mkRect(b, colX, cy, colW, 10, "raised", {
      stroke: "border",
      radius: 16,
      role: "card-bg",
      bg: true,
      pad,
      gap: 6,
      blk,
      stk: blk,
      name: "card-200",
    });
    let ty = cy + pad;
    const k = mkText(b, kicker, colX + pad, ty, colW - 2 * pad, {
      size: 11 * Z,
      weight: 600,
      color: C.text3,
      tok: TOK.text3,
      name: "kicker-200",
      blk,
      stk: blk,
    });
    ty += (k ? k.h : 30) + 4;
    const tt = mkText(b, ttl, colX + pad, ty, colW - 2 * pad, {
      size: 15 * Z,
      weight: 700,
      name: "title-200",
      blk,
      stk: blk,
    });
    ty += (tt ? tt.h : 40) + 8;
    for (const ln of lines) {
      const l = mkText(b, ln, colX + pad, ty, colW - 2 * pad, {
        size: 12.5 * Z,
        color: C.text2,
        tok: TOK.text2,
        name: "line-200",
        blk,
        stk: blk,
      });
      ty += (l ? l.h : 34) + 6;
    }
    const h = ty - cy + pad - 6;
    bg.resize(colW, h);
    return cy + h + 24;
  };
  y = card200(y, "T1", TEMPLATES[0].title, [
    TEMPLATES[0].s,
    TEMPLATES[0].needs,
    "Every position keeps a native stop — you can move it, not delete it.",
    "Opens in the form editor",
  ]);
  y = card200(
    y,
    "T2 — the second card of the single column; cards 3–12 follow below the viewport (the list scrolls)",
    TEMPLATES[1].title,
    [TEMPLATES[1].s],
  );
  y = card200(y, "PREVIEW — stacked below the list at 200 %", TEMPLATES[0].title, [
    "Create draft → the draft opens in SCR-081 in ≤300 ms",
    TEMPLATES[0].ex,
  ]);
  dbg.resize(colW + 32, y - dTop + 12);
  y += GAPY;
  const notes = grid(
    b,
    X,
    y,
    W,
    [
      {
        kicker: "THE RULES (§11)",
        title:
          "a row wraps the metric title, never the verb or the value; a ≥40-character title wraps at word boundaries and the row grows — no shipped name needs it, none is invented",
        body: "the value column keeps ≥24 px targets (48 CSS px at 200 %); the five sections reflow from the 160 px label column to stacked cards (label above control) rather than clipping; the summary block wraps at word boundaries and never truncates; the picker reflows to one column; CMP-234 lists all 12 entries with an internal scroll of ≤6 visible",
      },
      {
        kicker: "THE RULE DRAWN",
        title:
          "root all of with 10 rows and one any-of group of 2 (12 ≤ 32), 6 actions (≤ 10) — inside the shipped form subset",
        body: "the longest shipped display_name is Nearest imbalance zone distance (31 characters; the tool measures); the longest kernel-bound title is VWAP band sigma; the 125 % strip: the 1120 px column becomes 1400 CSS px inside 1920, rows stay single-line, nothing clips",
      },
    ],
    2,
    "b11-notes",
  );
  finish(b, notes);
};

// ---- Board 12: themes, densities, greyscale ------------------------------------------------------------------------
BUILD[12] = () => {
  const b = place(12, "themes-densities-greyscale", W_BOARD, 2400);
  const X = b.x + 32,
    Y = b.y + 28,
    W = W_BOARD - 64;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — Themes and densities (§15): one full SCR-081 and one SCR-083 composition at comfortable + light with the 1280×800 viewport outlined; light, high-contrast and comfortable specimens of the header, a row, a picker option, the read‑only card, the warning banner and a template card; the greyscale strip of the four indicator states; the measured pairs",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "MEASURED · 32 gated rows PASS in dark / light / high-contrast, 0 FAIL · 18 PROPOSED pairs.mjs rows · m5 and n5 pairs rejected, never drawn · the audit tool's numbers",
  );
  y += 24 + GAPY;
  const strip = mkText(
    b,
    "Greyscale strip — the four indicator states without hue: ✓ Round-trips · ⚠ Graph-only construct — read-only here · ✕ Round-trip mismatch · ? Not verified — glyph + word + fill lightness keep them apart",
    X,
    y,
    W,
    { size: 12.5, weight: 600, name: "greyscale-title" },
  );
  y += (strip ? strip.h : 18) + 8;
  let cx = X;
  for (const st of ["identical", "graph_only_construct", "mismatch", "unverified"])
    cx += indicatorChip(b, cx, y, st) + 16;
  y += 24 + GAPY;
  const t = tableBlock(
    b,
    X,
    y,
    [60, 560, 110, 90, 90, 90, 90, 150, 536],
    [
      "#",
      "Foreground on background",
      "Role",
      "Dark",
      "Light",
      "HC",
      "Verdict",
      "pairs.mjs",
      "Where",
    ],
    [
      [
        "1",
        "color.text.primary on color.surface.canvas",
        "text",
        "15.20",
        "16.78",
        "17.21",
        "PASS",
        "registered",
        "header title, sentence, row values",
      ],
      [
        "2",
        "color.text.secondary on color.surface.canvas",
        "text",
        "9.33",
        "9.65",
        "15.20",
        "PASS",
        "registered",
        "row fragments, option descriptions",
      ],
      [
        "3",
        "color.text.tertiary on color.surface.canvas",
        "text + non-text",
        "5.96",
        "6.36",
        "11.87",
        "PASS",
        "PROPOSED",
        "Last saved caption; the any-of bracket ink (n5)",
      ],
      [
        "4",
        "color.text.primary on color.surface.raised",
        "text",
        "14.35",
        "15.62",
        "16.25",
        "PASS",
        "registered",
        "cards, action-bar labels, dialog text",
      ],
      [
        "5",
        "color.text.secondary on color.surface.raised",
        "text",
        "8.81",
        "8.98",
        "14.35",
        "PASS",
        "registered",
        "T2 reason sentence, card body",
      ],
      [
        "6",
        "color.text.tertiary on color.surface.raised",
        "text",
        "5.62",
        "5.92",
        "11.21",
        "PASS",
        "registered",
        "T2 kept label (E09-D09)",
      ],
      [
        "7",
        "color.text.primary on color.status.success.subtle",
        "text",
        "10.21",
        "15.41",
        "11.56",
        "PASS",
        "PROPOSED",
        "indicator 1 word",
      ],
      [
        "8",
        "color.status.success.strong on color.status.success.subtle",
        "non-text",
        "6.69",
        "3.34",
        "6.69",
        "PASS",
        "PROPOSED",
        "indicator 1 glyph",
      ],
      [
        "9",
        "color.text.primary on color.status.warning.subtle",
        "text",
        "9.86",
        "15.62",
        "11.16",
        "PASS",
        "registered",
        "indicator 2 word, read‑only card, warning banner",
      ],
      [
        "10",
        "color.text.secondary on color.status.warning.subtle",
        "text",
        "6.05",
        "8.98",
        "9.86",
        "PASS",
        "PROPOSED",
        "the read‑only card's kicker (m5 fix)",
      ],
      [
        "11",
        "color.status.warning.strong on color.status.warning.subtle",
        "non-text",
        "7.56",
        "4.11",
        "7.56",
        "PASS",
        "registered",
        "indicator 2 glyph, banner glyph",
      ],
      [
        "12",
        "color.text.primary on color.status.danger.subtle",
        "text",
        "12.06",
        "14.64",
        "13.66",
        "PASS",
        "registered",
        "indicator 3 word, DCR-11 banner",
      ],
      [
        "13",
        "color.status.danger.strong on color.status.danger.subtle",
        "non-text",
        "7.83",
        "3.85",
        "7.83",
        "PASS",
        "PROPOSED",
        "indicator 3 glyph (dark danger.strong = palette.amber.400)",
      ],
      [
        "15",
        "color.text.primary on color.surface.hover",
        "text",
        "12.22",
        "14.37",
        "13.83",
        "PASS",
        "PROPOSED",
        "indicator 4 word, Checking…, the DRAFT pill",
      ],
      [
        "17",
        "color.status.danger.default on color.surface.canvas",
        "non-text",
        "3.63",
        "9.62",
        "4.30",
        "PASS",
        "PROPOSED",
        "the invalid row's 2 px outline",
      ],
      [
        "19",
        "color.text.primary on color.status.info.subtle",
        "text",
        "10.74",
        "15.44",
        "12.16",
        "PASS",
        "registered",
        "the CMP-227 word, CMP-158's sentence",
      ],
      [
        "20",
        "color.status.info.default on color.status.info.subtle",
        "non-text",
        "4.64",
        "3.44",
        "4.64",
        "PASS",
        "PROPOSED",
        "the chip's glyph and outline",
      ],
      [
        "21",
        "color.focus.ring on color.surface.canvas",
        "non-text",
        "7.05",
        "6.30",
        "18.32",
        "PASS",
        "registered",
        "focus ring on rows",
      ],
      [
        "23",
        "color.focus.ring on color.status.warning.subtle",
        "non-text",
        "4.57",
        "5.86",
        "11.88",
        "PASS",
        "PROPOSED",
        "focus ring on the read‑only card",
      ],
      [
        "28",
        "color.text.on-action on color.action.primary.default",
        "text",
        "4.76",
        "4.76",
        "7.45",
        "PASS",
        "registered",
        "Save draft, Create draft",
      ],
      [
        "29",
        "color.text.on-action on color.status.danger.default",
        "text",
        "5.05",
        "10.31",
        "4.54",
        "PASS",
        "PROPOSED",
        "Arm… (the destructive class)",
      ],
      [
        "—",
        "color.text.tertiary on color.status.warning.subtle",
        "rejected-text",
        "3.86",
        "5.92",
        "7.70",
        "FAIL (dark), never used",
        "—",
        "m5: never drawn; kickers on amber use color.text.secondary",
      ],
      [
        "—",
        "color.border.strong on color.surface.canvas",
        "rejected-non-text",
        "1.91",
        "1.57",
        "1.91",
        "FAIL, never used",
        "—",
        "n5: not the bracket ink; color.text.tertiary is",
      ],
      [
        "—",
        "color.text.disabled on color.surface.raised",
        "rejected-text",
        "2.86",
        "3.74",
        "2.86",
        "FAIL, never used",
        "—",
        "E09-D09 T2 keeps color.text.tertiary for a disabled label",
      ],
      [
        "—",
        "color.border.default on color.surface.raised",
        "decorative",
        "1.41",
        "1.22",
        "2.86",
        "reported, not gated",
        "—",
        "the T2 hairline and the card hairline",
      ],
    ],
    { stk: TICKET + ":b12-table", size: 11 },
  );
  y += t.h + GAPY;
  const cw = (W - 2 * 24) / 3;
  const cells = [
    {
      kicker: "LIGHT · HEADER + ROW",
      title: "the same anatomy: a token swap only (15 §0.3 rule 1)",
      body: "text.primary on canvas 16.78:1; the invalid outline color.status.danger.default on canvas 9.62:1; the indicator fills stay apart by glyph + word",
    },
    {
      kicker: "HIGH-CONTRAST · PICKER OPTION + READ‑ONLY CARD",
      title:
        "text.primary #F6F8FA on the dark surfaces (17.21:1); the amber card 11.16:1; the chip word 12.16:1",
      body: "14 high-contrast overrides over dark (themes.json); the focus ring 18.32:1 on canvas",
    },
    {
      kicker: "COMFORTABLE · WARNING BANNER + TEMPLATE CARD",
      title:
        "32 px rows and fields (size.control.height), space.inset.md; nothing else differs (16 §3 rule 1)",
      body: "the smallest target 32 × 32 px; compact: 24 × 24 px by padding; no essential exception on either screen",
    },
  ];
  const g = grid(b, X, y, W, cells, 3, "b12-cells");
  y = g + GAPY;
  const fc = card(b, X, y, W, {
    kicker: "FORCED COLOURS · PER SURFACE (05 §5 item 7; the E12-D02 §7 form)",
    title:
      "under forced-colors: active every state on both screens survives as text, border or glyph, never as a fill alone — T2: the CMP-019 lock glyph + the full label + the reason sentence (the raised fill and the hairline collapse to a CanvasText border); the indicator: glyph + word; invalid: the 2 px outline (CanvasText) + the glyph + Row n; CMP-158 and the read‑only card: their text and glyph; the estimated chip (CMP-227): the literal word; Buy / Sell and the destructive class: glyph + word; the DEMO / LIVE band: the text badge; cards, chips and filter chips (SCR-083 and its preview): a CanvasText border, the badge as text",
    titleSize: 12.5,
    body: "the dark / light / high-contrast matrix above is unaffected (forced colours replace the palette)",
  });
  y += fc.h + GAPY;
  // the two compositions at comfortable + light (the ticket's density × theme scope as frames, not an argument): SCR-081 02-1 draft (S1), then SCR-083; 1280 wide, the 1280×800 viewport outlined (16 §8)
  const ct = mkText(
    b,
    "Comfortable + light — one full SCR-081 (02-1 draft, S1) and one SCR-083 composition at 1280 wide; the 1280×800 viewport is outlined (16 §8); 32 px rows and controls, header 40 px, action bar 56 px, space.inset.md; the light column's hexes — the same anatomy, a token swap only (15 §0.3 rule 1)",
    X,
    y,
    W,
    { size: 14, weight: 700, name: "comp-title" },
  );
  y += (ct ? ct.h : 20) + 8;
  const compW = NUM.cropW;
  const c1y = y;
  let c1h = 0;
  withLightComfortable(() => {
    const bg = mkRect(b, X, c1y, compW, 10, "canvas", {
      stroke: "borderStrong",
      radius: 6,
      role: "crop",
      name: "light-canvas-scr081",
    });
    const bottom = scr081(b, X, c1y, compW, {
      rows: S1_ROWS,
      actions: S1_ACTIONS,
      armReason: "Simulate first — 5 fires or 24 h.",
    });
    c1h = bottom - c1y + 16;
    bg.resize(compW, c1h);
    mkRect(b, X, c1y, compW, NUM.cropH, null, {
      stroke: "borderSelected",
      strokeWidth: 2,
      radius: 4,
      role: "viewport",
      name: "viewport-1280x800",
    });
  });
  y = c1y + c1h + 8;
  const vc = mkText(
    b,
    "SCR-081 at comfortable + light: the outlined area is the 1280×800 viewport — below it the form scrolls and the action bar stays sticky; 1024 px column",
    X,
    y,
    compW,
    { size: 11.5, color: C.text2, tok: TOK.text2, name: "viewport-caption" },
  );
  y += (vc ? vc.h : 16) + GAPY;
  const c2y = y;
  let c2h = 0;
  withLightComfortable(() => {
    const bg = mkRect(b, X, c2y, compW, 10, "canvas", {
      stroke: "borderStrong",
      radius: 6,
      role: "crop",
      name: "light-canvas-scr083",
    });
    const bottom = scr083(b, X, c2y, compW, { stk: "b12-col" });
    c2h = bottom - c2y + 16;
    bg.resize(compW, c2h);
    mkRect(b, X, c2y, compW, NUM.cropH, null, {
      stroke: "borderSelected",
      strokeWidth: 2,
      radius: 4,
      role: "viewport",
      name: "viewport-1280x800",
    });
  });
  y = c2y + c2h + 8;
  const vc2 = mkText(
    b,
    "SCR-083 at comfortable + light: the twelve cards in the 1024 px dialog; the outlined area is the 1280×800 viewport — the list scrolls below it",
    X,
    y,
    compW,
    { size: 11.5, color: C.text2, tok: TOK.text2, name: "viewport-caption" },
  );
  y += (vc2 ? vc2.h : 16) + GAPY;
  const c = card(b, X, y, W, {
    kicker: "DS CHANGE REQUESTS (§15) · EACH WITH ITS OWNER",
    title:
      "missing names: font.mono · color.border.invalid · space.rulegroup.indent · color.status.warn · bare color.status.danger / color.status.info · color.chip.* (E36-D03 / the DS CODEOWNER) · 18 PROPOSED pairs.mjs rows (E36-S01) · an encodings.json row for the indicator (E36-S03) · icon/round-trip-ok · icon/round-trip-partial · icon/round-trip-mismatch · icon/round-trip-unverified (PROPOSED), icon/lock and icon/native-sl-shield reused",
    body: "light color.status.danger.strong resolves to the same hex as warning.strong (#9A6A05) and dark to palette.amber.400 — reported for the DS CODEOWNER; the indicator's states stay apart by glyph and word regardless; cvd_sim.py runs on every export (pending the boards)",
  });
  finish(b, y + c.h);
};

// ---- Board 13: keyboard, names, announcements, counts -----------------------------------------------------------------
BUILD[13] = () => {
  const b = place(13, "keyboard-a11y-copy", W_BOARD, 3000);
  const X = b.x + 32,
    Y = b.y + 28,
    W = W_BOARD - 64;
  let y =
    Y +
    title(
      b,
      X,
      Y,
      W,
      "E36-D02 — Keyboard, focus and targets (§12), names and roles (§13), the announcement policy, the observability callouts, the C / G / Q counts and the `15` amendments summary (§16, §20)",
      SRC,
    );
  stamp(
    b,
    X,
    y,
    "RULED · BQ-5 P11 is the model: Tab to enter, arrows move, Shift+F10 the row menu, Esc innermost, no drag, no invented global key · Ctrl+S, Ctrl+Enter = Save draft, Alt+G candidates; E36-D04 reviews",
  );
  y += 24 + GAPY;
  const t = tableBlock(
    b,
    X,
    y,
    [230, 520, 300, 480, 246],
    ["Key", "Action", "Focus after", "Global conflict? (05 §3.2 / §3.3)", "Status"],
    [
      [
        "Tab / Shift+Tab",
        "enter / leave the row list (one stop)",
        "the current row",
        "none",
        "P11",
      ],
      [
        "↑ / ↓",
        "move between rows (and into / out of an any-of group)",
        "the row",
        "none inside a composite (05 §3.4 item 2)",
        "P11",
      ],
      [
        "→ / ←",
        "move between a row's controls (metric → operator → value → menu)",
        "the control",
        "none",
        "P11",
      ],
      [
        "Shift+F10 / the menu button",
        "open the row menu: Move up · Move down · Duplicate · Remove",
        "the first item; on close, the row",
        "none (the standard context-menu key)",
        "P11",
      ],
      [
        "Esc",
        "cancel the innermost thing: the picker, the menu, the dialog, then nothing",
        "the control that opened it",
        "reserved universal cancel — untouched",
        "lane agreement",
      ],
      [
        "Enter / Space / Ctrl+S / Ctrl+Enter / a click on a T2 control",
        "Arm…, Save draft, Validate, Simulate, a T2 picker or option, Start recording: nothing staged — no dialog, no request, no state change; the reason (or the one notice's sentence) re-shown inline at the point of action, announced once, politely",
        "stays",
        "none",
        "E09-D09 §2.2, §9.3",
      ],
      [
        "↑ / ↓ in the action picker or CMP-157",
        "land on a T2 option (its second line is the reason); Enter on it as above",
        "the option",
        "none",
        "E09-D09 §9.3",
      ],
      ["Ctrl+S", "Save draft", "stays", "not in the §3.2 map", "candidate; E36-D04 reviews"],
      [
        "Ctrl+Enter",
        "Save draft (the product-wide commit chord, memo C8)",
        "stays",
        "Submit order is a trading-view binding — a mutually exclusive focus context (§3.3 rule 1 (3))",
        "candidate; E36-D04 reviews",
      ],
      [
        "Alt+G",
        "switch editor (form ↔ graph; CMP-235)",
        "the same rule in the other editor",
        "not in the §3.2 map",
        "candidate; E36-D04 reviews",
      ],
      [
        "Alt+Shift+↑ / Alt+Shift+↓",
        "move the row up / down (the menu path is primary)",
        "the moved row; the move announced",
        "none (Alt+↑/↓ alone is the Chart timeframe chord)",
        "memo G10 candidate for the E49 keymap owner",
      ],
      [
        "Alt+↑/↓, Ctrl+D",
        "dropped — reorder and duplicate go through the row menu",
        "—",
        "Alt+↑/↓ = Chart timeframe; Ctrl+D = browser bookmark (§3.3 rule 4)",
        "memo C8 — the 14 owner",
      ],
    ],
    { stk: TICKET + ":b13-keys" },
  );
  y += t.h + GAPY;
  const n = tableBlock(
    b,
    X,
    y,
    [330, 230, 640, 576],
    ["Element", "Role", "Accessible name (source)", "States / properties"],
    [
      [
        "the editor",
        "region",
        "Rule editor — BE after 1R (aria-label); aria-describedby → the sentence block",
        "aria-busy while validating",
      ],
      [
        "each section",
        "group (fieldset / legend)",
        "Scope · Trigger · Conditions — all of · Actions · Options",
        "—",
      ],
      [
        "a condition row",
        "group",
        "Condition 1 of 2 (aria-label); aria-describedby → its fragment",
        "aria-invalid + aria-describedby → the message when invalid; roving tabindex",
      ],
      [
        "the metric trigger / CMP-157",
        "combobox",
        "Metric + the current display_name",
        "aria-expanded, aria-activedescendant; options aria-selected; groups named by category",
      ],
      [
        "the estimated chip (CMP-227)",
        "button",
        "Estimated, In stop-hunt zone — the literal word",
        'aria-haspopup="dialog" (SCR-058)',
      ],
      [
        "the round‑trip indicator",
        "status (the word) + button (the chip)",
        "Round-trip: Round-trips",
        "aria-busy while checking; aria-describedby → the tooltip",
      ],
      [
        "the read‑only card",
        "group",
        "Authored in the graph editor: {sentence}",
        'aria-readonly="true"; Open in the graph editor is a native link',
      ],
      [
        "CMP-234 ValidationPanel",
        "log",
        "Validation — 2 errors, 0 warnings",
        "errors first; each entry a button",
      ],
      ["CMP-158", "note", "its sentence (text content)", "non-dismissible; not in the Tab order"],
      [
        "the Arm button · Save draft · Validate · Simulate",
        "button",
        "Arm… · Save draft · Validate · Simulate (the full label, kept)",
        "aria-disabled + aria-describedby → the reason or the one notice (never disabled); the CMP-019 lock Not available leads the label",
      ],
      [
        "a T2 picker option (CMP-157 / the action picker)",
        "option",
        "{display_name} · {unit} — the full label",
        "aria-disabled + aria-describedby → its second line (the reason); still reached by aria-activedescendant",
      ],
      [
        "the armed notice (02-5) · the engine-down banner (02-6)",
        "status · alert",
        "their sentences (text content)",
        "the one node every gated control's aria-describedby points at (E09-D09 §2.2 one notice, many pointers)",
      ],
      [
        "the view-as notice (any frame; the gallery's)",
        "status",
        "Read-only while viewing as {user}. (text content; rbac.view_as)",
        "the one node every write's aria-describedby points at while the session views as another user (E09-D09 §2.1 step 3a, §2.2)",
      ],
      [
        "the template list / a card",
        "list / listitem + button",
        "Rule templates — 12 / {title}. {sentence}. Opens in the form editor.",
        "roving tabindex; aria-pressed on the active filter chips",
      ],
    ],
    { stk: TICKET + ":b13-names" },
  );
  y += n.h + GAPY;
  const cw = (W - 2 * 24) / 3;
  const g = grid(
    b,
    X,
    y,
    W,
    [
      {
        kicker: "ANNOUNCEMENT POLICY (§13) · ≤1 AMBIENT PER 5 S",
        title:
          'the summary politely on blur of a row or on save (S1 = 44 words ≈ 9–13 s; never per keystroke, P12) · the CMP-234 error count on every recompile · the estimated-detector banner role="status" once · the indicator\'s word once on change · the vocabulary-unavailable banner role="alert" once · the row move Moved to position 2 of 3 · sl.kept once per attempt · the picker\'s results count per query · a T2 press → its reason (or the one notice\'s sentence), polite, once per press',
        body: "E06-D03 D5: a ~10-word summary takes 2–3 s to speak; nothing announces on a tick; nothing steals focus (05 §3.4 item 3)",
      },
      {
        kicker: "OBSERVABILITY (§17)",
        title:
          "rule.roundtrip_verified {result} on compile return (save / mode switch) · rule.roundtrip_mismatch_resolved {choice} audited · rule.saved · rule.validated · rule.template_previewed · rule.template_instantiated {templateId} · rule.created",
        body: "boards 03 and 10 carry the callouts; nothing else is instrumented by design",
      },
      {
        kicker: "COUNTS (§20) · THE `15` AMENDMENTS (§16)",
        title:
          "21 contradictions (D02-C1…21) · 15 gaps (D02-G1…15) · 12 questions (BQ-1..7 RULED, D02-Q8…12 PROPOSED) · 11 `15` amendment rows for E36-D03 (CMP-140 / 141 / 142 / 143 / 144 / 145 / 157 / 158 / 233 / 234 / 235) · 8 handoff blocks · 32 gated pairs, 18 PROPOSED, 0 FAIL · T2: CMP-079 RbacGate + the CMP-019 lock on CMP-140 / 142 / 145 / 157 / 233; rbac.view_as the first leg on every write; form validity outside the grammar (no lock, no key) · two A-rows to E09-D09 (D02-A1 / D02-A2 — the three rule.* keys)",
        body: "hand-offs: E36-D03 the amendments and the DS requests; E36-D04 the keyboard / name tables and the hotkey candidates; E36-D05 the handoff file; E36-T01 / S01–S04 the contracts; E35-D02 the SCR-085 string; E37-D01 the mirror; E40-D02 badge rows 10–11; E49 the keymap rows; the 14 / 15 / 12 / 11 owners; the memo owner (D02-C12 / D02-C13)",
      },
    ],
    3,
    "b13-notes",
  );
  finish(b, g);
};

const wanted = BOARDS.filter((bd) => want(bd.n)).map((bd) => bd.n);
const stop = gate(wanted);
if (stop) return stop;
const olds = PART === null || PART === 1 ? oldPlanned() : [];
try {
  for (const n of wanted) drawBoard(n);
} catch (e) {
  throw rolledBack(e);
}
clearPlanned(olds);

// ---------------------------------------------------------------- result ------------------------------------
try {
  page.setPluginData(TAG, "v1");
  page.setPluginData(TAG + ":built", new Date().toISOString());
} catch (e) {
  warn("page tag", e);
}
const exportCommands = built
  .map((x) => "python3 docs/design/_tools/penpot_export.py " + x.id + " " + x.exportAs)
  .join("\n");
return {
  writer: WRITER,
  version: VERSION,
  pageId: page.id,
  pageName: page.name,
  createdPage,
  removed,
  duplicatePages,
  pathFallback,
  boards: built,
  part: PART,
  partPlan: partPlan.filter((p) => wanted.indexOf(p.board) >= 0),
  pageSegs: GATE.pageSegs,
  selfCheck: GATE.selfCheck,
  knownWraps: GATE.knownWraps,
  next: nextStep(wanted),
  exportCommands,
  warnings,
};
