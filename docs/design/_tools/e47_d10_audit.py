#!/usr/bin/env python3
"""E47-D10 (#1309) audit: the design-system accessibility contribution (spec + hand-off).

Offline and default-deny. The shared machinery (git, markdown tables, hygiene, the public-repo
scan, R7, G-UNTOUCHED, the runner and the mutation harness) lives in `spec_audit_lib.py`; this
file keeps only E47-D10's rows. It reads the spec and the hand-off from the working tree, `15`
from the working tree for the ledger, and every other cited source AS TEXT at the base pin.

Gates: G-LEDGER, G-IDS, G-OLD, G-FINDINGS, G-DEPRECATE, G-PATTERNS, G-STORIES, G-HYGIENE,
G-MUTLIST (spec section 13.2 equals this tool's list) and G-UNTOUCHED.

Usage (from the repo root):
  python3 -I docs/design/_tools/e47_d10_audit.py --check | --self-test
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import functools
import json
import posixpath
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
BASE = "b81479ab0"  # origin/main at the spec's base; every cited source is read here

SPEC_REL = "docs/design/E47/E47-D10.md"
HANDOFF_REL = "docs/design/E47/E47-D10-handoff.md"
TOOL_REL = "docs/design/_tools/e47_d10_audit.py"
OWN = (SPEC_REL, HANDOFF_REL, TOOL_REL)  # the helper is read from main, never copied
CAT_REL = "docs/plan/15-component-catalogue.md"
REG_REL = "docs/plan/a11y/47-audit-register.json"
ANN_REL = "apps/web/src/features/app-shell/announcer.tsx"
COMPONENTS = "packages/ui/src/components"
FEATURES = "apps/web/src/features/"

BANDS: tuple[tuple[int, int], ...] = (
    (1, 39),
    (40, 69),
    (70, 99),
    (100, 139),
    (140, 159),
    (160, 179),
    (180, 199),
    (200, 253),
)
CLAUSE = "Contract (E47-D10"
PRIMITIVES = (
    ("3.1", "CMP-259", "LiveRegion"),
    ("3.2", "CMP-260", "VisuallyHidden"),
    ("3.3", "CMP-261", "MotionVariant"),
    ("3.4", "CMP-262", "NonColorState"),
)
A_ROWS = frozenset({1, 2, *range(7, 42)})  # D10-A3 ... D10-A6 are section C.2's block
PATTERNS = (
    ("P-1", "CMP-048"),
    ("P-2", "CMP-009"),
    ("P-3", "CMP-042"),
    ("P-4", "CMP-041"),
    ("P-5", "CMP-043"),
    ("P-6", "CMP-049"),
)
ARIA_DISABLED_ROWS = ("P-1", "P-3", "P-4")
ESC_ROWS = ("P-1", "P-2", "P-4", "P-5", "P-6")  # tabs have no `Esc` of their own
STORIES = ("Keyboard", "FocusVisible", "ReducedMotion", "HighContrast", "LiveRegion")
DP_MARKERS = ("aria-live", "role=", "matchMedia", "outline", "announce(", "reducedMotion")
CONFORMING = "DP-12"  # kept, not migrated: existence only
CENSUS_ERE = (
    r'aria-live="(polite|assertive)"|aria-live=\{|role="status"|role="alert"'  # git grep -E
)
HEADING_RE = re.compile(r"^### (CMP-(\d{3}))\b")
CITE_RE = re.compile(
    r"(ANN|`([^`]+\.(?:tsx|ts|css))`)((?::\d+(?:\u2013\d+)?)(?:, :\d+(?:\u2013\d+)?)*)"
)
SPAN_RE = re.compile(r":(\d+)(?:\u2013(\d+))?")


# ---------- sources -------------------------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


def at_base(rel: str) -> str:
    text = repo().show(BASE, rel)
    if text is None:
        raise L.AuditError(f"{rel} not readable at {BASE}")
    return text


def rows(text: str, heading: str) -> list[list[str]]:
    return L.table_rows(L.section(text, heading))


def plain(cell: str) -> str:
    return cell.replace("*", "").strip()


# ---------- the ledger (spec section 2.2) ---------------------------------------------------------
def ledger(catalogue: str) -> dict[str, list[str]]:
    """Per band: [entries, the no-A11y ids, clauses absent, clauses present]."""
    entries: list[tuple[int, list[str]]] = []
    for line in catalogue.split("\n"):
        m = HEADING_RE.match(line)
        if m:
            entries.append((int(m.group(2)), []))
        elif line.startswith("## "):
            entries.append((-1, []))  # a section boundary closes the entry
        elif entries and line.startswith("- **A11y"):
            entries[-1][1].append(line)
    out: dict[str, list[str]] = {}
    for lo, hi in BANDS:
        band = [(n, a) for n, a in entries if lo <= n <= hi]
        none = [str(n) for n, a in band if not a]
        present = sum(1 for _, a in band if any(CLAUSE in x for x in a))
        absent = len(band) - len(none) - present
        key = f"CMP-{lo:03d}..{hi:03d}"
        out[key] = [str(len(band)), ", ".join(none) or "—", str(absent), str(present)]
    return out


def g_ledger(t: L.Tree) -> list[str]:
    got = ledger(t.text("catalogue"))
    table = rows(t.text("spec"), "### 2.2")
    bad: list[str] = []
    seen = {r[0]: [plain(c) for c in r[1:5]] for r in table if r[0] in got}
    for band, want in got.items():
        if seen.get(band) != want:
            bad.append(f"{band}: spec {seen.get(band)} vs parse {want}")
    total = [r for r in table if plain(r[0]) == "Total"]
    sums = [sum(int(v[i]) for v in got.values()) for i in (0, 2, 3)]
    nones = sum(len(v[1].split(", ")) for v in got.values() if v[1] != "—")
    want_total = [str(sums[0]), str(nones), str(sums[1]), str(sums[2])]
    if not total or [plain(c) for c in total[0][1:5]] != want_total:
        bad.append(f"Total row is not {want_total}")
    return bad


# ---------- ids, A-rows, findings -----------------------------------------------------------------
def g_ids(t: L.Tree) -> list[str]:
    spec, hand = t.text("spec"), t.text("handoff")
    bad: list[str] = []
    for sec, cmp, name in PRIMITIVES:
        if not re.search(rf"^### {re.escape(sec)} {cmp} `{name}`", spec, re.MULTILINE):
            bad.append(f"spec section {sec} is not {cmp} `{name}`")
        if f"### {cmp} {name} (utility; E47-D10)" not in hand:
            bad.append(f"hand-off lacks the {cmp} {name} entry")
    if "**CMP-259 … CMP-262, PROPOSED**" not in spec:
        bad.append("section 3 does not state the ids PROPOSED")
    bq4 = [b for b in spec.split("\n") if b.startswith("- **BQ-4**")]
    if not bq4 or "**CMP-259, CMP-260, CMP-261, CMP-262 (PROPOSED)**" not in bq4[0]:
        bad.append("the BQ-4 bullet does not carry the ruled ids")
    return bad


def a_rows(hand: str) -> list[tuple[str, int, str]]:
    """(id, `15` line, Old) for every copy-ready row of the hand-off's section C."""
    out: list[tuple[str, int, str]] = []
    for line in hand.split("\n"):
        if not re.match(r"^\| D10-A\d+ +\|", line):
            continue
        c = L.cells(line)
        tail = re.search(r"\((\d+)\)$", c[2])
        if tail:
            out.append((c[0], int(tail.group(1)), c[2][: tail.start()].strip()))
            continue
        field = re.search(r"`15`:(\d+)\)", c[2])
        if field is None:
            raise L.AuditError(f"{c[0]}: no `15` line in {c[2]!r}")
        out.append((c[0], int(field.group(1)), c[3]))
    return out


def g_old(t: L.Tree) -> list[str]:
    cat = at_base(CAT_REL).split("\n")
    hand = t.text("handoff")
    found = a_rows(hand)
    bad = [f"{a} Old not on `15`:{n}" for a, n, old in found if old not in cat[n - 1]]
    ids = {int(a.split("-A")[1]) for a, _, _ in found}
    if ids != A_ROWS:
        bad.append(f"A-rows {sorted(A_ROWS ^ ids)} missing or extra")
    anchor = re.search(
        r"^### §C\.2 [^\n]*after `15`:(\d+), the last line of `([^`]+)` \(`15`:(\d+)\), "
        r"before the `---` at `15`:(\d+)\)",
        hand,
        re.MULTILINE,
    )
    if anchor is None:
        bad.append("section C.2's anchor is missing")
        return bad
    rule = int(anchor.group(4))
    last, hline = int(anchor.group(1)), int(anchor.group(3))
    if (
        cat[hline - 1] != anchor.group(2)
        or cat[rule - 1] != "---"
        or not cat[last - 1].startswith("- ")
        or any(line.strip() for line in cat[last : rule - 1])
        or any(line.startswith("### ") for line in cat[hline : rule - 1])
    ):
        bad.append("section C.2's insert-after anchor does not hold")
    return bad


def g_findings(t: L.Tree) -> list[str]:
    reg = json.loads(at_base(REG_REL))
    want = {f["id"]: f["status"] for f in reg["findings"] if f.get("designOwner") == "E47-D10"}
    got = {r[0]: r[1] for r in rows(t.text("spec"), "## 10.")}
    return (
        [] if got == want else [f"section 10 {sorted(got.items())} vs REG {sorted(want.items())}"]
    )


# ---------- the deprecation list ------------------------------------------------------------------
def dp_cites(cell: str) -> list[tuple[str, int, int]]:
    """(path, first, last) for every file:line of a DP cell; a bare name follows the cell's last
    full path (else the components folder)."""
    folder, out = COMPONENTS, []
    for m in CITE_RE.finditer(cell):
        if m.group(1) == "ANN":
            path = ANN_REL
        else:
            name = m.group(2)
            if name.startswith(("apps/", "packages/")):
                path, folder = name, posixpath.dirname(name)
            else:
                path = f"{folder}/{name}"
        for a, b in SPAN_RE.findall(m.group(3)):
            out.append((path, int(a), int(b or a)))
    return out


def census() -> dict[str, int]:
    out = repo().git_ok("grep", "-n", "-E", CENSUS_ERE, BASE, "--", f"{FEATURES}*.tsx")
    counts: dict[str, int] = {}
    for line in (out or "").splitlines():
        _, path, _, text = line.split(":", 3)
        skip = (".test." in path, ".stories." in path, path == ANN_REL)
        if any(skip) or text.lstrip().startswith(("*", "/*", "//")):
            continue
        counts[path] = counts.get(path, 0) + 1
    return counts


def g_deprecate(t: L.Tree) -> list[str]:
    bad: list[str] = []
    for r in rows(t.text("spec"), "## 6."):
        for path, lo, hi in dp_cites(r[1]):
            text = repo().lines_at(BASE, path)
            if text is None or hi > len(text):
                bad.append(f"{r[0]}: {path}:{lo} does not exist")
            elif r[0] != CONFORMING and not any(
                k in text[i - 1] for i in range(lo, hi + 1) for k in DP_MARKERS
            ):
                bad.append(f"{r[0]}: {path}:{lo} holds no deprecated pattern")
    counts = census()
    lines, files = sum(counts.values()), len(counts)
    if f"{lines} lines in {files} files" not in t.text("spec"):
        bad.append(f"DP-13 does not state {lines} lines in {files} files")
    table = {plain(r[0]).strip("`"): plain(r[1]) for r in rows(t.text("handoff"), "### §F.2")}
    want = {p.removeprefix(FEATURES): str(n) for p, n in counts.items()}
    want[f"{files} files"] = str(lines)
    if table != want:
        bad.append("hand-off section F.2 differs from the census")
    return bad


# ---------- patterns, stories ---------------------------------------------------------------------
def g_patterns(t: L.Tree) -> list[str]:
    sec = L.section(t.text("spec"), "## 5.")
    table = L.table_rows(sec)
    bad: list[str] = []
    if [r[0] for r in table] != [p for p, _ in PATTERNS]:
        bad.append(f"rows are {[r[0] for r in table]}")
    for r, (pid, cmp) in zip(table, PATTERNS, strict=False):
        t2 = r[-1]
        if cmp not in r[1]:
            bad.append(f"{pid} does not name {cmp}")
        if "T2" not in t2:
            bad.append(f"{pid}'s T2 cell names no T2")
        if pid in ARIA_DISABLED_ROWS and "`aria-disabled`" not in t2:
            bad.append(f"{pid}'s T2 cell lacks `aria-disabled`")
        if any("`disabled`" in c for c in r):
            bad.append(f"{pid} uses a bare `disabled`")
        if pid in ESC_ROWS and "`Esc`" not in r[3]:
            bad.append(f"{pid}'s keyboard cell names no `Esc`")
        if not re.search(rf"^- \*\*{pid}\*\* ", sec, re.MULTILINE):
            bad.append(f"{pid} has no APG-facets bullet")
    return bad


def g_stories(t: L.Tree) -> list[str]:
    a1 = [ln for ln in t.text("handoff").split("\n") if re.match(r"^\| D10-A1 +\|", ln)]
    if not a1:
        return ["no D10-A1 row"]
    new = L.cells(a1[0])[4]
    _head, sep, rest = new.partition("five Storybook a11y stories")
    listed, sep2, _ = rest.partition("each checked by the axe addon")
    bad = [] if sep and sep2 else ["D10-A1 lacks the stories sentence"]
    bad += [f"D10-A1 lacks {s}" for s in STORIES if s not in listed]
    for need in ("zero serious or critical", "interaction test", "names the component"):
        if need not in new:
            bad.append(f"D10-A1 lacks {need!r}")
    spec71 = L.section(t.text("spec"), "### 7.1")
    bad += [f"section 7.1 lacks `{s}`" for s in STORIES if f"**`{s}`**" not in spec71]
    return bad


# ---------- hygiene, the list, the paths ----------------------------------------------------------
def g_hygiene(t: L.Tree) -> list[str]:
    named = t.named("spec", "handoff")
    return (
        L.closing_keywords(named)
        + L.whitespace_hygiene(named)
        + L.scan_public(named)
        + L.comment_findings(named)
        + L.r7_findings(named)
    )


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(t.text("spec"), "### 13.2", MUTATIONS)


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN)


GATES: tuple[L.Gate, ...] = (
    L.Gate("G-LEDGER", g_ledger),
    L.Gate("G-IDS", g_ids),
    L.Gate("G-OLD", g_old),
    L.Gate("G-FINDINGS", g_findings),
    L.Gate("G-DEPRECATE", g_deprecate),
    L.Gate("G-PATTERNS", g_patterns),
    L.Gate("G-STORIES", g_stories),
    L.Gate("G-HYGIENE", g_hygiene),
    L.Gate("G-MUTLIST", g_mutlist),
    L.Gate("G-UNTOUCHED", g_untouched),
)

_M = L.Mutation
_KEYWORD = "Clo" + "ses #1309."
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-LEDGER", "change §2.2's total from 247 to 238", "spec",
       r"(\| \*\*Total\*\* +\| )\*\*247\*\*", r"\1**238**", regex=True),
    _M("M-2", "G-IDS", "rename CMP-261 to CMP-244 in §3.3's heading", "spec",
       "### 3.3 CMP-261 `MotionVariant`", "### 3.3 CMP-244 `MotionVariant`"),
    _M("M-3", "G-OLD", "alter one character of D10-A18's Old fragment", "handoff",
       "when blur validation shows or changes the message.",
       "when blur validation shows or changes a message."),
    _M("M-4", "G-FINDINGS", "drop the A11Y-R-E09-D10-F-32 row from §10", "spec",
       r"\n\| A11Y-R-E09-D10-F-32 [^\n]*", "", regex=True),
    _M("M-5", "G-DEPRECATE", "point DP-9 at `Popover.tsx`:12", "spec",
       r"(\| DP-9 +\| )`packages/ui/src/components/Popover\.tsx`:67\u201371", r"\1`Popover.tsx`:12",
       regex=True),
    _M("M-6", "G-PATTERNS", "replace `aria-disabled` with `disabled` in P-4's T2 cell", "spec",
       r"(\| P-4 [^\n]*a T2 item )`aria-disabled`", r"\1`disabled`", regex=True),
    _M("M-7", "G-STORIES", "delete `HighContrast` from D10-A1", "handoff",
       'ReducedMotion (data-motion="reduce"), HighContrast (the high-contrast theme) and,',
       'ReducedMotion (data-motion="reduce") and,'),
    _M("M-8", "G-HYGIENE", "add a closing keyword before an issue number in §15", "spec",
       "5. **Version line.**", _KEYWORD + "\n\n5. **Version line.**"),
    _M("M-9", "G-MUTLIST", "the list drifts", "spec",
       r"\| M-1 +\| G-LEDGER", "| M-1  | G-IDS", regex=True),
    _M("M-10", "G-UNTOUCHED", "an owner document edited", "@changed", "", CAT_REL),
    _M("M-11", "G-PATTERNS", "drop `Esc` from P-5's keyboard cell", "spec",
       "| `Tab` traps; `Esc` cancels;", "| `Tab` traps; the key cancels;"),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    base = repo().diff_base(BASE)
    return L.Tree(
        files={
            "spec": (ROOT / SPEC_REL).read_text(encoding="utf-8"),
            "handoff": (ROOT / HANDOFF_REL).read_text(encoding="utf-8"),
            "catalogue": (ROOT / CAT_REL).read_text(encoding="utf-8"),
        },
        changed=repo().changed_paths(base),
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test() -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def main(argv: list[str]) -> int:
    return L.cli(argv, {"check": check, "self-test": self_test}, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
