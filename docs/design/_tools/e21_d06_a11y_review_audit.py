#!/usr/bin/env python3
"""E21-D06 (#506) audit: the accessibility review of SCR-050's ladder grid and heatmap reveal.

Offline and default-deny. The shared gates (git, cites, pins, the G-T2 markers, closing keywords,
public text, hygiene, G-UNTOUCHED, the runner and the mutation harness) live in
`spec_audit_lib.py`, which sits beside this file byte-identical (G-HELPER); this file keeps only
E21-D06's rows. It reads, AS TEXT at a pinned commit, every document the review cites (the base
for the plan, the merged parents, the keymap and the built a11y modules; the two unmerged parents
at their PR heads), and, from the working tree, the review, its pins file and the helper. The
only repo code it runs is `contrast_ratio()` of `docs/design/_tools/contrast_check.py`,
`simulate()` / `delta_e76()` of `docs/research/_tools/cvd_simulate.py`, and the `PAIRS` lists of
E21-D02's and E21-D04's audit tools, imported (never copied) by path.

Gates: G-CITE, G-KEYCITE, G-VERSION, G-AC, G-INBOX, G-DECISIONS, G-KEYS, G-T2, G-LIVE, G-COLOUR,
G-CONTRAST, G-CVD, G-VERDICT, G-FINDINGS, G-IDS, G-HANDOFF, G-WALK, G-RULING, G-RIDERS,
G-RULED, G-NOCLOSE, G-PUBLIC, G-HYGIENE, G-HELPER, G-UNTOUCHED and G-MUTLIST (section 16.3
equals this tool's list). Pins (G-RULED): each BQ bullet's sha256[:16] in
`e21_d06_ruled_pins.txt`; `--repin-ruled` is the only writer. The BQ list is comment 6596009389
on #506 and its ruling of record is comment 6599703549: every bullet reads RULED, agreed or
amended as the ruling says (G-RULING), and every rider has its RR row (G-RIDERS).

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e21_d06_a11y_review_audit.py --check | --json | --self-test
  python3 -I -B docs/design/_tools/e21_d06_a11y_review_audit.py --repin | --repin-ruled | --fill
`--repin` prints where each key cite's words stand now; `--fill` writes sections 9 and 16.3.
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
BASE = "d023df0f6"  # origin/main where the ruling of record re-checked every cite
D03_HEAD = "c7b0d2087"  # #5518 (E21-D03, #503) head; re-pinned to its merge commit
D05_HEAD = "031c411d8"  # #5554 (E21-D05, #505) head; re-pinned to its merge commit
BQ_LIST = "6596009389"  # the BQ list on #506
RULING = "6599703549"  # the orchestrator's ruling of record on it
AGREED = (0, 1, 2, 14, 15)  # agreed as written; every other bullet amended
RIDERS = 25  # the RR rows: one per amendment, rider, missed row and cite note of the ruling
HELPER_SHA = "62b56d6446b218cd"  # sha256[:16] of the shared helper as landed

SPEC_REL = "docs/design/E21/E21-D06.md"
TOOL_REL = "docs/design/_tools/e21_d06_a11y_review_audit.py"
PIN_REL = "docs/design/_tools/e21_d06_ruled_pins.txt"
LIB_REL = "docs/design/_tools/spec_audit_lib.py"
OWN = (SPEC_REL, TOOL_REL, PIN_REL, LIB_REL)
BACKLOG_REL = "docs/plan/backlog/E21.json"
D02_TOOL = "docs/design/_tools/e21_d02_scr050_audit.py"
D04_TOOL = "docs/design/_tools/e21_d04_ds_audit.py"

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
}
KEYED = {
    "D02": L.DocRef("docs/design/E21/E21-D02.md", BASE),
    "D03": L.DocRef("docs/design/E21/E21-D03.md", D03_HEAD),
    "D04": L.DocRef("docs/design/E21/E21-D04.md", BASE),
    "D05": L.DocRef("docs/design/E21/E21-D05.md", D05_HEAD),
    "M": L.DocRef("docs/design/research/e21-dom-heatmap.md", BASE),
    "DS": L.DocRef(".claude/rules/32-design-specs.md", BASE),
    "KM": L.DocRef("apps/web/src/keymap/keymap.json", BASE),
    "PREF": L.DocRef("apps/web/src/features/a11y-preferences/model.ts", BASE),
    "FMT": L.DocRef("apps/web/src/chart/a11y/orderflowFormat.ts", BASE),
    "E08-D12": L.DocRef("docs/design/E08/E08-D12.md", BASE),
    "E09-D09": L.DocRef("docs/design/E09/E09-D09.md", BASE),
    "E27-D05": L.DocRef("docs/design/E27/E27-D05.md", BASE),
    "E47-D03": L.DocRef("docs/design/E47/E47-D03.md", BASE),
    "E47-D04": L.DocRef("docs/design/E47/E47-D04.md", BASE),
    "E47-D06": L.DocRef("docs/design/E47/E47-D06.md", BASE),
    "E47-D07": L.DocRef("docs/design/E47/E47-D07.md", BASE),
    "E47-D09": L.DocRef("docs/design/E47/E47-D09.md", BASE),
    "E17-D02": L.DocRef("docs/design/E17/E17-D02.md", BASE),
    "E17-D03": L.DocRef("docs/design/E17/E17-D03.md", BASE),
    "E14-D10": L.DocRef("docs/design/E14/E14-D10.md", BASE),
    "E08-D05": L.DocRef("docs/design/E08/E08-D05.md", BASE),
}
_ALTS = "|".join(re.escape(k) for k in sorted(KEYED, key=len, reverse=True))
# `NN`:line, KEY:line or `KEY`:line, with an optional –end.
CITE_RE = re.compile(
    rf"(?:`(?P<nn>\d\d)`|`?(?<![A-Za-z0-9-])(?P<named>{_ALTS})`?):(?P<first>\d+)"
    r"(?:–(?P<firstend>\d+))?"
)

# The load-bearing cites, pinned to their words (`--repin` proposes moves).
KEY_CITES: tuple[L.KeyCite, ...] = tuple(
    L.KeyCite(d, n, s)
    for d, n, s in (
        ("14", 1218, "`Ctrl+Shift+X` = cancel all working orders"),
        ("14", 1221, "64 100, ask 42, own order 0.1 working"),
        ("05", 63, "`Ctrl+Delete` (when order row focused)"),
        ("05", 67, "Place limit at focused row"),
        ("05", 69, "Cancel all at focused row"),
        ("05", 85, "zoom ladder price step"),
        ("05", 99, "Roving tabindex"),
        ("05", 185, "default 1 update / 2s per field"),
        ("05", 215, "up to 200-depth"),
        ("05", 227, "press Alt+T to refresh"),
        ("05", 229, "load more rows"),
        ("15", 1240, "`Shift+Enter`=sell"),
        ("15", 1262, "ladderRowSentence"),
        ("15", 1310, "press a documented key"),
        ("KM", 340, '"Alt+T"'),
        ("KM", 370, '"Ctrl+Shift+X"'),
        ("KM", 411, '"Space"'),
        ("KM", 426, '"Ctrl+Shift+T"'),
        ("D02", 136, "R-7 Announcements"),
        ("D02", 371, "`Shift+Enter` (PROPOSED)"),
        ("D02", 396, "load more rows"),
        ("D04", 99, "nor by the E21 state key"),
        ("D04", 151, "`Delete` cancels the row's one own order"),
        ("D04", 159, "the windowed reveal"),
        ("D05", 169, "Focus hold (PROPOSED; E21-D06 #506)"),
        ("D03", 274, "Save is T2"),
        ("PREF", 25, 'announce_prices: "significant"'),
        ("PREF", 92, "if (update.significant) return true;"),
        ("E08-D12", 106, "three objects"),
        ("DS", 15, "G-T2 miss is a Major"),
        ("14", 2497, "announce price updates"),
        ("E47-D04", 219, "Keys beyond the APG grid set"),
        ("E47-D04", 223, "the ladder: best bid"),
        ("E47-D04", 227, "a focused order cancels with `Ctrl+Delete`"),
        ("E47-D04", 283, "the nearest surviving level by price"),
        ("E47-D09", 163, "the row's menu (`Shift+F10`)"),
        ("E47-D09", 165, "`Ctrl+Enter` at the focused row"),
        ("E47-D09", 247, "`Ctrl+Shift+T` (KMAP:426, :564)"),
        ("E47-D09", 248, "`Ctrl+Shift+X` (KMAP:370)"),
        ("E47-D06", 240, "`Enter` on a row opens the level's history"),
        ("E47-D06", 258, "**Refresh to current**"),
        ("E47-D06", 428, "D06-C16"),
        ("E47-D03", 311, "the column header at Compact"),
        ("E47-D07", 210, "silent"),
        ("E17-D03", 243, "the heatmap table's column set is missing"),
    )
)

DEFICIENCIES = ("deuteranopia", "protanopia", "tritanopia")
CANVAS = "color.surface.canvas"
STOPS = "color.heatmap.*"
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
AREAS = ("order-flow", "design-system", "frontend-platform")
DISPOSITIONS = ("decision", "F row", "A row", "C row", "G row", "verdict")
LR_OBJECTS = ("field", "region", "episode", "press", "silent")
LR_POLITE = ("polite", "assertive", "off")
LR_RATES = ("1 per 2 s", "1 per 5 s", "once", "once per press", "never", "at most once a second")
LR_SILENT_NEED = ("heatmap column", "book tick", "reveal")
VERDICTS = (
    "compliant if #503 merges as is",
    "compliant if #505 merges as is",
    "compliant",
    "at risk",
    "non-compliant",
    "out of scope —",
    "not yet decidable —",
    "ruled divergence — BQ-",
)
SCENARIOS = 3
# Section 9.3: the carriers' pairs the parents leave unmeasured (F-11, G-06); the env badge's
# candidates and the amber, marker and accent inks. Measured; a floor miss is a finding, not a FAIL.
REVIEW_PAIRS: tuple[tuple[str, str, float], ...] = (
    ("color.text.primary", "color.env.demo", 4.5),
    ("color.text.primary", "color.env.live", 4.5),
    ("color.text.on-action", "color.env.demo", 4.5),
    ("color.text.on-action", "color.env.live", 4.5),
    ("color.env.demo", "color.surface.canvas", 4.5),
    ("color.env.live", "color.surface.canvas", 4.5),
    ("color.status.warning.default", "color.surface.canvas", 4.5),
    ("color.status.warning.strong", "color.surface.canvas", 4.5),
    ("color.position.entry", "color.surface.canvas", 3.0),
    ("color.buy.default", "color.surface.raised", 4.5),
    ("color.sell.default", "color.surface.raised", 4.5),
)
HOLD = (
    "**Hold:** E21-D02 (#440), E21-D03 (#503) and E21-D04 (#504) are not signed off while a"
    " Blocking row stands"
)
F_HEAD_RE = re.compile(
    r"^## 12\. Findings — F (\d+) \(Blocking (\d+) · Major (\d+) · Minor (\d+) · Info (\d+)\)"
    r" <!-- audit:f=(\d+)/(\d+)/(\d+)/(\d+)/(\d+) -->$",
    re.MULTILINE | re.DOTALL,
)
F_MARK_RE = re.compile(r" audit:f=\d+/\d+/\d+/\d+/\d+ ", re.DOTALL)
PREFIXES = "IB|AD|FO|KS|T2|LR|CR|SR|RR|F|V|C|G|Q|A|H"
ID_RE = re.compile(rf"(?:{PREFIXES})-\d\d")
# An own id; another spec's ids carry its prefix ("D04 A-36", "M F-15") and are skipped.
REF_RE = re.compile(rf"(?<![\w-])(?<!D0\d )(?<!M )(?:{PREFIXES})-\d\d(?![\w.]*\d)(?!\.\d)")
POINTER_WORDS = re.compile(r"\b(?:click|hover|drag|mouse|pointer)\b", re.IGNORECASE)


# ---------- sources and measurers -----------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def docs() -> L.Docs:
    return L.Docs(repo(), BASE, KEYED, plan=PLAN)


@functools.cache
def measurers() -> tuple[ModuleType, ModuleType]:
    return (
        L.load_module(ROOT, "docs/design/_tools/contrast_check.py", "contrast_check"),
        L.load_module(ROOT, "docs/research/_tools/cvd_simulate.py", "cvd_simulate"),
    )


def load_tool(rel: str, name: str) -> ModuleType:
    """A parent's audit tool by path, registered in sys.modules (its dataclasses need that)."""
    if name in sys.modules:
        return sys.modules[name]
    spec_ = importlib.util.spec_from_file_location(name, ROOT / rel)
    if spec_ is None or spec_.loader is None:
        raise L.AuditError(f"cannot load {rel}")
    mod = importlib.util.module_from_spec(spec_)
    sys.modules[name] = mod
    spec_.loader.exec_module(mod)
    return mod


@functools.cache
def parent_pairs() -> tuple[tuple[str, str, float], ...]:
    """E21-D02's and E21-D04's pair lists, imported from their tools; union, first seen wins."""
    out: dict[tuple[str, str], float] = {}
    for rel, name in ((D02_TOOL, "e21_d02_audit"), (D04_TOOL, "e21_d04_audit")):
        for fg, bg, floor in load_tool(rel, name).PAIRS:
            out.setdefault((str(fg), str(bg)), float(floor))
    return tuple((fg, bg, floor) for (fg, bg), floor in out.items())


@functools.cache
def theme(name: str) -> dict[str, str]:
    return L.resolve_theme(repo(), BASE, name)


def rgb(hexv: str) -> tuple[int, int, int]:
    h = hexv.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return float(measurers()[0].contrast_ratio(rgb(fg), rgb(bg)))


def stops(prefix: str) -> list[str]:
    return [f"{prefix}.{s}.{i}" for s in ("bid", "ask") for i in range(1, 6)]


def smallest_de(t: dict[str, str], prefix: str, deficiency: str) -> float:
    cvd = measurers()[1]
    return min(
        float(
            cvd.delta_e76(
                cvd.simulate(t[f"{prefix}.bid.{i}"], deficiency),
                cvd.simulate(t[f"{prefix}.ask.{i}"], deficiency),
            )
        )
        for i in range(1, 6)
    )


def stop_row(name: str) -> list[str]:
    """Section 9.1's row for one theme, cell by cell."""
    t = theme(name)

    def lowest(prefix: str) -> tuple[str, float]:
        best = min(stops(prefix), key=lambda k: ratio(t[k], t[CANVAS]))
        return best, ratio(t[best], t[CANVAS])

    low, low_r = lowest("color.heatmap")
    twin, twin_r = lowest("color.cvd.heatmap")
    twin_de = min(smallest_de(t, "color.cvd.heatmap", d) for d in DEFICIENCIES)
    return [
        name,
        f"`{low}`",
        f"{low_r:.2f}",
        f"{smallest_de(t, 'color.heatmap', 'deuteranopia'):.1f}",
        f"`{twin}`",
        f"{twin_r:.2f}",
        f"{twin_de:.1f}",
    ]


def pair_ratio(name: str, fg: str, bg: str) -> float:
    t = theme(name)
    if fg == STOPS:
        return min(ratio(t[k], t[bg]) for k in stops("color.heatmap"))
    return ratio(t[fg], t[bg])


def pair_row(fg: str, bg: str, floor: float) -> list[str]:
    return [
        f"`{fg}` on `{bg}`",
        f"{floor:g}",
        *(f"{pair_ratio(n, fg, bg):.2f}" for n in L.THEME_PARTS),
    ]


def review_row(fg: str, bg: str, floor: float) -> list[str]:
    """Section 9.3's row: the measured pair and whether it meets its floor in every theme."""
    row = pair_row(fg, bg, floor)
    return [*row, "yes" if min(float(v) for v in row[2:]) >= floor else "no"]


# ---------- spec helpers --------------------------------------------------------------------------
def spec(t: L.Tree) -> str:
    return t.text("spec")


def sec(t: L.Tree, heading: str) -> str:
    return L.section(spec(t), heading)


def rows(t: L.Tree, heading: str) -> list[list[str]]:
    return L.table_rows(sec(t, heading))


def defined_ids(text: str) -> set[str]:
    out: set[str] = set()
    for line in text.split("\n"):
        if line.startswith("|"):
            first = L.cells(line)[0] if L.cells(line) else ""
            if ID_RE.fullmatch(first):
                out.add(first)
    return out


def ids_in(cell: str) -> list[str]:
    return REF_RE.findall(cell)


# ---------- this review's gates -------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    cites = L.extract_cites(spec(t), CITE_RE)
    bad = L.check_cites(cites, docs(), nonblank=False, min_count=150)
    # A range may span blank lines; its two ends must carry text.
    bad += [
        c.raw
        for c in cites
        if not (docs().line(c.doc, c.lo) or "").strip()
        or not (docs().line(c.doc, c.hi) or "").strip()
    ]
    return [f"unresolved cites: {', '.join(b.split(' (')[0] for b in bad)}"] if bad else []


def g_keycite(t: L.Tree) -> list[str]:
    d = docs()
    drift = t.text("drift")  # "KEY|line|text": a source drifted in memory (self-test only)
    if drift:
        key, n, text = drift.split("|", 2)
        lines = list(d.lines(key) or ())
        lines[int(n) - 1] = text
        d = d.drifted(key, tuple(lines))
    return L.check_key_cites(KEY_CITES, d)


def g_version(t: L.Tree) -> list[str]:
    v = sec(t, "### 16.1 Version line")
    need = (BASE, D03_HEAD, D05_HEAD, "re-pinned to its merge commit", HELPER_SHA)
    miss = [n for n in need if n not in v]
    if f"Base `origin/main` `{BASE}`" not in spec(t):
        miss.append("Inputs pinned base")
    return [f"missing: {', '.join(miss)}"] if miss else []


def g_ac(t: L.Tree) -> list[str]:
    tickets = json.loads(repo().show(BASE, BACKLOG_REL) or "[]")
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E21-D06")
    names = [n.strip() for n in re.findall(r"Scenario: (.+)", body)]
    trace = sec(t, "## Acceptance-criteria and DoD trace")
    miss = [n for n in names if f'AC "{n}"' not in trace]
    return (
        [f"scenario names not verbatim: {miss or names}"] if len(names) != SCENARIOS or miss else []
    )


def g_inbox(t: L.Tree) -> list[str]:
    got = rows(t, "## 2. The inbox")
    defined = defined_ids(spec(t))
    bad = (
        []
        if [r[0] for r in got] == [f"IB-{i:02d}" for i in range(1, 23)]
        else ["not IB-01 … IB-22"]
    )
    for r in got:
        if len(r) < 4 or r[2] not in DISPOSITIONS:
            bad.append(f"{r[0]} disposition")
        elif not ids_in(r[3]) or any(i not in defined for i in ids_in(r[3])):
            bad.append(f"{r[0]} target")
    return bad


def g_decisions(t: L.Tree) -> list[str]:
    got = rows(t, "## 3. Adopted decisions")
    bad = (
        []
        if [r[0] for r in got] == [f"AD-{i:02d}" for i in range(1, 11)]
        else ["not AD-01 … AD-10"]
    )
    for r in got:
        if len(r) < 4 or not r[2].strip("— ") or not re.search(r"#\d+", r[3]):
            bad.append(f"{r[0]} test or owner")
    return bad


def g_keys(t: L.Tree) -> list[str]:
    keymap = {(r[0], r[1]): r for r in rows(t, "### 5.1") if len(r) > 3}
    bad = [f"bare `Delete` bound in {c}" for k, c in keymap if k == "`Delete`"]
    if "cancels" not in keymap.get(("`Ctrl+Delete`", "grid row"), ["", "", ""])[2]:
        bad.append("`Ctrl+Delete` row cancel")
    if "DOM context" not in keymap.get(("`Shift+Enter`", "grid row"), ["", "", ""])[2]:
        bad.append("`Shift+Enter` not scoped to the DOM context")
    if "row action menu" not in keymap.get(("`Enter`", "grid row or cell"), ["", "", ""])[2]:
        bad.append("`Enter` is not the row menu")
    if "row action menu" not in keymap.get(("`Shift+F10` / `Menu`", "grid row"), ["", "", ""])[2]:
        bad.append("no `Shift+F10` / `Menu` path to the row menu")
    if "first / last cell" not in keymap.get(("`Home` / `End`", "grid"), ["", "", ""])[2]:
        bad.append("`Home` / `End` lose the APG grid meaning")
    for r in rows(t, "### 5.2"):
        if len(r) < 5 or "`" not in r[2] or POINTER_WORDS.search(r[2]) or "`" not in r[4]:
            bad.append(f"{r[0] if r else '?'} not keyboard-only with a way out")
    return bad


def g_t2(t: L.Tree) -> list[str]:
    r4 = next((ln for ln in spec(t).split("\n") if ln.startswith("- **R-4 ")), "")
    bad = L.t2_markers(r4) + L.no_disabled_tokens(spec(t))
    got = rows(t, "## 6. Gated controls")
    if not got or "rbac.view_as" not in got[0][4] or "viewing as" not in got[0][1]:
        bad.append("the view-as row is not first")
    for r in got:
        if len(r) < 6 or r[2] not in ("T2", "not gated"):
            bad.append(f"{r[0] if r else '?'} class")
        elif re.search(r"CXL|cancel|Ctrl\+Delete", r[1]) and "never the arm" not in r[4]:
            bad.append(f"{r[0]} cancel gated on the arm")
    return bad


def g_live(t: L.Tree) -> list[str]:
    bad = []
    got = rows(t, "## 7. The live-region policy")
    for r in got:
        if len(r) < 6 or r[1] not in LR_OBJECTS or r[3] not in LR_POLITE or r[4] not in LR_RATES:
            bad.append(f"{r[0] if r else '?'} object, politeness or rate")
        elif r[1] == "silent" and (r[3], r[4]) != ("off", "never"):
            bad.append(f"{r[0]} silent row spoken")
        elif not L.extract_cites(r[5], CITE_RE) and "`T`" not in r[5]:
            bad.append(f"{r[0]} source")
    silent = " ".join(r[2] for r in got if len(r) > 2 and r[1] == "silent")
    bad += [f"no silent row for {w}" for w in LR_SILENT_NEED if w not in silent]
    field = [r for r in got if len(r) > 5 and r[1] == "field"]
    if len(field) != 1 or field[0][4] != "1 per 2 s" or "`05`:185" not in field[0][5]:
        bad.append("the field row")
    return bad


def g_colour(t: L.Tree) -> list[str]:
    bad = []
    for r in rows(t, "## 8. Colour never"):
        if len(r) < 6 or not r[3].strip("— ") or not r[4].strip("— "):
            bad.append(f"{r[0] if r else '?'} carrier")
        elif r[5] not in ("compliant", "at risk"):
            bad.append(f"{r[0]} verdict")
        elif r[5] == "at risk" and not re.search(r"F-\d\d", " ".join(r)):
            bad.append(f"{r[0]} at risk names no F row")
    return bad


def g_contrast(t: L.Tree) -> list[str]:
    bad = []
    got = {r[0]: r for r in rows(t, "### 9.1")}
    for name in L.THEME_PARTS:
        want, r = stop_row(name), got.get(name, [])
        if [r[i] for i in (1, 2, 4, 5)] != [want[i] for i in (1, 2, 4, 5)] if len(r) > 6 else True:
            bad.append(f"9.1 {name}: measured {want[1:3] + want[4:6]}")
        if float(want[2]) < 3.0 or float(want[5]) < 3.0:
            bad.append(f"9.1 {name} stop below 3")
    written = {r[0]: r for r in rows(t, "### 9.2")}
    for fg, bg, floor in parent_pairs():
        want_pair = pair_row(fg, bg, floor)
        if written.get(want_pair[0], [])[:5] != want_pair:
            bad.append(f"9.2 {want_pair[0]}: measured {want_pair[1:]}")
        if min(float(v) for v in want_pair[2:]) < floor:
            bad.append(f"9.2 {want_pair[0]} below {floor:g}")
    if len(written) != len(parent_pairs()):
        bad.append(f"{len(written)} pair rows for {len(parent_pairs())} pairs")
    added = {r[0]: r for r in rows(t, "### 9.3")}
    for q in REVIEW_PAIRS:
        want_row = review_row(*q)
        if added.get(want_row[0], [])[:6] != want_row:
            bad.append(f"9.3 {want_row[0]}: measured {want_row[1:]}")
    if len(added) != len(REVIEW_PAIRS):
        bad.append(f"{len(added)} 9.3 rows for {len(REVIEW_PAIRS)} pairs")
    return bad


def g_cvd(t: L.Tree) -> list[str]:
    got = {r[0]: r for r in rows(t, "### 9.1")}
    bad = []
    for name in L.THEME_PARTS:
        want, r = stop_row(name), got.get(name, [])
        if len(r) < 7 or [r[3], r[6]] != [want[3], want[6]]:
            bad.append(f"9.1 {name}: ΔE measured {[want[3], want[6]]}")
    return bad


def g_verdict(t: L.Tree) -> list[str]:
    sev = {r[0]: r[1] for r in rows(t, "## 12. Findings") if len(r) > 1}
    bad = []
    for r in rows(t, "## 11. Clause verdicts"):
        v = r[2] if len(r) > 3 else ""
        fs = re.findall(r"F-\d\d", v)
        if not v.startswith(VERDICTS):
            bad.append(f"{r[0] if r else '?'} vocabulary")
        elif v.startswith("compliant") and fs:
            bad.append(f"{r[0]} compliant names an F row")
        elif v.startswith("at risk") and not fs and "interim:" not in v:
            bad.append(f"{r[0]} at risk names no F row or interim path")
        elif v.startswith("non-compliant") and not any(sev.get(f) == "Blocking" for f in fs):
            bad.append(f"{r[0]} non-compliant without a Blocking row")
        elif v.startswith("ruled divergence") and not (
            re.search(r"C-\d\d", v) and re.search(r"A-\d\d", v)
        ):
            bad.append(f"{r[0]} ruled divergence without its C row and A row")
    return bad


def g_findings(t: L.Tree) -> list[str]:
    got = rows(t, "## 12. Findings")
    counts = [len(got)] + [sum(1 for r in got if r[1] == s) for s in SEVERITIES]
    m = F_HEAD_RE.search(spec(t))
    bad = []
    if m is None or [int(x) for x in m.groups()] != counts + counts:
        bad.append(f"heading or marker vs table {counts}")
    if HOLD not in sec(t, "## 12. Findings"):
        bad.append("hold sentence")
    for r in got:
        if len(r) < 7 or r[1] not in SEVERITIES:
            bad.append(f"{r[0] if r else '?'} severity")
            continue
        if not re.search(r"\b\d\.\d\.\d+\b|`05`", r[4]):
            bad.append(f"{r[0]} criterion")
        if not any(f"({a})" in r[5] for a in AREAS):
            bad.append(f"{r[0]} owner")
        info = r[1] == "Info"
        parent = re.search(r"#440|#503|#504", r[6])
        story = re.search(r"#648|#649", r[6])
        if "E21-D07 #576" not in r[6] or (not info and not (parent and story)):
            bad.append(f"{r[0]} targets")
        if info and r[6] != "E21-D07 #576":
            bad.append(f"{r[0]} Info targets")
    return bad


def g_ids(t: L.Tree) -> list[str]:
    defined = defined_ids(spec(t))
    refs = set(REF_RE.findall(spec(t)))
    return [f"dangling: {', '.join(sorted(refs - defined))}"] if refs - defined else []


def g_handoff(t: L.Tree) -> list[str]:
    got = rows(t, "### 13.5")
    q05 = [r for r in got if len(r) > 3 and "E21-Q05 #700" in r[3]]
    bad = [
        f"{r[0]} assertion name"
        for r in q05
        if not re.search(r"`scr050\.[a-z0-9.-]+` \((?:axe|Playwright)", r[1])
    ]
    covered = {i for r in q05 for i in re.findall(r"AD-\d\d", r[2])}
    ads = {r[0] for r in rows(t, "## 3. Adopted decisions")}
    return bad + [f"{a} reaches no E21-Q05 assertion" for a in sorted(ads - covered)]


def g_walk(t: L.Tree) -> list[str]:
    items = re.findall(r"^(\d+)\. ", sec(t, "### 14.3"), re.MULTILINE)
    n = len(items)
    ok = 0 < n <= 10 and items == [str(i) for i in range(1, n + 1)]
    return [] if ok else [f"{n} walkthrough items"]


def g_ruling(t: L.Tree) -> list[str]:
    return L.check_ruling(
        spec(t),
        heading_line=(
            f"## The questions BQ-0 … BQ-15 — RULED (orchestrator, comment {RULING},"
            f" on the BQ list {BQ_LIST})"
        ),
        list_ref=f"comment {BQ_LIST} on #506",
        count=16,
        verdict=lambda n: f"RULED ({RULING}), {'agreed' if n in AGREED else 'amended'}: ",
        need=("Built as:",),
        forbid=("PENDING (comment", "Default built:"),
    )


def g_riders(t: L.Tree) -> list[str]:
    got = rows(t, "## The ruling's riders")
    defined = defined_ids(spec(t))
    bad = (
        []
        if [r[0] for r in got] == [f"RR-{i:02d}" for i in range(1, RIDERS + 1)]
        else [f"not RR-01 … RR-{RIDERS:02d}"]
    )
    for r in got:
        if len(r) < 3 or not re.match(r"BQ-\d+|missed|cites", r[1]):
            bad.append(f"{r[0] if r else '?'} source")
        elif not ids_in(r[2]) or any(i not in defined for i in ids_in(r[2])):
            bad.append(f"{r[0]} lands nowhere")
    return bad


def g_ruled(t: L.Tree) -> list[str]:
    return L.check_hash_pins(spec(t), t.text("pins"))


def g_noclose(t: L.Tree) -> list[str]:
    return L.closing_keywords(t.named("spec", "pins", "tool"))


def g_public(t: L.Tree) -> list[str]:
    texts = t.named("spec", "pins", "tool")
    return L.scan_public(texts) + L.comment_findings(t.named("spec"), F_MARK_RE)


def g_hygiene(t: L.Tree) -> list[str]:
    return L.whitespace_hygiene(t.named("spec", "pins", "tool"))


def g_helper(t: L.Tree) -> list[str]:
    got = hashlib.sha256(t.text("lib").encode("utf-8")).hexdigest()
    return [] if got.startswith(HELPER_SHA) else [f"{LIB_REL} is {got[:16]}, not {HELPER_SHA}"]


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(spec(t), "### 16.3", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper(), f) for f in (
    g_cite, g_keycite, g_version, g_ac, g_inbox, g_decisions, g_keys, g_t2, g_live, g_colour,
    g_contrast, g_cvd, g_verdict, g_findings, g_ids, g_handoff, g_walk, g_ruling, g_riders,
    g_ruled, g_noclose, g_public, g_hygiene, g_helper, g_untouched, g_mutlist,
))
# fmt: on


def _drift(text: str) -> L.Mutation:
    def fn(tree: L.Tree) -> L.Tree:
        return dataclasses.replace(tree, files={**tree.files, "drift": text})

    return L.Mutation("M-02", "G-KEYCITE", "a pinned source line reworded", fn=fn)


_M = L.Mutation
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-01", "G-CITE", "a cite past the end of D02", "spec", "(D02:194)", "(D02:99999)"),
    _drift("14|1221|- **A11y:** the ladder announces the price only."),
    _M("M-03", "G-VERSION", "the version line drops the re-pin", "spec",
       "each re-pinned to its merge commit when it merges", "each kept when it merges"),
    _M("M-04", "G-AC", "a scenario name reworded", "spec",
       'AC "No live-region flooding"', 'AC "No flooding"'),
    _M("M-05", "G-INBOX", "an inbox row deferred", "spec",
       r"(\| IB-04 \|[^\n]*?\| )decision", r"\1deferred", regex=True),
    _M("M-06", "G-DECISIONS", "a decision with no owner ticket", "spec",
       r"(\| AD-10 \|[^\n]*\| )E21-S01 #648( *\|)", r"\1the build\2", regex=True),
    _M("M-07", "G-KEYS", "bare Delete bound on a row", "spec",
       r"\| `Ctrl\+Delete` +\| grid row", "| `Delete` | grid row", regex=True),
    _M("M-08", "G-KEYS", "a walk needs a pointer", "spec",
       "`Tab` to `BUY MKT`; `Enter`", "click `BUY MKT`"),
    _M("M-09", "G-T2", "R-4 loses the describedby link", "spec",
       "linked by `aria-describedby` (G-T2.1c)", "linked (G-T2.1c)"),
    _M("M-10", "G-T2", "a cancel gated on the arm", "spec",
       r"(\| T2-03 \|[^\n]*?)never the arm", r"\1the arm", regex=True),
    _M("M-11", "G-LIVE", "the heatmap column spoken", "spec",
       r"(\| LR-12 \|[^\n]*?\| )off( +\| )never", r"\1polite\2once", regex=True),
    _M("M-12", "G-LIVE", "a rate not from 05 or a parent", "spec",
       r"(\| LR-02 \|[^\n]*?\| )1 per 5 s", r"\g<1>1 per 3 s", regex=True),
    _M("M-13", "G-COLOUR", "estimated carried by nothing", "spec",
       r"(\| CR-09 \|[^|]*\|[^|]*\| )[^|]*?( +\|)", r"\1—\2", regex=True),
    _M("M-14", "G-CONTRAST", "a written pair ratio drifts", "spec",
       r"(`color\.text\.primary` on `color\.surface\.canvas` *\| 4\.5 *\| )\d+\.\d\d",
       r"\g<1>9.99", regex=True),
    _M("M-15", "G-CVD", "a written distance drifts", "spec",
       r"(\| dark +\|[^|]*\|[^|]*\| )\d+\.\d( +\|)", r"\g<1>9.9\2", regex=True),
    _M("M-16", "G-VERDICT", "a compliant verdict names an F row", "spec",
       r"(\| V-14 \|[^\n]*?\| )at risk — F-03", r"\1compliant — F-03", regex=True),
    _M("M-17", "G-FINDINGS", "the heading count drifts", "spec",
       "Major 3 · Minor 13 · Info 1)", "Major 3 · Minor 12 · Info 1)"),
    _M("M-18", "G-FINDINGS", "a finding loses its story", "spec",
       r"(\| F-02 \|[^\n]*?#504 PR 2 · E21-D07 #576) · E21-S01 #648", r"\1", regex=True),
    _M("M-19", "G-FINDINGS", "the hold sentence dropped", "spec",
       "**Hold:** E21-D02 (#440)", "Hold: E21-D02 (#440)"),
    _M("M-20", "G-IDS", "a dangling F id", "spec", "(F-01, G-01, G-02)", "(F-31, G-01, G-02)"),
    _M("M-21", "G-HANDOFF", "a decision with no Q05 assertion", "spec",
       "| AD-10; V-09 ", "| V-09        "),
    _M("M-22", "G-WALK", "an eleventh walkthrough item", "spec",
       "10. Comment `approved`", "10. One more pass.\n11. Comment `approved`"),
    _M("M-23", "G-RULING", "the heading names another comment", "spec",
       "RULED (orchestrator, comment 6599703549,", "RULED (orchestrator, comment 6599703548,"),
    _M("M-24", "G-RULED", "a BQ default edited without a re-pin", "spec",
       "Built as: 24 / 32 px rows", "Built as: 24 / 30 px rows"),
    _M("M-25", "G-NOCLOSE", "a closing keyword", "spec",
       "nothing is filed.", "nothing is filed. " + "Clo" + "ses #506."),
    _M("M-26", "G-PUBLIC", "a URL", "spec",
       "**No new boards and no new Penpot page**",
       "**No new boards and no new Penpot page** (" + "http" + "s://example.org)"),
    _M("M-27", "G-PUBLIC", "a stray HTML comment", "spec",
       "## 17. Summary for #506", "## 17. Summary for #506 " + "<!" + "-- note -->"),
    _M("M-28", "G-HYGIENE", "trailing whitespace", "spec",
       "## 17. Summary for #506\n", "## 17. Summary for #506  \n"),
    _M("M-29", "G-HELPER", "the helper edited", "lib",
       "Shared gates for the per-spec", "Shared checks for the per-spec"),
    _M("M-30", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/05-accessibility-standard.md"),
    _M("M-31", "G-MUTLIST", "the list drifts", "spec",
       r"\| M-01 +\| G-CITE +\|", "| M-01 | G-AC |", regex=True),
    _M("M-32", "G-KEYS", "`Home` / `End` back on the best prices", "spec",
       r"(\| `Home` / `End` +\| grid +\| )the row's first / last cell", r"\1the best ask / bid",
       regex=True),
    _M("M-33", "G-KEYS", "no `Shift+F10` path to the row menu", "spec",
       r"(\| `Shift\+F10` / `Menu` +\| grid row +\| )the row action menu", r"\1the context menu",
       regex=True),
    _M("M-34", "G-VERDICT", "a ruled divergence without its A row", "spec",
       "opens the row menu (C-04; A-03)", "opens the row menu (C-04)"),
    _M("M-35", "G-RIDERS", "a rider built nowhere", "spec",
       r"(\| RR-17 \|[^\n]*\| )CR-01( +\|)", r"\1§8\2", regex=True),
    _M("M-36", "G-FINDINGS", "the hold drops #504", "spec",
       "E21-D03 (#503) and E21-D04 (#504) are not signed off while",
       "E21-D03 (#503) are not signed off while"),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    def disk(rel: str) -> str:
        p = ROOT / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""

    return L.Tree(
        files={
            "spec": disk(SPEC_REL),
            "pins": disk(PIN_REL),
            "tool": disk(TOOL_REL),
            "lib": disk(LIB_REL),
        },
        changed=repo().changed_paths(repo().diff_base(BASE)),
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def as_json() -> int:
    res = L.run_gates(GATES, read_tree())
    print(
        json.dumps([{"gate": r.gate, "ok": r.ok, "detail": list(r.detail)} for r in res], indent=1)
    )
    return 0 if all(r.ok for r in res) else 1


def self_test() -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def repin() -> int:
    for pin, now in L.repin_key_cites(KEY_CITES, docs()):
        where = "gone" if now is None else str(now)
        print(f"{pin.doc}:{pin.line} -> {where} {pin.needle!r}")
    return 0


def repin_ruled() -> int:
    lines = L.bq_hash_pins((ROOT / SPEC_REL).read_text(encoding="utf-8"))
    head = "# E21-D06 ruled pins: sha256[:16] of each BQ bullet; written by --repin-ruled only"
    L.write_pins(ROOT / PIN_REL, "\n".join([head, *lines]))
    print(f"pinned {len(lines)} BQ lines")
    return 0


def replace_table(text: str, heading: str, table: str) -> str:
    t0 = text.index("\n|", text.index(heading)) + 1
    end = t0
    for line in text[t0:].split("\n"):
        if not line.startswith("|"):
            break
        end += len(line) + 1
    return text[:t0] + table + "\n" + text[end:]


def fill() -> int:
    p = ROOT / SPEC_REL
    text = p.read_text(encoding="utf-8")
    t91 = (
        "| Theme | Lowest stop | Ratio | Deuteranopia ΔE | CVD set lowest stop | Ratio "
        "| CVD set smallest ΔE |\n| --- | --- | --- | --- | --- | --- | --- |\n"
    ) + "\n".join("| " + " | ".join(stop_row(n)) + " |" for n in L.THEME_PARTS)
    t92 = "| Pair | Floor | dark | light | high-contrast |\n| --- | --- | --- | --- | --- |\n"
    t92 += "\n".join("| " + " | ".join(pair_row(*q)) + " |" for q in parent_pairs())
    t93 = "| Pair | Floor | dark | light | high-contrast | Meets in all three |\n"
    t93 += "| --- | --- | --- | --- | --- | --- |\n"
    t93 += "\n".join("| " + " | ".join(review_row(*q)) + " |" for q in REVIEW_PAIRS)
    text = replace_table(replace_table(text, "### 9.1", t91), "### 9.2", t92)
    text = replace_table(text, "### 9.3", t93)
    text = replace_table(text, "### 16.3", L.mutation_table(MUTATIONS))
    p.write_text(text, encoding="utf-8", newline="\n")
    print("sections 9.1, 9.2, 9.3 and 16.3 written")
    return 0


def main(argv: list[str]) -> int:
    modes = {
        "check": check,
        "json": as_json,
        "self-test": self_test,
        "repin": repin,
        "repin-ruled": repin_ruled,
        "fill": fill,
    }
    return L.cli(argv, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
