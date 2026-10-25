#!/usr/bin/env python3
"""E32-D03 bracket builder and CMP-119 BracketEditor audit (stdlib, offline; executes no repo code).

Reads the token JSON, `pairs.mjs`, the plan texts, the merged E32-D02 spec and this spec AS TEXT and
prints: (1) the WCAG 2.x ratio of every fg / bg pair SCR-069 and CMP-119 render in dark / light /
high-contrast (`themes.json` layering) and the validity composite; (2) every token the spec binds,
resolved or MISSING; (3-4) the contract facts the spec quotes, parsed from text, beside the spec's
claim; (5) the string gates (every E32-D02 section 3.8 key byte-equal, the CMP-158 sentence, the
RULED class word in sections 2 / 5 / 10, no "app-managed" in UI copy and no middle-dot class word
outside HA-14, T2 reasons within 60 characters, no private text,
every cited id and `file:line` still valid, C-2.6 on every position-opening frame); (6) the counts
and the fixture arithmetic (the E32-D01 ladder tool's formulas re-implemented; nothing typed twice).
`--json` feeds the check-nums script; `--check` re-derives the spec's `audit:` markers;
`--self-test` mutation-tests the cite rule (moved line = WARN; vanished or ambiguous = FAIL) and
the section 3 frame gates on this spec (a present-tense stop marker on one pre-send row = one
FAIL, in three phrasings; a renamed pre-send row = one FAIL; the viewer row without its stop =
one FAIL with its label kept; `submitted` without its flag = no FAIL, without its flag and "held by
the exchange" = one FAIL; a post-confirm control = no FAIL) and the class-word gate (a middle dot in
section 10's `cls.emulated` or in one of section 5's two = one FAIL each; section 10 without the
RULED word = one FAIL).
Exit 1 on a gated FAIL or a failed gate.

Usage: python3 -I docs/design/_tools/e32_d03_bracket_builder_audit.py [--json|--check|--self-test]
"""

from __future__ import annotations

import json
import re
import sys
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E32" / "E32-D03.md"
HANDOFF = DESIGN / "E32" / "E32-D03-handoff.md"
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
)
# Byte-equal to E33-D03 section 13 `tag.emulated`'s accessible name (em dash; HA-14).
RULED_WORD = "Emulated — run by CandleViewer, not Bybit"
# The middle-dot form HA-14 retired; only HA-14's quoted "from" string may still carry it.
RETIRED_WORD = re.escape("Emulated · run by CandleViewer, not Bybit")
HA14_ROW = r"^\| HA-14 \|[^\n]*\n?"
# The class words the orchestrator's rulings retired (RULED 2026-10-24): "app-managed" in the UI
# sections; the middle-dot class word anywhere in the spec outside the HA-14 row.
BANNED_COPY = (r"app-managed", RETIRED_WORD)
NOTE_DRAFT = (
    "Every position keeps a native stop — you can move it, not delete it. "
    "It is placed with the order, not after it."
)
SL_REQUIRED = "This account requires a stop-loss on every order."
STOP_LABEL = "Stop-loss (required)"
HOLDER = "held by Bybit"
# C-2.6: every position-opening frame of section 3 names its stop's holder — the holder line
# "held by Bybit", the registered "held by the exchange" or the wire flag. The label "Stop-loss
# (required)" names the row, not the holder, so it alone never passes (AC Sc. 1, section 12).
EXCHANGE = "held by the exchange"
STOP_MARKERS = (HOLDER, EXCHANGE, "native_sl_confirmed")
NON_OPENING = ("E33 extension point",)
# The twelve pre-send rows of section 3: no exchange stop exists yet. `sl.holder` "held by Bybit
# (exchange)" is the custodian word and stays verbatim; a marker or free sentence is state-true:
# "held by Bybit once placed" (or no stop / wrong side / not sent), never the present tense.
PRE_SEND = (
    "empty",
    "editing",
    "editing · TP ladder",
    "editing · LIVE arm",
    "validating",
    "validating · beyond liquidation",
    "validating · stop empty",
    "validating · ladder not splittable",
    "blocked",
    "error",
    "error · outcome unknown",
    "viewer-read-only",
)
PRESENT_HELD = (
    r"held by Bybit(?! once placed| \(exchange\))",
    r"stop [\d,.]+ held by Bybit(?! once)",
    r"held by the exchange",
    r"\d[\d,.]*(?: ·)? held by Bybit \(exchange\)",
)
CLASS_RE = r"\*\*(?:T2|T4|validity|status|outcome|T1|—)\*\*"
# element | fg | bg | role — every pair the screen draws (spec section 11, rows in order).
PAIRS_TABLE = """
dialog body, field values, the validation line | color.text.primary | color.surface.overlay | text
read-outs, holder line, reasons on the overlay | color.text.secondary | color.surface.overlay | text
the (provisional) grey, captions | color.text.tertiary | color.surface.overlay | text
T2 label and lock glyph (Place, a gated field) | color.text.tertiary | color.surface.raised | text
T2 reason on raised, CMP-119 source line | color.text.secondary | color.surface.raised | text
Place label (enabled) | color.text.on-action | color.action.primary.default | text
Cancel label, the unit segments | color.text.primary | color.surface.raised | text
Mono numbers in the field well | color.text.primary | color.surface.app | text
field well boundary | color.text.tertiary | color.surface.app | non-text
the 2 px danger boundary | color.status.danger.default | color.surface.overlay | non-text
error summary words | color.text.primary | color.status.danger.subtle | text
error summary glyph | color.status.danger.strong | color.status.danger.subtle | non-text
CMP-158 sentence | color.text.primary | color.status.info.subtle | text
CMP-158 glyph | color.status.info.strong | color.status.info.subtle | non-text
beyond-liquidation warning words | color.text.primary | color.status.warning.subtle | text
warning glyph | color.status.warning.strong | color.status.warning.subtle | non-text
accepted toast words | color.text.primary | color.status.success.subtle | text
success glyph | color.status.success.strong | color.status.success.subtle | non-text
DEMO badge word (AA bar) | color.text.primary | color.surface.raised | text
DEMO badge word (the 7:1 target) | color.text.primary | color.surface.raised | aaa-target
DEMO dot and border | color.env.demo | color.surface.raised | non-text
LIVE border on the arm frames | color.env.live | color.surface.raised | non-text
placing card progress bar | color.action.primary.default | color.surface.sunken | non-text
stale shading | color.data-confidence.stale.text | color.data-confidence.stale.surface | text
selected unit segment | color.text.primary | color.surface.selected | text
buy glyph on the overlay | color.buy.default | color.surface.overlay | non-text
sell glyph on the overlay | color.sell.default | color.surface.overlay | non-text
focus ring on the overlay | color.focus.ring | color.surface.overlay | non-text
focus ring on raised | color.focus.ring | color.surface.raised | non-text
REJECTED T2 label in text.disabled | color.text.disabled | color.surface.raised | rejected-text
the card hairline | color.border.default | color.surface.raised | decorative
"""
BINDINGS = (
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
    "color.surface.sunken",
    "color.surface.selected",
    "color.border.default",
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
    "color.action.selected",
    "color.focus.ring",
    "color.env.demo",
    "color.env.live",
    "color.buy.default",
    "color.sell.default",
    "color.data-confidence.stale.text",
    "color.data-confidence.stale.surface",
    "opacity.disabled",
    "border.thick",
    "radius.control",
    "radius.card",
    "radius.badge",
    "type.ui.caption",
    "type.ui.body",
    "type.ui.label",
    "type.num.sm",
    "type.num.base",
    "font.family.mono",
    "size.row.height",
    "size.control.height",
    "space.1",
    "space.2",
    "space.4",
    "space.inset.sm",
    "space.inset.md",
    "space.field.gap",
)
# doc | line at the base | text the line must hold once (the cite rule: moved = WARN, gone or
# ambiguous = FAIL). A `14` / `15` line may sit lower by this spec's own pointer lines.
CITED_TABLE = """
14 | 1575 | ### SCR-069
14 | 1577 | Entry + OCO exit pair, or a standalone OCO
14 | 1579 | CMP-119 BracketEditor, CMP-158 SafetyInvariantNotice, CMP-227 EstimatedBadge.
14 | 1581 | the residual-risk warning is `role="note"`
14 | 1584 | the mandatory native SL floor is shown as always-present
14 | 1391 | SL on the cor
14 | 1498 | Ladder totals 110 % — reduce a step.
14 | 2601 | ### SCR-131
14 | 2317 | CMP-086 SettingsNav / SettingsLayout, CMP-119
14 | 2628 | CMP-087 AdminLayout, CMP-093 AuditActionTrigger, CMP-104 LeverageSlider, CMP-119
15 | 1335 | ### CMP-119
15 | 1337 | There is no stop toggle
15 | 1338 | `partialTpLevels?: {pct,rMultiple}[]`
15 | 1340 | wrong-side or empty stop (a drawn blocked state
15 | 1346 | no render path yields `nativeSlConfirmed` true
15 | 1788 | ### CMP-158
15 | 1794 | `role="note"`, always visible in both CMP-145
15 | 2638 | ### CMP-227
15 | 799 | ### CMP-079
15 | 224 | ### CMP-019
22 | 281 | * **Read-only.** Every other state-changing request
22 | 5421 | operationId: placeOrder
22 | 5449 | either, the request is rejected with
22 | 5463 | lands on a tick rounded toward the entry;
22 | 12545 | operationId: previewTradeGroup
22 | 14232 | name: X-Arm-Token
22 | 15900 | OffsetUnit:
22 | 16947 | Offset:
22 | 18003 | take_profit_levels:
22 | 18013 | PlaceOrderRequest:
22 | 18268 | CreateTradeGroupRequest:
22 | 18312 | ResolvedLegParams:
22 | 18382 | native_sl_confirmed:
22 | 18397 | LegError:
22 | 18455 | OrderAcceptance:
22 | 18647 | SetTpSlRequest:
22 | 21128 | TradeGroupPreview:
23 | 3800 | "native_sl_confirmed": { "type": "boolean" },
24 | 2091 | ### 8.8 Safety invariant
24 | 2097 | 1. Entry orders are submitted **with `stopLoss` attached**
24 | 2532 | **9.3.1 Stop resolution.**
24 | 2536 | **9.3.3 Take-profit resolution.**
24 | 2881 | ### 10.7 Bracket
24 | 2889 | breakeven_offset_ticks: int = 2
24 | 2350 | ### 9.2 Per-account profile
24 | 2379 | require_native_sl: Literal[True] = True
24 | 2381 | sl_offset_unit: Literal["ticks","percent","atr"]
24 | 2441 | | `stop_loss.unit`
28 | 1660 | ### B1.2 States
28 | 2183 | ### B2.2 States
28 | 4458 | ### B8.2 States
05 | 96 | **Focus is never silently stolen**
05 | 97 | **Modal dialogs**
05 | 100 | **Target size**
05 | 131 | **Text resize (WCAG 1.4.4, AA)**
05 | 144 | ### 6.2 Layer 2
16 | 113 | | **Compact** (default for trading surfaces)
16 | 125 | 1. Density changes spacing-token resolution only
16 | 128 | 4. Zoom/text-scale
16 | 483 | ### 11.4 Per-component handoff checklist
13 | 237 | 1-3 TP levels with % split
13 | 242 | trading-stop TP/SL set atomically after entry fill
E33-D03 | 79 | an OCO leg never counts as the position's native stop
E33-D03 | 85 | may add / must not change" list
"""
POINTERS = ("E32-D03.md](../design/E32/E32-D03.md)",)
DOC_NAMES = (
    "05-accessibility-standard.md",
    "11-user-stories.md",
    "13-user-flows.md",
    "14-screens-catalogue.md",
    "15-component-catalogue.md",
    "16-design-system-brief.md",
    "22-api-openapi.yaml",
    "23-ws-protocol.md",
    "24-internal-schemas.md",
    "28-statechart-catalogue.md",
)
DOCS = {n[:2]: PLAN / n for n in DOC_NAMES}
# The merged design spec this spec cites by file:line (E33-D03 at its merge commit; unchanged).
DOCS["E33-D03"] = DESIGN / "E33" / "E33-D03.md"
# The four consumers the ticket names (SCR-131 is the per-account profile editor, `14` :2600).
CONSUMERS = ("SCR-060", "SCR-064", "SCR-069", "SCR-131")
# section | pattern — the counted rows per spec section (start, end, regex).
COUNTS = (
    ("frames_069", 3, 4, r"^\| \d+ +\| `SCR-069 / "),
    ("ladder_rows", 5, 6, r"^\| TP \d +\| "),
    ("consumer_rows", 5, 6, r"^\| `?SCR-\d{3}`? +\| (?:ticket|existing|bracket|profile)"),
    ("mode_rows", 5, 6, r"^\| (?:price|ticks|percent|R) +\| "),
    ("boards", 0, 1, r"^\| \d\d +\| `"),
    ("light_twins", 0, 1, r"^\| \d\d +\| `[^`]+-light`"),
    ("checklist_items", 12, 13, r"^\| 14:1584 "),
    ("walkthrough_items", 13, 14, r"^\d+\. "),
)
ROW_IDS = (("a_rows", "A"), ("c_rows", "C"), ("g_rows", "G"), ("q_rows", "Q"))
REASON_RE = r"^\| `((?:rbac)\.[a-z_.]+)` +\| ([^|]+?) +\|"
# The vocabulary owners whose registered strings this spec may not shorten (reported, not gated).
REGISTERED_STATE = ("frozen", "lockout", "arm.locked", "arm.unknown", "submit.not_connected")

# ------------------------------------------------------------ the fixture arithmetic ----
# E32-D01's ladder tool formulas (`docs/design/_tools/e32_d01_ladder_math.py` :86-127) re-done
# here, so every digit on a board is this tool's: tick 0.10, qty step 0.001, min qty 0.001 (the
# recorded BTCUSDT instrument), equity 12,500 USDT (E32-D02 section 6.1's fixture).
TICK, STEP, MIN_QTY, EQUITY = Decimal("0.1"), Decimal("0.001"), Decimal("0.001"), Decimal(12500)
ENTRY, STOP, TARGET, SIZE = (
    Decimal("64010.0"),
    Decimal("63900.0"),
    Decimal("64230.0"),
    Decimal("0.250"),
)
WEIGHTS = (Decimal("0.25"), Decimal("0.25"), Decimal("0.50"))
R_MULTIPLES = (1, 2, 3)


def snap(value: Decimal, unit: Decimal, rounding: str) -> Decimal:
    return ((value / unit).to_integral_value(rounding=rounding) * unit).quantize(unit)


def away_from_entry(px: Decimal, entry: Decimal) -> Decimal:
    """`24` section 9.3.1: a stop never rounds towards the entry (a long's stop rounds down)."""
    return snap(px, TICK, ROUND_CEILING if px > entry else ROUND_FLOOR)


def toward_entry(px: Decimal, entry: Decimal) -> Decimal:
    """`22` placeOrder: a take-profit lands on a tick rounded toward the entry (a long: down)."""
    return snap(px, TICK, ROUND_FLOOR if px > entry else ROUND_CEILING)


def floor_qty(qty: Decimal) -> Decimal:
    return snap(qty, STEP, ROUND_FLOOR)


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def risk_usdt(qty: Decimal, entry: Decimal, stop: Decimal) -> Decimal:
    return money(qty * abs(entry - stop))


def pct_of_equity(amount: Decimal) -> Decimal:
    return (amount / EQUITY * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def tp_ladder(qty: Decimal, weights: tuple[Decimal, ...]) -> list[Decimal]:
    """`24` section 9.3.3: floor(filled_qty * qty_pct) per rung; the last rung takes the rest."""
    legs = [floor_qty(qty * w) for w in weights[:-1]]
    return [*legs, qty - sum(legs, Decimal(0))]


def merged_ladder(qty: Decimal, weights: tuple[Decimal, ...]) -> tuple[list[Decimal], list[str]]:
    """E32-D02 G-13 (PROPOSED display, not in `24`): a sub-minimum rung merges into the next."""
    ws, labels = list(weights), list(range(1, len(weights) + 1))
    notes: list[str] = []
    while True:
        legs = tp_ladder(qty, tuple(ws))
        low = next((i for i in range(len(legs) - 1) if legs[i] < MIN_QTY), None)
        if low is None:
            return legs, notes
        notes.append(
            f"TP {labels[low]} merged into TP {labels[low + 1]}: below the {MIN_QTY} minimum"
        )
        ws[low + 1] += ws[low]
        del ws[low]
        del labels[low]


def fixture() -> dict[str, object]:
    r_px = ENTRY - STOP
    prices = [toward_entry(ENTRY + r_px * m, ENTRY) for m in R_MULTIPLES]
    qtys = tp_ladder(SIZE, WEIGHTS)
    usdt = [money(q * (p - ENTRY)) for q, p in zip(qtys, prices, strict=True)]
    total = sum(usdt, Decimal(0))
    risk = risk_usdt(SIZE, ENTRY, STOP)
    partial = Decimal("0.120")
    pct_stop = Decimal("0.0020")
    pct_px = away_from_entry(ENTRY * (1 - pct_stop), ENTRY)
    tp_pct = Decimal("0.0034")
    tp_pct_px = toward_entry(ENTRY * (1 + tp_pct), ENTRY)
    tiny = Decimal("0.002")
    merge_qty, merge_w = Decimal("0.005"), (Decimal("0.10"), Decimal("0.30"), Decimal("0.60"))
    merged, merge_notes = merged_ladder(merge_qty, merge_w)
    liq, liq_stop, liq_size = Decimal("63690.0"), Decimal("63500.0"), Decimal("0.100")
    fee_rate = Decimal("0.0001")
    out: dict[str, object] = {
        "entry": float(ENTRY),
        "stop": float(STOP),
        "target": float(TARGET),
        "size": float(SIZE),
        "tick": float(TICK),
        "equity": float(EQUITY),
        "r_px": float(r_px),
        "stop_ticks": int((r_px / TICK).to_integral_value()),
        "stop_pct": float((r_px / ENTRY * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "risk": float(risk),
        "pct_equity": float(pct_of_equity(risk)),
        "reward": float(money(SIZE * (TARGET - ENTRY))),
        "reward_r": int(((TARGET - ENTRY) / r_px).to_integral_value()),
        "target_ticks": int(((TARGET - ENTRY) / TICK).to_integral_value()),
        "ladder_prices": [float(p) for p in prices],
        "ladder_qty": [float(q) for q in qtys],
        "ladder_usdt": [float(u) for u in usdt],
        "ladder_total_usdt": float(total),
        "ladder_reward_r": float((total / risk).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "partial_fill": float(partial),
        "partial_ladder_qty": [float(q) for q in tp_ladder(partial, WEIGHTS)],
        "breakeven_r": 1.0,
        "breakeven_offset_ticks": 2,
        "breakeven_price": float(ENTRY + 2 * TICK),
        "fee_per_btc_side": float(money(ENTRY * fee_rate)),
        "offset_per_btc": float(2 * TICK),
        "pct_stop_typed": float(pct_stop * 100),
        "pct_stop_price": float(pct_px),
        "pct_stop_ticks": int(((ENTRY - pct_px) / TICK).to_integral_value()),
        "pct_stop_risk": float(risk_usdt(SIZE, ENTRY, pct_px)),
        "pct_stop_pct_equity": float(pct_of_equity(risk_usdt(SIZE, ENTRY, pct_px))),
        "tp_pct_typed": float(tp_pct * 100),
        "tp_pct_price": float(tp_pct_px),
        "tp_pct_usdt": float(money(SIZE * (tp_pct_px - ENTRY))),
        "tp_pct_r": float(
            ((tp_pct_px - ENTRY) / r_px).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ),
        "stop_typed_raw": 63899.96,
        "stop_typed_rounded": float(away_from_entry(Decimal("63899.96"), ENTRY)),
        "tp_typed_raw": 64230.04,
        "tp_typed_rounded": float(toward_entry(Decimal("64230.04"), ENTRY)),
        "wrong_side_stop": 64050.0,
        "wrong_side_tp": 63980.0,
        "ladder_over_pct": 110,
        "tiny_size": float(tiny),
        "tiny_ladder_qty": [float(q) for q in tp_ladder(tiny, WEIGHTS)],
        "single_target_r": 3,
        "single_target_price": float(prices[-1]),
        "merge_size": float(merge_qty),
        "merge_weights_pct": [int(w * 100) for w in merge_w],
        "merge_ladder_qty": [float(q) for q in merged],
        "merge_notes": merge_notes,
        "liq": float(liq),
        "liq_stop": float(liq_stop),
        "liq_size": float(liq_size),
        "liq_risk": float(risk_usdt(liq_size, ENTRY, liq_stop)),
        "liq_leverage": 100,
        "placing_resting": 2,
        "placing_total": 3,
        "failed_tp": 2,
        "failed_code": 110017,
        "mark": 64012.0,
        "min_qty": float(MIN_QTY),
        "tp_levels_max": 10,
        "dialog_px": 640,
        "zoom_width": 1280,
        "zoom_height": 800,
    }
    return out


# ------------------------------------------------------------ loaders, colour, text helpers ----
CITE_WARN: list[str] = []


def rows(table: str) -> list[list[str]]:
    return [[c.strip() for c in ln.split(" | ")] for ln in table.strip().splitlines()]


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


def first(pattern: str, text: str, flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1) if m else "MISSING"


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, MULTI))


def cite(lines: list[str], line: int, needle: str, shift: int = 0) -> tuple[str, str]:
    """The cite rule: `ok` when the needle sits on the cited line (or that line shifted by this
    spec's own pointer lines), `warn` naming the current line when the text moved, `fail` when the
    needle is nowhere in the file or matches more than one line (an ambiguous cite)."""
    hits = [i + 1 for i, ln in enumerate(lines) if needle in ln]
    if not hits:
        return "fail", f"text gone: :{line} {needle[:40]!r} is nowhere in the file"
    if len(hits) > 1:
        return "fail", f"ambiguous: {needle[:40]!r} matches lines {hits[:4]}"
    if hits[0] in (line, line + shift):
        return "ok", ""
    return "warn", f":{line} now at :{hits[0]} ({needle[:40]!r})"


def self_test() -> list[str]:
    """Mutation-test the cite rule on a planted document: a moved line warns, a missing needle
    fails, a two-hit needle fails; anything else is a defect in the rule."""
    doc = ["alpha one", "beta two", "gamma three", "beta two again", "delta four"]
    bad: list[str] = []
    if cite(doc, 3, "gamma three")[0] != "ok":
        bad.append("self-test: an exact cite must be ok")
    if cite(doc, 2, "gamma three")[0] != "warn":
        bad.append("self-test: a moved line must WARN")
    if cite(doc, 1, "epsilon five")[0] != "fail":
        bad.append("self-test: a vanished needle must FAIL")
    if cite(doc, 2, "beta two")[0] != "fail":
        bad.append("self-test: a two-hit needle must FAIL")
    if cite(doc, 1, "alpha one", shift=1)[0] != "ok" or cite(doc, 2, "gamma three", 1)[0] != "ok":
        bad.append("self-test: the pointer shift must be honoured")
    return bad


# ------------------------------------------------------------ contract facts (parsed from text)
def block(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.find(end, i + len(start))
    return text[i:] if j < 0 else text[i:j]


def schema(api: str, name: str) -> str:
    """One `22` component schema: from its 4-space heading to the next 4-space heading."""
    i = api.index(f"\n    {name}:\n") + 1
    m = re.compile(r"\n    [A-Za-z]").search(api, i + 1)
    return api[i:] if m is None else api[i : m.start()]


def contract_facts(t: dict[str, str]) -> dict[str, object]:
    """Every fact the spec quotes, parsed from the plan text; nothing is executed."""
    api, d24, d28 = t["22"], t["24"], t["28"]
    por = schema(api, "PlaceOrderRequest")
    por_props = re.findall(r"^        ([a-z_]+):", por, MULTI)
    bracket = block(api, "        bracket:\n", "\n    PlaceOrderRequest:")
    ctg = schema(api, "CreateTradeGroupRequest")
    tpsl = schema(api, "SetTpSlRequest")
    offset_unit = schema(api, "OffsetUnit")
    place_text = block(api, "      operationId: placeOrder", "\n  /orders/{orderId}:")
    bp = block(d24, "class BracketParams", "```")
    b1 = block(d28, "### B1.2 States", "### B1.3")
    b2 = block(d28, "### B2.2 States", "### B2.3")
    b8 = block(d28, "### B8.2 States", "### B8.3")
    s14 = t["14"]
    scr069 = block(s14, "### SCR-069", "\n### SCR-070")
    cmp119 = block(t["15"], "### CMP-119", "\n### CMP-120")
    cmp158 = block(t["15"], "### CMP-158", "\n### CMP-159")
    return {
        "por_has_stop_loss": "stop_loss" in por_props,
        "por_has_take_profit": "take_profit" in por_props,
        "por_has_tpsl_mode": "tpsl_mode" in por_props,
        "por_has_algo": "algo" in por_props,
        "por_has_sl_trigger_by": "sl_trigger_by" in por_props,
        "ctg_has_sl_trigger_by": "sl_trigger_by" in ctg,
        "tpsl_has_sl_trigger_by": "sl_trigger_by:" in tpsl,
        "tp_levels_max": int(first(r"maxItems: (\d+)", bracket)),
        "tp_level_fields": re.findall(r"^                  ([a-z_]+):", bracket, MULTI),
        "bracket_has_breakeven": "move_stop_to_breakeven_at" in bracket,
        "offset_unit_enum": first(r"enum: \[([^\]]+)\]", offset_unit).replace(" ", "").split(","),
        "place_native_stop_required": "`validation_failed` / `native_stop_required`" in place_text,
        "place_tp_rounded_toward": "rounded toward the entry" in place_text,
        "place_tp_r_multiple_unsupported": "is `stop_unit_unsupported` on `take_profit`"
        in place_text,
        "place_no_waiver": "No field, flag or profile setting waives it (C-4.14)" in place_text,
        "view_as_read_only": "`403 view_as_read_only`" in api,
        "view_as_carve_out": "`setPositionTpSl` (the `trading-stop`" in api,
        "stop_request_in_flight": "code: stop_request_in_flight" in api,
        "x_arm_token": "name: X-Arm-Token" in api,
        "bracket_params_fields": re.findall(r"^    ([a-z_]+):", bp, MULTI),
        "breakeven_offset_default": int(first(r"breakeven_offset_ticks: int = (\d+)", bp)),
        "prefer_native_single_tp": "exactly one TP leg" in d24,
        "ladders_emulated": "Multi-leg TP ladders are emulated as reduce-only limit" in d24,
        "stop_rounds_away": "further from entry, never closer" in d24,
        "r_multiple_invalid_for_stop": "`r_multiple` is invalid for the stop itself" in d24,
        "tp_last_leg_absorbs": "**last** leg absorbing the rounding remainder" in d24,
        "tp_sl_spec_in_24": d24.count("TpSlSpec"),
        "native_sl_confirmed_23": '"native_sl_confirmed": { "type": "boolean" }' in t["23"],
        "b1_lifecycle_states": re.findall(r"^\| `lifecycle\.([a-z_]+)` \| atomic", b1, MULTI),
        "b2_states": re.findall(r"^\| `([a-z_]+)` \| (?:atomic|final)", b2, MULTI),
        "b8_states": re.findall(r"^\| `sl\.([a-z_]+)` \| atomic", b8, MULTI),
        "scr069_checklist_items": len(
            re.findall(r"\[ \]", first(r"(checklist:\*\*.*)$", scr069, MULTI))
        ),
        "scr069_validation_oco_half": "opposite sides of the mark" in scr069,
        "cmp119_hosts_14": count(r"^- \*\*Components:\*\*.*CMP-119 BracketEditor", s14),
        "cmp119_sl_mode": first(r"`slMode: ([^`]+)`", cmp119),
        "cmp119_partial_tp": "`partialTpLevels?: {pct,rMultiple}[]`" in cmp119,
        "cmp119_no_toggle": "There is no stop toggle" in cmp119,
        "cmp119_native_assertion": "no render path yields `nativeSlConfirmed` true" in cmp119,
        "cmp158_says_app_managed": "app-managed" in cmp158,
        "cmp158_role_note": '`role="note"`' in cmp158,
        "scr131_is_admin_profile": "### SCR-131 — Admin: profile editor" in s14,
        "flow_13_tp_levels": "1-3 TP levels" in t["13"],
    }


# ------------------------------------------------------------ the gates ----------------------
def upstream_deck() -> dict[str, str]:
    """E32-D02 section 3.8's table: every key -> its merged string cell (byte-equality source)."""
    text = UPSTREAM.read_text(encoding="utf-8")
    deck = text[text.index("### 3.8 Copy deck") : text.index("\n## 4.")]
    out: dict[str, str] = {}
    for m in re.finditer(
        r"^\| ((?:`[^`]+`(?: · )?)+) +\| (.*?) +\| [^|]*\| [^|]*\| [^|]*\|$", deck, MULTI
    ):
        for key in re.findall(r"`([^`]+)`", m.group(1)):
            out[key] = m.group(2)
    return out


def quoted(cell: str) -> list[str]:
    return [s for s in re.findall(r'"((?:[^"\\]|\\.)*)"', cell) if s]


def frame_gates(s3: str) -> list[str]:
    """Section 3, row by row: C-2.6 (every position-opening frame names its stop), the CMP-158
    line, one class, and the tense gate (no present-tense "held by Bybit" marker on a pre-send
    row: before `native_sl_confirmed` the stop is "held by Bybit once placed")."""
    bad: list[str] = []
    frames = re.findall(r"^\| \d+ +\| `SCR-069 / ([^`]+)` +\|[^\n]*", s3, MULTI)
    for row in re.finditer(r"^\| \d+ +\| `SCR-069 / ([^`]+)` +\|([^\n]*)", s3, MULTI):
        name, rest = row.group(1), row.group(2)
        opening = not any(name.startswith(x) for x in NON_OPENING)
        if opening and not any(mk in rest for mk in STOP_MARKERS):
            bad.append(f"spec section 3: `{name}` opens a position and names no held stop (C-2.6)")
        if name != "E33 extension point" and "CMP-158" not in rest:
            bad.append(f"spec section 3: `{name}` lacks the CMP-158 line")
        if not re.search(CLASS_RE, rest):
            bad.append(f"spec section 3: `{name}` names no class")
        if name in PRE_SEND:
            hits = sorted({m.start() for p in PRESENT_HELD for m in re.finditer(p, rest)})
            if hits:
                at = rest[max(hits[0] - 20, 0) : hits[0] + 30]
                bad.append(f"spec section 3: `{name}` is pre-send but says present-tense {at!r}")
    if len(frames) != len(set(frames)):
        bad.append("spec section 3: a frame name repeats")
    missing = [n for n in PRE_SEND if n not in frames]
    if missing:
        bad.append(f"spec section 3: pre-send rows missing or renamed: {missing}")
    return bad


def self_test_frames() -> list[str]:
    """Mutation-test the frame gates on this spec: the head is clean; one present-tense marker
    on one pre-send row is exactly one FAIL (three phrasings); a renamed pre-send row is exactly
    one FAIL; the viewer row without its stop is exactly one FAIL; a present-tense marker on a
    post-confirm row (`submitting`) is no FAIL."""
    s3 = section(SPEC.read_text(encoding="utf-8"), 3, 4)
    bad: list[str] = []
    if frame_gates(s3):
        bad.append("self-test: the head's section 3 must pass the frame gates")
    draft = '"stop 63,900.0 held by Bybit once placed"'
    rows3 = s3.split("\n")
    for want, name, old, new in (
        (1, "editing`", draft, '"stop 63,900.0 held by Bybit"'),
        (1, "editing`", draft, '"stop 63,900.0 held by the exchange"'),
        (1, "blocked`", draft, '"Stop · 63,900.0 · held by Bybit (exchange)"'),
        (1, "blocked`", "`SCR-069 / blocked`", "`SCR-069 / blocked (renamed)`"),
        (1, "viewer-read-only`", "", ""),
        (0, "submitting`", "stop · 63,900.0 held by Bybit", "stop 63,900.0 held by Bybit"),
    ):
        hit = [i for i, ln in enumerate(rows3) if f"`SCR-069 / {name}" in ln]
        if len(hit) != 1 or old not in rows3[hit[0]]:  # "" plants on any row
            bad.append(f"self-test: cannot plant the {name[:-1]} mutation")
            continue
        mutated = rows3.copy()
        if old:
            mutated[hit[0]] = mutated[hit[0]].replace(old, new)
        else:  # strip every holder phrase from the row; the label "Stop-loss (required)" stays
            for mk in (HOLDER, EXCHANGE, "native_sl_confirmed"):
                mutated[hit[0]] = mutated[hit[0]].replace(mk, "—")
        if mutated[hit[0]] == rows3[hit[0]]:
            bad.append(f"self-test: the {name[:-1]} mutation changed nothing")
            continue
        if not old and STOP_LABEL not in mutated[hit[0]]:
            bad.append("self-test: the viewer mutation must keep the label (label alone fails)")
        got = len(frame_gates("\n".join(mutated)))
        if got != want:
            bad.append(f"self-test: the {name[:-1]} mutation gave {got} FAIL, not {want}")
    # Row 9 (`submitted`) names its stop as "held by the exchange" and the wire flag: without
    # the flag the registered words still carry it (0 FAIL); without both, exactly one FAIL.
    hit = [i for i, ln in enumerate(rows3) if "`SCR-069 / submitted`" in ln]
    for want, strip in ((0, ("native_sl_confirmed",)), (1, ("native_sl_confirmed", EXCHANGE))):
        if len(hit) != 1 or any(x not in rows3[hit[0]] for x in strip):
            bad.append("self-test: cannot plant the submitted mutation")
            continue
        mutated = rows3.copy()
        for x in strip:
            mutated[hit[0]] = mutated[hit[0]].replace(x, "—")
        got = len(frame_gates("\n".join(mutated)))
        if got != want:
            bad.append(f"self-test: submitted without {strip} gave {got} FAIL, not {want}")
    return bad


def class_word_gates(spec: str) -> list[str]:
    """The RULED class word present in sections 2, 5 and 10; every retired word refused: the
    "app-managed" pattern in the UI sections, the middle-dot form anywhere outside the HA-14 row
    (one FAIL per occurrence, so a middle dot in section 10's `cls.emulated` or in one of
    section 5's two is caught once)."""
    bad: list[str] = []
    for n in (2, 5, 10):
        if RULED_WORD not in section(spec, n, n + 1):
            bad.append(f"spec section {n}: the RULED class word is missing")
    for n in (2, 3, 4, 5, 6, 7, 8, 10):
        body = section(spec, n, n + 1)
        bad += [
            f"spec section {n}: retired word in UI copy: {mm.group(0)!r}"
            for p in BANNED_COPY
            if p != RETIRED_WORD
            for mm in re.finditer(p, body)
        ]
    for mm in re.finditer(RETIRED_WORD, re.sub(HA14_ROW, "", spec, flags=MULTI)):
        bad.append(f"spec: the retired middle-dot class word outside HA-14: {mm.group(0)!r}")
    return bad


def self_test_class_word() -> list[str]:
    """Mutation-test the class-word gate: the head is clean; the middle-dot form planted in
    section 10's `cls.emulated` row, or in one of section 5's two occurrences, is exactly one
    FAIL each; section 10 without the RULED word is exactly one FAIL; HA-14's own quoted "from"
    string is no FAIL."""
    spec = SPEC.read_text(encoding="utf-8")
    bad: list[str] = []
    if class_word_gates(spec):
        bad.append("self-test: the head's class words must pass the class-word gate")
    dot = "Emulated · run by CandleViewer, not Bybit"
    s5 = section(spec, 5, 6)
    for label, start, end, want in (
        ("section 10 cls.emulated", "\n| `cls.emulated` ", "\n", 1),
        ("section 5 (first of two)", s5[:20], "\n## 6.", 1),
    ):
        i = spec.index(start)
        j = spec.index(end, i + len(start))
        k = spec.find(RULED_WORD, i, j)
        if k < 0:
            bad.append(f"self-test: cannot plant the {label} class-word mutation")
            continue
        mutated = spec[:k] + dot + spec[k + len(RULED_WORD) :]
        got = len(class_word_gates(mutated))
        if got != want:
            bad.append(f"self-test: the {label} class-word mutation gave {got} FAIL, not {want}")
    s10 = section(spec, 10, 11)
    if class_word_gates(spec.replace(s10, s10.replace(RULED_WORD, "Emulated"))) != [
        "spec section 10: the RULED class word is missing"
    ]:
        bad.append("self-test: section 10 without the RULED word must be exactly one FAIL")
    if dot not in re.findall(HA14_ROW, spec, MULTI)[0]:
        bad.append("self-test: HA-14's quoted from-string must keep the middle dot")
    return bad


def gates(files: list[Path], spec: str, facts: dict[str, object], t: dict[str, str]) -> list[str]:
    bad: list[str] = []
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    deck = section(spec, 10, 11)
    up = upstream_deck()
    for m in re.finditer(r"^\| `([^`]+)` +\| (.*?) +\| (E32-D02[^|]*?) +\|", deck, MULTI):
        key, strings = m.group(1), quoted(m.group(2))
        if key not in up:
            bad.append(f"spec section 10: `{key}` is not an E32-D02 section 3.8 key")
            continue
        bad += [
            f"spec section 10: `{key}` not byte-equal to E32-D02: {s[:50]!r}"
            for s in strings
            if s not in up[key]
        ]
    for needle, where in ((NOTE_DRAFT, "the CMP-158 sentence"), (SL_REQUIRED, "v.sl.required")):
        if needle not in spec:
            bad.append(f"spec: {where} missing verbatim")
    bad += class_word_gates(spec)
    for key, cell in re.findall(REASON_RE, deck, MULTI):
        for s in quoted(cell):
            if len(s) > 60 or not s.endswith(".") or re.search(r"\d", s):
                bad.append(f"T2 reason {key}: {len(s)} chars; stop {s.endswith('.')}")
    bad += frame_gates(section(spec, 3, 4))
    s5 = section(spec, 5, 6)
    bad += [f"spec section 5: consumer {c} is not specified" for c in CONSUMERS if c not in s5]
    lines = {k: v.split("\n") for k, v in t.items()}
    CITE_WARN.clear()
    for doc, line_s, want in rows(CITED_TABLE):
        line = int(line_s)
        shift = 0
        if doc in ("14", "15"):
            shift = sum(any(p in ln for p in POINTERS) for ln in lines[doc][: line - 1])
        state, msg = cite(lines[doc], line, want, shift)
        if state == "warn":
            CITE_WARN.append(f"`{doc}` {msg}")
        elif state == "fail":
            bad.append(f"cite `{doc}` {msg}")
    for f in files:
        txt = f.read_text(encoding="utf-8")
        bad += [f"{f.name}: forbidden text {p}" for p in FORBIDDEN if re.search(p, txt)]
        for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", txt))):
            if f"**{r}" not in constitution:
                bad.append(f"{f.name}: dangling rule id {r}")
        for c in sorted(set(re.findall(r"\b(?:CMP|SCR)-\d{3}\b", txt))):
            if f"### {c} " not in t["15" if c.startswith("CMP") else "14"]:
                bad.append(f"{f.name}: no catalogue heading for {c}")
    claims = (
        ("por_has_sl_trigger_by", False, "G-23 stands: no sl_trigger_by on PlaceOrderRequest"),
        ("tpsl_has_sl_trigger_by", True, "SetTpSlRequest carries sl_trigger_by"),
        ("por_has_stop_loss", True, "PlaceOrderRequest.stop_loss"),
        ("por_has_algo", True, "PlaceOrderRequest.algo"),
        ("place_tp_rounded_toward", True, "a take-profit rounds toward the entry"),
        ("place_tp_r_multiple_unsupported", True, "R on take_profit is refused today"),
        ("stop_rounds_away", True, "the stop rounds away from the entry"),
        ("tp_last_leg_absorbs", True, "the last rung absorbs the remainder"),
        ("native_sl_confirmed_23", True, "native_sl_confirmed on the trade_groups leg"),
        ("cmp119_no_toggle", True, "CMP-119 has no stop toggle"),
        ("cmp158_says_app_managed", False, "CMP-158 does not say app-managed"),
        ("scr131_is_admin_profile", True, "SCR-131 is the per-account profile editor"),
    )
    for fact, expect, what in claims:
        if facts.get(fact) != expect:
            bad.append(f"contract fact: {what} — the text says {facts.get(fact)!r}")
    if facts.get("tp_levels_max") != 10 or facts.get("breakeven_offset_default") != 2:
        bad.append("contract fact: take_profit_levels maxItems 10 / breakeven_offset_ticks 2 moved")
    if facts.get("tp_sl_spec_in_24") != 0:
        bad.append("contract fact: `TpSlSpec` now exists in `24` — drop the wording gap")
    return bad


def flatten(d: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1]] = d
    return out


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        bad = self_test() + self_test_frames() + self_test_class_word()
        msg = "self-test: clean (cite: moved → WARN, gone → FAIL, ambiguous → FAIL; frames: "
        msg += "pre-send present tense (3 phrasings) → 1 FAIL, a renamed pre-send row → 1 FAIL, "
        msg += "viewer with its label alone → 1 FAIL, submitted without its flag → 0, without its "
        msg += "flag and 'held by the exchange' → 1, post-confirm → 0; class word: middle dot in "
        msg += "section 10 cls.emulated → 1 FAIL, in section 5 (one of two) → 1 FAIL, "
        msg += "section 10 without it → 1 FAIL)"
        print(msg if not bad else "\n".join(bad))
        return 1 if bad else 0
    themes = {k: load_theme(k) for k in THEMES}
    t = {k: p.read_text(encoding="utf-8") for k, p in DOCS.items()}
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
            verdict = "7:1 met" if demo_7 else "7:1 not met — shortfall stated (spec 11)"
        elif bar is None:
            verdict = "reported, not gated" if role == "decorative" else "rejected, never drawn"
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
        "validity composite (the Place label at opacity.disabled against its own fill at "
        f"opacity.disabled, both over the overlay; not gated): {composite}"
    )
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    missing = [tok for tok in BINDINGS if resolve(themes["dark"], tok) == "MISSING"]
    out += [
        f"{tok} | {' / '.join(resolve(tk, tok)[:40] for tk in themes.values())}" for tok in BINDINGS
    ]
    out.append(f"MISSING tokens: {missing}")
    facts = contract_facts(t)
    fx = fixture()
    out.append("\n## 3-4. Contract facts parsed from text, beside the spec's claims:")
    out.append(json.dumps(facts, ensure_ascii=False))
    spec = SPEC.read_text(encoding="utf-8")
    bad = gates([SPEC, HANDOFF], spec, facts, t)
    ok = (
        "OK — every E32-D02 section 3.8 key byte-equal; the CMP-158 sentence and v.sl.required "
        "verbatim; the RULED class word present; no retired word in UI copy; every rbac reason "
        "within 60 characters; every position-opening frame names its held stop (C-2.6); no "
        "private text; no present-tense stop marker on a pre-send row; every C / CMP / SCR id "
        "exists; every cited text found once"
    )
    out.append("\n## 5. String gates: " + (ok if not bad else "\n".join("FAIL " + b for b in bad)))
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    deck = section(spec, 10, 11)
    deck_rows = re.findall(r"^\| `[^|]*? +\| .*? +\| ([^|]+?) +\|", deck, MULTI)
    by_source: dict[str, int] = {}
    for src in deck_rows:
        key = src.split(" ")[0].strip("`*")
        by_source[key] = by_source.get(key, 0) + 1
    reasons = [k for k, _ in re.findall(REASON_RE, deck, MULTI)]
    state_keys = [k for k in REGISTERED_STATE if f"`{k}`" in deck]
    handoff = HANDOFF.read_text(encoding="utf-8") if HANDOFF.exists() else ""
    numbers: dict[str, object] = {k: count(p, section(spec, a, b)) for k, a, b, p in COUNTS}
    numbers.update({k: count(rf"^\| H{p}-\d+ ", spec) for k, p in ROW_IDS})
    numbers["bq_rows"] = count(r"^\| BQ-\d+ ", spec)
    numbers.update({"pairs_rows": gated, "pairs_registered": gated - proposed})
    numbers.update({"pairs_proposed": proposed, "pairs_fail": fails, "demo_badge_7_1": demo_7})
    numbers.update(
        {"composite": composite, "deck_rows": len(deck_rows), "deck_by_source": by_source}
    )
    numbers["opacity_disabled"] = float(resolve(themes["dark"], "opacity.disabled"))
    numbers.update({"deck_proposed": by_source.get("PROPOSED", 0), "reason_keys": len(reasons)})
    numbers["state_keys_cited"] = len(state_keys)
    numbers["handoff_blocks"] = count(r"^## Handoff checklist", handoff)
    numbers.update({"missing_tokens": len(missing), "consumers": len(CONSUMERS)})
    numbers["hosts_14"] = facts["cmp119_hosts_14"]
    numbers["cite_warnings"] = len(CITE_WARN)
    numbers["b2_states"] = len(list(facts["b2_states"]))  # type: ignore[call-overload]
    numbers["b8_states"] = len(list(facts["b8_states"]))  # type: ignore[call-overload]
    numbers["fixture"] = fx
    flat = flatten(numbers)
    if "--check" in argv:
        for key, val in re.findall(r"<!-- audit:([a-z0-9_.-]+)=([^ ]+) -->", spec + handoff):
            have = flat.get(key)
            same = str(have).lower() == val.lower()
            try:
                same = same or float(str(have)) == float(val)
            except ValueError:
                pass
            if have is None or not same:
                bad.append(f"marker audit:{key}={val} vs tool {have}")
        clean = not any(b.startswith("marker") for b in bad)
        out.append("markers: " + ("clean" if clean else "MISMATCH"))
    out.append("\n## 6. Counts: " + json.dumps(numbers, ensure_ascii=False))
    if "--json" in argv:
        palette = {th: {n: resolve(tk, n) for n in BINDINGS} for th, tk in themes.items()}
        payload = {"numbers": numbers, "matrix": matrix, "missing": missing, "facts": facts}
        payload.update({"problems": bad, "cite_warnings": CITE_WARN, "palette": palette})
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("\n".join(out))
    return 1 if fails or bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
