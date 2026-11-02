#!/usr/bin/env python3
"""E21-D05 (#505) audit: the DOM heatmap motion and reduced-motion spec (text first).

Offline and default-deny. The standing gates (git, cites, pins, G-T2, closing keywords, public
text, R7, G-UNTOUCHED, the runner and the mutation harness) come from `spec_audit_lib.py`; this
file keeps E21-D05's rows. It reads the cited texts AS TEXT at their pins (the plan and design
texts at the base; E21-D02 / D03 / D04 at their PR heads) and runs only `relative_luminance()` of
`docs/design/_tools/contrast_check.py`. It replays the re-centre band and oscillation (section 4),
the column-width crossover over `23`'s reference displays (section 3.2) and the per-frame
luminance of a 10x and 100x rescale on every shipped heatmap ramp (section 5.2).

Gates: see GATES (section 16.2); G-MUTLIST holds section 16.3 equal to MUTATIONS. G-RULED pins each
BQ bullet's sha256[:16] in `e21_d05_ruled_pins.txt` (`--repin-ruled` is the only writer); the
BQ list is comment 6582999442 on #505, defaults built, ruling pending (G-RULING).

Usage (from the repo root):
  python3 -I docs/design/_tools/e21_d05_motion_audit.py --check | --self-test | --repin-ruled
  python3 -I docs/design/_tools/e21_d05_motion_audit.py --fill   (sections 3.2, 4.2-4.3, 5.2, 16.3)
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import functools
import itertools
import json
import math
import re
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
BASE = "d23ec8bd7"  # origin/main when the BQ list was written; every plan cite is read here
HEADS = {
    "D02": ("7e1040260", "#5488"),
    "D03": ("c7b0d2087", "#5518"),
    "D04": ("1a320cde7", "#5519"),
}
BQ_LIST = "6582999442"  # the BQ list on #505; ruling pending

SPEC_REL = "docs/design/E21/E21-D05.md"
TOOL_REL = "docs/design/_tools/e21_d05_motion_audit.py"
PIN_REL = "docs/design/_tools/e21_d05_ruled_pins.txt"
LIB_REL = "docs/design/_tools/spec_audit_lib.py"
CAT_REL = "docs/plan/14-screens-catalogue.md"
DSB_REL = "docs/plan/16-design-system-brief.md"
OWN = (SPEC_REL, TOOL_REL, PIN_REL, LIB_REL)
BUDGETS = {CAT_REL: (2, 0), DSB_REL: (18, 0)}  # BQ-2: two pointer lines; the 16 section 7.3 block
BACKLOG_REL = "docs/plan/backlog/E21.json"

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": CAT_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "16": DSB_REL,
    "23": "docs/plan/23-ws-protocol.md",
    "26": "docs/plan/26-chart-engine-design.md",
}
KEYED = {
    "M": L.DocRef("docs/design/research/e21-dom-heatmap.md", BASE),
    **{k: L.DocRef(f"docs/design/E21/E21-{k}.md", h) for k, (h, _) in HEADS.items()},
    "D11E08": L.DocRef("docs/design/E08/E08-D11.md", BASE),
    "D04E10": L.DocRef("docs/design/E10/E10-D04.md", BASE),
    "D03E05": L.DocRef("docs/design/E05/E05-D03.md", BASE),
    "D03E17": L.DocRef("docs/design/E17/E17-D03.md", BASE),
    "PRIM": L.DocRef("packages/ui/tokens/primitives.tokens.json", BASE),
    "R32": L.DocRef(".claude/rules/32-design-specs.md", BASE),
    "README": L.DocRef("docs/design/README.md", BASE),
}
CITE_RE = L.cite_regex(KEYED, ranges=True)
# The ruled file:line:text pins: the numbers this spec builds on stand where it says they do.
KEY_PINS = (
    L.KeyCite("23", 804, "≥ 2 device pixels"),
    L.KeyCite("23", 811, "3-device-pixel column"),
    L.KeyCite("23", 832, "whenever `ideal_ms ≤ 2500`"),
    L.KeyCite("26", 301, "normalise by column max or global scale"),
    L.KeyCite("26", 309, "scrolling costs nothing extra"),
    L.KeyCite("26", 312, "re-uploads only the newly exposed rows"),
    L.KeyCite("06", 89, "100ms toward 250ms"),
    L.KeyCite("16", 218, "the latest explicit choice wins over the OS in both directions"),
    L.KeyCite("05", 233, "a single low-amplitude cross-fade"),
    L.KeyCite("11", 1982, "without jitter on every tick"),
    L.KeyCite("11", 2028, "rescale is smooth (no flashing)"),
    L.KeyCite("D02", 156, "Pause (WCAG 2.2.2)"),
    L.KeyCite("D11E08", 96, "the `fast` fade starts in that frame"),
    L.KeyCite("D04E10", 149, "banner enter (SCR-153"),
)

# ---------- the spec's own engine constants (PROPOSED; section 9) ---------------------------------
BAND_FRAC, BAND_MIN, BAND_MAX = 0.20, 3, 10  # heatmap.recentre.band*
INTERVAL_MS = 1000  # heatmap.recentre.minIntervalMs
CROSS_PX = 3.0  # continuous only above the 23 section 6.1.1 target column
LUMA_STEP, LUMA_CAP = 0.09, 0.10  # heatmap.rescale.lumaStep; the per-frame cap it serves
REVERSAL_MS = 1000  # heatmap.rescale.minReversalMs
ROWS = (4, 6, 8, 10, 12, 20, 40, 60)  # visible ladder rows replayed (zoom and text scale too)
REPLAY_MS, TICK_MS = 10_000, 5
OSC = ((40, 2, "edge ± 1 row"), (40, 5, "edge ± 1 row"), (40, 20, "edge ± 1 row"),
       (40, 2, "edge to edge"), (40, 5, "edge to edge"), (40, 20, "edge to edge"),
       (6, 20, "edge ± 1 row"), (6, 20, "edge to edge"))  # fmt: skip
WINDOWS = (900, 60)  # the 23 reference window and the trail chip's 60 s (`14`:1197)
BUCKETS = (100, 250, 500, 1000, 5000)
FRAME_MS = 1000 / 60
SETS = ("color.heatmap", "color.cvd.heatmap")
MOTIONS = ("Trail advance", "Re-centre", "Colour-scale rescale", "Resync enter / exit",
           "Depth-shed notice entry")  # fmt: skip
MOVING = ("translate", "continuous", "fade", "slide", "tween", "scroll offset")
COSTS = ("uniform only", "one column upload per write", "exposed rows only", "none (DOM")
ADOPT_CITES = ("D11E08:96", "D11E08:97", "D11E08:126", "D11E08:127", "D11E08:359",
               "D04E10:149", "D04E10:150")  # fmt: skip
MOTION_TOKEN_RE = re.compile(L.TOKEN_REF_RE.pattern.replace("|border)", "|border|motion)"))


# ---------- sources and measurers -----------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def docs() -> L.Docs:
    return L.Docs(repo(), BASE, KEYED, plan=PLAN)


def line_of(key: str, n: int) -> str:
    return docs().line(key, n) or ""


@functools.cache
def contrast() -> ModuleType:
    return L.load_module(ROOT, "docs/design/_tools/contrast_check.py", "contrast_check")


@functools.cache
def prim() -> dict[str, object]:
    return {k: v.get("$value") for k, v in L.token_file(repo(), BASE, "primitives").items()}


def ms(token: str) -> int:
    return int(str(prim()[token]).removesuffix("ms"))


def standard() -> tuple[float, float, float, float]:
    vals = prim()["motion.easing.standard"]
    if not isinstance(vals, list) or len(vals) != 4:
        raise L.AuditError("motion.easing.standard is not a cubic-bezier")
    a, b, c, d = (float(x) for x in vals)
    return a, b, c, d


# ---------- replay 1: the re-centre band and the oscillation runs (AC 1) --------------------------
def band(rows: int) -> int:
    """Section 4.1: 20 % of the rows, 3 to 10, capped so the centre row is never in the band."""
    clamped = min(BAND_MAX, max(BAND_MIN, math.floor(BAND_FRAC * rows)))
    return max(0, min(clamped, (rows - 1) // 2 - 1))


def replay(rows: int, hz: int, amp: str, interval: int) -> tuple[int, int | None]:
    """Re-centres in REPLAY_MS and the smallest gap between two (None: fewer than two). The mark
    alternates between two prices every half period; `interval` 0 is the band rule alone."""
    v, b, half = rows, band(rows), 1000 // (2 * hz)
    lo, hi = (b - 1, b) if amp.startswith("edge ±") else (b - 1, b - 1 + v)
    top, last, times = 0, -(10**9), []
    for t in range(0, REPLAY_MS, TICK_MS):
        price = lo if (t // half) % 2 == 0 else hi
        row = price - top
        if (row < b or row > v - 1 - b) and t - last >= interval:
            top, last = price - v // 2, t
            times.append(t)
    gaps = [b2 - a for a, b2 in itertools.pairwise(times)]
    return len(times), min(gaps) if gaps else None


def band_rows() -> list[list[str]]:
    return [[str(n), str(band(n)), str(n - 2 * band(n))] for n in ROWS]


def replay_rows() -> list[list[str]]:
    out = []
    for rows, hz, amp in OSC:
        naive, _ = replay(rows, hz, amp, 0)
        n, gap = replay(rows, hz, amp, INTERVAL_MS)
        out.append(
            [str(rows), f"{hz} Hz", amp, str(naive), str(n), "—" if gap is None else f"{gap} ms"]
        )
    return out


# ---------- replay 2: the column-width crossover (section 3.2) ------------------------------------
def bucket(ideal: float) -> int:
    pick = next((b for b in BUCKETS if b >= ideal), BUCKETS[-1])
    return 1000 if pick == 5000 and ideal <= 2500 else pick  # the ladder clamp, `23`:832


def reference_displays() -> list[tuple[str, int]]:
    """`23`:825-830: (display, device px), each row's ideal_ms re-derived as a sanity check."""
    out = []
    for n in range(825, 831):
        c = L.cells(line_of("23", n))
        dev, ideal = int(c[3].replace(" ", "")), int(c[4].replace(" ", ""))
        if round(900_000 / (dev / 3)) != ideal:
            raise L.AuditError(f"`23`:{n} ideal_ms is not the formula's")
        out.append((c[0], dev))
    return out


def crossover_rows() -> list[list[str]]:
    out = []
    for window in WINDOWS:
        for name, dev in reference_displays():
            ideal = window * 1000 / (dev / 3)
            pick = bucket(ideal)
            col = dev * pick / (window * 1000)
            mode = "continuous" if col > CROSS_PX else "step"
            out.append([name, str(dev), f"{window} s", f"{ideal:.0f}", str(pick), f"{col:.2f}",
                        mode, "step"])  # fmt: skip
    return out


# ---------- replay 3: the rescale ramp's per-frame luminance (AC 3) -------------------------------
def ease(t: float, p: tuple[float, float, float, float]) -> float:
    if t <= 0 or t >= 1:
        return min(1.0, max(0.0, t))
    lo, hi = 0.0, 1.0
    for _ in range(60):
        s = (lo + hi) / 2
        x = 3 * (1 - s) ** 2 * s * p[0] + 3 * (1 - s) * s * s * p[2] + s**3
        lo, hi = (s, hi) if x < t else (lo, s)
    s = (lo + hi) / 2
    return 3 * (1 - s) ** 2 * s * p[1] + 3 * (1 - s) * s * s * p[3] + s**3


def lut(theme: str, prefix: str, side: str) -> tuple[float, ...]:
    """The 256x1 LUT (`26`:305) as relative luminance: zero and stops 1-5 evenly spaced, linear
    in 8-bit sRGB between them (PROPOSED; G-1)."""
    t = L.resolve_theme(repo(), BASE, theme)
    keys = ["color.heatmap.zero"] + [f"{prefix}.{side}.{i}" for i in range(1, 6)]
    stops = [tuple(int(t[k][1 + 2 * j : 3 + 2 * j], 16) for j in range(3)) for k in keys]
    out = []
    for i in range(256):
        x = i / 255 * 5
        k = min(int(x), 4)
        c = tuple(round(a + (b - a) * (x - k)) for a, b in zip(stops[k], stops[k + 1]))
        out.append(float(contrast().relative_luminance(c)))
    return tuple(out)


VALUES = (0.0, *(10 ** (e / 20) for e in range(-60, 41)))  # resting sizes, 0.001-100 x bound


def pos(v: float, b: float, scale: str) -> int:
    x = v / b if scale == "linear" else math.log1p(100 * v) / math.log1p(100 * b)
    return round(min(1.0, max(0.0, x)) * 255)


def max_log_step(lum: tuple[float, ...]) -> float:
    """Derived once per LUT build: the largest per-frame step in ln(bound) that moves no LUT
    position by LUMA_STEP or more (searched on a 1/1024 grid of positions)."""
    xs = [i / 1024 for i in range(1025)]

    def ok(d: float) -> bool:
        return all(
            abs(lum[round(min(1.0, y) * 255)] - lum[round(x * 255)]) < LUMA_STEP
            for x in xs
            for y in (x * math.exp(d), x * math.exp(-d))
        )

    lo, hi = 0.0, 3.0
    for _ in range(30):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def ramp(lum: tuple[float, ...], factor: float, scale: str, dur: float, cap: float | None
         ) -> tuple[float, float, float]:  # fmt: skip
    """One rescale by `factor`: (worst per-frame luminance change, share of cells moving by
    LUMA_CAP or more in one frame, ms to land). `dur` 0 = the instant cut."""
    b0, target = 1.0, math.log(factor)
    prev = [lum[pos(v, b0, scale)] for v in VALUES]
    lnb, worst, first, k = 0.0, 0.0, -1.0, 0
    while k < 100_000:
        k += 1
        want = target * (ease(k * FRAME_MS / dur, standard()) if dur else 1.0)
        lnb += want - lnb if cap is None else max(-cap, min(cap, want - lnb))
        cur = [lum[pos(v, math.exp(lnb), scale)] for v in VALUES]
        d = [abs(a - c) for a, c in zip(prev, cur)]
        worst, prev = max(worst, *d), cur
        first = sum(1 for x in d if x >= LUMA_CAP) / len(d) if first < 0 else first
        if abs(lnb - target) < 1e-12 and k * FRAME_MS >= dur:
            return worst, first, k * FRAME_MS
    raise L.AuditError("the ramp never lands")


@functools.cache
def rescale_rows() -> tuple[tuple[str, ...], ...]:
    slow = ms("motion.duration.slow")
    out = []
    for theme in L.THEME_PARTS:
        inst = share = eased = 0.0
        step, worst, land10, land100 = 9.0, 0.0, 0.0, 0.0
        for prefix in SETS:
            for side in ("bid", "ask"):
                lum = lut(theme, prefix, side)
                cap = max_log_step(lum)
                step = min(step, cap)
                for scale in ("linear", "log"):
                    for f in (0.1, 10.0, 0.01, 100.0):
                        w, s, _ = ramp(lum, f, scale, 0, None)
                        inst, share = max(inst, w), max(share, s)
                        eased = max(eased, ramp(lum, f, scale, slow, None)[0])
                        w, _, land = ramp(lum, f, scale, slow, cap)
                        worst = max(worst, w)
                        big = abs(math.log10(f)) > 1.5
                        land10, land100 = (
                            (land10, max(land100, land)) if big else (max(land10, land), land100)
                        )
        out.append((theme, f"{inst:.3f}", f"{share:.0%}", f"{eased:.3f}", f"{step:.3f}",
                    f"{worst:.3f}", f"{land10:.0f} ms", f"{land100:.0f} ms"))  # fmt: skip
    return tuple(out)


# ---------- spec helpers --------------------------------------------------------------------------
def sec(t: L.Tree, heading: str) -> str:
    return L.section(t.text("spec"), heading)


def five(t: L.Tree) -> list[list[str]]:
    return L.table_rows(sec(t, "## 2. The five motions"))


def table_gate(t: L.Tree, heading: str, want: list[list[str]], what: str) -> list[str]:
    got = L.table_rows(sec(t, heading))
    if got == want:
        return []
    bad = [f"{what} row {i + 1}: written {g}, replayed {w}" for i, (g, w) in
           enumerate(zip(got, want)) if g != w]  # fmt: skip
    return bad or [f"{what}: {len(got)} rows, replayed {len(want)}"]


# ---------- this spec's gates ---------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    bad = L.check_cites(L.extract_cites(t.text("spec"), CITE_RE), docs(), min_count=150)
    return [f"unresolved: {', '.join(b.split(' (')[0] for b in bad)}"] if bad else []


def g_quote(t: L.Tree) -> list[str]:
    bad = L.check_key_cites(KEY_PINS, docs())
    for r in L.table_rows(sec(t, "## 12. Copy deck")):
        if len(r) < 5 or not r[4].startswith("verbatim"):
            continue
        c = L.extract_cites(r[3], CITE_RE)
        if not c or L.unquote(r[2]) not in line_of(c[0].doc, c[0].lo):
            bad.append(f"{r[0]} not on its line")
    return bad


def g_version(t: L.Tree) -> list[str]:
    v, spec = sec(t, "### 16.1 Version line"), t.text("spec")
    need = [BASE, "re-pinned to the merge commit", *(x for h in HEADS.values() for x in h)]
    miss = [n for n in need if n not in v]
    if f"Base `origin/main` `{BASE}`" not in spec:
        miss.append("Inputs pinned base")
    return [f"missing: {', '.join(miss)}"] if miss else []


def g_ac(t: L.Tree) -> list[str]:
    tickets = json.loads(repo().show(BASE, BACKLOG_REL) or "[]")
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E21-D05")
    names = [n.strip() for n in re.findall(r"Scenario: (.+)", body)]
    trace = sec(t, "## Acceptance-criteria and DoD trace")
    miss = [n for n in names if f'AC "{n}"' not in trace]
    return [f"scenario names not verbatim: {miss or names}"] if len(names) != 3 or miss else []


def g_five(t: L.Tree) -> list[str]:
    got = five(t)
    bad = [] if [r[1] for r in got] == list(MOTIONS) else [f"motions {[r[1] for r in got]}"]
    for r in got:
        if len(r) < 7 or not all(r[2:5]) or r[4] in ("—", "none"):
            bad.append(f"{r[1] if len(r) > 1 else '?'}: a safe, reduce or carrier cell")
            continue
        moving = [w for w in MOVING if w in r[3].lower()]
        if r[1] == "Colour-scale rescale":
            moving = [] if "luminance" in r[3] and "nothing moves" in r[3] else ["no luminance"]
        if moving:
            bad.append(f"{r[1]}: the reduce twin moves ({moving})")
    return bad


def g_recentre(t: L.Tree) -> list[str]:
    bad = table_gate(t, "### 4.2", band_rows(), "band")
    bad += table_gate(t, "### 4.3", replay_rows(), "replay")
    for rows, hz, amp in OSC:
        _, gap = replay(rows, hz, amp, INTERVAL_MS)
        if gap is not None and gap < INTERVAL_MS:
            bad.append(f"{rows} rows {hz} Hz {amp}: two re-centres {gap} ms apart")
    bad += [f"{n} rows: the centre row is in the band" for n in ROWS if n // 2 < band(n) or
            n // 2 > n - 1 - band(n)]  # fmt: skip
    return bad


def g_crossover(t: L.Tree) -> list[str]:
    bad = [] if "3-device-pixel" in line_of("23", 811) else ["`23`:811 no longer targets 3 px"]
    return bad + table_gate(t, "### 3.2", crossover_rows(), "crossover")


def g_rescale(t: L.Tree) -> list[str]:
    want = [list(r) for r in rescale_rows()]
    bad = table_gate(t, "### 5.2", want, "luminance")
    slow = f"{ms('motion.duration.slow')} ms"
    for r in want:
        if float(r[5]) >= LUMA_CAP or r[6] != slow:
            bad.append(f"{r[0]}: worst {r[5]}, 10x lands in {r[6]}")
    return bad


def g_tokens(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    bad = L.check_token_refs(spec, L.token_names(repo(), BASE), MOTION_TOKEN_RE)
    consts = {
        "heatmap.recentre.bandFraction": f"{BAND_FRAC:.2f}",
        "heatmap.recentre.bandMinRows": str(BAND_MIN),
        "heatmap.recentre.bandMaxRows": str(BAND_MAX),
        "heatmap.recentre.minIntervalMs": str(INTERVAL_MS),
        "heatmap.rescale.lumaStep": f"{LUMA_STEP:.2f}",
        "heatmap.rescale.minReversalMs": str(REVERSAL_MS),
    }
    seen = set()
    for r in L.table_rows(sec(t, "## 9. Tokens and engine constants")):
        name = r[1].strip("`") if len(r) > 3 else ""
        if name in prim():
            if r[2] != str(prim()[name]) or r[3] != "shipped":
                bad.append(f"{name}: {r[2]} {r[3]}")
        elif name in consts:
            seen.add(name)
            if r[2] != consts[name] or r[3] != "PROPOSED, engine constant":
                bad.append(f"{name}: {r[2]} {r[3]}")
        else:
            bad.append(f"unknown row {name}")
    return bad + [f"missing {c}" for c in sorted(set(consts) - seen)]


def g_noupload(t: L.Tree) -> list[str]:
    bad = [f"{r[1]}: {r[5]}" for r in five(t) if len(r) < 7 or not r[5].startswith(COSTS)]
    text = t.text("spec").lower()
    return bad + [f"names {w!r}" for w in ("full re-upload per", "whole texture per") if w in text]


def g_adopt(t: L.Tree) -> list[str]:
    got = L.table_rows(sec(t, "### 6.1"))
    bad = [] if [r[2] for r in got if len(r) > 2] == list(ADOPT_CITES) else ["the adopted set"]
    for r in got:
        c = L.extract_cites(r[2], CITE_RE) if len(r) > 2 else []
        if not c or L.unquote(r[1]) not in line_of(c[0].doc, c[0].lo):
            bad.append(f"{r[0]} not verbatim")
    return bad


def g_t2(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    r3 = next((ln for ln in spec.split("\n") if ln.startswith("- **R-3 ")), "")
    bad = L.t2_markers(r3) + L.no_disabled_tokens(spec)
    return bad + ([] if "No control this spec touches is gated" in r3 else ["the no-gate line"])


def g_env(t: L.Tree) -> list[str]:
    s7 = sec(t, "## 7. Tier changes")
    need = ("C-2.11 is a hard constraint", "never moves, fades or sheds",
            "the session environment, never the feed", "DEMO and LIVE frames are separate")  # fmt: skip
    return [n for n in need if n not in s7]


def g_boards(t: L.Tree) -> list[str]:
    return L.board_cap(L.table_rows(sec(t, "## 0. Status")), "E21-D05", t.text("spec"))


def g_penpot(t: L.Tree) -> list[str]:
    return L.r7_findings(
        t.named("spec", "pins"), ("page `E21-D05`", "page id"), sec(t, "## 0. Status")
    )


def g_ruling(t: L.Tree) -> list[str]:
    return L.check_ruling(
        t.text("spec"),
        heading_line="## The questions BQ-0 … BQ-13 — defaults built; ruling pending "
        f"(comment {BQ_LIST})",
        list_ref=f"comment {BQ_LIST} on #505",
        count=14,
        verdict=lambda _n: "Default built:",
        need=("Ruling pending.",),
        forbid=("RULED",),
    )


def g_ruled(t: L.Tree) -> list[str]:
    return L.check_hash_pins(t.text("spec"), t.text("pins"))


def g_noclose(t: L.Tree) -> list[str]:
    return L.closing_keywords(t.named("spec", "pins")) + L.whitespace_hygiene(
        t.named("spec", "pins")
    )


def g_public(t: L.Tree) -> list[str]:
    return L.scan_public(t.named("spec", "pins")) + L.comment_findings(t.named("spec"))


def g_untouched(t: L.Tree) -> list[str]:
    globs = ("docs/design/E21/img/E21-D05-*.png",)
    return L.untouched(t.changed, OWN, globs, BUDGETS, t.numstat)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(t.text("spec"), "### 16.3", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper(), f) for f in (
    g_cite, g_quote, g_version, g_ac, g_five, g_recentre, g_crossover, g_rescale, g_tokens,
    g_noupload, g_adopt, g_t2, g_env, g_boards, g_penpot, g_ruling, g_ruled, g_noclose, g_public,
    g_untouched, g_mutlist,
))
# fmt: on

_M = L.Mutation
_V = "### 16.1 Version line\n"
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-CITE", "a cite past the end of `23`", "spec",
       "the `23`:811 target", "the `23`:99999 target"),
    _M("M-2", "G-QUOTE", "W-16 reworded off its line", "spec",
       '"Re-centres on every book update', '"Re-centres on each book update'),
    _M("M-3", "G-QUOTE", "W-21 reworded off its line", "spec",
       '"Depth 200 → 50 — levels 51–200 hidden · Pin 200"', '"Depth 200 → 50 · Pin 200"'),
    _M("M-4", "G-VERSION", "the version line drops the re-pin", "spec",
       "each re-pinned to the merge commit when", "each kept when"),
    _M("M-5", "G-AC", "a scenario name reworded", "spec",
       'AC "Rescale never flashes"', 'AC "Rescale is smooth"'),
    _M("M-6", "G-FIVE", "the re-centre's reduce twin translates", "spec",
       "a cut to the target row in one frame;", "a short translate to the target row;"),
    _M("M-7", "G-FIVE", "the resync carrier dropped", "spec",
       "W-10, the `feed.resyncing` notice and the W-12 tag (D02:226)", "none"),
    _M("M-8", "G-FIVE", "the rescale twin moves", "spec",
       "the same luminance-only ramp: nothing moves,", "a short slide of the legend,"),
    _M("M-9", "G-RECENTRE", "the 20 Hz replay doubles", "spec",
       r"(\| 20 Hz +\| edge to edge +\| 400 +\| )10( +\| )1025 ms", r"\g<1>20\g<2>525 ms",
       regex=True),
    _M("M-10", "G-RECENTRE", "the band ceiling written as 12", "spec",
       r"\| 60( +)\| 10( +)\| 40 ", r"| 60\1| 12\2| 36 ", regex=True),
    _M("M-11", "G-CROSSOVER", "1 080 p at 900 s drawn continuous", "spec",
       r"(\| 1 920 × 1 080 +\| 1190 +\| 900 s +\| 2269 +\| 1000 +\| 1\.32 +\| )step",
       r"\1continuous", regex=True),
    _M("M-12", "G-RESCALE", "a worst luminance step drifts", "spec",
       r"(\| dark +\| 0\.650 +\| 62% +\| 0\.347 +\| 0\.112 +\| )0\.091", r"\g<1>0.081",
       regex=True),
    _M("M-13", "G-TOKENS", "the luminance step loosened", "spec",
       r"(`heatmap\.rescale\.lumaStep` +\| )0\.09", r"\g<1>0.12", regex=True),
    _M("M-14", "G-TOKENS", "an unshipped duration token", "spec",
       "over `motion.duration.slow`, and each", "over `motion.duration.long`, and each"),
    _M("M-15", "G-NOUPLOAD", "a full ring upload per frame", "spec",
       "| uniform only (`26`:305)", "| a full ring upload per frame (`26`:305)"),
    _M("M-16", "G-ADOPT", "H7's hold misquoted", "spec", '"**3 s** (fixed)"', '"**5 s** (fixed)"'),
    _M("M-17", "G-T2", "R-3 loses the opacity ban", "spec",
       "never `color.text.disabled`, never `opacity.disabled` (G-T2.2)",
       "never `color.text.disabled` (G-T2.2)"),
    _M("M-18", "G-T2", "the no-gate line dropped", "spec",
       "No control this spec touches is gated", "One control this spec touches is gated"),
    _M("M-19", "G-ENV", "the badge may fade", "spec",
       "never moves, fades or sheds", "rarely moves"),
    _M("M-20", "G-BOARDS", "a fourth light twin", "spec",
       r"(`E21-D05 / 02 trail-step-continuous`[^\n]*\| )dark( +\| PENDING)", r"\1light\2",
       regex=True),
    _M("M-21", "G-PENPOT", "a Penpot file id", "spec",
       "page `E21-D05`, cited", "page `E21-D05` (" + "file" + "-id=0), cited"),
    _M("M-22", "G-RULING", "the heading claims a ruling", "spec",
       "BQ-13 — defaults built; ruling pending (comment", "BQ-13 — RULED (comment"),
    _M("M-23", "G-RULED", "a BQ default edited without a re-pin", "spec",
       "10 boards, 3 light twins (01, 03, 07)", "9 boards, 3 light twins (01, 03, 07)"),
    _M("M-24", "G-NOCLOSE", "a closing keyword", "spec", _V, _V + "\n" + "Clo" + "ses #505.\n"),
    _M("M-25", "G-NOCLOSE", "a forbidden heading", "spec", "## 13. Heuristic evaluation",
       "## " + "What" + " this spec " + "fix" + "es\n\n## 13. Heuristic evaluation"),
    _M("M-26", "G-NOCLOSE", "trailing whitespace", "spec", _V, "### 16.1 Version line \n"),
    _M("M-27", "G-PUBLIC", "a URL", "spec",
       "Penpot: the file", "Penpot (" + "http" + "s://example.org): the file"),
    _M("M-28", "G-PUBLIC", "an HTML comment", "spec", "## 13. Heuristic evaluation",
       "<" + "!-- note --" + ">\n\n## 13. Heuristic evaluation"),
    _M("M-29", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/05-accessibility-standard.md"),
    _M("M-30", "G-UNTOUCHED", "a third catalogue line", f"@numstat:{CAT_REL}", "", "3 0"),
    _M("M-31", "G-UNTOUCHED", "the 16 block grows", f"@numstat:{DSB_REL}", "", "19 0"),
    _M("M-32", "G-MUTLIST", "the list drifts", "spec", "| M-1  | G-CITE ", "| M-1  | G-AC   "),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    pins = ROOT / PIN_REL
    base = repo().diff_base(BASE)
    return L.Tree(
        files={
            "spec": (ROOT / SPEC_REL).read_text(encoding="utf-8"),
            "pins": pins.read_text(encoding="utf-8") if pins.exists() else "",
        },
        changed=repo().changed_paths(base),
        numstat={rel: repo().numstat(base, rel) for rel in BUDGETS},
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test() -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def repin() -> int:
    lines = L.bq_hash_pins((ROOT / SPEC_REL).read_text(encoding="utf-8"))
    head = "# E21-D05 ruled pins: sha256[:16] of each BQ bullet; written by --repin-ruled only"
    L.write_pins(ROOT / PIN_REL, "\n".join([head, *lines]))
    print(f"pinned {len(lines)} BQ lines")
    return 0


def replace_table(spec: str, heading: str, table: str) -> str:
    t0 = spec.index("\n|", spec.index(heading)) + 1
    end = t0
    for line in spec[t0:].split("\n"):
        if not line.startswith("|"):
            break
        end += len(line) + 1
    return spec[:t0] + table + "\n" + spec[end:]


def md(head: list[str], body: list[list[str]] | list[tuple[str, ...]]) -> str:
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in body])


def fill() -> int:
    p = ROOT / SPEC_REL
    spec = p.read_text(encoding="utf-8")
    tables = {
        "### 3.2": md(["Display (`23`:825–830)", "Device px", "Window", "`ideal_ms`", "Bucket ms",
                       "Column px", "Safe mode", "Reduce"], crossover_rows()),
        "### 4.2": md(["Visible rows", "Band rows (each edge)", "Quiet rows"], band_rows()),
        "### 4.3": md(["Visible rows", "Oscillation", "Amplitude", "Band rule alone", "This spec",
                       "Smallest gap"], replay_rows()),
        "### 5.2": md(["Theme", "Cut: worst ΔL", "Cut: cells ≥ 0.10", "`slow` eased, no cap",
                       "Smallest δ", "This spec: worst ΔL", "10× lands", "100× lands"],
                      list(rescale_rows())),
    }  # fmt: skip
    for heading, table in tables.items():
        spec = replace_table(spec, heading, table)
    head_end = spec.index("\n", spec.index("### 16.3")) + 1
    body = spec[:head_end] + "\n" + L.mutation_table(MUTATIONS) + "\n"
    p.write_text(body, encoding="utf-8", newline="\n")
    print("sections 3.2, 4.2, 4.3, 5.2 and 16.3 written")
    return 0


def main(argv: list[str]) -> int:
    modes = {"check": check, "self-test": self_test, "repin-ruled": repin, "fill": fill}
    return L.cli(argv, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
