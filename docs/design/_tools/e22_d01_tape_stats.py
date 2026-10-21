"""E22-D01 tape statistics over the repo's trade fixtures, with a provenance label on every row.

Standalone, offline, stdlib only. Per fixture: prints, span, prints per second, inter-print gap
(p50 / p90 / max), size and notional percentiles, the window p80 (the engine's cap and its
`suggested_value`) and the share of prints a notional threshold would flag, counted with `>=` as
`BigTradeEngine._evaluate` does (the US-BIG-002 ">20 %" check; `OVERFLAG_FRACTION` 0.20 and
`OVERFLAG_MIN_SAMPLES` 20 are quoted from `orderflow/limits.py`, not imported, so this runs
without the backend). Then the worked examples the memo quotes: prints per 60 Hz frame at
50 / 500 / 2 000 prints per second against the rows a 600 px panel holds and the reading budget;
the bubble radius under linear, sqrt and log scaling over the range that is actually drawn (the
class's big threshold, where r_min sits, to its whale threshold at 4x, where r_max sits); and the
WCAG contrast of every tape colour pair over the real token JSON, layered per `themes.json`
(dark, light, high-contrast) with the formula of `contrast_check.py`. Provenance comes from
metadata only: the corpus `manifest.json` `source` ("documented-shape" = assembled,
"capture_fixture.py" = recorded), the conformance `MANIFEST.toml` (`synthetic = true`) and the
big-trade golden README's `Source:` line, whose named corpus file's manifest entry decides (the
README's own word is printed beside it). No assembled or synthetic number is market evidence;
the rates 50 / 500 / 2 000 are US-BIG-001's, not measured.

Usage: python3 -I docs/design/_tools/e22_d01_tape_stats.py          (Markdown)
       python3 -I docs/design/_tools/e22_d01_tape_stats.py --json   (the boards' numbers)
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import re
import sys
from collections.abc import Iterator
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "packages/fixtures/bybit/2026-10-05"
GOLDEN = ROOT / "packages/fixtures/golden/bigtrade"
BANK = ROOT / "packages/fixtures/golden/bars/conformance"
TOKENS = ROOT / "packages/ui/tokens"
OVERFLAG_FRACTION, OVERFLAG_MIN_SAMPLES = Decimal("0.20"), 20  # orderflow/limits.py (quoted)
THRESHOLDS_USDT = (250_000, 100_000, 30_000, 10_000)  # 250 000 = the shipped default
RATES = (50, 500, 2000)  # prints/s from US-BIG-001 and the ticket, not from the fixtures
HZ, PANEL_PX, ROW_PX = 60, 600, {"compact": 24, "comfortable": 32}  # 16 §3 row heights
WPM, TOKENS_FULL = 238, 5  # Brysbaert 2019; a full row = Time, Side, Size, Price, Notional
READ_ROWS_PER_S = {"full": round(WPM / 60 / TOKENS_FULL, 1), "scan": 4.0}  # scan = heuristic
R_MIN_PX, R_MAX_PX, WHALE_MULTIPLE = 3.0, 24.0, 4  # PROPOSED: r_min at big, r_max at whale (4x)
MULTIPLES = (1, 1.5, 2, 3, 4)  # of the class's big threshold; 4x = the whale threshold = the cap
CLASS_BIG = {"majors": 250_000, "mid-caps": 50_000}  # shipped value; memo 3.6 fallback (heuristic)
NEWLIST_TAPE = "newlist-2026-09-04.jsonl.gz"  # the new-listing seed = its p99 on a 1-2-5 step
CR5 = {  # E11-D02 §11.4 CR-5 `color.text.buy` / `color.text.sell`, requested, not yet a token (G7)
    "dark": ("palette.green.300", "palette.red.300"),
    "light": ("palette.light.green.700", "palette.light.red.700"),
    "high-contrast": ("palette.green.300", "palette.red.300"),
}
TEXT, NON_TEXT, DECOR = 4.5, 3.0, 0.0  # WCAG 1.4.3 text, 1.4.11 non-text, not gated
PAIRS = (  # (fg, bg, bar, use) — every colour pair the tape design (memo F4, F12, F15, F16) names
    ("color.text.primary", "color.surface.raised", TEXT, "row words and numerics, tiers 0-1"),
    ("color.text.primary", "color.buy.subtle", TEXT, "row text on the tier-2 buy fill"),
    ("color.text.primary", "color.sell.subtle", TEXT, "row text on the tier-2 sell fill"),
    ("color.text.tertiary", "color.surface.raised", TEXT, "dimmed HH:MM: prefix, tiers 0-1"),
    ("color.text.tertiary", "color.buy.subtle", TEXT, "dimmed prefix on the tier-2 buy fill"),
    ("color.text.tertiary", "color.sell.subtle", TEXT, "dimmed prefix on the tier-2 sell fill"),
    ("color.text.secondary", "color.buy.subtle", TEXT, "secondary as the tier-2 dim (alt.)"),
    ("color.text.secondary", "color.sell.subtle", TEXT, "secondary as the tier-2 dim (alt.)"),
    ("color.sell.default", "color.surface.raised", TEXT, "the side word in the side colour"),
    ("color.buy.default", "color.surface.raised", TEXT, "the side word in the side colour"),
    ("color.sell.default", "color.sell.subtle", TEXT, "side-coloured word on the tier-2 fill"),
    ("color.buy.default", "color.buy.subtle", TEXT, "side-coloured word on the tier-2 fill"),
    ("CR5:text.sell", "color.surface.raised", TEXT, "E11-D02 CR-5 text.sell, if it lands (G7)"),
    ("CR5:text.buy", "color.surface.raised", TEXT, "E11-D02 CR-5 text.buy, if it lands (G7)"),
    ("CR5:text.sell", "color.sell.subtle", TEXT, "CR-5 text.sell on the tier-2 fill"),
    ("CR5:text.buy", "color.buy.subtle", TEXT, "CR-5 text.buy on the tier-2 fill"),
    ("color.text.primary", "color.status.warning.subtle", TEXT, "the Paused chip"),
    ("color.buy.default", "color.surface.raised", NON_TEXT, "glyphs + 2 px accent, tiers 0-1"),
    ("color.sell.default", "color.surface.raised", NON_TEXT, "glyphs + 2 px accent, tiers 0-1"),
    ("color.buy.default", "color.buy.subtle", NON_TEXT, "glyphs on the tier-2 buy fill"),
    ("color.sell.default", "color.sell.subtle", NON_TEXT, "glyphs on the tier-2 sell fill"),
    ("color.buy.default", "color.surface.canvas", NON_TEXT, "bubble disc (in pairs.mjs)"),
    ("color.sell.default", "color.surface.canvas", NON_TEXT, "bubble ring (in pairs.mjs)"),
    ("color.buy.subtle", "color.surface.raised", DECOR, "tier-2 fill edge (glyph + weight carry)"),
    ("color.sell.subtle", "color.surface.raised", DECOR, "tier-2 fill edge (glyph + weight carry)"),
)
Print = tuple[int, Decimal, Decimal]  # ts_us, price, qty


def load_prints(path: Path) -> list[Print]:
    """Three layouts: Bybit publicTrade frames, the golden csv, a conformance tape."""
    out: list[Print] = []
    with gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open() as fh:
        if path.name.endswith(".csv.gz"):
            for r in csv.DictReader(fh):
                out.append((int(r["ts_event_us"]), Decimal(r["price"]), Decimal(r["qty"])))
        else:
            for line in fh:
                o = json.loads(line)
                for t in o.get("data", [o]):  # a frame holds prints (T ms, p, v); a tape row is one
                    ts = int(t["T"]) * 1000 if "T" in t else int(t["ts"])
                    px, qty = t.get("p", t.get("price")), t.get("v", t.get("size"))
                    out.append((ts, Decimal(px), Decimal(qty)))
    return sorted(out)


def pct(vals: list, q: float):
    """Nearest-rank percentile over an ascending list (deterministic, no interpolation)."""
    return vals[min(len(vals) - 1, max(0, math.ceil(q / 100 * len(vals)) - 1))]


def step125(v: Decimal) -> int:
    """Nearest 1-2-5 step (the seed rounding of memo 3.6): 1 732 -> 2 000, 71 -> 50."""
    e = 10 ** (len(str(int(v))) - 1)
    return min((m * e for m in (1, 2, 5, 10)), key=lambda s: abs(s - v))


def label(source: str) -> str:
    return "recorded" if source.startswith("capture_fixture") else "assembled"


def provenance() -> list[tuple[Path, str, str]]:
    """(file, label, note) for every trade fixture, from the metadata files only."""
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    src = {e["path"]: e["source"] for e in manifest["fixtures"]}
    items = sorted(src.items())
    rows = [(CORPUS / p, label(s), f"manifest: {s}") for p, s in items if "Trade" in p]
    readme = (GOLDEN / "README.md").read_text(encoding="utf-8")
    m = re.search(r"Source: (\w+) corpus\s+`bybit/2026-10-05/([^`]+)`", readme)
    word, gsrc = (m.group(1), src.get(m.group(2), "?")) if m else ("?", "?")
    note = f"README says '{word}'; manifest: {gsrc}"
    rows.append((GOLDEN / "trades_BTCUSDT.csv.gz", label(gsrc), note))
    for block in (BANK / "MANIFEST.toml").read_text(encoding="utf-8").split("[[tape]]")[1:]:
        f = re.search(r'^file = "(.+)"', block, re.MULTILINE)
        d = re.search(r'^description = "(.+)"', block, re.MULTILINE)
        syn = "synthetic" if re.search(r"^synthetic = true", block, re.MULTILINE) else "unknown"
        if f:
            rows.append((ROOT / f.group(1), syn, d.group(1) if d else ""))
    return rows


def file_stats(path: Path, prov: str, note: str) -> dict:
    prints = load_prints(path)
    n = len(prints)
    span_s = (prints[-1][0] - prints[0][0]) / 1e6 if n > 1 else 0.0
    gaps = sorted((b[0] - a[0]) / 1000 for a, b in pairwise(prints))
    sizes = sorted(p[2] for p in prints)
    notionals = sorted(p[1] * p[2] for p in prints)
    flagged = {}
    for thr in (*THRESHOLDS_USDT, 99, 80):  # absolute USDT values, then the p99 and p80 modes
        value = pct(notionals, thr) if thr <= 100 else Decimal(thr)
        frac = Decimal(sum(1 for v in notionals if v >= value)) / n  # `>=`, as the engine flags
        advisory = n >= OVERFLAG_MIN_SAMPLES and frac > OVERFLAG_FRACTION
        key = f"p{thr}" if thr <= 100 else str(thr)
        flagged[key] = {"thr_usdt": str(value), "fraction": f"{frac:.4f}", "advisory": advisory}
    q3 = (("p50", 50), ("p90", 90), ("p99", 99))
    return {
        "file": str(path.relative_to(ROOT)),
        "provenance": prov,
        "note": note,
        "prints": n,
        "span_s": round(span_s, 1),
        "prints_per_s": round(n / span_s, 3) if span_s else None,
        "gap_ms": {"p50": pct(gaps, 50), "p90": pct(gaps, 90), "max": gaps[-1]} if gaps else None,
        "size": {k: str(pct(sizes, q)) for k, q in q3} | {"max": str(sizes[-1])},
        "notional_usdt": {k: str(pct(notionals, q)) for k, q in q3} | {"max": str(notionals[-1])},
        "flagged": flagged,
    }


def radius(k: float, mode: str) -> float:
    """PROPOSED: r_min at 1x the class's big threshold, r_max at the whale (4x), clamped above.

    With the cap at 4x big for every class, the radius depends only on the multiple k."""
    x = min(1.0, max(0.0, (k - 1) / (WHALE_MULTIPLE - 1)))
    if mode == "log":
        x = min(1.0, math.log(max(k, 1.0)) / math.log(WHALE_MULTIPLE))
    elif mode == "sqrt":
        x = math.sqrt(x)
    return round(R_MIN_PX + x * (R_MAX_PX - R_MIN_PX), 1)


def worked(files: list[dict]) -> dict:
    rows = {k: PANEL_PX // v for k, v in ROW_PX.items()}
    rates = {
        str(r): {
            "prints_per_frame": round(r / HZ, 2),
            "row_dwell_ms": {k: round(1000 * v / r, 1) for k, v in rows.items()},
            "rate_over_reading": {k: round(r / v, 1) for k, v in READ_ROWS_PER_S.items()},
        }
        for r in RATES
    }
    newlist = next(f for f in files if f["file"].endswith(NEWLIST_TAPE))
    big = CLASS_BIG | {"new listing (seed)": step125(Decimal(newlist["notional_usdt"]["p99"]))}
    classes = {
        k: {"big": v, "whale": v * WHALE_MULTIPLE, "at": {str(m): round(v * m) for m in MULTIPLES}}
        for k, v in big.items()
    }
    radii = {str(m): {s: radius(m, s) for s in ("linear", "sqrt", "log")} for m in MULTIPLES}
    gap = {
        a + "-" + b: round(max(abs(v[a] - v[b]) for v in radii.values()), 1)
        for a, b in (("sqrt", "log"), ("linear", "sqrt"))
    }
    bubble = {
        "r_min_px": R_MIN_PX,
        "r_max_px": R_MAX_PX,
        "whale_multiple": WHALE_MULTIPLE,
        "newlist_p99_usdt": newlist["notional_usdt"]["p99"],
        "classes": classes,
        "radii_px": radii,
        "max_gap_px": gap,
        "ink_cap_over_floor": round((R_MAX_PX / R_MIN_PX) ** 2),  # the same under every law
    }
    reading = {"wpm": WPM, "tokens_full": TOKENS_FULL, "rows_per_s": READ_ROWS_PER_S}
    return {
        "hz": HZ,
        "panel_px": PANEL_PX,
        "rows_visible": rows,
        "reading": reading,
        "rates": rates,
        "bubble": bubble,
    }


def _leaves(o: object, path: tuple[str, ...] = ()) -> Iterator[tuple[str, object]]:
    if isinstance(o, dict):
        if "$value" in o:
            yield ".".join(path), o["$value"]
        else:
            for k, v in o.items():
                if not k.startswith("$"):
                    yield from _leaves(v, (*path, k))


def palette() -> dict[str, dict[str, object]]:
    """Per theme, the token sets of themes.json layered in order (a later set overrides)."""
    cfg = json.loads((TOKENS / "themes.json").read_text(encoding="utf-8"))["themes"]
    out: dict[str, dict[str, object]] = {}
    for t in cfg:
        flat: dict[str, object] = {}
        for s in t["sets"]:
            doc = json.loads((TOKENS / f"{s}.tokens.json").read_text(encoding="utf-8"))
            flat.update(_leaves(doc))
        out[t["name"]] = flat
    return out


def hexof(flat: dict[str, object], name: str, theme: str) -> str:
    """Resolve `{alias}` chains to a hex; `CR5:` names stand for E11-D02's requested tokens."""
    if name.startswith("CR5:"):
        name = CR5[theme][0 if name.endswith("buy") else 1]
    v = flat[name]
    while isinstance(v, str) and v.startswith("{"):
        v = flat[v[1:-1]]
    return str(v)


def _lin(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def ratio(fg: str, bg: str) -> float:
    """WCAG 2.x contrast ratio, the formula of contrast_check.py (relative luminance)."""
    lum = []
    for h in (fg, bg):
        r, g, b = (int(h[i : i + 2], 16) for i in (1, 3, 5))
        lum.append(0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b))
    return round((max(lum) + 0.05) / (min(lum) + 0.05), 2)


def contrast() -> list[dict]:
    pal = palette()
    out = []
    for fg, bg, bar, use in PAIRS:
        ratios = {th: ratio(hexof(f, fg, th), hexof(f, bg, th)) for th, f in pal.items()}
        verdict = "decorative (not gated)" if not bar else "PASS"
        failed = [th for th, v in ratios.items() if bar and v < bar]
        if failed:
            verdict = "FAIL " + ", ".join(failed)
        row = {"fg": fg, "bg": bg, "bar": bar, "use": use, "ratio": ratios, "verdict": verdict}
        out.append(row)
    return out


def main(argv: list[str]) -> int:
    files = [file_stats(*row) for row in provenance()]
    result = {
        "files": files,
        "worked": worked(files),
        "contrast": contrast(),
        "reading_source": "Brysbaert 2019, 238 wpm",
    }
    if "--json" in argv:
        print(json.dumps(result, indent=2))
        return 0
    print("| file | provenance | prints | span s | /s | gap p50/p90/max ms | notional p50/p99/max")
    print("| flagged >=250k / >=10k / >=30k | p99 / p80 USDT | advisory at 30k |")
    print("|---|---|---:|---:|---:|---|---|---|---|---|")
    for f in files:
        g, nt, fl = f["gap_ms"] or {}, f["notional_usdt"], f["flagged"]
        cells = [
            f"`{f['file']}`",
            f"**{f['provenance']}** ({f['note']})",
            f["prints"],
            f["span_s"],
            f["prints_per_s"],
            f"{g.get('p50')} / {g.get('p90')} / {g.get('max')}",
            f"{nt['p50']} / {nt['p99']} / {nt['max']}",
            f"{fl['250000']['fraction']} / {fl['10000']['fraction']} / {fl['30000']['fraction']}",
            f"{fl['p99']['thr_usdt']} / {fl['p80']['thr_usdt']}",
            "strip" if fl["30000"]["advisory"] else "none",
        ]
        print("| " + " | ".join(str(c) for c in cells) + " |")
    w = result["worked"]
    print(f"\nRows in a {PANEL_PX} px panel: {w['rows_visible']} (16 §3 row heights); reading")
    print(f"{w['reading']}\n\n| rate /s | prints per 60 Hz frame | row dwell ms | rate / reading |")
    print("|---:|---:|---|---|")
    for r, v in w["rates"].items():
        print(f"| {r} | {v['prints_per_frame']} | {v['row_dwell_ms']} | {v['rate_over_reading']} |")
    b = w["bubble"]
    print(f"\nBubble radius px (PROPOSED): r {R_MIN_PX:g} at 1x the class's big threshold,")
    print(f"{R_MAX_PX:g} at {WHALE_MULTIPLE}x = the whale threshold, clamped above; max gap px")
    print(f"{b['max_gap_px']}; cap/floor ink {b['ink_cap_over_floor']}x under every law\n")
    print("| class | big | whale | " + " | ".join(f"{m}x USDT" for m in b["radii_px"]) + " |")
    print("|---|---:|---:|" + "---:|" * len(MULTIPLES))
    for k, c in b["classes"].items():
        at = " | ".join(str(v) for v in c["at"].values())
        print(f"| {k} | {c['big']} | {c['whale']} | {at} |")
    print("\n| multiple of big | linear | sqrt | log |\n|---:|---:|---:|---:|")
    for m, v in b["radii_px"].items():
        print(f"| {m}x | {v['linear']} | {v['sqrt']} | {v['log']} |")
    print("\n| pair (fg on bg) | use | bar | dark | light | hc | verdict |")
    print("|---|---|---:|---:|---:|---:|---|")
    for p in result["contrast"]:
        r, bar = p["ratio"], f"{p['bar']:g}:1" if p["bar"] else "-"
        print(
            f"| `{p['fg']}` on `{p['bg']}` | {p['use']} | {bar} | {r['dark']:.2f} | "
            f"{r['light']:.2f} | {r['high-contrast']:.2f} | {p['verdict']} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
