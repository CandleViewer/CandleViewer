#!/usr/bin/env python3
"""E36-D04 accessibility design review audit: every number the review quotes, from the repo.

Offline, stdlib only beyond four repo files it IMPORTS (never re-implements) through
`importlib.util`: the two E36 lane tools `e36_d02_form_audit.py` (`PAIRS_TABLE`, `rows()`,
`load_theme()`, `resolve()`, `contrast()`) and `e36_d03_screens_audit.py` (`PAIRS_TABLE`,
`MOTION_TABLE`, `TARGETS_TABLE`, `merged()`, `hex_of()`, `contrast()`, `motion()`, `targets()`,
`px_of()`, `fmt()`) - both guard `main()` under `__main__` and their only top-level call is D02's
`RECORDED_INPUTS = frozenset(...)`, so importing them runs nothing - `scripts/keymap_lint.py`
(`normalise`, `expand`, `lint_keymap`, `check_coverage`, `parse_catalogue`, `RESERVED`), which reads
`apps/web/src/keymap/reserved-keys.json` at import and nothing else, and E11-D07's
`e11_d07_a11y_review_audit.py` (merged as MERGE_E11_D07; BQ-6 RULED: import, never copy or
re-implement) for the key-map classes it owns - `nrm()`, `expand_keys()`, `shipped_bindings()`,
`load_reserved()` (the reserved file plus the `05` section 3.3 item 4 four), `parse_05_hotkeys()` /
`hotkey_05_keys()`, `coactive()`, `ALWAYS`, `SR_LIVE_MODES` - and its `load_fixture()` over
`e11_d07_sr_reserved_keys.json` (the screen-reader rows). Importing that tool runs its module-level
setup: it loads the token verifier, the contrast and CVD helpers, the five E11 sibling tools and
`keymap_lint.py` and resolves the three themes from `packages/ui/tokens` - repo files only. It
executes no other repo code and makes no network call. It prints, with a source label on every row:
(1) the `05` clause inventory against the review's verdict table; (2) the key-map matrix - the
shipped registry x `05` section 3.2 x the design bindings of E36-D02 sections 7 / 10 / 12 and
E36-D03 sections 6 / 13 x the reserved keys x the E11-D07 screen-reader fixture (imported; the
review quotes the subset whose normal form is one of the editor's keys) - with the conflict classes
in E11-D07's vocabulary (same-context, shadow of Global / Workspace, disjoint-context reuse,
reserved, the `Alt+<letter>` family), `lint_keymap()` on the shipped file, the `check_coverage()`
coupling and the eight-chord divergence table; (3) the union of the two specs' pair tables
re-measured with each
sibling's own ratio, plus the D04-only rows (the validity composite reported, not gated); (4) the
hit-target table from the size tokens; (5) the 200 % statement scan; (6) the motion rows; (7) the
review's T2 walk, SR script, naming, dialog and acceptance tables - every AL row cites a hand-off
section B scenario by a line that starts one (`Scenario:`), or carries the review-only marker; (8)
the string gates; (9) the counts.
`--json` prints one object (the board script's CONST and the check-nums consume it); `--check
<review> [--draft <file>]` re-derives every `<!-- audit:NAME=VALUE -->` marker and exits 1 on drift.

Usage: python3 -I docs/design/_tools/e36_d04_a11y_review_audit.py [--json]
       [--check REVIEW [--draft FILE]]
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOOLS, PLAN = ROOT / "docs" / "design" / "_tools", ROOT / "docs" / "plan"
E36 = ROOT / "docs" / "design" / "E36"
REVIEW, D02, D03 = E36 / "E36-D04.md", E36 / "E36-D02.md", E36 / "E36-D03.md"
H02, H03 = E36 / "E36-D02-handoff.md", E36 / "E36-D03-handoff.md"
STD05, CAT14 = PLAN / "05-accessibility-standard.md", PLAN / "14-screens-catalogue.md"
KEYMAP = ROOT / "apps" / "web" / "src" / "keymap" / "keymap.json"
MERGE_D02 = "787e574fca4e21ec460f240dc22d5f0f477ee4db"
MERGE_D03 = "6c2446be25a90126dc4f6a7756642b62c5307e8f"
MERGE_E11_D07 = "de9a67609f887a82405abf45ef3286c963842d15"
DEBOUNCE_MS, COALESCE_MS, AMBIENT_S, STD_CADENCE_S = 300, 250, 5, 2
VERDICTS = ("compliant", "at risk", "non-compliant", "out of scope", "not yet decidable")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
F_CLASSES = [
    "keyboard",
    "hotkey",
    "focus",
    "announcement",
    "naming",
    "aria",
    "t2",
    "validity",
    "colour",
    "contrast",
    "target",
    "zoom",
    "motion",
    "table",
    "tree",
    "import",
    "equal-status",
    "perf",
]
MECHANISMS = ("focus", "status", "alert", "log", "alertdialog", "name", "none")
POLITENESS = ("polite", "assertive", "none")
T2_KINDS = (
    "role",
    "grant",
    "env",
    "session",
    "state",
    "validity",
    "loading",
    "status",
    "outcome",
    "absence",
    "T1",
)
LOOKS = ("T2", "validity", "loading", "status", "outcome", "absence", "T1")
VERIFIER = re.compile(r"^(axe:|e2e:|sr:|measure:)")
# R1: the `05` clauses the verdict table carries, one row each (ids are the review's).
CLAUSES = [
    "3.1.1",
    "3.1.2",
    "3.1.3",
    "3.1.4",
    "3.1.6",
    "3.3.1",
    "3.3.4",
    "3.4.1",
    "3.4.2",
    "3.4.3",
    "3.4.4",
    "3.4.5",
    "3.4.6",
    "3.4.7",
    "3.4.8",
    "3.4.9",
    "3.4.10",
    "4.0",
    "4.1",
    "4.1.d",
    "4.2",
    "4.4",
    "5.1",
    "5.2",
    "5.7",
    "6.2.a",
    "6.2.b",
    "6.2.c",
    "6.2.d",
    "6.3.sort",
    "6.3.filter",
    "6.3.live",
    "6.5",
    "7.1",
    "7.2",
    "7.3",
    "7.4",
    "8.2",
    "10",
    "11.2",
    "11.5",
    "11.6",
    "11.7",
]
# The design bindings: key | screen | stop | action | registry id the design means, or - | source.
# A line indented by two spaces continues the record above it (no physical line passes 100).
DESIGN = """
Tab | SCR-081 | the page / the row list | enter or leave the row list, one stop | - | D02 §12:221
Shift+Tab | SCR-081 | the page / the row list | leave the row list backwards | - | D02 §12:221
↑ | SCR-081 | the rows | move between rows, into and out of an any-of group | - | D02 §12:222
↓ | SCR-081 | the rows | move between rows | - | D02 §12:222
← | SCR-081 | a row's controls | metric → operator → value → menu | - | D02 §12:223
→ | SCR-081 | a row's controls | the next control; the chip inside an option | -
  | D02 §12:223, §7:154
Shift+F10 | SCR-081 | a row | open the row menu (Move up · Move down · Duplicate · Remove) | -
  | D02 §12:224
Enter | SCR-081 | a control | activate; select in CMP-157; preview a card | - | D02 §12:225
Space | SCR-081 | a control | activate | - | D02 §12:225
Esc | SCR-081 | the innermost thing | cancel the picker, the menu, the dialog | - | D02 §12:226
Ctrl+S | SCR-081 | the editor | Save draft | rules.save_draft | D02 §12:229
Ctrl+Enter | SCR-081 | the editor | Save draft (the commit chord) | rules.save_draft | D02 §12:230
Alt+G | SCR-081 | the editor | switch editor (CMP-235) | rules.graph_mode | D02 §12:231
Alt+Shift+↑ | SCR-081 | a row | move the row up (the menu path is primary) | - | D02 §12:232
Alt+Shift+↓ | SCR-081 | a row | move the row down | - | D02 §12:232
Home | SCR-081 | CMP-157 | the first option | - | D02 §7:154
End | SCR-081 | CMP-157 | the last option | - | D02 §7:154
A..Z | SCR-081 | CMP-157 | type to filter | - | D02 §7:154
↑ | SCR-083 | the card grid | roving cards | - | D02 §10:192
↓ | SCR-083 | the card grid | roving cards | - | D02 §10:192
← | SCR-083 | the card grid | roving cards | - | D02 §10:192
→ | SCR-083 | the card grid | roving cards | - | D02 §10:192
Enter | SCR-083 | a card | preview | - | D02 §10:192
Esc | SCR-083 | the dialog | close | - | D02 §10:192
Tab | SCR-080 | the page / the table | enter or leave the table, the bulk bar | - | D03 §13:269
Shift+Tab | SCR-080 | the page / the table | leave backwards | - | D03 §13:269
↑ | SCR-080 | the rows | move between rows | - | D03 §13:270
↓ | SCR-080 | the rows | move between rows | - | D03 §13:270
← | SCR-080 | a row's cells | move between cells and controls | - | D03 §13:271
→ | SCR-080 | a row's cells | move between cells and controls | - | D03 §13:271
Enter | SCR-080 | a row / a header | open the rule; sort; a menu item | - | D03 §13:272
Space | SCR-080 | a row | toggle the selection; a button | - | D03 §13:273
Shift+F10 | SCR-080 | a row | open the row menu (nine items) | - | D03 §13:274
Esc | SCR-080 | the innermost thing | close the menu, the dialog, the drawer | - | D03 §13:275
Tab | SCR-088 | the drawer | the close button → the segments → the content | - | D03 §13:265
← | SCR-088 | the tree | collapse | - | D03 §13:271
→ | SCR-088 | the tree | expand | - | D03 §13:271
↑ | SCR-088 | the tree | the previous item | - | D03 §13:270
↓ | SCR-088 | the tree | the next item | - | D03 §13:270
Home | SCR-088 | the tree | the first item | - | D03 §13:276
End | SCR-088 | the tree | the last item | - | D03 §13:276
A..Z | SCR-088 | the tree | type-ahead | - | D03 §13:276
* | SCR-088 | the tree | expand all | - | D03 §13:276
Esc | SCR-088 | the drawer | close; focus returns to the opener | - | D03 §13:275
Ctrl+C | SCR-088 | the pre | native copy of the selection | - | D03 §13:281
Tab | SCR-089 | the dialog | the tabs → the selection or drop zone → the table → the buttons
  | - | D03 §13:265
Enter | SCR-089 | the drop zone | open the file picker | - | D03 §13:272
↑ | SCR-089 | the pre-check table | the previous row | - | D03 §13:270
↓ | SCR-089 | the pre-check table | the next row | - | D03 §13:270
Esc | SCR-089 | the dialog | close | - | D03 §13:275
"""
# The eight chords of the divergence table (R16) with D02's position as merged (BQ-5 RULED).
CHORDS = """
Ctrl+S | Save draft — candidate; E36-D04 reviews (D02 §12:229)
Ctrl+Enter | Save draft, the commit chord (memo C8); candidate (D02 §12:230)
Alt+G | switch editor (CMP-235); candidate (D02 §12:231)
Alt+↑/↓ | dropped — reorder through the row menu (D02 §12:233)
Ctrl+D | dropped — duplicate through the row menu (D02 §12:233)
Alt+Shift+↑/↓ | memo G10 candidate for the E49 keymap owner (D02 §12:232)
Ctrl+A | not bound on SCR-080 — the header checkbox selects all (D03 §13:277)
Del | not bound on SCR-080 — Delete is a menu item with a confirm (D03 §13:279)
"""
# The screen-reader rows are E11-D07's fixture `docs/design/_tools/e11_d07_sr_reserved_keys.json`
# (NVDA / JAWS / VoiceOver, pinned from vendor documentation), read through E11-D07's own
# `load_fixture()` - nothing typed, nothing copied (BQ-6 RULED; E11-D07 merged as MERGE_E11_D07).
# The review quotes the subset whose `norm` is in the editor's key set (the design keys, the native
# composite keys and the thirteen chords); the chord-hit test runs over every fixture row.
# D04-only pairs (Safety 9): label | fg | bg | role | bar  (gated at the bar; "report" = not gated)
D04_PAIRS = """
the reason text beside a validity-disabled control | color.text.secondary | color.surface.raised
  | text | 4.5
the reason text beside a validity-disabled control, on canvas | color.text.secondary
  | color.surface.canvas | text | 4.5
the T2 label (lock + full label) | color.text.tertiary | color.surface.raised | text | 4.5
the T2 label on the row menu | color.text.tertiary | color.surface.overlay | text | 4.5
the T2 reason on the row menu | color.text.secondary | color.surface.overlay | text | 4.5
the lock glyph (non-text) | color.text.tertiary | color.surface.raised | non-text | 3.0
the invalid row's outline | color.status.danger.default | color.surface.canvas | non-text | 3.0
the invalid row's outline on a card | color.status.danger.default | color.surface.raised
  | non-text | 3.0
focus ring on canvas | color.focus.ring | color.surface.canvas | non-text | 3.0
focus ring on raised | color.focus.ring | color.surface.raised | non-text | 3.0
focus ring on hover | color.focus.ring | color.surface.hover | non-text | 3.0
focus ring on selected | color.focus.ring | color.surface.selected | non-text | 3.0
focus ring on overlay | color.focus.ring | color.surface.overlay | non-text | 3.0
focus ring on sunken | color.focus.ring | color.surface.sunken | non-text | 3.0
focus ring on success.subtle | color.focus.ring | color.status.success.subtle | non-text | 3.0
focus ring on warning.subtle | color.focus.ring | color.status.warning.subtle | non-text | 3.0
focus ring on danger.subtle | color.focus.ring | color.status.danger.subtle | non-text | 3.0
focus ring on info.subtle | color.focus.ring | color.status.info.subtle | non-text | 3.0
focus ring on the primary button | color.focus.ring | color.action.primary.default | non-text
  | report
"""
# The target table (Safety 8): surface | token or typed px | density
TARGETS = """
CMP-140 ordinal cell "Condition N of M" (a label inside the 24 px row) | size.control.compact
  | compact
CMP-157 trigger button | size.control.compact | compact
CMP-227 chip in a row (20 px pill + 2 px padding) | pill20 | compact
operator select (CMP-009) | size.control.compact | compact
value field (CMP-008) | size.control.compact | compact
row-menu button (CMP-002) | size.control.compact | compact
+ condition / + any-of group / + action | size.control.compact | compact
CMP-233 fields | size.control.compact | compact
action bar: Validate · Simulate · Save draft · Arm… | size.control.compact | compact
the action bar strip (not a target) | typed:48 | compact
the round-trip indicator chip | size.control.compact | compact
CMP-235 segments | size.control.compact | compact
SCR-083 filter chips | size.control.compact | compact
SCR-083 cards (roving items) | size.row.compact | compact
SCR-083 Create draft | size.control.compact | compact
every control above, comfortable | size.control.comfortable | comfortable
"""
# The 200 % statement scan (R8d): surface | file | section anchor | end anchor
ZOOM = """
SCR-081 at 200 % | D02 | ## 11. | ## 12.
SCR-083's dialog at 200 % | D02 | ## 11. | ## 12.
the mismatch recovery dialog at 200 % | D02 | ## 4. | ## 5.
the typed Arm confirm (SCR-085, E35-D02's) | D02 | ## 9. | ## 10.
SCR-080 at 200 % | D03 | ## 4. | ## 5.
SCR-088's docked drawer at 200 % | D03 | ## 5. | ## 6.
SCR-089's dialog at 200 % | D03 | ## 7. | ## 8.
the bulk-disarm dialog at 200 % | D03 | ## 3. | ## 4.
the delete confirm at 200 % | D03 | ## 2. | ## 3.
"""
ZOOM_RE = re.compile(r"200 ?%|stacked cards|reflow|fills the viewport|narrow mode|overlay fallback")
TEXT_SCALE_RE = re.compile(r"text[ -]scale", re.IGNORECASE)
FABRICATED = (
    r"\b(NVDA|JAWS|VoiceOver)\b.{0,40}\b(read|reads|said|announced|spoke|speaks|heard)\b",
    r"\bparticipant",
    r"\bsession (was )?run\b",
    r"we observed",
    r"the user said",
)
# Hygiene: generic patterns only - no personal word, no notes-folder name, no hostname (whole or
# split); the path literal is split so this file never contains the string it forbids. The host
# pattern skips the plugin API's own identifiers (`penpot.fonts.*`, `penpot.current*`).
HYGIENE = (
    r"/(?:ho[m]e|Users)/[^/\s]+/",
    r"penpot\.(?!fonts\b|current)[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
    r"#/workspa[c]e",
    r"page[L]ink",
)
CLOSING = re.compile(
    r"\b(clos(?:e|es|ed)|fix(?:es|ed)?|resolv(?:e|es|ed))\b\s*:?\s*#\d+", re.IGNORECASE
)
DRAFT_WORDS = re.compile(r"\b(closes|fixes|resolves|resolved)\b", re.IGNORECASE)


def load(name: str, path: Path) -> ModuleType:
    """Import a repo module by path; the three modules run nothing at import (docstring)."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The four imports are typed Any at the boundary: the siblings ship no stubs (one-line reason).
d02: Any = load("e36_d02_form_audit", TOOLS / "e36_d02_form_audit.py")
d03: Any = load("e36_d03_screens_audit", TOOLS / "e36_d03_screens_audit.py")
kl: Any = load("keymap_lint", ROOT / "scripts" / "keymap_lint.py")
e11: Any = load("e11_d07_a11y_review_audit", TOOLS / "e11_d07_a11y_review_audit.py")
Row = list[str]


def rows(table: str) -> list[Row]:
    """One record per line; a line indented by two spaces continues the record above it."""
    recs: list[str] = []
    for ln in table.strip("\n").splitlines():
        if ln.startswith("  ") and recs:
            recs[-1] += " " + ln.strip()
        elif ln:
            recs.append(ln)
    return [[c.strip() for c in r.split(" | ")] for r in recs]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def b_scenarios(path: Path) -> dict[int, str]:
    """The `Scenario:` lines of a hand-off's section B (`05` section 10 block), by 1-based line."""
    out: dict[int, str] = {}
    in_b = False
    for i, ln in enumerate(read(path).splitlines(), 1):
        if ln.startswith("## "):
            in_b = ln.startswith("## B.")
        m = re.match(r"^\s+Scenario: (.+)$", ln)
        if in_b and m:
            out[i] = m.group(1).strip()
    return out


B_REF = re.compile(r"§B :(\d+)")
B_HANDOFF = re.compile(r"\b(D0[23])-handoff\b")
REVIEW_ONLY = "no §B scenario — review-only"


def section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i : j if j > 0 else len(text)]


def cells(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]


def table_rows(text: str, prefix: str) -> list[list[str]]:
    return [cells(ln) for ln in text.splitlines() if re.match(rf"^\| {prefix}", ln)]


def fmt(r: float) -> str:
    return str(d03.fmt(r))


# ------------------------------------------------------------------------- 1. clauses (R1 / R2)
def clause_inventory(std: str) -> dict[str, int]:
    """Count the numbered items of the `05` sections R1 draws on (printed beside R1's ids)."""
    out: dict[str, int] = {}
    for key, start, end in (
        ("c31", "### 3.1", "### 3.2"),
        ("c33", "### 3.3", "### 3.4"),
        ("c34", "### 3.4", "## 4."),
        ("c4", "## 4.", "## 5."),
        ("c5", "## 5.", "## 6."),
        ("c7", "## 7.", "## 8."),
    ):
        out[key] = len(re.findall(r"^\d+\. ", section(std, start, end), re.MULTILINE))
    sec62 = section(std, "### 6.2", "### 6.3")
    out["c62"] = len(
        re.findall(r"^  - `aria-live|^  - A user-facing|^- \*\*Region", sec62, re.MULTILINE)
    )
    return out


def verdict_word(cell: str) -> str:
    for v in VERDICTS:
        if cell.startswith(v):
            return "routed" if v == "not yet decidable" else v
    return "?"


# ------------------------------------------------------------------------- 2. key map (R4)
def norm(key: str) -> str:
    """E11-D07's `nrm()`: `keymap_lint.normalise()` where it applies, its canonical form for the
    keys the repo normaliser leaves out on purpose (Home / End / PageUp / PageDown, `*`)."""
    return str(e11.nrm(key))


def map05_rows() -> list[tuple[str, str, list[str]]]:
    """(category, action, atomic keys) per row of `05` section 3.2 - E11-D07's parser
    (`parse_05_hotkeys()` reads the file; `hotkey_05_keys()` normalises and expands the ranges)."""
    return [
        (str(r["category"]), str(r["action"]), [str(k) for k in e11.hotkey_05_keys(r)])
        for r in e11.parse_05_hotkeys()
    ]


def _chord_row(
    key: str,
    pos: str,
    by_bind: dict[str, list[dict[str, Any]]],
    screens: dict[str, set[str]],
    map05: list[tuple[str, str, list[str]]],
    sr_hits: dict[str, int],
    reserved_all: dict[str, str],
) -> dict[str, Any]:
    atoms = [norm(key.replace("↑/↓", a)) for a in ("↑", "↓")] if "↑/↓" in key else [norm(key)]
    regs = sorted(
        {
            f"{c['id']} ({c['context']}"
            + (", screens " + "/".join(c["screens"]) if c.get("screens") else "")
            + ")"
            for a in atoms
            for c in by_bind.get(a, [])
        }
    )
    r05 = sorted({f"{cat.strip()} — {act}" for cat, act, ks in map05 for a in atoms if a in ks})
    res = sorted({reserved_all[a] for a in atoms if a in reserved_all})
    return {
        "chord": key,
        "in_14": any(a in screens.get("SCR-081", set()) for a in atoms),
        "d02": pos,
        "registry": regs or ["—"],
        "map05": r05 or ["—"],
        "reserved": res or ["—"],
        "sr_rows": sum(sr_hits.get(a, 0) for a in atoms),
    }


def keymap_matrix(cat14: str) -> dict[str, Any]:
    km = json.loads(read(KEYMAP))
    cmds = km["commands"]
    by_id = {c["id"]: c for c in cmds}
    rules = [c for c in cmds if c["context"] == "Rules"]
    # E11-D07's expansion of the shipped registry: one row per atomic binding, ranges included
    by_bind: dict[str, list[dict[str, Any]]] = {}
    for s in e11.shipped_bindings(km):
        by_bind.setdefault(str(s["key"]), []).append(by_id[s["id"]])
    reserved_all: dict[str, str] = {
        str(k): str(v) for k, v in e11.load_reserved().items()
    }  # the file + the `05` four
    design = rows(DESIGN)
    dkeys = {norm(r[0]) for r in design if r[0] != "A..Z"} | set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    native = set(kl.NAMED_KEYS) | {"Shift+Tab", "Home", "End", "*", "PageUp", "PageDown"}
    chords = [
        norm(k)
        for k in [
            "Ctrl+S",
            "Ctrl+Enter",
            "Alt+G",
            "Alt+↑",
            "Alt+↓",
            "Ctrl+D",
            "Alt+Shift+↑",
            "Alt+Shift+↓",
            "Shift+F10",
            "Ctrl+A",
            "F2",
            "Del",
            "Ctrl+C",
        ]
    ]
    # the screen-reader rows: E11-D07's fixture through its loader; the editor subset is quoted
    fixture = e11.load_fixture()
    sr_all: list[dict[str, Any]] = list(fixture["keys"])
    editor_keys = dkeys | native | set(chords)
    sr = [r for r in sr_all if str(r["norm"]) in editor_keys]
    sr_hits = {k: sum(str(r["norm"]) == k for r in sr_all) for k in chords}
    sr_by_mode: dict[str, int] = {}
    for r in sr:
        if r["norm"] in dkeys:
            sr_by_mode[str(r["mode"])] = sr_by_mode.get(str(r["mode"]), 0) + 1
    sr_live = sum(1 for r in sr if r["mode"] in e11.SR_LIVE_MODES)
    map05 = map05_rows()
    rule05 = [m for m in map05 if "Rule builder" in m[0]]
    same: list[str] = []
    reuse: list[str] = []
    shadow_ws: list[str] = []
    reserved: list[str] = []
    alt_family: list[str] = []
    unregistered: list[str] = []
    for key, _screen, _stop, _action, expects, _src in design:
        if key == "A..Z":
            continue
        n = norm(key)
        for c in by_bind.get(n, []):
            tag = f"{n} · {c['id']}"
            is_same = expects != c["id"] and (expects != "-" or n in native)
            # E11-D07's classes: same-context (the Rules context holds the key for another
            # action), shadow-global (an always-live Global / Workspace binding), reuse (a
            # context never co-active with Rules); the bare composite keys are APG, not bindings
            if c["context"] == "Rules" and is_same and tag not in same:
                same.append(tag)
            elif c["context"] in e11.ALWAYS and tag not in shadow_ws:
                shadow_ws.append(tag)
            elif (
                c["context"] != "Rules"
                and not e11.coactive("Rules", c["context"])
                and n not in native
            ):
                reuse += [f"{tag} ({c['context']})"] * (f"{tag} ({c['context']})" not in reuse)
        if n in reserved_all and f"{n} · {reserved_all[n]}" not in reserved:
            reserved.append(f"{n} · {reserved_all[n]}")
        if re.fullmatch(r"Alt\+[A-Z]", n) and n not in alt_family:
            alt_family.append(n)
        if n not in native and n not in by_bind and "+" in n and n not in unregistered:
            unregistered.append(n)
    dnorm = {norm(r[0]) for r in design}
    reg_unspec = [
        c["id"]
        for c in rules
        if c["id"] != "rules.delete"
        and not any(b in dnorm for b in e11.expand_keys(c["defaultBinding"]))
    ]
    unscoped = [c["id"] for c in rules if not c.get("screens")]
    # a `05` row whose key is unregistered in its own context but bound in Rules to another action
    ctx_of = {
        "Chart": "Chart",
        "Drawing": "Chart",
        "Trading": "Ticket",
        "DOM Ladder": "DOM",
        "Replay": "Replay",
        "Global / Navigation": "Global",
        "Rule builder (node graph)": "Rules",
        "Accessibility": "Settings",
    }
    contradicted: list[str] = []
    for cat, a, ks in map05:
        own = ctx_of.get(cat.strip(), "")
        for b in ks:
            hits = by_bind.get(b, [])
            if b in native or own == "Rules" or any(c["context"] == own for c in hits):
                continue
            contradicted += [
                f"{b} · {cat.strip()} {a} → {c['id']}" for c in hits if c["context"] == "Rules"
            ]
    rule05_rows = []
    for _c, a, ks in rule05:
        bound = [
            f"{k} → {c['id']}" for k in ks for c in by_bind.get(k, []) if c["context"] == "Rules"
        ]
        res = [reserved_all[k] for k in ks if k in reserved_all]
        rule05_rows.append(
            f"{a}: {' '.join(ks)} — {'; '.join(bound) if bound else 'unregistered'}"
            + (f"; reserved ({', '.join(res)})" if res else "")
        )
    screens, _groups, perr = kl.parse_catalogue(cat14)
    cov = kl.check_coverage(km, cat14)
    marker = "`Ctrl+S` save draft; `Ctrl+Enter` validate"
    line_1764 = next((ln for ln in cat14.splitlines() if marker in ln), "")
    a01 = (
        "- **Interactions/hotkeys:** `Ctrl+S` / `Ctrl+Enter` save draft (the commit chord); "
        "`Alt+G` switch to graph; reorder, duplicate and remove through the row menu (Shift+F10); "
        "Alt+Shift+↑/↓ reorder — a candidate, pending the keymap owner."
    )
    cov_a01 = kl.check_coverage(km, cat14.replace(line_1764, a01)) if line_1764 else ["no :1764"]
    a01_bad = a01.replace("(Shift+F10)", "(`Shift+F10`)")
    cov_bad = kl.check_coverage(km, cat14.replace(line_1764, a01_bad)) if line_1764 else []
    chord_rows = [
        _chord_row(k, p, by_bind, screens, map05, sr_hits, reserved_all) for k, p in rows(CHORDS)
    ]
    return {
        "commands": len(cmds),
        "rules_commands": len(rules),
        "atomic_bindings": sum(len(v) for v in by_bind.values()),
        "reserved_combos": len(json.loads(read(KEYMAP.with_name("reserved-keys.json")))),
        "reserved_atomic": len(e11.load_reserved_file_keys()),
        "reserved_with_05_four": len(reserved_all),
        "lint_errors": len(kl.lint_keymap(km)),
        "coverage_errors": len(cov) + len(perr),
        "coverage_errors_a01": len(cov_a01),
        "coverage_errors_a01_backticked": len(cov_bad),
        "map05_rows": len(map05),
        "map05_rule_builder_rows": len(rule05),
        "rule05": rule05_rows,
        "contradicted_05": contradicted,
        "design_rows": len(design),
        "design_keys": len(dkeys),
        "same_context": same,
        "disjoint_reuse": reuse,
        "shadow_workspace": shadow_ws,
        "reserved_design": reserved,
        "alt_family": alt_family,
        "specified_unregistered": unregistered,
        "registered_unspecified": reg_unspec,
        "unscoped_rules_rows": unscoped,
        "sr_fixture_rows": len(sr_all),
        "sr_fixture_sources": len(fixture["sources"]),
        "sr_fixture_by_reader": {
            who: sum(1 for r in sr_all if r["sr"] == who) for who in ("nvda", "jaws", "voiceover")
        },
        "sr_subset_rows": len(sr),
        "sr_subset_live_mode_rows": sr_live,
        "sr_chord_hits": sum(sr_hits.values()),
        "sr_chord_hits_by_key": sr_hits,
        "sr_rows_by_mode": sr_by_mode,
        "sr_letter_rows": sum(len(str(r["norm"])) == 1 and str(r["norm"]).isalpha() for r in sr),
        "sr_letter_rows_by_reader": {
            who: sum(
                1
                for r in sr
                if r["sr"] == who and len(str(r["norm"])) == 1 and str(r["norm"]).isalpha()
            )
            for who in ("nvda", "jaws", "voiceover")
        },
        "chords": chord_rows,
    }


# ------------------------------------------------------------------------- 3. the matrices (R8)
def blend(fg: str, bg: str, a: float) -> str:
    f = [int(fg[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a * x + (1 - a) * y):02X}" for x, y in zip(f, b, strict=True))


def luma601(h: str) -> int:
    r, g, b = (int(h[i : i + 2], 16) for i in (1, 3, 5))
    return int(0.299 * r + 0.587 * g + 0.114 * b)


GREY_TOKENS = [
    "color.status.success.subtle",
    "color.status.warning.subtle",
    "color.status.danger.subtle",
    "color.surface.hover",
    "color.status.success.strong",
    "color.status.warning.strong",
    "color.status.danger.strong",
    "color.status.info.strong",
    "color.status.info.subtle",
    "color.status.info.default",
    "color.env.demo",
    "color.env.live",
    "color.buy.default",
    "color.sell.default",
    "color.surface.raised",
    "color.surface.canvas",
    "color.action.primary.default",
    "color.status.danger.default",
    "color.text.tertiary",
    "color.text.secondary",
    "color.text.primary",
]
MORE_TOKENS = [
    "color.surface.overlay",
    "color.surface.selected",
    "color.surface.app",
    "color.surface.sunken",
    "color.text.on-action",
    "color.text.disabled",
    "color.border.default",
    "color.border.selected",
    "color.focus.ring",
]


def matrices() -> dict[str, Any]:
    th02 = {k: d02.load_theme(k) for k in d02.THEMES}
    th03 = {k: d03.merged(v) for k, v in d03.THEMES.items()}
    out: dict[str, Any] = {"d02": {}, "d03": {}, "fail": [], "agree": True}
    bars = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}
    for name, table, tool in (("d02", d02.PAIRS_TABLE, d02), ("d03", d03.PAIRS_TABLE, d03)):
        gated = fails = 0
        per_theme = dict.fromkeys(th03, 0)
        for rec in tool.rows(table):
            fg, bg, role = rec[1], rec[2], rec[3]
            bar = bars.get(role)
            if bar is None:
                continue
            gated += 1
            for t, tok in th03.items():
                if name == "d02":
                    r = float(tool.contrast(tool.resolve(th02[t], fg), tool.resolve(th02[t], bg)))
                else:
                    r = float(tool.contrast(tool.hex_of(fg, tok), tool.hex_of(bg, tok)))
                if role == "hc-text" and t != "high-contrast":
                    continue
                if r < bar:
                    fails += 1
                    per_theme[t] += 1
                    out["fail"].append(f"{name}: {fg} on {bg} ({t}) {fmt(r)} < {bar}")
                h2 = float(d02.contrast(d02.resolve(th02[t], fg), d02.resolve(th02[t], bg)))
                if abs(h2 - r) >= 0.005:
                    out["agree"] = False
        out[name] = {"gated": gated, "fail": fails, "fail_per_theme": per_theme}
    d04 = []
    for label, fg, bg, role, bar_s in rows(D04_PAIRS):
        rat = {
            t: float(d03.contrast(d03.hex_of(fg, tok), d03.hex_of(bg, tok)))
            for t, tok in th03.items()
        }
        b = None if bar_s == "report" else float(bar_s)
        verdict = (
            "reported" if b is None else ("PASS" if all(v >= b for v in rat.values()) else "FAIL")
        )
        row = {"label": label, "fg": fg, "bg": bg, "role": role, "bar": bar_s, "verdict": verdict}
        d04.append(row | {t: round(v, 2) for t, v in rat.items()})
    alpha = float(d03.resolve(th03["dark"]["opacity.disabled"]["$value"], th03["dark"]))
    comp = []
    for host in ("color.surface.raised", "color.surface.canvas"):
        crow: dict[str, Any] = {"host": host, "alpha": alpha}
        for t, tok in th03.items():
            fill = blend(
                d03.hex_of("color.action.primary.default", tok), d03.hex_of(host, tok), alpha
            )
            label = blend(d03.hex_of("color.text.on-action", tok), d03.hex_of(host, tok), alpha)
            crow[t] = round(float(d03.contrast(label, fill)), 2)
        comp.append(crow)
    grey = {n: {t: luma601(d03.hex_of(n, tok)) for t, tok in th03.items()} for n in GREY_TOKENS}
    palette = {
        t: {n: d03.hex_of(n, tok) for n in GREY_TOKENS + MORE_TOKENS} for t, tok in th03.items()
    }
    slug = {r["label"]: re.sub(r"[^a-z0-9]+", "_", str(r["label"]).lower()).strip("_") for r in d04}
    out["d04_ratios"] = {slug[r["label"]]: {t: r[t] for t in th03} for r in d04}
    out["composite"] = {
        f"{str(v['host']).rsplit('.', 1)[-1]}_{t}": v[t] for v in comp for t in th03
    }
    out |= {
        "d04": d04,
        "d04_fail": sum(r["verdict"] == "FAIL" for r in d04),
        "d04_rows": len(d04),
        "validity_composite": comp,
        "opacity_disabled": alpha,
        "greyscale": grey,
        "palette": palette,
    }
    return out


# ------------------------------------------------------------------- 4-6. targets, zoom, motion
def target_table() -> dict[str, Any]:
    prim = d03.merged(("primitives",))
    minimum = int(d03.px_of("size.target.min", prim))
    table, typed, under = [], [], []
    for surface, src, density in rows(TARGETS):
        if src.startswith("typed:"):
            px, label = int(src[6:]), f"typed: {src[6:]} px — no token"
            typed.append(surface)
        else:
            px, label = int(d03.px_of(src, prim)), src
        ok = px >= minimum or "not a target" in surface
        if not ok:
            under.append(surface)
        table.append([surface, label, f"{px} px", density, "PASS" if ok else "FAIL"])
    d03_table, d03_problems = d03.targets(prim)
    return {
        "minimum": minimum,
        "rows": table,
        "typed_no_token": typed,
        "under": under,
        "d03_rows": len(d03_table),
        "d03_problems": d03_problems,
        "pill20": int(d03.px_of("pill20", prim)),
    }


def zoom_table() -> dict[str, Any]:
    """Per surface: the 200 % statement and, beside it, the in-app text-scale statement (`05`
    section 5 item 7 names both; `16`'s `data-text-scale` 100 / 112 / 125 / 150)."""
    texts = {"D02": read(D02), "D03": read(D03)}
    out = []
    for surface, doc, start, end in rows(ZOOM):
        sec = section(texts[doc], start, end)
        hits = sorted({m.group(0) for m in ZOOM_RE.finditer(sec)})
        cited = "E35-D02" in surface
        state = "cited — E35-D02" if cited else ("stated" if hits else "silent")
        ts = "cited — E35-D02" if cited else ("stated" if TEXT_SCALE_RE.search(sec) else "silent")
        out.append(
            {
                "surface": surface,
                "doc": doc,
                "section": start.strip("# ."),
                "state": state,
                "hits": hits,
                "text_scale": ts,
            }
        )
    return {
        "rows": out,
        "stated": sum(r["state"] == "stated" for r in out),
        "silent": sum(r["state"] == "silent" for r in out),
        "cited": sum(str(r["state"]).startswith("cited") for r in out),
        "text_scale_stated": sum(r["text_scale"] == "stated" for r in out),
        "text_scale_silent": sum(r["text_scale"] == "silent" for r in out),
        "text_scale_cited": sum(str(r["text_scale"]).startswith("cited") for r in out),
    }


def motion_table() -> dict[str, Any]:
    dark = d03.merged(d03.THEMES["dark"])
    table, problems, rates = d03.motion(dark)
    reduce_kinds: dict[str, int] = {}
    for r in table:
        reduce_kinds[str(r[4])] = reduce_kinds.get(str(r[4]), 0) + 1
    t4 = section(read(H02), "### Table 4", "### Table 5")
    t4_rows = [
        ln
        for ln in t4.splitlines()
        if ln.startswith("| ") and not ln.startswith(("| Comp", "| ---"))
    ]
    return {
        "rows": len(table),
        "problems": problems,
        "rates": rates,
        "reduce_variants": reduce_kinds,
        "d02_table4_rows": len(t4_rows),
        "d02_nothing_animates": "none animated" in t4,
        "info_rows_without_carrier": [str(r[0]) for r in table if not r[5]],
    }


# --------------------------------------------------------------------- 7. the review's tables
def _t2_check(r: list[str]) -> tuple[str, str]:
    """Return (kind, problem) for one T2 row; the problem names an over- or under-conversion.

    A row whose verdict starts "divergence" quotes the upstream spec's own drawing (D03 drawing a
    validity, loading or deferred state as T2) and classifies it here; the quote is not the
    review's conversion, so the lock / CMP-079 words in its cell are accepted - but the row must
    name a C-row, and the look stays the review's classification."""
    kind, items, key, look = r[4], r[5].lower(), r[6], r[7]
    if kind not in T2_KINDS or look not in LOOKS:
        return kind, f"{r[0]}: kind {kind!r} / look {look!r}"
    gate = kind in ("role", "grant", "env", "session", "state")
    keyed = re.search(r"rbac\.|rule\.|PROPOSED|engine\.|the one notice|the banner", key)
    has_lock = re.search(r"six items|lock glyph|(?<!no )(?<!never a )\block\b", items)
    dimmed = "opacity.disabled" in items or "text.disabled" in items
    drawn_lock = re.search(r"(?<!no )(?<!never a )(?<!not )\block glyph\b", items)
    quoted = r[8].startswith("divergence")
    if quoted and not r[9].strip("— "):
        return kind, f"{r[0]}: a divergence without a C-row"
    if gate and look == "T2":
        if not keyed or not has_lock:
            return kind, f"{r[0]}: under-conversion — a T2 row without a key or the lock"
        if dimmed:
            return kind, f"{r[0]}: over-conversion — a T2 row dimmed"
    elif gate:
        return kind, f"{r[0]}: a {kind} gate not drawn as T2 (a divergence is a C-row, the look T2)"
    elif kind == "validity":
        own_lock = drawn_lock or "cmp-079" in items.replace("no cmp-079", "")
        if look != "validity" or (own_lock and not quoted):
            return kind, f"{r[0]}: over-conversion — a validity row drawn as T2"
        if "0.45" not in items:
            return kind, f"{r[0]}: a validity row without the 0.45 look"
    elif look == "T2" or (drawn_lock and not quoted):
        return kind, f"{r[0]}: over-conversion — a {kind} row drawn as T2"
    return kind, ""


def review_tables(text: str) -> tuple[dict[str, Any], list[str]]:
    """Parse the verdict, T2, SR, naming, AL and finding tables; return counts and problems."""
    bad: list[str] = []
    n: dict[str, Any] = {}
    # verdicts: id | SC | requirement | screens | where met | verdict | evidence | finding |
    # owner | target
    sec3 = section(text, "## 3.", "## 4.")
    vrows = [
        r for r in table_rows(sec3, r"(?:\d+\.\d+(?:\.\w+)?|10|11\.\d) +\|") if r[0] in CLAUSES
    ]
    ids = [r[0] for r in vrows]
    n["clauses_expected"], n["clauses_found"] = len(CLAUSES), len(set(ids))
    bad += [f"clause {c} missing" for c in CLAUSES if c not in ids]
    bad += [f"clause {c} repeated" for c in set(ids) if ids.count(c) > 1]
    tally = {"compliant": 0, "at risk": 0, "non-compliant": 0, "out of scope": 0, "routed": 0}
    for r in vrows:
        if len(r) < 10:
            bad.append(f"clause {r[0]}: {len(r)} cells")
            continue
        v = verdict_word(r[5])
        if v == "?":
            bad.append(f"clause {r[0]}: verdict {r[5]!r}")
            continue
        tally[v] += 1
        if not r[6].strip("— "):
            bad.append(f"clause {r[0]}: no evidence")
        if v in ("at risk", "non-compliant", "routed") and not (
            r[8].strip("— ") and r[9].strip("— ")
        ):
            bad.append(f"clause {r[0]}: {v} without owner / target")
    n |= {"verdict_" + k.replace(" ", "_").replace("-", "_"): v for k, v in tally.items()}
    # the stop tables of 4.1 (SCR-081 as a table; the other four as arrow-separated prose) and 4.2
    sec41 = section(text, "### 4.1", "### 4.2")
    n["stops_081"] = len(table_rows(section(sec41, "**SCR-081**", "**SCR-083**"), r"\d+ +\|"))
    for scr, nxt in (
        ("083", "**SCR-080**"),
        ("080", "**SCR-088**"),
        ("088", "**SCR-089**"),
        ("089", "**Dialogs and the preview**"),
    ):
        para = section(sec41, f"**SCR-{scr}**", nxt)
        n[f"stops_{scr}"] = para.count(" → ") + 1 if para else 0
    dsec = section(sec41, "**Dialogs and the preview**", "### 4.2")
    n["dialog_rows"] = len(
        [
            ln
            for ln in dsec.splitlines()
            if ln.startswith("| ") and not ln.startswith(("| Dialog", "| -"))
        ]
    )
    n["ac1_steps"] = len(table_rows(section(text, "### 4.2", "### 4.3"), r"\d+ +\|"))
    n["colour_rows"] = len(table_rows(section(text, "## 10.", "## 11."), r"\d+ +\|"))
    h20 = [ln for ln in section(text, "## 20.", "## 21.").splitlines() if ln.startswith("| ")]
    n["handoff_rows"] = max(0, len(h20) - 2)
    # T2 walk: id | control | screen | frame | kind | six items | reason key | look | verdict
    # | C-row
    t2 = table_rows(section(text, "## 8.", "## 9."), r"T2-\d+ +\|")
    kinds: dict[str, int] = {}
    over = under = diverge = 0
    for r in t2:
        if len(r) < 10:
            bad.append(f"{r[0]}: {len(r)} cells")
            continue
        kind, problem = _t2_check(r)
        kinds[kind] = kinds.get(kind, 0) + 1
        diverge += r[8].startswith("divergence")
        if problem:
            bad.append(problem)
            over += "over-conversion" in problem
            under += "under-conversion" in problem
    n |= {"t2_rows": len(t2), "t2_by_kind": kinds, "t2_over_conversion": over}
    n["t2_under_conversion"] = under
    n["t2_divergences"] = diverge  # the upstream's over-conversions the walk records as C-rows
    # SR script: id | event | trigger | announced | mechanism | politeness | cadence | class |
    # verdict | finding
    srr = table_rows(section(text, "## 5.", "## 6."), r"SR-\d+ +\|")
    for r in srr:
        if len(r) < 10:
            bad.append(f"{r[0]}: {len(r)} cells")
            continue
        ok = r[4] in MECHANISMS and r[5] in POLITENESS and re.search(r"6\.2\.[a-d]|—", r[7])
        if not ok or verdict_word(r[8]) == "?":
            bad.append(f"{r[0]}: mechanism / politeness / class / verdict")
    n["sr_rows"] = len(srr)
    n["sr_assertive"] = sum(r[5] == "assertive" for r in srr if len(r) >= 10)
    # naming: id | element | role | name | description | requirement | verdict | finding
    nr = table_rows(section(text, "## 6.", "## 7."), r"N-\d+ +\|")
    for r in nr:
        if len(r) < 8 or not r[2].strip("— ") or ('"' not in r[3] and "“" not in r[3]):
            bad.append(f"{r[0] if r else 'N-?'}: role or quoted name missing")
    n["naming_rows"] = len(nr)
    # AL: id | criterion | SC + clause | screen | section | verifier | pass bar | source
    al = table_rows(section(text, "## 16.", "## 17."), r"AL-\d+ +\|")
    princ: dict[str, int] = {}
    names = {"1": "perceivable", "2": "operable", "3": "understandable", "4": "robust"}
    scen = {"D02": b_scenarios(H02), "D03": b_scenarios(H03)}
    b_cited = review_only = 0
    for i, r in enumerate(al, 1):
        if len(r) < 8:
            bad.append(f"{r[0]}: {len(r)} cells")
            continue
        if r[0] != f"AL-{i:02d}":
            bad.append(f"{r[0]}: expected AL-{i:02d}")
        if not VERIFIER.match(r[5]):
            bad.append(f"{r[0]}: no verifier")
        m = re.search(r"\b([1-4])\.\d+\.\d+", r[2])
        p = names.get(m.group(1) if m else "", "none")
        princ[p] = princ.get(p, 0) + 1
        # the section cell: every `§B :N` after a `D0n-handoff` must start a Scenario of that file
        valid = 0
        for part in r[4].split(";"):
            h = B_HANDOFF.search(part)
            if not h:
                continue
            for ref in B_REF.finditer(part):
                if int(ref.group(1)) in scen[h.group(1)]:
                    valid += 1
                else:
                    bad.append(
                        f"{r[0]}: §B :{ref.group(1)} starts no Scenario of {h.group(1)}-handoff"
                    )
        marker = REVIEW_ONLY in r[4]
        if valid and marker:
            bad.append(f"{r[0]}: both a §B citation and the review-only marker")
        elif valid:
            b_cited += 1
        elif marker:
            review_only += 1
        else:
            bad.append(f"{r[0]}: no §B scenario line and no review-only marker")
    n["al_rows"] = len(al)
    n["al_without_verifier"] = sum(1 for r in al if len(r) >= 8 and not VERIFIER.match(r[5]))
    n["al_by_principle"] = princ
    n["al_b_cited"], n["al_review_only"] = b_cited, review_only
    n["b_scenarios"] = {"d02": len(scen["D02"]), "d03": len(scen["D03"])}
    # findings
    fnd = section(text, "## 15.", "## 16.")
    frows = table_rows(fnd, r"F-\d+ +\|")
    sev: dict[str, int] = {}
    cls: dict[str, int] = {}
    noown = 0
    for r in frows:
        if len(r) < 8:
            bad.append(f"{r[0]}: {len(r)} cells")
            continue
        sev[r[2]] = sev.get(r[2], 0) + 1
        cls[r[1]] = cls.get(r[1], 0) + 1
        if r[2] not in SEVERITIES or r[1] not in F_CLASSES:
            bad.append(f"{r[0]}: severity {r[2]!r} / class {r[1]!r}")
        if not r[5].strip("— ") or not r[6].strip("— "):
            noown += 1
    n |= {"f_rows": len(frows), "f_by_severity": sev, "f_by_class": cls}
    n["f_without_owner_target"] = noown
    fams = (("a", r"A-\d+ +\|"), ("c", r"C-\d+ +\|"), ("g", r"G-\d+ +\|"), ("q", r"Q-\d+ +\|"))
    for fam, pat in (*fams, ("h", r"H-\d+ +\|"), ("k", r"K-\d+ +\|")):
        fr = table_rows(text if fam == "k" else fnd, pat)
        n[f"{fam}_rows"] = len(fr)
        for r in fr:
            body = r[1] if len(r) > 1 else ""
            if fam == "a" and not re.search(
                r"`(?:14|15|05):\d+`|(`(?:14|15|05)`|E09-D09|the memo).*(:\d+|§)", body
            ):
                bad.append(f"{r[0]}: an A-row without a file and line / section")
            if fam == "c" and " vs " not in body:
                bad.append(f"{r[0]}: a C-row without both sources (' vs ')")
            if fam == "h" and "(heuristic)" not in " ".join(r):
                bad.append(f"{r[0]}: an H-row without (heuristic)")
    if noown:
        bad.append(f"F rows without owner / target: {noown}")
    if n["al_without_verifier"]:
        bad.append(f"AL rows without verifier: {n['al_without_verifier']}")
    return n, bad


# --------------------------------------------------------------------------- 8. string gates
def string_gates(text: str, label: str, draft: bool = False) -> list[str]:
    bad = []
    for pat in FABRICATED:
        bad += [f"{label}: fabricated-AT phrase {m.group(0)!r}" for m in re.finditer(pat, text)]
    bad += [f"{label}: hygiene hit {pat}" for pat in HYGIENE if re.search(pat, text)]
    bad += [f"{label}: closing keyword {m.group(0)!r}" for m in CLOSING.finditer(text)]
    if draft:
        bad += [f"{label}: the word {m.group(0)!r}" for m in DRAFT_WORDS.finditer(text)]
    cons = read(ROOT / "CONSTITUTION.md")
    cited = sorted(set(re.findall(r"\bC-\d+\.\d+\b", text)))
    bad += [f"{label}: dangling {c}" for c in cited if f"**{c}" not in cons]
    return bad


def host_pattern_selftest() -> dict[str, bool]:
    pat = re.compile(HYGIENE[1])
    probes = {
        "penpot.fonts.all": False,
        "penpot.fonts.findByName": False,
        "penpot.currentFile": False,
        "penpot.currentPage": False,
        "penpot" + ".example." + "org": True,
    }
    return {k: bool(pat.search(k)) == want for k, want in probes.items()}


def flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            flat |= flatten(v, f"{prefix}{k}.")
        else:
            flat[f"{prefix}{k}"] = len(v) if isinstance(v, list) else v
    return flat


REQUIRED_MARKERS = [
    "clauses_found",
    "f_rows",
    "al_rows",
    "al_b_cited",
    "sr_rows",
    "t2_rows",
    "k_rows",
    "keymap.lint_errors",
    "keymap.sr_chord_hits",
    "matrix.d04_fail",
    "targets_under",
]


def check_markers(text: str, counts: dict[str, Any]) -> list[str]:
    flat = flatten(counts)
    bad, seen = [], 0
    for m in re.finditer(r"<!--\s*audit:([A-Za-z0-9_.-]+)=([^\s>]+)\s*-->", text):
        seen += 1
        name, val = m.group(1), m.group(2)
        if name not in flat:
            bad.append(f"marker {name}: no such number")
            continue
        want = flat[name]
        if isinstance(want, bool):
            ok = val.lower() == str(want).lower()
        elif isinstance(want, float):
            ok = abs(float(val) - want) < 0.006
        else:
            ok = str(val) == str(want)
        if not ok:
            bad.append(f"marker {name}={val}: the tool computes {want}")
    for r in REQUIRED_MARKERS:
        if not re.search(rf"<!--\s*audit:{re.escape(r)}=", text):
            bad.append(f"required marker missing: {r}")
    return bad + (["no audit markers in the review"] if not seen else [])


# ----------------------------------------------------------------------------------- 9. main
def main(argv: list[str]) -> int:
    std, cat14 = read(STD05), read(CAT14)
    inv, km = clause_inventory(std), keymap_matrix(cat14)
    mx, tg, zm, mo = matrices(), target_table(), zoom_table(), motion_table()
    counts: dict[str, Any] = {
        "clause_inventory": inv,
        "keymap": km,
        "matrix": {k: v for k, v in mx.items() if k != "palette"},
        "targets_rows": len(tg["rows"]),
        "targets_under": len(tg["under"]),
        "targets_typed_no_token": len(tg["typed_no_token"]),
        "targets_min": tg["minimum"],
        "pill20": tg["pill20"],
        "zoom": {k: v for k, v in zm.items() if k != "rows"},
        "motion": mo,
        "cadence": {
            "debounce_ms": DEBOUNCE_MS,
            "coalesce_ms": COALESCE_MS,
            "recompiles_per_s": round(1000 / DEBOUNCE_MS, 2),
            "patches_per_s": round(1000 / COALESCE_MS, 2),
            "ambient_budget_s": AMBIENT_S,
            "std_cadence_s": STD_CADENCE_S,
        },
        "host_selftest": host_pattern_selftest(),
    }
    review_path = Path(argv[argv.index("--check") + 1]) if "--check" in argv else REVIEW
    review = read(review_path)
    problems: list[str] = []
    if review:
        rt, bad = review_tables(review)
        counts |= rt
        problems += bad + string_gates(review, review_path.name)
        if "--check" in argv:
            problems += check_markers(review, counts)
            for s in (MERGE_D02, MERGE_D03, MERGE_E11_D07):
                if s not in review:
                    problems.append(f"sha {s[:12]} not in the review's header")
    if "--draft" in argv:
        draft = Path(argv[argv.index("--draft") + 1])
        problems += string_gates(read(draft), draft.name, draft=True)
    problems += [f"union FAIL: {f}" for f in mx["fail"]]
    problems += [f"D04 FAIL: {r['label']}" for r in mx["d04"] if r["verdict"] == "FAIL"]
    problems += [f"target under {tg['minimum']}: {t}" for t in tg["under"]]
    problems += mo["problems"] + tg["d03_problems"]
    problems += [
        f"host self-test failed: {k}" for k, ok in counts["host_selftest"].items() if not ok
    ]
    if km["lint_errors"]:
        problems.append(f"lint_keymap errors: {km['lint_errors']}")
    counts["problems"] = problems
    if "--json" in argv:
        extra = {
            "palette": mx["palette"],
            "d04_pairs": mx["d04"],
            "targets": tg["rows"],
            "zoom_rows": zm["rows"],
            "chords": km["chords"],
        }
        print(json.dumps(counts | extra, ensure_ascii=False, indent=1))
        return 1 if problems else 0
    c, k = counts, km
    out = [
        (
            "# E36-D04 review audit (05 at the base; keymap.json; packages/ui/tokens; "
            "the two sibling tools imported)"
        ),
        "",
        (
            f"## 1. clauses: {c.get('clauses_found', 0)} found / {len(CLAUSES)} expected · "
            f"05 items {inv} · compliant {c.get('verdict_compliant', '-')} / at risk "
            f"{c.get('verdict_at_risk', '-')} / non-compliant "
            f"{c.get('verdict_non_compliant', '-')} "
            f"/ out of scope {c.get('verdict_out_of_scope', '-')} / routed "
            f"{c.get('verdict_routed', '-')}"
        ),
        (
            f"## 2. key map: {k['commands']} commands / {k['atomic_bindings']} atomic; Rules "
            f"{k['rules_commands']}; reserved {k['reserved_combos']} combos → "
            f"{k['reserved_atomic']} atomic; lint_keymap errors (shipped): {k['lint_errors']}; "
            f"check_coverage errors: {k['coverage_errors']} (A-01 text: "
            f"{k['coverage_errors_a01']}; with Shift+F10 backticked: "
            f"{k['coverage_errors_a01_backticked']}); 05 §3.2 rows {k['map05_rows']} (rule "
            f"builder {k['map05_rule_builder_rows']}: {'; '.join(k['rule05'])})"
        ),
        (
            f"- design bindings {k['design_rows']} rows / {k['design_keys']} keys; same-context "
            f"{len(k['same_context'])}: {k['same_context']}; disjoint reuse "
            f"{len(k['disjoint_reuse'])}: {k['disjoint_reuse']}; shadow of Workspace "
            f"{len(k['shadow_workspace'])}: {k['shadow_workspace']}; reserved (design) "
            f"{len(k['reserved_design'])}: {k['reserved_design']}; Alt+<letter> "
            f"{k['alt_family']}; specified-unregistered {k['specified_unregistered']}; "
            f"registered-unspecified {k['registered_unspecified']}; unscoped Rules rows "
            f"{len(k['unscoped_rules_rows'])}: {k['unscoped_rules_rows']}; 05 contradicted by "
            f"the registry: {k['contradicted_05']}"
        ),
        (
            f"- E11-D07 fixture (imported) {k['sr_fixture_rows']} rows {k['sr_fixture_by_reader']} "
            f"from {k['sr_fixture_sources']} sources; the editor subset {k['sr_subset_rows']} "
            f"(letters {k['sr_letter_rows']} {k['sr_letter_rows_by_reader']}; live-mode rows "
            f"{k['sr_subset_live_mode_rows']}); chord hits {k['sr_chord_hits']} "
            f"{k['sr_chord_hits_by_key']}; rows by mode over the design keys {k['sr_rows_by_mode']}"
        ),
        "- the eight chords: "
        + " · ".join(
            f"{ch['chord']}: 14 {'yes' if ch['in_14'] else 'no'}; D02 {ch['d02']}; registry "
            f"{', '.join(ch['registry'])}; 05 {', '.join(ch['map05'])}; reserved "
            f"{', '.join(ch['reserved'])}; SR rows {ch['sr_rows']}"
            for ch in k["chords"]
        ),
        (
            f"## 3. union matrix: D02 {mx['d02']} · D03 {mx['d03']} · gated FAIL "
            f"{len(mx['fail'])} · the two ratio functions agree to 0.005: {mx['agree']}"
        ),
    ]
    out += [
        f"- D04 {r['label']}: {r['fg']} on {r['bg']} ({r['role']}, bar {r['bar']}) dark "
        f"{r['dark']} / light {r['light']} / hc {r['high-contrast']} → {r['verdict']}"
        for r in mx["d04"]
    ]
    out += [
        f"- validity composite ({v['alpha']} over {v['host']}): label over fill dark {v['dark']} "
        f"/ light {v['light']} / hc {v['high-contrast']} — reported, not gated (an inactive "
        "control, WCAG 1.4.3)"
        for v in mx["validity_composite"]
    ]
    out.append(
        "- greyscale luma (Rec. 601, floored) dark / light: "
        + "; ".join(
            f"{n.split('.', 1)[1]} {v['dark']} / {v['light']}" for n, v in mx["greyscale"].items()
        )
    )
    out.append(
        f"## 4. targets ({len(tg['rows'])} rows; min {tg['minimum']} px; under: {tg['under']}; "
        f"typed with no token: {tg['typed_no_token']}; D03's table {tg['d03_rows']} rows, "
        f"problems {tg['d03_problems']})"
    )
    out += [f"- {' | '.join(r)}" for r in tg["rows"]]
    out.append(
        f"## 5. 200 %: stated {zm['stated']} / silent {zm['silent']} / cited {zm['cited']}; the "
        f"in-app text scale: stated {zm['text_scale_stated']} / silent {zm['text_scale_silent']} / "
        f"cited {zm['text_scale_cited']}"
    )
    out += [
        f"- {r['surface']} ({r['doc']} §{r['section']}): {r['state']} {r['hits']}; text scale "
        f"{r['text_scale']}"
        for r in zm["rows"]
    ]
    out.append(
        f"## 6. motion: {mo['rows']} rows; reduce variants {mo['reduce_variants']}; rates "
        f"{mo['rates']}; D02 Table 4 rows {mo['d02_table4_rows']} 'none animated' "
        f"{mo['d02_nothing_animates']}; problems {mo['problems']}"
    )
    out.append(
        f"## 7. review tables: T2 {c.get('t2_rows', '-')} by kind {c.get('t2_by_kind', {})} "
        f"over-conversion {c.get('t2_over_conversion', '-')} / under-conversion "
        f"{c.get('t2_under_conversion', '-')} / upstream divergences recorded as C-rows "
        f"{c.get('t2_divergences', '-')}; SR {c.get('sr_rows', '-')} (assertive "
        f"{c.get('sr_assertive', '-')}); naming {c.get('naming_rows', '-')}; AL "
        f"{c.get('al_rows', '-')} by principle {c.get('al_by_principle', {})}; F "
        f"{c.get('f_rows', '-')} {c.get('f_by_severity', {})} {c.get('f_by_class', {})}; "
        f"A / C / G / Q / H / K {c.get('a_rows', '-')} / {c.get('c_rows', '-')} / "
        f"{c.get('g_rows', '-')} / {c.get('q_rows', '-')} / {c.get('h_rows', '-')} / "
        f"{c.get('k_rows', '-')}"
    )
    out.append(
        f"## 8. gates: F rows without owner/target: {c.get('f_without_owner_target', '-')}; "
        f"AL rows without verifier: {c.get('al_without_verifier', '-')}; AL rows citing a §B "
        f"scenario / review-only: {c.get('al_b_cited', '-')} / {c.get('al_review_only', '-')} "
        f"(scenarios {c.get('b_scenarios', {})}; dialogs {c.get('dialog_rows', '-')}); "
        f"fabricated-AT phrases: "
        f"{sum('fabricated' in q for q in problems)}; T2 walk: over-conversion "
        f"{c.get('t2_over_conversion', '-')} / under-conversion "
        f"{c.get('t2_under_conversion', '-')}; union matrix gated FAIL: {len(mx['fail'])}; "
        f"D04 rows gated FAIL: {mx['d04_fail']}; targets < {tg['minimum']} without exception: "
        f"{len(tg['under'])}; lint_keymap errors (shipped): {k['lint_errors']}; E11-D07 fixture "
        f"chord hits: {k['sr_chord_hits']}; host self-test {c['host_selftest']}"
    )
    out.append("## 9. problems: " + ("\n".join(problems) if problems else "none"))
    print("\n".join(out))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
