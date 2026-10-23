"""E13-D05 accessibility design review audit: every number the review quotes, from the repo.

Offline (``python3 -I`` from the repo root), stdlib only beyond the repo modules it imports.
It imports three lane tools and executes no other repo code: ``e13_d02_wires_audit.py`` (its
``PAIRS``, ``col()``), ``e13_d03_palette_audit.py`` (its ``PAIRS``, ``T``, ``JND``, ``key_hex()``,
``hx()``, ``ratio()``, ``lstar()``, ``de()``, ``sim()``, ``blend()`` -- which themselves load the
repo scripts ``packages/ui/tokens/tests/verify_tokens.py`` (the token loader),
``docs/design/_tools/contrast_check.py`` (``contrast_ratio()``) and
``docs/research/_tools/cvd_simulate.py`` (the Brettel / Vienot projection and ``delta_e76()``)) and
``e11_d07_a11y_review_audit.py`` (``nrm``, ``expand_keys``, ``load_keymap``, ``shipped_bindings``,
``load_reserved``, ``parse_05_hotkeys``, ``hotkey_05_keys``, ``load_fixture``, the string gates and
``table_cell_mismatches``; it loads ``scripts/keymap_lint.py`` -- ``normalise``, ``expand``,
``lint_keymap``). No colour or key maths is re-implemented, so every ratio and dE agrees with
E13-D02 / E13-D03 to the hundredth; two small pieces repeat E11's shape instead of importing it --
``coactive()`` (E11's co-active sets are Chart / Grid + Replay; this review's are Objects / Chart +
Replay, so a plain import would give the wrong answer) and the two screen-reader classifier
regexes -- and ``cvd_pairs()`` is not called (D03 section 10.3's pairs are cited, not re-derived).
No network call is made and no URL literal exists in this file; the hygiene checks
use generic patterns that name no host, user or folder.

Sections (each row names its source so a reviewer can re-grep it):

1. The clause inventory (R1): the ``05`` items at the base beside the review's 40 clause ids, and
   the review's verdict table parsed from ``docs/design/E13/E13-D05.md`` (every id once, a verdict
   from the fixed vocabulary, evidence, and an owner + target on every at-risk / non-compliant /
   routed row).
2. The keyboard contract (R3), the seven-operation table (R13) and the gesture audit (R5): rows,
   stops per surface, the tree's keys, no empty keyboard-path cell.
3. The expected-rendering script (R4) and the politeness routing table (R7): every live-event
   string exists verbatim in E13-D02 section 12 at the base; AC 3's four events present, how
   many carry a politeness, and how many are specified (a deck string and a politeness -- a
   PROPOSED placeholder string is recorded, never counted as a deck string); every quoted string
   of the K / R / T2 tables exists verbatim in one of the cited sources; nothing assertive; the
   cadence arithmetic; the fabricated-AT phrases (expected 0).
4. The state-carrier audit (R6): every carrier pair measured per theme (text 4.5, non-text 3,
   hc-text 7), its greyscale dL*, its protanopia / deuteranopia / tritanopia dE76 (JND 5.0); the
   union of the two upstream ``PAIRS`` lists re-measured; D05's composition rows (gated).
5. The key-map matrix (R9): the E13 design bindings typed from E13-D02 / E13-D03 with their source
   line against the shipped ``keymap.json``, ``reserved-keys.json``, the ``05`` section 3.2 table
   and the screen-reader fixture; the classes (every live-mode fixture hit classed, none dropped),
   the type-ahead split per class and the hits per reader and mode; the D25 shadow column compared
   with the registry; ``lint_keymap()`` on the shipped file (expected 0).
6. The T2 table (R8): rows by gate class; a non-gate row whose Form cell renders the control as T2
   is an over-conversion candidate and must carry an F id (the count is a marker).
7. The target table: every size resolved from its token in ``primitives.tokens.json`` or marked
   typed; verdict >= 24 px.
8. String gates on the review (and on the PR draft with ``--draft``): every H row ``(heuristic)``,
   every F row with exactly one owner, one target and a consumer, listed by the clause row it
   cites, every A row with a file and a section, no local path, no Penpot host (a generic
   pattern), every table row with its header's cell count, no closing keyword beside an issue
   number in the draft.

Usage:
  python3 -I docs/design/_tools/e13_d05_a11y_review_audit.py            Markdown report
  ... --json                                                            one object for the boards
  ... --check docs/design/E13/E13-D05.md [--draft <file>]                re-derive every marker
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
PLAN = ROOT / "docs" / "plan"
SPEC_DEFAULT = ROOT / "docs" / "design" / "E13" / "E13-D05.md"
D02_PATH = ROOT / "docs" / "design" / "E13" / "E13-D02.md"
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float] = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The imported lane tools are untyped modules: every attribute below is Any at this boundary.
D02: Any = _load(TOOLS / "e13_d02_wires_audit.py", "e13_d02_wires_audit")
D03: Any = _load(TOOLS / "e13_d03_palette_audit.py", "e13_d03_palette_audit")
E11: Any = _load(TOOLS / "e11_d07_a11y_review_audit.py", "e11_d07_a11y_review_audit")
JND = float(D03.JND)


def hx(theme: str, token: str) -> str:
    return str(D03.hx(theme, token))


def ratio(fg: str, bg: str) -> float:
    return float(D03.ratio(fg, bg))


def fmt(v: float) -> str:
    return f"{v:.2f}"


def fmt1(v: float) -> str:
    return f"{v:.1f}"


def grey_hex(h: str) -> str:
    y = int(E11.luma(h))
    return f"#{y:02X}{y:02X}{y:02X}"


# --------------------------------------------------------------------------- 1. clauses (R1)
# The review's clause ids: 05 section 3.1 (5 of its 7 items -- item 5 is the 1-click armed indicator
# and item 7 the chart keys, E11-D07's), 3.3 (4), 3.4 (10, item 6 split into its SC 2.4.11 half and
# its ring half), 4 (4), 5 (6 of 7 -- item 5, the near-black rule, is a token rule), 6.2 (4 clauses
# from 2 bullets), 6.4 (1), 6.5 (1), 7 (4) = 40.
# The wording is derived from 05 at the base, never from this list.
CLAUSES: list[str] = [
    *("3.1.1", "3.1.2", "3.1.3", "3.1.4", "3.1.6"),
    *("3.3.1", "3.3.2", "3.3.3", "3.3.4"),
    *("3.4.1", "3.4.2", "3.4.3", "3.4.4", "3.4.5", "3.4.6a", "3.4.6b", "3.4.7", "3.4.8"),
    *("3.4.9", "3.4.10"),
    *("4.1", "4.2", "4.3", "4.4"),
    *("5.1", "5.2", "5.3", "5.4", "5.6", "5.7"),
    *("6.2a", "6.2b", "6.2c", "6.2d", "6.4a", "6.5a"),
    *("7.1", "7.2", "7.3", "7.4"),
]
VERDICTS = (
    "compliant",
    "at risk",
    "non-compliant",
    "out of scope — E11",
    "out of scope — E14",
    "out of scope — E10",
    "out of scope — E47",
    "not yet decidable — routed to E13-Q04",
)
NEEDS_OWNER = ("at risk", "non-compliant", "not yet decidable — routed to E13-Q04")
# Expected numbered items / bullets per 05 section between its headings at the base.
SECTIONS_05: dict[str, tuple[str, str, int]] = {
    "3.1": ("### 3.1 ", "### 3.2 ", 7),
    "3.3": ("### 3.3 ", "### 3.4 ", 6),
    "3.4": ("### 3.4 ", "## 4. ", 10),
    "4": ("## 4. ", "## 5. ", 4),
    "5": ("## 5. ", "## 6. ", 7),
    "6.2": ("### 6.2 ", "### 6.3 ", 2),
    "6.4": ("### 6.4 ", "### 6.5 ", 2),
    "6.5": ("### 6.5 ", "## 7. ", 1),
    "7": ("## 7. ", "## 8. ", 4),
}
GATE_CLASSES = (
    "view-as",
    "role / grant",
    "session",
    "state",
    "validity",
    "busy / status",
    "outcome",
    "deferred",
)
NOT_GATES = ("validity", "busy / status", "outcome", "deferred")
POLITENESS = ("polite", "assertive", "none", "label")


def items_05() -> dict[str, int]:
    text = (PLAN / "05-accessibility-standard.md").read_text(encoding="utf-8")
    out: dict[str, int] = {}
    for key, (start, end, _want) in SECTIONS_05.items():
        body = text.split(start, 1)[1].split(end, 1)[0]
        out[key] = sum(1 for ln in body.splitlines() if re.match(r"^(\d+\. |- )", ln))
    return out


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rows_with(text: str, rx: str) -> list[list[str]]:
    out: list[list[str]] = []
    for ln in text.splitlines():
        if ln.startswith("|") and re.match(rf"^\|\s*`?{rx}", ln):
            out.append(cells(ln))
    return out


def clause_section(spec: str) -> dict[str, Any]:
    problems: list[str] = []
    idrx = "(" + "|".join(re.escape(c) for c in CLAUSES) + r")`?\s*\|"
    found: dict[str, list[str]] = {}
    for ln in spec.splitlines():
        m = re.match(r"^\|\s*`?" + idrx, ln)
        if not m:
            continue
        cid = m.group(1)
        if cid in found:
            problems.append(f"clause {cid}: listed twice")
        found[cid] = cells(ln)
    by_verdict: dict[str, int] = {v: 0 for v in VERDICTS}
    for cid in CLAUSES:
        row = found.get(cid)
        if row is None:
            problems.append(f"clause {cid}: missing from the verdict table")
            continue
        if len(row) < 8:
            problems.append(f"clause {cid}: {len(row)} cells, expected 8")
            continue
        verdict = row[3]
        if verdict not in VERDICTS:
            problems.append(f"clause {cid}: verdict {verdict!r} not in the vocabulary")
        else:
            by_verdict[verdict] += 1
        if not row[4] or row[4] == "—":
            problems.append(f"clause {cid}: empty evidence cell")
        if verdict in NEEDS_OWNER and (row[6] in ("", "—") or row[7] in ("", "—")):
            problems.append(f"clause {cid}: {verdict} without an owner and a target")
    out_of_scope = sum(v for k, v in by_verdict.items() if k.startswith("out of scope"))
    return {
        "expected": len(CLAUSES),
        "found": len([c for c in CLAUSES if c in found]),
        "compliant": by_verdict["compliant"],
        "at_risk": by_verdict["at risk"],
        "non_compliant": by_verdict["non-compliant"],
        "out_of_scope": out_of_scope,
        "routed": by_verdict["not yet decidable — routed to E13-Q04"],
        "by_verdict": by_verdict,
        "problems": problems,
    }


# --------------------------------------------------------------------------- 2. key map (R9)
# key | context | stop | action | source | line. "*" = a chord live anywhere in its context; a named
# stop is a focus-scoped key (05 section 3.3 item 1(3): mutually exclusive). "typeahead" expands to
# the letters and digits the tree's type-ahead consumes (E13-D02 D25).
SRC = {
    "D02": "docs/design/E13/E13-D02.md",
    "D03": "docs/design/E13/E13-D03.md",
    "D3H": "docs/design/E13/E13-D03-handoff.md",
}
DESIGN_TABLE = """
↑ | Library | combobox | previous option (aria-activedescendant) | D02 | 380
↓ | Library | combobox | next option | D02 | 380
PageUp | Library | combobox | one page of options back (proposed) | D02 | 380
PageDown | Library | combobox | one page of options forward (proposed) | D02 | 380
Enter | Library | combobox | add the active option; the dialog stays open | D02 | 380
Esc | Library | * | clear a non-empty query, else close and return focus | D02 | 380
← | Library | tabs | previous category tab (roving) | D02 | 380
→ | Library | tabs | next category tab (roving) | D02 | 380
Enter | Library | star | toggle Favourite (aria-pressed) | D02 | 124
Space | Library | star | toggle Favourite (aria-pressed) | D02 | 124
← | Library | pane-target | previous segment | D02 | 124
→ | Library | pane-target | next segment | D02 | 124
Enter | Library | add | Add to chart | D02 | 124
Space | Library | add | Add to chart | D02 | 124
Tab | Library | * | the next stop | D02 | 380
← | Settings | tabs | previous tab (roving) | D02 | 382
→ | Settings | tabs | next tab (roving) | D02 | 382
↑ | Settings | stepper | step up by step | D02 | 179
↓ | Settings | stepper | step down by step | D02 | 179
PageUp | Settings | stepper | step up x10 | D02 | 179
PageDown | Settings | stepper | step down x10 | D02 | 179
Home | Settings | stepper | minimum | D02 | 179
End | Settings | stepper | maximum | D02 | 179
Enter | Settings | field | Apply (a valid field); re-announce the message (an invalid one) | D02
  | 382
Enter | Settings | save-row | save the preset | D02 | 195
Esc | Settings | * | close the save row first, else Cancel and return focus | D02 | 382
↑ | Settings | swatch-radiogroup | previous radio (T2 today: moves and checks nothing) | D03 | 464
↓ | Settings | swatch-radiogroup | next radio | D03 | 464
← | Settings | swatch-radiogroup | previous radio | D03 | 464
→ | Settings | swatch-radiogroup | next radio | D03 | 464
↓ | Settings | reset-menu | open the Reset split menu | D02 | 162
Enter | Settings | alertdialog | Done (initial focus) in the D17 alertdialog | D02 | 382
Tab | Settings | * | the next stop | D02 | 382
↑ | Objects | tree | previous visible item | D02 | 253
↓ | Objects | tree | next visible item | D02 | 253
← | Objects | tree | collapse | D02 | 254
→ | Objects | tree | expand; into the first child | D02 | 254
Home | Objects | tree | first visible item | D02 | 255
End | Objects | tree | last visible item | D02 | 255
typeahead | Objects | tree | focus the next item whose label starts with the typed characters
  | D02 | 256
Enter | Objects | tree | open SCR-035 / SCR-037 properties / SCR-091 | D02 | 257
Space | Objects | tree | toggle visibility | D02 | 258
Ctrl+Space | Objects | tree | toggle selection | D02 | 259
Shift+↑ | Objects | tree | extend the selection up | D02 | 260
Shift+↓ | Objects | tree | extend the selection down | D02 | 260
Shift+Space | Objects | tree | select from the anchor | D02 | 261
Ctrl+A | Objects | tree | select every item of the focused group | D02 | 262
Del | Objects | tree | remove the focused item or the selection | D02 | 263
F2 | Objects | tree | rename in place | D02 | 264
Alt+↑ | Objects | tree | reorder up within the group | D02 | 265
Alt+↓ | Objects | tree | reorder down within the group | D02 | 265
Shift+F10 | Objects | tree | open the item menu | D02 | 266
Menu | Objects | tree | open the item menu | D02 | 266
Ctrl+Z | Objects | tree | undo the last removal (OQ-G) | D02 | 267
Esc | Objects | * | clear the selection; with none, close the drawer | D02 | 268
Tab | Objects | * | leave the tree for the bulk bar, the footer, the filter or Close | D02 | 269
Enter | Objects | row-controls | eye / lock / menu button | D02 | 220
Space | Objects | row-controls | eye / lock / menu button | D02 | 220
↑ | Objects | item-menu | previous item (T2 items reachable) | D03 | 464
↓ | Objects | item-menu | next item | D03 | 464
Enter | Objects | item-menu | activate the item | D02 | 220
Enter | Objects | alertdialog | Done (initial focus) in the D24 alertdialog | D02 | 383
↑ | Chart | legend | previous row | D3H | 115
↓ | Chart | legend | next row | D3H | 115
← | Chart | legend | the row's previous control; collapse a ribbon | D3H | 116
→ | Chart | legend | the row's next control; expand a ribbon | D3H | 116
Space | Chart | legend | toggle visibility | D3H | 117
Enter | Chart | legend | quick-edit on the value (C-12, proposed); the +N more popover | D3H | 118
Esc | Chart | legend | back to the plot cursor | D3H | 120
Enter | Chart | legend-quick-edit | commit (or the D17 guard) | D02 | 298
Esc | Chart | legend-quick-edit | revert | D02 | 298
↑ | Chart | legend-quick-edit | spinbutton step up | D02 | 410
↓ | Chart | legend-quick-edit | spinbutton step down | D02 | 410
Enter | Chart | toolbar | count chip opens SCR-036 | D3H | 121
Space | Chart | toolbar | count chip opens SCR-036 | D3H | 121
"""
DESIGN_BINDINGS: list[tuple[str, str, str, str, str, int]] = [
    (r[0], r[1], r[2], r[3], SRC[r[4]], int(r[5])) for r in E11.rows(DESIGN_TABLE)
]
# The shadow column of E13-D02 D25 (docs/design/E13/E13-D02.md:253-269) as text: key -> ids.
D25_SHADOWS: dict[str, list[str]] = {
    "Enter": ["rules.inspect_node", "positions.open_sltp", "global.auth.submit"],
    "Space": ["dom.recentre", "replay.play_pause"],
    "Ctrl+Space": [],
    "Ctrl+A": ["rules.select_all"],
    "Del": ["chart.delete_drawing", "rules.delete"],
    "F2": ["rules.rename"],
    "Alt+↑": ["rules.move_up"],
    "Alt+↓": ["rules.move_down"],
    "Ctrl+Z": ["chart.undo"],
    "↑": [],
    "↓": [],
    "←": [],
    "→": [],
    "Home": [],
    "End": [],
    "Shift+↑": [],
    "Shift+↓": [],
    "Shift+Space": [],
    "Shift+F10": [],
    "Esc": [],
    "Tab": [],
}
# Co-active focus contexts: Global and Workspace with everything (05 section 3.3 item 1(1)); the
# docked drawer and the chart's stops can be live beside a replay session (E11-D07 section 7.1's
# model); the two modals trap focus, so they are co-active with Global / Workspace only.
COACTIVE_SETS = ({"Objects", "Replay"}, {"Chart", "Replay"})
ALWAYS = {"Global", "Workspace"}
REUSE_CONTEXTS = ("Objects", "Library", "Settings", "Chart")
APG = {"Enter", "Esc", "Space", "Tab", "←", "→", "↑", "↓", "Home", "End", "PageUp", "PageDown"}
TYPEAHEAD = [chr(c) for c in range(65, 91)] + [str(d) for d in range(10)]
# Platform notes the fixture cannot carry (E13-D02 D25 / OQ-G) and the browser defaults E11-D07
# F-20 found missing from reserved-keys.json.
PLATFORM_NOTES = (("Ctrl+Space", "Objects", "the Windows IME on / off toggle on CJK layouts"),)
BROWSER_OMITTED = {"Ctrl+A": "select all (E11-D07 F-20: absent from reserved-keys.json)"}


# E11-D07's coactive() by shape, bound to this review's sets: importing E11's would test its
# Chart / Grid + Replay sets, not the Objects / Chart + Replay ones above.
def coactive(a: str, b: str) -> bool:
    if a == b or a in ALWAYS or b in ALWAYS:
        return True
    return any(a in s and b in s for s in COACTIVE_SETS)


def design_rows() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, ctx, stop, action, src, line in DESIGN_BINDINGS:
        keys = TYPEAHEAD if key == "typeahead" else E11.expand_keys(key)
        for b in keys:
            out.append(
                {"key": b, "context": ctx, "stop": stop, "action": action, "src": src, "line": line}
            )
    return out


def keymap_section() -> dict[str, Any]:
    km = E11.load_keymap()
    shipped = E11.shipped_bindings(km)
    reserved = E11.load_reserved()
    with (E11.ROOT / "apps/web/src/keymap/reserved-keys.json").open(encoding="utf-8") as fh:
        reserved_raw: dict[str, str] = json.load(fh)
    hot = E11.parse_05_hotkeys()
    fixture = E11.load_fixture()
    sr_by_key: dict[str, list[dict[str, Any]]] = {}
    for r in fixture["keys"]:
        sr_by_key.setdefault(str(r["norm"]), []).append(r)
    design = design_rows()
    conflicts: list[dict[str, Any]] = []

    def add(cls: str, a: str, b: str, ctx: str, note: str) -> None:
        conflicts.append({"class": cls, "a": a, "b": b, "contexts": ctx, "note": note})

    def who(x: dict[str, Any]) -> str:
        return f"{x['key']} {x['context']}/{x['stop']}: {x['action']} ({x['src']}:{x['line']})"

    # (a) design vs design: the same key, co-active contexts, the same stop or a chord
    for i, x in enumerate(design):
        for y in design[i + 1 :]:
            if x["key"] != y["key"] or not coactive(x["context"], y["context"]):
                continue
            same_ctx = x["context"] == y["context"]
            if same_ctx and x["stop"] != "*" and y["stop"] != "*" and x["stop"] != y["stop"]:
                continue
            if same_ctx and x["stop"] == y["stop"]:
                continue
            add(
                "same-context" if same_ctx else "cross-context",
                who(x),
                who(y),
                f"{x['context']} + {y['context']}",
                "two meanings on one key where both can be live",
            )
    # (b) design vs the shipped registry
    for x in design:
        for s in shipped:
            if x["key"] != s["key"]:
                continue
            if not coactive(x["context"], s["context"]):
                if x["key"] not in APG and x["context"] in REUSE_CONTEXTS:
                    add(
                        "reuse",
                        who(x),
                        f"{s['key']} {s['context']}: {s['id']}",
                        f"{x['context']} | {s['context']} (disjoint)",
                        "keymap_lint: reciprocal shadows with a rationale at registration",
                    )
                continue
            if s["context"] in ALWAYS:
                cls, note = "shadow-global", f"shadows {s['context']} {s['id']} ({s['validWhen']})"
            elif s["context"] == x["context"]:
                cls = "same-context"
                note = f"the shipped {s['id']} holds the key in {s['context']} ({s['validWhen']})"
            else:
                cls = "cross-context"
                note = f"{s['id']} ({s['context']}) can be live; a declared shadow at registration"
            add(
                cls,
                who(x),
                f"{s['key']} {s['context']}: {s['id']}",
                f"{x['context']} + {s['context']}",
                note,
            )
    # (c) reserved without an override
    for x in design:
        if x["key"] in reserved:
            add(
                "reserved",
                who(x),
                f"reserved: {reserved[x['key']]}",
                x["context"],
                "no reservedOverride",
            )
    # (d) screen-reader hits (the fixture). Every live-mode hit is classed -- none is dropped:
    # sr-table (table mode), sr-browse (single letters / digits in browse mode or single-key
    # Quick Nav), sr-quicknav (arrows under VoiceOver Quick Nav), sr-browse-nav (browse-mode
    # arrows, Enter, Space, Home / End), sr-focus (a focus-mode key -- NVDA's Esc after an automatic
    # switch), sr-global (a reader-global key -- JAWS's Say All arrows, VoiceOver's Esc), sr-chord,
    # and sr-<mode> for any other mode the fixture carries. Hits are also counted per reader + mode.
    sr_hits: dict[str, int] = {}
    for x in design:
        for r in sr_by_key.get(x["key"], []):
            if r["mode"] not in E11.SR_LIVE_MODES:
                continue
            single = re.fullmatch(r"(Shift\+)?([A-Z0-9]|[,;'/-])", x["key"]) is not None
            arrow = re.fullmatch(r"(Shift\+)?[←→↑↓]", x["key"]) is not None
            if r["mode"] == "table":
                kind = "sr-table"
            elif r["mode"] in ("browse", "quick-nav") and single:
                kind = "sr-browse"
            elif r["mode"] == "quick-nav" and arrow:
                kind = "sr-quicknav"
            elif r["mode"] == "browse":
                kind = "sr-browse-nav"
            elif r["mode"] == "focus":
                kind = "sr-focus"
            elif r["mode"] == "global":
                kind = "sr-global"
            elif "+" in x["key"] and not arrow:
                kind = "sr-chord"
            else:
                kind = "sr-" + str(r["mode"])
            sr_hits[f"{r['sr']} {r['mode']}"] = sr_hits.get(f"{r['sr']} {r['mode']}", 0) + 1
            add(
                kind,
                who(x),
                f"{r['sr'].upper()} {r['mode']}: {r['keys']} = {r['function']} ({r['section']})",
                "AT",
                "consumed by the screen reader in that mode before the app sees it",
            )
    # (e) 05 section 3.2 rows holding a design key under another action. The APG keys (Enter, Esc,
    # Space, Tab, arrows, Home / End, PageUp / PageDown) are excluded here: their same-key cases are
    # the reuse / cross-context rows above, through the shipped registry that implements 05.
    for x in design:
        if x["key"] in APG:
            continue
        for row in hot:
            if x["key"] in E11.hotkey_05_keys(row):
                add(
                    "05-row",
                    who(x),
                    f"05 section 3.2 {row['category']}: {row['action']} = {row['raw']}",
                    f"{x['context']} | 05 {row['category']}",
                    "a 05 default under another action; the remap UI shows both (05 section 3.3)",
                )
    # (f) platform notes and omitted browser defaults (literal lists, cited)
    for key, ctx, note in PLATFORM_NOTES:
        add("platform", f"{key} {ctx}", note, ctx, "E13-D02 OQ-G's caveat; not a fixture row")
    for x in design:
        if x["key"] in BROWSER_OMITTED and x["context"] == "Objects":
            add("browser-omitted", who(x), BROWSER_OMITTED[x["key"]], x["context"], "E11-D07 F-20")
    # (g) D25's shadow column against the shipped holders of each key (text compare)
    by_key_holders: dict[str, set[str]] = {}
    for s in shipped:
        by_key_holders.setdefault(s["key"], set()).add(s["id"])
    undeclared: list[str] = []
    stale: list[str] = []
    for key, declared in D25_SHADOWS.items():
        holders = by_key_holders.get(E11.nrm(key), set())
        for h in sorted(holders - set(declared)):
            undeclared.append(f"{key}: {h} holds the key and D25 declares no shadow")
        for d in sorted(set(declared) - holders):
            stale.append(f"{key}: D25 declares {d}, which does not hold the key")
    by_class: dict[str, int] = {}
    for c in conflicts:
        by_class[c["class"]] = by_class.get(c["class"], 0) + 1
    # The split each KM row quotes: how many of a class fall on the tree's type-ahead letters and
    # digits (KM-02, KM-11, KM-14) and how many on the other keys (KM-01, KM-03..KM-07).
    typeahead_mark = "Objects/tree: focus the next item"
    by_class_typeahead: dict[str, int] = {}
    for c in conflicts:
        if typeahead_mark in c["a"]:
            by_class_typeahead[c["class"]] = by_class_typeahead.get(c["class"], 0) + 1
    objects_cmds = [c["id"] for c in km["commands"] if c["context"] == "Objects"]
    return {
        "shipped_commands": len(km["commands"]),
        "shipped_bindings": len(shipped),
        "reserved_entries": len(reserved),
        "reserved_raw": len(reserved_raw),
        "hot_05_rows": len(hot),
        "design_literals": len(DESIGN_BINDINGS),
        "design_bindings": len(design),
        "typeahead_keys": len(TYPEAHEAD),
        "sr_rows": len(fixture["keys"]),
        "sr_nvda": sum(1 for r in fixture["keys"] if r["sr"] == "nvda"),
        "sr_jaws": sum(1 for r in fixture["keys"] if r["sr"] == "jaws"),
        "sr_voiceover": sum(1 for r in fixture["keys"] if r["sr"] == "voiceover"),
        "sr_sources": len(fixture["sources"]),
        "objects_context_commands": len(objects_cmds),
        "objects_prefixed_commands": sum(
            1 for c in km["commands"] if c["id"].startswith("objects.")
        ),
        "conflicts": conflicts,
        "conflicts_by_class": by_class,
        "conflicts_by_class_typeahead": by_class_typeahead,
        "sr_hits_by_reader_mode": sr_hits,
        "d25_undeclared": undeclared,
        "d25_stale": stale,
        "lint_errors": list(E11.keymap_lint.lint_keymap(km)),
    }


# --------------------------------------------------------------------- 3. carriers, union (R6)
# id | state | surface | carrier (glyph / word) | fg token | bg token | role
CARRIER_TABLE = """
SC-01 | provisional | legend row | the word "provisional" beside the dashed leg
  | color.text.primary | color.surface.canvas | text
SC-02 | errored | legend row | icon/warning | color.status.danger.strong | color.surface.canvas
  | non-text
SC-03 | errored | legend row | the word "error" | color.text.primary | color.surface.canvas | text
SC-04 | warming-up (insufficient history) | legend row | "34 more bars needed" + icon/bars-missing
  | color.text.secondary | color.surface.canvas | text
SC-05 | hidden | legend row / tree row | icon/eye-off + the word "hidden" | color.text.tertiary
  | color.surface.canvas | text
SC-06 | hidden (a selected tree row) | tree row | the label + "hidden" | color.text.secondary
  | color.surface.selected | text
SC-07 | locked | tree row | the lock button aria-pressed + icon/lock | color.text.secondary
  | color.surface.overlay | non-text
SC-08 | locked (the reason) | tree menu | "Unlock to move or remove" as the second line
  | color.text.secondary | color.surface.overlay | text
SC-09 | stale | legend row | "Stale 7s" + the frozen value | color.text.tertiary
  | color.surface.canvas | text
SC-10 | rebuilding | legend row | the word "rebuilding" | color.text.secondary
  | color.surface.canvas | text
SC-11 | computing | legend row | the words "computing" / "still computing" | color.text.secondary
  | color.surface.canvas | text
SC-12 | before-history | legend row | icon/history-partial + the sentence | color.text.secondary
  | color.surface.canvas | non-text
SC-13 | history unavailable | legend row | "history unavailable" + Retry | color.text.secondary
  | color.surface.canvas | text
SC-14 | used by rules | legend row / tree row | icon/rule + "used by rules" in the name
  | color.status.warning.strong | color.surface.canvas | non-text
SC-15 | selected | tree row | the check glyph + aria-selected | color.text.primary
  | color.surface.selected | non-text
SC-16 | edited | SCR-035 header / field | the dot + the word "edited" | color.status.info.default
  | color.surface.overlay | non-text
SC-17 | invalid | SCR-035 field | icon/warning + aria-invalid | color.status.danger.strong
  | color.surface.overlay | non-text
SC-18 | invalid (the message) | SCR-035 field | "Period must be between 1 and 5000."
  | color.text.primary | color.status.danger.subtle | text
SC-19 | editing (quick-edit) | legend row | the inline field | color.text.primary
  | color.surface.raised | text
SC-20 | T2 (gated) | every surface | the lock glyph + the full label | color.text.tertiary
  | color.surface.raised | text
SC-21 | T2 (the reason) | every surface | the reason sentence | color.text.secondary
  | color.surface.raised | text
SC-22 | validity (Apply) | SCR-035 footer | the reason at full opacity | color.text.secondary
  | color.surface.overlay | text
SC-23 | mode badge | blocked-removal row | "Armed" + the glyph | color.text.primary
  | color.status.warning.subtle | text
SC-24 | environment badge | blocked-removal row | the word LIVE / DEMO | color.text.primary
  | color.surface.raised | text
SC-25 | environment icon | blocked-removal row | icon/env-live | color.env.live
  | color.surface.raised | non-text
SC-26 | count chip suffix | CMP-224 | the word + icon/warning | color.status.danger.strong
  | color.surface.raised | non-text
SC-27 | tags (On chart \u00d7N, Requires recorded history) | SCR-034 option | the tag words
  | color.text.secondary | color.surface.hover | text
SC-28 | second instance | legend row | the next ladder tier + the label suffix
  | color.text.primary | color.surface.canvas | text
"""
# id | composition | fg expression | bg expression | role  (blend(fg, bg, alpha) = sRGB composite)
COMPOSITION_TABLE = """
CP-01 | T2 lock glyph + label on a hovered menu item | color.text.tertiary | color.surface.hover
  | text
CP-02 | T2 reason as a hovered menu item's second line | color.text.secondary
  | color.surface.hover | text
CP-03 | T2 Delete label on the bulk bar (hover fill) | color.text.tertiary | color.surface.hover
  | text
CP-04 | T2 reason beside Delete on the bulk bar | color.text.secondary | color.surface.hover | text
CP-05 | validity: Apply's primary fill at opacity.disabled over the overlay | validity_fill
  | color.surface.overlay | reported
CP-06 | validity: Apply's label under group opacity (opacity.disabled on the control)
  | blend(color.text.on-action, color.surface.overlay, 0.45) | validity_fill | reported
CP-07 | validity: the reason beside Apply at full opacity | color.text.secondary
  | color.surface.overlay | text
CP-08 | focus ring beside a slot swatch tile (on the overlay, 2 px offset) | color.focus.ring
  | color.surface.overlay | non-text
CP-09 | focus ring against the hidden row's swatch (adjacent, not a stack) | color.focus.ring
  | color.text.tertiary | reported
CP-10 | the view-as / Viewer notice under a header | color.text.secondary | color.surface.overlay
  | text
CP-11 | the T2 hairline on raised | color.border.default | color.surface.raised | decorative
CP-12 | the lock badge on the SCR-034 star (icon-only, 2b) | color.text.tertiary
  | color.surface.raised | non-text
CP-13 | the errored glyph on a hovered legend row | color.status.danger.strong
  | color.surface.hover | non-text
CP-14 | the used-by-rules glyph on a selected tree row | color.status.warning.strong
  | color.surface.selected | non-text
"""


# A named composite the composition rows reuse (E30-D02 D3's look: opacity.disabled on the control,
# a group opacity -- so the fill and the label are each composited over the overlay at 0.45, and the
# label never passes through the fill; CP-06 measures the two composites against each other).
ALIASES = {"validity_fill": "blend(color.action.primary.default, color.surface.overlay, 0.45)"}


def ev(theme: str, expr: str) -> str:
    expr = ALIASES.get(expr.strip(), expr.strip())
    m = re.fullmatch(r"blend\((.*)\)", expr)
    if not m:
        return hx(theme, expr)
    depth, parts, cur = 0, [], ""
    for ch in m.group(1):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return str(D03.blend(ev(theme, parts[0]), ev(theme, parts[1]), float(parts[2])))


def measure(fg: str, bg: str, role: str) -> dict[str, Any]:
    vals = [ratio(ev(t, fg), ev(t, bg)) for t in THEMES]
    bar = BAR.get(role)
    if bar is None:
        bad: list[str] = []
    elif role == "hc-text":
        bad = ["high-contrast"] if vals[2] < bar else []
    else:
        bad = [THEMES[i] for i, v in enumerate(vals) if v < bar]
    fd, bd = ev("dark", fg), ev("dark", bg)
    fl, bl = ev("light", fg), ev("light", bg)
    return {
        "dark": vals[0],
        "light": vals[1],
        "hc": vals[2],
        "fail": bad,
        "dl": abs(float(D03.lstar(fd)) - float(D03.lstar(bd))),
        "protan": float(D03.de(D03.sim(fd, "protanopia"), D03.sim(bd, "protanopia"))),
        "deutan": float(D03.de(D03.sim(fd, "deuteranopia"), D03.sim(bd, "deuteranopia"))),
        "tritan": float(D03.de(D03.sim(fd, "tritanopia"), D03.sim(bd, "tritanopia"))),
        "hex": {
            "dark": fd,
            "light": fl,
            "hc": ev("high-contrast", fg),
            "grey": grey_hex(fd),
            "protan": str(D03.sim(fd, "protanopia")),
            "deutan": str(D03.sim(fd, "deuteranopia")),
            "bg_dark": bd,
            "bg_light": bl,
            "bg_grey": grey_hex(bd),
            "bg_protan": str(D03.sim(bd, "protanopia")),
            "bg_deutan": str(D03.sim(bd, "deuteranopia")),
            "light_grey": grey_hex(fl),
            "light_protan": str(D03.sim(fl, "protanopia")),
            "light_deutan": str(D03.sim(fl, "deuteranopia")),
            "bg_light_grey": grey_hex(bl),
            "bg_light_protan": str(D03.sim(bl, "protanopia")),
            "bg_light_deutan": str(D03.sim(bl, "deuteranopia")),
        },
    }


def carriers() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in E11.rows(CARRIER_TABLE):
        cid, state, surface, carrier, fg, bg, role = r
        m = measure(fg, bg, role)
        m.update(
            {
                "id": cid,
                "state": state,
                "surface": surface,
                "carrier": carrier,
                "fg": fg,
                "bg": bg,
                "role": role,
            }
        )
        m["colour_only"] = not re.search(
            r"icon/|word|\"|glyph|label|sentence|field|Retry|check|dot|tier|aria|reason", carrier
        )
        out.append(m)
    return out


def compositions() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in E11.rows(COMPOSITION_TABLE):
        cid, label, fg, bg, role = r
        m = measure(fg, bg, role)
        m.update({"id": cid, "label": label, "fg": fg, "bg": bg, "role": role})
        out.append(m)
    return out


def union_matrix() -> dict[str, Any]:
    under: list[str] = []
    per: dict[str, dict[str, int]] = {}
    total = gated = 0
    for element, fg, bg, role in D02.PAIRS:
        total += 1
        per.setdefault("E13-D02", {"rows": 0, "gated": 0})["rows"] += 1
        bar = BAR.get(role)
        if bar is None:
            continue
        gated += 1
        per["E13-D02"]["gated"] += 1
        for th in ("high-contrast",) if role == "hc-text" else THEMES:
            r = ratio(str(D02.col(th, fg)), str(D02.col(th, bg)))
            if r < bar:
                under.append(f"E13-D02 | {element} | {fg} on {bg} | {th} | {fmt(r)} < {bar}")
    for element, fg, bg, role in D03.PAIRS:
        total += 1
        per.setdefault("E13-D03", {"rows": 0, "gated": 0})["rows"] += 1
        bar = BAR.get(role)
        if bar is None:
            continue
        gated += 1
        per["E13-D03"]["gated"] += 1
        for th in ("high-contrast",) if role == "hc-text" else THEMES:
            r = ratio(str(D03.key_hex(th, fg, 0.0)), str(D03.key_hex(th, bg, 0.0)))
            if r < bar:
                under.append(f"E13-D03 | {element} | {fg} on {bg} | {th} | {fmt(r)} < {bar}")
    return {"rows": total, "gated": gated, "under": under, "per_spec": per}


# --------------------------------------------------------------------------- 4. targets (R6b)
# id | surface | density | w | h | spec. A dimension is a primitive token name or "typed:<px>";
# "full" / "pill" / "-" are not dimensions. "not a target" rows are informational.
TARGET_TABLE = """
TG-01 | SCR-034 option row (two-line) | compact | full | typed:48 | D02 :62
TG-02 | SCR-034 option row (two-line) | comfortable | full | typed:56 | D02 :62
TG-03 | SCR-034 search field, category tab, footer button | compact | - | size.control.compact
  | D02 :61
TG-04 | SCR-034 search field, category tab, footer button | comfortable | -
  | size.control.comfortable | D02 :61
TG-05 | SCR-034 star; stepper + / -; tree eye / lock / menu | compact | size.control.compact
  | size.control.compact | D02 :67, :439
TG-06 | the same icon buttons | comfortable | size.control.comfortable | size.control.comfortable
  | D02 :67
TG-07 | SCR-036 tree row | compact | full | size.row.compact | D02 :67
TG-08 | SCR-036 tree row | comfortable | full | size.row.comfortable | D02 :67
TG-09 | CMP-199 legend row and its eye | compact / dense | size.control.compact | size.row.compact
  | D02 :69; handoff :168
TG-10 | CMP-199 legend row (32) with its 24 x 24 eye | comfortable | size.control.compact
  | size.row.comfortable | handoff :167
TG-11 | CMP-224 count chip hit box (20 px pill + 2 + 2) | compact | pill | size.target.min | D02 :70
TG-12 | CMP-224 count chip (24 px pill) | comfortable | pill | size.target.min | handoff :170
TG-13 | toast Undo | compact | - | size.control.compact | D02 :439
TG-14 | bulk-action bar buttons (the bar itself 32 / 40, typed) | compact | -
  | size.control.compact | D02 :68
TG-15 | swatch radio (the 16 x 16 tile and the 8 x 8 swatch are not targets) | every | typed:24
  | typed:24 | D03 :92
TG-16 | blocked-removal row actions | compact | - | size.control.compact | D02 :72
TG-17 | SCR-035 field row control | compact | - | size.control.compact | D02 :65
TG-18 | legend "+N more" button | compact | - | size.row.compact | E11-D02 D12 :119
TG-19 | drawer Close / Filter | compact | size.control.compact | size.control.compact | D02 :215
TG-20 | the 8 x 8 shape swatch (not a target; informational) | every | typed:8 | typed:8 | D02 :69
"""


def px(expr: str) -> tuple[str, int | None]:
    expr = expr.strip()
    if expr in ("full", "pill", "-"):
        return expr, None
    if expr.startswith("typed:"):
        return f"typed {expr[6:]}", int(expr[6:])
    v = D03.T["dark"].get(expr)
    if v is None:
        return f"{expr} (no such token)", None
    return f"{expr} {v}", int(str(v))


def target_rows() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in E11.rows(TARGET_TABLE):
        tid, surface, density, w, h, spec = r
        wl, wv = px(w)
        hl, hv = px(h)
        dims = [v for v in (wv, hv) if v is not None]
        informational = "not a target" in surface
        typed = any(x.startswith("typed") for x in (wl, hl))
        no_token = any("no such token" in x for x in (wl, hl))
        ok = informational or (bool(dims) and min(dims) >= 24)
        out.append(
            {
                "id": tid,
                "surface": surface,
                "density": density,
                "w": wl,
                "h": hl,
                "min": min(dims) if dims else None,
                "typed": typed,
                "no_token": no_token,
                "informational": informational,
                "ok": ok,
                "spec": spec,
            }
        )
    return out


# --------------------------------------------------------------------- 5. the review's tables
def d02_copy_deck() -> str:
    text = D02_PATH.read_text(encoding="utf-8")
    body = text.split("## 12. Copy deck", 1)[1].split("## 13.", 1)[0]
    return re.sub(r"\s+", " ", body.replace("\u00a0", " "))


def unquote(cell: str) -> list[str]:
    """The quoted strings of a cell (straight or curly quotes); the whole cell when none."""
    found = re.findall(r"[\"“]([^\"”]+)[\"”]", cell)
    return found or [cell.strip("`* ")]


# The sources every quoted string of the keyboard-contract (K), expected-rendering (R) and gated-
# control (T2) tables must come from, verbatim: the two merged specs and the handoff, the neighbours
# the review cites for names and reasons, and the plan documents. Read at the base.
SOURCE_FILES = (
    "docs/design/E13/E13-D02.md",
    "docs/design/E13/E13-D03.md",
    "docs/design/E13/E13-D03-handoff.md",
    "docs/design/E09/E09-D09.md",
    "docs/design/E11/E11-D02.md",
    "docs/design/E06/E06-D03.md",
    "docs/design/E14/E14-D02.md",
    "docs/plan/05-accessibility-standard.md",
    "docs/plan/14-screens-catalogue.md",
    "docs/plan/15-component-catalogue.md",
    "docs/plan/11-user-stories.md",
)
QUOTED_TABLES = ("K34", "K35", "K36", "KL", "TK", "R34", "R35", "R36", "RL", "T2")
QUOTE_MIN_CHARS = 12


def flat(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u2019", "'").replace('\\"', '"')
    return re.sub(r"\s+", " ", text)


def sources_text() -> str:
    return " ".join(flat((ROOT / p).read_text(encoding="utf-8")) for p in SOURCE_FILES)


def quoted_string_misses(spec: str) -> list[str]:
    """Quoted strings of >= QUOTE_MIN_CHARS in the K / R / T2 tables that no source carries.

    A quote with an ellipsis or a placeholder brace is an abbreviation, not a string, and is
    skipped; everything else is compared whitespace-folded against SOURCE_FILES at the base."""
    src = sources_text()
    misses: list[str] = []
    for pre in QUOTED_TABLES:
        for r in rows_with(spec, pre + r"-\d+"):
            for cell in r[1:]:
                for s in re.findall(r"[\"“]([^\"”]+)[\"”]", cell):
                    s2 = flat(s).strip()
                    if len(s2) < QUOTE_MIN_CHARS or "…" in s2 or "{" in s2:
                        continue
                    if s2 not in src:
                        misses.append(f"{r[0]}: {s!r}")
    return misses


def review_section(spec: str) -> dict[str, Any]:
    problems: list[str] = []
    out: dict[str, Any] = {}
    # keyboard contracts (R3): id, stop / element, role, name (source), keys, result, focus after
    for pre, key in (
        ("K34", "stops_scr034"),
        ("K35", "stops_scr035"),
        ("K36", "stops_scr036"),
        ("KL", "stops_legend"),
    ):
        rows = rows_with(spec, pre + r"-\d+")
        out[key] = len(rows)
        for r in rows:
            if len(r) < 10:
                problems.append(f"{r[0]}: {len(r)} cells, expected 10")
                continue
            if not r[2] or r[2] == "—":
                problems.append(f"{r[0]}: empty role cell")
            if not re.search(r"\d", r[3]):
                problems.append(f"{r[0]}: the name cell carries no source line")
            if not r[4] or not r[6]:
                problems.append(f"{r[0]}: empty keys or focus-after cell")
    out["tree_keys"] = len(rows_with(spec, r"TK-\d+"))
    # operations (R13): id, operation, tree path, legend path, result, announcement, verdict
    ops = rows_with(spec, r"OP-\d+")
    out["operations"] = len(ops)
    out["operations_with_tree_path"] = sum(1 for r in ops if len(r) > 2 and r[2] not in ("", "—"))
    # gestures (R5): id, gesture, surface, pointer form, keyboard path, equal capability, ...
    pg = rows_with(spec, r"PG-\d+")
    out["gestures"] = len(pg)
    out["gestures_blocking"] = sum(
        1 for r in pg if len(r) > 4 and (r[4] in ("", "—") or r[4].lower().startswith("none"))
    )
    out["gestures_partial"] = sum(
        1 for r in pg if len(r) > 5 and r[5].lower().startswith("partial")
    )
    # expected rendering (R4)
    for pre, key in (
        ("R34", "render_scr034"),
        ("R35", "render_scr035"),
        ("R36", "render_scr036"),
        ("RL", "render_legend"),
    ):
        out[key] = len(rows_with(spec, pre + r"-\d+"))
    # live-region routing (R7): id, event, source, region, politeness, cadence, throttled, class
    deck = d02_copy_deck()
    lr = rows_with(spec, r"LR-\d+")
    out["lr_rows"] = len(lr)
    out["lr_assertive"] = 0
    # AC 3's four events: a row must exist for each ("present"), and the row is "specified" only
    # when it carries a deck string and a politeness level -- a row whose string and politeness are
    # both "none" is present but not specified (the ticket asks for a string and a level).
    events = {"add": False, "remov": False, "error": False, "warm-up complete": False}
    specified = dict(events)
    with_politeness = dict(events)
    placeholders: list[str] = []
    for r in lr:
        if len(r) < 9:
            problems.append(f"{r[0]}: {len(r)} cells, expected 9")
            continue
        pol = r[4].split(",")[0].split("(")[0].strip().lower()
        if pol not in POLITENESS:
            problems.append(f"{r[0]}: politeness {r[4]!r} not in {POLITENESS}")
        if pol == "assertive":
            out["lr_assertive"] += 1
        has_string = r[8] not in ("", "—") and not r[8].lower().startswith("none")
        # A PROPOSED placeholder (the string the merged deck still lacks) is recorded, never a
        # deck string: the row must name its F id, and it never counts as "specified".
        placeholder = has_string and "PROPOSED" in r[8]
        if placeholder:
            placeholders.append(r[0])
            if not re.search(r"\bF-\d\d\b", r[8]):
                problems.append(f"{r[0]}: a PROPOSED placeholder string must name its F row")
        deck_ok = has_string and not placeholder
        if deck_ok:
            for s in unquote(r[8]):
                if re.sub(r"\s+", " ", s) not in deck:
                    problems.append(f"{r[0]}: string {s!r} is not in E13-D02 section 12")
                    deck_ok = False
        for ev_name in events:
            if ev_name in r[1].lower():
                events[ev_name] = True
                if pol in ("polite", "assertive", "label"):
                    with_politeness[ev_name] = True
                    if deck_ok:
                        specified[ev_name] = True
    out["events_present"] = sum(events.values())
    out["events_missing"] = [k for k, v in events.items() if not v]
    out["events_specified"] = sum(specified.values())
    out["events_unspecified"] = [k for k, v in specified.items() if not v]
    out["events_with_politeness"] = sum(with_politeness.values())
    out["lr_placeholders"] = len(placeholders)
    out["lr_placeholder_ids"] = placeholders
    # Every quoted string in the K / R / T2 tables is a source's, verbatim (the deck check widened).
    quote_misses = quoted_string_misses(spec)
    out["quoted_string_misses"] = quote_misses
    problems += [f"quoted string not in any source: {m}" for m in quote_misses]
    # T2 table (R8): id, control, gate class, form, what the spec says, verdict, finding. A row of a
    # non-gate class whose Form cell renders the control as T2 is an over-conversion candidate and
    # must carry an existing F id in its finding cell.
    t2 = rows_with(spec, r"T2-\d+")
    out["t2_rows"] = len(t2)
    by_class = {c: 0 for c in GATE_CLASSES}
    over: list[str] = []
    f_ids = {r[0].strip("`") for r in rows_with(spec, r"F-\d+")}
    for r in t2:
        if len(r) < 7:
            problems.append(f"{r[0]}: {len(r)} cells, expected 7")
            continue
        cls = r[2].split("(")[0].strip()
        if cls not in GATE_CLASSES:
            problems.append(f"{r[0]}: gate class {r[2]!r} not in the set")
            continue
        by_class[cls] += 1
        if cls in NOT_GATES and re.search(r"\bT2\b", r[3]):
            fid = re.search(r"F-\d+", r[6] or "")
            over.append(r[0])
            if not fid or fid.group(0) not in f_ids:
                problems.append(
                    f"{r[0]}: over-conversion candidate without an F row in the finding cell"
                )
    out["t2_by_class"] = by_class
    out["t2_overconversion_ids"] = over
    out["t2_overconversion_candidates"] = len(over)
    # focus moves, motion, plug-in, hand-offs, protocol tasks, boards
    fm = rows_with(spec, r"FM-\d+")
    out["focus_moves"] = len(fm)
    out["focus_data_driven"] = sum(1 for r in fm if len(r) > 3 and r[3].strip().lower() == "no")
    mr = rows_with(spec, r"MR-\d+")
    out["motion_rows"] = len(mr)
    out["motion_exceptions"] = sum(1 for r in mr if len(r) > 4 and r[4].strip().lower() == "no")
    pi = rows_with(spec, r"PI-\d+")
    out["plugin_rows"] = len(pi)
    out["plugin_gaps"] = sum(1 for r in pi if len(r) > 4 and r[4].strip().lower().startswith("gap"))
    out["handoffs"] = len(rows_with(spec, r"HO-\d+"))
    out["rt_tasks"] = len(rows_with(spec, r"R-T\d+"))
    out["km_rows"] = len(rows_with(spec, r"KM-\d+"))
    out["boards"] = len([r for r in rows_with(spec, r"0\d") if "PENDING" in " ".join(r)])
    # findings (R11): id, class, severity, clause, change, owner, target, consumer, evidence. One
    # owner and one target per row (the consumer column may name two stories); every F row whose
    # clause cell names a 05 clause id must be listed in that clause's finding cell (section 10.1).
    f_rows = rows_with(spec, r"F-\d+")
    sev = {"Blocking": 0, "Major": 0, "Minor": 0, "Info": 0}
    classes: dict[str, int] = {}
    clause_rows = {c: r for c in CLAUSES for r in rows_with(spec, re.escape(c) + r"`?\s*\|") if r}
    for r in f_rows:
        if len(r) < 9:
            problems.append(f"{r[0]}: {len(r)} cells, expected 9")
            continue
        s = r[2].strip()
        if s not in sev:
            problems.append(f"{r[0]}: severity {s!r}")
        else:
            sev[s] += 1
        classes[r[1]] = classes.get(r[1], 0) + 1
        if r[5] in ("", "—") or r[6] in ("", "—"):
            problems.append(f"{r[0]}: no owner or no target")
        elif E11._two_parties(r[5]) or E11._two_parties(r[6]):
            problems.append(f"{r[0]}: more than one owner or target")
        if r[7] in ("", "—"):
            problems.append(f"{r[0]}: no consumer named")
        for cid in re.findall(r"`([0-9]+\.[0-9]+(?:\.[0-9]+)?[ab]?)`", r[3]):
            row = clause_rows.get(cid)
            if row is None:
                problems.append(f"{r[0]}: clause {cid} is not a clause row")
            elif len(row) < 6 or r[0] not in row[5]:
                problems.append(f"{r[0]}: clause {cid}'s finding cell does not list it")
    out["f_rows"] = len(f_rows)
    out["f_by_severity"] = sev
    out["f_by_class"] = classes
    for pre, key in (
        ("A", "a_rows"),
        ("C", "c_rows"),
        ("G", "g_rows"),
        ("Q", "q_rows"),
        ("H", "h_rows"),
    ):
        rows = rows_with(spec, pre + r"-\d+")
        out[key] = len(rows)
        if pre == "H":
            for r in rows:
                if "(heuristic)" not in " ".join(r):
                    problems.append(f"{r[0]}: an H row without (heuristic)")
        if pre == "A":
            for r in rows:
                if len(r) < 3 or "`" not in r[1] or "§" not in r[1] + r[2]:
                    problems.append(f"{r[0]}: an A row without a file and a section")
    # fabricated AT phrases and hygiene
    hits = [
        p
        for p in E11.AT_PHRASES
        for m in re.finditer(p, spec)
        if "should announce" not in m.group(0)
    ]
    out["fabricated_at"] = len(hits)
    out["fabricated_at_hits"] = hits
    if E11.LOCAL_PATH.search(spec):
        problems.append("a local path in the review")
    if E11.PENPOT_HOST.search(spec):
        problems.append("a Penpot host in the review")
    mism = E11.table_cell_mismatches(spec)
    out["table_cell_mismatches"] = len(mism)
    problems += [f"table row off its header: {m}" for m in mism]
    out["problems"] = problems
    return out


def check_numeric_rows(
    spec: str, prefix: str, computed: list[dict[str, Any]], fields: list[tuple[int, str, int]]
) -> list[str]:
    """Compare the review's SC / CP cells with the tool's values: (cell index, key, decimals)."""
    errs: list[str] = []
    by_id = {c["id"]: c for c in computed}
    for r in rows_with(spec, prefix + r"-\d+"):
        c = by_id.get(r[0].strip("`"))
        if c is None:
            errs.append(f"{r[0]}: not a row the tool computes")
            continue
        for idx, key, dec in fields:
            if idx >= len(r):
                errs.append(f"{r[0]}: missing cell {idx}")
                continue
            want = c[key]
            got = r[idx].strip()
            exp = f"{float(want):.{dec}f}" if isinstance(want, float) else str(want)
            if got != exp:
                errs.append(f"{r[0]} cell {idx}: {got!r} vs the tool's {exp!r}")
    return errs


# --------------------------------------------------------------------------- counts, json, check
def build(spec_path: Path | None) -> dict[str, Any]:
    items = items_05()
    km = keymap_section()
    car = carriers()
    comp = compositions()
    union = union_matrix()
    targets = target_rows()
    problems: list[str] = []
    for key, (_a, _b, want) in SECTIONS_05.items():
        if items[key] != want:
            problems.append(f"05 section {key}: {items[key]} items at the base, expected {want}")
    comp_fail = [c["id"] for c in comp if c["fail"]]
    # The ids behind each minimum and the light-theme non-text rows between 3:1 and 4.5:1 (the
    # glyphs whose text bar is met by the word beside them) -- printed so the review quotes ids the
    # tool found, not ids it remembered.
    min_protan = min(car, key=lambda c: float(c["protan"]))
    min_deutan = min(car, key=lambda c: float(c["deutan"]))
    min_dl = min(car, key=lambda c: float(c["dl"]))
    light_nontext = [
        c["id"] for c in car if c["role"] == "non-text" and 3.0 <= float(c["light"]) < 4.5
    ]
    counts: dict[str, Any] = {
        "clauses_expected": len(CLAUSES),
        "carriers_rows": len(car),
        "carriers_colour_only": sum(1 for c in car if c["colour_only"]),
        "carriers_min_protan": min(c["protan"] for c in car),
        "carriers_min_deutan": min(c["deutan"] for c in car),
        "carriers_min_dl": min(c["dl"] for c in car),
        "carriers_min_protan_id": min_protan["id"],
        "carriers_min_deutan_id": min_deutan["id"],
        "carriers_min_dl_id": min_dl["id"],
        "carriers_light_nontext_3_45": len(light_nontext),
        "carriers_light_nontext_3_45_ids": ", ".join(light_nontext),
        "composition_rows": len(comp),
        "composition_gated": sum(1 for c in comp if BAR.get(c["role"]) is not None),
        "composition_fail": len(comp_fail),
        "union_rows": union["rows"],
        "union_gated": union["gated"],
        "union_under": len(union["under"]),
        "union_d02_rows": union["per_spec"]["E13-D02"]["rows"],
        "union_d03_rows": union["per_spec"]["E13-D03"]["rows"],
        "target_rows": len(targets),
        "targets_below_24": sum(1 for t in targets if not t["ok"]),
        "targets_typed": sum(1 for t in targets if t["typed"]),
        "targets_no_token": sum(1 for t in targets if t["no_token"]),
        "shipped_commands": km["shipped_commands"],
        "shipped_bindings": km["shipped_bindings"],
        "reserved_entries": km["reserved_entries"],
        "reserved_raw": km["reserved_raw"],
        "hot_05_rows": km["hot_05_rows"],
        "design_literals": km["design_literals"],
        "design_bindings": km["design_bindings"],
        "typeahead_keys": km["typeahead_keys"],
        "sr_rows": km["sr_rows"],
        "sr_nvda": km["sr_nvda"],
        "sr_jaws": km["sr_jaws"],
        "sr_voiceover": km["sr_voiceover"],
        "sr_sources": km["sr_sources"],
        "objects_context_commands": km["objects_context_commands"],
        "objects_prefixed_commands": km["objects_prefixed_commands"],
        "conflicts_total": len(km["conflicts"]),
        "d25_undeclared": len(km["d25_undeclared"]),
        "d25_stale": len(km["d25_stale"]),
        "lint_errors": len(km["lint_errors"]),
        "ticks_per_window": 20 * 2,
        "cursor_per_s": int(1000 / 500),
        "ambient_per_window": 1,
        "jnd": JND,
    }
    for cls, n in sorted(km["conflicts_by_class"].items()):
        counts["conflicts_" + cls.replace("-", "_")] = n
    for cls, n in sorted(km["conflicts_by_class_typeahead"].items()):
        counts["conflicts_" + cls.replace("-", "_") + "_typeahead"] = n
    counts["conflict_classes"] = len(km["conflicts_by_class"])
    for rm, n in sorted(km["sr_hits_by_reader_mode"].items()):
        counts["sr_hits_" + rm.replace(" ", "_").replace("-", "_")] = n
    for k, v in items.items():
        counts["items_05_" + k.replace(".", "_")] = v
    rev: dict[str, Any] = {}
    cl: dict[str, Any] = {}
    if spec_path is not None and spec_path.exists():
        spec = spec_path.read_text(encoding="utf-8")
        cl = clause_section(spec)
        rev = review_section(spec)
        problems += cl["problems"] + rev["problems"]
        problems += check_numeric_rows(
            spec,
            "SC",
            car,
            [
                (5, "dark", 2),
                (6, "light", 2),
                (7, "hc", 2),
                (8, "dl", 1),
                (9, "protan", 1),
                (10, "deutan", 1),
            ],
        )
        problems += check_numeric_rows(
            spec, "CP", comp, [(5, "dark", 2), (6, "light", 2), (7, "hc", 2)]
        )
        counts.update(
            {
                "clauses_found": cl["found"],
                "verdict_compliant": cl["compliant"],
                "verdict_at_risk": cl["at_risk"],
                "verdict_non_compliant": cl["non_compliant"],
                "verdict_out_of_scope": cl["out_of_scope"],
                "verdict_routed": cl["routed"],
                "f_blocking": rev["f_by_severity"]["Blocking"],
                "f_major": rev["f_by_severity"]["Major"],
                "f_minor": rev["f_by_severity"]["Minor"],
                "f_info": rev["f_by_severity"]["Info"],
            }
        )
        for k in (
            "stops_scr034",
            "stops_scr035",
            "stops_scr036",
            "stops_legend",
            "tree_keys",
            "operations",
            "operations_with_tree_path",
            "gestures",
            "gestures_blocking",
            "gestures_partial",
            "render_scr034",
            "render_scr035",
            "render_scr036",
            "render_legend",
            "lr_rows",
            "lr_assertive",
            "events_present",
            "events_specified",
            "events_with_politeness",
            "lr_placeholders",
            "t2_rows",
            "t2_overconversion_candidates",
            "focus_moves",
            "focus_data_driven",
            "motion_rows",
            "motion_exceptions",
            "plugin_rows",
            "plugin_gaps",
            "handoffs",
            "rt_tasks",
            "km_rows",
            "boards",
            "f_rows",
            "a_rows",
            "c_rows",
            "g_rows",
            "q_rows",
            "h_rows",
            "fabricated_at",
            "table_cell_mismatches",
        ):
            counts[k] = rev[k]
        for cls, n in rev["t2_by_class"].items():
            counts["t2_" + cls.replace(" / ", "_").replace("-", "_")] = n
        if rev["events_missing"]:
            problems.append(
                "AC 3 events missing from the routing table: " + ", ".join(rev["events_missing"])
            )
        if rev["operations"] != 7 or rev["operations_with_tree_path"] != 7:
            problems.append(
                f"operations: {rev['operations']} rows, "
                f"{rev['operations_with_tree_path']} with a tree path (7 / 7 expected)"
            )
        if rev["tree_keys"] != 17:
            problems.append(f"tree keys: {rev['tree_keys']} rows (D25 has 17)")
        if rev["fabricated_at"]:
            problems.append("fabricated-AT phrases: " + "; ".join(rev["fabricated_at_hits"]))
        for cls, n in km["conflicts_by_class"].items():
            if n and not any(cls in " ".join(r) for r in rows_with(spec, r"KM-\d+")):
                problems.append(f"conflict class {cls} ({n}) has no KM resolution row")
    if comp_fail:
        problems.append("D05 composition FAIL: " + ", ".join(comp_fail))
    return {
        "counts": counts,
        "items_05": items,
        "clauses": cl,
        "review": rev,
        "keymap": km,
        "carriers": car,
        "compositions": comp,
        "union": union,
        "targets": targets,
        "problems": problems,
    }


def closing_keywords(text: str) -> list[str]:
    return [str(h) for h in E11.closing_keywords(text)]


def check_markers(spec_text: str, counts: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    seen = 0
    for m in re.finditer(r"<!--\s*audit:([A-Za-z0-9_]+)=([^\s>]+)\s*-->", spec_text):
        seen += 1
        name, val = m.group(1), m.group(2)
        if name not in counts:
            errs.append(f"marker {name}: no such number in the tool")
            continue
        want = counts[name]
        exp = fmt(want) if isinstance(want, float) else str(want)
        got = fmt(float(val)) if isinstance(want, float) else str(val)
        if got != exp:
            errs.append(f"marker {name}={val}: the tool computes {exp}")
    required = (
        "clauses_found",
        "f_rows",
        "conflicts_total",
        "carriers_rows",
        "carriers_colour_only",
        "composition_rows",
        "composition_fail",
        "union_rows",
        "union_under",
        "operations",
        "gestures",
        "gestures_blocking",
        "tree_keys",
        "t2_rows",
        "target_rows",
        "targets_below_24",
        "lint_errors",
        "sr_rows",
        "lr_rows",
        "events_present",
        "events_specified",
        "t2_overconversion_candidates",
        "fabricated_at",
        "boards",
        "design_bindings",
    )
    for r in required:
        if not re.search(rf"<!--\s*audit:{r}=", spec_text):
            errs.append(f"required marker missing: {r}")
    if not seen:
        errs.append("no audit markers in the review")
    return errs


def render_report(d: dict[str, Any]) -> str:
    c, km, cl, rv, u = d["counts"], d["keymap"], d["clauses"], d["review"], d["union"]
    out: list[str] = ["# E13-D05 accessibility design review audit", ""]
    items = " / ".join(f"{k} {v}" for k, v in d["items_05"].items())
    out.append(
        f"05 items at the base: {items}; review clause ids expected {c['clauses_expected']}."
    )
    if cl:
        out.append(
            f"clauses: {cl['expected']} expected / {cl['found']} found / "
            f"{cl['compliant']} compliant / {cl['at_risk']} at risk / "
            f"{cl['non_compliant']} non-compliant / {cl['out_of_scope']} out of scope / "
            f"{cl['routed']} routed"
        )
    if rv:
        out.append(
            f"stops: SCR-034 {rv['stops_scr034']} / SCR-035 {rv['stops_scr035']} / "
            f"SCR-036 {rv['stops_scr036']} / legend {rv['stops_legend']}; "
            f"tree keys {rv['tree_keys']}"
        )
        out.append(
            f"operations: {rv['operations']} / {rv['operations_with_tree_path']} with a tree path"
        )
        out.append(
            f"gestures: {rv['gestures']} rows / {rv['gestures_blocking']} Blocking / "
            f"{rv['gestures_partial']} partial"
        )
        out.append(
            f"events: {rv['events_present']} of 4 present "
            f"(missing: {rv['events_missing'] or 'none'}); "
            f"{rv['events_specified']} of 4 specified with a string and a politeness "
            f"(unspecified: {rv['events_unspecified'] or 'none'}); "
            f"{rv['events_with_politeness']} of 4 with a politeness; "
            f"placeholders {rv['lr_placeholders']} {rv['lr_placeholder_ids']};"
            f" routing rows {rv['lr_rows']}, assertive {rv['lr_assertive']}"
        )
        out.append(
            f"T2 rows: {rv['t2_rows']} by class {rv['t2_by_class']}; "
            f"over-conversion candidates {rv['t2_overconversion_candidates']} "
            f"{rv['t2_overconversion_ids']}"
        )
        out.append(
            f"quoted strings in the K / R / T2 tables not in any source: "
            f"{len(rv['quoted_string_misses'])}"
        )
        out.append(
            f"F rows: {rv['f_rows']} {rv['f_by_severity']}; A {rv['a_rows']} C {rv['c_rows']} "
            f"G {rv['g_rows']} Q {rv['q_rows']} H {rv['h_rows']}"
        )
        out.append(
            f"fabricated-AT phrases: {rv['fabricated_at']}; "
            f"table rows off their header: {rv['table_cell_mismatches']}"
        )
    out += ["", "## Carriers (per theme; grey dL*; protan / deutan / tritan dE76)", ""]
    out.append(
        "| id | state | fg on bg | role | dark | light | hc | dL* "
        "| protan | deutan | tritan | colour-only |"
    )
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in d["carriers"]:
        head = f"| {r['id']} | {r['state']} | `{r['fg']}` on `{r['bg']}` | {r['role']} "
        nums = f"| {fmt(r['dark'])} | {fmt(r['light'])} | {fmt(r['hc'])} | {fmt1(r['dl'])} "
        cvd = f"| {fmt1(r['protan'])} | {fmt1(r['deutan'])} | {fmt1(r['tritan'])} "
        out.append(head + nums + cvd + f"| {'yes' if r['colour_only'] else 'no'} |")
    out += [
        "",
        (
            f"carriers: {c['carriers_rows']} rows / {c['carriers_colour_only']} colour-only; "
            f"minimum dL* {fmt(c['carriers_min_dl'])} ({c['carriers_min_dl_id']}), "
            f"protan dE {fmt(c['carriers_min_protan'])} ({c['carriers_min_protan_id']}), "
            f"deutan dE {fmt(c['carriers_min_deutan'])} ({c['carriers_min_deutan_id']}); "
            f"light non-text rows between 3:1 and 4.5:1: {c['carriers_light_nontext_3_45']} "
            f"({c['carriers_light_nontext_3_45_ids']})"
        ),
        "",
    ]
    out += [
        "## D05 composition rows",
        "",
        "| id | composition | role | dark | light | hc | verdict |",
    ]
    out.append("|---|---|---|---|---|---|---|")
    for r in d["compositions"]:
        v = "PASS" if not r["fail"] else "FAIL: " + ", ".join(r["fail"])
        if BAR.get(r["role"]) is None:
            v = f"{r['role']} (not gated)"
        nums = f"{fmt(r['dark'])} | {fmt(r['light'])} | {fmt(r['hc'])}"
        out.append(f"| {r['id']} | {r['label']} | {r['role']} | {nums} | {v} |")
    out.append("")
    under = "" if not u["under"] else "\n" + "\n".join("- " + x for x in u["under"])
    out.append(
        f"union: {u['rows']} rows ({u['per_spec']}) / {u['gated']} gated / "
        f"{len(u['under'])} under their bar" + under
    )
    out += [f"D05 composition FAIL: {c['composition_fail']}", "", "## Targets", ""]
    for t in d["targets"]:
        state = "ok" if t["ok"] else "BELOW 24"
        typed = " (typed)" if t["typed"] else ""
        out.append(
            f"- {t['id']} {t['surface']} ({t['density']}): {t['w']} x {t['h']} -> {state}{typed}"
        )
    out.append(
        f"targets: {c['target_rows']} rows / {c['targets_below_24']} below 24 / "
        f"{c['targets_typed']} typed / {c['targets_no_token']} unknown tokens"
    )
    out += ["", "## Key map", ""]
    out.append(
        f"shipped {c['shipped_commands']} commands / {c['shipped_bindings']} bindings; "
        f"reserved {c['reserved_raw']} raw / {c['reserved_entries']} expanded; "
        f"05 rows {c['hot_05_rows']}; "
        f"design literals {c['design_literals']} -> {c['design_bindings']} atomic bindings "
        f"(type-ahead {c['typeahead_keys']} keys); fixture {c['sr_rows']} rows; "
        f"Objects-context commands shipped {c['objects_context_commands']}; "
        f"lint_keymap errors (shipped): {c['lint_errors']}"
    )
    out.append(
        f"conflicts: {c['conflicts_total']} total in {c['conflict_classes']} classes "
        f"{km['conflicts_by_class']}; on the tree's type-ahead keys "
        f"{km['conflicts_by_class_typeahead']}; screen-reader hits by reader and mode "
        f"{km['sr_hits_by_reader_mode']}"
    )
    for x in km["conflicts"]:
        out.append(f"- [{x['class']}] {x['a']}  vs  {x['b']}  ({x['contexts']}; {x['note']})")
    out.append("")
    out.append(
        f"D25 shadow column vs the registry: {c['d25_undeclared']} undeclared holders, "
        f"{c['d25_stale']} stale declarations"
    )
    for x in km["d25_undeclared"] + km["d25_stale"]:
        out.append("- " + x)
    out.append("")
    out.append(
        f"cadence: {c['ticks_per_window']} ticks per 2 s window at 20 Hz; the cursor region "
        f"{c['cursor_per_s']} per s while held (repeatWindow 500 ms); "
        f"ambient {c['ambient_per_window']} per 2 s per field (05 section 6.2)"
    )
    out += ["", "## Counts\n" + json.dumps(c, ensure_ascii=False, default=str), ""]
    out.append("PROBLEMS: " + ("; ".join(d["problems"]) if d["problems"] else "none"))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the reference machine's console is cp1252
    ap = argparse.ArgumentParser(description="E13-D05 accessibility design review audit")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", metavar="SPEC")
    ap.add_argument("--draft", metavar="DRAFT")
    args = ap.parse_args(argv)
    spec_path = Path(args.check) if args.check else SPEC_DEFAULT
    d = build(spec_path)
    if args.check:
        text = spec_path.read_text(encoding="utf-8")
        errs = check_markers(text, d["counts"])
        if args.draft:
            dt = Path(args.draft).read_text(encoding="utf-8")
            errs += [
                "closing keyword beside an issue number in the draft: " + h
                for h in closing_keywords(dt)
            ]
            if E11.LOCAL_PATH.search(dt) or E11.PENPOT_HOST.search(dt):
                errs.append("local path or Penpot host in the draft")
        d["problems"] += errs
    rc = 1 if d["problems"] else 0
    if args.json:
        slim = {k: v for k, v in d.items() if k != "keymap"}
        slim["keymap"] = {k: v for k, v in d["keymap"].items() if k != "by_id"}
        print(json.dumps(slim, ensure_ascii=False, indent=1, default=str))
    else:
        print(render_report(d))
        if args.check:
            print(f"--check: {len(d['problems'])} problem(s)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
