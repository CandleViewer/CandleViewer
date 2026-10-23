"""E14-D06 audit: the long/short position tool and its send-to-ticket hand-off.

Offline, stdlib plus the repo's own token / contrast / CVD helpers (imported, never re-done).
Prints, with a source label on every row: (1) the one constants block of
docs/design/E14/E14-D06.md section 1 and every money row a frame shows — the recorded
instrument and fee fixtures, the mock account, 24-internal-schemas.md section 9.3's arithmetic
(fee-aware risk-based size, floor to the lot step, the recorded clamp, stops rounded away from
the entry), E30-D02's worked example reproduced to the cent; (2) rounding and formatting;
(3) the registries parsed from `22` / `24` / the keymap as text, so every code, reason and
state word the copy deck binds is registered; (4) the WCAG matrix of every pair the frames
render, judged on the unrounded ratio; (5) the CVD rows (dE76, JND 5.0) and the Rec. 601 greys;
(6) the string, reuse and anchor gates on the spec, the hand-off and any extra file given;
(7) the counts the boards and the PR quote. `--json` feeds the board-script check.

Usage: python3 -I docs/design/_tools/e14_d06_position_audit.py [--json] [--check] [files...]
Exit 1 only on a gated FAIL (`--check` is the same gate, spelled out). No network anywhere.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from collections.abc import Callable
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
TOKENS, PLAN = ROOT / "packages" / "ui" / "tokens", ROOT / "docs" / "plan"
E14, RES = ROOT / "docs" / "design" / "E14", ROOT / "docs" / "design" / "research"
SPEC, HANDOFF, D02 = E14 / "E14-D06.md", E14 / "E14-D06-handoff.md", E14 / "E14-D02.md"
E30D02, E09 = ROOT / "docs/design/E30/E30-D02.md", ROOT / "docs/design/E09/E09-D09.md"
E32, MEMO = RES / "e32-brackets-ladders.md", RES / "e14-drawing-mental-models.md"
FIXTURE = ROOT / "packages/fixtures/bybit/2026-10-05/rest/instruments_after.json"
FEE_FIXTURE = ROOT / "packages/fixtures/accounts/_base/fee_rate.json"
D = Decimal
FAILS: list[str] = []
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0, "decorative": None}


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")


def resolve_theme(name: str) -> dict[str, str]:
    allt = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    cols = {k: v for k, v in allt.items() if v.get("$type") == "color"}
    return {k: str(verify.resolve(v["$value"], allt)) for k, v in cols.items()}


T = {n: resolve_theme(n) for n in THEMES}


def col(theme: str, short: str) -> str:
    return T[theme]["color." + short]


def rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def ratio(fg: str, bg: str) -> float:
    return float(contrast.contrast_ratio(rgb(fg), rgb(bg)))


def grey(h: str) -> str:  # cvd_sim.py's to_greyscale: Rec. 601 luma, floored, as a hex grey
    r, g, b = rgb(h)
    return "#" + f"{max(0, min(255, int(0.299 * r + 0.587 * g + 0.114 * b))):02X}" * 3


# ---- 1. the constants block (spec section 1) and every derived money row ----------------------
def instrument() -> tuple[dict[str, Decimal], str]:
    k = "tick=tickSize step=qtyStep min_qty=minOrderQty max_qty=maxOrderQty"
    keys = dict(s.split("=") for s in (k + " min_notional=minNotionalValue").split())
    try:
        rows_ = json.loads(FIXTURE.read_text(encoding="utf-8"))["result"]["list"]
        row = next(r for r in rows_ if r["symbol"] == "BTCUSDT")
        flt = dict(row["priceFilter"]) | dict(row["lotSizeFilter"])
        return {a: D(flt[b]) for a, b in keys.items()}, f"read from {FIXTURE.relative_to(ROOT)}"
    except (OSError, KeyError, StopIteration, ValueError) as exc:
        vals = map(D, ("0.10", "0.001", "0.001", "100.000", "5"))
        return dict(zip(keys, vals, strict=True)), f"transcribed; not read: {type(exc).__name__}"


def fee_rates() -> tuple[Decimal, Decimal, str]:
    try:
        row = json.loads(FEE_FIXTURE.read_text(encoding="utf-8"))["result"]["list"][0]
        src = f"read from {FEE_FIXTURE.relative_to(ROOT)}"
        return D(row["takerFeeRate"]), D(row["makerFeeRate"]), src
    except (OSError, KeyError, IndexError, ValueError) as exc:
        return D("0.00055"), D("0.0002"), f"transcribed; not read: {type(exc).__name__}"


INST, INST_SRC = instrument()
TAKER, MAKER, FEE_SRC = fee_rates()
ACCT_SRC = (
    "equity=12500.00 available=9840.00 leverage=10 risk_pct=0.005 profile_sl_ticks=200 "
    "fallback_pct=0.02 max_position=17500 daily_cap=500 daily_used=120 stale_age_s=14"
)
A = {k: D(v) for k, v in (s.split("=") for s in ACCT_SRC.split())}
A["headroom"] = A["daily_cap"] - A["daily_used"]
# plan | side | entry | stop | target | mode | qty  (spec section 1; the frames name them)
PLAN_SRC = (
    "long-default|buy|64010.0|63900.0|64300.0|risk_based|-",
    "fixed-twin|buy|64010.0|63900.0|64300.0|fixed_qty|0.250",
    "short-mirror|sell|64010.0|64120.0|63720.0|risk_based|-",
    "entry-stop-only|buy|64010.0|63900.0|-|fixed_qty|0.250",
    "over-cap|buy|64010.0|62400.0|64300.0|fixed_qty|0.250",
    "below-min|buy|64010.0|63900.0|64300.0|fixed_qty|0.0004",
    "wrong-side|buy|64010.0|64050.0|64300.0|fixed_qty|0.250",
    "wrong-target|buy|64010.0|63900.0|63950.0|fixed_qty|0.250",
    "zero-distance|buy|64010.0|64010.0|64300.0|fixed_qty|0.250",
)
PX_DP = max(0, -int(INST["tick"].normalize().as_tuple().exponent))
QTY_DP = max(0, -int(INST["step"].normalize().as_tuple().exponent))
NUMERIC = re.compile(r"^\d")


def cents(x: Decimal) -> Decimal:
    return x.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def lot(x: Decimal) -> Decimal:
    return (x / INST["step"]).to_integral_value(rounding=ROUND_FLOOR) * INST["step"]


def to_tick(px: Decimal, away_up: bool) -> Decimal:  # 24 section 9.3.1: away from the entry
    mode = ROUND_CEILING if away_up else ROUND_FLOOR
    return (px / INST["tick"]).to_integral_value(rounding=mode) * INST["tick"]


def fmt(x: Decimal, dp: int) -> str:  # thousands separators, minus U+2212, fixed decimals
    return ("\u2212" if x < 0 else "") + f"{abs(x):,.{dp}f}"


def plan(line: str) -> dict[str, str]:
    name, side, e, s, t, mode, q = line.split("|")
    entry, stop, long = D(e), D(s), side == "buy"
    target = None if t == "-" else D(t)
    dist = abs(entry - stop)
    fee_unit = cents(entry * TAKER * 2)  # 24 section 9.3 step 5: entry + exit taker fees
    out = {"plan": name, "side": "long" if long else "short", "entry": fmt(entry, PX_DP)}
    out |= {"stop": fmt(stop, PX_DP), "target": "—" if target is None else fmt(target, PX_DP)}
    out |= {"ticks": fmt(dist / INST["tick"], 0), "fee_unit": fmt(fee_unit, 2), "mode": mode}
    bad_stop = dist == 0 or (stop > entry if long else stop < entry)
    bad_target = target is not None and (target <= entry if long else target >= entry)
    if bad_stop or bad_target:
        reason = "invalid_stop_distance" if dist == 0 else "wrong side"
        return out | {"valid": "no", "reason": reason, "rr": "—", "risk": "—", "size": "—"}
    clamp = ""
    if mode == "risk_based":
        raw = lot((A["equity"] * A["risk_pct"]) / (dist + fee_unit))
        qty = raw
        if qty * entry > A["max_position"]:
            qty = lot(A["max_position"] / entry)
            clamp = (
                f"reduced from {fmt(raw, QTY_DP)} to {fmt(qty, QTY_DP)} by max_position_notional"
            )
        out["raw_qty"] = fmt(raw, QTY_DP)
    else:
        qty = lot(D(q))
    if qty < INST["min_qty"] or qty * entry < INST["min_notional"]:
        bad = {"valid": "no", "reason": "below_min_notional", "size": fmt(qty, QTY_DP)}
        return out | bad | {"rr": "—", "risk": "—"}
    risk, notional = cents(qty * dist), cents(qty * entry)
    be_raw = entry * (1 + TAKER) / (1 - TAKER) if long else entry * (1 - TAKER) / (1 + TAKER)
    be = to_tick(be_raw, away_up=long)
    out |= {"valid": "yes", "size": fmt(qty, QTY_DP), "notional": fmt(notional, 2), "clamp": clamp}
    out |= {"risk": fmt(risk, 2), "risk_fees": fmt(cents(qty * (dist + fee_unit)), 2)}
    out |= {"risk_pct": fmt(cents(risk / A["equity"] * 100), 2), "be": fmt(be, PX_DP)}
    out |= {"margin": fmt(cents(notional / A["leverage"]), 2), "headroom": fmt(A["headroom"], 2)}
    out |= {
        "fee_1w": fmt(cents(qty * entry * TAKER), 2),
        "fee_rt": fmt(cents(qty * entry * TAKER * 2), 2),
        "be_ticks": fmt(abs(be - entry) / INST["tick"], 0),
    }
    out["cap"] = "exceeds" if risk > A["headroom"] else "within"
    out["server_clamp"] = fmt(lot(A["headroom"] / dist), QTY_DP) if out["cap"] == "exceeds" else ""
    if target is None:
        return out | {"reward": "— set a target", "rr": "— set a target"}
    rr = (abs(target - entry) / dist).quantize(D("0.01"), rounding=ROUND_HALF_UP)
    return out | {"reward": fmt(cents(qty * abs(target - entry)), 2), "rr": str(rr)}


PLANS = {p["plan"]: p for p in map(plan, PLAN_SRC)}
FORMATS = {
    "price_width_btc": fmt(D("64010.0"), 1),
    "price_sol": fmt(D("148.125"), 3),
    "seven_decimals": fmt(D("0.0012345"), 7),
    "stop_long_typed": fmt(to_tick(D("63899.96"), away_up=False), 1),
    "stop_short_typed": fmt(to_tick(D("64120.04"), away_up=True), 1),
    "qty_floor": fmt(lot(D("0.3464")), QTY_DP),
    "very_small": fmt(cents(INST["min_qty"] * D("64010.0")), 2),
    "very_large": fmt(cents(INST["max_qty"] * D("64010.0")), 2),
    "minus": fmt(D("-27.50"), 2),
}

# ---- 3. the registries, parsed from 22 / 24 / the keymap as text --------------------------------
Y = (PLAN / "22-api-openapi.yaml").read_text(encoding="utf-8")
S24 = (PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")
KEYMAP = (ROOT / "apps/web/src/keymap/keymap.json").read_text(encoding="utf-8")


def enum_after(anchor: str, key: str, sub: str = "") -> list[str]:
    i = Y.index(anchor)
    i = Y.index(sub, i) if sub else i
    pat = rf"{key}:\s*(?:\n\s*)?\[([^\]]+)\]|{key}:\s*\n((?:\s+- \w+\n)+)"
    m = re.search(pat, Y[i : i + 6000])
    return re.findall(r"\w+", (m.group(1) or m.group(2)).replace("-", " ")) if m else []


def props_under(anchor: str) -> list[str]:
    i = Y.index(anchor)
    return re.findall(r"^        (\w+):", Y[i : i + 4000], re.MULTILINE)


_origin = re.search(r"origin: Literal\[([^\]]+)\]", S24[S24.index("class OrderIntent") :])
_clamps = S24[S24.index("**9.3.2 Clamp order**") :][:600]
REG: dict[str, list[str]] = {
    "DrawingTool": enum_after("    DrawingTool:", "enum"),
    "SizingMode": enum_after("    SizingMode:", "enum"),
    "ProfileSizingMode": enum_after("    ProfileSizingMode:", "enum"),
    "preview.rejection.code": enum_after("    TradeGroupPreview:", "enum", "rejection:"),
    "OrderEntryRefusalReason": enum_after("    OrderEntryRefusalReason:", "enum"),
    "Instrument.status": enum_after("    Instrument:", "status: \\{ type: string, enum"),
    "Instrument": props_under("    Instrument:"),
    "PlaceOrderRequest": props_under("    PlaceOrderRequest:"),
    "ResolvedLegParams": props_under("    ResolvedLegParams:"),
    "24.9.3 skip/fail": sorted(set(re.findall(r'LegSizing\.(?:skip|fail)\("(\w+)"\)', S24))),
    "24.9.3.2 clamps": re.findall(r"`(max_\w+)`", _clamps),
    "24.8.1 origin": re.findall(r'"(\w+)"', _origin.group(1)) if _origin else [],
    "keymap chart.*": re.findall(r'"id": "(chart\.\w+)"', KEYMAP),
}
EXPECT = {"SizingMode": 6, "ProfileSizingMode": 4, "preview.rejection.code": 8}
EXPECT |= {"OrderEntryRefusalReason": 4, "Instrument.status": 4, "DrawingTool": 25}
EXACT3 = re.search(r"exactly 3:([^\n]*\n[^\n]*)", Y)
PLACE_REQ = re.search(r"PlaceOrderRequest:\n(?:.*\n){0,3}.*required: \[([^\]]+)\]", Y)
# every code / state word the copy deck binds -> the registry that must hold it
BOUND_SRC = (
    "account_locked kill_switch_engaged symbol_not_allowed cap_breached@preview.rejection.code",
    "invalid_stop_distance below_min_notional@24.9.3 skip/fail",
    "Delivering Trading@Instrument.status",
    "long_position short_position@DrawingTool",
    "max_position_notional@24.9.3.2 clamps",
    "chart@24.8.1 origin",
    "min_notional_value status tick_size qty_step min_order_qty max_order_qty@Instrument",
    "stop_loss_price risk_usd estimated_fee_usd sizing_explanation@ResolvedLegParams",
    "stop_loss take_profit profile_id note@PlaceOrderRequest",
    "chart.limit_at_price chart.market_order@keymap chart.*",
)
BOUND = [(w, g.split("@")[1]) for g in BOUND_SRC for w in g.split("@")[0].split()]

# ---- 4. the measured matrix and 5. the CVD rows -------------------------------------------------
# element|fg|bg|role, one pair per line (the frames name each element)
PAIR_SRC = """
read-out dt / dd, chip words|text.primary|surface.overlay|text
read-out units, sources, reasons under a control|text.secondary|surface.overlay|text
(provisional) / (estimated) tags, captions|text.tertiary|surface.overlay|text
chip and tag text on the raised fill|text.primary|surface.raised|text
T2 Send label + lock glyph (E09-D09 2.2)|text.tertiary|surface.raised|text
T2 reason / validity reason under Send|text.secondary|surface.raised|text
loss-zone label (word + signed number)|text.primary|sell.subtle|text
reward-zone label (word + signed number)|text.primary|buy.subtle|text
loss-zone caption (ticks)|text.secondary|sell.subtle|text
reward-zone caption (R)|text.secondary|buy.subtle|text
stale rows: shaded text|data-confidence.stale.text|data-confidence.stale.surface|text
ticket fragment: BUY label (E30-D02 D3 reproduced)|text.inverse|buy.default|text
ticket fragment: SELL label (E30-D02 D3 reproduced)|text.inverse|sell.default|text
chip text, 7:1 stretch (05 section 5 item 3)|text.primary|surface.raised|hc-text
entry line on the canvas (pairs.mjs row)|position.entry|surface.canvas|non-text
stop edge on the canvas (pairs.mjs row)|position.sl|surface.canvas|non-text
target edge on the canvas (pairs.mjs row)|position.tp|surface.canvas|non-text
selected outline on the canvas (pairs.mjs row)|drawing.selected|surface.canvas|non-text
stop edge over the loss zone|position.sl|sell.subtle|non-text
target edge over the reward zone|position.tp|buy.subtle|non-text
loss zone against the canvas|sell.subtle|surface.canvas|decorative
reward zone against the canvas|buy.subtle|surface.canvas|decorative
danger glyph on the Risk row (E30-D02 D16)|status.danger.strong|surface.overlay|non-text
danger glyph on the loss-zone label (over the cap)|status.danger.strong|sell.subtle|non-text
clamp pill glyph|status.warning.strong|status.warning.subtle|non-text
clamp pill text|text.primary|status.warning.subtle|text
focus ring on the canvas|focus.ring|surface.canvas|non-text
focus ring on the loss zone|focus.ring|sell.subtle|non-text
focus ring on the reward zone|focus.ring|buy.subtle|non-text
focus ring on the read-out|focus.ring|surface.overlay|non-text
DEMO dot + border on the raised pill|env.demo|surface.raised|non-text
LIVE dot + border on the raised pill|env.live|surface.raised|non-text
read-out divider hairline|border.default|surface.overlay|decorative
"""
PAIRS = PAIR_SRC.strip().splitlines()
MJS = re.sub(r"\s+", " ", (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8"))
REGISTERED = set(re.findall(r'fg: "([^"]+)", bg: "([^"]+)"', MJS))
CVD_PAIRS = (
    "loss zone vs reward zone|sell.subtle|buy.subtle",
    "stop edge vs target edge|position.sl|position.tp",
    "entry line vs up candle|position.entry|candle.up",
    "entry line vs down candle|position.entry|candle.down",
    "danger glyph vs clamp glyph|status.danger.strong|status.warning.strong",
    "long chip accent vs short chip accent|buy.default|sell.default",
)
GREY_SRC = "surface.canvas position.entry position.sl position.tp buy.subtle sell.subtle"
GREY_TOKENS = (GREY_SRC + " drawing.selected text.primary").split()

# ---- 6. string gates ----------------------------------------------------------------------------
FORBID = ["team-" + "id=", "file-" + "id=", "#/work" + "space"]
PATH_RE = re.compile(r"/(?:home|Users)/[^/\s]+/")
HOST_RE = re.compile(r"\bpenpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE)
HOME_USER = Path.home().name
NORMATIVE = "no order is placed by this action under any circumstance"
ADVICE = re.compile(
    r"\b(should|recommend\w*|good|bad|ideal|safe|take this|buy now|sell now)\b", re.IGNORECASE
)
POINTER = "- **Hi-fi spec (position tool):** [E14-D06.md](../design/E14/E14-D06.md) (E14-D06;"
S14 = (PLAN / "14-screens-catalogue.md").read_text(encoding="utf-8").splitlines()
S15 = (PLAN / "15-component-catalogue.md").read_text(encoding="utf-8").splitlines()
_F14 = ["Type", "Data", "Components", "A11y", "Performance", "Validation", "Interactions", "RBAC"]
FIELD14 = {"Analytics": "Analytics/audit", "checklist": "Design sign-off acceptance checklist"}
FIELD14 |= {f: f for f in [*_F14, "States"]}
ANCHOR14 = re.compile(r"`14` (?:SCR-\d{3} )?(\w+) :(\d+)")
ANCHOR15 = re.compile(r"CMP-(\d{3}) :(\d+)")
PIN22 = re.compile(r"`22` schema lines at the base \(([^)]*)\)")
NAMED22 = re.compile(r"`([^`\s]+)` :(\d+)")
Y_LINES, S24_LINES = Y.splitlines(), S24.splitlines()
H24 = [(m.group(1), i) for i, ln in enumerate(S24_LINES) if (m := re.match(r"### (\d+\.\d+) ", ln))]


def read(p: Path) -> str:
    if not p.exists():
        FAILS.append(f"missing file {p.name}")
        return ""
    return p.read_text(encoding="utf-8")


def rows(md: str, start: str, end: str) -> list[list[str]]:
    if start not in md:
        return []
    i = md.index(start)
    j = md.index(end, i) if end in md[i:] else len(md)
    lines = [
        ln for ln in md[i:j].splitlines() if ln.startswith("| ") and not ln.startswith("| ---")
    ]
    return [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]


def tick(cell: str) -> str:
    mt = re.search(r"`([^`]+)`", cell)
    return mt.group(1) if mt else cell


def anchor_gates(spec: str) -> dict[str, int]:
    n = {"anchors14": 0, "anchors15": 0, "anchors22": 0, "anchors24": 0}
    for m in ANCHOR14.finditer(spec):
        field, ln = m.group(1), int(m.group(2))
        if field in FIELD14:
            line = S14[ln - 1] if ln <= len(S14) else ""
            if not line.startswith(f"- **{FIELD14[field]}"):
                FAILS.append(f"14 anchor :{ln} is not the {field} line")
            n["anchors14"] += 1
    for m in ANCHOR15.finditer(spec):
        cid, ln = m.group(1), int(m.group(2))
        if not (S15[ln - 1] if ln <= len(S15) else "").startswith(f"### CMP-{cid} "):
            FAILS.append(f"15 anchor :{ln} is not the CMP-{cid} heading")
        n["anchors15"] += 1
    pin = PIN22.search(spec)
    for name, ln in NAMED22.findall(pin.group(1)) if pin else []:
        line = Y_LINES[int(ln) - 1] if int(ln) <= len(Y_LINES) else ""
        if name.split("/")[-1].split(".")[-1] not in line:
            FAILS.append(f"22 anchor :{ln} is not the {name} line")
        n["anchors22"] += 1
    for cite in re.finditer(r"`24` §(\d+\.\d+)[^|\n]{0,120}", spec):
        window = re.split(r"`\d\d`|; | §", cite.group(0)[6:])[
            0
        ]  # stop at the next doc or section cite
        starts = [i for sec, i in H24 if sec == cite.group(1)]
        nxt = [i for _, i in H24 if starts and i > starts[0]]
        lo, hi = (starts[0] + 1, nxt[0] if nxt else len(S24_LINES)) if starts else (0, -1)
        for num in re.findall(r"(?<![\d:]):(\d{3,5})", window):
            if not lo <= int(num) <= hi:
                FAILS.append(f"24 anchor :{num} is outside section {cite.group(1)}")
            n["anchors24"] += 1
    return n


def string_gates(spec: str, hand: str, extra: list[Path]) -> dict[str, int]:
    const = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    for name, txt in [("spec", spec), ("handoff", hand), *((p.name, read(p)) for p in extra)]:
        for bad in FORBID:
            if bad in txt:
                FAILS.append(f"{name}: forbidden text {bad!r}")
        if PATH_RE.search(txt) or (HOME_USER and HOME_USER in txt) or HOST_RE.search(txt):
            FAILS.append(f"{name}: a local path, the local user or a Penpot host")
        if NORMATIVE not in txt:
            FAILS.append(f"{name}: the normative no-order sentence is missing")
    for cid in sorted(set(re.findall(r"\bC-\d+\.\d+\b", spec + hand))):
        if not re.search(rf"(?<![\w.]){re.escape(cid)}(?![\w.])", const):
            FAILS.append(f"dangling rule id {cid}")
    d02, memo = read(D02), read(MEMO)
    FAILS.extend(
        f"D02 transition {t} not found"
        for t in set(re.findall(r"\bT\d\d\b", spec))
        if f"| {t} " not in d02
    )
    FAILS.extend(
        f"memo decision {a} not found"
        for a in set(re.findall(r"\bAD-\d+\b", spec))
        if f"| {a} " not in memo
    )
    decks = {"E30-D02": rows(read(E30D02), "## 14. Copy deck", "## 15.")}
    decks["E32-D01"] = rows(read(E32), "**5.3 Copy deck", "**5.4")
    decks["E09-D09"] = rows(read(E09), "## 10. Copy deck", "## 11.")
    src = {k: {tick(r[0]): r[1] for r in v if len(r) > 1} for k, v in decks.items()}
    deck = rows(spec, "## 10. Copy deck", "## 11.")
    reused = 0
    for r in deck:
        if len(r) < 3:
            continue
        key, text, source = tick(r[0]), r[1], r[2]
        if ADVICE.search(text):
            FAILS.append(f"copy deck {key}: an advice verb")
        if "held by" in text and "held by Bybit (exchange)" not in text:
            FAILS.append(f"copy deck {key}: a holder line without 'held by Bybit (exchange)'")
        if key == "pos.send.label" and not text.startswith('"Send to ticket'):
            FAILS.append("copy deck: the Send label does not start with 'Send to ticket'")
        owner = next((k for k in src if source.startswith(k)), None)
        if owner and "PROPOSED" not in source:
            reused += 1
            q = re.search(r'"([^"]+)"', text)
            base = src[owner].get(key) or src[owner].get(key.split(" /")[0])
            if base is None or q is None or q.group(1) not in base:
                FAILS.append(f"copy deck {key}: differs from {owner}")
    if sum(ln.startswith(POINTER) for ln in S14) != 1:
        FAILS.append("the 14 pointer line is not present exactly once")
    return {"copy_keys": len(deck), "reused_verbatim": reused, **anchor_gates(spec)}


def counts(spec: str, hand: str) -> dict[str, int | dict[str, int]]:
    def ids(prefix: str, start: str, end: str) -> int:
        return len({r[0] for r in rows(spec, start, end) if re.fullmatch(rf"{prefix}\d+", r[0])})

    def heads(start: str, end: str, pat: str) -> int:
        return len([r for r in rows(spec, start, end) if re.match(pat, r[0])])

    board_rows = [r for r in rows(spec, "## 0.", "## 1.") if re.fullmatch(r"\d\d", r[0])]
    frames = {r[0]: len(re.findall(r"`SCR-0\d\d/[a-z0-9-]+`", "|".join(r))) for r in board_rows}
    out: dict[str, int | dict[str, int]] = {
        "boards": len(board_rows),
        "frames": frames,
        "frames_total": sum(frames.values()),
        "states": heads("## 5.", "## 6.", r"`SCR-037/position-"),
        "creation_frames": heads("## 4.", "## 5.", r"`SCR-037/"),
        "readout_rows": heads("### 2.2", "## 3.", r"\*\*"),
        "payload_fields": heads("### 6.2", "### 6.3", r"`"),
        "threats": heads("## 11.", "## 12.", r"T\d$"),
        "events": heads("## 12.", "## 13.", r"`drawing\."),
        "A": ids("A", "## 17.", "## 18."),
        "C": ids("C", "## 18.", "## 19."),
        "G": ids("G", "## 19.", "## 20."),
        "Q": ids("Q", "## 20.", "## 21."),
        "handoff_blocks": hand.count("## Handoff checklist"),
    }
    blank = [ln for ln in hand.splitlines() if ln.startswith("- [ ]") and "N/A" not in ln]
    FAILS.extend(f"handoff: blank checklist line {ln[:40]!r}" for ln in blank)
    return out


def check_plans() -> None:
    w, ld, sm = PLANS["fixed-twin"], PLANS["long-default"], PLANS["short-mirror"]
    exp = "notional=16,002.50 margin=1,600.25 risk=27.50 risk_pct=0.22 rr=2.64 fee_rt=17.60"
    exp += " ticks=1,100"
    for ek, ev in (s.split("=") for s in exp.split()):
        if w[ek] != ev:
            FAILS.append(f"E30-D02 worked example not reproduced: {ek} {w[ek]} != {ev}")
    if (ld["raw_qty"], ld["size"], ld["fee_unit"]) != ("0.346", "0.273", "70.41"):
        FAILS.append(
            f"E30-D03 chain not reproduced: {ld['raw_qty']} / {ld['size']} / {ld['fee_unit']}"
        )
    if ld["rr"] != sm["rr"]:
        FAILS.append("R:R differs between the long and its short mirror")
    for name, pl in PLANS.items():
        if NUMERIC.match(pl["rr"]) and D(pl["rr"]) <= 0:
            FAILS.append(f"{name}: a non-positive R:R on a frame")
        if pl["valid"] == "no" and NUMERIC.match(pl["rr"]):
            FAILS.append(f"{name}: an invalid plan shows a number")
    exceeds = {n for n, pl in PLANS.items() if pl.get("cap") == "exceeds"}
    if exceeds != {"over-cap"}:
        FAILS.append(f"the cap verdicts are wrong: {sorted(exceeds)}")
    bm = PLANS["below-min"]
    if bm.get("reason") != "below_min_notional" or bm["size"] != fmt(D(0), QTY_DP):
        FAILS.append("the below-minimum plan is not refused at 0.000")


def check_registries(p: Callable[[str], None]) -> list[str]:
    req = re.findall(r"\w+", PLACE_REQ.group(1)) if PLACE_REQ else []
    for rk, rv in REG.items():
        p(f"| {rk} | {len(rv)} | {', '.join(f'`{x}`' for x in rv)} |")
        if (rk in EXPECT and len(rv) != EXPECT[rk]) or not rv:
            FAILS.append(f"registry {rk}: {len(rv)} members (unparsed or unexpected)")
    if not EXACT3 or not all(t in EXACT3.group(1) for t in ("long_position", "short_position")):
        FAILS.append("DrawingTool 'exactly 3' does not list both position tools")
    if req != ["exchange_account_id", "symbol", "side", "order_type", "sizing"]:
        FAILS.append(f"PlaceOrderRequest.required = {req}")
    if "chart.draw_position" in REG["keymap chart.*"]:
        FAILS.append("a chart.draw_position chord is registered; gap G8 is stale")
    FAILS.extend(f"bound word {w} not in {g}" for w, g in BOUND if w not in REG[g])
    return req


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    extra = [Path(a) for a in args if not a.startswith("--")]
    out: list[str] = []
    p = out.append
    p("## 1. Constants (one block) and the derived money rows (spec section 1; 24 section 9.3)\n")
    p(f"instrument BTCUSDT: {', '.join(f'{k}={v}' for k, v in INST.items())} ({INST_SRC})")
    p(f"fees: taker={TAKER} maker={MAKER} ({FEE_SRC})")
    p(f"account (mock): {ACCT_SRC}; headroom={A['headroom']}\n")
    keys = "plan side entry stop target ticks mode size notional risk risk_fees risk_pct reward rr"
    keys += " fee_1w fee_rt be be_ticks margin cap clamp server_clamp reason"
    p("| " + " | ".join(keys.split()) + " |\n|" + "---|" * len(keys.split()))
    for pl in PLANS.values():
        p("| " + " | ".join(pl.get(k, "") for k in keys.split()) + " |")
    check_plans()
    p("\n## 2. Rounding and formatting\n\n| rule | specimen |\n|---|---|")
    p("\n".join(f"| {k} | {v} |" for k, v in FORMATS.items()))
    p(f"| price / qty decimals | {PX_DP} / {QTY_DP} (from tick_size / qty_step) |")
    p("\n## 3. Registries (parsed from 22 / 24 / the keymap as text)\n")
    p("| registry | count | members |\n|---|---|---|")
    req = check_registries(p)
    p(f"\nbound words: {len(BOUND)}; PlaceOrderRequest.required = {req}; no chart.draw_* chord\n")
    p("## 4. Measured matrix (ratio per theme; bar per role; pairs.mjs status)\n")
    p("| element | fg | bg | role | dark | light | hc | verdict | pairs.mjs |\n|" + "---|" * 9)
    reg_n = prop_n = fail_n = 0
    for line in PAIRS:
        el, fg, bg, role = line.split("|")
        vals = [ratio(col(t, fg), col(t, bg)) for t in THEMES]
        bar = BAR.get(role)
        if bar is None:
            verdict = f"{role} (not gated)"
        elif role == "hc-text":
            verdict = "PASS" if vals[2] >= bar else "FAIL: high-contrast"
        else:
            bad = [THEMES[i] for i, v in enumerate(vals) if v < bar]
            verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
        if verdict.startswith("FAIL"):
            fail_n += 1
            FAILS.append(f"pair below the bar: {el}")
        status = "registered" if ("color." + fg, "color." + bg) in REGISTERED else "PROPOSED"
        reg_n += status == "registered"
        prop_n += status == "PROPOSED"
        v3 = " | ".join(f"{v:.2f}" for v in vals)
        p(f"| {el} | `color.{fg}` | `color.{bg}` | {role} | {v3} | {verdict} | {status} |")
    p(f"\npairs {len(PAIRS)} x 3 themes; registered {reg_n}, PROPOSED {prop_n}, FAIL {fail_n}\n")
    p("## 5. CVD (dE76 under each deficiency; JND 5.0) and the greyscale strip's greys\n")
    p("| pair | theme | normal | protan | deutan | tritan | verdict |\n|" + "---|" * 7)
    collapses = 0
    for line in CVD_PAIRS:
        name, a, b = line.split("|")
        for t in THEMES:
            ha, hb = col(t, a), col(t, b)
            d = [float(cvd.delta_e76(ha, hb))]
            for kind in ("protanopia", "deuteranopia", "tritanopia"):
                sa, sb = str(cvd.simulate(ha, kind)), str(cvd.simulate(hb, kind))
                d.append(float(cvd.delta_e76(sa, sb)))
            verdict = (
                "distinct" if min(d) >= 5.0 else "COLLAPSES (word / glyph / position carries it)"
            )
            collapses += verdict != "distinct"
            p(f"| {name} | {t} | " + " | ".join(f"{x:.1f}" for x in d) + f" | {verdict} |")
    p("\n| token (dark) | hex | Rec. 601 grey |\n|---|---|---|")
    p(
        "\n".join(
            f"| `color.{k}` | {col('dark', k)} | {grey(col('dark', k))} |" for k in GREY_TOKENS
        )
    )
    spec, hand = read(SPEC), read(HANDOFF)
    gates = string_gates(spec, hand, extra)
    cnt = counts(spec, hand)
    p(f"\n## 6. String gates and 7. counts\n\ngates: {gates}; counts: {json.dumps(cnt)}")
    p(f"\nFAIL count (gated rows only): {len(FAILS)}" + "".join("\n- " + f for f in FAILS))
    if "--json" in args:
        summary: dict[str, object] = {"inst": {k: str(v) for k, v in INST.items()}}
        summary |= {"fees": [str(TAKER), str(MAKER)], "acct": {k: str(v) for k, v in A.items()}}
        summary |= {"plans": PLANS, "formats": FORMATS, "bound": len(BOUND)}
        summary |= {"registries": {k: len(v) for k, v in REG.items()}}
        summary |= {"pairs": [len(PAIRS), reg_n, prop_n, fail_n], "cvd_rows": len(CVD_PAIRS) * 3}
        summary |= {
            "cvd_collapses": collapses,
            "grey": {k: grey(col("dark", k)) for k in GREY_TOKENS},
        }
        summary |= {"gates": gates, "counts": cnt, "fails": FAILS}
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print("\n".join(out))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
