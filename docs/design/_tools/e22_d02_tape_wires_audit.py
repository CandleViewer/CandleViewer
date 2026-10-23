"""E22-D02 tape-wireframe audit: every number the SCR-053 greyscale wireframes claim, computed.

Standalone, offline, stdlib only (`python3 -I`). Themes resolve exactly as
`packages/ui/tokens/tests/verify_tokens.py` resolves them; contrast is `contrast_ratio()` from
`docs/design/_tools/contrast_check.py`; every fixture-derived number comes from
`docs/design/_tools/e22_d01_tape_stats.py` (its `provenance` / `file_stats` / `worked` / `cvd`
functions build the dict its `--json` prints) - all three imported with one loader, never
re-implemented; this tool reads no fixture and imports nothing from the `candleviewer` package. The
tape and bubble geometry is re-derived from the px literals of `docs/design/E22/E22-D02.md`, the
engine constants are quoted as text and the spec's strings are gated. Every section names its
source.

Usage: python3 -I docs/design/_tools/e22_d02_tape_wires_audit.py [--json] [--spec P] [--draft P]
Exit 1 only on a gated contrast FAIL, a radii or memo 3.9 mismatch, a changed quoted constant or a
failed string gate; the E13-D02 13 reproduction is reported, never adjusted. Stdout is UTF-8.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
TOOLS = ROOT / "docs" / "design" / "_tools"
ORDERFLOW = ROOT / "services" / "api" / "candleviewer" / "orderflow"
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0, "decorative": None, "rejected": 4.5}


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(TOOLS / "contrast_check.py", "contrast_check")
d01 = _load(TOOLS / "e22_d01_tape_stats.py", "e22_d01_tape_stats")


def resolve_theme(name: str) -> dict[str, Any]:
    allt: dict[str, Any] = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    out: dict[str, Any] = {}
    for k, v in allt.items():
        if isinstance(v, dict) and "$value" in v:
            raw = v["$value"]
            out[k] = verify.resolve(raw, allt) if isinstance(raw, str) else "composite"
    return out


T = {n: resolve_theme(n) for n in THEMES}


def rows_of(txt: str, sep: str = "|") -> list[list[str]]:
    return [ln.split(sep) for ln in txt.strip().splitlines()]


TOK = dict(rows_of("""canvas|color.surface.canvas
raised|color.surface.raised
sunken|color.surface.sunken
hover|color.surface.hover
selected|color.surface.selected
overlay|color.surface.overlay
t1|color.text.primary
t2|color.text.secondary
t3|color.text.tertiary
b.default|color.border.default
b.strong|color.border.strong
buy|color.buy.default
sell|color.sell.default
buy.subtle|color.buy.subtle
sell.subtle|color.sell.subtle
warn.subtle|color.status.warning.subtle"""))


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(rgb(fg), rgb(bg)))


def col(theme: str, short: str) -> str:
    return str(T[theme][TOK.get(short, short)])


# A. the matrix (spec 14): text tokens on every neutral surface, the focus stand-in, the decorative
# hairlines, and the hi-fi pairs memo 3.8 measured for E22-D03 ("D03:" rows reported, not gated).
SURF = ("canvas", "raised", "sunken", "hover", "selected", "overlay")
USE = {"t1": "words, numerics", "t2": "reason, readout", "t3": "HH:MM:, headers"}
PAIRS = [[f"{u} on {s}", t, s, "text"] for s in SURF for t, u in USE.items()]
PAIRS = [p for p in PAIRS if (p[1], p[2]) != ("t3", "selected")]
PAIRS += [[f"focus stand-in on {s}", "t1", s, "non-text"] for s in SURF]
PAIRS += rows_of("""REJECTED: dimmed prefix on the selected row|t3|selected|rejected
divider hairline, card outline|b.default|raised|decorative
live-edge divider|b.strong|raised|decorative
tier-2 band edge (glyph + weight carry)|hover|raised|decorative
D03: row text on raised|t1|raised|text
D03: dimmed HH:MM: prefix on raised|t3|raised|text
D03: Paused chip text|t1|warn.subtle|text
D03: row text on the tier-2 buy fill|t1|buy.subtle|text
D03: row text on the tier-2 sell fill|t1|sell.subtle|text
D03: tertiary prefix on buy.subtle (undimmed on tier 2)|t3|buy.subtle|text
D03: buy glyph + accent on raised|buy|raised|non-text
D03: sell glyph + accent on raised|sell|raised|non-text
D03: buy disc on canvas|buy|canvas|non-text
D03: sell square on canvas|sell|canvas|non-text""")
E13_DARK: dict[str, float] = json.loads(  # docs/design/E13/E13-D02.md 13 (dark), to the hundredth
    '{"t1|canvas": 15.20, "t2|canvas": 9.33, "t3|canvas": 5.96, "t1|raised": 14.35,'
    ' "t2|raised": 8.81, "t2|sunken": 10.69, "t3|sunken": 6.83, "t1|hover": 12.22,'
    ' "t2|hover": 7.50, "t1|selected": 10.17, "t2|selected": 6.24}'
)
MEMO_38: dict[str, list[float]] = json.loads(  # e22-tape-reading.md 3.8 (dark / light / hc)
    '{"t1|raised": [14.35, 15.62, 16.25], "t3|raised": [5.62, 5.92, 11.21],'
    ' "t1|warn.subtle": [9.86, 15.62, 11.16], "buy|canvas": [7.45, 5.03, 9.96],'
    ' "sell|canvas": [4.68, 4.85, 7.60]}'
)
# B. tape geometry: the spec's px literals (2, PROPOSED) are the inputs; row counts are printed.
FRAMES = {"1280x800": (800, 40, 24), "2560x1440": (1440, 40, 24)}  # viewport h, shell top, bottom
SLOTS = {"header": 32, "status": 28, "chips": 24, "column header": 20, "control strip": 24}
STRIP_EXPANDED = (
    80  # three 24 px rows + space.1 x 2; the default state draws the strip collapsed (24)
)
CH = {"Time": 12, "Price": 9, "Size": 6, "Notional": 6, "Side": 4, "side glyph": 1, "tier mark": 1}
MONO_EM = 0.60  # (heuristic) JetBrains Mono's nominal advance, printed as an estimate
DOM_MAX, DIVIDERS, RATES = 60, 2, (50, 500, 2000)
# D. memo 3.9: cvd_sim.py's maths as e22_d01_tape_stats.py quotes it
DEUTERANOPIA = (  # cvd_sim.py: Machado, Oliveira & Fernandes 2009 sRGB-space matrix (quoted)
    (0.367322, 0.860646, -0.227968),
    (0.280085, 0.672501, 0.047413),
    (-0.011820, 0.042940, 0.968881),
)
LUMA_601 = (0.299, 0.587, 0.114)  # cvd_sim.py: Rec. 601 greyscale weights (quoted)
MEMO_39 = rows_of(  # e22-tape-reading.md lines 227-234: token, greyscale, deuteranopia
    """color.buy.default|#878787|#9F905E
color.sell.default|#787878|#81744B
color.buy.subtle|#2C2C2C|#332E20
color.sell.subtle|#262626|#292517
color.text.primary|#EAEAEA|#E9EAED
color.text.tertiary|#929292|#8E929E
color.surface.raised|#1A1A1A|#181A22
color.surface.canvas|#141414|#12141A"""
)
MEMO_SEP = {"hue": [1.59, 1.23, 1.46], "fill": [1.18, 1.08, 1.13]}  # memo lines 238-239
# E. the engine constants, quoted as text (a changed value fails the run): name|expected
LIMITS = rows_of("""OVERFLAG_FRACTION|Decimal("0.20")
OVERFLAG_CAP_QUANTILE|0.80
OVERFLAG_MIN_SAMPLES|20
RING_BUFFER_MAX_PRINTS|50_000
VISIBLE_BUBBLES_MAX|5000
BUBBLE_FLASH_MAX_HZ|3
THRESHOLD_REFRESH_US|5_000_000
CLUSTER_WINDOW_MS_MAX_WS|2000
CLUSTER_TOLERANCE_TICKS_MAX|20""")
CONFIG = rows_of("""mode|"notional"
value|Decimal("250000")
percentile_window_ms|3_600_000
cluster_window_ms|0
cluster_tolerance_ticks|0""")
# F. every token the spec and the boards name; the last six are the DS requests and must be MISSING
NAMED_TXT = """
color.surface.app color.surface.canvas color.surface.raised color.surface.overlay
color.surface.sunken color.surface.hover color.surface.selected color.text.primary
color.text.secondary color.text.tertiary color.border.default color.border.strong color.focus.ring
color.buy.default color.sell.default color.buy.subtle color.sell.subtle color.status.warning.subtle
color.status.warning.strong color.status.info.subtle color.status.info.default
color.data-confidence.stale.text color.data-confidence.stale.indicator
color.data-confidence.gapped.text size.row.compact size.row.comfortable size.target.min
size.control.compact size.icon.sm space.1 space.2 space.3 radius.badge radius.card font.family.mono
font.size.2xs font.size.xs font.size.sm font.size.base font.size.md font.size.lg font.size.xl
font.size.2xl font.weight.medium font.weight.bold type.num.sm type.num.base type.ui.caption
type.ui.label opacity.scrim motion.duration.normal
size.bubble.scale color.chip.neutral font.mono space.filterbar.gap color.text.buy color.text.sell
"""
NAMED = NAMED_TXT.split()
EXPECT_MISSING = set(NAMED[-6:])
# G. tools/contrast/pairs.mjs: registered today; the PROPOSED tape rows (memo 3.8 -> E22-S01 / D03)
REGISTERED = rows_of("""color.text.tertiary|color.surface.app
color.buy.default|color.surface.canvas
color.sell.default|color.surface.canvas""")
PROPOSED = rows_of("""color.text.primary|color.buy.subtle|TEXT
color.text.primary|color.sell.subtle|TEXT
color.text.tertiary|color.sell.subtle|TEXT
color.buy.default|color.surface.raised|NON_TEXT
color.sell.default|color.surface.raised|NON_TEXT
color.buy.default|color.buy.subtle|NON_TEXT
color.sell.default|color.sell.subtle|NON_TEXT""")
# H. string gates: the catalogue strings, the label word, the shared contract-gap sentence, hygiene
MUST = (
    "Paused — 412 prints buffered",
    "No prints above 10 000 USDT in the last 5 min",
    "(estimated)",
)
SHARED = "Research PRs never edit `22`."
FORBIDDEN = {
    "local path": re.compile(r"/(?:home|Users)/[^/\s]+/"),
    "Penpot host": re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE),
    "Penpot team / file / workspace ref": re.compile(r"team-id=|file-id=|#/workspace"),
}
COUNT_RX = rows_of(  # the ids the spec's tables carry: what the boards and the draft quote
    r"""boards=^\| (?:0[1-9]|1[0-3]) +\| `
states=^\| S\d+
copy=^\| CP\d+
keyboard=^\| K\d+
pause_transitions=^\| P\d+
c_inherited=^\| C\d+
c_own=^\| D02-C\d+
g_inherited=^\| G\d+
g_own=^\| D02-G\d+
q=^\| Q\d+
bq=^\| BQ-\d
amendments_15=^\| A15-\d+
heuristics=^\| H-\d+
handoffs=^\| HO-\d+ """,
    "=",
)


def simulate(h: str, rendering: str) -> str:
    """cvd_sim.py's per-pixel maths on one hex (as e22_d01_tape_stats.py quotes it)."""
    c = rgb(h)
    if rendering == "greyscale":
        y = sum(v * w for v, w in zip(c, LUMA_601, strict=True))
        out: tuple[float, ...] = (y, y, y)
    else:
        out = tuple(sum(v * m for v, m in zip(c, row, strict=True)) for row in DEUTERANOPIA)
    return "#" + "".join(f"{min(255, max(0, round(v))):02X}" for v in out)


def radii(k: float) -> dict[str, float]:
    """r_min 3 -> r_max 24 px over 1x ... 4x the big threshold (memo F14, 3.5)."""
    lin, sq = 3 + 21 * (k - 1) / 3, math.sqrt(9 + 189 * (k - 1))
    return {"linear": round(lin, 1), "sqrt": round(sq, 1), "log": round(3 + 21 * math.log(k, 4), 1)}


def quoted(path: Path, pattern: str) -> str | None:
    m = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    return m.group(1).strip() if m else None


def gates(text: str, label: str, constitution: str, problems: list[str]) -> dict[str, Any]:
    missing = [s for s in MUST if s not in text]
    problems += [f"{label}: missing {s!r}" for s in missing]
    for ln in text.splitlines():
        if "Est." in ln and not re.search(r"E11-D04|E25-D05|C15|Q4", ln):
            problems.append(f"{label}: 'Est.' outside a sibling citation")
        g_row = re.match(r"^\| (?:G\d+|D02-G\d+) ", ln) and re.search(r"`2[23]`", ln)
        if g_row and SHARED not in ln:
            problems.append(f"{label}: a G-row names `22` / `23` without the shared sentence")
    hits = {name: sorted(set(rx.findall(text))) for name, rx in FORBIDDEN.items()}
    problems += [f"{label}: {name} {h!r}" for name, hs in hits.items() for h in hs]
    ids = sorted(set(re.findall(r"\bC-\d+\.\d+\b", text)))
    absent = [i for i in ids if not re.search(rf"\b{re.escape(i)}\b", constitution)]
    problems += [f"{label}: {i} not in CONSTITUTION.md" for i in absent]
    return {
        "missing": missing,
        "forbidden": {k: len(v) for k, v in hits.items()},
        "rule_ids": len(ids),
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--spec", default=str(ROOT / "docs" / "design" / "E22" / "E22-D02.md"))
    ap.add_argument("--draft", default=None)
    a = ap.parse_args(argv)
    quiet, problems, out = bool(a.json), [], {}  # type: bool, list[str], dict[str, Any]

    def say(s: str) -> None:
        if not quiet:
            print(s)

    files = [d01.file_stats(*row) for row in d01.provenance()]  # the dict e22_d01 --json prints
    w, cvd01 = d01.worked(files), d01.cvd()
    say("## A. Greyscale matrix (packages/ui/tokens; unrounded compare; 4 decimals on a bar)\n")
    say("| Element | fg | bg | role | dark | light | hc | verdict |")
    say("|---|---|---|---|---|---|---|---|")
    fails, rows, repro = 0, [], []  # type: int, list[dict[str, Any]], list[list[Any]]
    for element, fg, bg, role in PAIRS:
        vals = [ratio(col(t, fg), col(t, bg)) for t in THEMES]
        bar, d03 = BAR[role], element.startswith("D03")
        bad = [THEMES[i] for i, v in enumerate(vals) if bar is not None and v < bar]
        verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
        if bar is None:
            verdict = "decorative (not gated)"
        elif role == "rejected":
            verdict = "rejected by design; would " + verdict
        elif d03:
            verdict = "D03 inherits; " + verdict + " (not gated)"
        elif bad:
            fails += 1
        cells = " | ".join(f"{v:.4f}" if bar and abs(v - bar) < 0.005 else f"{v:.2f}" for v in vals)
        say(f"| {element} | `{TOK[fg]}` | `{TOK[bg]}` | {role} | {cells} | {verdict} |")
        r2, key = [round(v, 2) for v in vals], f"{fg}|{bg}"
        rows.append({"element": element, "fg": TOK[fg], "bg": TOK[bg], "role": role, "ratio": r2})
        if role == "text" and not d03 and key in E13_DARK:
            repro.append(["E13-D02", key, r2[0], E13_DARK[key], r2[0] == E13_DARK[key]])
        if key in MEMO_38:
            repro.append(["memo 3.8", key, r2, MEMO_38[key], r2 == MEMO_38[key]])
    n_ok = sum(1 for e in repro if e[4])
    diff = "" if n_ok == len(repro) else f" DIFF {[e for e in repro if not e[4]]}"
    say(f"\nFAIL count (gated rows only): {fails}; reproductions {n_ok}/{len(repro)} match{diff}")
    resolved = {t: {TOK[k]: col(t, k) for k in TOK} for t in THEMES}
    out["matrix"] = {"rows": rows, "fail": fails, "reproductions": repro, "resolved": resolved}

    say("\n## B. Tape geometry (spec 2 / 3 px literals; row counts printed, never asserted)\n")
    row = {d: int(T["dark"][f"size.row.{d}"]) for d in ("compact", "comfortable")}
    fs = {
        "compact": int(T["dark"]["font.size.xs"]),
        "comfortable": int(T["dark"]["font.size.base"]),
    }
    gaps, inset = (len(CH) - 1) * int(T["dark"]["space.2"]), 2 * int(T["dark"]["space.3"])
    chs = sum(CH.values())
    tape: dict[str, Any] = {"row_px": row, "font_px": fs, "slots": SLOTS, "ch": CH, "ch_total": chs}
    tape.update(
        {"mono_em": MONO_EM, "strip_expanded_px": STRIP_EXPANDED, "frames": {}, "rates": {}}
    )
    tape["rows_600"] = {d: 600 // r for d, r in row.items()}
    for name, (h, top, bottom) in FRAMES.items():
        log = h - top - bottom - sum(SLOTS.values())
        n = {d: log // r for d, r in row.items()}
        over = {d: DOM_MAX - v - DIVIDERS for d, v in n.items()}
        tape["frames"][name] = {"panel_px": h - top - bottom, "log_px": log, "rows": n}
        tape["frames"][name]["overscan"] = over
        say(f"- {name}: panel {h - top - bottom} px, log {log} px, rows {n}, overscan {over}")
    ok600 = "MATCH" if tape["rows_600"] == w["rows_visible"] else "DIFF"
    say(f"- 600 px panel: rows {tape['rows_600']} (e22_d01 {w['rows_visible']}) {ok600}")
    tape["min_width_px"] = {d: math.ceil(chs * MONO_EM * fs[d]) + gaps + inset + 2 for d in row}
    say(f"- min width = {chs} ch x {MONO_EM} em (heuristic) x font + {gaps} + {inset} + 2 px:")
    say(f"  {tape['min_width_px']}")
    for r in RATES:
        wr, pf = w["rates"][str(r)], round(r / 60, 2)
        dwell = {d: round(n_ * 1000 / r, 1) for d, n_ in tape["rows_600"].items()}
        okr = pf == wr["prints_per_frame"] and dwell["compact"] == wr["row_dwell_ms"]["compact"]
        tape["rates"][str(r)] = {"prints_per_frame": pf, "dwell_ms": dwell, "match_d01": okr}
        say(f"- {r} /s: {pf} per frame, dwell {dwell} ms; e22_d01 {'MATCH' if okr else 'DIFF'}")
    out["tape"] = tape

    say("\n## C. Bubble geometry (memo F14-F16; compared with e22_d01 worked.bubble)\n")
    bub = w["bubble"]
    rad = {k: radii(float(k)) for k in ("1", "1.5", "2", "3", "4")}
    for k, rv in rad.items():
        okk = "MATCH" if rv == bub["radii_px"][k] else "MISMATCH"
        problems += (
            [] if okk == "MATCH" else [f"radii at {k}x: {rv} vs e22_d01 {bub['radii_px'][k]}"]
        )
        say(f"- {k}x: linear {rv['linear']} / area-linear {rv['sqrt']} / log {rv['log']} px {okk}")
    side = {f"r{r}": round(r * math.sqrt(math.pi), 1) for r in (3, 10, 24)}
    geo: dict[str, Any] = {"radii": rad, "square_side_px": side, "glyph_r_px": 10}
    geo.update({"shape_floor_r_px": 5, "shape_floor_multiple": round(1 + 16 / 189, 3)})
    geo.update({"r_at_1_1x_px": round(math.sqrt(27.9), 1), "cap_outline_r_px": 27, "cap_gap_px": 2})
    geo.update({"bars_covered_at_12px": 48 // 12, "above_cap": bub["above_cap_dense"]})
    geo["flagged_below_r_pct"] = bub["shape_floor"]["flagged_below_pct"]
    say(f"- square side r*sqrt(pi) {side} (e22_d01 {bub['equal_area_square']['side_px']})")
    say(
        f"- shape floor r 5 px = {geo['shape_floor_multiple']}x (e22_d01 "
        f"{bub['shape_floor']['multiple']}); r at 1.1x {geo['r_at_1_1x_px']} px; cap outline "
        f"r + 3 = 27 px, 2 px of canvas; 24 px covers {geo['bars_covered_at_12px']} bars "
        f"at 12 px/bar"
    )
    ac = bub["above_cap_dense"]
    say(
        f"- flagged under r 4 / 5 / 10 px (dense tape, synthetic) {geo['flagged_below_r_pct']} %;"
        f" above the cap {ac['count']} of 200 000 ({100 * float(ac['fraction']):.2f} %)"
    )
    out["bubble"] = geo

    say("\n## D. Memo 3.9 reproduced (the quoted weights and matrix on the eight dark tokens)\n")
    sw: dict[str, dict[str, str]] = {}
    for tk, g_exp, d_exp in MEMO_39:
        n0 = str(T["dark"][tk])
        sw[tk] = {"normal": n0, "greyscale": simulate(n0, "greyscale")}
        sw[tk]["deuteranopia"] = simulate(n0, "deuteranopia")
        got, ds = (sw[tk]["greyscale"], sw[tk]["deuteranopia"]), cvd01["swatches"]["dark"][tk]
        okc = got == (g_exp, d_exp) and (ds["greyscale"], ds["deuteranopia"]) == got
        problems += [] if okc else [f"3.9 {tk}: {got} vs memo {(g_exp, d_exp)} / e22_d01 {ds}"]
        say(f"- `{tk}` {n0} -> {got[0]} / {got[1]} {'MATCH' if okc else 'MISMATCH'}")
    sep: dict[str, list[float]] = {}
    pairs39 = {"hue": ("color.buy.default", "color.sell.default")}
    pairs39["fill"] = ("color.buy.subtle", "color.sell.subtle")
    for sname, (x, y) in pairs39.items():
        sep[sname] = [round(ratio(sw[x][r_], sw[y][r_]), 2) for r_ in sw[x]]
        oks = "MATCH" if sep[sname] == MEMO_SEP[sname] else "MISMATCH"
        problems += (
            [] if oks == "MATCH" else [f"3.9 separation {sname}: {sep[sname]} vs {MEMO_SEP[sname]}"]
        )
        say(
            f"- buy vs sell {sname} separation (normal / greyscale / deuteranopia) {sep[sname]} "
            f"{oks}"
        )
    out["cvd"] = {"swatches": sw, "separation": sep}

    say("\n## E. The >20 % numbers (e22_d01; synthetic dense tape, shape only); quoted constants\n")
    dense = next(f for f in files if str(f["file"]).endswith("btcusdt-2026-09-01.jsonl.gz"))
    keys = ("250000", "100000", "30000", "10000", "p80", "p99")
    flagged = {k: round(100 * float(dense["flagged"][k]["fraction"]), 2) for k in keys}
    p80 = float(dense["flagged"]["p80"]["thr_usdt"])
    say(
        f"- {dense['provenance']}: flagged % {flagged}; advisory at 30 000: "
        f"{dense['flagged']['30000']['advisory']}; p80 {p80:,.2f} USDT = suggested_value -> 34 723"
    )
    consts: dict[str, str | None] = {}
    for lname, lexp in LIMITS:
        consts[lname] = quoted(ORDERFLOW / "limits.py", rf"^{lname}: Final = ([^#\n]+?)\s*(?:#|$)")
        if consts[lname] != lexp:
            problems.append(f"limits.py {lname} = {consts[lname]!r}, the spec quotes {lexp!r}")
    for cname, cexp in CONFIG:
        key, rx = "BigTradeConfig." + cname, rf"^\s+{cname}: [^=\n]+= ([^#\n]+?)\s*(?:#|$)"
        consts[key] = quoted(ORDERFLOW / "bigtrade_models.py", rx)
        if consts[key] != cexp:
            problems.append(
                f"bigtrade_models.py {cname} = {consts[key]!r}, the spec quotes {cexp!r}"
            )
    say("- quoted: " + "; ".join(f"{k} = {v}" for k, v in consts.items()))
    out["overflag"] = {"flagged_pct": flagged, "p80_usdt": p80, "suggested_value": 34723}
    out["overflag"]["constants"] = consts

    say("\n## F. Token bindings (dark / light / hc, or MISSING = a DS request)\n")
    binds = {
        nm: " / ".join(str(T[t][nm]) for t in THEMES) if nm in T["dark"] else "MISSING"
        for nm in NAMED
    }
    for nm, bv in binds.items():
        say(f"- `{nm}`: {bv}")
    missing = {k for k, v in binds.items() if v == "MISSING"}
    if missing != EXPECT_MISSING:
        problems.append(f"MISSING set changed: {sorted(missing ^ EXPECT_MISSING)}")
    sizes = ("2xs", "xs", "sm", "base", "md", "lg", "xl", "2xl")
    scale = [int(T["dark"][f"font.size.{s}"]) for s in sizes]
    out["tokens"] = {"bindings": binds, "missing": sorted(missing), "font_size_scale": scale}

    say("\n## G. tools/contrast/pairs.mjs: registered vs the PROPOSED tape rows (E22-S01 / D03)\n")
    pj = re.sub(
        r"\s+", " ", (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8")
    )
    reg = {(m[0], m[1]) for m in re.findall(r'fg: "([^"]+)", bg: "([^"]+)"', pj)}
    for fg, bg in REGISTERED:
        problems += [] if (fg, bg) in reg else [f"pairs.mjs no longer registers {fg} on {bg}"]
        say(f"- registered: `{fg}` on `{bg}`: {'yes' if (fg, bg) in reg else 'NO'}")
    for fg, bg, thr in PROPOSED:
        say(f"- PROPOSED ({thr}): `{fg}` on `{bg}`: {'registered' if (fg, bg) in reg else 'open'}")
    already = sum((p[0], p[1]) in reg for p in PROPOSED)
    out["pairs"] = {
        "registered_total": len(reg),
        "checked": len(REGISTERED),
        "proposed": len(PROPOSED),
    }
    out["pairs"]["proposed_already"] = already

    say("\n## H. String gates and the counts the boards and the draft quote\n")
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    spec_text = Path(a.spec).read_text(encoding="utf-8") if Path(a.spec).exists() else ""
    out["gates"] = {
        "spec": gates(spec_text, "spec", constitution, problems) if spec_text else "no spec"
    }
    if a.draft:
        draft_text = Path(a.draft).read_text(encoding="utf-8")
        out["gates"]["draft"] = gates(draft_text, "draft", constitution, problems)
    cnt: dict[str, int] = {k: len(re.findall(rx, spec_text, re.MULTILINE)) for k, rx in COUNT_RX}
    cnt.update({"tiers": 3, "radii": 5, "pairs_rows": len(rows), "pairs_fail": fails})
    say("- " + "; ".join(f"{k} {v}" for k, v in cnt.items()))
    out["counts"], out["problems"] = cnt, problems
    if quiet:
        print(json.dumps(out, indent=1, ensure_ascii=False))
    else:
        tail = problems + ([f"{fails} gated contrast FAIL(s)"] if fails else [])
        ok_line = (
            "OK: no gated failure; every reproduction matches; every quoted constant unchanged"
        )
        print("\n" + ("\n".join(f"PROBLEM: {p}" for p in tail) or ok_line))
    return 1 if problems or fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
