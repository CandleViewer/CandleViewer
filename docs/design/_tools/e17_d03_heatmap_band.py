"""E17-D03 heatmap column legibility band: the `23` §6.1.1 arithmetic reproduced, plus the stimuli.

Standalone, offline, stdlib only; `Decimal` for every ratio and byte count, so two runs agree to
the digit. Every input is a planning assumption quoted from its owner (named per constant): the
formula, ladder, clamp and fallback of `docs/plan/23-ws-protocol.md` §6.1.1 with its six reference
rows, the seven clamp-boundary cases of `services/api/tests/contract/ws/test_ws_contract.py`
(quoted, never imported; exit 1 when the tool's selections differ from either), the body_kind 6 row
layout of `23` §3.4, the 2 000-column snapshot cap and the §16.3 budget. It adds the column §6.1.1
omits: the effective device px per column at the selected rung, and at the unclamped one. The
stimuli are synthetic (no recorded heatmap data exists in the repo): one palette PNG per (pane, px
per column) at full device resolution, no text, no time chunk, byte-identical across runs (a fixed
LCG seeded 250); colours are the dark theme's `color.heatmap.*` tokens from `packages/ui/tokens`.
No display was viewed by this tool or its author; the owner opens each PNG at 1:1.

Usage: python3 -I docs/design/_tools/e17_d03_heatmap_band.py [--json] [--png-dir <dir>]
"""

from __future__ import annotations

import argparse
import binascii
import json
import struct
import sys
import zlib
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from pathlib import Path

D = Decimal
TOKENS = Path(__file__).resolve().parents[3] / "packages/ui/tokens"
WINDOW_S, DIVISOR, LADDER = 900, 3, (100, 250, 500, 1000, 5000)  # 23 §6.1.1 formula and ladder
CLAMP_MS, CLAMP_IDEAL_MAX_MS, FALLBACK_MS = 1000, 2500, 500  # 23 §6.1.1 clamp; server fallback
BAND_PX, TARGET_PX = (D(2), D(8)), D(3)  # the two numbers design owns (23 §6.1.1 "Design review")
# fmt: off
ROWS = (  # 23 §6.1.1 reference rows: display, pane CSS px, DPR, device px, ideal_ms, rung, selected
    ("4 K, 100 % scale (3840)", 2380, "1", 2380, 1134, 5000, 1000),
    ("4 K, 150 % scale (2560 CSS)", 1587, "1.5", 2380, 1134, None, 1000),
    ("2 560 x 1 440", 1587, "1", 1587, 1701, 5000, 1000),
    ("1 920 x 1 080", 1190, "1", 1190, 2269, 5000, 1000),
    ('MacBook 14" (1512 CSS)', 937, "2", 1874, 1441, None, 1000),
    ("Half-width pane, 1 920", 595, "1", 595, 4538, None, 5000),
)
EXTRA = (("16 §8 minimum viewport 1 280 (62 % pane)", 794, "1"),)  # not a §6.1.1 row; added here
BOUNDARY = ((2500, 1000), (2500.1, 5000), (1000, 1000), (1000.1, 1000), (500, 500), (50, 100),
            (6000, 5000))  # test_ws_contract.py test_heatmap_bucket_selection_ladder_clamp_boundary
ROWS_PER_COLUMN = 400  # 23 §6.1.1 "~400 populated price rows/column"
BYTES_PER_ROW = {"23 §6.1.1 table (4 B)": 4, "23 §3.4 kind 6 (16 B)": 16}  # u64 bid + u64 ask
SNAPSHOT_CAP_COLUMNS, SNAPSHOT_BUDGET_KIB = 2000, 700  # 23 §6.1.1 cap; §16.3 "< 700 KiB"
PANES = {"4k": 2380, "1080p": 1190, "half": 595}  # device px: §6.1.1 rows 1, 4 and 6
# The committed stimuli: (pane, px-per-column label) -> columns in the window; None = exact integer
# columns (pane // width, the remainder left at zero); a number = that rung's columns over the pane.
STIMULI: dict[tuple[str, str], int | None] = {
    ("4k", "2"): None, ("4k", "2.6"): 900, ("4k", "3"): None, ("4k", "4"): None, ("4k", "6"): None,
    ("4k", "8"): None, ("1080p", "1.3"): 900, ("1080p", "1.8"): 675, ("1080p", "2"): None,
    ("1080p", "3"): None, ("1080p", "4"): None, ("1080p", "6"): None, ("1080p", "6.6"): 180,
    ("1080p", "8"): None, ("half", "3.3"): 180,
}
PRICE_ROWS, ROW_PX, NOISE = 200, 2, D("0.15")  # depth-200 rows at 2 device px; noise share
BAND, CORE, GAP = (130, 136), (132, 134), (D("0.55"), D("0.60"))  # bid band rows and its gap share
ASK_BAND, ASK_CORE, ASK_GAP = (64, 70), (66, 68), (D("0.30"), D("0.34"))  # the mirrored ask band
WALL_ROWS, WALL_AT = (150, 158), D("0.72")  # one bright column of 8 rows at 72 % of the window
SIDES = ("bid", "ask")
NAMES = ["color.heatmap.zero"] + [f"color.heatmap.{s}.{i}" for s in SIDES for i in (1, 2, 3, 4, 5)]
# fmt: on


def q(v: Decimal, places: str = "0.01") -> str:
    return str(v.quantize(D(places), rounding=ROUND_HALF_UP))


def ideal(css: Decimal | int, dpr: str) -> Decimal:
    return D(WINDOW_S * 1000) / (D(css) * D(dpr) / DIVISOR)


def rung(ideal_ms: Decimal) -> int:
    return next((r for r in LADDER if r >= ideal_ms), LADDER[-1])


def select(ideal_ms: Decimal) -> int:  # the normative upward clamp (23 §6.1.1 footnote)
    r = rung(ideal_ms)
    return CLAMP_MS if r == LADDER[-1] and ideal_ms <= CLAMP_IDEAL_MAX_MS else r


def px_per_col(device_px: int, bucket_ms: int) -> Decimal:
    return D(device_px) * bucket_ms / (WINDOW_S * 1000)


def row(display: str, css: int, dpr: str, device: int, in_doc: bool) -> dict[str, object]:
    i = ideal(css, dpr)
    r, s = rung(i), select(i)
    px = px_per_col(device, s)
    # fmt: off
    return {"display": display, "pane_css_px": css, "dpr": dpr, "device_px": device,
            "ideal_ms": q(i, "0.1"), "rung_ms": r, "selected_ms": s, "clamped": r != s,
            "columns_in_window": WINDOW_S * 1000 // s, "px_per_col_selected": q(px),
            "px_per_col_unclamped": q(px_per_col(device, r)),
            "in_band": BAND_PX[0] <= px <= BAND_PX[1], "in_23_6_1_1": in_doc}
    # fmt: on


def reference(errors: list[str]) -> list[dict[str, object]]:
    out = []
    for display, css, dpr, device, ideal_doc, rung_doc, sel_doc in ROWS:
        i = ideal(css, dpr)
        got = (D(css) * D(dpr), int(q(i, "1")), rung(i), select(i))
        ok = abs(got[0] - device) <= D("0.5") and got[1] == ideal_doc and got[3] == sel_doc
        if not ok or rung_doc not in (None, got[2]):
            errors.append(f"23 §6.1.1 row {display!r}: tool device/ideal/rung/selected {got}")
        out.append(row(display, css, dpr, device, True))
    return out + [row(d, c, p, int(q(D(c) * D(p), "1")), False) for d, c, p in EXTRA]


def boundary(errors: list[str]) -> list[dict[str, object]]:
    out = []
    for ideal_doc, expected in BOUNDARY:
        css = D(WINDOW_S * 1000) / D(str(ideal_doc)) * DIVISOR  # the DPR-1 pane yielding ideal_doc
        got = select(ideal(css, "1"))
        if got != expected:
            errors.append(f"boundary ideal {ideal_doc}: tool {got}, the test expects {expected}")
        out.append({"ideal_ms": str(ideal_doc), "pane_css_px_dpr1": q(css), "selected_ms": got})
    return out


def bandwidth() -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for b in LADDER:
        per_s, cols = D(1000) / b, WINDOW_S * 1000 // b
        sent = min(cols, SNAPSHOT_CAP_COLUMNS)
        r: dict[str, object] = {"bucket_ms": b, "columns_per_s": q(per_s, "0.1")}
        r |= {"columns_in_window": cols, "snapshot_capped": sent < cols}
        for name, bpr in BYTES_PER_ROW.items():
            cb = ROWS_PER_COLUMN * bpr
            # fmt: off
            r[name] = {"kib_per_s": q(per_s * cb / 1024, "0.1"),
                       "window_mib": q(D(cols * cb) / 2**20, "0.1"),
                       "snapshot_mib": q(D(sent * cb) / 2**20, "0.1"),
                       "snapshot_under_700_kib": sent * cb < SNAPSHOT_BUDGET_KIB * 1024}
            # fmt: on
        out.append(r)
    return out


def tokens_dark() -> dict[str, str]:
    """`themes.json` dark = primitives then semantic-dark; `{alias}` chains resolved to hex."""
    flat: dict[str, object] = {}
    todo: list[tuple[str, object]] = []
    for name in ("primitives", "semantic-dark"):
        todo.append(("", json.loads((TOKENS / f"{name}.tokens.json").read_text(encoding="utf-8"))))
    while todo:
        path, o = todo.pop()
        if isinstance(o, dict) and "$value" in o:
            flat[path] = o["$value"]
        elif isinstance(o, dict):
            todo += [(f"{path}.{k}".strip("."), v) for k, v in o.items() if not k.startswith("$")]

    def hexof(name: str) -> str:
        v = flat[name]
        while isinstance(v, str) and v.startswith("{"):
            v = flat[v[1:-1]]
        return str(v)

    return {n: hexof(n) for n in NAMES}


def geometry(pane: str, label: str, n: int | None) -> tuple[list[int], dict[str, object]]:
    width = PANES[pane]
    cols = n or width // int(label)
    edges = [i * int(label) if n is None else i * width // cols for i in range(cols + 1)]
    widths = [b - a for a, b in pairwise(edges)]
    wall = next(i for i in range(int(cols * WALL_AT), cols) if widths[i] == min(widths))
    gaps = [[int(cols * g[0]), int(cols * g[1])] for g in (GAP, ASK_GAP)]
    # fmt: off
    info: dict[str, object] = {
        "file": f"E17-D03-stim-{pane}-{label}px.png", "pane": pane, "pane_device_px": width,
        "px_per_col": label, "px_per_col_exact": q(D(edges[-1]) / cols), "columns": cols,
        "column_px_min_max": [min(widths), max(widths)], "wall_column": wall,
        "wall_px": widths[wall], "wall_rows": list(WALL_ROWS), "band_rows": list(BAND),
        "band_gap_columns": gaps[0], "ask_band_rows": list(ASK_BAND), "ask_gap_columns": gaps[1],
    }
    # fmt: on
    return edges, info


def chunk(kind: bytes, body: bytes) -> bytes:
    crc = binascii.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def render(path: Path, edges: list[int], info: dict[str, object], hexes: dict[str, str]) -> int:
    """Palette PNG, 8-bit indices into the eleven tokens; filter 0, then Up for the duplicate."""
    bid, ask = list(range(1, 6)), list(range(6, 11))  # NAMES order: zero, bid.1..5, ask.1..5
    width, cols, wall = PANES[str(info["pane"])], len(edges) - 1, int(str(info["wall_column"]))
    gaps = [info["band_gap_columns"], info["ask_gap_columns"]]
    gap, agap = (x if isinstance(x, list) else [0, 0] for x in gaps)
    state, cut, raw = 250, int(NOISE * 2**24), bytearray()  # a 64-bit LCG seeded 250: no library
    for r in range(PRICE_ROWS):
        line, below = bytearray(width), r >= PRICE_ROWS // 2  # bids below the mid line, asks above
        for i in range(cols):
            state = (state * 6364136223846793005 + 1442695040888963407) % 2**64
            v = (bid[0] if below else ask[0]) if state >> 40 < cut else 0
            if below and BAND[0] <= r < BAND[1] and not gap[0] <= i < gap[1]:
                v = bid[3] if CORE[0] <= r < CORE[1] else bid[2]
            if not below and ASK_BAND[0] <= r < ASK_BAND[1] and not agap[0] <= i < agap[1]:
                v = ask[3] if ASK_CORE[0] <= r < ASK_CORE[1] else ask[2]
            if below and WALL_ROWS[0] <= r < WALL_ROWS[1] and i == wall:
                v = bid[4]
            if v:
                line[edges[i] : edges[i + 1]] = bytes([v]) * (edges[i + 1] - edges[i])
        raw += b"\x00" + line + (b"\x02" + bytes(width)) * (ROW_PX - 1)
    ihdr = struct.pack(">IIBBBBB", width, PRICE_ROWS * ROW_PX, 8, 3, 0, 0, 0)
    plte = b"".join(bytes.fromhex(hexes[n][1:]) for n in NAMES)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"PLTE", plte)
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)
    return len(png)


def table(rows: list[dict[str, object]], cols: list[str]) -> None:
    print(f"\n| {' | '.join(cols)} |\n|" + "---|" * len(cols))
    print("\n".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E17-D03 heatmap band arithmetic and stimuli")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--png-dir", type=Path)
    a = ap.parse_args(argv)
    errors: list[str] = []
    stim = [geometry(p, lb, n) for (p, lb), n in STIMULI.items()]
    ref, bw = reference(errors), bandwidth()
    # fmt: off
    data: dict[str, object] = {
        "band_px": [str(b) for b in BAND_PX], "target_px": str(TARGET_PX), "window_s": WINDOW_S,
        "divisor": DIVISOR, "ladder_ms": list(LADDER), "clamp_ms": CLAMP_MS,
        "clamp_ideal_max_ms": CLAMP_IDEAL_MAX_MS, "fallback_ms": FALLBACK_MS, "reference": ref,
        "boundary": boundary(errors), "bandwidth": bw, "tokens_dark": tokens_dark(),
        "clamp_boundary_pane_css_px": {d: q(D(1080) / D(d), "1") for d in ("1", "1.5", "2")},
        "stimuli": [s[1] for s in stim],
        "provenance": "planning assumptions from 23 §3.4, §6.1.1, §16.3 and the contract test; "
                      "synthetic stimuli, no recorded book data, no display viewed",
    }
    # fmt: on
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    if a.png_dir:
        a.png_dir.mkdir(parents=True, exist_ok=True)
        hexes = tokens_dark()
        for edges, info in stim:
            info["bytes"] = render(a.png_dir / str(info["file"]), edges, info, hexes)
    if a.json:
        print(json.dumps(data, indent=2))
        return 0
    table(ref, [k for k in ref[0] if k not in ("clamped", "in_23_6_1_1")])
    kib = "{kib_per_s} KiB/s, snapshot {snapshot_mib} MiB"
    flat = [{k: kib.format(**v) if isinstance(v, dict) else v for k, v in r.items()} for r in bw]
    table(flat, list(flat[0]))
    table([s[1] for s in stim], [k for k in stim[0][1] if "rows" not in k and "gap" not in k])
    print(f"\nclamp boundary pane CSS px per DPR {data['clamp_boundary_pane_css_px']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
