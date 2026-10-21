"""E22-D01 tape statistics over the repo's trade fixtures, with a provenance label on every row.

Standalone, offline, stdlib only. Per fixture: prints, span, prints per second, inter-print gap
(p50 / p90 / max), size and notional percentiles, and the share of prints a notional threshold
would flag (the US-BIG-002 ">20 %" check; `OVERFLAG_FRACTION` 0.20 and `OVERFLAG_MIN_SAMPLES` 20
are quoted from `orderflow/limits.py`, not imported, so this runs without the backend). Then the
worked examples the memo quotes: prints per 60 Hz frame at 50 / 500 / 2 000 prints per second
against the rows a 600 px panel holds, and the bubble radius under linear, sqrt and log scaling.
Provenance comes from metadata only: the corpus `manifest.json` `source` ("documented-shape" =
assembled, "capture_fixture.py" = recorded), the conformance `MANIFEST.toml` (`synthetic = true`)
and the big-trade golden README's `Source:` line, whose named corpus file's manifest entry decides
(the README's own word is printed beside it). No assembled or synthetic number is market evidence;
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
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "packages/fixtures/bybit/2026-10-05"
GOLDEN = ROOT / "packages/fixtures/golden/bigtrade"
BANK = ROOT / "packages/fixtures/golden/bars/conformance"
OVERFLAG_FRACTION, OVERFLAG_MIN_SAMPLES = Decimal("0.20"), 20  # orderflow/limits.py (quoted)
THRESHOLDS_USDT = (250_000, 100_000, 30_000, 10_000)  # 250 000 = the shipped default
RATES = (50, 500, 2000)  # prints/s from US-BIG-001 and the ticket, not from the fixtures
HZ, PANEL_PX, ROW_PX = 60, 600, {"compact": 24, "comfortable": 32}  # 16 §3 row heights
READ_ROWS_PER_S = {"full row (4 tokens at 238 wpm)": 1.0, "scan one token (heuristic)": 4.0}
R_MIN_PX, R_MAX_PX, N_FLOOR, N_CAP = 3.0, 24.0, 10_000.0, 1_000_000.0  # PROPOSED radius mapping
BUBBLE_NOTIONALS = (10_000, 25_000, 50_000, 100_000, 250_000, 1_000_000)
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
        frac = Decimal(sum(1 for v in notionals if v > value)) / n
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


def radius(n: float, mode: str) -> float:
    """PROPOSED mapping: r_min at the floor notional, r_max at the cap, clamped; three scalings."""
    x = min(1.0, max(0.0, (n - N_FLOOR) / (N_CAP - N_FLOOR)))
    if mode == "log":
        x = min(1.0, max(0.0, math.log(max(n, N_FLOOR) / N_FLOOR) / math.log(N_CAP / N_FLOOR)))
    elif mode == "sqrt":
        x = math.sqrt(x)
    return round(R_MIN_PX + x * (R_MAX_PX - R_MIN_PX), 1)


def worked() -> dict:
    rows = {k: PANEL_PX // v for k, v in ROW_PX.items()}
    rates = {
        str(r): {
            "prints_per_frame": round(r / HZ, 2),
            "row_dwell_ms": {k: round(1000 * v / r, 1) for k, v in rows.items()},
            "rate_over_reading": {k: round(r / v, 1) for k, v in READ_ROWS_PER_S.items()},
        }
        for r in RATES
    }
    radii = {str(n): {m: radius(n, m) for m in ("linear", "sqrt", "log")} for n in BUBBLE_NOTIONALS}
    return {"hz": HZ, "panel_px": PANEL_PX, "rows_visible": rows, "rates": rates, "radii_px": radii}


def main(argv: list[str]) -> int:
    files = [file_stats(*row) for row in provenance()]
    result = {"files": files, "worked": worked(), "reading_source": "Brysbaert 2019, 238 wpm"}
    if "--json" in argv:
        print(json.dumps(result, indent=2))
        return 0
    print("| file | provenance | prints | span s | /s | gap p50/p90/max ms | notional p50/p99/max")
    print("| flagged >250k / >10k / >p99 | p99 |\n|---|---|---:|---:|---:|---|---|---|---|")
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
            f"{fl['250000']['fraction']} / {fl['10000']['fraction']} / {fl['p99']['fraction']}",
            f"(p99 = {fl['p99']['thr_usdt']})",
        ]
        print("| " + " | ".join(str(c) for c in cells) + " |")
    w = result["worked"]
    print(f"\nRows in a {PANEL_PX} px panel: {w['rows_visible']} (16 §3 row heights)\n")
    print("| rate /s | prints per 60 Hz frame | row dwell ms | rate ÷ reading |")
    print("|---:|---:|---|---|")
    for r, v in w["rates"].items():
        print(f"| {r} | {v['prints_per_frame']} | {v['row_dwell_ms']} | {v['rate_over_reading']} |")
    print(f"\nBubble radius px, r {R_MIN_PX:g}..{R_MAX_PX:g}, floor {N_FLOOR:g}, cap {N_CAP:g}")
    print("USDT (PROPOSED)\n\n| notional USDT | linear | sqrt | log |\n|---:|---:|---:|---:|")
    for n, v in w["radii_px"].items():
        print(f"| {n} | {v['linear']} | {v['sqrt']} | {v['log']} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
