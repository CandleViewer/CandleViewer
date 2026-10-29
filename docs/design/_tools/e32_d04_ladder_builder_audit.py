#!/usr/bin/env python3
"""E32-D04 SCR-065 scaled / DCA ladder builder audit (stdlib, offline; no network, no HTTP).

Reads the token JSON, `pairs.mjs`, the plan texts, the merged E32-D02 and the spec AS TEXT, and
imports the merged `e32_d01_ladder_math.py` as a sibling so every ladder figure here is E32-D02's
by construction (BQ-14). It prints: (1) the WCAG 2.x ratio of every fg / bg pair SCR-065 renders
in dark / light / high-contrast (`themes.json` layering) and the validity composite; (2) every
token the spec binds, resolved or MISSING; (3) the `pairs.mjs` status of each pair; (4) the ladder
arithmetic — `24` §10.6's rule as the merged tool applies it (conservative buy-down price rounding,
floored quantities, the remainder on the level nearest `price_start`, duplicate prices merged,
sub-minimum levels dropped and redistributed; the linear-skew formula is the merged tool's and
stays PROPOSED, E32-D02 G-11), the cumulative columns, the resulting average Σ price·qty / Σ qty,
the worst case Σ (price - stop)·qty, the custody split and the request count
(`queued_split()`: batches of 10 now, singles later), the DCA ladder, the table's column widths
and the dialog width they imply; E32-D02 §5.1 / §5.2's four tables must re-derive byte-equal
(any difference is a C-row against E32-D02, never a silent change); (5) the copy gates (every
E32-D02 §3.8 key the spec lists byte-equal, `14`'s strings verbatim, retired words absent, T2
reasons within 60 characters with no digit, no private path or host, every cited `file:line`
still valid — drift is a WARN naming the current line, a missing or ambiguous needle is a FAIL —
the per-frame C-2.6 gate: every position-opening `SCR-065 /` row of the state table carries its
stop marker, pre-send rows in the state-true tense "held by Bybit once placed", post-confirm rows
"held by Bybit (exchange)", an empty-stop row no stop value; a present-tense marker beside an
entry on a pre-send row is a FAIL; on a mixed post-confirm row every per-level clause (`rows a-b
"<where>" … "stop …"`, the range with the spec's en dash) is gated by its where word — resting /
filled → the custodian string, placing… / queued → "once placed" and never the present tense,
failed → "not sent"; every request
or cap figure carries `(provisional)` while G-9 / G-10 / G-14 are open; every row drawn on the DCA
fixture carries the G-21 marker; the read-only row says "no CMP-158"); (6) the counts the boards
quote. `--json` feeds the check-nums script; `--check` re-derives the spec's `audit:` markers;
`--self-test` mutates copies in memory (a moved, a deleted and a duplicated cite → WARN / FAIL /
FAIL; a removed stop marker → FAIL; a present-tense marker on a pre-send row → FAIL; on the
`placing` row a present-tense marker on the placing… clause → FAIL and that clause's marker
removed → FAIL; one changed derived cell in a scaled row, in the DCA table and in a spec table →
FAIL; the placing… clause deleted (rows 1…N no longer covered once) → FAIL; `ladder.placing`'s k
off by one → FAIL; on a pre-send row a custodian string not followed by " once placed" — the
"(exchange) once placed" variant and "held at Bybit now" — → FAIL) and prints `self-test: clean`
only if every mutation is caught. Exit 1 on a gated FAIL or a failed gate.

The tool's own arithmetic (D04-C4; BQ-14): the duplicate-price merge re-sums the merged tool's
rows, the DCA table's per-row columns are summed over `dca_ladder()`'s levels, and the
drop-and-redistribute floors are re-derived for the remainder note. Each uses the merged tool's
convention — notional and cumulative notional through `:,.2f` in the default Decimal context
(half-even), risk through the merged tool's own `money()` — and `derived_gate()` asserts the
recomputed rows equal the merged tool's rows on every unmerged fixture and its totals on every
fixture. The spec's own tables (sections 2, 4.2, 4.3, 5.2, 5.5) re-derive cell by cell. The C-2.6
gate also requires, on every post-confirm row, per-child clause ranges that cover rows 1…N exactly
once and a resting count equal to the row's count sentence (`ladder.placing`'s k); on every
pre-send row any "held by Bybit" / "held at Bybit" not immediately followed by " once placed" is a
FAIL — the registered `sl.holder` string is never modified (orchestrator, text round 1 M-2).

The text approval's carries (orchestrator, 2026-10-24): `ladder.stop.line.mixed`'s two counts equal
the per-child clauses' resting and placing… / queued rows; the custodian scan is case-insensitive
and also runs on every not-yet-confirmed clause of a mixed row; every Σ line (sections 2, 4.2,
4.3, 5.2) and every figure a section 3 row restates equal the tool's. Each has one self-test
mutation, caught exactly once. E32-D03 and E32-D05 are read for the class word's glyph only, at
their merge commits (`git show <sha>:path`, local and offline).

Usage: python3 -I docs/design/_tools/e32_d04_ladder_builder_audit.py [--json] [--check]
       [--self-test] [--extra F ...]
"""

from __future__ import annotations

import copy
import importlib
import json
import re
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import ModuleType
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E32" / "E32-D04.md"
UPSTREAM = DESIGN / "E32" / "E32-D02.md"
# E32-D03 / E32-D05 are read at their merge commits (#4421, #4417), not at `main`: their boards
# PRs (#4453, #4440) moved the cited lines, and the spec cites the text "at those merge commits".
SIBLING_PINS = {
    "E32-D02": "27bd8e885cf07d9ed47fdbf23880c65fdf60d5a8",  # its merge commit; G-rows cited by line
    "E32-D03": "edca4c31ade27fcf2ed22f1f7ab2164cb4b28829",
    "E32-D05": "e8f8558aaf9f931d960bfc987c6d92306ee29045",
}
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES = {"dark": (PRIM, DARK), "light": (PRIM, DARK, LIGHT), "high-contrast": (PRIM, DARK, HC)}
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0}
MULTI = re.MULTILINE
# Generic patterns only: no personal word, no hostname whole or split; the path literal is split.
FORBIDDEN = (
    r"/(?:ho[m]e|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
    r"(?<![A-Za-z0-9])wt-[a-z]+/",
)
# Words retired from user-facing copy (E33-D01 SC-6; E32-D02 D10's word is replaced by E33-D03's
# registered `tag.emulated` name, BQ-17, A-row D04-A7); checked on the copy deck only.
BANNED_COPY = (
    r"app-managed",
    r"client-side",
    r"client-of-exchange-side",
    r"\(estimated\) tag",
    r"\bfallback\b",
)
CLASS_WORD = "Emulated — run by CandleViewer, not Bybit"  # E33-D03 `tag.emulated` (BQ-17)
NOTE_DRAFT = (
    "Every position keeps a native stop — you can move it, not delete it.",
    "It is placed with the order, not after it.",
)
CHILD_MIN_14 = "Child 5 is below the minimum — reduce the order count"
PRE_SEND = "held by Bybit once placed"
CUSTODIAN = "held by Bybit (exchange)"
# A present-tense custodian directly beside a price on a pre-send row is the tense FAIL (BQ-16).
PRESENT_MARKER = r"stop [\d,]+\.\d(?: ·)? held by Bybit \(exchange\)"
# On a pre-send row every custodian mention is the state-true marker: "held by|at Bybit" not
# immediately followed by " once placed" FAILs, the "(exchange) once placed" variant included
# (the registered `sl.holder` string is never modified; orchestrator, text round 1 M-2).
PRE_SEND_HELD = r"held (?:by|at) Bybit(?! once placed)"  # matched case-insensitively
# The pinned stop line on a mixed row (`ladder.stop.line.mixed`): its two counts are the per-child
# clauses' resting and not-yet-confirmed (placing… / queued) rows (orchestrator, text approval).
MIXED_LINE = r"held by Bybit \(exchange\) on (\d+) resting · once placed on (\d+)"
# The state-table rows that open no position (no stop marker required): the empty modal, the
# refused generator, the read-only panel and the reduce-only scale-out (`sl.reduce_only`).
NON_OPENING = ("empty", "no viable ladder", "viewer-read-only", "preview · reduce-only")
# Rows whose depicted children are already at Bybit (`native_sl_confirmed` per child): the
# custodian string is right there; every other opening row is pre-send. Each names the fixture it
# draws, whose level count N the per-child clauses must cover exactly once.
POST_CONFIRM = {
    "placing": "anatomy",
    "placing · queued levels": "rows_50",
    "partial placement failure with retry": "anatomy",
    "cancelled": "anatomy",
}
# The count sentences a post-confirm row may carry; the per-child clauses must agree with them.
PLACING_K = r"Placing (\d+) orders — (\d+) of (\d+) resting"  # `ladder.placing`
CUSTODY_K = r"(\d+) resting · (\d+) queued"  # `ladder.custody.result`
PARTIAL_K = r"(\d+) of (\d+) placed — (\d+) failed"  # `ladder.partial`
STOP_EMPTY = "preview · stop empty"
# Rows drawn on the DCA fixture: the server cannot preview a DCA ladder (E32-D02 G-21 lists SCR-065
# rows 7 and 14), so each carries the G-21 marker.
DCA_ROWS = ("preview · DCA", "risk-cap refusal")
# One per-level clause of a mixed row: `rows a-b "<where>" … ` (the spec writes the range with an
# en dash) up to the next clause or `;`.
EN_DASH = "\u2013"
CHILD_CLAUSE = rf'rows (\d+){EN_DASH}(\d+) "([^"]+)"((?:(?!rows \d+{EN_DASH}|; ).)*)'
PROVISIONAL = "(provisional)"
# element | fg | bg | role — every pair SCR-065 draws (spec section 13, rows in order).
PAIRS_TABLE = """
dialog body, cell words on the dialog | color.text.primary | color.surface.overlay | text
labels, reasons, tile captions on the dialog | color.text.secondary | color.surface.overlay | text
T2 label and lock glyph on the dialog | color.text.tertiary | color.surface.overlay | text
cell words on the odd row | color.text.primary | color.surface.canvas | text
secondary cells, the where column, notes | color.text.secondary | color.surface.canvas | text
tertiary captions on canvas | color.text.tertiary | color.surface.canvas | text
cell words on the even row, panel text | color.text.primary | color.surface.raised | text
labels, read-outs, T2 reasons on raised | color.text.secondary | color.surface.raised | text
T2 label and lock glyph on raised | color.text.tertiary | color.surface.raised | text
sticky header words | color.text.primary | color.surface.hover | text
pinned totals, stop and risk lines | color.text.primary | color.surface.sunken | text
pinned-line captions | color.text.secondary | color.surface.sunken | text
tile value (CMP-228 on sunken) | color.text.primary | color.surface.sunken | text
DEMO badge word (AA bar) | color.text.primary | color.surface.raised | text
DEMO badge word (the 7:1 target) | color.text.primary | color.surface.raised | aaa-target
DEMO dot and border | color.env.demo | color.surface.raised | non-text
LIVE dot and border (row 12 only) | color.env.live | color.surface.raised | non-text
DEMO band rule | color.env.demo | color.surface.app | non-text
CMP-158 sentence, info banner word | color.text.primary | color.status.info.subtle | text
CMP-158 glyph | color.status.info.strong | color.status.info.subtle | non-text
warning words (crosses, dropped, cap line) | color.text.primary | color.status.warning.subtle | text
warning second line | color.text.secondary | color.status.warning.subtle | text
warning glyph | color.status.warning.strong | color.status.warning.subtle | non-text
refusal words (no viable, budget, partial) | color.text.primary | color.status.danger.subtle | text
danger second line | color.text.secondary | color.status.danger.subtle | text
danger glyph | color.status.danger.strong | color.status.danger.subtle | non-text
validation boundary on the dialog | color.status.danger.default | color.surface.overlay | non-text
cancelled result word | color.text.primary | color.status.success.subtle | text
success glyph | color.status.success.strong | color.status.success.subtle | non-text
progress bar fill on its track | color.action.primary.default | color.surface.sunken | non-text
slider filled track and thumb | color.action.primary.default | color.surface.overlay | non-text
slider unfilled track | color.text.tertiary | color.surface.overlay | non-text
Place label | color.text.on-action | color.action.primary.default | text
Cancel k levels label | color.text.on-action | color.status.danger.default | text
focus ring on the dialog | color.focus.ring | color.surface.overlay | non-text
focus ring on raised | color.focus.ring | color.surface.raised | non-text
field well boundary | color.text.tertiary | color.surface.app | non-text
buy word glyph on the dialog | color.buy.default | color.surface.overlay | non-text
sell word glyph on the dialog | color.sell.default | color.surface.overlay | non-text
stale value | color.data-confidence.stale.text | color.data-confidence.stale.surface | text
the card hairline | color.border.default | color.surface.raised | decorative
"""
BINDINGS = (
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
    "color.surface.sunken",
    "color.surface.hover",
    "color.surface.selected",
    "color.border.default",
    "color.border.subtle",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.on-action",
    "color.status.info.subtle",
    "color.status.info.strong",
    "color.status.warning.subtle",
    "color.status.warning.strong",
    "color.status.danger.subtle",
    "color.status.danger.default",
    "color.status.danger.strong",
    "color.status.success.subtle",
    "color.status.success.strong",
    "color.action.primary.default",
    "color.focus.ring",
    "color.env.demo",
    "color.env.live",
    "color.buy.default",
    "color.sell.default",
    "color.data-confidence.stale.text",
    "color.data-confidence.stale.surface",
    "opacity.disabled",
    "radius.control",
    "radius.card",
    "radius.badge",
    "radius.md",
    "type.ui.caption",
    "type.ui.body",
    "type.ui.label",
    "type.num.base",
    "size.row.height",
    "size.row.compact",
    "size.row.comfortable",
    "size.control.height",
    "size.target.min",
    "space.1",
    "space.2",
    "space.3",
    "space.4",
    "space.inset.sm",
)
# doc | line at the base | text the line must hold, unique in the file; a `14` / `15` line below
# the pointer line may sit one lower (the shift is counted, never assumed).
CITED_TABLE = """
14 | 1525 | **Type:** Modal. Split size across N orders
14 | 1541 | `POST /api/v1/orders` (backend places N children and tracks them as one algo)
14 | 1542 | ("Child 5 is below the minimum — reduce the order count")
14 | 1543 | placing (per-child progress) · partial placement failure with retry.
14 | 1544 | CMP-130 SlippageEstimateChip, CMP-228 PreviewTile.
14 | 1547 | Preview recomputes locally within one frame
14 | 1548 | `algo.scaled_created` with `{symbol, side, levels, totalQty
14 | 1549 | (flat / linear / exponential / custom) drawn
14 | 1550 | recommendations PROPOSED pending the owner's sessions: the preview as a real table
15 | 139 | ### CMP-010 Slider
15 | 144 | `role="slider"`, `aria-valuenow/min/max/text`
15 | 232 | ### CMP-019 Icon
15 | 272 | ### CMP-023 Progress Bar
15 | 554 | ### CMP-049 Table (base data table)
15 | 557 | `virtualized?: boolean` (default true above 50 rows)
15 | 849 | ### CMP-079 RbacGate (disabled-with-reason wrapper)
15 | 1362 | ### CMP-118 AlgoProgressCard (emulated TWAP/Iceberg/Chase/Scaled)
15 | 1387 | ### CMP-119 BracketEditor (SL/TP attach widget)
15 | 1522 | ### CMP-130 SlippageEstimateChip
15 | 1846 | ### CMP-158 SafetyInvariantNotice
15 | 2717 | ### CMP-228 PreviewTile
15 | 2719 | the live miniature preview inside settings dialogs
22 | 6802 | /trade-groups:
22 | 6843 | summary: Place one ticket across N accounts (fan-out) with per-leg overrides
22 | 6859 | `403 risk_limit_breached` with one `errors[]` entry per offending leg: its `field`
22 | 6893 | Fan-out is scheduled against a **per-UID** rate budget
22 | 7117 | /trade-groups/{tradeGroupId}/amend:
22 | 7182 | operationId: cancelTradeGroup
22 | 13653 | /trade-groups/preview:
22 | 13667 | who cannot submit, a Viewer included, gets `403 forbidden`. It needs no arm token.
22 | 15420 | name: X-Arm-Token
22 | 18389 | max_orders_per_minute: { type: integer, minimum: 1, maximum: 600 }
22 | 18530 | max_concurrent_orders: { type: ["integer", "null"], minimum: 1, maximum: 500 }
22 | 18534 | max_orders_per_minute: { type: integer, minimum: 1, maximum: 600, default: 30 }
22 | 19440 | levels: { type: integer, minimum: 2, maximum: 50 }
22 | 19443 | distribution: { type: string, enum: [equal, linear, geometric] }
22 | 19447 | description: ">1 weights size toward `to_price`.",
22 | 19765 | CreateTradeGroupRequest:
22 | 19809 | ResolvedLegParams:
22 | 19843 | TradeGroupLeg:
22 | 19894 | LegError:
22 | 19911 | retryable: { type: boolean }
22 | 22956 | TradeGroupPreview:
22 | 23013 | rate_budget_exhausted,
23 | 3189 | ### 14.8 `TickerUpdate`
23 | 3367 | ### 15.1 `OrderUpdate`
23 | 3777 | ### 15.5 `TradeGroupUpdate`
24 | 135 | `mode="conservative"` rounds a buy limit _down_ and a sell limit _up_
24 | 2086 | ### 8.7 Rate budgeting
24 | 2117 | submission fails fast with `RATE_BUDGET_EXCEEDED`
24 | 2124 | ### 8.8 Safety invariant — native stop-loss
24 | 2511 | | `risk_caps.max_orders_per_minute`
24 | 2615 | **9.3.1 Stop resolution.**
24 | 2661 | ### 9.4 Fan-out algorithm
24 | 2701 | 4. **Rate budget is checked across all UIDs before the first send.**
24 | 2984 | ### 10.6 Scaled (laddered) orders
24 | 2991 | distribution: Literal["equal","linear","geometric","custom"] = "equal"
24 | 2997 | batch_size: int = 10
24 | 3000 | duplicate prices after rounding are **merged**
24 | 3002 | Submission uses Bybit's batch endpoint (1
24 | 5007 | ### 15.5 Audited action vocabulary (closed set)
28 | 2005 | ## B2 — TradeGroup
28 | 2274 | ### B2.2 States
28 | 2289 | ### B2.3 Events and transitions
11 | 3261 | #### US-ALGO-004 — Scaled entry orders · Should
11 | 3271 | and I can retry only the failed leg
11 | 3399 | #### US-ALGO-009 — DCA / scale-in safety ladders · Should
05 | 90 | ### 3.4 Focus management in dense layouts
05 | 131 | 7. **Text resize (WCAG 1.4.4, AA)**
05 | 147 | default 1 update / 2s per field
06 | 21 | ## 2. Core performance budgets (summary table)
16 | 113 | | **Compact** (default for trading surfaces)
16 | 114 | | **Comfortable** (default for admin/onboarding/settings)
16 | 125 | 1. Density changes spacing-token resolution only
23 | 4420 | `oms.account_stale`
E32-D02 | 285 | Account stale (`oms.account_stale`
E32-D02 | 369 | `ladder.cancel.confirm` · `ladder.cancelled`
E32-D02 | 466 | stale refuses order entry, never a tighten
E32-D02 | 810 | | G-20 |
E32-D02 | 811 | so the server cannot preview a DCA ladder
E32-D02 | 835 | SCR-065 7, 14 (DCA, risk cap)
E30-D04 | 219 | `frozen.reason` "Trading frozen by the owner — new orders off." (PROPOSED
E33-D03 | 363 | "Emulated" · name "Emulated — run by CandleViewer, not Bybit"
E32-D03 | 46 | | BQ-14 | the class word
E32-D03 | 413 | `cls.emulated`
E32-D05 | 45 | | BQ-12 | the word for protection layers
E32-D05 | 403 | | `e32.class.emulated`
"""
POINTER = "E32-D04.md](../design/E32/E32-D04.md)"
DOC_NAMES = (
    "05-accessibility-standard.md",
    "06-performance-and-load-standard.md",
    "11-user-stories.md",
    "14-screens-catalogue.md",
    "15-component-catalogue.md",
    "16-design-system-brief.md",
    "22-api-openapi.yaml",
    "23-ws-protocol.md",
    "24-internal-schemas.md",
    "28-statechart-catalogue.md",
)
DOCS = {n[:2]: PLAN / n for n in DOC_NAMES}
D = Decimal
# E32-D02 §5's calls, verbatim: total, price_start, price_end, levels, distribution, skew.
LADDERS: dict[str, tuple[Decimal, Decimal, Decimal, int, str, Decimal]] = {
    "anatomy": (D("1.000"), D("63900"), D("63700"), 5, "linear", D("1.4")),
    "skew_1": (D("1.000"), D("63900"), D("63700"), 5, "linear", D("1.0")),
    "rows_3": (D("1.000"), D("63900"), D("63700"), 3, "linear", D("1.4")),
    "rows_10": (D("1.000"), D("63900"), D("63450"), 10, "linear", D("1.4")),
    "rows_50": (D("1.000"), D("63900"), D("61450"), 50, "linear", D("1.4")),
    "dropped": (D("0.006"), D("63900"), D("63700"), 5, "linear", D("0.6")),
    "merged": (D("1.000"), D("63900"), D("63899.7"), 5, "linear", D("1.4")),
    "crosses": (D("1.000"), D("64100"), D("63900"), 5, "linear", D("1.4")),
    "no_viable": (D("0.004"), D("63900"), D("63700"), 5, "linear", D("1.4")),
}
MARK = D("64012.5")  # E32-D02 row 10's mark (`TickerUpdate.mark_price`)
# The profile placeholders (never account data): `max_concurrent_orders` 20 is `22`'s example,
# `max_orders_per_minute` 30 is `22`'s default (BQ-11), the daily-loss cap and its used part are
# E32-D02 row 14's placeholder; the 50-row frame keeps E32-D02's queue cap of 3.
PROFILE = {"max_concurrent_orders": 20, "max_orders_per_minute": 30, "queue_cap_50": 3}
DAILY = {"cap": D("2500.00"), "used": D("1900.00")}
OVER_BUDGET_LEVELS = 50  # the over-budget fixture: 50 levels resting at once (queue cap 50)
HEADERS = (
    "#",
    "price",
    "qty",
    "notional",
    "cum. qty",
    "cum. notional",
    "avg entry",
    "risk at stop",
    "where",
)
COLLAPSED = ("notional", "cum. notional")  # R2's order: the first two to go at the minimum width
MONO_EM, UI_EM, CELL_PAD, DIALOG_INSET = (
    0.62,
    0.56,
    16,
    16,
)  # px per em at 12 px; `space.2` x 2; `space.4`
NUM_PX = 12  # `type.num.base` at compact density (the board script's JetBrains Mono size)
ROWS = {"compact_px": 24, "comfortable_px": 32, "scroll_rows": 12, "zoom_min_rows": 5}
COUNTS = (
    ("frames", 3, 4, r"^\| \d+ +\| `[^`]+` +\| \d\d +\| (?:full|inset)"),
    ("frames_full", 3, 4, r"^\| \d+ +\| `[^`]+` +\| \d\d +\| full"),
    ("frames_inset", 3, 4, r"^\| \d+ +\| `[^`]+` +\| \d\d +\| inset"),
    ("tiles", 8, 9, r"^\| `tile\."),
    ("boards", 0, 1, r"^\| \d\d +\| `E32-D04 / "),
    ("light_twins", 0, 1, r"^\| \d\d +\| `E32-D04 / [^`]+-light`"),
    (
        "classification_rows",
        1,
        2,
        r"^\| [^|]+\| \*\*(?:T[124]|validity look|status|outcome|absence)",
    ),
)
ROW_IDS = (("d_rows", "D"), ("c_rows", "C"), ("g_rows", "G"), ("a_rows", "A"), ("q_rows", "Q"))
# `lockout` carries its registered reason in the same deck cell as its banner; `frozen` is a banner
# only — Place's reason is `frozen.reason` (E30-D04 §2.5 / G6), which the gate measures.
REGISTERED_REASONS = ("lockout", "arm.locked", "arm.unknown", "submit.not_connected")
CITE_WARN: list[str] = []


def rows(table: str) -> list[list[str]]:
    return [[c.strip() for c in ln.split("|")] for ln in table.strip().splitlines()]


def cites() -> list[tuple[str, str, str]]:
    """doc, line, needle — the needle may itself hold a `|`, so it is the third field whole."""
    out: list[tuple[str, str, str]] = []
    for ln in CITED_TABLE.strip().splitlines():
        doc, line_s, want = ln.split(" | ", 2)
        out.append((doc.strip(), line_s.strip(), want.strip()))
    return out


def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        data = json.loads((TOKENS / f).read_text(encoding="utf-8"))
        merged.update({k: v.get("$value") for k, v in data.items() if isinstance(v, dict)})
    return merged


def resolve(tokens: dict[str, object], name: str) -> str:
    if name not in tokens:
        return "MISSING"
    value, hops = tokens[name], 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1], "MISSING"), hops + 1
    return str(value)


def rgb(hex6: str) -> list[int]:
    return [int(hex6.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]


def luminance(hex6: str) -> float:
    lin = [
        (c / 12.92) if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in (v / 255 for v in rgb(hex6))
    ]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def blend(fg: str, bg: str, alpha: float) -> str:
    mixed = (round(a * alpha + b * (1 - alpha)) for a, b in zip(rgb(fg), rgb(bg), strict=True))
    return "#" + "".join(f"{v:02X}" for v in mixed)


def show(ratio: float) -> str:
    near = any(abs(ratio - bar) < 0.005 for bar in (3.0, 4.5, 7.0))
    return f"{ratio:.4f}" if near else f"{ratio:.2f}"


def section(spec: str, a: int, b: int) -> str:
    start = spec.index(f"\n## {a}.")
    try:
        return spec[start : spec.index(f"\n## {b}.")]
    except ValueError:
        return spec[start:]


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, MULTI))


def money(value: Decimal) -> str:
    return f"{value.quantize(D('0.01'), rounding=ROUND_HALF_UP):,.2f}"


# ---- the arithmetic: the merged tool, imported, never re-implemented (BQ-14) ------------------
def ladder_math() -> ModuleType:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    return importlib.import_module("e32_d01_ladder_math")


def level_rows(raw: Any) -> list[dict[str, str]]:
    return [{str(k): str(v) for k, v in vars(r).items()} for r in list(raw)]


def merge_duplicates(
    lm: ModuleType, rows_in: list[dict[str, str]], stop: Decimal
) -> list[dict[str, str]]:
    """`24` §10.6: duplicate prices after rounding are merged, their quantities summed.

    This tool's own arithmetic (D04-C4): the derived columns are re-summed in the merged tool's
    convention — `:,.2f` in the default (half-even) Decimal context, risk via its `money()`."""
    out: list[dict[str, str]] = []
    for r in rows_in:
        if out and out[-1]["price"] == r["price"]:
            out[-1]["qty"] = f"{D(out[-1]['qty']) + D(r['qty']):.3f}"
            out[-1]["merged_from"] = f"{out[-1].get('merged_from', out[-1]['level'])},{r['level']}"
        else:
            out.append(dict(r))
    cum_q, cum_n, cum_r = D(0), D(0), D(0)
    for r in out:
        p, q = D(r["price"].replace(",", "")), D(r["qty"])
        cum_q, cum_n, cum_r = cum_q + q, cum_n + p * q, cum_r + q * abs(p - stop)
        r["notional"] = f"{p * q:,.2f}"
        r["cum_qty"], r["cum_notional"] = f"{cum_q:.3f}", f"{cum_n:,.2f}"
        r["avg_entry"], r["risk_cum"] = f"{cum_n / cum_q:,.1f}", f"{lm.money(cum_r):,.2f}"
    return out


def ladder(lm: ModuleType, key: str) -> dict[str, object]:
    total, p_start, p_end, n, dist, skew = LADDERS[key]
    stop = D(str(lm.shared_stop(p_end, p_start)))
    weights = [D(str(w)) for w in lm.weights(n, dist, skew)]
    floors = [D(str(lm.floor_qty(total * w))) for w in weights]
    min_qty = D(str(lm.MIN_QTY))
    viable = any(f >= min_qty for f in floors)
    raw_rows, raw_totals = lm.scaled_ladder(total, p_start, p_end, n, dist, skew, stop=stop)
    table = level_rows(raw_rows)
    totals = {str(k): str(v) for k, v in dict(raw_totals).items()}
    kept = [i for i, f in enumerate(floors) if f >= min_qty]
    dropped = [i + 1 for i in range(n) if i not in kept]
    if dropped and viable:
        sub = [D(str(w)) for w in lm.weights(len(kept), dist, skew)]
        floors = [
            D(str(lm.floor_qty(total * sub[kept.index(i)]))) if i in kept else D(0)
            for i in range(n)
        ]
    remainder = total - sum(floors, D(0))
    merged = merge_duplicates(lm, table, stop)
    merged_note = [r["merged_from"] for r in merged if "merged_from" in r]
    above_mark = [r["level"] for r in table if D(r["price"].replace(",", "")) > MARK]
    cap = PROFILE["queue_cap_50"] if n == 50 else PROFILE["max_concurrent_orders"]
    split = {str(k): str(v) for k, v in dict(lm.queued_split(len(merged), cap)).items()}
    return {
        "call": f"scaled_ladder({total}, {p_start:,}, {p_end:,}, {n}, {dist}, {skew})",
        "viable": viable,
        "rows": merged,
        "rows_before_merge": len(table),
        "totals": totals,
        "stop": f"{stop:,.1f}",
        "stop_offset_pct": f"{D(str(lm.STOP_OFFSET_PCT)) * 100:.0f}",
        "remainder": f"{remainder:.3f}",
        "dropped": dropped,
        "merged": merged_note,
        "above_mark": above_mark,
        "min_qty": f"{min_qty}",
        "split": split,
        "requests_line": (
            f"{split['requests_now']} batch request now ({split['resting']} orders)"
            f" + up to {split['queued']} single placements later"
            if int(split["queued"])
            else f"{split['requests_now']} batch request now, {split['requests_later']} later"
        ),
    }


def dca(lm: ModuleType) -> dict[str, object]:
    """The DCA table. Its per-row columns are this tool's own arithmetic (D04-C4) in the merged
    tool's convention; `derived_gate()` holds them to `dca_ladder()`'s totals."""
    raw = dict(lm.dca_ladder())
    levels = [{str(k): str(v) for k, v in dict(x).items()} for x in list(raw["levels"])]
    stop = D(str(raw["shared_stop"]).replace(",", ""))
    cum_q, cum_n, cum_r = D(0), D(0), D(0)
    for lv in levels:
        p, q = D(lv["price"].replace(",", "")), D(lv["qty"])
        cum_q, cum_n, cum_r = cum_q + q, cum_n + p * q, cum_r + q * (p - stop)
        lv.update({"notional": f"{p * q:,.2f}", "cum_qty": f"{cum_q:.3f}"})
        lv.update({"cum_notional": f"{cum_n:,.2f}", "avg_entry": f"{cum_n / cum_q:,.1f}"})
        lv["risk_cum"] = f"{lm.money(cum_r):,.2f}"
    headroom = DAILY["cap"] - DAILY["used"]
    full = D(str(raw["risk_full"]).replace(",", ""))
    return {
        "call": "dca_ladder()",
        "levels": levels,
        "shared_stop": str(raw["shared_stop"]),
        "stop_pct": "2.5",
        "total_qty": str(raw["total_qty"]),
        "total_notional": f"{cum_n:,.2f}",
        "avg_entry": str(raw["avg_entry"]),
        "risk_full": str(raw["risk_full"]),
        "risk_full_pct": str(raw["risk_full_pct"]),
        "risk_first_leg": str(raw["risk_first_leg"]),
        "headroom": money(headroom),
        "cap": money(DAILY["cap"]),
        "used": money(DAILY["used"]),
        "over_by": money(full - headroom),
        "breached": full > headroom,
        "split": {
            str(k): str(v)
            for k, v in dict(lm.queued_split(len(levels), PROFILE["max_concurrent_orders"])).items()
        },
    }


def up8(value: int) -> int:
    return -(-value // 8) * 8


def widths(fixtures: dict[str, dict[str, object]]) -> dict[str, object]:
    """Column fit widths from the longest cell of every fixture: mono digits, Inter for `where`."""
    keys = ("level", "price", "qty", "notional", "cum_qty", "cum_notional", "avg_entry", "risk_cum")
    longest = {h: len(h) for h in HEADERS}
    where_words = ("→ Bybit", "→ queue (CandleViewer)", "fills at once", "dropped")
    for fx in fixtures.values():
        for r in cast(list[dict[str, str]], fx["rows"]):
            for h, k in zip(HEADERS[:-1], keys, strict=True):
                longest[h] = max(longest[h], len(r[k]))
    longest["where"] = max(longest["where"], max(len(w) for w in where_words))
    px = {
        h: int(-(-longest[h] * NUM_PX * (UI_EM if h == "where" else MONO_EM) // 1)) + CELL_PAD
        for h in HEADERS
    }
    fit = sum(px.values())
    minimum = fit - sum(px[h] for h in COLLAPSED)
    return {
        "columns": px,
        "table_fit_px": fit,
        "table_min_px": minimum,
        "dialog_fit_px": up8(fit + 2 * DIALOG_INSET),
        "dialog_min_px": up8(minimum + 2 * DIALOG_INSET),
        "collapsed": list(COLLAPSED),
    }


# ---- E32-D02's tables must re-derive byte-equal (cells compared after a strip; BQ-14) --------
FULL_KEYS = (
    "level",
    "price",
    "qty",
    "notional",
    "cum_qty",
    "cum_notional",
    "avg_entry",
    "risk_cum",
)
SHORT_KEYS = ("level", "price", "qty", "cum_qty", "avg_entry", "risk_cum")


def where_word(level: int, resting: int) -> str:
    return "→ Bybit" if level <= resting else "→ queue (CandleViewer)"


def table_rows(block: str) -> list[list[str]]:
    return [
        [c.strip() for c in ln.strip().strip("|").split("|")]
        for ln in block.splitlines()
        if re.match(r"^\|\s*\d+\s*\|", ln.strip())
    ]


def upstream_tables(upstream: str, fx: dict[str, dict[str, object]]) -> list[str]:
    """E32-D02 §5.1's table and §5.2's three tables against the tool's rows, cell by cell."""
    bad: list[str] = []
    s51 = upstream[upstream.index("### 5.1") : upstream.index("### 5.2")]
    s52 = upstream[upstream.index("### 5.2") : upstream.index("### 5.3")]
    blocks = {
        "anatomy": (s51, FULL_KEYS, 5),
        "rows_3": (s52[s52.index("3 rows —") : s52.index("10 rows —")], FULL_KEYS, 20),
        "rows_10": (s52[s52.index("10 rows —") : s52.index("50 rows,")], FULL_KEYS, 20),
        "rows_50": (s52[s52.index("50 rows,") :], SHORT_KEYS, PROFILE["queue_cap_50"]),
    }
    for key, (block, keys, resting) in blocks.items():
        tool_rows = cast(list[dict[str, str]], fx[key]["rows"])
        by_level = {int(r["level"]): r for r in tool_rows}
        drawn = table_rows(block)
        if not drawn:
            bad.append(f"E32-D02 {key}: no table rows found")
            continue
        for cells in drawn:
            lvl = int(cells[0])
            want = [by_level[lvl][k] for k in keys] + [where_word(lvl, resting)]
            if cells != want:
                bad.append(f"E32-D02 {key} level {lvl}: drawn {cells} vs tool {want}")
        totals = cast(dict[str, str], fx[key]["totals"])
        sigma = next((ln for ln in block.splitlines() if ln.strip().startswith("| Σ")), "")
        for k in ("total_notional", "avg_entry", "worst_case_usdt", "worst_case_pct_equity"):
            if totals[k] not in sigma:
                bad.append(f"E32-D02 {key}: Σ line lacks the tool's {k} {totals[k]}")
        if f"+{fx[key]['remainder']} added to level 1" not in block:
            bad.append(f"E32-D02 {key}: the remainder note is not +{fx[key]['remainder']}")
    return bad


# ---- the tool's own arithmetic against the merged tool (M-1; BQ-14) --------------------------
def derived_gate(
    lm: ModuleType, fx: dict[str, dict[str, object]], dca_fx: dict[str, object]
) -> list[str]:
    """Recomputed rows equal the merged tool's rows (unmerged fixtures) and totals (every one)."""
    bad: list[str] = []
    for key, (total, p_start, p_end, n, dist, skew) in LADDERS.items():
        mine = cast(list[dict[str, str]], fx[key]["rows"])
        if not mine:
            continue
        stop = lm.shared_stop(p_end, p_start)
        raw_rows, raw_totals = lm.scaled_ladder(total, p_start, p_end, n, dist, skew, stop=stop)
        theirs, totals = level_rows(raw_rows), dict(raw_totals)
        if not fx[key]["merged"]:
            for a, b in zip(mine, theirs, strict=True):
                diff = [k for k in FULL_KEYS if a[k] != b[k]]
                if diff:
                    bad.append(
                        f"derived {key} level {b['level']}: {diff} differ from the merged tool"
                    )
        last = mine[-1]
        for k, t in (
            ("cum_qty", "total_qty"),
            ("cum_notional", "total_notional"),
            ("avg_entry", "avg_entry"),
            ("risk_cum", "worst_case_usdt"),
        ):
            if last[k] != totals[t]:
                bad.append(f"derived {key}: last row {k} {last[k]} vs the merged tool's {t}")
    raw = dict(lm.dca_ladder())
    levels = cast(list[dict[str, str]], dca_fx["levels"])
    want = [{str(k): str(v) for k, v in dict(x).items()} for x in list(raw["levels"])]
    for i, (a, b) in enumerate(zip(levels, want, strict=True), start=1):
        if (a["price"], a["qty"]) != (b["price"], b["qty"]):
            bad.append(f"derived dca level {i}: price / qty differ from dca_ladder()")
    for k, have in (
        ("total_qty", levels[-1]["cum_qty"]),
        ("avg_entry", levels[-1]["avg_entry"]),
        ("risk_full", levels[-1]["risk_cum"]),
        ("risk_first_leg", levels[0]["risk_cum"]),
    ):
        if have != str(raw[k]):
            bad.append(f"derived dca: {have} vs dca_ladder()'s {k} {raw[k]}")
    return bad


def has(value: str, text: str) -> bool:
    """`value` in `text` as a whole figure: no digit, comma or point glued to either end."""
    return re.search(rf"(?<![\d.,]){re.escape(value)}(?!\d)", text) is not None


def sigma_line(sec: str, block: str, key: str, f: dict[str, object]) -> list[str]:
    """A spec Σ line against the fixture's totals (and its custody split where it names one)."""
    sigma = next((ln for ln in block.splitlines() if ln.strip().startswith("| Σ")), "")
    if not sigma:
        return [f"spec section {sec} {key}: no Σ line found"]
    totals = cast(dict[str, str], f["totals"])
    split = cast(dict[str, str], f["split"])
    want = [(k, totals[k]) for k in ("total_qty", "total_notional", "avg_entry")]
    want += [("worst_case_usdt", totals["worst_case_usdt"])]
    want += [("worst_case_pct_equity", f"({totals['worst_case_pct_equity']} %")]
    if "first order alone" in sigma:
        want.append(("first_leg_risk_usdt", f"first order alone {totals['first_leg_risk_usdt']}"))
    if "→ Bybit" in sigma:
        want.append(("split", f"{split['resting']} → Bybit · {split['queued']} → queue"))
    return [
        f"spec section {sec} {key}: the Σ line lacks the tool's {k} {v!r}"
        for k, v in want
        if not has(v, sigma)
    ]


def spec_tables(
    spec: str, fx: dict[str, dict[str, object]], dca_fx: dict[str, object]
) -> list[str]:
    """The spec's own tables (sections 2, 4.2, 4.3, 5.2, 5.5) against the tool, cell by cell."""
    bad: list[str] = []

    def sub(a: str, b: str) -> str:
        start = spec.index(a)
        return spec[start : spec.index(b, start)]

    def want(key: str, lvl: int, keys: tuple[str, ...], where: bool = True) -> list[str]:
        r = next(x for x in cast(list[dict[str, str]], fx[key]["rows"]) if x["level"] == str(lvl))
        resting = int(cast(dict[str, str], fx[key]["split"])["resting"])
        return [r[k] for k in keys] + ([where_word(lvl, resting)] if where else [])

    s42 = sub("\n### 4.2", "\n### 4.3")
    blocks = (
        ("2", sub("\n## 2.", "\n## 3."), "anatomy", FULL_KEYS),
        ("4.2", s42[s42.index("3 rows —") : s42.index("10 rows —")], "rows_3", FULL_KEYS),
        ("4.2", s42[s42.index("10 rows —") :], "rows_10", FULL_KEYS),
        ("4.3", sub("\n### 4.3", "\n### 4.4"), "rows_50", SHORT_KEYS),
    )
    for sec, block, key, keys in blocks:
        drawn = table_rows(block)
        if not drawn:
            bad.append(f"spec section {sec} {key}: no table rows found")
        for cells in drawn:
            exp = want(key, int(cells[0]), keys)
            if cells[: len(exp)] != exp:
                bad.append(f"spec section {sec} {key} level {cells[0]}: {cells[: len(exp)]}")
    sigmas = [(sec, block, key) for sec, block, key, _ in blocks]
    s52_block = sub("\n### 5.2", "\n### 5.3")
    s52_sigma = next((ln for ln in s52_block.splitlines() if ln.startswith("| Σ")), "")
    sigmas += [
        ("5.2", f"| Σ{part}", key)
        for part, key in zip(s52_sigma.split("| Σ")[1:], ("skew_1", "anatomy"), strict=False)
    ]
    for sec, block, key in sigmas:
        bad += sigma_line(sec, block, key, fx[key])
    s52 = table_rows(s52_block)
    if not s52:
        bad.append("spec section 5.2: no table rows found")
    for cells in s52:
        for off, key in ((0, "skew_1"), (9, "anatomy")):
            got = cells[off : off + 8]
            if got != want(key, int(got[0]), FULL_KEYS, where=False):
                bad.append(f"spec section 5.2 {key} level {got[0]}: {got}")
    s55 = sub("\n### 5.5", "\n## 6.")
    levels = cast(list[dict[str, str]], dca_fx["levels"])
    resting = int(cast(dict[str, str], dca_fx["split"])["resting"])
    drawn = table_rows(s55)
    if len(drawn) != len(levels):
        bad.append(f"spec section 5.5: {len(drawn)} DCA rows vs the tool's {len(levels)}")
    dca_keys = FULL_KEYS[1:]
    for cells, (i, lv) in zip(drawn, enumerate(levels, start=1), strict=False):
        exp = [str(i)] + [lv[k] for k in dca_keys] + [where_word(i, resting)]
        if cells[: len(exp)] != exp:
            bad.append(f"spec section 5.5 dca level {i}: {cells[: len(exp)]} vs {exp}")
    sigma = next((ln for ln in s55.splitlines() if ln.startswith("| Σ")), "")
    for k in ("total_qty", "total_notional", "avg_entry", "risk_full", "risk_first_leg"):
        if str(dca_fx[k]) not in sigma:
            bad.append(f"spec section 5.5: the Σ line lacks the tool's {k} {dca_fx[k]}")
    return bad


# ---- section 3's restated figures: each named frame quotes its fixture's numbers -------------
def frame_figures(
    fx: dict[str, dict[str, object]], dca_fx: dict[str, object], side: dict[str, dict[str, str]]
) -> dict[str, list[tuple[str, str]]]:
    """The figures each section 3 row restates, from the tool (label, value)."""

    def scaled(key: str, *facets: str) -> list[tuple[str, str]]:
        f = fx[key]
        totals = cast(dict[str, str], f["totals"])
        rws = cast(list[dict[str, str]], f["rows"])
        out: list[tuple[str, str]] = [("stop", f"stop {f['stop']}")]
        if "totals" in facets:
            out += [(k, totals[k]) for k in ("total_notional", "avg_entry", "worst_case_usdt")]
            out.append(("worst_case_pct_equity", f"({totals['worst_case_pct_equity']} %"))
        if "first" in facets:
            out.append(("first_leg_risk_usdt", totals["first_leg_risk_usdt"]))
        if "worst" in facets:
            out.append(("worst_case_usdt", totals["worst_case_usdt"]))
        if "remainder" in facets:
            out.append(("remainder", f"+{f['remainder']}"))
        if "qtys" in facets:
            out.append(("qty column", " / ".join(r["qty"] for r in rws)))
        if "rows" in facets:
            out.append(("price / qty rows", " · ".join(f"{r['price']} / {r['qty']}" for r in rws)))
        if "merged" in facets:
            out += [("merged row", f"{r['price']} / {r['qty']}") for r in rws if "merged_from" in r]
        if "above" in facets:
            above = cast(list[str], f["above_mark"])
            out.append(("above-mark prices", ", ".join(rws[int(a) - 1]["price"] for a in above)))
        if "requests" in facets:
            out.append(("requests line", cast(str, f["requests_line"])))
        if "filled" in facets:
            out.append(("filled cum. qty", f"({rws[1]['cum_qty']} BTC"))
        return out

    lv = cast(list[dict[str, str]], dca_fx["levels"])
    dca_rows: list[tuple[str, str]] = [
        ("stop", f"stop {dca_fx['shared_stop']}"),
        ("dca price / qty", " · ".join(f"{x['price']} / {x['qty']}" for x in lv)),
        ("dca cum. qty", " · ".join(x["cum_qty"] for x in lv)),
        ("dca avg", " · ".join(x["avg_entry"] for x in lv)),
        ("dca risk", " · ".join(x["risk_cum"] for x in lv)),
        ("dca total_notional", cast(str, dca_fx["total_notional"])),
        ("dca risk_full_pct", f"({dca_fx['risk_full_pct']} %"),
    ]
    refusal, budget = side["refusal"], side["budget"]
    cap_rows: list[tuple[str, str]] = [
        ("stop", f"stop {dca_fx['shared_stop']}"),
        ("dca risk_full", cast(str, dca_fx["risk_full"])),
        ("headroom", cast(str, dca_fx["headroom"])),
        ("dca over_by", f"over by {dca_fx['over_by']}"),
        ("scaled worst_case", refusal["worst_case"]),
        ("scaled over_by", f"over by {refusal['over_by']}"),
        ("scaled stop", f"stop {fx['anatomy']['stop']}"),
    ]
    budget_rows: list[tuple[str, str]] = [
        ("stop", f"stop {fx['rows_50']['stop']}"),
        ("requests now", f"{budget['requests_now']} batch requests now"),
        ("per-minute figure", f"{budget['levels']} of {budget['minute_budget']} orders a minute"),
    ]
    return {
        "preview": scaled("anatomy", "requests"),
        "preview · 3 rows": scaled("rows_3", "totals", "remainder", "qtys", "requests"),
        "preview · 10 rows": scaled("rows_10", "totals", "remainder", "requests"),
        "preview · 50 rows": scaled("rows_50", "requests"),
        "preview · DCA": dca_rows,
        "preview · level dropped": scaled("dropped", "totals", "first", "rows", "remainder"),
        "preview · levels merged": scaled("merged", "totals", "first", "merged", "remainder"),
        "preview · crosses the mark": scaled("crosses", "totals", "first", "above"),
        "preview · LIVE arm": scaled("anatomy", "worst"),
        "risk-cap refusal": cap_rows,
        "over-budget refusal": budget_rows,
        "cancelled": scaled("anatomy", "filled"),
    }


def restated_gate(
    spec: str,
    fx: dict[str, dict[str, object]],
    dca_fx: dict[str, object],
    side: dict[str, dict[str, str]],
) -> list[str]:
    """Every figure a section 3 row restates equals the tool's (orchestrator, text approval)."""
    bad: list[str] = []
    found = {m.group(1): m.group(0) for m in re.finditer(FRAME_ROW, section(spec, 3, 4), MULTI)}
    for name, figures in frame_figures(fx, dca_fx, side).items():
        row = found.get(name, "")
        if not row:
            bad.append(f"spec section 3 `{name}`: the row is missing")
            continue
        bad += [
            f"spec section 3 `{name}`: lacks the tool's {label} {value!r}"
            for label, value in figures
            if not has(value, row)
        ]
    return bad


# ---- the copy deck (spec section 12): key | string | where | source ---------------------------
DECK_ROW = r"^\| `([^`]+)`[^|]*\| ([^\n]*?) \| ([^|]*?) \| ([^|]*?) \|$"


def deck_rows(spec: str) -> list[tuple[str, str, str, str]]:
    return [
        (m.group(1), m.group(2), m.group(3).strip(), m.group(4).strip())
        for m in re.finditer(DECK_ROW, section(spec, 12, 13), MULTI)
    ]


def deck_gates(spec: str, texts: dict[str, str]) -> list[str]:
    bad: list[str] = []
    deck = section(spec, 12, 13)
    sources = {
        "E32-D02": texts["E32-D02"],
        "14": texts["14"],
        "E30-D02": texts["E30-D02"],
        "E30-D04": texts["E30-D04"],
        "E09-D09": texts["E09-D09"],
        "E33-D03": texts["E33-D03"],
    }
    for key, cell, where, source in deck_rows(spec):
        bad += [
            f"spec section 12 `{key}`: retired word in UI copy: {m.group(0)!r}"
            for p in BANNED_COPY
            for m in re.finditer(p, cell)
        ]
        strings = [s for s in re.findall(r'"([^"]+)"', cell) if "{" not in s or source != "E32-D02"]
        owner = source.split(" ")[0].strip("`*")
        if owner in sources:
            bad += [
                f"spec section 12 `{key}`: not byte-equal in {owner}: {s[:50]!r}"
                for s in re.findall(r'"([^"]+)"', cell)
                if s not in sources[owner]
            ]
        elif not source.startswith("PROPOSED"):
            bad.append(f"spec section 12 `{key}`: unknown source {source!r}")
        if "T2 reason" in where and key not in REGISTERED_REASONS:
            for s in strings:
                if len(s) > 60 or not s.endswith(".") or re.search(r"\d", s):
                    bad.append(
                        f"T2 reason {key}: {len(s)} chars; stop {s.endswith('.')};"
                        f" digit {bool(re.search(r'[0-9]', s))}"
                    )
    checks = [(CLASS_WORD, "the class word")] + [(s, "e32.sl.note.draft") for s in NOTE_DRAFT]
    for want, name in checks:
        if want not in deck:
            bad.append(f"spec section 12: {name} missing")
    if CHILD_MIN_14 not in deck or CHILD_MIN_14 not in texts["14"]:
        bad.append("spec section 12 / 14: the sub-minimum line is not verbatim")
    return bad


# ---- the per-frame gates on the state table (spec section 3) --------------------------------
FRAME_ROW = r"^\| \d+ +\| `([^`]+)` +\| \d\d +\| (?:full|inset)[^\n]*"
STOP_VALUE = r"stop [\d,]+\.\d"


def clause_counts(row: str, n: int, clauses: list[re.Match[str]]) -> list[str]:
    """Rows 1…N covered once; the resting (queued, failed) counts equal the row's count sentence."""
    bad: list[str] = []
    covered: list[int] = []
    size: dict[str, int] = {"resting": 0, "queued": 0, "failed": 0, "placing": 0}
    for m in clauses:
        a, b = int(m.group(1)), int(m.group(2))
        covered += range(a, b + 1)
        for word in size:
            size[word] += (b - a + 1) if word in m.group(3) else 0
    if sorted(covered) != list(range(1, n + 1)):
        gaps = sorted(set(range(1, n + 1)) - set(covered))
        extra = sorted({c for c in covered if covered.count(c) > 1 or not 1 <= c <= n})
        bad.append(f"the per-child clauses cover rows 1…{n} not exactly once ({gaps=}, {extra=})")
    # (resting k, the level total, the other per-child count it names) per count sentence
    sentences: list[tuple[re.Match[str], int, int, tuple[str, int] | None]] = []
    if (m1 := re.search(PLACING_K, row)) is not None:
        g = [int(x) for x in m1.groups()]
        sentences.append((m1, g[1], g[0] if g[0] == g[2] else -1, None))
    if (m2 := re.search(CUSTODY_K, row)) is not None:
        g = [int(x) for x in m2.groups()]
        sentences.append((m2, g[0], g[0] + g[1], ("queued", g[1])))
    if (m3 := re.search(PARTIAL_K, row)) is not None:
        g = [int(x) for x in m3.groups()]
        sentences.append((m3, g[0], g[1], ("failed", g[2])))
    for found, k, total, other in sentences:
        said = found.group(0)
        if k != size["resting"]:
            bad.append(f"{said!r}: k {k} vs {size['resting']} resting per-child rows")
        if total != n:
            bad.append(f"{said!r}: the count is not the ladder's {n} levels")
        if other and size[other[0]] != other[1]:
            bad.append(f"{said!r}: {other[1]} {other[0]} vs {size[other[0]]} per-child rows")
    pending = size["placing"] + size["queued"]
    for mixed in re.finditer(MIXED_LINE, row):
        held, later = int(mixed.group(1)), int(mixed.group(2))
        if (held, later) != (size["resting"], pending):
            bad.append(
                f"`ladder.stop.line.mixed` {mixed.group(0)!r}: {held} / {later} vs"
                f" {size['resting']} resting / {pending} placing or queued per-child rows"
            )
    return bad


def child_clauses(row: str, n: int) -> list[str]:
    """The per-child tense on a mixed row: each `rows a-b "<where>" …` clause by its where word."""
    bad: list[str] = []
    clauses = list(re.finditer(CHILD_CLAUSE, row))
    if not clauses:
        return ['a post-confirm row without a per-level clause (rows a-b "<where>" …)']
    bad += clause_counts(row, n, clauses)
    for m in clauses:
        where, rest = m.group(3), m.group(4)
        span = f'rows {m.group(1)}{EN_DASH}{m.group(2)} "{where}"'
        if re.search(r"resting|filled", where):
            if CUSTODIAN not in rest:
                bad.append(f"{span}: a resting child without {CUSTODIAN!r}")
        elif re.search(r"placing|queued", where):
            if PRE_SEND not in rest:
                bad.append(f"{span}: a not-yet-confirmed child without {PRE_SEND!r}")
            for h in re.finditer(PRE_SEND_HELD, rest, re.IGNORECASE):
                bad.append(
                    f"{span}: present-tense custodian on a not-yet-confirmed child"
                    f" ({rest[h.start() : h.end() + 14]!r})"
                )
        elif "failed" in where and "not sent" not in where + rest:
            bad.append(f"{span}: a failed child without 'not sent'")
    return bad


def frame_gates(spec: str) -> list[str]:
    """C-2.6 per row, the tense, the empty stop, LIVE, CMP-158, the class, provisional."""
    bad: list[str] = []
    s3 = section(spec, 3, 4)
    for m in re.finditer(FRAME_ROW, s3, MULTI):
        name, row = m.group(1), m.group(0)
        tag = f"spec section 3 `{name}`"
        if not re.search(r"\| \*\*(?:T1|T2|T4|validity look|status|outcome|absence)", row):
            bad.append(f"{tag}: no class named")
        if name == "viewer-read-only":
            if "no CMP-158" not in row:
                bad.append(f"{tag}: the read-only row must say 'no CMP-158' (spec section 2)")
        elif "CMP-158" not in row:
            bad.append(f"{tag}: the CMP-158 line is missing")
        if name == STOP_EMPTY:
            if re.search(STOP_VALUE, row) or CUSTODIAN in row:
                bad.append(f"{tag}: a stop value or custodian on the empty-stop frame")
            if "no stop" not in row.lower():
                bad.append(f"{tag}: the empty-stop marker is missing")
        elif name not in NON_OPENING:
            if not re.search(STOP_VALUE, row):
                bad.append(f"{tag}: no stop marker on a position-opening row (C-2.6)")
            if name in POST_CONFIRM:
                if CUSTODIAN not in row:
                    bad.append(f"{tag}: post-confirm row without {CUSTODIAN!r}")
                if name == "placing" and not re.search(PLACING_K, row):
                    bad.append(f"{tag}: the `ladder.placing` count sentence is missing")
                n = LADDERS[POST_CONFIRM[name]][3]
                bad += [f"{tag}: {b}" for b in child_clauses(row, n)]
            else:
                if PRE_SEND not in row:
                    bad.append(f"{tag}: pre-send row without {PRE_SEND!r} (state-true tense)")
                if re.search(PRESENT_MARKER, row):
                    bad.append(f"{tag}: present-tense stop marker on a pre-send row")
        if name not in POST_CONFIRM:
            for h in re.finditer(PRE_SEND_HELD, row, re.IGNORECASE):
                bad.append(
                    f"{tag}: a custodian string on a pre-send row not followed by ' once placed'"
                    f" ({row[h.start() : h.end() + 14]!r})"
                )
        live = name != "preview · LIVE arm" and re.search(r"\bLIVE\b", row)
        if live and not re.search(r"\b(?:no|never|not|only|absence|absent)\b", row, re.IGNORECASE):
            bad.append(f"{tag}: LIVE without the arm frame or a negation")
        figure = re.search(r"a minute|batch request|loss budget|request[s]? now", row)
        if figure and PROVISIONAL not in row:
            bad.append(f"{tag}: a request or cap figure without (provisional)")
        if name in DCA_ROWS and "G-21" not in row:
            bad.append(f"{tag}: a row on the DCA fixture without the G-21 marker")
    tiles = section(spec, 8, 9)
    for key in ("tile.risk_cap", "tile.requests"):
        row = next((ln for ln in tiles.splitlines() if ln.startswith(f"| `{key}`")), "")
        if not row or PROVISIONAL not in row:
            bad.append(f"spec section 8 `{key}`: missing or without (provisional)")
    return bad


# ---- the cite rule: drift = WARN naming the current line; missing or ambiguous = FAIL --------
def cite_gate(texts: dict[str, str]) -> tuple[list[str], list[str]]:
    bad: list[str] = []
    warn: list[str] = []
    lines = {k: v.split("\n") for k, v in texts.items()}
    for doc, line_s, want in cites():
        line = int(line_s)
        found = [i + 1 for i, ln in enumerate(lines[doc]) if want in ln]
        if len(found) > 1:
            bad.append(
                f"cited text ambiguous: `{doc}` :{line} {want[:40]!r} occurs {len(found)} times"
            )
            continue
        if not found:
            bad.append(f"cited text gone: `{doc}` :{line} {want[:40]!r} is nowhere in the file")
            continue
        shift = sum(POINTER in ln for ln in lines[doc][: line - 1]) if doc in ("14", "15") else 0
        if found[0] not in (line, line + shift):
            warn.append(f"`{doc}` :{line} now at :{found[0]} ({want[:40]!r})")
    return bad, warn


def file_gates(files: list[Path], texts: dict[str, str]) -> list[str]:
    bad: list[str] = []
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    for f in files:
        txt = f.read_text(encoding="utf-8")
        bad += [f"{f.name}: forbidden text {p}" for p in FORBIDDEN if re.search(p, txt)]
        for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", txt))):
            if f"**{r}" not in constitution:
                bad.append(f"{f.name}: dangling rule id {r}")
        for c in sorted(set(re.findall(r"\b(?:CMP|SCR)-\d{3}\b", txt))):
            if f"### {c} " not in texts["15" if c.startswith("CMP") else "14"]:
                bad.append(f"{f.name}: no catalogue heading for {c}")
        if re.search(r"https?://", txt) and f.suffix == ".py":
            bad.append(f"{f.name}: a URL literal in a committed tool")
    return bad


def flatten(d: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(d, list) and d and all(isinstance(x, dict) for x in d):
        for i, x in enumerate(d):
            out.update(flatten(x, f"{prefix}{i + 1}."))
    else:
        out[prefix[:-1]] = d
    return out


def read_texts() -> dict[str, str]:
    t = {k: p.read_text(encoding="utf-8") for k, p in DOCS.items()}
    t["E32-D02"] = UPSTREAM.read_text(encoding="utf-8")
    for sibling, sha in SIBLING_PINS.items():  # the class word's glyph only (D04-A10, D04-A11)
        t[sibling] = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{sha}:docs/design/E32/{sibling}.md"],
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
        ).stdout
    for name in ("E30/E30-D02", "E30/E30-D04", "E09/E09-D09", "E33/E33-D03"):
        t[name.split("/")[1]] = (DESIGN / f"{name}.md").read_text(encoding="utf-8")
    return t


def bump(value: str) -> str:
    """One changed derived cell: the last digit moved by one."""
    return value[:-1] + str((int(value[-1]) + 1) % 10)


def self_test_derived(
    spec: str, lm: ModuleType, fx: dict[str, dict[str, object]], dca_fx: dict[str, object]
) -> list[str]:
    """M-1: one changed derived cell in a scaled row, the DCA table and a spec table → FAIL."""
    failures: list[str] = []
    fx2 = copy.deepcopy(fx)
    row = cast(list[dict[str, str]], fx2["anatomy"]["rows"])[1]
    row["notional"] = bump(row["notional"])
    if not any("derived anatomy level 2" in b for b in derived_gate(lm, fx2, dca_fx)):
        failures.append("a changed derived cell in a scaled row was not a FAIL")
    dca2 = copy.deepcopy(dca_fx)
    last = cast(list[dict[str, str]], dca2["levels"])[-1]
    last["risk_cum"] = bump(last["risk_cum"])
    if not any(b.startswith("derived dca") for b in derived_gate(lm, fx, dca2)):
        failures.append("a changed derived cell in the DCA table was not a FAIL")
    lv = cast(list[dict[str, str]], dca_fx["levels"])[1]
    start = spec.index("\n### 5.5")
    line = next(ln for ln in spec[start:].splitlines() if re.match(r"^\| 2 \|", ln))
    planted = spec.replace(line, line.replace(lv["notional"], bump(lv["notional"])), 1)
    if not any("5.5 dca level 2" in b for b in spec_tables(planted, fx, dca_fx)):
        failures.append("a changed cell in the spec's DCA table was not a FAIL")
    return failures


def caught_once(problems: list[str], needle: str) -> bool:
    return sum(needle in p for p in problems) == 1


def self_test_carries(
    spec: str,
    fx: dict[str, dict[str, object]],
    dca_fx: dict[str, object],
    side: dict[str, dict[str, str]],
) -> list[str]:
    """The text-approval carries: each planted fault is caught exactly once."""
    failures: list[str] = []
    s3 = section(spec, 3, 4)
    frames = {m.group(1): m.group(0) for m in re.finditer(FRAME_ROW, s3, MULTI)}
    placing, preview = frames.get("placing", ""), frames.get("preview", "")
    mixed = re.search(MIXED_LINE, placing)
    clause = next((m for m in re.finditer(CHILD_CLAUSE, placing) if "placing" in m.group(3)), None)
    if mixed is None or clause is None or PRE_SEND not in preview:
        return ["the `placing` / `preview` rows lack the text the carry mutations plant into"]
    total = int(mixed.group(1)) + int(mixed.group(2))
    moved = mixed.group(0).replace(
        f"on {mixed.group(1)} resting · once placed on {mixed.group(2)}",
        f"on {total} resting · once placed on 0",
    )
    if not caught_once(
        frame_gates(spec.replace(placing, placing.replace(mixed.group(0), moved))),
        "`ladder.stop.line.mixed`",
    ):
        failures.append("the mixed stop line's counts moved was not caught exactly once")
    capital = preview.replace(PRE_SEND, f"{PRE_SEND}; Held by Bybit (exchange)", 1)
    if not caught_once(frame_gates(spec.replace(preview, capital)), "'Held by Bybit"):
        failures.append("a capitalised custodian on a pre-send row was not caught exactly once")
    now = clause.group(0).replace(PRE_SEND, f"{PRE_SEND}, held at Bybit now", 1)
    planted = spec.replace(placing, placing.replace(clause.group(0), now))
    if not caught_once(frame_gates(planted), "'held at Bybit"):
        failures.append("held at Bybit now on the placing… clause was not caught exactly once")
    s42 = spec[spec.index("\n### 4.2") : spec.index("\n### 4.3")]
    block = s42[s42.index("3 rows —") : s42.index("10 rows —")]
    sigma = next(ln for ln in block.splitlines() if ln.startswith("| Σ"))
    worst = cast(dict[str, str], fx["rows_3"]["totals"])["worst_case_usdt"]
    bumped = spec.replace(sigma, sigma.replace(worst, bump(worst), 1), 1)
    if not caught_once(spec_tables(bumped, fx, dca_fx), "the Σ line lacks"):
        failures.append("a changed figure on section 4.2's Σ line was not caught exactly once")
    merged = frames.get("preview · levels merged", "")
    worst = cast(dict[str, str], fx["merged"]["totals"])["worst_case_usdt"]
    if worst not in merged:
        return [*failures, "the `preview · levels merged` row lacks its worst case to mutate"]
    restated = spec.replace(merged, merged.replace(worst, bump(worst), 1))
    if not caught_once(restated_gate(restated, fx, dca_fx, side), "lacks the tool's"):
        failures.append("a changed restated figure on section 3 was not caught exactly once")
    return failures


def self_test(
    spec: str,
    texts: dict[str, str],
    lm: ModuleType,
    fx: dict[str, dict[str, object]],
    dca_fx: dict[str, object],
    side: dict[str, dict[str, str]],
) -> list[str]:
    """Plant one fault per gate in a copy and expect it caught; a silent gate is a FAIL here."""
    failures: list[str] = self_test_derived(spec, lm, fx, dca_fx)
    failures += self_test_carries(spec, fx, dca_fx, side)
    doc, line_s, want = cites()[0]
    lines = texts[doc].split("\n")
    idx = int(line_s) - 1
    moved = dict(texts)
    moved[doc] = "\n".join([*lines[:idx], "", *lines[idx:]])
    bad, warn = cite_gate(moved)
    if not any(f"`{doc}` :{line_s}" in w for w in warn) or any(f":{line_s} " in b for b in bad):
        failures.append("moved cite was not a WARN")
    gone = dict(texts)
    gone[doc] = "\n".join([*lines[:idx], lines[idx].replace(want, ""), *lines[idx + 1 :]])
    bad, _ = cite_gate(gone)
    if not any(b.startswith("cited text gone") and f":{line_s} " in b for b in bad):
        failures.append("deleted cite was not a FAIL")
    dup = dict(texts)
    dup[doc] = texts[doc] + "\n" + lines[idx]
    bad, _ = cite_gate(dup)
    if not any(b.startswith("cited text ambiguous") and f":{line_s} " in b for b in bad):
        failures.append("duplicated needle was not a FAIL")
    s3 = section(spec, 3, 4)
    row = next(
        (m.group(0) for m in re.finditer(FRAME_ROW, s3, MULTI) if m.group(1) == "preview"), ""
    )
    if not row or PRE_SEND not in row:
        failures.append("the `preview` row lacks the pre-send marker the self-test mutates")
        return failures
    stripped = spec.replace(row, re.sub(STOP_VALUE, "", row.replace(PRE_SEND, "")))
    if not any("no stop marker" in b for b in frame_gates(stripped)):
        failures.append("a removed stop marker was not a FAIL")
    tense = spec.replace(row, row.replace(f"{PRE_SEND}", CUSTODIAN))
    if not any("present-tense stop marker" in b for b in frame_gates(tense)):
        failures.append("a present-tense marker on a pre-send row was not a FAIL")
    held = "not followed by ' once placed'"
    for planted, what in (
        ("held by Bybit (exchange) once placed", "the (exchange) once placed variant"),
        (f"{PRE_SEND}; the stop is held at Bybit now", "held at Bybit now"),
    ):
        mutated = spec.replace(row, row.replace(PRE_SEND, planted, 1))
        if not any(held in b for b in frame_gates(mutated)):
            failures.append(f"{what} on a pre-send row was not a FAIL")
    placing = next(
        (m.group(0) for m in re.finditer(FRAME_ROW, s3, MULTI) if m.group(1) == "placing"), ""
    )
    clause = next((m for m in re.finditer(CHILD_CLAUSE, placing) if "placing" in m.group(3)), None)
    if clause is None or PRE_SEND not in clause.group(4):
        failures.append("the `placing` row lacks the placing… clause the self-test mutates")
        return failures
    present = placing.replace(clause.group(0), clause.group(0).replace(PRE_SEND, CUSTODIAN))
    if not any("present-tense custodian" in b for b in frame_gates(spec.replace(placing, present))):
        failures.append("a present-tense marker on the placing… clause was not a FAIL")
    bare = clause.group(0)[: clause.group(0).index(" with ")] if " with " in clause.group(0) else ""
    if not bare:
        failures.append("the placing… clause has no ` with ` marker to remove")
        return failures
    gone_marker = spec.replace(placing, placing.replace(clause.group(0), bare))
    if not any("not-yet-confirmed child without" in b for b in frame_gates(gone_marker)):
        failures.append("a removed marker on the placing… clause was not a FAIL")
    deleted = spec.replace(placing, placing.replace(clause.group(0), ""))
    if not any("not exactly once" in b for b in frame_gates(deleted)):
        failures.append("the placing… clause deleted was not a FAIL")
    k = re.search(PLACING_K, placing)
    if k is None:
        failures.append("the `placing` row lacks the `ladder.placing` count the self-test mutates")
        return failures
    off = f"Placing {k.group(1)} orders — {int(k.group(2)) - 1} of {k.group(3)} resting"
    if not any(
        ": k " in b for b in frame_gates(spec.replace(placing, placing.replace(k.group(0), off)))
    ):
        failures.append("`ladder.placing`'s k off by one was not a FAIL")
    return failures


def main(argv: list[str]) -> int:
    extra = [Path(a) for a in argv[argv.index("--extra") + 1 :]] if "--extra" in argv else []
    themes = {k: load_theme(k) for k in THEMES}
    texts = read_texts()
    pairs_text = (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8")
    registered = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_text))
    out = ["## 1. Measured matrix (fg on bg | role | dark / light / hc | verdict | pairs | where)"]
    matrix: list[dict[str, object]] = []
    fails = proposed = gated = 0
    demo_7 = True
    for element, fg, bg, role in rows(PAIRS_TABLE):
        ratios = {th: contrast(resolve(tk, fg), resolve(tk, bg)) for th, tk in themes.items()}
        bar = BAR.get(role)
        if role == "aaa-target":
            demo_7 = all(r >= 7.0 for r in ratios.values())
            verdict = "7:1 met" if demo_7 else "7:1 not met — shortfall stated (spec 13)"
        elif bar is None:
            verdict = "reported, not gated"
        else:
            gated += 1
            verdict = "PASS" if all(r >= bar for r in ratios.values()) else "FAIL"
            fails += verdict == "FAIL"
            proposed += (fg, bg) not in registered
        reg = "registered" if (fg, bg) in registered else "PROPOSED"
        row: dict[str, object] = {"element": element, "fg": fg, "bg": bg, "role": role}
        row.update(
            {"verdict": verdict, "pairs": reg, **{k: round(v, 4) for k, v in ratios.items()}}
        )
        matrix.append(row)
        shown = " / ".join(show(r) for r in ratios.values())
        out.append(f"{fg} on {bg} | {role} | {shown} | {verdict} | {reg} | {element}")
    composite: dict[str, float] = {}
    for th, tk in themes.items():
        over = resolve(tk, "color.surface.overlay")
        label = blend(resolve(tk, "color.text.on-action"), over, 0.45)
        fill = blend(resolve(tk, "color.action.primary.default"), over, 0.45)
        composite[th] = round(contrast(label, fill), 2)
    out.append(
        f"validity composite (Place at opacity.disabled over the dialog; not gated): {composite}"
    )
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    missing = [tok for tok in BINDINGS if resolve(themes["dark"], tok) == "MISSING"]
    out += [
        f"{tok} | {' / '.join(resolve(tk, tok)[:40] for tk in themes.values())}" for tok in BINDINGS
    ]
    out.append(f"MISSING tokens: {missing}")
    lm = ladder_math()
    fixtures = {k: ladder(lm, k) for k in LADDERS}
    dca_fx = dca(lm)
    budget = {
        str(k): str(v)
        for k, v in dict(lm.queued_split(OVER_BUDGET_LEVELS, OVER_BUDGET_LEVELS)).items()
    }
    budget["minute_budget"] = str(PROFILE["max_orders_per_minute"])
    budget["over_by"] = str(OVER_BUDGET_LEVELS - PROFILE["max_orders_per_minute"])
    wide = widths(fixtures)
    # The scaled-ladder refusal inset (spec section 6.1): the anatomy ladder's fully-filled worst
    # case against the same daily-loss headroom — a `cap_breached` answer the server can return
    # today (no G-21 dependency), unlike the DCA frame.
    anatomy_totals = cast(dict[str, str], fixtures["anatomy"]["totals"])
    anatomy_worst = D(anatomy_totals["worst_case_usdt"].replace(",", ""))
    headroom = DAILY["cap"] - DAILY["used"]
    scaled_refusal = {
        "worst_case": money(anatomy_worst),
        "headroom": money(headroom),
        "over_by": money(anatomy_worst - headroom),
        "breached": anatomy_worst > headroom,
    }
    side = {"refusal": {k: str(v) for k, v in scaled_refusal.items()}, "budget": budget}
    out.append(
        "\n## 3-4. pairs.mjs status is per row above; the ladder arithmetic (the merged tool's):"
    )
    for key, fx in fixtures.items():
        out.append(
            f"{key}: {fx['call']} · stop {fx['stop']} · viable {fx['viable']}"
            f" · {len(cast(list[object], fx['rows']))} rows"
        )
        for r in cast(list[dict[str, str]], fx["rows"]):
            out.append("  | " + " | ".join(r[k] for k in FULL_KEYS) + " |")
        out.append(
            f"  totals {fx['totals']} remainder +{fx['remainder']} dropped {fx['dropped']}"
            f" merged {fx['merged']} above mark {fx['above_mark']} split {fx['split']}"
        )
    out.append(f"dca: {json.dumps(dca_fx, ensure_ascii=False)}")
    out.append(f"scaled refusal inset: {scaled_refusal}")
    out.append(f"over-budget: {budget}")
    out.append(f"widths: {wide}")
    spec = SPEC.read_text(encoding="utf-8") if SPEC.exists() else ""
    bad: list[str] = [] if spec else ["spec missing: docs/design/E32/E32-D04.md"]
    bad += upstream_tables(texts["E32-D02"], fixtures)
    bad += derived_gate(lm, fixtures, dca_fx)
    cite_bad, cite_warn = cite_gate(texts)
    bad += cite_bad
    CITE_WARN[:] = cite_warn
    if spec:
        bad += deck_gates(spec, texts)
        bad += frame_gates(spec)
        bad += spec_tables(spec, fixtures, dca_fx)
        bad += restated_gate(spec, fixtures, dca_fx, side)
        bad += file_gates([SPEC, *extra], texts)
    ok = (
        "OK — E32-D02's four tables re-derive byte-equal; the tool's own derived columns equal the"
        " merged tool's rows and totals; the spec's own tables re-derive cell by cell; every listed"
        " E32-D02 key byte-equal; the"
        " class word, the CMP-158 sentence and 14's sub-minimum line verbatim; no retired word in"
        " UI"
        " copy; every T2 reason within 60 characters, no digit; every position-opening row carries"
        " its stop in the state-true tense, per child on the mixed rows (C-2.6); every Σ line and"
        " every section 3 restated figure equal to the tool's; every request and"
        " cap figure (provisional); every DCA-fixture row stamped G-21; no private text; every C /"
        " CMP / SCR id exists; every cited text found once"
    )
    out.append("\n## 5. String gates: " + (ok if not bad else "\n".join("FAIL " + b for b in bad)))
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    deck = deck_rows(spec) if spec else []
    by_source: dict[str, int] = {}
    for _, _, _, src in deck:
        key = src.split(" ")[0].strip("`*")
        by_source[key] = by_source.get(key, 0) + 1
    reasons = [k for k, _, where, _ in deck if "T2 reason" in where]
    numbers: dict[str, object] = {
        k: count(p, section(spec, a, b)) if spec else 0 for k, a, b, p in COUNTS
    }
    numbers.update({k: count(rf"^\| D04-{p}\d+ ", spec) for k, p in ROW_IDS})
    numbers["bq_rows"] = count(r"^\| BQ-\d+ ", spec)
    numbers.update({"pairs_rows": gated, "pairs_registered": gated - proposed})
    numbers.update({"pairs_proposed": proposed, "pairs_fail": fails, "demo_badge_7_1": demo_7})
    numbers.update({"composite": composite, "deck_rows": len(deck), "deck_by_source": by_source})
    numbers["opacity_disabled"] = float(resolve(themes["dark"], "opacity.disabled"))
    numbers.update({"deck_new": by_source.get("PROPOSED", 0), "reason_keys": len(reasons)})
    numbers["reason_keys_proposed"] = sum(
        not r.startswith("rbac.") and r not in REGISTERED_REASONS for r in reasons
    )
    numbers["checklist_items"] = count(r"^\| 14:1537 ", spec)
    numbers["missing_tokens"] = len(missing)
    numbers["banned_copy_words"] = len(BANNED_COPY)
    numbers["rows"] = ROWS
    numbers["widths"] = wide
    numbers["profile"] = PROFILE
    numbers["daily"] = {k: money(v) for k, v in DAILY.items()}
    numbers["over_budget"] = budget
    numbers["ladder"] = {
        k: {
            "stop": fx["stop"],
            "rows": len(cast(list[object], fx["rows"])),
            "remainder": fx["remainder"],
            "totals": fx["totals"],
            "split": fx["split"],
            "above_mark": len(cast(list[object], fx["above_mark"])),
            "dropped": len(cast(list[object], fx["dropped"])),
            "viable": fx["viable"],
        }
        for k, fx in fixtures.items()
    }
    numbers["dca"] = {k: v for k, v in dca_fx.items() if k not in ("levels", "call")}
    numbers["scaled_refusal"] = scaled_refusal
    numbers["levels"] = {"min": 2, "max": 50, "batch_cap": str(lm.BATCH_CAP)}
    numbers["skew"] = {"min": "0.5", "max": "3.0", "step": "0.1"}  # PROPOSED bounds (D04-G2)
    flat = flatten(numbers)
    if "--check" in argv and spec:
        for key, val in re.findall(r"<!-- audit:([a-z0-9_.-]+)=([^ ]+) -->", spec):
            have = flat.get(key)
            same = str(have).lower() == val.lower()
            try:
                same = same or float(str(have).replace(",", "")) == float(val.replace(",", ""))
            except ValueError:
                pass
            if have is None or not same:
                bad.append(f"marker audit:{key}={val} vs tool {have}")
        clean = not any(b.startswith("marker") for b in bad)
        out.append("markers: " + ("clean" if clean else "MISMATCH"))
    if "--self-test" in argv and spec:
        failed = self_test(spec, texts, lm, fixtures, dca_fx, side)
        bad += [f"self-test: {f}" for f in failed]
        out.append(
            "self-test: clean (moved → WARN, gone → FAIL, ambiguous → FAIL, stop marker removed →"
            " FAIL, present tense pre-send → FAIL, placing clause present tense → FAIL, placing"
            " clause marker removed → FAIL, derived scaled cell → FAIL, derived DCA cell → FAIL,"
            " spec DCA cell → FAIL, (exchange) once placed pre-send → FAIL, held at Bybit now"
            " pre-send → FAIL, placing clause deleted → FAIL, ladder.placing k off by one → FAIL,"
            " mixed stop line counts → FAIL once, Held by Bybit pre-send → FAIL once, held at"
            " Bybit now on the placing clause → FAIL once, section 4.2 Σ figure → FAIL once,"
            " section 3 restated figure → FAIL once)"
            if not failed
            else "self-test: FAILED " + "; ".join(failed)
        )
    out.append("\n## 6. Counts: " + json.dumps(numbers, ensure_ascii=False))
    if "--json" in argv:
        palette = {th: {n: resolve(tk, n) for n in BINDINGS} for th, tk in themes.items()}
        payload = {"numbers": numbers, "matrix": matrix, "missing": missing, "fixtures": fixtures}
        payload.update(
            {"dca": dca_fx, "problems": bad, "cite_warnings": CITE_WARN, "palette": palette}
        )
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("\n".join(out))
    return 1 if fails or bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
