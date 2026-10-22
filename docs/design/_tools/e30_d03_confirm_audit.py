"""E30-D03 audit: SCR-076 / 077 / 158 / 114 and the selector (docs/design/E30/E30-D03.md).

Offline, stdlib only. It prints, with a source label on every row: (1) the one constants block
and every money row a frame shows, derived from that frame's own inputs (carries C1 / C2 / N5 /
N6 of the E30-D02 boards round), with the D02 worked example reproduced exactly; (2) the gates
and timers; (3) the code registries parsed from `22` / `24` as text, so every code the copy deck
binds is registered; (4) the WCAG contrast matrix of every pair the four screens render, with
`contrast_check.contrast_ratio()` over the real token JSON resolved exactly as
`packages/ui/tokens/tests/verify_tokens.py` resolves it, judged on the unrounded ratio; (5) the
CVD rows (Brettel / Vienot via `docs/research/_tools/cvd_simulate.py`, dE76, JND 5.0) and the
Rec. 601 luma greys of the DEMO / LIVE pair; (6) the string gates on the spec, the handoff file
and any extra file given; (7) the counts the boards and the PR quote.

Usage: python3 -I docs/design/_tools/e30_d03_confirm_audit.py [--json] [extra files to gate...]
Exit 1 only on a gated FAIL. `decorative` and `exempt` rows are reported, never gated.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
E30 = ROOT / "docs" / "design" / "E30"
SPEC, HANDOFF, D02 = E30 / "E30-D03.md", E30 / "E30-D03-handoff.md", E30 / "E30-D02.md"
D = Decimal
FAILS: list[str] = []
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0, "exempt": None}


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
    out = {}
    for k, v in allt.items():
        if v.get("$type") == "color":
            out[k] = str(verify.resolve(v["$value"], allt))
    return out


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


def cents(x: Decimal) -> Decimal:
    return x.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def lot(x: Decimal) -> Decimal:
    return x.quantize(D("0.001"), rounding=ROUND_DOWN)


# ---- 1. the constants block (spec section 1.4) and every derived money row ----------------------
CONST_SRC = (
    "tick=0.10 step=0.001 min_qty=0.001 min_notional=5 equity=12500.00 available=9840.00 "
    "leverage=10 fee_rate=0.00055 bid=64010.0 ask=64010.1 mark=64012.5 entry=64010.0 "
    "stop=63900.0 tp=64300.0 qty=0.250 max_position=17500 daily_cap_pct=0.04 daily_used=120 "
    "lockout_used=500 profile_sl_ticks=200 fallback_pct=0.02 risk_pct=0.005 avail_short=1240.00 "
    "lev_asked=20 bad_price=64010.03 bad_qty=0.2504 slip_ticks=0.4 held_age_1=12 held_age_2=5 "
    "stale_age=14 cap_create=10 used_create=8 cap_cancel=10 used_cancel=1 cap_read=50 used_read=12"
)
C = {k: D(v) for k, v in (s.split("=") for s in CONST_SRC.split())}
C["daily_cap"] = cents(C["equity"] * C["daily_cap_pct"])
# account env sizing value leverage equity sent  (spec section 3; mock values, synthetic names)
LEG_SRC = (
    "Main LIVE fixed_qty 0.250 10 12500 yes",
    "sub_001 LIVE fixed_qty 0.100 5 6000 yes",
    "sub_002 LIVE risk_based 0.005 10 4000 yes",
    "sub_003 LIVE fixed_qty 0.100 10 3000 no",
)
LEGS = [r.split() for r in LEG_SRC]
COL_SRC = "qty entry stop ticks notional pct_eq im avail_after risk risk_pct fee tp_r"
COLS = COL_SRC.split()


def money(
    qty: Decimal,
    entry: Decimal,
    stop: Decimal,
    lev: Decimal,
    eq: Decimal,
    tp: Decimal | None = None,
) -> dict[str, str]:
    dist = abs(entry - stop)
    notional, risk = cents(qty * entry), cents(qty * dist)
    im = cents(notional / lev)
    tp_px = C["tp"] if tp is None else tp
    tp_r = (abs(tp_px - entry) / dist).quantize(D("0.01"), rounding=ROUND_HALF_UP)
    vals = [
        f"{qty:,.3f}",
        f"{entry:,.1f}",
        f"{stop:,.1f}",
        f"{(dist / C['tick']).to_integral_value():,.0f}",
        f"{notional:,.2f}",
        f"{cents(notional / eq * 100):,.1f}",
        f"{im:,.2f}",
        f"{cents(C['available'] - im):,.2f}",
        f"{risk:,.2f}",
        f"{cents(risk / eq * 100):,.2f}",
        f"{cents(notional * C['fee_rate']):,.2f}",
        f"{tp_r}",
    ]
    return dict(zip(COLS, vals, strict=True))


def risk_based(
    risk_usd: Decimal, entry: Decimal, stop: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    fee_unit = cents(entry * C["fee_rate"] * 2)  # 24 section 9.3 step 5: entry + exit taker fees
    qty = lot(risk_usd / (abs(entry - stop) + fee_unit))
    return fee_unit, qty, lot(C["max_position"] / entry)


def dec(s: str) -> Decimal:
    return D(s.replace(",", ""))


E, S, Q, LEV, EQ = C["entry"], C["stop"], C["qty"], C["leverage"], C["equity"]
WORKED = "SCR-076/live-limit = D02 worked example; SCR-077 what-was-sent; SCR-158 held 1"
FRAMES = {
    WORKED: money(Q, E, S, LEV, EQ),
    "SCR-076/live-market (entry = the ask)": money(Q, C["ask"], S, LEV, EQ),
    "SCR-076/live-conditional (limit 64,110.0 / stop 64,000.0 / TP 64,400.0)": money(
        Q, D("64110.0"), D("64000.0"), LEV, EQ, D("64400.0")
    ),
    "SCR-158 held intent 2 (0.100 at market)": money(D("0.100"), C["ask"], S, LEV, EQ),
    "SCR-114 template summary (stop 200 ticks, TP 2 R)": money(
        Q,
        E,
        E - C["profile_sl_ticks"] * C["tick"],
        LEV,
        EQ,
        E + 2 * C["profile_sl_ticks"] * C["tick"],
    ),
}
FEE_UNIT, RB_QTY, CLAMP_QTY = risk_based(EQ * C["risk_pct"], E, S)
EXPLAIN = (
    f"risk_based: {cents(EQ * C['risk_pct'])} USD / ({abs(E - S)} + {FEE_UNIT} fee) = {RB_QTY} BTC"
    f" → max_position_notional {C['max_position']:,} USD → {CLAMP_QTY} BTC"
)
LEG_ROWS: list[dict[str, str]] = []
for acct, env, mode, value, lev, eq, sent in LEGS:
    qty = D(value) if mode == "fixed_qty" else risk_based(D(eq) * D(value), E, S)[1]
    row = money(qty, E, S, D(lev), D(eq))
    row.update(account=acct, env=env, mode=mode, leverage=f"{lev}x", sent=sent)
    row["explain"] = f"{mode}: {qty} BTC"
    if mode == "risk_based":
        budget = cents(D(eq) * D(value))
        row["explain"] = f"risk_based: {budget} USD / ({abs(E - S)} + {FEE_UNIT} fee) = {qty} BTC"
    LEG_ROWS.append(row)
SENT = [r for r in LEG_ROWS if r["sent"] == "yes"]


def tot(key: str, places: int) -> str:
    return f"{sum(dec(r[key]) for r in SENT):,.{places}f}"


TOTALS = {
    "accounts": f"{len(SENT)} of {len(LEG_ROWS)}",
    "qty": tot("qty", 3),
    "notional": tot("notional", 2),
    "risk": tot("risk", 2),
    "fee": tot("fee", 2),
}
# ---- 2. gates and timers (every value beside its source) -----------------------------------------
RETRY_AFTER_S = 42
_abs = (14 * 3600 + 31 * 60 + 28 + RETRY_AFTER_S) % 86400
RETRY_AT = f"{_abs // 3600:02d}:{_abs % 3600 // 60:02d}:{_abs % 60:02d}"
TIMERS = [
    (
        "confirm auto-cancel",
        "20 s of inactivity; any key or pointer event restarts it",
        "14 SCR-076",
    ),
    (
        "countdown announcements",
        "aria-live=off; polite at 0:10 and at 0:00",
        "15 CMP-035; 14 SCR-158",
    ),
    (
        "Confirm activation gate",
        "Enter, Space or pointer: accepted 400 ms after open",
        "14 SCR-076 A11y; spec D3",
    ),
    (
        "replay",
        "opens on a fresh settled preview of the held intent, never the held numbers",
        "spec D2; 14 SCR-158 Performance",
    ),
    ("appearance budget", "100 ms from in-memory state, no fetch", "14 SCR-076 Performance"),
    ("SCR-114 save round-trip", "400 ms", "14 SCR-114 Performance"),
    ("SCR-158 announcement cadence", "at most once per 10 s", "14 SCR-158 A11y"),
    (
        "retry-after",
        f"14:31:28 + {RETRY_AFTER_S} s = {RETRY_AT} (in {RETRY_AFTER_S} s)",
        "22 Problem",
    ),
]

# ---- 3. the code registries, parsed from 22 / 24 as text -----------------------------------------
Y = (PLAN / "22-api-openapi.yaml").read_text(encoding="utf-8")
S24 = (PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")


def enum_after(anchor: str, key: str) -> list[str]:
    j = Y.index("enum:", Y.index(key, Y.index(anchor)))
    body = Y[Y.index("[", j) + 1 : Y.index("]", j)].replace("\n", " ")
    return [x.strip() for x in body.split(",") if x.strip()]


def props_under(anchor: str, key: str, indent: int) -> list[str]:
    i = Y.index(key, Y.index(anchor))
    out: list[str] = []
    for ln in Y[Y.index("\n", i) + 1 :].splitlines():
        if ln.strip() and len(ln) - len(ln.lstrip()) <= indent - 4:
            break
        if re.match(rf"^ {{{indent}}}(\w+):", ln):
            out.append(ln.split(":")[0].strip())
    return out


_x0 = Y.index("\nx-error-codes:")
_xm = re.search(r"\n[a-z]", Y[_x0 + 2 :])
XB = Y[_x0 : _x0 + 2 + (_xm.start() if _xm else len(Y))]
XCODES = {
    m.group(1): m.group(2) or "ws" for m in re.finditer(r"- code: (\w+)\n(?:\s+status: (\d+))?", XB)
}
REG = {
    "x-error-codes": sorted(XCODES),
    "preview.rejection.code": enum_after("    TradeGroupPreview:", "rejection:"),
    "OrderEntryRefusalReason": enum_after("    OrderEntryRefusalReason:", "enum:"),
    "LegStatus": enum_after("    LegStatus:", "enum:"),
    "OffsetUnit": enum_after("    OffsetUnit:", "enum:"),
    "Settings.trading": props_under("    Settings:", "        trading:", 12),
    "ExchangeRecordFields": props_under("    ExchangeRecordFields:", "properties:", 8),
}
EXPECT = {"preview.rejection.code": 8, "OrderEntryRefusalReason": 4, "LegStatus": 9}
EXPECT.update({"OffsetUnit": 5, "Settings.trading": 6})
S86 = S24[S24.index("### 8.6") : S24.index("### 8.7")]
RET: dict[str, str] = {}
for mt in re.finditer(r"^\| `(\d+)`(?:/`(\d+)`)?\s*\|[^|]*\|\s*`([A-Z_]+)`", S86, re.MULTILINE):
    RET[mt.group(1)] = mt.group(3)
    if mt.group(2):
        RET[mt.group(2)] = mt.group(3)
# every code the copy deck binds (spec sections 5 and 8): slug / preview code / reason / retCode
SLUG_SRC = (
    "validation_failed tick_size_violation lot_size_violation insufficient_balance rate_limited "
    "exchange_rate_limited exchange_error idempotency_in_flight exchange_unavailable "
    "store_unavailable audit_unavailable timeout degraded_data risk_limit_breached "
    "trading_disabled account_scope_denied session_not_armed step_up_required"
)
RET_SRC = (
    "10001 10006 10018 110004 110007 110012 110013 110016 110017 110024 110025 110028 110031 "
    "110036 110038 110043 110044 110045 110047 110086 110089 3400139"
)
BOUND_SLUGS, BOUND_RET = SLUG_SRC.split(), RET_SRC.split()
PROPOSED_CODES = "risk_state_unavailable (503, E39-S01); account_locked (403, E39-S01)"

# ---- 4. the measured matrix: element | fg | bg | role (tokens without the `color.` prefix) ------
PAIRS = (
    "dialog / drawer body, restatement values, class line|text.primary|surface.overlay|text",
    "dialog labels; reason text under a disabled control|text.secondary|surface.overlay|text",
    "countdown caption, captions, struck leg row|text.tertiary|surface.overlay|text",
    "env pill, code pill, leg-status chip, T2 pill text|text.primary|surface.raised|text",
    "non-binding limit rows; chip secondary text|text.secondary|surface.raised|text",
    "selector selected row / active preset text|text.primary|surface.selected|text",
    "selector hovered row text|text.primary|surface.hover|text",
    "quote block: verbatim exchange text (mono) in the well|text.primary|surface.sunken|text",
    "Confirm BUY label (D02 D3 reproduced)|text.inverse|buy.default|text",
    "Confirm SELL label (D02 D3 reproduced)|text.inverse|sell.default|text",
    "drawer class banner text (danger family)|text.primary|status.danger.subtle|text",
    "binding limit row; SCR-158 banner text|text.primary|status.warning.subtle|text",
    "CMP-158 note; SCR-158 backend per-user banner|text.primary|status.info.subtle|text",
    "SCR-114 saved banner text|text.primary|status.success.subtle|text",
    "env pill text, 7:1 stretch (05 section 5 item 3)|text.primary|surface.raised|hc-text",
    "Confirm BUY label AAA stretch (gated in hc only)|text.inverse|buy.default|hc-text",
    "Confirm SELL label AAA stretch (gated in hc only)|text.inverse|sell.default|hc-text",
    "disabled control label (the reason text is gated above)|text.disabled|surface.raised|exempt",
    "LIVE pill border + dot and the 2 px rule on the dialog|env.live|surface.overlay|non-text",
    "DEMO pill border + dot and the 2 px rule on the dialog|env.demo|surface.overlay|non-text",
    "LIVE border + dot on the raised pill (CMP-106 env dot)|env.live|surface.raised|non-text",
    "DEMO border + dot on the raised pill|env.demo|surface.raised|non-text",
    "focus ring on the dialog / drawer surface (halo)|focus.ring|surface.overlay|non-text",
    "focus ring on pills and buttons (raised)|focus.ring|surface.raised|non-text",
    "danger boundary: drawer rule, invalid field|status.danger.default|surface.overlay|non-text",
    "danger glyph (x-circle) on the overlay|status.danger.strong|surface.overlay|non-text",
    "danger glyph on the class banner|status.danger.strong|status.danger.subtle|non-text",
    "warning glyph on the binding row|status.warning.strong|status.warning.subtle|non-text",
    "info glyph on CMP-158|status.info.strong|status.info.subtle|non-text",
    "check glyph on the saved banner|status.success.strong|status.success.subtle|non-text",
    "would-be-rejected leg glyph on the raised row|status.danger.strong|surface.raised|non-text",
    "Confirm BUY fill vs the dialog surface|buy.default|surface.overlay|non-text",
    "Confirm SELL fill vs the dialog surface|sell.default|surface.overlay|non-text",
    "row divider hairline on the overlay|border.default|surface.overlay|decorative",
)
MJS = re.sub(r"\s+", " ", (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8"))
REGISTERED = set(re.findall(r'fg: "([^"]+)", bg: "([^"]+)"', MJS))
CVD_PAIRS = (
    "LIVE vs DEMO (pill border, dot, rule)|env.live|env.demo",
    "BUY vs SELL confirm fills|buy.default|sell.default",
    "danger vs warning fill (banner vs binding row)|status.danger.subtle|status.warning.subtle",
    "danger glyph vs warning glyph|status.danger.strong|status.warning.strong",
    "LIVE accent vs SELL fill (same-token identity, D02 F5)|env.live|sell.default",
)
GREY_SRC = (
    "surface.canvas surface.raised surface.overlay text.primary text.secondary border.default "
    "env.live env.demo buy.default sell.default"
)
GREY_TOKENS = GREY_SRC.split()

# ---- 6. string gates and 7. counts ---------------------------------------------------------------
HOME_USER = Path.home().name
FORBID = [
    "/" + "home/",
    "wt" + "-notes",
    "team-" + "id=",
    "file-" + "id=",
    "#/work" + "space",
    "IP-level",
]
FORBID.append("penpot." + "candleviewer.com")
LIVE_SENTENCE = "You are about to send a LIVE order"
STOP_KEY = re.compile(r"^(confirm|drawer|ratelimit|selector|template)\..*stop")
S14 = (PLAN / "14-screens-catalogue.md").read_text(encoding="utf-8").splitlines()
FIELD14 = {"Analytics": "Analytics/audit", "checklist": "Design sign-off acceptance checklist"}
for _f in (
    "Type",
    "Note",
    "Data",
    "Components",
    "A11y",
    "Performance",
    "Validation",
    "Interactions",
):
    FIELD14[_f] = _f
ANCHOR14 = re.compile(r"`14` (?:SCR-\d{3} )?(\w+) :(\d+)|(\w+) \(`14` :(\d+)\)")


def read(p: Path) -> str:
    if not p.exists():
        FAILS.append(f"missing file {p.name}")
        return ""
    return p.read_text(encoding="utf-8")


def rows(md: str, start: str, end: str | None = None) -> list[list[str]]:
    if start not in md:
        return []
    i = md.index(start)
    rest = md[i + len(start) :]
    j = i + len(start) + rest.index(end) if end and end in rest else len(md)
    out = []
    for ln in md[i:j].splitlines():
        if ln.startswith("| ") and not ln.startswith("| ---"):
            out.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return out


def tick(cell: str) -> str:
    mt = re.search(r"`([^`]+)`", cell)
    return mt.group(1) if mt else cell


def anchor_gates(spec: str) -> int:
    """Every `14` line anchor that names a field must point at that field's line (F-7)."""
    n = 0
    for m in ANCHOR14.finditer(spec):
        field, ln = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        if field not in FIELD14:
            continue
        line = S14[int(ln) - 1] if int(ln) <= len(S14) else ""
        if not line.startswith(f"- **{FIELD14[field]}"):
            FAILS.append(f"14 anchor :{ln} is not the {field} line")
        n += 1
    return n


def string_gates(spec: str, hand: str, extra: list[Path]) -> dict[str, int]:
    const = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    for name, txt in [("spec", spec), ("handoff", hand), *((p.name, read(p)) for p in extra)]:
        for bad in [*FORBID, HOME_USER]:
            if bad and bad in txt:
                FAILS.append(f"{name}: forbidden text {bad!r}")
    if LIVE_SENTENCE not in spec:
        FAILS.append("spec: the LIVE confirm sentence is missing")
    for cid in sorted(set(re.findall(r"\bC-\d+\.\d+\b", spec + hand))):
        if not re.search(rf"(?<![\w.]){re.escape(cid)}(?![\w.])", const):
            FAILS.append(f"dangling rule id {cid}")
    deck = rows(spec, "## 12. Copy deck", "## 13.")
    d02 = {tick(r[0]): r[1] for r in rows(read(D02), "## 14. Copy deck", "## 15.")}
    reused = 0
    for r in deck:
        key = tick(r[0])
        if STOP_KEY.match(key) and "held by Bybit" not in r[1]:
            FAILS.append(f"copy deck {key}: stop line without 'held by Bybit'")
        if "10018" in r[1]:
            FAILS.append(f"copy deck {key}: a 10018-keyed message")
        if len(r) > 2 and r[2].startswith("D02"):
            reused += 1
            q = re.search(r'"([^"]+)"', r[1])
            if key not in d02 or not q or q.group(1) not in d02[key]:
                FAILS.append(f"copy deck {key}: differs from E30-D02 section 14")
    live = spec.count(LIVE_SENTENCE)
    anchors = anchor_gates(spec)
    return {
        "copy_keys": len(deck),
        "d02_reused": reused,
        "live_sentence": live,
        "anchors14": anchors,
    }


def counts(spec: str, hand: str) -> dict[str, int | dict[str, int]]:
    def ids(prefix: str, start: str, end: str) -> int:
        return len({r[0] for r in rows(spec, start, end) if re.fullmatch(rf"{prefix}\d+", r[0])})

    def digit_rows(start: str, end: str, pat: str = r"\d") -> int:
        return len([r for r in rows(spec, start, end) if re.fullmatch(pat, r[0])])

    frames: dict[str, int] = {}
    for k in ("SCR-076", "SCR-077", "SCR-158", "SCR-114", "SCR-061"):
        fr = rows(spec, "## 2.", "## 10.")
        frames[k] = len({tick(r[0]) for r in fr if tick(r[0]).startswith(k + "/")})
    codes = REG["preview.rejection.code"]
    deck_keys = [tick(r[0]) for r in rows(spec, "## 12.", "## 13.")]
    out: dict[str, int | dict[str, int]] = {
        "boards": digit_rows("## 0.", "## 1.", r"\d\d"),
        "reasons": digit_rows("## 5.", "## 6."),
        "scopes": len(
            [r for r in rows(spec, "## 6.", "## 7.") if r[0].startswith("`ratelimit.scope.")]
        ),
        "rejection_codes": len([r for r in rows(spec, "## 8.", "## 9.") if tick(r[0]) in codes]),
        "fieldsets": digit_rows("## 7.", "## 8."),
        "policy_options": len([k for k in deck_keys if k.startswith("defaults.policy.")]),
        "frames": frames,
        "C": ids("C", "## 20.", "## 21."),
        "G": ids("G", "## 21.", "## 22."),
        "Q": ids("Q", "## 22.", "## 23."),
        "A": ids("A", "## 19.", "## 20."),
        "handoff_blocks": hand.count("## Handoff checklist"),
    }
    for ln in hand.splitlines():
        if ln.startswith("- [ ]") and "N/A" not in ln:
            FAILS.append(f"handoff: blank checklist line {ln[:40]!r}")
    return out


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    extra = [Path(a) for a in args if a != "--json"]
    out: list[str] = []
    p = out.append
    p("## 1. Constants (one block) and the derived money rows (spec section 1.4; 24 section 9.3)\n")
    p("| constant | value |\n|---|---|")
    p("\n".join(f"| `{ck}` | {cv:,} |" for ck, cv in C.items()))
    p("\n| frame | " + " | ".join(COLS) + " |\n|" + "---|" * (len(COLS) + 1))
    for name, m in FRAMES.items():
        p(f"| {name} | " + " | ".join(m[k] for k in COLS) + " |")
    w = FRAMES[WORKED]
    expect = {"notional": "16,002.50", "im": "1,600.25", "avail_after": "8,239.75"}
    expect.update({"risk": "27.50", "tp_r": "2.64", "fee": "8.80"})
    for ek, ev in expect.items():
        if w[ek] != ev:
            FAILS.append(f"D02 worked example not reproduced: {ek} {w[ek]} != {ev}")
    binds = (
        dec(w["notional"]) >= C["max_position"]
        or C["daily_used"] + dec(w["risk"]) >= C["daily_cap"]
    )
    if binds:
        FAILS.append("a default frame binds a limit (C1)")
    if C["daily_cap"] != EQ * C["daily_cap_pct"] or lot(dec(w["notional"]) / E) != Q:
        FAILS.append("constants disagree (C1)")
    if cents(RB_QTY * E) <= C["max_position"]:
        FAILS.append("the clamp frame does not bind (C1)")
    p(
        f"\nclamp frame (binding): risk-based {RB_QTY} BTC x {E:,.1f} = "
        f"{cents(RB_QTY * E):,.2f} USDT > {C['max_position']:,} → {CLAMP_QTY} BTC; "
        f'sizing_explanation = "{EXPLAIN}"'
    )
    p(
        f"lockout frame: daily {C['lockout_used']:,} of {C['daily_cap']:,.0f} USDT used (binding);"
        f" default frames {C['daily_used']:,} of {C['daily_cap']:,.0f}\n"
    )
    leg_src = "account env mode qty leverage stop ticks risk im fee notional sent explain"
    leg_cols = leg_src.split()
    p("| " + " | ".join(leg_cols) + " |\n|" + "---|" * len(leg_cols))
    for r in LEG_ROWS:
        p("| " + " | ".join(r[k] for k in leg_cols) + " |")
    p(
        f"\ntotals: {TOTALS['accounts']} accounts · {TOTALS['qty']} BTC · "
        f"{TOTALS['notional']} USDT · risk {TOTALS['risk']} USDT · fee {TOTALS['fee']} USDT"
        " (fee = the sum of the legs' estimated_fee_usd)"
    )
    short = cents(dec(w["im"]) - C["avail_short"])
    p(
        f"frame inputs: insufficient-margin needs {w['im']} USDT, {C['avail_short']:,} available"
        f" (short by {short:,}); leverage asked {C['lev_asked']}x against the 10x cap; tick / lot"
        f" {C['bad_price']:,} → {E:,.1f} and {C['bad_qty']} → {Q}; post-only reprice ="
        f" ask - 1 tick = {C['ask'] - C['tick']:,.1f}; profile stop {C['profile_sl_ticks']} ticks ="
        f" {E - C['profile_sl_ticks'] * C['tick']:,.1f}; request budget order.create"
        f" {C['used_create']} of {C['cap_create']} (reserve {max(2, int(C['cap_create']) // 10)}),"
        f" order.cancel {C['used_cancel']} of {C['cap_cancel']} (reserve"
        f" {max(2, int(C['cap_cancel']) // 10)}), position.read {C['used_read']} of {C['cap_read']}"
        f" (reserve {max(2, int(C['cap_read']) // 10)}); slippage {C['slip_ticks']} ticks (est.)\n"
    )
    label = f"Send {TOTALS['accounts']} legs — BUY BTCUSDT limit {w['entry']}"
    intent = f"BUY {w['qty']} BTCUSDT limit {w['entry']} · stop {w['stop']}"
    p(f'confirm labels from the same rows: "{intent}"; "{label}"\n')
    p("## 2. Gates and timers\n\n| gate | value | source |\n|---|---|---|")
    p("\n".join(f"| {a} | {b} | {c} |" for a, b, c in TIMERS))
    p("\n## 3. Code registries (parsed from 22 / 24 as text)\n")
    p("| registry | count | members |\n|---|---|---|")
    for rk, rv in REG.items():
        p(f"| {rk} | {len(rv)} | {', '.join(f'`{x}`' for x in rv)} |")
        if rk in EXPECT and len(rv) != EXPECT[rk]:
            FAILS.append(f"registry {rk}: {len(rv)} != {EXPECT[rk]}")
    ret = ", ".join(f"`{rc}` {oms}" for rc, oms in sorted(RET.items(), key=lambda kv: int(kv[0])))
    p(f"| 24 section 8.6 retCode rows | {len(RET)} | {ret} |")
    FAILS.extend(f"bound slug not registered: {s}" for s in BOUND_SLUGS if s not in XCODES)
    FAILS.extend(f"bound retCode not in 24 section 8.6: {rc}" for rc in BOUND_RET if rc not in RET)
    if "RATE_BUDGET_EXCEEDED" not in S24:
        FAILS.append("RATE_BUDGET_EXCEEDED missing from 24")
    p(
        f"\nbound: {len(BOUND_SLUGS)} slugs, {len(REG['preview.rejection.code'])} preview codes, "
        f"{len(REG['OrderEntryRefusalReason'])} reasons, {len(BOUND_RET)} retCodes; "
        f"proposed (not registered, reported): {PROPOSED_CODES}\n"
    )
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
            low = [THEMES[i] for i in (0, 1) if vals[i] < bar]
            verdict += f" (AAA stretch not met in {', '.join(low)})" if low else ""
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
    p(
        f"\npairs {len(PAIRS)} x 3 themes; registered {reg_n}, PROPOSED {prop_n}, "
        f"gated FAIL {fail_n}\n"
    )
    p("## 5. CVD (dE76 under each deficiency; JND 5.0) and the greyscale strip's greys\n")
    p("| pair | theme | normal | protan | deutan | tritan | verdict |\n|" + "---|" * 7)
    for line in CVD_PAIRS:
        name, a, b = line.split("|")
        for t in THEMES:
            ha, hb = col(t, a), col(t, b)
            d = [float(cvd.delta_e76(ha, hb))]
            for kind in ("protanopia", "deuteranopia", "tritanopia"):
                sa, sb = str(cvd.simulate(ha, kind)), str(cvd.simulate(hb, kind))
                d.append(float(cvd.delta_e76(sa, sb)))
            verdict = "distinct" if min(d) >= 5.0 else "COLLAPSES (word / glyph / shape carries it)"
            p(f"| {name} | {t} | " + " | ".join(f"{x:.1f}" for x in d) + f" | {verdict} |")
    p("\n| token (dark) | hex | Rec. 601 grey |\n|---|---|---|")
    p(
        "\n".join(
            f"| `color.{k}` | {col('dark', k)} | {grey(col('dark', k))} |" for k in GREY_TOKENS
        )
    )
    p(
        "\nthe eight leg statuses carry a word and a glyph each, never a hue (spec section 8); the "
        "greyscale survivors of the DEMO / LIVE pair are the word, the weight and the dot shape "
        "(the 2 px accent rule is hue only)\n"
    )
    spec, hand = read(SPEC), read(HANDOFF)
    gates = string_gates(spec, hand, extra)
    cnt = counts(spec, hand)
    p(f"## 6. String gates and 7. counts\n\nstring gates: {gates}; counts: {json.dumps(cnt)}")
    p(f"\nFAIL count (gated rows only): {len(FAILS)}" + "".join("\n- " + f for f in FAILS))
    if "--json" in args:
        summary = {
            "const": {k: str(v) for k, v in C.items()},
            "frames": FRAMES,
            "legs": LEG_ROWS,
            "totals": TOTALS,
            "explain": EXPLAIN,
            "clamp": [str(RB_QTY), str(CLAMP_QTY), str(FEE_UNIT)],
            "retry_at": RETRY_AT,
            "registries": {k: len(v) for k, v in REG.items()},
            "retcodes": len(RET),
            "pairs": [len(PAIRS), reg_n, prop_n, fail_n],
            "cvd_rows": len(CVD_PAIRS) * 3,
            "gates": gates,
            "counts": cnt,
            "fails": FAILS,
        }
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print("\n".join(out))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
