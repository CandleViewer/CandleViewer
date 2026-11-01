#!/usr/bin/env python3
"""E19-D01 (#382) audit: the profiles UX-research memo and its worked numbers.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads
the plan texts AS TEXT at the pinned base (`git show BASE:<path>`), the recorded BTCUSDT
fixtures and the token JSON from the working tree, and the memo from the working tree. Nothing
it prints is user evidence: the fixtures are documented-shape files, not live captures.

Modes (default-deny: a gate passes only on what it positively recognises):

  --json       the worked numbers the memo quotes (section 4): a bar-approximated profile of the
               kline fixture under two allocation rules, the tick profile of the trade fixture,
               the row-density arithmetic and the profile tokens' contrast under normal,
               greyscale and deuteranopia renderings (cvd_sim.py's maths, contrast_check.py's
               formula).
  --check      every gate over the memo; prints one PASS or FAIL line per gate; exit 1 on FAIL.
  --self-test  applies each mutation M-n to the memo text in memory; each must add exactly one
               FAIL from the gate it names; the file on disk is verified byte-identical after.

Gates: G-CITE (every `KEY` :line cite resolves to a non-blank line at BASE), G-QUOTE (every
curly-quoted string of QUOTE_MIN characters or more is verbatim in a file its line cites),
G-AC (the AC trace has AC 1-5 and the DoD rows, each with a known status), G-LEVELS (the level
table has the ten rows, each complete), G-PD (6-10 decisions, each with PASS/FAIL checks, a
finding, a target ticket and PROPOSED), G-HEUR (every finding is `(heuristic)`; no participant,
quote or timing lexicon outside the protocol), G-COMP (every competitive row has a URL and a
fetched date, or says "unsourced observation"), G-IMG (no image is committed in the text leg),
G-MARKER (every HTML comment is an `audit:` value the tool recomputes), G-BQ (the BQ section
names every BQ and the ruling of record, with no pending line left), G-PUBLIC (no local path,
host or worker name), G-PIN (the memo's pin line names BASE as its 12-character short sha and the
memo holds no 40-hex string: a full sha beside a vendor word trips the secret scanners) and
G-UNTOUCHED (only the memo and this tool differ from BASE; no plan document: the ruling makes
every amendment an A-row). G-PUBLIC scans the memo and this file. G-COMP checks only that a vendor row carries a
URL and a fetched date: the accuracy of a vendor quote is checked by hand, not by this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
BASE = "ca49e693ae45512d77dbf7e16daf15dea79775a2"
MEMO_REL = "docs/design/research/e19-profiles.md"
TOOL_REL = "docs/design/_tools/e19_d01_profiles_audit.py"
SCREENS_REL = "docs/plan/14-screens-catalogue.md"
MEMO = ROOT / MEMO_REL
CORPUS = ROOT / "packages/fixtures/bybit/2026-10-05"
TOKENS = ROOT / "packages/ui/tokens"
BQ_COMMENT = "6563727875"
# The orchestrator's ruling of record on the BQ list (ruled pin).
RULING_COMMENT = "6563817073"

KEYS: dict[str, str] = {  # the cite keys the memo declares in its key line
    "05": "docs/plan/05-accessibility-standard.md",
    "10": "docs/plan/10-personas.md",
    "11": "docs/plan/11-user-stories.md",
    "14": SCREENS_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
    "26": "docs/plan/26-chart-engine-design.md",
    "README": "docs/design/README.md",
    "E16-D05": "docs/design/E16/E16-D05.md",
    "E18-D02": "docs/design/E18/E18-D02.md",
    "digest-01": "docs/research/digests/01-tradingview-charting.digest.md",
    "digest-04": "docs/research/digests/04-deepcharts-deepchart.digest.md",
}
CORE = ("11", "14", "15", "24")  # a quote may also come from these without a same-line cite
QUOTE_MIN = 12

# --- worked numbers -------------------------------------------------------------------------
TICK = Decimal("0.10")  # instruments_after.json BTCUSDT priceFilter.tickSize (read, asserted)
VA_PCT = Decimal("0.70")  # `24` :1009 default; `22` :4874 default 70
AGGREGATIONS = (1, 10, 25, 50)  # row sizes in ticks for the density ladder
PANE_PX = (320, 480, 640)  # example pane heights (assumed, not sourced; the memo says so)
MERGE_FLOOR_PX = 2  # `26` :238 rows merge when < 2 px tall
LABEL_FLOOR_PX = 10  # `05` :208 the one-number canvas text floor (footprint; the only frozen one)
ROW_PX = {"compact": 24, "comfortable": 32}  # `16` :129-130
LUMA_601 = (0.299, 0.587, 0.114)  # cvd_sim.py Rec. 601 weights (quoted)
DEUTERANOPIA = (  # cvd_sim.py Machado, Oliveira & Fernandes 2009 sRGB matrix (quoted)
    (0.367322, 0.860646, -0.227968),
    (0.280085, 0.672501, 0.047413),
    (-0.011820, 0.042940, 0.968881),
)
NON_TEXT = 3.0  # WCAG 1.4.11 against the background and against an adjacent colour
PROFILE_TOKENS = ("color.profile.bar", "color.profile.poc", "color.profile.valuearea")
BACKGROUNDS = ("color.surface.canvas", "color.surface.raised")
PAIRS = (  # (a, b, use) adjacent-colour pairs inside one profile
    ("color.profile.poc", "color.profile.valuearea", "POC row inside the value area"),
    ("color.profile.valuearea", "color.profile.bar", "value-area rows vs rows outside it"),
    ("color.profile.poc", "color.profile.bar", "POC row vs a row outside the value area"),
)
RENDERINGS = ("normal", "greyscale", "deuteranopia")

Level = int
Profile = dict[Level, Decimal]


def klines() -> list[tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal]]:
    """The three kline pages, oldest first: (open_ms, open, high, low, close, volume)."""
    rows: list[tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal]] = []
    for i in range(3):
        doc = json.loads((CORPUS / f"rest/kline_BTCUSDT_1_page{i}.json").read_text("utf-8"))
        for r in doc["result"]["list"]:
            rows.append(
                (
                    int(r[0]),
                    Decimal(r[1]),
                    Decimal(r[2]),
                    Decimal(r[3]),
                    Decimal(r[4]),
                    Decimal(r[5]),
                )
            )
    rows.sort(key=lambda r: r[0])
    return rows


def trades() -> list[tuple[Decimal, Decimal, str]]:
    """The recorded publicTrade frames: (price, size, side)."""
    out: list[tuple[Decimal, Decimal, str]] = []
    for line in (CORPUS / "ws/recorded_publicTrade_BTCUSDT.jsonl").read_text("utf-8").splitlines():
        if line.strip():
            for t in json.loads(line)["data"]:
                out.append((Decimal(t["p"]), Decimal(t["v"]), t["S"]))
    return out


def tick_size() -> Decimal:
    doc = json.loads((CORPUS / "rest/instruments_after.json").read_text("utf-8"))
    for x in doc["result"]["list"]:
        if x["symbol"] == "BTCUSDT":
            return Decimal(x["priceFilter"]["tickSize"])
    raise SystemExit("BTCUSDT not in instruments_after.json")


def level(price: Decimal, agg: int) -> Level:
    return int((price / TICK) // agg)


def poc(profile: Profile, last: Level) -> tuple[Level, int]:
    """Max-volume level; the `24` :1007 chain (VWAP -> last price -> lower). Returns (poc, ties)."""
    top = max(profile.values())
    tied = sorted(k for k, v in profile.items() if v == top)
    total = sum(profile.values(), Decimal(0))
    vwap = sum((Decimal(k) * v for k, v in profile.items()), Decimal(0)) / total
    best = min(tied, key=lambda k: (abs(Decimal(k) - vwap), abs(k - last), k))
    return best, len(tied)


def value_area(profile: Profile, centre: Level) -> tuple[Level, Level]:
    """Single-step expansion toward the heavier adjacent row (`22` :4841); equal takes both."""
    total = sum(profile.values())
    lo = hi = centre
    acc = profile.get(centre, Decimal(0))
    lowest, highest = min(profile), max(profile)
    while acc < total * VA_PCT and (lo > lowest or hi < highest):
        up = profile.get(hi + 1, Decimal(0)) if hi < highest else Decimal(-1)
        dn = profile.get(lo - 1, Decimal(0)) if lo > lowest else Decimal(-1)
        if up >= dn and hi < highest:
            hi += 1
            acc += max(up, Decimal(0))
        if dn >= up and lo > lowest:
            lo -= 1
            acc += max(dn, Decimal(0))
    return lo, hi


def bar_profile(agg: int, rule: str) -> Profile:
    """Bar-approximated volume by price: `uniform` over [low, high] or `ohlc4` (a quarter each)."""
    prof: Profile = {}
    for _, o, h, lo, c, v in klines():
        if rule == "uniform":
            a, b = level(lo, agg), level(h, agg)
            share = v / (b - a + 1)
            for k in range(a, b + 1):
                prof[k] = prof.get(k, Decimal(0)) + share
        else:
            for p in (o, h, lo, c):
                k = level(p, agg)
                prof[k] = prof.get(k, Decimal(0)) + v / 4
    return prof


def price_of(k: Level, agg: int) -> str:
    return str((Decimal(k) * agg * TICK).quantize(TICK))


def summarise(prof: Profile, agg: int, last: Level) -> dict[str, Any]:
    p, ties = poc(prof, last)
    lo, hi = value_area(prof, p)
    return {
        "rows": len(prof),
        "poc": price_of(p, agg),
        "poc_ties": ties,
        "val": price_of(lo, agg),
        "vah": price_of(hi, agg),
        "va_rows": hi - lo + 1,
    }


def worked_bars() -> dict[str, Any]:
    ks = klines()
    agg = 10
    last = level(ks[-1][4], agg)
    out: dict[str, Any] = {
        "bars": len(ks),
        "minutes": (ks[-1][0] - ks[0][0]) // 60_000 + 1,
        "low": str(min(k[3] for k in ks)),
        "high": str(max(k[2] for k in ks)),
        "row_ticks": agg,
    }
    for rule in ("uniform", "ohlc4"):
        out[rule] = summarise(bar_profile(agg, rule), agg, last)
    u, o = out["uniform"], out["ohlc4"]
    out["poc_shift_usd"] = str(abs(Decimal(u["poc"]) - Decimal(o["poc"])))
    out["delta_available"] = False  # a kline carries no aggressor side (fixture columns)
    return out


def worked_ticks() -> dict[str, Any]:
    ts = trades()
    prof: Profile = {}
    delta: dict[Level, Decimal] = {}
    for p, v, s in ts:
        k = level(p, 1)
        prof[k] = prof.get(k, Decimal(0)) + v
        delta[k] = delta.get(k, Decimal(0)) + (v if s == "Buy" else -v)
    span = max(prof) - min(prof) + 1
    out = summarise(prof, 1, level(ts[-1][0], 1))
    out.update(
        {
            "prints": len(ts),
            "span_rows": span,
            "untraded_rows_in_span": span - len(prof),
            "zero_delta_rows": sum(1 for v in delta.values() if v == 0),
            "low": str(min(t[0] for t in ts)),
            "high": str(max(t[0] for t in ts)),
        }
    )
    return out


def worked_density() -> dict[str, Any]:
    ks = klines()
    span_ticks = int((max(k[2] for k in ks) - min(k[3] for k in ks)) / TICK) + 1
    ladder: list[dict[str, Any]] = []
    for agg in AGGREGATIONS:
        rows = math.ceil(span_ticks / agg)
        for h in PANE_PX:
            px = h / rows
            ladder.append(
                {
                    "row_ticks": agg,
                    "rows": rows,
                    "pane_px": h,
                    "px_per_row": round(px, 2),
                    "merge_factor": max(1, math.ceil(MERGE_FLOOR_PX / px)),
                    "label_every_row": px >= LABEL_FLOOR_PX,
                }
            )
    return {
        "span_ticks": span_ticks,
        "ladder": ladder,
        "labelled_rows_cap": {h: h // LABEL_FLOOR_PX for h in PANE_PX},
        "table_rows_visible": {d: {h: h // px for h in PANE_PX} for d, px in ROW_PX.items()},
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
    cfg = json.loads((TOKENS / "themes.json").read_text("utf-8"))["themes"]
    out: dict[str, dict[str, object]] = {}
    for t in cfg:
        flat: dict[str, object] = {}
        for s in t["sets"]:
            flat.update(_leaves(json.loads((TOKENS / f"{s}.tokens.json").read_text("utf-8"))))
        out[t["name"]] = flat
    return out


def hexof(flat: dict[str, object], name: str) -> str:
    v = flat[name]
    while isinstance(v, str) and v.startswith("{"):
        v = flat[v[1:-1]]
    return str(v)


def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _lin(c: int) -> float:
    x = c / 255
    return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4


def ratio(a: str, b: str) -> float:
    """WCAG 2.x contrast ratio, contrast_check.py's formula."""
    lum = [
        0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(bb) for r, g, bb in map(_rgb, (a, b))
    ]
    return round((max(lum) + 0.05) / (min(lum) + 0.05), 2)


def simulate(h: str, rendering: str) -> str:
    rgb = _rgb(h)
    if rendering == "greyscale":
        y = sum(c * w for c, w in zip(rgb, LUMA_601, strict=True))
        vals: tuple[float, ...] = (y, y, y)
    elif rendering == "deuteranopia":
        vals = tuple(sum(c * m for c, m in zip(rgb, row, strict=True)) for row in DEUTERANOPIA)
    else:
        vals = tuple(float(c) for c in rgb)
    return "#" + "".join(f"{min(255, max(0, round(v))):02X}" for v in vals)


def worked_colour() -> dict[str, Any]:
    pal = palette()
    rows: list[dict[str, Any]] = []
    for th, flat in pal.items():
        for r in RENDERINGS:
            for fg in PROFILE_TOKENS:
                for bg in BACKGROUNDS:
                    v = ratio(simulate(hexof(flat, fg), r), simulate(hexof(flat, bg), r))
                    rows.append({"theme": th, "rendering": r, "a": fg, "b": bg, "ratio": v})
            for a, b, _ in PAIRS:
                v = ratio(simulate(hexof(flat, a), r), simulate(hexof(flat, b), r))
                rows.append({"theme": th, "rendering": r, "a": a, "b": b, "ratio": v})
    below = [x for x in rows if x["ratio"] < NON_TEXT]
    grey_pairs = sorted({f"{x['a']}|{x['b']}" for x in below if x["rendering"] == "greyscale"})
    return {"bar": NON_TEXT, "rows": rows, "below_bar": len(below), "greyscale_below": grey_pairs}


def worked() -> dict[str, Any]:
    if tick_size() != TICK:
        raise SystemExit("tick size moved: re-read instruments_after.json")
    return {
        "base": BASE,
        "bars": worked_bars(),
        "ticks": worked_ticks(),
        "density": worked_density(),
        "colour": worked_colour(),
    }


# --- the memo gates -------------------------------------------------------------------------
_BASE_CACHE: dict[str, list[str]] = {}
COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)
MARKER = re.compile(r"^\s*audit:([a-z_.]+)=([0-9]+)\s*$", re.DOTALL)
CITE_KEY = re.compile(
    r"`(" + "|".join(re.escape(k) for k in KEYS) + r")` ((?::\d+(?:–:?\d+)?(?:, )?)+)"
)
CITE_NUM = re.compile(r":(\d+)(?:–:?(\d+))?")
CURLY = re.compile(r"“([^”]+)”")
H2 = re.compile(r"^## ", re.MULTILINE)
LEXICON = re.compile(
    r"\b(participant (said|told|chose|found|preferred)|they told us|we observed|was observed"
    r"|in the session[s]?,|minutes into|users reported|traders told|said verbatim"
    r"|p[0-9] said|the owner said)\b",
    re.IGNORECASE,
)
# Built from fragments so that this file, which G-PUBLIC also scans, never matches itself.
_DENY_PARTS = (
    "/" + "home/",
    "/" + "tmp/",
    "/" + "Users/",
    r"\b[a-z]+-" + r"worker-\d+\b",
    "pen" + r"pot\.[a-z]+\.[a-z]+",
    "rel" + r"ay\.[a-z]+\.[a-z]+",
    r"\\\\" + "w" + "sl",
    "scr" + "atch",
    "an" + "vil",
    r"\bh" + r"cl\b",
    r"\bh" + r"pe\b",
    "basil" + "tt",
    "relay" + "room",
)
PUBLIC_DENY = re.compile("(" + "|".join(_DENY_PARTS) + ")", re.IGNORECASE)
LEVEL_NAMES = (
    "POC",
    "VAH",
    "VAL",
    "Value-area shading",
    "HVN",
    "LVN",
    "Naked POC",
    "Single prints",
    "Developing state",
    "Initial balance",
)
AC_ROWS = ("AC 1", "AC 2", "AC 3", "AC 4", "AC 5")
STATUSES = ("done", "heuristic-only", "open", "design approval pending")
TICKETS = re.compile(r"\bE(?:19|16|18|25|05)-[A-Z]\d\d\b|\bowner\b")


def base_lines(rel: str) -> list[str]:
    if rel not in _BASE_CACHE:
        res = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{BASE}:{rel}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise SystemExit(f"git show {BASE[:9]}:{rel} failed")
        _BASE_CACHE[rel] = res.stdout.split("\n")
    return _BASE_CACHE[rel]


def section(text: str, title: str) -> str:
    """The body of the `## ` section whose heading starts with `title` (to the next `## `)."""
    m = re.search(r"^## " + re.escape(title) + r".*$", text, re.MULTILINE)
    if not m:
        return ""
    nxt = H2.search(text, m.end())
    return text[m.end() : nxt.start() if nxt else len(text)]


def table_rows(body: str) -> list[list[str]]:
    out = []
    for ln in body.splitlines():
        if ln.startswith("|") and not re.match(r"^\|\s*-", ln):
            out.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return out[1:] if out else []


def cites_in(line: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE_KEY.finditer(line):
        for n in CITE_NUM.finditer(m.group(2)):
            a = int(n.group(1))
            out.append((m.group(1), a, int(n.group(2)) if n.group(2) else a))
    return out


def g_cite(text: str) -> list[str]:
    bad = []
    count = 0
    for ln in text.splitlines():
        for key, a, b in cites_in(ln):
            count += 1
            lines = base_lines(KEYS[key])
            if b < a or b > len(lines) or not lines[a - 1].strip():
                bad.append(f"`{key}` :{a}-:{b}")
    if count == 0:
        bad.append("no cite found")
    return bad


def _norm(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", s).strip()


_HAY: dict[str, str] = {}


def _hay(key: str) -> str:
    if key not in _HAY:
        _HAY[key] = _norm("\n".join(base_lines(KEYS[key])))
    return _HAY[key]


def g_quote(text: str) -> list[str]:
    bad = []
    for ln in text.splitlines():
        keys = {k for k, _, _ in cites_in(ln)} | set(CORE)
        quotes = CURLY.findall(ln)
        if not quotes:
            continue
        hay = [_hay(k) for k in sorted(keys)]
        for q in quotes:
            if len(q) >= QUOTE_MIN and not any(_norm(q) in h for h in hay):
                bad.append(q[:60])
    return bad


def g_ac(text: str) -> list[str]:
    rows = table_rows(section(text, "Acceptance-criteria trace"))
    bad = []
    leads = [r[0] for r in rows]
    for ac in AC_ROWS:
        hit = [r for r in rows if r[0].startswith(ac + " ")]
        if len(hit) != 1:
            bad.append(f"{ac} rows={len(hit)}")
    if sum(1 for x in leads if x.startswith("DoD")) < 4:
        bad.append("fewer than 4 DoD rows")
    for r in rows:
        if len(r) < 3 or not any(s in r[-1] for s in STATUSES):
            bad.append(f"status? {r[0][:30]}")
    for ac in ("AC 2", "AC 3"):
        for r in rows:
            if r[0].startswith(ac + " ") and "open" not in r[-1]:
                bad.append(f"{ac} must stay open")
    return bad


def g_levels(text: str) -> list[str]:
    rows = table_rows(section(text, "5. Derived levels"))
    names = [r[0].strip("*") for r in rows]
    bad = [f"missing {n}" for n in LEVEL_NAMES if n not in names]
    bad += [f"extra {n}" for n in names if n not in LEVEL_NAMES]
    for r in rows:
        if len(r) != 6 or any(not c for c in r):
            bad.append(f"incomplete {r[0][:20]}")
        elif not re.search(r"\bF-\d+\b", r[5]):
            bad.append(f"no finding {r[0][:20]}")
        elif r[3] not in ("1 labelled", "2 labelled", "3 implied"):
            bad.append(f"rank {r[0][:20]}")
    return bad


def g_pd(text: str) -> list[str]:
    rows = table_rows(section(text, "7. Proposed decisions"))
    bad = []
    ids = [r[0].strip("*") for r in rows]
    if not 6 <= len(ids) <= 10:
        bad.append(f"count {len(ids)}")
    if ids != [f"PD-{i}" for i in range(1, len(ids) + 1)]:
        bad.append("ids not PD-1..PD-n")
    for r in rows:
        if len(r) != 6:
            bad.append(f"cells {r[0]}")
            continue
        if "PASS if" not in r[2] or "FAIL if" not in r[2]:
            bad.append(f"check {r[0]}")
        if not re.search(r"\bF-\d+\b", r[3]):
            bad.append(f"evidence {r[0]}")
        if not re.search(r"\bE19-[A-Z]\d\d\b", r[4]):
            bad.append(f"target {r[0]}")
        if r[5] != "PROPOSED":
            bad.append(f"status {r[0]}")
    return bad


def g_heur(text: str) -> list[str]:
    bad = []
    rows = table_rows(section(text, "3. Heuristic evaluation"))
    if not rows:
        bad.append("no findings")
    ids = [r[0] for r in rows]
    if ids != [f"F-{i}" for i in range(1, len(ids) + 1)]:
        bad.append("ids not F-1..F-n")
    for r in rows:
        if "(heuristic)" not in " ".join(r):
            bad.append(f"{r[0]} unlabelled")
    proto = section(text, "10. Owner session protocol")
    rest = text.replace(proto, "")
    for m in LEXICON.finditer(rest):
        bad.append(f"lexicon '{m.group(0)}'")
    return bad


def g_comp(text: str) -> list[str]:
    rows = table_rows(section(text, "8. Competitive review"))
    bad = [] if rows else ["no rows"]
    for r in rows:
        src = r[-1]
        sourced = re.search(r"https://\S+", src) and re.search(r"fetched 20\d\d-\d\d-\d\d", src)
        if not sourced and "unsourced observation" not in src:
            bad.append(r[0][:30])
    return bad


def g_img(text: str) -> list[str]:
    bad = []
    for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):
        bad.append(m.group(1)[:60])
    for m in re.finditer(r"https?://\S+\.(?:png|jpe?g|gif|webp|svg)\b", text, re.IGNORECASE):
        bad.append(m.group(0)[:60])
    return bad


def g_marker(text: str, computed: dict[str, int]) -> list[str]:
    bad = []
    for m in COMMENT.finditer(text):
        mm = MARKER.match(m.group(1))
        if not mm:
            bad.append(f"comment '{m.group(1)[:30]}'")
        elif mm.group(1) not in computed:
            bad.append(f"unknown {mm.group(1)}")
        elif int(mm.group(2)) != computed[mm.group(1)]:
            bad.append(f"{mm.group(1)}={mm.group(2)} != {computed[mm.group(1)]}")
    return bad


def g_bq(text: str) -> list[str]:
    body = section(text, "1. Brief questions")
    bad = []
    if f"Status: **RULED (comment {RULING_COMMENT})**" not in body:
        bad.append("ruled line")
    if BQ_COMMENT not in body:
        bad.append("BQ list comment")
    if re.search(r"ruling pending|Built as:", body):
        bad.append("pending line left")
    for i in range(16):
        if not re.search(rf"\*\*BQ-{i}\b", body):
            bad.append(f"BQ-{i}")
    return bad


def g_public(text: str) -> list[str]:
    """The memo (as given) and this tool's own source."""
    tool = (ROOT / TOOL_REL).read_text("utf-8")
    hay = (text, tool)
    return [m.group(0) for h in hay for m in PUBLIC_DENY.finditer(h)]


HEX40 = re.compile(r"\b[0-9a-f]{40}\b")


def g_pin(text: str) -> list[str]:
    bad = []
    if f"**Inputs pinned:** `main` `{BASE[:12]}`;" not in text:
        bad.append(f"pin line does not name {BASE[:12]}")
    bad += [f"40-hex {m.group(0)[:12]}" for m in HEX40.finditer(text)]
    return bad


def _git(*args: str) -> str | None:
    res = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
    )
    return res.stdout if res.returncode == 0 else None


def g_untouched(git: Callable[..., str | None] = _git) -> list[str]:
    committed = git("diff", "--name-only", f"{BASE}...HEAD")
    work = git("diff", "--name-only", "HEAD")
    untracked = git("ls-files", "--others", "--exclude-standard")
    if committed is None or work is None or untracked is None:
        return ["git call failed"]
    paths = set((committed + work + untracked).split())
    # The ruling of record: a plan-document change is an A-row in the memo, never an edit.
    allowed = {MEMO_REL, TOOL_REL}
    return [f"touched {p}" for p in sorted(paths - allowed)]


def counts(text: str) -> dict[str, int]:
    return {
        "findings": len(table_rows(section(text, "3. Heuristic evaluation"))),
        "decisions": len(table_rows(section(text, "7. Proposed decisions"))),
        "levels": len(table_rows(section(text, "5. Derived levels"))),
        "competitive_rows": len(table_rows(section(text, "8. Competitive review"))),
        "boards": 9,
    }


GATES: dict[str, Callable[[str], list[str]]] = {
    "G-CITE": g_cite,
    "G-QUOTE": g_quote,
    "G-AC": g_ac,
    "G-LEVELS": g_levels,
    "G-PD": g_pd,
    "G-HEUR": g_heur,
    "G-COMP": g_comp,
    "G-IMG": g_img,
    "G-MARKER": lambda t: g_marker(t, counts(t)),
    "G-BQ": g_bq,
    "G-PUBLIC": g_public,
    "G-PIN": g_pin,
}


def run_gates(text: str, untouched: bool = True) -> dict[str, list[str]]:
    out = {name: fn(text) for name, fn in GATES.items()}
    if untouched:
        out["G-UNTOUCHED"] = g_untouched()
    return out


def check() -> int:
    res = run_gates(MEMO.read_text("utf-8"))
    fails = 0
    for name, bad in res.items():
        print(f"{'FAIL' if bad else 'PASS'} {name}" + (f": {'; '.join(bad)[:80]}" if bad else ""))
        fails += bool(bad)
    print(f"FAIL {fails}")
    return 1 if fails else 0


def _sub(old: str, new: str, count: int = 1) -> Callable[[str], str]:
    def f(t: str) -> str:
        if old not in t:
            raise SystemExit(f"self-test anchor moved: {old[:40]!r}")
        return t.replace(old, new, count)

    return f


MUTATIONS: tuple[tuple[str, str, Callable[[str], str]], ...] = (
    ("M-1 a cite past the end of `24`", "G-CITE", _sub("`24` :1002", "`24` :99999")),
    (
        "M-2 a curly quote edited",
        "G-QUOTE",
        _sub("“closest to the range midpoint”", "“closest to the mid”"),
    ),
    (
        "M-3 AC 2 marked done",
        "G-AC",
        lambda t: re.sub(r"(\| AC 2 [^\n]*\| )[^|\n]*open[^|\n]*\|", r"\1done |", t, count=1),
    ),
    (
        "M-4 the HVN level renamed",
        "G-LEVELS",
        lambda t: re.sub(r"\n\| HVN ", "\n| High node ", t, count=1),
    ),
    ("M-5 PD-1 loses its FAIL clause", "G-PD", _sub("FAIL if", "fails if", 1)),
    (
        "M-6 a finding loses its label",
        "G-HEUR",
        lambda t: re.sub(r"(\| F-2 +\| )\(heuristic\)", r"\1(observed)", t, count=1),
    ),
    (
        "M-7 a participant quote invented",
        "G-HEUR",
        _sub("## 4. Worked numbers", "We observed a misread.\n\n## 4. Worked numbers"),
    ),
    (
        "M-8 a competitive row loses its source",
        "G-COMP",
        lambda t: re.sub(
            r"(TradingView — TPO [^\n]*\| )unsourced observation", r"\1seen", t, count=1
        ),
    ),
    (
        "M-9 a vendor screenshot embedded",
        "G-IMG",
        _sub("## 9. Amendments", "![tv](img/tv.png)\n\n## 9. Amendments"),
    ),
    (
        "M-10 a stale audit marker",
        "G-MARKER",
        lambda t: re.sub(r"audit:decisions=\d+", "audit:decisions=99", t, count=1),
    ),
    (
        "M-11 the RULED line reverted to pending",
        "G-BQ",
        _sub(f"**RULED (comment {RULING_COMMENT})**", "**defaults built; ruling pending**"),
    ),
    (
        "M-16 a BQ line left unruled",
        "G-BQ",
        _sub("Ruled as proposed:", "Built as:"),
    ),
    (
        "M-12 a local path leaked",
        "G-PUBLIC",
        _sub("## 12. References", "See /" + "home/x/notes.\n\n## 12. References"),
    ),
    (
        "M-13 a free HTML comment",
        "G-MARKER",
        _sub("## 12. References", "<!-- note\nto self -->\n\n## 12. References"),
    ),
    ("M-17 the pin widened to the full sha", "G-PIN", _sub(f"`{BASE[:12]}`", f"`{BASE}`")),
    ("M-18 a stale pin", "G-PIN", _sub(f"`main` `{BASE[:12]}`", "`main` `46e6acd2ddf3`")),
)


def _fake_git(extra: str) -> Callable[..., str | None]:
    def git(*args: str) -> str | None:
        if args[:2] == ("diff", "--name-only"):
            return f"{MEMO_REL}\n{TOOL_REL}\n{extra}\n" if "HEAD" not in args[2:] else ""
        return ""

    return git


UNTOUCHED_MUTATIONS: tuple[tuple[str, Callable[..., str | None]], ...] = (
    (
        "M-14 a path outside the ticket touched",
        _fake_git("docs/plan/24-internal-schemas.md"),
    ),
    ("M-15 a `14` pointer line added (an A-row by the ruling)", _fake_git(SCREENS_REL)),
)


def self_test() -> int:
    raw = MEMO.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    base = run_gates(text, untouched=False)
    base_fails = {k for k, v in base.items() if v}
    ok = True
    if base_fails:
        print(f"FAIL baseline not clean: {sorted(base_fails)}")
        ok = False
    for label, gate, mutate in MUTATIONS:
        res = run_gates(mutate(text), untouched=False)
        new = {k for k, v in res.items() if v} - base_fails
        good = new == {gate}
        ok &= good
        print(f"{'ok  ' if good else 'FAIL'} {label} -> {sorted(new) or 'nothing'}")
    if g_untouched(_fake_git("")):
        print("FAIL G-UNTOUCHED rejects the clean fake")
        ok = False
    for label, fake in UNTOUCHED_MUTATIONS:
        good = bool(g_untouched(fake))
        ok &= good
        print(f"{'ok  ' if good else 'FAIL'} {label} -> {'G-UNTOUCHED' if good else 'nothing'}")
    if hashlib.sha256(MEMO.read_bytes()).hexdigest() != digest:
        print("FAIL the memo changed on disk")
        ok = False
    print("self-test ok" if ok else "self-test FAILED")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        return check()
    if a.self_test:
        return self_test()
    print(json.dumps(worked(), indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
