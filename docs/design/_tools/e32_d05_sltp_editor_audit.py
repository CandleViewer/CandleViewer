#!/usr/bin/env python3
"""E32-D05 SCR-064 position SL/TP editor and CMP-120 audit (stdlib, offline; executes no repo code).

Reads the token JSON, `pairs.mjs`, the plan texts, the merged upstream specs and the spec AS TEXT
and prints: (1) the WCAG 2.x ratio of every fg / bg pair SCR-064 and CMP-120 render in dark /
light / high-contrast (`themes.json` layering) and the validity composite; (2) every token the
spec binds, resolved or MISSING, and the glyph names no merged spec uses yet; (3) the pairs
`pairs.mjs` registers; (4) the contract facts the boards quote, parsed from text; (5) the trail
arithmetic over the fixture (Decimal, tick 0.10): the readout's digits, the lockout stop, the
loosen risk, the `22` example's implied reference, the ratchet's widest trail, the ladder frames'
fixture; (6) the string gates (no banned word in the copy deck, no raw error-code token, every T2
reason within 60 characters, the stale template's fixed text within 60, no private path, every
cited id and line still valid, the C-2.6 sentences present, no LIVE frame without the arm or the
step-up, no pending frame that reads as applied, no closing keyword in a draft passed with
`--extra`); (7) the counts the boards and the draft quote. `--json` feeds the check-nums script;
`--check` re-derives the spec's `audit:` markers; `--self-test` flips each gate on a copy of the
spec in memory and expects exactly one named FAIL. Exit 1 on a gated FAIL or a failed gate.

Usage: python3 -I docs/design/_tools/e32_d05_sltp_editor_audit.py [--json] [--check] [--self-test]
       [--extra F ...]
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E32" / "E32-D05.md"
HANDOFF = DESIGN / "E32" / "E32-D05-handoff.md"
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES = {"dark": (PRIM, DARK), "light": (PRIM, DARK, LIGHT), "high-contrast": (PRIM, DARK, HC)}
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0}
MULTI = re.MULTILINE
# Generic patterns only (no personal word, no hostname, no folder name, whole or split): a local
# home path, a design-tool host, a team / file id query, a home-relative path.
FORBIDDEN = (
    r"/(?:ho[m]e|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
    r"~/[a-z0-9-]+/",
)
# Words that leave user-facing copy (the BQ-12 ruling; the memo SC-6, F6; `24` :2053's code-only
# rule; a step-up class id or an audit action name is an annotation, never a sentence); checked on
# the copy deck only.
BANNED_COPY = (
    r"app-managed",
    r"client-side",
    r"engine-managed",
    r"retMsg",
    r"ret_msg",
    r"sl_loosen",
    r"sl\.loosened",
)
# The C-2.6 sentences the spec must carry verbatim (section 1.1 and the state rows).
STOP_SENTENCES = (
    "never empty at rest, no clear glyph, no toggle",
    "the board self-check throws on a `SCR-064 /` frame without its `stop-marker`",
    "the only path to a wider stop is the owner's flow",
)
HELD_NOW = "Held by Bybit now"
# element | fg | bg | role — every pair the two screens draw (spec section 14, rows in order).
PAIRS_TABLE = """
dialog body, field values, read-out words | color.text.primary | color.surface.overlay | text
labels, read-outs, reasons on the overlay | color.text.secondary | color.surface.overlay | text
T2 menu / slot label on the overlay | color.text.tertiary | color.surface.overlay | text
key-card words on raised | color.text.primary | color.surface.raised | text
reasons on raised | color.text.secondary | color.surface.raised | text
T2 label and lock glyph on raised | color.text.tertiary | color.surface.raised | text
captions on the canvas | color.text.secondary | color.surface.canvas | text
tertiary captions on the canvas | color.text.tertiary | color.surface.canvas | text
field value in the well | color.text.primary | color.surface.app | text
field well boundary | color.text.tertiary | color.surface.app | non-text
the active segment's word | color.text.primary | color.surface.selected | text
env badge word (AA bar) | color.text.primary | color.surface.raised | text
env badge word (the 7:1 target) | color.text.primary | color.surface.raised | aaa-target
LIVE ring on raised | color.env.live | color.surface.raised | non-text
DEMO ring on raised | color.env.demo | color.surface.raised | non-text
CMP-158 sentence, pending line | color.text.primary | color.status.info.subtle | text
CMP-158 glyph, pending hatch lines | color.status.info.strong | color.status.info.subtle | non-text
the estimated badge outline | color.status.info.default | color.status.info.subtle | non-text
refusal, rejected and revert words | color.text.primary | color.status.danger.subtle | text
danger glyph, unprotected hatch | color.status.danger.strong | color.status.danger.subtle | non-text
validation boundary, marked step | color.status.danger.default | color.surface.overlay | non-text
applied words | color.text.primary | color.status.success.subtle | text
applied check glyph | color.status.success.strong | color.status.success.subtle | non-text
liquidation warning, stamp words | color.text.primary | color.status.warning.subtle | text
warning glyph, the stamp ring | color.status.warning.strong | color.status.warning.subtle | non-text
stale values | color.data-confidence.stale.text | color.data-confidence.stale.surface | text
Apply / Loosen-to label | color.text.on-action | color.action.primary.default | text
focus ring on the overlay | color.focus.ring | color.surface.overlay | non-text
focus ring on raised | color.focus.ring | color.surface.raised | non-text
REJECTED T2 label in text.disabled | color.text.disabled | color.surface.raised | rejected-text
the dialog hairline | color.border.default | color.surface.overlay | decorative
"""
BINDINGS = (
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
    "color.surface.selected",
    "color.border.default",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.on-action",
    "color.status.info.subtle",
    "color.status.info.default",
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
    "color.data-confidence.stale.text",
    "color.data-confidence.stale.surface",
    "opacity.disabled",
    "radius.card",
    "type.ui.caption",
    "type.ui.body",
    "type.ui.label",
    "type.num.base",
    "size.control.height",
    "space.inset.sm",
    "space.inset.md",
)
DS_REQUESTS = ("pattern.hatch",)
GLYPHS = ("lock", "alert-triangle", "check", "x", "hourglass", "shield-off", "info")
GLYPH_PRECEDENTS = (
    "E29/E29-D02.md",
    "E29/E29-D03.md",
    "E30/E30-D04.md",
    "E33/E33-D03.md",
    "E17/E17-D02.md",
)
# doc | line at the base | text the line must hold (re-found by content: drift = WARN, gone = FAIL).
CITED_TABLE = """
14 | 1477 | ### SCR-064
14 | 1498 | Every position keeps a native stop
14 | 1499 | persistent, readable note, not a tooltip
14 | 1500 | `position.stop_modified`, `position.tp_ladder_set`
14 | 1501 | never optimistically as confirmed
14 | 1502 | CMP-120 TrailingStopEditor, CMP-130
14 | 1504 | keyboard path equivalent to chart drag-to-modify
14 | 242 | ### SCR-006
15 | 1349 | ### CMP-120 TrailingStopEditor
15 | 1356 | re-submitting stop-order amendments via the order-amend REST endpoint
15 | 799 | ### CMP-079 RbacGate
15 | 224 | ### CMP-019 Icon
15 | 2638 | ### CMP-227 EstimatedBadge
22 | 6671 | /positions/{positionId}/tpsl:
22 | 6680 | Trailing stop is a price distance on Bybit, not a percentage
22 | 6690 | Only the owner can loosen a stop
22 | 6704 | A trail is never cleared here
22 | 6709 | x-rbac: { permissions: [positions:write], scope: granted_accounts }
22 | 6723 | pctTrail:
22 | 6748 | trailing_stop_distance: "757.43"
22 | 11750 | `backups` and `sl_loosen` are no-grace
22 | 11789 | Required for a no-grace class
22 | 14242 | owner's loosened stop on `setPositionTpSl`
22 | 15902 | enum: [ticks, percent, r_multiple, atr, price]
22 | 18012 | move_stop_to_breakeven_at:
22 | 18589 | Position:
22 | 18616 | trailing_stop:
22 | 18622 | native_stop_present:
22 | 18647 | SetTpSlRequest:
22 | 18666 | TpSlResult:
23 | 3472 | ### 15.2 `PositionUpdate`
23 | 4368 | ### 15.10 `MachineStateUpdate`
24 | 165 | `InstrumentPolicy.round_price` (nearest, `ROUND_HALF_EVEN`)
24 | 1385 | trailing_active_price: Px
24 | 2053 | **Code-only rule
24 | 2091 | ### 8.8 Safety invariant
24 | 2101 | 5. Smarter stops (ATR trail, structure trail, breakeven)
24 | 2111 | A tightening is never refused by it
24 | 2143 | one-sided TP/SL modification via `trading-stop` breaks Bybit's OCO pairing
24 | 2162 | tightens the stop, so it is never gated either
24 | 2532 | **9.3.1 Stop resolution.**
24 | 2889 | breakeven_offset_ticks: int = 2
24 | 2896 | class TrailSpec(BaseModel):
24 | 2902 | only_tighten: bool = True
24 | 2906 | **price distance, not a percentage**
24 | 3434 | `move_to_breakeven`
24 | 3476 | `sys.breakeven_at_1r`
24 | 4834 | `sl.loosened` and `sl.loosen_refused`
28 | 4161 | ## B8 — Position protection
28 | 4458 | ### B8.2 States
28 | 4477 | ### B8.3 Events and transitions
28 | 4550 | ### B8.7 Invariants
11 | 3044 | #### US-ORD-008
11 | 3379 | #### US-ALGO-008
11 | 3395 | percentage trails are emulated
13 | 196 | auto-confirms after 2s
13 | 202 | `17-ux-diagrams.md` §8 hotkey map
17 | 422 | ## 7. Hotkey map
17 | 437 | `Arrow Up/Down` (on SL/TP handle)
17 | 457 | ## 8. Traceability
05 | 72 | `Shift+←` / `Shift+→`
05 | 96 | **Focus is never silently stolen**
05 | 101 | **Dragging alternatives**
05 | 127 | **AAA stretch target for critical state**
05 | 131 | **Text resize (WCAG 1.4.4, AA)**
06 | 28 | Order submit → ack
16 | 107 | ## 3. Density modes
16 | 134 | ## 4. Dark-first theming + light theme
18 | 332 | ### 2.18 ALGO
E32-D02 | 167 | **One native-stop treatment**
E32-D02 | 168 | **Loosen slot reserved:**
E32-D02 | 174 | **Four class words with one sentence each**
E32-D02 | 175 | **SCR-064 is layered:**
E32-D02 | 181 | **Pending is never confirmed:**
E32-D02 | 203 | ### 3.2 The native-stop floor
E32-D02 | 224 | app-managed ("(app-managed)", text, never CMP-227)
E32-D02 | 346 | (app-managed) · only tightens
E32-D02 | 437 | B8's states are not on the wire (G-5)
E32-D02 | 468 | `viewer-read-only`
E32-D02 | 477 | ### 4.4 Focus order
E32-D02 | 485 | ### 4.5 The keyboard path equivalent to chart drag-to-modify
E32-D02 | 497 | ### 4.6 Events per control
E09-D09 | 49 | **T2 Disabled with a visible reason (D4).**
E09-D09 | 83 | ### 3.1 The keys
E09-D09 | 90 | `rbac.owner_only`
E09-D09 | 110 | `positions:write` → "change positions"
E09-D09 | 224 | ### 9.1 `aria-disabled` versus `disabled`
E09-D09 | 230 | a control disabled by **form validity**
E09-D09 | 238 | ### 9.3 Keys on a T2 control
E09-D09 | 263 | `notice.panel_read_only`
E30-D02 | 128 | **Side and submit:**
E30-D02 | 140 | **Arm indicator (CMP-229, global scope)
E30-D02 | 416 | `submit.not_connected`
E30-D02 | 421 | Locked out — reduce through Close position
E30-D02 | 422 | Trading frozen by the owner at {hh:mm} UTC
E30-D04 | 180 | ### 2.3 `unprotected`
E30-D04 | 201 | ### 2.5 The two disabled looks, written once
E09-D02 | 186 | ## 9. SCR-006 Step-up modal
E17-D01 | 152 | Order entry off — <message>. <what still works>
E17-D01 | 103 | Order entry off — <role-neutral message>. <what still works>
E33-D02 | 338 | name "Emulated — run by CandleViewer, not Bybit"
E32-D02 | 528 | 22,419.75
22 | 6726 | trailing_stop: { unit: percent, value: "1.2" }
24 | 2384 | fallback_sl_offset_pct: Decimal
E25-D01 | 329 | ### 9.5 Catalogue amendments
README | 73 | one **page per screen**
"""
DOC_NAMES = {
    "05": "05-accessibility-standard.md",
    "06": "06-performance-and-load-standard.md",
    "11": "11-user-stories.md",
    "13": "13-user-flows.md",
    "14": "14-screens-catalogue.md",
    "15": "15-component-catalogue.md",
    "16": "16-design-system-brief.md",
    "17": "17-ux-diagrams.md",
    "18": "18-traceability-matrix.md",
    "21": "21-database-schema.md",
    "22": "22-api-openapi.yaml",
    "23": "23-ws-protocol.md",
    "24": "24-internal-schemas.md",
    "28": "28-statechart-catalogue.md",
}
DESIGN_DOCS = {
    "E32-D02": "E32/E32-D02.md",
    "E09-D09": "E09/E09-D09.md",
    "E09-D02": "E09/E09-D02.md",
    "E30-D02": "E30/E30-D02.md",
    "E30-D04": "E30/E30-D04.md",
    "E17-D01": "E17/E17-D01.md",
    "E25-D01": "E25/E25-D01.md",
    "E33-D02": "E33/E33-D02.md",
    "README": "README.md",
}
MERGE_SHAS = (
    "d74b05b3031618d9cb042ba90c914da0369da9ba",
    "27bd8e885cf07d9ed47fdbf23880c65fdf60d5a8",
    "4f9d15b6beef6c7dc060ddd14fd6179f4597f535",
    "88839ea334a61482ad9b3936286e70ef3b5ba4b4",
    "f798a64e65d15d13f2f816c9b5564e0d148ba2ae",
    "b7154f95153d5357b5c50cc91c5f43000de64335",
    "035c4b069b0a006758644807f4db996bbfc506b9",
    "ca7d61fa1a767f6698d5243379546ad9f95090ab",
    "baccf724a1fa3ad66f9333e440a7f5e8668b6eff",
)
CLOSING = r"\b(?:clos(?:e|es|ed|ing)|fix(?:es|ed)?|resolv(?:e|es|ed))\s*:?\s*#\d+"
# The fixture (E32-D02 section 4.1's placeholder set); every derived figure is computed below.
TICK = Decimal("0.1")
F: dict[str, Decimal] = {
    "entry": Decimal("64010.0"),
    "mark": Decimal("64012.5"),
    "last": Decimal("64011.0"),
    "liq": Decimal("57929.0"),
    "stop": Decimal("63900.0"),
    "size": Decimal("0.250"),
    "equity": Decimal(12500),
    "leverage": Decimal(10),
    "step": Decimal("0.001"),
}
ROWS = {"compact_px": 24, "comfortable_px": 32, "dialog_px": 640}
COUNT_RE = {
    "a_rows": r"^\| D05-A\d+ ",
    "c_rows": r"^\| D05-C\d+ ",
    "g_rows": r"^\| D05-G\d+ ",
    "q_rows": r"^\| D05-Q\d+ ",
    "bq_rows": r"^\| BQ-\d+ ",
}
STATE_ROW = r"^\| (\d+) +\| `([^`]+)`[^|]*\| ([^|]+?) +\| ([^|]+?) +\|([^\n]*)"
REASON_RE = r"^\| `((?:rbac|arm|submit)\.[a-z_.]+|frozen|lockout)` +\| ([^|]+?) +\|"
DECK_RE = r"^\| (`[^|]+?`|— [^|]*?) +\| ([^|]*?) +\| ([^|]+?) +\|$"
POINTERS = {
    "14": "E32-D05.md](../design/E32/E32-D05.md)",
    "15": "E32-D05-handoff.md](../design/E32/E32-D05-handoff.md)",
}
CITE_WARN: list[str] = []


def rows(table: str) -> list[list[str]]:
    return [[c.strip() for c in ln.split("|")] for ln in table.strip().splitlines()]


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


def section(spec: str, a: int, b: int | None) -> str:
    start = spec.index(f"\n## {a}.")
    return spec[start:] if b is None else spec[start : spec.index(f"\n## {b}.")]


def first(pattern: str, text: str, flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1) if m else "MISSING"


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, MULTI))


def num(d: Decimal) -> float:
    return float(d)


# ---- the trail arithmetic (Decimal; the spec's section 5 is this, printed) ----------------------
def up_to_tick(x: Decimal) -> Decimal:
    return (x / TICK).quantize(Decimal(1), rounding=ROUND_CEILING) * TICK


def away_from_entry(price: Decimal, side: str) -> Decimal:
    rounding = ROUND_FLOOR if side == "long" else ROUND_CEILING
    return (price / TICK).quantize(Decimal(1), rounding=rounding) * TICK


def ticks_between(a: Decimal, b: Decimal) -> int:
    return int(((a - b).copy_abs() / TICK).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def one_r() -> Decimal:
    return (F["entry"] - F["stop"]) * F["size"]


def r_to_price(r: Decimal, side: str = "long") -> Decimal:
    per_unit = (F["entry"] - F["stop"]).copy_abs() * r
    return F["entry"] + per_unit if side == "long" else F["entry"] - per_unit


def risk_usd(stop: Decimal) -> Decimal:
    return ((F["entry"] - stop).copy_abs() * F["size"]).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def pct_of_equity(usd: Decimal) -> Decimal:
    return (usd / F["equity"] * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def trail_translate(
    pct: Decimal, ref: Decimal, side: str, activation: Decimal
) -> dict[str, Decimal]:
    """percent of the reference -> a distance rounded UP to the tick; the first trigger from the
    activation (the mark when it arms at once), rounded further from entry (24 section 9.3.1)."""
    distance = up_to_tick(ref * pct / 100)
    raw = activation - distance if side == "long" else activation + distance
    return {"distance": distance, "trigger": away_from_entry(raw, side)}


def tp_ladder(size: Decimal, legs: list[tuple[Decimal, Decimal]]) -> list[dict[str, Decimal]]:
    """E32-D01's rule: each leg floors to the step; the last leg absorbs the remainder."""
    out: list[dict[str, Decimal]] = []
    used = Decimal(0)
    for i, (pct, r) in enumerate(legs):
        qty = (size * pct / 100 / F["step"]).quantize(Decimal(1), rounding=ROUND_FLOOR) * F["step"]
        if i == len(legs) - 1:
            qty = size - used
        used += qty
        price = r_to_price(r)
        usd = ((price - F["entry"]) * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out.append({"r": r, "price": price, "qty": qty, "usd": usd})
    return out


def arithmetic() -> dict[str, object]:
    r1 = one_r()
    act = r_to_price(Decimal("1.0"))
    pct15 = trail_translate(Decimal("1.5"), F["mark"], "long", act)
    pct015 = trail_translate(Decimal("0.15"), F["mark"], "long", act)
    pct12 = trail_translate(Decimal("1.2"), F["mark"], "long", act)
    atr_value, atr_mult = Decimal("320.0"), Decimal("2.0")
    atr_distance = atr_value * atr_mult
    atr_mark_needed = F["stop"] + atr_distance
    example = Decimal("757.43")
    implied_ref = (example / Decimal("0.012")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    lock_stop = away_from_entry(F["entry"] * (1 - Decimal("0.0015")), "long")
    pend_stop = F["entry"] - 600 * TICK
    loosen = Decimal("63800.0")
    ladder = tp_ladder(
        F["size"], [(Decimal(25), Decimal(1)), (Decimal(25), Decimal(2)), (Decimal(50), Decimal(3))]
    )
    fixture: dict[str, object] = {k: num(v) for k, v in F.items() if k != "step"}
    fixture.update(
        {
            "tick": num(TICK),
            "stop_ticks": ticks_between(F["entry"], F["stop"]),
            "stop_pct": num(
                ((F["entry"] - F["stop"]) / F["entry"] * 100).quantize(Decimal("0.01"))
            ),
            "risk_1r": num(r1),
            "risk_pct": num(pct_of_equity(r1)),
            "breakeven": num(F["entry"] + 2 * TICK),
        }
    )
    for i, leg in enumerate(ladder, start=1):
        fixture[f"tp{i}"] = num(leg["price"])
        fixture[f"tp_qty{i}"] = num(leg["qty"])
        fixture[f"tp_usdt{i}"] = num(leg["usd"])
    trail: dict[str, object] = {
        "fixed_distance": 150.0,
        "activation": num(act),
        "fixed_trigger": num(away_from_entry(act - Decimal("150.0"), "long")),
        "pct15_distance": num(pct15["distance"]),
        "pct15_trigger": num(pct15["trigger"]),
        "pct15_wider_than_stop": pct15["trigger"] < F["stop"],
        "pct015_distance": num(pct015["distance"]),
        "pct015_trigger": num(pct015["trigger"]),
        "pct015_wider_than_stop": pct015["trigger"] < F["stop"],
        "pct12_distance": num(pct12["distance"]),
        "example_distance": num(example),
        "example_ref": num(implied_ref),
        "example_ref_on_tick": implied_ref % TICK == 0,
        "atr_value": num(atr_value),
        "atr_mult": num(atr_mult),
        "atr_distance": num(atr_distance),
        "atr_trigger": num(F["mark"] - atr_distance),
        "atr_mark_needed": num(atr_mark_needed),
        "atr_r_needed": num(
            ((atr_mark_needed - F["entry"]) / (F["entry"] - F["stop"])).quantize(Decimal("0.01"))
        ),
        "revert_distance": 300.0,
        "revert_activation": num(r_to_price(Decimal("2.0"))),
        # the widest trail the ratchet accepts on this fixture: arming at +1.0 R the trigger must
        # stay at or above the stop in force; arming at once, from the mark
        "max_at_activation": num(act - F["stop"]),
        "max_at_once": num(F["mark"] - F["stop"]),
    }
    # The two ladder pending frames use E32-D02 section 5.1's scaled entry (its table, quoted and
    # re-found by the cite gate): levels 1-2 filled, the stop 2 % below the far end, re-derived.
    ladder_far_end = Decimal("63700.0")
    ladder_stop = ladder_far_end * (1 - Decimal("0.02"))
    ladder_tighten = Decimal("62476.0")
    ladder_fixture = {
        "size": 0.351,
        "avg": 63873.9,
        "far_end": num(ladder_far_end),
        "stop": num(ladder_stop),
        "tighten": num(ladder_tighten),
        "tighter_ticks": ticks_between(ladder_stop, ladder_tighten),
    }
    lockout = {
        "pct": 0.15,
        "stop": num(lock_stop),
        "ticks": ticks_between(F["entry"], lock_stop),
        "risk": num(risk_usd(lock_stop)),
        "pct_eq": num(pct_of_equity(risk_usd(lock_stop))),
    }
    pending = {
        "ticks": 600,
        "stop": num(pend_stop),
        "risk": num(risk_usd(pend_stop)),
        "pct": num(pct_of_equity(risk_usd(pend_stop))),
        "tighter_by": num(F["stop"] - pend_stop + 0),
    }
    pending["tighter_by"] = (
        num((F["stop"] - pend_stop).copy_abs()) if False else num(pend_stop - F["stop"])
    )
    loosen_risk = risk_usd(loosen)
    loosened = {
        "stop": num(loosen),
        "risk": num(loosen_risk),
        "added": num(loosen_risk - r1),
        "r": num((loosen_risk / r1).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "pct": num(pct_of_equity(loosen_risk)),
        "wider": num(F["stop"] - loosen),
        "wider_ticks": ticks_between(F["stop"], loosen),
    }
    liq = {"ticks": 250, "cleared": num(Decimal("64010.0") - 250 * TICK)}
    return {
        "fixture": fixture,
        "trail": trail,
        "lockout": lockout,
        "pending": pending,
        "loosen": loosened,
        "liq": liq,
        "ladder_fixture": ladder_fixture,
    }


def contract_facts(t: dict[str, str]) -> dict[str, object]:
    """Every fact a board quotes, parsed from the plan text; nothing is executed."""
    api, d24, d28 = t["22"], t["24"], t["28"]
    op = api[api.index("  /positions/{positionId}/tpsl:") :]
    op = op[: op.index("\n  /", 1)]
    position = api[api.index("    Position:\n") : api.index("    AggregatePosition:")]
    req = api[api.index("    SetTpSlRequest:") : api.index("    TpSlResult:")]
    res = api[api.index("    TpSlResult:") :]
    end = re.search(r"\n    \w", res[1:])
    res = res[: end.start() + 1] if end else res
    b8 = d28[d28.index("### B8.2") : d28.index("### B8.4")]
    budget = first(r"^\| 4 \| Order submit → ack \| ([^|]+)\|", t["06"], MULTI)
    scr064 = t["14"][t["14"].index("### SCR-064") : t["14"].index("### SCR-065")]
    cmp120 = t["15"][t["15"].index("### CMP-120") : t["15"].index("### CMP-121")]
    return {
        "set_tpsl_present": "operationId: setPositionTpSl" in op,
        "set_tpsl_rbac_positions_write": "permissions: [positions:write]" in op,
        "trail_clear_unsupported": "trail_clear_unsupported" in op,
        "native_stop_required": "native_stop_required" in op,
        "distance_not_percentage": "price distance on Bybit, not a percentage" in op,
        "owner_only_loosen": "Only the owner can loosen a stop" in op,
        "offset_units": re.findall(
            r"\w+", first(r"OffsetUnit:\s*\n\s*type: string\s*\n\s*enum: \[([^\]]+)\]", api)
        ),
        "set_tpsl_fields": re.findall(r"^        (\w+):", req, MULTI),
        "tpsl_result_fields": re.findall(r"^        (\w+):", res, MULTI),
        "position_has_native_stop_present": "native_stop_present:" in position,
        "position_has_trailing_stop": "trailing_stop:" in position,
        "position_has_r_multiple": "r_multiple:" in position,
        "position_lacks_activation_price": "activation_price" not in position,
        "arm_token_names_set_tpsl": "owner's loosened stop on `setPositionTpSl`" in api,
        "sl_loosen_no_grace": "`backups` and `sl_loosen` are no-grace" in api,
        "rule5_tighten_only": "may only ever **tighten** the native stop" in d24,
        "rule5_never_refuses_tighten": "A tightening is never refused by it" in d24,
        "stop_resolution_further": "further from entry, never closer" in d24,
        "trail_distance_not_pct_24": "**price distance, not a percentage**" in d24,
        "only_tighten_binding": "only_tighten: bool = True" in d24,
        "trail_kinds_24": re.findall(
            r'"(\w+)"', first(r"kind: Literal\[(.*?)\]", d24[d24.index("class TrailSpec") :])
        ),
        "internal_trailing_active_price": "trailing_active_price: Px | None" in d24,
        "code_only_rule": "the exchange's `retMsg` never reaches" in d24,
        "b8_states": re.findall(r"^\| `sl\.([a-z_]+)` \| atomic", b8, MULTI),
        "b8_guards": sorted(set(re.findall(r"`(tightens_only|explicit_audited_override)`", b8))),
        "b8_no_public_id": "have no public id yet" in t["23"],
        "budget_4": budget.strip(),
        "scr064_checklist_items": first(r"acceptance checklist:\*\* (.*)$", scr064, MULTI).count(
            "[ ]"
        ),
        "cmp120_modes_15": re.findall(r'"(\w+)"', first(r"mode: (\"[^·]+?)\s*·", cmp120)),
        "cmp120_select_15": "CMP-009 Select" in cmp120,
        "us_algo_008_client_side": "maintained client-side" in t["11"],
        "flow_toast_2s": "auto-confirms after 2s" in t["13"],
    }


def oms_error_codes(d24: str) -> list[str]:
    block = d24[d24.index("class OmsErrorCode(StrEnum):") :]
    block = block[: block.index("```")]
    return re.findall(r"^\s+([A-Z_]+) = ", block, MULTI)


def cite_gates(t: dict[str, str]) -> list[str]:
    bad: list[str] = []
    lines = {k: v.split("\n") for k, v in t.items()}
    CITE_WARN.clear()
    for doc, line_s, want in rows(CITED_TABLE):
        line, doc_lines = int(line_s), lines[doc]
        shift = sum(POINTERS[doc] in ln for ln in doc_lines[: line - 1]) if doc in POINTERS else 0
        if any(0 < n <= len(doc_lines) and want in doc_lines[n - 1] for n in (line, line + shift)):
            continue
        found = [i + 1 for i, ln in enumerate(doc_lines) if want in ln]
        if len(found) == 1:
            CITE_WARN.append(f"`{doc}` :{line} now at :{found[0]} ({want[:40]!r})")
        elif not found:
            bad.append(f"cited text gone: `{doc}` :{line} {want[:40]!r} is nowhere in the file")
        else:
            bad.append(f"cited text ambiguous: `{doc}` :{line} {want[:40]!r} at {found[:4]}")
    return bad


def state_rows(spec: str) -> list[tuple[str, str, str, str]]:
    """(frame, board, class, the rest of the row) for every section 3 state row."""
    return [(m[1], m[2], m[3], m[4]) for m in re.findall(STATE_ROW, section(spec, 3, 4), MULTI)]


def gates(
    files: list[Path], spec: str, facts: dict[str, object], t: dict[str, str], codes: list[str]
) -> list[str]:
    bad: list[str] = []
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    deck = section(spec, 13, 14)
    header = spec[: spec.index("\n## 0.")]
    bad += [f"spec: C-2.6 sentence missing: {s[:48]}" for s in STOP_SENTENCES if s not in spec]
    bad += [
        f"spec section 13: banned word in UI copy: {m.group(0)!r}"
        for p in BANNED_COPY
        for m in re.finditer(p, deck)
    ]
    deck_strings = " ".join(re.findall(r'"([^"]+)"', deck))
    bad += [
        f"spec section 13: raw error-code token in UI copy: {c}"
        for c in codes
        if re.search(rf"\b{c}\b", deck_strings)
    ]
    for key, cell in re.findall(REASON_RE, deck, MULTI):
        if not key.startswith("rbac."):
            continue  # registered state strings are cited verbatim, never shortened here
        for s in re.findall(r'"([^"]+)"', cell):
            if len(s) > 60 or not s.endswith(".") or re.search(r"\d", s):
                bad.append(
                    f"T2 reason {key}: {len(s)} chars; stop {s.endswith('.')}; "
                    f"digit {bool(re.search(r'[0-9]', s))}"
                )
    stale = first(r'^\| `e32\.stale\.entry_off` +\| "([^"]+)"', deck, MULTI)
    if stale == "MISSING":
        bad.append("spec section 13: e32.stale.entry_off (E17-D01's form instantiated) is missing")
    elif len(stale.replace("{message}", "")) > 60 or "still works." not in stale:
        bad.append(f"spec section 13: e32.stale.entry_off fixed text {len(stale) - 9} chars / form")
    for frame, board, cls, rest in state_rows(spec):
        drawn = "not drawn" not in board
        if drawn and not re.fullmatch(r"\d\d", board):
            bad.append(f"spec section 3: {frame} has no board number ({board!r})")
        if (
            "pending" in frame
            and HELD_NOW not in rest
            and "`sltp.pending.held`" not in rest
            and "row 11" not in rest
            and "row 12" not in rest
        ):
            bad.append(
                f"spec section 3: {frame} is a pending frame that does not name the stop in force"
            )
        if (
            "pending" in frame
            and re.search(r"✓|\bapplied\b(?! until)", rest)
            and 'never "applied"' not in rest
        ):
            bad.append(f"spec section 3: {frame} is a pending frame that reads as applied")
        if re.search(r"\bLIVE\b", rest) and not re.search(r"\barm|step-up|DEMO|never|not\b", rest):
            bad.append(f"spec section 3: {frame} draws LIVE with no arm or step-up in the frame")
        if "T2" in cls and "opacity.disabled" in rest:
            bad.append(f"spec section 3: {frame} is T2 and dims (over-conversion)")
        if "validity" in cls and re.search(r"lock glyph|CMP-079", rest):
            bad.append(
                f"spec section 3: {frame} is the validity look with a lock (over-conversion)"
            )
    cls_table = section(spec, 1, 2)
    for line in cls_table.split("\n"):
        if not line.startswith("| ") or "**validity look**" not in line:
            continue
        if re.search(r"lock glyph|CMP-079|`rbac\.", line):
            bad.append(
                "spec section 1.3: a validity-look row carries a lock, CMP-079 or an rbac key"
            )
    if not re.search(
        r"^\| \d+ +\| `only-tighten revert`[^\n]*`sltp\.trail\.refused`", section(spec, 4, 5), MULTI
    ):
        bad.append("spec section 4: the only-tighten revert row does not bind sltp.trail.refused")
    bad += [f"spec header: merge sha missing: {s[:9]}" for s in MERGE_SHAS if s not in header]
    bad += cite_gates(t)
    texts = [("spec", spec)] + [(f.name, f.read_text(encoding="utf-8")) for f in files if f != SPEC]
    for name, txt in texts:
        for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", txt))):
            if f"**{r}" not in constitution:
                bad.append(f"{name}: dangling rule id {r}")
        for c in sorted(set(re.findall(r"\b(?:CMP|SCR)-\d{3}\b", txt))):
            if f"### {c} " not in t["15" if c.startswith("CMP") else "14"]:
                bad.append(f"{name}: no catalogue heading for {c}")
    for f in files:
        txt = f.read_text(encoding="utf-8")
        bad += [f"{f.name}: forbidden text {p}" for p in FORBIDDEN if re.search(p, txt)]
        if f not in (SPEC, HANDOFF) and re.search(CLOSING, txt, re.IGNORECASE):
            bad.append(f"{f.name}: a closing keyword (text-first: Refs + Partial only)")
    return bad


def flatten(d: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


def counts(spec: str, handoff: str) -> dict[str, object]:
    s0 = section(spec, 0, 1)
    rows3 = state_rows(spec)
    numbers: dict[str, object] = {k: count(p, spec) for k, p in COUNT_RE.items()}
    numbers["boards"] = count(r"^\| \d\d +\| `E32-D05 / ", s0)
    numbers["light_twins"] = count(r"^\| \d\d +\| `E32-D05 / [^`]+-light`", s0)
    row01 = first(r"^(\| 01 +\|[^\n]*)", s0, MULTI)
    numbers["key_frames"] = int("`Key —" in row01) + int("`Fixture" in row01)
    numbers["frames_064_rows"] = len(rows3)
    numbers["frames_064"] = sum("not drawn" not in b for _, b, _, _ in rows3)
    numbers["loosen_frames"] = sum("loosen ·" in f and "not drawn" not in b for f, b, _, _ in rows3)
    numbers["frames_120"] = count(r"^\| \d+ +\| `[a-z]", section(spec, 4, 5))
    numbers["frames_total"] = (
        int(str(numbers["frames_064"]))
        + int(str(numbers["frames_120"]))
        + int(str(numbers["key_frames"]))
    )
    deck = section(spec, 13, 14)
    deck_rows = [m for m in re.findall(DECK_RE, deck, MULTI) if m[0] != "`Key`"]
    numbers["deck_rows"] = len(deck_rows)
    numbers["deck_new"] = sum(src.startswith("new") for _, _, src in deck_rows)
    numbers["reason_keys"] = len(re.findall(REASON_RE, deck, MULTI))
    numbers["checklist_items"] = count(r"^\| 14:1504 ", section(spec, 15, 16))
    numbers["handoff_blocks"] = count(r"^## Handoff checklist", handoff)
    numbers["cites_pinned"] = len(rows(CITED_TABLE))
    numbers["gestures"] = count(
        r"^\| (?:select|drag|drop|switch|release|abort) ", section(spec, 9, 10)
    )
    numbers["rows"] = dict(ROWS)
    return numbers


def mutations() -> list[tuple[str, Callable[[str], str], str]]:
    def swap(a: str, b: str) -> Callable[[str], str]:
        return lambda s: s.replace(a, b, 1)

    def sub(pattern: str, repl: str) -> Callable[[str], str]:
        return lambda s: re.sub(pattern, repl, s, count=1, flags=MULTI)

    return [
        (
            "banned",
            sub(
                r'^(\| `trail\.only_tighten` +\| )"Only tightens:',
                r'\1"Only tightens (app-managed):',
            ),
            "banned word",
        ),
        (
            "reason-long",
            sub(
                r'^(\| `rbac\.owner_only` +\| )"Only the owner can loosen a stop\."',
                r'\1"Only the owner can loosen a stop, and only after the step-up has been '
                r'answered."',
            ),
            "T2 reason",
        ),
        ("rule-id", swap("(C-4.4; BQ-2)", "(C-4.4; C-99.9; BQ-2)"), "dangling rule id"),
        (
            "cmp-id",
            swap(
                "239 (the `· disconnected` inset's marker)",
                "239, CMP-999 (the `· disconnected` inset's marker)",
            ),
            "no catalogue heading",
        ),
        (
            "no-stop",
            swap("never empty at rest, no clear glyph, no toggle", "editable at rest"),
            "C-2.6 sentence",
        ),
        (
            "sha",
            swap(
                "baccf724a1fa3ad66f9333e440a7f5e8668b6eff",
                "baccf724a1fa3ad66f9333e440a7f5e8668b6eg",
            ),
            "merge sha missing",
        ),
        (
            "live",
            sub(r"^(\| 1 +\| `loading` +\| 04 +\| status +\| )the layout", r"\1the LIVE layout"),
            "draws LIVE",
        ),
        (
            "held",
            lambda s: s.replace(
                '+ `sltp.pending.held` "Held by Bybit now: 63,900.0."; after the 200',
                "; after the 200",
                1,
            )
            .replace("`sltp.pending.held` under it", "the line under it", 1)
            .replace(
                'reads "Held by Bybit now: 63,900.0 — last confirmed by the position read."',
                "reads the read's confirmation",
                1,
            ),
            "stop in force",
        ),
        (
            "optimistic",
            sub(
                r"^(\| 11 +\| `pending-acknowledgement` +\| 04 +\| status +\| )Apply on a tighten",
                r"\1✓ applied: Apply on a tighten",
            ),
            "reads as applied",
        ),
        (
            "over-convert",
            swap(
                "the CMP-027 summary on a press, Apply at `opacity.disabled`; `sltp.applied.none`",
                "the CMP-027 summary on a press, a lock glyph, Apply at `opacity.disabled`; "
                "`sltp.applied.none`",
            ),
            "validity-look row carries",
        ),
        (
            "stale-long",
            sub(
                r'^(\| `e32\.stale\.entry_off` +\| "Order entry off — \{message\}\. )'
                r"Tightening the stop still works\.",
                r"\1Tightening the stop and attaching one still work as before.",
            ),
            "e32.stale.entry_off",
        ),
        (
            "revert",
            swap(
                "`sltp.trail.refused` (distance) · `sltp.trail.refused` (activation)",
                "the distance line · the activation line",
            ),
            "only-tighten revert",
        ),
    ]


def main(argv: list[str]) -> int:
    extra = [Path(a) for a in argv[argv.index("--extra") + 1 :]] if "--extra" in argv else []
    themes = {k: load_theme(k) for k in THEMES}
    t = {k: (PLAN / p).read_text(encoding="utf-8") for k, p in DOC_NAMES.items()}
    t.update({k: (DESIGN / p).read_text(encoding="utf-8") for k, p in DESIGN_DOCS.items()})
    pairs_text = (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8")
    registered = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_text))
    out = ["## 1. Measured matrix (fg on bg | role | dark / light / hc | verdict | pairs | where)"]
    matrix: list[dict[str, object]] = []
    fails = proposed = gated = 0
    badge_7 = True
    for element, fg, bg, role in rows(PAIRS_TABLE):
        ratios = {th: contrast(resolve(tk, fg), resolve(tk, bg)) for th, tk in themes.items()}
        bar = BAR.get(role)
        if role == "aaa-target":
            badge_7 = all(r >= 7.0 for r in ratios.values())
            verdict = "7:1 met" if badge_7 else "7:1 not met — shortfall stated (spec 14)"
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
        out.append(
            f"{fg} on {bg} | {role} | {' / '.join(show(r) for r in ratios.values())} | "
            f"{verdict} | {reg} | {element}"
        )
    composite: dict[str, float] = {}
    for th, tk in themes.items():
        over = resolve(tk, "color.surface.overlay")
        label = blend(resolve(tk, "color.text.on-action"), over, 0.45)
        fill = blend(resolve(tk, "color.action.primary.default"), over, 0.45)
        composite[th] = round(contrast(label, fill), 2)
    out.append(
        f"validity composite (Apply at opacity.disabled over the overlay; not gated): {composite}"
    )
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    missing = [tok for tok in BINDINGS if resolve(themes["dark"], tok) == "MISSING"]
    out += [
        f"{tok} | {' / '.join(resolve(tk, tok)[:40] for tk in themes.values())}" for tok in BINDINGS
    ]
    precedents = (
        "".join((DESIGN / p).read_text(encoding="utf-8") for p in GLYPH_PRECEDENTS) + t["15"]
    )
    glyphs_new = [g for g in GLYPHS if f"`{g}`" not in precedents]
    out.append(
        f"MISSING tokens: {missing} (gated) | DS requests: {list(DS_REQUESTS)} | "
        f"glyph names no merged spec names yet: {glyphs_new}"
    )
    facts = contract_facts(t)
    codes = oms_error_codes(t["24"])
    out.append("\n## 3-4. pairs.mjs status is per row above; contract facts parsed from text:")
    out.append(json.dumps(facts, ensure_ascii=False))
    numbers = arithmetic()
    out.append(
        "\n## 5. Trail arithmetic (Decimal, tick 0.10): " + json.dumps(numbers, ensure_ascii=False)
    )
    spec = SPEC.read_text(encoding="utf-8")
    handoff = HANDOFF.read_text(encoding="utf-8") if HANDOFF.exists() else ""
    bad = gates([SPEC, HANDOFF, *extra], spec, facts, t, codes)
    bad += [f"token MISSING: {m}" for m in missing]
    for key in (
        "set_tpsl_present",
        "trail_clear_unsupported",
        "native_stop_required",
        "rule5_tighten_only",
        "only_tighten_binding",
    ):
        if not facts[key]:
            bad.append(f"contract fact false: {key}")
    if not facts["position_lacks_activation_price"]:
        CITE_WARN.append("gap closed — `22` Position now carries activation_price: update D05-G4")
    ok = (
        "OK — the C-2.6 sentences present; no banned word or raw error-code token in the copy "
        "deck; every T2 reason within 60 characters; every pending frame names the stop in force "
        "and never reads as applied; no LIVE frame without the arm or the step-up; no private "
        "path; every C / CMP / SCR id "
        "exists; every merge sha in the header; every cited text exists"
    )
    out.append("\n## 6. String gates: " + (ok if not bad else "\n".join("FAIL " + b for b in bad)))
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    numbers.update(counts(spec, handoff))
    numbers.update(
        {"pairs_rows": gated, "pairs_registered": gated - proposed, "pairs_proposed": proposed}
    )
    numbers.update({"pairs_fail": fails, "badge_7_1": badge_7, "composite": composite})
    numbers["opacity_disabled"] = float(resolve(themes["dark"], "opacity.disabled"))
    m = re.findall(r"p95 < (\d+)ms", str(facts["budget_4"]))
    numbers["ms"] = {"ack_demo_p95": int(m[0]), "ack_live_p95": int(m[1]), "confirm_gate": 400}
    b8_states = facts["b8_states"]
    if not isinstance(b8_states, list):
        raise TypeError("b8_states")
    numbers.update(
        {"missing_tokens": len(missing), "glyphs_new": len(glyphs_new), "b8_states": len(b8_states)}
    )
    flat = flatten(numbers)
    if "--check" in argv:
        for key, val in re.findall(r"<!-- audit:([a-z0-9_.-]+)=([^ ]+) -->", spec):
            have = flat.get(key)
            same = str(have).lower() == val.lower()
            try:
                same = same or float(str(have)) == float(val)
            except ValueError:
                pass
            if have is None or not same:
                bad.append(f"marker audit:{key}={val} vs tool {have}")
        out.append(
            "markers: " + ("clean" if not any(b.startswith("marker") for b in bad) else "MISMATCH")
        )
    if "--self-test" in argv:
        for name, fn, expect in mutations():
            mutated = fn(spec)
            if mutated == spec:
                bad.append(f"self-test {name}: the mutation did not apply")
                continue
            hits = [b for b in gates([], mutated, facts, t, codes) if expect in b]
            base = [b for b in gates([], spec, facts, t, codes) if expect in b]
            if len(hits) - len(base) != 1:
                bad.append(
                    f"self-test {name}: expected exactly one new {expect!r} FAIL, "
                    f"got {len(hits) - len(base)}"
                )
        out.append(
            "self-test: "
            + (
                "every mutation caught once"
                if not any(b.startswith("self-test") for b in bad)
                else "FAILED"
            )
        )
    out.append("\n## 7. Counts: " + json.dumps(numbers, ensure_ascii=False))
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
