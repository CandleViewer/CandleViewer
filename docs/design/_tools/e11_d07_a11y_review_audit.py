"""E11-D07 accessibility design review audit: every number the review quotes, from the repo.

Offline, stdlib only beyond the repo modules it imports (``python3 -I`` from the repo root).
It imports five lane tools and two repo scripts and executes no other repo code: the token loader
``packages/ui/tokens/tests/verify_tokens.py``, ``docs/design/_tools/contrast_check.py``
(``contrast_ratio()``), ``docs/research/_tools/cvd_simulate.py`` (Brettel / Vienot ``simulate()``
and ``delta_e76()``), the four upstream contrast tools ``e11_d02_chassis_audit.py``,
``e11_d03_scales_audit.py``, ``e11_d04_table_audit.py``, ``e11_d05_ds_audit.py`` (their ``PAIRS``
and ``col()``), ``e11_d06_motion_audit.py`` (its ``ROWS`` and ``col()``) and
``scripts/keymap_lint.py`` (``normalise``, ``expand``, ``lint_keymap``). Nothing is re-implemented,
so every ratio agrees with E11-D02..D06's to the hundredth. No network call is made and no URL
literal exists in this file. The greyscale luma uses the coefficients of ``cvd_sim.py``
(0.299 / 0.587 / 0.114, floored); that script needs numpy and PIL, which the reference host lacks,
so the formula is applied here in plain arithmetic and said so.

Sections (each row names its source so a reviewer can re-grep it):

1. The clause inventory: the ``05`` section 6 bullets at the base beside the review's 43 clause
   ids (R1), and the review's verdict table parsed from ``docs/design/E11/E11-D07.md`` (every id
   once, a verdict from the fixed vocabulary, evidence, and an owner + target on every ``at risk``
   / ``non-compliant`` row).
2. The key-map matrix (R4): the shipped ``apps/web/src/keymap/keymap.json`` (ranges expanded), the
   ``05`` section 3.2 table parsed as text, the design bindings typed from the five specs with
   their source line, ``reserved-keys.json`` plus the ``05`` section 3.3 item 4 four, and the
   screen-reader fixture ``e11_d07_sr_reserved_keys.json`` (NVDA / JAWS / VoiceOver rows pinned
   from vendor documentation by hpe-worker-1; its limits are stated in the review). Classes:
   same-context collision, cross-context shadow of Global / Workspace, reserved without an
   override, screen-reader hit (table-mode chord, browse-mode single key, VO chord, SRKEY),
   ``05`` row contradicted by the registry, and the ``Alt+<letter>`` family (conditional on
   E11-D01 O13). ``lint_keymap()`` runs on the shipped file (expected 0 errors). A free-key list
   for the Chart context is printed for the review's resolutions.
3. The composed contrast matrix (R7): the union of the five upstream pair lists re-measured over
   dark / light / high-contrast (bars text 4.5, non-text 3, hc-text 7, compared unrounded), then
   the D07 composition rows as composite colours (the stale dim as the x0.85 channel multiply
   E11-D02 section 10 states; the D10 core over its halo; the ring over every surface it can land
   on), CVD distance (ΔE76, JND 5.0) for the new composed pairs, and the greyscale luma of every
   stacked token. Only a D07 composition row under its bar is a gated FAIL.
4. The channel-reuse table: E11-D05 section 7's registry ids and the token-meaning pairs the five
   specs bind, one meaning per channel per surface.
5. The target table (R6): every interactive surface with its token resolved from
   ``primitives.tokens.json``, or marked as a typed number with no token.
6. The reduced-motion table (R8): E11-D06 section 7 parsed from the spec (47 rows), the reduce
   variant classified per row, the section 9.3 flash rates re-checked against 3/s, the section
   9.4 under-reduce column, and the override's entry points.
7. The numbers block: node counts, ticks per ambient window, the cursor cap, the mirror slice, the
   table's scripting budget and the footprint column-set text compare.
8. String gates on the review (and on the PR draft with ``--draft``): no fabricated-AT phrase, no
   ``display:none`` recommended for the mirror, every H row ``(heuristic)``, every F row with an
   owner and a target, every A row with a file and a section, no local path, no Penpot host
   (a generic pattern that names no domain), no closing keyword beside an issue number.

Usage:
  python3 -I docs/design/_tools/e11_d07_a11y_review_audit.py            Markdown report
  ... --json                                                            one object for the boards
  ... --check docs/design/E11/E11-D07.md [--draft <file>]                re-derive every marker
  ... --figures docs/design/E11/img                                      render the two PNGs
Exit 1 only on a gated FAIL (a D07 composition pair under its bar, a verdict row missing or
malformed, an F row without owner / target, a fabricated-AT phrase, a ``--check`` drift).
Stdout is forced to UTF-8.
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
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
DESIGN = ROOT / "docs" / "design"
TOOLS = DESIGN / "_tools"
SPEC_DEFAULT = DESIGN / "E11" / "E11-D07.md"
FIXTURE = TOOLS / "e11_d07_sr_reserved_keys.json"
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float] = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
# The imported lane tools are untyped modules: every attribute below is Any at this boundary.
verify: Any = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check: Any = _load(TOOLS / "contrast_check.py", "contrast_check")
cvd: Any = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")
keymap_lint: Any = _load(ROOT / "scripts" / "keymap_lint.py", "keymap_lint")
SIBLINGS: dict[str, Any] = {
    "E11-D02": _load(TOOLS / "e11_d02_chassis_audit.py", "e11_d02_chassis_audit"),
    "E11-D03": _load(TOOLS / "e11_d03_scales_audit.py", "e11_d03_scales_audit"),
    "E11-D04": _load(TOOLS / "e11_d04_table_audit.py", "e11_d04_table_audit"),
    "E11-D05": _load(TOOLS / "e11_d05_ds_audit.py", "e11_d05_ds_audit"),
    "E11-D06": _load(TOOLS / "e11_d06_motion_audit.py", "e11_d06_motion_audit"),
}


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(hex_to_rgb(fg), hex_to_rgb(bg)))


def fmt(v: float) -> str:
    return f"{v:.2f}"


def resolve_theme(name: str) -> dict[str, str]:
    prim = verify.load(verify.PRIMITIVES)
    allt = dict(prim)
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {
        k: str(verify.resolve(v["$value"], allt))
        for k, v in allt.items()
        if v.get("$type") == "color"
    }


T: dict[str, dict[str, str]] = {n: resolve_theme(n) for n in THEMES}


def primitives() -> dict[str, Any]:
    out: dict[str, Any] = {}

    def walk(d: dict[str, Any], pre: str) -> None:
        for k, v in d.items():
            if isinstance(v, dict) and "$value" in v:
                out[pre + k] = v["$value"]
            elif isinstance(v, dict):
                walk(v, pre + k + ".")

    walk(verify.load(verify.PRIMITIVES), "")
    return out


PRIM = primitives()


def dim85(h: str) -> str:
    """The stale state's data-ink x0.85 (E11-D02 section 10: a uniform multiply, no scrim)."""
    r, g, b = hex_to_rgb(h)
    return rgb_to_hex((int(r * 0.85), int(g * 0.85), int(b * 0.85)))


def luma(h: str) -> int:
    """Greyscale luma with cvd_sim.py's coefficients (0.299 / 0.587 / 0.114), floored."""
    r, g, b = hex_to_rgb(h)
    return int(0.299 * r + 0.587 * g + 0.114 * b)


# --------------------------------------------------------------------------- 1. clauses (R1)
# The review's clause ids: `05` section 6 (23) + the ticket's extra clauses (16) + two NFRs + two
# `06` rows = 43. The wording is derived from `05` at the base, never from this list.
CLAUSES: list[str] = (
    [f"6.1{c}" for c in "abcdefgh"]
    + [f"6.2{c}" for c in "abcd"]
    + [f"6.3{c}" for c in "abcdefghi"]
    + ["6.4a", "6.4b"]
    + ["3.1.6", "3.1.7", "3.4.2", "3.4.3", "3.4.6", "3.4.7", "3.4.8"]
    + ["4.1", "4.3", "5.2", "5.4", "5.7", "7.1", "7.2", "7.3", "7.4"]
    + ["US-CHART-008 NFR", "US-CHART-014 NFR", "06 §4.3", "06 §4.4"]
)
VERDICTS = (
    "compliant",
    "at risk",
    "non-compliant",
    "out of scope — E19",
    "out of scope — E21",
    "not yet decidable — routed to E11-Q05",
)
# Expected `05` section 6 bullet counts between the `### 6.n` headings at the base.
BULLETS_EXPECTED = {"6.1": 4, "6.2": 2, "6.3": 6, "6.4": 2}

# --------------------------------------------------------------------------- 2. key map (R4)
# (key, context, stop, action, source file, line). Stops: "*" = a chord live anywhere in its
# context; a named stop is a focus-scoped key (05 section 3.3 item 1(3): mutually exclusive).
D02 = "docs/design/E11/E11-D02.md"
D03 = "docs/design/E11/E11-D03.md"
D04 = "docs/design/E11/E11-D04.md"
E06 = "docs/design/E06/E06-D03.md"
P26 = "docs/plan/26-chart-engine-design.md"
P05 = "docs/plan/05-accessibility-standard.md"
P14 = "docs/plan/14-screens-catalogue.md"
E14 = "docs/design/E14/E14-D02.md (head a12cb2ac, in flight)"
SRC = {
    "D02": D02,
    "D03": D03,
    "D04": D04,
    "E06": E06,
    "P26": P26,
    "P05": P05,
    "P14": P14,
    "E14": E14,
}
# key | context | stop | action | source | line. "*" = a chord live anywhere in its context; a
# named stop is a focus-scoped key (05 section 3.3 item 1(3): mutually exclusive).
DESIGN_TABLE = """
← | Chart | plot | cursor one bar back | E06 | 107
→ | Chart | plot | cursor one bar forward | E06 | 107
Shift+← | Chart | plot | cursor ten bars back | E06 | 107
Shift+→ | Chart | plot | cursor ten bars forward | E06 | 107
PageUp | Chart | plot | the ten-bar alias (replay-safe) | D02 | 322
PageDown | Chart | plot | the ten-bar alias (replay-safe) | D02 | 322
↑ | Chart | plot | cursor one price level up | E06 | 107
↓ | Chart | plot | cursor one price level down | E06 | 107
Home | Chart | plot | oldest loaded bar | E06 | 107
End | Chart | plot | latest bar, resume follow | E06 | 107
Enter | Chart | plot | expand the cursor bar's cells in the mirror | E06 | 107
Esc | Chart | plot | collapse the detail; not consumed when nothing is open | E06 | 107
+ | Chart | plot | zoom in (viewport, no announcement) | P26 | 279
- | Chart | plot | zoom out (viewport, no announcement) | P26 | 279
Space | Chart | plot | pan-drag modifier (not consumed in replay) | P26 | 279
Alt+← | Chart | plot | step tick in replay (26's row) | P26 | 279
Alt+→ | Chart | plot | step tick in replay (26's row) | P26 | 279
Ctrl+Shift+↑ | Chart | plot | PROPOSED here: cursor level to the bar's high | D04 | 0
Ctrl+Shift+↓ | Chart | plot | PROPOSED here: cursor level to the bar's low | D04 | 0
Alt+T | Chart | * | toggle Chart / Table (global handler) | D04 | 143
Alt+G | Chart | * | go to date (conditional on E11-D01 O13) | D03 | 367
Ctrl+Shift+G | Chart | * | go to date (the O13 fallback) | D03 | 367
Ctrl+Shift+D | Chart | * | SCR-046 diagnostics overlay | D02 | 383
Ctrl+\\ | Chart | * | leave the chart region (05 region cycle) | D02 | 654
Ctrl+Alt+1..9 | Chart | * | SCR-049: focus sub-chart n | P14 | 1072
Alt+C | Chart | * | cycle chart type (05 row, unregistered) | P05 | 54
Alt+↑ | Chart | * | cycle timeframe (05 row, unregistered) | P05 | 55
Alt+↓ | Chart | * | cycle timeframe (05 row, unregistered) | P05 | 55
H | Chart | * | toggle heatmap overlay (05 row, unregistered) | P05 | 56
P | Chart | * | toggle profile overlay (05 row, unregistered) | P05 | 56
Alt+1..4 | Chart | * | drawing tools (05 row; dead under Global Alt+1..9) | P05 | 58
Backspace | Chart | * | delete selected drawing (05 row; shipped is Del) | P05 | 59
↑ | Chart | price-axis | compress the scale 10 % | D02 | 254
↓ | Chart | price-axis | expand the scale 10 % | D02 | 254
Shift+↑ | Chart | price-axis | compress 25 % | D02 | 255
Shift+↓ | Chart | price-axis | expand 25 % | D02 | 255
PageUp | Chart | price-axis | shift the range up 50 % | D02 | 256
PageDown | Chart | price-axis | shift the range down 50 % | D02 | 256
Home | Chart | price-axis | auto-fit (restore autoscale) | D02 | 257
Shift+F10 | Chart | price-axis | SCR-043 price-scale menu | D02 | 258
Esc | Chart | price-axis | back to the plot cursor | D02 | 259
Enter | Chart | lock-badge | restore autoscale | D02 | 261
Space | Chart | lock-badge | restore autoscale | D02 | 261
← | Chart | time-axis | pan 10 % of the width | D02 | 283
→ | Chart | time-axis | pan 10 % of the width | D02 | 283
Shift+← | Chart | time-axis | pan one width | D02 | 283
Shift+→ | Chart | time-axis | pan one width | D02 | 283
+ | Chart | time-axis | bar spacing x1.1 | D02 | 285
- | Chart | time-axis | bar spacing /1.1 | D02 | 285
Home | Chart | time-axis | fit every loaded bar | D02 | 286
End | Chart | time-axis | latest bar, follow resumes | D02 | 287
Ctrl+Home | Chart | time-axis | reset bar spacing | D02 | 288
Shift+F10 | Chart | time-axis | SCR-043 time-scale menu | D02 | 289
Esc | Chart | time-axis | back to the plot cursor | D02 | 290
← | Chart | cluster | previous segment | D02 | 291
→ | Chart | cluster | next segment | D02 | 291
Enter | Chart | cluster | activate the segment | D02 | 292
Space | Chart | cluster | activate the segment | D02 | 292
↑ | Chart | legend | previous row | D02 | 345
↓ | Chart | legend | next row | D02 | 345
← | Chart | legend | previous control in the row | D02 | 345
→ | Chart | legend | next control in the row | D02 | 345
Space | Chart | legend | toggle visibility | D02 | 345
Enter | Chart | legend | toggle visibility / open +N more | D02 | 345
Esc | Chart | legend | back to the plot | D02 | 345
← | Chart | chips | previous chip | D02 | 667
→ | Chart | chips | next chip | D02 | 667
Enter | Chart | chips | open the chip's details | D02 | 667
Esc | Chart | chips | dismiss the tooltip, then the last-focused plot | D02 | 667
↑ | Chart | splitter | boundary up 2 % | D02 | 361
↓ | Chart | splitter | boundary down 2 % | D02 | 361
Shift+↑ | Chart | splitter | boundary up 10 % | D02 | 362
Shift+↓ | Chart | splitter | boundary down 10 % | D02 | 362
Home | Chart | splitter | equal ratios | D02 | 363
End | Chart | splitter | pane above at maximum | D02 | 364
Esc | Chart | splitter | plot cursor of the pane above | D02 | 365
Enter | Chart | stub | restore / collapse the pane | D02 | 367
Space | Chart | stub | restore / collapse the pane | D02 | 367
Esc | Overlay | * | close the overlay | D02 | 383
Enter | Overlay | copy | copy diagnostics | D02 | 670
Space | Overlay | copy | copy diagnostics | D02 | 670
↑ | Grid | * | previous row (cursor origin table) | D04 | 507
↓ | Grid | * | next row | D04 | 507
← | Grid | * | previous cell / collapse | D04 | 508
→ | Grid | * | next cell / expand | D04 | 508
Home | Grid | * | first cell of the row (APG) | D04 | 509
End | Grid | * | last cell of the row (APG) | D04 | 509
Ctrl+Home | Grid | * | first row; raises a history page at the edge | D04 | 510
Ctrl+End | Grid | * | last row; resumes follow-live | D04 | 510
PageUp | Grid | * | one visible page of rows | D04 | 511
PageDown | Grid | * | one visible page of rows | D04 | 511
Enter | Grid | * | expand the sub-table / open the drawer / cycle a sort | D04 | 512
Space | Grid | * | toggle selection / cycle a sort on a header | D04 | 515
Shift+↑ | Grid | * | extend the selection | D04 | 516
Shift+↓ | Grid | * | extend the selection | D04 | 516
Ctrl+A | Grid | * | select all loaded rows | D04 | 517
Ctrl+C | Grid | * | copy as TSV (the browser's) | D04 | 518
Shift+F10 | Grid | * | row-action menu | D04 | 519
Esc | Grid | * | menu > selection > sub-table > back to the chart | D04 | 520
Shift+R | Grid | * | refresh to current | D04 | 521
Alt+T | Grid | * | return to the chart (pure toggle) | D04 | 522
Alt+↑ | Picker | * | CMP-056 column reorder | D04 | 221
Alt+↓ | Picker | * | CMP-056 column reorder | D04 | 221
↑ | Menu | * | previous item | D03 | 459
↓ | Menu | * | next item | D03 | 459
Home | Menu | * | first item | D03 | 460
End | Menu | * | last item | D03 | 460
Enter | Menu | * | activate | D03 | 462
Space | Menu | * | activate | D03 | 462
Esc | Menu | * | close; focus returns to the opening stop | D03 | 463
Tab | Menu | * | close and move to the next stop | D03 | 464
Tab | Dialog | * | trapped cycle | D03 | 472
Enter | Dialog | * | Jump (in an input) | D03 | 475
Space | Dialog | * | toggle a segment / press a button | D03 | 476
Esc | Dialog | * | close the calendar, then the dialog | D03 | 477
PageUp | Dialog | * | calendar: by month | D03 | 474
PageDown | Dialog | * | calendar: by month | D03 | 474
Alt+L | Chart | * | E14: trendline (in flight) | E14 | 62
Alt+H | Chart | * | E14: horizontal line (in flight) | E14 | 62
Alt+O | Chart | * | E14: Fibonacci (in flight; (b) Alt+F) | E14 | 62
Alt+R | Chart | * | E14: rectangle (in flight) | E14 | 62
Alt+D | Chart | * | E14: measure (in flight) | E14 | 62
Ctrl+M | Chart | * | E14: magnet toggle (in flight) | E14 | 62
"""


def rows(text: str) -> list[list[str]]:
    """Parse a pipe-separated text table; two-space-indented lines continue the record above."""
    records: list[str] = []
    for ln in text.strip("\n").splitlines():
        if ln.startswith("  ") and records:
            records[-1] += " " + ln.strip()
        elif ln.strip():
            records.append(ln)
    return [[c.strip() for c in r.split("|")] for r in records]


DESIGN_BINDINGS: list[tuple[str, str, str, str, str, int]] = [
    (r[0], r[1], r[2], r[3], SRC[r[4]], int(r[5])) for r in rows(DESIGN_TABLE)
]
# `05` section 3.2 actions the shipped registry implements under another key (action -> command id).
HOT_05_IMPL: dict[str, str] = {
    "Toggle keyboard-hotkey cheat-sheet overlay": "global.cheatsheet",
    "Toggle sidebar / panel focus cycle": "workspace.panel_next",
    "Size preset 1-5": "ticket.qty_preset",
    "Toggle 1-click trading": "ticket.arm",
    "Delete selected drawing": "chart.delete_drawing",
    "Cancel all at focused row": "dom.cancel_all",
}
# `05` section 3.3 item 4's four blocklisted OS / Electron combos.
OS_FOUR = ("Ctrl+W", "Ctrl+Q", "Alt+F4", "Ctrl+N")
# Co-active focus contexts: Global and Workspace with everything; the chart's stops and the replay
# bar and the pinned diagnostics overlay can be live together; the table can be open in replay.
COACTIVE_SETS = ({"Chart", "Replay"}, {"Grid", "Replay"})
ALWAYS = {"Global", "Workspace"}
# Browse-mode single keys apply to any unmodified letter / digit binding that can be live while
# a document or table has focus (E06-D03 H4); table-mode chords and VO chords always.
SR_LIVE_MODES = {"browse", "table", "global", "quick-nav", "interact", "focus"}

LOCAL_KEYS = {
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pgup": "PageUp",
    "pagedown": "PageDown",
    "pgdn": "PageDown",
    "backspace": "Backspace",
    "insert": "Insert",
    "delete": "Del",
    "del": "Del",
    "esc": "Esc",
    "escape": "Esc",
    "enter": "Enter",
    "space": "Space",
    "tab": "Tab",
    "menu": "Menu",
}
MODS = ("Ctrl", "Alt", "Shift")


def nrm(raw: str) -> str:
    """keymap_lint.normalise() where it applies; a local canonical form for the tokens the repo
    normaliser leaves out on purpose (Home / End / PageUp / PageDown, SRKEY, Win, numpad)."""
    try:
        return str(keymap_lint.normalise(raw))
    except keymap_lint.KeymapError:
        parts = (
            [p for p in raw.replace("+", " + ").split() if p != "+"]
            if raw not in ("+", "-")
            else [raw]
        )
    mods: list[str] = []
    key = parts[-1] if parts else raw
    for p in parts[:-1]:
        m = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift"}.get(p.lower(), p)
        mods.append(m)
    k = LOCAL_KEYS.get(key.lower(), key if len(key) > 1 else key.upper())
    ordered = [m for m in MODS if m in mods] + [m for m in mods if m not in MODS]
    return "+".join([*ordered, k])


def expand_keys(raw: str) -> list[str]:
    try:
        return [str(x) for x in keymap_lint.expand(raw)]
    except keymap_lint.KeymapError:
        m = re.match(r"^(.*?)(\d)\.\.(\d)$", raw)
        if m:
            return [nrm(f"{m.group(1)}{d}") for d in range(int(m.group(2)), int(m.group(3)) + 1)]
        return [nrm(raw)]


def load_keymap() -> dict[str, Any]:
    with (ROOT / "apps/web/src/keymap/keymap.json").open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def shipped_bindings(km: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in km["commands"]:
        for b in expand_keys(c["defaultBinding"]):
            rows.append(
                {
                    "key": b,
                    "context": c["context"],
                    "id": c["id"],
                    "validWhen": c.get("validWhen", ""),
                    "shadows": [s.get("command") for s in c.get("shadows", []) or []],
                    "reservedOverride": bool(c.get("reservedOverride")),
                }
            )
    return rows


def load_reserved() -> dict[str, str]:
    with (ROOT / "apps/web/src/keymap/reserved-keys.json").open(encoding="utf-8") as fh:
        raw: dict[str, str] = json.load(fh)
    out: dict[str, str] = {}
    for k, why in raw.items():
        for b in expand_keys(k):
            out[b] = why
    for k in OS_FOUR:
        out.setdefault(nrm(k), "05 §3.3 item 4")
    return out


def parse_05_hotkeys() -> list[dict[str, str]]:
    """The `05` section 3.2 table as (category, action, keys[])."""
    text = (PLAN / "05-accessibility-standard.md").read_text(encoding="utf-8")
    body = text.split("### 3.2 Default hotkey map")[1].split("### 3.3")[0]
    rows: list[dict[str, str]] = []
    cat = ""
    for ln in body.splitlines():
        if not ln.startswith("|") or ln.startswith("| ---") or "Default key" in ln:
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[0]:
            cat = cells[0].strip("*")
        keys = re.findall(r"`([^`]+)`", cells[2])
        rows.append({"category": cat, "action": cells[1], "keys": " ".join(keys), "raw": cells[2]})
    return rows


def hotkey_05_keys(row: dict[str, str]) -> list[str]:
    out: list[str] = []
    for k in row["keys"].split():
        if k in ("?", "i.e.") or k.startswith("(") or k.endswith(")"):
            continue
        m = re.match(r"^(.*?)(\d)\.\.(\d)$", k)
        if m:
            out.extend(expand_keys(k))
            continue
        out.append(nrm(k.replace("Delete", "Del")))
    # `Ctrl+1`..`Ctrl+9` is written as two backticks
    if len(out) == 2 and re.match(r"^Ctrl\+1$", out[0]) and re.match(r"^Ctrl\+9$", out[1]):
        out = [f"Ctrl+{d}" for d in range(1, 10)]
    if len(out) == 2 and out[0] == "1" and out[1] == "5":
        out = [str(d) for d in range(1, 6)]
    return out


def load_fixture() -> dict[str, Any]:
    with FIXTURE.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def coactive(a: str, b: str) -> bool:
    if a == b or a in ALWAYS or b in ALWAYS:
        return True
    return any(a in s and b in s for s in COACTIVE_SETS)


def keymap_section() -> dict[str, Any]:
    km = load_keymap()
    shipped = shipped_bindings(km)
    reserved = load_reserved()
    hot = parse_05_hotkeys()
    fixture = load_fixture()
    sr_rows = fixture["keys"]
    sr_by_key: dict[str, list[dict[str, Any]]] = {}
    for r in sr_rows:
        sr_by_key.setdefault(str(r["norm"]), []).append(r)
    design: list[dict[str, Any]] = []
    for key, ctx, stop, action, src, line in DESIGN_BINDINGS:
        for b in expand_keys(key):
            design.append(
                {"key": b, "context": ctx, "stop": stop, "action": action, "src": src, "line": line}
            )
    by_id = {c["id"]: c for c in km["commands"]}
    conflicts: list[dict[str, Any]] = []

    def add(cls: str, a: str, b: str, ctx: str, note: str) -> None:
        conflicts.append({"class": cls, "a": a, "b": b, "contexts": ctx, "note": note})

    # (a) design vs design: same key, co-active contexts, same stop or a chord
    for i, x in enumerate(design):
        for y in design[i + 1 :]:
            if x["key"] != y["key"] or not coactive(x["context"], y["context"]):
                continue
            same_ctx = x["context"] == y["context"]
            if same_ctx and x["stop"] != "*" and y["stop"] != "*" and x["stop"] != y["stop"]:
                continue  # focus-scoped: mutually exclusive stops
            if same_ctx and x["stop"] == y["stop"] and x["action"] == y["action"]:
                continue
            if x["src"] == y["src"] and x["line"] == y["line"]:
                continue
            cls = "same-context" if same_ctx else "cross-context"
            add(
                cls,
                f"{x['key']} {x['context']}/{x['stop']}: {x['action']} ({x['src']}:{x['line']})",
                f"{y['key']} {y['context']}/{y['stop']}: {y['action']} ({y['src']}:{y['line']})",
                f"{x['context']} + {y['context']}",
                "two meanings on one key where both can be live",
            )
    # (b) design vs shipped registry
    apg = {"Enter", "Esc", "Space", "Tab", "←", "→", "↑", "↓", "Home", "End", "PageUp", "PageDown"}
    for x in design:
        for s in shipped:
            if x["key"] != s["key"]:
                continue
            if not coactive(x["context"], s["context"]):
                if x["key"] not in apg and x["context"] in ("Chart", "Grid", "Picker"):
                    add(
                        "reuse",
                        f"{x['key']} {x['context']}/{x['stop']}: {x['action']} "
                        f"({x['src']}:{x['line']})",
                        f"{s['key']} {s['context']}: {s['id']}",
                        f"{x['context']} | {s['context']} (disjoint)",
                        "keymap_lint: reciprocal shadows with a rationale at registration",
                    )
                continue
            if s["context"] in ALWAYS:
                cls = "shadow-global"
                note = (
                    f"shadows {s['context']} {s['id']} ({s['validWhen']}); "
                    "undeclared (unregistered)"
                )
            elif s["context"] == x["context"]:
                cls = "same-context"
                note = f"the shipped {s['id']} holds the key in {s['context']}"
            else:
                cls = "cross-context"
                note = (
                    f"{s['id']} ({s['context']}) is co-active; "
                    "needs a declared shadow at registration"
                )
            add(
                cls,
                f"{x['key']} {x['context']}/{x['stop']}: {x['action']} ({x['src']}:{x['line']})",
                f"{s['key']} {s['context']}: {s['id']}",
                f"{x['context']} + {s['context']}",
                note,
            )
    # (c) reserved without an override
    for x in design:
        if x["key"] in reserved:
            add(
                "reserved",
                f"{x['key']} {x['context']}/{x['stop']}: {x['action']} ({x['src']}:{x['line']})",
                f"reserved: {reserved[x['key']]}",
                x["context"],
                "a design binding on a reserved key with no reservedOverride",
            )

    # (d) screen-reader hits (fixture)
    def sr_hit(key: str, who: str) -> None:
        for r in sr_by_key.get(key, []):
            if r["mode"] not in SR_LIVE_MODES:
                continue
            single = re.fullmatch(r"(Shift\+)?([A-Z0-9]|[,;'/-])", key) is not None
            arrow = re.fullmatch(r"(Shift\+)?[←→↑↓]", key) is not None
            if r["mode"] == "table":
                kind = "sr-table"
            elif r["mode"] in ("browse", "quick-nav") and single:
                kind = "sr-browse"
            elif r["mode"] == "quick-nav" and arrow:
                kind = "sr-quicknav"
            elif "+" in key and not arrow:
                kind = "sr-chord"
            else:
                continue  # bare arrows / Esc / Enter in the SR's own reading modes: not a binding
            add(
                kind,
                who,
                f"{r['sr'].upper()} {r['mode']}: {r['keys']} = {r['function']} ({r['section']})",
                "AT",
                "consumed by the screen reader in that mode before the app sees it",
            )

    for x in design:
        sr_hit(
            x["key"],
            f"{x['key']} {x['context']}/{x['stop']}: {x['action']} ({x['src']}:{x['line']})",
        )
    for s in shipped:
        if s["context"] in ("Global", "Workspace", "Chart", "Replay"):
            sr_hit(s["key"], f"{s['key']} {s['context']}: {s['id']} (shipped)")
    # (e) `05` section 3.2 rows the registry contradicts, and unregistered rows
    shipped_keys = {s["key"] for s in shipped}
    design_keys = {d["key"] for d in design}
    unregistered_05: list[str] = []
    contradicted_05: list[str] = []
    for row in hot:
        keys = hotkey_05_keys(row)
        if not keys:
            continue
        label = f"{row['category']}: {row['action']} = {row['raw']}"
        impl = HOT_05_IMPL.get(row["action"].replace("\u2013", "-"))
        if impl:
            got = sorted({s["key"] for s in shipped if s["id"] == impl})
            if not set(keys) <= set(got):
                contradicted_05.append(f"{label} -> shipped {impl} {got}")
            continue
        if all(k in shipped_keys for k in keys):
            continue
        on_reserved = [k for k in keys if k in reserved]
        if on_reserved:
            contradicted_05.append(f"{label} -> on a reserved key: " + ", ".join(on_reserved))
        unregistered_05.append(label)
    # (f) the Alt+<letter> family (E11-D01 O13)
    alt_family = sorted(
        {d["key"] for d in design if re.fullmatch(r"Alt\+[A-Z]", d["key"])}
        | {s["key"] for s in shipped if re.fullmatch(r"Alt\+[A-Z]", s["key"])}
    )
    # unregistered design keys (specified, not in keymap.json)
    unregistered_design = sorted(
        {
            f"{d['key']} ({d['context']}/{d['stop']}, {d['src']}:{d['line']})"
            for d in design
            if d["key"] not in shipped_keys
            and d["context"] in ("Chart", "Grid")
            and d["stop"] in ("*", "plot")
            and not d["action"].startswith("E14")
            and d["key"] not in ("Esc", "Enter", "Space", "Tab", "←", "→", "↑", "↓")
        }
    )
    # free keys for the Chart context: single-modifier combos bound nowhere, reserved nowhere,
    # with no screen-reader row
    taken = shipped_keys | design_keys | set(reserved) | set(sr_by_key)
    letters = [chr(c) for c in range(65, 91)]
    free_single = [
        f"{m}+{k}" for m in ("Ctrl", "Alt", "Shift") for k in letters if f"{m}+{k}" not in taken
    ]
    free_double = [
        f"Ctrl+Shift+{k}" for k in [*letters, "←", "→", "↑", "↓"] if f"Ctrl+Shift+{k}" not in taken
    ]
    lint_errors = list(keymap_lint.lint_keymap(km))
    by_class: dict[str, int] = {}
    for c in conflicts:
        by_class[c["class"]] = by_class.get(c["class"], 0) + 1
    srk = fixture["keys"]
    sr_counts = {sr: sum(1 for r in srk if r["sr"] == sr) for sr in ("nvda", "jaws", "voiceover")}
    alt_t_rows = [r for r in srk if r["norm"] == "Alt+T"]
    return {
        "shipped_commands": len(km["commands"]),
        "shipped_bindings": len(shipped),
        "reserved_total": len(reserved),
        "reserved_file": len(load_reserved_file_keys()),
        "hot_05_rows": len(hot),
        "design_bindings": len(design),
        "design_literals": len(DESIGN_BINDINGS),
        "sr_rows": len(srk),
        "sr_counts": sr_counts,
        "sr_sources": len(fixture["sources"]),
        "alt_t_sr_rows": len(alt_t_rows),
        "conflicts": conflicts,
        "conflicts_by_class": by_class,
        "contradicted_05": contradicted_05,
        "unregistered_05": unregistered_05,
        "unregistered_design": unregistered_design,
        "alt_family": alt_family,
        "free_single": free_single,
        "free_double": free_double,
        "lint_errors": lint_errors,
        "by_id": by_id,
    }


def load_reserved_file_keys() -> set[str]:
    with (ROOT / "apps/web/src/keymap/reserved-keys.json").open(encoding="utf-8") as fh:
        raw: dict[str, str] = json.load(fh)
    out: set[str] = set()
    for k in raw:
        out.update(expand_keys(k))
    return out


# ------------------------------------------------------------------- 3. composed matrix (R7)
def sibling_pairs(name: str) -> list[tuple[str, str, str, str]]:
    mod = SIBLINGS[name]
    rows = mod.ROWS if name == "E11-D06" else mod.PAIRS
    return [(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows]


def sibling_col(name: str, theme: str, token: str) -> str | None:
    try:
        return str(SIBLINGS[name].col(theme, token))
    except (KeyError, TypeError, AttributeError):  # the CR map may lack the token
        return None


def union_matrix() -> dict[str, Any]:
    per_spec: dict[str, dict[str, int]] = {}
    under: list[str] = []
    total = 0
    gated = 0
    for name in SIBLINGS:
        rows = sibling_pairs(name)
        per_spec[name] = {"rows": len(rows), "gated": 0, "under": 0, "unresolved": 0}
        for element, fg, bg, role in rows:
            total += 1
            bar = BAR.get(role)
            if bar is None or "exempt" in element.lower():
                if bar is not None:
                    per_spec[name]["exempted"] = per_spec[name].get("exempted", 0) + 1
                continue
            per_spec[name]["gated"] += 1
            gated += 1
            themes = ("high-contrast",) if role == "hc-text" else THEMES
            for th in themes:
                f = sibling_col(name, th, fg)
                b = sibling_col(name, th, bg)
                if f is None or b is None:
                    per_spec[name]["unresolved"] += 1
                    continue
                r = ratio(f, b)
                if r < bar:
                    per_spec[name]["under"] += 1
                    under.append(f"{name} | {element} | {fg} on {bg} | {th} | {fmt(r)} < {bar}")
    return {"per_spec": per_spec, "rows": total, "gated": gated, "under": under}


# id | label | fg expression | bg expression | role | stack (a token, or dim85(token))
COMPOSITION_TABLE = """
C1 | stale candle up x0.85 on the canvas | dim85(color.candle.up) | color.surface.canvas
  | non-text | data-ink under the stale dim (E11-D02 §10 :410)
C2 | stale candle down x0.85 on the canvas | dim85(color.candle.down) | color.surface.canvas
  | non-text | as C1
C3 | stale wick x0.85 on the canvas | dim85(color.candle.wick) | color.surface.canvas | non-text
  | as C1
C4 | stale imbalance outline x0.85 on the canvas | dim85(color.footprint.imbalance)
  | color.surface.canvas | non-text | the outline is data-ink, dimmed with it
C5 | D10 cursor core on its 1 px halo | color.focus.ring | color.surface.canvas | non-text
  | E06-D03 D10; E11-D05 §9.1 (halo = the pane colour)
C6 | crosshair on a major gridline | color.crosshair | color.border.default | non-text
  | E11-D02 D3 (dash phase offset; >= 3.08 claimed)
C7 | crosshair on a minor gridline | color.crosshair | color.grid.line | non-text | E11-D02 D3
C8 | horizontal crosshair against the D10 halo that interrupts it | color.crosshair
  | color.surface.canvas | non-text
  | E11-D02 D3 :110 (the column keeps its halo; the pane colour separates the two)
C8b | ring core against the crosshair at the crossing (no halo) | color.focus.ring
  | color.crosshair | reported
  | a 2 px point intersection, not a stack: separated by C8's halo; not gated
C9 | imbalance bar on a selected table row | color.footprint.imbalance | color.surface.selected
  | non-text | E11-D04 §6.1 :247 bar + §8.3 selected fill
C10 | imbalance bar on a hovered table row | color.footprint.imbalance | color.surface.hover
  | non-text | E11-D04 §17 hover fill
C11 | imbalance bar on the sub-table surface | color.footprint.imbalance | color.surface.app
  | non-text | E11-D04 §6.1 :250
C12 | focus ring on a selected row | color.focus.ring | color.surface.selected | non-text
  | cursor row + selected row at once (E11-D04 §17 :501)
C13 | focus ring on a hovered row | color.focus.ring | color.surface.hover | non-text
  | E11-D04 §17
C14 | focus ring on the sub-table surface | color.focus.ring | color.surface.app | non-text
  | E11-D04 §6.1
C15 | focus ring on raised chrome (chips, badge, stub) | color.focus.ring | color.surface.raised
  | non-text | E11-D02 §12; E11-D05 §9.1 (6.66 claimed)
C16 | focus ring on the legend popover | color.focus.ring | color.surface.overlay | non-text
  | E11-D02 §7.5 :341
C17 | focus ring on the stale banner's Refresh button | color.focus.ring
  | color.status.warning.subtle | non-text | E11-D04 §7 :271 banner fill
C18 | text.tertiary axis label / hidden legend label / grip on the canvas | color.text.tertiary
  | color.surface.canvas | text | one token, four roles (E11-D02 D7, D12, §8)
C19 | primary text on a selected row | color.text.primary | color.surface.selected | text
  | E11-D04 §8.3
C20 | secondary text on a selected row | color.text.secondary | color.surface.selected | text
  | E11-D04 §5.1 secondary type
"""
COMPOSITION: list[tuple[str, str, str, str, str, str]] = [
    (r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows(COMPOSITION_TABLE)
]
CVD_TABLE = """
stale candle up vs stale candle down (buy / sell under the dim) | dim85(color.candle.up)
  | dim85(color.candle.down) | E11-D02 §10
imbalance bar vs selected row fill | color.footprint.imbalance | color.surface.selected
  | E11-D04 §8.3
focus ring vs stale banner fill | color.focus.ring | color.status.warning.subtle | E11-D04 §7
focus ring vs crosshair | color.focus.ring | color.crosshair | E06-D03 D10 / E11-D02 D3
"""
CVD_COMPOSED: list[tuple[str, str, str, str]] = [(r[0], r[1], r[2], r[3]) for r in rows(CVD_TABLE)]
STACK_TOKENS = (
    "color.surface.canvas",
    "color.grid.line",
    "color.border.default",
    "color.crosshair",
    "color.focus.ring",
    "color.candle.up",
    "color.candle.down",
    "color.footprint.imbalance",
    "color.text.tertiary",
    "color.surface.selected",
    "color.surface.hover",
)


def expr(theme: str, e: str) -> str | None:
    m = re.fullmatch(r"dim85\((.+)\)", e)
    tok = m.group(1) if m else e
    h = T[theme].get(tok)
    if h is None:
        return None
    return dim85(h) if m else h


def composition_rows() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cid, label, fg, bg, role, stack in COMPOSITION:
        row: dict[str, Any] = {
            "id": cid,
            "label": label,
            "fg": fg,
            "bg": bg,
            "role": role,
            "stack": stack,
        }
        worst = 99.0
        for th in THEMES:
            f, b = expr(th, fg), expr(th, bg)
            if f is None or b is None:
                row[th] = None
                continue
            r = ratio(f, b)
            row[th] = round(r, 2)
            worst = min(worst, r)
        bar = BAR.get(role)
        row["bar"] = bar if bar is not None else "n/a"
        row["verdict"] = "reported" if bar is None else "FAIL" if worst < bar else "PASS"
        out.append(row)
    return out


def cvd_rows() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for label, a, b, src in CVD_COMPOSED:
        row: dict[str, Any] = {"label": label, "source": src}
        for th in THEMES:
            ha, hb = expr(th, a), expr(th, b)
            if ha is None or hb is None:
                row[th] = None
                continue
            des = {}
            for d in ("deuteranopia", "protanopia", "tritanopia"):
                des[d] = round(float(cvd.delta_e76(cvd.simulate(ha, d), cvd.simulate(hb, d))), 1)
            row[th] = des
        out.append(row)
    return out


def greyscale_strip() -> dict[str, int]:
    return {t: luma(T["dark"][t]) for t in STACK_TOKENS if t in T["dark"]}


# channel | meaning | surface | spec  (one meaning per channel per surface, or a finding)
CHANNELS_TABLE = """
hatch 45 deg, 2 px pitch (pattern.hatch.estimated) | estimated value | footprint cell
  | E11-D05 §7 :313
hatch 45 deg, 6 px pitch (pattern.hatch.gap) | absent coverage | time strip / plot band
  | E11-D05 §7 :315
hatch 45 deg, 6 px pitch (pattern.hatch.absent) | broken zone status | zone overlay (E25)
  | E11-D05 §7 :316
outline (pattern.outline.imbalance) | imbalance flag | footprint cell | E11-D05 §7 :318
outline 1 px color.border.strong | pressed segment reinforcement | cluster / view switch
  | E11-D04 §4.1 :139
double ring (CMP-039 + D10) | keyboard focus | chart boundary / cursor column | E11-D05 §9.1 :438
dash 4 / 4 (dash.4-4) | crosshair (pointer-bound) | plot | E11-D05 §7.2 :336
dash 4 / 4 (dash.4-4) | session / day boundary | plot | E11-D05 §7.2 :336
dash 4 / 4 (dash.4-4) | remote crosshair | plot | E11-D05 §7.2 :336
dash 4 / 4 (dash.4-4) | coverage-gap edge | plot | E11-D05 §7.2 :336
dash 2 / 6 (dash.2-6) | mark-price line | plot | E11-D05 §7.2 :337
dash 4 / 3 (dash.4-3) | estimated series / tested zone | plot | E11-D05 §7.2 :339
glyph notch (glyph.notch.delta) | delta sign at L2 | footprint cell | E11-D05 §7 :319
glyph ▲ / ▼ | bar direction | last-price pill / tooltip | E11-D02 D7, D10
color.text.tertiary | axis tick label | price / time axis | E11-D02 D7
color.text.tertiary | hidden legend row label | legend | E11-D02 D12 :343
color.text.tertiary | splitter grip | splitter | E11-D02 §8 :355
color.text.tertiary | session / gap boundary line | plot | E11-D02 D1
color.surface.selected | pressed segment | cluster / view switch | E11-D02 D8; E11-D04 D1
color.surface.selected | selected row | data table | E11-D04 §8.3 :296
color.status.warning.* | closing countdown / stale banner / paused / corner badge
  | status row, table, cluster, pane | E11-D02 D11, D16; E11-D04 D7
"""
CHANNELS: list[tuple[str, str, str, str]] = [(r[0], r[1], r[2], r[3]) for r in rows(CHANNELS_TABLE)]


def channel_reuse() -> dict[str, Any]:
    by: dict[tuple[str, str], set[str]] = {}
    for ch, meaning, surface, _ in CHANNELS:
        by.setdefault((ch, surface), set()).add(meaning)
    multi = [
        {"channel": ch, "surface": surface, "meanings": sorted(m)}
        for (ch, surface), m in by.items()
        if len(m) > 1
    ]
    return {"rows": len(CHANNELS), "multi": multi}


# surface | density | w | h | spec:line | note. A token name is resolved from primitives; a bare
# integer is a typed number; full / pane / pill = the containing dimension.
TARGETS_TABLE = """
splitter hit band | compact / dense | full | space.6 | D02:94, :355
  | 24 px band, 12 each side; grip 24 x 4
splitter hit band | comfortable | full | space.6 | D02:94 | grip 32 x 4
time strip (drag zone) | comfortable | full | size.control.comfortable | D02:92 |
time strip (drag zone) | compact / dense | full | size.control.compact | D02:92, :233
  | the 24 px floor in dense
price gutter (drag zone) | comfortable | 56 | pane | D02:91, :246
  | widest label + 16, min 56 (typed minimum)
price gutter (drag zone) | compact / dense | space.12 | pane | D02:91, :246
  | widest label + 8, min 48
cluster segment | comfortable | size.control.comfortable | size.control.comfortable | D02:93 |
cluster segment | compact / dense | size.control.compact | size.control.compact | D02:93, :233 |
legend row / eye toggle | comfortable | size.control.comfortable | size.control.comfortable
  | D02:87, :339 | chevron and menu buttons 24 x 24
legend row / eye toggle | compact / dense | size.control.compact | size.control.compact
  | D02:87, :233, :345 |
status chip button (20 px pill + 2 px padding) | compact / dense | pill | 24 | D02:652
  | 20 + 2 + 2 = 24 (HPE-R2-5)
status chip button | comfortable | pill | space.6 | D02:86 | 24 px pill
collapsed stub + restore button | comfortable | full | size.control.comfortable | D02:95, :367
  | restore 24 x 24
collapsed stub + restore button | compact / dense | full | size.control.compact | D02:95, :367 |
lock badge hit box | every density | pill | size.target.min | D03:451 |
SCR-043 menu row | comfortable | full | size.control.comfortable | D03:451 |
SCR-043 menu row | compact | full | size.control.compact | D03:451 |
SCR-044 close button | every density | size.control.compact | size.control.compact | D03:451 |
SCR-044 calendar day cell | every density | 32 | 32 | D03:451 | typed 32 (no token named)
SCR-044 quick-jump button | every density | full | 32 | D03:451 | typed 32 (no token named)
SCR-031 toggle | every density | 44 | size.control.compact | D03:451 | 24 x 44 (typed width)
table row (bar / level) | compact | full | size.row.compact | D04:540 | the row is the target
table expander cell / header button / chip / Kbd / segment | compact | size.target.min
  | size.target.min | D04:540 | chips: 20 px pill + 2 px invisible padding
view switch segment (Chart / Table) | compact | pill | size.control.height | D04:139
  | token name does not exist at the base (G-row)
E14 drawing-rail tool button (in flight) | compact / dense | size.control.compact
  | size.control.compact | E14:132 | E14's; Info
E14 drawing-rail tool button (in flight) | comfortable | size.control.comfortable
  | size.control.comfortable | E14:132 | E14's; Info
D10 cursor column (not a target: a focus-visible mark) | every density | 2 | pane | E06:176
  | >= 2 px core + 1 px halos; informational
"""


def _dim(s: str) -> Any:
    return int(s) if re.fullmatch(r"\d+", s) else s


TARGETS: list[tuple[str, str, Any, Any, str, str]] = [
    (r[0], r[1], _dim(r[2]), _dim(r[3]), r[4], r[5] if len(r) > 5 else "")
    for r in rows(TARGETS_TABLE)
]


def px(v: Any) -> tuple[str, int | None]:
    if isinstance(v, int):
        return (f"typed {v}", v)
    if v in ("full", "pane", "pill"):
        return (v, None)
    val = PRIM.get(v)
    if val is None:
        return (f"{v} (no such token)", None)
    return (f"{v} {val}", int(val))


def target_rows() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for surface, density, w, h, src, note in TARGETS:
        wl, wv = px(w)
        hl, hv = px(h)
        dims = [d for d in (wv, hv) if d is not None]
        informational = surface.startswith("D10")
        ok = informational or not dims or min(dims) >= 24
        g_row = "no such token" in wl or "no such token" in hl
        typed = wl.startswith("typed") or hl.startswith("typed")
        out.append(
            {
                "surface": surface,
                "density": density,
                "w": wl,
                "h": hl,
                "ok": ok,
                "typed": typed,
                "g_row": g_row,
                "src": src,
                "note": note,
            }
        )
    return out


# --------------------------------------------------------------------------- 6. reduced motion (R8)
REDUCE_CLASSES = (
    ("cut", r"\bcut\b"),
    ("instant", r"\binstant|0 ms|one frame|1 frame|same frame|in one change"),
    ("same", r"^same\b|\bsame\b|\bidentical\b"),
    ("static", r"\bstatic\b"),
    ("off", r"\boff\b|\bnone\b|no coast|disabled|stops exactly"),
    ("n/a", r"^—$|^-$|^n/a"),
)


def parse_table(text: str, start: str, end: str) -> list[list[str]]:
    body = text.split(start, 1)[1].split(end, 1)[0]
    rows: list[list[str]] = []
    for ln in body.splitlines():
        if ln.startswith("|") and not ln.startswith("| ---"):
            cells = ln.strip().strip("|").replace("\\|", "\x00").split("|")
            rows.append([c.strip().replace("\x00", "|") for c in cells])
    return rows


def motion_section() -> dict[str, Any]:
    text = (DESIGN / "E11" / "E11-D06.md").read_text(encoding="utf-8")
    rows = parse_table(text, "## 7. The motion spec table", "## 8. The safety rows")
    header, data = rows[0], [r for r in rows[1:] if r and re.fullmatch(r"\d+", r[0])]
    hi = {h.lower(): i for i, h in enumerate(header)}
    rv = next(i for h, i in hi.items() if "reduced" in h)
    ci = next(i for h, i in hi.items() if "information" in h)
    classified: list[dict[str, str]] = []
    exceptions: list[str] = []
    for r in data:
        variant = r[rv] if rv < len(r) else ""
        carries = r[ci] if ci < len(r) else ""
        cls = "other"
        low = variant.lower()
        for name, rx in REDUCE_CLASSES:
            if re.search(rx, low):
                cls = name
                break
        classified.append(
            {
                "row": r[0],
                "element": r[1][:60],
                "variant": variant[:80],
                "class": cls,
                "carries": carries[:60],
            }
        )
        if cls == "other":
            exceptions.append(
                f"row {r[0]} ({r[1][:40]}): reduce variant unclassified: {variant[:80]}"
            )
        elif carries.lower().startswith("yes") and cls == "off":
            exceptions.append(
                f"row {r[0]} ({r[1][:40]}): information-carrying motion removed, not replaced"
            )
    flash = parse_table(text, "### 9.3 Flash audit", "### 9.4 Vestibular")
    rates: list[float] = []
    for r in flash[1:]:
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:/\s*s|Hz)", " ".join(r)):
            rates.append(float(m.group(1)))
    vest = parse_table(text, "### 9.4 Vestibular", "## 10.")
    vh = [h.lower() for h in vest[0]]
    ui = next(i for i, h in enumerate(vh) if "reduce" in h)
    under = [r[ui].strip() for r in vest[1:] if len(r) > ui]
    classes = {c["class"]: 0 for c in classified}
    for c in classified:
        classes[c["class"]] += 1
    return {
        "rows": len(data),
        "classes": classes,
        "exceptions": exceptions,
        "animate_under_safe": sum(
            1 for c in classified if c["class"] in ("cut", "instant", "static", "off")
        ),
        "flash_rates": rates,
        "flash_max": max(rates) if rates else 0.0,
        "vestibular_rows": len(under),
        "vestibular_under_reduce": under,
        "vestibular_ok": all(u in ("off", "cut", "instant", "static") for u in under),
        "override_entry_points": 3,
        "classified": classified,
    }


# --------------------------------------------------------------------------- 7. numbers
FOOTPRINT_05 = ["Price", "Bid vol", "Ask vol", "Delta", "Imbalance flag", "Estimated badge"]
FOOTPRINT_D04 = ["price", "bid", "ask", "delta", "imbalance", "(estimated)"]


def _colname(s: str) -> str:
    """A column name reduced to its stem: 'Bid vol' / 'bid', 'Imbalance flag' / 'imbalance'."""
    low = s.lower().replace("vol", "").replace("flag", "").replace("badge", "")
    return re.sub(r"[^a-z]", "", low)


def numbers_block() -> dict[str, Any]:
    text05 = (PLAN / "05-accessibility-standard.md").read_text(encoding="utf-8")
    fp = parse_table(text05, "**Footprint table**", "**Profile table**")
    names_05 = [r[0] for r in fp[1:]]
    text04 = (DESIGN / "E11" / "E11-D04.md").read_text(encoding="utf-8")
    sub = parse_table(
        text04,
        "**Column contract (the `05` §6.3 footprint table, verbatim set).**",
        "The level table's sort",
    )
    names_04 = [re.sub(r"\s*\(`<th[^)]*\)", "", r[0]).strip("` ") for r in sub[1:]]
    diff = [a for a in names_05 if _colname(a) not in {_colname(b) for b in names_04}]
    return {
        "nodes_per_row": 9,
        "nodes_fixed": 10,
        "nodes_default": 9 * 60 + 10,
        "nodes_cap": 9 * 200,
        "cap_ticket": 500,
        "ticks_per_window": 20 * 2,
        "cursor_per_s": 1000 // 500,
        "slice_ms": 1.0,
        "mirror_p95_default_ms": 0.8,
        "mirror_p95_cap_ms": 1.4,
        "table_scroll_ms": 8,
        "table_patch_hz": 0.5,
        "footprint_05": names_05,
        "footprint_d04": names_04,
        "footprint_diff": diff,
        "stops_three_panes_d02": 19,
    }


# --------------------------------------------------------------------------- 8. the review's text
AT_PHRASES = (
    r"\b(NVDA|JAWS|VoiceOver)\b.{0,40}\b(read|reads|said|announced|spoke|speaks)\b",
    r"\bparticipant",
    r"\bsession (was )?run\b",
    r"we observed",
    r"the user said",
)
PENPOT_HOST = re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE)
CLOSING = re.compile(r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b", re.IGNORECASE)
ISSUE_REF = re.compile(r"#\d{2,}")


def table_rows_with_prefix(text: str, rx: str) -> list[list[str]]:
    out: list[list[str]] = []
    for ln in text.splitlines():
        if ln.startswith("|") and re.match(rf"^\|\s*`?{rx}", ln):
            out.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return out


def bullets_05() -> dict[str, int]:
    text = (PLAN / "05-accessibility-standard.md").read_text(encoding="utf-8")
    out: dict[str, int] = {}
    for sec in ("6.1", "6.2", "6.3", "6.4"):
        nxt = "### 6.5" if sec == "6.4" else f"### {float(sec) + 0.1:.1f}"
        body = text.split(f"### {sec} ")[1].split(nxt)[0]
        out[sec] = sum(1 for ln in body.splitlines() if ln.startswith("- "))
    return out


def spec_section(spec: str) -> dict[str, Any]:
    problems: list[str] = []
    idrx = r"(" + "|".join(re.escape(c) for c in CLAUSES) + r")`?\s*\|"
    rows = table_rows_with_prefix(spec, idrx)
    found: dict[str, list[str]] = {}
    for r in rows:
        cid = r[0].strip("` ")
        found.setdefault(cid, []).append("|".join(r))
        if len(r) < 8:
            problems.append(f"verdict row {cid}: {len(r)} cells, expected 8")
            continue
        verdict = r[3].strip("* ")
        if verdict not in VERDICTS:
            problems.append(f"verdict row {cid}: verdict {verdict!r} not in the vocabulary")
        if not r[4] or r[4] == "—":
            problems.append(f"verdict row {cid}: empty evidence cell")
        if verdict in ("at risk", "non-compliant", "not yet decidable — routed to E11-Q05") and (
            r[6] in ("", "—") or r[7] in ("", "—")
        ):
            problems.append(f"verdict row {cid}: {verdict} without an owner and a target")
    missing = [c for c in CLAUSES if c not in found]
    dupes = [c for c, v in found.items() if len(v) > 1]
    if missing:
        problems.append("verdict rows missing: " + ", ".join(missing))
    if dupes:
        problems.append("verdict rows duplicated: " + ", ".join(dupes))
    by_verdict: dict[str, int] = {v: 0 for v in VERDICTS}
    for r in rows:
        if len(r) >= 8 and r[3].strip("* ") in by_verdict:
            by_verdict[r[3].strip("* ")] += 1
    f_rows = table_rows_with_prefix(spec, r"F-\d\d")
    f_bad = [r[0] for r in f_rows if len(r) < 8 or r[5] in ("", "—") or r[6] in ("", "—")]
    sev: dict[str, int] = {"Blocking": 0, "Major": 0, "Minor": 0, "Info": 0}
    cls: dict[str, int] = {}
    for r in f_rows:
        if len(r) >= 3:
            s = r[2].strip("* ")
            if s in sev:
                sev[s] += 1
            cls[r[1]] = cls.get(r[1], 0) + 1
    a_rows = table_rows_with_prefix(spec, r"A-\d\d")
    a_bad = [
        r[0]
        for r in a_rows
        if len(r) < 2
        or not re.search(r"`(05|14|15|26|06|E11\.json)`", r[1])
        or not re.search(r"§|SCR-\d+|CMP-\d+|ADR", r[1])
    ]
    c_rows = table_rows_with_prefix(spec, r"C-\d\d")
    g_rows = table_rows_with_prefix(spec, r"G-\d\d")
    q_rows = table_rows_with_prefix(spec, r"Q-\d\d")
    h_rows = table_rows_with_prefix(spec, r"H-\d\d")
    h_bad = [r[0] for r in h_rows if "(heuristic)" not in "|".join(r)]
    stop_rows = table_rows_with_prefix(spec, r"ST\d\d")
    gesture_rows = table_rows_with_prefix(spec, r"PG\d\d")
    hit_rows = table_rows_with_prefix(spec, r"TG\d\d")
    desync_rows = table_rows_with_prefix(spec, r"DS\d\d")
    parity_rows = table_rows_with_prefix(spec, r"PR\d\d")
    rt_rows = table_rows_with_prefix(spec, r"R-T\d")
    hand_rows = table_rows_with_prefix(spec, r"HO-\d\d")
    blocking_gestures = sum(1 for r in gesture_rows if len(r) >= 10 and "Blocking" in r[9])
    partial_gestures = sum(
        1 for r in gesture_rows if len(r) >= 6 and r[5].lower().startswith("partial")
    )
    at: list[str] = []
    for rx in AT_PHRASES:
        at.extend(m.group(0) for m in re.finditer(rx, spec))
    if at:
        problems.append("fabricated-AT phrase: " + " | ".join(at[:5]))
    for m in re.finditer(r"display:\s*none", spec):
        pre = spec[max(0, m.start() - 60) : m.start()].lower()
        if not re.search(r"never|not |no |forbid|instead of|rather than|\(not", pre):
            problems.append(
                "display:none recommended near: "
                + spec[m.start() - 40 : m.end() + 20].replace("\n", " ")
            )
    if f_bad:
        problems.append("F rows without owner/target: " + ", ".join(f_bad))
    if a_bad:
        problems.append("A rows without a file and a section: " + ", ".join(a_bad))
    if h_bad:
        problems.append("H rows without (heuristic): " + ", ".join(h_bad))
    if "/home/" in spec:
        problems.append("local path in the review")
    if PENPOT_HOST.search(spec):
        problems.append("a Penpot host in the review")
    return {
        "clauses_expected": len(CLAUSES),
        "clauses_found": len(found),
        "by_verdict": by_verdict,
        "f_rows": len(f_rows),
        "f_by_severity": sev,
        "f_by_class": cls,
        "a_rows": len(a_rows),
        "c_rows": len(c_rows),
        "g_rows": len(g_rows),
        "q_rows": len(q_rows),
        "h_rows": len(h_rows),
        "stops": len(stop_rows),
        "gestures": len(gesture_rows),
        "gestures_blocking": blocking_gestures,
        "gestures_partial": partial_gestures,
        "hit_boxes": len(hit_rows),
        "desync_paths": len(desync_rows),
        "parity_rows": len(parity_rows),
        "rt_tasks": len(rt_rows),
        "handoffs": len(hand_rows),
        "problems": problems,
    }


def closing_keywords(text: str) -> list[str]:
    hits: list[str] = []
    for ln in text.splitlines():
        if CLOSING.search(ln) and ISSUE_REF.search(ln):
            hits.append(ln.strip()[:100])
    return hits


# --------------------------------------------------------------------------- counts, json, check
def build(spec_path: Path | None) -> dict[str, Any]:
    km = keymap_section()
    union = union_matrix()
    comp = composition_rows()
    cvdr = cvd_rows()
    grey = greyscale_strip()
    chan = channel_reuse()
    targets = target_rows()
    motion = motion_section()
    nums = numbers_block()
    bullets = bullets_05()
    spec_text = spec_path.read_text(encoding="utf-8") if spec_path and spec_path.exists() else ""
    sp: dict[str, Any] = (
        spec_section(spec_text)
        if spec_text
        else {"problems": ["review not found: " + str(spec_path)]}
    )
    comp_fail = [c["id"] for c in comp if c["verdict"] == "FAIL"]
    cvd_low = [
        f"{r['label']} {th} {d} {v}"
        for r in cvdr
        for th in THEMES
        if isinstance(r.get(th), dict)
        for d, v in r[th].items()
        if v < 5.0
    ]
    counts: dict[str, Any] = {
        "shipped_commands": km["shipped_commands"],
        "shipped_bindings": km["shipped_bindings"],
        "reserved_entries": km["reserved_file"],
        "hot_05_rows": km["hot_05_rows"],
        "design_bindings": km["design_bindings"],
        "sr_rows": km["sr_rows"],
        "sr_nvda": km["sr_counts"]["nvda"],
        "sr_jaws": km["sr_counts"]["jaws"],
        "sr_voiceover": km["sr_counts"]["voiceover"],
        "sr_sources": km["sr_sources"],
        "alt_t_sr_rows": km["alt_t_sr_rows"],
        "conflicts_total": len(km["conflicts"]),
        "unregistered_05": len(km["unregistered_05"]),
        "contradicted_05": len(km["contradicted_05"]),
        "free_single": len(km["free_single"]),
        "free_double": len(km["free_double"]),
        "unregistered_design": len(km["unregistered_design"]),
        "alt_family": len(km["alt_family"]),
        "lint_errors": len(km["lint_errors"]),
        "union_rows": union["rows"],
        "union_gated": union["gated"],
        "union_under": len(union["under"]),
        "composition_rows": len(comp),
        "composition_fail": len(comp_fail),
        "cvd_rows": len(cvdr),
        "cvd_below_jnd": len(cvd_low),
        "channel_rows": chan["rows"],
        "channel_multi": len(chan["multi"]),
        "target_rows": len(targets),
        "targets_below_24": sum(1 for t in targets if not t["ok"]),
        "targets_typed": sum(1 for t in targets if t["typed"]),
        "targets_no_token": sum(1 for t in targets if t["g_row"]),
        "motion_rows": motion["rows"],
        "motion_exceptions": len(motion["exceptions"]),
        "flash_max_per_s": motion["flash_max"],
        "vestibular_rows": motion["vestibular_rows"],
        "override_entry_points": motion["override_entry_points"],
        "bullets_6_1": bullets["6.1"],
        "bullets_6_2": bullets["6.2"],
        "bullets_6_3": bullets["6.3"],
        "bullets_6_4": bullets["6.4"],
        "clauses_expected": len(CLAUSES),
    }
    for k, v in nums.items():
        if isinstance(v, (int, float)):
            counts[k] = v
    for c in km["conflicts_by_class"]:
        counts[f"conflicts_{c.replace('-', '_')}"] = km["conflicts_by_class"][c]
    for k in (
        "clauses_found",
        "f_rows",
        "a_rows",
        "c_rows",
        "g_rows",
        "q_rows",
        "h_rows",
        "stops",
        "gestures",
        "gestures_blocking",
        "gestures_partial",
        "hit_boxes",
        "desync_paths",
        "parity_rows",
        "rt_tasks",
        "handoffs",
    ):
        if k in sp:
            counts[k] = sp[k]
    if "by_verdict" in sp:
        for v, n in sp["by_verdict"].items():
            counts["verdict_" + re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_")] = n
        for s, n in sp["f_by_severity"].items():
            counts["f_" + s.lower()] = n
    for c in comp:
        for th in THEMES:
            if c[th] is not None:
                counts[f"{c['id']}_{th.replace('-', '_')}"] = c[th]
    for t, lv in grey.items():
        counts["luma_" + t.replace(".", "_")] = lv
    dark_hex = {
        t: T["dark"][t]
        for t in (
            *STACK_TOKENS,
            "color.surface.raised",
            "color.surface.app",
            "color.surface.overlay",
            "color.text.primary",
            "color.text.secondary",
            "color.border.strong",
            "color.status.warning.subtle",
            "color.status.warning.strong",
            "color.action.primary.default",
            "color.status.success.strong",
            "color.status.danger.strong",
            "color.status.info.strong",
            "color.env.demo",
            "color.env.live",
        )
        if t in T["dark"]
    }
    problems = list(sp.get("problems", []))
    if comp_fail:
        problems.append("D07 composition FAIL: " + ", ".join(comp_fail))
    if km["lint_errors"]:
        problems.append(f"lint_keymap errors (shipped): {len(km['lint_errors'])}")
    return {
        "counts": counts,
        "keymap": km,
        "union": union,
        "composition": comp,
        "cvd": cvdr,
        "greyscale": grey,
        "channels": chan,
        "targets": targets,
        "motion": motion,
        "numbers": nums,
        "spec": sp,
        "dark_hex": dark_hex,
        "theme_hex": {th: {t: T[th][t] for t in dark_hex if t in T[th]} for th in THEMES},
        "problems": problems,
    }


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
        got = fmt(float(val)) if isinstance(want, float) else str(val)
        exp = fmt(want) if isinstance(want, float) else str(want)
        if got != exp:
            errs.append(f"marker {name}={val}: the tool computes {exp}")
    required = (
        "clauses_found",
        "f_rows",
        "conflicts_total",
        "composition_rows",
        "composition_fail",
        "union_under",
        "stops",
        "gestures",
        "gestures_blocking",
        "motion_rows",
        "target_rows",
        "sr_rows",
        "alt_t_sr_rows",
        "lint_errors",
    )
    for r in required:
        if not re.search(rf"<!--\s*audit:{r}=", spec_text):
            errs.append(f"required marker missing: {r}")
    if not seen:
        errs.append("no audit markers in the review")
    return errs


def _kv(label: str, value: Any) -> str:
    return f"{label} {value}"


def render_report(d: dict[str, Any]) -> str:
    km, c, sp = d["keymap"], d["counts"], d["spec"]
    out: list[str] = ["# E11-D07 a11y review audit", "", "## 1. Clauses"]
    out.append(
        "05 §6 bullets at the base: "
        + " / ".join(f"{s} {c['bullets_' + s.replace('.', '_')]}" for s in BULLETS_EXPECTED)
        + f" (expected {BULLETS_EXPECTED}); review clause ids expected {c['clauses_expected']}."
    )
    if "clauses_found" in sp:
        bv, sev = sp["by_verdict"], sp["f_by_severity"]
        oos = bv["out of scope — E19"] + bv["out of scope — E21"]
        out.append(
            f"clauses: {c['clauses_expected']} expected / {sp['clauses_found']} found / "
            f"{bv['compliant']} compliant / {bv['at risk']} at risk / "
            f"{bv['non-compliant']} non-compliant / {oos} out of scope / "
            f"{bv['not yet decidable — routed to E11-Q05']} routed"
        )
        out.append(
            f"F rows {sp['f_rows']} (Blocking {sev['Blocking']}, Major {sev['Major']}, "
            f"Minor {sev['Minor']}, Info {sev['Info']}); A {sp['a_rows']} C {sp['c_rows']} "
            f"G {sp['g_rows']} Q {sp['q_rows']} H {sp['h_rows']}"
        )
        out.append(
            f"stops {sp['stops']}; gestures {sp['gestures']} (Blocking {sp['gestures_blocking']}, "
            f"partial {sp['gestures_partial']}); hit boxes {sp['hit_boxes']}; desync paths "
            f"{sp['desync_paths']}; parity rows {sp['parity_rows']}; R-T tasks {sp['rt_tasks']}; "
            f"hand-offs {sp['handoffs']}"
        )
        fb = sum(1 for p in sp["problems"] if p.startswith("F rows"))
        at = sum(1 for p in sp["problems"] if p.startswith("fabricated"))
        out.append(f"F rows without owner/target: {fb}")
        out.append(f"fabricated-AT phrases: {at}")
    out += ["", "## 2. Key map"]
    out.append(
        f"shipped {c['shipped_commands']} commands / {c['shipped_bindings']} atomic bindings; "
        f"05 §3.2 rows {c['hot_05_rows']}; design bindings {c['design_bindings']} "
        f"(from {km['design_literals']} literals); reserved file entries {c['reserved_entries']} "
        f"+ 05 §3.3 item 4's {len(OS_FOUR)}"
    )
    out.append(
        f"SR fixture rows {c['sr_rows']} (nvda {c['sr_nvda']} / jaws {c['sr_jaws']} / "
        f"voiceover {c['sr_voiceover']}; {c['sr_sources']} sources)"
    )
    out.append(f"lint_keymap errors (shipped): {c['lint_errors']}")
    out.append(f"Alt+T rows in the SR fixture: {c['alt_t_sr_rows']} (0 = no vendor list binds it)")
    out.append(f"conflicts: {c['conflicts_total']} by class {km['conflicts_by_class']}")
    out += ["", "| class | a | b | contexts | note |", "| --- | --- | --- | --- | --- |"]
    for x in km["conflicts"]:
        out.append(f"| {x['class']} | {x['a']} | {x['b']} | {x['contexts']} | {x['note']} |")
    out.append("")
    out.append(f"05 §3.2 rows not fully registered ({len(km['unregistered_05'])}):")
    out += [f"- {u}" for u in km["unregistered_05"]]
    out.append(f"05 rows the registry contradicts ({len(km['contradicted_05'])}):")
    out += [f"- {u}" for u in km["contradicted_05"]]
    out.append(f"specified, unregistered chart / grid keys ({len(km['unregistered_design'])}):")
    out += [f"- {u}" for u in km["unregistered_design"]]
    out.append("Alt+<letter> family (conditional on E11-D01 O13): " + ", ".join(km["alt_family"]))
    out.append(
        f"free single-modifier keys for the Chart context ({len(km['free_single'])}): "
        + ", ".join(km["free_single"])
    )
    out.append(
        f"free Ctrl+Shift combos ({len(km['free_double'])}): " + ", ".join(km["free_double"])
    )
    out += ["", "## 3. Composed matrix"]
    u = d["union"]
    out.append(
        f"union rows {u['rows']} (gated {u['gated']}); per spec {u['per_spec']}; "
        f"upstream rows under their bar: {len(u['under'])}"
    )
    out += [f"- {x}" for x in u["under"]]
    out += [
        "",
        "| id | composition | fg | bg | role | dark | light | hc | bar | verdict |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in d["composition"]:
        cells = " | ".join("n/a" if r[th] is None else fmt(r[th]) for th in THEMES)
        out.append(
            f"| {r['id']} | {r['label']} | {r['fg']} | {r['bg']} | {r['role']} | {cells} | "
            f"{r['bar']} | {r['verdict']} |"
        )
    out.append(f"D07 composition FAIL: {c['composition_fail']}")
    out += ["", "CVD ΔE76 (deut / prot / trit; JND 5.0) for the new composed pairs:"]
    for r in d["cvd"]:
        parts = []
        for th in THEMES:
            v = r[th]
            txt = "n/a" if not isinstance(v, dict) else " / ".join(str(v[k]) for k in sorted(v))
            parts.append(f"{th}: {txt}")
        out.append(f"- {r['label']} ({r['source']}): " + "; ".join(parts))
    out.append(f"CVD pairs below the JND: {c['cvd_below_jnd']}")
    out.append("greyscale luma (dark): " + ", ".join(f"{t} {v}" for t, v in d["greyscale"].items()))
    out += ["", "## 4. Channel reuse"]
    out.append(
        f"rows {c['channel_rows']}; channels with more than one meaning on one surface: "
        f"{c['channel_multi']}"
    )
    for m in d["channels"]["multi"]:
        out.append(f"- {m['channel']} on {m['surface']}: " + ", ".join(m["meanings"]))
    out += [
        "",
        "## 5. Targets",
        "| surface | density | w | h | >=24 | typed | source | note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for t in d["targets"]:
        ok = "yes" if t["ok"] else "NO"
        typed = "yes" if t["typed"] else ""
        out.append(
            f"| {t['surface']} | {t['density']} | {t['w']} | {t['h']} | {ok} | {typed} | "
            f"{t['src']} | {t['note']} |"
        )
    out.append(
        f"targets below 24 without an exception: {c['targets_below_24']}; typed numbers "
        f"{c['targets_typed']}; token names that do not exist {c['targets_no_token']}"
    )
    out += ["", "## 6. Reduced motion"]
    mo = d["motion"]
    out.append(
        f"D06 §7 rows {mo['rows']}; reduce-variant classes {mo['classes']}; "
        f"exceptions {len(mo['exceptions'])}"
    )
    out += [f"- {e}" for e in mo["exceptions"]]
    out.append(f"flash rates found {mo['flash_rates']} -> max {mo['flash_max']}/s (bar 3/s)")
    vest = "all in the set" if mo["vestibular_ok"] else "OUT OF SET"
    out.append(
        f"vestibular rows {mo['vestibular_rows']} under reduce {mo['vestibular_under_reduce']} "
        f"-> {vest}"
    )
    out.append(f"override entry points {mo['override_entry_points']} (E11-D06 C-11), one store")
    out += ["", "## 7. Numbers"]
    n = d["numbers"]
    out.append(
        f"nodes: {n['nodes_per_row']} per row + {n['nodes_fixed']} fixed -> {n['nodes_default']} "
        f"at 60 rows; {n['nodes_cap']} at the 200-row cap; the ticket's cap {n['cap_ticket']}"
    )
    out.append(
        f"ticks per 2 s window at 20 Hz: {n['ticks_per_window']}; cursor cap {n['cursor_per_s']}/s "
        f"(repeatWindow 500 ms); mirror slice {n['slice_ms']} ms vs measured "
        f"{n['mirror_p95_default_ms']} / {n['mirror_p95_cap_ms']} ms (E06-D03 F14)"
    )
    out.append(
        f"table {n['table_scroll_ms']} ms per scroll frame (14 SCR-045) and "
        f"{n['table_patch_hz']} Hz value patching (E11-D04 §6.3)"
    )
    out.append(
        f"footprint columns 05: {n['footprint_05']}; E11-D04 §6.1: {n['footprint_d04']}; "
        f"names in 05 with no D04 twin: {n['footprint_diff']}"
    )
    out += ["", "## 8. Problems"]
    out += [f"- {p}" for p in d["problems"]] or ["- none"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the reference machine's console is cp1252
    ap = argparse.ArgumentParser(description="E11-D07 accessibility design review audit")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", metavar="SPEC")
    ap.add_argument("--draft", metavar="DRAFT")
    ap.add_argument("--figures", metavar="DIR")
    args = ap.parse_args(argv)
    spec_path = Path(args.check) if args.check else SPEC_DEFAULT
    d = build(spec_path)
    rc = 1 if d["problems"] else 0
    if args.check:
        text = spec_path.read_text(encoding="utf-8")
        errs = check_markers(text, d["counts"])
        if args.draft:
            dt = Path(args.draft).read_text(encoding="utf-8")
            errs += [
                "closing keyword beside an issue number in the draft: " + h
                for h in closing_keywords(dt)
            ]
            if "/home/" in dt or PENPOT_HOST.search(dt):
                errs.append("local path or Penpot host in the draft")
        d["problems"] += errs
        rc = 1 if d["problems"] else 0
    if args.figures:
        figures: Any = _load(TOOLS / "e11_d07_figures.py", "e11_d07_figures")
        written = figures.render_all(Path(args.figures), d)
        d["figures"] = [str(p) for p in written]
    if args.json:
        slim = {k: v for k, v in d.items() if k not in ("keymap",)}
        slim["keymap"] = {k: v for k, v in d["keymap"].items() if k != "by_id"}
        print(json.dumps(slim, ensure_ascii=False, indent=1, default=str))
    else:
        print(render_report(d))
        if args.check:
            print(f"--check: {len(d['problems'])} problem(s)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
