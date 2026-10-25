#!/usr/bin/env python3
"""E33-D02 algo-builders audit: measured matrix, token bindings, arithmetic, plan facts, gates.

Standalone, offline, stdlib only; it executes no repo code. It reads the token JSON, `pairs.mjs`,
`22`, `24`, `14`, the E33-D01 memo and the spec AS TEXT and prints, with a source label on every
row: (1) the WCAG 2.x ratio of every fg / bg pair the three builders render in dark / light /
high-contrast (`themes.json` layering) against the role's bar; `rejected-*`, `decorative` and
`aaa-target` rows are reported, never gated; (2) every token the spec binds, resolved or MISSING;
(3) the pure arithmetic the boards quote (the TWAP schedule, the iceberg floor, the chase bound and
the rate projections); (4) the plan facts the frames quote, parsed from text (`22` bounds vs `24`
defaults, the `24` defaults the frames override, the two catalogue validation strings, the three
memo caveats); (5) the copy gates on the spec, the reduce-only CMP-158 sentence, every drawn
override and wire difference named in D02-C7, every reused reason over E09-D09's 60 characters
named in a C-row, and every `file:line` the spec cites by number (the cite rule: the fragment
searched by content; another single line is a WARN, none or several lines a FAIL); (6) the counts
the boards and the draft quote. `--selftest` mutates the cite rule (an ambiguous, a gone, a
drifted and an exact fragment) and fails unless each gives its verdict. Exit 1 on a gated FAIL or
a failed gate.

Usage: python3 -I docs/design/_tools/e33_d02_algo_builders_audit.py [--json] [--check]
       [--selftest] [--extra FILE ...]
"""

from __future__ import annotations

import json
import re
import sys
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
SPEC = ROOT / "docs" / "design" / "E33" / "E33-D02.md"
MEMO = ROOT / "docs" / "design" / "research" / "e33-emulated-algo-trust.md"
CAT14 = ROOT / "docs" / "plan" / "14-screens-catalogue.md"
API22 = ROOT / "docs" / "plan" / "22-api-openapi.yaml"
DOC24 = ROOT / "docs" / "plan" / "24-internal-schemas.md"
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES: dict[str, tuple[str, ...]] = {
    "dark": (PRIM, DARK),
    "light": (PRIM, DARK, LIGHT),
    "high-contrast": (PRIM, DARK, HC),
}
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}
MULTI = re.MULTILINE


class Facts(TypedDict):
    bounds_22: dict[str, dict[str, str]]
    defaults_24: dict[str, dict[str, str]]
    overrides_24: dict[str, dict[str, str]]
    catalogue_strings: list[str]
    caveats: dict[str, str]
    help_text: str
    link_down_in_memo: bool
    algo_kind: str


BOUND = r"(minimum|maximum|default): ([^,}\s]+)"
# `24` defaults the frames override (D02-C7): field -> the drawn default; `24`'s own is parsed.
DRAWN_24 = {
    "catch_up": "proportional",
    "final_market_sweep": "leave as limit (no sweep)",
    "reprice_interval_ms": "500",
    "max_repricings": "120 (derived: timeout / interval)",
}
# Drawn values `22` cannot carry (D02-C7): AlgoSpec sub-block -> field -> what the frames draw.
DRAWN_VS_22 = {"chase": {"offset_ticks": "signed (the -1 tick example, BQ-11)"}}
# E09-D09 :85's reason rule: one sentence, at most 60 characters, a full stop, never data.
REASON_MAX = 60
# Plan lines the spec cites by number at its pinned `origin/main` (`file:line` -> a fragment that
# ends on that line; re-pinned by content at the round-1 approval fold: `24` +3 from PR 4358 /
# PR 4319). `14` lines after SCR-066 :1545 sit lower by the pointer lines this PR inserts above
# them: a `14` cite's own line is the cited number plus those pointer lines (a coordinate change,
# not a window). The cite rule searches the fragment by content over the whole file: found only on
# the cited line passes; found on exactly one other line is a WARN naming it (re-pin at the next
# text touch); found nowhere is a FAIL; found on more than one line is a FAIL "ambiguous: N
# matches" (the fix is a longer fragment, never a re-pin). There is no distance limit. Where two
# table rows are identical, the fragment carries the rows above it, joined by "\n", and the match
# line is the line where the fragment ends.
# B4 to B7 `completing` (D03-A13: the finishing Cancel is T2 `algo.finishing`): the B5, B6 and
# B7 rows are identical, so each fragment carries the rows above it up to a distinct one.
_DONE = "| `completing` | `CHILDREN_TERMINAL` |"
_P_RESUME = "| `paused` | `RESUME` | — | `reconciling` | — | — |"
_P_CANCEL = "| `paused` | `USER_CANCEL` | — | `cancelling` | — | — |"
_B5_COOL = "| `cooling_down` | `COOLDOWN_DUE` | — | `submitting_slice` | — | — |"
_B6_HELD = "| `price_blocked` | _always_ | `abort_on_price_limit` | `cancelling` | — | — |"
_W_PAUSE = "| `working` | `USER_PAUSE` | — | `paused` | — | — |"
_DEFER = '  "onUnhandled": "defer",'


def _rows(*lines: str) -> str:
    return "\n".join(lines)


CITED: tuple[tuple[str, int, str], ...] = (
    ("14", 1540, "Slices of 0.0004 BTC are below the minimum"),
    ("14", 1546, "algo.twap_previewed"),
    ("14", 1552, "Visible size must be at least the minimum lot"),
    ("14", 1555, "running state announces refreshes politely at most once every 5 s"),
    ("14", 1557, "algo.iceberg_previewed"),
    ("14", 1563, "max chase distance > offset"),
    ("14", 1564, "stops and notifies"),
    ("14", 1567, "repriced 7 times"),
    ("14", 1568, "refuses configurations projected to exceed"),
    ("14", 1699, "never scrolled away or covered by a modal"),
    ("22", 263, "View-as session (read-only, #3085)"),
    ("22", 265, "AD-F03 of the E42 threat model"),
    ("22", 281, "**Read-only.**"),
    ("22", 291, "**Protective writes (C-2.6).**"),
    ("22", 6258, "twapExit:"),
    ("22", 17975, "offset_ticks: { type: integer, minimum: 0"),
    ("22", 17976, "max_chases: { type: integer"),
    ("22", 17978, "repricing_interval_ms: { type: integer"),
    ("23", 898, "`algo:{algo_id}`"),
    ("24", 2091, "### 8.8 Safety invariant"),
    ("24", 2730, "class AlgoState(BaseModel):"),
    ("24", 2826, "catch_up: Literal["),
    ("24", 2832, "`final_market_sweep` (default `true`)"),
    ("24", 2843, "    offset_ticks: int = 0"),
    ("24", 2845, "reprice_interval_ms: int = 200"),
    ("24", 2847, "max_repricings: int = 200"),
    ("28", 3015, _rows("| `settling_a` | `*` | — | _(internal)_ | `defer` | — |", _DONE)),
    ("28", 3019, "`LEG_B_FILL` *(Corrected 2026-10-10, #2204, OC-03)* | — | _(internal)_ |"),
    # B5's root defers what a state does not take (the cooldown's Pause and Cancel, D03-C17).
    ("28", 3099, _rows('"id": "iceberg",', '  "actionErrorPolicy": "rollback",', _DEFER)),
    ("28", 3371, "| `working` | `CHILD_CANCELLED` |"),
    (
        "28",
        3373,
        _rows(
            "`CHILD_CANCELLED` | — | `waiting_refill` | — | — |",
            _W_PAUSE,
            "| `working` | `WS_DISCONNECT` |",
        ),
    ),
    ("28", 3384, "| `cooling_down` | `COOLDOWN_DUE` | — | `submitting_slice` |"),
    ("28", 3387, _rows(_B5_COOL, _P_RESUME, _P_CANCEL, _DONE)),
    ("28", 3725, "| `armed` | `WS_DISCONNECT` |"),
    ("28", 3730, "| `price_blocked` | `PRICE_OK` |"),
    ("28", 3734, "| `price_blocked` | _always_ |"),
    ("28", 3735, _rows(_B6_HELD, "| `paused` | `RESUME` |")),
    ("28", 3737, _rows(_B6_HELD, _P_RESUME, _P_CANCEL, _DONE)),
    ("28", 4088, "| `working` | `RATE_BUDGET_EXHAUSTED` |"),
    (
        "28",
        4090,
        _rows(
            "`RATE_BUDGET_EXHAUSTED` | — | `paused` | — | — |",
            _W_PAUSE,
            "| `working` | `WS_DISCONNECT` |",
        ),
    ),
    ("28", 4093, "| `bound_exceeded` | _always_ | `on_timeout_is_market` |"),
    ("28", 4095, "| `bound_exceeded` | _always_ | — | `parked` |"),
    ("28", 4099, "| `parked` | `CHILD_FILLED` |"),
    ("28", 4100, "| `parked` | `USER_CANCEL` |"),
    ("28", 4103, _rows("| `paused` | `RESUME` | — | `working` | — | — |", _P_CANCEL, _DONE)),
)
CITE_WARN: list[str] = []
PLAN = {
    "14": CAT14,
    "22": API22,
    "23": ROOT / "docs" / "plan" / "23-ws-protocol.md",
    "24": DOC24,
    "28": ROOT / "docs" / "plan" / "28-statechart-catalogue.md",
}
POINTER = "E33-D02.md](../design/E33/E33-D02.md)"
# Private paths and hosts that never belong in a public file: generic patterns only, no personal
# word and no hostname, whole or split; the path literal is split so this file never holds it.
FORBIDDEN = (
    r"/(?:ho[m]e|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
)
# Words the memo retires from user-facing copy (SC-6, F6, F7, F11; the ticket's Security notes);
# the kill switch's own typed word FREEZE passes (upper case only). Checked on spec section 8.
BANNED_COPY = (
    r"app-managed",
    r"client-side",
    r"client-of-exchange-side",
    r"backend disconnects",
    r"Bybit has no",
    r"\bunlimited\b",
    r"\bbacktest",
    r"\bfreeze\b",
    r"\bmid\b",
)
TAG_NAME = "Emulated — run by CandleViewer, not Bybit"
LINK_DOWN = "Can't start algos: CandleViewer's live link to Bybit is down"
# element | fg | bg | role -- every pair the three builders draw (spec section 10, rows in order).
PAIRS_TABLE = """
dialog title, body text, field values | color.text.primary | color.surface.overlay | text
labels, read-outs, validity and T2 reasons | color.text.secondary | color.surface.overlay | text
captions, PROPOSED stamps | color.text.tertiary | color.surface.overlay | text
T2 label and lock glyph on the control | color.text.tertiary | color.surface.raised | text
T2 reason beside a raised control | color.text.secondary | color.surface.raised | text
Advanced summary, table body, Emulated tag | color.text.primary | color.surface.raised | text
Emulated tag word (secondary) | color.text.secondary | color.surface.raised | text
DEMO badge word (AA bar) | color.text.primary | color.surface.raised | text
DEMO badge word (the 7:1 target) | color.text.primary | color.surface.raised | aaa-target
DEMO dot and border on the badge | color.env.demo | color.surface.raised | non-text
DEMO band rule on the app chrome | color.env.demo | color.surface.app | non-text
CMP-158 algo sentence, CMP-227 word | color.text.primary | color.status.info.subtle | text
CMP-158 glyph | color.status.info.strong | color.status.info.subtle | non-text
over-budget reason, Paused words | color.text.primary | color.status.warning.subtle | text
over-budget second line | color.text.secondary | color.status.warning.subtle | text
warning glyph | color.status.warning.strong | color.status.warning.subtle | non-text
T4 refusal line, Halted and Failed words | color.text.primary | color.status.danger.subtle | text
T4 second line | color.text.secondary | color.status.danger.subtle | text
danger glyph | color.status.danger.strong | color.status.danger.subtle | non-text
validation summary boundary | color.status.danger.default | color.surface.overlay | non-text
Completed word | color.text.primary | color.status.success.subtle | text
success glyph | color.status.success.strong | color.status.success.subtle | non-text
Running and Starting words on the neutral pill | color.text.primary | color.surface.hover | text
progress bar fill on its track | color.action.primary.default | color.surface.sunken | non-text
schedule table zebra row text | color.text.primary | color.surface.canvas | text
schedule table secondary cells | color.text.secondary | color.surface.canvas | text
stale rows (case 1) | color.data-confidence.stale.text | color.data-confidence.stale.surface | text
Start button label | color.text.on-action | color.action.primary.default | text
Cancel and flatten confirm button | color.text.on-action | color.status.danger.default | text
focus ring on the overlay | color.focus.ring | color.surface.overlay | non-text
focus ring on a raised control | color.focus.ring | color.surface.raised | non-text
the field well boundary | color.text.tertiary | color.surface.app | non-text
a T2 label never uses text.disabled | color.text.disabled | color.surface.raised | rejected-text
the hairline on a card | color.border.default | color.surface.overlay | decorative
"""
BINDINGS = (
    "color.surface.overlay",
    "color.surface.raised",
    "color.surface.canvas",
    "color.surface.app",
    "color.surface.sunken",
    "color.surface.hover",
    "color.border.default",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.on-action",
    "color.status.info.subtle",
    "color.status.info.strong",
    "color.status.info.default",
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
    "elevation.4",
    "radius.lg",
    "radius.control",
    "radius.pill",
    "type.ui.heading-sm",
    "type.ui.body",
    "type.ui.caption",
    "type.ui.label",
    "type.num.base",
    "space.inset.sm",
    "space.inset.md",
    "space.inset.lg",
    "space.stack.sm",
    "space.dialog.padding",
    "space.row.height.compact",
    "space.row.height.comfortable",
    "size.control.height",
    "color.track",
)
PRIMITIVE_ALIAS = {"elevation.4": "elevation.dialog"}


def rows(table: str) -> list[list[str]]:
    return [[c.strip() for c in ln.split(" | ")] for ln in table.strip("\n").splitlines() if ln]


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


def luminance(hex6: str) -> float:
    r, g, b = (int(hex6.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def blend(fg: str, bg: str, alpha: float) -> str:
    f = [int(fg.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    g = [int(bg.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(
        f"{round(a * alpha + c * (1 - alpha)):02X}" for a, c in zip(f, g, strict=True)
    )


def show(ratio: float) -> str:
    near = any(abs(ratio - bar) < 0.005 for bar in (3.0, 4.5, 7.0))
    return f"{ratio:.4f}" if near else f"{ratio:.2f}"


def dec(x: str | int) -> Decimal:
    return Decimal(str(x))


def arithmetic() -> dict[str, dict[str, object]]:
    """The numbers the boards quote: E30-D02 section 5.4 fixture, the memo's section 2 examples."""
    tick, step = dec("0.10"), dec("0.001")
    total, minutes, slices, cap, floor_slices = dec("2.000"), 30, 10, 450, 2000
    nominal, seconds = (total / slices).quantize(step, ROUND_FLOOR), minutes * 60
    dense = min(cap, seconds)
    # The dense schedule and the catalogue's 0.0004 example are reachable configurations of their
    # own: the dense total divides evenly over 450 slices (no remainder row), and 0.180 BTC over
    # 450 slices reproduces the catalogue string inside slices 2-450 and the 1 s floor.
    dense_total, min_lot_total = dec("1.800"), dec("0.180")
    dense_qty = (dense_total / dense).quantize(step, ROUND_FLOOR)
    twap: dict[str, object] = {
        "total": float(total), "minutes": minutes, "slices": slices, "nominal": float(nominal),
        "lo": float(nominal * dec("0.80")), "hi": float(nominal * dec("1.20")),
        "interval_s": seconds // slices, "jitter_s": seconds // slices // 4,
        "derived_60s": seconds // 60, "cap": cap, "dense_slices": dense,
        "dense_total": float(dense_total), "dense_qty": float(dense_qty),
        "dense_remainder": float(dense_total - dense_qty * dense),
        "dense_interval_s": seconds // dense, "dense_jitter_s": seconds // dense // 4,
        "dense_middle": dense - 2,
        "min_lot_total": float(min_lot_total), "min_lot_slices": cap,
        "min_lot_qty": float((min_lot_total / cap).normalize()),
        "floor_slices": floor_slices, "floor_interval_s": float(dec(seconds) / floor_slices),
        "floor_max": min(cap, seconds), "window_end_left": 0.40, "worst_limit": 64250.0,
        "min_interval_ms": 1000,
    }  # fmt: skip
    ice_total, visible = dec(5), dec("0.25")
    iceberg: dict[str, object] = {
        "total": float(ice_total), "visible": float(visible),
        "floor": float((ice_total / 360).quantize(step, ROUND_CEILING)),
        "pct_shown": float((visible / ice_total * 100).normalize()),
        "slices_about": int(ice_total / visible), "lo": float(visible * dec("0.80")),
        "hi": float(visible * dec("1.20")), "cap_orders": cap, "half": float(ice_total / 2),
        "refill_ms": 250, "refill_jitter_ms": 250,
    }  # fmt: skip
    start, ticks, headroom = dec("64010.0"), 20, 2
    per_min = {ms: 60000 // ms for ms in (200, 250, 500)}
    chase: dict[str, object] = {
        "start": float(start), "ticks": ticks, "worst": float(start + ticks * tick),
        "pct": float((ticks * tick / start * 100).quantize(dec("0.001"))), "timeout_s": 60,
        "interval_ms": 500, "floor_ms": 200, "repricings": 60000 // 500, "repricings_cap": 500,
        "per_min": {str(k): v for k, v in per_min.items()},
        "per_s": {str(k): v // 60 for k, v in per_min.items()}, "headroom_per_s": headroom,
        "budget_per_s": 4, "over_per_s": per_min[200] // 60,
        "nearest_ms": next(ms for ms in range(200, 10001, 50) if 1000 / ms <= headroom),
        "offset_price": float(start - tick), "fill_price": 64004.0, "repriced": 7, "drift_ticks": 3,
    }  # fmt: skip
    fixture: dict[str, object] = {
        "tick": float(tick), "step": float(step), "min_qty": 0.001, "min_notional": 5,
    }  # fmt: skip
    return {"fixture": fixture, "twap": twap, "iceberg": iceberg, "chase": chase}


def plan_facts() -> Facts:
    """`22` AlgoSpec bounds vs `24` defaults; the catalogue strings; the memo's caveats (text)."""
    api = API22.read_text(encoding="utf-8")
    block = api[api.index("    AlgoSpec:") :]
    end = re.search(r"\n    [A-Z][A-Za-z]*:", block[20:])
    block = block[: end.start() + 20] if end else block
    bounds: dict[str, dict[str, str]] = {}
    for sub in ("iceberg", "twap", "chase"):
        seg = block[block.index(f"        {sub}:") :]
        nxt = re.search(r"\n        [a-z]+:", seg[1:])
        seg = seg[: nxt.start() + 1] if nxt else seg
        bounds[sub] = {
            m[1]: ", ".join(f"{k} {v}" for k, v in re.findall(BOUND, m[2]))
            for m in re.finditer(r"(\w+):\s*\{([^{}]*)\}", seg)
        }
    doc = DOC24.read_text(encoding="utf-8")
    defaults: dict[str, dict[str, str]] = {}
    for cls in ("IcebergParams", "TwapParams", "ChaseParams"):
        body = doc[doc.index(f"class {cls}(BaseModel):") :]
        body = body[: body.index("```")]
        field = r"^\s+(\w+):\s*[^=#\n]+?(?:=\s*([^#\n]+))?\s*(?:#.*)?$"
        defaults[cls] = {
            m[1]: (m[2] or "required").strip() for m in re.finditer(field, body, MULTI)
        }
    cat = CAT14.read_text(encoding="utf-8")
    memo = MEMO.read_text(encoding="utf-8")
    sweep = re.search(r"`final_market_sweep` \(default `(\w+)`\)", doc)
    overrides = {
        "catch_up": {
            "24": defaults["TwapParams"].get("catch_up", "MISSING"),
            "drawn": DRAWN_24["catch_up"],
        },
        "final_market_sweep": {
            "24": f"{sweep.group(1)} (prose, not in TwapParams)" if sweep else "MISSING",
            "drawn": DRAWN_24["final_market_sweep"],
        },
    }
    for name in ("reprice_interval_ms", "max_repricings"):
        overrides[name] = {
            "24": defaults["ChaseParams"].get(name, "MISSING"),
            "drawn": DRAWN_24[name],
        }
    caveats: dict[str, str] = {}
    for k in ("TWAP", "Iceberg", "Chase"):
        m = re.search(rf"- \*\*{k}:\*\* \"(.+?)\"\n", memo, re.DOTALL)
        caveats[k] = " ".join(m.group(1).split()) if m else "MISSING"
    help_m = re.search(r"\*\*Help\s+text:\*\* \"(.+?)\"", memo, re.DOTALL)
    kind = re.search(r"AlgoKind:\s*\{[^}]*enum: \[([^\]]+)\]", api, re.DOTALL)
    return Facts(
        bounds_22=bounds,
        defaults_24=defaults,
        overrides_24=overrides,
        catalogue_strings=re.findall(r'"(Slices of [^"]+|Visible size must [^"]+)"', cat),
        caveats=caveats,
        help_text=" ".join(help_m.group(1).split()) if help_m else "MISSING",
        link_down_in_memo=LINK_DOWN in memo,
        algo_kind=kind.group(1) if kind else "MISSING",
    )


def cite_hits(text: str, want: str) -> list[int]:
    """The distinct lines on which `want` ends, searched by content over the whole file."""
    hits: set[int] = set()
    i = text.find(want)
    while i >= 0:
        hits.add(text.count("\n", 0, i + len(want) - 1) + 1)
        i = text.find(want, i + 1)
    return sorted(hits)


def cited_lines(
    cited: tuple[tuple[str, int, str], ...] = CITED, warn: list[str] | None = None
) -> list[str]:
    """The cite rule over every `file:line` the spec cites: the fragment found only on the cited
    line passes; on exactly one other line, a WARN naming it (re-pinned at the next text touch);
    nowhere, a FAIL; on more than one line, a FAIL "ambiguous: N matches" (lengthen the fragment,
    never re-pin). No window, no distance limit; `check_rule_refs` stays the hard gate for rule
    ids. Returns the FAILs; the WARNs go to `warn` (CITE_WARN by default)."""
    out: list[str] = []
    warns = CITE_WARN if warn is None else warn
    warns.clear()
    texts = {k: PLAN[k].read_text(encoding="utf-8") for k in PLAN}
    for doc, line, want in cited:
        text = texts[doc]
        shift = 0
        if doc == "14":
            shift = sum(POINTER in ln for ln in text.split("\n")[: line - 1])
        hits, own, short = cite_hits(text, want), line + shift, want.split("\n")[-1][:40]
        if not hits:
            out.append(f"cited text gone: `{doc}` :{line} {short!r} is nowhere in the file")
        elif len(hits) > 1:
            out.append(
                f"cited text ambiguous: {len(hits)} matches: `{doc}` :{line} {short!r} on lines "
                f"{', '.join(map(str, hits))} — lengthen the fragment, never re-pin"
            )
        elif hits[0] != own:
            warns.append(f"`{doc}` :{line} now at :{hits[0]} ({short!r})")
    return out


def selftest() -> list[str]:
    """Mutations of the cite rule: each must produce its verdict, and the real list must pass."""
    bad: list[str] = []
    probe = next(c for c in CITED if c[0] != "14")
    warn: list[str] = []
    base = cited_lines(CITED, warn)
    bad += [f"selftest: the real cite list fails: {b}" for b in base]
    cases = (
        ("ambiguous", (probe[0], probe[1], "|"), "FAIL", "ambiguous"),
        (
            "gone",
            (probe[0], probe[1], "E33-D02 selftest: a fragment no plan file holds"),
            "FAIL",
            "gone",
        ),
        ("drifted", (probe[0], probe[1] - 1, probe[2]), "WARN", "now at"),
        ("exact", probe, "ok", ""),
    )
    for name, case, verdict, needle in cases:
        warn = []
        fails = cited_lines((case,), warn)
        got = "FAIL" if fails else "WARN" if warn else "ok"
        text = " ".join(fails + warn)
        if got != verdict or needle not in text:
            bad.append(f"selftest {name}: expected {verdict} {needle!r}, got {got} {text!r}")
    return bad


def section(spec: str, a: int, b: int) -> str:
    return spec[spec.index(f"## {a}.") : spec.index(f"## {b}.")]


def gates(files: list[Path], facts: Facts, spec: str) -> list[str]:
    bad: list[str] = []
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    deck = section(spec, 8, 9)
    verbatim = [*facts["catalogue_strings"], *facts["caveats"].values(), facts["help_text"]]
    for s in [*verbatim, TAG_NAME, LINK_DOWN]:
        if s not in spec:
            bad.append(f"spec: verbatim string missing: {s[:60]}")
    for p in BANNED_COPY:
        bad += [
            f"spec section 8: retired word in UI copy: {m.group(0)!r}" for m in re.finditer(p, deck)
        ]
    frames = re.findall(r"^\| `(SCR-06[678]/[a-z0-9-]+)` +\|(.*)$", spec, MULTI)
    bad += [
        f"spec: frame {f} lacks the CMP-158 algo line"
        for f, rest in frames
        if "CMP-158" not in rest
    ]
    bad += [
        "spec: the reduce-only frame must name stop.algo_builder.reduce_only (C-2.6 path)"
        for f, rest in frames
        if f == "SCR-066/reduce-only" and "stop.algo_builder.reduce_only" not in rest
    ]
    c7 = next((ln for ln in spec.splitlines() if ln.startswith("| D02-C7 ")), "")
    for name, over in facts["overrides_24"].items():
        if over["24"] == "MISSING":
            bad.append(f"`24`: the overridden default {name} is gone")
        if f"`{name}`" not in c7:
            bad.append(f"spec D02-C7: the drawn override of `24` {name} is not named")
    for sub, fields in DRAWN_VS_22.items():
        for name in fields:
            if "minimum 0" not in facts["bounds_22"].get(sub, {}).get(name, ""):
                bad.append(f"`22` {sub}.{name}: minimum 0 gone (re-read D02-C7)")
            if f"`{sub}.{name}`" not in c7:
                bad.append(f"spec D02-C7: the drawn {sub}.{name} vs `22` is not named")
    c_rows = "\n".join(ln for ln in spec.splitlines() if ln.startswith("| D02-C"))
    for key, text in re.findall(
        r"^\| `(lockout|frozen|algo\.submit\.link_down|algo\.finishing)` +\| \"([^\"]+)\"",
        deck,
        MULTI,
    ):
        too_long, no_stop = len(text) > REASON_MAX, not text.endswith(".")
        if (too_long or no_stop) and f"`{key}`" not in c_rows:
            bad.append(
                f"spec: reason `{key}` breaks E09-D09's rule ({len(text)} chars) with no C-row"
            )
    bad += cited_lines()
    for f in files:
        t = f.read_text(encoding="utf-8")
        bad += [f"{f.name}: forbidden text {p}" for p in FORBIDDEN if re.search(p, t)]
        cited = sorted(set(re.findall(r"\bC-\d+\.\d+\b", t)))
        bad += [f"{f.name}: dangling rule id {r}" for r in cited if f"**{r}" not in constitution]
    return bad


def flatten(d: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


def main(argv: list[str]) -> int:
    extra = [Path(a) for a in argv[argv.index("--extra") + 1 :]] if "--extra" in argv else []
    themes = {k: load_theme(k) for k in THEMES}
    pairs_text = (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8")
    registered = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_text))
    out = ["## 1. Measured matrix (fg on bg | role | dark / light / hc | verdict | pairs | where)"]
    matrix: list[dict[str, object]] = []
    fails = proposed = gated = 0
    demo_7 = True
    for element, fg, bg, role in rows(PAIRS_TABLE):
        ratios = {th: contrast(resolve(t, fg), resolve(t, bg)) for th, t in themes.items()}
        bar = BAR.get(role)
        if role == "aaa-target":
            demo_7 = all(r >= 7.0 for r in ratios.values())
            verdict = "7:1 met" if demo_7 else "7:1 not met — shortfall stated (spec 10)"
        elif bar is None:
            verdict = "reported, not gated" if role == "decorative" else "rejected, never drawn"
        else:
            gated += 1
            verdict = "PASS" if all(r >= bar for r in ratios.values()) else "FAIL"
            fails += verdict == "FAIL"
            proposed += (fg, bg) not in registered
        reg = "registered" if (fg, bg) in registered else "PROPOSED"
        matrix.append({"element": element, "fg": fg, "bg": bg, "role": role, "verdict": verdict})
        matrix[-1]["pairs"] = reg
        matrix[-1].update({k: round(v, 4) for k, v in ratios.items()})
        shown = " / ".join(show(r) for r in ratios.values())
        out.append(f"{fg} on {bg} | {role} | {shown} | {verdict} | {reg} | {element}")
    composite: dict[str, float] = {}
    for th, t in themes.items():
        over = resolve(t, "color.surface.overlay")
        label = blend(resolve(t, "color.text.on-action"), over, 0.45)
        composite[th] = round(
            contrast(label, blend(resolve(t, "color.action.primary.default"), over, 0.45)), 2
        )
    out.append(f"validity look composite (Start at 0.45 over the overlay; not gated): {composite}")
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    missing: list[str] = []
    for token in BINDINGS:
        vals = [resolve(t, token)[:40] for t in themes.values()]
        if token in PRIMITIVE_ALIAS:
            vals = [f"primitive; alias {PRIMITIVE_ALIAS[token]}"]
        if vals[0] == "MISSING":
            missing.append(token)
        out.append(f"{token} | {' / '.join(vals)}")
    counts = {
        f: sum("$value" in v for v in json.loads((TOKENS / f).read_text(encoding="utf-8")).values())
        for f in (PRIM, DARK, LIGHT, HC)
    }
    out.append(f"token files: {counts} | MISSING: {missing}")
    arith = arithmetic()
    out.append(
        "\n## 3. Arithmetic (fixture BTCUSDT tick 0.10 / step 0.001 / min qty 0.001 / notional 5)"
    )
    out.append(json.dumps(arith, ensure_ascii=False))
    facts = plan_facts()
    out.append(
        "\n## 4. Plan facts parsed from text (22 bounds | 24 defaults | 14 strings | memo caveats)"
    )
    out.append(json.dumps(facts, ensure_ascii=False))
    spec = SPEC.read_text(encoding="utf-8")
    out.append("\n## 5. String gates")
    bad = gates([SPEC, *extra], facts, spec)
    ok = (
        "OK — catalogue strings, caveats, help text, tag name and link-down sentence present; "
        "no retired word in the copy deck; CMP-158 on every frame; no private path"
    )
    out.append(ok if not bad else "\n".join("FAIL " + b for b in bad))
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    deck = section(spec, 8, 9)
    deck_rows = re.findall(r"^\| `[^`]+` +\| [^|]*\| ([^|]+?) +\|", deck, MULTI)
    by_source: dict[str, int] = {}
    for src in deck_rows:
        key = src.split(" ")[0].strip("`")
        by_source[key] = by_source.get(key, 0) + 1
    frames = re.findall(r"^\| `(SCR-06[678])/", spec, MULTI)
    mapping = section(spec, 3, 7)
    status = {
        s: len(re.findall(rf"\| {s} +\|$", mapping, MULTI))
        for s in ("both", "`24` only", "`22` only", "neither")
    }
    reason_re = r"^\| `(?:rbac\.[a-z_]+|algo\.(?:submit\.link_down|finishing)|lockout|frozen)` +\|"
    numbers: dict[str, object] = {
        "frames_twap": frames.count("SCR-066"), "frames_iceberg": frames.count("SCR-067"),
        "frames_chase": frames.count("SCR-068"), "frames_total": len(frames),
        "boards": len(re.findall(r"^\| \d\d +\| `", section(spec, 0, 1), MULTI)),
        "light_twins": len(re.findall(r"^\| \d\d +\| `[^`]+-light`", section(spec, 0, 1), MULTI)),
        "pairs_rows": gated, "pairs_registered": gated - proposed, "pairs_proposed": proposed,
        "pairs_fail": fails, "demo_badge_7_1": demo_7, "composite": composite,
        "opacity_disabled": float(resolve(themes["dark"], "opacity.disabled")),
        "c_rows": len(re.findall(r"^\| D02-C\d+ ", spec, MULTI)),
        "g_rows": len(re.findall(r"^\| D02-G\d+ ", spec, MULTI)),
        "a_rows": len(re.findall(r"^\| D02-A\d+ ", spec, MULTI)),
        "q_rows": len(re.findall(r"^\| D02-Q\d+ ", spec, MULTI)),
        "bq_rows": len(re.findall(r"^\| BQ-\d+ ", spec, MULTI)), "deck_rows": len(deck_rows),
        "deck_new": by_source.get("new", 0), "deck_by_source": by_source,
        "reason_keys": len(re.findall(reason_re, deck, MULTI)),
        "controls_both": status["both"], "controls_24_only": status["`24` only"],
        "controls_22_only": status["`22` only"], "controls_neither": status["neither"],
        "checklist_items": len(re.findall(r"^\| 14:15(?:47|58|70) ", spec, MULTI)),
        "missing_tokens": len(missing), "banned_copy_words": len(BANNED_COPY),
    }  # fmt: skip
    numbers.update(arith)
    out.append("\n## 6. Counts: " + json.dumps(numbers, ensure_ascii=False))
    flat = flatten(numbers)
    if "--selftest" in argv:
        st = selftest()
        out.append("selftest: " + ("ok (ambiguous, gone, drifted, exact)" if not st else "FAILED"))
        bad += st
    if "--check" in argv:
        for key, val in re.findall(r"<!-- audit:([a-z0-9_.]+)=([^ ]+) -->", spec):
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
    if "--json" in argv:
        payload = {
            "numbers": numbers,
            "matrix": matrix,
            "missing": missing,
            "facts": facts,
            "problems": bad,
            "cite_warnings": CITE_WARN,
            "palette": {th: {n: resolve(t, n) for n in BINDINGS} for th, t in themes.items()},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("\n".join(out))
    return 1 if fails or bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
