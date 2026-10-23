"""E14-D03 drawing tool rail audit: every number the hi-fi spec and its boards quote, computed.

Standalone, offline, stdlib only (run with ``python3 -I``). Eight sections, each row labelled with
its source so a reviewer can re-grep it:

1. Registry parity: the spec's icon table (``docs/design/E14/E14-D03.md`` section 2) against the
   E14-D02 registry, read from E14-D02's own tool (``e14_d02_interaction_audit.py`` ``REG``; one
   source, never a third copy). Every rail row of the registry has its icon row, the six deferred
   rows appear only in the overflow sub-table, every ``IconName`` is unique, kebab-case and absent
   from ``packages/ui/src`` (the registry does not exist in code yet).
2. The rail model: E14-D02's formula (``rail_height`` / ``rail_fit``, imported) re-run for the
   compact rail (gated equal to E14-D02's heights) and for the comfortable 32 px rail (new numbers),
   the groups drawn at the 728 and 600 px pane stacks, and the icon-grid arithmetic from the
   primitive tokens (button, glyph, padding, badge, inset bar, separator block, focus ring).
3. The hotkey lint: E14-D02's ``lint_report`` reproduced (SCR-037's own set, scheme (a) gated at 0,
   scheme (b) reported) plus the E11-D07 screen-reader fixture (``e11_d07_sr_reserved_keys.json``,
   PR 4228, a contract in flight: passed with ``--sr-fixture`` or found beside this tool once it
   merges) for the six interim chords and SCR-037's colliding set; the spec's stamp rule.
4. The measured matrix: every fg / bg pair the rail and its menus render x dark / light /
   high-contrast, resolved as ``verify_tokens.py`` does and measured with
   ``contrast_check.contrast_ratio()`` (imported, never re-implemented); the bar per role; the
   reproductions of E14-D02 section 15 (gated equal), E30-D02 line 361 and E09-D09 section 11.
5. The CVD rows: ``cvd_simulate.simulate`` / ``delta_e76`` under protanopia, deuteranopia and
   tritanopia for the rail's fills and inks (JND floor 5.0, reported, never gated: shape and text
   carry every state), the greyscale luminance strip, and the spec's shape sentence (gated).
6. Token bindings: every token the spec binds in sections 3, 4 and 9 exists in the merged dark set
   (or is marked PROPOSED on its row); ``color.text.disabled`` / ``opacity.disabled`` never in a T2
   row; ``color.icon.`` only in a G-row.
7. String gates on the committed files (the T2 rule once, "T2" in every gated row, the view-as leg
   first, no "same as dark", no SET-ME / TODO / TBD, no trading word on the rail, no local path,
   no Penpot host (a generic pattern; no host named), no pageLink, no closing keyword with an
   issue number, every planned board PENDING, the interim stamp, two handoff blocks).
8. The counts the boards and the PR draft quote (``--json`` feeds the local check-nums).

Usage: python3 -I docs/design/_tools/e14_d03_rail_audit.py [--json] [--check] [--sr-fixture PATH]
A plain run prints every section and exits 0; ``--check`` exits 1 on any gated FAIL. UTF-8 stdout.
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
TOKENS = ROOT / "packages" / "ui" / "tokens"
SPEC = ROOT / "docs" / "design" / "E14" / "E14-D03.md"
HANDOFF = ROOT / "docs" / "design" / "E14" / "E14-D03-handoff.md"
D02_SPEC = ROOT / "docs" / "design" / "E14" / "E14-D02.md"
SR_FIXTURE = TOOLS / "e11_d07_sr_reserved_keys.json"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(TOOLS / "contrast_check.py", "contrast_check")
keymap_lint = _load(ROOT / "scripts" / "keymap_lint.py", "keymap_lint")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")
d02 = _load(TOOLS / "e14_d02_interaction_audit.py", "e14_d02_interaction_audit")

THEMES = ("dark", "light", "high-contrast")
RAIL_GROUPS: tuple[str, ...] = tuple(d02.RAIL_GROUPS)
PANE_STACKS = (728, 600)

# --- 1. the icon set (spec section 2), one row per glyph: registry id | IconName (PROPOSED unless
# noted) | rail group | tooltip label = accessible name | Kbd hint (interim, OQ-1a) or how it arms |
# the glyph in grid words (16 px canvas, 1.5 px stroke).
ICON_TXT = """
cursor|cursor|cursor|Cursor|Esc ladder
crosshair|crosshair|cursor|Crosshair|rail
select_area|select-area|cursor|Select area|rail / palette
trendline|trendline|lines|Trendline|Alt+L
ray|ray|lines|Ray|rail / palette
extended_line|extended-line|lines|Extended line|rail / palette
horizontal_line|horizontal-line|lines|Horizontal line|Alt+H
vertical_line|vertical-line|lines|Vertical line|rail / palette
rectangle|rectangle|shapes|Rectangle|Alt+R
ellipse|ellipse|shapes|Ellipse|rail / palette
triangle|triangle|shapes|Triangle|rail / palette
parallel_channel|parallel-channel|shapes|Parallel channel|rail / palette
fib_retracement|fib-retracement|fibonacci|Fib retracement|Alt+O
fib_extension|fib-extension|fibonacci|Fib extension|rail / palette
fib_timezone|fib-timezone|fibonacci|Fib time zones|rail / palette
anchored_vwap|anchored-vwap|analysis|Anchored VWAP|rail / palette
measure|measure|analysis|Measure|Alt+D
long_position|long-position|analysis|Long position|rail / palette
short_position|short-position|analysis|Short position|rail / palette
text|text-note|annotation|Text note|rail / palette
callout|callout|annotation|Callout|rail / palette
arrow|arrow|annotation|Arrow|rail / palette
polyline|polyline|annotation|Polyline|rail / palette
magnet|magnet-off|controls|Magnet: off|Ctrl+M
magnet|magnet-weak|controls|Magnet: weak|Ctrl+M
magnet|magnet-strong|controls|Magnet: strong|Ctrl+M
keep_active|pin|controls|Keep tool active|rail
lock_all|lock-open|controls|Lock all drawings|rail
lock_all|lock|controls|Lock all drawings|rail
hide_all|eye|controls|Hide all drawings|rail
hide_all|eye-off|controls|Hide all drawings|rail
delete_all|trash|controls (apart)|Delete all drawings…|rail
overflow|more-horizontal|menus|More tools|rail
draw|pencil|menus|Draw|rail
armed_item|check|menus|armed|rail
"""
# the glyph in grid words (16 px canvas, 1.5 px stroke): IconName | description
GLYPH_TXT = """
cursor|a slanted arrow pointer, apex top-left, with a short tail
crosshair|two centred perpendicular lines with a 4 px gap at the centre
select-area|a square drawn as four corner brackets with a small solid pointer at its bottom-right
trendline|one diagonal from bottom-left to top-right with a 3 px dot at each end
ray|a diagonal from a bottom-left dot to the top-right edge, no end dot
extended-line|one diagonal crossing the canvas edge to edge, no dots
horizontal-line|one horizontal rule edge to edge with a centre dot
vertical-line|one vertical rule edge to edge with a centre dot
rectangle|an outlined 12 x 8 rectangle, centred
ellipse|an outlined 12 x 8 ellipse, centred
triangle|an outlined triangle, apex up, on a 12 px base
parallel-channel|two parallel diagonals 5 px apart, the upper one dotted at both ends
fib-retracement|four horizontal rules of shrinking spacing between two end dots
fib-extension|three horizontal rules with an open arrowhead leaving the top rule
fib-timezone|four vertical rules of growing spacing on a baseline
anchored-vwap|an anchor dot bottom-left with a rising curve and one band rule above it
measure|a vertical double-headed arrow between two short horizontal end caps
long-position|a tall filled block above the entry rule, a short filled block below it, an up arrow
short-position|a short filled block above the entry rule, a tall filled block below it, a down arrow
text-note|a serif T: a horizontal bar with a vertical stem and two serifs
callout|a speech-bubble rectangle with a tail at its bottom-left
arrow|a diagonal shaft with an open arrowhead at the top-right
polyline|a zig-zag of three segments with a dot at each vertex
magnet-off|a U magnet with a 45 degree strike through it
magnet-weak|an outline U magnet with two pole caps
magnet-strong|the outline U magnet with filled pole caps
pin|a pushpin: a round head, a collar and a needle
lock-open|a padlock body with the shackle open to the right
lock|a padlock body with the shackle closed (reused: E09-D09 section 8, the T2 badge)
eye|an almond-shaped eye with a pupil dot
eye-off|the eye with a 45 degree strike through it
trash|a bin: a lid rule, a body outline and two inner vertical rules
more-horizontal|three 2 px dots in a row
pencil|a slanted pencil with a separate tip
check|a check mark of two strokes
"""
GLYPHS = dict(ln.split("|", 1) for ln in GLYPH_TXT.strip().splitlines())
ICONS = [[*ln.split("|"), GLYPHS[ln.split("|")[1]]] for ln in ICON_TXT.strip().splitlines()]

# the control names the registry rows must carry, grep-checked against E14-D02's Table 3 text
D02_TABLE3_CONTROLS: tuple[str, ...] = ("Magnet: weak", "Keep tool active", "Lock all drawings")
D02_TABLE3_CONTROLS += ("Hide all drawings", "Delete all drawings…", "More tools")
CONTROL_GLYPHS = {"magnet": 3, "keep_active": 1, "lock_all": 2, "hide_all": 2, "delete_all": 1}
SECTION_HEADINGS = (
    "Lines",
    "Shapes",
    "Fibonacci",
    "Analysis",
    "Annotation",
    "Deferred",
    "Controls",
)

# --- 3. the chords (E14-D02 section 2.2 / Q2 scheme (a); the ticket's colliding set as the C-row)
SCHEME_A = ("Alt+L", "Alt+H", "Alt+O", "Alt+R", "Alt+D", "Ctrl+M")
COLLIDING = ("Alt+T", "Alt+H", "Alt+F", "Alt+R", "Alt+M")
SR_LIVE_MODES = {"browse", "table", "global", "quick-nav", "interact", "focus"}

# --- 4. the matrix (spec section 9): fg | bg | role | what the pair is on the rail
TEXT, UI, STRUCT = "text", "ui", "structure"
PAIR_TXT = """
color.text.primary|color.surface.raised|ui|enabled glyph on the column; chip text; Kbd text
color.text.primary|color.surface.hover|ui|glyph on the hover fill
color.text.primary|color.surface.selected|ui|glyph on the pressed fill (tool-active, toggles on)
color.text.primary|color.action.selected|ui|glyph on the alternative pressed fill (reported)
color.border.selected|color.surface.selected|ui|the 2 px inset bar on the pressed fill
color.border.selected|color.surface.raised|ui|the inset bar against the column
color.border.selected|color.action.selected|ui|the inset bar on the alternative fill (reported)
color.focus.ring|color.surface.raised|ui|focus ring on the column
color.focus.ring|color.surface.hover|ui|focus ring on a hovered button
color.focus.ring|color.surface.selected|ui|focus ring on the pressed button
color.focus.ring|color.surface.canvas|ui|focus ring overflowing onto the pane (chart background)
color.focus.ring|color.surface.sunken|ui|focus ring on the toolbar fill (collapsed Draw button)
color.text.tertiary|color.surface.raised|ui|T2 glyph and lock badge on the rail (E09-D09 section 11)
color.text.tertiary|color.surface.overlay|text|T2 menu item label (overflow and Draw menus)
color.text.secondary|color.surface.overlay|text|T2 reason: echo, menu second line, deferred tag
color.text.primary|color.surface.overlay|text|menu item label; tooltip label
color.status.danger.default|color.surface.raised|ui|the delete-all glyph (the rail's only hue ink)
color.status.danger.default|color.surface.overlay|ui|the delete-all glyph as a danger menu item
color.text.primary|color.surface.sunken|ui|the Draw button glyph on the toolbar fill
color.text.primary|color.surface.canvas|ui|glyph reference over the pane (never painted there)
color.text.tertiary|color.surface.canvas|ui|T2 glyph reference over the pane
color.border.default|color.surface.raised|structure|the separator rule (grouping only, no meaning)
color.border.strong|color.surface.raised|structure|the armed-tool chip outline (text carries)
color.border.default|color.surface.overlay|structure|menu section rules
color.surface.selected|color.surface.raised|structure|pressed fill vs column (bar + chip carry)
color.surface.hover|color.surface.raised|structure|hover fill vs column (reinforcement)
color.surface.raised|color.surface.canvas|structure|the rail column against the pane
color.drawing.default|color.surface.canvas|ui|CMP-191 default stroke (E14-D08's; for the record)
color.drawing.selected|color.surface.canvas|ui|CMP-191 selected stroke (E14-D08's; for the record)
"""
PAIRS = [ln.split("|") for ln in PAIR_TXT.strip().splitlines()]
BAR = {TEXT: 4.5, UI: 3.0}
RAIL_TOKENS = sorted({p[0] for p in PAIRS} | {p[1] for p in PAIRS})

# --- 5. the CVD rows: ink or fill pairs whose difference a deficiency could collapse
CVD_TXT = """
color.surface.selected|color.surface.hover|pressed fill vs hover fill
color.surface.selected|color.surface.raised|pressed fill vs the column
color.surface.hover|color.surface.raised|hover fill vs the column
color.border.selected|color.surface.selected|inset bar vs the pressed fill
color.border.selected|color.surface.raised|inset bar vs the column
color.status.danger.default|color.text.primary|delete-all glyph vs the other glyphs
color.text.tertiary|color.text.primary|T2 glyph vs an enabled glyph
color.focus.ring|color.border.selected|focus ring vs the inset bar
color.drawing.default|color.drawing.selected|CMP-191 default vs selected (E14-D08's; record)
"""
CVD_ROWS = [ln.split("|") for ln in CVD_TXT.strip().splitlines()]
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
JND = float(cvd.JND_FLOOR)
SHAPE_SENTENCE = (
    "The three magnet modes, the lock and hide states and the armed state are carried by shape and "
    "text, never by hue alone."
)
T2_SENTENCE = (
    "Every role-, grant-, environment-, session- or state-gated control on the rail is E09-D09's T2"
)
VIEW_AS = "Read-only while viewing as {user}."
PERMISSION_WS = "Your role can't save workspaces."
PERMISSION_SET = "Your role can't change settings."
STAMP = "interim (OQ-1a)"
TOKEN_RE = re.compile(
    r"`((?:color|space|size|radius|border|type|elevation|opacity|font)\.[a-z0-9.\-]+)`"
)
LOCAL_PATH_RE = re.compile(r"/(?:home|Users)/[^/\s]+/")
PENPOT_HOST_RE = re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE)
CLOSING_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[^\n]{0,40}#\d+", re.IGNORECASE
)


def section(text: str, start: str, end: str | None) -> str:
    """The spec between two ``## N.`` headings (``end`` None = to the end)."""
    a = text.find(start)
    if a < 0:
        return ""
    b = text.find(end, a + 1) if end else -1
    return text[a:] if b < 0 else text[a:b]


def table_rows(block: str) -> list[list[str]]:
    rows = []
    for ln in block.splitlines():
        if ln.startswith("| ") and not ln.startswith("| ---"):
            rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return rows


def chord_of(cell: str) -> str | None:
    m = re.search(r"Alt\+[A-Z]\b|Ctrl\+M\b", cell)
    return m.group(0) if m else None


# --- 1. registry parity ------------------------------------------------------------------------
def icon_report(fails: list[str], spec: str) -> dict[str, Any]:
    reg: list[list[str]] = list(d02.REG)
    rail_ids = [r[0] for r in reg if r[4] not in ("overflow",)]
    deferred_ids = [r[0] for r in reg if r[4] == "overflow"]
    tool_ids = [r[0] for r in reg if r[4] in RAIL_GROUPS]
    icon_ids = [r[0] for r in ICONS]
    for tid in tool_ids:
        n = icon_ids.count(tid)
        if n != 1:
            fails.append(f"icon rows for {tid}: {n} (one per tool)")
    for cid, want in CONTROL_GLYPHS.items():
        if icon_ids.count(cid) != want:
            fails.append(f"icon rows for {cid}: {icon_ids.count(cid)} (want {want})")
    for r in ICONS:
        if r[0] in tool_ids:
            reg_row = next(x for x in reg if x[0] == r[0])
            if reg_row[4] != r[2]:
                fails.append(f"{r[0]}: icon group {r[2]} vs registry {reg_row[4]}")
            if reg_row[5] != r[4]:
                fails.append(f"{r[0]}: icon key {r[4]} vs registry {reg_row[5]}")
    for did in deferred_ids:
        if did in icon_ids:
            fails.append(f"deferred {did} has a glyph row (menu text only)")
    names = [r[1] for r in ICONS]
    dupes = sorted({n for n in names if names.count(n) > 1})
    fails += [f"IconName not unique: {n}" for n in dupes]
    fails += [
        f"IconName not kebab-case: {n}" for n in names if not re.fullmatch(r"[a-z]+(-[a-z]+)*", n)
    ]
    ui_src = ROOT / "packages" / "ui" / "src"
    in_code = 0
    for p in ui_src.rglob("*.ts*"):
        txt = p.read_text(encoding="utf-8", errors="ignore")
        in_code += sum(1 for n in names if f'"{n}"' in txt) + ("IconName" in txt)
    d02_text = D02_SPEC.read_text(encoding="utf-8") if D02_SPEC.exists() else ""
    fails += [
        f"E14-D02 Table 3 lacks the control name {n}"
        for n in D02_TABLE3_CONTROLS
        if n not in d02_text
    ]
    for r in ICONS:
        if r[0] in tool_ids:
            reg_row = next(x for x in reg if x[0] == r[0])
            alts = {r[0].replace("_", " ")} | {a.strip().lower() for a in reg_row[1].split("/")}
            alts |= {"fib " + x for x in alts}  # the Fibonacci family shares one SCR-037 name
            if r[3].lower() not in alts and reg_row[1] != "-":
                fails.append(f"{r[0]}: label {r[3]!r} is neither the id nor the SCR-037 name")
    bad_words = [r[3] for r in ICONS if re.search(r"\b(Buy|Sell|Place|Order)\b", r[3])]
    fails += [f"trading word on a rail label: {w}" for w in bad_words]
    out: dict[str, Any] = {
        "registry_rows": len(reg),
        "rail_ids": len(rail_ids),
        "tool_ids": len(tool_ids),
    }
    out |= {"deferred": len(deferred_ids), "glyphs": len(ICONS), "icon_names": len(set(names))}
    out |= {"controls": len([i for i in rail_ids if i not in tool_ids]), "in_code": in_code}
    out["proposed_names"] = len([r for r in ICONS if "reused" not in r[5]])
    out["section_headings"] = len(SECTION_HEADINGS)
    # the spec's section 2 table against this literal
    rows = table_rows(section(spec, "### 2.1", "### 2.2"))
    spec_rows = [r for r in rows if r and r[0] in icon_ids]
    out["spec_icon_rows"] = len(spec_rows)
    if spec:
        if len(spec_rows) != len(ICONS):
            fails.append(f"spec section 2.1 icon rows {len(spec_rows)} vs the tool's {len(ICONS)}")
        for r in spec_rows:
            icon = r[1].strip("`")
            lit = next((x for x in ICONS if x[1] == icon), None)
            if lit is None:
                fails.append(f"spec icon row {icon} has no literal")
                continue
            if r[0] != lit[0] or r[2] != lit[2] or r[3] != lit[3]:
                fails.append(f"spec icon row {icon}: id / group / label differ from the literal")
            key = chord_of(r[4]) or lit[4]
            if key != lit[4] and lit[4] not in r[4]:
                fails.append(f"spec icon row {icon}: key {r[4]!r} vs {lit[4]!r}")
        drows = [
            r for r in table_rows(section(spec, "### 2.2", "### 2.3")) if r and r[0] in deferred_ids
        ]
        if len(drows) != len(deferred_ids):
            fails.append(f"spec section 2.2 deferred rows {len(drows)} vs {len(deferred_ids)}")
        for h in SECTION_HEADINGS:
            if f'"{h}"' not in spec:
                fails.append(f"menu section heading {h!r} not in the spec")
    else:
        fails.append("spec absent: section 2 parity not checked")
    return out


# --- 2. the rail model and the icon grid -------------------------------------------------------
def prim(name: str) -> int | float:
    allt = dict(verify.load(verify.PRIMITIVES))
    v = verify.resolve(allt[name]["$value"], allt)
    return float(v) if isinstance(v, float) and not float(v).is_integer() else int(float(v))


def fit(pane_h: int, s: int) -> int:
    groups = len(RAIL_GROUPS)
    while groups > 1 and d02.rail_height(groups, s) > pane_h:
        groups -= 1
    return groups


def rail_report(fails: list[str]) -> dict[str, Any]:
    compact = [int(d02.rail_height(g, 24)) for g in (6, 5, 4)]
    comfortable = [int(d02.rail_height(g, 32)) for g in (6, 5, 4)]
    if compact != list(d02.GEOM["rail_heights"]):
        fails.append(f"rail heights {compact} differ from E14-D02's {d02.GEOM['rail_heights']}")
    btn_c, btn_f, glyph = (
        int(prim("size.control.compact")),
        int(prim("size.control.comfortable")),
        int(prim("size.icon.md")),
    )
    bar, ring, hair = (
        int(prim("border.thick")),
        int(prim("border.focus")),
        int(prim("border.hairline")),
    )
    grid: dict[str, Any] = {"button_compact": btn_c, "button_comfortable": btn_f, "glyph": glyph}
    grid |= {
        "stroke": 1.5,
        "pad_compact": (btn_c - glyph) // 2,
        "pad_comfortable": (btn_f - glyph) // 2,
    }
    grid |= {
        "badge": glyph // 2,
        "halo": hair,
        "bar": bar,
        "separator": (2, hair, 3),
        "separator_block": 2 + hair + 3,
    }
    grid |= {"ring_width": ring, "ring_offset": 2, "ring_box_compact": btn_c + 2 * (ring + 2)}
    grid["ring_overflow_compact"] = (grid["ring_box_compact"] - btn_c) // 2
    grid |= {"ring_box_comfortable": btn_f + 2 * (ring + 2), "pad_column": int(prim("space.1"))}
    grid |= {"radius_fill": int(prim("radius.sm")), "radius_kbd": int(prim("radius.xs"))}
    grid |= {
        "zoom_125_button": round(btn_c * 1.25),
        "zoom_200_button": btn_c * 2,
        "zoom_200_glyph": glyph * 2,
    }
    grid |= {
        "chip_compact": 20,
        "chip_comfortable": 24,
        "delete_gap": int(d02.RAIL_PX["delete_gap"]),
    }
    grid |= {
        "target_min": int(prim("size.target.min")),
        "icon_sizes": [int(prim(f"size.icon.{s}")) for s in ("sm", "md", "lg")],
    }
    if grid["target_min"] != btn_c:
        fails.append("the compact button is not exactly the target floor")
    tools_per_group = [sum(1 for r in d02.REG if r[4] == g) for g in RAIL_GROUPS]
    out: dict[str, Any] = {
        "compact": compact,
        "comfortable": comfortable,
        "tools_per_group": tools_per_group,
    }
    out |= {
        "groups_drawn_compact": [fit(h, 24) for h in PANE_STACKS],
        "groups_drawn_comfortable": [fit(h, 32) for h in PANE_STACKS],
    }
    out |= {
        "pane_stacks": list(PANE_STACKS),
        "grid": grid,
        "collapse_order": list(reversed(RAIL_GROUPS[3:])),
    }
    out["drawn_height_compact"] = [int(d02.rail_height(fit(h, 24), 24)) for h in PANE_STACKS]
    out["drawn_height_comfortable"] = [int(d02.rail_height(fit(h, 32), 32)) for h in PANE_STACKS]
    return out


# --- 3. the hotkey lint ------------------------------------------------------------------------
def sr_lint(fixture: Path | None) -> dict[str, Any]:
    if fixture is None or not fixture.exists():
        return {
            "fixture": None,
            "note": "fixture absent at this head (PR 4228 in flight): pass --sr-fixture",
        }
    data = json.loads(fixture.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = list(data["keys"])
    classes: list[dict[str, Any]] = list(data["classes"])
    by_norm: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_norm.setdefault(str(r["norm"]), []).append(r)
    examples: dict[str, set[str]] = {}
    for c in classes:
        for ex in c.get("examples", []):
            try:
                examples.setdefault(str(c["class"]), set()).add(str(keymap_lint.normalise(str(ex))))
            except (keymap_lint.KeymapError, ValueError):  # outside the repo's key vocabulary
                examples.setdefault(str(c["class"]), set()).add(str(ex))
    out: dict[str, Any] = {
        "fixture": fixture.name,
        "rows": len(rows),
        "classes": len(classes),
        "chords": {},
    }
    for chord in dict.fromkeys(SCHEME_A + COLLIDING):
        norm = str(keymap_lint.normalise(chord))
        live = [r for r in by_norm.get(norm, []) if r["mode"] in SR_LIVE_MODES]
        hits = [f"{r['sr']} {r['mode']}: {r['keys']} = {r['function']}" for r in live]
        cls: list[str] = []
        if re.search(r"\b(NVDA|INSERT|VO|SRKEY|CapsLock)\+", chord, re.IGNORECASE):
            cls.append("sr-modifier")
        if re.fullmatch(r"(Shift\+)?[A-Z0-9]", norm):
            cls.append("browse-single-letter")
        if norm.startswith("Ctrl+Alt+") and re.search(r"(←|→|↑|↓|Home|End|PageUp|PageDown)$", norm):
            cls.append("table-nav")
        cls += [k for k, v in examples.items() if norm in v and k not in cls]
        out["chords"][chord] = {"norm": norm, "rows": hits, "classes": cls}
    out["scheme_a_hits"] = sum(
        len(out["chords"][c]["rows"]) + len(out["chords"][c]["classes"]) for c in SCHEME_A
    )
    out["colliding_hits"] = sum(
        len(out["chords"][c]["rows"]) + len(out["chords"][c]["classes"]) for c in COLLIDING
    )
    return out


def lint_report(fails: list[str], spec: str, fixture: Path | None) -> dict[str, Any]:
    out: dict[str, Any] = dict(d02.lint_report(fails))
    out["sr"] = sr_lint(fixture)
    if out["sr"].get("fixture") and out["sr"]["scheme_a_hits"]:
        fails.append(f"screen-reader fixture hits for scheme (a): {out['sr']['scheme_a_hits']}")
    stamp_misses: list[str] = []
    stray: list[str] = []
    if spec:
        parts = re.split(r"(?m)^## ", spec)
        for part in parts[1:]:
            head = part.split("\n", 1)[0][:12]
            for chord in SCHEME_A:
                idx = [m.start() for m in re.finditer(re.escape(chord), part)]
                if idx and not any("interim" in part[max(0, i - 120) : i + 120] for i in idx):
                    stamp_misses.append(
                        f"{chord} in section {head!r} without the interim stamp nearby"
                    )
        for ln in spec.splitlines():
            if re.search(r"Alt\+[TFM]\b", ln) and not re.search(
                r"lint|collid|supersed|\| C|C-row|Q7", ln
            ):
                stray.append(ln[:80])
        if STAMP not in spec:
            stamp_misses.append("the stamp 'interim (OQ-1a)' is absent")
    fails += stamp_misses + [f"colliding chord outside a C-row / lint line: {s}" for s in stray]
    out |= {"stamp_misses": stamp_misses, "stray_colliding": stray}
    return out


# --- 4. the measured matrix --------------------------------------------------------------------
def themes() -> dict[str, dict[str, str]]:
    return {t: dict(d02.resolve_theme(t)) for t in THEMES}


def ratio(th: dict[str, str], fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(d02.hex_rgb(th[fg]), d02.hex_rgb(th[bg])))


def matrix_report(fails: list[str]) -> dict[str, Any]:
    th = themes()
    pairs: list[dict[str, Any]] = []
    for fg, bg, role, use in PAIRS:
        ratios = {t: ratio(th[t], fg, bg) for t in THEMES}
        bar = BAR.get(role)
        failing = [t for t in THEMES if bar is not None and ratios[t] < bar]
        verdict = (
            "n/a (structure)"
            if bar is None
            else ("FAIL " + ", ".join(failing) if failing else "PASS")
        )
        if failing and "reported" not in use and "record" not in use:
            fails.append(f"contrast {fg} on {bg} ({role}) under {bar}: {failing}")
        pairs.append(
            {
                "fg": fg,
                "bg": bg,
                "role": role,
                "use": use,
                "bar": bar,
                "ratios": ratios,
                "verdict": verdict,
            }
        )
    hc_keys = set(verify.merged_set(["semantic-hc.tokens.json"]).keys())
    no_hc = [t for t in RAIL_TOKENS if t not in hc_keys]
    # reproductions: E14-D02 section 15 (gated equal to its tool), E30-D02 361, E09-D09 section 11
    d02_pairs = d02.contrast_report([])["pairs"]
    repro: list[dict[str, Any]] = []
    for p in d02_pairs:
        mine = {t: ratio(th[t], p["fg"], p["bg"]) for t in THEMES}
        if any(abs(mine[t] - p["ratios"][t]) > 1e-9 for t in THEMES):
            fails.append(f"E14-D02 section 15 pair {p['fg']} on {p['bg']} not reproduced")
        repro.append({"fg": p["fg"], "bg": p["bg"], "ratios": mine})
    focus = {
        bg: {t: ratio(th[t], "color.focus.ring", bg) for t in THEMES}
        for bg in ("color.surface.canvas", "color.surface.raised")
    }
    t2 = {t: ratio(th[t], "color.text.tertiary", "color.surface.raised") for t in THEMES}
    reason = {t: ratio(th[t], "color.text.secondary", "color.surface.overlay") for t in THEMES}
    gated = [p for p in pairs if p["bar"] is not None]
    failing_n = {t: len([p for p in gated if p["ratios"][t] < p["bar"]]) for t in THEMES}
    # the pressed-fill choice: text.primary and the bar on surface.selected vs on action.selected
    choice = {
        k: {t: ratio(th[t], fg, bg) for t in THEMES}
        for k, (fg, bg) in {
            "glyph_on_selected": ("color.text.primary", "color.surface.selected"),
            "bar_on_selected": ("color.border.selected", "color.surface.selected"),
            "glyph_on_action": ("color.text.primary", "color.action.selected"),
            "bar_on_action": ("color.border.selected", "color.action.selected"),
        }.items()
    }
    tokens = {t: {k: th[t][k] for k in RAIL_TOKENS} for t in THEMES}
    out: dict[str, Any] = {
        "pairs": pairs,
        "rows": len(pairs),
        "gated": len(gated),
        "failing": failing_n,
    }
    out |= {"structure_rows": len(pairs) - len(gated), "no_hc_override": no_hc, "tokens": tokens}
    out |= {
        "d02_repro": repro,
        "focus_ring": focus,
        "t2_label": t2,
        "t2_reason_overlay": reason,
        "pressed_choice": choice,
    }
    out["darkest_chart_bg"] = {
        "token": "color.surface.canvas",
        "theme": "dark",
        "hex": th["dark"]["color.surface.canvas"],
    }
    out["lightest_chart_bg"] = {
        "token": "color.surface.canvas",
        "theme": "light",
        "hex": th["light"]["color.surface.canvas"],
    }
    return out


# --- 5. the CVD rows ---------------------------------------------------------------------------
def cvd_report(fails: list[str], spec: str) -> dict[str, Any]:
    th = themes()
    rows: list[dict[str, Any]] = []
    for a, b, what in CVD_ROWS:
        per: dict[str, dict[str, float]] = {}
        for t in THEMES:
            d: dict[str, float] = {"normal": float(cvd.delta_e76(th[t][a], th[t][b]))}
            for dfc in DEFICIENCIES:
                d[dfc] = float(
                    cvd.delta_e76(cvd.simulate(th[t][a], dfc), cvd.simulate(th[t][b], dfc))
                )
            per[t] = d
        under = [f"{t}/{k}" for t in THEMES for k, v in per[t].items() if v < JND]
        rows.append({"a": a, "b": b, "what": what, "delta_e": per, "under_jnd": under})
    fills: tuple[str, ...] = (
        "color.surface.raised",
        "color.surface.hover",
        "color.surface.selected",
        "color.action.selected",
    )
    fills += ("color.surface.overlay", "color.surface.canvas", "color.surface.sunken")
    luma = {
        t: {f: round(float(cvd.relative_luminance(th[t][f])), 4) for f in fills} for t in THEMES
    }
    if spec and SHAPE_SENTENCE not in spec:
        fails.append("the spec lacks the shape sentence")
    return {
        "rows": rows,
        "n": len(rows),
        "jnd": JND,
        "luma": luma,
        "deficiencies": list(DEFICIENCIES),
    }


# --- 6. token bindings -------------------------------------------------------------------------
def token_report(fails: list[str], spec: str) -> dict[str, Any]:
    allt = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES["dark"]))
    known = set(allt.keys())
    bound: set[str] = set()
    missing: list[str] = []
    proposed: list[str] = []
    bad_t2: list[str] = []
    bad_icon: list[str] = []
    for start, end in (("## 3.", "## 4."), ("## 4.", "## 5."), ("## 9.", "## 10.")):
        for ln in section(spec, start, end).splitlines():
            for tok in TOKEN_RE.findall(ln):
                bound.add(tok)
                if tok not in known:
                    (proposed if "PROPOSED" in ln else missing).append(tok)
            t2_row = start == "## 4." and ln.startswith("| ") and "T2" in ln
            if t2_row and ("color.text.disabled" in ln or "opacity.disabled" in ln):
                bad_t2.append(ln[:60])
    for ln in spec.splitlines():
        if "color.icon." in ln and not re.search(r"\| G\d|G-row", ln):
            bad_icon.append(ln[:60])
    fails += [f"token bound but unknown: {t}" for t in sorted(set(missing))]
    fails += [f"T2 row with a dimming token: {s}" for s in bad_t2]
    fails += [f"color.icon.* outside a G-row: {s}" for s in bad_icon]
    out: dict[str, Any] = {
        "bound": len(bound),
        "known": len(known),
        "missing": sorted(set(missing)),
    }
    return out | {
        "proposed": sorted(set(proposed)),
        "bad_t2_rows": bad_t2,
        "bad_icon_lines": bad_icon,
    }


# --- 7. string gates ---------------------------------------------------------------------------
def string_report(fails: list[str], spec: str, handoff: str) -> dict[str, Any]:
    gates: dict[str, bool] = {}
    both = spec + "\n" + handoff
    gates["t2_rule_once"] = spec.count(T2_SENTENCE) == 1
    s4 = section(spec, "## 4.", "## 5.")
    gated_rows = [
        r for r in s4.splitlines() if r.startswith("| ") and re.search(r"Viewer|view-as", r)
    ]
    gates["t2_in_gated_rows"] = bool(gated_rows) and all("T2" in r for r in gated_rows)
    gates["view_as_first"] = (
        0 <= spec.find(VIEW_AS) < spec.find(PERMISSION_WS) and PERMISSION_SET in spec
    )
    gates["no_same_as_dark"] = "same as dark" not in both.lower()
    gates["no_placeholders"] = not re.search(r"SET-ME|TODO|TBD", both)
    gates["no_local_path"] = not LOCAL_PATH_RE.search(both)
    gates["no_penpot_host"] = not PENPOT_HOST_RE.search(both)
    gates["no_pagelink"] = "pageLink" not in both
    gates["no_closing_keyword"] = not CLOSING_RE.search(both)
    board_rows = [
        r for r in section(spec, "## 0.", "## 1.").splitlines() if re.match(r"^\| 0\d", r)
    ]
    gates["boards_pending"] = bool(board_rows) and all(
        re.search(r"PENDING\s*\|\s*$", r) for r in board_rows
    )
    gates["stamp_present"] = STAMP in spec
    gates["handoff_two_blocks"] = handoff.count("## Handoff checklist — ") == 2
    blank = [
        ln
        for ln in handoff.splitlines()
        if re.fullmatch(r"- \[ \]\s*(\*\*[^*]+\*\*\s*—?\s*)?", ln.strip())
    ]
    gates["handoff_no_blank_line"] = not blank
    gates["shape_sentence"] = SHAPE_SENTENCE in spec
    gates["validity_sentence"] = "no form-validity control" in spec
    fails += [f"string gate failed: {k}" for k, ok in gates.items() if not ok]
    counts = {
        "boards": len(board_rows),
        "handoff_lines": len(handoff.splitlines()),
        "spec_lines": len(spec.splitlines()),
    }
    for key, pat, start, end in (
        ("states", r"\| \d+ +\|", "## 4.", "## 5."),
        ("storybook", r"- `", "## 11.", "## 12."),
        ("a_rows", r"\| A\d+ ", "### 15.2", "### 15.3"),
        ("c_rows", r"\| C\d+ ", "### 15.3", "### 15.4"),
        ("g_rows", r"\| G\d+ ", "### 15.4", "### 15.5"),
        ("q_rows", r"\| Q\d+ ", "### 15.5", "### 15.6"),
        ("handoff_rows", r"\| [A-Z`]", "### 15.6", "### 15.7"),
    ):
        block = section(spec, start, end)
        n = len(re.findall(r"(?m)^" + pat, block))
        counts[key] = n - 1 if key == "handoff_rows" and n else n  # minus the header row
    return {"gates": gates, "counts": counts, "blank_checklist": blank}


# --- 8. counts and the CLI ---------------------------------------------------------------------
def fmt(v: float) -> str:
    return f"{v:.2f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E14-D03 drawing tool rail audit")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 on any gated FAIL")
    ap.add_argument("--sr-fixture", type=Path, default=SR_FIXTURE if SR_FIXTURE.exists() else None)
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8") if SPEC.exists() else ""
    handoff = HANDOFF.read_text(encoding="utf-8") if HANDOFF.exists() else ""
    fails: list[str] = []
    icons, rail = icon_report(fails, spec), rail_report(fails)
    lint, matrix = lint_report(fails, spec, a.sr_fixture), matrix_report(fails)
    cvdr, toks = cvd_report(fails, spec), token_report(fails, spec)
    strings = (
        string_report(fails, spec, handoff) if spec and handoff else {"gates": {}, "counts": {}}
    )
    if not (spec and handoff):
        fails.append("spec or handoff absent: string gates not checked")
    counts: dict[str, Any] = {"boards": 9, "light_twins": 3, "themes": len(THEMES)}
    counts |= {k: v for k, v in icons.items() if isinstance(v, int)}
    counts |= {"rail_compact": rail["compact"], "rail_comfortable": rail["comfortable"]}
    counts |= {
        "groups_drawn_compact": rail["groups_drawn_compact"],
        "groups_drawn_comfortable": rail["groups_drawn_comfortable"],
    }
    counts |= {f"lint_{k}": len(lint[k]) for k in ("scr037", "scr037_table", "a", "b")}
    counts |= {
        "sr_scheme_a_hits": lint["sr"].get("scheme_a_hits"),
        "sr_colliding_hits": lint["sr"].get("colliding_hits"),
    }
    counts |= {
        "matrix_rows": matrix["rows"],
        "matrix_gated": matrix["gated"],
        "matrix_failing": matrix["failing"],
    }
    counts |= {
        "matrix_structure": matrix["structure_rows"],
        "cvd_rows": cvdr["n"],
        "no_hc_override": len(matrix["no_hc_override"]),
    }
    counts |= {"tokens_bound": toks["bound"], "tokens_proposed": len(toks["proposed"])} | dict(
        strings["counts"]
    )
    if counts["light_twins"] * 3 > counts["boards"]:
        fails.append("light twins exceed one third of the boards (lever 4)")
    if a.json:
        out: dict[str, Any] = {
            "counts": counts,
            "icons": icons,
            "rail": rail,
            "lint": lint,
            "matrix": matrix,
            "cvd": cvdr,
        }
        out |= {"tokens": toks, "strings": strings, "grid": rail["grid"], "fails": fails}
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 1 if (a.check and fails) else 0
    print("## 1. Registry parity (E14-D02 REG via its tool; spec section 2)\n")
    print(json.dumps({k: v for k, v in icons.items()}, ensure_ascii=False))
    print("\n| id | IconName | group | label = name | key | glyph |\n|---|---|---|---|---|---|")
    for r in ICONS:
        print("| " + " | ".join(r) + " |")
    print("\n## 2. Rail model (E14-D02 rail_height / rail_fit; px)\n")
    print(json.dumps({k: v for k, v in rail.items()}, ensure_ascii=False))
    print("\n## 3. Hotkey lint (keymap_lint.lint_keymap; E11-D07 fixture)\n")
    for key, label in {
        "base": "shipped keymap",
        "scr037": "SCR-037 set",
        "scr037_table": "SCR-037 + table",
        "a": "scheme (a) + snap-cycle + table",
        "b": "scheme (b) + table",
    }.items():
        print(f"- {label}: {len(lint[key])} error(s)")
        for e in lint[key]:
            print(f"    - {e}")
    print(f"- Backspace as a binding: {lint['backspace']}")
    print("- screen-reader fixture: " + json.dumps(lint["sr"], ensure_ascii=False))
    print(f"- stamp misses: {lint['stamp_misses']}")
    print(f"- stray colliding chords: {lint['stray_colliding']}")
    print("\n## 4. Measured matrix (contrast_check.contrast_ratio; bar text 4.5 / ui 3.0)\n")
    print(
        "| fg | bg | role | dark | light | hc | verdict | use |\n|---|---|---|---|---|---|---|---|"
    )
    for p in matrix["pairs"]:
        cells = " | ".join(fmt(p["ratios"][t]) for t in THEMES)
        print(
            f"| `{p['fg']}` | `{p['bg']}` | {p['role']} | {cells} | {p['verdict']} | {p['use']} |"
        )
    print(f"\nrows {matrix['rows']} · gated {matrix['gated']} · failing {matrix['failing']}")
    print(f"no hc override: {matrix['no_hc_override']}")
    print("\n| token | dark | light | hc |\n|---|---|---|---|")
    for k in RAIL_TOKENS:
        print(f"| `{k}` | " + " | ".join(matrix["tokens"][t][k] for t in THEMES) + " |")
    print(
        "\nE14-D02 section 15 reproduced (dark): "
        + "; ".join(
            f"{r['fg'].split('.')[-1]} on {r['bg'].split('.')[-1]} {fmt(r['ratios']['dark'])}"
            for r in matrix["d02_repro"]
        )
    )
    print(
        "focus ring (E30-D02 line 361): "
        + json.dumps(
            {k: {t: fmt(v) for t, v in d.items()} for k, d in matrix["focus_ring"].items()}
        )
    )
    print(
        "T2 label on raised (E09-D09 section 11): "
        + json.dumps({t: fmt(v) for t, v in matrix["t2_label"].items()})
    )
    print(
        "T2 reason on overlay: "
        + json.dumps({t: fmt(v) for t, v in matrix["t2_reason_overlay"].items()})
    )
    print(
        "pressed-fill choice: "
        + json.dumps(
            {k: {t: fmt(v) for t, v in d.items()} for k, d in matrix["pressed_choice"].items()}
        )
    )
    print(
        "chart backgrounds: "
        + json.dumps([matrix["darkest_chart_bg"], matrix["lightest_chart_bg"]])
    )
    print(f"\n## 5. CVD (cvd_simulate; delta E76; JND {JND})\n")
    for r in cvdr["rows"]:
        de = {t: {k: fmt(v) for k, v in d.items()} for t, d in r["delta_e"].items()}
        print(f"- {r['what']}: {json.dumps(de)} · under JND: {r['under_jnd'] or 'none'}")
    print("greyscale luminance: " + json.dumps(cvdr["luma"]))
    print("\n## 6. Token bindings\n")
    print(json.dumps(toks, ensure_ascii=False))
    print("\n## 7. String gates\n")
    print(json.dumps(strings.get("gates", {}), ensure_ascii=False))
    print("\n## 8. Counts\n")
    print(json.dumps(counts, ensure_ascii=False))
    print(f"\nFAIL count (gated): {len(fails)}")
    for f in fails:
        print(f"- {f}")
    return 1 if (a.check and fails) else 0


if __name__ == "__main__":
    raise SystemExit(main())
