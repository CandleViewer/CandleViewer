#!/usr/bin/env python3
"""E26-D06 (#513) audit: the replay motion spec and accessibility design review.

Offline and default-deny. The shared gates (git, cites, pins, the G-T2 markers, closing keywords,
public text, hygiene, boards, G-UNTOUCHED, the runner and the mutation harness) live in
`spec_audit_lib.py`, which sits beside this file byte-identical (G-HELPER); this file keeps only
E26-D06's rows. It reads, AS TEXT at a pinned commit, every document the review cites (the base
for the plan, the research memo, E26-D02's merged text, E11-D06, the E47 specs, the keymap and the
tokens; E26-D02 at its boards PR head as D02B and E26-D03 ... D05 at their assembled heads), and,
from the working tree, the review and the helper. The only repo code it runs is
`contrast_ratio()` of `docs/design/_tools/contrast_check.py` and `simulate()` / `delta_e76()` of
`docs/research/_tools/cvd_simulate.py`, loaded by path.

Gates: G-CITE, G-KEYCITE, G-VERSION, G-AC, G-INBOX, G-DECISIONS, G-MOTION, G-TOKENS, G-SPEED,
G-KEYS, G-T2, G-LIVE, G-COLOUR, G-ENV, G-CONTRAST, G-CVD, G-VERDICT, G-FINDINGS, G-IDS,
G-HANDOFF, G-WALK, G-BOARDS, G-RULING, G-RULED, G-OUTRANK, G-NOCLOSE, G-PUBLIC, G-HYGIENE,
G-HELPER, G-UNTOUCHED and G-MUTLIST (section 17.3 equals this tool's list). The BQ list is
comment 6598368751 on #513, RULED by comment 6608045629 (G-RULING). Pins (G-RULED): each BQ
bullet's sha256[:16] in RULED_PINS below, with no separate pins file (the pack rule);
`--repin-ruled` is the only writer of that block.

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e26_d06_motion_a11y_audit.py --check | --json | --self-test
  python3 -I -B docs/design/_tools/e26_d06_motion_a11y_audit.py --repin | --repin-ruled | --fill
`--repin` prints where each key cite's words stand now; `--fill` writes sections 10 and 17.3.
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import re
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
BASE = "b81479ab0"  # origin/main at the ruling fold; the BQ list read 497856e27
D02B_HEAD = "06967e08a"  # #5513 (E26-D02 boards, #509) head; re-pinned to its merge commit
D03_HEAD = "582a7c956"  # E26-D03 (#510) assembled head; re-pinned to its merge commit
D04_HEAD = "78a17238e"  # E26-D04 (#511) assembled head; re-pinned to its merge commit
D05_HEAD = "14a0ff517"  # E26-D05 (#512) assembled head; re-pinned to its merge commit
BQ_LIST = "6598368751"  # the BQ list on #513
RULING = "6608045629"  # the orchestrator's ruling of record on the BQ list
BQ_VERDICTS = (
    "AGREE",
    "AGREE",
    "AMEND",
    "AGREE",
    "AMEND",
    "AGREE (ruled 20×)",
    "AGREE",
    "DISAGREE",
    "AMEND",
    "AGREE",
    "AGREE",
    "AGREE",
    "AGREE",
    "AGREE",
)
HELPER_SHA = "62b56d6446b218cd"  # sha256[:16] of the shared helper as landed

SPEC_REL = "docs/design/E26/E26-D06.md"
TOOL_REL = "docs/design/_tools/e26_d06_motion_a11y_audit.py"
LIB_REL = "docs/design/_tools/spec_audit_lib.py"
OWN = (SPEC_REL, TOOL_REL, LIB_REL)
BACKLOG_REL = "docs/plan/backlog/E26.json"
PRIM_REL = "packages/ui/tokens/primitives.tokens.json"

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
}
_E26 = "docs/design/E26/E26-"
KEYED = {
    "D01": L.DocRef("docs/research/ux/replay-study-sessions.md", BASE),
    "D02": L.DocRef(_E26 + "D02.md", BASE),
    "D02H": L.DocRef(_E26 + "D02-handoff.md", BASE),
    "D02B": L.DocRef(_E26 + "D02.md", D02B_HEAD),
    "D03": L.DocRef(_E26 + "D03.md", D03_HEAD),
    "D03H": L.DocRef(_E26 + "D03-handoff.md", D03_HEAD),
    "D04": L.DocRef(_E26 + "D04.md", D04_HEAD),
    "D04H": L.DocRef(_E26 + "D04-handoff.md", D04_HEAD),
    "D05": L.DocRef(_E26 + "D05.md", D05_HEAD),
    "D05H": L.DocRef(_E26 + "D05-handoff.md", D05_HEAD),
    "E05D02R": L.DocRef("docs/design/E05/E05-D02-rest.md", BASE),
    "E11D02": L.DocRef("docs/design/E11/E11-D02.md", BASE),
    "E11D06": L.DocRef("docs/design/E11/E11-D06.md", BASE),
    "E47D05": L.DocRef("docs/design/E47/E47-D05.md", BASE),
    "E47D04": L.DocRef("docs/design/E47/E47-D04.md", BASE),
    "E47D07": L.DocRef("docs/design/E47/E47-D07.md", BASE),
    "E47D08": L.DocRef("docs/design/E47/E47-D08.md", BASE),
    "E47D09": L.DocRef("docs/design/E47/E47-D09.md", BASE),
    "DS": L.DocRef(".claude/rules/32-design-specs.md", BASE),
    "KM": L.DocRef("apps/web/src/keymap/keymap.json", BASE),
    "PRIM": L.DocRef(PRIM_REL, BASE),
    "SEMD": L.DocRef("packages/ui/tokens/semantic-dark.tokens.json", BASE),
    "SEML": L.DocRef("packages/ui/tokens/semantic-light.tokens.json", BASE),
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
        ("05", 185, "default 1 update / 2s per field"),
        ("05", 248, "`prefers-reduced-motion: reduce`"),
        ("05", 251, "accessible pause control"),
        ("05", 164, "≥7:1 body text"),
        ("06", 26, "replay at 20x"),
        ("06", 39, "Sustain up to 100x"),
        ("14", 2251, "`R` jump to real time"),
        ("14", 2254, "labelled live region updated at most 1 Hz"),
        ("16", 212, "Dialog/drawer open"),
        ("16", 218, "Respects `prefers-reduced-motion`"),
        ("D01", 266, "the same 25× as the paper boundary"),
        ("D02", 61, 'role="timer"'),
        ("D02", 116, "4 px inset, against 2 px focus rings"),
        ("D02", 118, "`color.replay.border`"),
        ("D02", 125, "Entering and leaving the page flips"),
        ("D02", 269, "Playhead = thumb"),
        ("D02", 292, "elapsed at 1 Hz"),
        ("D02", 411, "**The scrub thumb**"),
        ("D02", 453, "changes only on a user action or on pause"),
        ("D02", 700, "OQ-12"),
        ("D03", 306, "Initial focus"),
        ("D04", 595, "PROPOSED `color.replay.border`"),
        ("D05", 246, "24 × 24 compact"),
        ("D05", 365, "`aria-valuenow` the cursor in epoch seconds"),
        ("D05", 367, "focus goes to `Play`"),
        ("E11D06", 96, "no transition, ever"),
        ("KM", 921, '"replay.play_pause"'),
        ("KM", 1010, '"Jump to real time"'),
        ("SEMD", 705, '"color.chart.replay.border"'),
        ("DS", 15, "G-T2 miss is a Major"),
        ("D02B", 209, "3.98:1"),
        ("05", 128, "K-3 Arrows adjust by one unit"),
        ("05", 130, "K-5 `Esc`"),
        ("16", 659, "re-sync needed"),
        ("16", 743, 'moved from "Backlog" to "Ready"'),
        ("E11D06", 203, "**it never eases**"),
        ("E47D04", 139, "| workspace "),
        ("E47D04", 301, "| form dialog (settings, builders, editors)"),
        ("E47D04", 304, "| drawer (`aria-modal`)"),
        ("E47D07", 247, "at most once per 5 s per region"),
        ("E47D08", 233, "never flashes faster"),
        ("E47D08", 260, "Pause controls are never gated"),
        ("E47D08", 327, '"Paused at 13:38:04"'),
        ("E47D09", 179, "| DE-19 |"),
    )
)

THEMES = tuple(L.THEME_PARTS)
DEFICIENCIES = ("deuteranopia", "protanopia", "tritanopia")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
AREAS = ("recorder-replay", "design-system")
DISPOSITIONS = ("decision", "F row", "A row", "C row", "G row", "H row", "verdict")
FIX_DISPOSITIONS = ("fixed in design", "accepted", "deferred to E26-Q05")
PARENT_PRS = re.compile(r"#5513|#510\b|#511\b|#512\b")
STORIES = re.compile(r"#623|#807|#811|#812")
REDUCE = ("instant", "identical")
AT_SPEED = ("reduce form", "unchanged (a cut)", "unchanged (data)")
T_MOTIONS = (
    "Playhead advance",
    "Scrub drag",
    "Scrub settle",
    "Seeking",
    "Play / pause",
    "Bookmark marker",
    "Gap-encountered",
    "REPLAY chrome entry / exit",
)
DECORATIVE_TOKENS = ("`motion.duration.fast`", "`motion.duration.normal`")
THRESHOLD = "20"
LR_OBJECTS = ("clock", "opt-in", "status", "alert", "notice", "press", "dialog", "drawer", "silent")
LR_POLITE = ("off", "polite", "assertive")
LR_RATES = (
    "at most once a second",
    "1 per 2 s by default, at most once a second",
    "once per event",
    "once per event, at most 1 per 5 s per region (held)",
    "once on entry",
    "at 60 s and 10 s",
    "once per press",
    "never",
)
LR_SILENT_NEED = ("readout", "value text", "motion", "tick", "elapsed")
VERDICTS = (
    "compliant if #510 merges as is",
    "compliant if #511 merges as is",
    "compliant if #512 merges as is",
    "compliant",
    "at risk",
    "non-compliant",
    "out of scope —",
    "not yet decidable —",
)
SCENARIOS = 4
AC3_ACTIONS = (
    "play / pause",
    "step bar",
    "step tick",
    "jump",
    "seek",
    "bookmark",
    "skip gap",
    "jump to real time",
)
THUMB_KEYS = (
    "`←` / `→`",
    "`Shift+←` / `Shift+→`",
    "`↑` / `↓`",
    "`PageUp` / `PageDown`",
    "`Home` / `End`",
    "`Enter`",
    "`Esc`",
    "`Tab` / `Shift+Tab`",
)
# Section 10.1: the union of the parents' pairs (D02 section 12.2, D03 section 13, D04 section
# 11.2, D05 section 7.2), the replay frame on the shipped token; every pair must meet its floor.
_T, _N = 4.5, 3.0
UNION_PAIRS: tuple[tuple[str, str, float], ...] = (
    ("color.text.primary", "color.surface.raised", _T),
    ("color.text.secondary", "color.surface.raised", _T),
    ("color.text.tertiary", "color.surface.raised", _T),
    ("color.text.primary", "color.surface.selected", _T),
    ("color.text.on-action", "color.action.primary.default", _T),
    ("color.text.primary", "color.status.warning.subtle", _T),
    ("color.text.primary", "color.status.info.subtle", _T),
    ("color.text.primary", "color.status.danger.subtle", _T),
    ("color.text.primary", "color.surface.overlay", _T),
    ("color.text.secondary", "color.surface.overlay", _T),
    ("color.text.tertiary", "color.surface.overlay", _T),
    ("color.text.primary", "color.surface.canvas", _T),
    ("color.text.primary", "color.surface.hover", _T),
    ("color.chart.replay.border", "color.surface.canvas", _N),
    ("color.chart.replay.border", "color.surface.raised", _N),
    ("color.env.demo", "color.surface.raised", _N),
    ("color.text.tertiary", "color.surface.sunken", _N),
    ("color.neutral.default", "color.surface.raised", _N),
    ("color.neutral.default", "color.surface.sunken", _N),
    ("color.neutral.default", "color.surface.overlay", _N),
    ("color.focus.ring", "color.surface.raised", _N),
    ("color.focus.ring", "color.surface.canvas", _N),
    ("color.focus.ring", "color.surface.overlay", _N),
    ("color.focus.ring", "color.status.warning.subtle", _N),
    ("color.status.warning.strong", "color.status.warning.subtle", _N),
    ("color.status.info.strong", "color.status.info.subtle", _N),
    ("color.status.danger.strong", "color.surface.overlay", _N),
    ("color.buy.default", "color.surface.overlay", _N),
    ("color.sell.default", "color.surface.overlay", _N),
    ("color.action.primary.default", "color.surface.overlay", _N),
    ("color.text.on-action", "color.text.tertiary", _N),
)
# Section 10.2: the parents' rejected pairs; each must stay below its bar in at least one theme.
REJECTED_PAIRS: tuple[tuple[str, str, float], ...] = (
    ("color.text.tertiary", "color.surface.selected", _T),
    ("color.border.strong", "color.surface.raised", _N),
    ("color.border.strong", "color.surface.overlay", _N),
    ("color.text.primary", "color.neutral.default", _N),
    ("color.text.disabled", "color.surface.raised", _T),
    ("color.text.disabled", "color.surface.overlay", _T),
    ("color.sell.default", "color.surface.overlay", _T),
    ("color.buy.default", "color.surface.overlay", _T),
    ("color.sell.default", "color.surface.raised", _T),
    ("color.status.warning.default", "color.surface.overlay", _T),
)
# Section 10.3: the pairs this review adds (F-01, F-02); a floor miss is a finding, not a FAIL.
REVIEW_PAIRS: tuple[tuple[str, str, float], ...] = (
    ("color.focus.ring", "color.neutral.default", _N),
    ("color.focus.ring", "color.surface.sunken", _N),
    ("color.surface.raised", "color.neutral.default", _N),
    ("color.focus.ring", "color.chart.replay.border", _N),
)
# Section 10.4: the replay hue against its neighbours, per theme.
CVD_OTHERS = ("color.focus.ring", "color.env.demo", "color.env.live")
REPLAY = "color.chart.replay.border"
HOLD = "**Hold:** E26-D07 (#514) does not take this pack while a Blocking row stands"
F_HEAD_RE = re.compile(
    r"^## 13\. Findings — F (\d+) \(Blocking (\d+) · Major (\d+) · Minor (\d+) · Info (\d+)\)"
    r" <!-- audit:f=(\d+)/(\d+)/(\d+)/(\d+)/(\d+) -->$",
    re.MULTILINE | re.DOTALL,
)
F_MARK_RE = re.compile(r" audit:f=\d+/\d+/\d+/\d+/\d+ ", re.DOTALL)
LOW_HC_RE = re.compile(r"^\*\*Lowest high-contrast text pair:\*\* (.+)$", re.MULTILINE)
PREFIXES = "IB|AD|MP|FO|KS|T2|LR|CR|SR|F|V|C|G|Q|A|H"
ID_RE = re.compile(rf"(?:{PREFIXES})-\d\d")
# An own id; another spec's ids carry its prefix ("D02 D-19") and are skipped.
REF_RE = re.compile(rf"(?<![\w-])(?<!D0\d )(?:{PREFIXES})-\d\d(?![\w.]*\d)(?!\.\d)")
POINTER_WORDS = re.compile(r"\b(?:click|hover|drag|mouse|pointer)\b", re.IGNORECASE)
MOTION_TOKEN_RE = re.compile(r"`(motion\.(?:duration|easing)\.[a-z]+)`")


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


@functools.cache
def theme(name: str) -> dict[str, str]:
    return L.resolve_theme(repo(), BASE, name)


@functools.cache
def prim() -> dict[str, object]:
    raw = json.loads(repo().show(BASE, PRIM_REL) or "{}")
    return {k: v.get("$value") for k, v in raw.items() if isinstance(v, dict)}


def rgb(hexv: str) -> tuple[int, int, int]:
    h = hexv.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(name: str, fg: str, bg: str) -> float:
    t = theme(name)
    return float(measurers()[0].contrast_ratio(rgb(t[fg]), rgb(t[bg])))


def pair_row(fg: str, bg: str, floor: float) -> list[str]:
    return [f"`{fg}` on `{bg}`", f"{floor:g}", *(f"{ratio(n, fg, bg):.2f}" for n in THEMES)]


def rejected_row(fg: str, bg: str, floor: float) -> list[str]:
    return [*pair_row(fg, bg, floor), "REJECTED"]


def review_row(fg: str, bg: str, floor: float) -> list[str]:
    row = pair_row(fg, bg, floor)
    return [*row, "yes" if min(float(v) for v in row[2:]) >= floor else "no"]


def cvd_row(other: str, name: str) -> list[str]:
    cvd, t = measurers()[1], theme(name)
    return [
        f"`{REPLAY}` vs `{other}`",
        name,
        *(
            f"{float(cvd.delta_e76(cvd.simulate(t[REPLAY], d), cvd.simulate(t[other], d))):.1f}"
            for d in DEFICIENCIES
        ),
    ]


def cvd_rows() -> list[list[str]]:
    return [cvd_row(o, n) for o in CVD_OTHERS for n in THEMES]


def lowest_hc() -> str:
    text = [(fg, bg) for fg, bg, floor in UNION_PAIRS if floor == _T]
    fg, bg = min(text, key=lambda p: ratio("high-contrast", *p))
    return f"`{fg}` on `{bg}`, {ratio('high-contrast', fg, bg):.2f}."


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


def numbered(got: list[list[str]], prefix: str, n: int) -> list[str]:
    want = [f"{prefix}-{i:02d}" for i in range(1, n + 1)]
    return [] if [r[0] for r in got] == want else [f"not {want[0]} … {want[-1]}"]


# ---------- this review's gates -------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    cites = L.extract_cites(spec(t), CITE_RE)
    bad = L.check_cites(cites, docs(), nonblank=False, min_count=200)
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
    v = sec(t, "### 17.1 Version line")
    need = (BASE, D02B_HEAD, D03_HEAD, D04_HEAD, D05_HEAD, RULING, "re-pinned to its merge commit")
    miss = [n for n in (*need, HELPER_SHA) if n not in v]
    if f"Base `origin/main` `{BASE}`" not in spec(t):
        miss.append("Inputs pinned base")
    return [f"missing: {', '.join(miss)}"] if miss else []


def g_ac(t: L.Tree) -> list[str]:
    tickets = json.loads(repo().show(BASE, BACKLOG_REL) or "[]")
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E26-D06")
    names = [n.strip() for n in re.findall(r"Scenario: (.+)", body)]
    trace = sec(t, "## Acceptance-criteria and DoD trace")
    miss = [n for n in names if f'AC "{n}"' not in trace]
    return (
        [f"scenario names not verbatim: {miss or names}"] if len(names) != SCENARIOS or miss else []
    )


def g_inbox(t: L.Tree) -> list[str]:
    got = rows(t, "## 2. The inbox")
    defined = defined_ids(spec(t))
    bad = numbered(got, "IB", 22)
    for r in got:
        if len(r) < 4 or r[2] not in DISPOSITIONS:
            bad.append(f"{r[0]} disposition")
        elif not ids_in(r[3]) or any(i not in defined for i in ids_in(r[3])):
            bad.append(f"{r[0]} target")
    return bad


def g_decisions(t: L.Tree) -> list[str]:
    got = rows(t, "## 3. Adopted decisions")
    bad = numbered(got, "AD", 10)
    for r in got:
        if len(r) < 4 or not r[2].strip("— ") or not re.search(r"#\d+", r[3]):
            bad.append(f"{r[0]} test or owner")
    return bad


def g_motion(t: L.Tree) -> list[str]:
    got = rows(t, "### 4.1")
    bad = numbered(got, "MP", 13)
    names = " ".join(r[1] for r in got if len(r) > 1)
    bad += [f"no row for {m!r}" for m in T_MOTIONS if m not in names]
    for r in got:
        if len(r) < 9 or r[5] not in REDUCE or r[7] not in AT_SPEED:
            bad.append(f"{r[0] if r else '?'} reduce or speed cell")
        elif not r[6].strip("— ") or not L.extract_cites(r[8], CITE_RE):
            bad.append(f"{r[0]} carrier or source")
    return bad


def g_tokens(t: L.Tree) -> list[str]:
    p = prim()
    bad = [f"{n} not shipped" for n in set(MOTION_TOKEN_RE.findall(spec(t))) if n not in p]
    for r in rows(t, "### 4.4"):
        m = MOTION_TOKEN_RE.fullmatch(r[1]) if len(r) > 3 else None
        if m is None:
            if len(r) < 4 or not r[3].startswith("PROPOSED"):
                bad.append(f"{r[1] if len(r) > 1 else '?'} neither shipped nor PROPOSED")
            continue
        val = p.get(m.group(1))
        want = ", ".join(f"{x:g}" for x in val) if isinstance(val, list) else str(val)
        want = f"[{want}]" if isinstance(val, list) else want
        if r[2] != want or r[3] != "shipped":
            bad.append(f"{m.group(1)} written {r[2]!r}, shipped {want!r}")
    names = L.token_names(repo(), BASE)
    bad += [f"{n} not a shipped token" for n in L.check_token_refs(spec(t), names)]
    return bad


def g_speed(t: L.Tree) -> list[str]:
    bad = []
    rule = sec(t, "### 4.2")
    if f"requested speed of {THRESHOLD}× or more" not in rule or "`06`:26" not in rule:
        bad.append("the rule sentence or its budget cite")
    const = [r for r in rows(t, "### 4.4") if len(r) > 3 and r[3].startswith("PROPOSED")]
    if [r[2] for r in const] != [THRESHOLD]:
        bad.append(f"the constant is {[r[2] for r in const]}, not {THRESHOLD}")
    for r in rows(t, "### 4.1"):
        if len(r) < 8:
            continue
        deco = any(tok in r[4] for tok in DECORATIVE_TOKENS)
        if deco != (r[7] == "reduce form"):
            bad.append(f"{r[0]} decorative {deco} but {r[7]!r} at the threshold")
        if r[0] == "MP-05" and r[4] != "`motion.duration.instant`":
            bad.append("the settle is eased (BQ-4 makes it a cut)")
    return bad


def g_keys(t: L.Tree) -> list[str]:
    km = rows(t, "### 6.1")
    thumb = {r[0]: r[2] for r in km if len(r) > 4 and r[1] == "the thumb"}
    bad = [f"no thumb row {k}" for k in THUMB_KEYS if k not in thumb]
    want = (
        ("`Tab` / `Shift+Tab`", ("leaves",)),
        ("`←` / `→`", ("pending", "DE-19")),
        ("`Enter`", ("seek",)),
        ("`Esc`", ("restores", "sends nothing", "no trap")),
    )
    for key, words in want:
        bad += [f"thumb {key} lacks {w!r}" for w in words if w not in thumb.get(key, "")]
    esc = [r for r in km if len(r) > 2 and r[0] == "`Esc`" and r[1].startswith("the transport")]
    if len(esc) != 1 or "cancel" not in esc[0][2]:
        bad.append("the transport's `Esc` row")
    walks = rows(t, "### 6.2")
    bad += numbered(walks, "KS", 10)
    for r in walks:
        if len(r) < 5 or "`" not in r[2] or POINTER_WORDS.search(r[2]) or "`" not in r[4]:
            bad.append(f"{r[0] if r else '?'} not keyboard-only with a way out")
    named = " ".join(r[1] for r in walks if len(r) > 1)
    bad += [f"AC 3 action {a!r} has no walk" for a in AC3_ACTIONS if a not in named]
    return bad


def g_t2(t: L.Tree) -> list[str]:
    r4 = next((ln for ln in spec(t).split("\n") if ln.startswith("- **R-4 ")), "")
    bad = L.t2_markers(r4) + L.no_disabled_tokens(spec(t))
    got = rows(t, "## 7. Gated controls")
    if not got or "rbac.view_as" not in got[0][4] or "viewing as" not in got[0][1]:
        bad.append("the view-as row is not first")
    for r in got:
        if len(r) < 6 or r[2] not in ("T2", "not gated"):
            bad.append(f"{r[0] if r else '?'} class")
        elif re.search(r"cancel|close", r[1]) and "never the arm" not in " ".join(r):
            bad.append(f"{r[0]} cancel gated on the arm")
    return bad


def g_live(t: L.Tree) -> list[str]:
    bad = []
    got = rows(t, "## 8. The live-region policy")
    for r in got:
        if len(r) < 6 or r[1] not in LR_OBJECTS or r[3] not in LR_POLITE or r[4] not in LR_RATES:
            bad.append(f"{r[0] if r else '?'} object, politeness or rate")
        elif r[1] == "silent" and (r[3], r[4]) != ("off", "never"):
            bad.append(f"{r[0]} silent row spoken")
        elif r[1] not in ("silent", "clock") and r[3] == "off":
            bad.append(f"{r[0]} an announcement that is off")
        elif not L.extract_cites(r[5], CITE_RE):
            bad.append(f"{r[0]} source")
    clock = [r for r in got if len(r) > 5 and r[1] == "clock"]
    if len(clock) != 1 or (clock[0][3], clock[0][4]) != ("off", "at most once a second"):
        bad.append("the clock row")
    opt = [r for r in got if len(r) > 5 and r[1] == "opt-in"]
    if (
        len(opt) != 1
        or opt[0][3] != "polite"
        or "`05`:185" not in opt[0][5]
        or "`14`:2254" not in opt[0][5]
    ):
        bad.append("the opt-in row")
    silent = " ".join(r[2] for r in got if len(r) > 2 and r[1] == "silent")
    bad += [f"no silent row for {w}" for w in LR_SILENT_NEED if w not in silent]
    return bad


def g_colour(t: L.Tree) -> list[str]:
    bad = []
    for r in rows(t, "### 9.1"):
        if len(r) < 6 or not r[3].strip("— ") or not r[4].strip("— "):
            bad.append(f"{r[0] if r else '?'} carrier")
        elif not r[5].startswith(("compliant", "at risk")):
            bad.append(f"{r[0]} verdict")
        elif r[5].startswith("at risk") and not re.search(r"F-\d\d", r[5]):
            bad.append(f"{r[0]} at risk names no F row")
    return bad


def g_env(t: L.Tree) -> list[str]:
    bad = []
    mp = {r[0]: r for r in rows(t, "### 4.1") if r}
    m1 = mp.get("MP-01", [])
    if len(m1) < 7 or m1[4] != "`motion.duration.instant`" or m1[5] != "instant":
        bad.append("the chrome is not a cut")
    elif "`DEMO` / `NO ACCOUNT`" not in m1[6]:
        bad.append("the chrome's carriers lack the badges")
    if not any(len(r) > 1 and r[1] == "DEMO / NO ACCOUNT" for r in rows(t, "### 9.1")):
        bad.append("no DEMO / NO ACCOUNT carrier row")
    fo = {r[0]: r for r in rows(t, "## 5. Region") if r}
    if "names the workspace environment" not in " ".join(fo.get("FO-07", [])):
        bad.append("the leave confirm names no environment")
    r6 = next((ln for ln in spec(t).split("\n") if ln.startswith("- **R-6 C-2.11.")), "")
    bad += [
        f"R-6 lacks {w}"
        for w in ("`DEMO`", "`NO ACCOUNT`", "is moved, shed or transitioned")
        if w not in r6
    ]
    return bad


def _table_check(t: L.Tree, heading: str, want: list[list[str]], width: int) -> list[str]:
    written = {r[0]: r for r in rows(t, heading)}
    bad = [
        f"{heading[4:]} {w[0]}: measured {w[1:]}"
        for w in want
        if written.get(w[0], [])[:width] != w[:width]
    ]
    if len(written) != len(want):
        bad.append(f"{heading[4:]}: {len(written)} rows for {len(want)}")
    return bad


def g_contrast(t: L.Tree) -> list[str]:
    union = [pair_row(*q) for q in UNION_PAIRS]
    bad = _table_check(t, "### 10.1", union, 5)
    bad += [f"{r[0]} below {r[1]}" for r in union if min(float(v) for v in r[2:]) < float(r[1])]
    m = LOW_HC_RE.search(sec(t, "### 10.1"))
    if m is None or m.group(1) != lowest_hc():
        bad.append(f"lowest high-contrast line: measured {lowest_hc()}")
    rej = [rejected_row(*q) for q in REJECTED_PAIRS]
    bad += _table_check(t, "### 10.2", rej, 6)
    bad += [
        f"{r[0]} passes everywhere" for r in rej if min(float(v) for v in r[2:5]) >= float(r[1])
    ]
    bad += _table_check(t, "### 10.3", [review_row(*q) for q in REVIEW_PAIRS], 6)
    return bad


def g_cvd(t: L.Tree) -> list[str]:
    written = [r[:5] for r in rows(t, "### 10.4")]
    want = cvd_rows()
    if written == want:
        return []
    diff = [w for w in want if w not in written]
    return [f"10.4 measured {diff[:2] or 'a different row count'}"]


def g_verdict(t: L.Tree) -> list[str]:
    sev = {r[0]: r[1] for r in rows(t, "## 13. Findings") if len(r) > 1}
    bad = []
    for r in rows(t, "## 12. Clause verdicts"):
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
    return bad


def g_findings(t: L.Tree) -> list[str]:
    got = rows(t, "## 13. Findings")
    counts = [len(got)] + [sum(1 for r in got if len(r) > 1 and r[1] == s) for s in SEVERITIES]
    m = F_HEAD_RE.search(spec(t))
    bad = []
    if m is None or [int(x) for x in m.groups()] != counts + counts:
        bad.append(f"heading or marker vs table {counts}")
    if HOLD not in sec(t, "## 13. Findings"):
        bad.append("hold sentence")
    for r in got:
        if len(r) < 8 or r[1] not in SEVERITIES:
            bad.append(f"{r[0] if r else '?'} severity")
            continue
        if not re.search(r"\b\d\.\d\.\d+\b|`05`", r[4]):
            bad.append(f"{r[0]} criterion")
        if not any(f"({a})" in r[5] for a in AREAS):
            bad.append(f"{r[0]} owner")
        if r[6] not in FIX_DISPOSITIONS:
            bad.append(f"{r[0]} disposition")
        info = r[1] == "Info"
        if info and r[7] != "E26-D07 #514":
            bad.append(f"{r[0]} Info targets")
        elif not info and not (
            "E26-D07 #514" in r[7] and PARENT_PRS.search(r[7]) and STORIES.search(r[7])
        ):
            bad.append(f"{r[0]} targets")
    return bad


def g_ids(t: L.Tree) -> list[str]:
    defined = defined_ids(spec(t))
    refs = set(REF_RE.findall(spec(t)))
    return [f"dangling: {', '.join(sorted(refs - defined))}"] if refs - defined else []


def g_handoff(t: L.Tree) -> list[str]:
    got = rows(t, "### 14.5")
    named = [r for r in got if len(r) > 3 and r[1].startswith("`scr")]
    bad = [
        f"{r[0]} assertion name"
        for r in named
        if not re.search(r"`scr09[789]\.[a-z0-9.-]+` \((?:axe|Playwright)", r[1])
        or "E26-Q05 #805" not in r[3]
    ]
    covered = {i for r in got if len(r) > 2 for i in re.findall(r"AD-\d\d", r[2])}
    ads = {r[0] for r in rows(t, "## 3. Adopted decisions")}
    bad += [f"{a} reaches no assertion" for a in sorted(ads - covered)]
    fcov = {i for r in got if len(r) > 2 for i in re.findall(r"F-\d\d", r[2])}
    deferred = [
        r[0] for r in rows(t, "## 13. Findings") if len(r) > 6 and r[6] == FIX_DISPOSITIONS[2]
    ]
    return bad + [f"{f} deferred with no H row" for f in deferred if f not in fcov]


def g_walk(t: L.Tree) -> list[str]:
    items = re.findall(r"^(\d+)\. ", sec(t, "### 15.3"), re.MULTILINE)
    n = len(items)
    ok = 0 < n <= 10 and items == [str(i) for i in range(1, n + 1)]
    return [] if ok else [f"{n} walkthrough items"]


def g_boards(t: L.Tree) -> list[str]:
    boards = rows(t, "## 0. Status")
    bad = L.board_cap(boards, "E26-D06", spec(t))
    return bad + L.r7_findings(t.named("spec"), ("page `E26-D06`",), spec(t))


def g_ruling(t: L.Tree) -> list[str]:
    return L.check_ruling(
        spec(t),
        heading_line=f"## The questions BQ-0 … BQ-13 — RULED (comment {RULING})",
        list_ref=f"comment {BQ_LIST} on #513",
        count=14,
        verdict=lambda n: f"RULED, {BQ_VERDICTS[n]} (comment {RULING}). Applied:",
        need=("Applied:",),
        forbid=("PENDING", "Default built:"),
    )


# ruled-pins:begin (written by --repin-ruled only)
RULED_PINS: tuple[str, ...] = (
    "BQ-0 7bb5d5ceb5ed6c04",
    "BQ-1 191dd12073a4aa71",
    "BQ-2 55d15bd60609988d",
    "BQ-3 583aa9e4df37bdb7",
    "BQ-4 485b9c72fa5c7125",
    "BQ-5 a3451e531467647c",
    "BQ-6 014817a72d76dda6",
    "BQ-7 4257452494242623",
    "BQ-8 8817f362d19fbf82",
    "BQ-9 bd2cfb9532dad927",
    "BQ-10 4f3af5bb4d1a9417",
    "BQ-11 b2ac60b543a68f11",
    "BQ-12 ebc9328051bee661",
    "BQ-13 85b712db0ef4a877",
)
# ruled-pins:end


def g_ruled(t: L.Tree) -> list[str]:
    return L.check_hash_pins(spec(t), "\n".join(RULED_PINS))


def g_outrank(t: L.Tree) -> list[str]:
    """The ruling's added rows: E47-D04 / E47-D09 outrank, Pause never gated, the merge duties."""
    want: tuple[tuple[list[list[str]], str, tuple[str, ...]], ...] = (
        (rows(t, "### 14.1"), "C-06", ("E47D09:179", "DE-19")),
        (rows(t, "### 14.4"), "A-06", ("E47D04:139", "Replay transport")),
        (rows(t, "## 13. Findings"), "F-10", ("E47D04:301",)),
        (rows(t, "## 7. Gated controls"), "T2-13", ("not gated", "E47D08:260")),
    )
    bad = []
    for got, rid, words in want:
        r = " | ".join(next((x for x in got if x and x[0] == rid), []))
        bad += [f"{rid} lacks {w!r}" for w in words if w not in r]
    duties = sec(t, "### 16.1")
    need = ("`16`:743", "`16`:659", "Ready", "re-sync needed")
    bad += [f"16.1 lacks {w}" for w in need if w not in duties]
    d7 = next((ln for ln in spec(t).split("\n") if ln.startswith("- **D-7**")), "")
    if "C-4.10" not in d7 or "conventional commit" not in d7:
        bad.append("D-7, the PR-title deviation")
    return bad


def g_noclose(t: L.Tree) -> list[str]:
    return L.closing_keywords(t.named("spec", "tool"))


def g_public(t: L.Tree) -> list[str]:
    texts = t.named("spec", "tool")
    return L.scan_public(texts) + L.comment_findings(t.named("spec"), F_MARK_RE)


def g_hygiene(t: L.Tree) -> list[str]:
    return L.whitespace_hygiene(t.named("spec", "tool"))


def g_helper(t: L.Tree) -> list[str]:
    got = hashlib.sha256(t.text("lib").encode("utf-8")).hexdigest()
    return [] if got.startswith(HELPER_SHA) else [f"{LIB_REL} is {got[:16]}, not {HELPER_SHA}"]


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(spec(t), "### 17.3", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper(), f) for f in (
    g_cite, g_keycite, g_version, g_ac, g_inbox, g_decisions, g_motion, g_tokens, g_speed,
    g_keys, g_t2, g_live, g_colour, g_env, g_contrast, g_cvd, g_verdict, g_findings, g_ids,
    g_handoff, g_walk, g_boards, g_ruling, g_ruled, g_outrank, g_noclose, g_public, g_hygiene,
    g_helper, g_untouched, g_mutlist,
))
# fmt: on


def _drift(text: str) -> L.Mutation:
    def fn(tree: L.Tree) -> L.Tree:
        return dataclasses.replace(tree, files={**tree.files, "drift": text})

    return L.Mutation("M-02", "G-KEYCITE", "a pinned source line reworded", fn=fn)


_M = L.Mutation
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-01", "G-CITE", "a cite past the end of D02", "spec", "(D02:700)", "(D02:99999)"),
    _drift("14|2254|- **A11y:** the replay clock speaks every second."),
    _M("M-03", "G-VERSION", "the version line drops the re-pin", "spec",
       "each re-pinned to its merge commit when it merges", "each kept when it merges"),
    _M("M-04", "G-AC", "a scenario name reworded", "spec",
       'AC "Every animation has a reduced-motion answer"', 'AC "Every animation is reduced"'),
    _M("M-05", "G-INBOX", "an inbox row deferred", "spec",
       r"(\| IB-04 \|[^\n]*?\| )F row", r"\1deferred", regex=True),
    _M("M-06", "G-DECISIONS", "a decision with no owner ticket", "spec",
       r"(\| AD-10 \|[^\n]*\| )E26-S02 #807; E26-T05 #628( *\|)", r"\1the build\2", regex=True),
    _M("M-07", "G-MOTION", "a reduce form is a cross-fade", "spec",
       r"(\| MP-08 \|(?:[^|\n]*\|){4} )instant", r"\1cross-fade", regex=True),
    _M("M-08", "G-MOTION", "a ticket motion has no row", "spec",
       "| MP-08 | Bookmark marker appearance", "| MP-08 | Marker appearance"),
    _M("M-09", "G-TOKENS", "a token value drifts", "spec",
       r"(`motion\.duration\.fast` *\| )100ms", r"\g<1>120ms", regex=True),
    _M("M-10", "G-SPEED", "a decorative row keeps its motion", "spec",
       r"(\| MP-08 \|[^\n]*?\| )reduce form", r"\1unchanged (data)", regex=True),
    _M("M-11", "G-SPEED", "the constant differs from the rule", "spec",
       r"(\| )20( +\| PROPOSED)", r"\g<1>25\2", regex=True),
    _M("M-12", "G-KEYS", "Tab stays on the thumb", "spec",
       r"(\| `Tab` / `Shift\+Tab` +\| the thumb +\| )leaves the thumb", r"\1stays on the thumb",
       regex=True),
    _M("M-13", "G-KEYS", "a walk needs a pointer", "spec",
       r"(\| KS-04 \|[^|]*\| )`Ctrl\+→` / `Ctrl\+←`", r"\1drag the thumb", regex=True),
    _M("M-14", "G-T2", "R-4 loses the describedby link", "spec",
       "linked by `aria-describedby` (G-T2.1c)", "linked (G-T2.1c)"),
    _M("M-15", "G-T2", "a cancel gated on the arm", "spec",
       "never the arm (R-5)", "the arm (R-5)"),
    _M("M-16", "G-LIVE", "the clock speaks", "spec",
       r"(\| LR-01 \|[^\n]*?\| )off( +\| )", r"\1polite\2", regex=True),
    _M("M-17", "G-LIVE", "a rate not from the vocabulary", "spec",
       r"(\| LR-02 \|[^\n]*?\| )1 per 2 s by default, at most once a second", r"\1every frame",
       regex=True),
    _M("M-18", "G-COLOUR", "coverage carried by nothing", "spec",
       r"(\| CR-02 \|[^|]*\|[^|]*\| )[^|]*?( +\|)", r"\1—\2", regex=True),
    _M("M-19", "G-ENV", "the leave confirm names no environment", "spec",
       "it names the workspace environment returned to", "it names nothing"),
    _M("M-20", "G-CONTRAST", "a written pair ratio drifts", "spec",
       r"(`color\.text\.primary` on `color\.surface\.raised` *\| 4\.5 *\| )\d+\.\d\d",
       r"\g<1>9.99", regex=True),
    _M("M-21", "G-CVD", "a written distance drifts", "spec",
       r"(`color\.chart\.replay\.border` vs `color\.focus\.ring` *\| dark *\| )\d+\.\d",
       r"\g<1>9.9", regex=True),
    _M("M-22", "G-VERDICT", "an at-risk clause called compliant", "spec",
       r"(\| V-08 \|[^\n]*?\| )at risk — F-02", r"\1compliant — F-02", regex=True),
    _M("M-23", "G-FINDINGS", "the heading count drifts", "spec",
       "Major 0 · Minor 8 · Info 3)", "Major 0 · Minor 7 · Info 3)"),
    _M("M-24", "G-FINDINGS", "a finding loses its story", "spec",
       r"(\| F-02 \|[^\n]*?E26-D07 #514) · E26-S02 #807", r"\1", regex=True),
    _M("M-25", "G-FINDINGS", "the hold sentence dropped", "spec",
       "**Hold:** E26-D07 (#514)", "Hold: E26-D07 (#514)"),
    _M("M-26", "G-IDS", "a dangling F id", "spec",
       "text done; routed (F-01, F-02)", "text done; routed (F-31, F-02)"),
    _M("M-27", "G-HANDOFF", "a decision with no assertion", "spec",
       r"(\| H-02 \|[^|]*\| )AD-03", r"\1V-03", regex=True),
    _M("M-28", "G-WALK", "an eleventh walkthrough item", "spec",
       "10. Comment `approved`", "10. One more pass.\n11. Comment `approved`"),
    _M("M-29", "G-BOARDS", "a board marked drawn", "spec",
       r"(\| 03 +\|[^\n]*\| )PENDING", r"\1DRAWN", regex=True),
    _M("M-30", "G-RULING", "the heading names another comment", "spec",
       "BQ-13 — RULED (comment 6608045629)", "BQ-13 — RULED (comment 6608045620)"),
    _M("M-31", "G-RULED", "a BQ default edited without a re-pin", "spec",
       "Applied: one MP table", "Applied: one motion table"),
    _M("M-32", "G-NOCLOSE", "a closing keyword", "spec",
       "nothing is filed.", "nothing is filed. " + "Clo" + "ses #513."),
    _M("M-33", "G-PUBLIC", "a URL", "spec",
       "**Nothing is drawn in this PR**",
       "**Nothing is drawn in this PR** (" + "http" + "s://example.org)"),
    _M("M-34", "G-PUBLIC", "a stray HTML comment", "spec",
       "## 18. Summary for #513", "## 18. Summary for #513 " + "<!" + "-- note -->"),
    _M("M-35", "G-HYGIENE", "trailing whitespace", "spec",
       "## 18. Summary for #513\n", "## 18. Summary for #513  \n"),
    _M("M-36", "G-HELPER", "the helper edited", "lib",
       "Shared gates for the per-spec", "Shared checks for the per-spec"),
    _M("M-37", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/16-design-system-brief.md"),
    _M("M-38", "G-MUTLIST", "the list drifts", "spec",
       r"\| M-01 +\| G-CITE +\|", "| M-01 | G-AC |", regex=True),
    _M("M-39", "G-HANDOFF", "a deferred finding with no assertion", "spec",
       r"(\| H-16 \|[^|]*\| )F-07", r"\1AD-01", regex=True),
    _M("M-40", "G-SPEED", "the settle eased again", "spec",
       r"(\| MP-05 \|(?:[^|\n]*\|){3} )`motion\.duration\.instant`", r"\1`motion.duration.fast`",
       regex=True),
    _M("M-41", "G-KEYS", "the thumb's arrows apply at once", "spec",
       "adjust a pending seek one bar (DE-19)", "step one bar at once"),
    _M("M-42", "G-OUTRANK", "replay Pause gated", "spec",
       r"(\| T2-13 \|[^|]*\| )not gated", r"\1T2", regex=True),
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
    p = ROOT / TOOL_REL
    src = p.read_text(encoding="utf-8")
    head, _, rest = src.partition("RULED_PINS: tuple[str, ...] = (")
    _, _, tail = rest.partition("\n# ruled-pins:end")
    body = "".join(f'    "{ln}",\n' for ln in lines)
    p.write_text(f"{head}RULED_PINS: tuple[str, ...] = (\n{body})\n# ruled-pins:end{tail}", "utf-8")
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


def _md(head: list[str], body: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    return "\n".join(out + ["| " + " | ".join(r) + " |" for r in body])


def fill() -> int:
    p = ROOT / SPEC_REL
    text = p.read_text(encoding="utf-8")
    pair_head = ["Pair", "Floor", *THEMES]
    text = replace_table(text, "### 10.1", _md(pair_head, [pair_row(*q) for q in UNION_PAIRS]))
    text = LOW_HC_RE.sub(lambda _m: f"**Lowest high-contrast text pair:** {lowest_hc()}", text)
    rej_head = ["Pair", "Bar", *THEMES, "Status"]
    text = replace_table(
        text, "### 10.2", _md(rej_head, [rejected_row(*q) for q in REJECTED_PAIRS])
    )
    rev_head = [*pair_head, "Meets in all three"]
    text = replace_table(text, "### 10.3", _md(rev_head, [review_row(*q) for q in REVIEW_PAIRS]))
    text = replace_table(text, "### 10.4", _md(["Pair", "Theme", *DEFICIENCIES], cvd_rows()))
    text = replace_table(text, "### 17.3", L.mutation_table(MUTATIONS))
    p.write_text(text, encoding="utf-8", newline="\n")
    print("sections 10.1, 10.2, 10.3, 10.4 and 17.3 written")
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
