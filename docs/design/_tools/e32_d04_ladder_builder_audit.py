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
entry on a pre-send row is a FAIL; every request or cap figure carries `(provisional)` while
G-9 / G-10 / G-14 are open; every DCA figure carries the G-21 marker); (6) the counts the boards
quote. `--json` feeds the check-nums script; `--check` re-derives the spec's `audit:` markers;
`--self-test` mutates copies in memory (a moved, a deleted and a duplicated cite → WARN / FAIL /
FAIL; a removed stop marker → FAIL; a present-tense marker on a pre-send row → FAIL) and prints
`self-test: clean` only if every mutation is caught. Exit 1 on a gated FAIL or a failed gate.

Usage: python3 -I docs/design/_tools/e32_d04_ladder_builder_audit.py [--json] [--check]
       [--self-test] [--extra F ...]
"""

from __future__ import annotations

import importlib
import json
import re
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
# Words retired from user-facing copy (E33-D01 SC-6; E32-D02 D10's word is replaced by the lane's
# class word, A-row); checked on the copy deck only.
BANNED_COPY = (
    r"app-managed",
    r"client-side",
    r"client-of-exchange-side",
    r"\(estimated\) tag",
    r"\bfallback\b",
)
CLASS_WORD = "Emulated · run by CandleViewer, not Bybit"
NOTE_DRAFT = (
    "Every position keeps a native stop — you can move it, not delete it.",
    "It is placed with the order, not after it.",
)
CHILD_MIN_14 = "Child 5 is below the minimum — reduce the order count"
PRE_SEND = "held by Bybit once placed"
CUSTODIAN = "held by Bybit (exchange)"
# A present-tense custodian directly beside a price on a pre-send row is the tense FAIL (BQ-16).
PRESENT_MARKER = r"stop [\d,]+\.\d(?: ·)? held by Bybit \(exchange\)"
# The state-table rows that open no position (no stop marker required): the empty modal, the
# refused generator, the read-only panel and the reduce-only scale-out (`sl.reduce_only`).
NON_OPENING = ("empty", "no viable ladder", "viewer-read-only", "preview · reduce-only")
# Rows whose depicted children are already at Bybit (`native_sl_confirmed` per child): the
# custodian string is right there; every other opening row is pre-send.
POST_CONFIRM = (
    "placing",
    "placing · queued levels",
    "partial placement failure with retry",
    "cancelled",
)
STOP_EMPTY = "preview · stop empty"
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
14 | 1509 | **Type:** Modal. Split size across N orders
14 | 1525 | `POST /api/v1/orders` (backend places N children and tracks them as one algo)
14 | 1526 | ("Child 5 is below the minimum — reduce the order count")
14 | 1527 | placing (per-child progress) · partial placement failure with retry.
14 | 1528 | CMP-130 SlippageEstimateChip, CMP-228 PreviewTile.
14 | 1531 | Preview recomputes locally within one frame
14 | 1532 | `algo.scaled_created` with `{symbol, side, levels, totalQty
14 | 1533 | (flat / linear / exponential / custom) drawn
14 | 1534 | recommendations PROPOSED pending the owner's sessions: the preview as a real table
15 | 139 | ### CMP-010 Slider
15 | 144 | `role="slider"`, `aria-valuenow/min/max/text`
15 | 224 | ### CMP-019 Icon
15 | 261 | ### CMP-023 Progress Bar
15 | 512 | ### CMP-049 Table (base data table)
15 | 515 | `virtualized?: boolean` (default true above 50 rows)
15 | 799 | ### CMP-079 RbacGate (disabled-with-reason wrapper)
15 | 1310 | ### CMP-118 AlgoProgressCard (emulated TWAP/Iceberg/Chase/Scaled)
15 | 1335 | ### CMP-119 BracketEditor (SL/TP attach widget)
15 | 1468 | ### CMP-130 SlippageEstimateChip
15 | 1788 | ### CMP-158 SafetyInvariantNotice
15 | 2652 | ### CMP-228 PreviewTile
15 | 2654 | the live miniature preview inside settings dialogs
22 | 6091 | /trade-groups:
22 | 6125 | summary: Place one ticket across N accounts (fan-out) with per-leg overrides
22 | 6139 | `403 risk_limit_breached` with one `errors[]` entry per offending leg, audited, before
22 | 6170 | Fan-out is scheduled against a **per-UID** rate budget
22 | 6376 | /trade-groups/{tradeGroupId}/amend:
22 | 6441 | operationId: cancelTradeGroup
22 | 12542 | /trade-groups/preview:
22 | 12556 | who cannot submit, a Viewer included, gets `403 forbidden`. It needs no arm token.
22 | 14232 | name: X-Arm-Token
22 | 16997 | max_orders_per_minute: { type: integer, minimum: 1, maximum: 600 }
22 | 17138 | max_concurrent_orders: { type: ["integer", "null"], minimum: 1, maximum: 500 }
22 | 17142 | max_orders_per_minute: { type: integer, minimum: 1, maximum: 600, default: 30 }
22 | 17990 | levels: { type: integer, minimum: 2, maximum: 50 }
22 | 17993 | distribution: { type: string, enum: [equal, linear, geometric] }
22 | 17997 | description: ">1 weights size toward `to_price`.",
22 | 18268 | CreateTradeGroupRequest:
22 | 18312 | ResolvedLegParams:
22 | 18346 | TradeGroupLeg:
22 | 18397 | LegError:
22 | 18414 | retryable: { type: boolean }
22 | 21128 | TradeGroupPreview:
22 | 21159 | rate_budget_exhausted,
23 | 3144 | ### 14.8 `TickerUpdate`
23 | 3310 | ### 15.1 `OrderUpdate`
23 | 3720 | ### 15.5 `TradeGroupUpdate`
24 | 135 | `mode="conservative"` rounds a buy limit _down_ and a sell limit _up_
24 | 2057 | ### 8.7 Rate budgeting
24 | 2088 | submission fails fast with `RATE_BUDGET_EXCEEDED`
24 | 2091 | ### 8.8 Safety invariant — native stop-loss
24 | 2458 | | `risk_caps.max_orders_per_minute`
24 | 2532 | **9.3.1 Stop resolution.**
24 | 2538 | ### 9.4 Fan-out algorithm
24 | 2578 | 4. **Rate budget is checked across all UIDs before the first send.**
24 | 2861 | ### 10.6 Scaled (laddered) orders
24 | 2868 | distribution: Literal["equal","linear","geometric","custom"] = "equal"
24 | 2874 | batch_size: int = 10
24 | 2877 | duplicate prices after rounding are **merged**
24 | 2879 | Submission uses Bybit's batch endpoint (1
24 | 4826 | ### 15.5 Audited action vocabulary (closed set)
28 | 1914 | ## B2 — TradeGroup
28 | 2183 | ### B2.2 States
28 | 2198 | ### B2.3 Events and transitions
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
REGISTERED_REASONS = ("lockout", "frozen", "arm.locked", "arm.unknown", "submit.not_connected")
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


def merge_duplicates(rows_in: list[dict[str, str]], stop: Decimal) -> list[dict[str, str]]:
    """`24` §10.6: duplicate prices after rounding are merged, their quantities summed."""
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
        r["avg_entry"], r["risk_cum"] = f"{cum_n / cum_q:,.1f}", money(cum_r)
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
    merged = merge_duplicates(table, stop)
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
    raw = dict(lm.dca_ladder())
    levels = [{str(k): str(v) for k, v in dict(x).items()} for x in list(raw["levels"])]
    stop = D(str(raw["shared_stop"]).replace(",", ""))
    cum_q, cum_n, cum_r = D(0), D(0), D(0)
    for lv in levels:
        p, q = D(lv["price"].replace(",", "")), D(lv["qty"])
        cum_q, cum_n, cum_r = cum_q + q, cum_n + p * q, cum_r + q * (p - stop)
        lv.update({"notional": money(p * q), "cum_qty": f"{cum_q:.3f}"})
        lv.update({"cum_notional": money(cum_n), "avg_entry": f"{cum_n / cum_q:,.1f}"})
        lv["risk_cum"] = money(cum_r)
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


def frame_gates(spec: str) -> list[str]:
    """C-2.6 per row, the tense, the empty stop, LIVE, CMP-158, the class, provisional."""
    bad: list[str] = []
    s3 = section(spec, 3, 4)
    for m in re.finditer(FRAME_ROW, s3, MULTI):
        name, row = m.group(1), m.group(0)
        tag = f"spec section 3 `{name}`"
        if not re.search(r"\| \*\*(?:T1|T2|T4|validity look|status|outcome|absence)", row):
            bad.append(f"{tag}: no class named")
        if name != "viewer-read-only" and "CMP-158" not in row:
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
            else:
                if PRE_SEND not in row:
                    bad.append(f"{tag}: pre-send row without {PRE_SEND!r} (state-true tense)")
                if re.search(PRESENT_MARKER, row):
                    bad.append(f"{tag}: present-tense stop marker on a pre-send row")
        live = name != "preview · LIVE arm" and re.search(r"\bLIVE\b", row)
        if live and not re.search(r"\b(?:no|never|not|only|absence|absent)\b", row, re.IGNORECASE):
            bad.append(f"{tag}: LIVE without the arm frame or a negation")
        figure = re.search(r"a minute|batch request|loss budget|request[s]? now", row)
        if figure and PROVISIONAL not in row:
            bad.append(f"{tag}: a request or cap figure without (provisional)")
        if name == "preview · DCA" and "G-21" not in row:
            bad.append(f"{tag}: a DCA row without the G-21 marker")
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
    lines = {k: v.split("\n") for k, v in texts.items() if k in DOCS}
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
    for name in ("E30/E30-D02", "E30/E30-D04", "E09/E09-D09", "E33/E33-D03"):
        t[name.split("/")[1]] = (DESIGN / f"{name}.md").read_text(encoding="utf-8")
    return t


def self_test(spec: str, texts: dict[str, str]) -> list[str]:
    """Plant one fault per gate in a copy and expect it caught; a silent gate is a FAIL here."""
    failures: list[str] = []
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
    out.append(f"over-budget: {budget}")
    out.append(f"widths: {wide}")
    spec = SPEC.read_text(encoding="utf-8") if SPEC.exists() else ""
    bad: list[str] = [] if spec else ["spec missing: docs/design/E32/E32-D04.md"]
    bad += upstream_tables(texts["E32-D02"], fixtures)
    cite_bad, cite_warn = cite_gate(texts)
    bad += cite_bad
    CITE_WARN[:] = cite_warn
    if spec:
        bad += deck_gates(spec, texts)
        bad += frame_gates(spec)
        bad += file_gates([SPEC, *extra], texts)
    ok = (
        "OK — E32-D02's four tables re-derive byte-equal; every listed E32-D02 key byte-equal; the"
        " class word, the CMP-158 sentence and 14's sub-minimum line verbatim; no retired word in"
        " UI"
        " copy; every T2 reason within 60 characters, no digit; every position-opening row carries"
        " its stop in the state-true tense (C-2.6); every request and cap figure (provisional); no"
        " private text; every C / CMP / SCR id exists; every cited text found once"
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
    numbers["checklist_items"] = count(r"^\| 14:1533 ", spec)
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
        failed = self_test(spec, texts)
        bad += [f"self-test: {f}" for f in failed]
        out.append(
            "self-test: clean (moved → WARN, gone → FAIL, ambiguous → FAIL, stop marker removed →"
            " FAIL, present tense pre-send → FAIL)"
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
