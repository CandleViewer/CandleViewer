#!/usr/bin/env python3
"""E19-D06 (#501) audit: the accessibility review of the profile panel and its settings dialog.

Offline and default-deny. The shared gates (git, cites, pins, the G-T2 markers, closing keywords,
public text, hygiene, G-UNTOUCHED, the runner and the mutation harness) live in
`spec_audit_lib.py`, which sits beside this file byte-identical (G-HELPER); this file keeps only
E19-D06's rows. It reads, AS TEXT at a pinned commit, every document the review cites (the base
for the plan, the merged E19-D02, the memo, the rules and E26-D02; the three unmerged parents at
their PR heads), and, from the working tree, the review, the helper and `14`. The only
repo code it runs is `contrast_ratio()` of `docs/design/_tools/contrast_check.py` and
`simulate()` / `contrast_ratio()` / `delta_e76()` of `docs/research/_tools/cvd_simulate.py`,
loaded by path; E19-D03's written figures are read from its text at its pin, never copied.

Gates: `GATES` below, as section 16.2 names them. Pins (G-RULED): each BQ bullet's sha256[:16]
in `RULED_PINS` below, no separate pins file (the ruling's hand-off-pack rule 2); `--repin-ruled`
is the only writer. The BQ list is comment 6598368330 on #501, RULED by comment 6608044786.

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e19_d06_a11y_review_audit.py --check | --json | --self-test
  python3 -I -B docs/design/_tools/e19_d06_a11y_review_audit.py --repin | --repin-ruled | --fill
`--repin` prints where each key cite's words stand now; `--fill` writes section 9.
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
BASE = "b81479ab0"  # origin/main where the ruling fold re-read every cite
D03_HEAD = "35032f521"  # #5517 (E19-D03, #438) head; re-pinned to its merge commit
D02_PIN = "98b3c51a2"  # #5587 (E19-D02's boards, #416) merge commit
D04_PIN = "35465247d"  # #5553 (E19-D04, #439) merge commit, re-pinned from head b720bd97f
D05_PIN = "7e9b06296"  # #5555 (E19-D05, #500) merge commit, re-pinned from head eacb7cce2
BQ_LIST = "6598368330"  # the BQ list on #501
RULING = "6608044786"  # its ruling of record
AMENDED = frozenset({6, 7, 8, 12, 13, 14, 15})  # the rest AGREE
HELPER_SHA = "62b56d6446b218cd"  # sha256[:16] of the shared helper as landed

PIN_MARK = "# ruled-" + "pins:"  # the block --repin-ruled rewrites
# fmt: off
# ruled-pins:begin (sha256[:16] of each BQ bullet; written by --repin-ruled only)
RULED_PINS = (
    "BQ-0 e15b4ee159e64764", "BQ-1 5865cd9aafc259b7", "BQ-2 3bea5f26fab87a9e",
    "BQ-3 18b24acd51fde850", "BQ-4 94c62cc11354b579", "BQ-5 e17f624915c2ee08",
    "BQ-6 d1d88118077edfff", "BQ-7 00c19ce21a7a3c49", "BQ-8 b6995fd458810cbf",
    "BQ-9 2743dbd6cc066444", "BQ-10 1b5cf514e50b53a8", "BQ-11 4f3f5231422e5dbb",
    "BQ-12 ce92980deacfea70", "BQ-13 35e1c533e039681a", "BQ-14 72c51605f39a5c1e",
    "BQ-15 a3cfb7aaa9bbca31",
)
# ruled-pins:end
# fmt: on

SPEC_REL = "docs/design/E19/E19-D06.md"
TOOL_REL = "docs/design/_tools/e19_d06_a11y_review_audit.py"
LIB_REL = "docs/design/_tools/spec_audit_lib.py"
P14_REL = "docs/plan/14-screens-catalogue.md"
OWN = (SPEC_REL, TOOL_REL, LIB_REL)
# RULED BQ-14: the one link-only line this PR adds to `14`, under SCR-038's E19-D04 line.
ANCHOR = "- **Flows (E19-D04):** [E19-D04.md](../design/E19/E19-D04.md) §2\u2013§7"
POINTER = (
    "- **A11y review (E19-D06):** [E19-D06.md](../design/E19/E19-D06.md) §3, §7 (the table "
    "strategy and the announcement policy, text first, owner approval pending; a pointer only, "
    "it changes no requirement here)."
)
BACKLOG_REL = "docs/plan/backlog/E19.json"

# fmt: off
PLAN = {k: f"docs/plan/{k}-{v}.md" for k, v in (
    ("05", "accessibility-standard"), ("11", "user-stories"), ("14", "screens-catalogue"),
    ("15", "component-catalogue"), ("16", "design-system-brief"), ("23", "ws-protocol"),
    ("24", "internal-schemas"),
)}
KEYED = {k: L.DocRef(path, pin) for k, path, pin in (
    ("D02", "docs/design/E19/E19-D02.md", D02_PIN), ("D03", "docs/design/E19/E19-D03.md", D03_HEAD),
    ("D03H", "docs/design/E19/E19-D03-handoff.md", D03_HEAD),
    ("D04", "docs/design/E19/E19-D04.md", D04_PIN),
    ("D05", "docs/design/E19/E19-D05.md", D05_PIN),
    ("M", "docs/design/research/e19-profiles.md", BASE),
    ("DS", ".claude/rules/32-design-specs.md", BASE), ("README", "docs/design/README.md", BASE),
    ("KM", "apps/web/src/keymap/keymap.json", BASE),
)} | {k: L.DocRef(f"docs/design/{k[:3]}/{k}.md", BASE) for k in (
    "E26-D02", "E47-D04", "E47-D06", "E47-D07", "E17-D02", "E12-D11", "E08-D12", "E09-D10",
)}
# fmt: on
_ALTS = "|".join(re.escape(k) for k in sorted(KEYED, key=len, reverse=True))
# `NN`:line, KEY:line or `KEY`:line, with an optional -end.
CITE_RE = re.compile(
    rf"(?:`(?P<nn>\d\d)`|`?(?<![A-Za-z0-9-])(?P<named>{_ALTS})`?):(?P<first>\d+)"
    r"(?:\u2013(?P<firstend>\d+))?"
)

# The load-bearing cites, pinned to their words (`--repin` proposes moves).
# fmt: off
KEY_CITES: tuple[L.KeyCite, ...] = tuple(
    L.KeyCite(d, n, s)
    for d, n, s in (
        ("14", 1014, "a table alternative lists each price row"), ("14", 1015, "up to 5 000 rows"),
        ("14", 1028, "the mode selector is a radio group"), ("05", 99, "Roving tabindex"),
        ("05", 100, "Focus is never silently stolen"), ("05", 101, "trap focus"),
        ("05", 104, "essential exception"), ("05", 150, "accessible name of the window region"),
        ("05", 162, "profile-histogram bars"), ("05", 185, "default 1 update / 2s per field"),
        ("05", 187, "reduce announcements"), ("05", 249, "Ctrl+Shift+M"), ("05", 251, "2.2.2"),
        ("05", 252, "No content flashes more than 3 times per second"),
        ("05", 205, "**Profile table**"), ("05", 229, "load more rows"),
        ("15", 592, "the shared composite-grid pattern"), ("15", 1298, "never fill-colour alone"),
        ("15", 2410, "each TPO letter-block is DOM-mirrored"),
        ("16", 146, "never the 24 px targets"), ("23", 753, "1 000 ms"),
        ("23", 1346, "drop `heatmap` and `profile` to 1 000 ms"),
        ("24", 981, "class ProfileLevel(BaseModel):"), ("D02", 97, "no DEMO / LIVE badge"),
        ("D02", 100, "R-4 Announcements"), ("D02", 256, "none (E17's system notice owns it)"),
        ("D02", 271, "Initial focus: the first radio of Period"), ("D02", 273, "focus trapped"),
        ("D02", 339, "MEMO A-6's TPO count"),
        ("D02", 340, "header controls → histogram mirror → legend → table"),
        ("D02", 343, "essential exception"),
        ("D02", 383, "{level word} {price}: volume {v}, delta {d}"),
        ("D03", 175, "the engine draws from system colours"), ("D03", 183, "wrap, never truncate"),
        ("D03", 285, "Behaviour (1.4.13)"), ("D03", 355, "The Levels group"),
        ("D03", 424, "D03-C11"), ("D03", 442, "D03-A3"), ("D03", 461, "no tritan matrix"),
        ("D04", 183, "24 \u00d7 24 CSS px"), ("D04", 260, "profile range stop"),
        ("D04", 405, "D04-C6"),
        ("D05", 166, "RenderFlags.animate"), ("D05", 170, "The canvas is not recoloured by the OS"),
        ("D05", 172, "wrap or truncate with a"), ("D05", 243, "WCAG 2.2.2"),
        ("D05", 394, "Combined M-2 + M-4 + M-8"), ("D05", 433, '"Final" spoken alone'),
        ("E26-D02", 44, "profile"), ("M", 265, "A-6"), ("DS", 15, "G-T2 miss is a Major"),
        ("05", 105, "2.5.7"), ("05", 119, "R-11"), ("16", 142, "documented compensating control"),
        ("16", 743, "7. Ticket's linked downstream"),
        ("E47-D04", 117, "R-2 One stop per composite"),
        ("E47-D04", 122, "R-7 Restore to the invoker"),
        ("E47-D06", 151, "one Tab stop (the plot stop)"),
        ("E47-D06", 171, "| profile | mirror rows"), ("E47-D06", 191, "| N-3 | profile level"),
        ("E47-D06", 192, "| N-4 | TPO level"),
        ("E47-D06", 220, "**Profile** (`05`'s column set verbatim"),
        ("E47-D06", 270, "`Alt+T` toggles it in that panel's context"),
        ("E47-D07", 243, "one composite per cadence"),
        ("E47-D07", 247, "at most once per 5 s per region"), ("E47-D07", 638, "1 / 2 / 5 s"),
        ("E17-D02", 88, "Heatmap refresh slowed to 1 second."),
        ("E26-D02", 446, "replay of 13 September 2026"), ("KM", 337, '"id": "chart.table_toggle"'),
        ("README", 44, "Mandatory evidence on EVERY design ticket"),
        ("E12-D11", 69, "no boards and no Penpot page"),
        ("E08-D12", 60, "no boards, no Penpot page"),
        ("E09-D10", 43, "No new boards, no Penpot page"),
    )
)
# fmt: on

DEFICIENCIES = ("deuteranopia", "protanopia", "tritanopia")
CANVAS = "color.surface.canvas"
# D03's PROPOSED aliases for the TPO tokens (D03:121-122); high contrast resolves to dark.
TPO_ALIAS: dict[str, dict[str, str]] = {
    "dark": {
        "color.tpo.letter": "palette.neutral.700",
        "color.tpo.initialbalance": "palette.cyan.400",
    },
    "light": {
        "color.tpo.letter": "palette.light.neutral.700",
        "color.tpo.initialbalance": "palette.light.cyan.300",
    },
}
TPO_ALIAS["high-contrast"] = TPO_ALIAS["dark"]
# Section 9.1: the pairs the profile draws (ink or text, background, floor).
# fmt: off
PAIRS: tuple[tuple[str, str, float], ...] = (
    ("color.profile.bar", CANVAS, 3.0), ("color.profile.poc", CANVAS, 3.0),
    ("color.profile.valuearea", CANVAS, 3.0), ("color.tpo.letter", CANVAS, 4.5),
    ("color.tpo.initialbalance", CANVAS, 3.0), ("color.tpo.letter", "color.surface.raised", 4.5),
    ("color.text.tertiary", CANVAS, 3.0), ("color.text.secondary", CANVAS, 3.0),
    ("color.buy.default", CANVAS, 3.0), ("color.sell.default", CANVAS, 3.0),
    ("color.chart.focus.ring", CANVAS, 3.0), ("color.focus.ring", CANVAS, 3.0),
    ("color.focus.ring", "color.surface.raised", 3.0),
    ("color.focus.ring", "color.surface.overlay", 3.0),
    ("color.text.primary", "color.surface.raised", 4.5),
    ("color.text.secondary", "color.surface.raised", 4.5),
    ("color.text.tertiary", "color.surface.raised", 4.5),
    ("color.text.secondary", "color.surface.overlay", 4.5),
    ("color.text.tertiary", "color.surface.overlay", 4.5),
)
# fmt: on
# Section 9.2: the inks under simulation, each on the canvas.
# fmt: off
INKS: tuple[tuple[str, float], ...] = (
    ("color.profile.bar", 3.0), ("color.profile.poc", 3.0), ("color.profile.valuearea", 3.0),
    ("color.tpo.letter", 4.5), ("color.tpo.initialbalance", 3.0), ("color.buy.default", 3.0),
    ("color.sell.default", 3.0),
)
# fmt: on
D03_CHECKED = INKS[:5]  # D03 section 2.2 writes these five on the canvas (D03:132-136)
SIDE_PAIR = ("color.buy.default", "color.sell.default")

SEVERITIES = ("Blocking", "Major", "Minor", "Info")
AREAS = ("order-flow", "design-system")
DISPOSITIONS = ("decision", "F row", "A row", "C row", "G row", "verdict")
LR_OBJECTS = ("level", "state", "action", "press", "silent")
LR_POLITE = ("polite", "off")
LR_RATES = ("the cadence", "≤ 1 per 5 s", "once", "once per press", "never")
LR_SILENT_NEED = ("VAH or VAL", "print", "re-bucket", "patches", "reduce announcements")
# fmt: off
VERDICTS = (
    "compliant if #5517 merges as is", "compliant", "at risk", "non-compliant", "out of scope —",
    "not yet decidable —",
)
# fmt: on
CR_VERDICTS = ("compliant", "compliant if #5517 merges as is", "at risk")
# Section 10.1 and the motion verdicts: one row per moving D05 section 2 entry.
MOTION_HEAD = "### 10.1 Motion is never the only carrier"
MOTION_V = (("2.3.1", "`05`:252", "D05:389"), ("2.2.2", "`05`:251", "D05:243"))
SCENARIOS = 6
INBOX = 24
DECISIONS = 10
# RULED BQ-6: `05`'s five columns (`05`:209-213), adopted verbatim by E47-D06 (:224-228).
COLUMNS = ("Price", "Volume", "Delta", "% of POC", "Value area")
COLUMN_ROWS = (("05", 208), ("E47-D06", 223))  # 0-based first row of each table
NOT_COLUMNS = ("Buy", "Sell", "Trades", "Level", "TPO count")
# fmt: off
TABLE_NEED = (
    "at most 200 rows mounted", "`aria-rowcount`", "`aria-rowindex`", "above and below",
    "the focused row stays mounted", "**Rejected:**",
)
# fmt: on
HOLD = "**Hold:** #501 is not Done and E19-D07 (#502) does not start while a Blocking row stands"
PARENT_RE = re.compile(r"#438 boards PR|#439 boards PR|#500 boards PR")
STORY_RE = re.compile(r"#638|#639|#640|#642|#679|#680|#681|#747|#748")
ENV_NEED = ("DEMO / LIVE", "global chrome", "REPLAY chip", '"replay of {date}"')
ACCOUNT_WORDS = re.compile(r"\b(?:account|credential|balance|api key|secret)\b", re.IGNORECASE)
F_HEAD_RE = re.compile(
    r"^## 12\. Findings — F (\d+) \(Blocking (\d+) · Major (\d+) · Minor (\d+) · Info (\d+)\)"
    r" <!-- audit:f=(\d+)/(\d+)/(\d+)/(\d+)/(\d+) -->$",
    re.MULTILINE | re.DOTALL,
)
F_MARK_RE = re.compile(r" audit:f=\d+/\d+/\d+/\d+/\d+ ", re.DOTALL)
PREFIXES = "IB|AD|FO|KS|T2|LR|CR|SR|F|V|C|G|Q|A|H"
ID_RE = re.compile(rf"(?:{PREFIXES})-\d\d")
# An own id; another spec's ids carry its prefix ("D05 W-1b", "M A-6") and are skipped.
REF_RE = re.compile(rf"(?<![\w-])(?<!D0\d )(?<!M )(?:{PREFIXES})-\d\d(?![\w.]*\d)(?!\.\d)")
POINTER_WORDS = re.compile(r"\b(?:click|hover|drag|mouse|pointer)\b", re.IGNORECASE)


# ---------- sources and measurers -----------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def docs() -> L.Docs:
    return L.Docs(repo(), BASE, KEYED, plan=PLAN)


def docs_of(t: L.Tree) -> L.Docs:
    """The cited documents, with a source drifted in memory when the tree says so (self-test)."""
    d = docs()
    drift = t.text("drift")  # "KEY|line|text"
    if drift:
        key, n, text = drift.split("|", 2)
        lines = list(d.lines(key) or ())
        lines[int(n) - 1] = text
        d = d.drifted(key, tuple(lines))
    return d


@functools.cache
def measurers() -> tuple[ModuleType, ModuleType]:
    return (
        L.load_module(ROOT, "docs/design/_tools/contrast_check.py", "contrast_check"),
        L.load_module(ROOT, "docs/research/_tools/cvd_simulate.py", "cvd_simulate"),
    )


@functools.cache
def theme(name: str) -> dict[str, str]:
    return L.resolve_theme(repo(), BASE, name)


def colour(name: str, token: str) -> str:
    t = theme(name)
    value = t.get(TPO_ALIAS[name].get(token, token), "")
    if not value.startswith("#"):
        raise L.AuditError(f"{token} does not resolve in {name}")
    return value


def rgb(hexv: str) -> tuple[int, int, int]:
    h = hexv.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(name: str, fg: str, bg: str) -> float:
    return float(measurers()[0].contrast_ratio(rgb(colour(name, fg)), rgb(colour(name, bg))))


def sim_ratio(name: str, fg: str, bg: str, deficiency: str) -> float:
    cvd = measurers()[1]
    a = cvd.simulate(colour(name, fg), deficiency)
    b = cvd.simulate(colour(name, bg), deficiency)
    return float(cvd.contrast_ratio(a, b))


def pair_row(fg: str, bg: str, floor: float) -> list[str]:
    return [
        f"`{fg}` on `{bg}`",
        f"{floor:g}",
        *(f"{ratio(n, fg, bg):.2f}" for n in L.THEME_PARTS),
    ]


def ink_row(fg: str, floor: float) -> list[str]:
    def cell(n: str) -> str:
        return " / ".join(f"{sim_ratio(n, fg, CANVAS, d):.2f}" for d in DEFICIENCIES)

    return [f"`{fg}`", f"{floor:g}", *(cell(n) for n in L.THEME_PARTS)]


def side_row(name: str) -> list[str]:
    cvd = measurers()[1]
    a, b = (colour(name, k) for k in SIDE_PAIR)
    normal = float(cvd.delta_e76(a, b))
    sims = [float(cvd.delta_e76(cvd.simulate(a, d), cvd.simulate(b, d))) for d in DEFICIENCIES]
    return [name, *(f"{v:.1f}" for v in (normal, *sims))]


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


def doc_text(d: L.Docs, key: str) -> str:
    return "\n".join(d.lines(key) or ())


# ---------- this review's gates -------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    d = docs_of(t)
    cites = L.extract_cites(spec(t), CITE_RE)
    bad = L.check_cites(cites, d, nonblank=False, min_count=150)
    # A range may span blank lines; its two ends must carry text.
    bad += [
        c.raw
        for c in cites
        if not (d.line(c.doc, c.lo) or "").strip() or not (d.line(c.doc, c.hi) or "").strip()
    ]
    return (
        [f"unresolved cites: {', '.join(sorted({b.split(' (')[0] for b in bad}))}"] if bad else []
    )


def g_keycite(t: L.Tree) -> list[str]:
    return L.check_key_cites(KEY_CITES, docs_of(t))


def g_version(t: L.Tree) -> list[str]:
    v = sec(t, "### 16.1 Version line")
    need = (BASE, D02_PIN, D03_HEAD, D04_PIN, D05_PIN, "re-pinned to its merge commit", HELPER_SHA)
    miss = [n for n in need if n not in v]
    if f"Base `origin/main` `{BASE}`" not in spec(t):
        miss.append("Inputs pinned base")
    return [f"missing: {', '.join(miss)}"] if miss else []


def g_ac(t: L.Tree) -> list[str]:
    tickets = json.loads(repo().show(BASE, BACKLOG_REL) or "[]")
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E19-D06")
    names = [n.strip() for n in re.findall(r"Scenario: (.+)", body)]
    trace = sec(t, "## Acceptance-criteria and DoD trace")
    miss = [n for n in names if f'AC "{n}"' not in trace]
    return (
        [f"scenario names not verbatim: {miss or names}"] if len(names) != SCENARIOS or miss else []
    )


def g_inbox(t: L.Tree) -> list[str]:
    got = rows(t, "## 2. The inbox")
    defined = defined_ids(spec(t))
    want = [f"IB-{i:02d}" for i in range(1, INBOX + 1)]
    bad = [] if [r[0] for r in got] == want else [f"not IB-01 … IB-{INBOX}"]
    for r in got:
        if len(r) < 4 or r[2] not in DISPOSITIONS:
            bad.append(f"{r[0]} disposition")
        elif not ids_in(r[3]) or any(i not in defined for i in ids_in(r[3])):
            bad.append(f"{r[0]} target")
    return bad


def g_decisions(t: L.Tree) -> list[str]:
    got = rows(t, "## 3. Adopted decisions")
    want = [f"AD-{i:02d}" for i in range(1, DECISIONS + 1)]
    bad = [] if [r[0] for r in got] == want else [f"not AD-01 … AD-{DECISIONS}"]
    for r in got:
        if len(r) < 4 or not r[2].strip("— ") or not re.search(r"#\d+", r[3]):
            bad.append(f"{r[0]} test or owner")
    return bad


def g_table(t: L.Tree) -> list[str]:
    ad = {r[0]: r[1] for r in rows(t, "## 3. Adopted decisions") if len(r) > 1}
    bad = [f"AD-01 lacks {n!r}" for n in TABLE_NEED if n not in ad.get("AD-01", "")]
    d = docs_of(t)
    for key, first in COLUMN_ROWS:
        got = [L.cells(ln)[0] for ln in (d.lines(key) or ())[first : first + 5]]
        if got != list(COLUMNS):
            bad.append(f"{key}'s profile columns are {got}")
    text = ad.get("AD-02", "")
    at = [text.find(f"**{c}**") for c in COLUMNS]
    if -1 in at or at != sorted(at) or any(f"**{c}**" in text for c in NOT_COLUMNS):
        bad.append("AD-02's columns are not `05`'s five in order, and no other")
    return bad


def g_keys(t: L.Tree) -> list[str]:
    bad = []
    for r in rows(t, "### 5.2"):
        if len(r) < 5 or "`" not in r[2] or POINTER_WORDS.search(r[2]) or "`" not in r[4]:
            bad.append(f"{r[0] if r else '?'} not keyboard-only with a way out")
    keymap = rows(t, "### 5.1")
    if any("letter" in r[1] for r in keymap if len(r) > 1):
        bad.append("a key bound per letter")
    ad5 = next((r[1] for r in rows(t, "## 3. Adopted decisions") if r[0] == "AD-05"), "")
    if "never a stop per letter" not in ad5:
        bad.append("AD-05 allows a stop per letter")
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
        elif r[5] not in VERDICTS:
            bad.append(f"{r[0]} verdict")
    return bad


def g_live(t: L.Tree) -> list[str]:
    bad = []
    got = rows(t, "## 7. The announcement policy")
    for r in got:
        if len(r) < 6 or r[1] not in LR_OBJECTS or r[3] not in LR_POLITE or r[4] not in LR_RATES:
            bad.append(f"{r[0] if r else '?'} object, politeness or rate")
        elif (r[1] == "silent") != ((r[3], r[4]) == ("off", "never")):
            bad.append(f"{r[0]} silent row spoken, or a spoken row silenced")
        elif not L.extract_cites(r[5], CITE_RE) and "`T`" not in r[5]:
            bad.append(f"{r[0]} source")
    silent = " ".join(r[2] for r in got if len(r) > 2 and r[1] == "silent")
    bad += [f"no silent row for {w}" for w in LR_SILENT_NEED if w not in silent]
    level = [r for r in got if len(r) > 5 and r[1] == "level"]
    if len(level) != 1 or level[0][4] != "the cadence" or "E47-D07:243" not in level[0][5]:
        bad.append("the POC row is not the one ambient field")
    for r in got:
        if len(r) > 5 and r[1] != "level" and r[4] == "the cadence":
            bad.append(f"{r[0]} ambient, not the POC")
        if len(r) > 5 and (r[1] == "state") != (r[4] == "≤ 1 per 5 s" and "E47-D07:247" in r[5]):
            bad.append(f"{r[0]} status pacing")
    return bad


def d03_meanings(d: L.Docs) -> list[str]:
    block = L.section(doc_text(d, "D03"), "## 3. The non-colour encoding table")
    return [r[1] for r in L.table_rows(block) if len(r) > 1 and r[0].isdigit()]


def norm(s: str) -> str:
    return s.split(" (")[0].strip().lower()


def g_colour(t: L.Tree) -> list[str]:
    got = rows(t, "## 8. Colour never")
    want = [norm(m) for m in d03_meanings(docs_of(t))]
    bad = [] if len(want) == 14 else [f"D03 lists {len(want)} meanings"]
    if [norm(r[1]) for r in got[:14] if len(r) > 1] != want:
        bad.append("CR-01 … CR-14 are not D03 section 3's meanings in its order")
    for r in got:
        if len(r) < 6 or not r[3].strip("— ") or not r[4].strip("— "):
            bad.append(f"{r[0] if r else '?'} carrier")
        elif not r[5].startswith(CR_VERDICTS):
            bad.append(f"{r[0]} verdict")
        elif r[5].startswith("at risk") and not re.search(r"F-\d\d", r[5]):
            bad.append(f"{r[0]} at risk names no F row")
    return bad


def d03_written(d: L.Docs) -> dict[str, list[str]]:
    block = L.section(doc_text(d, "D03"), "### 2.2 Measured contrast")
    return {r[0]: r[3:6] for r in L.table_rows(block) if len(r) > 5}


def g_contrast(t: L.Tree) -> list[str]:
    bad = []
    written = {r[0]: r for r in rows(t, "### 9.1")}
    for fg, bg, floor in PAIRS:
        want = pair_row(fg, bg, floor)
        if written.get(want[0], [])[:5] != want:
            bad.append(f"9.1 {want[0]}: measured {want[1:]}")
        if min(float(v) for v in want[2:]) < floor:
            bad.append(f"9.1 {want[0]} below {floor:g}")
    if len(written) != len(PAIRS):
        bad.append(f"{len(written)} 9.1 rows for {len(PAIRS)} pairs")
    d03 = d03_written(docs_of(t))
    for fg, floor in D03_CHECKED:
        want = pair_row(fg, CANVAS, floor)
        if d03.get(want[0]) != want[2:]:
            bad.append(f"D03 writes {want[0]} as {d03.get(want[0])}, measured {want[2:]}")
    return bad


def g_cvd(t: L.Tree) -> list[str]:
    bad = []
    written = {r[0]: r for r in rows(t, "### 9.2")}
    for fg, floor in INKS:
        want = ink_row(fg, floor)
        if written.get(want[0], []) != want:
            bad.append(f"9.2 {want[0]}: measured {want[2:]}")
        lows = [float(v) for cell in want[2:] for v in cell.split(" / ")]
        if min(lows) < floor:
            bad.append(f"9.2 {want[0]} below {floor:g} under simulation")
    if len(written) != len(INKS):
        bad.append(f"{len(written)} 9.2 rows for {len(INKS)} inks")
    sides = {r[0]: r for r in rows(t, "### 9.3")}
    for name in L.THEME_PARTS:
        if sides.get(name) != side_row(name):
            bad.append(f"9.3 {name}: measured {side_row(name)[1:]}")
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
    return bad


def g_findings(t: L.Tree) -> list[str]:
    got = rows(t, "## 12. Findings")
    counts = [len(got)] + [sum(1 for r in got if len(r) > 1 and r[1] == s) for s in SEVERITIES]
    m = F_HEAD_RE.search(spec(t))
    bad = []
    if m is None or [int(x) for x in m.groups()] != counts + counts:
        bad.append(f"heading or marker vs table {counts}")
    if HOLD not in sec(t, "## 12. Findings"):
        bad.append("hold sentence")
    order = [SEVERITIES.index(r[1]) for r in got if len(r) > 1 and r[1] in SEVERITIES]
    if order != sorted(order):
        bad.append("not most severe first")
    for r in got:
        if len(r) < 7 or r[1] not in SEVERITIES:
            bad.append(f"{r[0] if r else '?'} severity")
            continue
        if not L.extract_cites(r[2], CITE_RE) and "§9" not in r[2]:
            bad.append(f"{r[0]} evidence")
        if not re.search(r"\b\d\.\d\.\d+\b|`05`", r[4]):
            bad.append(f"{r[0]} criterion")
        if not any(f"({a})" in r[5] for a in AREAS):
            bad.append(f"{r[0]} owner")
        if r[1] == "Info":
            if r[6] != "E19-D07 #502":
                bad.append(f"{r[0]} Info targets")
        elif "E19-D07 #502" not in r[6] or not PARENT_RE.search(r[6]) or not STORY_RE.search(r[6]):
            bad.append(f"{r[0]} targets")
    return bad


def g_ids(t: L.Tree) -> list[str]:
    defined = defined_ids(spec(t))
    refs = set(REF_RE.findall(spec(t)))
    return [f"dangling: {', '.join(sorted(refs - defined))}"] if refs - defined else []


def g_handoff(t: L.Tree) -> list[str]:
    got = rows(t, "### 13.5")
    q06 = [r for r in got if len(r) > 3 and "E19-Q06 #744" in r[3]]
    bad = [
        f"{r[0]} assertion name"
        for r in q06
        if not re.search(r"`scr03[89]\.[a-z0-9.-]+` \((?:axe|Playwright)", r[1])
    ]
    covered = {i for r in q06 for i in re.findall(r"AD-\d\d", r[2])}
    ads = {r[0] for r in rows(t, "## 3. Adopted decisions")}
    return bad + [f"{a} reaches no E19-Q06 assertion" for a in sorted(ads - covered)]


def g_env(t: L.Tree) -> list[str]:
    ad9 = next((r[1] for r in rows(t, "## 3. Adopted decisions") if r[0] == "AD-09"), "")
    bad = [f"AD-09 lacks {n!r}" for n in ENV_NEED if n not in ad9]
    if not any(ln.startswith("- **R-5 C-2.11.") for ln in spec(t).split("\n")):
        bad.append("R-5")
    for r in rows(t, "### 14.1"):
        if ACCOUNT_WORDS.search(" ".join(r[1:3])):
            bad.append(f"{r[0]} speaks account data")
    return bad


def d05_moving(d: L.Docs) -> list[str]:
    block = L.section(doc_text(d, "D05"), "## 2. The motion table")
    return [f"D05 {r[0]}" for r in L.table_rows(block) if len(r) > 3 and r[3].startswith("yes")]


def g_motion(t: L.Tree) -> list[str]:
    want = d05_moving(docs_of(t))
    got = rows(t, MOTION_HEAD)
    bad = [] if want else ["D05 section 2 lists no moving entry"]
    if [r[0] for r in got] != want:
        bad.append(f"10.1 rows {[r[0] for r in got]} are not D05's moving entries {want}")
    for r in got:
        if len(r) < 5 or not r[2].strip("— ") or not r[3].strip("— "):
            bad.append(f"{r[0] if r else '?'} carrier or reduce form")
        elif not r[4].startswith(VERDICTS):
            bad.append(f"{r[0]} verdict")
    verdicts = rows(t, "## 11. Clause verdicts")
    for clause, rule, evidence in MOTION_V:
        hit = [r for r in verdicts if len(r) > 3 and r[1].startswith(f"{clause} / {rule}")]
        if len(hit) != 1 or evidence not in hit[0][3]:
            bad.append(f"no {clause} verdict citing {evidence}")
    v29 = next((r[1] for r in verdicts if r and r[0] == "V-29"), "")
    if "`Ctrl+Shift+M`" not in v29:
        bad.append("V-29 omits the in-app override")
    return bad


def g_walk(t: L.Tree) -> list[str]:
    items = re.findall(r"^(\d+)\. ", sec(t, "### 14.3"), re.MULTILINE)
    n = len(items)
    ok = 0 < n <= 10 and items == [str(i) for i in range(1, n + 1)]
    return [] if ok else [f"{n} walkthrough items"]


def g_ruling(t: L.Tree) -> list[str]:
    return L.check_ruling(
        spec(t),
        heading_line=(
            "## The questions BQ-0 … BQ-15 — "
            f"RULED (orchestrator, comment {RULING}, on the BQ list {BQ_LIST})"
        ),
        list_ref=f"comment {BQ_LIST} on #501",
        count=16,
        verdict=lambda n: f"RULED ({RULING}), {'AMEND' if n in AMENDED else 'AGREE'}",
        forbid=("PENDING (comment",),
    )


def g_ruled(t: L.Tree) -> list[str]:
    return L.check_hash_pins(spec(t), "\n".join(RULED_PINS))


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
    return L.untouched(t.changed, OWN, budgets={P14_REL: (1, 0)}, numstat=t.numstat)


def g_pointer(t: L.Tree) -> list[str]:
    base = (repo().show(repo().diff_base(BASE), P14_REL) or "").splitlines()
    at = next((i for i, ln in enumerate(base) if ln.startswith(ANCHOR)), None)
    if at is None:
        return ["SCR-038's E19-D04 line is not in `14`"]
    want = [*base[: at + 1], POINTER, *base[at + 1 :]]
    ok = t.text("p14").splitlines() == want
    return [] if ok else ["`14` is not its base plus the one pointer line under SCR-038"]


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper(), f) for f in (
    g_cite, g_keycite, g_version, g_ac, g_inbox, g_decisions, g_table, g_keys, g_t2, g_live,
    g_colour, g_contrast, g_cvd, g_verdict, g_findings, g_ids, g_handoff, g_env, g_motion, g_walk,
    g_ruling, g_ruled, g_noclose, g_public, g_hygiene, g_helper, g_untouched, g_pointer,
))
# fmt: on


def _drift(mid: str, gate: str, what: str, text: str) -> L.Mutation:
    def fn(tree: L.Tree) -> L.Tree:
        return dataclasses.replace(tree, files={**tree.files, "drift": text})

    return L.Mutation(mid, gate, what, fn=fn)


_M = L.Mutation
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-01", "G-CITE", "a cite past the end of D03", "spec", "(D03:199)", "(D03:99999)"),
    _drift("M-02", "G-KEYCITE", "a pinned source line reworded",
           "14|1014|- **A11y:** the profile is read aloud."),
    _M("M-03", "G-VERSION", "the version line drops the re-pin", "spec",
       "D02 at #5587's merge commit `98b3c51a2`", "D02 at the base"),
    _M("M-04", "G-AC", "a scenario name reworded", "spec",
       'AC "A blocker stops sign-off"', 'AC "A blocker stops"'),
    _M("M-05", "G-INBOX", "an inbox row deferred", "spec",
       r"(\| IB-09 \|[^\n]*?\| )G row", r"\1deferred", regex=True),
    _M("M-06", "G-DECISIONS", "a decision with no owner ticket", "spec",
       r"(\| AD-06 \|[^\n]*\| )E19-T04 #642( *\|)", r"\1the engine\2", regex=True),
    _M("M-07", "G-TABLE", "the columns leave `05`'s order", "spec",
       "**Volume**, **Delta**", "**Delta**, **Volume**"),
    _M("M-08", "G-TABLE", "the mounted cap raised", "spec",
       "at most 200 rows mounted (PROPOSED", "at most 500 rows mounted (PROPOSED"),
    _M("M-09", "G-KEYS", "a walk needs a pointer", "spec",
       "`Tab` to Settings; `Enter`; `Tab` through", "click Settings; `Tab` through"),
    _M("M-10", "G-KEYS", "a stop per letter allowed", "spec",
       "never a stop per letter (F-10)", "a stop per letter allowed (F-10)"),
    _M("M-11", "G-T2", "R-4 loses the describedby link", "spec",
       "linked by `aria-describedby` (G-T2.1c)", "linked (G-T2.1c)"),
    _M("M-12", "G-T2", "the view-as leg not first", "spec",
       "`rbac.view_as` first (D02:112; D04:111)", "`rbac.permission` first (D02:112; D04:111)"),
    _M("M-13", "G-LIVE", "a print spoken", "spec",
       r"(\| LR-12 \|[^\n]*?\| )off( +\| )never", r"\1polite\2once", regex=True),
    _M("M-14", "G-LIVE", "the POC row leaves the cadence", "spec",
       r"(\| LR-01 \|[^\n]*?\| )the cadence", r"\g<1>1 per 1 s", regex=True),
    _M("M-15", "G-LIVE", "an assertive message", "spec",
       r"(\| LR-06 \|[^\n]*?\| )polite", r"\1assertive", regex=True),
    _M("M-16", "G-COLOUR", "a meaning out of D03's order", "spec",
       r"\| CR-05 \| HVN ", "| CR-05 | LVN ", regex=True),
    _M("M-17", "G-COLOUR", "a meaning carried by nothing", "spec",
       r"(\| CR-09 \|[^|]*\|[^|]*\| )[^|]*?( +\|)", r"\1—\2", regex=True),
    _M("M-18", "G-CONTRAST", "a written pair ratio drifts", "spec",
       r"(`color\.profile\.bar` on `color\.surface\.canvas` *\| 3 *\| )\d+\.\d\d",
       r"\g<1>9.99", regex=True),
    _drift("M-19", "G-CONTRAST", "D03's written figure disagrees",
           "D03|132|| `color.profile.bar` on `color.surface.canvas` | non-text | 3.0 | 3.33"
           " | 4.02 | 3.03 | pass |"),
    _M("M-20", "G-CVD", "a simulated ratio drifts", "spec",
       r"(\| `color\.profile\.bar` *\| 3 *\| )\d+\.\d\d", r"\g<1>9.99", regex=True),
    _M("M-21", "G-VERDICT", "a compliant verdict names an F row", "spec",
       r"(\| V-02 \|[^\n]*?\| )compliant( +\|)", r"\1compliant — F-10\2", regex=True),
    _M("M-22", "G-FINDINGS", "the heading count drifts", "spec",
       "Major 2 · Minor 10 · Info 3)", "Major 2 · Minor 9 · Info 3)"),
    _M("M-23", "G-FINDINGS", "a finding loses its story", "spec",
       r"(\| F-03 \|[^\n]*?E19-D07 #502) · E19-S01 #638", r"\1", regex=True),
    _M("M-24", "G-FINDINGS", "the hold sentence dropped", "spec",
       "**Hold:** #501 is not Done", "Hold: #501 is not Done"),
    _M("M-25", "G-IDS", "a dangling F id", "spec", "(F-08; G-01)", "(F-28; G-01)"),
    _M("M-26", "G-HANDOFF", "a decision with no Q06 assertion", "spec",
       "| AD-08; V-08 ", "| V-08        "),
    _M("M-27", "G-ENV", "the script speaks an account", "spec",
       "the Settings button's name; nothing else", "the Settings button's name and the account"),
    _M("M-28", "G-ENV", "the replay name dropped", "spec",
       'its region name ending "replay of {date}"', 'its region name ending "Replay"'),
    _M("M-29", "G-WALK", "an eleventh walkthrough item", "spec",
       "10. Comment `approved`", "10. One more pass.\n11. Comment `approved`"),
    _M("M-30", "G-RULING", "the heading names another comment", "spec",
       "RULED (orchestrator, comment 6608044786", "RULED (orchestrator, comment 6608044787"),
    _M("M-31", "G-RULED", "a BQ default edited without a re-pin", "spec",
       "Default built: virtualised, at most 200", "Default built: virtualised, at most 250"),
    _M("M-32", "G-NOCLOSE", "a closing keyword", "spec",
       "nothing is filed.", "nothing is filed. " + "Clo" + "ses #501."),
    _M("M-33", "G-PUBLIC", "a URL", "spec",
       "**No new boards and no new Penpot page**",
       "**No new boards and no new Penpot page** (" + "http" + "s://example.org)"),
    _M("M-34", "G-PUBLIC", "a stray HTML comment", "spec",
       "## 17. Summary for #501", "## 17. Summary for #501 " + "<!" + "-- note -->"),
    _M("M-35", "G-HYGIENE", "trailing whitespace", "spec",
       "## 17. Summary for #501\n", "## 17. Summary for #501  \n"),
    _M("M-36", "G-HELPER", "the helper edited", "lib",
       "Shared gates for the per-spec", "Shared checks for the per-spec"),
    _M("M-37", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/05-accessibility-standard.md"),
    _M("M-38", "G-MOTION", "a moving entry loses its static carrier", "spec",
       r"(\| D05 M-2 +\|[^|\n]*\| )[^|\n]*?( +\|)", r"\1—\2", regex=True),
    _M("M-39", "G-MOTION", "the flash verdict dropped", "spec",
       "| 2.3.1 / `05`:252 — nothing flashes", "| `05`:252 — nothing flashes"),
    _M("M-40", "G-MOTION", "V-29 loses the in-app override", "spec",
       "reduce, by OS or `Ctrl+Shift+M`, keeps meaning", "reduce, by OS setting, keeps meaning"),
    _M("M-41", "G-POINTER", "the `14` pointer line reworded", "p14",
       "§3, §7 (the table strategy", "§3, §7 (the binding table strategy"),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    base = repo().diff_base(BASE)

    def disk(rel: str) -> str:
        p = ROOT / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""

    return L.Tree(
        files={
            "spec": disk(SPEC_REL),
            "tool": disk(TOOL_REL),
            "lib": disk(LIB_REL),
            "p14": disk(P14_REL),
        },
        changed=repo().changed_paths(base),
        numstat={P14_REL: repo().numstat(base, P14_REL)},
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
    pins = L.bq_hash_pins((ROOT / SPEC_REL).read_text(encoding="utf-8"))
    p = ROOT / TOOL_REL
    src = p.read_text(encoding="utf-8")
    a = src.index(PIN_MARK + "begin")
    a = src.index("\n", a) + 1
    b = src.index(PIN_MARK + "end")
    rows = (", ".join(f'"{x}"' for x in pins[i : i + 3]) for i in range(0, len(pins), 3))
    body = "RULED_PINS = (\n" + "".join(f"    {r},\n" for r in rows) + ")\n"
    L.write_pins(p, src[:a] + body + src[b:])
    print(f"pinned {len(pins)} BQ lines")
    return 0


def replace_table(text: str, heading: str, table: str) -> str:
    t0 = text.index("\n|", text.index(heading)) + 1
    end = t0
    for line in text[t0:].split("\n"):
        if not line.startswith("|"):
            break
        end += len(line) + 1
    return text[:t0] + table + "\n" + text[end:]


def md_table(head: list[str], body: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    return "\n".join(out + ["| " + " | ".join(r) + " |" for r in body])


def fill() -> int:
    p = ROOT / SPEC_REL
    text = p.read_text(encoding="utf-8")
    themes = list(L.THEME_PARTS)
    t91 = md_table(["Pair", "Floor", *themes], [pair_row(*q) for q in PAIRS])
    t92 = md_table(["Ink", "Floor", *themes], [ink_row(*q) for q in INKS])
    t93 = md_table(["Theme", "normal", *DEFICIENCIES], [side_row(n) for n in themes])
    text = replace_table(text, "### 9.1", t91)
    text = replace_table(text, "### 9.2", t92)
    text = replace_table(text, "### 9.3", t93)
    p.write_text(text, encoding="utf-8", newline="\n")
    print("sections 9.1, 9.2 and 9.3 written")
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
