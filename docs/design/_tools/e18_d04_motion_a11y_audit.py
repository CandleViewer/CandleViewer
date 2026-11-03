#!/usr/bin/env python3
"""E18-D04 (#498) audit: the footprint motion spec and accessibility review (text first).

Offline and default-deny. The shared gates (git, cites, pins, G-T2 vocabulary, closing keywords,
public text, G-UNTOUCHED, the runner and the mutation harness) live in `spec_audit_lib.py`; this
file keeps only E18-D04's rows. It reads, AS TEXT at the pinned base, the plan and design texts
the spec cites, the ticket JSON and the token JSON, and, from the working tree, the spec and its
figure. The only repo code it runs is `relative_luminance()` of
`docs/research/_tools/cvd_simulate.py`, loaded by path. Three simulations are its own: the
marker hold (section 3), the fill hold (section 4) and the LOD sweep over `LOD_PROFILE_M0`
(section 5); each written number in those tables is re-derived here.

Gates: G-CITE, G-PINS, G-VERSION, G-AC, G-BQ, G-TOKENS, G-MOTION (AC 1), G-HOLD, G-FLASH,
G-LOD (AC 3), G-LIVE (AC 2), G-KEYS, G-STOPS, G-FIGURE, G-SURVIVE, G-PARITY, G-ROUTE, G-T2,
G-ENV, G-NOCLOSE, G-PUBLIC, G-UNTOUCHED and G-MUTLIST (section 13.3 equals this tool's list).
The BQ list is comment 6609418330 on #498; its defaults are built and the ruling is pending
(G-BQ), so nothing is hash-pinned yet: the ruling fold adds the pins inside this file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e18_d04_motion_a11y_audit.py --check | --self-test
  python3 -I docs/design/_tools/e18_d04_motion_a11y_audit.py --figure   (writes figure A)
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
BASE = "b81479ab0"  # origin/main when the pack was written; every cite is read here
D03_HEAD = "72c20eafd"  # #497's text head the review reads, cited by section only
BQ_LIST = "6609418330"  # the BQ list on #498 (defaults built, ruling pending)
BQ_COUNT = 10

SPEC_REL = "docs/design/E18/E18-D04.md"
FIG_REL = "docs/design/E18/img/E18-D04-figA-focus-order.svg"
TOOL_REL = "docs/design/_tools/e18_d04_motion_a11y_audit.py"
LIB_REL = "docs/design/_tools/spec_audit_lib.py"
OWN = (SPEC_REL, FIG_REL, TOOL_REL, LIB_REL)
BACKLOG_REL = "docs/plan/backlog/E18.json"

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "26": "docs/plan/26-chart-engine-design.md",
}
KEYED = {
    "D02": L.DocRef("docs/design/E18/E18-D02.md", BASE),
    "E06D01": L.DocRef("docs/design/E06/E06-D01.md", BASE),
    "E06D03": L.DocRef("docs/design/E06/E06-D03.md", BASE),
    "E11D06": L.DocRef("docs/design/E11/E11-D06.md", BASE),
    "E11D07": L.DocRef("docs/design/E11/E11-D07.md", BASE),
    "E47D04": L.DocRef("docs/design/E47/E47-D04.md", BASE),
    "E47D06": L.DocRef("docs/design/E47/E47-D06.md", BASE),
    "E47D08": L.DocRef("docs/design/E47/E47-D08.md", BASE),
    "E47D09": L.DocRef("docs/design/E47/E47-D09.md", BASE),
    "K02": L.DocRef("docs/plan/spikes/E06-K02.md", BASE),
    "TOK": L.DocRef("packages/ui/tokens/primitives.tokens.json", BASE),
    "README": L.DocRef("docs/design/README.md", BASE),
}
CITE_RE = L.cite_regex(KEYED, ranges=True)

# The load-bearing cites: the needle must stand on the cited line at the base.
PINS: tuple[L.KeyCite, ...] = (
    L.KeyCite("11", 1666, "coalesced to ≤10 Hz"),
    L.KeyCite("26", 236, "asymmetric ±15 % hysteresis"),
    L.KeyCite("26", 244, "±15 % dead band"),
    L.KeyCite("26", 284, "alpha_outline"),
    L.KeyCite("26", 797, "disables momentum, fades and transitions"),
    L.KeyCite("05", 57, "`Alt+T`"),
    L.KeyCite("05", 186, "never throttled/coalesced"),
    L.KeyCite("05", 185, "1 update / 2s per field"),
    L.KeyCite("05", 187, "reduce announcements"),
    L.KeyCite("05", 202, '"Bid-stacked" / "Ask-stacked"'),
    L.KeyCite("05", 250, "single low-amplitude cross-fade"),
    L.KeyCite("05", 252, "No content flashes more than 3 times per second"),
    L.KeyCite("15", 1292, 'homeEnd: "col"'),
    L.KeyCite("16", 119, "motion.duration.{instant,fast,normal,slow}"),
    L.KeyCite("16", 212, "Dialog/drawer open"),
    L.KeyCite("16", 225, "`motion.hold.*` group"),
    L.KeyCite("16", 394, "code-only"),
    L.KeyCite("D02", 398, "250 ms cadence"),
    L.KeyCite("D02", 644, "miniature engine instance"),
    L.KeyCite("D02", 736, "oldest loaded bar; latest bar with follow on"),
    L.KeyCite("D02", 749, "footprint at low detail"),
    L.KeyCite("D02", 750, "a newly formed stack are"),
    L.KeyCite("D02", 913, "`stacked` / `stack_size` only"),
    L.KeyCite("E06D01", 59, "10.2px"),
    L.KeyCite("E06D01", 61, "8.5px"),
    L.KeyCite("E06D01", 71, "minHeightPx: 6"),
    L.KeyCite("E06D03", 105, "`repeatWindow` = 500 ms"),
    L.KeyCite("E11D06", 232, "one frame, in both modes"),
    L.KeyCite("E11D06", 372, "nothing switches a flag on under reduce"),
    L.KeyCite("E47D04", 227, "never cancels an order"),
    L.KeyCite("E47D06", 190, "Bid-stacked / Ask-stacked"),
    L.KeyCite("E47D08", 118, "Skip, never zero"),
    L.KeyCite("E47D08", 194, "crossings of the 0.1 luminance step"),
    L.KeyCite("E47D08", 195, "≥ 3 flashes in any 1 s"),
    L.KeyCite("E47D09", 204, "`Home` / `End` the oldest loaded / latest bar"),
    L.KeyCite("K02", 56, "<=6"),
    L.KeyCite("TOK", 460, '"100ms"'),
    L.KeyCite("TOK", 476, "[0, 0, 0, 1]"),
)

# ---------- the numbers this tool re-derives ------------------------------------------------------
FRAME_MS = 1000 / 60
HOLD_MS = 200  # the marker hold (section 3), PROPOSED into E08-D11's motion.hold.* group
FR6_CROSSINGS = 2  # E47-D08 FR-6, reused for the forming column's fills (section 4)
FR7_FLASHES = 3  # E47-D08 FR-7, the gate: fail at >= 3 flashes in any 1 s window
STEP = 0.1  # the 0.1 relative-luminance step of WCAG 2.3.1's general-flash definition
DARK_BELOW = 0.8  # the darker image is below 0.80
CADENCE_HZ = 10  # US-FP-009's coalescing ceiling
INPUT_HZ = range(1, CADENCE_HZ + 1)  # coalesced toggle rates the hold simulation tries
# LOD_PROFILE_M0 (E06-D01 section 2): down-switch below, up-switch at or above.
LOD_DOWN = {0: 10.2, 1: 8.5, 2: 6.0}
LOD_UP = {1: 12.0, 2: 10.0, 3: 6.0}
BAND = 1 / 0.85  # the dead band as a ratio: a wobble below it cannot cross back
SWEEPS = (("down", 20.0, 2.0), ("up", 2.0, 20.0))
JITTERS = (0.0, 0.07, 0.10)
GATED_JITTERS = (0.0, 0.07)
B2_MAX = 6
THEMES = tuple(L.THEME_PARTS)
FILLS = (
    "color.surface.canvas",
    "color.sell.default",
    "color.heatmap.ask.1",
    "color.heatmap.bid.1",
    "color.buy.default",
)
DURATIONS = {"instant": "0ms", "fast": "100ms", "normal": "200ms", "slow": "400ms"}
EASINGS = {
    "standard": [0.2, 0, 0, 1],
    "decelerate": [0, 0, 0, 1],
    "accelerate": [0.3, 0, 1, 1],
}
# The ticket's eight moments (T Scope), each a word that must name a row of section 2.
MOMENTS = (
    "forming-cell value",
    "forming-cell heat fill",
    "imbalance outline appears",
    "stacked zone",
    "LOD text",
    "POC",
    "unfinished-auction ledge",
    "drawer",
    "preview tile",
)
ANNOUNCE_TRIGGERS = ("focus move", "bar close", "new stack", "user zoom")
QUIET = ("forming-cell value", "imbalance", "POC", "fill", "markers")
D02_KEYS = ("`←` / `→`", "`↑` / `↓`", "`Enter`", "`Esc`", "`Home` / `End`", "`Alt+T`")
PARITY_FIELDS = (
    "price",
    "bid",
    "ask",
    "delta",
    "imbalance flag",
    "estimated",
    "point of control",
    "stack",
    "forming",
)
SURVIVE_ROWS = 6
LEVELS = ("L0", "L1", "L2", "L3")
OWNER_RE = re.compile(r"#\d+|\bE\d\d-[A-Z]\d\d\b|\bowner\b")
SVG_NS = "http" + "://www.w3.org/2000/svg"  # split so the public scan never reads it as a link
AGENT_RE = re.compile(r"\blens\b|\bagent\b", re.IGNORECASE)


@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def docs() -> L.Docs:
    return L.Docs(repo(), BASE, KEYED, plan=PLAN)


@functools.cache
def cvd() -> ModuleType:
    return L.load_module(ROOT, "docs/research/_tools/cvd_simulate.py", "cvd_simulate")


@functools.cache
def theme(name: str) -> dict[str, str]:
    return dict(L.resolve_theme(repo(), BASE, name))


def lum(hexv: str) -> float:
    return float(cvd().relative_luminance(hexv[:7]))


def worst_pair(name: str) -> tuple[str, str, float, float]:
    """The two fills a forming cell can reach with the largest luminance step, darker first."""
    t = theme(name)
    best = ("", "", 0.0, 0.0)
    for i, a in enumerate(FILLS):
        for b in FILLS[i + 1 :]:
            la, lb = lum(t[a]), lum(t[b])
            if abs(la - lb) > best[2]:
                lo, hi = (a, b) if la < lb else (b, a)
                best = (lo, hi, abs(la - lb), min(la, lb))
    return best


def window_max(times: list[float]) -> int:
    """The most events in any half-open 1 000 ms window ending on an event."""
    return max((sum(1 for x in times if t - 1000 < x <= t) for t in times), default=0)


def frames(secs: float = 10.0) -> list[float]:
    return [k * FRAME_MS for k in range(int(secs * 1000 / FRAME_MS))]


def hold_changes(in_hz: int, hold_ms: float) -> list[float]:
    """Section 3: a marker whose wanted state toggles at `in_hz`; a change is admitted only
    `hold_ms` after the last admitted one, the latest wanted state winning at the hold's end."""
    shown, last = 0, -1e9
    out: list[float] = []
    for now in frames():
        want = int(now // (1000 / in_hz)) % 2
        if want != shown and now - last >= hold_ms:
            shown, last = want, now
            out.append(now)
    return out


def fill_changes(in_hz: int, cap: int | None) -> list[float]:
    """Section 4: a fill alternating between the worst pair on each coalesced update (at most
    CADENCE_HZ); with `cap`, at most `cap` step crossings in any 1 000 ms window (FR-6)."""
    period = 1000 / min(in_hz, CADENCE_HZ)
    shown = 0
    out: list[float] = []
    for now in frames():
        want = int(now // period) % 2
        if want == shown:
            continue
        if cap is not None and sum(1 for x in out if now - 1000 < x <= now) >= cap:
            continue
        shown = want
        out.append(now)
    return out


def flashes(changes: int) -> int:
    return changes // 2


def lod_step(level: int, h: float) -> int:
    while True:
        if level in LOD_DOWN and h < LOD_DOWN[level]:
            level += 1
        elif level in LOD_UP and h >= LOD_UP[level]:
            level -= 1
        else:
            return level


def lod_sweep(h0: float, h1: float, jitter: float) -> tuple[int, int, int]:
    """(text thresholds crossed, text-tier changes, layer-level changes) over a 10 s sweep from
    h0 to h1 px of cell height at 60 Hz, with a 3 Hz multiplicative wobble of +-jitter."""
    level = lod_step(0 if h0 > h1 else 3, h0)
    tiers, levels = [min(level, 2)], [level]
    for i in range(1, 601):
        t = i / 60
        h = h0 * (h1 / h0) ** (t / 10) * (1 + jitter * math.sin(2 * math.pi * 3 * t))
        level = lod_step(level, h)
        tiers.append(min(level, 2))
        levels.append(level)
    lo, hi = min(h0, h1), max(h0, h1)
    crossed = sum(1 for th in (LOD_DOWN[0], LOD_DOWN[1]) if lo < th < hi)

    def changes(xs: list[int]) -> int:
        return sum(1 for a, b in itertools.pairwise(xs) if a != b)

    return crossed, changes(tiers), changes(levels)


# ---------- spec helpers --------------------------------------------------------------------------
def rows(block: str) -> list[list[str]]:
    return L.table_rows(block)


def sec(t: L.Tree, heading: str) -> str:
    return L.section(t.text("spec"), heading)


def bullet(spec: str, rid: str) -> str:
    return next((ln for ln in spec.split("\n") if ln.startswith(f"- **{rid} ")), "")


def fmt(x: float, nd: int = 3) -> str:
    return f"{x:.{nd}f}"


# ---------- the gates -----------------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    bad = L.check_cites(L.extract_cites(t.text("spec"), CITE_RE), docs(), min_count=80)
    return [f"unresolved cites: {', '.join(b.split(' (')[0] for b in bad)}"] if bad else []


def g_pins(t: L.Tree) -> list[str]:
    bad = L.check_key_cites(PINS, docs())
    cited = {
        (c.doc, n) for c in L.extract_cites(t.text("spec"), CITE_RE) for n in range(c.lo, c.hi + 1)
    }
    bad += [f"{p.doc}:{p.line} pinned but not cited" for p in PINS if (p.doc, p.line) not in cited]
    return bad


def g_version(t: L.Tree) -> list[str]:
    spec, v = t.text("spec"), sec(t, "### 13.1 Version line")
    miss = [n for n in (BASE, D03_HEAD, "re-pinned", "#497") if n not in v]
    if f"Base `origin/main` `{BASE}`" not in spec:
        miss.append("the Inputs line's base")
    if f"`{D03_HEAD}`" not in spec or "if #497 merges as is" not in spec:
        miss.append("the D03 pin")
    return [f"missing: {', '.join(miss)}"] if miss else []


def g_ac(t: L.Tree) -> list[str]:
    tickets = json.loads(repo().show(BASE, BACKLOG_REL) or "[]")
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E18-D04")
    names = re.findall(r"Scenario: (.+)", body)
    dod = re.findall(r"- \[ \] (.+)", body)
    first = [r[0] for r in rows(sec(t, "## Acceptance-criteria and DoD trace"))]
    miss = [n for n in names if f'AC "{n.strip()}"' not in first]
    miss += [d for d in dod if f"DoD {d.strip()}" not in first]
    if len(names) != 3 or len(dod) != 5:
        miss.append(f"{len(names)} scenarios, {len(dod)} DoD items")
    return [f"not traced verbatim: {miss}"] if miss else []


def g_bq(t: L.Tree) -> list[str]:
    bad = L.check_ruling(
        t.text("spec"),
        heading_line=(
            f"## The questions BQ-0 … BQ-{BQ_COUNT - 1} — defaults built; ruling pending "
            f"(comment {BQ_LIST})"
        ),
        list_ref=f"comment {BQ_LIST} on #498",
        count=BQ_COUNT,
        verdict=lambda _n: "**PENDING** (ORCH-default built)",
        need=("Built:",),
        forbid=("RULED",),
    )
    walk = sec(t, "## 12. Owner walkthrough")
    if f"comment {BQ_LIST}" not in walk or "ruling pending" not in walk:
        bad.append("the walkthrough's BQ item")
    return bad


def g_tokens(t: L.Tree) -> list[str]:
    raw = L.token_file(repo(), BASE, "primitives")
    bad = []
    for k, v in DURATIONS.items():
        if raw.get(f"motion.duration.{k}", {}).get("$value") != v:
            bad.append(f"motion.duration.{k} is not {v} at the base")
    for k, arr in EASINGS.items():
        if raw.get(f"motion.easing.{k}", {}).get("$value") != arr:
            bad.append(f"motion.easing.{k} is not {arr} at the base")
    spec = t.text("spec")
    for line in spec.split("\n"):
        for m in re.finditer(r"`(motion\.[a-z]+\.[a-z*]+)`", line):
            name = m.group(1)
            if name.startswith("motion.hold."):
                if "PROPOSED" not in line:
                    bad.append(f"{name} bound outside its PROPOSED line")
            elif name not in raw:
                bad.append(f"{name} is not shipped")
    head = bullet(spec, "R-1")
    for need in ("0 / 100 / 200 / 400 ms", "frame loop", "four numbers", "never CSS"):
        if need not in head:
            bad.append(f"R-1 lacks {need!r}")
    bad += L.check_token_refs(spec, L.token_names(repo(), BASE))
    return bad


def g_motion(t: L.Tree) -> list[str]:
    got = rows(sec(t, "## 2. The motion table"))
    bad = [] if len(got) >= len(MOMENTS) else [f"{len(got)} rows"]
    names = " ".join(r[1] for r in got if len(r) > 1)
    bad += [f"no row for {m!r}" for m in MOMENTS if m not in names]
    for r in got:
        if len(r) < 10:
            bad.append(f"{r[0] if r else '?'} has {len(r)} cells")
            continue
        mid, prop, dur, ease, red, calm, carrier = r[0], r[3], r[4], r[5], r[6], r[7], r[8]
        if not red.startswith("instant") or "same as" in red.lower():
            bad.append(f"{mid} reduce is {red!r}")
        if not calm.startswith("instant") and not calm.startswith("runs"):
            bad.append(f"{mid} canvas calm is {calm!r}")
        cut = dur == "a cut"
        if not cut and not re.fullmatch(r"`motion\.duration\.(fast|normal|slow)`.*", dur):
            bad.append(f"{mid} duration {dur!r}")
        if cut != (ease == "a cut") or (
            not cut and not re.fullmatch(r"`motion\.easing\.[a-z]+`.*", ease)
        ):
            bad.append(f"{mid} easing {ease!r}")
        if cut != prop.startswith("none"):
            bad.append(f"{mid} property {prop!r} against its duration")
        if re.search(r"\b(scale|bounce|slide)\b", prop):
            bad.append(f"{mid} animates scale, bounce or a slide")
        if not carrier or carrier == "—":
            bad.append(f"{mid} has no carrier")
    return bad


def hold_numbers() -> dict[str, str]:
    held = max(window_max(hold_changes(f, HOLD_MS)) for f in INPUT_HZ)
    free = max(window_max(hold_changes(f, 0)) for f in INPUT_HZ)
    return {
        "unheld": f"{free} changes, {flashes(free)} flashes",
        "held": f"{held} changes, {flashes(held)} flashes",
        "cycles": f"{held / 2:.1f}",
    }


def g_hold(t: L.Tree) -> list[str]:
    s3 = sec(t, "## 3. The flicker policy")
    want = hold_numbers()
    got = {r[0]: r[1] for r in rows(s3) if len(r) > 1}
    bad = [f"{k}: {got.get(k)!r} != {v!r}" for k, v in want.items() if got.get(k) != v]
    held = int(want["held"].split()[0])
    if flashes(held) >= FR7_FLASHES:
        bad.append("the hold does not keep a marker under FR-7")
    for need in (f"{HOLD_MS} ms", "latest wins", "never scale or bounce", "never a slide"):
        if need not in s3:
            bad.append(f"lacks {need!r}")
    return bad


def flash_rows() -> list[list[str]]:
    out = []
    for name in THEMES:
        lo, hi, d, dark = worst_pair(name)
        pair = "yes" if d >= STEP and dark < DARK_BELOW else "no"
        free = window_max(fill_changes(CADENCE_HZ, None))
        held = window_max(fill_changes(CADENCE_HZ, FR6_CROSSINGS))
        out.append(
            [
                name,
                f"`{lo}` → `{hi}`",
                fmt(d),
                fmt(dark),
                pair,
                str(flashes(free)),
                str(flashes(held)),
            ]
        )
    return out


def g_flash(t: L.Tree) -> list[str]:
    got = [r[:7] for r in rows(sec(t, "## 4. The forming bar"))]
    want = flash_rows()
    bad = [] if got == want else [f"table differs from the tool: {want}"]
    if any(int(r[6]) >= FR7_FLASHES for r in want):
        bad.append("a held fill reaches FR-7")
    return bad


def lod_rows() -> list[list[str]]:
    out = []
    for name, h0, h1 in SWEEPS:
        for j in JITTERS:
            crossed, text, layer = lod_sweep(h0, h1, j)
            out.append([name, f"±{round(j * 100)} %", str(crossed), str(text), str(layer)])
    return out


def g_lod(t: L.Tree) -> list[str]:
    s5 = sec(t, "## 5. LOD text")
    want = lod_rows()
    got = [r[:5] for r in rows(s5)]
    bad = [] if got == want else [f"table differs from the tool: {want}"]
    for r in want:
        gated = float(r[1].strip("± %")) / 100 in GATED_JITTERS
        if gated and r[2] != r[3]:
            bad.append(f"{r[0]} {r[1]}: {r[3]} text changes for {r[2]} crossings")
    round_trip = sum(int(r[4]) for r in want if r[1] == "±0 %")
    if round_trip > B2_MAX:
        bad.append(f"round trip {round_trip} > {B2_MAX}")
    if max(GATED_JITTERS) * 2 >= BAND - 1 + 0.03:
        bad.append("a gated wobble reaches the dead band")
    for need in ("one alpha uniform", "never a second pass", "a hard cut", "fills"):
        if need not in s5:
            bad.append(f"lacks {need!r}")
    return bad


def g_live(t: L.Tree) -> list[str]:
    block = sec(t, "### 7.3 The announcement policy table")
    got = rows(block)
    bad = []
    said = [r for r in got if len(r) > 3 and r[2].startswith("yes")]
    quiet = [r for r in got if len(r) > 3 and r[2].startswith("no")]
    for r in said:
        if not any(r[1].startswith(tr) for tr in ANNOUNCE_TRIGGERS):
            bad.append(f"{r[0]} announces on {r[1]!r}")
        if "assertive" in r[3]:
            bad.append(f"{r[0]} is assertive")
    names = " ".join(r[1] for r in quiet)
    bad += [f"no not-announced row for {q!r}" for q in QUIET if q not in names]
    stack = next((r for r in said if r[1].startswith("new stack")), [])
    if not stack or "≤ 1 / 2 s" not in " ".join(stack) or "master toggle" not in " ".join(stack):
        bad.append("the new-stack row's cadence or master toggle")
    if "signed artefact" not in block or "E18-S11 #741" not in block or "E18-Q04" not in block:
        bad.append("the consumers")
    return bad


def g_keys(t: L.Tree) -> list[str]:
    got = rows(sec(t, "### 7.2 The keyboard map"))
    keys = [r[0] for r in got]
    bad = [f"no row for {k}" for k in D02_KEYS if k not in keys]
    he = next((r for r in got if r[0] == "`Home` / `End`"), [])
    if not he or "oldest loaded" not in he[1] or 'homeEnd: "col"' not in " ".join(he):
        bad.append("Home / End reading")
    esc = next((r for r in got if r[0] == "`Esc`"), [])
    if not esc or "never cancels an order" not in " ".join(esc):
        bad.append("Esc layering")
    return bad


def stop_rows(spec: str) -> list[list[str]]:
    return rows(L.section(spec, "### 7.1 Focus order"))


def g_stops(t: L.Tree) -> list[str]:
    got = stop_rows(t.text("spec"))
    ids = [r[0] for r in got]
    bad = [] if ids == [f"FS{i:02d}" for i in range(1, len(ids) + 1)] else [f"ids {ids}"]
    if f"Stops: {len(ids)}." not in sec(t, "### 7.1 Focus order"):
        bad.append("the stop count")
    for r in got:
        if len(r) < 7 or not all(r[1:7]):
            bad.append(f"{r[0] if r else '?'} has an empty cell")
            continue
        refs = re.findall(r"FS\d\d", r[4] + r[5])
        bad += [f"{r[0]} names {x}" for x in refs if x not in ids]
    return bad


def figure(spec: str) -> str:
    """Figure A: the stop table as boxes in Tab order with their enter keys (SVG, text only)."""
    got = stop_rows(spec)
    h = 40 + 56 * len(got)
    out = [
        (
            f'<svg xmlns="{SVG_NS}" width="720" height="{h}" '
            f'viewBox="0 0 720 {h}" font-family="sans-serif" font-size="13">'
        ),
        "<title>E18-D04 figure A: the footprint layer's focus stops (section 7.1)</title>",
        '<rect width="720" height="100%" fill="white"/>',
    ]
    for i, r in enumerate(got):
        y = 20 + 56 * i
        label = f"{r[0]} {L.unquote(r[1])}"[:70].replace("&", "&amp;").replace("<", "&lt;")
        enter = f"from: {r[4]}"[:90].replace("&", "&amp;").replace("<", "&lt;")
        out.append(f'<rect x="20" y="{y}" width="680" height="40" fill="white" stroke="black"/>')
        out.append(f'<text x="30" y="{y + 17}">{label}</text>')
        out.append(f'<text x="30" y="{y + 33}" font-size="11">{enter}</text>')
        if i + 1 < len(got):
            out.append(f'<line x1="360" y1="{y + 40}" x2="360" y2="{y + 56}" stroke="black"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def g_figure(t: L.Tree) -> list[str]:
    want = figure(t.text("spec"))
    return [] if t.text("figure") == want else ["figure A is stale (run --figure)"]


def g_survive(t: L.Tree) -> list[str]:
    got = rows(sec(t, "### 7.6 Non-colour survival per LOD"))
    bad = [] if len(got) == SURVIVE_ROWS else [f"{len(got)} rows"]
    for r in got:
        if len(r) < 6 or any(not c for c in r[1:5]):
            bad.append(f"{r[0] if r else '?'} has an empty level")
            continue
        for lvl, cell in zip(LEVELS, r[1:5]):
            if cell.startswith("gone") and not ("SCR-045" in r[5] or re.search(r"F-\d", cell)):
                bad.append(f"{r[0]} at {lvl}: gone with no alternative")
    return bad


def f_ids(spec: str) -> list[str]:
    return [r[0] for r in rows(L.section(spec, "## 9. Findings"))]


def g_parity(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    got = rows(sec(t, "### 7.5 SCR-045 parity"))
    fields = [r[0] for r in got]
    bad = [f"no row for {f}" for f in PARITY_FIELDS if f not in fields]
    fs = f_ids(spec)
    for r in got:
        if len(r) < 4:
            bad.append(f"{r[0]} cells")
        elif r[3] != "parity" and not any(f in r[3] for f in fs):
            bad.append(f"{r[0]} is {r[3]!r} without an F-row")
    return bad


def g_route(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    bad = []
    for r in rows(sec(t, "## 9. Findings")):
        if len(r) < 6 or "(heuristic)" not in r[2] or not OWNER_RE.search(r[4]):
            bad.append(f"{r[0] if r else '?'} unmarked or unrouted")
    for head in ("### 10.1", "### 10.2", "### 10.3", "### 10.4"):
        for r in rows(sec(t, head)):
            if not OWNER_RE.search(r[-1]) or AGENT_RE.search(r[-1]):
                bad.append(f"{r[0]} owner {r[-1]!r}")
    for r in rows(sec(t, "### 10.3")):
        if len(r) < 4 or not L.extract_cites(r[1], CITE_RE) or not r[2]:
            bad.append(f"{r[0]} lacks its Old cite or its New")
    if not rows(sec(t, "## 9. Findings")):
        bad.append("no findings table")
    if "never edited here" not in sec(t, "## 10. Rows"):
        bad.append("the routing rule")
    return bad + [f"F-row {f} never cited" for f in f_ids(spec) if spec.count(f) < 2]


def g_t2(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    return L.t2_markers(bullet(spec, "R-9")) + L.no_disabled_tokens(spec)


def g_env(t: L.Tree) -> list[str]:
    r10 = bullet(t.text("spec"), "R-10")
    need = ("C-2.11", "hard constraint", "public market data", "no environment")
    return [n for n in need if n not in r10]


def g_noclose(t: L.Tree) -> list[str]:
    return L.closing_keywords(t.named("spec", "figure"))


def g_public(t: L.Tree) -> list[str]:
    named = t.named("spec")
    fig = [("figure", t.text("figure").replace(SVG_NS, ""))]
    return (
        L.scan_public([*named, *fig])
        + L.comment_findings(named)
        + L.whitespace_hygiene(t.named("spec", "figure"))
    )


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN, (), {}, t.numstat)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(t.text("spec"), "### 13.3", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper(), f) for f in (
    g_cite, g_pins, g_version, g_ac, g_bq, g_tokens, g_motion, g_hold, g_flash, g_lod, g_live,
    g_keys, g_stops, g_figure, g_survive, g_parity, g_route, g_t2, g_env, g_noclose, g_public,
    g_untouched, g_mutlist,
))
# fmt: on


def _refigure(m: L.Mutation) -> L.Mutation:
    """A mutation of the stop table that also re-renders the figure, so only its own gate trips."""

    def fn(tree: L.Tree) -> L.Tree:
        t2 = L.apply_mutation(tree, L.Mutation(m.mid, m.gate, m.what, m.path, m.find, m.replace))
        return L.Tree({**t2.files, "figure": figure(t2.text("spec"))}, t2.changed, t2.numstat)

    return L.Mutation(m.mid, m.gate, m.what, m.path, m.find, m.replace, m.regex, fn)


_M = L.Mutation
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-CITE", "a cite past the end of `26`", "spec", "`26`:797", "`26`:99999"),
    _M("M-2", "G-PINS", "a pinned cite moved off its line", "spec", "(K02:56)", "(K02:55)"),
    _M("M-3", "G-VERSION", "the D03 pin loses its condition", "spec",
       "if #497 merges as is", "once #497 merges"),
    _M("M-4", "G-AC", "a scenario name reworded", "spec",
       'AC "LOD switching does not flicker"', 'AC "LOD switching does not flash"'),
    _M("M-5", "G-BQ", "a bullet claims a ruling", "spec",
       "**PENDING** (ORCH-default built). Built: the flicker",
       "**RULED** (ORCH-default built). Built: the flicker"),
    _M("M-6", "G-TOKENS", "an unshipped motion token", "spec",
       "`motion.easing.decelerate` (the ticket's", "`motion.easing.easeout` (the ticket's"),
    _M("M-7", "G-MOTION", "a reduce cell left as the default", "spec",
       r"(\| M-03 [^\n]*?\| )instant( +\|)", r"\1same as default\2", regex=True),
    _M("M-8", "G-MOTION", "a marker bounces", "spec",
       "outline alpha 0 → 1", "outline scale 0 → 1, a bounce"),
    _M("M-9", "G-MOTION", "a bespoke duration", "spec",
       r"(\| M-02 [^|]*\|[^|]*\|[^|]*\|[^|]*\| )`motion\.duration\.fast`", r"\g<1>120 ms", regex=True),
    _M("M-10", "G-HOLD", "a written hold number drifts", "spec",
       r"(\| held +\| )\d+ changes", r"\g<1>9 changes", regex=True),
    _M("M-11", "G-FLASH", "a written luminance step drifts", "spec",
       r"(\| dark +\|[^|]+\| )\d\.\d{3}", r"\g<1>0.001", regex=True),
    _M("M-12", "G-LOD", "the sweep table drifts", "spec",
       r"(\| down +\| ±7 % +\| 2 +\| )2", r"\g<1>3", regex=True),
    _M("M-13", "G-LOD", "the crossfade becomes a second pass", "spec",
       "fades: one alpha uniform", "fades: a second batched draw"),
    _M("M-14", "G-LIVE", "forming cells announced", "spec",
       r"(\| LR-0?\d+ +\| forming-cell value[^|]*\| )no", r"\1yes", regex=True),
    _M("M-15", "G-LIVE", "the new-stack row loses its cadence", "spec",
       "polite, ≤ 1 / 2 s", "polite, per stack"),
    _M("M-16", "G-KEYS", "Home / End read as row ends", "spec",
       "oldest loaded bar; latest bar", "the row's first and last cell"),
    _refigure(_M("M-17", "G-STOPS", "a stop leaves to a stop that does not exist", "spec",
                 "`Esc` to FS02", "`Esc` to FS99")),
    _M("M-18", "G-FIGURE", "the figure goes stale", "figure", "FS02", "FS20"),
    _M("M-19", "G-SURVIVE", "a channel gone with no alternative", "spec",
       r"(\| delta sign [^\n]*\| )gone at L3[^|]*\|[^|]*\|", r"\1gone | none |", regex=True),
    _M("M-20", "G-PARITY", "a gap with no F-row", "spec",
       r"(\| point of control +\|[^|]+\|[^|]+\| )gap → F-2", r"\1gap", regex=True),
    _M("M-21", "G-ROUTE", "a finding without (heuristic)", "spec",
       r"(\| F-1 +\|[^|]+\| )\(heuristic\) ", r"\1", regex=True),
    _M("M-22", "G-ROUTE", "an open question owned by a lens", "spec",
       r"(\| OQ-1 [^\n]*\| )[^|\n]+\|\n", r"\1the motion lens |\n", regex=True),
    _M("M-23", "G-T2", "R-9 loses the opacity ban", "spec",
       "never `color.text.disabled`, never `opacity.disabled`", "never `color.text.disabled`"),
    _M("M-24", "G-ENV", "C-2.11 no longer hard", "spec",
       "C-2.11 is a hard constraint", "C-2.11 is a preference"),
    _M("M-25", "G-NOCLOSE", "a closing keyword", "spec",
       "Refs #498", "Clo" + "ses #498"),
    _M("M-26", "G-PUBLIC", "a URL", "spec",
       "Refs #498", "Refs #498 " + "http" + "s://example.org"),
    _M("M-27", "G-UNTOUCHED", "an owner document edited", "@changed", "",
       "docs/plan/15-component-catalogue.md"),
    _M("M-28", "G-MUTLIST", "the list drifts", "spec",
       "| M-28 | G-MUTLIST   | the list drifts", "| M-28 | G-MUTLIST   | the list moved"),
)
# fmt: on


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def read_tree() -> L.Tree:
    base = repo().diff_base(BASE)
    return L.Tree(
        files={"spec": read(SPEC_REL), "figure": read(FIG_REL)},
        changed=repo().changed_paths(base),
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test() -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def write_figure() -> int:
    out = ROOT / FIG_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(figure(read(SPEC_REL)), encoding="utf-8", newline="\n")
    print(f"wrote {FIG_REL}")
    return 0


def main(argv: list[str]) -> int:
    modes = {"check": check, "self-test": self_test, "figure": write_figure}
    return L.cli(argv, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
